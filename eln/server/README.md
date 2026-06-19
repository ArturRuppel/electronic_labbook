# `eln.server` — Flask API + overlay/admin + publish

**Roadmap step 6.**

Lands here (ported from the original `api_server.py` + `catalog/` overlay):

- REST API routes (`/api/*`) and HTML serving with overlay injection.
- `admin.js` admin panel (incl. title ↔ ID synchronization).
- Overlay injection: read HTML, strip `auth.js`, inject overlay `<link>` +
  `<script>` before `</body>` for local editing.
- **Publish flow** that commits `experiments.sql` to the **data** repo (not this
  code repo).

Static overlay/admin assets live in `../catalog/`. See `docs/ROADMAP.md`.
