#!/usr/bin/env python3
# test_v2_admin_help_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Help group.
Version: 0.261.275
Implemented in: 0.261.275

The V2 admin surface renders the Help group from ``admin_settings_fields.py``,
while the server-rendered page renders it from ``templates/admin/_panes/``. Before
this change only three Help switches were declared, so V2 had no Menu Name, no
Send Feedback destination or recipient, no Send Feedback forms, no per-announcement
visibility, and nothing at all for Admin Latest Features.

These checks keep the two descriptions together:

- every form field the Help panes submit is claimed by the schema, by the
  generated per-announcement names, or by ``LEGACY_FORM_ONLY_FIELDS``;
- the schema declares nothing the panes do not have;
- the utility inputs are owned by components the schema actually declares;
- the Support section reports a missing recipient through its status rule;
- the Admin Latest Features tab, which declares no sections, is rendered by the
  V2 page from the release catalogue, as the classic page does.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
PANES_DIR = REPO_ROOT / "application" / "single_app" / "templates" / "admin" / "_panes"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
LATEST_FEATURES_TS = V2_SRC / "lib" / "latestFeatures.ts"

HELP_GROUP_ID = "help"
HELP_PANES = {
    "support-menu": ("support-menu-section",),
    "send-feedback": (
        "send-feedback-overview-card",
        "send-feedback-bug-card",
        "send-feedback-feature-card",
    ),
    "user-facing-latest-features": ("user-facing-latest-features-section",),
    # Rendered from the admin release catalogue on both surfaces.
    "latest-features": (),
}
HELP_SECTIONS = {section for sections in HELP_PANES.values() for section in sections}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
BLOCK_TAG_RE = re.compile(r"\{%-?\s*(if|endif)\b[^%]*%\}")
FEATURE_ID_PLACEHOLDER = "{{ feature.id }}"

fields_module = import_app_module("admin_settings_fields")
support_menu_config = import_app_module("support_menu_config")


