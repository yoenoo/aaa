"""Export a failed canary honestly: valid debug scores, no invented scheming scores."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

from inspect_ai.event import ModelEvent, ScoreEvent
from inspect_ai.log import EvalResults, EvalScore, read_eval_log, write_eval_log
from inspect_ai.log._log import EvalScorer
from inspect_ai.scorer import Score
from transcript import rebuild_index
from experiments.aaa_vs_petri.export_rejudged import split_judge_events
from experiments.aaa_vs_petri.export_viewer import convert_petri
from experiments.aaa_vs_petri.full_judge import spec
from experiments.aaa_vs_petri.full_judge.export import add_usage, render_exchange, score_for
from experiments.aaa_vs_petri.full_judge.recovery import DEFAULT, ROOT, verify
from experiments.aaa_vs_petri.full_judge.run import atomic_json, now, sha


def export(run=DEFAULT):
    m = verify(run)
    destination = run / 'canary-diagnostic'
    if destination.exists():
        raise ValueError('Choose a fresh diagnostic export directory')
    audit = next(a for a in json.loads((run / 'private/audits.json').read_text()) if a['id'] == m['canary_audit_id'])
    source = ROOT / audit['source']
    original = read_eval_log(source, resolve_attachments='full')
    before = next(s for s in original.samples if s.uuid == audit['id'])
    rows = {f: json.loads((run / 'predictions' / f"{audit['id']}-{f}.json").read_text()) for f in spec.FAMILIES}
    if rows[spec.FAMILIES[0]]['status'] != 'failed' or rows[spec.FAMILIES[1]]['status'] != 'success':
        raise ValueError('Expected failed scheming and valid debug canary')
    spec.validate(rows[spec.FAMILIES[1]]['result'], json.loads((run / 'inputs' / f"{audit['id']}-{spec.FAMILIES[1]}.json").read_text()), spec.FAMILIES[1])
    destination.mkdir()
    for folder in ('eval', 'archive', 'judge-transcripts', 'viewer', 'viewer/data'):
        (destination / folder).mkdir()
    retained, retired = split_judge_events(before.events)
    copied = original.model_copy(deep=True)
    after = before.model_copy(deep=True)
    after.events, after.scores = deepcopy(retained), {}
    provenance = {'run': str(run), 'run_manifest_sha256': sha(run / 'manifest.json'),
                  'source_sha256': sha(source), 'exported_at': now(), 'execution_backend': 'modal',
                  'status': 'canary_failed_validation', 'batch_dispatched': False,
                  'note': 'Only debugging has valid scores. Scheming responses are saved as invalid attempts, not judgments or awareness labels.'}
    for family, row in rows.items():
        (destination / 'judge-transcripts' / f"{row['id']}.md").write_text(render_exchange(run, row))
        for attempt in row['attempts']:
            for raw in attempt['model_events']:
                event = ModelEvent.model_validate(raw)
                event.metadata = {**(event.metadata or {}), 'original_recorded_role': event.role,
                                  'judge_family': family, 'attempt': attempt['number'],
                                  'validation_status': attempt['status'], 'execution_backend': 'modal'}
                event.role = 'judge'
                after.events.append(event)
        if row['status'] == 'success':
            score = score_for(row, audit, provenance)
        else:
            failures = '\n'.join(f"- Attempt {a['number']}: {a.get('error', 'No valid result')}" for a in row['attempts'])
            score = Score(value={}, answer='**SCHEMING JUDGE FAILED VALIDATION — NO VALID SCORES OR AWARENESS LABELS.**\n\n'
                          + failures + '\n\nAll three returned responses and their requests are preserved in the copied .eval and judge-transcripts folder. The remaining batch was not launched.',
                          explanation='Invalid outputs are not negative findings, absent awareness, or low scores.',
                          metadata={'judge': 'scheming', 'judge_family': family, 'parse_status': 'failed_validation',
                                    'provenance': provenance, 'highlights': []})
        after.scores[family] = score
        after.events.append(ScoreEvent(score=score, scorer=family, metadata={'posthoc_import': True}))
    after.events = after.events[:len(retained)] + sorted(after.events[len(retained):], key=lambda e: e.timestamp)
    after.metadata = {**before.metadata, 'full_judge_canary_diagnostic': provenance}
    after.model_usage, after.role_usage = add_usage(after.events)
    copied.samples = [after]
    copied.eval.eval_id += '-canary-diagnostic-' + provenance['run_manifest_sha256'][:8]
    copied.eval.run_id += '-canary-diagnostic-' + provenance['run_manifest_sha256'][:8]
    copied.eval.scorers = [EvalScorer(name=f) for f in spec.FAMILIES]
    copied.eval.metrics = None
    copied.eval.metadata = {**(copied.eval.metadata or {}), 'full_judge_canary_diagnostic': provenance}
    copied.results = EvalResults(total_samples=1, completed_samples=1, scores=[
        EvalScore(name=f, scorer=f, scored_samples=int(rows[f]['status'] == 'success'), metrics={}) for f in spec.FAMILIES])
    copied.reductions = None
    copied.stats.model_usage = add_usage(after.events)[0]
    copied.recompute_tags_and_metadata()
    path = destination / 'eval' / 'recurring-agent-canary-diagnostic.eval'
    write_eval_log(copied, path)
    reopened = read_eval_log(path, resolve_attachments='full')
    sample = reopened.samples[0]
    allowed = {'scores', 'events', 'metadata', 'model_usage', 'role_usage', 'attachments', 'events_data'}
    if before.model_dump(mode='json', exclude=allowed) != sample.model_dump(mode='json', exclude=allowed):
        raise ValueError('Original sample content changed')
    if [e.model_dump(mode='json') for e in retained] != [e.model_dump(mode='json') for e in sample.events[:len(retained)]]:
        raise ValueError('Original audit events changed')
    if sample.scores[spec.FAMILIES[0]].value != {} or len(sample.scores[spec.FAMILIES[1]].value) != 14:
        raise ValueError('Invalid diagnostic score coverage')
    data = convert_petri(reopened, sample, path)
    data['id'] += '-canary-diagnostic-' + provenance['run_manifest_sha256'][:8]
    data['title'] += ' · CANARY: scheming validation failed'
    data['provenance']['full_judge_canary_diagnostic'] = provenance
    data['judge']['categorical_results'] = {}  # No inferred absent/unassessable awareness labels.
    atomic_json(destination / 'viewer/data' / f"{data['id']}.json", data)
    rebuild_index(destination / 'viewer/data')
    atomic_json(destination / 'archive/retired-judgments.json', {
        'scores': {k: v.model_dump(mode='json') for k, v in (before.scores or {}).items()},
        'events': [e.model_dump(mode='json') for e in retired]})
    if sha(source) != m['source_sha256'][audit['source']]:
        raise ValueError('Original transcript changed')
    atomic_json(destination / 'manifest.json', {**provenance, 'viewer_id': data['id'],
        'exporter_sha256': sha(Path(__file__)),
        'artifact_sha256': {str(p.relative_to(destination)): sha(p) for p in destination.rglob('*') if p.is_file()}})
    print(json.dumps({'destination': str(destination), 'viewer_id': data['id'], 'valid_debug_dimensions': 14,
                      'valid_scheming_dimensions': 0, 'captured_judge_model_events': sum(len(a['model_events']) for r in rows.values() for a in r['attempts'])}, indent=2))


if __name__ == '__main__':
    export()
