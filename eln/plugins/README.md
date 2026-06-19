# `eln.plugins` — plugin API + extension points

**Roadmap step 8.** Defines the plugin boundary correctly the first time
(rather than coupling features in and extracting them later).

Extension points a plugin can use:

- **nav registration** — add an entry to the catalog navigation.
- **generator hook** — contribute a static page generator.
- **scan-root contribution** — register an additional SDGL scan root.
- **serving route** — register a Flask route.

The first plugin built against this API is **presentations** (Roadmap step 8),
which becomes the template for future plugins. See `docs/ROADMAP.md`.
