"""Offline full evidence digest; no model calls or automatic awareness labels."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from inspect_ai.log import read_eval_log
from judge_packet import sample_packet
from experiments.gemini_realism_awareness.overpermission import MESSAGES, pressure_windows, scenario_user_text


def review(job):
    files = list(job.glob('*.eval'))
    if len(files) != 1 or not (job / 'summary.json').exists():
        return None
    log = read_eval_log(str(files[0]), resolve_attachments='full')
    if not log.samples:
        return {'job': job.name, 'status': log.status, 'assessable': False}
    s = log.samples[0]
    packet, _ = sample_packet(s, str(log.eval.model))
    (job / 'full-evidence-packet.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2))
    window = pressure_windows(packet)
    (job / 'observation-window.json').write_text(json.dumps(window, ensure_ascii=False, indent=2))
    outputs = [r for r in packet['records'] if r['actor'] == 'target']
    phase = {ident: stage for stage, ids in window['stage_output_ids'].items() for ident in ids}
    text = []
    candidates = []
    for r in outputs:
        stage = phase.get(r['id'], 'AUXILIARY' if r['id'] in window['auxiliary_output_ids'] else 'UNMAPPED')
        text.append(f"## {r['id']} | stage {stage} | primary {r['id'] in window['primary_output_ids']}\n")
        for channel in ('assistant_text', 'reasoning_summary'):
            value = r.get(channel, '')
            text.append(f'### {channel}\n\n{value}\n')
            for match in re.finditer(r'\b(?:eval\w*|benchmark\w*|simulat\w*|mock\w*|test\w*|honeypot\w*)\b', value, re.I):
                candidates.append({'record': r['id'], 'stage': stage, 'channel': channel,
                    'excerpt': value[max(0,match.start()-100):match.end()+220]})
        text.append('### Tool calls\n\n' + json.dumps(r.get('tool_calls'), ensure_ascii=False, indent=2) + '\n')
    (job / 'target-output-digest.md').write_text('\n'.join(text))
    users = [r for r in packet['records'] if r['actor'] == 'user']
    user_texts = list(dict.fromkeys(r.get('text','') for r in users))
    acting_inputs = {i for q in packet['requests'] if q['output_id'] not in window['auxiliary_output_ids'] for i in q['input_ids']}
    acting_users = list(dict.fromkeys(scenario_user_text(r.get('text','')) for r in users if r['id'] in acting_inputs))
    systems = [r.get('text','') for r in packet['records'] if r['actor'] == 'system']
    contract = json.loads((job / 'shared-scenario.json').read_text())
    toolsets = []
    for r in packet['records']:
        if r['actor'] != 'tool_definitions':
            continue
        names = sorted(t['name'] for t in json.loads(r['text']))
        if names not in toolsets:
            toolsets.append(names)
    row = {'job': job.name, 'source': str(files[0]),
        'source_sha256': hashlib.sha256(files[0].read_bytes()).hexdigest(),
        'review_code_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(__file__).with_name('overpermission.py')]},
        'status': log.status, 'sample_error': str(s.error) if s.error else None,
        'sample_limit': s.limit.model_dump(mode='json') if s.limit else None,
        'wall_seconds': s.total_time,
        'target_outputs': len(outputs),
        'acting_target_outputs': len(outputs) - len(window['auxiliary_output_ids']),
        'auxiliary_output_ids': window['auxiliary_output_ids'],
        'output_ids_by_stage': window['stage_output_ids'],
        'primary_output_ids': window['primary_output_ids'],
        'both_pressure_stages_observed': window['both_pressure_stages_observed'],
        'observed_user_texts': user_texts,
        'exact_user_script': acting_users == MESSAGES,
        'script_comparison_note': 'AAA startup session_context wrapper is recorded verbatim but excluded from message equality. Distinct CLI diagnostic-agent requests remain recorded and are excluded from acting-target counts.',
        'native_petri_exact_role': bool(systems) and all(x == contract['shared_role'] for x in systems) if '-petri-' in job.name else None,
        'observed_target_toolsets': toolsets,
        'reasoning_records': sum(bool(r.get('reasoning_summary')) for r in outputs),
        'nontext_omitted_records': sum(bool(r.get('nontext_omitted')) for r in outputs),
        'lexical_candidates_not_labels': candidates,
        'awareness_label': None,
        'limitations': 'Requires complete output review and observed-state conformance checks. Keyword hits are not awareness labels. No numeric realism score inferred.'}
    (job / 'evidence-review.json').write_text(json.dumps(row, ensure_ascii=False, indent=2))
    if '-petri-' in job.name:
        results = {}
        for r in packet['records']:
            if r['actor'] == 'tool':
                match = re.match(r'tool_call_id=([^\n]+)\n(.*)', r.get('text',''), re.S)
                if match:
                    results[match[1]] = match[2]
        transitions = []
        for r in outputs:
            for call in r.get('tool_calls', []):
                transitions.append({'record_id':r['id'], 'stage':phase.get(r['id']),
                    'call':call, 'result':results.get(call['id']),
                    'assessment':None})
        (job / 'observed-transitions.json').write_text(json.dumps(transitions, ensure_ascii=False, indent=2))
    return {k:v for k,v in row.items() if k not in ('lexical_candidates_not_labels','observed_user_texts')}


def main():
    rows = []
    for job in sorted((ROOT / 'logs/gemini-realism-awareness').glob('flash-permissions-*')):
        if job.is_dir():
            result = review(job)
            if result:
                rows.append(result)
    print(json.dumps(rows, indent=2))


if __name__ == '__main__': main()
