<script lang="ts">
  import type { AuditIndexEntry } from './types';

  let { onOpen }: { onOpen: (id: string) => void } = $props();

  let entries = $state<AuditIndexEntry[]>([]);
  let error = $state<string | null>(null);
  let loaded = $state(false);
  let query = $state('');
  let sort = $state<'newest' | 'score' | 'duration' | 'scaffold'>('newest');

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

  const filtered = $derived.by<AuditIndexEntry[]>(() => {
    const q = query.trim().toLowerCase();
    let list = entries;
    if (q) {
      list = list.filter((e) =>
        e.id.toLowerCase().includes(q) ||
        e.title.toLowerCase().includes(q) ||
        e.seed_name.toLowerCase().includes(q) ||
        e.scaffold_name.toLowerCase().includes(q) ||
        e.auditor_model.toLowerCase().includes(q) ||
        e.target_model.toLowerCase().includes(q),
      );
    }
    const sorted = [...list];
    if (sort === 'newest') sorted.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    else if (sort === 'score') sorted.sort((a, b) => (b.top_score ?? -1) - (a.top_score ?? -1));
    else if (sort === 'duration') sorted.sort((a, b) => (b.total_time_s ?? 0) - (a.total_time_s ?? 0));
    else if (sort === 'scaffold') sorted.sort((a, b) => (a.scaffold_name || '').localeCompare(b.scaffold_name || ''));
    return sorted;
  });

  function fmtDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function fmtDuration(s: number | null | undefined): string {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const rem = Math.round(s - m * 60);
    if (m < 60) return `${m}m ${rem.toString().padStart(2, '0')}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${(m - h * 60).toString().padStart(2, '0')}m`;
  }

  function scoreColor(v: number): string {
    if (v >= 7) return 'var(--danger)';
    if (v >= 4) return 'var(--warning)';
    return 'var(--user)';
  }
</script>

