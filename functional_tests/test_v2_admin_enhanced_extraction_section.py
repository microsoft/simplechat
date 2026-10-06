#!/usr/bin/env python3
# test_v2_admin_enhanced_extraction_section.py
"""
Functional test for the V2 Admin Settings Enhanced Extraction section.
Version: 0.261.260
Implemented in: 0.261.260

This test ensures that Enhanced extraction and the Azure AI Content Understanding
connection behind it read as one capability in the V2 admin surface.

Before this, "Enable Enhanced extraction" sat inside a collapsed group of the
Document Intelligence card, and Content Understanding was a card of its own that
could be filled in while Enhanced was off -- the one state in which it is never
called. Turning Enhanced on also changed nothing by itself in V2: the mode stayed
on Standard, so Content Understanding never ran, where the server-rendered form
has always moved the mode to Auto.

The checks pin the corrected shape:

* Document Intelligence is the connection alone, and Enhanced Extraction is the
  section after it, led by its switch.
* Every setting that only means something while Enhanced is on is hidden while it
  is off, and Content Understanding is also hidden in clouds that do not offer it.
* Turning Enhanced on moves Standard to Auto, in the browser and on the server.
* The Document Intelligence connection test only sends the mode while Enhanced is on.
* The settings API reports whether this cloud offers Content Understanding, and the
  page hands that flag to the card.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
PANE = APP_ROOT / "templates" / "admin" / "_panes" / "extraction.html"
V2_ROUTE = APP_ROOT / "route_backend_v2.py"
ADMIN_PAGE = V2_SRC / "pages" / "AdminSettingsPage.tsx"

SECTION_ID = "enhanced-extraction-section"
SWITCH = "enable_enhanced_extraction"
MODE = "document_intelligence_pdf_image_extraction_mode"
CU_FLAG = "content_understanding_supported"

CONTENT_UNDERSTANDING_KEYS = (
    "azure_content_understanding_endpoint",
    "azure_content_understanding_authentication_type",
    "azure_content_understanding_key",
    "azure_content_understanding_api_version",
    "azure_content_understanding_analyzer_id",
    "azure_content_understanding_image_analyzer_id",
)

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates
evaluate = fields_module.evaluate_dependency


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def field_identity(field):
    return field.get("key") or field.get("component")


def visible(field, state, flags):
    return evaluate(field.get("depends_on"), state.get, flags)


def test_enhanced_extraction_follows_document_intelligence_in_navigation():
    """The capability is navigated to by name, right after the connection it falls back to."""
    print("Testing the Enhanced Extraction navigation entry...")

    assert_app_version_at_least("0.261.260")

    extraction_tab = next(
        tab
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "extraction"
    )
    sections = [section["id"] for section in extraction_tab["sections"]]

    assert sections[:2] == ["document-intelligence-section", SECTION_ID], (
        f"Enhanced Extraction should directly follow Document Intelligence: {sections}"
    )
    assert "content-understanding-section" not in sections, (
        "Content Understanding is a navigation section of its own again, which "
        "separates it from the switch that decides whether it is ever called."
    )

    entry = extraction_tab["sections"][1]
    assert entry["label"] == "Enhanced Extraction", entry

    print(f"  Document Extraction sections: {sections[:3]}...")
    return True


def test_enhanced_extraction_leads_its_section():
    """The switch is the section's capability, and everything else hangs off it."""
    print("\nTesting the Enhanced Extraction section shape...")

    fields = section_fields(SECTION_ID)
    assert fields, f"{SECTION_ID} declares no fields."

    leader = fields[0]
    assert leader.get("key") == SWITCH and leader.get("role") == "capability", (
        "Enable Enhanced extraction must lead its section as the capability, so it "
        "is never inside a collapsed group."
    )
    assert not leader.get("group"), "The capability switch must not belong to a group."

    for field in fields[1:]:
        conditions = list(fields_module.iter_field_dependencies(field))
        assert {"key": SWITCH, "equals": True} in conditions, (
            f"{field_identity(field)} is not gated on Enhanced extraction, so it can "
            "be edited while it has no effect."
        )

    keys = {field.get("key") for field in fields}
    for expected in (MODE, "document_intelligence_auto_sample_pages",
                     "enable_document_intelligence_formula_extraction",
                     *CONTENT_UNDERSTANDING_KEYS):
        assert expected in keys, f"{expected} is not declared under Enhanced Extraction."

    components = [field.get("component") for field in fields if field.get("type") == "component"]
    assert "enhanced-extraction-engine" in components, (
        "The engine notice is what tells an administrator which engine is in force."
    )

    print(f"  {len(fields)} field(s), led by the capability and all gated on it.")
    return True


