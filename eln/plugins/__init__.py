"""Plugin system (Roadmap step 9) — the OSS plugin template.

A plugin extends the notebook through four clean extension points, each an
optional field on :class:`Plugin`:

- **nav registration** — :class:`NavLink` shown in every page's nav bar.
- **generator hook** — ``generate(root, catalog_out)`` writes a static page.
- **serving route** — :class:`StaticMount` (and optional ``register_routes``)
  served by the Flask app.
- **scan-root contribution** — ``scan_roots(root)`` adds directories to the SDGL
  scan.

Plugins are discovered from two sources, merged and deduped by ``name`` with the
built-ins winning: the in-tree :data:`BUILTIN_PLUGINS` list, and third-party
packages that expose a ``plugin`` object via the ``eln.plugins`` entry-point
group (``[project.entry-points."eln.plugins"]`` in their ``pyproject.toml``).
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class NavLink:
    """A nav-bar entry. ``href`` is the generated page's filename (also its URL)."""

    label: str
    href: str


@dataclass(frozen=True)
class StaticMount:
    """Serve ``source(root)`` at ``/{url_prefix}/<path>``."""

    url_prefix: str
    source: Callable[[Path], Path]


@dataclass(frozen=True)
class HomeCard:
    """Presentation metadata for the home-page card. Title and href come from the
    plugin's :class:`NavLink`; the count (if any) from ``home_count``."""

    icon: str
    description: str


@dataclass(frozen=True)
class Plugin:
    """A unit of notebook functionality. Every extension point is optional."""

    name: str
    nav: Optional[NavLink] = None
    generate: Optional[Callable[..., Path]] = None
    static_mount: Optional[StaticMount] = None
    scan_roots: Optional[Callable[[Path], list]] = None
    register_routes: Optional[Callable[[Any, Path], None]] = None
    home_card: Optional[HomeCard] = None
    home_count: Optional[Callable[[Path], int]] = None


def _builtin_plugins() -> list:
    """The in-tree plugins. Imported lazily to avoid an import cycle (the
    presentations plugin imports names from this module)."""
    from eln.plugins import presentations

    return [presentations.plugin]


def _entry_point_plugins() -> list:
    """Third-party plugins advertised under the ``eln.plugins`` entry-point group.

    Tolerant of a missing group / old importlib.metadata so the core never fails
    to start just because no external plugins are installed."""
    try:
        eps = importlib.metadata.entry_points(group="eln.plugins")
    except TypeError:  # Python <3.10 selection API
        eps = importlib.metadata.entry_points().get("eln.plugins", [])
    plugins = []
    for ep in eps:
        try:
            plugins.append(ep.load())
        except Exception:  # noqa: BLE001 — a broken third-party plugin must not crash core
            continue
    return plugins


def discover_plugins() -> list:
    """All plugins, built-ins first, deduped by ``name`` (built-ins win)."""
    seen, out = set(), []
    for plugin in [*_builtin_plugins(), *_entry_point_plugins()]:
        if plugin.name in seen:
            continue
        seen.add(plugin.name)
        out.append(plugin)
    return out


__all__ = ["NavLink", "StaticMount", "HomeCard", "Plugin", "discover_plugins"]
