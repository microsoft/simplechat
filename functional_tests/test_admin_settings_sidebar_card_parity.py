# test_admin_settings_sidebar_card_parity.py
"""
Functional test for Admin Settings sidebar card parity.
Version: 0.250.192
Implemented in: 0.250.192

This test ensures every top-level Admin Settings configuration card has an
equivalent left-sidebar destination and every static destination resolves.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = (
    ROOT_DIR / "application" / "single_app" / "templates" / "admin_settings.html"
)
SIDEBAR_TEMPLATE = (
    ROOT_DIR / "application" / "single_app" / "templates" / "_sidebar_nav.html"
)
SIDEBAR_SCRIPT = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "admin"
    / "admin_sidebar_nav.js"
)
EXCLUDED_TAB_IDS = {"latest-features"}


def _read(path):
    """Read a repository text file."""
    return path.read_text(encoding="utf-8")


def _parse_section_map(script_source):
    """Return sidebar section aliases from the JavaScript map."""
    match = re.search(
        r"const sectionMap = \{(?P<body>.*?)^\s*\};",
        script_source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Admin sidebar sectionMap was not found"
    return dict(
        re.findall(
            r"'([^']+)'\s*:\s*'([^']+)'",
            match.group("body"),
        )
    )


def _is_top_level_configuration_card(card, pane):
    """Return whether a card is top-level within its tab and outside a modal."""
    for parent in card.parents:
        if parent is pane:
            return True
        classes = parent.get("class", []) if hasattr(parent, "get") else []
        if "modal" in classes or "card" in classes:
            return False
    return False


def _top_level_cards(pane):
    """Return top-level configuration cards in document order."""
    return [
        card
        for card in pane.select(".card")
        if _is_top_level_configuration_card(card, pane)
    ]


def _card_title(card):
    """Return a readable card title for assertion output."""
    heading = card.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if heading is None:
        return card.get("id", "<unknown card>")
    return " ".join(heading.get_text(" ", strip=True).split())


def _navigation_contract():
    """Parse the admin template, sidebar template, and section alias map."""
    admin_source = _read(ADMIN_TEMPLATE)
    sidebar_source = _read(SIDEBAR_TEMPLATE)
    script_source = _read(SIDEBAR_SCRIPT)
    admin_soup = BeautifulSoup(admin_source, "html.parser")
    sidebar_soup = BeautifulSoup(sidebar_source, "html.parser")
    section_map = _parse_section_map(script_source)

    tab_targets = {
        link["data-tab"]
        for link in sidebar_soup.select(".admin-nav-tab[data-tab]")
    }
    section_targets = defaultdict(list)
    for link in sidebar_soup.select(
        ".admin-nav-section[data-tab][data-section]"
    ):
        raw_target = link["data-section"]
        section_targets[link["data-tab"]].append(
            section_map.get(raw_target, raw_target)
        )

    return {
        "admin_source": admin_source,
        "sidebar_source": sidebar_source,
        "script_source": script_source,
        "admin_soup": admin_soup,
        "sidebar_soup": sidebar_soup,
        "section_map": section_map,
        "tab_targets": tab_targets,
        "section_targets": section_targets,
    }


def test_every_top_level_card_has_sidebar_destination():
    """Require card parity and preserve card order within each submenu."""
    assert_app_version_at_least("0.250.192")
    contract = _navigation_contract()
    tab_content = contract["admin_soup"].find(id="adminSettingsTabContent")
    assert tab_content is not None, "Admin Settings tab content was not found"

    errors = []
    panes = tab_content.find_all("div", class_="tab-pane", recursive=False)
    for pane in panes:
        tab_id = pane.get("id")
        if not tab_id or tab_id in EXCLUDED_TAB_IDS:
            continue

        cards = _top_level_cards(pane)
        card_ids = []
        for card in cards:
            card_id = card.get("id")
            if not card_id:
                errors.append(
                    f"{tab_id}: top-level card '{_card_title(card)}' has no id"
                )
                continue
            card_ids.append(card_id)

        if len(card_ids) == 1 and tab_id in contract["tab_targets"]:
            continue

        targets = contract["section_targets"][tab_id]
        for card_id in card_ids:
            if card_id not in targets:
                errors.append(
                    f"{tab_id}: card '{card_id}' has no sidebar destination"
                )

        ordered_card_targets = [
            target for target in targets if target in set(card_ids)
        ]
        if ordered_card_targets != card_ids:
            errors.append(
                f"{tab_id}: card/sidebar order differs: "
                f"{card_ids} != {ordered_card_targets}"
            )

    assert not errors, "\n".join(errors)


def test_every_static_sidebar_section_target_resolves():
    """Reject sidebar links that cannot resolve to rendered template IDs."""
    contract = _navigation_contract()
    template_ids = {
        element["id"] for element in contract["admin_soup"].select("[id]")
    }
    errors = []

    for link in contract["sidebar_soup"].select(
        ".admin-nav-section[data-section]"
    ):
        raw_target = link["data-section"]
        if "{{" in raw_target:
            continue
        resolved_target = contract["section_map"].get(raw_target, raw_target)
        if resolved_target not in template_ids:
            errors.append(
                f"Sidebar target '{raw_target}' resolves to missing "
                f"'{resolved_target}'"
            )
        nav_text = link.select_one(".nav-text")
        if nav_text is None or not nav_text.get_text(strip=True):
            errors.append(f"Sidebar target '{raw_target}' has no search label")

    assert not errors, "\n".join(errors)


def test_conditional_agent_template_destination_matches_card():
    """Keep the optional Agent Template Approvals card and link in sync."""
    contract = _navigation_contract()
    card_marker = 'id="agent-template-approvals-section"'
    link_marker = 'data-section="agent-template-approvals-section"'

    card_condition = contract["admin_source"].index(
        "{% if settings.enable_agent_template_gallery %}"
    )
    card_position = contract["admin_source"].index(card_marker)
    card_end = contract["admin_source"].index("{% endif %}", card_position)
    assert card_condition < card_position < card_end

    link_condition = contract["sidebar_source"].index(
        "{% if app_settings.enable_agent_template_gallery %}"
    )
    link_position = contract["sidebar_source"].index(link_marker)
    link_end = contract["sidebar_source"].index("{% endif %}", link_position)
    assert link_condition < link_position < link_end


def test_sidebar_search_no_results_uses_safe_text_rendering():
    """Prevent sidebar search input from being interpolated into HTML."""
    script_source = _read(SIDEBAR_SCRIPT)

    assert "noResultsDiv.innerHTML" not in script_source
    assert (
        'message.textContent = `No settings found for "${searchTerm}"`;'
        in script_source
    )
    assert "noResultsDiv.append(searchIcon, message);" in script_source


if __name__ == "__main__":
    tests = [
        test_every_top_level_card_has_sidebar_destination,
        test_every_static_sidebar_section_target_resolves,
        test_conditional_agent_template_destination_matches_card,
        test_sidebar_search_no_results_uses_safe_text_rendering,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
