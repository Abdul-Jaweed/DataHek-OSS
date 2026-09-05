# DataHek — Landing Page Requirements (Landing.md)

**Audience:** developers, data analysts, and technical evaluators evaluating "ChatGPT for your databases."
**Goal:** communicate what DataHek does in 30 seconds and convert visitors to (a) self-host (OSS) or (b) request the Enterprise edition.
**Tone:** technical, confident, zero hype.

---

## Global landing rules

- Dark theme (tokens from `Design.md`), full-bleed sections with generous vertical rhythm (`--space-16`, 96–128px on desktop).
- Max content width 1120px, centered; 20px gutters on mobile.
- Fonts: IBM Plex Sans (UI) + JetBrains Mono (code/terminals).
- Every section has one primary message; one CTA per section max (two only in the hero).
- Monospace accents everywhere data/SQL is referenced (schema snippets, terminal mock).
- Animated elements: only on desktop, gated by `prefers-reduced-motion`.

---

## Section-by-section spec

### 0. Top bar / navigation

- **Purpose:** orientation + CTA access while scrolling.
- **Layout:** sticky 56px bar, blur `rgba(15,23,42,.8)` + backdrop-blur, border-bottom `--border-700`.
- **Content (left→right):** logo (⚡ mark + "DataHek" wordmark, "OSS" badge) · nav links: Features, How it works, Docs, GitHub · right: "Request Enterprise" (secondary) + "Self-host" (primary sm).
- **Mobile:** logo + hamburger → slide-down panel with links + CTAs.
- **Interaction:** smooth-scroll anchors; active section underline (optional).

### 1. Hero

- **Purpose:** instant comprehension — natural language in, safe answer out.
- **Layout:** centered stack: badge → headline → subcopy → CTAs → live product mock (chat window).
- **Badge:** pill `DataHek OSS · Apache-2.0` (green border).
- **Headline (h1 hero):** "Ask your data. In plain language." — variant with brand-green "plain language."
- **Subcopy:** "DataHek discovers your schema, plans a read-only query, validates it through safety guardrails, and explains the results — across API, CLI, MCP, and a web chat."
- **CTAs:** [Self-host — Docker] (primary lg) · [Read the docs] (secondary lg).
- **Visual:** a **live chat mock card** — realistic conversation:
  - user: "What is the error count by service in the traces table?"
  - assistant: streaming text + a small results table (service / error_count rows) + a caption "read-only · 3 rows · 210ms"
  - plus a subtle mono footer strip: `plan → guardrails → execute → explain`.
- **Background:** page bg + faint radial brand glow behind the mock; grid pattern optional (very subtle, `--bg-800` 1px lines at 8% opacity).
- **Responsive:** mock scales down, scrolls horizontally if needed on <640px; CTAs stack full-width.

### 2. Logos / "built on" strip (optional but recommended)

- **Purpose:** credibility.
- **Layout:** single row of muted tech names in mono: ClickHouse · PostgreSQL · LangGraph · FastAPI · MCP. Text-only (no external logos to avoid asset/license issues).

### 3. Value proposition — "One question, four surfaces"

- **Purpose:** show breadth without feature-dump.
- **Layout:** 4 equal cards (icon + title + 2-line copy):
  1. **Web chat** — streaming answers with tables and charts-ready data.
  2. **REST API** — `/ask`, `/connections`, `/evaluations` — typed errors.
  3. **CLI** — `datahek ask "…" --connection ch1`.
  4. **MCP server** — `data.list_tables`, `data.table_schema`, `data.ask` for Claude & agents.
- **Interaction:** cards link to the relevant doc section (docs site).

### 4. Key features (3×2 grid)

- **Purpose:** the differentiators, each provable.
- **Layout:** 6 feature cards (icon, h3, 2–3 line copy, optional mono tag):
  1. **Read-only by construction** — Write operations structurally denied before any provider runs. *(tag: guardrails)*
  2. **Schema-aware planning** — real schema discovery grounds every answer. *(tag: logical plan)*
  3. **Masked before reasoning** — sensitive columns are masked before the model explains. *(tag: privacy)*
  4. **Full audit trail** — every guardrail decision and execution recorded. *(tag: audit)*
  5. **Multi-turn conversations** — follow-ups keep context; results are reusable. *(tag: memory)*
  6. **Evaluation built in** — every execution scored; curated regression datasets. *(tag: quality)*
- **Responsive:** 3×2 → 2×3 (≥768px) → 1 col.

### 5. How it works (4-step pipeline)

