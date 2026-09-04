#!/usr/bin/env python3
# test_v2_admin_knowledge_file_sync.py
"""
Functional test for the Knowledge group's File Sync tab in the V2 admin UI.
Version: 0.261.072
Implemented in: 0.261.072

File Sync is the first section to declare a prerequisite owned by another group.
It needs Redis Cache, which lives under Scale, and the server-rendered card says
so with the ``data-requires`` attributes ``admin_settings_dependencies.js``
reads. Without carrying that across, an administrator turns File Sync on and
nothing happens, with no visible reason until a flash message after saving.

Two other things are worth pinning.

The per-run size limit is entered in gigabytes and stored in bytes. A missing
conversion in either direction is silent: the field shows 5368709120 in a box
labelled GB, or saves 5 bytes as the limit.

The group and public-workspace assignment lists are new functionality rather
than a port. The server-rendered pane renders both assignment modals in markup
but never wired up the JavaScript for them, so
``file_sync_allowed_group_ids`` and ``file_sync_allowed_public_workspace_ids``
have not been editable from either interface.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
PANE = (
    REPO_ROOT
    / "application"
    / "single_app"
    / "templates"
    / "admin"
    / "_panes"
    / "file-sync.html"
)

FILE_SYNC_SECTIONS = (
    "file-sync-section",
    "file-sync-source-types-section",
    "file-sync-personal-section",
    "file-sync-group-section",
    "file-sync-public-section",
)

SCOPE_SECTIONS = (
    "file-sync-personal-section",
    "file-sync-group-section",
    "file-sync-public-section",
)

GIBIBYTE = 1073741824

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates
evaluate = fields_module.evaluate_dependency

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")


def pane_field_names():
    markup = PANE.read_text(encoding="utf-8")
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def field_in(section_id, key):
    return next(
        (field for field in section_fields(section_id) if field.get("key") == key), None
    )


def test_the_tab_sections_match_navigation():
    """A field filed under an unknown section id would never render."""
    print("Testing File Sync sections against ADMIN_NAV...")

    assert_app_version_at_least("0.261.072")

    nav_sections = tuple(
        section["id"]
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "file-sync"
        for section in tab["sections"]
    )

    assert nav_sections == FILE_SYNC_SECTIONS, (
        f"ADMIN_NAV: {list(nav_sections)}\n  test: {list(FILE_SYNC_SECTIONS)}"
    )
    for section_id in FILE_SYNC_SECTIONS:
        assert section_fields(section_id), f"{section_id} declares no fields."

    print(f"  All {len(nav_sections)} section(s) exist in ADMIN_NAV and are described.")
    return True


def test_the_redis_prerequisite_is_declared():
    """Otherwise File Sync is switched on and silently never runs."""
    print("\nTesting the Redis Cache prerequisite...")

    field = field_in("file-sync-section", "enable_file_sync")
    assert field, "enable_file_sync is not declared."

    requirement = field.get("requires")
    assert requirement, (
        "enable_file_sync declares no prerequisite. Sync runs stay inactive "
        "without Redis Cache, and the server-rendered card says so; leaving it "
        "out here means the V2 surface does not."
    )
    assert requirement["key"] == "enable_redis_cache", requirement

    # warn rather than block: the backend accepts the settings as intent and
    # reconciles once Redis is configured, so the fields stay editable.
    assert requirement.get("mode") == "warn", (
        "The Redis prerequisite should warn rather than block, matching the "
        f"server-rendered card: {requirement}"
    )
    assert requirement.get("target_section"), (
        "The prerequisite should name a section to jump to, or an administrator "
        "has to go and find Redis Cache themselves."
    )
    assert requirement.get("description"), (
        "The prerequisite should explain the consequence, not just name a setting."
    )

    # And it should match what the V1 card declares, so the two interfaces do not
    # describe the same dependency differently.
    markup = PANE.read_text(encoding="utf-8")
    assert 'data-requires="enable_redis_cache"' in markup, (
        "The V1 card no longer declares this prerequisite; the two descriptions "
        "have diverged."
    )
    assert 'data-requires-mode="warn"' in markup, markup[:0]

    print("  The Redis Cache prerequisite is declared, in warn mode, with a target.")
    return True


def test_the_per_run_size_limit_converts_between_gb_and_bytes():
    """A missing conversion silently sets the limit to five bytes."""
    print("\nTesting the per-run size limit conversion...")

    field = field_in("file-sync-section", "file_sync_max_gb_per_run")
    assert field, "file_sync_max_gb_per_run is not declared."
    assert field.get("scale") == GIBIBYTE, (
        f"Expected a GiB scale to match the server-rendered form: {field.get('scale')}"
    )
    assert field.get("paths") == ["file_sync_max_bytes_per_run"], (
        "The limit is stored under file_sync_max_bytes_per_run; writing the GB "
        f"value to its own key would leave the real limit untouched: {field.get('paths')}"
    )

    normalized, errors, _ = normalize({"file_sync_max_gb_per_run": 5}, {})
    assert not errors, errors
    assert "file_sync_max_gb_per_run" not in normalized, normalized
    assert normalized["file_sync_max_bytes_per_run"] == 5 * GIBIBYTE, (
        f"5 GB should store as {5 * GIBIBYTE} bytes: {normalized}"
    )

    # Bounds are declared in the editing unit, so clamping happens before scaling.
    clamped, errors, _ = normalize({"file_sync_max_gb_per_run": 99999}, {})
    assert not errors, errors
    assert clamped["file_sync_max_bytes_per_run"] == 1024 * GIBIBYTE, clamped

    print("  Gigabytes in, bytes out, clamped in the unit the field is edited in.")
    return True


def test_the_scope_sections_share_one_shape():
    """Learning one scope should be enough to read the other two."""
    print("\nTesting the scope sections...")

    for section_id in SCOPE_SECTIONS:
        fields = section_fields(section_id)

        capability = [field for field in fields if field.get("role") == "capability"]
        assert len(capability) == 1, (
            f"{section_id} names {len(capability)} capability switches; each scope "
            "should name exactly one."
        )

        admin_only = [
            field for field in fields if field.get("key", "").endswith("_admin_only")
        ]
        assert len(admin_only) == 1, (
            f"{section_id} should offer an administrators-only control like the "
            "other scopes."
        )
        assert (admin_only[0].get("group") or {}).get("id") == "access", (
            f"{section_id}: the access control is not in the access group."
        )

    print(f"  All {len(SCOPE_SECTIONS)} scope section(s) share the same shape.")
    return True


def test_assignment_lists_are_editable_and_gated():
    """These have never been editable from the server-rendered pane."""
    print("\nTesting the assignment lists...")

    cases = (
        (
            "file-sync-group-section",
            "file_sync_allowed_group_ids",
            "enable_file_sync_group",
            "require_group_assignment_for_file_sync",
        ),
        (
            "file-sync-public-section",
            "file_sync_allowed_public_workspace_ids",
            "enable_file_sync_public",
            "require_public_workspace_assignment_for_file_sync",
        ),
    )

    for section_id, key, capability, requirement in cases:
        field = field_in(section_id, key)
        assert field, f"{key} is not declared."
        assert field["type"] == "id_list", field["type"]
        assert field.get("search_endpoint"), (
            f"{key} has no search endpoint, so it could only be edited by typing "
            "opaque identifiers from memory."
        )
        assert field.get("results_key"), f"{key} does not say how to read the response."

        dependency = field["depends_on"]
        assert not evaluate(dependency, {capability: True}.get), (
            f"{key} shows while its restriction is off, where it has no effect."
        )
        assert evaluate(dependency, {capability: True, requirement: True}.get), (
            f"{key} stays hidden with the restriction on, so it could not be set."
        )
        assert not evaluate(dependency, {requirement: True}.get), (
            f"{key} shows while the whole scope is disabled."
        )

    print("  Both assignment lists are searchable and shown only where they apply.")
    return True


def test_assignment_lists_round_trip():
    """The stored shape is a JSON array, and V1 wrote it as a string."""
    print("\nTesting assignment list storage...")

    # Group ids are validated as canonical UUIDs by the shared normalizer, which
    # is what the server-rendered form stores, so anything else is dropped.
    group_a = "11111111-1111-1111-1111-111111111111"
    group_b = "22222222-2222-2222-2222-222222222222"

    normalized, errors, _ = normalize(
        {"file_sync_allowed_group_ids": [group_a, group_b, group_a]}, {}
    )
    assert not errors, errors
    assert normalized["file_sync_allowed_group_ids"] == [group_a, group_b], normalized

    dropped, errors, _ = normalize(
        {"file_sync_allowed_group_ids": ["not-a-uuid"]}, {}
    )
    assert not errors, errors
    assert dropped["file_sync_allowed_group_ids"] == [], (
        "A non-canonical group id should be dropped, matching what the "
        f"server-rendered form stores: {dropped}"
    )

    # Public workspace ids are not UUID-constrained, so they are only trimmed
    # and deduplicated. The picker holds records rather than bare ids.
    from_records, errors, _ = normalize(
        {
            "file_sync_allowed_public_workspace_ids": [
                {"id": "ws-1"},
                "ws-2",
                "ws-1",
            ]
        },
        {},
    )
    assert not errors, errors
    assert from_records["file_sync_allowed_public_workspace_ids"] == ["ws-1", "ws-2"], (
        from_records
    )

    # V1 stores this as a JSON string inside a hidden textarea, so a document
    # written by that form has to read back.
    from_string, errors, _ = normalize(
        {"file_sync_allowed_public_workspace_ids": '["ws-1", "ws-2"]'}, {}
    )
    assert not errors, errors
    assert from_string["file_sync_allowed_public_workspace_ids"] == ["ws-1", "ws-2"], (
        from_string
    )

    print("  Assignment lists validate group ids and accept both stored shapes.")
    return True


def test_unreleased_source_types_are_shown_disabled():
    """Omitting them would read as the connector having been removed."""
    print("\nTesting the source type options...")

    field = field_in("file-sync-source-types-section", "file_sync_visible_source_types")
    assert field, "file_sync_visible_source_types is not declared."
    assert field["type"] == "checkbox_set", field["type"]
    assert field.get("default") == ["smb", "azure_files"], field.get("default")

    options = {option["value"]: option for option in field["options"]}
    for value in ("smb", "azure_files", "azure_blob"):
        assert value in options, f"{value} is missing from the source type options."
        assert not options[value].get("disabled"), f"{value} should be selectable."

    for value in ("onedrive", "sharepoint_on_prem", "google_workspace"):
        assert value in options, f"{value} is missing from the source type options."
        assert options[value].get("disabled"), (
            f"{value} is not released yet and should be shown disabled rather than "
            "selectable."
        )
        assert options[value].get("description"), (
            f"{value} should say why it cannot be selected."
        )

    # Selecting nothing would leave the Add Source workflow with no options.
    assert field.get("min_selected") == 1, field.get("min_selected")
    _, errors, _ = normalize(
        {"file_sync_visible_source_types": []}, {"enable_file_sync": True}
    )
    assert "file_sync_visible_source_types" in errors, (
        "An empty source type selection was accepted, which leaves the Add Source "
        "workflow with nothing to offer."
    )

    print(f"  All {len(options)} source type(s) declared, three shown as coming soon.")
    return True


def test_every_v1_field_is_claimed():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that V1 File Sync fields are claimed...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    missing = sorted(pane_field_names() - claimed - documented)

    assert not missing, (
        "These fields exist in the server-rendered File Sync pane but are not "
        "described in admin_settings_fields.py:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(pane_field_names())} V1 field(s) are claimed.")
    return True


def test_the_schema_invents_nothing():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema invents no File Sync fields...")

    v1_names = pane_field_names()

    invented = []
    for section_id in FILE_SYNC_SECTIONS:
        for field in section_fields(section_id):
            key = field.get("key")
            if not key:
                continue
            legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
            if not any(name in v1_names for name in legacy):
                invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 pane:\n  "
        + "\n  ".join(invented)
    )

    print("  Every declared field maps back to a V1 field.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_tab_sections_match_navigation,
        test_the_redis_prerequisite_is_declared,
        test_the_per_run_size_limit_converts_between_gb_and_bytes,
        test_the_scope_sections_share_one_shape,
        test_assignment_lists_are_editable_and_gated,
        test_assignment_lists_round_trip,
        test_unreleased_source_types_are_shown_disabled,
        test_every_v1_field_is_claimed,
        test_the_schema_invents_nothing,
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
