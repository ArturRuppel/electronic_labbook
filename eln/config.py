"""Unified configuration for the labbook CLI.

One ``labbook.toml`` (gitignored, in the code repo) replaces the old in-repo
``sdgl.toml`` and additionally records ``data_root`` — the data-repo location.
The file is discovered from the installed package's code-repo checkout (the
directory containing ``pyproject.toml``), overridable by ``--config`` /
``LABBOOK_CONFIG``. The data root is overridable by ``--root`` / ``ELN_ROOT``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.9 / 3.10
    import tomli as tomllib

CONFIG_FILENAME = "labbook.toml"
ENV_CONFIG = "LABBOOK_CONFIG"
ENV_ROOT = "ELN_ROOT"


@dataclass
class Config:
    """Resolved configuration. ``scan_roots`` paths are absolute."""

    data_root: Path
    scanner: dict = field(default_factory=dict)
    scan_roots: list = field(default_factory=list)  # [{"name": str, "path": Path}]
    channel_aliases: list = field(default_factory=list)  # [[canonical, variant, ...]]


def find_config_path() -> Path:
    """Locate ``labbook.toml``.

    ``LABBOOK_CONFIG`` wins; otherwise derive the code-repo checkout from this
    package's location (the nearest parent holding ``pyproject.toml``).
    """
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent / CONFIG_FILENAME
    raise FileNotFoundError(
        "Could not locate the code-repo root (no pyproject.toml above "
        f"{here}). Set {ENV_CONFIG} to the labbook.toml path."
    )


def load_config(config_path=None, *, root_override=None) -> Config:
    """Parse the unified config into a :class:`Config`.

    Root precedence: ``root_override`` (``--root``) > ``ELN_ROOT`` > the file's
    ``data_root``. Relative ``scan_roots`` paths resolve against ``data_root``.
    """
    path = Path(config_path) if config_path else find_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Copy labbook.toml.example to {path}."
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    root = root_override or os.environ.get(ENV_ROOT) or data.get("data_root")
    if not root:
        raise ValueError(
            "No data_root: set --root, ELN_ROOT, or data_root in the config."
        )
    data_root = Path(root).expanduser().resolve()

    scan_roots = []
    for entry in data.get("scan_roots", []):
        p = Path(entry["path"]).expanduser()
        if not p.is_absolute():
            p = data_root / p
        scan_roots.append({"name": entry.get("name"), "path": p.resolve()})

    # Channel fungibility: equivalence groups of interchangeable markers
    # (e.g. ["GFP", "488", "FITC"]); the first member is canonical.
    channel_aliases = [
        list(group) for group in data.get("channels", {}).get("aliases", [])
    ]

    return Config(
        data_root=data_root,
        scanner=data.get("scanner", {}),
        scan_roots=scan_roots,
        channel_aliases=channel_aliases,
    )
