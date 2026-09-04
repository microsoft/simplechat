#!/usr/bin/env python3
# test_v2_admin_actions_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Actions tab.
Version: 0.261.062
Implemented in: 0.261.062

Two things in this tab are not ordinary settings, and both fail silently.

``document_action_capabilities`` is stored as one nested object holding six
values across two action types. Nothing reads a flattened form of them, so a
schema that declared six top-level keys would save settings the application never
looks at, and the Analyze and Comparison limits would appear to have no effect.
The schema therefore declares a ``settings_path`` per field and the container is
reassembled on save.

Fact memory and tabular processing are owned elsewhere: fact memory is a chat
capability edited under Chat, and tabular processing is recomputed from Enhanced
Citations on every settings read. Both belong in an actions list for an
administrator working out what an agent can do, but neither may be written from
here -- tabular processing in particular used to render as an editable toggle
under Chat > Processing Thoughts, where flipping it did nothing at all.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
DOCUMENT_ACTIONS_MODULE = APP_ROOT / "functions_document_actions.py"
DOCUMENT_ANALYSIS_MODULE = APP_ROOT / "functions_document_analysis.py"

ACTIONS_SECTIONS = (
    "document-action-capabilities-card",
    "plugin-feature-toggles",
    "core-plugin-toggles",
    "actions-config",
)

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def literal_assignment(source, name):
    """Return a module-level literal assignment, without importing the module.

    ``functions_document_actions`` reaches ``config.py``, which builds a Cosmos
    client at import time, so it cannot be imported in a plain test process. The
    values are read out of the source the same way the other schema tests read
    the settings defaults.
    """
    tree = ast.parse(source)
    namespace = {}
    wanted = None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                namespace[target.id] = _resolve(node.value, namespace)
            except AssertionError:
                # Values built from imported names or calls are not needed here.
                continue
            if target.id == name:
                wanted = namespace[target.id]

    assert wanted is not None, f"{name} was not found; the extraction likely broke."
    return wanted


