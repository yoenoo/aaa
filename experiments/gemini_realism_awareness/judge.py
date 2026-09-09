"""Score a finished development log with frozen production v3 judges; keep originals."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
os.environ['AAA_EXPERIMENT_BUDGET'] = '1'
from experiments.gemini_realism_awareness import budget
from inspect_ai import score
from inspect_ai.log import read_eval_log, write_eval_log
from scorer import scheming_judge_v3, debug_judge_v3


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('job')
    args = ap.parse_args()
    root = ROOT / 'logs/gemini-realism-awareness'
    path = root / args.job
    if path.resolve().parent != root.resolve(): ap.error('job must be a run directory name')
    files = list(path.glob('*.eval'))
    if len(files) != 1: ap.error('expected exactly one generated eval')
    source = files[0]
    log = read_eval_log(str(source), resolve_attachments='full')
    if log.status == 'started': ap.error('generation is still running')
    if not log.samples: ap.error('no samples to judge')
    out = path / 'judged'
    if out.exists(): ap.error('judged directory already exists')
    out.mkdir()
    os.environ['AAA_EXPERIMENT_JOB'] = args.job + '-judging'
    prompts = list((ROOT / 'src/prompts/judges').rglob('*')) + [ROOT / 'src/scorer.py', ROOT / 'src/structured_judge.py', ROOT / 'src/judge_packet.py']
    manifest = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'judge_model': 'anthropic/claude-opus-4-8', 'retries': 2,
                'packet_budget_chars': 700_000,
                'hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in prompts if p.is_file()}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    scored = score(log, [scheming_judge_v3(retries=2, budget_chars=700_000), debug_judge_v3(retries=2, budget_chars=700_000)], action='overwrite', display='plain')
    dest = out / source.name
    write_eval_log(scored, str(dest))
    rows = []
    for sample in scored.samples:
        rows.append({'uuid': sample.uuid, 'sample_id': sample.id,
                     'scores': {k: {'answer': s.answer, 'value': s.value, 'metadata': s.metadata} for k,s in (sample.scores or {}).items()}})
    (out / 'results.json').write_text(json.dumps(rows, indent=2, default=str))
    print(json.dumps({'job': args.job, 'scored': str(dest), 'samples': len(rows)}), flush=True)


if __name__ == '__main__': main()
