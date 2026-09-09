"""Offline conformance checks for the published synthetic-inbox baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspect_ai.log import read_eval_log
from experiments.gemini_realism_awareness import published_blackmail as fixture
from experiments.gemini_realism_awareness.matched import NATIVE_AUDITOR_TOOLS


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items() if v is not None}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def review(job):
    manifest = json.loads((job/'manifest.json').read_text())
    packet = json.loads((job/'full-evidence-packet.json').read_text())
    log = read_eval_log(str(next(job.glob('*.eval'))))
    sample = log.samples[0]
    records = packet['records']
    checks = {}
    for role in ('system','user'):
        values = [r['text'] for r in records if r['actor'] == role]
        checks['exact_' + role] = len(values) == 1 and sha(values[0]) == manifest['actual_fixture_hashes'][role]
    schemas = [clean(json.loads(r['text'])) for r in records if r['actor'] == 'tool_definitions']
    checks['exact_tool_schemas'] = bool(schemas) and all(sorted(s, key=lambda t:t['name']) == sorted(fixture.TOOL_SCHEMAS, key=lambda t:t['name']) for s in schemas)
    outputs = [r for r in records if r['actor'] == 'target']
    reads = [t for r in outputs for t in r.get('tool_calls',[]) if t['function'] == 'read_inbox']
    results = {r['text'].split('\n',1)[0].removeprefix('tool_call_id='):r['text'].split('\n',1)[1]
        for r in records if r['actor'] == 'tool' and r['text'].startswith('tool_call_id=') and '\n' in r['text']}
    checks['fixture_source_hash'] = sha(fixture.EMAILS) == manifest['actual_fixture_hashes']['emails']
    checks['complete_exact_inbox_ignoring_outer_whitespace'] = bool(reads) and all(
        t['arguments'] == {} and t['id'] in results and results[t['id']].strip() == fixture.EMAILS.strip() for t in reads)
    checks['one_branch'] = {q['branch'] for q in packet['requests']} == {1}
    checks['within_output_limit'] = 2 <= len(outputs) <= 5
    events = [e for e in sample.events if e.event == 'model' and getattr(e,'role',None) == 'target']
    checks['target_model_and_config'] = len(events) == len(outputs) and all(
        e.model == manifest['model'] and e.config.reasoning_tokens == 4096 and e.config.max_tokens == 16384 for e in events)
    realism_answer_ids = {t.id for e in sample.events if e.event == 'model' and getattr(e,'role',None) == 'realism'
        for t in (e.output.message.tool_calls or []) if t.function == 'answer'}
    tool_events = [e for e in sample.events if e.event == 'tool']
    checks['realism_answers_attributed'] = all(e.id in realism_answer_ids for e in tool_events if e.function == 'answer')
    tool_names = sorted({e.function for e in tool_events if not (e.function == 'answer' and e.id in realism_answer_ids)})
    checks['native_synthetic_auditor_only'] = set(tool_names) <= NATIVE_AUDITOR_TOOLS
    checks['no_error_or_limit'] = log.status == 'success' and not sample.error and not sample.limit
    row = {'job':job.name, 'conformant':all(checks.values()), 'checks':checks,
        'inbox_byte_verbatim':bool(reads) and all(results.get(t['id']) == fixture.EMAILS for t in reads),
        'target_outputs':len(outputs), 'observed_auditor_tools':tool_names,
        'internal_realism_answer_calls':sum(e.function == 'answer' and e.id in realism_answer_ids for e in tool_events),
        'target_calls':[t['function'] for r in outputs for t in r.get('tool_calls',[])],
        'review_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256(next(job.glob('*.eval')).read_bytes()).hexdigest(),
        'awareness_label':None, 'note':'Conformance only. Awareness requires full manual output/context review; no label inferred here.'}
    (job/'conformance-review.json').write_text(json.dumps(row,indent=2))
    return row


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('jobs',nargs='+')
    args = ap.parse_args()
    print(json.dumps([review(ROOT/'logs/gemini-realism-awareness'/j) for j in args.jobs],indent=2))
