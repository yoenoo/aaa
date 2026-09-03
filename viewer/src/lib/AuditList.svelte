<script lang="ts">
  import type { AuditIndexEntry } from './types';

  let { onOpen }: { onOpen: (id: string) => void } = $props();

  let entries = $state<AuditIndexEntry[]>([]);
  let error = $state<string | null>(null);
  let loaded = $state(false);
  let query = $state('');
  let seedSort = $state<'concern' | 'runs' | 'name'>('concern');
  let expanded = $state<Set<string>>(new Set());

  (async () => {
    try {
      const res = await fetch('/data/index.json');
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      entries = (await res.json()) as AuditIndexEntry[];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  })();

  // Concerning dimensions only: exclude positive (higher=better) and the
  // auditor/target quality dimensions, so the score reflects misalignment.
  const POSITIVE = new Set([
    'transparent_disagreement', 'genuine_honesty', 'legitimate_escalation', 'scenario_realism',
  ]);
  function isConcerning(name: string): boolean {
    return !POSITIVE.has(name) && !name.startsWith('auditor_') && !name.startsWith('target_');
  }
  function concernOf(e: AuditIndexEntry): number {
    let m = 0;
    for (const [n, v] of Object.entries(e.scores || {})) if (isConcerning(n) && v > m) m = v;
    return m;
  }
  function topDims(e: AuditIndexEntry, k = 3): [string, number][] {
    return Object.entries(e.scores || {})
      .filter(([n, v]) => isConcerning(n) && v >= 6)
      .sort((a, b) => b[1] - a[1])
      .slice(0, k);
  }
  function shortModel(m: string): string { return (m || '').split('/').pop() || m; }

  type Run = AuditIndexEntry & { concern: number };
  type Group = {
    seed: string; runs: Run[]; peak: number;
    high: number; mild: number; low: number; flagged: number;
    targets: string[]; avgRealism: number | null; totalHl: number;
  };

  const filtered = $derived.by<AuditIndexEntry[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) =>
      e.id.toLowerCase().includes(q) || e.title.toLowerCase().includes(q) ||
      e.seed_name.toLowerCase().includes(q) || e.scaffold_name.toLowerCase().includes(q) ||
      e.auditor_model.toLowerCase().includes(q) || e.target_model.toLowerCase().includes(q));
  });

  const groups = $derived.by<Group[]>(() => {
    const map = new Map<string, Run[]>();
    for (const e of filtered) {
      const s = e.seed_name || 'unknown';
      (map.get(s) || map.set(s, []).get(s)!).push({ ...e, concern: concernOf(e) });
    }
    const out: Group[] = [];
    for (const [seed, runs] of map) {
      runs.sort((a, b) => b.concern - a.concern || (b.created_at || '').localeCompare(a.created_at || ''));
      const realisms = runs.map((r) => (r.scores || {}).scenario_realism).filter((v): v is number => v != null);
      out.push({
        seed, runs,
        peak: Math.max(0, ...runs.map((r) => r.concern)),
        high: runs.filter((r) => r.concern >= 7).length,
        mild: runs.filter((r) => r.concern >= 4 && r.concern < 7).length,
        low: runs.filter((r) => r.concern < 4).length,
        flagged: runs.filter((r) => r.concern >= 6).length,
        targets: [...new Set(runs.map((r) => shortModel(r.target_model)))],
        avgRealism: realisms.length ? realisms.reduce((a, b) => a + b, 0) / realisms.length : null,
        totalHl: runs.reduce((n, r) => n + (r.highlight_count || 0), 0),
      });
    }
    out.sort((a, b) =>
      seedSort === 'name' ? a.seed.localeCompare(b.seed)
      : seedSort === 'runs' ? b.runs.length - a.runs.length
      : b.peak - a.peak || b.flagged - a.flagged);
    return out;
  });

  const totalConcerning = $derived(entries.filter((e) => concernOf(e) >= 6).length);

  function fmtDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }
  function sev(v: number): 'high' | 'mild' | 'low' {
    return v >= 7 ? 'high' : v >= 4 ? 'mild' : 'low';
  }
  function toggle(seed: string) {
    const next = new Set(expanded);
    next.has(seed) ? next.delete(seed) : next.add(seed);
    expanded = next;
  }
  function setAll(open: boolean) {
    expanded = open ? new Set(groups.map((g) => g.seed)) : new Set();
  }
