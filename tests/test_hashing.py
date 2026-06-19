import hashlib

from eln.hashing import sha256_file, sha256_hex


def test_sha256_hex_matches_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    assert sha256_hex(f) == hashlib.sha256(b"hello world").hexdigest()


def test_sha256_file_is_prefixed(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    assert sha256_file(f) == "sha256:" + hashlib.sha256(b"hello world").hexdigest()


def test_sha256_hex_streams_large_input(tmp_path):
    f = tmp_path / "big.bin"
    payload = b"x" * (3 * (1 << 20) + 7)  # spans several 1 MiB chunks
    f.write_bytes(payload)
    assert sha256_hex(f) == hashlib.sha256(payload).hexdigest()
