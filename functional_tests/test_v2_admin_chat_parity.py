#!/usr/bin/env python3
# test_v2_admin_chat_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Chat group.
Version: 0.261.059
Implemented in: 0.261.059

The V2 React admin surface renders from ``admin_settings_fields.py`` rather than
from the server-rendered panes, so the two descriptions of the same settings can
drift apart silently: a field added to a V1 pane simply never appears in V2, and
nothing fails.

Before the Chat group was described, that gap was not hypothetical. The V2
surface could only discover settings by scanning for ``enable_*`` booleans, so
every non-boolean chat setting was invisible -- the conversation history limit,
the default system prompt, and the nine Enhanced Citations controls -- along with
the two switches whose keys do not start with ``enable_``
(``enforce_workspace_scope_lock`` and
``require_member_of_chat_file_upload_user``).

This test closes that gap the way ``test_v2_admin_appearance_parity.py`` closes
it for Appearance. It reads the three panes that make up the group, collects the
form field names V1 submits, and requires each one to be claimed by the schema.

It also checks the parts of a field a generic renderer must get right and a
name-only comparison would miss: select option values and numeric bounds. Bounds
are compared only where V1 declares them, because V1 leaves several number inputs
unbounded and inventing a matching absence in the schema would mean shipping a
control with no floor.
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

# The three tabs that make up the Chat group, and the sections each one
# contributes. Sourced from ADMIN_NAV, verified against it below.
CHAT_GROUP_ID = "chat"
CHAT_PANES = {
    "chat-experience": (
        "processing-thoughts-section",
        "chat-file-uploads-section",
        "conversation-contents-drawer-section",
        "workspace-scope-lock-section",
        "conversation-history-section",
        "default-system-prompt-section",
        "fact-memory-section",
    ),
    "feedback-alerts": ("user-feedback-section", "desktop-notifications-section"),
    "citation": ("standard-citations-section", "enhanced-citations-section"),
}

# Sections in the group that hold no settings at all. Standard Citations is a
# card of explanatory prose in V1: standard citations are always on and have
# nothing to configure. Declaring an empty section would imply otherwise.
SECTIONS_WITHOUT_SETTINGS = {"standard-citations-section"}

