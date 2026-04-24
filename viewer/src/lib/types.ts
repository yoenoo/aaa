// Schema for a petri audit transcript. Produced by dump_log.py, consumed by App.svelte.

export interface TranscriptData {
  id: string;
  title: string;
  auditor_model: string;
  target_model: string;
  scaffold_name: string;
  seed_name: string;
  seed_instruction: string;
  auditor_system_prompt?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  total_time_s?: number | null;
  role_usage?: Record<string, RoleUsage>;
  judge: JudgeOutput;
  branches: Branch[];
  events: Event[];
}

export interface RoleUsage {
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  input_tokens_cache_read: number;
  input_tokens_cache_write: number;
  reasoning_tokens: number;
  total_cost: number | null;
  calls: number;
}

export interface ToolError {
  type: string;
  message: string;
}

export interface JudgeOutput {
  summary: string;
  summaries: Record<string, string>;
  sources: string[];
  scores: Record<string, number>;
  score_sources: Record<string, string>;
  score_descriptions: Record<string, string>;
  parse_status: Record<string, string>;
  highlights: Highlight[];
}

export interface Highlight {
  event_id: string;
  quoted_text: string;
  note: string;
}

export interface Branch {
  index: number;
  label: string;
  start_event_id: string;
  end_event_id: string;
  event_count?: number;
  duration_s?: number;
  highlight_count?: number;
}

export type Role = 'system' | 'user' | 'assistant' | 'tool';

interface BaseEvent {
  id: string;
  branch: number;
  role: Role;
  duration_s?: number | null;
}

export interface SystemEvent extends BaseEvent {
  role: 'system';
  content: string;
}

export interface UserEvent extends BaseEvent {
  role: 'user';
  content: string;
}

export interface AssistantEvent extends BaseEvent {
  role: 'assistant';
  content: string;
  reasoning?: string;
  redacted_reasoning_chars?: number;
  tool_calls: ToolCall[];
  auditor_context?: ContextMessage[] | null;
}

export interface ContextMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  preview: string;
  length: number;
  event_id: string | null;
  tool_calls?: { function: string; id: string }[];
  tool_call_id?: string;
  function?: string;
}

export interface TargetToolCall {
  id: string;
  function: string;
  arguments: Record<string, unknown>;
  result: string | null;
}

export interface TargetTurn {
  text: string;
  reasoning: string;
  redacted_reasoning_chars?: number;
  tool_calls: TargetToolCall[];
}

export interface ToolEvent extends BaseEvent {
  role: 'tool';
  tool_call_id: string;
  tool_name: string;
  content: string;
  error?: ToolError | null;
  target_activity?: TargetTurn[];
  target_system_prompt?: string;
}

export type Event = SystemEvent | UserEvent | AssistantEvent | ToolEvent;

export interface ToolCall {
  id: string;
  function: string;
  arguments: Record<string, unknown>;
}

export interface AuditIndexEntry {
  id: string;
  title: string;
  auditor_model: string;
  target_model: string;
  scaffold_name: string;
  seed_name: string;
  created_at: string;
  completed_at?: string;
  total_time_s?: number | null;
  event_count: number;
  branch_count: number;
  highlight_count: number;
  scores: Record<string, number>;
  top_score: number | null;
}
