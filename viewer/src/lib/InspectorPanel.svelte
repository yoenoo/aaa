<script lang="ts">
  import type { TranscriptData, Highlight } from './types';
  import MarkdownText from './MarkdownText.svelte';

  let {
    transcript,
    tab = $bindable<'evidence' | 'scores' | 'run'>('evidence'),
    onJump,
  }: {
    transcript: TranscriptData;
    tab?: 'evidence' | 'scores' | 'run';
    onJump: (highlight: Highlight) => void;
  } = $props();

  const positiveDimensions = new Set([
    'genuine_honesty',
    'transparent_disagreement',
    'legitimate_escalation',
    'scenario_realism',
  ]);
  const metaDimensions = new Set(['eval_awareness', 'monitoring_detection']);

  const orderedScores = $derived.by(() =>
    Object.entries(transcript.judge.scores || {})
      .map(([name, value]) => ({
        name,
        value,
        source: transcript.judge.score_sources?.[name] || '',
      }))
      .sort((a, b) => {
        if (a.source !== b.source) return a.source.localeCompare(b.source);
        return b.value - a.value;
      }),
  );

  function sourceLabel(source: string): string {
    return (source || 'judge').replace(/_judge$/, '').replace(/_/g, ' ');
  }

  function scoreTone(name: string, value: number, source: string): string {
    if (source === 'debug' || positiveDimensions.has(name)) return value >= 7 ? 'good' : value >= 4 ? 'mild' : 'quiet';
    if (metaDimensions.has(name)) return value >= 6 ? 'meta' : 'quiet';
    return value >= 6 ? 'high' : value >= 4 ? 'mild' : 'quiet';
  }

  function shortModel(model: string): string {
    return model.split('/').pop() || model;
  }

  function compactNumber(value: number): string {
    if (value < 1_000) return String(value);
    if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}K`;
    return `${(value / 1_000_000).toFixed(2)}M`;
  }
</script>

<aside class="inspector">
  <div class="tabs" role="tablist" aria-label="Transcript analysis">
    <button class:active={tab === 'evidence'} onclick={() => (tab = 'evidence')}>
      Evidence <span>{transcript.judge.highlights.length}</span>
    </button>
    <button class:active={tab === 'scores'} onclick={() => (tab = 'scores')}>
      Scores <span>{orderedScores.length}</span>
    </button>
    <button class:active={tab === 'run'} onclick={() => (tab = 'run')}>Run</button>
  </div>

  <div class="panel-scroll">
    {#if tab === 'evidence'}
      {#if transcript.judge.sources?.length}
        <details class="summary-card" open>
          <summary>Judge synthesis</summary>
          <div class="summary-body">
            {#each transcript.judge.sources as source}
              {#if transcript.judge.summaries?.[source]}
                <section class="judge-summary">
                  <div class="source-label">{sourceLabel(source)}</div>
                  <MarkdownText text={transcript.judge.summaries[source]} />
                </section>
              {/if}
            {/each}
          </div>
        </details>
      {:else if transcript.judge.summary}
        <details class="summary-card" open>
          <summary>Judge synthesis</summary>
          <div class="summary-body"><MarkdownText text={transcript.judge.summary} /></div>
        </details>
      {/if}

      {#if transcript.judge.highlights.length === 0}
        <p class="empty">No cited evidence in this run.</p>
      {:else}
        <ol class="evidence-list">
          {#each transcript.judge.highlights as h, i (i)}
            <li>
              <button class="evidence-card" onclick={() => onJump(h)}>
                <div class="evidence-meta">
                  <span class="source {h.source || ''}">{sourceLabel(h.source || 'judge')}</span>
                  <code>{h.event_id}</code>
                  <span class="index">{i + 1}</span>
                </div>
                <div class="note">{h.note}</div>
                {#if h.quoted_text}<blockquote>{h.quoted_text}</blockquote>{/if}
              </button>
            </li>
          {/each}
        </ol>
      {/if}
    {:else if tab === 'scores'}
      <div class="score-legend">
        <span><i class="high"></i> concerning</span>
        <span><i class="good"></i> positive / quality</span>
        <span><i class="meta"></i> meta</span>
      </div>
      <div class="score-list">
        {#each orderedScores as score (score.name)}
          {@const tone = scoreTone(score.name, score.value, score.source)}
          <div class="score-row {tone}" title={transcript.judge.score_descriptions?.[score.name] || score.name}>
            <div class="score-head">
              <span class="score-name">{score.name.replace(/_/g, ' ')}</span>
              <span class="score-source">{sourceLabel(score.source)}</span>
              <strong>{score.value}</strong>
            </div>
            <div class="score-track"><i style={`width:${Math.max(0, Math.min(100, score.value * 10))}%`}></i></div>
          </div>
        {/each}
      </div>
    {:else}
      <section class="run-block">
        <h3>Models</h3>
        <dl>
          <div><dt>Target</dt><dd title={transcript.target_model}>{shortModel(transcript.target_model)}</dd></div>
          <div><dt>Auditor</dt><dd title={transcript.auditor_model}>{shortModel(transcript.auditor_model)}</dd></div>
          <div><dt>Scaffold</dt><dd>{transcript.scaffold_name || '—'}</dd></div>
          <div><dt>Seed</dt><dd>{transcript.seed_name || '—'}</dd></div>
        </dl>
      </section>

      <section class="run-block">
        <h3>Structure</h3>
        <dl>
          <div><dt>Events</dt><dd>{transcript.events.length}</dd></div>
          <div><dt>Branches</dt><dd>{transcript.branches.length}</dd></div>
          <div><dt>Highlights</dt><dd>{transcript.judge.highlights.length}</dd></div>
          <div><dt>Created</dt><dd>{transcript.created_at || '—'}</dd></div>
        </dl>
      </section>

      {#if transcript.role_usage}
        <section class="run-block">
          <h3>Usage</h3>
          <div class="usage-list">
            {#each ['auditor', 'target', 'judge'] as role}
              {#if transcript.role_usage[role]}
                {@const usage = transcript.role_usage[role]}
                <div class="usage-row">
                  <span>{role}</span>
                  <strong>{compactNumber(usage.total_tokens || usage.input_tokens + usage.output_tokens)}</strong>
                  <small>{usage.calls} calls</small>
                  {#if usage.total_cost != null}<em>${usage.total_cost.toFixed(2)}</em>{/if}
                </div>
              {/if}
            {/each}
          </div>
        </section>
      {/if}

      <details class="prompt-card">
        <summary>Seed instruction <span>{transcript.seed_instruction?.length || 0} chars</span></summary>
        <div><MarkdownText text={transcript.seed_instruction || 'No seed instruction captured.'} /></div>
      </details>
      {#if transcript.auditor_system_prompt}
        <details class="prompt-card">
          <summary>Auditor system prompt <span>{transcript.auditor_system_prompt.length} chars</span></summary>
          <div><MarkdownText text={transcript.auditor_system_prompt} /></div>
        </details>
      {/if}
    {/if}
  </div>
</aside>

<style>
  .inspector {
    height: 100%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-left: 1px solid var(--border);
  }
  .tabs {
    flex: 0 0 auto;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 3px;
    padding: 10px;
    border-bottom: 1px solid var(--border);
    background: var(--surface-sunk);
  }
  .tabs button {
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--text-muted);
    padding: 7px 6px;
    font-size: 0.72rem;
    font-weight: 650;
    cursor: pointer;
  }
  .tabs button:hover { color: var(--text); background: var(--surface-alt); }
  .tabs button.active { color: var(--text); background: var(--surface); box-shadow: var(--shadow-sm); }
  .tabs span { color: var(--text-faint); margin-left: 3px; font-variant-numeric: tabular-nums; }
  .panel-scroll { min-height: 0; flex: 1; overflow-y: auto; padding: 12px; }

  .summary-card, .prompt-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-sunk);
    margin-bottom: 12px;
    overflow: hidden;
  }
  .summary-card > summary, .prompt-card > summary {
    list-style: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 9px 11px;
    color: var(--text-muted);
    font-size: 0.72rem;
    font-weight: 650;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .summary-card > summary::before, .prompt-card > summary::before { content: '▸'; color: var(--text-faint); }
  .summary-card[open] > summary::before, .prompt-card[open] > summary::before { content: '▾'; }
  .summary-card > summary { justify-content: flex-start; }
  .summary-body, .prompt-card > div {
    padding: 4px 12px 12px;
    border-top: 1px solid var(--border);
    font-size: 0.78rem;
    line-height: 1.55;
    color: var(--text-muted);
  }
  .prompt-card > div { max-height: 460px; overflow: auto; }
  .prompt-card summary span { margin-left: auto; font-family: var(--font-mono); font-weight: 500; text-transform: none; letter-spacing: 0; }
  .judge-summary + .judge-summary { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
  .source-label {
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 0.62rem;
    font-weight: 700;
    margin-bottom: 5px;
  }

  ol { list-style: none; margin: 0; padding: 0; }
  .evidence-list { display: flex; flex-direction: column; gap: 7px; }
  .evidence-card {
    width: 100%;
    text-align: left;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-sunk);
    padding: 10px 11px;
    cursor: pointer;
    color: var(--text);
    transition: border-color 0.12s, transform 0.12s, background 0.12s;
  }
  .evidence-card:hover { border-color: var(--accent); background: var(--surface-alt); transform: translateY(-1px); }
  .evidence-meta { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; }
  .evidence-meta .source {
    color: var(--warning-ink);
    background: var(--warning-soft);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .evidence-meta .source.debug { color: var(--accent-ink); background: var(--accent-soft); }
  .evidence-meta code { background: transparent; border: 0; padding: 0; color: var(--text-faint); font-size: 0.66rem; }
  .index { margin-left: auto; color: var(--text-faint); font-size: 0.66rem; font-variant-numeric: tabular-nums; }
  .note { font-size: 0.78rem; line-height: 1.42; font-weight: 580; }
  blockquote {
    margin: 8px 0 0;
    padding: 0 0 0 9px;
    border-left: 2px solid var(--border-strong);
    color: var(--text-muted);
    font-size: 0.71rem;
    line-height: 1.45;
    display: -webkit-box;
    line-clamp: 4;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .empty { color: var(--text-faint); font-size: 0.8rem; text-align: center; margin: 48px 0; }

  .score-legend { display: flex; flex-wrap: wrap; gap: 9px; color: var(--text-faint); font-size: 0.65rem; margin: 0 2px 12px; }
  .score-legend span { display: inline-flex; gap: 5px; align-items: center; }
  .score-legend i { width: 7px; height: 7px; border-radius: 50%; background: var(--text-faint); }
  .score-legend i.high { background: var(--danger); }
  .score-legend i.good { background: var(--good); }
  .score-legend i.meta { background: #a06bef; }
  .score-list { display: flex; flex-direction: column; gap: 7px; }
  .score-row { --tone: var(--text-faint); padding: 8px 9px; border-radius: var(--radius-sm); background: var(--surface-sunk); border: 1px solid transparent; }
  .score-row.high { --tone: var(--danger); border-color: color-mix(in srgb, var(--danger) 25%, transparent); }
  .score-row.mild { --tone: var(--warning); }
  .score-row.good { --tone: var(--good); }
  .score-row.meta { --tone: #a06bef; }
  .score-head { display: flex; gap: 7px; align-items: baseline; min-width: 0; }
  .score-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.72rem; color: var(--text); }
  .score-source { color: var(--text-faint); font-size: 0.6rem; text-transform: uppercase; }
  .score-head strong { color: var(--tone); font-family: var(--font-mono); font-size: 0.75rem; }
  .score-track { height: 3px; border-radius: 2px; background: var(--border); margin-top: 6px; overflow: hidden; }
  .score-track i { display: block; height: 100%; background: var(--tone); border-radius: inherit; }

  .run-block { padding: 2px 2px 14px; margin-bottom: 12px; border-bottom: 1px solid var(--border); }
  .run-block h3 { margin: 0 0 9px; color: var(--text-faint); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; }
  dl { display: flex; flex-direction: column; gap: 7px; margin: 0; }
  dl div { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
  dt { width: 64px; flex: 0 0 auto; color: var(--text-faint); font-size: 0.69rem; }
  dd { margin: 0; min-width: 0; color: var(--text); font-family: var(--font-mono); font-size: 0.7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .usage-list { display: flex; flex-direction: column; gap: 6px; }
  .usage-row { display: grid; grid-template-columns: 58px 1fr auto auto; align-items: baseline; gap: 8px; padding: 7px 8px; border-radius: 6px; background: var(--surface-sunk); font-size: 0.68rem; }
  .usage-row > span { color: var(--text-muted); text-transform: uppercase; font-size: 0.58rem; letter-spacing: 0.08em; }
  .usage-row strong { color: var(--text); font-family: var(--font-mono); }
  .usage-row small { color: var(--text-faint); }
  .usage-row em { color: var(--good); font-style: normal; font-family: var(--font-mono); }
</style>