</script>

<main class="audit-list">
  <div class="wrap">
  <header>
    <div class="brand">
      <span class="glyph" aria-hidden="true">
        <svg viewBox="0 0 32 32"><rect width="32" height="32" rx="7.4" fill="#161c17"/><rect x="8.6" y="7" width="4" height="18" rx="2" fill="#8fb9cf"/><rect x="19.4" y="7" width="4" height="18" rx="2" fill="#d9ad66"/><circle cx="16" cy="16" r="1.95" fill="#ec7fb2"/></svg>
      </span>
      Loupe · Audits
    </div>
    <h1>Audit transcripts</h1>
    <p class="lede">{entries.length} audits across {groups.length} seeds · {totalConcerning} with concerning behavior (misalignment ≥&nbsp;6).<br>Grouped by scenario — open a seed to see its runs, or a run to read the transcript.</p>
  </header>

  <div class="controls">
    <label class="search">
      <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      <input type="search" placeholder="Filter by seed, model, scaffold, id…" bind:value={query} spellcheck="false" />
    </label>
    <div class="seg">
      <span class="k">sort seeds</span>
      <select bind:value={seedSort}>
        <option value="concern">by peak concern</option>
        <option value="runs">by run count</option>
        <option value="name">by name</option>
      </select>
    </div>
    <button class="ghost" onclick={() => setAll(false)}>expand all</button>
    <button class="ghost" onclick={() => setAll(true)}>collapse all</button>
  </div>

  {#if error}
    <div class="state">
      <p class="err">Failed to load index: <code>{error}</code></p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> from the repo root to backfill.</p>
    </div>
  {:else if !loaded}
    <div class="state"><div class="spinner"></div><p>Loading…</p></div>
  {:else if !entries.length}
    <div class="state">
      <p>No audits dumped yet.</p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> to build the index from <code>logs/*.eval</code>.</p>
    </div>
  {:else if !groups.length}
    <div class="state"><p>No audits match “{query}”.</p></div>
  {:else}
    <div class="seeds">
      {#each groups as g (g.seed)}
        {@const open = expanded.has(g.seed)}
        <section class="group" class:open>
          <button class="ghead" onclick={() => toggle(g.seed)} aria-expanded={open}>
            <span class="chev" class:open>▸</span>
            <span class="seedname">{g.seed}</span>
            <span class="runcount">{g.runs.length} run{g.runs.length === 1 ? '' : 's'}</span>

            <span class="dist" title="{g.high} concerning · {g.mild} mild · {g.low} aligned">
              {#if g.high}<span class="seg-high" style="flex:{g.high}"></span>{/if}
              {#if g.mild}<span class="seg-mild" style="flex:{g.mild}"></span>{/if}
              {#if g.low}<span class="seg-low" style="flex:{g.low}"></span>{/if}
            </span>

            <span class="gstat"><b class="sev-{sev(g.peak)}">{g.peak}</b><i>peak</i></span>
            <span class="gstat"><b class:flag={g.flagged > 0}>{g.flagged}</b><i>flagged</i></span>
            {#if g.avgRealism != null}<span class="gstat"><b>{g.avgRealism.toFixed(1)}</b><i>realism</i></span>{/if}

            <span class="targets">{#each g.targets.slice(0, 4) as t (t)}<span class="tchip">{t}</span>{/each}{#if g.targets.length > 4}<span class="tmore">+{g.targets.length - 4}</span>{/if}</span>
          </button>

          {#if open}
            <ul class="runs">
              {#each g.runs as r (r.id)}
                <li>
                  <button class="run" onclick={() => onOpen(r.id)}>
                    <span class="rscore sev-{sev(r.concern)}" title="peak concerning dimension">{r.concern}</span>
                    <span class="rmain">
                      <span class="rtarget">{shortModel(r.target_model)}</span>
                      <span class="rdims">
                        {#each topDims(r) as [name, v] (name)}<span class="rdim sev-{sev(v)}">{name.replace(/_/g, ' ')} {v}</span>{/each}
                        {#if !topDims(r).length}<span class="rdim clean">no concerning behavior</span>{/if}
                      </span>
                    </span>
                    <span class="rmeta">{r.branch_count}&nbsp;br · {r.highlight_count}&nbsp;hl · {r.event_count}&nbsp;ev</span>
                    <span class="rdate">{fmtDate(r.created_at)}</span>
                    <span class="rarrow">→</span>
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/each}
    </div>
  {/if}
  </div>
</main>

<style>
  .audit-list {
    --bg: #121613; --surface: #191f1a; --surface-alt: #212822; --surface-sunk: #10150f;
    --border: #2b332c; --border-strong: #4c574e;
    --text: #dfe5dd; --text-muted: #8d978e; --text-faint: #6e7b6e;
    --aud: #8fb9cf; --tgt: #d9ad66; --hl: #e874ac; --hl-bg: #3a1628; --hl-ink: #f090bd;
    --high: #e5686b; --mild: #d6a63c; --low: #6cc191;
    --font-serif: ui-serif, 'Iowan Old Style', 'Palatino Linotype', Charter, Georgia, serif;
    --font-mono: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace;
    --font-sans: system-ui, 'Segoe UI', -apple-system, sans-serif;
    min-height: 100vh; background: var(--bg); color: var(--text);
    font-family: var(--font-sans);
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 44px 28px 80px; }
  :global(:root[data-theme='light']) .audit-list {
    --bg: #eef0ea; --surface: #f8f9f5; --surface-alt: #e9ece5; --surface-sunk: #e4e7df;
    --border: #d3d9d0; --border-strong: #a7b1a6;
    --text: #20261f; --text-muted: #6b756c; --text-faint: #8a938a;
    --aud: #2e5568; --tgt: #8a5b1d; --hl: #a91e60; --hl-bg: #f6dfe9; --hl-ink: #8c1750;
    --high: #c0392b; --mild: #a6791e; --low: #2f7d55;
  }

  .brand { display: inline-flex; align-items: center; gap: 9px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }
  .glyph { width: 22px; height: 22px; } .glyph svg { width: 100%; height: 100%; display: block; }
  h1 { font-family: var(--font-serif); font-size: 30px; font-weight: 600; letter-spacing: -0.015em; margin: 12px 0 8px; }
  .lede { color: var(--text-muted); max-width: 74ch; font-size: 14.5px; line-height: 1.55; margin: 0; }

  .controls { display: flex; align-items: center; gap: 12px; margin: 28px 0 20px; flex-wrap: wrap; }
  .search { flex: 1; min-width: 260px; display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; color: var(--text-faint); }
  .search:focus-within { border-color: var(--aud); }
  .search svg { width: 15px; height: 15px; flex: none; }
  .search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; font-size: 13.5px; }
  .seg { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); }
  .seg .k { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); }
  .seg select { font: inherit; font-size: 12.5px; padding: 6px 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; color: var(--text); cursor: pointer; }
  .ghost { font: inherit; font-size: 12px; color: var(--text-muted); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px 11px; cursor: pointer; }
  .ghost:hover { color: var(--text); border-color: var(--border-strong); }

  .state { max-width: 560px; margin: 90px auto; text-align: center; color: var(--text-muted); }
  .err { color: var(--high); font-weight: 500; }
  .hint { font-size: 13px; margin-top: 8px; }
  .state code, .hint code { font-family: var(--font-mono); font-size: 0.86em; background: var(--surface-alt); padding: 1px 5px; border-radius: 4px; border: 1px solid var(--border); }
  .spinner { width: 20px; height: 20px; margin: 0 auto 12px; border: 2px solid var(--border); border-top-color: var(--aud); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .seeds { display: flex; flex-direction: column; gap: 12px; }
  .group { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); overflow: hidden; }
  .group.open { border-color: var(--border-strong); }

  .ghead { display: flex; align-items: center; gap: 14px; width: 100%; text-align: left; background: transparent; border: 0; cursor: pointer; font: inherit; color: var(--text); padding: 14px 18px; }
  .ghead:hover { background: var(--surface-alt); }
  .chev { color: var(--text-faint); font-size: 11px; transition: transform 0.15s; flex: none; }
  .chev.open { transform: rotate(90deg); }
  .seedname { font-family: var(--font-serif); font-size: 16.5px; font-weight: 600; letter-spacing: -0.01em; white-space: nowrap; }
  .runcount { font-family: var(--font-mono); font-size: 11.5px; color: var(--text-muted); flex: none; }
  .dist { display: flex; gap: 2px; height: 7px; flex: 1; min-width: 60px; max-width: 200px; border-radius: 4px; overflow: hidden; background: var(--surface-sunk); }
  .dist > span { display: block; }
  .seg-high { background: var(--high); } .seg-mild { background: var(--mild); } .seg-low { background: var(--low); }
  .gstat { display: flex; flex-direction: column; align-items: center; line-height: 1.05; flex: none; min-width: 42px; }
  .gstat b { font-family: var(--font-mono); font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .gstat b.flag { color: var(--hl-ink); }
  .gstat i { font-style: normal; font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-faint); margin-top: 2px; }
  .targets { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; margin-left: auto; max-width: 300px; }
  .tchip { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); background: var(--surface-sunk); border: 1px solid var(--border); border-radius: 5px; padding: 2px 6px; white-space: nowrap; }
  .tmore { font-family: var(--font-mono); font-size: 10px; color: var(--text-faint); align-self: center; }

  .runs { list-style: none; margin: 0; padding: 0 8px 8px; border-top: 1px solid var(--border); }
  .run { display: flex; align-items: center; gap: 14px; width: 100%; text-align: left; background: transparent; border: 0; border-radius: 8px; cursor: pointer; font: inherit; color: var(--text); padding: 9px 10px; }
  .run:hover { background: var(--surface-alt); }
  .run:focus-visible { outline: 2px solid var(--aud); outline-offset: -2px; }
  .rscore { flex: none; width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; font-family: var(--font-mono); font-weight: 700; font-size: 14px; font-variant-numeric: tabular-nums; }
  .rmain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .rtarget { font-size: 13.5px; font-weight: 550; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .rdims { display: flex; gap: 5px; flex-wrap: wrap; }
  .rdim { font-family: var(--font-mono); font-size: 10px; border-radius: 5px; padding: 1px 6px; white-space: nowrap; }
  .rdim.clean { color: var(--text-faint); border: 1px solid var(--border); }
  .rmeta { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); white-space: nowrap; flex: none; }
  .rdate { font-family: var(--font-mono); font-size: 11px; color: var(--text-faint); white-space: nowrap; flex: none; min-width: 78px; text-align: right; }
  .rarrow { color: var(--text-faint); flex: none; }
  .run:hover .rarrow { color: var(--aud); }

  /* severity color for scores + dim chips */
  .sev-high { background: color-mix(in srgb, var(--high) 15%, transparent); color: var(--high); }
  .sev-mild { background: color-mix(in srgb, var(--mild) 15%, transparent); color: var(--mild); }
  .sev-low { background: color-mix(in srgb, var(--low) 14%, transparent); color: var(--low); }
  b.sev-high { background: none; color: var(--high); } b.sev-mild { background: none; color: var(--mild); } b.sev-low { background: none; color: var(--low); }

  @media (max-width: 820px) {
    .targets, .gstat i { display: none; }
    .rmeta { display: none; }
    .dist { max-width: 120px; }
  }
  @media (max-width: 560px) {
    .rdate, .dist { display: none; }
    .ghead { flex-wrap: wrap; gap: 8px 12px; }
  }
</style>
