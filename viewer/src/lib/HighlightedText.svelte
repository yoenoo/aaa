<script lang="ts">
  let { text, quotes = [], debugQuotes = [] }: { text: string; quotes?: string[]; debugQuotes?: string[] } = $props();

  type Segment = { kind: 'plain' | 'mark' | 'mark-debug'; text: string };

  const segments = $derived.by<Segment[]>(() => {
    if (!text || (quotes.length === 0 && debugQuotes.length === 0)) return [{ kind: 'plain', text: text ?? '' }];

    const ranges: { s: number; e: number; debug: boolean }[] = [];
    const collect = (list: string[], debug: boolean) => {
      for (const q of list) {
        if (!q) continue;
        let from = 0;
        while (from < text.length) {
          const idx = text.indexOf(q, from);
          if (idx === -1) break;
          ranges.push({ s: idx, e: idx + q.length, debug });
          from = idx + q.length;
        }
      }
    };
    collect(quotes, false);
    collect(debugQuotes, true);
    if (ranges.length === 0) return [{ kind: 'plain', text }];

    ranges.sort((a, b) => a.s - b.s || a.e - b.e);
    const merged: { s: number; e: number; debug: boolean }[] = [];
    for (const r of ranges) {
      const last = merged[merged.length - 1];
      if (last && r.s <= last.e) { last.e = Math.max(last.e, r.e); last.debug = last.debug && r.debug; }
      else merged.push({ ...r });
    }

    const out: Segment[] = [];
    let cursor = 0;
    for (const { s, e, debug } of merged) {
      if (cursor < s) out.push({ kind: 'plain', text: text.slice(cursor, s) });
      out.push({ kind: debug ? 'mark-debug' : 'mark', text: text.slice(s, e) });
      cursor = e;
    }
    if (cursor < text.length) out.push({ kind: 'plain', text: text.slice(cursor) });
    return out;
  });
</script>

{#each segments as seg, i (i)}
  {#if seg.kind === 'mark'}<mark>{seg.text}</mark>{:else if seg.kind === 'mark-debug'}<mark class="hl-debug">{seg.text}</mark>{:else}{seg.text}{/if}
{/each}

<style>
  mark {
    background: linear-gradient(180deg, transparent 0%, transparent 30%, #fde68a 30%, #fde68a 100%);
    color: inherit;
    padding: 0 2px;
    border-radius: 2px;
    box-decoration-break: clone;
    -webkit-box-decoration-break: clone;
  }
</style>
