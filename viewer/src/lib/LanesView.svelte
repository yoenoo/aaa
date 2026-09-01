<script lang="ts">
  import { onMount } from 'svelte';
  import type { TranscriptData, Event, AssistantEvent, ToolEvent, Highlight, Branch } from './types';
  import MarkdownText from './MarkdownText.svelte';
  import HighlightedText from './HighlightedText.svelte';

  let {
    logId,
    initialEventId = '',
    onBack,
  }: {
    logId: string;
    initialEventId?: string;
    onBack?: () => void;
  } = $props();

  let transcript = $state<TranscriptData | null>(null);
  let error = $state<string | null>(null);
  let mode = $state<'beats' | 'full'>('beats');
  let theme = $state<'dark' | 'light'>('dark');
  let curEventId = $state('');
  let curBranch = $state<number>(1);

  onMount(() => {
    const saved = window.localStorage.getItem('petri-viewer-theme');
    theme = saved === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
  });

  $effect(() => {
    const id = logId;
    transcript = null;
    error = null;
    (async () => {
      try {
        const res = await fetch(`/data/${encodeURIComponent(id)}.json`);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = (await res.json()) as TranscriptData;
        if (logId === id) transcript = data;
      } catch (e) {
        if (logId === id) error = (e as Error).message;
      }
    })();
  });

  $effect(() => {
    if (!transcript || !initialEventId) return;
    requestAnimationFrame(() => jumpTo(initialEventId));
  });

  // ---- helpers ----------------------------------------------------------
  function shortModel(m: string): string { return m.split('/').pop() || m; }

  function fmtDuration(seconds: number | null | undefined): string {
    if (seconds == null) return '—';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    if (m < 60) return `${m}m ${Math.round(seconds - m * 60)}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${m - h * 60}m`;
  }

  function decodeEntities(s: string): string {
    return s
      .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'");
  }

  type HL = Highlight & { n: number; debug: boolean; dq: string };
  const hAll = $derived.by<HL[]>(() =>
    (transcript?.judge.highlights || []).map((h, i) => ({
      ...h, n: i + 1, debug: debugHl(h), dq: decodeEntities(h.quoted_text),
    })));

  const highlightsByEvent = $derived.by(() => {
    const m = new Map<string, HL[]>();
    for (const h of hAll) {
      const arr = m.get(h.event_id) || [];
      arr.push(h);
      m.set(h.event_id, arr);
    }
    return m;
  });

  function quotesFor(id: string): string[] {
    return (highlightsByEvent.get(id) || []).filter((h) => !h.debug).map((h) => h.dq).filter(Boolean);
  }
  function debugQuotesFor(id: string): string[] {
    return (highlightsByEvent.get(id) || []).filter((h) => h.debug).map((h) => h.dq).filter(Boolean);
  }
  // highlights for an event whose quote falls within a given text slice (a turn)
  function hlsInText(id: string, ...texts: string[]): HL[] {
    const joined = texts.join('\n');
    return (highlightsByEvent.get(id) || []).filter((h) => joined.includes(h.dq));
  }
  function quoteInText(id: string, text: string): boolean {
    return (highlightsByEvent.get(id) || []).some((h) => text.includes(h.dq));
  }
  // A judge quote on a target tool call is the escaped "[id] fn({\"command\": \"…\"})"
  // form; the card now shows only the unescaped command, so pull the command out of
  // each quote to re-anchor the highlight on the displayed command text.
  function extractCmd(q: string): string | null {
    const m = q.match(/"command"\s*:\s*"((?:[^"\\]|\\.)*)/);
    return m ? unescapeJsonStr(m[1]) : null;
  }
  function cmdQuotes(id: string): { scheming: string[]; debug: string[] } {
    const out = { scheming: [] as string[], debug: [] as string[] };
    for (const h of highlightsByEvent.get(id) || []) {
      const cmd = extractCmd(h.dq);
      if (cmd) (h.debug ? out.debug : out.scheming).push(stripTrunc(cmd).text);
    }
    return out;
  }
  // Tool results arrive wrapped, e.g. {"output": "<untrusted_context>\nOutput: …"}.
  // Unwrap the JSON value and strip the scaffold framing so only the output shows.
  function cleanResult(s: string): string {
    let t = (s || '').trim();
    if (t.startsWith('{')) {
      try {
        const o = JSON.parse(t);
        if (o && typeof o === 'object' && !Array.isArray(o)) {
          if (typeof o.output === 'string') t = o.output;
          else {
            const strs = Object.values(o).filter((v) => typeof v === 'string') as string[];
            if (strs.length) t = strs.join('\n');
          }
        }
      } catch { /* not JSON — leave as-is */ }
    }
    t = t.replace(/<\/?untrusted_context>/gi, '').replace(/^\s*Output:\s*/i, '');
    return t.trim();
  }

  // The source dump appends "...[truncated, N more chars]" when it caps a value;
  // remove the marker for display and report how many chars were dropped.
  function stripTrunc(s: string): { text: string; more: number } {
    const m = (s || '').match(/\.\.\.\[truncated,\s*(\d+)\s*more chars\]/);
    if (!m || m.index === undefined) return { text: s || '', more: 0 };
    return { text: (s.slice(0, m.index) + s.slice(m.index + m[0].length)).replace(/\s+$/, ''), more: Number(m[1]) };
  }

  function isTargetEvent(ev: Event): boolean {
    return ev.role === 'tool' && (ev.tool_name === 'query_target' || !!(ev as ToolEvent).target_activity?.length);
  }

  function callText(call: { function: string; arguments: Record<string, unknown> }): string {
    const a = call.arguments || {};
    if (typeof a.command === 'string') return a.command;
    if (typeof a.message === 'string') return a.message;
    try { return JSON.stringify(a); } catch { return String(a); }
  }

  // ---- parse a flattened target reply into turns + calls ----------------
  // Real transcripts leave target_activity empty; the target's turns live in
  // the tool event's `content` as text: a "Target response (N calls):" header,
  // "-- turn K --" delimiters, and "[id: call_X] fn({args}) → result" blocks.
  type TCall = { id: string; head: string; result: string };
  type TTurn = { no: string; preamble: string; calls: TCall[] };

  function preambleOf(body: string): string {
    const i = body.search(/\[id:\s*call_\w+\]/);
    return (i === -1 ? body : body.slice(0, i)).trim();
  }
  function parseCalls(body: string): TCall[] {
    const re = /\[id:\s*(call_\w+)\]/g;
    const marks: { idx: number; id: string }[] = [];
    let m: RegExpExecArray | null;
    while ((m = re.exec(body))) marks.push({ idx: m.index, id: m[1] });
    return marks.map((mk, i) => {
      const seg = body.slice(mk.idx, i + 1 < marks.length ? marks[i + 1].idx : body.length).trim();
      const arrow = seg.indexOf('→'); // →
      if (arrow === -1) return { id: mk.id, head: seg, result: '' };
      return { id: mk.id, head: seg.slice(0, arrow).trim(), result: seg.slice(arrow + 1).replace(/^[\s→]+/, '').trim() };
    });
  }

  // Full, untruncated tool calls recovered by transcript.py into target_activity,
  // keyed by call id so we can swap them in for the truncated flattened content.
  const fullCallMap = $derived.by(() => {
    const m = new Map<string, { arguments: Record<string, unknown>; result: string | null; function: string }>();
    if (!transcript) return m;
    for (const e of transcript.events) {
      if (e.role !== 'tool') continue;
      for (const t of (e as ToolEvent).target_activity || []) {
        for (const c of t.tool_calls || []) if (c.id) m.set(c.id, c);
      }
    }
    return m;
  });
  function parseTargetContent(content: string): { turns: TTurn[]; finalText: string } {
    // Strip the "Target response (N model calls):" header, then split the tool
    // activity (inside <target_activity>…</target_activity>) from the model's
    // trailing natural-language message.
    const text = (content || '').replace(/^\s*Target response\s*\(\d+\s*model calls?\):\s*/i, '');
    let block = text;
    let finalText = '';
    const open = text.indexOf('<target_activity>');
    const close = text.lastIndexOf('</target_activity>');
    if (open !== -1 && close !== -1) {
      block = text.slice(open + '<target_activity>'.length, close);
      finalText = text.slice(close + '</target_activity>'.length).trim();
    } else if (open === -1 && close === -1) {
      block = '';
      finalText = text.trim();
    }
    const turnRe = /(?:^|\n)\s*--\s*turn\s*(\d+)\s*--\s*/gi;
    const marks: { at: number; end: number; no: string }[] = [];
    let m: RegExpExecArray | null;
    while ((m = turnRe.exec(block))) marks.push({ at: m.index, end: turnRe.lastIndex, no: m[1] });
    let turns: TTurn[];
    if (!marks.length) {
      turns = block.trim() ? [{ no: '', preamble: preambleOf(block), calls: parseCalls(block) }] : [];
    } else {
      turns = marks.map((mk, i) => {
        const body = block.slice(mk.end, i + 1 < marks.length ? marks[i + 1].at : block.length);
        return { no: mk.no, preamble: preambleOf(body), calls: parseCalls(body) };
      });
    }
    return { turns, finalText };
  }
  function fnOf(head: string): string {
    return head.match(/\]\s*(\w+)\s*\(/)?.[1] || '';
  }

  function unescapeJsonStr(s: string): string {
    return s.replace(/\\"/g, '"').replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\\\/g, '\\');
  }

  // A parsed target tool call: "[id: call_X] fn({...json...})" -> fn + args object.
  // The log truncates long args, leaving invalid JSON; recover the command field.
  function parseCall(head: string): { fn: string; args: Record<string, unknown> | null; argStr: string } {
    const m = head.match(/^\s*\[id:\s*call_\w+\]\s*(\w+)\(([\s\S]*)\)\s*$/);
    if (!m) return { fn: fnOf(head), args: null, argStr: head.trim() };
    const argStr = m[2].trim();
    let args: Record<string, unknown> | null = null;
    try {
      const parsed = JSON.parse(argStr);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) args = parsed as Record<string, unknown>;
    } catch {
      const cm = argStr.match(/"command"\s*:\s*"((?:[^"\\]|\\.)*)/);
      if (cm) {
        args = { command: unescapeJsonStr(cm[1]) };
        const dm = argStr.match(/"description"\s*:\s*"((?:[^"\\]|\\.)*?)"/);
        if (dm) args.description = unescapeJsonStr(dm[1]);
      }
    }
    return { fn: m[1], args, argStr };
  }
  function asText(v: unknown): string {
    return typeof v === 'string' ? v : JSON.stringify(v);
  }

  // Group a target reply's turns: show turns that carry judge evidence (plus the
  // first and last for context); fold consecutive routine turns behind a summary.
  type TurnGroup =
    | { fold: false; t: TTurn; no: string; hls: HL[] }
    | { fold: true; turns: { t: TTurn; no: string }[] };
  function groupTurns(id: string, content: string): { groups: TurnGroup[]; finalText: string; turnCount: number } {
    const parsed = parseTargetContent(content);
    const N = parsed.turns.length;
    const groups: TurnGroup[] = [];
    let fold: { t: TTurn; no: string }[] = [];
    const flush = () => { if (fold.length) { groups.push({ fold: true, turns: fold }); fold = []; } };
    parsed.turns.forEach((t, i) => {
      const texts = [t.preamble, ...t.calls.flatMap((c) => [c.head, c.result])];
      const hls = hlsInText(id, ...texts);
      const important = hls.length > 0 || i === 0 || i === N - 1;
      if (important) {
        flush();
        groups.push({ fold: false, t, no: t.no || String(i + 1), hls });
      } else {
        fold.push({ t, no: t.no || String(i + 1) });
      }
    });
    flush();
    return { groups, finalText: parsed.finalText, turnCount: N };
  }

  function debugHl(h: Highlight): boolean {
    const src = h.source || '';
    return src === 'debug' || (transcript?.judge.score_sources?.[src] === 'debug');
  }

  function topicTitle(content: string): string {
    const titles = [...(content || '').matchAll(/"title":\s*"([^"]+)"/g)].map((m) => m[1]);
    return titles.length ? titles[titles.length - 1] : '';
  }

  // The first user event is the auditor's seed-delivery message (wraps the seed
  // instruction); it duplicates the seed card, so drop it from the lane stream.
  function isSeedDelivery(e: Event): boolean {
    return e.role === 'user' && !!transcript && !!e.content
      && e.content.includes(transcript.seed_instruction.slice(0, 60));
  }

  // ---- overview silhouette ---------------------------------------------
  const overview = $derived.by(() => {
    if (!transcript) return [] as { a: number; t: number; hl: boolean; cut: boolean; id: string }[];
    const evs = transcript.events.filter((e) => !isSeedDelivery(e));
    // Every event contributes activity to one side: the auditor lane (its own
    // turns + the tool results it fetched) or the target lane (its replies).
    // sqrt compresses the scale so a single 28 KB reply doesn't flatten the rest.
    const mag = (n: number) => (n > 0 ? Math.sqrt(n) : 0);
    const raw = evs.map((ev, i) => {
      let audN = 0;
      let tgtN = 0;
      if (isTargetEvent(ev)) tgtN = ev.content?.length || 0;
      else if (ev.role === 'assistant') audN = (ev.content?.length || 0) + 260 * ((ev as AssistantEvent).tool_calls?.length || 0);
      else if (ev.role === 'tool') audN = (ev.content?.length || 0) + 150;
      else audN = (ev.content?.length || 0) + 100;
      const prev = evs[i - 1];
      return { a: mag(audN), t: mag(tgtN), hl: highlightsByEvent.has(ev.id), cut: !!prev && prev.branch !== ev.branch, id: ev.id };
    });
    const maxA = Math.max(1, ...raw.map((r) => r.a));
    const maxT = Math.max(1, ...raw.map((r) => r.t));
    return raw.map((r) => ({
      ...r,
      a: r.a > 0 ? Math.max(0.14, r.a / maxA) : 0,
      t: r.t > 0 ? Math.max(0.14, r.t / maxT) : 0,
    }));
  });

  // ---- judge scores (direction-aware) -----------------------------------
  // Positive dimensions score higher=better, so LOW is the bad signal. Per the
  // judge dimension configs: every debug-source dim is positive, plus these four
  // scheming-source dims. All others are negative (higher=worse).
  const POSITIVE_SCHEMING = new Set([
    'transparent_disagreement', 'genuine_honesty', 'legitimate_escalation', 'scenario_realism',
  ]);
  function isPositiveDim(name: string): boolean {
    return transcript?.judge.score_sources?.[name] === 'debug' || POSITIVE_SCHEMING.has(name);
  }
  type ScoreRow = { name: string; value: number; positive: boolean; flag: 'concerning' | 'weak' | null; notable: boolean; severity: number };
  function classifyScore(name: string, value: number): ScoreRow {
    const positive = isPositiveDim(name);
    const flag = positive ? (value <= 4 ? 'weak' : null) : (value >= 6 ? 'concerning' : null);
    // Show elevated negatives (a bad behavior showed up) and weak positives (a
    // dimension that should be high came out low).
    const notable = positive ? value <= 4 : value > 1;
    const severity = positive ? 10 - value : value;
    return { name, value, positive, flag, notable, severity };
  }

  const scoreRows = $derived.by<ScoreRow[]>(() => {
    if (!transcript) return [];
    return Object.entries(transcript.judge.scores || {})
      .map(([name, value]) => classifyScore(name, value))
      .filter((r) => r.notable)
      // Concerning (high-is-bad) behaviors first, worst at top; positive/quality
      // dimensions (low-is-bad) sink to the bottom.
      .sort((a, b) => (a.positive !== b.positive ? (a.positive ? 1 : -1) : b.value - a.value));
  });

  // Every judged dimension (for the complete, collapsible list).
  const allScores = $derived.by(() => {
    if (!transcript) return [] as ScoreRow[];
    return Object.entries(transcript.judge.scores || {})
      .map(([name, value]) => classifyScore(name, value))
      .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));
  });

  // ---- branch comparison (data-driven) ---------------------------------
  const branchStats = $derived.by(() => {
    if (!transcript) return [] as {
      branch: Branch; events: number; auditorCalls: number; targetReplies: number;
      highlights: Highlight[];
    }[];
    return transcript.branches.map((branch) => {
      const evs = transcript!.events.filter((e) => e.branch === branch.index);
      const auditorCalls = evs.filter((e) => e.role === 'assistant')
        .reduce((n, e) => n + ((e as AssistantEvent).tool_calls?.length || 0), 0);
      const targetReplies = evs.filter(isTargetEvent).length;
      const highlights = (transcript!.judge.highlights || [])
        .filter((h) => evs.some((e) => e.id === h.event_id));
      return { branch, events: evs.length, auditorCalls, targetReplies, highlights };
    });
  });

  // ---- granular timeline (segments cut at branch changes + target replies) ---
  type Seg = { label: string; branch: number; anchorId: string; count: number; hl: number; flagged: boolean };
  const timeline = $derived.by<Seg[]>(() => {
    if (!transcript) return [];
    const evs = transcript.events.filter((e) => !isSeedDelivery(e));
    type Raw = { branch: number; anchorId: string; count: number; hasTarget: boolean; title: string; hasEnd: boolean; hl: number; flagged: boolean };
    const raw: Raw[] = [];
    let bucket: Event[] = [];
    const flush = () => {
      if (!bucket.length) return;
      const target = bucket.find(isTargetEvent) as ToolEvent | undefined;
      const hls = bucket.flatMap((e) => highlightsByEvent.get(e.id) || []);
      raw.push({
        branch: bucket[0].branch, anchorId: (target || bucket[0]).id, count: bucket.length,
        hasTarget: !!target, title: target ? topicTitle(target.content) : '',
        hasEnd: bucket.some((e) => e.role === 'tool' && (e as ToolEvent).tool_name === 'end_audit'),
        hl: hls.length, flagged: hls.some((h) => !debugHl(h)),
      });
      bucket = [];
    };
    evs.forEach((ev, i) => {
      if (i > 0 && evs[i - 1].branch !== ev.branch) flush();
      bucket.push(ev);
      if (isTargetEvent(ev)) flush();
    });
    flush();
    // Label with per-branch position so setup/close land correctly.
    return raw.map((r, i) => {
      const firstOfBranch = raw.findIndex((s) => s.branch === r.branch) === i;
      const lastOfBranch = raw.map((s) => s.branch).lastIndexOf(r.branch) === i;
      let label: string;
      if (r.hasTarget) label = r.title || 'target reply';
      else if (firstOfBranch) label = r.branch > 1 ? 'rollback & setup' : 'setup';
      else if (r.hasEnd || lastOfBranch) label = 'verify & close';
      else label = 'auditor actions';
      return { label, branch: r.branch, anchorId: r.anchorId, count: r.count, hl: r.hl, flagged: r.flagged };
    });
  });

  // Horizontal position (%) of each branch boundary, on the timeband's event-count
  // basis, so a single divider can span the silhouette and the band aligned.
  const cutPcts = $derived.by<number[]>(() => {
    const total = timeline.reduce((n, s) => n + s.count, 0);
    if (!total || !timeline.length) return [];
    const out: number[] = [];
    let acc = 0;
    let branch = timeline[0].branch;
    for (const s of timeline) {
      if (s.branch !== branch) { out.push((acc / total) * 100); branch = s.branch; }
      acc += s.count;
    }
    return out;
  });

  // ---- render rows: branch cuts + events (key-beats collapses content) ------
  type Row = { kind: 'cut'; ev: Event } | { kind: 'event'; ev: Event };
  const rows = $derived.by<Row[]>(() => {
    if (!transcript) return [];
    const evs = transcript.events.filter((e) => !isSeedDelivery(e));
    const out: Row[] = [];
    evs.forEach((ev, i) => {
      if (i > 0 && evs[i - 1].branch !== ev.branch) out.push({ kind: 'cut', ev });
      out.push({ kind: 'event', ev });
    });
    return out;
  });

  function scrollToId(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const usage = $derived.by(() => {
    const ru = transcript?.role_usage || {};
    const fmtTok = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : `${n}`;
    const rows = ['auditor', 'target', 'judge']
      .filter((r) => ru[r])
      .map((r) => {
        const u = ru[r];
        return { role: r, inTok: fmtTok(u.input_tokens), outTok: fmtTok(u.output_tokens), calls: u.calls, cost: u.total_cost };
      });
    const totalCost = rows.reduce((s, r) => s + (r.cost || 0), 0);
    return { rows, totalCost };
  });

  const totalToolCalls = $derived.by(() => {
    if (!transcript) return 0;
    return Object.values(transcript.role_usage || {}).reduce((n, u) => n + (u.calls || 0), 0);
  });

  // ---- interaction ------------------------------------------------------
  function jumpTo(id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1400);
  }

  function jumpBranch(index: number) {
    const el = document.getElementById(`branch-${index}`) || document.getElementById(firstEventOfBranch(index));
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function firstEventOfBranch(index: number): string {
    return transcript?.events.find((e) => e.branch === index)?.id || '';
  }

  function setMode(m: 'beats' | 'full') {
    mode = m;
    requestAnimationFrame(() => {
      document.querySelectorAll<HTMLDetailsElement>('.lanes-root details.disc')
        .forEach((d) => { if (!d.dataset.pin) d.open = m === 'full'; });
    });
  }

  function onBranchSelect(e: globalThis.Event) {
    const idx = Number((e.currentTarget as HTMLSelectElement).value);
    jumpBranch(idx);
  }

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem('petri-viewer-theme', theme);
  }

  function onScroll() {
    const secs = Array.from(document.querySelectorAll<HTMLElement>('.lanes-root .ev[data-ev]'));
    const y = 150;
    let cur = secs[0];
    for (const s of secs) { if (s.getBoundingClientRect().top <= y) cur = s; else break; }
    if (cur) {
      curEventId = cur.dataset.ev || '';
      curBranch = Number(cur.dataset.branch || '1');
    }
  }

  const curBranchLabel = $derived.by(() => {
    const b = transcript?.branches.find((x) => x.index === curBranch);
    return b ? b.label : `branch ${curBranch}`;
  });
