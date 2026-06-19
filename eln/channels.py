"""Channel fungibility: collapse equivalent channel markers to a canonical name.

Microscopy markers are recorded by many interchangeable names — the same dye
appears as ``"GFP"``, ``"488"``, or ``"FITC"`` depending on who typed it. When
the lab declares such equivalences in ``labbook.toml`` (``[channels].aliases``),
this module maps every variant onto a single canonical label so autocomplete
suggestions and grouping treat them as one.

The config shape is a list of equivalence groups; the first member of each group
is the canonical label::

    [channels]
    aliases = [
        ["GFP", "488", "FITC"],
        ["RFP", "561", "mCherry"],
    ]
"""

from __future__ import annotations


def build_alias_map(groups):
    """Build a ``{lowercased variant: canonical}`` map from equivalence groups.

    ``groups`` is a list of lists; the first non-empty member of each group is
    its canonical label. Blank entries are ignored, and a later group never
    overrides a variant already claimed by an earlier one.
    """
    alias_map = {}
    for group in groups or []:
        members = [str(m).strip() for m in group if str(m).strip()]
        if not members:
            continue
        canonical = members[0]
        for member in members:
            alias_map.setdefault(member.lower(), canonical)
    return alias_map


def canonical_channel(value, alias_map):
    """Return the canonical label for ``value``, or its trimmed self if unknown.

    Lookup is case-insensitive; an empty/whitespace value yields ``""``.
    """
    text = (value or "").strip()
    if not text:
        return ""
    return alias_map.get(text.lower(), text)
