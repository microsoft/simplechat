#!/usr/bin/env python3
# test_theme_card_code_format.py
"""
Functional test for the Theme Card code format.
Version: 0.261.452
Implemented in: 0.261.452

This test ensures that a Theme Card code made by the V2 interface (colorScheme.ts) decodes
with the documented server-side format (functions_color_schemes.py), that the Python encoder
produces the same code, and that a card edited after it was made is refused. The pinned code
below was produced by the browser and read out of a downloaded Theme Card PNG, so it proves
the two implementations agree byte for byte.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

import pytest

from functions_color_schemes import (
    ColorSchemeError,
    decode_theme_card_code,
    encode_theme_card_code,
    theme_card_checksum,
)

# Made by V2's encodeThemeCardCode for "Harbor Night", dark base.
BROWSER_CODE = (
    "SCTHEME1.eyJ2IjoxLCJuIjoiSGFyYm9yIE5pZ2h0IiwiYiI6ImRhcmsiLCJjIjp7ImFjY2VudCI6IjJERDRCRiIs"
    "Im9uQWNjZW50IjoiMEIxMDIwIiwiYmFja2Ryb3AiOiIwNzBCMTgiLCJwYW5lbCI6IjEwMTcyOCIsImJvcmRlciI6"
    "IjJCMzU1MCIsInRleHQxIjoiRjFGNUY5IiwidGV4dDIiOiJCM0MwRDQiLCJvayI6IjM0RDM5OSIsIndhcm4iOiJG"
    "QkJGMjQiLCJkYW5nZXIiOiJGODcxNzEiLCJpbmZvIjoiMjJEM0VFIn19.kSvKUwZWEhIpsmkbF-7pPg"
)


def _payload(code):
    segment = code.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _rebuild(body, checksum=None):
    payload = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"SCTHEME1.{payload}.{checksum or theme_card_checksum(payload)}"


def test_browser_code_decodes_on_the_server():
    """The code V2 writes into a Theme Card is read back exactly by the documented format."""
    mode = decode_theme_card_code(BROWSER_CODE)
    assert mode["name"] == "Harbor Night"
    assert mode["base"] == "dark"
    assert mode["colors"]["accent"] == "#2DD4BF"
    assert mode["colors"]["backdrop"] == "#070B18"


def test_python_encoder_matches_the_browser():
    """Encoding the same mode in Python yields the identical code."""
    mode = decode_theme_card_code(BROWSER_CODE)
    assert encode_theme_card_code(mode["name"], mode["base"], mode["colors"]) == BROWSER_CODE


def test_an_edited_card_is_refused():
    """Changing a color without the matching checksum is caught."""
    body = _payload(BROWSER_CODE)
    body["c"]["accent"] = "FF00FF"
    forged = _rebuild(body, checksum=BROWSER_CODE.split(".")[2])
    with pytest.raises(ColorSchemeError, match="changed after it was made"):
        decode_theme_card_code(forged)


def test_a_recomputed_checksum_still_cannot_carry_unsafe_values():
    """The checksum is open by design; the colors are validated regardless."""
    body = _payload(BROWSER_CODE)
    body["c"]["accent"] = "000000;background:url(//evil)"
    with pytest.raises(ColorSchemeError):
        decode_theme_card_code(_rebuild(body))
    body = _payload(BROWSER_CODE)
    body["c"]["extra"] = "000000"
    with pytest.raises(ColorSchemeError):
        decode_theme_card_code(_rebuild(body))


@pytest.mark.parametrize(
    "code",
    ["", "hello", "SCTHEME2.abc.def", "SCTHEME1.abc", "SCTHEME1." + "A" * 3000 + ".x", None],
)
def test_things_that_are_not_cards(code):
    """Anything that is not a version 1 Theme Card is refused."""
    with pytest.raises(ColorSchemeError):
        decode_theme_card_code(code)


def test_newer_versions_are_reported():
    """A card from a newer format is refused with a clear reason."""
    body = _payload(BROWSER_CODE)
    body["v"] = 2
    with pytest.raises(ColorSchemeError, match="newer version"):
        decode_theme_card_code(_rebuild(body))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
