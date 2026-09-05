# DataHek — Frontend Technical Requirements (Technical.md)

## 1. Framework & language

| Choice | Rationale |
|---|---|
| **React 19** (TypeScript strict) | Component model matches the inventory; ecosystem maturity |
| **Vite 6** | Fast dev server, first-class TS, simple SSR-less build |
| Build target | Modern browsers (ES2022); no legacy IE |

### Optional/avoided
- **No SSR/framework** (Next.js etc.) in v1 — the app is authenticated data tooling; document-served is unnecessary. Landing can be static + React (same Vite app) or plain HTML; choose React for shared components.
- **No heavy UI framework** — build on our primitives; use **Radix UI** only for headless behavior (Modal, Dropdown, Tooltip, Tabs) where accessibility is non-trivial.
- **No state library beyond what's needed** (see §5).

## 2. Styling approach

- **Tailwind CSS v4** with a **design-token layer**: tokens defined as CSS custom properties in `src/styles/tokens.css` (single source of truth mirroring `Design.md`).
- Tailwind maps tokens: `bg-page`, `text-body`, `border-default`, `bg-brand`, etc. via `@theme` (v4) — no arbitrary values in components.
- **Dark-only** in v1; tokens structured so a light theme can be added later without component changes.
- Component styles colocated: `Button.module.css` or inline via Tailwind utilities with the token layer; prefer Tailwind utilities + a tiny set of shared classes for repeated patterns (card, row, caption).

## 3. Component architecture

- **Atomic layers:** `ui/` primitives (no domain knowledge) → `layout/` → `domain/` (know about API entities: Connection, Prompt, EvaluationRun, ChatMessage).
- **No CSS-in-JS** (runtime cost, SSR-free anyway); no styled-components.
- Every component: typed props, default exports avoided, `data-testid` on key nodes, Storybook optional (nice-to-have, not required for v1).
- Error boundaries: one app-level boundary + per-screen boundary.

## 4. Design tokens (file layout)

```
src/styles/
├── tokens.css        # :root variables (colors, type, space, radius, shadow, motion)
├── base.css          # reset, body, focus-visible, scrollbars, reduced-motion
└── utilities.css     # shared classes: .card, .row, .caption, .mono, .container
```

Token names exactly match `Design.md` (§3–§6, §14).

## 5. State management

| Concern | Solution |
|---|---|
| Server state (connections, prompts, runs) | **TanStack Query** (caching, invalidation, retries, optimistic updates for activate/delete) |
| Streaming chat state | Local component state + a dedicated **SSE hook** (`useStreamAnswer`) consuming `fetch` ReadableStream; buffer events; no global store |
| UI/global state (auth key, sidebar mode, connection selection) | **Zustand** (small) or React Context; v1 defaults to Zustand for the few global slices |
| Route state | React Router (`/chat?conversation=`, etc.) |

Rule: nothing derived from server data lives in global state (Query is the source).

## 6. Form handling

- **React Hook Form** + **Zod** schemas shared with the API models where possible.
- Validation: Zod schema per form (`connectionSchema`, `promptSchema`, `apiKeySchema`); errors map to field errors; client mirrors server rules (see `UX.md` §4).
- `useForm` per modal; dirty tracking for close warnings.

## 7. API layer

- **Client:** `fetch` wrapper `apiClient` (base `/`, JSON, `X-API-Key` from store, typed errors `{code,message,details}` → mapped to `ApiError`).
- **Endpoints consumed** (v0.2.0 surface):
  - `GET /health` (capabilities, entitlements, providers)
  - `GET/POST /connections`, `GET/POST /connections/{id}/test|activate`
  - `POST /ask`, `POST /ask/stream` (SSE: start/token/rows/clarification/done)
  - `GET/POST /conversations`, `GET /conversations/{id}`
  - `GET/POST/DELETE /prompts`
  - `GET /evaluations`, `POST /evaluations/run`
- **SSE parser:** `src/lib/sse.ts` — typed event union; consumed by `useStreamAnswer`.
- **Type generation:** hand-written `src/api/types.ts` mirroring the Pydantic models (small surface; codegen later).
- **Error mapping:** `ApiError` with `code` union (`CONNECTION_NOT_FOUND`, `RATE_LIMITED`, `QUERY_BLOCKED`, …) + status.

## 8. Folder structure

```
apps/web/
├── src/
│   ├── main.tsx / App.tsx
│   ├── router.tsx
│   ├── styles/            # tokens, base, utilities
│   ├── api/               # client, types, endpoints, sse.ts
│   ├── hooks/             # useStreamAnswer, useConnections, usePrompts, ...
│   ├── store/             # zustand slices (auth, ui)
│   ├── components/
│   │   ├── ui/            # Button, Input, Modal, Dropdown, Tabs, Tooltip, Toast, ...
│   │   ├── layout/        # AppShell, Sidebar, Header, PageHeader, EmptyState
│   │   ├── data/          # DataTable, StatusDot, MetricCard, LimitBadge, ConnectionPill
│   │   ├── chat/          # Composer, MessageBubble, ResultTable, StreamThread
│   │   └── domain/        # ConnectionForm, PromptEditor, EvalSummary, OnboardingSteps
│   ├── features/          # screen containers: ChatPage, ConnectionsPage, ...
│   ├── routes/
│   └── test/              # vitest + testing-library
├── index.html
├── vite.config.ts
└── tsconfig.json
```

**Location:** `apps/web/` inside the DataHek-OSS repo (the Python package serves the built app at `/`; Vite output copied into `src/datahek/api/static/` or served by the API in dev via proxy).

## 9. Testing strategy

- **Vitest + React Testing Library + MSW** for API mocking.
- Coverage targets (v1): components (state matrix per `Components.md`), the SSE parser (event sequences, malformed frames), forms (Zod rules), key flows (`UX.md` §2.2–2.5) via integration tests at the feature level.
- CI: `pnpm test` + `pnpm build` + `tsc --noEmit`; typecheck gate.

## 10. Performance & delivery

- Bundle: code-split per route; chat page chunk lazy; landing static.
- Fonts: self-hosted woff2 (IBM Plex Sans, JetBrains Mono) — no runtime Google Fonts in the app.
- Icons: tree-shaken Lucide imports.
- Streaming: no re-render of full thread per token — only the active bubble updates.
- a11y audits in CI (axe) on critical screens.

## 11. Environment & build

- `pnpm` package manager · Node 20+ · `vite build` output to `dist/` → served by the FastAPI app (static mount) with `index.html` at `/`; API routes unchanged (`/api` prefix optional, not required — routes coexist).
- Dev proxy: `vite.config.ts` proxies `/health`, `/ask*`, `/connections*`, `/conversations*`, `/prompts*`, `/evaluations*` to the uvicorn server (default `http://localhost:8000`).