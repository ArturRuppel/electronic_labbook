# `eln.server` — Flask API + overlay/admin + publish

**Roadmap step 6.** Ported from the original `api_server.py` + `catalog/` overlay.

`create_app(root)` builds the local Flask app bound to a **data-repo root** (the
same root the generators and SDGL use). Run it with the unified CLI:

```bash
labbook admin [--port 5000] [--scan] [--no-browser]
```

(The data-repo root comes from `labbook.toml` / `ELN_ROOT` / `--root`.)

The server is **local-only and unauthenticated by design**.

## What it serves

- **REST API** (`/api/*`): experiments (incl. CODE-NN id resolution), protocols,
  reports, tags, the full SDGL graph/tree/scan surface, `/api/regenerate`, and
  `/api/publish`.
- **HTML with overlay injection**: generated pages (`experiments.html`,
  `protocols.html`, `reports.html`, `presentations.html`, `index.html`) are read
  from `root/catalog/`; the static frontend (`sdgl.html` at `/`, `admin.html`,
  `admin.js`, `edit-overlay.*`) ships in the **code repo's** `catalog/` and is
  found via `ASSETS_DIR`. On serve, `auth.js` is stripped and the edit overlay is
  injected before `</body>`.
- `auth.js` is served as a **no-op** locally; the real Pages password gate is a
  *deployment* concern (see `catalog/auth.js.example`), so no password hash is
  committed to the public code repo.

## Two architectural changes vs. the original

1. **Regenerate runs in-process** (`generate_all(root, catalog_dir)`) instead of
   shelling out to `scripts/`.
2. **Publish targets the data repo, diffably.** `eln.server.publish.publish(root)`
   materializes CODE-NN identifiers, dumps `experiments.sql` via `eln.db.dump`,
   then `git add experiments.sql reports/ presentations/ thumbnails/` + commit +
   push — the binary `experiments.db` is **never** committed. The static
   `catalog/` is not committed either; GitLab CI rebuilds it (ROADMAP step 7).

## Modules

- `app.py` — the `create_app` factory and all routes.
- `experiment_ids.py` — pure, cursor-based CODE-NN helpers (code allocation,
  repetition namespaces, the excluded `X` marker), unit-tested without Flask.
- `publish.py` — the data-repo publish flow.

Tested by `tests/server/` (app end-to-end, id helpers, publish into a real git repo).
