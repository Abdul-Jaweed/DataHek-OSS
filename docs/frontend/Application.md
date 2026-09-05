# DataHek — Application Requirements (Application.md)

The application is the product UI served at `/` (replacing the current single-page chat) — a dashboard for connecting data sources and having guarded, streaming conversations with them.

---

## 1. Application shell

### Layout

```
┌──────────────────────────────────────────────────────────┐
│ Header (56px): breadcrumb/title · connection pill · user │
├──────────┬───────────────────────────────────────────────┤
│ Sidebar  │  Main content (page)                          │
│ 240px    │                                               │
│ nav      │                                               │
├──────────┴───────────────────────────────────────────────┤
│ Status bar (28px, optional): LLM provider · auth mode    │
└──────────────────────────────────────────────────────────┘
```

- **Desktop:** fixed sidebar 240px + sticky header. Sidebar collapsible to 64px icon rail.
- **Tablet (768–1023px):** sidebar collapses to icon rail by default; expandable.
- **Mobile (<768px):** sidebar becomes a slide-in drawer (hamburger in header), overlay + `aria-modal`.

### Sidebar navigation

| Item | Icon | Route | Badge |
|---|---|---|---|
| Chat | MessageSquare | `/chat` | active connection name |
| Connections | Database | `/connections` | count (5 max) |
| Conversations | History | `/conversations` | — |
| Prompts | FileText | `/prompts` | count (3 max) |
| Evaluations | Gauge | `/evaluations` | — |
| Settings | Settings | `/settings` | — |

- Active item: brand text + 2px brand left rail. Hover: `--bg-800`.
- Section label above nav: "Workspace" (mono caption).

### Header

- Left: page title (h1) + breadcrumb (secondary pages).
- Right: **connection pill** (mono, `ch1 · clickhouse` with status dot green/amber/red → dropdown to switch/test) · auth indicator (lock icon when `DATAHEK_AUTH_MODE=local`) · user menu (avatar initials, Settings / Sign out placeholder).

---

## 2. Main screens

### 2.1 Chat (`/chat`) — the hero screen

**Purpose:** ask questions, watch streaming answers, see results, continue conversations.

**Layout (3 zones):**
1. **Composer** (bottom, sticky): textarea (auto-grow, Enter=send, Shift+Enter=newline) + Send button + connection selector + conversation context label.
2. **Thread** (middle, scroll): message list — user bubbles (right, info-tinted) / assistant bubbles (left, panel bg, mono for data) / system cards (blocked, clarification).
3. **Context bar** (top, optional toggle): active connection, conversation id (mono, copyable), prompt applied (name + "Custom prompt" chip).

**Message rendering:**
- User: plain text bubble.
- Assistant: markdown-lite (bold, lists, code, tables) + **data table** when `rows` event arrives + captions: `N rows · truncated` mono caption + timestamps.
- Streaming: caret `▍` until `done`; `aria-live="polite"` on the active bubble.
- Blocked/clarification: system card with amber/red border and code chip (`QUERY_BLOCKED`, `clarification`).
- Actions on completed answers: 👍/👎 feedback (optional in v1 UI), "Copy", "Show SQL" (expandable mono block when plan is available in future).

**State machine (client):**
- `idle → sending → streaming → completed | blocked | clarification | error | failed(connection)`.
- On error event / HTTP error: inline error card + Retry button (re-sends same question).

**Empty state:** centered: icon, "Ask anything about your data", steps (1. Connect a database, 2. Select it, 3. Ask), primary CTA → `/connections`.

**Interactions:**
- Send disabled when: no connection selected, empty input, streaming in progress.
- Conversation auto-created on first send; header shows its id.
- "New conversation" button (clear thread, new id).

**Responsive:** composer full-width, bubbles max-width 85%; on mobile the context bar collapses to a chip row.

### 2.2 Connections (`/connections`)

**Purpose:** manage the ≤5 data source connections.

**Layout:**
- Page header: title + count pill (`2/5`) + "Add connection" primary button.
- **Table** (desktop) / **cards** (mobile): columns: Name · Provider · Host:Port · Database · Status (dot + label) · Active (radio) · Actions (test, activate, delete).
- Status: `unknown` (gray), `testing` (spinner), `ok` (green), `error` (red + error message in tooltip/row expand).

