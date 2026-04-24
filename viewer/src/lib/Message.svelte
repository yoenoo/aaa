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
  let rawView = $state(false);
  let sysPromptOpen = $state(false);

  // Ground-truth auditor context: the literal ChatMessage list the model
  // received for this generate() call, taken from the paired ModelEvent's
  // input. Null for non-assistant events or when no ModelEvent was recorded.
  const auditorContext = $derived(
    event.role === 'assistant' ? (event.auditor_context ?? null) : null,
  );

  function ctxPreview(cm: import('./types').ContextMessage): string {
    const line = (cm.preview || '').split('\n')[0];
    if (cm.role === 'system') return `system prompt · ${cm.length} chars`;
    if (cm.role === 'assistant') {
      const body = line.slice(0, 100);
      const tcs = cm.tool_calls?.length
        ? ` · ${cm.tool_calls.length} tool call${cm.tool_calls.length === 1 ? '' : 's'}`
        : '';
      return body + tcs;
    }
    if (cm.role === 'tool') {
      const name = cm.function || 'tool';
      return `${name} · ${line.slice(0, 100)}`;
    }
    return line.slice(0, 140);
  }

  function ctxLabel(cm: import('./types').ContextMessage): string {
    if (cm.role === 'assistant') return 'auditor';
    if (cm.role === 'tool') return cm.function === 'query_target' ? 'target' : 'tool';
    return cm.role;
  }

  function jumpTo(id: string, ev: MouseEvent) {
    ev.preventDefault();
    const h = window.location.hash.replace(/^#\/?/, '').split('/')[0] || '';
    window.location.hash = `/${h}/${id}`;
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  const quotes = $derived(highlights.map((h) => h.quoted_text).filter(Boolean));

  function jumpLink(): string {
    const h = window.location.hash.replace(/^#\/?/, '').split('/')[0] || '';
    return `#/${h}/${event.id}`;
  }

  async function copyJumpLink(e: MouseEvent) {
    e.preventDefault();
    const url = `${window.location.origin}${window.location.pathname}${jumpLink()}`;
    try { await navigator.clipboard.writeText(url); } catch { /* noop */ }
    window.location.hash = jumpLink();
  }

  function fmtDur(s: number | null | undefined): string {
    if (s == null) return '';
    if (s < 1) return `${Math.round(s * 1000)}ms`;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s - m * 60)}s`;
  }

  // Tool events render inline inside their parent assistant's ToolCall by
  // default. Promote to a standalone card only for `query_target` (multi-turn
  // target session with its own presentation) or errors (so the failure is
  // visible at the top level). Judge highlights alone do NOT promote — that
  // would duplicate the render (inline + standalone) for every flagged tool.
  const showAsCard = $derived(
    event.role !== 'tool' ||
      event.tool_name === 'query_target' ||
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
        <a class="anchor" href={jumpLink()} onclick={copyJumpLink} title="Copy link to event {event.id}">{event.id}</a>
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
        <a class="anchor" href={jumpLink()} onclick={copyJumpLink} title="Copy link to event {event.id}">{event.id}</a>
        {#if hasHighlights}<span class="hl-badge" title="{highlights.length} judge highlight(s)">★ {highlights.length}</span>{/if}
        {#if event.duration_s != null}<span class="dur" title="Model generation time">{fmtDur(event.duration_s)}</span>{/if}
      </span>
    </div>
    {#if auditorContext && auditorContext.length > 0}
      <details class="ctx">
        <summary>
          <span class="ctx-label">auditor context</span>
          <span class="ctx-note">ground-truth input to this generate() call</span>
          <span class="ctx-count">{auditorContext.length}</span>
        </summary>
        <ul class="ctx-list">
          {#each auditorContext as cm, ci (ci)}
            <li class="ctx-row" class:unmatched={cm.event_id == null}>
              <span class="ctx-role ctx-role-{cm.role}">{ctxLabel(cm)}</span>
              {#if cm.event_id}
                <a class="ctx-id" href={`#/`} onclick={(ev) => jumpTo(cm.event_id!, ev)}>{cm.event_id}</a>
              {:else}
                <span class="ctx-id unmatched-id" title="This message in the ModelEvent input does not match sample.messages at the same position — the auditor received something different from what the transcript renders.">⚠</span>
              {/if}
              <span class="ctx-preview">{ctxPreview(cm)}</span>
            </li>
          {/each}
        </ul>
      </details>
    {:else if event.role === 'assistant' && event.auditor_context === null}
      <div class="ctx-missing" title="No ModelEvent was recorded for this turn — cannot show ground-truth context.">
        📜 auditor context: not recorded
      </div>
    {/if}
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
      {#if event.tool_name === 'query_target' && event.target_system_prompt}
        <button
          class="role role-btn"
          class:active={sysPromptOpen}
          onclick={() => (sysPromptOpen = !sysPromptOpen)}
          title="Click to {sysPromptOpen ? 'hide' : 'show'} target system prompt ({event.target_system_prompt.length} chars)"
        >target</button>
      {:else}
        <span class="role">{event.tool_name === 'query_target' ? 'target' : `tool · ${event.tool_name}`}</span>
      {/if}
      <span class="right">
        {#if event.tool_name === 'query_target' && event.target_activity && event.target_activity.length > 0}
          <button
            class="view-toggle"
            onclick={() => (rawView = !rawView)}
            title={rawView ? 'Show parsed per-turn view' : 'Show the exact string the auditor received as tool result'}
          >{rawView ? 'parsed' : 'raw'}</button>
        {/if}
        <a class="anchor" href={jumpLink()} onclick={copyJumpLink} title="Copy link to event {event.id}">{event.id}</a>
        {#if hasHighlights}<span class="hl-badge" title="{highlights.length} judge highlight(s)">★ {highlights.length}</span>{/if}
        {#if hasError && event.error}<span class="err-badge">error · {event.error.type || 'unknown'}</span>{/if}
        {#if event.duration_s != null}<span class="dur">{fmtDur(event.duration_s)}</span>{/if}
      </span>
    </div>
    {#if hasError && event.error?.message}
      <div class="err-body">{event.error.message}</div>
    {/if}
    {#if event.tool_name === 'query_target' && event.target_system_prompt && sysPromptOpen}
      <div class="target-sys-body">
        <div class="target-sys-head">target system prompt · {event.target_system_prompt.length} chars</div>
        <MarkdownText text={event.target_system_prompt} />
      </div>
    {/if}
    {#if event.tool_name === 'query_target' && event.target_activity && event.target_activity.length > 0 && !rawView}
      <TargetActivity turns={event.target_activity} {quotes} />
    {:else if rawView}
      <div class="raw-label">auditor input · {event.content.length} chars</div>
      <pre class="raw-content">{event.content}</pre>
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

  .msg.user { --role-accent: var(--user); }
  .msg.assistant { --role-accent: var(--auditor); }
  .msg.target { --role-accent: var(--target); }
  .msg.errored { --role-accent: var(--danger); }
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
  .anchor {
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--text-faint);
    text-decoration: none;
    padding: 1px 6px;
    border: 1px solid transparent;
    border-radius: 4px;
    opacity: 0.55;
    transition: opacity 0.12s, color 0.12s, border-color 0.12s;
  }
  .anchor:hover { opacity: 1; color: var(--text); border-color: var(--border); }
  .view-toggle {
    font: inherit;
    font-size: 0.64rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid var(--border);
    padding: 1px 8px;
    border-radius: 4px;
    cursor: pointer;
  }
  .view-toggle:hover { color: var(--text); border-color: var(--border-strong); }
  .raw-label {
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-faint);
    font-weight: 600;
    margin: 4px 0 6px;
  }
  .raw-content {
    font-family: var(--font-mono);
    font-size: 0.76rem;
    background: #0f172a;
    color: #e2e8f0;
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    max-height: 560px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.55;
    margin: 0;
  }
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
    display: inline-block;
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 999px;
    color: var(--role-accent, var(--text-muted));
    background: color-mix(in srgb, var(--role-accent, var(--text-muted)) 11%, transparent);
    border: 1px solid color-mix(in srgb, var(--role-accent, var(--text-muted)) 30%, transparent);
  }
  .dur {
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
    opacity: 0.55;
    transition: opacity 0.12s;
  }
  .msg:hover .dur { opacity: 1; }

  .content {
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--text);
    word-break: break-word;
  }
  .ctx {
    margin: 6px 0 10px;
    font-size: 0.8rem;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-left: 2px solid var(--auditor);
    border-radius: var(--radius-sm);
    padding: 4px 12px;
  }
  .ctx > summary {
    cursor: pointer;
    color: var(--text-muted);
    list-style: none;
    padding: 4px 0;
    font-size: 0.74rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ctx > summary::-webkit-details-marker { display: none; }
  .ctx > summary::before {
    content: '📜';
    font-size: 0.82rem;
    opacity: 0.7;
  }
  .ctx-label {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text);
    font-size: 0.66rem;
  }
  .ctx-note {
    font-style: italic;
    color: var(--text-faint);
    font-size: 0.7rem;
  }
  .ctx-count {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
    font-size: 0.68rem;
  }
  .ctx-list {
    list-style: none;
    padding: 6px 0 4px;
    margin: 0;
    max-height: 320px;
    overflow: auto;
  }
  .ctx-row {
    display: grid;
    grid-template-columns: 58px 44px minmax(0, 1fr);
    align-items: center;
    column-gap: 10px;
    padding: 2px 2px;
    font-size: 0.76rem;
    line-height: 1.4;
  }
  .ctx-role {
    font-size: 0.58rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 3px;
    text-align: center;
    border: 1px solid color-mix(in srgb, var(--ctx-c, var(--text-muted)) 30%, transparent);
    background: color-mix(in srgb, var(--ctx-c, var(--text-muted)) 10%, transparent);
    color: var(--ctx-c, var(--text-muted));
  }
  .ctx-role-system { --ctx-c: var(--text-faint); }
  .ctx-role-user { --ctx-c: var(--user); }
  .ctx-role-assistant { --ctx-c: var(--auditor); }
  .ctx-role-tool { --ctx-c: var(--target); }
  .ctx-id {
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--text-faint);
    text-decoration: none;
    text-align: right;
  }
  .ctx-id:hover { color: var(--text); text-decoration: underline; }
  .ctx-preview {
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ctx-row.unmatched {
    background: color-mix(in srgb, var(--danger) 8%, transparent);
  }
  .unmatched-id {
    color: var(--danger);
    font-size: 0.8rem;
    text-align: right;
    cursor: help;
  }
  .ctx-missing {
    margin: 6px 0 10px;
    font-size: 0.72rem;
    color: var(--text-faint);
    font-style: italic;
    padding: 4px 10px;
    background: var(--surface-sunk);
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    display: inline-block;
    cursor: help;
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

  .role-btn {
    font: inherit;
    font-size: 0.6rem;
    letter-spacing: 0.14em;
    font-weight: 700;
    box-sizing: content-box;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
  }
  .role-btn:hover { background: color-mix(in srgb, var(--role-accent, var(--text-muted)) 18%, transparent); }
  .role-btn.active {
    background: color-mix(in srgb, var(--role-accent, var(--text-muted)) 22%, transparent);
    border-color: color-mix(in srgb, var(--role-accent, var(--text-muted)) 50%, transparent);
  }
  .target-sys-body {
    margin: 4px 0 10px;
    max-height: 340px;
    overflow: auto;
    padding: 10px 12px;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-left: 2px solid var(--target);
    border-radius: var(--radius-sm);
    font-size: 0.82rem;
    line-height: 1.55;
    color: var(--text);
  }
  .target-sys-head {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-faint);
    font-weight: 600;
    margin-bottom: 8px;
  }
</style>
