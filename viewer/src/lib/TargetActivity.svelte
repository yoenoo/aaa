<script lang="ts">
  import type { TargetTurn } from './types';
  import MarkdownText from './MarkdownText.svelte';

  let { turns, quotes = [] }: { turns: TargetTurn[]; quotes?: string[] } = $props();

  function argsPreview(args: Record<string, unknown>): string {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(args)) {
      let s: string;
      if (typeof v === 'string') s = v.length > 70 ? v.slice(0, 70) + '…' : v;
      else s = JSON.stringify(v);
      parts.push(`${k}: ${s}`);
      if (parts.length >= 2) break;
    }
    const more = Object.keys(args).length - parts.length;
    return parts.join(' · ') + (more > 0 ? ` · +${more} more` : '');
  }
</script>

<div class="activity">
  {#each turns as turn, i (i)}
    <div class="turn">
      {#if turn.reasoning}
        <details class="target-reasoning">
          <summary>
            <span class="tr-label">internal reasoning</span>
            <span class="tr-note">not shown to auditor</span>
            <span class="tr-count">{turn.reasoning.length} chars</span>
          </summary>
          <pre>{turn.reasoning}</pre>
        </details>
      {:else if turn.redacted_reasoning_chars}
        <div class="target-redacted" title="Provider returned the reasoning as encrypted ciphertext. Not decodable by the viewer.">
          🔒 encrypted reasoning · {turn.redacted_reasoning_chars} chars
        </div>
      {/if}
      {#if turn.text}
        <div class="turn-text"><MarkdownText text={turn.text} {quotes} /></div>
      {/if}
      {#each turn.tool_calls as tc (tc.id)}
        <details class="tcall">
          <summary>
            <span class="caret"></span>
            <span class="fn">{tc.function}</span>
            <span class="args">{argsPreview(tc.arguments)}</span>
          </summary>
          <div class="tcall-body">
            <div class="tc-label">args</div>
            <pre class="tc-args">{JSON.stringify(tc.arguments, null, 2)}</pre>
            <div class="tc-label">result</div>
            {#if tc.result == null}
              <div class="tc-empty">(no result captured)</div>
            {:else}
              <pre class="tc-result">{tc.result}</pre>
            {/if}
          </div>
        </details>
      {/each}
    </div>
  {/each}
</div>

<style>
  .activity {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .turn {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .turn + .turn {
    padding-top: 10px;
    border-top: 1px dashed var(--border);
  }

  .target-reasoning {
    font-size: 0.78rem;
    background: var(--surface-sunk);
    border: 1px solid var(--border);
    border-left: 2px solid var(--text-muted);
    border-radius: var(--radius-sm);
    padding: 4px 12px;
  }
  .target-reasoning summary {
    cursor: pointer;
    color: var(--text-muted);
    list-style: none;
    padding: 4px 0;
    font-size: 0.74rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .target-reasoning summary::-webkit-details-marker { display: none; }
  .target-reasoning summary::before {
    content: '🧠';
    font-size: 0.82rem;
    opacity: 0.75;
  }
  .tr-label {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text);
    font-size: 0.66rem;
  }
  .tr-note {
    font-style: italic;
    color: var(--text-faint);
    font-size: 0.7rem;
  }
  .tr-count {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--text-faint);
    font-family: var(--font-mono);
    font-size: 0.68rem;
  }
  .target-redacted {
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
  .target-reasoning pre {
    white-space: pre-wrap;
    background: var(--surface);
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: 0.74rem;
    line-height: 1.55;
    max-height: 260px;
    overflow: auto;
    margin-top: 6px;
    color: var(--text-muted);
  }

  .turn-text {
    font-size: 0.9rem;
    line-height: 1.6;
  }

  .tcall {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-sunk);
    overflow: hidden;
  }
  .tcall summary {
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px;
    list-style: none;
    font-size: 0.82rem;
    color: var(--text);
  }
  .tcall summary::-webkit-details-marker { display: none; }
  .tcall summary:hover { background: var(--surface-alt); }
  .caret {
    width: 0;
    height: 0;
    border-left: 4px solid var(--text-faint);
    border-top: 3px solid transparent;
    border-bottom: 3px solid transparent;
    transition: transform 0.15s;
    flex-shrink: 0;
  }
  .tcall[open] .caret { transform: rotate(90deg); }
  .fn {
    font-family: var(--font-mono);
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--target);
    flex-shrink: 0;
  }
  .args {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.76rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }
  .tcall-body {
    padding: 6px 14px 12px;
    background: var(--surface);
    border-top: 1px solid var(--border);
  }
  .tc-label {
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-faint);
    font-weight: 600;
    margin: 10px 0 4px;
  }
  .tc-args, .tc-result {
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
  .tc-empty {
    font-size: 0.78rem;
    color: var(--text-faint);
    font-style: italic;
    padding: 4px 0;
  }
</style>
