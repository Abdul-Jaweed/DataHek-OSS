# DataHek — Component Inventory (Components.md)

Reusable component system for both the landing page and the application. Naming follows `ComponentName` (PascalCase). All components accept a standard set: `className`, `data-testid`, and are keyboard-accessible.

**Component tree (top-level):**
```
ui/         — primitives (Button, Input, Modal, …)
layout/     — AppShell, Sidebar, Header, PageHeader, EmptyState
data/       — DataTable, StatusDot, ConnectionPill, MetricCard
chat/       — Composer, MessageBubble, StreamThread, ResultTable
domain/     — ConnectionForm, PromptEditor, EvalSummary, LimitBadge
```

---

## UI primitives

### Button
- **Purpose:** trigger an action.
- **Variants:** primary · secondary · ghost · danger · icon · link; sizes sm/md/lg.
- **Props:** `variant`, `size`, `icon?: IconName`, `loading?: boolean`, `disabled`, `fullWidth`, `type`.
- **States:** default/hover/focus/active/disabled/loading (label retained, spinner replaces icon).
- **Accessibility:** real `<button>`; `aria-busy` when loading; visible focus ring.

### Input / TextArea / Select / Checkbox / Toggle
- **Purpose:** form controls.
- **Props:** `label`, `hint?`, `error?`, `value`, `onChange`, `disabled`, `autoFocus`, `mono?`.
- **States:** default/hover/focus/error/disabled; error shows `--danger-500` border + message + `aria-describedby`.
- **Accessibility:** visible `<label>` (or `aria-label` for icon-only use), `required` semantics.

### Modal
- **Purpose:** focused task on top of content.
- **Variants:** default · confirm (danger) · form (md) · large (lg).
- **Props:** `open`, `title`, `onClose`, `footer?`, `size`, `closeOnOverlay`.
- **States:** open (animation), closing; ESC + overlay close; focus trap; body scroll lock.
- **Accessibility:** `role="dialog"`, `aria-modal="true"`, labelled by title, focus returned on close.

### Dropdown / Menu
- **Purpose:** compact action menu or selection.
- **Props:** `items: {label, icon?, onSelect, danger?}[]`, `align`, `trigger`.
- **States:** open/close animation; item hover; keyboard arrows/enter/esc.
- **Accessibility:** `role="menu"`, items `role="menuitem"`.

### Tabs
- **Props:** `tabs: {id, label}[]`, `active`, `onChange`.
- **Variants:** underline (app) · pill (landing demo).
- **Accessibility:** `role="tablist"` + `aria-selected`.

### Tooltip
- **Props:** `content`, `side`, `delay`.
- **Accessibility:** `role="tooltip"`; not the only info source.

### Toast / Notification
- **Props:** `type: success|error|info|warning`, `title`, `message?`, `duration?`, `onClose`.
- **System:** `ToastProvider` — stack top-right, auto-dismiss (sticky for errors), close button.
- **Accessibility:** `role="status"` (info/success) / `role="alert"` (error).

### Badge / Pill / StatusDot
- **Purpose:** compact state/label display.
- **Variants:** brand · info · warning · danger · neutral; sizes sm/md.
- **StatusDot:** `state: ok|error|testing|unknown` (green/red/amber/gray + pulse on testing).

### Skeleton
- **Props:** `variant: text|rect|circle|table`, `lines?`, `width?`.
- **Behavior:** pulse animation, `aria-hidden`, parent container labelled with real content via `aria-busy`.

### EmptyState
- **Props:** `icon`, `title`, `description?`, `action?`.
- **Layout:** centered, max-width 420px, icon 40px `--text-600`.

### ErrorAlert / BlockedCard
- **Props:** `code?`, `message`, `retry?`.
- **Variants:** inline error (`--danger-50` fill) · blocked (amber/red, code chip mono).

### ConfirmDialog
- **Props:** `title`, `body`, `confirmLabel`, `danger`, `onConfirm`, `onCancel`.
- **Behavior:** destructive confirmations use danger button; "Cancel" always present.

### ProgressBar
- **Props:** `value (0–1)`, `color?`, `label?`.
- **Use:** evaluation pass rate, entitlement usage bars.

### Accordion
- **Props:** `items: {title, content}[]`, `singleOpen`.
- **Accessibility:** buttons + `aria-expanded`, region `aria-hidden` when closed.

---

## Layout components

### AppShell
- **Props:** `sidebarItems`, `headerContent`, `children`, `footer?`.
- **Behavior:** manages sidebar collapse/drawer state, scroll containers, mobile drawer.
- **Accessibility:** `<aside>`/`<nav aria-label="Main">`, skip-link to main content.

