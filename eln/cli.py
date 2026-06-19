"""The unified ``labbook`` command — the one entry point to every operation.

Installed via ``[project.scripts]`` (``pip install -e .`` puts ``labbook`` on
PATH). Subcommands call existing library functions; configuration comes from the
unified ``labbook.toml`` (see :mod:`eln.config`).
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from eln.config import load_config
from eln.db import DEFAULT_DB_NAME, DEFAULT_SQL_NAME
from eln.db.rebuild_db import rebuild


def _load(args):
    """Resolve config from the global --config / --root flags."""
    return load_config(args.config, root_override=args.root)


def _ensure_db(config):
    """Ensure experiments.db exists, building from experiments.sql only if
    missing. Never clobbers a live working DB (``rebuild`` is a no-op when the
    binary already exists)."""
    db = config.data_root / DEFAULT_DB_NAME
    sql = config.data_root / DEFAULT_SQL_NAME
    rebuild(sql, db)  # force defaults False -> builds only when db is absent
    return db


# ---- subcommand handlers -------------------------------------------------

def cmd_admin(args):
    from eln.server import create_app

    config = _load(args)
    _ensure_db(config)
    app = create_app(
        config.data_root,
        scan_roots=config.scan_roots,
        channel_aliases=config.channel_aliases,
    )
    url = f"http://localhost:{args.port}/"
    print("=" * 50)
    print(f"Lab Notebook (admin view): {url}")
    print("Local use only — unauthenticated.")
    print("=" * 50)
    if args.scan:
        app.start_background_scan()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(debug=args.debug, port=args.port)
    return 0


def cmd_scan(args):
    from eln.plugins import effective_scan_roots
    from eln.sdgl import SDGL

    config = _load(args)
    sdgl = SDGL(config.data_root)
    roots = effective_scan_roots(config.scan_roots, config.data_root)

    def report(event):
        if event.get("phase") == "root":
            print(f"  scanning {event.get('root')} ({event.get('path')})")
        elif event.get("phase") == "done":
            s = event.get("summary", {})
            print(f"  done: {s}")

    sdgl.scan_roots(roots, progress=report)
    return 0


def cmd_regenerate(args):
    from eln.generators import generate_all

    config = _load(args)
    written = generate_all(config.data_root, args.catalog_out)
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


def cmd_rebuild(args):
    config = _load(args)
    db = config.data_root / DEFAULT_DB_NAME
    sql = config.data_root / DEFAULT_SQL_NAME
    if db.exists() and not args.force:
        if sql.exists() and sql.stat().st_mtime > db.stat().st_mtime:
            print(f"WARNING: {sql} is newer than {db}. Use --force to rebuild.")
        else:
            print(f"{db} already exists; left unchanged (use --force to rebuild).")
        return 0
    rebuild(sql, db, force=args.force)
    print(f"Rebuilt {db} <- {sql}")
    return 0


def cmd_publish(args):
    from eln.server.publish import publish

    config = _load(args)
    result = publish(config.data_root)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    print(result.get("message", "Published."))
    return 0


def cmd_backup(args):
    """Launch the local server and open the explorer, where data can be selected
    and backed up (Roadmap step 8). Reuses the admin server (local, unauthenticated)."""
    from eln.server import create_app

    config = _load(args)
    _ensure_db(config)
    app = create_app(
        config.data_root,
        scan_roots=config.scan_roots,
        channel_aliases=config.channel_aliases,
    )
    url = f"http://localhost:{args.port}/"
    print("=" * 50)
    print(f"Lab Notebook backup: {url}")
    print("Select experiments/files, then click Backup.")
    print("=" * 50)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(debug=False, port=args.port)
    return 0


# ---- parser --------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="labbook", description="Electronic lab notebook CLI.")
    parser.add_argument("--config", default=None, help="path to labbook.toml (overrides discovery)")
    parser.add_argument("--root", default=None, help="data-repo root (overrides ELN_ROOT and config)")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("admin", help="start the server and open the admin/authoring view")
    p.add_argument("--scan", action="store_true", help="run an SDGL scan on startup")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("scan", help="scan configured roots with live feedback")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("regenerate", help="DB -> catalog HTML")
    p.add_argument("--catalog-out", default=None)
    p.set_defaults(func=cmd_regenerate)

    p = sub.add_parser("rebuild", help="experiments.sql -> DB")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("publish", help="DB -> experiments.sql -> commit + push")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("backup", help="launch the data backup flow (step 8)")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.set_defaults(func=cmd_backup)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
