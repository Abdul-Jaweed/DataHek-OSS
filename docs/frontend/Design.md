# DataHek — Frontend Design System (Design.md)

**Status:** Spec v1.0 · For frontend development · Products: landing page + application
**Companion docs:** `Landing.md` · `Application.md` · `Components.md` · `Responsive.md` · `UX.md` · `Technical.md`

---

## 1. Design philosophy & visual direction

DataHek is a **universal conversational data platform** — "ChatGPT for your databases." The design must make complex data feel:

- **Approachable** — natural language is the interface; UI never requires SQL literacy.
- **Trustworthy** — safety, auditability, and guardrails are core value; the UI makes execution feel *guarded*, never risky.
- **Technical, but not intimidating** — developer-grade aesthetics (monospace accents, dense data tables) with consumer-grade polish (streaming, smooth states).
- **Calm and focused** — one primary action per screen (ask, connect, run); low noise; the chat is the hero.

**Mood keywords:** dark, precise, data-forward, calm, confident. Think *Linear × GitHub dark mode × a query console*.

**Core interaction metaphor:** the **conversation**. The chat is the product. Everything else (connections, prompts, evaluations) exists to support better conversations.

**Design principles**
1. **One surface, one pipeline** — chat, connections, and prompts all feel like part of one tool.
2. **Streaming is the signature** — token-by-token answers with a visible caret are a brand moment, not an implementation detail.
3. **Data is always visible** — answers show their source: columns, row counts, truncated flags, SQL (when shown).
4. **Safety is visible** — blocked queries, masked columns, and risk states are explicit, never silent.
5. **Dark-first** — dark is the default and only shipped theme in v1 (consistent with the existing web UI and brand decks).

---

## 2. Brand personality & tone

| Attribute | Expression |
|---|---|
| Voice | Concise, technical, confident. No marketing fluff in-app. |
| Copy tone | "Ask about your data" not "Revolutionize your analytics." |
| Errors | Specific + actionable: "Connection 'ch1' not found" + a fix hint. |
| Loading | Honest progress: streaming tokens, spinner + label ("Discovering schema…"). |
| Empty states | Teach, don't apologize: "Connect a database to start asking questions." |

---

## 3. Color palette

The design tokens are exposed as CSS custom properties (see `Technical.md`).

### Primary & brand

| Token | Value | Usage |
|---|---|---|
| `--brand-500` (primary accent) | `#22C55E` | Primary buttons, active nav, focus rings, positive signals |
| `--brand-600` (hover) | `#16A34A` | Hover state for primary actions |
| `--brand-700` (active) | `#15803D` | Active/pressed state |
| `--brand-50` (tint) | `#F0FDF4` | Badges/tints on light surfaces (docs, exports) |

### Secondary / informational

| Token | Value | Usage |
|---|---|---|
| `--info-500` | `#38BDF8` | User messages, links, informational badges, "streaming" states |
| `--info-600` | `#0284C7` | Hover for info accents |

### Surfaces (dark theme)

| Token | Value | Usage |
|---|---|---|
| `--bg-950` (page) | `#0F172A` | App + landing page background |
| `--bg-900` (panel) | `#1E293B` | Cards, sidebar, inputs, code blocks |
| `--bg-800` (elevated) | `#334155` | Hover fills, dropdowns, active rows |
| `--bg-850` (input) | `#0B1220` | Input fields inside panels |

### Text

| Token | Value | Usage |
|---|---|---|
| `--text-100` | `#F8FAFC` | Headings, primary text |
| `--text-300` | `#CBD5E1` | Body text |
| `--text-500` | `#94A3B8` | Secondary/muted text, labels, placeholders |
| `--text-600` | `#64748B` | Disabled text, captions |

### Borders & dividers

| Token | Value | Usage |
|---|---|---|
| `--border-700` | `#334155` | Default borders, dividers, table row lines |
| `--border-600` | `#475569` | Hover borders, stronger dividers |

### Semantic states

| Token | Value | Usage |
|---|---|---|
| `--success-500` | `#22C55E` | Success toasts, "connection OK", passed evaluations |
| `--warning-500` | `#F59E0B` | Warnings, risk indicators (medium) |
| `--danger-500` | `#EF4444` | Errors, destructive actions, failed evaluations |
| `--danger-50` | `#450A0A` | Error fills (toast/alert background) |
| `--warning-50` | `#451A03` | Warning fills |

**Contrast rules:** body text ≥ 4.5:1 on its surface; muted text ≥ 3:1 (label-only usage); brand green on `#0F172A` meets 4.5:1 for text — use `#22C55E` for text accents only at ≥14px, otherwise `#4ADE80`.