def read_pane(pane_id):
    """Return a pane's markup with any block the template can never render removed."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return strip_disabled_blocks(pane_path.read_text(encoding="utf-8"))


def strip_disabled_blocks(markup):
    """Remove every ``{% if false %}`` block, nested ``if`` tags included.

    The Admin Latest Features pane keeps a long run of retired cards behind
    ``{% if false %}``. Their proxy inputs are never rendered, so they are not
    fields an administrator can submit and must not count against parity.
    """
    while True:
        opening = re.search(r"\{%-?\s*if\s+false\s*-?%\}", markup)
        if not opening:
            return markup
        depth = 0
        for tag in BLOCK_TAG_RE.finditer(markup, opening.start()):
            depth += 1 if tag.group(1) == "if" else -1
            if depth == 0:
                markup = markup[: opening.start()] + markup[tag.end():]
                break
        else:
            raise AssertionError("Unbalanced {% if false %} block in an Admin Settings pane.")


def collect_pane_field_names(markup):
    """Return the form field names a pane submits, expanding the per-feature loop."""
    names = set()
    feature_ids = [feature["id"] for feature in support_menu_config.get_support_latest_feature_catalog()]
    for name in FIELD_NAME_RE.findall(markup):
        if FEATURE_ID_PLACEHOLDER in name:
            names.update(name.replace(FEATURE_ID_PLACEHOLDER, feature_id) for feature_id in feature_ids)
        elif not JINJA_RE.search(name):
            names.add(name)
    return names


def help_fields():
    """Yield ``(section_id, field)`` for every Help field the schema declares."""
    for section_id, field in fields_module.iter_fields():
        if section_id in HELP_SECTIONS:
            yield section_id, field


def test_help_panes_match_navigation():
    """The panes read here must be the ones ADMIN_NAV puts in the Help group."""
    print("Testing Help pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.275")

    group = next((item for item in ADMIN_NAV if item["id"] == HELP_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'help' group."

    nav_tabs = {tab["id"]: tuple(section["id"] for section in tab["sections"]) for tab in group["tabs"]}
    assert nav_tabs == HELP_PANES, (
        "The Help group changed. Update HELP_PANES and the schema together.\n"
        f"  ADMIN_NAV: {nav_tabs}\n  test: {HELP_PANES}"
    )

    latest = next(tab for tab in group["tabs"] if tab["id"] == "latest-features")
    assert latest.get("render") == "latest_features", (
        "Admin Latest Features must stay rendered from the release catalogue; the V2 "
        "page keys its catalogue card off render == 'latest_features'."
    )

    print(f"  {len(nav_tabs)} Help tab(s) match ADMIN_NAV.")
    return True


def test_disabled_template_blocks_are_stripped():
    """The parity reading must ignore markup the template can never render."""
    print("\nTesting that {% if false %} blocks are ignored...")

    markup = (
        'before <input name="kept">'
        "{% if false %}<input name=\"hidden_a\">{% if settings.x %}"
        '<input name="hidden_b">{% endif %}{% endif %}'
        ' after <input name="also_kept">'
    )
    names = collect_pane_field_names(strip_disabled_blocks(markup))
    assert names == {"kept", "also_kept"}, names

    raw = (PANES_DIR / "latest-features.html").read_text(encoding="utf-8")
    assert "latest_features_enable_thoughts_proxy" in raw, (
        "The retired Latest Features proxies are gone; drop the {% if false %} handling."
    )
    assert not collect_pane_field_names(read_pane("latest-features")), (
        "Admin Latest Features submits no settings once its disabled block is removed."
    )

    print("  Disabled blocks are removed before field names are read.")
    return True


def test_every_v1_help_field_is_claimed():
    """A V1 Help field with no V2 owner would be invisible in the new UI."""
    print("\nTesting that every V1 Help field is claimed...")

    claimed = fields_module.get_legacy_field_names()
    form_only = set(fields_module.LEGACY_FORM_ONLY_FIELDS)
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in HELP_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - form_only - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These Help fields exist in the server-rendered panes but have no V2 owner. "
        "Declare them in admin_settings_fields.py, record a shape difference in "
        "LEGACY_FIELD_NAMES, or map a non-setting input in LEGACY_FORM_ONLY_FIELDS:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    assert total >= 90, f"Only {total} Help field names were read; the extraction likely broke."
    print(f"  All {total} V1 Help field name(s) are claimed.")
    return True


def test_schema_does_not_invent_help_fields():
    """A Help key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Help fields...")

    v1_names = set()
    for pane_id in HELP_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for section_id, field in help_fields():
        key = field.get("key")
        if not key:
            continue
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if not legacy or not all(name in v1_names for name in legacy):
            invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These Help schema fields do not map onto the V1 panes:\n  " + "\n  ".join(invented)
    )

    print("  Every Help schema key maps back to the V1 panes.")
    return True


def test_form_only_inputs_belong_to_declared_components():
    """Each Send Feedback input must be offered by a component V2 actually draws."""
    print("\nTesting the Send Feedback inputs against their components...")

    declared = {
        field["component"]: section_id
        for section_id, field in help_fields()
        if field.get("type") == "component"
    }
    expected_sections = {
        "send-feedback-bug-report": "send-feedback-bug-card",
        "send-feedback-feature-request": "send-feedback-feature-card",
    }

    problems = []
    for name, component in fields_module.LEGACY_FORM_ONLY_FIELDS.items():
        if component not in declared:
            problems.append(f"{name}: component {component!r} is not declared")
        elif declared[component] != expected_sections.get(component):
            problems.append(f"{name}: component {component!r} is declared in {declared[component]}")

    send_feedback_names = collect_pane_field_names(read_pane("send-feedback"))
    assert send_feedback_names == set(fields_module.LEGACY_FORM_ONLY_FIELDS), (
        "LEGACY_FORM_ONLY_FIELDS should name exactly the Send Feedback inputs:\n"
        f"  pane: {sorted(send_feedback_names)}\n"
        f"  schema: {sorted(fields_module.LEGACY_FORM_ONLY_FIELDS)}"
    )
    assert "send-feedback-overview" in declared, "The Send Feedback overview card has no component."
    assert not problems, "\n  ".join(problems)

    print(f"  {len(fields_module.LEGACY_FORM_ONLY_FIELDS)} Send Feedback input(s) are owned by declared components.")
    return True


