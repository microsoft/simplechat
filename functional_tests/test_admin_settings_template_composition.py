#!/usr/bin/env python3
# test_admin_settings_template_composition.py
"""
Functional test for the Admin Settings composed-template contract.
Version: 0.260.003
Implemented in: 0.260.003

Admin Settings is assembled from per-tab partials under templates/admin/, so
reading admin_settings.html straight from disk only yields the parent shell.
This test pins that contract:

  1. The parent template delegates its tab panes to partials.
  2. Every partial is reachable from the parent.
  3. The composed template still exposes every configuration card.
  4. No functional test reads admin_settings.html without composing it first,
     which would silently assert against markup that is no longer there.
"""

import re
import sys
from pathlib import Path

from test_support.templates import (
    ADMIN_SETTINGS_TEMPLATE,
    TEMPLATE_DIR,
    read_admin_settings_template,
    resolve_template_includes,
)
from test_support.versioning import assert_app_version_at_least


TESTS_DIR = Path(__file__).resolve().parent
PARTIAL_DIR = TEMPLATE_DIR / "admin"

# Tests that legitimately reference the template path without reading markup,
# or that already compose it through the shared helpers.
COMPOSITION_HELPERS = (
    "read_admin_settings_template",
    "compose_if_admin_settings",
    "resolve_template_includes",
    "read_composed_template",
)


def test_parent_template_delegates_panes_to_partials():
    """The parent template should include partials rather than inline panes."""
    print("Testing Admin Settings partial delegation...")

    assert_app_version_at_least("0.260.003")
    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")

    includes = re.findall(r'\{%\s*include\s+"(admin/[^"]+)"\s*%\}', parent)
    assert includes, "Parent template should include Admin Settings partials"

    missing = [
        target for target in includes if not (TEMPLATE_DIR / target).is_file()
    ]
    assert not missing, f"Parent includes missing partials: {missing}"

    print(f"Parent delegates to {len(includes)} partial(s).")


def test_every_partial_is_reachable_from_the_parent():
    """Orphaned partials would silently drop settings from the page."""
    print("Testing Admin Settings partial reachability...")

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    composed = read_admin_settings_template()

    referenced = set()
    for target in re.findall(r'\{%\s*include\s+"(admin/[^"]+)"\s*%\}', parent):
        referenced.add((TEMPLATE_DIR / target).resolve())
    for target in re.findall(r'\{%\s*include\s+"(admin/[^"]+)"\s*%\}', composed):
        referenced.add((TEMPLATE_DIR / target).resolve())

    on_disk = {path.resolve() for path in PARTIAL_DIR.rglob("*.html")}
    orphans = sorted(path.name for path in on_disk - referenced)

    assert not orphans, f"Partials are never included: {orphans}"
    print(f"All {len(on_disk)} partial(s) are reachable.")


def test_composed_template_exposes_configuration_cards():
    """Composition must restore the cards that live inside the partials."""
    print("Testing composed Admin Settings card visibility...")

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    composed = read_admin_settings_template()

    card_pattern = re.compile(r'<div class="card[^"]*"[^>]*\sid="([^"]+)"')
    parent_cards = set(card_pattern.findall(parent))
    composed_cards = set(card_pattern.findall(composed))

    assert len(composed_cards) > len(parent_cards), (
        "Composing the template should reveal cards held in partials "
        f"(parent={len(parent_cards)}, composed={len(composed_cards)})"
    )

    # Spot-check cards that are known to live in partials.
    for card_id in ("keyvault-section", "branding-section", "content-safety-section"):
        assert card_id in composed_cards, (
            f"Composed template is missing '{card_id}'"
        )

    print(f"Composed template exposes {len(composed_cards)} card(s).")


def test_no_functional_test_reads_the_template_uncomposed():
    """Guard the convention so new tests do not assert on the parent shell.

    Only tests that actually reference a card or form field living exclusively
    inside a partial are flagged. Tests that assert on markup still held by the
    parent (the nav, the form tag, the modals) are reading what they expect.
    """
    print("Testing Admin Settings read convention across functional tests...")

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    composed = read_admin_settings_template()

    card_pattern = re.compile(r'<div class="card[^"]*"[^>]*\sid="([^"]+)"')
    field_pattern = re.compile(r'\sname="([^"]+)"')

    parent_cards = set(card_pattern.findall(parent))
    partial_only_cards = set(card_pattern.findall(composed)) - parent_cards
    assert partial_only_cards, "Expected some cards to live only in partials"

    parent_fields = set(field_pattern.findall(parent))
    partial_only_fields = set(field_pattern.findall(composed)) - parent_fields
    assert partial_only_fields, "Expected some fields to live only in partials"

    offenders = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue

        source = path.read_text(encoding="utf-8")
        if "admin_settings.html" not in source:
            continue
        if any(helper in source for helper in COMPOSITION_HELPERS):
            continue

        referenced = sorted(
            card_id for card_id in partial_only_cards if card_id in source
        )
        referenced += sorted(
            f'name="{field}"'
            for field in partial_only_fields
            if f'name="{field}"' in source
        )
        if referenced:
            offenders.append(f"{path.name} -> {', '.join(referenced[:3])}")

    assert not offenders, (
        "These tests reference cards that live inside Admin Settings partials "
        "but read admin_settings.html without composing it, so they assert "
        "against an incomplete template. Use "
        "test_support.templates.read_admin_settings_template() or "
        "compose_if_admin_settings():\n  " + "\n  ".join(offenders)
    )

    print("All functional tests compose the template before asserting.")


if __name__ == "__main__":
    tests = [
        test_parent_template_delegates_panes_to_partials,
        test_every_partial_is_reachable_from_the_parent,
        test_composed_template_exposes_configuration_cards,
        test_no_functional_test_reads_the_template_uncomposed,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
