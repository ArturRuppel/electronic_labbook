from eln.channels import build_alias_map, canonical_channel


def test_build_alias_map_maps_variants_to_first_member():
    amap = build_alias_map([["GFP", "488", "FITC"]])
    assert amap == {"gfp": "GFP", "488": "GFP", "fitc": "GFP"}


def test_build_alias_map_ignores_blanks_and_empty_groups():
    amap = build_alias_map([["GFP", "", "  "], [], ["  "]])
    assert amap == {"gfp": "GFP"}


def test_build_alias_map_first_group_wins_on_collision():
    amap = build_alias_map([["GFP", "488"], ["Alexa488", "488"]])
    # "488" was claimed by the GFP group first.
    assert amap["488"] == "GFP"


def test_canonical_channel_is_case_insensitive():
    amap = build_alias_map([["GFP", "488", "FITC"]])
    assert canonical_channel("fitc", amap) == "GFP"
    assert canonical_channel("  488 ", amap) == "GFP"


def test_canonical_channel_passes_through_unknown_and_blank():
    amap = build_alias_map([["GFP", "488"]])
    assert canonical_channel("mCherry", amap) == "mCherry"
    assert canonical_channel("  ", amap) == ""
    assert canonical_channel(None, amap) == ""
