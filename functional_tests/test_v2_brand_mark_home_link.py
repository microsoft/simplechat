#!/usr/bin/env python3
"""
Functional test for the V2 rail's brand mark and the removal of the Home nav item.

Version: 0.261.050
Implemented in: 0.261.050

Three faults met at the top of the navigation rail.

The rail led with a Home nav item -- house icon, "Home" label, `to: '/'` -- directly beneath
a brand area holding the logo and application title. That is two controls for one
destination, and the brand area is the one a reader reaches for.

The brand area was not a control at all. It was a plain `<div>`, so the thing every user
expects to click was inert, and removing the Home nav item without fixing that would have
left `/v2` unreachable from the rail entirely.

And the letter square was drawn beside the title it substitutes for. When no custom logo is
configured the brand fell back to an accent square holding the first letter of the
application title -- and then rendered the whole title next to it whenever the rail was
expanded and "Hide Application Title" was off. "S SimpleChat" is the same word twice. The
square exists for the places the title cannot go, not alongside it.

This test ensures the Home nav item is gone, that the brand mark carries the home
destination in its place with an accessible name that survives a collapsed rail, and that
the letter square is gated on the title being absent rather than on the logo being absent.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SIDEBAR = V2_SRC / "components" / "layout" / "Sidebar.tsx"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def _nav_items():
    """The NAV_ITEMS array literal."""
    source = _read(SIDEBAR)
    items = re.search(r"const NAV_ITEMS: NavItem\[\] = \[(.|\n)*?\n\];", source)
    assert items, "Sidebar should declare a NAV_ITEMS array"
    return items.group(0)


def _brand_mark():
    """The body of the BrandMark helper component."""
    source = _read(SIDEBAR)
    component = re.search(
        r"function BrandMark\(\{ collapsed \}: \{ collapsed: boolean \}\)(.|\n)*?\n\}", source
    )
    assert component, "Sidebar should declare a BrandMark component"
    return component.group(0)


def test_the_home_nav_item_is_gone():
    """One destination does not need two controls stacked on top of each other."""
    print("Testing the Home nav item removal...")

    items = _nav_items()

    assert "'Home'" not in items, (
        "The rail must not carry a Home nav item: the brand mark directly above the list "
        "is the link to the same place, and a row repeating it spends a slot on a "
        "destination the logo already implies"
    )
    assert "to: '/'," not in items, "No nav item may claim the landing route"

    source = _read(SIDEBAR)
    assert not re.search(r"^\s+Home,$", source, re.MULTILINE), (
        "The lucide Home icon is only imported for the removed nav item"
    )

    # `end` existed on NavItem solely so "/" would not match every route. With that entry
    # gone the field describes nothing, and a stale optional field invites a nav item to
    # be added later that silently never matches.
    assert "end?: boolean;" not in source, (
        "The NavItem end field exists only for the removed '/' entry"
    )
    assert "end={item.end}" not in source, "No nav item needs exact matching any more"

    # The one nav item that carries behaviour must be untouched by the removal.
    assert "{ to: '/chat', label: 'Chats', icon: MessagesSquare }," in items, (
        "Chats is what reaches a fresh conversation from elsewhere and must remain"
    )

    print("Home nav item removal test passed!")
    return True


def test_the_brand_mark_is_the_home_link():
    """Removing the nav item only works because the brand took the destination over."""
    print("Testing the brand mark home link...")

    body = _brand_mark()

    link = re.search(r"<NavLink\s+to=\"/\"\s+end\s+aria-label=", body)
    assert link, (
        "The brand mark must be a NavLink to '/'. It is the only route to the landing "
        "page left in the rail, and `end` is required because '/' prefixes every other "
        "path and would otherwise claim aria-current on all of them"
    )

    assert "aria-label={`${title} home`}" in body, (
        "The link must name itself: the collapsed rail shows only a logo or a letter, "
        "both of which are decorative, so without this the link has no accessible name. "
        "The title is included so the visible label stays inside the accessible name, "
        "which naming it only 'Home' would break (WCAG 2.5.3, Label in Name)"
    )

    assert 'alt=""' in body, (
        "The logo is decorative now that the link names itself; alt text would announce "
        "the application title twice"
    )

    assert "hover:bg-surface-2" in body, (
        "The brand area has to look clickable now that it is: it is the only home link"
    )

    # A negative margin against the padding keeps the hover surface from shifting the
    # logo and title off the inset they share with everything else in the rail.
    assert "-mx-1.5" in body and "px-1.5" in body, (
        "The hover pill must be inset with negative margin, or adding its padding moves "
        "the brand mark away from the rail's left edge alignment"
    )

    print("Brand mark home link test passed!")
    return True


def test_the_letter_square_only_stands_in_for_an_absent_title():
    """The square is a substitute for the title, so it must not appear beside it."""
    print("Testing the letter square...")

    body = _brand_mark()

    assert "const showTitle = !collapsed && !branding?.hide_app_title;" in body, (
        "Whether the title is on screen is the condition everything else keys off"
    )
    assert "const showInitial = !logoUrl && !showTitle;" in body, (
        "The letter square must be gated on the title being absent, not merely on the "
        "logo being absent. Gated on the logo alone it rendered next to the full title "
        "in the expanded rail, showing the same word twice"
    )

    # It still has to appear where nothing else can: the collapsed rail, and a deployment
    # with no logo that has also hidden the title. Both are covered by showInitial, which
    # would be pointless if the square were not actually gated on it.
    square = re.search(r"\{showInitial && \(\s*<span(.|\n)*?</span>\s*\)\}", body)
    assert square, "The letter square must be the element gated on showInitial"
    assert "title.slice(0, 1).toUpperCase()" in square.group(0), (
        "The gated element must be the initial, not something else"
    )
    assert 'aria-hidden="true"' in square.group(0), (
        "The square is decorative; the link's aria-label is what names the destination"
    )

    # The logo is independent of the title: a deployment showing both should keep both.
    assert "const logoUrl = branding?.show_logo ? themedLogoUrl : null;" in body, (
        "A stored logo that has been switched off is not a logo, and the fallback has to "
        "treat it that way or the brand slot renders empty"
    )
    logo = re.search(r"\{logoUrl && \(", body)
    assert logo, "The logo must render whenever one is configured, title or not"

    print("Letter square test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The change is present from the version that introduced it onwards."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.050")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_home_nav_item_is_gone,
        test_the_brand_mark_is_the_home_link,
        test_the_letter_square_only_stands_in_for_an_absent_title,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
