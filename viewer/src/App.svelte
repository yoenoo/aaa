<script lang="ts">
  import { onMount } from 'svelte';
  import AuditList from './lib/AuditList.svelte';
  import TranscriptView from './lib/TranscriptView.svelte';

  function parseHash(): string {
    const h = (typeof window === 'undefined' ? '' : window.location.hash) || '';
    const stripped = h.replace(/^#\/?/, '');
    return decodeURIComponent(stripped);
  }

  let route = $state(parseHash());

  onMount(() => {
    const handler = () => { route = parseHash(); };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  });

  function open(id: string) {
    window.location.hash = `/${encodeURIComponent(id)}`;
  }
  function back() {
    window.location.hash = '';
  }
</script>

{#if route}
  {#key route}
    <TranscriptView logId={route} onBack={back} />
  {/key}
{:else}
  <AuditList onOpen={open} />
{/if}
