#!/usr/bin/env python3
# test_admin_card_links.py
"""
Functional test for Admin Settings card-targeted navigation links.
Version: 0.260.008
Implemented in: 0.260.008

Cross-tab links used to name a tab button directly, for example
switchTab(event, 'workspaces-tab'). That couples every link to a tab id, so an
information-architecture change silently breaks it: the button no longer
exists, no pane is activated, and the URL hash points at nothing. Two links
were already wrong this way, pointing at the Workspaces tab for video and audio
settings that live under Search and Extract.

Links now name the card they want with data-admin-link, and the owning tab is
resolved from the DOM at click time. This test pins that contract:

  1. Every data-admin-link target is a real element id in the composed template.
  2. Every such link carries a matching href fragment, so it degrades sensibly
     without JavaScript and remains copy-pasteable.
  3. No link reintroduces the tab-coupled switchTab pattern.
  4. The resolver module is wired into the page.
"""

import re
import sys
from pathlib import Path

from test_support.templates import (
    ADMIN_SETTINGS_TEMPLATE,
    read_admin_settings_template,
)
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CARD_LINKS_JS = (
    REPO_ROOT
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "admin"
    / "admin_card_links.js"
)

LINK_RE = re.compile(r'<a\b[^>]*\bdata-admin-link="(?P<target>[^"]+)"[^>]*>')
HREF_RE = re.compile(r'\bhref="#(?P<fragment>[^"]+)"')


def _links(markup):
    """Return every anchor tag that declares a card target."""
    return [(m.group("target"), m.group(0)) for m in LINK_RE.finditer(markup)]


def test_every_card_link_target_exists():
    """A link that resolves to nothing is a dead end for the admin."""
    print("Testing Admin Settings card link targets...")

    assert_app_version_at_least("0.260.008")
    composed = read_admin_settings_template()
    element_ids = set(re.findall(r'\sid="([^"]+)"', composed))

    links = _links(composed)
    assert links, "Expected Admin Settings to declare card-targeted links"

    missing = sorted({target for target, _ in links if target not in element_ids})
    assert not missing, (
        "data-admin-link targets do not exist in the composed template: "
        f"{missing}"
    )

    print(f"All {len(links)} card link(s) resolve to real elements.")


def test_card_links_keep_a_matching_href():
    """The href is the no-JavaScript fallback and should match the target."""
    print("Testing Admin Settings card link href fallbacks...")

    composed = read_admin_settings_template()
    mismatched = []

    for target, tag in _links(composed):
        href = HREF_RE.search(tag)
        if href is None:
            mismatched.append(f"{target} (no href)")
        elif href.group("fragment") != target:
            mismatched.append(f"{target} (href points at {href.group('fragment')})")

    assert not mismatched, (
        "Card links should carry href=\"#<same-target>\": " f"{mismatched}"
    )

    print("Every card link href matches its data-admin-link target.")


def test_no_tab_coupled_links_remain():
    """switchTab links break silently whenever a tab is renamed or regrouped."""
    print("Testing that no tab-coupled admin links remain...")

    composed = read_admin_settings_template()
    offenders = re.findall(r'onclick="switchTab\(event,\s*\'([^\']+)\'\)"', composed)

    assert not offenders, (
        "These links still name a tab button, so they break when the tab id "
        "changes. Use data-admin-link with a card id instead: "
        f"{sorted(set(offenders))}"
    )

    print("No tab-coupled links remain.")


def test_card_link_resolver_is_wired_in():
    """The markup contract is useless if the resolver never loads."""
    print("Testing Admin Settings card link resolver wiring...")

    assert CARD_LINKS_JS.is_file(), f"Missing resolver module at {CARD_LINKS_JS}"

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    assert "js/admin/admin_card_links.js" in parent, (
        "admin_card_links.js is not loaded by admin_settings.html"
    )

    source = CARD_LINKS_JS.read_text(encoding="utf-8")
    for marker in (
        "export function openAdminCard",
        "data-admin-link",
        "closest('.tab-pane')",
    ):
        assert marker in source, f"Resolver is missing expected logic: {marker}"

    # The resolver must derive the tab from the DOM rather than hardcode a map,
    # which is the whole reason the links survive an IA change. Comments are
    # stripped first so the explanation of the old pattern does not trip this.
    code = re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)
    assert "switchTab(" not in code, (
        "Resolver should not depend on the tab-coupled switchTab helper"
    )

    print("Card link resolver is present and wired into the page.")


if __name__ == "__main__":
    tests = [
        test_every_card_link_target_exists,
        test_card_links_keep_a_matching_href,
        test_no_tab_coupled_links_remain,
        test_card_link_resolver_is_wired_in,
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
