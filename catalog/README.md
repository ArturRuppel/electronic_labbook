# `catalog/` — static frontend assets

This directory holds the **hand-written** static frontend assets that ship with
the code:

- `edit-overlay.js` / `edit-overlay.css` — local edit toolbar + inline Edit/Add
  buttons injected by the server into catalog pages.
- `forms.js` — the inline create/edit form modals (experiments, protocols,
  documents, reports) opened from the viewer's Edit/Add buttons.
- `sdgl.html` — the Scientific Data Graph Layer, served at `/`; it is the
  notebook's home page.
- `manifest.webmanifest`, `sw.js`, `icon-*.png` — PWA assets so `labbook admin`
  is installable as a standalone desktop app (own window, launcher icon). The
  server injects the manifest link + service-worker registration into every
  served page's `<head>`.
- shared CSS.

The **generated** pages (`experiments.html`, `protocols.html`, `notebooks.html`,
`reports.html`) are produced by `eln.generators` at build time and are
**gitignored** (`catalog/*.html`). On deploy they are built fresh and served via
GitLab Pages from the **data** repo.

Assets are ported from the original server + overlay; the former standalone admin
panel has been absorbed into the viewer as inline `forms.js` modals.
