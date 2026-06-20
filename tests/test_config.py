import os
import pytest
from pathlib import Path

from eln.config import Config, find_config_path, load_config


def _write_config(tmp_path, data_root, extra=""):
    cfg = tmp_path / "labbook.toml"
    cfg.write_text(
        f'data_root = "{data_root}"\n\n'
        '[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n' + extra,
        encoding="utf-8",
    )
    return cfg


def test_load_config_resolves_data_root_and_relative_scan_roots(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(tmp_path, data)
    c = load_config(cfg)
    assert isinstance(c, Config)
    assert c.data_root == data.resolve()
    assert c.scan_roots[0]["name"] == "data"
    assert c.scan_roots[0]["path"] == (data / "data").resolve()


def test_absolute_scan_root_is_left_absolute(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    ext = tmp_path / "external"
    cfg = _write_config(
        tmp_path, data,
        extra=f'\n[[scan_roots]]\nname = "ext"\npath = "{ext}"\n',
    )
    c = load_config(cfg)
    assert c.scan_roots[1]["path"] == ext.resolve()


def test_channel_aliases_default_empty(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(tmp_path, data)
    assert load_config(cfg).channel_aliases == []


def test_channel_aliases_parsed(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(
        tmp_path, data,
        extra='\n[channels]\naliases = [["GFP", "488", "FITC"], ["RFP", "561"]]\n',
    )
    c = load_config(cfg)
    assert c.channel_aliases == [["GFP", "488", "FITC"], ["RFP", "561"]]


def test_root_override_beats_config(tmp_path):
    data = tmp_path / "data-repo"
    other = tmp_path / "other"
    other.mkdir()
    cfg = _write_config(tmp_path, data)
    c = load_config(cfg, root_override=str(other))
    assert c.data_root == other.resolve()


def test_env_root_beats_config_but_not_override(tmp_path, monkeypatch):
    data = tmp_path / "data-repo"
    env_root = tmp_path / "env"
    env_root.mkdir()
    cli_root = tmp_path / "cli"
    cli_root.mkdir()
    cfg = _write_config(tmp_path, data)
    monkeypatch.setenv("ELN_ROOT", str(env_root))
    assert load_config(cfg).data_root == env_root.resolve()
    assert load_config(cfg, root_override=str(cli_root)).data_root == cli_root.resolve()


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_no_data_root_raises(tmp_path):
    cfg = tmp_path / "labbook.toml"
    cfg.write_text("[scanner]\nrun_on_startup = false\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg)


def test_timestamp_config_defaults_and_override(tmp_path, monkeypatch):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(
        tmp_path, data,
        extra='\n[timestamp]\nenabled = false\ntsa_url = "https://t.example/tsr"\n',
    )
    monkeypatch.delenv("ELN_ROOT", raising=False)
    c = load_config(cfg)
    assert c.timestamp["enabled"] is False
    assert c.timestamp["tsa_url"] == "https://t.example/tsr"


def test_timestamp_config_absent_is_empty(tmp_path, monkeypatch):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(tmp_path, data)
    monkeypatch.delenv("ELN_ROOT", raising=False)
    assert load_config(cfg).timestamp == {}


def test_resolve_timestamp_config_fills_defaults():
    from eln.timestamp import resolve_timestamp_config, DEFAULT_TSA_URL
    cfg = resolve_timestamp_config({})
    assert cfg["enabled"] is True
    assert cfg["tsa_url"] == DEFAULT_TSA_URL
    assert isinstance(cfg["cert_bytes"], bytes) and cfg["cert_bytes"]
    assert "experiments.sql" in cfg["paths"]


def test_find_config_path_uses_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("LABBOOK_CONFIG", str(target))
    assert find_config_path() == target


def test_find_config_path_derives_from_package(monkeypatch):
    monkeypatch.delenv("LABBOOK_CONFIG", raising=False)
    path = find_config_path()
    assert path.name == "labbook.toml"
    assert (path.parent / "pyproject.toml").exists()
