<script lang="ts">
  import type { Event, Highlight, ToolEvent } from './types';
  import Message from './Message.svelte';

  let {
    events,
    highlights = [],
    query = '',
    viewMode = 'flow',
  }: {
    events: Event[];
    highlights?: Highlight[];
    query?: string;
    viewMode?: 'flow' | 'evidence' | 'full';
  } = $props();

  const highlightedIds = $derived(new Set(highlights.map((h) => h.event_id).filter(Boolean)));

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

  function isFlowEvent(e: Event): boolean {
    if (e.role === 'user') return true;
    if (e.role === 'tool') return e.tool_name === 'query_target';
    if (e.role === 'system') return false;
    if (highlightedIds.has(e.id)) return true;
    if (e.tool_calls.some((tc) => ['send_message', 'reset_target', 'end_audit'].includes(tc.function))) return true;
    return e.tool_calls.length === 0 && !!e.content?.trim();
  }

  const evidenceIds = $derived.by(() => {
    const ids = new Set<string>(highlightedIds);
    for (let i = 0; i < events.length; i++) {
      if (!highlightedIds.has(events[i].id)) continue;
      const branch = events[i].branch;
      for (let j = Math.max(0, i - 4); j <= Math.min(events.length - 1, i + 1); j++) {
        const candidate = events[j];
        if (candidate.branch !== branch) continue;
        if (candidate.role === 'tool' && candidate.tool_name === 'query_target') ids.add(candidate.id);
        if (candidate.role === 'assistant' && candidate.tool_calls.some((tc) => tc.function === 'send_message')) ids.add(candidate.id);
        if (candidate.id === events[i].id) ids.add(candidate.id);
      }
    }
    return ids;
  });

  // Visible events + the branches they belong to. Search intentionally spans
  // the full trace, regardless of the active reader mode.
  const filtered = $derived.by(() => {
    const q = query.trim();
    if (q) return events.filter((e) => eventMatchesQuery(e, q));
    if (viewMode === 'full') return events;
    if (viewMode === 'evidence') return events.filter((e) => evidenceIds.has(e.id));
    return events.filter(isFlowEvent);
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
  {#if !filterActive && viewMode !== 'full'}
    <div class="mode-info">
      {#if viewMode === 'flow'}
        Reader mode hides setup and verification noise. <strong>{filtered.length}</strong> of {events.length} events shown.
      {:else}
        Evidence mode shows cited events with nearby auditor context. <strong>{filtered.length}</strong> of {events.length} events shown.
      {/if}
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
  .mode-info {
    margin: 10px 0 14px;
    padding: 8px 11px;
    color: var(--text-faint);
    background: var(--surface-sunk);
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    font-size: 0.7rem;
  }
  .mode-info strong { color: var(--text-muted); font-variant-numeric: tabular-nums; }
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