---

## 4. Typography

| Role | Font | Fallback |
|---|---|---|
| UI text, headings, body | **IBM Plex Sans** (400/500/600/700) | system-ui, sans-serif |
| Data, code, SQL, identifiers, IDs, table cells, buttons labels | **JetBrains Mono** (400/500/600) | ui-monospace, monospace |

Import: `@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');`

### Type scale

| Token | Size / weight / line-height | Usage |
|---|---|---|
| `--text-hero` | 40–56px / 700 / 1.1 | Landing hero, app empty-state titles |
| `--text-h1` | 28–32px / 600 / 1.2 | Page titles |
| `--text-h2` | 20–24px / 600 / 1.3 | Section headers |
| `--text-h3` | 16–18px / 600 / 1.4 | Card titles |
| `--text-body` | 14px / 400 / 1.6 | Body, chat messages |
| `--text-small` | 13px / 400 / 1.5 | Secondary text, table cells |
| `--text-caption` | 12px / 400 / 1.4 | Labels, timestamps, footnotes |
| `--text-mono` | 13px / 400 / 1.5 | SQL, IDs, data values |

### Hierarchy rules
- One `h1` per screen. Sections use `h2` + optional caption.
- Labels are `11px` uppercase `--text-500` with `letter-spacing: 0.08em` (JetBrains Mono).
- Buttons: 14px, weight 600 (Sans); mono for code-ish actions (rare).
- Never use font-weight below 400 for body text.

---

## 5. Spacing system

4px base grid. Tokens: `--space-1`=4 · `--space-2`=8 · `--space-3`=12 · `--space-4`=16 · `--space-5`=20 · `--space-6`=24 · `--space-8`=32 · `--space-10`=40 · `--space-12`=48 · `--space-16`=64.

Conventions:
- Card padding: `--space-5` (20px).
- Page padding: `--space-8` desktop, `--space-5` mobile.
- Component gaps: `--space-3`/`--space-4`.
- Section rhythm on landing: `--space-16` (64px), doubled on large screens (96–128px).

---

## 6. Border radius & elevation

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | 6px | Inputs, small buttons, badges |
| `--radius-md` | 10px | Cards, buttons, dropdowns |
| `--radius-lg` | 14px | Modals, chat bubbles |
| `--radius-full` | 999px | Pills, tags, avatars |

### Shadows (dark theme = borders over shadows)

| Token | Value | Usage |
|---|---|---|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,.3)` | Cards on panels |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,.4)` | Dropdowns, popovers |
| `--shadow-lg` | `0 12px 32px rgba(0,0,0,.5)` | Modals |
| `--glow-brand` | `0 0 0 3px rgba(34,197,94,.18)` | Focus ring (primary) |
| `--glow-info` | `0 0 0 3px rgba(56,189,248,.18)` | Focus ring (info) |

Prefer **border-color transitions** over box-shadow for hover states (cheaper, calmer).

---

## 7. Iconography

- **Source:** Lucide icons (consistent 24×24 viewBox, `stroke-width: 2`).
- Sizes: 16 (inline/meta), 20 (buttons), 24 (nav), 32+ (empty states, hero).
- **No emoji as UI icons** anywhere in the product. Emojis appear only inside user/LLM message *content*.
- Icons are decorative unless alone (label provided via aria-label).
- Icon + text buttons: icon left of label (except `X` close on right).
- Loader icons: `Loader2` with `animate-spin` only for blocking actions.

---

## 8. Buttons

| Variant | Style | Use |
|---|---|---|
| `primary` | bg `--brand-500`, text `#052E16`, radius-md, weight 600 | The one main action per view |
| `secondary` | bg `--bg-800`, border `--border-700`, text `--text-100` | Common actions |
| `ghost` | transparent, text `--text-300`, hover bg `--bg-800` | Toolbar, subtle actions |
| `danger` | bg transparent, border `--danger-500`, text `--danger-500`; solid variant on confirm modals | Destructive actions |
| `icon` | square 36px, ghost style | Icon-only (edit, delete, copy) |
| `link` | text `--info-500`, underline on hover | Inline actions |

Sizes: `sm` 32px, `md` 36px, `lg` 44px. Full-width on mobile for primary actions.

**States:** default → hover (bg/border shift, 150ms) → focus (2px `--glow-brand` ring, offset 2px) → active (translateY(0.5px), darker bg) → disabled (40% opacity, no pointer) → loading (spinner + label retained width).

---

## 9. Inputs & forms