def _resolve(node, namespace):
    """Evaluate a literal expression, resolving names already seen in the module."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        assert node.id in namespace, f"unresolved name {node.id}"
        return namespace[node.id]
    if isinstance(node, ast.Dict):
        return {
            _resolve(key, namespace): _resolve(value, namespace)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_resolve(element, namespace) for element in node.elts]
    if isinstance(node, ast.Set):
        return {_resolve(element, namespace) for element in node.elts}
    raise AssertionError(f"unsupported expression: {type(node).__name__}")


def document_action_bounds():
    """Return the min/max bounds the application enforces per execution context."""
    source = DOCUMENT_ACTIONS_MODULE.read_text(encoding="utf-8")
    return literal_assignment(source, "DOCUMENT_ACTION_LIMIT_BOUNDS")


def document_action_default_limits():
    """Return the default chat and workflow limits."""
    source = DOCUMENT_ANALYSIS_MODULE.read_text(encoding="utf-8")
    return {
        "chat": literal_assignment(source, "CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS"),
        "workflow": literal_assignment(source, "WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS"),
    }


def test_actions_sections_match_navigation():
    """The sections this test asserts on must be the ones ADMIN_NAV declares."""
    print("Testing the Actions tab sections against ADMIN_NAV...")

    assert_app_version_at_least("0.261.062")

    tab = next(
        (
            tab
            for group in ADMIN_NAV
            if group["id"] == "agents-actions"
            for tab in group["tabs"]
            if tab["id"] == "actions"
        ),
        None,
    )
    assert tab, "ADMIN_NAV no longer defines an 'actions' tab."

    actual = tuple(section["id"] for section in tab["sections"])
    assert actual == ACTIONS_SECTIONS, (
        f"The Actions sections changed.\n  ADMIN_NAV: {actual}\n  test: {ACTIONS_SECTIONS}"
    )

    conditions = {section["id"]: section.get("condition") for section in tab["sections"]}
    assert conditions["plugin-feature-toggles"] == "per_user_semantic_kernel", (
        "Workspace Action Permissions must be conditional on Workspace Mode, "
        "because nothing reads those permissions outside it."
    )

    print(f"  {len(actual)} section(s) match ADMIN_NAV.")
    return True


def test_every_actions_pane_field_is_claimed_by_the_schema():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Actions field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    names = {
        name
        for name in FIELD_NAME_RE.findall(read_pane("actions"))
        if not JINJA_RE.search(name)
    }
    missing = sorted(names - claimed - documented)

    assert not missing, (
        "These V1 Actions fields have no V2 equivalent and no recorded reason:\n  "
        + "\n  ".join(missing)
    )

    print(f"  All {len(names)} V1 Actions field name(s) are claimed.")
    return True


def test_document_action_fields_write_into_the_nested_container():
    """A flat key here would save a setting the application never reads."""
    print("\nTesting document action settings paths...")

    schema = fields_module.get_admin_settings_fields()
    fields = schema["document-action-capabilities-card"]

    expected = {
        "document_action_analyze_enabled": ["document_action_capabilities", "analyze", "enabled"],
        "document_action_analyze_chat_max_documents": [
            "document_action_capabilities",
            "analyze",
            "chat_max_documents",
        ],
        "document_action_analyze_workflow_max_documents": [
            "document_action_capabilities",
            "analyze",
            "workflow_max_documents",
        ],
        "document_action_comparison_enabled": [
            "document_action_capabilities",
            "comparison",
            "enabled",
        ],
        "document_action_comparison_chat_max_documents": [
            "document_action_capabilities",
            "comparison",
            "chat_max_documents",
        ],
        "document_action_comparison_workflow_max_documents": [
            "document_action_capabilities",
            "comparison",
            "workflow_max_documents",
        ],
    }

    actual = {field["key"]: field.get("settings_path") for field in fields}
    assert actual == expected, (
        f"Document action settings paths drifted.\n  schema: {actual}\n  expected: {expected}"
    )

    print(f"  All {len(expected)} document action field(s) name their container path.")
    return True


def test_document_action_bounds_match_the_application():
    """A wider bound in the UI accepts a value the server silently clamps."""
    print("\nTesting document action bounds against functions_document_actions...")

    bounds = document_action_bounds()
    defaults = document_action_default_limits()
    schema = fields_module.get_admin_settings_fields()

    problems = []
    for field in schema["document-action-capabilities-card"]:
        path = field["settings_path"]
        leaf = path[-1]
        if leaf == "enabled":
            if field.get("default") is not True:
                problems.append(f"{field['key']}: default {field.get('default')!r}, expected True")
            continue

        context = "chat" if leaf == "chat_max_documents" else "workflow"
        if field.get("min") != bounds[context]["min"]:
            problems.append(
                f"{field['key']}: min {field.get('min')!r} != {bounds[context]['min']!r}"
            )
        if field.get("max") != bounds[context]["max"]:
            problems.append(
                f"{field['key']}: max {field.get('max')!r} != {bounds[context]['max']!r}"
            )
        if field.get("default") != defaults[context]:
            problems.append(
                f"{field['key']}: default {field.get('default')!r} != {defaults[context]!r}"
            )

    assert not problems, (
        "These document action bounds disagree with the application, which clamps "
        "to DOCUMENT_ACTION_LIMIT_BOUNDS on save:\n  " + "\n  ".join(problems)
    )

    print(f"  Bounds and defaults match: chat {bounds['chat']}, workflow {bounds['workflow']}.")
    return True


def test_nested_values_are_folded_into_their_container_on_save():
    """Saving one limit must not discard the other five.

    The container normalizer is replaced with an identity function for this
    check. It lives in ``functions_document_actions``, which reaches
    ``config.py`` and a live Cosmos client and so cannot be imported in a test
    process; the delegation itself is asserted separately below, and the bounds
    it enforces are pinned against its source above.
    """
    print("\nTesting the nested container fold...")

    current = {
        "document_action_capabilities": {
            "analyze": {
                "enabled": True,
                "chat_max_documents": 5,
                "workflow_max_documents": 50,
            },
            "comparison": {
                "enabled": False,
                "chat_max_documents": 7,
                "workflow_max_documents": 70,
            },
        }
    }

    original = fields_module._CONTAINER_NORMALIZERS
    fields_module._CONTAINER_NORMALIZERS = {"document_action_capabilities": lambda value: value}
    try:
        normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
            {"document_action_analyze_chat_max_documents": 9}, current
        )
    finally:
        fields_module._CONTAINER_NORMALIZERS = original

    assert not errors, f"Unexpected errors: {errors}"
    assert "document_action_analyze_chat_max_documents" not in normalized, (
        "The flat key must not reach update_settings; nothing reads it."
    )

    capabilities = normalized["document_action_capabilities"]
    assert capabilities["analyze"]["chat_max_documents"] == 9
    assert capabilities["analyze"]["workflow_max_documents"] == 50, (
        "Rebuilding the container dropped a sibling value."
    )
    assert capabilities["comparison"] == {
        "enabled": False,
        "chat_max_documents": 7,
        "workflow_max_documents": 70,
    }, "Rebuilding the container disturbed the other action type."

    assert current["document_action_capabilities"]["analyze"]["chat_max_documents"] == 5, (
        "The stored settings were mutated in place rather than copied."
    )

    print("  One edit rebuilds the container without losing its siblings.")
    return True


def test_the_container_is_normalized_by_the_module_that_owns_it():
    """Reimplementing the clamp here would let the two surfaces disagree."""
    print("\nTesting that container validation is delegated...")

    assert "document_action_capabilities" in fields_module._CONTAINER_NORMALIZERS, (
        "The container has no normalizer, so out-of-range limits would be stored."
    )

    source = (APP_ROOT / "admin_settings_fields.py").read_text(encoding="utf-8")
    assert (
        "from functions_document_actions import normalize_document_action_capabilities"
        in source
    ), (
        "Document action bounds must be enforced by the function the classic "
        "admin form already uses, not reimplemented here."
    )

    print("  Clamping is delegated to functions_document_actions.")
    return True


def test_read_only_mirrors_name_their_owner_and_cannot_invent_a_value():
    """A mirror must report a value, never set one it does not own."""
    print("\nTesting read-only action mirrors...")

    schema = fields_module.get_admin_settings_fields()
    mirrors = {
        field["key"]: field
        for field in schema["core-plugin-toggles"]
        if field.get("readonly")
    }

    assert set(mirrors) == {
        "enable_fact_memory_plugin",
        "enable_tabular_processing_plugin",
    }, f"Unexpected read-only mirrors: {sorted(mirrors)}"

    for key, field in mirrors.items():
        assert field.get("managed_by"), f"{key}: read-only without naming its owner"

    # Tabular processing has no editable declaration anywhere, because the
    # application recomputes it from Enhanced Citations on every settings read.
    # A write must therefore be refused rather than stored and then overwritten.
    _normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"enable_tabular_processing_plugin": True}, {}
    )
    assert "enable_tabular_processing_plugin" in errors, (
        "A derived setting accepted a write, which would store a value the next "
        "settings read discards."
    )
    assert mirrors["enable_tabular_processing_plugin"]["managed_by"] in (
        errors["enable_tabular_processing_plugin"]
    ), "The rejection must point at where the value really comes from."

    print(f"  {len(mirrors)} mirror(s) name their owner; the derived one refuses writes.")
    return True


def test_fact_memory_stays_editable_where_it_is_owned():
    """Mirroring a key must not remove the control that actually sets it."""
    print("\nTesting that fact memory is still editable under Chat...")

    owner = fields_module.get_field_definition("enable_fact_memory_plugin")
    assert owner is not None, "enable_fact_memory_plugin is not declared."
    assert not owner.get("readonly"), (
        "The read-only mirror claimed the key, so the Chat control that really "
        "sets it would be rejected on save."
    )

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"enable_fact_memory_plugin": False}, {}
    )
    assert not errors, f"Editing fact memory was rejected: {errors}"
    assert normalized["enable_fact_memory_plugin"] is False

    assert 'name="enable_fact_memory_plugin"' in read_pane("chat-experience"), (
        "The V1 owner control moved; the schema still points at Chat."
    )

    print("  Fact memory remains editable under Chat and mirrored under Actions.")
    return True


def test_tabular_processing_is_no_longer_an_editable_toggle():
    """It is recomputed from Enhanced Citations, so editing it never did anything.

    The fallback scan used to file it under Chat > Processing Thoughts as a live
    switch, purely because "processing" matched. Declaring it as a mirror is what
    takes it out of that scan.
    """
    print("\nTesting that tabular processing is declared as derived...")

    field = fields_module.get_field_definition("enable_tabular_processing_plugin")
    assert field is not None, "enable_tabular_processing_plugin is not declared."
    assert field.get("readonly"), "It is derived, so it must not be editable."
    assert "Enhanced Citations" in field.get("help", ""), (
        "The mirror must say what recomputes it, or an administrator has no way "
        "of knowing where to change it."
    )

    assert "is_tabular_processing_enabled" in (
        APP_ROOT / "route_frontend_admin_settings.py"
    ).read_text(encoding="utf-8"), (
        "The application no longer recomputes it, so it may now be settable and "
        "the mirror would be wrong."
    )

    print("  Tabular processing is declared derived and names its source.")
    return True


if __name__ == "__main__":
    tests = [
        test_actions_sections_match_navigation,
        test_every_actions_pane_field_is_claimed_by_the_schema,
        test_document_action_fields_write_into_the_nested_container,
        test_document_action_bounds_match_the_application,
        test_nested_values_are_folded_into_their_container_on_save,
        test_the_container_is_normalized_by_the_module_that_owns_it,
        test_read_only_mirrors_name_their_owner_and_cannot_invent_a_value,
        test_fact_memory_stays_editable_where_it_is_owned,
        test_tabular_processing_is_no_longer_an_editable_toggle,
    ]
    results = [test() for test in tests]
    print(f"\nResults: {sum(bool(r) for r in results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
