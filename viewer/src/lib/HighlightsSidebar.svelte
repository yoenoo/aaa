<script lang="ts">
  import type { Highlight } from './types';

  let { highlights }: { highlights: Highlight[] } = $props();

  function findTarget(h: Highlight): HTMLElement | null {
    const container = document.getElementById(h.event_id);
    if (!container) return null;
    if (!h.quoted_text) return container;

    // Ensure any collapsed <details> containing the quote is opened so the
    // mark is laid out and scrollable.
    const marks = Array.from(container.querySelectorAll<HTMLElement>('mark'));
    let picked: HTMLElement | null = null;
    for (const m of marks) {
      if (m.textContent === h.quoted_text) { picked = m; break; }
    }
    if (!picked) {
      for (const m of marks) {
        const t = m.textContent ?? '';
        if (t.includes(h.quoted_text) || h.quoted_text.includes(t)) { picked = m; break; }
      }
    }
    if (picked) {
      for (let p = picked.parentElement; p && p !== container; p = p.parentElement) {
        if (p.tagName === 'DETAILS' && !(p as HTMLDetailsElement).open) {
          (p as HTMLDetailsElement).open = true;
        }
      }
      return picked;
    }
    return container;
  }

  function jump(h: Highlight) {
    const el = findTarget(h);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('hl-flash');
    void el.offsetWidth;
    el.classList.add('hl-flash');
    setTimeout(() => el.classList.remove('hl-flash'), 1400);
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
          <button class="card" onclick={() => jump(h)}>
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
  :global(.hl-flash) {
    animation: hl-flash-kf 1.4s ease-out;
    scroll-margin-top: 80px;
  }
  :global(mark.hl-flash) {
    outline: 2px solid rgba(180, 83, 9, 0.9);
    outline-offset: 2px;
    border-radius: 2px;
  }
  @keyframes hl-flash-kf {
    0%   { box-shadow: 0 0 0 3px rgba(180, 83, 9, 0.55); }
    60%  { box-shadow: 0 0 0 6px rgba(180, 83, 9, 0.10); }
    100% { box-shadow: 0 0 0 0 rgba(180, 83, 9, 0); }
  }
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
