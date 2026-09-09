"""Durable pre-request reservations for the user-authorized $1,000 experiment.

Uses Inspect's propagated LimitExceededError, not an ordinary hook exception
(Inspect logs and swallows ordinary hook exceptions). Text-only pilot requests
are bounded to 2 MB of serialized input/schema and 16,384 output tokens.
Unsettled/error requests retain their full reservation until manually reconciled.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import time
import uuid

from inspect_ai.hooks import Hooks, hooks
from inspect_ai.util import LimitExceededError

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / 'logs/gemini-realism-awareness/budget.json'
API_CAP = 900.0  # remaining $100 reserved for bounded sandbox/build charges
REQUEST_RESERVE = 25.0
MAX_BYTES = 2_000_000
MAX_OUTPUT = 16_384
# Conservative rates: long-context Pro; no cache discount assumed. USD / MTok.
RATES = {
    'google/gemini-3.1-pro-preview': (4.0, 18.0),
    'google/gemini-3.8-flash': (1.65, 7.5),
    'anthropic/claude-opus-4-8': (10.0, 25.0),
    # User authorized broader baseline-model search. Upper envelope includes
    # long-context/cache-write margin, above published Sonnet 4.5 rates.
    'anthropic/claude-sonnet-4-5-20250929': (12.0, 30.0),
}


def stop(message):
    raise LimitExceededError('cost', value=API_CAP, limit=API_CAP, message=message)


@contextmanager
def transaction(path=LEDGER):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {
            'authorized_total_usd': 1000, 'api_cap_usd': API_CAP,
            'infrastructure_reserve_usd': 100, 'requests': [], 'infrastructure': [],
        }
        yield data
        temp = path.with_suffix(f'.{os.getpid()}.tmp')
        with temp.open('w') as f:
            json.dump(data, f, indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)


def committed(data):
    return sum(r.get('charged_upper_usd', r['reserved_usd']) for r in data['requests'])


def reserve(model, job, payload_bytes, output_tokens, path=LEDGER):
    if model not in RATES:
        stop(f'No approved pricing envelope for model {model}')
    if payload_bytes > MAX_BYTES or output_tokens > MAX_OUTPUT:
        stop('Request exceeds the experiment pricing envelope')
    with transaction(path) as data:
        if committed(data) + REQUEST_RESERVE > API_CAP:
            stop('Experiment API budget exhausted, including outstanding reservations')
        rid = str(uuid.uuid4())
        data['requests'].append(dict(id=rid, model=model, job=job, reserved_usd=REQUEST_RESERVE,
                                     payload_bytes=payload_bytes, max_output_tokens=output_tokens,
                                     status='reserved', reserved_at=time.time()))
    return rid


def settle(rid, usage, path=LEDGER):
    fields = ('input_tokens', 'output_tokens', 'input_tokens_cache_read', 'input_tokens_cache_write')
    counts = {k: usage.get(k) or 0 for k in fields}
    if any(not isinstance(n, (float, int)) or not math.isfinite(n) or n < 0 for n in counts.values()):
        stop('Invalid usage: reservation retained; reconciliation required')
    with transaction(path) as data:
        row = next(r for r in data['requests'] if r['id'] == rid)
        if row['status'] != 'reserved':
            stop('Duplicate request settlement')
        inp, out = RATES[row['model']]
        # Cache counters can overlap input_tokens for some providers. Counting
        # them again intentionally overestimates rather than underestimates cost.
        cost = (inp * sum(counts[k] for k in fields if k != 'output_tokens') + out * counts['output_tokens']) / 1e6
        row.update(status='settled', usage=usage, charged_upper_usd=cost, settled_at=time.time())
        exceeded = cost > row['reserved_usd'] or committed(data) > API_CAP
    if exceeded:
        stop('Usage exceeded its reserved envelope; stop and reconcile pricing')


def reserve_sandbox(job, path=LEDGER):
    """Reserve $3 per <=1-hour, <=2-vCPU/4-GiB sandbox, including build margin."""
    with transaction(path) as data:
        if sum(x['reserved_usd'] for x in data['infrastructure']) + 3 > 100:
            stop('Infrastructure reserve exhausted; reconcile before more runs')
        data['infrastructure'].append({'job': job, 'reserved_usd': 3, 'at': time.time()})


@hooks(name='gemini_experiment_budget', description='Reserve spend before every experiment provider request')
class ExperimentBudget(Hooks):
    pending = {}

    def enabled(self):
        return os.environ.get('AAA_EXPERIMENT_BUDGET') == '1'

    async def on_before_model_generate(self, data):
        try:
            for msg in data.input:
                if isinstance(msg.content, list):
                    if any(c.type not in ('text', 'reasoning') for c in msg.content):
                        stop('Only text and recorded reasoning are budgeted in this pilot')
            data.config.max_tokens = min(data.config.max_tokens or MAX_OUTPUT, MAX_OUTPUT)
            data.config.max_retries = 0
            payload = json.dumps({'messages': [m.model_dump(mode='json') for m in data.input],
                                  'tools': [t.model_dump(mode='json') for t in data.tools],
                                  'config': data.config.model_dump(mode='json')}, ensure_ascii=False)
            rid = reserve(data.model_name, os.environ.get('AAA_EXPERIMENT_JOB', 'unspecified'),
                          len(payload.encode()), data.config.max_tokens)
            # These hooks run in the same generate coroutine. Failed prior
            # attempts stay reserved; they are never silently refunded.
            self.pending[(asyncio.current_task(), data.model_name)] = rid
        except LimitExceededError:
            raise
        except Exception as exc:
            stop(f'Budget guard failed closed: {type(exc).__name__}')

    async def on_model_usage(self, data):
        try:
            rid = self.pending.pop((asyncio.current_task(), data.model_name), None)
            if rid is None:
                stop('Usage had no matching pre-request reservation')
            settle(rid, data.usage.model_dump(mode='json'))
        except LimitExceededError:
            raise
        except Exception as exc:
            stop(f'Budget settlement failed closed: {type(exc).__name__}')