def test_document_intelligence_is_the_connection_alone():
    """Nothing that only matters while Enhanced is on is left behind in the connection card."""
    print("\nTesting the Document Intelligence section...")

    fields = section_fields("document-intelligence-section")
    groups = {(field.get("group") or {}).get("id") for field in fields}
    assert groups == {"connection"}, f"Document Intelligence holds more than its connection: {groups}"

    keys = {field.get("key") for field in fields}
    leftovers = keys & {SWITCH, MODE, "document_intelligence_auto_sample_pages",
                        "enable_document_intelligence_formula_extraction"}
    assert not leftovers, f"Enhanced settings left in Document Intelligence: {sorted(leftovers)}"

    print(f"  {len(fields)} connection field(s), nothing else.")
    return True


def test_everything_but_the_switch_is_hidden_while_enhanced_is_off():
    """With Enhanced off the card is the switch, so Content Understanding cannot be filled in."""
    print("\nTesting visibility with Enhanced extraction off and on...")

    fields = section_fields(SECTION_ID)
    flags = {CU_FLAG: True}

    off = {SWITCH: False, MODE: "auto", "azure_content_understanding_authentication_type": "key"}
    shown_off = [field_identity(field) for field in fields if visible(field, off, flags)]
    assert shown_off == [SWITCH], f"Visible with Enhanced off: {shown_off}"

    on = {SWITCH: True, MODE: "auto", "azure_content_understanding_authentication_type": "key"}
    shown_on = {field_identity(field) for field in fields if visible(field, on, flags)}
    for expected in (MODE, "document_intelligence_auto_sample_pages",
                     "enable_document_intelligence_formula_extraction",
                     "enhanced-extraction-engine", *CONTENT_UNDERSTANDING_KEYS):
        assert expected in shown_on, f"{expected} is hidden with Enhanced on."

    managed = {**on, "azure_content_understanding_authentication_type": "managed_identity"}
    by_key = {field.get("key"): field for field in fields if field.get("key")}
    assert not visible(by_key["azure_content_understanding_key"], managed, flags), (
        "The key is only needed for key authentication."
    )

    print(f"  Off shows only the switch; on shows {len(shown_on)} field(s).")
    return True


def test_content_understanding_follows_the_cloud():
    """Content Understanding is not offered in every Azure cloud, and the card says so."""
    print("\nTesting Content Understanding cloud gating...")

    fields = section_fields(SECTION_ID)
    on = {SWITCH: True, MODE: "auto", "azure_content_understanding_authentication_type": "key"}

    sovereign = {field_identity(field) for field in fields if visible(field, on, {CU_FLAG: False})}
    leaked = sovereign & set(CONTENT_UNDERSTANDING_KEYS)
    assert not leaked, f"Content Understanding fields shown where it is not offered: {sorted(leaked)}"
    # The capability still works there, on Document Intelligence Layout, and the
    # engine notice is what says there is nothing more to configure.
    assert {MODE, "enhanced-extraction-engine"} <= sovereign, sovereign

    tests = [
        field for field in fields
        if field.get("component") == "connection-test" and field.get("test_type") == "content_understanding"
    ]
    assert tests and not visible(tests[0], on, {CU_FLAG: False}), (
        "The Content Understanding connection test is offered in a cloud without the service."
    )

    print("  Content Understanding is hidden where the cloud does not offer it.")
    return True


def test_the_connection_group_waits_on_the_endpoint():
    """An optional connection opens while unconnected, because it is the likely next step."""
    print("\nTesting the Content Understanding connection group...")

    endpoint = fields_module.get_field_definition("azure_content_understanding_endpoint")
    group = endpoint.get("group") or {}
    assert group.get("variant") == "connection", group
    assert group.get("open_until_set") == "azure_content_understanding_endpoint", group
    assert not endpoint.get("required"), (
        "Enhanced works without Content Understanding, so its endpoint must not mark "
        "the section as needing configuration."
    )

    print(f"  Group {group.get('id')!r} opens until the endpoint is set.")
    return True


