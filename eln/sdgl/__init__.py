"""Scientific Data Graph Layer (SDGL) — the project's differentiator.

Public API re-exported from :mod:`eln.sdgl.engine`. See ``docs/ROADMAP.md`` step 4
and the SDGL design spec.
"""

from .engine import (
    SDGL,
    allocate_experiment_codes,
    allocate_experiment_uids,
    derive_code,
    format_experiment_id,
    parse_code_folder,
    parse_id_folder,
    parse_sdgl_toml,
    update_labbook,
)

__all__ = [
    "SDGL",
    "allocate_experiment_codes",
    "allocate_experiment_uids",
    "derive_code",
    "format_experiment_id",
    "parse_code_folder",
    "parse_id_folder",
    "parse_sdgl_toml",
    "update_labbook",
]
