#!/usr/bin/env python3
# test_color_schemes_validation.py
"""
Functional test for V2 custom color scheme validation.
Version: 0.261.452
Implemented in: 0.261.452

This test ensures that administrator color schemes and users' custom color modes are reduced
to a fixed set of #RRGGBB colors before they are stored. Every value ends up in a stylesheet
in someone's browser, so anything other than a plain six-digit hex color, an unknown color
name, or an over-long name must be refused, and the readable-contrast rule must hold.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

import pytest

from functions_color_schemes import (
    COLOR_MODES,
    PALETTE_TOKENS,
    ColorSchemeError,
    contrast_ratio,
    normalize_color_mode,
    normalize_color_scheme,
    normalize_custom_color_mode,
    normalize_palette,
    readability_problems,
)

HARBOR_NIGHT = {
    "accent": "#2dd4bf",
    "onAccent": "#06201C",
    "backdrop": "#0B1A24",
    "panel": "#12283A",
    "border": "#21415A",
    "text1": "#E6F4F1",
    "text2": "#9CC3C0",
    "ok": "#34D399",
    "warn": "#FBBF24",
    "danger": "#F87171",
    "info": "#22D3EE",
}

DEFAULT_LIGHT = {
    "accent": "#3B6EF0",
    "onAccent": "#FFFFFF",
    "backdrop": "#EEF2FB",
    "panel": "#FFFFFF",
    "border": "#DCE3EE",
    "text1": "#0F172A",
    "text2": "#475569",
    "ok": "#059669",
    "warn": "#D97706",
    "danger": "#DC2626",
    "info": "#0E7490",
}


def test_palette_is_normalized_to_uppercase_hex():
    """Valid colors are kept, with a leading # and upper case."""
    palette = normalize_palette({**HARBOR_NIGHT, "accent": "2dd4bf"})
    assert palette["accent"] == "#2DD4BF"
    assert list(palette) == list(PALETTE_TOKENS)


@pytest.mark.parametrize(
    "bad_value",
    [
        "red",
        "#FFF",
        "#GGGGGG",
        "#123456; background: url(//evil)",
        "url(https://example.com/x.png)",
        "var(--accent)",
        "rgb(0 0 0)",
        12,
        None,
    ],
)
def test_palette_refuses_anything_but_six_digit_hex(bad_value):
    """CSS expressions, short hex, names and non-strings never reach a stylesheet."""
    with pytest.raises(ColorSchemeError):
        normalize_palette({**HARBOR_NIGHT, "accent": bad_value})


def test_palette_refuses_unknown_and_missing_colors():
    """Only the known tokens are accepted, and all of them are required."""
    with pytest.raises(ColorSchemeError):
        normalize_palette({**HARBOR_NIGHT, "background-image": "#000000"})
    missing = dict(HARBOR_NIGHT)
    del missing["panel"]
    with pytest.raises(ColorSchemeError):
        normalize_palette(missing)
    with pytest.raises(ColorSchemeError):
        normalize_palette(["#000000"])


def test_color_scheme_accepts_null_and_both_modes():
    """None keeps the SimpleChat default; otherwise both light and dark are required."""
    assert normalize_color_scheme(None) is None
    scheme = normalize_color_scheme({"light": DEFAULT_LIGHT, "dark": HARBOR_NIGHT})
    assert scheme["dark"]["accent"] == "#2DD4BF"
    with pytest.raises(ColorSchemeError):
        normalize_color_scheme({"light": DEFAULT_LIGHT})
    with pytest.raises(ColorSchemeError):
        normalize_color_scheme({"light": DEFAULT_LIGHT, "dark": HARBOR_NIGHT, "sepia": HARBOR_NIGHT})


def test_custom_color_mode_cleans_the_name_and_checks_the_base():
    """Names are plain text up to 40 characters; the base is light or dark."""
    mode = normalize_custom_color_mode(
        {"name": "  Harbor\u0000 Night\n ", "base": "dark", "colors": HARBOR_NIGHT}
    )
    assert mode["name"] == "Harbor Night"
    assert mode["base"] == "dark"
    assert normalize_custom_color_mode({"name": "", "base": "light", "colors": DEFAULT_LIGHT})["name"] == "My color mode"
    assert normalize_custom_color_mode(None) is None
    with pytest.raises(ColorSchemeError):
        normalize_custom_color_mode({"name": "x" * 41, "base": "dark", "colors": HARBOR_NIGHT})
    with pytest.raises(ColorSchemeError):
        normalize_custom_color_mode({"name": "x", "base": "sepia", "colors": HARBOR_NIGHT})
    with pytest.raises(ColorSchemeError):
        normalize_custom_color_mode({"name": "x", "base": "dark", "colors": HARBOR_NIGHT, "css": "a"})


def test_readable_contrast_rule():
    """Hard-to-read text is refused only when the administrator requires readable colors."""
    unreadable = {**HARBOR_NIGHT, "text2": "#1A2E3E"}
    assert readability_problems(unreadable)
    assert normalize_custom_color_mode({"name": "x", "base": "dark", "colors": unreadable})
    with pytest.raises(ColorSchemeError):
        normalize_custom_color_mode(
            {"name": "x", "base": "dark", "colors": unreadable}, require_readable=True
        )


def test_shipped_defaults_are_readable():
    """The SimpleChat light palette must pass its own rule, or users could not start from it.

    Its accent is 4.48:1 on white; the rule is judged on the ratio shown, to one decimal.
    """
    assert round(contrast_ratio("#3B6EF0", "#FFFFFF"), 1) == 4.5
    assert readability_problems(DEFAULT_LIGHT) == []
    assert normalize_custom_color_mode(
        {"name": "x", "base": "light", "colors": DEFAULT_LIGHT}, require_readable=True
    )


def test_color_mode_values():
    """Only light, dark, system and custom are stored."""
    for mode in COLOR_MODES:
        assert normalize_color_mode(mode) == mode
    for bad in ("sepia", "", None, True):
        with pytest.raises(ColorSchemeError):
            normalize_color_mode(bad)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
