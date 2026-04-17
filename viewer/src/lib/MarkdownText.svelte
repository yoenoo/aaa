<script lang="ts">
  import { Marked } from 'marked';
  import { markedHighlight } from 'marked-highlight';
  import hljs from 'highlight.js/lib/common';
  import 'highlight.js/styles/github-dark.css';

  let { text, quotes = [] }: { text: string; quotes?: string[] } = $props();

  const md = new Marked(
    { breaks: true, gfm: true },
    markedHighlight({
      langPrefix: 'hljs language-',
      highlight(code: string, lang: string) {
        try {
          if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
          }
          return hljs.highlightAuto(code).value;
        } catch {
          return code;
        }
      },
    }),
  );

  // Insert literal <mark>…</mark> tokens around every occurrence of a quoted
  // string, then hand the result to marked. marked passes raw HTML through,
  // so highlights survive markdown rendering for the common case where the
  // quoted span doesn't straddle markdown syntax.
  const html = $derived.by(() => {
    const src = text ?? '';
    if (!src) return '';
    if (quotes.length === 0) return md.parse(src) as string;

    const ranges: [number, number][] = [];
    for (const q of quotes) {
      if (!q) continue;
      let from = 0;
      while (from < src.length) {
        const idx = src.indexOf(q, from);
        if (idx === -1) break;
        ranges.push([idx, idx + q.length]);
        from = idx + q.length;
      }
    }
    if (ranges.length === 0) return md.parse(src) as string;

    ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const merged: [number, number][] = [];
    for (const [s, e] of ranges) {
      const last = merged[merged.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else merged.push([s, e]);
    }

    let out = '';
    let cursor = 0;
    for (const [s, e] of merged) {
      out += src.slice(cursor, s);
      out += '<mark>' + src.slice(s, e) + '</mark>';
      cursor = e;
    }
    out += src.slice(cursor);
    return md.parse(out) as string;
  });
</script>

<div class="md">{@html html}</div>

<style>
  .md :global(p) { margin: 0 0 0.7em; }
  .md :global(p:last-child) { margin-bottom: 0; }
  .md :global(ul), .md :global(ol) { margin: 0 0 0.7em; padding-left: 1.4em; }
  .md :global(li) { margin: 0.15em 0; }
  .md :global(h1), .md :global(h2), .md :global(h3), .md :global(h4) {
    margin: 0.9em 0 0.4em;
    font-weight: 600;
    line-height: 1.3;
  }
  .md :global(h1) { font-size: 1.15rem; }
  .md :global(h2) { font-size: 1.05rem; }
  .md :global(h3) { font-size: 0.98rem; }
  .md :global(h4) { font-size: 0.92rem; color: var(--text-muted); }
  .md :global(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .md :global(a:hover) { text-decoration-thickness: 2px; }
  .md :global(blockquote) {
    margin: 0.5em 0;
    padding: 4px 12px;
    border-left: 3px solid var(--border-strong);
    color: var(--text-muted);
    background: var(--surface-alt);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  }
  .md :global(code) {
    font-family: var(--font-mono);
    font-size: 0.86em;
    background: var(--surface-alt);
    padding: 1px 5px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }
  .md :global(pre) {
    margin: 0.6em 0;
    padding: 12px 14px;
    background: #1e1e24;
    color: #e4e4e7;
    border-radius: var(--radius-sm);
    overflow-x: auto;
    font-size: 0.82rem;
    line-height: 1.55;
  }
  .md :global(pre code) {
    background: transparent;
    border: none;
    padding: 0;
    color: inherit;
    font-size: inherit;
  }
  .md :global(strong) { font-weight: 600; }
  .md :global(em) { font-style: italic; }
  .md :global(hr) {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1em 0;
  }
  .md :global(table) {
    border-collapse: collapse;
    margin: 0.6em 0;
    font-size: 0.88em;
  }
  .md :global(th), .md :global(td) {
    border: 1px solid var(--border);
    padding: 4px 10px;
    text-align: left;
  }
  .md :global(th) { background: var(--surface-alt); font-weight: 600; }
  .md :global(mark) {
    background: linear-gradient(180deg, transparent 0%, transparent 30%, #fde68a 30%, #fde68a 100%);
    color: inherit;
    padding: 0 2px;
    border-radius: 2px;
    box-decoration-break: clone;
    -webkit-box-decoration-break: clone;
  }
</style>
