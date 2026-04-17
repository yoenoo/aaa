<script lang="ts">
  import type { Highlight } from './types';

  let { highlights }: { highlights: Highlight[] } = $props();

  function jump(eventId: string) {
    const el = document.getElementById(eventId);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }
</script>

<aside class="sidebar">
  <div class="header">
    <h3>Judge Highlights</h3>
    <span class="count">{highlights.length}</span>
  </div>
  {#if highlights.length === 0}
    <p class="empty">No highlights.</p>
  {:else}
    <ol>
      {#each highlights as h, i (i)}
        <li>
          <button class="card" onclick={() => jump(h.event_id)}>
            <div class="top">
              <span class="idx">#{i + 1}</span>
              <span class="anchor">{h.event_id}</span>
            </div>
            <div class="note">{h.note}</div>
            <blockquote>{h.quoted_text}</blockquote>
          </button>
        </li>
      {/each}
    </ol>
  {/if}
</aside>

<style>
  .sidebar {
    position: sticky;
    top: 80px;
    max-height: calc(100vh - 100px);
    overflow-y: auto;
    padding: 4px 4px 16px 4px;
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .sidebar::-webkit-scrollbar { width: 0; height: 0; }
  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
  }
  h3 {
    font-size: 0.72rem;
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 600;
    color: var(--text-muted);
  }
  .count {
    background: var(--warning-soft);
    color: var(--warning-ink);
    font-size: 0.7rem;
    padding: 1px 8px;
    border-radius: 4px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .empty {
    color: var(--text-faint);
    font-size: 0.85rem;
    font-style: italic;
  }
  ol {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .card {
    display: block;
    width: 100%;
    text-align: left;
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 2px solid var(--warning);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    cursor: pointer;
    font: inherit;
    transition: background 0.12s, border-color 0.12s;
  }
  .card:hover {
    background: var(--warning-soft);
    border-color: var(--border-strong);
    border-left-color: var(--warning);
  }
  .top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .idx {
    font-size: 0.66rem;
    font-weight: 600;
    color: var(--warning-ink);
    font-variant-numeric: tabular-nums;
  }
  .anchor {
    font-size: 0.66rem;
    color: var(--text-faint);
    font-family: var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .note {
    font-size: 0.8rem;
    color: var(--text);
    font-weight: 500;
    line-height: 1.45;
    margin-bottom: 6px;
  }
  blockquote {
    margin: 0;
    padding-left: 10px;
    border-left: 2px solid var(--border-strong);
    color: var(--text-muted);
    font-size: 0.76rem;
    line-height: 1.5;
    max-height: 4.6em;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