# Capabilities declared under a Chat section whose server-rendered control lives
# in another group's pane, mapped to the pane that actually draws them.
#
# The audio cue is the case. It plays a short bundled sound locally when a
# response finishes and needs no Azure Speech resource -- its own help text says
# as much -- so V2 files it with the other completion alerts instead of at the
# top of the AI Voice card, where V1 still draws it. The check below follows it
# to its real pane rather than skipping it, so it still has to exist in V1.
RELOCATED_INTO_CHAT = {
    "enable_chat_completion_audio_cues": "audio-video",
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)
NUMBER_BLOCK_RE = re.compile(r'<input[^>]*type="number"(?P<attrs>[^>]*)>', re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

# V1 renders a secret as a password input. The schema must agree, or the V2
# surface would print a stored connection string in cleartext on the page.
PASSWORD_BLOCK_RE = re.compile(r'<input[^>]*type="password"(?P<attrs>[^>]*)>', re.DOTALL)

# Markup that V1 comments out is not a live field. The citation pane keeps the
# video and audio storage cards commented out pending a presentation layer, and
# treating those as unclaimed V1 fields would demand V2 controls for settings the
# server-rendered page does not actually show either.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the live markup for one Admin Settings pane, comments removed."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return HTML_COMMENT_RE.sub("", pane_path.read_text(encoding="utf-8"))


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {
        name
        for name in FIELD_NAME_RE.findall(markup)
        if not JINJA_RE.search(name)
    }


def chat_section_ids():
    """Every section id in the Chat group."""
    return {section for sections in CHAT_PANES.values() for section in sections}


def test_chat_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Chat pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.059")

    group = next((g for g in ADMIN_NAV if g["id"] == CHAT_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'chat' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}

    assert set(nav_tabs) == set(CHAT_PANES), (
        "The Chat group's tabs changed. Update CHAT_PANES and the schema "
        f"together.\n  ADMIN_NAV: {sorted(nav_tabs)}\n  test: {sorted(CHAT_PANES)}"
    )

    for tab_id, section_ids in nav_tabs.items():
        assert section_ids == CHAT_PANES[tab_id], (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {section_ids}\n  test: {CHAT_PANES[tab_id]}"
        )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_every_v1_field_is_claimed_by_the_schema():
    """A V1 Chat field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Chat field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in CHAT_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These fields exist in the server-rendered Chat panes but are not "
        "described in admin_settings_fields.py, so they cannot appear in the V2 "
        "admin UI. Add a field definition, record the name in LEGACY_FIELD_NAMES "
        "if the shapes differ, or document the omission in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    print(f"  All {total} V1 Chat field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_chat_fields():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Chat fields...")

    v1_names = set()
    for pane_id in CHAT_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for section_id, field in fields_module.iter_fields():
        if section_id not in chat_section_ids():
            continue
        key = field.get("key")
        if not key:
            continue
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        # A capability relocated into Chat is checked against the pane that
        # actually draws it, so the "nothing reads this" guarantee still holds.
        names = v1_names
        if key in RELOCATED_INTO_CHAT:
            names = collect_pane_field_names(read_pane(RELOCATED_INTO_CHAT[key]))
        if not any(name in names for name in legacy):
            invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 Chat panes, so V2 "
        "would write settings the rest of the application never reads:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Chat schema field maps back to a V1 field.")
    return True


def test_every_chat_section_with_settings_is_described():
    """An undescribed section falls back to switches, which is what this fixes."""
    print("\nTesting that every Chat section with settings is described...")

    described = set(fields_module.ADMIN_SETTINGS_FIELDS)

    missing = []
    for pane_id, section_ids in CHAT_PANES.items():
        pane_has_fields = bool(collect_pane_field_names(read_pane(pane_id)))
        for section_id in section_ids:
            if section_id in SECTIONS_WITHOUT_SETTINGS or section_id in described:
                continue
            if pane_has_fields:
                missing.append(f"{section_id} (from {pane_id}.html)")

    assert not missing, (
        "These Chat sections have no schema entry, so the V2 surface falls back "
        "to guessing their settings from enable_* booleans:\n  "
        + "\n  ".join(missing)
    )

    empty = sorted(
        section_id
        for section_id in SECTIONS_WITHOUT_SETTINGS
        if section_id in described
    )
    assert not empty, (
        "These sections are recorded as holding no settings but are declared "
        "anyway. Either V1 gained a control and SECTIONS_WITHOUT_SETTINGS is "
        "stale, or the declaration is empty and should be removed:\n  "
        + "\n  ".join(empty)
    )

    print(f"  All {len(chat_section_ids())} Chat section(s) accounted for.")
    return True


def test_select_options_match_v1():
    """A select offering different values than V1 would save unreadable state."""
    print("\nTesting Chat select option values against V1...")

    v1_options = {}
    for pane_id in CHAT_PANES:
        for match in SELECT_BLOCK_RE.finditer(read_pane(pane_id)):
            name = match.group("name")
            if JINJA_RE.search(name):
                continue
            v1_options[name] = OPTION_RE.findall(match.group("body"))

    mismatches = []
    checked = 0
    for section_id, field in fields_module.iter_fields():
        if section_id not in chat_section_ids() or field.get("type") != "select":
            continue
        key = field.get("key")
        if key not in v1_options:
            continue
        schema_values = [option["value"] for option in field["options"]]
        if schema_values != v1_options[key]:
            mismatches.append(
                f"{key}: schema {schema_values} != template {v1_options[key]}"
            )
        checked += 1

    assert not mismatches, (
        "These selects offer different values in each interface:\n  "
        + "\n  ".join(mismatches)
    )

    assert checked, "No Chat select fields were compared; the extraction likely broke."
    print(f"  {checked} select(s) offer identical values in both interfaces.")
    return True


def test_number_bounds_match_v1():
    """A tighter bound in one interface rejects a value the other accepts."""
    print("\nTesting Chat number bounds against V1...")

    v1_numbers = {}
    for pane_id in CHAT_PANES:
        for match in NUMBER_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            name = attrs.get("name")
            if not name or JINJA_RE.search(name):
                continue
            v1_numbers[name] = attrs

    mismatches = []
    checked = 0
    for section_id, field in fields_module.iter_fields():
        if section_id not in chat_section_ids() or field.get("type") != "number":
            continue
        attrs = v1_numbers.get(field.get("key"))
        if not attrs:
            continue
        checked += 1
        for prop in ("min", "max"):
            # Only compare a bound V1 actually declares. V1 leaves several number
            # inputs unbounded; the schema still needs a floor so the control
            # cannot produce a negative, and that is not a parity failure.
            if prop not in attrs:
                continue
            if str(field.get(prop)) != attrs[prop]:
                mismatches.append(
                    f"{field['key']}.{prop}: schema {field.get(prop)} "
                    f"!= template {attrs[prop]}"
                )

    assert not mismatches, (
        "These number controls differ between interfaces:\n  " + "\n  ".join(mismatches)
    )
    assert checked, "No Chat number fields were compared; the extraction likely broke."
    print(f"  {checked} number control(s) agree with the bounds V1 declares.")
    return True


def test_v1_password_fields_are_declared_as_secrets():
    """A secret declared as text would print a credential onto the page."""
    print("\nTesting that V1 password fields are declared as secrets...")

    v1_passwords = set()
    for pane_id in CHAT_PANES:
        for match in PASSWORD_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            name = attrs.get("name")
            if name and not JINJA_RE.search(name):
                v1_passwords.add(name)

    assert v1_passwords, (
        "No password inputs were found in the Chat panes; the extraction likely broke."
    )

    declared_types = {
        field["key"]: field.get("type")
        for section_id, field in fields_module.iter_fields()
        if section_id in chat_section_ids() and field.get("key")
    }

    wrong = [
        f"{name}: declared as {declared_types.get(name)!r}, expected 'secret'"
        for name in sorted(v1_passwords)
        if declared_types.get(name) != "secret"
    ]

    assert not wrong, (
        "V1 masks these fields as password inputs, so the schema must declare "
        "them as secrets. Any other type renders the stored value in cleartext:\n  "
        + "\n  ".join(wrong)
    )

    print(f"  All {len(v1_passwords)} V1 password field(s) are declared as secrets.")
    return True


if __name__ == "__main__":
    tests = [
        test_chat_panes_match_navigation,
        test_every_v1_field_is_claimed_by_the_schema,
        test_schema_does_not_invent_chat_fields,
        test_every_chat_section_with_settings_is_described,
        test_select_options_match_v1,
        test_number_bounds_match_v1,
        test_v1_password_fields_are_declared_as_secrets,
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
