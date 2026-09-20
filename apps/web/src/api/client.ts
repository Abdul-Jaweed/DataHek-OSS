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