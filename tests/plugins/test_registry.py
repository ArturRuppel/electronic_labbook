"""Plugin registry: built-in plugins + third-party entry-point discovery."""

from eln.plugins import Plugin, NavLink, discover_plugins


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


def test_builtin_wins_over_duplicate_entry_point(monkeypatch):
    impostor = Plugin(name="presentations", nav=NavLink("Fake", "fake.html"))
    monkeypatch.setattr("eln.plugins._entry_point_plugins", lambda: [impostor])
    pres = [p for p in discover_plugins() if p.name == "presentations"]
    assert len(pres) == 1
    assert pres[0].nav.href == "presentations.html"  # built-in, not the impostor
