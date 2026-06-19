"""Run the local lab-notebook server: ``python -m eln.server ROOT [--port 5000]``.

ROOT is the data-repo root (holds experiments.db, sdgl.db, reports/,
presentations/, thumbnails/, sdgl.toml). Local-only and unauthenticated.
"""

import argparse
from pathlib import Path

from eln.server.app import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-scan", action="store_true",
                        help="skip the configured startup SDGL scan")
    args = parser.parse_args(argv)

    app = create_app(args.root)
    print("=" * 50)
    print(f"Lab Notebook server: http://localhost:{args.port}")
    print("Note: This server is for local use only")
    print("=" * 50)
    if not args.no_scan:
        app.start_background_scan()
    app.run(debug=args.debug, port=args.port)


if __name__ == "__main__":
    main()
