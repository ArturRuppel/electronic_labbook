# `catalog/` — static frontend assets

This directory holds the **hand-written** static frontend assets that ship with
the code:

- `edit-overlay.js` / `edit-overlay.css` — local edit toolbar injected by the
  server into catalog pages.
- `admin.js` / `admin.html` — the admin panel (with deep-link support).
- shared CSS.

The **generated** pages (`index.html`, `experiments.html`, `protocols.html`,
`reports.html`) are produced by `eln.generators` at build time and are
**gitignored** (`catalog/*.html`). On deploy they are built fresh and served via
GitLab Pages from the **data** repo.

Assets are ported in Roadmap step 6 (server + overlay/admin).
