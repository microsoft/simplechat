#!/usr/bin/env python3
# test_v2_admin_backup_recovery_parity.py
"""
Functional parity test between the classic and V2 Backup & Recovery admin surfaces.
Version: 0.261.275
Implemented in: 0.261.275

Both interfaces drive the same admin API under /api/admin/data-management. The classic
page is the reference: what it saves, which endpoints it calls, which typed phrases it
sends. The V2 surface re-describes all of that in TypeScript, and every one of those
descriptions can drift silently -- a missing settings key is simply never saved, a
missing endpoint is a capability that quietly does not exist in V2, and a phrase that
differs by one character makes a destructive action impossible to confirm.

These checks read both sides from source and require them to agree.
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
V1_JS = APP_ROOT / "static" / "js" / "admin" / "admin_data_management.js"
BACKEND = APP_ROOT / "functions_data_management.py"
V2_LIB = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "dataManagement.ts"
V2_FIELDS = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "dataManagementFields.ts"

# The Backup & Recovery navigation, tab by tab, and the V2 component drawing each section.
EXPECTED_SECTIONS = {
    "backup": {
        "data-management-readiness-section": "data-management-readiness",
        "data-management-backup-section": "data-management-backup-runs",
        "data-management-schedule-section": "data-management-schedule",
        "data-management-storage-section": "data-management-storage",
        "data-management-encryption-section": "data-management-encryption",
    },
    "migrate": {"data-management-migration-section": "data-management-migration"},
    "restore": {"data-management-backup-inventory-section": "data-management-backup-inventory"},
    "cosmos-editor": {"data-management-cosmos-editor-section": "data-management-cosmos-editor"},
    "jobs": {"data-management-jobs-section": "data-management-jobs"},
}

# Typed confirmations: V2 constant -> backend constant.
PHRASES = {
    "RESTORE_OVERWRITE_PHRASE": "DATA_MANAGEMENT_RESTORE_OVERWRITE_CONFIRMATION",
    "MIRROR_CONFIRMATION_PHRASE": "DATA_MANAGEMENT_MIRROR_CONFIRMATION",
    "COSMOS_EDITOR_SAVE_PHRASE": "DATA_MANAGEMENT_COSMOS_EDITOR_CONFIRMATION_PHRASE",
}

# Upper bounds the V2 form enforces -> the backend constant that clamps the same value.
UPPER_BOUNDS = {
    "backup_max_parallel_operations": "DATA_MANAGEMENT_BACKUP_MAX_PARALLEL_OPERATIONS",
    "backup_retry_count": "DATA_MANAGEMENT_BACKUP_MAX_RETRY_COUNT",
    "backup_blob_max_parallel_operations": "DATA_MANAGEMENT_BLOB_BACKUP_MAX_PARALLEL_OPERATIONS",
    "backup_blob_chunk_size_mib": "DATA_MANAGEMENT_BLOB_BACKUP_MAX_CHUNK_SIZE_MIB",
    "backup_blob_retry_count": "DATA_MANAGEMENT_BACKUP_MAX_RETRY_COUNT",
    "backup_temporary_source_ru": "DATA_MANAGEMENT_BACKUP_MAX_SOURCE_RU",
    "migration_max_parallel_operations": "DATA_MANAGEMENT_MIGRATION_MAX_PARALLEL_OPERATIONS",
    "migration_retry_count": "DATA_MANAGEMENT_MIGRATION_MAX_RETRY_COUNT",
    "migration_skip_recent_within_hours": "DATA_MANAGEMENT_MIGRATION_MAX_SKIP_WITHIN_HOURS",
    "migration_temporary_destination_ru": "DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU",
}

fields_module = import_app_module("admin_settings_fields")


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _block(source, start_marker, open_char="{", close_char="}"):
    """Return the text between the bracket opened after ``start_marker`` and its match."""
    start = source.index(start_marker)
    open_index = source.index(open_char, start)
    depth = 0
    for index in range(open_index, len(source)):
        if source[index] == open_char:
            depth += 1
        elif source[index] == close_char:
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : index]
    raise AssertionError(f"Unbalanced block after {start_marker!r}")


def _backend_constant(source, name):
    match = re.search(rf"^{name} = (.+)$", source, re.MULTILINE)
    assert match, f"Backend constant {name} was not found"
    return ast.literal_eval(match.group(1).strip())


def _assigned_object(source, marker):
    """Return the body of the object literal assigned after ``marker``.

    A TypeScript annotation can hold braces of its own, so the search starts at the
    assignment rather than at the first brace after the name.
    """
    assignment = source.index("= {", source.index(marker))
    return _block(source[assignment:], "= {")


def _v1_collect_settings_keys():
    body = _block(_read(V1_JS), "function collectSettings()")
    returned = _block(body, "return {")
    keys = re.findall(r"^\s*([a-z0-9_]+):", returned, re.MULTILINE)
    assert keys, "Could not read collectSettings() from admin_data_management.js"
    return keys


def _v2_editable_keys():
    block = _block(_read(V2_LIB), "export const DM_EDITABLE_KEYS = [", "[", "]")
    keys = re.findall(r"'([a-z0-9_]+)'", block)
    assert keys, "Could not read DM_EDITABLE_KEYS from dataManagement.ts"
    return keys


def _normalize_endpoint(path):
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{query\}$", "", path)
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    return path.rstrip("/")


def test_backup_recovery_navigation_is_fully_described():
    """Every Backup & Recovery section is drawn by exactly one V2 component."""
    print("Testing Backup & Recovery navigation against the V2 components...")

    assert_app_version_at_least("0.261.275")

    group = next(item for item in ADMIN_NAV if item["id"] == "backup-recovery")
    tabs = {tab["id"]: [section["id"] for section in tab["sections"]] for tab in group["tabs"]}
    assert set(tabs) == set(EXPECTED_SECTIONS), (
        "The Backup & Recovery tabs changed. Update EXPECTED_SECTIONS and the V2 "
        f"components together.\n  ADMIN_NAV: {sorted(tabs)}"
    )

    schema = fields_module.get_admin_settings_fields()
    problems = []
    for tab_id, sections in EXPECTED_SECTIONS.items():
        if list(sections) != tabs[tab_id]:
            problems.append(f"{tab_id}: nav sections {tabs[tab_id]} != {list(sections)}")
        for section_id, component in sections.items():
            fields = schema.get(section_id, [])
            components = [field.get("component") for field in fields if field.get("type") == "component"]
            if components != [component] or len(fields) != 1:
                problems.append(f"{section_id}: expected only component {component!r}, found {fields}")
    assert not problems, "Backup & Recovery is not fully described:\n  " + "\n  ".join(problems)

    print(f"  {sum(len(sections) for sections in EXPECTED_SECTIONS.values())} section(s) across {len(tabs)} tab(s) described.")
    return True


def test_v2_saves_every_setting_the_classic_page_saves():
    """A key the classic page sends but V2 does not would never be saved from V2."""
    print("\nTesting the settings save payload against collectSettings()...")

    v1_keys = _v1_collect_settings_keys()
    v2_keys = _v2_editable_keys()
    assert v1_keys == v2_keys, (
        "DM_EDITABLE_KEYS must match the classic collectSettings() keys, in order.\n"
        f"  only classic: {sorted(set(v1_keys) - set(v2_keys))}\n"
        f"  only V2: {sorted(set(v2_keys) - set(v1_keys))}"
    )

    fields_source = _read(V2_FIELDS)
    derived = {"retention_days", "target_cosmos_database_name"}
    # Edited by bespoke controls in the Schedule card rather than a declared field.
    custom_controls = {"scheduled_time_utc", "retention_value", "retention_unit"}
    undeclared = [
        key for key in v2_keys
        if key not in derived and key not in custom_controls and f"dmKey: '{key}'" not in fields_source
    ]
    assert not undeclared, (
        "These saved settings have no control declaration in dataManagementFields.ts, so "
        f"nothing in V2 can edit them: {undeclared}"
    )

    print(f"  All {len(v1_keys)} settings keys match, and every editable one has a control.")
    return True


def test_v2_calls_every_endpoint_the_classic_page_calls():
    """An endpoint only the classic page calls is a capability V2 lacks."""
    print("\nTesting data-management endpoints...")

    v1_paths = set()
    for raw in re.findall(r"/api/admin/data-management([^\"'`]*)", _read(V1_JS)):
        if raw.startswith("/${listKind}"):
            # One helper serves both history lists.
            v1_paths.update({"/backups", "/jobs"})
            continue
        v1_paths.add(_normalize_endpoint(raw))

    v2_source = _read(V2_LIB)
    v2_paths = {
        _normalize_endpoint(raw)
        for raw in re.findall(r"`\$\{DM_API\}([^`]*)`", v2_source)
    }

    missing = sorted(v1_paths - v2_paths)
    assert not missing, (
        "The classic page calls these data-management endpoints but dataManagement.ts "
        f"does not, so V2 is missing what they do: {missing}"
    )

    print(f"  All {len(v1_paths)} classic endpoint(s) are called by V2.")
    return True


def test_typed_confirmations_match_the_server():
    """A phrase that differs by one character makes the action impossible to confirm."""
    print("\nTesting typed confirmation phrases...")

    backend = _read(BACKEND)
    v2_source = _read(V2_LIB)
    for v2_name, backend_name in PHRASES.items():
        match = re.search(rf"export const {v2_name} = '([^']+)';", v2_source)
        assert match, f"{v2_name} is missing from dataManagement.ts"
        expected = _backend_constant(backend, backend_name)
        assert match.group(1) == expected, f"{v2_name} is {match.group(1)!r}, the server expects {expected!r}"

    print(f"  All {len(PHRASES)} phrases match the server.")
    return True


def test_defaults_and_bounds_match_the_server():
    """A drifted default shows the wrong value for a setting the document does not hold yet."""
    print("\nTesting data-management defaults and bounds...")

    backend = _read(BACKEND)
    defaults_block = _block(backend, "DATA_MANAGEMENT_DEFAULT_SETTINGS = {")
    backend_defaults = {}
    for key, raw in re.findall(r'^\s*"([a-z0-9_]+)":\s*(.+?),\s*$', defaults_block, re.MULTILINE):
        raw = raw.strip()
        try:
            backend_defaults[key] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            backend_defaults[key] = _backend_constant(backend, raw)

    v2_source = _read(V2_LIB)
    v2_block = _assigned_object(v2_source, "export const DM_DEFAULTS")
    v2_defaults = {}
    for key, raw in re.findall(r"^\s*([a-z0-9_]+):\s*(.+?),\s*$", v2_block, re.MULTILINE):
        raw = raw.strip()
        if raw in ("true", "false"):
            v2_defaults[key] = raw == "true"
        elif re.fullmatch(r"-?\d+", raw):
            v2_defaults[key] = int(raw)
        elif raw.startswith("'"):
            v2_defaults[key] = raw.strip("'")
        else:
            constant = re.search(rf"export const {raw} = '([^']+)';", v2_source)
            assert constant, f"Unresolved V2 default constant {raw}"
            v2_defaults[key] = constant.group(1)

    mismatches = [
        f"{key}: V2 {value!r} != server {backend_defaults.get(key)!r}"
        for key, value in v2_defaults.items()
        if backend_defaults.get(key) != value
    ]
    assert not mismatches, "DM_DEFAULTS drifted from the server:\n  " + "\n  ".join(mismatches)

    bounds_block = _assigned_object(v2_source, "export const DM_NUMBER_BOUNDS")
    v2_max = {
        key: int(value)
        for key, value in re.findall(r"([a-z0-9_]+): \{ min: \d+, max: (\d+)", bounds_block)
    }
    wrong = [
        f"{key}: V2 max {v2_max.get(key)} != {constant} {_backend_constant(backend, constant)}"
        for key, constant in UPPER_BOUNDS.items()
        if v2_max.get(key) != _backend_constant(backend, constant)
    ]
    assert not wrong, "Form bounds drifted from the server clamps:\n  " + "\n  ".join(wrong)

    print(f"  {len(v2_defaults)} default(s) and {len(UPPER_BOUNDS)} bound(s) match the server.")
    return True


if __name__ == "__main__":
    tests = [
        test_backup_recovery_navigation_is_fully_described,
        test_v2_saves_every_setting_the_classic_page_saves,
        test_v2_calls_every_endpoint_the_classic_page_calls,
        test_typed_confirmations_match_the_server,
        test_defaults_and_bounds_match_the_server,
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
