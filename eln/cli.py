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
        scanner=config.scanner,
        timestamp=config.timestamp,
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
    from eln.sdgl import SDGL, hashing_options

    config = _load(args)
    sdgl = SDGL(config.data_root)
    roots = effective_scan_roots(config.scan_roots, config.data_root)
    content_hash, hash_max_bytes = hashing_options(config.scanner)
    content_hash = content_hash or bool(getattr(args, "hash", False))

    def report(event):
        if event.get("phase") == "root":
            print(f"  scanning {event.get('root')} ({event.get('path')})")
        elif event.get("phase") == "done":
            s = event.get("summary", {})
            print(f"  done: {s}")

    if content_hash:
        print("  content hashing: on")
    sdgl.scan_roots(roots, progress=report, content_hash=content_hash,
                    hash_max_bytes=hash_max_bytes)
    return 0


def cmd_verify(args):
    from eln.sdgl import SDGL

    config = _load(args)
    result = SDGL(config.data_root).verify_hashes()
    print(f"  checked {result['checked']} hashed file(s): "
          f"{result['ok']} ok, {len(result['mismatch'])} changed, "
          f"{len(result['missing'])} missing")
    for item in result["mismatch"]:
        print(f"  CHANGED  {item['path']}")
    for item in result["missing"]:
        print(f"  MISSING  {item['path']}")

    from eln import timestamp
    cfg = timestamp.resolve_timestamp_config(config.timestamp)
    ts = timestamp.verify_all(config.data_root, cfg)
    print(f"  {ts['timestamps']} timestamp(s): {ts['ok']} ok, "
          f"{len(ts['invalid'])} invalid, {len(ts['pending'])} pending; "
          f"live snapshot {'anchored' if ts['live_anchored'] else 'NOT anchored'}")
    for item in ts["invalid"]:
        print(f"  INVALID  {item['id']}: {item['reason']}")
    drift = bool(result["mismatch"] or result["missing"] or ts["invalid"])
    return 1 if drift else 0


def cmd_timestamp(args):
    from eln import timestamp

    config = _load(args)
    cfg = timestamp.resolve_timestamp_config(config.timestamp)
    if args.retry:
        updated = timestamp.retry_pending(config.data_root, cfg)
        print(f"  completed {len(updated)} pending timestamp(s)")
        for entry in updated:
            print(f"  OK  {entry['id']}")
    else:
        entry = timestamp.create_timestamp(config.data_root, cfg["paths"], cfg)
        print(f"  {entry['status'].upper()}  {entry['id']}")
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
    and backed up. Reuses the admin server (local, unauthenticated)."""
    from eln.server import create_app

    config = _load(args)
    _ensure_db(config)
    app = create_app(
        config.data_root,
        scan_roots=config.scan_roots,
        channel_aliases=config.channel_aliases,
        scanner=config.scanner,
        timestamp=config.timestamp,
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


def cmd_export(args):
    """Write a self-contained static HTML bundle: the whole
    catalog, a single report, or a single presentation, to --dest."""
    from eln.share import export_all, export_item

    config = _load(args)
    _ensure_db(config)
    if args.all:
        result = export_all(config.data_root, args.dest)
    elif args.report:
        result = export_item(config.data_root, args.dest, "report", args.report)
    elif args.presentation:
        result = export_item(config.data_root, args.dest, "presentation", args.presentation)
    else:
        print("nothing to export: pass --all, --report ID, or --presentation ID",
              file=sys.stderr)
        return 1
    print(f"Exported {result['files']} files ({result['bytes']:,} bytes) to {args.dest}")
    for rel in result["missing"]:
        print(f"  WARNING missing referenced asset (skipped): {rel}", file=sys.stderr)
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
    p.add_argument("--hash", action="store_true",
                   help="store a SHA-256 per file (overrides [scanner].content_hashing)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("verify", help="recompute file hashes + verify timestamps")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("timestamp",
                       help="obtain an RFC 3161 trusted timestamp (or --retry pending)")
    p.add_argument("--retry", action="store_true",
                   help="re-request tokens for pending timestamps")
    p.set_defaults(func=cmd_timestamp)

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

    p = sub.add_parser("export", help="write a self-contained static HTML bundle")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="export the whole catalog")
    g.add_argument("--report", help="export a single report (path under reports/)")
    g.add_argument("--presentation", help="export a single presentation (dir name)")
    p.add_argument("--dest", required=True, help="output folder for the bundle")
    p.set_defaults(func=cmd_export)

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
