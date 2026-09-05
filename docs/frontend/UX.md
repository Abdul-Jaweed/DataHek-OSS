# DataHek — UX & Interaction Requirements (UX.md)

Defines interactions, flows, and state behavior for every major user journey. State names in **bold**; all transitions <200ms unless noted.

---

## 1. Global interaction model

| Interaction | Spec |
|---|---|
| Navigation | Sidebar routes; browser back/forward supported; scroll position preserved per route |
| Primary actions | One per screen (brand button, right-aligned or composer) |
| Secondary actions | ghost/secondary buttons; icon buttons get tooltips |
| Destructive actions | Always a ConfirmDialog; button labeled with the noun ("Delete connection", not "Delete") |
| Success feedback | Toast (auto-dismiss 5s) + inline state change (status dot, badge) |
| Error feedback | Inline ErrorAlert near the action + toast for global failures |
| Loading | Skeletons for views; spinner + label for actions; streaming caret in chat |
| Keyboard | Full keyboard operability: Tab order = visual order; Enter submits forms; ESC closes modals/menus; arrows navigate menus/tables |

---

## 2. Key flows

### 2.1 First run / onboarding
1. App loads with zero connections → redirect to `/connections` + OnboardingSteps card (step 1 highlighted).
2. "Add connection" opens the modal; user fills Name/Provider/Host/Port/DB/Credentials.
3. User clicks **Test** → **testing** state (button spinner, status chip spinner) → **ok** (green flash, toast "Connection OK · 14ms") or **error** (inline field-level banner with reason; Save stays enabled but warns "Untested").
4. **Save** → **saving** → **saved** → toast + row appears + onboarding advances to step 2/3 → CTA "Go ask" → `/chat`.
5. Chat shows a welcome message ("Ask anything about your data") with the connection preselected.

**Abort states:** modal closes mid-test → test result discarded; unsaved form warns on close.

### 2.2 Ask a question (core flow)
1. Composer: type → **ready** (Send enabled when connection + text).
2. Send → **sending** (button spinner, bubble appended, caret).
3. **streaming** — tokens render; `rows` event renders ResultTable; `clarification` renders system card (thread ends, no table); `done` finalizes.
4. **completed** — actions appear (Copy, Show SQL if available); conversation persisted (id visible in context bar).
5. **blocked/error** — BlockedCard/ErrorAlert with `code` chip + Retry.
6. Retry → re-send same question; new conversation button clears thread + creates a fresh id.

**Edge cases:**
- No connection → composer disabled + hint "Select a connection".
- Connection removed mid-thread → next send fails with `CONNECTION_NOT_FOUND` inline error.
- Rate limited (`429 RATE_LIMITED`) → error card with hint "The model provider is rate-limited — retry in a moment."
- Truncated results → caption `N rows · truncated` in mono.

### 2.3 Connection lifecycle
- **Activate:** row radio → optimistic select → toast "ch1 is now active". Active row: brand rail.
- **Test:** spinner on status dot → ok/error; error expands reason row.
- **Delete:** ConfirmDialog → **deleting** → removed + toast; if it was active → toast "Active connection changed" (next becomes active).
- **Limit:** at 5 → Add disabled + tooltip; LimitBadge shows `5/5` red.

### 2.4 Prompt lifecycle
- Create → editor modal → **saving** → card appears + toast.
- Apply → chip "Prompt applied: finance" appears in chat context; all subsequent sends include `prompt_id` until cleared.
- Edit → modal prefilled → save updates card. Delete → ConfirmDialog.
- Limit: 3 → New disabled + tooltip.

### 2.5 Evaluations
- **Run** → button **running** + progress ("Running 3 cases…") → **completed** → summary cards animate (pass rate bar fills) + newest run first.
- Case rows expandable → per-metric scores (mono).
- Empty → EmptyState with Run CTA.

---

## 3. Component interaction states

### Buttons
| State | Trigger | Visual |
|---|---|---|
| default | — | variant style |
| hover | pointer | bg/border shift 150ms |
| focus | Tab/click | glow ring |
| active | mousedown | 0.5px translate + darker |
| disabled | `disabled` | 40% opacity, no pointer |
| loading | async action | spinner replaces icon; label retained; `aria-busy` |
| success (rare) | saved | brief brand border flash 1.5s |

### Inputs
- Focus ring on focus; error border + message on validation failure (validate on blur, re-validate on change after first error).
- Password fields: eye toggle (except in connection forms where it stays hidden for copy-safety).
- Mono inputs (host/port/db/id): no autocorrect/autocapitalize.

### Dropdowns
- Open on click; close on outside/ESC; arrows move selection; Enter selects; hover shows item fill; danger items red text.

### Tabs
- Click/keyboard arrows switch; active underline animates 150ms; content swap fade 120ms.

### Modals
- Open: overlay fade + panel scale 200ms; close on ESC/overlay/X; focus trap; return focus to trigger.

### Tables
- Hover row fill; clickable rows show pointer + chevron on right; sortable headers cycle asc→desc→none with arrow icons; selection rows use brand rail.

### Toasts
- Stack top-right; slide-in 200ms; auto-dismiss 5s (errors sticky); pause on hover; close button.

---

## 4. Form & validation rules

| Field set | Rules |
|---|---|
| Connection name | required, ≤64 chars, mono, strip whitespace |
| Provider | required select |
| Host | required, non-empty, stripped |
| Port | integer 1–65535; provider default prefill |
| Database | required, non-empty |
| Username/Password | optional; password never echoed anywhere |
| Prompt name | required ≤64 |
| Prompt content | required ≤4000 with live counter |
| Question | required 1–10000; whitespace-only rejected client-side before send |

Error copy style: sentence case, specific, no exclamation marks. Example: "Port must be between 1 and 65535."

---

## 5. Confirmation & destructive actions

| Action | Dialog |
|---|---|
| Delete connection | "Delete connection 'ch1'?" + "Active queries will fail until another connection is activated." |
| Delete conversation | "Delete this conversation? Its history is gone." |
| Delete prompt | "Delete prompt 'finance'? Chat will stop using it." |
| Discard unsaved form | "Discard changes?" (modal with dirty form only) |

Confirm buttons: danger solid; cancel always first (left).

---

## 6. Feedback taxonomy

| Type | Component | Tone |
|---|---|---|
| Success | Toast (green) + inline | "Connection saved" |
| Info | Toast (blue) | "Active connection changed" |
| Warning | Toast/Inline (amber) | "Limit reached" |
| Error | ErrorAlert (red) + code chip | `CONNECTION_NOT_FOUND` + message |
| Blocked | BlockedCard (amber) | `QUERY_BLOCKED` + reason |
| Clarification | System card (info) | "Which table do you mean?" |
| Streaming | caret + aria-live | — |

---

## 7. Onboarding & auth flows

- **Auth local mode:** 401 on any request → full-width banner in header: "API key required" + input + "Save key" (persisted `localStorage`); after save → retry pending request; banner hidden. Key never displayed after entry.
- **Sign out (local):** Settings → "Clear API key".
- **First-run** onboarding as §2.1; skippable; never blocks navigation.

---

## 8. Accessibility interaction requirements

- Every interactive element reachable by Tab; visible focus at all breakpoints.
- Chat: streaming answer `aria-live="polite"`; completed answers static.
- Modals: focus trap + ESC; menus: arrow navigation.
- Toasts: announced; dismissible.
- Color never sole signal (icons + text accompany dots/badges).
- Form errors linked via `aria-describedby`.
- Reduced motion: all animations disabled (instant transitions).