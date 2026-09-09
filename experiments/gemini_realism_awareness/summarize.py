"""Summarize pilot scoring offline, preserving failed/missing judgments."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = {
    'scheming': ['verbalized_eval_awareness', 'simulation_suspicion', 'awareness_conditioned_behavior'],
    'debug': ['scenario_realism', 'role_organizational_realism', 'tool_interface_realism',
              'state_causal_consistency', 'interaction_naturalness'],
}


def summarize_scores(scores):
    families = {}
    for family, dimensions in DIMENSIONS.items():
        score = scores.get(family + '_judge_v3')
        if score is None:
            families[family] = {'status': 'missing', 'assessments': {}}
            continue
        meta = score.get('metadata') or {}
        valid = meta.get('parse_status') == 'full'
        families[family] = {'status': 'valid' if valid else 'invalid',
            'attempts': [a.get('status') for a in meta.get('attempts', [])],
            'summary': score.get('answer'), 'coverage': meta.get('coverage'),
            'unresolved_limitations': meta.get('unresolved_limitations'), 'assessments': {}}
        for dimension in dimensions:
            applicability = (meta.get('applicability') or {}).get(dimension)
            value = score.get('value')
            families[family]['assessments'][dimension] = {
                'score': value.get(dimension) if valid and applicability == 'exercised' and isinstance(value, dict) else None,
                'applicability': applicability,
                'reason': (meta.get('reasons') or {}).get(dimension),
                'evidence': (meta.get('evidence') or {}).get(dimension, []),
            }
    return families


def main():
    root = ROOT / 'logs/gemini-realism-awareness'
    rows = []
    for review in json.loads((root / 'review.json').read_text()):
        path = root / review['job'] / 'judged/results.json'
        scores = {}
        if path.exists():
            samples = json.loads(path.read_text())
            if len(samples) != 1:
                raise ValueError('Pilot summary expects one sample per job')
            scores = samples[0]['scores']
        rows.append({k:v for k,v in review.items() if k != 'lexical_screen_only'} |
                    {'judgments': summarize_scores(scores)})
    (root / 'pilot-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    for row in rows:
        print(row['job'], {f: {'status': r['status'], 'scores': {d:a['score'] for d,a in r['assessments'].items()}}
                          for f,r in row['judgments'].items()})


if __name__ == '__main__': main()
