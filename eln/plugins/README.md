# `eln.plugins` — plugin API + extension points

**Roadmap step 9.** Defines the plugin boundary correctly the first time (rather
than coupling features in and extracting them later). **Presentations** is the
first plugin built against this API and the template for future ones.

## Extension points

A plugin is a `Plugin` instance (frozen dataclass). Every field is optional — a
plugin uses only the points it needs:

| Field | Extension point | Shape |
|-------|-----------------|-------|
| `nav` | **nav registration** | `NavLink(label, href)` — added to every page's nav bar |
| `generate` | **generator hook** | `generate(root, catalog_out) -> Path` — writes a static page |
| `static_mount` | **serving route** | `StaticMount(url_prefix, source)` — serve `source(root)` at `/{url_prefix}/<path>` |
| `register_routes` | **serving route** | `register_routes(app, root)` — register arbitrary Flask routes |
| `scan_roots` | **scan-root contribution** | `scan_roots(root) -> list` — extra SDGL scan roots |
| `home_card` + `home_count` | home page | `HomeCard(icon, description)` + `home_count(root) -> int` — a card + stat tile |

## Discovery

`discover_plugins()` merges two sources, deduped by `name` with **built-ins
winning**:

1. **In-tree** — `BUILTIN_PLUGINS` (currently just presentations).
2. **Third-party** — any installed package exposing a `plugin` object under the
   `eln.plugins` entry-point group.

The core never has to know a third-party plugin exists: nav, generation, serving,
and scanning all iterate `discover_plugins()`.

## Writing a third-party plugin (the OSS template)

```python
# my_eln_slides/__init__.py
from pathlib import Path
from eln.plugins import Plugin, NavLink, StaticMount

def generate(root, catalog_out=None):
    out = Path(catalog_out or Path(root) / "catalog") / "slides.html"
    out.write_text("<html>…</html>")
    return out

plugin = Plugin(
    name="slides",
    nav=NavLink("Slides", "slides.html"),
    generate=generate,
    static_mount=StaticMount("slides", lambda root: Path(root) / "slides"),
)
```

```toml
# my_eln_slides/pyproject.toml
[project.entry-points."eln.plugins"]
slides = "my_eln_slides:plugin"
```

`pip install` the package and `labbook regenerate` / the server pick it up
automatically. See `eln/plugins/presentations.py` for the reference plugin and
`docs/superpowers/plans/2026-06-19-presentations-plugin.md` for the design.