- Field: 36px height, radius-sm, bg `--bg-850`, border `--border-700`, text `--text-100`, mono for connection details (host/port/db).
- Label: 11px uppercase mono, `--text-500`, above field. Helper text: 12px `--text-500`. Error: 12px `--danger-500` with `--danger-50` field border.
- Focus: `--glow-brand` ring. Placeholder: `--text-600`.
- Textarea (prompt content): 4 rows min, mono, radius-md.
- Selects, checkboxes, toggles share the same field chrome.

---

## 10. Cards, modals, dropdowns, tabs, tooltips, toasts

- **Cards:** bg `--bg-900`, border `--border-700`, radius-md, padding `--space-5`; hover = border `--border-600` (clickable cards) or `--brand-500` (selectable).
- **Modals:** overlay `rgba(2,6,23,.6)` + backdrop-blur(2px); panel bg `--bg-900`, border, radius-lg, `--shadow-lg`; width 480px (sm) / 640px (md) / 800px (lg); max-height 85vh scroll; header (title + close) / body / footer. ESC closes; click-outside closes; focus trap; `role="dialog"` + `aria-modal`.
- **Dropdowns:** bg `--bg-800`, border, radius-md, `--shadow-md`, 8px padding; items 32px with hover fill; separator 1px `--border-700`; keyboard: arrows + enter + esc.
- **Tabs:** underline style — 2px `--brand-500` active underline, `--text-100` active / `--text-500` inactive; `role="tablist"` semantics.
- **Tooltips:** 10px delay, bg `--bg-800`, border, text 12px, radius-sm, `role="tooltip"`; never the only source of info (title attr or visible label fallback).
- **Toasts:** top-right stack, bg `--bg-900`, border-left 3px semantic color, icon, title + optional detail, auto-dismiss 5s (success/info) / sticky (error), close button, `role="status"` / `role="alert"`.

---

## 11. Loading, empty, error states

- **Loading:** skeleton shimmer (bg `--bg-800` pulse) for panels; spinner + contextual label for actions ("Running query…", "Discovering schema…"); streaming caret `▍` blinking during answer generation.
- **Empty states:** centered icon (40px, `--text-600`), title (`--text-h3`), body copy, one primary CTA. Always answer "what do I do next?"
- **Error states:** inline alert (bg `--danger-50`, border `--danger-500`, icon, message + optional retry button); full-page error only for hard failures with a "Back to dashboard" action.
- **Blocked/denied states:** amber/red treatment in chat (blocked message card with reason code).

---

## 12. Hover / focus / active / disabled rules

- Hover transitions: 150ms ease on color/border/background only (no layout shift).
- Focus visible on every interactive element (keyboard nav requires it); focus ring color = brand for primary, info for secondary.
- Active: 1px inset press effect on buttons; row highlight on tables.
- Disabled: 40% opacity; disabled buttons show a tooltip explaining why when it matters ("Limit reached — 3 prompts max").
- Respect `prefers-reduced-motion`: disable all non-essential animation (see §14).

---

## 13. Accessibility guidelines

- WCAG 2.1 AA: contrast (see §3), keyboard operability, visible focus.
- Semantic HTML (header/nav/main/aside/section/table).
- Form fields: visible labels + `aria-describedby` for helpers/errors.
- Tables: `th scope="col"`, `aria-label` on icon-only actions.
- Streaming chat: `aria-live="polite"` on the active answer; completed answers `aria-live="off"`.
- Toasts announce via `aria-live`; modal focus trap + return focus.
- Target size ≥ 32×32px for touch.
- No color-only signaling: blocked states always include an icon + text.

---

## 14. Animation & micro-interactions

| Motion | Spec |
|---|---|
| Token stream | content updates only; caret `▍` blinks (1s ease) |
| Panel fade-in | 150ms ease, translateY(4px)→0 |
| Modal | 200ms scale 0.98→1 + fade |
| Dropdown | 120ms fade + 4px translateY |
| Toast | slide-in-right 200ms, exit 150ms |
| Skeleton pulse | 1.4s ease-in-out opacity 0.4→0.8 |
| Hover shifts | 150ms color/border |

- Curves: `cubic-bezier(0.16, 1, 0.3, 1)` (expo-out) for entrances; linear-ish `cubic-bezier(0.4, 0, 0.2, 1)` for states.
- All decorative motion gated behind `@media (prefers-reduced-motion: reduce)` → durations ~0 or instant.

---

## 15. Design tokens (summary)

CSS custom properties under `:root` (dark-only in v1). Token groups: color (`--bg-*`, `--text-*`, `--border-*`, `--brand-*`, `--info-*`, semantic), typography (`--text-*` scale), space (`--space-*`), radius (`--radius-*`), shadow/glow, motion (`--dur-*`, `--ease-*`). See `Technical.md` for the token file layout.