**Add connection (modal):**
- Fields: Name (mono, required), Provider (select: ClickHouse, PostgreSQL — from `GET /health.providers`), Host, Port (default 8123/5432 per provider), Database, Username, Password (type=password, optional hint "stored as a secret reference").
- Actions: "Test connection" (secondary, runs POST test → inline result banner ok/error + latency ms) then "Save" (primary; disabled until name+provider).
- Limit reached (5): button disabled + tooltip "Connection limit reached (5)".

**Row actions:**
- **Test:** async; status column spins; on ok → green flash + toast "Connection OK · 14ms".
- **Activate:** radio; activates immediately + toast; active row gets brand left rail.
- **Delete:** confirm modal (danger) "Delete connection 'ch1'? Queries will fail until another is active." → destructive confirm.

**Empty state:** "No connections yet" + "Add your first connection" primary CTA.

**Error states:** per-row error banner (e.g., auth failed) with the sanitized reason.

### 2.3 Conversations (`/conversations`)

**Purpose:** browse past conversations (SQLite-backed).

**Layout:**
- List (desktop table / mobile cards): Title (first question truncated) · Created · Messages count · Last message snippet · Actions (Open, Delete).
- Click → navigates to `/chat?conversation=` — loads the thread, composer continues the conversation.
- Delete → confirm modal; empty state: "No conversations yet — start asking in Chat."

### 2.4 Prompts (`/prompts`)

**Purpose:** manage ≤3 custom planner prompt templates.

**Layout:**
- Header: title + count pill (`1/3`) + "New prompt" primary.
- Cards grid: Name (mono chip) · content preview (2-line clamp, mono) · actions: Apply in chat (link → sets `prompt_id` for next asks), Edit, Delete.
- **Editor modal:** Name (required) + Content textarea (mono, 4–8 rows, required, ≤4000 chars with counter) + hint "Injected as 'Additional guidance' into the planner." Save/Cancel.
- Limit reached: "New prompt" disabled + tooltip.

### 2.5 Evaluations (`/evaluations`)

**Purpose:** quality at a glance.

**Layout:**
- Header: title + "Run evaluation" primary button (POST `/evaluations/run`).
- **Summary cards:** Total · Passed · Pass rate (progress bar) — updated after each run.
- **Runs list** (most recent first): dataset name · pass rate · timestamp · expand → per-case table (name, passed badge, scores: plan_validity/safety/execution/latency).
- Running state: run button spinner + "Running 3 cases…" with a small progress list.
- Empty state: "No runs yet — run the built-in dataset."

### 2.6 Settings (`/settings`)

**Purpose:** environment visibility (read-only in v1).

**Layout (sections):**
- **LLM provider:** Base URL · Model · connected state (green/red dot) — read-only, mono.
- **Authentication:** mode pill (`none` / `local`) with hint "Set DATAHEK_AUTH_MODE to enable API keys."
- **Entitlements:** table of limits (connections 5, prompts 3, MCP 3, users 5) with current usage bars.
- **About:** version, providers list, links to docs.

---

## 3. Cross-cutting behaviors

- **API client:** typed wrapper over the REST API; base URL `/` (same origin) with optional `X-API-Key` persisted in `localStorage` when auth is local (Settings → "API key" input shown only when `GET /health` reports auth local? Auth is env-based; expose a setting input + note).
- **Auth:** if a request returns 401 → banner "API key required" + inline key input; store key; retry.
- **Global loading:** route-level skeleton; per-action spinners.
- **Global errors:** toast system + per-view inline alerts.
- **Unsaved changes:** modals warn before closing with dirty forms.

---

## 4. Onboarding

**Goal:** first-run → connected → first question, in <2 minutes.

**Flow (only when zero connections):**
1. On app load with no connections → onboarding overlay/card on `/connections`: step 1 "Add your database" (opens modal with provider presets), step 2 "Test it", step 3 "Go ask".
2. After first connection saved → toast "Connection ready — ask your first question" + primary CTA → `/chat`.
3. Progress indicator: 1→2→3 chips; dismissible.

**Auth-related onboarding:** if 401 on first load, show the API-key card first.

---

## 5. Screen map

| Route | Screen | Purpose |
|---|---|---|
| `/` | redirect → `/chat` | app entry |
| `/chat` | Chat | core experience |
| `/chat?conversation=` | Chat (loaded) | resume thread |
| `/connections` | Connections | manage sources |
| `/conversations` | Conversations | history |
| `/prompts` | Prompts | custom guidance |
| `/evaluations` | Evaluations | quality runs |
| `/settings` | Settings | env visibility |
| `*` | 404 | not found + back link |