def test_turning_enhanced_on_moves_standard_to_auto():
    """Enhanced with the mode still on Standard would change nothing at all."""
    print("\nTesting the Enhanced extraction on_enable rule...")

    stored_off = {SWITCH: False, MODE: "read"}

    normalized, errors, warnings = normalize({SWITCH: True}, stored_off)
    assert not errors, errors
    assert normalized.get(MODE) == "auto", normalized
    assert "Auto" in warnings.get(MODE, ""), (
        "A mode changed on the administrator's behalf has to say so."
    )

    # An explicit choice in the same save wins, which is what the browser sends
    # when the administrator picks Standard back after turning Enhanced on.
    normalized, errors, warnings = normalize({SWITCH: True, MODE: "read"}, stored_off)
    assert not errors and normalized[MODE] == "read" and MODE not in warnings, normalized

    # A stored Enhanced or Auto choice comes back as it was.
    normalized, errors, _ = normalize({SWITCH: True}, {SWITCH: False, MODE: "layout"})
    assert not errors and MODE not in normalized, normalized

    # Re-saving a switch that is already on is not a transition.
    normalized, errors, _ = normalize({SWITCH: True}, {SWITCH: True, MODE: "read"})
    assert not errors and MODE not in normalized, normalized

    # Turning it off leaves the stored mode alone; Standard is enforced on read.
    normalized, errors, _ = normalize({SWITCH: False}, {SWITCH: True, MODE: "auto"})
    assert not errors and MODE not in normalized, normalized

    # A settings document that never stored a mode reads as the declared default.
    normalized, errors, _ = normalize({SWITCH: True}, {})
    assert not errors and normalized.get(MODE) == "auto", normalized

    print("  Standard moves to Auto on the transition only, and explicit choices win.")
    return True


def test_document_intelligence_test_sends_the_mode_only_while_enhanced_is_on():
    """With Enhanced off every document is Standard, so the test should exercise Read."""
    print("\nTesting the Document Intelligence connection test payload...")

    test = next(
        field for field in section_fields("document-intelligence-section")
        if field.get("component") == "connection-test"
    )
    payload = test["test_payload"]
    for path in (MODE, "document_intelligence_auto_sample_pages"):
        assert payload[path].get("when") == {"key": SWITCH, "equals": True}, (
            f"{path} is sent while Enhanced is off, so the test would exercise a "
            "mode no document can use."
        )

    print("  The mode and sample pages are only sent while Enhanced is on.")
    return True


def test_the_settings_api_and_page_carry_the_cloud_flag():
    """The flag is resolved by the server and must reach both the page and the card."""
    print("\nTesting the content_understanding_supported runtime flag wiring...")

    route = V2_ROUTE.read_text(encoding="utf-8")
    assert re.search(
        r'"content_understanding_supported":\s*\(\s*is_content_understanding_supported_environment\(\)',
        route,
    ), "The V2 settings API no longer reports whether Content Understanding is offered."

    page = ADMIN_PAGE.read_text(encoding="utf-8")
    assert "runtimeFlags={runtimeFlags}" in page, (
        "The page filters flag-gated fields with the runtime flags but does not hand "
        "them to SettingsSection, which then drops every one of those fields."
    )
    assert "case 'enhanced-extraction-engine'" in page, "The engine notice is not rendered."
    assert "applyEnableEffect(" in page, "Switch on_enable companions are not applied to the draft."

    print("  The API reports the flag, and the page passes it to the card.")
    return True


def test_the_classic_sidebar_lands_on_the_enhanced_switch():
    """ADMIN_NAV is shared, so the server-rendered sidebar needs the same destination."""
    print("\nTesting the server-rendered destination...")

    markup = PANE.read_text(encoding="utf-8")
    match = re.search(
        r'<div[^>]*\bid="enhanced-extraction-section"[^>]*>(?P<body>.*?)</div>',
        markup,
        re.DOTALL,
    )
    assert match, "No element in extraction.html carries id=\"enhanced-extraction-section\"."
    assert 'id="enable_enhanced_extraction"' in match.group("body"), (
        "The Enhanced Extraction destination should be the row holding the switch."
    )

    print("  The classic sidebar link scrolls to the Enhanced switch.")
    return True


if __name__ == "__main__":
    tests = [
        test_enhanced_extraction_follows_document_intelligence_in_navigation,
        test_enhanced_extraction_leads_its_section,
        test_document_intelligence_is_the_connection_alone,
        test_everything_but_the_switch_is_hidden_while_enhanced_is_off,
        test_content_understanding_follows_the_cloud,
        test_the_connection_group_waits_on_the_endpoint,
        test_turning_enhanced_on_moves_standard_to_auto,
        test_document_intelligence_test_sends_the_mode_only_while_enhanced_is_on,
        test_the_settings_api_and_page_carry_the_cloud_flag,
        test_the_classic_sidebar_lands_on_the_enhanced_switch,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
