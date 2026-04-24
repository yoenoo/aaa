<script lang="ts">
  import type { Event, Branch, Highlight } from './types';

  let {
    events,
    branches,
    highlights = [],
  }: { events: Event[]; branches: Branch[]; highlights?: Highlight[] } = $props();

  const highlightedIds = $derived(new Set(highlights.map((h) => h.event_id).filter(Boolean)));

  function roleDot(role: Event['role']): string {
    // ch = single-character role marker
    if (role === 'system') return 'S';
    if (role === 'user') return 'U';
    if (role === 'assistant') return 'A';
    return 'T';
  }

  function label(e: Event): string {
    if (e.role === 'system') return 'system prompt';
    if (e.role === 'user') return e.content?.slice(0, 60) || '';
    if (e.role === 'assistant') {
      if (e.tool_calls?.length) {
        const names = e.tool_calls.map((t) => t.function).join(', ');
        return names.length > 50 ? names.slice(0, 50) + '…' : names;
      }
      return (e.content || '').slice(0, 60);
    }
    // tool
    return e.tool_name || 'tool';
  }

  function fmtDur(s: number | null | undefined): string {
    if (s == null || s === 0) return '';
    if (s < 1) return `${Math.round(s * 1000)}ms`;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    return `${m}m${Math.round(s - m * 60)}s`;
  }

  function jumpTo(id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }

  // active event tracking — watch scroll, find the event closest to a
  // reference line near the top of the viewport.
  let activeId = $state<string | null>(null);
  let rafPending = false;

  function updateActive() {
    rafPending = false;
    const refY = 140;
    let best: string | null = null;
    let bestDist = Infinity;
    for (const e of events) {
      const el = document.getElementById(e.id);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      // only consider events at or above the reference line
      if (r.top > refY + 40) continue;
      const dist = Math.abs(r.top - refY);
      if (dist < bestDist) {
        bestDist = dist;
        best = e.id;
      }
    }
    activeId = best;
  }

  function onScroll() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(updateActive);
  }

  $effect(() => {
    window.addEventListener('scroll', onScroll, { passive: true });
    updateActive();
    return () => window.removeEventListener('scroll', onScroll);
  });

  const byBranch = $derived.by(() => {
    const groups: { branch: Branch; events: Event[] }[] = [];
    const branchByIdx = new Map<number, Branch>();
    for (const b of branches) branchByIdx.set(b.index, b);
    let current: { branch: Branch; events: Event[] } | null = null;
    for (const e of events) {
      const b = branchByIdx.get(e.branch);
      if (!b) continue;
      if (!current || current.branch.index !== b.index) {
        current = { branch: b, events: [] };
        groups.push(current);
      }
      current.events.push(e);
    }
    return groups;
  });
</script>

<aside class="tree">
  <div class="tree-head">
    <h3>Timeline</h3>
    <span class="count">{events.length}</span>
  </div>
  <ol class="branches">
    {#each byBranch as group (group.branch.index)}
      <li class="branch">
        <button class="branch-header" onclick={() => jumpTo(group.events[0].id)}>
          <span class="commit-marker">◆</span>
          <span class="branch-name">{group.branch.label}</span>
          <span class="branch-meta">
            {group.branch.event_count ?? group.events.length}
            {#if group.branch.duration_s != null && group.branch.duration_s > 0}
              · {fmtDur(group.branch.duration_s)}
            {/if}
          </span>
        </button>
        <ol class="events">
          {#each group.events as e (e.id)}
            <li class="event role-{e.role}" class:active={activeId === e.id} class:highlighted={highlightedIds.has(e.id)}>
              <button class="event-btn" onclick={() => jumpTo(e.id)} title={label(e)}>
                <span class="rail" aria-hidden="true">
                  <span class="dot"></span>
                </span>
                <span class="role-ch">{roleDot(e.role)}</span>
                <span class="e-label">{label(e)}</span>
                <span class="e-right">
                  {#if highlightedIds.has(e.id)}<span class="hl">★</span>{/if}
                  {#if e.duration_s != null && e.duration_s > 0}<span class="dur">{fmtDur(e.duration_s)}</span>{/if}
                </span>
              </button>
            </li>
          {/each}
        </ol>
      </li>
    {/each}
  </ol>
</aside>

<style>
  .tree {
    position: sticky;
    top: 80px;
    max-height: calc(100vh - 100px);
    overflow-y: auto;
    padding: 4px 4px 16px 0;
    font-size: 0.78rem;
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .tree::-webkit-scrollbar { width: 0; height: 0; }
  .tree-head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
  }
  .tree-head h3 {
    font-size: 0.72rem;
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 600;
    color: var(--text-muted);
  }
  .count {
    font-size: 0.7rem;
    color: var(--text-faint);
    font-variant-numeric: tabular-nums;
  }

  ol { list-style: none; padding: 0; margin: 0; }
  .branches { display: flex; flex-direction: column; gap: 6px; }

  .branch-header {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 6px 8px;
    background: transparent;
    border: none;
    cursor: pointer;
    font: inherit;
    text-align: left;
    color: var(--text);
    border-radius: var(--radius-sm);
    transition: background 0.12s;
  }
  .branch-header:hover { background: var(--surface-alt); }
  .commit-marker {
    color: var(--text-muted);
    font-size: 0.7rem;
    flex-shrink: 0;
  }
  .branch-name {
    font-weight: 600;
    font-size: 0.78rem;
    color: var(--text);
    flex: 1;
    min-width: 0;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .branch-meta {
    font-size: 0.7rem;
    color: var(--text-faint);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
  }

  .events {
    display: flex;
    flex-direction: column;
  }

  .event { position: relative; }
  .event-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 3px 6px 3px 0;
    background: transparent;
    border: none;
    cursor: pointer;
    font: inherit;
    text-align: left;
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    transition: background 0.12s, color 0.12s;
  }
  .event-btn:hover { background: var(--surface-alt); color: var(--text); }

  .rail {
    position: relative;
    flex-shrink: 0;
    width: 18px;
    align-self: stretch;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .rail::before {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    left: 50%;
    width: 1px;
    background: var(--border);
    transform: translateX(-0.5px);
  }
  .dot {
    position: relative;
    z-index: 1;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--surface);
    border: 1.5px solid var(--border-strong);
    box-shadow: 0 0 0 2px var(--bg);
  }
  .event.role-user .dot { border-color: var(--user); }
  .event.role-assistant .dot { border-color: var(--auditor); }
  .event.role-tool .dot { border-color: var(--target); }
  .event.role-system .dot { border-color: var(--text-faint); }

  .role-ch {
    font-size: 0.6rem;
    font-family: var(--font-mono);
    color: var(--text-faint);
    font-weight: 700;
    width: 10px;
    flex-shrink: 0;
    letter-spacing: 0;
  }
  .e-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.78rem;
  }
  .e-right {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .dur {
    font-size: 0.66rem;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
  }
  .hl {
    font-size: 0.7rem;
    color: var(--warning);
  }

  .event.highlighted .e-label { color: var(--text); }
  .event.highlighted .dot {
    background: var(--warning);
    border-color: var(--warning);
  }

  .event.active .event-btn {
    background: var(--accent-soft);
    color: var(--text);
  }
  .event.active .e-label { font-weight: 600; }
  .event.active .dot {
    background: var(--accent);
    border-color: var(--accent);
  }
</style>
