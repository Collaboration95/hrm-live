"""Tests for zone calculation and helpers."""

import pytest

from zones import (
    get_zone,
    zone_color,
    zone_label,
    validate_zones,
    DEFAULT_COLORS,
    ZONE_LABELS,
)


# ── Zone calculation ────────────────────────────────────────────────────

DEFAULT_ZONES = {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}


def test_zone_z1_below_60() -> None:
    # 113 / 190 ≈ 0.595 < 0.60 → Z1
    assert get_zone(113, 190, DEFAULT_ZONES) == "Z1"


def test_zone_z1_at_zero() -> None:
    assert get_zone(0, 190, DEFAULT_ZONES) == "Z1"


def test_zone_z2_exactly_60() -> None:
    # 114 / 190 = 0.60 → Z2
    assert get_zone(114, 190, DEFAULT_ZONES) == "Z2"


def test_zone_z2_mid() -> None:
    # 130 / 190 ≈ 0.684 → Z2
    assert get_zone(130, 190, DEFAULT_ZONES) == "Z2"


def test_zone_z2_just_below_75() -> None:
    # 142 / 190 ≈ 0.747 → Z2
    assert get_zone(142, 190, DEFAULT_ZONES) == "Z2"


def test_zone_z3_exactly_75() -> None:
    # 142.5 → 142 / 190 ≈ 0.747, but let's use 143 / 190 ≈ 0.7526
    # Actually 75% of 190 = 142.5. 143 / 190 ≈ 0.7526 → Z3
    assert get_zone(143, 190, DEFAULT_ZONES) == "Z3"


def test_zone_z3_mid() -> None:
    # 150 / 190 ≈ 0.789 → Z3
    assert get_zone(150, 190, DEFAULT_ZONES) == "Z3"


def test_zone_z3_just_below_88() -> None:
    # 167 / 190 ≈ 0.8789 → Z3
    assert get_zone(167, 190, DEFAULT_ZONES) == "Z3"


def test_zone_z4_exactly_88() -> None:
    # 167.2 → 168 / 190 ≈ 0.884 → Z4
    assert get_zone(168, 190, DEFAULT_ZONES) == "Z4"


def test_zone_z4_above() -> None:
    assert get_zone(190, 190, DEFAULT_ZONES) == "Z4"
    assert get_zone(200, 190, DEFAULT_ZONES) == "Z4"


def test_zone_custom_boundaries() -> None:
    zones = {"z1_max": 0.50, "z2_max": 0.70, "z3_max": 0.90}
    # 100 / 200 = 0.50 → Z2
    assert get_zone(100, 200, zones) == "Z2"


def test_zone_zero_max_hr() -> None:
    assert get_zone(100, 0, DEFAULT_ZONES) == "Z1"


def test_zone_negative_bpm() -> None:
    assert get_zone(-5, 190, DEFAULT_ZONES) == "Z1"


# ── Zone colors ─────────────────────────────────────────────────────────

def test_zone_color_default() -> None:
    assert zone_color("Z1") == "#888888"
    assert zone_color("Z2") == "#4CAF50"
    assert zone_color("Z3") == "#FF9800"
    assert zone_color("Z4") == "#F44336"


def test_zone_color_custom() -> None:
    custom = {"Z1": "#000000", "Z2": "#111111", "Z3": "#222222", "Z4": "#333333"}
    assert zone_color("Z1", custom) == "#000000"
    assert zone_color("Z3", custom) == "#222222"


def test_zone_color_unknown_zone() -> None:
    assert zone_color("Z5") == "#888888"  # falls back to Z1 default


def test_zone_color_none_colors() -> None:
    assert zone_color("Z1", None) == "#888888"


# ── Zone labels ─────────────────────────────────────────────────────────

def test_zone_label_known() -> None:
    assert zone_label("Z1") == "Recovery"
    assert zone_label("Z2") == "Aerobic"
    assert zone_label("Z3") == "Threshold"
    assert zone_label("Z4") == "VO2 Max"


def test_zone_label_unknown() -> None:
    assert zone_label("Z5") == "Z5"


# ── Validation ──────────────────────────────────────────────────────────

def test_validate_zones_valid() -> None:
    # Should not raise
    validate_zones(DEFAULT_ZONES)


def test_validate_zones_non_monotonic() -> None:
    with pytest.raises(ValueError, match="zone boundaries"):
        validate_zones({"z1_max": 0.80, "z2_max": 0.60, "z3_max": 0.88})


def test_validate_zones_out_of_range() -> None:
    with pytest.raises(ValueError, match="zone boundaries"):
        validate_zones({"z1_max": -0.1, "z2_max": 0.60, "z3_max": 0.88})


def test_validate_zones_non_numeric() -> None:
    with pytest.raises(ValueError, match="zone boundaries"):
        validate_zones({"z1_max": "abc", "z2_max": 0.60, "z3_max": 0.88})


def test_validate_zones_missing_keys() -> None:
    # Missing keys get default values, should pass
    validate_zones({})
