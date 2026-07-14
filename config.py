"""Configuration loading, validation, and persistence.

Config file location: ~/.config/hrm/config.json

On missing or malformed config, defaults are returned and the broken file
is renamed with a .corrupt suffix.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

# ── Defaults ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "device_address": "",
    "device_name": "",
    "max_hr": 190,
    "zones": {
        "z1_max": 0.60,
        "z2_max": 0.75,
        "z3_max": 0.88,
    },
    "zone_colors": {
        "Z1": "#888888",
        "Z2": "#4CAF50",
        "Z3": "#FF9800",
        "Z4": "#F44336",
    },
    "graph_window_minutes": 10,
}

CONFIG_DIR = Path.home() / ".config" / "hrm"
CONFIG_PATH = CONFIG_DIR / "config.json"


# ── Public API ───────────────────────────────────────────────────────────

def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from *path* (default ~/.config/hrm/config.json).

    Returns a merged dict of defaults + saved values.  If the file is
    missing, returns defaults unchanged.  If the file is malformed JSON,
    the broken file is renamed with a ``.corrupt`` suffix and defaults
    are returned.
    """
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        return _deep_copy(DEFAULT_CONFIG)

    try:
        raw = cfg_path.read_text(encoding="utf-8")
        saved: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        # Rename broken file so the user can recover it
        _safely_rename_corrupt(cfg_path)
        return _deep_copy(DEFAULT_CONFIG)

    # Merge — saved keys override defaults, missing keys stay at defaults
    merged = _deep_copy(DEFAULT_CONFIG)
    if isinstance(saved, dict):
        _deep_merge(merged, saved)
    return merged


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    """Validate and save *config* to disk.

    Raises ``ValueError`` if validation fails.
    Creates the config directory if it does not exist.
    """
    _validate_config(config)
    cfg_path = path or CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    tmp.replace(cfg_path)


# ── Validation ───────────────────────────────────────────────────────────

def _validate_config(config: dict[str, Any]) -> None:
    """Raise ``ValueError`` if *config* contains invalid values."""
    errors: list[str] = []

    device_address = config.get("device_address", "")
    if not isinstance(device_address, str):
        errors.append(
            f"device_address must be a string, got {device_address!r}"
        )

    device_name = config.get("device_name", "")
    if not isinstance(device_name, str):
        errors.append(f"device_name must be a string, got {device_name!r}")

    max_hr = config.get("max_hr", 190)
    if not isinstance(max_hr, int) or max_hr <= 0:
        errors.append(f"max_hr must be a positive integer, got {max_hr!r}")

    zones = config.get("zones", {})
    try:
        z1 = float(zones.get("z1_max", 0.60))
        z2 = float(zones.get("z2_max", 0.75))
        z3 = float(zones.get("z3_max", 0.88))
    except (ValueError, TypeError, AttributeError):
        errors.append("zone boundaries must be numbers")
    else:
        if not (0 < z1 < z2 < z3 < 1):
            errors.append(
                f"zone boundaries must satisfy 0 < z1_max < z2_max < z3_max < 1, "
                f"got z1_max={z1}, z2_max={z2}, z3_max={z3}"
            )

    colors = config.get("zone_colors", {})
    for zone in ("Z1", "Z2", "Z3", "Z4"):
        color = colors.get(zone, "")
        if not _is_valid_hex_color(color):
            errors.append(f"zone_colors.{zone} must be a hex string like #RRGGBB, got {color!r}")

    gw = config.get("graph_window_minutes", 10)
    if not isinstance(gw, int) or gw <= 0:
        errors.append(f"graph_window_minutes must be a positive integer, got {gw!r}")

    if errors:
        raise ValueError("; ".join(errors))


def _is_valid_hex_color(s: str) -> bool:
    if not isinstance(s, str) or not s.startswith("#") or len(s) != 7:
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False


# ── Internal helpers ─────────────────────────────────────────────────────

def _deep_copy(d: dict) -> dict:
    """Return a deep-enough copy for our simple nested dicts."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deep_copy(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def _deep_merge(base: dict, override: dict) -> None:
    """Merge *override* into *base* in-place (nested dicts recurse)."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _safely_rename_corrupt(path: Path) -> None:
    """Rename a corrupt config file so the user can inspect it."""
    if not path.exists():
        return
    counter = 0
    while True:
        suffix = f".corrupt" if counter == 0 else f".corrupt.{counter}"
        dst = path.with_name(path.name + suffix)
        if not dst.exists():
            shutil.move(str(path), str(dst))
            return
        counter += 1
