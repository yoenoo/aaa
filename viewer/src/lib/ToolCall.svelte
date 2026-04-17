<script lang="ts">
  import type { ToolCall, ToolEvent } from './types';
  import { getExpandContext } from './expandContext';

  let { call, result }: { call: ToolCall; result?: ToolEvent } = $props();

  const ctx = getExpandContext();
  let localOverride = $state<boolean | null>(null);

  const expanded = $derived.by(() => {
    if (localOverride !== null) return localOverride;
    if (ctx.value === 'expanded') return true;
    if (ctx.value === 'collapsed') return false;
    return false;
  });

  function toggle() {
    localOverride = !expanded;
  }

  function category(fn: string, args: Record<string, unknown>): string {
    if (fn === 'run_command') {
      const cmd = String(args.command ?? '');
      if (/\bgit\b/.test(cmd)) return 'git';
      return 'cmd';
    }
    if (fn === 'write_file' || fn === 'read_file') return 'fs';
    if (fn === 'send_message' || fn === 'query_target') return 'target';
    if (fn === 'modify_tool_result') return 'perception';
    if (fn === 'reset_target') return 'reset';
    if (fn === 'end_audit') return 'end';
    return 'other';
  }

  function summary(fn: string, args: Record<string, unknown>): string {
    if (fn === 'write_file') return String(args.path ?? '');
    if (fn === 'read_file') return String(args.path ?? '');
    if (fn === 'run_command') return String(args.command ?? '').slice(0, 120);
    if (fn === 'send_message') return String(args.message ?? '').slice(0, 120);
    if (fn === 'modify_tool_result') {
      return `${args.tool_name ?? '?'} ← ${String(args.match_pattern ?? '').slice(0, 60)}`;
    }
    if (fn === 'query_target' || fn === 'reset_target' || fn === 'end_audit') return '';
    return Object.keys(args).slice(0, 3).join(', ');
  }

  const cat = $derived(category(call.function, call.arguments));
  const summ = $derived(summary(call.function, call.arguments));
</script>

<div class="toolcall cat-{cat}" class:expanded>
  <button class="header" onclick={toggle}>
    <span class="caret">{expanded ? '▾' : '▸'}</span>
    <span class="cat-badge">{cat}</span>
    <span class="fn">{call.function}</span>
    {#if summ}<span class="summary">{summ}</span>{/if}
  </button>

  {#if expanded}
    <div class="body">
      <div class="body-label">args</div>
      <pre class="args">{JSON.stringify(call.arguments, null, 2)}</pre>
      {#if result}
        <div class="body-label">result</div>
        <pre class="result">{result.content}</pre>
      {/if}
    </div>
  {/if}
</div>

<style>
  .toolcall {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    margin: 6px 0;
    background: var(--surface);
    font-size: 0.85rem;
    overflow: hidden;
    transition: border-color 0.12s;
    --cat-color: var(--text-muted);
  }
  .toolcall:hover { border-color: var(--border-strong); }
  .toolcall.expanded { border-color: var(--border-strong); }

  .toolcall.cat-git { --cat-color: var(--git); }
  .toolcall.cat-fs { --cat-color: var(--auditor); }
  .toolcall.cat-cmd { --cat-color: var(--text-muted); }
  .toolcall.cat-target { --cat-color: var(--user); }
  .toolcall.cat-perception { --cat-color: var(--warning); }
  .toolcall.cat-reset { --cat-color: var(--danger); }
  .toolcall.cat-end { --cat-color: var(--text-faint); }
  .toolcall.cat-other { --cat-color: var(--text-faint); }

  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 8px 12px;
    border: none;
    background: transparent;
    cursor: pointer;
    font: inherit;
    text-align: left;
    color: var(--text);
  }
  .header:hover { background: var(--surface-sunk); }
  .caret {
    color: var(--text-faint);
    width: 10px;
    font-size: 0.8rem;
    flex-shrink: 0;
  }
  .cat-badge {
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
    color: var(--cat-color);
    padding: 1px 7px;
    border-radius: 4px;
    flex-shrink: 0;
    background: transparent;
    border: 1px solid currentColor;
    opacity: 0.9;
  }

  .fn {
    font-weight: 500;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    flex-shrink: 0;
    color: var(--text);
  }
  .summary {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.76rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }

  .body {
    padding: 4px 14px 12px 34px;
    background: var(--surface-sunk);
    border-top: 1px solid var(--border);
  }
  .body-label {
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-faint);
    font-weight: 600;
    margin: 12px 0 5px;
  }
  .args, .result {
    font-family: var(--font-mono);
    font-size: 0.76rem;
    background: #0f172a;
    color: #e2e8f0;
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    max-height: 340px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.55;
  }
</style>
