<script lang="ts">
  import type { Event, Highlight, ToolEvent } from './types';
  import Message from './Message.svelte';

  let {
    events,
    highlights = [],
    query = '',
  }: { events: Event[]; highlights?: Highlight[]; query?: string } = $props();

  const highlightsByEventId = $derived.by(() => {
    const map: Record<string, Highlight[]> = {};
    for (const h of highlights) {
      if (!h.event_id) continue;
      (map[h.event_id] ??= []).push(h);
    }
    return map;
  });

  const resultsByCallId = $derived.by(() => {
    const map: Record<string, ToolEvent> = {};
    for (const e of events) {
      if (e.role === 'tool' && e.tool_call_id) map[e.tool_call_id] = e;
    }
    return map;
  });

  function eventMatchesQuery(e: Event, q: string): boolean {
    if (!q) return true;
    const needle = q.toLowerCase();
    if (e.role === 'assistant' && e.content?.toLowerCase().includes(needle)) return true;
    if (e.role !== 'assistant' && 'content' in e && e.content?.toLowerCase().includes(needle)) return true;
    if (e.role === 'assistant') {
      for (const tc of e.tool_calls) {
        if (tc.function.toLowerCase().includes(needle)) return true;
        if (JSON.stringify(tc.arguments).toLowerCase().includes(needle)) return true;
      }
      if (e.reasoning?.toLowerCase().includes(needle)) return true;
    }
    if (e.role === 'tool') {
      if (e.tool_name?.toLowerCase().includes(needle)) return true;
      if (e.error?.message?.toLowerCase().includes(needle)) return true;
    }
    return false;
  }

  // Visible events + the branches they belong to.
  const filtered = $derived.by(() => {
    const q = query.trim();
    if (!q) return events;
    return events.filter((e) => eventMatchesQuery(e, q));
  });

  const byBranch = $derived.by(() => {
    const groups: { branch: number; events: Event[] }[] = [];
    for (const e of filtered) {
      const last = groups[groups.length - 1];
      if (!last || last.branch !== e.branch) {
        groups.push({ branch: e.branch, events: [e] });
      } else {
        last.events.push(e);
      }
    }
    return groups;
  });

  const filterActive = $derived(!!query.trim());
</script>

<div class="transcript">
  {#if filterActive}
    <div class="filter-info">
      Showing <strong>{filtered.length}</strong> of {events.length} events matching
      <code>{query}</code>
    </div>
  {/if}
  {#if filtered.length === 0 && filterActive}
    <div class="empty">No events match that query.</div>
  {/if}
  {#each byBranch as group (group.branch)}
    <div class="branch-divider" id="branch-{group.branch}">
      <span class="line"></span>
      <span class="label">Branch {group.branch}</span>
      <span class="line"></span>
    </div>
    {#each group.events as e (e.id)}
      <Message event={e} {resultsByCallId} highlights={highlightsByEventId[e.id] ?? []} />
    {/each}
  {/each}
</div>

<style>
  .transcript { margin-top: 8px; }
  .filter-info {
    margin: 8px 0 4px;
    padding: 7px 12px;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  .filter-info strong { color: var(--text); font-variant-numeric: tabular-nums; font-weight: 600; }
  .empty {
    margin: 16px 0;
    padding: 20px;
    text-align: center;
    color: var(--text-faint);
    font-size: 0.85rem;
  }
  .branch-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 28px 0 14px;
    scroll-margin-top: 80px;
  }
  .branch-divider .line {
    flex: 1;
    height: 1px;
    background: var(--border);
  }
  .branch-divider .label {
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-muted);
    background: var(--bg);
    padding: 2px 12px;
    font-weight: 600;
  }
</style>
