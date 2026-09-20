/** Typed API models mirroring the DataHek backend Pydantic models. */

export interface Health {
  status: string;
  version: string;
  auth_mode?: string;
  capabilities: Record<string, boolean>;
  entitlements: Record<string, number>;
  providers: string[];
}

export interface Connection {
  id: string;
  name: string;
  provider: string;
  host: string | null;
  port: number | null;
  database: string | null;
}

export interface ConnectionCreate {
  name: string;
  provider: string;
  host?: string;
  port?: number;
  database?: string;
  settings?: Record<string, string>;
}

export interface AskResponse {
  clarification: string | null;
  answer: string;
  columns: string[] | null;
  rows: Record<string, unknown>[] | null;
  row_count: number;
  truncated: boolean;
  plan_sources: string[];
  conversation_id: string | null;
}

export interface Conversation {
  id: string;
  org_id: string;
  project_id: string;
  title: string | null;
  messages: { role: string; content: string; message_type?: string }[];
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  updated_at?: string;
}

export interface Prompt {
  id: string;
  name: string;
  content: string;
}

export interface EvaluationReport {
  total: number;
  passed: number;
  pass_rate: number;
  cases: { name: string; passed: boolean; scores: Record<string, number>; error: string | null }[];
}

export type ErrorCode =
  | 'INTERNAL' | 'VALIDATION' | 'NOT_FOUND' | 'UNAUTHORIZED' | 'FORBIDDEN'
  | 'QUERY_DENIED' | 'QUERY_TIMEOUT' | 'RATE_LIMITED' | 'CONNECTION_FAILED'
  | 'CONNECTION_NOT_FOUND' | 'CONNECTION_EXISTS' | 'UNSUPPORTED_PROVIDER'
  | 'PLAN_INVALID' | 'RESULT_TOO_LARGE' | 'MODEL_UNAVAILABLE'
  | 'CONVERSATION_NOT_FOUND';

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(public code: ErrorCode, message: string, public status: number, public details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
  }
}

/** SSE stream events from /ask/stream. */
export type StreamEvent =
  | { type: 'start'; conversation_id: string | null; columns: string[]; row_count: number }
  | { type: 'token'; content: string }
  | { type: 'rows'; rows: Record<string, unknown>[]; columns: string[]; row_count: number; truncated: boolean }
  | { type: 'progress'; stage: string; message: string }
  | { type: 'verification'; ok: boolean; note: string }
  | { type: 'redactions'; categories: string[] }
  | { type: 'steps'; steps: { question: string; row_count: number | null; sql: string | null }[] }
  | { type: 'suggestions'; items: string[] }
  | { type: 'error'; code?: string; message: string }
  | { type: 'clarification'; text: string }
  | { type: 'done' };