- **Purpose:** show the safety pipeline visually.
- **Layout:** horizontal 4-step flow on desktop (numbered, mono), vertical on mobile:
  1. **Connect** — ClickHouse, PostgreSQL, more on the way. `datahek connections`
  2. **Ask** — natural language, follow-ups welcome.
  3. **Guarded plan** — schema → logical plan → read-only + policy checks → execution.
  4. **Explained result** — masked where needed, audited always.
- **Visual:** step cards connected by an arrow line (brand color); each card: number in mono, title, one-line copy.
- **Interaction:** none required (static); optional subtle scroll-reveal.

### 6. Product screenshots / demo

- **Purpose:** prove it works.
- **Layout:** tabbed demo (tabs: Chat / API / MCP / CLI) showing:
  - Chat: real screenshot or accurate HTML mock of the app chat with a live-feeling table.
  - API: a code block with `curl /ask` + JSON response (mono, syntax-highlighted).
  - MCP: `claude mcp add data-vault …` + tool list.
  - CLI: terminal mock (`datahek ask` output).
- **Each tab:** caption below with a "Try it yourself" link to docs.
- **Responsive:** tab content stacks; code blocks horizontally scrollable.

### 7. Use cases / benefits (2-col split)

- **Purpose:** map to real audiences.
- **Layout:** two stacked panels, each with 3 bullets:
  - **For analysts** — ask follow-ups in context; export-ready tables; no SQL writing.
  - **For platform teams** — one guarded data surface for API, CLI, MCP and AI agents; audit and evaluation out of the box.
- **Style:** icon bullets (brand check), no images.

### 8. Social proof / adoption signals

- **Purpose:** early credibility.
- **Layout:** single strip: "Built for self-hosters" + GitHub badge links (stars → "Star on GitHub", issues → "Open an issue") + version pill (`v0.2.0 · 224 tests`). No fabricated testimonials.

### 9. OSS vs Enterprise (comparison)

- **Purpose:** the open-core story; conversion path.
- **Layout:** two cards side by side:
  - **OSS (highlighted, brand border):** "Free · self-hosted · Apache-2.0" + features list (core engine, 2+ connectors, all surfaces, guardrails, audit, evaluation) + CTA "Get started".
  - **Enterprise:** "SSO · multi-tenancy · policy engine · centralized audit" + CTA "Request access".
- **Footnote (muted):** "Enterprise extends OSS through the same contracts — never a fork."

### 10. FAQ

- **Purpose:** remove friction. Accordion (details/summary or controlled), 6–8 items max:
  - "Do I need SQL knowledge?" — No.
  - "What databases are supported?" — ClickHouse and PostgreSQL today; MySQL/SQLite planned.
  - "Is it really read-only?" — Yes, enforced structurally + guardrails.
  - "How do I self-host?" — Docker compose, two commands.
  - "Can AI agents use it?" — MCP server (`/mcp`), same guarded pipeline.
  - "What's the relationship between OSS and Enterprise?" — One core, extension contracts.
- **Accessibility:** buttons with aria-expanded; visible focus.

### 11. Final CTA

- **Purpose:** close the loop.
- **Layout:** centered: headline "Ask your data tonight." + primary CTA "Self-host with Docker" + secondary "Read the docs" + mono hint `docker compose up -d --build`.

### 12. Footer

- **Layout:** 4 columns on desktop (Product / Docs / Community / Legal), stacked on mobile:
  - Product: Self-host, Features, Enterprise, GitHub.
  - Docs: Quick start, API reference, MCP, Evaluation.
  - Community: Issues, Discussions, Changelog (if exists).
  - Legal: License (Apache-2.0) · Privacy (placeholder) — honest placeholders only.
- Bottom strip: © 2026 DataHek · "Built with LangGraph, FastAPI, ClickHouse."

---

## Landing interactions summary

| Element | Default | Hover | Focus | Notes |
|---|---|---|---|---|
| Nav links | `--text-500` | `--text-100` | ring | 150ms |
| Primary CTA | brand solid | brand-600 | glow ring | arrow → slides on hover |
| Feature cards | border-700 | border-600 + lift 2px | ring | clickable → docs |
| FAQ rows | border-700 | bg-900 | ring | expand chevron rotates 180° |
| Tabs (demo) | underline none | text-100 | ring | active = brand underline |

## Responsive landing behavior

| Section | ≥1024px | 640–1023px | <640px |
|---|---|---|---|
| Nav | full | full (compressed CTAs) | hamburger |
| Hero mock | 640px card | 100% width | 100%, horizontal scroll inside |
| Feature grid | 3 cols | 2 cols | 1 col |
| Pipeline | horizontal | horizontal (compact) | vertical |
| Demo tabs | tab row | tab row (scrollable) | tab row scrollable |
| OSS/Enterprise | 2 cards | 2 cards | stacked |
| Footer | 4 cols | 2 cols | 1 col |