</script>

<svelte:window onscroll={onScroll} />

{#if error}
  <main class="state">
    <div class="state-card">
      <div class="kick">Transcript unavailable</div>
      <h1>Could not load this audit</h1>
      <p><code>{error}</code></p>
      <p class="hint">Run <code>uv run python dump_log.py --all</code> to rebuild viewer data.</p>
      {#if onBack}<button onclick={onBack}>← All audits</button>{/if}
    </div>
  </main>
{:else if !transcript}
  <main class="state"><div class="loader"></div><span>Loading transcript</span></main>
{:else}
<div class="lanes-root">
  <header class="topbar">
    <div class="meta">
      <button class="brand" onclick={onBack} disabled={!onBack} title="All audits">← audits</button>
      <h1>{transcript.seed_name || transcript.title} <span class="mono">· {logId}</span></h1>
      <span class="stat">auditor <b>{shortModel(transcript.auditor_model)}</b></span>
      <span class="stat">target <b>{shortModel(transcript.target_model)}</b> · {transcript.scaffold_name}</span>
      <span class="stat"><b>{transcript.branches.length}</b> branches · <b>{transcript.judge.highlights.length}</b> highlights · <b>{totalToolCalls}</b> tool calls · {fmtDuration(transcript.total_time_s)}{#if usage.totalCost} · ${usage.totalCost.toFixed(2)}{/if}</span>
    </div>

    <div class="controls">
      <div class="seg" role="group" aria-label="Transcript detail level">
        <button type="button" aria-pressed={mode === 'beats'} onclick={() => setMode('beats')}>Key beats</button>
        <button type="button" aria-pressed={mode === 'full'} onclick={() => setMode('full')}>Full transcript</button>
      </div>
      <span class="spacer"></span>
      <div class="branchpick">
        <svg class="bicon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="4" cy="3.4" r="1.5"/><circle cx="4" cy="12.6" r="1.5"/><circle cx="12" cy="6" r="1.5"/><path d="M4 4.9v6.2M4 8.3h4.4A3.4 3.4 0 0 0 11.4 6.6"/></svg>
        <select class="branchsel" aria-label="Jump to branch" onchange={onBranchSelect}>
          {#each transcript.branches as b (b.index)}
            <option value={b.index}>{b.label}</option>
          {/each}
        </select>
        <svg class="chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4.5 6 7.5 9 4.5"/></svg>
      </div>
      <button type="button" class="themebtn" onclick={toggleTheme} aria-label="Toggle color theme"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 9.6A5.5 5.5 0 1 1 6.4 3 4.6 4.6 0 0 0 13 9.6z" fill="currentColor"/></svg></button>
    </div>

    <div class="ov" aria-hidden="true">
      <div class="ovcols">
        {#each overview as c (c.id)}
          <i class:hl={c.hl} style="--a:{c.a}; --t:{c.t}"></i>
        {/each}
      </div>
      {#each cutPcts as pct (pct)}
        <div class="branch-line" style="left:{pct}%"></div>
      {/each}
    </div>

    <nav class="timeband" aria-label="Timeline">
      {#each timeline as seg, i (i)}
        <button type="button" class:flag={seg.flagged} style="--w:{seg.count}" onclick={() => jumpTo(seg.anchorId)} title={seg.label}>
          <span class="segnm">{seg.label}</span>
          <span class="segmeta">B{seg.branch}{#if seg.hl} · {seg.hl} hl{/if}</span>
        </button>
      {/each}
    </nav>

    <div class="posline">
      <span class="mono">at <b>{curEventId || transcript.events[0]?.id}</b> · <span>{curBranchLabel}</span></span>
      <span class="lanekey"><span class="k-aud">auditor</span><span class="k-tgt">target</span><span class="k-hl">judge evidence</span><button type="button" class="jlink" onclick={() => scrollToId('judge')}>judge summary</button></span>
    </div>
  </header>

  {#snippet annBtn(h: HL)}
    <button class="ann" class:debug={h.debug} onclick={() => jumpTo(h.event_id)}>
      <span class="lbl"><span class="hn">H{h.n}</span> {h.debug ? 'debug' : h.source}</span>{h.note}
    </button>
  {/snippet}

  {#snippet targetCard(id: string, t: TTurn, no: string, hls: HL[])}
    <div class="tgt-card" class:flag={hls.some((h) => !h.debug)}>
      <span class="lbl">turn {no}</span>
      {#if t.preamble}<div class="ttext"><HighlightedText text={t.preamble} quotes={quotesFor(id)} debugQuotes={debugQuotesFor(id)} /></div>{/if}
      {#each t.calls as c, ci (ci)}
        {@const pc = parseCall(c.head)}
        {@const full = c.id ? fullCallMap.get(c.id) : undefined}
        {@const args = full ? full.arguments : pc.args}
        {@const resultText = cleanResult(full ? (full.result || '') : c.result)}
        <div class="tcall">
          <div class="tcall-fn"><span class="fn">{full?.function || pc.fn || 'call'}</span></div>
          {#if args && typeof args.command === 'string'}
            {@const cq = cmdQuotes(id)}
            {@const cmd = stripTrunc(args.command)}
            {#if typeof args.description === 'string'}<div class="tcall-desc">{args.description}</div>{/if}
            <div class="tcall-cmd"><HighlightedText text={cmd.text} quotes={[...quotesFor(id), ...cq.scheming]} debugQuotes={[...debugQuotesFor(id), ...cq.debug]} />{#if cmd.more}<span class="trunc">⋯ {cmd.more.toLocaleString()} more chars truncated in source</span>{/if}</div>
          {:else if args}
            <div class="tcall-args">
              {#each Object.entries(args) as [k, v] (k)}
                {@const av = stripTrunc(asText(v))}
                <div class="tcall-arg"><span class="argk">{k}</span><span class="argv"><HighlightedText text={av.text} quotes={quotesFor(id)} debugQuotes={debugQuotesFor(id)} />{#if av.more}<span class="trunc">⋯ {av.more.toLocaleString()} more truncated</span>{/if}</span></div>
              {/each}
            </div>
          {:else if pc.argStr}
            <div class="tcall-cmd"><HighlightedText text={stripTrunc(pc.argStr).text} quotes={quotesFor(id)} debugQuotes={debugQuotesFor(id)} /></div>
          {/if}
          {#if resultText}
            {@const res = stripTrunc(resultText)}
            {#if res.text.length > 220 && !quoteInText(id, res.text)}
              <details class="disc tres-fold" open={mode === 'full'}>
                <summary>output · {res.text.split('\n').length} lines{#if res.more} · +{res.more.toLocaleString()} truncated{/if}</summary>
                <div class="tres"><HighlightedText text={res.text} quotes={quotesFor(id)} debugQuotes={debugQuotesFor(id)} />{#if res.more}<span class="trunc">⋯ {res.more.toLocaleString()} more chars truncated in source</span>{/if}</div>
              </details>
            {:else}
              <div class="tres"><HighlightedText text={res.text} quotes={quotesFor(id)} debugQuotes={debugQuotesFor(id)} />{#if res.more}<span class="trunc">⋯ {res.more.toLocaleString()} more chars truncated in source</span>{/if}</div>
            {/if}
          {/if}
        </div>
      {/each}
    </div>
  {/snippet}

  <main class="score">
    <!-- seed instruction -->
    <section class="ev" data-ev="seed" data-branch="1">
      <div class="sp wide">
        <div class="sp-card seeddoc">
          <span class="lbl">system · seed instruction</span>
          <details class="disc" open={mode === 'full'}>
            <summary><span class="lbl">show seed instruction</span></summary>
            <div class="seedbody"><MarkdownText text={transcript.seed_instruction || transcript.title} /></div>
          </details>
        </div>
      </div>
    </section>

    {#each rows as row (row.ev.id + (row.kind === 'cut' ? '-cut' : ''))}
      {#if row.kind === 'cut'}
        {@const ev = row.ev}
        <section class="ev cutrow" id={`branch-${ev.branch}`} data-ev={ev.id} data-branch={ev.branch}>
          <div class="cut"><span>↩ <b>{transcript.branches.find((b) => b.index === ev.branch)?.label || `Branch ${ev.branch}`}</b></span></div>
        </section>
      {:else}
        {@const ev = row.ev}
        <section class="ev" id={ev.id} data-ev={ev.id} data-branch={ev.branch}>
        <span class="nid">{ev.id}</span>

        {#if ev.role === 'assistant'}
          <!-- auditor, left lane -->
          {@const hls = highlightsByEvent.get(ev.id) || []}
          {#if hls.length}
            <div class="ml">{#each hls as h (h.n)}{@render annBtn(h)}{/each}</div>
          {/if}
          <div class="la">
            <div class="aud">
              <span class="lbl">auditor · assistant</span>
              {#if ev.reasoning}
                <div class="reason"><span class="lbl">reasoning</span> <MarkdownText text={ev.reasoning} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} /></div>
              {/if}
              {#if ev.content}
                <MarkdownText text={ev.content} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} />
              {/if}
              {#if ev.tool_calls?.length}
                <div class="callrow">
                  {#each ev.tool_calls as call (call.id)}
                    <div class="call"><span class="fn">{call.function}</span>(<HighlightedText text={callText(call)} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} />)</div>
                  {/each}
                </div>
              {/if}
            </div>
          </div>

        {:else if ev.role === 'tool'}
          {@const hls = highlightsByEvent.get(ev.id) || []}
          {#if isTargetEvent(ev)}
            <!-- target activity, right lane (each card paired with its judge note to the right) -->
            {@const grouped = groupTurns(ev.id, ev.content || '')}
            {@const finalHls = grouped.finalText ? hlsInText(ev.id, grouped.finalText) : []}
            {@const matchedN = new Set([...grouped.groups.flatMap((g) => g.fold ? [] : g.hls.map((h) => h.n)), ...finalHls.map((h) => h.n)])}
            {@const unmatched = hls.filter((h) => !matchedN.has(h.n))}
            <div class="lt lt-wide">
              {#if grouped.groups.length || grouped.finalText}
                <div class="tlabel lbl">{#if grouped.turnCount}{grouped.turnCount} turn{grouped.turnCount === 1 ? '' : 's'}{:else}reply{/if}</div>
                {#if unmatched.length}
                  <div class="turn-row"><div class="turn-main"></div><div class="turn-anns">{#each unmatched as h (h.n)}{@render annBtn(h)}{/each}</div></div>
                {/if}
                {#each grouped.groups as g, gi (gi)}
                  {#if g.fold}
                    <details class="disc turnfold" open={mode === 'full'}>
                      <summary>⋯ {g.turns.length} more turn{g.turns.length === 1 ? '' : 's'} ⋯</summary>
                      <div class="turnfold-body">
                        {#each g.turns as ft, fi (fi)}
                          {@render targetCard(ev.id, ft.t, ft.no, [])}
                        {/each}
                      </div>
                    </details>
                  {:else}
                    <div class="turn-row">
                      <div class="turn-main">{@render targetCard(ev.id, g.t, g.no, g.hls)}</div>
                      <div class="turn-anns">{#each g.hls as h (h.n)}{@render annBtn(h)}{/each}</div>
                    </div>
                  {/if}
                {/each}
                {#if grouped.finalText}
                  <div class="turn-row">
                    <div class="turn-main">
                      <div class="tgt-card" class:flag={finalHls.some((h) => !h.debug)}>
                        <span class="lbl">final message</span>
                        <div class="tmsg"><MarkdownText text={grouped.finalText} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} /></div>
                      </div>
                    </div>
                    <div class="turn-anns">{#each finalHls as h (h.n)}{@render annBtn(h)}{/each}</div>
                  </div>
                {/if}
              {:else}
                <div class="quiet"><span class="lbl">target</span> No visible turn returned.</div>
              {/if}
            </div>
          {:else}
            <!-- auditor tool result, spine -->
            <div class="sp wide">
              <div class="sp-card" class:errc={!!ev.error}>
                <span class="lbl">tool · {ev.tool_name} → auditor{#if ev.duration_s} · {fmtDuration(ev.duration_s)}{/if}</span>
                {#if ev.error}
                  <div class="errmsg">{ev.error.type}: {ev.error.message}</div>
                {:else if ev.content && ev.content.length > 120}
                  <details class="disc" open={mode === 'full' || hls.length > 0} data-pin={hls.length ? 'hl' : null}>
                    <summary><span class="lbl">show output</span></summary>
                    <div class="term"><pre>{ev.content}</pre></div>
                  </details>
                {:else if ev.content}
                  <div class="termline mono"><HighlightedText text={ev.content} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} /></div>
                {/if}
              </div>
            </div>
            {#if hls.length}
              <div class="mr">{#each hls as h (h.n)}{@render annBtn(h)}{/each}</div>
            {/if}
          {/if}

        {:else if ev.role === 'user'}
          <!-- auditor-injected user message, spine -->
          {@const hls = highlightsByEvent.get(ev.id) || []}
          <div class="sp">
            <div class="sp-card usermsg">
              <span class="lbl">auditor → target · user message</span>
              {#if ev.content}<div class="umbody"><MarkdownText text={ev.content} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} /></div>{/if}
            </div>
          </div>
          {#if hls.length}
            <div class="mr">{#each hls as h (h.n)}{@render annBtn(h)}{/each}</div>
          {/if}

        {:else}
          <!-- system event, spine -->
          <div class="sp wide">
            <div class="sp-card">
              <span class="lbl">system</span>
              {#if ev.content}<div class="umbody"><MarkdownText text={ev.content} quotes={quotesFor(ev.id)} debugQuotes={debugQuotesFor(ev.id)} /></div>{/if}
            </div>
          </div>
        {/if}
        </section>
      {/if}
    {/each}
  </main>

  <!-- judge -->
  <section class="judge" id="judge">
    <div class="judge-card">
      <h2>Judge report</h2>
      <span class="lbl muted">{shortModel(transcript.auditor_model)} · {transcript.judge.highlights.length} highlights</span>
      <div class="jgrid">
        <div class="scores">
          <div class="scores-cap lbl">notable dimensions · <span class="k-concern">concerning</span> behavior scored high (≥6) · <span class="k-weak">quality</span> scored low (≤4)</div>
          {#each scoreRows as s (s.name)}
            <div class="srow" class:concern={s.flag === 'concerning'} class:weak={s.flag === 'weak'}>
              <span>{s.name.replace(/_/g, ' ')}{#if s.positive}<span class="dir" title="higher is better">▲</span>{/if}<span class="sbar" class:pos={s.positive}><i style="--v:{s.value * 10}%"></i></span></span>
              <span class="mono">{s.value}</span>
            </div>
          {/each}
          {#if !scoreRows.length}<div class="muted">Nothing notable — no concerning behavior and no weak quality scores.</div>{/if}
          <details class="disc allscores">
            <summary>all {allScores.length} judged dimensions</summary>
            <div class="allscores-body">
              {#each allScores as s (s.name)}
                <div class="arow" class:deb={s.positive} class:concern={s.flag === 'concerning'} class:weak={s.flag === 'weak'}><span>{s.name.replace(/_/g, ' ')}{#if s.positive}<span class="dir">▲</span>{/if}</span><span class="mono">{s.value}</span></div>
              {/each}
            </div>
          </details>
        </div>
        <div class="jsummary">
          <MarkdownText text={transcript.judge.summary || Object.values(transcript.judge.summaries || {}).join('\n\n')} />
        </div>
      </div>
      <div class="hlist-cap lbl">{hAll.length} highlighted moments — quotes the judge flagged · <span class="hn">scheming</span> · <span class="deb-k">debug/quality</span></div>
      <ul class="hlist">
        {#each hAll as h (h.n)}
          <li>
            <button class:deb={h.debug} onclick={() => jumpTo(h.event_id)}>
              <span class="he"><span class="hn">H{h.n}</span><span class="eid">{h.event_id}</span></span>
              <span class="src">{h.debug ? 'debug' : h.source}</span>
              <span class="hnote">{h.note}</span>
            </button>
          </li>
        {/each}
      </ul>
      {#if usage.rows.length}
        <div class="usage">
          {#each usage.rows as r (r.role)}
            <span>{r.role} · {r.inTok} in / {r.outTok} out · {r.calls} calls{#if r.cost} · ${r.cost.toFixed(2)}{/if}</span>
          {/each}
          {#if usage.totalCost}<span>total · ${usage.totalCost.toFixed(2)} · {fmtDuration(transcript.total_time_s)}</span>{/if}
        </div>
      {/if}
    </div>
  </section>

  <!-- branch comparison -->
  {#if branchStats.length > 1}
    <section class="compare" id="compare">
      <div class="compare-card">
        <h2>Branch comparison</h2>
        <p class="sub">The auditor rolls back and re-runs; behavior deltas between branches are the measurement. Each column lists the judge's highlighted observations for that branch.</p>
        <div class="cmp" style="grid-template-columns: repeat({branchStats.length}, 1fr)">
          {#each branchStats as bs (bs.branch.index)}
            <div class="chead" class:flag={bs.highlights.some((h) => !debugHl(h))}>
              <span class="tag">B{bs.branch.index}</span> {bs.branch.label}
            </div>
          {/each}
          {#each branchStats as bs (bs.branch.index)}
            <div class="cstat mono">{bs.events} events · {bs.auditorCalls} auditor calls · {bs.targetReplies} target replies</div>
          {/each}
          {#each branchStats as bs (bs.branch.index)}
            <div class="ccell">
              {#if bs.highlights.length}
                <ul>
                  {#each bs.highlights as h (h.note)}
                    <li class:debug={debugHl(h)}>
                      <button onclick={() => jumpTo(h.event_id)}><span class="src">{h.source}</span> {h.note} <span class="eid">{h.event_id}</span></button>
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="muted">No highlighted observations.</p>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    </section>
  {/if}
</div>
{/if}

<style>
  /* ---- states ---- */
  .state { min-height: 100vh; display: flex; align-items: center; justify-content: center; gap: 12px; color: var(--text-muted); }
  .state-card { width: min(520px, calc(100vw - 32px)); padding: 28px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-md); }
  .state-card h1 { margin: 4px 0 12px; font-size: 1.3rem; }
  .state-card .kick { color: var(--danger); font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; }
  .state-card button { border: 1px solid var(--border); background: var(--surface-alt); border-radius: var(--radius-sm); padding: 7px 12px; cursor: pointer; }
  .hint { font-size: 0.8rem; }
  .loader { width: 18px; height: 18px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ---- lane palette — ported from the longform-lanes-v2 mockup ---- */
  .lanes-root {
    /* dark (default; app sets data-theme=dark) */
    --bg: #121613; --surface: #191f1a; --surface-alt: #212822; --surface-sunk: #10150f;
    --border: #2b332c; --border-strong: #4c574e;
    --text: #dfe5dd; --text-muted: #8d978e; --text-faint: #6e7b6e;
    --auditor: #8fb9cf; --target: #d9ad66;
    --aud: #8fb9cf; --tgt: #d9ad66;
    --aud-line: #33505f; --aud-bg: #182229; --tgt-line: #5c4722; --tgt-bg: #241d10;
    --hl: #e874ac; --hl-bg: #3a1628; --hl-ink: #f090bd;
    --ok: #6cc191; --ok-bg: #14241a; --ok-ink: #8fd6ad;
    --railc: #4c574e; --chipbg: #212822;
    --term-bg: #0d110e; --term-ink: #c2ccbf; --term-dim: #6e7b6e; --term-line: #28302a;
    --danger: #e58163; --danger-soft: #361b10;
    --good: #6cc191; --good-soft: #14241a;
    --warn: #d6a63c; --warn-ink: #e8bf63;

    --font-sans: system-ui, 'Segoe UI', -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif;
    --font-serif: ui-serif, 'Iowan Old Style', 'Palatino Linotype', Charter, Georgia, serif;
    --font-mono: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace;
    --mono: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace;

    min-height: 100vh; background: var(--bg); color: var(--text);
    font-family: var(--font-sans); font-size: 15px; line-height: 1.5;
  }
  :global(:root[data-theme='light']) .lanes-root {
    --bg: #eef0ea; --surface: #f8f9f5; --surface-alt: #e9ece5; --surface-sunk: #e4e7df;
    --border: #d3d9d0; --border-strong: #a7b1a6;
    --text: #20261f; --text-muted: #6b756c; --text-faint: #8a938a;
    --auditor: #2e5568; --target: #8a5b1d;
    --aud: #2e5568; --tgt: #8a5b1d;
    --aud-line: #a9c0cb; --aud-bg: #eef3f4; --tgt-line: #d8c19a; --tgt-bg: #f5efe1;
    --hl: #a91e60; --hl-bg: #f6dfe9; --hl-ink: #8c1750;
    --ok: #2f7d55; --ok-bg: #e4efe6; --ok-ink: #256545;
    --railc: #a7b1a6; --chipbg: #e9ece5;
    --term-bg: #1c231d; --term-ink: #c9d3c6; --term-dim: #7f8d7f; --term-line: #333d33;
    --danger: #b23c1e; --danger-soft: #f4e2da;
    --good: #2f7d55; --good-soft: #e4efe6;
    --warn: #a6791e; --warn-ink: #85610f;
  }
  .lanes-root .meta h1, .lanes-root .judge-card h2, .lanes-root .compare-card h2 { font-family: var(--font-serif); }
  .lanes-root .aud, .lanes-root .jsummary { font-family: var(--font-serif); }
  .lanes-root.lanes-root :global(mark) {
    background: var(--hl-bg); box-shadow: inset 0 -2px 0 var(--hl); color: inherit; padding: 0 1px; border-radius: 0;
  }
  .lanes-root.lanes-root :global(mark.hl-debug) {
    background: transparent; box-shadow: none; border-bottom: 1.5px dashed var(--railc); color: var(--text-muted);
  }
  .hn { font-family: var(--mono); font-weight: 700; color: var(--hl-ink); }
  .debug .hn, .ann.debug .hn, button.deb .hn { color: var(--text-muted); }
  .lbl { font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--text-faint); }
  .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .muted { color: var(--text-muted); }

  /* ---- topbar ---- */
  .topbar { position: sticky; top: 0; z-index: 20; background: var(--bg); border-bottom: 1px solid var(--border); padding: 9px 20px 0; }
  .meta { display: flex; flex-wrap: wrap; gap: 5px 16px; align-items: baseline; max-width: 1480px; margin: 0 auto; }
  .meta .brand { border: 1px solid var(--border); background: var(--surface-sunk); color: var(--text-muted); border-radius: 7px; padding: 3px 9px; font-size: 11.5px; cursor: pointer; }
  .meta .brand:hover:not(:disabled) { color: var(--text); border-color: var(--border-strong); }
  .meta h1 { font: 600 15px/1.2 var(--font-sans); margin: 0; letter-spacing: -0.01em; }
  .meta h1 .mono { font-size: 11.5px; color: var(--text-faint); font-weight: 400; }
  .meta .stat { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .meta .stat b { color: var(--text); font-weight: 600; }

  .controls { display: flex; flex-wrap: wrap; gap: 10px 12px; align-items: center; max-width: 1480px; margin: 10px auto 2px; }
  .spacer { flex: 1; }
  .seg { display: inline-flex; padding: 3px; gap: 2px; background: var(--surface-sunk); border: 1px solid var(--border); border-radius: 9px; }
  .seg button { appearance: none; border: 0; background: transparent; cursor: pointer; white-space: nowrap; font: inherit; font-size: 12px; font-weight: 500; color: var(--text-muted); padding: 5px 14px; border-radius: 6px; transition: background .16s, color .16s, box-shadow .16s; }
  .seg button:hover { color: var(--text); }
  .seg button[aria-pressed='true'] { background: var(--surface-alt); color: var(--text); font-weight: 600; box-shadow: var(--shadow-sm), inset 0 0 0 1px var(--border); }
  .branchpick { position: relative; display: inline-flex; align-items: center; }
  .branchpick .bicon { position: absolute; left: 11px; width: 13px; height: 13px; color: var(--text-muted); pointer-events: none; }
  .branchpick .chev { position: absolute; right: 10px; width: 11px; height: 11px; color: var(--text-muted); pointer-events: none; }
  .branchsel { appearance: none; -webkit-appearance: none; font: inherit; font-size: 12px; font-weight: 600; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 6px 30px 6px 31px; cursor: pointer; }
  .branchsel:hover { border-color: var(--border-strong); }
  .themebtn { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 31px; appearance: none; cursor: pointer; color: var(--text-muted); background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
  .themebtn:hover { color: var(--text); border-color: var(--border-strong); }
  .themebtn svg { width: 15px; height: 15px; }

  .ov { position: relative; max-width: 1480px; margin: 9px auto 0; height: 42px; border: 1px solid var(--border); background: var(--surface); }
  .branch-line { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1.5px dashed var(--border-strong); pointer-events: none; z-index: 4; }
  .ovcols { display: flex; height: 100%; background: linear-gradient(var(--railc), var(--railc)) center/100% 1px no-repeat; }
  .ovcols i { flex: 1; position: relative; min-width: 0; }
  .ovcols i::before { content: ""; position: absolute; left: 18%; right: 18%; bottom: 50%; height: calc(var(--a, 0) * 46%); background: var(--aud); }
  .ovcols i::after { content: ""; position: absolute; left: 18%; right: 18%; top: 50%; height: calc(var(--t, 0) * 46%); background: var(--tgt); }
  .ovcols i.hl { box-shadow: inset 0 -3px 0 var(--hl); }

  .timeband { display: flex; gap: 2px; max-width: 1480px; margin: 5px auto 0; }
  .timeband button { flex: var(--w, 1); min-width: 0; text-align: left; cursor: pointer; appearance: none; background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--railc); padding: 5px 9px 6px; font: inherit; color: var(--text-muted); display: flex; flex-direction: column; gap: 2px; }
  .timeband button:hover { border-color: var(--text); }
  .timeband button.flag { border-top-color: var(--hl); }
  .timeband .segnm { font-size: 10.5px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-transform: capitalize; }
  .timeband button.flag .segnm { color: var(--hl-ink); }
  .timeband .segmeta { font-size: 9.5px; font-family: var(--mono); letter-spacing: 0.03em; }
  .jlink { appearance: none; border: 0; background: transparent; color: var(--text-muted); cursor: pointer; font: inherit; font-family: var(--mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; padding: 0; text-decoration: underline; text-underline-offset: 2px; }
  .jlink:hover { color: var(--text); }
  .turnfold { margin: 2px 0; border: 1.5px dashed var(--railc); border-radius: 7px; background: var(--bg); }
  .turnfold > summary { cursor: pointer; list-style: none; font-family: var(--mono); font-size: 12px; color: var(--text-muted); padding: 9px 14px; letter-spacing: 0.02em; }
  .turnfold > summary::-webkit-details-marker { display: none; }
  .turnfold[open] > summary { border-bottom: 1px dashed var(--railc); }
  .turnfold-body { display: flex; flex-direction: column; gap: 10px; padding: 10px 12px 12px; }

  .posline { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; max-width: 1480px; margin: 0 auto; padding: 7px 0 9px; font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .posline b { color: var(--text); }
  .lanekey { display: flex; gap: 14px; flex-wrap: wrap; font-family: var(--mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; }
  .lanekey span::before { content: ""; display: inline-block; width: 9px; height: 9px; margin-right: 5px; }
  .k-aud::before { background: var(--aud); } .k-tgt::before { background: var(--tgt); } .k-hl::before { background: var(--hl); }

  /* ---- score grid ---- */
  .score { max-width: 1480px; margin: 0 auto; padding: 18px 20px 40px; }
  .ev { display: grid; position: relative; column-gap: 20px; padding: 9px 0; grid-template-columns: minmax(0, 158px) minmax(0, 1fr) 56px minmax(0, 1fr) minmax(0, 158px); }
  .ev::before { content: ""; position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--railc); opacity: 0.5; }
  .ev.cutrow::before { display: none; }
  .nid { grid-column: 3; grid-row: 1; justify-self: center; align-self: start; z-index: 1; font-family: var(--mono); font-size: 10.5px; color: var(--text-faint); background: var(--bg); border: 1px solid var(--railc); border-radius: 9px; padding: 1px 7px; font-variant-numeric: tabular-nums; }
  .ml { grid-column: 1; grid-row: 1; } .la { grid-column: 2; grid-row: 1; }
  .lt { grid-column: 4; grid-row: 1; } .mr { grid-column: 5; grid-row: 1; }
  .lt { display: flex; flex-direction: column; gap: 10px; }
  .ml, .mr { display: flex; flex-direction: column; gap: 8px; padding-top: 4px; }

  .aud { position: relative; background: var(--surface); border: 1px solid var(--border); border-top: 4px double var(--aud); padding: 12px 16px 13px; font-size: 14.5px; line-height: 1.55; }
  .aud .lbl { color: var(--aud); }
  .reason { color: var(--text-muted); border-left: 2px dotted var(--aud); padding-left: 11px; margin: 0.5em 0; font-style: italic; }
  .reason .lbl { font-style: normal; display: block; margin-bottom: 2px; }
  .callrow { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; margin-top: 10px; }
  .call { max-width: 100%; font-family: var(--mono); font-size: 12px; line-height: 1.45; background: var(--chipbg); border: 1px solid var(--border); border-right: 3px solid var(--railc); padding: 6px 10px; white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; }
  .call .fn { color: var(--aud); font-weight: 600; }

  .tlabel { display: block; color: var(--tgt); margin-bottom: 8px; }
  .lt-wide { grid-column: 4 / 6; }
  .turn-row { display: flex; gap: 14px; align-items: flex-start; }
  .turn-main { flex: 1; min-width: 0; }
  .turn-anns { flex: 0 0 208px; display: flex; flex-direction: column; gap: 6px; }
  .tgt-card { position: relative; background: var(--tgt-bg); border: 1px solid var(--tgt-line); border-left: 5px solid var(--tgt); border-radius: 0 7px 7px 0; padding: 11px 14px 12px; font-size: 14px; line-height: 1.5; }
  .tgt-card.flag { box-shadow: 0 0 0 1px var(--hl); }
  .tgt-card > .lbl { color: var(--tgt); display: block; margin-bottom: 6px; }
  .tmsg { font-size: 13.5px; line-height: 1.55; }
  .tmsg :global(p) { margin: 0.4em 0; }
  .tmsg :global(ol), .tmsg :global(ul) { margin: 0.4em 0; padding-left: 1.3em; }
  .tmsg :global(li) { margin: 0.2em 0; }
  .ttext { white-space: pre-wrap; word-break: break-word; color: var(--text-muted); font-style: italic; border-left: 2px dotted var(--tgt); padding-left: 10px; margin: 2px 0 4px; }
  .tcall { font-family: var(--mono); font-size: 11.6px; line-height: 1.5; background: var(--surface); border: 1px solid var(--tgt-line); border-radius: 3px; padding: 6px 9px; margin: 7px 0 0; }
  .tcall-fn { margin-bottom: 5px; }
  .tcall .fn { color: var(--tgt); font-weight: 700; }
  .tcall-desc { font-size: 11px; color: var(--text-faint); font-style: italic; margin-bottom: 4px; }
  .tcall-cmd { font-family: var(--mono); font-size: 11.6px; line-height: 1.5; background: var(--surface-sunk); color: var(--text); border-left: 2px solid var(--tgt-line); border-radius: 3px; padding: 6px 9px; white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; }
  .trunc { display: inline-block; margin-top: 4px; font-family: var(--mono); font-size: 10px; color: var(--text-faint); font-style: italic; letter-spacing: 0.02em; }
  .tcall-args { display: flex; flex-direction: column; gap: 5px; }
  .tcall-arg { display: flex; gap: 8px; align-items: baseline; }
  .argk { color: var(--text-faint); font-weight: 400; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.06em; flex: none; min-width: 78px; }
  .argv { color: var(--text); white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; min-width: 0; }
  .tres { color: var(--text-muted); border-top: 1px dashed var(--tgt-line); margin-top: 5px; padding-top: 5px; white-space: pre-wrap; word-break: break-word; }
  .tres-fold { margin-top: 5px; border-top: 1px dashed var(--tgt-line); }
  .tres-fold > summary { cursor: pointer; list-style: none; padding: 5px 0 0; color: var(--text-faint); font-size: 11px; letter-spacing: 0.02em; }
  .tres-fold > summary::-webkit-details-marker { display: none; }
  .tres-fold > summary::before { content: "＋ "; color: var(--hl-ink); font-weight: 700; }
  .tres-fold[open] > summary::before { content: "－ "; }
  .tres-fold .tres { border-top: 0; margin-top: 3px; }
  .quiet { border: 1.5px dashed var(--railc); border-radius: 7px; color: var(--text-muted); font-size: 12.5px; padding: 12px 14px; }

  .sp { grid-column: 2 / 5; grid-row: 1; justify-self: center; width: min(700px, 100%); z-index: 1; }
  .sp.wide { width: min(880px, 100%); }
  .sp-card { background: var(--surface); border: 1px solid var(--border); border-radius: 3px; padding: 9px 13px; font-size: 13px; }
  .sp-card .lbl { color: var(--text-muted); }
  .usermsg { border-left: 3px solid var(--aud); }
  .umbody { margin-top: 5px; font-size: 13.5px; }
  .termline { margin-top: 5px; font-size: 12px; color: var(--text-muted); white-space: pre-wrap; word-break: break-word; }
  .term { background: var(--term-bg); color: var(--term-ink); border: 1px solid var(--term-line); border-radius: 4px; margin-top: 8px; }
  .term pre { margin: 0; padding: 10px 14px; font-size: 12px; line-height: 1.5; font-variant-numeric: tabular-nums; white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; }
  .errc { border-left: 4px solid var(--danger); background: var(--danger-soft); }
  .errmsg { font-family: var(--mono); font-size: 12.5px; color: var(--danger); margin-top: 5px; }

  .seeddoc { border-top: 4px double var(--railc); }
  .seedbody { margin-top: 8px; font-size: 12.5px; column-count: 2; column-gap: 26px; }
  .seedbody :global(h1), .seedbody :global(h2), .seedbody :global(h3) { break-after: avoid; }

  /* disclosures */
  details.disc > summary { cursor: pointer; list-style: none; }
  details.disc > summary::-webkit-details-marker { display: none; }
  .sp-card details.disc > summary { color: var(--text-muted); }
  .sp-card details.disc > summary::before, .seeddoc details.disc > summary::before { content: "＋ "; font-family: var(--mono); color: var(--hl-ink); font-weight: 700; }
  .sp-card details.disc[open] > summary::before, .seeddoc details.disc[open] > summary::before { content: "－ "; }

  /* branch cut */
  .cut { grid-column: 1 / -1; grid-row: 1; z-index: 2; margin: 16px 0 6px; border-top: 2px solid var(--text); display: flex; justify-content: center; }
  .cut span { transform: translateY(-55%); background: var(--bg); border: 1.5px solid var(--text); padding: 4px 14px; font-family: var(--mono); font-size: 11.5px; }
  .cut b { color: var(--text); }

  /* margin annotations */
  .ann { text-align: left; font-size: 12px; line-height: 1.45; color: var(--text); border: 0; border-left: 3px solid var(--hl); background: var(--surface); padding: 7px 9px; cursor: pointer; font-family: inherit; }
  .ann:hover { background: var(--surface-alt); }
  .ann .lbl { color: var(--hl-ink); display: block; margin-bottom: 2px; }
  .ann .hn { margin-right: 5px; }
  .ann.debug { border-left-color: var(--railc); color: var(--text-muted); }
  .ann.debug .lbl { color: var(--text-muted); }
  .ml .ann { text-align: right; border-left: 0; border-right: 3px solid var(--hl); }
  .ml .ann.debug { border-right-color: var(--railc); }

  :global(.flash) { animation: flash 1.4s ease-out; }
  @keyframes flash { 0% { box-shadow: 0 0 0 2px var(--hl); } 100% { box-shadow: 0 0 0 8px transparent; } }

  /* ---- judge ---- */
  .judge { max-width: 1480px; margin: 0 auto; padding: 0 20px 30px; }
  .judge-card { border: 1px solid var(--border); border-top: 4px double var(--hl); background: var(--surface); padding: 20px 24px; }
  .judge-card h2 { font: 600 16px/1.2 var(--font-sans); margin: 0 0 4px; }
  .jgrid { display: grid; grid-template-columns: minmax(240px, 320px) minmax(0, 1fr); gap: 26px; margin-top: 14px; }
  .scores { display: flex; flex-direction: column; gap: 8px; }
  .scores-cap { color: var(--text-faint); text-transform: none; letter-spacing: 0; font-size: 10.5px; margin-bottom: 2px; }
  .allscores { margin-top: 6px; border-top: 1px solid var(--border); padding-top: 6px; }
  .allscores > summary { cursor: pointer; list-style: none; font-family: var(--mono); font-size: 10.5px; color: var(--text-muted); }
  .allscores > summary::-webkit-details-marker { display: none; }
  .allscores > summary::before { content: "＋ "; color: var(--hl-ink); font-weight: 700; }
  .allscores[open] > summary::before { content: "－ "; }
  .allscores-body { display: grid; grid-template-columns: 1fr auto; gap: 1px 12px; margin-top: 8px; max-height: 260px; overflow-y: auto; }
  .arow { display: contents; }
  .arow > span { font-size: 11px; padding: 2px 0; text-transform: capitalize; }
  .arow > .mono { text-align: right; color: var(--text); }
  .arow.deb > span { color: var(--text-faint); }
  .hlist-cap { color: var(--text-faint); text-transform: none; letter-spacing: 0; font-size: 10.5px; margin: 16px 0 6px; }
  .hlist-cap .deb-k { color: var(--text-faint); }
  .srow { display: grid; grid-template-columns: 1fr 30px; gap: 8px; align-items: center; font-size: 12.5px; }
  .srow > span:first-child { text-transform: capitalize; }
  .srow .mono { text-align: right; }
  .srow .dir { color: var(--text-faint); font-size: 8px; margin-left: 4px; vertical-align: 1px; }
  .sbar { display: block; height: 7px; background: var(--surface-sunk); border: 1px solid var(--border); position: relative; margin-top: 3px; }
  .sbar i { position: absolute; inset: 0; width: var(--v); background: var(--railc); }
  /* positive dims fill from the right so a short bar reads as "low = bad" */
  .sbar.pos i { left: auto; right: 0; }
  .srow.concern .sbar i { background: var(--hl); }
  .srow.concern .mono { color: var(--hl-ink); font-weight: 700; }
  .srow.weak .sbar i { background: var(--warn); }
  .srow.weak .mono { color: var(--warn-ink); font-weight: 700; }
  .srow.weak .dir { color: var(--warn-ink); }
  .k-concern { color: var(--hl-ink); } .k-weak { color: var(--warn-ink); }
  .arow.concern > .mono { color: var(--hl-ink); font-weight: 700; }
  .arow.weak > .mono { color: var(--warn-ink); font-weight: 700; }
  .arow .dir { color: var(--text-faint); font-size: 8px; margin-left: 4px; }
  .jsummary { font-size: 14px; line-height: 1.6; }
  .hlist { list-style: none; margin: 14px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .hlist button { display: grid; grid-template-columns: 42px 96px 1fr; gap: 10px; align-items: center; width: 100%; text-align: left; border: 1px solid var(--border); background: var(--bg); color: var(--text); font: inherit; font-size: 12.5px; padding: 6px 8px; cursor: pointer; }
  .hlist button:hover { border-color: var(--hl); }
  .hlist button.deb { border-left: 3px solid var(--railc); }
  .hlist button:not(.deb) { border-left: 3px solid var(--hl); }
  .he { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.15; }
  .he .hn { font-size: 12px; }
  .he .eid { font-family: var(--mono); font-size: 9.5px; color: var(--text-faint); }
  .hlist .src { font-family: var(--mono); font-size: 10px; color: var(--hl-ink); text-transform: uppercase; letter-spacing: 0.03em; overflow: hidden; text-overflow: ellipsis; }
  .hlist button.deb .src { color: var(--text-faint); }
  .hlist .hnote { color: var(--text-muted); }
  .usage { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 11.5px; color: var(--text-muted); font-family: var(--mono); font-variant-numeric: tabular-nums; }

  /* ---- comparison ---- */
  .compare { max-width: 1480px; margin: 0 auto; padding: 0 20px 70px; }
  .compare-card { border: 1px solid var(--border); background: var(--surface); padding: 20px 24px; }
  .compare-card h2 { font: 600 16px/1.2 var(--font-sans); margin: 0 0 3px; }
  .compare-card .sub { font-size: 12.5px; color: var(--text-muted); margin: 0 0 14px; max-width: 70ch; }
  .cmp { display: grid; gap: 1px; background: var(--border); border: 1px solid var(--border); }
  .cmp > div { background: var(--surface); padding: 10px 13px; }
  .cmp .chead { background: var(--surface-alt); font-weight: 600; font-size: 12.5px; display: flex; align-items: center; gap: 8px; }
  .cmp .chead .tag { font-family: var(--mono); font-size: 10px; letter-spacing: 0.05em; border-radius: 4px; padding: 1px 7px; background: var(--surface-sunk); border: 1px solid var(--border); }
  .cmp .chead.flag .tag { background: var(--hl-bg); color: var(--hl-ink); border-color: var(--hl); }
  .cmp .cstat { font-family: var(--mono); font-size: 10.5px; color: var(--text-muted); border-bottom: 1px solid var(--border); }
  .cmp .ccell ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
  .cmp .ccell button { text-align: left; width: 100%; border: 0; background: transparent; color: var(--text); font: inherit; font-size: 12.5px; line-height: 1.45; cursor: pointer; padding: 0; border-left: 3px solid var(--hl); padding-left: 9px; }
  .cmp .ccell li.debug button { border-left-color: var(--railc); color: var(--text-muted); }
  .cmp .ccell button:hover { color: var(--hl-ink); }
  .cmp .ccell .src { font-family: var(--mono); font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--hl-ink); }
  .cmp .ccell .eid { font-family: var(--mono); font-size: 9.5px; color: var(--text-faint); }

  @media (max-width: 1220px) {
    .ev { grid-template-columns: minmax(0, 1fr) 48px minmax(0, 1fr); }
    .la { grid-column: 1; } .nid { grid-column: 2; } .lt { grid-column: 3; }
    .lt-wide { grid-column: 3; }
    .turn-anns { flex-basis: 168px; }
    .sp { grid-column: 1 / 4; } .cut { grid-column: 1 / -1; }
    .ml, .mr { grid-row: 2; padding-top: 8px; }
    .ml { grid-column: 1 / 2; } .mr { grid-column: 3 / 4; }
    .ml .ann { text-align: left; border-right: 0; border-left: 3px solid var(--hl); }
    .ml .ann.debug { border-left-color: var(--railc); }
    .seedbody { column-count: 1; }
  }
  @media (max-width: 900px) {
    .turn-row { flex-direction: column; }
    .turn-anns { flex-basis: auto; }
  }
  @media (max-width: 760px) {
    .ev { display: block; padding: 8px 0; }
    .ev::before { left: 8px; margin-left: 0; }
    .nid { display: inline-block; margin-left: 24px; margin-bottom: 6px; }
    .la, .lt, .ml, .mr, .sp { display: block; width: auto; margin-left: 24px; }
    .lt > * { margin-bottom: 10px; }
    .jgrid { grid-template-columns: 1fr; }
    .cmp { grid-template-columns: 1fr !important; }
  }
</style>
