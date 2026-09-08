"""One entrypoint: canary -> viewer gate -> remaining full Petri judgments."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import modal

ROOT = Path(__file__).resolve().parents[3] if modal.is_local() else Path('/opt/aaa')
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
app = modal.App('aaa-petri-full-judge-nullable')
state = modal.Dict.from_name('aaa-petri-full-judge-v1-records', create_if_missing=True)
image = modal.Image.debian_slim(python_version='3.13').pip_install(
    'inspect-ai==0.3.246', 'anthropic==0.116.0', 'pydantic==2.13.4', 'pyyaml==6.0.3',
).env({'PYTHONPATH': '/opt/aaa:/opt/aaa/src'})
for relative in ('src/awareness_v5.py', 'src/awareness_v3.py', 'src/judge_v4.py',
                 'experiments/aaa_vs_petri/full_judge/spec.py', 'experiments/aaa_vs_petri/full_judge/worker.py',
                 'experiments/aaa_vs_petri/full_judge/nullable_array.py', 'experiments/aaa_vs_petri/full_judge/worker_nullable.py'):
    image = image.add_local_file(ROOT / relative, '/opt/aaa/' + relative)
image = image.add_local_dir(ROOT / 'src/prompts', '/opt/aaa/src/prompts', ignore=['**/__pycache__/**'])
key = os.environ.get('ANTHROPIC_API_KEY')
if not key and modal.is_local():
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / '.env').get('ANTHROPIC_API_KEY')
if not key:
    raise ValueError('Missing Anthropic key; no key values logged')


@app.function(image=image, secrets=[modal.Secret.from_dict({'ANTHROPIC_API_KEY': key})],
              retries=0, max_containers=6, timeout=1100, cpu=1, memory=2048)
async def judge_job(job):
    from experiments.aaa_vs_petri.full_judge.worker_nullable import execute_one
    return await execute_one(job, state)


@app.local_entrypoint()
def main(phase: str = 'canary', approved_paid_run: bool = False):
    from experiments.aaa_vs_petri.full_judge.recovery import DEFAULT, prepare, payloads
    from experiments.aaa_vs_petri.full_judge.run import atomic_json, now, sha
    run = DEFAULT
    m = prepare(run)
    jobs = list(payloads(run))
    namespace = sha(run / 'manifest.json')
    if phase not in {'canary', 'rest', 'fetch'}:
        raise ValueError('Use canary, rest, or fetch')

    def fetch():
        counts, reservations = Counter(), 0
        for job in jobs:
            row = state.get(f"{namespace}/{job['id']}/row", None) or job['initial']
            if row['id'] != job['id'] or len(row['attempts']) > 3:
                raise ValueError('Invalid recovery checkpoint')
            atomic_json(run / 'predictions' / f"{job['id']}.json", row)
            counts[row['status']] += 1
            for slot in range(1, job['max_new_attempts'] + 1):
                reservations += state.contains(f"{namespace}/{job['id']}/reservation/{slot}")
        if reservations > 91:
            raise ValueError('Additional request ceiling exceeded')
        progress = {'recorded_at': now(), 'execution_backend': 'modal', 'job_status_counts': dict(counts),
                    'new_requests_reserved': reservations, 'new_request_ceiling': 91,
                    'total_provider_requests_upper_bound': 12 + reservations,
                    'total_ledger_entries': 99 + reservations, 'original_pre_send_failures': 87,
                    'run_hash': namespace}
        atomic_json(run / 'progress.json', progress)
        print(json.dumps(progress, indent=2), flush=True)

    if phase == 'fetch':
        fetch()
        return
    if not approved_paid_run:
        raise ValueError('Explicit paid-run approval required')
    if state.get(namespace + '/halt', None):
        fetch()
        raise ValueError('Recovery provider halt is set; no calls dispatched')
    if phase == 'rest':
        gate = json.loads((run / 'viewer-gate.json').read_text())
        bundle = run / 'canary-results'
        if (gate.get('run_manifest_sha256') != namespace or not gate.get('browser_verified')
                or gate.get('canary_audit_id') != m['canary_audit_id']
                or gate.get('export_manifest_sha256') != sha(bundle / 'manifest.json')):
            raise ValueError('A verified canary viewer gate is required before fanout')
        for job in jobs:
            if job['audit_id'] == m['canary_audit_id']:
                row = state.get(f"{namespace}/{job['id']}/row", None)
                if not row or row['status'] != 'success':
                    raise ValueError('Canary judgments are not complete')
    selected = [j for j in jobs if j['audit_id'] == m['canary_audit_id']] if phase == 'canary' else jobs
    try:
        for outcome in judge_job.map(selected, order_outputs=False):
            print(json.dumps(outcome), flush=True)
            row = state.get(f"{namespace}/{outcome['id']}/row", None)
            if row:
                atomic_json(run / 'predictions' / f"{outcome['id']}.json", row)
    finally:
        fetch()
    selected_rows = [json.loads((run / 'predictions' / f"{j['id']}.json").read_text()) for j in selected]
    if any(r['status'] != 'success' for r in selected_rows):
        raise RuntimeError('Some judgments did not validate; inspect preserved attempts before further action')
    from experiments.aaa_vs_petri.full_judge.export import export
    destination = run / ('canary-results' if phase == 'canary' else 'full-results')
    if not destination.exists():
        result = export(run, destination, audit_ids=[m['canary_audit_id']] if phase == 'canary' else None)
        print(json.dumps({'export': str(destination), 'audits': result['audits']}), flush=True)