<main>
  <header>
    <div class="brand">Petri · Audits</div>
    <h1>All audits</h1>
    <p class="lede">Every completed audit dumped by the viewer hook. Click one to open its transcript.</p>
  </header>

  <div class="controls">
    <input
      type="search"
      placeholder="Filter by id, seed, model, scaffold…"
      bind:value={query}
      class="search"
    />
    <div class="sort">
      <span class="k">sort</span>
      <select bind:value={sort}>
        <option value="newest">newest</option>
        <option value="score">highest judge score</option>
        <option value="duration">longest duration</option>
        <option value="scaffold">scaffold</option>
      </select>
    </div>
    <span class="count">{filtered.length} / {entries.length}</span>
  </div>

  {#if error}
    <div class="state">
      <p class="error">Failed to load index: <code>{error}</code></p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> from the repo root to backfill.</p>
    </div>
  {:else if !loaded}
    <div class="state"><p class="loading">Loading…</p></div>
  {:else if entries.length === 0}
    <div class="state">
      <p class="loading">No audits dumped yet.</p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> to build the index from <code>logs/*.eval</code>.</p>
    </div>
  {:else if filtered.length === 0}
    <div class="state"><p class="loading">No audits match this filter.</p></div>
  {:else}
    <ul class="grid">
      {#each filtered as e (e.id)}
        <li>
          <button class="card" onclick={() => onOpen(e.id)}>
            <div class="card-head">
              <div class="title-block">
                <div class="title">{e.title}</div>
                <div class="subtitle">{e.seed_name || '—'}</div>
              </div>
              {#if e.top_score != null}
                <div class="score" style="--sev: {scoreColor(e.top_score)}" title="highest judge score">
                  {e.top_score.toFixed(1)}
                </div>
              {/if}
            </div>

            <dl class="kv">
              <div><dt>auditor</dt><dd><code>{e.auditor_model}</code></dd></div>
              <div><dt>target</dt><dd><code>{e.target_model}</code></dd></div>
              <div><dt>scaffold</dt><dd>{e.scaffold_name || '—'}</dd></div>
            </dl>

            {#if Object.keys(e.scores || {}).length}
              <div class="scores">
                {#each Object.entries(e.scores) as [name, value]}
                  <div class="s-chip" style="--sev: {scoreColor(value)}" title={name}>
                    <span class="s-name">{name}</span>
                    <span class="s-val">{value.toFixed(1)}</span>
                  </div>
                {/each}
              </div>
            {/if}

            <footer class="card-foot">
              <span class="stat">{e.event_count} events</span>
              <span class="sep">·</span>
              <span class="stat">{e.branch_count} branches</span>
              <span class="sep">·</span>
              <span class="stat">{e.highlight_count} highlights</span>
              <span class="spacer"></span>
              <span class="stat" title="total duration">{fmtDuration(e.total_time_s)}</span>
              <span class="sep">·</span>
              <span class="stat date" title={e.created_at}>{fmtDate(e.created_at)}</span>
            </footer>
            <div class="id-row"><code>{e.id}</code></div>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  main {
    max-width: 1200px;
    margin: 0 auto;
    padding: 40px 28px 56px;
  }
  header {
    margin-bottom: 28px;
  }
  .brand {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 10px;
  }
  h1 {
    margin: 0 0 6px;
    font-size: 1.7rem;
    letter-spacing: -0.02em;
  }
  .lede {
    color: var(--text-muted);
    margin: 0;
    font-size: 0.9rem;
  }

  .controls {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: 20px 0 18px;
    flex-wrap: wrap;
  }
  .search {
    flex: 1;
    min-width: 240px;
    padding: 8px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font: inherit;
    font-size: 0.88rem;
    color: var(--text);
  }
  .search:focus { outline: none; border-color: var(--auditor); }
  .sort {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.78rem;
    color: var(--text-muted);
  }
  .sort .k { text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.66rem; color: var(--text-faint); }
  .sort select {
    font: inherit;
    font-size: 0.82rem;
    padding: 5px 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    cursor: pointer;
  }
  .count {
    font-size: 0.78rem;
    color: var(--text-faint);
    font-variant-numeric: tabular-nums;
  }

  .state {
    max-width: 560px;
    margin: 80px auto;
    text-align: center;
  }
  .loading { color: var(--text-muted); }
  .error { color: var(--danger); font-weight: 500; }
  .hint { color: var(--text-muted); font-size: 0.9rem; margin-top: 8px; }

  .grid {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 14px;
  }

  .card {
    display: block;
    width: 100%;
    text-align: left;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
    cursor: pointer;
    font: inherit;
    color: inherit;
    transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s;
  }
  .card:hover {
    border-color: var(--border-strong);
    box-shadow: var(--shadow-sm);
    transform: translateY(-1px);
  }
  .card:focus-visible {
    outline: 2px solid var(--auditor);
    outline-offset: 2px;
  }
  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 12px;
  }
  .title-block { min-width: 0; }
  .title {
    font-size: 1.02rem;
    font-weight: 600;
    color: var(--text);
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .subtitle {
    font-family: var(--font-mono);
    font-size: 0.74rem;
    color: var(--text-muted);
    margin-top: 3px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .score {
    flex-shrink: 0;
    min-width: 44px;
    height: 44px;
    padding: 0 10px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--sev) 12%, transparent);
    color: var(--sev);
    border: 1px solid color-mix(in srgb, var(--sev) 30%, transparent);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    font-size: 1.1rem;
    letter-spacing: -0.02em;
  }

  .kv {
    margin: 0 0 12px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px 16px;
    font-size: 0.78rem;
  }
  .kv > div { display: flex; gap: 6px; min-width: 0; }
  .kv dt {
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.64rem;
    flex-shrink: 0;
    align-self: center;
    font-weight: 600;
  }
  .kv dd {
    margin: 0;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .kv code {
    background: transparent;
    padding: 0;
    border: none;
    font-size: 0.76rem;
    color: var(--text);
  }

  .scores {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 12px;
  }
  .s-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px 2px 6px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--sev) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--sev) 28%, transparent);
    font-size: 0.7rem;
  }
  .s-name {
    color: var(--text-muted);
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .s-val {
    color: var(--sev);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .card-foot {
    display: flex;
    align-items: center;
    gap: 6px;
    padding-top: 10px;
    border-top: 1px solid var(--surface-alt);
    font-size: 0.72rem;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
    flex-wrap: wrap;
  }
  .card-foot .sep { color: var(--border-strong); }
  .card-foot .spacer { flex: 1; }
  .card-foot .date { color: var(--text-faint); }

  .id-row {
    margin-top: 8px;
    font-size: 0.66rem;
    color: var(--text-faint);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .id-row code {
    background: transparent;
    padding: 0;
    border: none;
    font-size: 0.66rem;
    color: var(--text-faint);
  }
</style>
