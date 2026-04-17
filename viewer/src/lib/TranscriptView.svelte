<script lang="ts">
  import type { TranscriptData } from './types';
  import Transcript from './Transcript.svelte';
  import BranchNav from './BranchNav.svelte';
  import BranchTree from './BranchTree.svelte';
  import HighlightsSidebar from './HighlightsSidebar.svelte';
  import MarkdownText from './MarkdownText.svelte';
  import { setExpandContext } from './expandContext';

  let { logId, onBack }: { logId: string; onBack?: () => void } = $props();

  let transcript = $state<TranscriptData | null>(null);
  let error = $state<string | null>(null);
  let expandMode = $state<'expanded' | 'collapsed' | 'auto'>('auto');
  let searchQuery = $state('');
  let branchNavRef: { focusSearch: () => void } | null = $state(null);

  setExpandContext({
    get value() { return expandMode; },
  });

  const RATES: Record<string, { in: number; out: number; cached_in?: number }> = {
    'openai/gpt-5': { in: 1.25, out: 10.0, cached_in: 0.125 },
    'openai/gpt-5-mini': { in: 0.25, out: 2.0, cached_in: 0.025 },
    'anthropic/claude-opus-4-5': { in: 15.0, out: 75.0, cached_in: 1.5 },
    'anthropic/claude-opus-4-7': { in: 15.0, out: 75.0, cached_in: 1.5 },
    'anthropic/claude-sonnet-4-6': { in: 3.0, out: 15.0, cached_in: 0.3 },
  };

  function estimateCost(model: string, u: { input_tokens?: number; input_tokens_cache_read?: number; output_tokens?: number }): number | null {
    const r = RATES[model];
    if (!r) return null;
    const fresh = Math.max(0, (u.input_tokens ?? 0) - (u.input_tokens_cache_read ?? 0));
    const cached = u.input_tokens_cache_read ?? 0;
    const out = u.output_tokens ?? 0;
    return (
      (fresh * r.in) / 1_000_000 +
      (cached * (r.cached_in ?? r.in)) / 1_000_000 +
      (out * r.out) / 1_000_000
    );
  }

  const roleOrder = ['auditor', 'target', 'judge'] as const;
  const roleAccent: Record<string, string> = {
    auditor: 'var(--auditor)',
    target: 'var(--target)',
    judge: 'var(--warning)',
  };

  function fmtTokens(n: number | null | undefined): string {
    if (n == null) return '—';
    if (n < 1_000) return n.toString();
    if (n < 1_000_000) return `${(n / 1_000).toFixed(n < 10_000 ? 1 : 0)}K`;
    return `${(n / 1_000_000).toFixed(2)}M`;
  }

  function fmtCost(c: number | null): string {
    if (c == null) return '—';
    if (c < 0.01) return `<$0.01`;
    return `$${c.toFixed(2)}`;
  }

  function onKeydown(e: KeyboardEvent) {
    const tag = (e.target as HTMLElement | null)?.tagName ?? '';
    const editable = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement | null)?.isContentEditable;
    if (e.key === 'Escape' && editable) {
      (e.target as HTMLElement).blur();
      return;
    }
    if (editable) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === '/') {
      e.preventDefault();
      branchNavRef?.focusSearch();
      return;
    }
    if (!transcript) return;

    if (e.key === 'j' || e.key === 'k') {
      e.preventDefault();
      navigateEvent(e.key === 'j' ? 1 : -1);
      return;
    }
    if (e.key === '[' || e.key === ']') {
      e.preventDefault();
      navigateBranch(e.key === ']' ? 1 : -1);
      return;
    }
  }

  function visibleEventIds(): string[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.msg[id]'))
      .filter((el) => el.offsetParent !== null)
      .map((el) => el.id);
  }

  function findCenterEvent(ids: string[]): number {
    const y = window.innerHeight / 2;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < ids.length; i++) {
      const el = document.getElementById(ids[i]);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const dist = Math.abs(r.top + r.height / 2 - y);
      if (dist < bestDist) { bestDist = dist; best = i; }
    }
    return best;
  }

  function navigateEvent(dir: 1 | -1) {
    const ids = visibleEventIds();
    if (ids.length === 0) return;
    const cur = findCenterEvent(ids);
    const next = Math.max(0, Math.min(ids.length - 1, cur + dir));
    document.getElementById(ids[next])?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function navigateBranch(dir: 1 | -1) {
    if (!transcript) return;
    const current = document.querySelectorAll<HTMLElement>('.branch-divider');
    if (current.length === 0) return;
    const y = 100;
    let idx = 0;
    for (let i = 0; i < current.length; i++) {
      const r = current[i].getBoundingClientRect();
      if (r.top <= y) idx = i;
    }
    const next = Math.max(0, Math.min(current.length - 1, idx + dir));
    current[next].scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $effect(() => {
    const id = logId;
    transcript = null;
    error = null;
    (async () => {
      try {
        const res = await fetch(`/data/${encodeURIComponent(id)}.json`);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = (await res.json()) as TranscriptData;
        if (logId === id) transcript = data;
      } catch (e) {
        if (logId === id) error = (e as Error).message;
      }
    })();
  });

  function scoreColor(v: number): string {
    if (v >= 7) return 'var(--danger)';
    if (v >= 4) return 'var(--warning)';
    return 'var(--user)';
  }

  interface Finding { dimension: string; score: number; text: string; }

  // Parse paragraphs of the shape:
  //   "dim_name (N): text"
  //   "- dim_name (N): text"
  //   "**Dim Name (N/10)**: text"
  //   "dim_a (N) / dim_b (N): text"         (shared text, one Finding per dimension)
  //   "dim_name: N/10 — text"               (score after colon, em-dash body)
  //   "dim_name: N/10 - text"               (ASCII hyphen variant)
  //   "dim_a, dim_b: N/10 — text"           (comma-listed dims with shared score)
  // Lines like "All other dimensions: 1/10. …" stay in leftover.
  function parseFindings(summary: string): { findings: Finding[]; leftover: string } {
    if (!summary) return { findings: [], leftover: '' };
    const parenHead = /\b([A-Za-z][A-Za-z0-9_ \-\/]*?)\s*\((\d+)(?:\s*\/\s*10)?\)/g;
    // head ("dim" or "dim_a / dim_b" or "dim_a, dim_b"): N/10 [em-dash|hyphen] body
    const postColon = /^([A-Za-z][A-Za-z0-9_ ]*(?:\s*[\/,]\s*[A-Za-z][A-Za-z0-9_ ]*)*)\s*:\s*(\d+)\s*\/\s*10\s*[—–\-]\s+(.+)$/s;
    const findings: Finding[] = [];
    const leftoverParts: string[] = [];

    for (const raw of summary.split(/\n\s*\n/)) {
      const para = raw.trim();
      if (!para) continue;
      const stripped = para.replace(/^\s*[-*]\s+/, '').replace(/^\*+|\*+$/g, '');

      // catch-all "all other ..." / "remaining ..." lines — keep as prose
      if (/^\s*(all other|other dimensions|remaining)/i.test(stripped)) {
        leftoverParts.push(para);
        continue;
      }

      // shape: "dim: N/10 — text"
      const pm = postColon.exec(stripped);
      if (pm) {
        const score = parseInt(pm[2], 10);
        const body = pm[3].trim();
        for (const name of pm[1].split(/[\/,]/).map((s) => s.trim().replace(/\*+/g, '')).filter(Boolean)) {
          findings.push({ dimension: name, score, text: body });
        }
        continue;
      }

      // shape: "dim (N): text" / "dim_a (N) / dim_b (N): text"
      const colon = stripped.indexOf(':');
      if (colon < 0) { leftoverParts.push(para); continue; }
      const head = stripped.slice(0, colon);
      const body = stripped.slice(colon + 1).trim();
      const dims: { name: string; score: number }[] = [];
      parenHead.lastIndex = 0;
      let hm: RegExpExecArray | null;
      while ((hm = parenHead.exec(head)) !== null) {
        const name = hm[1].trim().replace(/\*+/g, '');
        if (!name) continue;
        dims.push({ name, score: parseInt(hm[2], 10) });
      }
      if (dims.length === 0 || !body) { leftoverParts.push(para); continue; }
      for (const d of dims) findings.push({ dimension: d.name, score: d.score, text: body });
    }
    return { findings: findings.sort((a, b) => b.score - a.score), leftover: leftoverParts.join('\n\n') };
  }

  const parsed = $derived(parseFindings(transcript?.judge.summary || ''));
  const findings = $derived(parsed.findings);
  const leftoverSummary = $derived(parsed.leftover);
  const notable = $derived(findings.filter(f => f.score > 1));
  const quiet = $derived(findings.filter(f => f.score <= 1));

  function fmtDuration(s: number | null | undefined): string {
    if (s == null) return '';
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const rem = Math.round(s - m * 60);
    if (m < 60) return `${m}m ${rem.toString().padStart(2, '0')}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${(m - h * 60).toString().padStart(2, '0')}m`;
  }
</script>

<main>
  {#if error}
    <div class="state">
      <p class="error">Failed to load transcript: <code>{error}</code></p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> to backfill, or launch an audit — the post-task hook dumps automatically.</p>
      {#if onBack}<button class="back-btn" onclick={onBack}>← Back to all audits</button>{/if}
    </div>
  {:else if !transcript}
    <div class="state"><p class="loading">Loading transcript…</p></div>
  {:else}
    <header>
      <div class="brand-row">
        {#if onBack}
          <button class="back-link" onclick={onBack} title="Back to all audits">← all audits</button>
        {/if}
        <div class="brand">Petri · Audit</div>
      </div>
      <h1>{transcript.title}</h1>
      <div class="meta">
        <span><span class="k">auditor</span><code>{transcript.auditor_model}</code></span>
        <span><span class="k">target</span><code>{transcript.target_model}</code></span>
        <span><span class="k">scaffold</span><code>{transcript.scaffold_name}</code></span>
        <span><span class="k">seed</span><code>{transcript.seed_name}</code></span>
        {#if transcript.total_time_s != null}
          <span class="total-time" title="Total audit wall-clock time">
            <span class="k">duration</span><code>{fmtDuration(transcript.total_time_s)}</code>
          </span>
        {/if}
      </div>
    </header>

    <section class="kpis">
      {#each Object.entries(transcript.judge.scores) as [name, value]}
        <div class="kpi" title={transcript.judge.score_descriptions[name] ?? ''}>
          <div class="kpi-name">{name}</div>
          <div class="kpi-val">{value.toFixed(1)}</div>
          <div class="kpi-bar">
            <div class="kpi-fill" style="width: {Math.min(100, value * 10)}%; background: {scoreColor(value)};"></div>
          </div>
        </div>
      {/each}
    </section>

    <section class="verdict">
      <div class="verdict-head">
        <span class="verdict-eyebrow">Judge Verdict</span>
        <span class="verdict-meta">{findings.length || Object.keys(transcript.judge.scores).length} dimensions · {transcript.judge.highlights.length} highlights</span>
      </div>

      {#if findings.length === 0}
        <div class="verdict-fallback"><MarkdownText text={transcript.judge.summary} /></div>
      {:else}
        {#if notable.length}
          <ul class="findings">
            {#each notable as f (f.dimension)}
              <li class="finding" style="--sev: {scoreColor(f.score)}">
                <div class="score">{f.score}</div>
                <div class="f-body">
                  <div class="f-dim">{f.dimension}</div>
                  <div class="f-text">{f.text}</div>
                </div>
              </li>
            {/each}
          </ul>
        {/if}

        {#if quiet.length}
          <details class="quiet" open={notable.length === 0}>
            <summary>
              <span class="q-count">{quiet.length}</span>
              <span>dimensions with no notable findings</span>
              <span class="q-chev">▸</span>
            </summary>
            <ul class="findings">
              {#each quiet as f (f.dimension)}
                <li class="finding" style="--sev: {scoreColor(f.score)}">
                  <div class="score">{f.score}</div>
                  <div class="f-body">
                    <div class="f-dim">{f.dimension}</div>
                    <div class="f-text">{f.text}</div>
                  </div>
                </li>
              {/each}
            </ul>
          </details>
        {/if}

        {#if leftoverSummary}
          <div class="verdict-leftover"><MarkdownText text={leftoverSummary} /></div>
        {/if}
      {/if}
    </section>

    <details class="section">
      <summary>Seed Instruction</summary>
      <div class="seed-body"><MarkdownText text={transcript.seed_instruction} /></div>
    </details>

    {#if transcript.auditor_system_prompt}
      <details class="section">
        <summary>Auditor System Prompt</summary>
        <div class="seed-body"><MarkdownText text={transcript.auditor_system_prompt} /></div>
      </details>
    {/if}

    <section class="transcript-section">
      <div class="t-head">
        <h2>Transcript</h2>
        <p class="muted">
          <span>{transcript.events.length} events</span>
          <span class="dot">·</span>
          <span>{transcript.branches.length} branches</span>
          <span class="dot">·</span>
          <span>{transcript.judge.highlights.length} highlights</span>
        </p>
      </div>
      <BranchNav bind:this={branchNavRef} branches={transcript.branches} bind:expandMode bind:searchQuery />
      <div class="transcript-layout">
        <div class="tree-col">
          <BranchTree
            events={transcript.events}
            branches={transcript.branches}
            highlights={transcript.judge.highlights}
          />
        </div>
        <div class="transcript-col">
          <Transcript
            events={transcript.events}
            highlights={transcript.judge.highlights}
            query={searchQuery}
          />
        </div>
        <div class="sidebar-col">
          <HighlightsSidebar highlights={transcript.judge.highlights} />
        </div>
      </div>

      {#if transcript.role_usage}
        <footer class="usage">
          <div class="usage-title">Token usage by role</div>
          <div class="role-grid">
            {#each roleOrder as role}
              {#if transcript.role_usage[role]}
                {@const u = transcript.role_usage[role]}
                <div class="role-card" style="--role-accent: {roleAccent[role]}">
                  <div class="rc-head">
                    <span class="rc-role">{role}</span>
                    <code class="rc-model">{u.model || '—'}</code>
                  </div>
                  {#if u.calls === 0 && u.input_tokens === 0}
                    <div class="rc-empty">not tracked</div>
                  {:else}
                    <div class="rc-cost">{fmtCost(u.total_cost ?? estimateCost(u.model, u))}</div>
                    <div class="rc-stats">
                      <div><span class="k">input</span><span class="v">{fmtTokens(u.input_tokens)}</span></div>
                      <div><span class="k">cached</span><span class="v">{fmtTokens(u.input_tokens_cache_read)}</span></div>
                      <div><span class="k">output</span><span class="v">{fmtTokens(u.output_tokens)}</span></div>
                      {#if u.reasoning_tokens > 0}
                        <div><span class="k">reasoning</span><span class="v">{fmtTokens(u.reasoning_tokens)}</span></div>
                      {/if}
                      <div><span class="k">calls</span><span class="v">{u.calls}</span></div>
                    </div>
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
          <div class="usage-foot">
            Cost is an estimate using hardcoded per-model rates. Judge tokens
            aren't tracked in <code>log.stats</code> by inspect_ai — what you
            see here is a best-effort residual.
          </div>
        </footer>
      {/if}
    </section>
  {/if}
</main>

<svelte:window onkeydown={onKeydown} />

<style>
  main {
    max-width: none;
    margin: 0;
    padding: 28px 28px 56px;
  }
  .state {
    max-width: 560px;
    margin: 96px auto;
    text-align: center;
  }
  .loading { color: var(--text-muted); }
  .error { color: var(--danger); font-weight: 500; }
  .hint { color: var(--text-muted); font-size: 0.9rem; margin-top: 8px; }
  .back-btn {
    margin-top: 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font: inherit;
    color: var(--text);
  }
  .back-btn:hover { border-color: var(--border-strong); }

  header {
    padding-bottom: 20px;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--border);
  }
  .brand-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }
  .back-link {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    font-size: 0.72rem;
    color: var(--text-muted);
    text-transform: lowercase;
    letter-spacing: 0.06em;
  }
  .back-link:hover { color: var(--text); }
  .brand {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--text-muted);
    font-weight: 600;
  }
  header h1 {
    margin: 0 0 14px;
    font-size: 1.6rem;
    line-height: 1.25;
    letter-spacing: -0.02em;
  }
  .meta {
    display: flex;
    gap: 22px;
    font-size: 0.82rem;
    color: var(--text-muted);
    flex-wrap: wrap;
    align-items: center;
  }
  .meta > span { display: inline-flex; align-items: center; gap: 6px; }
  .meta .k {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.66rem;
    color: var(--text-faint);
    font-weight: 500;
  }
  .meta code {
    background: transparent;
    border: none;
    padding: 0;
    font-size: 0.8rem;
    color: var(--text);
    font-weight: 500;
  }

  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 8px;
    margin: 20px 0 16px;
  }
  .kpi {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    transition: border-color 0.12s;
  }
  .kpi:hover { border-color: var(--border-strong); }
  .kpi-name {
    font-size: 0.68rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .kpi-val {
    font-size: 1.7rem;
    font-weight: 600;
    margin-top: 6px;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.025em;
    color: var(--text);
  }
  .kpi-bar {
    height: 2px;
    background: var(--surface-alt);
    border-radius: 1px;
    margin-top: 10px;
    overflow: hidden;
  }
  .kpi-fill {
    height: 100%;
    border-radius: 1px;
    transition: width 0.4s ease;
  }

  .section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 18px;
    margin: 10px 0;
  }
  .section summary {
    cursor: pointer;
    font-weight: 500;
    font-size: 0.86rem;
    color: var(--text);
    list-style: none;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section summary::before {
    content: '';
    width: 0;
    height: 0;
    border-left: 4px solid var(--text-faint);
    border-top: 3px solid transparent;
    border-bottom: 3px solid transparent;
    transition: transform 0.15s;
  }
  .section[open] summary::before { transform: rotate(90deg); }
  .verdict {
    margin: 16px 0;
    padding: 18px 22px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .verdict-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
  }
  .verdict-eyebrow {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-muted);
    font-weight: 600;
  }
  .verdict-meta {
    font-size: 0.72rem;
    color: var(--text-faint);
    font-variant-numeric: tabular-nums;
  }

  .findings {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
  }
  .finding {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 16px;
    padding: 12px 0;
    border-bottom: 1px solid var(--surface-alt);
    align-items: start;
  }
  .finding:last-child { border-bottom: none; }
  .score {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--sev) 10%, transparent);
    color: var(--sev);
    border: 1px solid color-mix(in srgb, var(--sev) 30%, transparent);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }
  .f-body {
    min-width: 0;
    padding-top: 2px;
  }
  .f-dim {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text);
    margin-bottom: 4px;
  }
  .f-text {
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--text-muted);
  }

  .quiet {
    margin-top: 10px;
    border-top: 1px solid var(--border);
    padding-top: 10px;
  }
  .quiet > summary {
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 2px;
    font-size: 0.78rem;
    color: var(--text-muted);
  }
  .quiet > summary::-webkit-details-marker { display: none; }
  .q-count {
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .q-chev {
    margin-left: auto;
    font-size: 0.7rem;
    color: var(--text-faint);
    transition: transform 0.15s;
  }
  .quiet[open] .q-chev { transform: rotate(90deg); }
  .quiet[open] > summary { margin-bottom: 6px; }

  .verdict-fallback {
    font-size: 0.95rem;
    line-height: 1.7;
    color: var(--text);
  }
  .verdict-leftover {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px dashed var(--border);
    font-size: 0.85rem;
    line-height: 1.6;
    color: var(--text-muted);
  }
  .seed-body {
    margin-top: 12px;
    max-height: 460px;
    overflow: auto;
    padding: 12px 14px;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 0.86rem;
    line-height: 1.55;
  }
  .total-time code { color: var(--text); font-weight: 600; }

  .transcript-section { margin-top: 32px; }
  .t-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 14px;
    margin-bottom: 6px;
  }
  .t-head h2 {
    margin: 0;
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    font-weight: 600;
  }
  .muted {
    color: var(--text-faint);
    font-size: 0.78rem;
    margin: 0;
    display: flex;
    gap: 8px;
    font-variant-numeric: tabular-nums;
  }
  .muted .dot { color: var(--border-strong); }

  .transcript-layout {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr) 320px;
    gap: 24px;
  }
  .transcript-col { min-width: 0; }
  .tree-col { min-width: 0; }
  @media (max-width: 1280px) {
    .transcript-layout { grid-template-columns: 240px minmax(0, 1fr); }
    .sidebar-col { display: none; }
  }
  @media (max-width: 960px) {
    .transcript-layout { grid-template-columns: 1fr; }
    .tree-col, .sidebar-col { display: none; }
  }

  .usage {
    margin-top: 40px;
    padding: 18px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .usage-title {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 12px;
  }
  .role-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 10px;
  }
  .role-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-sunk);
    padding: 12px 14px;
    transition: border-color 0.12s;
  }
  .role-card:hover { border-color: var(--border-strong); }
  .rc-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 4px;
  }
  .rc-role {
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--role-accent);
    font-weight: 700;
  }
  .rc-model code {
    font-size: 0.7rem;
    background: transparent;
    border: none;
    color: var(--text-faint);
    padding: 0;
  }
  .rc-cost {
    font-size: 1.35rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    margin: 8px 0 10px;
    letter-spacing: -0.025em;
  }
  .rc-empty {
    font-size: 0.78rem;
    color: var(--text-faint);
    font-style: italic;
    margin: 8px 0 4px;
  }
  .rc-stats {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 3px 12px;
    font-size: 0.76rem;
  }
  .rc-stats div { display: flex; justify-content: space-between; gap: 6px; }
  .rc-stats .k { color: var(--text-faint); }
  .rc-stats .v { font-variant-numeric: tabular-nums; color: var(--text); }
  .usage-foot {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    font-size: 0.72rem;
    color: var(--text-faint);
  }
  .usage-foot code { font-size: 0.7rem; background: transparent; border: none; padding: 0; color: var(--text-muted); }
</style>
