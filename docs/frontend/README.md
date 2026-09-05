# DataHek — Frontend Specifications

Complete frontend specification package for the DataHek product (landing page + application).

## Documents

| Doc | Contents |
|---|---|
| [Design.md](Design.md) | Design system: philosophy, brand, colors, typography, spacing, radius, shadows, icons, buttons, forms, cards, modals, dropdowns, tabs, tooltips, toasts, loading/empty/error states, accessibility, animation |
| [Landing.md](Landing.md) | Landing page: section-by-section spec (nav, hero, value prop, features, how-it-works, demo, use cases, OSS/Enterprise, FAQ, final CTA, footer) with copy, layout, and responsive rules |
| [Application.md](Application.md) | Application: shell, sidebar/header, and every screen (Chat, Connections, Conversations, Prompts, Evaluations, Settings) with layout, components, states, and flows |
| [Components.md](Components.md) | Reusable component inventory: every component with purpose, variants, props, states, interactions, responsive behavior, accessibility |
| [Responsive.md](Responsive.md) | Breakpoints and per-screen responsive behavior (stack/collapse/drawer/bottom-sheet rules) |
| [UX.md](UX.md) | Interactions & flows: onboarding, ask, connection lifecycle, prompts, evaluations; form rules; destructive actions; feedback taxonomy; keyboard and a11y requirements |
| [Technical.md](Technical.md) | Tech stack: React 19 + TS + Vite + Tailwind v4, tokens, component architecture, state management, forms, API layer, folder structure, testing, build |

## Grounding

The spec is grounded in the actual DataHek OSS product (v0.2.0):

- API surface: `/health`, `/connections` (+test/activate), `/ask` + `/ask/stream` (SSE: start/token/rows/clarification/done), `/conversations`, `/prompts`, `/evaluations` (+run)
- Entitlements: connections ≤ 5, prompts ≤ 3, MCP ≤ 3 — enforced server-side (429)
- Security: read-only by construction, masked columns (`***`), PII-redacted answers, sanitized errors, optional local auth (`X-API-Key`)
- Existing design language (dark OLED, brand green, JetBrains Mono) formalized into tokens

## Suggested build order

1. Design tokens + ui primitives (Button, Input, Modal, Toast, EmptyState)
2. AppShell + routing + API client + SSE parser
3. Chat screen (core) — streaming, ResultTable, blocked/clarification cards
4. Connections screen (CRUD + test/activate + limits)
5. Prompts + Evaluations screens
6. Landing page (reuses tokens + components)
7. Responsive pass + a11y audit + tests