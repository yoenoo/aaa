"""Frozen, additive recovery accounting; never reset the original Modal ledger."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

from experiments.aaa_vs_petri.full_judge import nullable_array, spec
from experiments.aaa_vs_petri.full_judge.run import ROOT, DEFAULT as ORIGINAL, atomic_json, now, sha, verify as verify_original

DEFAULT = ROOT / 'logs/petri-full-judge/nullable-recovery-opus48'
CANARY = 'QweM4k2qncPCxxwFbvCSww'


def pre_send(attempt):
    """Only the diagnosed closed-client traceback qualifies; unknowns count."""
    events = attempt.get('model_events', [])
    return (attempt.get('status') == 'error' and 'response' not in attempt and bool(events)
            and all('Cannot send a request, as the client has been closed.' in e.get('traceback', '')
                    and e.get('error') and not (e.get('output') or {}).get('usage')
                    and not (e.get('output') or {}).get('completion')
                    and all(not c.get('message', {}).get('content') and not c.get('message', {}).get('tool_calls')
                            for c in (e.get('output') or {}).get('choices', [])) for e in events))


def prepare(run=DEFAULT):
    if run.exists():
        return verify(run)
    original = verify_original(ORIGINAL)
    jobs = json.loads((ORIGINAL / 'jobs.json').read_text())
    rows = {j['id']: json.loads((ORIGINAL / 'predictions' / f"{j['id']}.json").read_text()) for j in jobs}
    excluded = sum(pre_send(a) for r in rows.values() for a in r['attempts'])
    reserved = sum(len(r['attempts']) for r in rows.values())
    if (len(rows), reserved, excluded, sum(r['status'] == 'success' for r in rows.values())) != (36, 99, 87, 3):
        raise ValueError('Original accounting differs from the reviewed 99-record snapshot')
    run.mkdir(parents=True)
    for folder in ('inputs', 'prompts', 'private', 'initial', 'predictions'):
        (run / folder).mkdir()
    for filename in ('audits.json', 'frozen-v5-audits.json'):
        shutil.copyfile(ORIGINAL / 'private' / filename, run / 'private' / filename)
    schemas = json.loads((ORIGINAL / 'schemas.json').read_text())
    wire = {}
    for family in spec.FAMILIES:
        wire[family] = nullable_array.wire_schema(schemas[family]['inlined'], family)
        (run / 'prompts' / f'{family}.txt').write_text(nullable_array.transport_prompt(
            (ORIGINAL / 'prompts' / f'{family}.txt').read_text(), wire[family]))
    atomic_json(run / 'schemas.json', wire)
    for job in jobs:
        row = deepcopy(rows[job['id']])
        row['legacy_prediction'] = str(ORIGINAL / 'predictions' / f"{job['id']}.json")
        row['legacy_pre_send_attempt_numbers'] = [a['number'] for a in row['attempts'] if pre_send(a)]
        row['attempts'] = [a for a in row['attempts'] if not pre_send(a)]
        for a in row['attempts']:
            a['origin'] = 'original_run'
        if row['status'] != 'success':
            row['status'] = 'pending'
            row.pop('result', None)
        job['max_new_attempts'] = 0 if row['status'] == 'success' else 3 - len(row['attempts'])
        atomic_json(run / 'initial' / f"{job['id']}.json", row)
        atomic_json(run / 'predictions' / f"{job['id']}.json", row)
        shutil.copyfile(ORIGINAL / 'inputs' / f"{job['id']}.json", run / 'inputs' / f"{job['id']}.json")
    if sum(j['max_new_attempts'] for j in jobs) != 91:
        raise ValueError('Recovery exceeds the approved 91 new requests')
    atomic_json(run / 'jobs.json', jobs)
    code = ['recovery.py', 'worker_nullable.py', 'modal_recovery.py', 'nullable_array.py', 'spec.py', 'worker.py']
    m = {**original, 'version': 'full-audit-integration-v1-nullable-recovery',
         'created_at': now(), 'original_run': str(ORIGINAL), 'original_manifest_sha256': sha(ORIGINAL / 'manifest.json'),
         'original_ledger_entries': 99, 'original_pre_send_failures': 87, 'original_provider_requests': 12,
         'max_additional_requests': 91, 'max_provider_requests': 103, 'max_total_ledger_entries': 190,
         'canary_audit_id': CANARY,
         'approval': 'User approved recovery, first one audit through both judges and transcript-viewer verification, then remaining transcripts on Modal. Up to 91 additional requests, 103 total provider requests; all original failures preserved.',
         'transport': 'Native array of dimension/score pairs with one nullable score schema; None/null retained. Rubric semantics unchanged, output-format instructions/schema changed. Three prior valid judgments reused with their actual historical transport.',
         'retry_policy': 'First structurally valid result wins. At most three counted attempts per job including prior provider requests; unknown new failures count. No SDK/Inspect/Modal retries. Original 87 proven pre-send failures archived, not erased.',
         'code_sha256': {str((Path(__file__).parent / f).relative_to(ROOT)): sha(Path(__file__).parent / f) for f in code},
         'original_prediction_sha256': {str(p): sha(p) for p in (ORIGINAL / 'predictions').glob('*.json')}}
    m['artifact_sha256'] = {str(p.relative_to(run)): sha(p) for p in run.rglob('*')
                          if p.is_file() and 'predictions' not in p.relative_to(run).parts}
    atomic_json(run / 'manifest.json', m)
    return verify(run)


def verify(run=DEFAULT):
    m = json.loads((run / 'manifest.json').read_text())
    verify_original(Path(m['original_run']))
    if sha(Path(m['original_run']) / 'manifest.json') != m['original_manifest_sha256']:
        raise ValueError('Original manifest changed')
    if (m['max_additional_requests'], m['max_provider_requests'], m['max_total_ledger_entries']) != (91, 103, 190):
        raise ValueError('Recovery budget changed')
    for paths, root in ((m['code_sha256'], ROOT), (m['artifact_sha256'], run),
                        (m['original_prediction_sha256'], Path('/'))):
        for relative, expected in paths.items():
            if sha(root / relative) != expected:
                raise ValueError(f'Frozen recovery artifact changed: {relative}')
    return m


def payloads(run=DEFAULT):
    m = verify(run)
    schemas = json.loads((run / 'schemas.json').read_text())
    for job in json.loads((run / 'jobs.json').read_text()):
        content = (run / 'inputs' / f"{job['id']}.json").read_text()
        yield {**job, 'run_hash': sha(run / 'manifest.json'), 'model': m['judge_model'],
               'input_text': content, 'input_sha256': hashlib.sha256(content.encode()).hexdigest(),
               'prompt': (run / 'prompts' / f"{job['family']}.txt").read_text(),
               'schema': schemas[job['family']],
               'initial': json.loads((run / 'initial' / f"{job['id']}.json").read_text())}
