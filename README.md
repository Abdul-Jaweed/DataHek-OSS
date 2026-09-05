# DataHek Cloud — public marketing site (GitHub Pages)

The public-facing website for **DataHek Cloud**, the hosted product. Deployed independently through GitHub Pages — it does not run inside the OSS application and has no dependencies on it.

## Pages

| Page | Purpose |
|---|---|
| `index.html` | Home — problem, audience, features, hosted vs OSS, CTA |
| `features.html` | Detailed feature breakdown |
| `pricing.html` | Pricing — only **Open Source** (free, self-hosted) and **Enterprise** (Coming Soon) |

## Structure

```
├── index.html        # home — hero, problem, audience, features, hosted vs OSS, CTA
├── features.html     # detailed feature breakdown
├── pricing.html      # OSS (free, self-hosted) + Enterprise (Coming Soon)
├── assets/
│   ├── css/site.css  # shared design system (light + auto dark)
│   ├── js/site.js    # nav toggle, scroll reveal, demo form, year
│   └── img/favicon.svg
└── .nojekyll         # disable Jekyll processing
```

Pure static HTML/CSS/JS — no build step. All links are relative, so the site works at any GitHub Pages base path. This branch's repository root **is** the website.

## Deploy to GitHub Pages

### Option A — Deploy from this branch (recommended)

1. Repo → **Settings → Pages** → Source: **Deploy from a branch**
2. Branch: `feature/landing-page` → folder: `/ (root)`
3. The branch root is the website — push changes to this branch and Pages updates automatically.

### Option B — GitHub Actions (requires workflow-scoped token)

Add `.github/workflows/pages.yml` (upload-pages-artifact with `path: '.'`) and set Pages source to **GitHub Actions**. Pushing workflow files requires a token with the `workflow` scope (`gh auth login --scopes workflow`).

### Manual deploy (anywhere)

Serve the folder statically:

```bash
python -m http.server 8080
```

or drag the folder into Netlify/Vercel/Cloudflare Pages — no configuration needed.

## Content notes

- **Branding**: DataHek **Cloud** (hosted product) vs DataHek **OSS** (Apache-2.0, self-hosted). The footer and comparison table keep the two clearly distinct.
- **Pricing**: exactly two offerings — OSS (Free) and Enterprise (Coming Soon). No other tiers.
- **Enterprise** is always labeled "Coming Soon" with a waitlist CTA — never purchasable.
- The waitlist form (`index.html#get-started`) is a demo capture — wire it to your email/CRM backend when ready.