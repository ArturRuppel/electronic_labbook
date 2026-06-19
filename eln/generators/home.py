#!/usr/bin/env python3
"""Generate the home/landing page (``index.html``) from a static template.

The template ``home_template.html`` is a code-repo asset (input); statistics are
read from the data-repo *root* and the output ``index.html`` is written into the
data-repo ``catalog/``. "Last updated" is date-only, so regenerating twice on the
same day is byte-identical.
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from eln.plugins import discover_plugins

DEFAULT_DB_NAME = "experiments.db"
# Bundled static template lives in the code repo's catalog/ directory.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "catalog"

# Card/stat markup matches the template's hand-written tiles byte-for-byte so the
# plugin-injected presentations card is indistinguishable from the core cards.
_CARD = (
    '            <a href="{href}" class="card">\n'
    '                <div class="card-icon">{icon}</div>\n'
    '                <div class="card-title">{label}</div>\n'
    '                <div class="card-description">{desc}</div>\n'
    '            </a>'
)
_STAT = (
    '            <div class="stat-item"><div class="stat-number">{count}</div>'
    '<div class="stat-label">{label}</div></div>'
)


def _plugin_cards(plugins):
    """Render one home-page card per plugin that declares a nav entry + home card."""
    cards = [
        _CARD.format(href=p.nav.href, icon=p.home_card.icon,
                     label=p.nav.label, desc=p.home_card.description)
        for p in plugins if p.nav and p.home_card
    ]
    return "\n".join(cards)


def _plugin_stats(plugins, root):
    """Render one stat tile per plugin that declares a nav entry + counter."""
    stats = [
        _STAT.format(count=p.home_count(root), label=p.nav.label)
        for p in plugins if p.nav and p.home_count
    ]
    return "\n".join(stats)


def generate_home(root, catalog_out=None, template_path=None, plugins=None):
    """Generate ``index.html`` for the data-repo at *root*.

    *template_path* defaults to the bundled ``catalog/home_template.html``; output
    is written to *catalog_out* (default ``root/catalog``).
    """
    root = Path(root)
    database_path = root / DEFAULT_DB_NAME
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"
    template_file = Path(template_path) if template_path else ASSETS_DIR / "home_template.html"

    # Get statistics
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM experiments")
    total_experiments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT name) FROM protocols")
    total_protocols = cursor.fetchone()[0]

    conn.close()

    # Count reports
    reports_dir = root / "reports"
    total_reports = len(list(reports_dir.glob("**/*.md"))) if reports_dir.exists() else 0

    # Read template
    html = template_file.read_text()

    # Plugin-contributed cards + stat tiles (e.g. presentations).
    if plugins is None:
        plugins = discover_plugins()
    html = html.replace('__PLUGIN_CARDS__', _plugin_cards(plugins))
    html = html.replace('__PLUGIN_STATS__', _plugin_stats(plugins, root))

    # Replace placeholders
    html = html.replace('__TOTAL_EXPERIMENTS__', str(total_experiments))
    html = html.replace('__TOTAL_PROTOCOLS__', str(total_protocols))
    html = html.replace('__TOTAL_REPORTS__', str(total_reports))
    html = html.replace('__UPDATE_DATE__', datetime.now().strftime("%Y-%m-%d"))

    # Write to file
    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "index.html"
    output_file.write_text(html)

    print(f"Home page generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds experiments.db)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    parser.add_argument("--template", type=Path, default=None,
                        help="home template (default: bundled catalog/home_template.html)")
    args = parser.parse_args(argv)
    generate_home(args.root, args.catalog_out, args.template)


if __name__ == "__main__":
    main()
