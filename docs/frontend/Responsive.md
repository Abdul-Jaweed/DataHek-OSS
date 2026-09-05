# DataHek — Responsive Design (Responsive.md)

Single source of truth for how the UI behaves across screen sizes. **Breakpoints (min-width):**

| Name | Range | Primary device |
|---|---|---|
| `sm` | 0–639px | Mobile |
| `md` | 640–1023px | Tablet / small laptop |
| `lg` | 1024–1439px | Desktop |
| `xl` | ≥1440px | Large desktop |

Strategy: **mobile-first** with `min-width` media queries. All layouts use fluid spacing (`clamp()` for type), containers cap at 1120px (landing) / full-width with 32px gutters (app).

---

## Global rules

1. **Never guess:** every screen lists its behavior at each breakpoint (see tables below).
2. **Tables collapse, never scroll** (except data cells inside chat bubbles and code blocks, which are allowed to scroll horizontally).
3. **One primary action per screen** — it becomes full-width on mobile.
4. **Modals become bottom sheets on mobile.**
5. **Navigation moves, never shrinks to nothing:** sidebar → rail → drawer.
6. **Touch targets ≥ 32px** on `sm`; row actions become icon buttons with labels revealed in an overflow menu.
7. **Hover-only interactions are progressive enhancements** — everything must be reachable via tap.
8. **Type scale down:** `h1` 28px on mobile, 32px desktop; hero 40px mobile → 56px desktop.

---

## Application shell

| Element | lg+ (≥1024) | md (640–1023) | sm (<640) |
|---|---|---|---|
| Sidebar | 240px fixed; collapsible to 64px rail | rail by default; expandable | hidden → drawer (hamburger) |
| Header | title + pill + user | same, condensed | title truncated; pill icon-only (tooltip title) |
| Content padding | 32px | 24px | 16px |
| Status bar | visible | visible | hidden (info into settings) |

---

## Per-screen responsive behavior

### Chat
| Element | lg | md | sm |
|---|---|---|---|
| Layout | full-width thread + right context panel (320px, optional) | thread only (context → top chips) | thread only |
| Bubbles | max-width 75% | 85% | 92% |
| ResultTable | full bubble width | full bubble width | horizontal scroll inside bubble |
| Composer | inline textarea + button | same | full-width stack (button below on <420px) |
| Context chips | header row | header row (wrap) | collapse to "…" menu |

### Connections
| Element | lg | md | sm |
|---|---|---|---|
| List | DataTable | DataTable | Cards (name, provider, status dot, overflow actions) |
| Add modal | centered 640px | centered | bottom sheet |
| Row actions | inline icon buttons | inline | overflow menu (⋯) |

### Conversations
- lg/md: table (title, created, messages, last snippet); sm: cards with 2-line snippet.

### Prompts
- All sizes: card grid (3 → 2 → 1 columns); editor modal → bottom sheet on sm.

### Evaluations
- Summary cards: 3 → 2 (md) → stacked (sm); case table collapses to cards on sm.
- Run button full-width on sm.

### Settings
- Two-column section layout on lg; single column below.

---

## Landing page responsive

| Section | lg | md | sm |
|---|---|---|---|
| Nav | full links + CTAs | links hidden → hamburger (CTAs keep icon) | hamburger only |
| Hero | centered, mock 640px | mock 100% | mock 100% (inner chat scrolls) |
| Feature grid | 3 cols | 2 cols | 1 col |
| Pipeline steps | horizontal | horizontal | vertical stack with down arrows |
| Demo tabs | tab row + content | tab row scrollable | tab row scrollable |
| OSS/Enterprise | 2 cards | 2 cards | stacked |
| FAQ | single column, max 720px | same | same |
| Footer | 4 cols | 2 cols | 1 col |

---

## Layout primitives behavior

| Primitive | lg | md | sm |
|---|---|---|---|
| Container | 1120px max, centered | 100% + 24px gutters | 100% + 16px |
| Section padding | 96–128px vertical | 64px | 48px |
| Card grid | auto-fit minmax(280px,1fr) | same | 1 col |
| Button groups | inline | inline | primary full-width, secondary below |
| Modal | centered 480/640/800 | centered | bottom sheet, 92vh max, top radius 14px |
| Tooltips | pointer | pointer | disabled (use title) |
| Dropdown menus | anchored | anchored | bottom-anchored, 48px items |
| Tables | full | full | card list (via cardRender) |
| Sticky headers | standard | standard | shadow on scroll |

---

## Focus, safe areas, and gestures

- Respect `env(safe-area-inset-*)` on mobile for fixed bars (composer, header).
- Pull-to-refresh disabled inside the app (breaks streaming).
- No horizontal page scroll anywhere; overflow lives inside components.
- `overscroll-behavior: contain` on thread and modals.
- Landscape phones (<640px height): modals and the composer remain usable; keyboard resizes handled via `visualViewport`.

## Testing checklist

- [ ] No horizontal scroll at 375px, 640px, 768px, 1024px, 1440px.
- [ ] One-finger tap reaches every action (no hover-only).
- [ ] Chat streaming stays readable during resize (bubbles reflow, no jump).
- [ ] Modals usable on 320px screens (scrolling body).
- [ ] Focus rings visible after keyboard Tab at every breakpoint.