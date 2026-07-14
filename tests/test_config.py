"""Tests for config load/save/validation."""

import json
import os
import tempfile
from pathlib import Path

import pytest

import config as cfg_mod


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def temp_config_path() -> Path:
    """Return a temporary path for config (deleted after test)."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "config.json"


# ── Defaults ────────────────────────────────────────────────────────────

def test_default_config_values() -> None:
    cfg = cfg_mod.load_config(path=Path("/nonexistent/config.json"))
    assert cfg["device_address"] == ""
    assert cfg["device_name"] == ""
    assert cfg["max_hr"] == 190
    assert cfg["zones"]["z1_max"] == 0.60
    assert cfg["zones"]["z2_max"] == 0.75
    assert cfg["zones"]["z3_max"] == 0.88
    assert cfg["zone_colors"]["Z1"] == "#888888"
    assert cfg["zone_colors"]["Z2"] == "#4CAF50"
    assert cfg["zone_colors"]["Z3"] == "#FF9800"
    assert cfg["zone_colors"]["Z4"] == "#F44336"
    assert cfg["graph_window_minutes"] == 10


def test_missing_config_returns_defaults(temp_config_path: Path) -> None:
    cfg = cfg_mod.load_config(path=temp_config_path)
    assert cfg["max_hr"] == 190


def test_save_and_load(temp_config_path: Path) -> None:
    config = cfg_mod.load_config(path=temp_config_path)
    config["max_hr"] = 175
    config["device_address"] = "AA:BB:CC:DD:EE:FF"
    config["device_name"] = "Polar H10"
    cfg_mod.save_config(config, path=temp_config_path)

    loaded = cfg_mod.load_config(path=temp_config_path)
    assert loaded["max_hr"] == 175
    assert loaded["device_address"] == "AA:BB:CC:DD:EE:FF"
    assert loaded["device_name"] == "Polar H10"
    assert loaded["zones"]["z1_max"] == 0.60  # unchanged


def test_save_creates_directory(temp_config_path: Path) -> None:
    # Remove the parent dir first
    parent = temp_config_path.parent
    if parent.exists():
        import shutil
        shutil.rmtree(parent)
    assert not parent.exists()
    cfg_mod.save_config(cfg_mod.load_config(path=temp_config_path), path=temp_config_path)
    assert parent.exists()
    assert temp_config_path.exists()


# ── Malformed JSON ──────────────────────────────────────────────────────

def test_malformed_json_returns_defaults(temp_config_path: Path) -> None:
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    original_content = "this is not json"
    temp_config_path.write_text(original_content, encoding="utf-8")

    cfg = cfg_mod.load_config(path=temp_config_path)
    assert cfg["max_hr"] == 190
    # Corrupt file should have been renamed (config.json.corrupt or config.json.corrupt.0 etc.)
    # The original file is no longer at config.json
    assert not temp_config_path.exists()
    corrupt_files = sorted(temp_config_path.parent.glob("*corrupt*"))
    assert len(corrupt_files) >= 1, f"Expected corrupt files, found: {list(temp_config_path.parent.iterdir())}"


def test_empty_json_returns_defaults(temp_config_path: Path) -> None:
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_config_path.write_text("{}", encoding="utf-8")

    cfg = cfg_mod.load_config(path=temp_config_path)
    assert cfg["max_hr"] == 190
    assert cfg["device_address"] == ""
    assert cfg["device_name"] == ""


def test_partial_config_merges_with_defaults(temp_config_path: Path) -> None:
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_config_path.write_text(
        json.dumps({"max_hr": 180}), encoding="utf-8"
    )

    cfg = cfg_mod.load_config(path=temp_config_path)
    assert cfg["max_hr"] == 180
    assert cfg["zones"]["z1_max"] == 0.60  # default
    assert cfg["device_address"] == ""  # default
    assert cfg["device_name"] == ""  # default


def test_extra_keys_ignored(temp_config_path: Path) -> None:
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_config_path.write_text(
        json.dumps({"max_hr": 200, "future_key": "v2"}), encoding="utf-8"
    )

    cfg = cfg_mod.load_config(path=temp_config_path)
    assert cfg["max_hr"] == 200
    # Extra keys from saved config are preserved (they may be used by future versions)
    # Key requirement: they should not break loading
    assert "future_key" in cfg  # preserved, not harmful


def test_device_address_can_be_uuid_string(temp_config_path: Path) -> None:
    cfg = cfg_mod.load_config(path=temp_config_path)
    cfg["device_address"] = "7A6B6C7D-8E8F-9091-A1B2-C3D4E5F60708"
    cfg["device_name"] = "Chest Strap"
    cfg_mod.save_config(cfg, path=temp_config_path)

    loaded = cfg_mod.load_config(path=temp_config_path)
    assert loaded["device_address"] == "7A6B6C7D-8E8F-9091-A1B2-C3D4E5F60708"
    assert loaded["device_name"] == "Chest Strap"


# ── Validation ──────────────────────────────────────────────────────────

def test_validate_max_hr_zero() -> None:
    with pytest.raises(ValueError, match="max_hr"):
        cfg_mod.save_config({"max_hr": 0, "zones": cfg_mod.DEFAULT_CONFIG["zones"],
                             "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
                             "graph_window_minutes": 10, "device_address": ""},
                            path=Path("/tmp/_test_invalid.json.tmp"))


def test_validate_max_hr_negative() -> None:
    with pytest.raises(ValueError, match="max_hr"):
        cfg_mod.save_config({"max_hr": -10, "zones": cfg_mod.DEFAULT_CONFIG["zones"],
                             "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
                             "graph_window_minutes": 10, "device_address": ""},
                            path=Path("/tmp/_test_invalid.json.tmp"))


def test_validate_non_monotonic_zones() -> None:
    with pytest.raises(ValueError, match="zone boundaries"):
        cfg_mod.save_config({
            "max_hr": 190,
            "zones": {"z1_max": 0.80, "z2_max": 0.60, "z3_max": 0.88},
            "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
            "graph_window_minutes": 10, "device_address": "",
        }, path=Path("/tmp/_test_invalid.json.tmp"))


def test_validate_invalid_color() -> None:
    with pytest.raises(ValueError, match="zone_colors"):
        cfg_mod.save_config({
            "max_hr": 190,
            "zones": cfg_mod.DEFAULT_CONFIG["zones"],
            "zone_colors": {"Z1": "not-a-color", "Z2": "#4CAF50", "Z3": "#FF9800", "Z4": "#F44336"},
            "graph_window_minutes": 10, "device_address": "",
        }, path=Path("/tmp/_test_invalid.json.tmp"))


def test_validate_device_fields_must_be_strings() -> None:
    with pytest.raises(ValueError, match="device_address"):
        cfg_mod.save_config({
            "device_address": 123,
            "device_name": "",
            "max_hr": 190,
            "zones": cfg_mod.DEFAULT_CONFIG["zones"],
            "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
            "graph_window_minutes": 10,
        }, path=Path("/tmp/_test_invalid.json.tmp"))

    with pytest.raises(ValueError, match="device_name"):
        cfg_mod.save_config({
            "device_address": "",
            "device_name": 123,
            "max_hr": 190,
            "zones": cfg_mod.DEFAULT_CONFIG["zones"],
            "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
            "graph_window_minutes": 10,
        }, path=Path("/tmp/_test_invalid.json.tmp"))


def test_validate_graph_window_zero() -> None:
    with pytest.raises(ValueError, match="graph_window_minutes"):
        cfg_mod.save_config({
            "max_hr": 190,
            "zones": cfg_mod.DEFAULT_CONFIG["zones"],
            "zone_colors": cfg_mod.DEFAULT_CONFIG["zone_colors"],
            "graph_window_minutes": 0, "device_address": "",
        }, path=Path("/tmp/_test_invalid.json.tmp"))


def test_valid_config_saves(temp_config_path: Path) -> None:
    cfg = cfg_mod.load_config(path=temp_config_path)
    cfg["max_hr"] = 200
    cfg["zones"]["z1_max"] = 0.50
    cfg_mod.save_config(cfg, path=temp_config_path)
    # Should not raise


# ── Config dir creation ─────────────────────────────────────────────────

def test_save_creates_config_dir_implicit() -> None:
    """save_config creates the config directory on save."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "nested" / "dir" / "config.json"
        cfg = cfg_mod.DEFAULT_CONFIG.copy()
        cfg_mod.save_config(cfg, path=p)
        assert p.exists()
