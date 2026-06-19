"""Run all static page generators: ``python -m eln.generators ROOT [--catalog-out DIR]``."""

import argparse
from pathlib import Path

from eln.generators import generate_all


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds experiments.db, reports/, ...)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    written = generate_all(args.root, args.catalog_out)
    for name, path in written.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
