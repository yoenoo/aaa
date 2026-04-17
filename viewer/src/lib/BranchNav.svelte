<script lang="ts">
  import type { Branch } from './types';

  let {
    branches,
    expandMode = $bindable('auto'),
    searchQuery = $bindable(''),
  }: {
    branches: Branch[];
    expandMode?: 'expanded' | 'collapsed' | 'auto';
    searchQuery?: string;
  } = $props();

  function jumpTo(index: number) {
    const el = document.getElementById(`branch-${index}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function cycle() {
    expandMode = expandMode === 'auto' ? 'expanded' : expandMode === 'expanded' ? 'collapsed' : 'auto';
  }

  function fmtDur(s: number | null | undefined): string {
    if (s == null) return '';
    if (s < 60) return `${s.toFixed(0)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s - m * 60)}s`;
  }

  let searchInput: HTMLInputElement | undefined = $state();
  export function focusSearch() {
    searchInput?.focus();
    searchInput?.select();
  }
</script>

<nav class="branch-nav">
  <div class="branches">
    <span class="nav-label">Branches</span>
    {#each branches as b (b.index)}
      <button class="branch-btn" onclick={() => jumpTo(b.index)} title="{b.event_count ?? 0} events · {fmtDur(b.duration_s)}">
        <span class="b-label">{b.label}</span>
        {#if b.event_count != null}<span class="stat">{b.event_count}</span>{/if}
        {#if b.duration_s != null && b.duration_s > 0}<span class="stat muted">{fmtDur(b.duration_s)}</span>{/if}
        {#if b.highlight_count}<span class="stat highlight">★ {b.highlight_count}</span>{/if}
      </button>
    {/each}
  </div>
  <div class="search-wrap">
    <input
      bind:this={searchInput}
      bind:value={searchQuery}
      type="text"
      placeholder="Search…  (/)"
      class="search"
      spellcheck="false"
    />
    {#if searchQuery}
      <button class="clear" onclick={() => (searchQuery = '')} title="Clear">×</button>
    {/if}
  </div>
  <button class="expand-toggle" onclick={cycle} title="Cycle tool-call expansion">
    <span class="t-label">tools</span>
    <span class="t-value">{expandMode}</span>
  </button>
</nav>

<style>
  .branch-nav {
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(248, 250, 252, 0.88);
    backdrop-filter: saturate(180%) blur(10px);
    -webkit-backdrop-filter: saturate(180%) blur(10px);
    border-bottom: 1px solid var(--border);
    padding: 10px 28px;
    margin: 12px -28px 16px;
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 0.85rem;
  }
  .nav-label {
    color: var(--text-faint);
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 600;
  }
  .branches {
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
  }
  .branch-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 4px 10px;
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--text);
    cursor: pointer;
    transition: border-color 0.12s, background 0.12s;
  }
  .branch-btn:hover {
    background: var(--surface-alt);
    border-color: var(--border-strong);
  }
  .branch-btn:active { background: var(--surface-sunk); }
  .b-label { font-weight: 600; color: var(--text); }
  .stat {
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    color: var(--text-muted);
  }
  .stat.muted { color: var(--text-faint); }
  .stat.highlight {
    color: var(--warning-ink);
    background: var(--warning-soft);
    padding: 1px 6px;
    border-radius: 3px;
  }

  .search-wrap {
    position: relative;
    flex: 1;
    max-width: 280px;
    min-width: 140px;
  }
  .search {
    width: 100%;
    padding: 6px 26px 6px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.82rem;
    outline: none;
    transition: border-color 0.12s, box-shadow 0.12s;
  }
  .search:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
  }
  .search::placeholder { color: var(--text-faint); }
  .clear {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    background: transparent;
    border: none;
    color: var(--text-faint);
    cursor: pointer;
    font-size: 1rem;
    padding: 2px 6px;
    line-height: 1;
  }
  .clear:hover { color: var(--text); }
  .expand-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 5px 10px;
    font-size: 0.78rem;
    cursor: pointer;
    transition: border-color 0.12s;
  }
  .expand-toggle:hover { border-color: var(--border-strong); }
  .t-label {
    color: var(--text-faint);
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
  }
  .t-value {
    font-weight: 500;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
</style>
