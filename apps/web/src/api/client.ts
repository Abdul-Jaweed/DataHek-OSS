import { ApiError, ApiErrorBody, type Connection, type ConnectionCreate, type Conversation, type EvaluationReport, type Health, type Prompt } from './types';

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

  listConnections: () => request<Connection[]>('/connections'),
  createConnection: (body: ConnectionCreate) => request<Connection>('/connections', { method: 'POST', body: JSON.stringify(body) }),
  testConnection: (id: string) => request<{ ok: boolean; latency_ms?: number; error?: string }>(`/connections/${id}/test`, { method: 'POST' }),

  createConversation: (title?: string) => request<{ id: string; title: string | null }>('/conversations', { method: 'POST', body: JSON.stringify({ title: title ?? null }) }),
  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),

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