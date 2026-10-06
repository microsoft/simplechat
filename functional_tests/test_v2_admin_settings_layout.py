#!/usr/bin/env python3
# test_v2_admin_settings_layout.py
"""
Functional test for the wide V2 Admin Settings layout and section presentation.
Version: 0.261.253
Implemented in: 0.261.253

The settings content used to sit in a 768px column, and only the four Agents cards
had the header band, icon, and nested-switch presentation. The page now fills the
width beside an "On this page" index, every section is drawn the same distinct way
with an icon taken from the navigation, and fields lay out label-left/control-right
on a wide card. The behaviour of the hierarchy rule and the section shell is executed
by test_v2_admin_section_logic.ts (run from test_v2_admin_section_shell.py); this file
pins the structural contracts: icon coverage for every navigation entry, the wide
frame, the regression fix for in-page jumps, and the layout rules themselves.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
SECTION_TSX = V2_SRC / "components" / "admin" / "SettingsSection.tsx"
INDEX_TSX = V2_SRC / "components" / "admin" / "SettingsIndex.tsx"
ICONS_TS = V2_SRC / "components" / "admin" / "adminSectionIcons.ts"
FIELDS_TSX = V2_SRC / "components" / "admin" / "fields.tsx"
THEME_CSS = V2_SRC / "styles" / "theme.css"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _nav_icon_names():
    names = set()
    for group in ADMIN_NAV:
        names.add(group.get("icon"))
        for tab in group["tabs"]:
            names.add(tab.get("icon"))
            names.update(section.get("icon") for section in tab["sections"])
    names.discard(None)
    return names


def test_every_navigation_icon_has_a_v2_icon():
    """A new section reusing an unknown icon name would silently draw the fallback."""
    print("Testing navigation icon coverage...")
    assert_app_version_at_least("0.261.253")

    mapped = set(re.findall(r"^\s*'(bi-[a-z0-9-]+)':\s*[A-Z]\w*,\s*$", _read(ICONS_TS), re.MULTILINE))
    missing = sorted(_nav_icon_names() - mapped)
    assert not missing, (
        "admin_settings_nav.py names icons adminSectionIcons.ts does not translate: "
        f"{missing}. Add each to ADMIN_NAV_ICONS with a local Lucide icon."
    )
    print(f"  {len(_nav_icon_names())} navigation icon names all resolve.")


def test_the_page_fills_the_width_beside_an_index():
    """The 768px column is gone, and the index sits beside the cards on wide screens."""
    print("\nTesting the wide page frame...")
    page = _read(PAGE_TSX)

    assert "max-w-3xl" not in page, "The settings content should no longer be capped at 768px."
    assert "@min-[76rem]:grid-cols-[minmax(0,1fr)_15rem]" in page, (
        "Wide screens should lay the cards out beside the On this page index."
    )
    assert "<SettingsIndex" in page and "scrollRoot={scrollRef}" in page
    assert 'aria-label="On this page"' in _read(INDEX_TSX)
    assert "status={statusBySection.get(section.sectionId)}" in page, (
        "The card chip and the index must read one status per section."
    )
    print("  Cards fill the width; the index shares their status.")


def test_every_section_uses_the_distinct_presentation():
    """No section falls back to the old flat card."""
    print("\nTesting the section presentation...")
    section = _read(SECTION_TSX)

    assert 'className="admin-settings-distinct scroll-mt-4 border-edge-strong"' in section, (
        "Every section should render the distinct card, not only those with an appearance."
    )
    assert 'role="region"' in section and "aria-labelledby={`${sectionId}-title`}" in section
    assert "deriveFieldHierarchy(" in section, (
        "Which switch leads which settings should be read from the schema."
    )
    assert "icon={resolveAdminNavIcon(section.icon)}" in _read(PAGE_TSX)
    print("  Every section is a labelled, distinct card with a navigation icon.")


def test_in_page_jumps_target_the_rendered_card():
    """Regression: jumps looked up `admin-section-<id>` after cards became `<id>`."""
    print("\nTesting in-page section jumps...")
    page = _read(PAGE_TSX)
    section = _read(SECTION_TSX)

    assert "admin-section-${" not in page, (
        "goToSection must look up the id the card actually renders."
    )
    assert "document.getElementById(pendingScroll)" in page
    assert "id={sectionId}" in section
    assert "prefers-reduced-motion" in page, "Smooth scrolling must respect reduced motion."
    print("  Jumps scroll to the rendered card and honour reduced motion.")


def test_fields_split_into_label_and_control_columns_on_wide_cards():
    """The layout rules live in one place and resolve against the card."""
    print("\nTesting the field layout rules...")
    css = _read(THEME_CSS)
    fields = _read(FIELDS_TSX)

    assert re.search(r"@container \(min-width: 50rem\) \{\s*\.admin-field,", css), (
        "Fields should split into label and control columns once the card is wide."
    )
    assert "'heading control'" in css and "'help control'" in css
    assert re.search(r"@container \(min-width: 64rem\) \{\s*\.admin-switch-grid", css), (
        "Independent switches should pair up on wide cards."
    )
    assert 'className="admin-field py-3" data-field-width={width}' in fields
    for width in ("compact", "standard", "full"):
        assert f'width="{width}"' in fields, f"No control declares the {width} width"
    print("  Split rows, control widths, and switch grids are declared.")


if __name__ == "__main__":
    tests = [
        test_every_navigation_icon_has_a_v2_icon,
        test_the_page_fills_the_width_beside_an_index,
        test_every_section_uses_the_distinct_presentation,
        test_in_page_jumps_target_the_rendered_card,
        test_fields_split_into_label_and_control_columns_on_wide_cards,
    ]
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