def test_support_menu_fields_match_v1():
    """The Support card offers V1's controls, in V1's order, behind the same gates."""
    print("\nTesting the Support Menu declaration...")

    fields = fields_module.ADMIN_SETTINGS_FIELDS["support-menu-section"]
    keys = [field["key"] for field in fields]
    assert keys == [
        "enable_support_menu",
        "support_menu_name",
        "enable_support_send_feedback",
        "support_feedback_recipient_email",
        "enable_support_latest_features",
    ], keys

    by_key = {field["key"]: field for field in fields}
    recipient = by_key["support_feedback_recipient_email"]
    assert recipient.get("input_type") == "email"
    assert recipient.get("required") is True
    gates = {condition["key"] for condition in fields_module.iter_field_dependencies(recipient)}
    assert gates == {"enable_support_menu", "enable_support_send_feedback"}, gates

    menu_name = by_key["support_menu_name"]
    assert menu_name.get("fallback_when_empty") is True and menu_name.get("default") == "Support"

    related = by_key["enable_support_latest_features"].get("related_section") or {}
    assert related.get("section_id") == "user-facing-latest-features-section", related
    assert not related.get("classic_only"), "V2 draws the User-Facing Latest Features card itself."

    print("  The Support card mirrors the V1 pane.")
    return True


def test_support_status_reports_a_missing_recipient():
    """Send Feedback on with no recipient is a configuration gap, not a working state."""
    print("\nTesting the Support section status rule...")

    rule = fields_module.ADMIN_SECTION_STATUS.get("support-menu-section")
    assert rule, "The Support section declares no status rule."
    assert rule["enabled_key"] == "enable_support_menu"
    assert rule["configured"] == [
        {
            "when": {"enable_support_send_feedback": True},
            "requires": ["support_feedback_recipient_email"],
        }
    ], rule["configured"]

    print("  A missing recipient reads as Needs configuration.")
    return True


def test_user_facing_choices_are_editable_before_publishing():
    """The checklist and its doc-links switch are drawn whatever the Support state."""
    print("\nTesting the User-Facing Latest Features declaration...")

    fields = fields_module.ADMIN_SETTINGS_FIELDS["user-facing-latest-features-section"]
    components = [field.get("component") for field in fields if field.get("type") == "component"]
    assert components == [
        "support-latest-features-publication",
        "support-latest-features-visibility",
    ], components

    visibility = next(field for field in fields if field.get("component") == "support-latest-features-visibility")
    assert visibility.get("key") == "support_latest_features_visibility"
    assert "default" not in visibility, (
        "The application default is computed from the catalogue, so the schema must "
        "not pin a literal one."
    )

    for field in fields:
        assert not field.get("depends_on"), (
            f"{field.get('key') or field.get('component')} is gated; V2 lets the "
            "announcements be prepared before they are published."
        )

    print("  The announcements can be curated before they are published.")
    return True


def test_v2_page_renders_the_latest_features_tab():
    """Without a branch for render == 'latest_features' the tab would draw nothing."""
    print("\nTesting that the V2 page renders Admin Latest Features...")

    page = PAGE_TSX.read_text(encoding="utf-8")
    library = LATEST_FEATURES_TS.read_text(encoding="utf-8")

    assert "export const LATEST_FEATURES_RENDER = 'latest_features';" in library
    assert "tab.render === LATEST_FEATURES_RENDER" in page, (
        "AdminSettingsPage.tsx no longer turns the catalogue tab into a card."
    )
    assert "<AdminLatestFeatures" in page
    assert "/api/v2/admin/latest-features" in page, "The page no longer loads the catalogues."

    print("  The catalogue tab is rendered as a card.")
    return True


if __name__ == "__main__":
    tests = [
        test_help_panes_match_navigation,
        test_disabled_template_blocks_are_stripped,
        test_every_v1_help_field_is_claimed,
        test_schema_does_not_invent_help_fields,
        test_form_only_inputs_belong_to_declared_components,
        test_support_menu_fields_match_v1,
        test_support_status_reports_a_missing_recipient,
        test_user_facing_choices_are_editable_before_publishing,
        test_v2_page_renders_the_latest_features_tab,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