### Sidebar / SidebarNav
- **Items:** `{route, label, icon, badge?, active}`.
- **States:** active (brand rail + text), hover fill; collapsed rail shows icons with tooltips.

### Header / PageHeader
- **Header (shell):** title/breadcrumb slot, connection pill slot, user slot.
- **PageHeader:** h1 + subtitle slot + action slot (primary on right).

### ConnectionPill (app header)
- **Props:** `connection?: {name, provider, status}`, `onSwitch`, `onTest`.
- **Behavior:** click → dropdown (list connections, Activate/Test actions); status dot reflects last test.

### MetricCard
- **Props:** `label`, `value`, `sub?`, `tone?`.
- **Use:** evaluation summary (total/passed/rate), entitlement usage.

### DataTable
- **Props:** `columns: {key, header, render?, mono?, align}[]`, `rows`, `loading?`, `empty?`, `onRowClick?`, `selectable?`, `sortable?`.
- **States:** loading (skeleton rows), empty (EmptyState slot), hover row fill, selected row brand rail.
- **Responsive:** on <768px renders as cards via `cardRender` prop (never horizontal-scroll by default).
- **Accessibility:** `<table>` semantics, `aria-busy` on loading, caption when useful.

### TabsPanel / ListRow / PageSection
- Standard groupings: section header (h2 + optional caption/action), card body.

---

## Chat components

### Composer
- **Props:** `connectionId`, `connectionStatus`, `disabled?`, `onSend(text)`, `promptId?`, `onAttachPrompt?`.
- **Behavior:** auto-grow textarea (2–6 rows), Enter to send, Shift+Enter newline, send spinner while streaming, disabled without connection.
- **Accessibility:** labelled textarea, `aria-disabled` state explained via hint.

### MessageBubble
- **Props:** `role: user|assistant`, `content` (markdown-lite), `meta?` (timestamp, message id), `streaming?`, `actions?`.
- **States:** streaming (caret + `aria-live=polite`), completed (actions revealed), error/blocked variants.
- **Markdown support:** bold, italic, lists, inline code, code blocks, tables — sanitized (no raw HTML).

### ResultTable (chat)
- **Props:** `columns: string[]`, `rows: Record<string, unknown>[]`, `truncated?`, `rowCount`.
- **Behavior:** rendered inside the assistant bubble after tokens; mono cells; caption `N rows · truncated` when flagged; masked cells display `***` as-is.
- **Responsive:** horizontal scroll inside the bubble on small screens.

### StreamThread
- **Props:** `messages`, `activeStream` (events buffer), `onRetry`, `autoScroll`.
- **Behavior:** consumes the SSE parser output; auto-scrolls unless user scrolled up; renders system cards (clarification/blocked/error).

### SSE parser (utility, not visual)
- Consumes `fetch` ReadableStream; emits typed events: `start`, `token`, `rows`, `clarification`, `done`, `error`; handles reconnects only via user Retry.

---

## Domain components

### ConnectionForm (modal body)
- **Props:** `providers: string[]`, `onSubmit(values)`, `onTest(values)`, `testing?`, `testResult?`, `limitReached?`.
- **Behavior:** provider select pre-fills default ports; test button runs validation inline; save disabled until valid + tested (test optional, warned).

### PromptEditor (modal body)
- **Props:** `initial?`, `onSave(values)`, `limitReached?`.
- **Behavior:** content counter `0/4000`; name required; mono textarea.

### EvalSummary
- **Props:** `run: {total, passed, pass_rate, cases}`.
- **Behavior:** MetricCards + case table; expandable case scores.

### LimitBadge
- **Props:** `used`, `limit`, `resource`.
- **Behavior:** `2/5` mono pill; amber when ≥80%, red at limit, tooltip when disabled action.

### OnboardingSteps
- **Props:** `step: 1|2|3`, `onNext`.
- **Behavior:** chip stepper; dismissible; shown only when zero connections.

---

## Component states matrix (standard)

| State | Visual |
|---|---|
| default | token value |
| hover | border/bg shift, 150ms, no layout shift |
| focus | 2px glow ring, offset 2 |
| active | press (0.5px translate / darker bg) |
| disabled | 40% opacity + no pointer |
| loading | spinner or skeleton + contextual label |
| success (transient) | green flash/border 1.5s |
| error | danger border/fill + message |

## Responsive component behavior

| Component | Desktop ≥1024 | Tablet 768–1023 | Mobile <768 |
|---|---|---|---|
| DataTable | full table | full table | card list (cardRender) |
| Composer | full width | full width | full width, auto-grow |
| Modal | centered fixed | centered fixed | bottom-sheet (radius top, 92vh max) |
| Sidebar | 240px / rail | rail default | drawer |
| Tooltips | pointer | pointer | suppressed (title attr) |
| Button groups | inline | inline | full-width primary |