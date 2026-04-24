<script lang="ts">
  import { onMount } from 'svelte';
  import AuditList from './lib/AuditList.svelte';
  import TranscriptView from './lib/TranscriptView.svelte';

  function parseHash(): { id: string; eventId: string } {
    const h = (typeof window === 'undefined' ? '' : window.location.hash) || '';
    const stripped = h.replace(/^#\/?/, '');
    const [id = '', eventId = ''] = stripped.split('/');
    return { id: decodeURIComponent(id), eventId: decodeURIComponent(eventId) };
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

{#if route.id}
  {#key route.id}
    <TranscriptView logId={route.id} initialEventId={route.eventId} onBack={back} />
  {/key}
{:else}
  <AuditList onOpen={open} />
{/if}
