<script lang="ts">
  import type { Event, Highlight, ToolEvent } from './types';
  import ToolCall from './ToolCall.svelte';
  import MarkdownText from './MarkdownText.svelte';
  import TargetActivity from './TargetActivity.svelte';

  let {
    event,
    resultsByCallId,
    highlights = [],
  }: {
    event: Event;
    resultsByCallId: Record<string, ToolEvent>;
    highlights?: Highlight[];
  } = $props();

  let reasoningOpen = $state(false);

  const quotes = $derived(highlights.map((h) => h.quoted_text).filter(Boolean));

  function fmtDur(s: number | null | undefined): string {
    if (s == null) return '';
    if (s < 1) return `${Math.round(s * 1000)}ms`;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s - m * 60)}s`;
  }

  const showAsCard = $derived(
    event.role !== 'tool' ||
      event.tool_name === 'query_target' ||
      highlights.length > 0 ||
      !!(event.role === 'tool' && event.error),
  );

  const hasError = $derived(event.role === 'tool' && !!event.error);
  const hasHighlights = $derived(highlights.length > 0);
</script>

{#if event.role === 'system'}
  <details class="msg system" id={event.id}>
    <summary><span class="chev">▸</span> system prompt</summary>
    <div class="system-body"><MarkdownText text={event.content} /></div>
  </details>
{:else if event.role === 'user'}
  <div class="msg user" class:annotated={hasHighlights} id={event.id}>
    <div class="role-row">
      <span class="role">user</span>
      <span class="right">
        {#if hasHighlights}<span class="hl-badge" title="{highlights.length} judge highlight(s)">★ {highlights.length}</span>{/if}
        {#if event.duration_s != null}<span class="dur">{fmtDur(event.duration_s)}</span>{/if}
      </span>
    </div>
    <div class="content"><MarkdownText text={event.content} {quotes} /></div>
  </div>
{:else if event.role === 'assistant'}
  <div class="msg assistant" class:annotated={hasHighlights} id={event.id}>
    <div class="role-row">
      <span class="role">auditor</span>
      <span class="right">
        {#if hasHighlights}<span class="hl-badge" title="{highlights.length} judge highlight(s)">★ {highlights.length}</span>{/if}
        {#if event.duration_s != null}<span class="dur" title="Model generation time">{fmtDur(event.duration_s)}</span>{/if}
      </span>
    </div>
    {#if event.reasoning}
      <details class="reasoning" bind:open={reasoningOpen}>
        <summary>
          <span class="reasoning-label">internal reasoning</span>
          <span class="reasoning-note">not shown to target</span>
          <span class="reasoning-count">{event.reasoning.length} chars</span>
        </summary>
        <pre>{event.reasoning}</pre>
      </details>
    {:else if event.redacted_reasoning_chars}
      <div class="reasoning-redacted" title="Provider returned the reasoning as encrypted ciphertext (OpenAI encrypted_content / Anthropic redacted_thinking). Not decodable by the viewer.">
        encrypted reasoning · {event.redacted_reasoning_chars} chars
      </div>
    {/if}
    {#if event.content}
      <div class="content"><MarkdownText text={event.content} {quotes} /></div>
    {/if}
    {#each event.tool_calls as tc (tc.id)}
      <ToolCall call={tc} result={resultsByCallId[tc.id]} />
    {/each}
  </div>
{:else if event.role === 'tool' && showAsCard}
  <div class="msg target" class:errored={hasError} class:annotated={hasHighlights} id={event.id}>
    <div class="role-row">
      <span class="role">{event.tool_name === 'query_target' ? 'target' : `tool · ${event.tool_name}`}</span>
      <span class="right">
        {#if hasHighlights}<span class="hl-badge" title="{highlights.length} judge highlight(s)">★ {highlights.length}</span>{/if}
        {#if hasError && event.error}<span class="err-badge">error · {event.error.type || 'unknown'}</span>{/if}
        {#if event.duration_s != null}<span class="dur">{fmtDur(event.duration_s)}</span>{/if}
      </span>
    </div>
    {#if hasError && event.error?.message}
      <div class="err-body">{event.error.message}</div>
    {/if}
    {#if event.tool_name === 'query_target' && event.target_system_prompt}
      <details class="target-sys">
        <summary>system prompt · {event.target_system_prompt.length} chars</summary>
        <div class="target-sys-body"><MarkdownText text={event.target_system_prompt} /></div>
      </details>
    {/if}
    {#if event.tool_name === 'query_target' && event.target_activity && event.target_activity.length > 0}
      <TargetActivity turns={event.target_activity} {quotes} />
    {:else}
      <div class="content"><MarkdownText text={event.content} {quotes} /></div>
    {/if}
  </div>
{/if}

<style>
  .msg {
    margin: 8px 0;
    padding: 14px 18px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--surface);
    transition: border-color 0.12s;
  }
  .msg:hover { border-color: var(--border-strong); }

  .msg.user { border-left: 2px solid var(--user); }
  .msg.assistant { border-left: 2px solid var(--auditor); }
  .msg.target { border-left: 2px solid var(--target); }
  .msg.errored { border-left-color: var(--danger); }
  .hl-badge {
    font-size: 0.66rem;
    font-weight: 600;
    color: var(--warning-ink);
    background: var(--warning-soft);
    border: 1px solid transparent;
    padding: 1px 7px;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;
  }
  .err-badge {
    font-size: 0.64rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--danger-ink);
    background: var(--danger-soft);
    padding: 2px 8px;
    border-radius: 4px;
  }
  .err-body {
    margin: 0 0 8px;
    padding: 10px 12px;
    background: var(--danger-soft);
    border-left: 2px solid var(--danger);
    border-radius: var(--radius-sm);
    color: var(--danger-ink);
    font-family: var(--font-mono);
    font-size: 0.78rem;
    line-height: 1.45;
    word-break: break-word;
  }
  .right { display: inline-flex; align-items: center; gap: 6px; }
  .msg.system {
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-left: 2px solid var(--border-strong);
    padding: 10px 16px;
  }
  .role-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;
  }
  .role {
    font-size: 0.64rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 600;
    color: var(--text-muted);
  }
  .dur {
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
  }
  .msg.user .role { color: var(--user); }
  .msg.assistant .role { color: var(--auditor); }
  .msg.target .role { color: var(--target); }

  .content {
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--text);
    word-break: break-word;
  }
  .reasoning {
    margin: 6px 0 10px;
    font-size: 0.8rem;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-left: 2px solid var(--text-muted);
    border-radius: var(--radius-sm);
    padding: 4px 12px;
  }
  .reasoning summary {
    cursor: pointer;
    color: var(--text-muted);
    list-style: none;
    padding: 4px 0;
    font-size: 0.74rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .reasoning summary::-webkit-details-marker { display: none; }
  .reasoning summary::before {
    content: '🧠';
    font-size: 0.82rem;
    opacity: 0.75;
  }
  .reasoning-label {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text);
    font-size: 0.66rem;
  }
  .reasoning-note {
    font-style: italic;
    color: var(--text-faint);
    font-size: 0.7rem;
  }
  .reasoning-count {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
    font-size: 0.68rem;
  }
  .reasoning-redacted {
    margin: 6px 0 10px;
    font-size: 0.72rem;
    color: var(--text-faint);
    font-family: var(--font-mono);
    padding: 4px 10px;
    background: var(--surface-sunk);
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    display: inline-block;
    cursor: help;
  }
  .reasoning-redacted::before {
    content: '🔒 ';
    opacity: 0.6;
  }
  .reasoning pre {
    white-space: pre-wrap;
    background: var(--surface);
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: 0.76rem;
    line-height: 1.55;
    max-height: 340px;
    overflow: auto;
    margin-top: 6px;
    color: var(--text-muted);
  }
  .system-body {
    margin-top: 10px;
    max-height: 420px;
    overflow: auto;
    font-size: 0.84rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 12px 14px;
    line-height: 1.55;
    color: var(--text);
  }
  .msg.system summary {
    cursor: pointer;
    color: var(--text-muted);
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .msg.system .chev {
    font-size: 0.64rem;
    color: var(--text-faint);
    transition: transform 0.15s;
  }
  .msg.system[open] .chev { transform: rotate(90deg); }

  .target-sys {
    margin: 0 0 8px;
    font-size: 0.78rem;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 4px 12px;
  }
  .target-sys summary {
    cursor: pointer;
    color: var(--text-muted);
    list-style: none;
    padding: 4px 0;
    font-size: 0.74rem;
  }
  .target-sys summary::-webkit-details-marker { display: none; }
  .target-sys-body {
    margin-top: 6px;
    max-height: 340px;
    overflow: auto;
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 0.82rem;
    line-height: 1.55;
    color: var(--text);
  }
</style>
