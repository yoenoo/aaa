<script lang="ts">
  let { text, quotes = [] }: { text: string; quotes?: string[] } = $props();

  type Segment = { kind: 'plain' | 'mark'; text: string };

  const segments = $derived.by<Segment[]>(() => {
    if (!text || quotes.length === 0) return [{ kind: 'plain', text: text ?? '' }];

    const ranges: [number, number][] = [];
    for (const q of quotes) {
      if (!q) continue;
      let from = 0;
      while (from < text.length) {
        const idx = text.indexOf(q, from);
        if (idx === -1) break;
        ranges.push([idx, idx + q.length]);
        from = idx + q.length;
      }
    }
    if (ranges.length === 0) return [{ kind: 'plain', text }];

    ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const merged: [number, number][] = [];
    for (const [s, e] of ranges) {
      const last = merged[merged.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else merged.push([s, e]);
    }

    const out: Segment[] = [];
    let cursor = 0;
    for (const [s, e] of merged) {
      if (cursor < s) out.push({ kind: 'plain', text: text.slice(cursor, s) });
      out.push({ kind: 'mark', text: text.slice(s, e) });
      cursor = e;
    }
    if (cursor < text.length) out.push({ kind: 'plain', text: text.slice(cursor) });
    return out;
  });
</script>

{#each segments as seg, i (i)}
  {#if seg.kind === 'mark'}<mark>{seg.text}</mark>{:else}{seg.text}{/if}
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
