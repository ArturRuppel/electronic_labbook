"""Plugin registry: built-in plugins + third-party entry-point discovery."""

from eln.plugins import Plugin, NavLink, discover_plugins, effective_scan_roots


def test_builtin_includes_presentations():
    names = {p.name for p in discover_plugins()}
    assert "presentations" in names


def test_presentations_declares_nav_and_generator():
    pres = next(p for p in discover_plugins() if p.name == "presentations")
    assert isinstance(pres.nav, NavLink)
    assert pres.nav.href == "presentations.html"
    assert callable(pres.generate)


def test_entry_point_plugins_are_merged(monkeypatch):
    extra = Plugin(name="widgets", nav=NavLink("Widgets", "widgets.html"))

    class _EP:
        name = "widgets"

        def load(self):
            return extra

    monkeypatch.setattr("eln.plugins._entry_point_plugins", lambda: [extra])
    names = {p.name for p in discover_plugins()}
    assert {"presentations", "widgets"} <= names


def test_effective_scan_roots_appends_plugin_roots():
    base = [{"name": "data", "path": "/data"}]
    contributor = Plugin(
        name="decks",
        scan_roots=lambda root: [{"name": "decks", "path": f"{root}/decks"}],
    )
    roots = effective_scan_roots(base, "/repo", plugins=[contributor])
    assert {"name": "data", "path": "/data"} in roots
    assert {"name": "decks", "path": "/repo/decks"} in roots


def test_effective_scan_roots_unchanged_without_contributors():
    base = [{"name": "data", "path": "/data"}]
    quiet = Plugin(name="quiet")  # no scan_roots
    assert effective_scan_roots(base, "/repo", plugins=[quiet]) == base


def test_builtin_wins_over_duplicate_entry_point(monkeypatch):
    impostor = Plugin(name="presentations", nav=NavLink("Fake", "fake.html"))
    monkeypatch.setattr("eln.plugins._entry_point_plugins", lambda: [impostor])
    pres = [p for p in discover_plugins() if p.name == "presentations"]
    assert len(pres) == 1
    assert pres[0].nav.href == "presentations.html"  # built-in, not the impostor
