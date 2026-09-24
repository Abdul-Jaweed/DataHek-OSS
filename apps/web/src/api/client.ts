import { ApiError, ApiErrorBody, type Connection, type ConnectionCreate, type Conversation, type ConversationSummary, type EvaluationReport, type Health, type Prompt } from './types';

const API_KEY_STORAGE = 'datahek-api-key';

export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'content-type': 'application/json', ...(init.headers as Record<string, string> | undefined) };
  const key = getApiKey();
  if (key) headers['X-API-Key'] = key;

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error */
    }
    if (body?.code) throw new ApiError(body.code, body.message, res.status, body.details);
    throw new ApiError('INTERNAL', `Request failed (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>('/health'),
  login: (username: string, password: string) =>
    request<{ token: string; user: string; roles: string[]; provider: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  listConnections: () => request<Connection[]>('/connections'),
  createConnection: (body: ConnectionCreate) => request<Connection>('/connections', { method: 'POST', body: JSON.stringify(body) }),
  testConnection: (body: ConnectionCreate) => request<{ ok: boolean; latency_ms?: number; error?: string }>('/connections/test', { method: 'POST', body: JSON.stringify(body) }),
  deleteConnection: (id: string) => request<void>(`/connections/${id}`, { method: 'DELETE' }),
  updateConnection: (id: string, body: ConnectionCreate) =>
    request<Connection>(`/connections/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

  createConversation: (title?: string) => request<{ id: string; title: string | null }>('/conversations', { method: 'POST', body: JSON.stringify({ title: title ?? null }) }),
  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),
  listConversations: (cursor?: string) =>
    request<{ items: ConversationSummary[]; next_cursor: string | null }>(
      `/conversations${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`,
    ),

  getLlmSettings: () => request<{ base_url: string; model: string; api_key_set: boolean }>('/settings/llm'),
  saveLlmSettings: (body: { base_url?: string; api_key?: string; model?: string }) =>
    request<{ base_url: string; model: string; api_key_set: boolean }>('/settings/llm', { method: 'POST', body: JSON.stringify(body) }),

  listSavedQueries: () =>
    request<{ id: string; name: string; question: string; connection_id: string }[]>('/saved-queries'),
  createSavedQuery: (body: { name: string; question: string; connectionId: string }) =>
    request<{ id: string }>('/saved-queries', {
      method: 'POST',
      body: JSON.stringify({ name: body.name, question: body.question, connection_id: body.connectionId }),
    }),
  runSavedQuery: (id: string) =>
    request<{ answer: string; row_count?: number; clarification?: string | null }>(`/saved-queries/${id}/run`, { method: 'POST' }),
  deleteSavedQuery: (id: string) => request<void>(`/saved-queries/${id}`, { method: 'DELETE' }),
  listSchedules: () =>
    request<{ id: string; saved_query_id: string; interval_seconds: number; last_status: string | null; last_rows: number | null; next_run_at: string }[]>('/schedules'),
  createSchedule: (savedQueryId: string, intervalSeconds: number) =>
    request<{ id: string }>('/schedules', {
      method: 'POST',
      body: JSON.stringify({ saved_query_id: savedQueryId, interval_seconds: intervalSeconds }),
    }),
  deleteSchedule: (id: string) => request<void>(`/schedules/${id}`, { method: 'DELETE' }),

  listMetrics: () =>
    request<{ id: string; name: string; table: string; aggregate: string; column: string; filter: string | null; description: string }[]>('/semantics'),
  createMetric: (body: { name: string; table: string; aggregate: string; column?: string; filter?: string | null; description?: string }) =>
    request<{ id: string }>('/semantics', { method: 'POST', body: JSON.stringify(body) }),
  deleteMetric: (id: string) => request<void>(`/semantics/${id}`, { method: 'DELETE' }),

  listApprovals: () =>
    request<{ id: string; status: string; reason: string; requester: string; resource_ref: string }[]>('/approvals'),
  decideApproval: (id: string, decision: 'approve' | 'reject', actor = 'ui') =>
    request<{ approval_id: string; status: string }>(`/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, actor }),
    }),

  listPrompts: () => request<Prompt[]>('/prompts'),
  createPrompt: (name: string, content: string) => request<Prompt>('/prompts', { method: 'POST', body: JSON.stringify({ name, content }) }),
  deletePrompt: (id: string) => request<void>(`/prompts/${id}`, { method: 'DELETE' }),

  listEvaluations: () => request<{ total: number; pass_rate: number; runs: unknown[] }>('/evaluations'),
  runEvaluations: () => request<EvaluationReport>('/evaluations/run', { method: 'POST' }),
};

/** POST /ask with SSE streaming; yields typed events. */
export async function* streamAsk(
  question: string,
  connectionId: string,
  conversationId?: string,
  promptId?: string,
): AsyncGenerator<import('./types').StreamEvent> {
  const res = await fetch('/ask/stream', {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(getApiKey() ? { 'X-API-Key': getApiKey()! } : {}) },
    body: JSON.stringify({ question, connection_id: connectionId, conversation_id: conversationId ?? null, prompt_id: promptId ?? null }),
  });

  if (!res.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = await res.json();
    } catch { /* noop */ }
    throw new ApiError(body?.code ?? 'INTERNAL', body?.message ?? `Request failed (${res.status})`, res.status, body?.details);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      let event: import('./types').StreamEvent;
      try {
        event = JSON.parse(line.slice(6));
      } catch {
        continue;
      }
      yield event;
    }
  }
}

export interface ContextRecord {
  context_id: string;
  org_id: string;
  connection_id: string;
  scope: string;
  version: number;
  state: string;
  schema_hash: string;
  artifact_kinds: string[];
  quality: { state: string; human_validation: number; [key: string]: unknown };
  freshness: { state: string; schema_hash_matches: boolean; [key: string]: unknown };
}

export interface PendingItem {
  kind: string;
  section: string;
  index: number;
  label: string;
  provenance: string;
  validation: string;
  confidence: number;
}

export interface ContextPreview {
  context_id: string;
  version: number;
  schema_hash: string;
  stale: boolean;
  tables: { name: string; columns: number }[];
  metrics: string[];
  tokens: number;
  dropped: string[];
  insufficient: string;
  trust: string;
  quality: string;
  persisted?: boolean;
  rebuild_job?: { id: string; state: string } | null;
}

export const contextApi = {
  status: (connectionId: string, scope = 'connection') =>
    request<{ context: ContextRecord | null }>(
      `/connections/${connectionId}/context?scope=${encodeURIComponent(scope)}`,
    ),
  versions: (connectionId: string, scope = 'connection') =>
    request<{ versions: ContextRecord[] }>(
      `/connections/${connectionId}/context/versions?scope=${encodeURIComponent(scope)}`,
    ),
  pending: (connectionId: string, scope = 'connection') =>
    request<{ items: PendingItem[] }>(
      `/connections/${connectionId}/context/pending?scope=${encodeURIComponent(scope)}`,
    ),
  validate: (
    connectionId: string,
    decisions: { kind: string; index: number; action: string; section?: string; patch?: Record<string, unknown> }[],
    scope = 'connection',
  ) =>
    request<{ context: ContextRecord }>(
      `/connections/${connectionId}/context/validate?scope=${encodeURIComponent(scope)}`,
      { method: 'POST', body: JSON.stringify({ decisions }) },
    ),
  build: (
    connectionId: string,
    body: { enrichment?: boolean; scope?: string; tables?: string[] | null } = {},
  ) =>
    request<{ state: string; version: number | null; context_id: string | null; degraded: boolean; stages: { name: string; status: string; duration_ms: number }[] }>(
      `/connections/${connectionId}/context/build`,
      { method: 'POST', body: JSON.stringify({ enrichment: false, scope: 'connection', ...body }) },
    ),
  rebuild: (connectionId: string, enrichment = false, scope = 'connection') =>
    request<{ id: string; state: string }>(
      `/connections/${connectionId}/context/rebuild?enrichment=${enrichment ? 'true' : 'false'}&scope=${encodeURIComponent(scope)}`,
      { method: 'POST' },
    ),
  rebuilds: () => request<{ jobs: { id: string; connection_id: string; state: string; version: number | null; error: string }[] }>('/context/rebuilds'),
  preview: (connectionId: string, question: string, options: { persist?: boolean; budgetTokens?: number; scope?: string } = {}) =>
    request<ContextPreview>(
      `/connections/${connectionId}/context/preview?scope=${encodeURIComponent(options.scope ?? 'connection')}`,
      {
        method: 'POST',
        body: JSON.stringify({
          question,
          persist: options.persist ?? false,
          budget_tokens: options.budgetTokens ?? null,
        }),
      },
    ),
};
