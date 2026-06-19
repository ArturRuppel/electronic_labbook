import hashlib
from pathlib import Path

from eln.sdgl.backup import hash_file, dest_subpath


def test_hash_file_matches_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world" * 1000)
    assert hash_file(str(f)) == hashlib.sha256(f.read_bytes()).hexdigest()


def test_dest_subpath_experiment():
    assert dest_subpath("experiment:TFMSP-01") == Path("TFMSP") / "TFMSP-01"


def test_dest_subpath_excluded_repetition():
    assert dest_subpath("experiment:COV2D-X03") == Path("COV2D") / "COV2D-X03"


def test_dest_subpath_aggregate():
    assert dest_subpath("aggregate_analysis:TFMSP") == Path("TFMSP") / "TFMSP_aggregate"
