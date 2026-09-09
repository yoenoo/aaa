"""Offline review/export of completed canaries; makes no provider calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from inspect_ai.log import read_eval_log
from judge_packet import sample_packet, compact
from transcript import convert_log, rebuild_index
from experiments.aaa_vs_petri.export_viewer import convert_petri


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--viewer-data', type=Path)
    args = ap.parse_args()
    root = ROOT / 'logs/gemini-realism-awareness'
    rows = []
    for manifest in sorted(root.glob('*/manifest.json')):
        job = manifest.parent.name
        m = json.loads(manifest.read_text())
        files = list(manifest.parent.glob('*.eval'))
        if len(files) != 1: continue
        source = files[0]
        log = read_eval_log(str(source), resolve_attachments='full')
        if log.status == 'started' or not log.samples: continue
        sample = log.samples[0]
        try:
            packet, _ = sample_packet(sample, str(log.eval.model))
        except ValueError as error:
            # A time-limited Petri audit can retain provider events without its
            # finalized auditor messages. Preserve evidence, never invent anchors.
            targets = [e for e in sample.events if e.event == 'model' and e.role == 'target']
            raw = manifest.parent / 'target-provider-events.json'
            raw.write_text(json.dumps([e.model_dump(mode='json') for e in targets], ensure_ascii=False, indent=2))
            rows.append({'job': job, 'condition': m['condition'],
                'support_evidence': m.get('support_evidence', False),
                'generation_status': log.status, 'sample_error': bool(sample.error),
                'sample_limit': sample.limit.model_dump(mode='json') if sample.limit else None,
                'wall_seconds': sample.total_time, 'packet_error': str(error),
                'target_outputs': sum(e.output is not None and not e.error for e in targets),
                'outputs_by_branch': None, 'payload': None,
                'raw_target_provider_events': str(raw), 'lexical_screen_only': []})
            continue
        payload = manifest.parent / 'judge-payload-review.json'
        payload.write_text(json.dumps(compact(packet, 700_000), ensure_ascii=False, indent=2))
        if m.get('matched'):
            from experiments.gemini_realism_awareness.matched import observation_window
            window = observation_window(packet)
            if m['seed'] == 'as-recurring-agent-overpermission':
                from experiments.gemini_realism_awareness.overpermission import pressure_windows
                window = pressure_windows(packet)
            (manifest.parent / 'observation-window.json').write_text(json.dumps(window, ensure_ascii=False, indent=2))
        evidence = []
        target_records = [r for r in packet['records'] if r['actor'] == 'target']
        for r in target_records:
            for channel in ('assistant_text', 'reasoning_summary'):
                text = r.get(channel, '')
                for match in re.finditer(r'\b(?:simulat\w*|mock\w*|evaluation|benchmark|test of)\b', text, re.I):
                    evidence.append({'record_id': r.get('id'), 'channel': channel,
                        'excerpt': text[max(0, match.start()-140):match.end()+240]})
        row = {'job': job, 'condition': m['condition'], 'support_evidence': m.get('support_evidence', False),
               'matched': m.get('matched', False), 'scenario_contract_sha256': m.get('scenario_contract_sha256'),
               'generation_status': log.status, 'sample_error': bool(sample.error),
               'sample_limit': sample.limit.model_dump(mode='json') if sample.limit else None,
               'wall_seconds': sample.total_time,
               'outputs_by_branch': {str(b): sum(r.get('branch') == b for r in target_records) for b in sorted({r.get('branch', 1) for r in target_records})},
               'target_outputs': len(target_records), 'payload': str(payload),
               'payload_sha256': hashlib.sha256(payload.read_bytes()).hexdigest(),
               'payload_bytes': payload.stat().st_size,
               'lexical_screen_only': evidence}
        if args.viewer_data:
            sid = 'experiment-' + job
            judged = list((manifest.parent / 'judged').glob('*.eval'))
            if len(judged) > 1:
                raise ValueError(f'Multiple judged logs for {job}')
            export_source = judged[0] if judged else source
            export_log = read_eval_log(str(export_source), resolve_attachments='full') if judged else log
            export_sample = export_log.samples[0]
            if m['condition'] == 'petri':
                export_sample = export_sample.model_copy(update={'metadata': {**(export_sample.metadata or {}), 'source_scenario': m['seed']}})
                data = convert_petri(export_log, export_sample, export_source)
                data['id'] = sid
            else:
                data = convert_log(export_log, log_id=sid)
            variant = 'matched specification' if m.get('matched') else 'diagnostic evidence' if m.get('support_evidence') else 'baseline'
            label = f"Pilot · {m['condition'].upper()} · {variant}"
            data['title'] = label
            data['seed_name'] = label + ' · ' + m['seed']
            data['provenance'] = {**data.get('provenance', {}), 'experiment_job': job,
                'source_log': str(export_source), 'generation_source_log': str(source),
                'stage': 'development-canary', 'judgment_status': 'scoring_attempted' if judged else 'not_yet_judged',
                'scenario_contract_sha256': m.get('scenario_contract_sha256'),
                'sample_limit': row['sample_limit']}
            args.viewer_data.mkdir(parents=True, exist_ok=True)
            (args.viewer_data / (sid + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2))
            row['viewer_url'] = f'http://127.0.0.1:5180/#/{sid}'
        rows.append(row)
    (root / 'review.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    if args.viewer_data: rebuild_index(args.viewer_data)
    print(json.dumps([{k:v for k,v in r.items() if k != 'lexical_screen_only'} for r in rows], indent=2))


if __name__ == '__main__': main()
