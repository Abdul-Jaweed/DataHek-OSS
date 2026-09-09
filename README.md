# DataHek OSS — landing page branch

This branch's repository root **is** the OSS landing page (GitHub Pages–deployable).

- `index.html` — hero, features, how it works, quick start, stack, CTA
- `assets/` — shared CSS/JS/favicon (auto light/dark via OS preference)
- `.nojekyll` — disables Jekyll processing

## Deploy to GitHub Pages

1. Repo → **Settings → Pages** → Source: **Deploy from a branch**
2. Branch: `oss-landing-page` → folder: `/ (root)`

Pure static HTML — no build step. Or serve locally: `python -m http.server 8080`.

> This is the **open-source** landing page. The hosted-product site lives on `feature/landing-page`; the application itself on `main`.
