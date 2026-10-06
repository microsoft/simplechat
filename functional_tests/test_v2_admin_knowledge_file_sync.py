# test_v2_admin_knowledge_file_sync.py
#!/usr/bin/env python3
"""
Functional test for the Knowledge group's File Sync tab in the V2 admin UI.
Version: 0.261.266
Implemented in: 0.261.084
Consolidated into one card in: 0.261.266

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

Everything File Sync governs is one card. It used to be five -- the switch with
its run limits, the source types, and a card per workspace type -- and nothing
tied a workspace type back to the switch it depends on. A workspace type is only
live while File Sync and its own switch are both on, so the type switches now
nest under File Sync, and each type's access rules sit in a panel anchored
beneath that type's switch. The structure is what these tests hold still: the
nesting is derived from declaration order and ``depends_on``, so a reordered or
under-gated field silently breaks it.
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

FILE_SYNC_SECTION = "file-sync-section"

FILE_SYNC_SECTIONS = (FILE_SYNC_SECTION,)

# The workspace type switches, in the order they nest under File Sync.
SCOPE_SWITCHES = (
    "enable_file_sync_personal",
    "enable_file_sync_group",
    "enable_file_sync_public",
)

RUN_LIMIT_KEYS = (
    "file_sync_max_sources_per_scope",
    "file_sync_min_schedule_interval_minutes",
    "file_sync_max_files_per_run",
    "file_sync_max_gb_per_run",
    "file_sync_max_concurrent_runs",
    "file_sync_allow_recursive_sources",
)

GIBIBYTE = 1073741824

fields_module = import_app_module("admin_settings_fields")
roles_module = import_app_module("admin_app_roles")
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


def group_of(field):
    """The field's group descriptor as a dict, whichever shape it was declared in."""
    group = field.get("group")
    if isinstance(group, str):
        return {"id": group, "label": group}
    return group or {}


def anchored_to(anchor):
    """The File Sync fields drawn in the panel beneath ``anchor``."""
    return [
        field
        for field in section_fields(FILE_SYNC_SECTION)
        if group_of(field).get("anchor") == anchor
    ]


def reader(**values):
    """A settings reader for ``evaluate_dependency``; unset keys read as None."""
    return values.get


def test_the_tab_is_one_card():
    """Five cards for one capability is what this layout replaces."""
    print("Testing the File Sync tab against ADMIN_NAV...")

    assert_app_version_at_least("0.261.266")

    nav_sections = tuple(
        section["id"]
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "file-sync"
        for section in tab["sections"]
    )

    assert nav_sections == FILE_SYNC_SECTIONS, (
        "The File Sync tab should be a single card, so the workspace types and "
        "source types read as part of File Sync rather than beside it.\n"
        f"  ADMIN_NAV: {list(nav_sections)}\n  test: {list(FILE_SYNC_SECTIONS)}"
    )
    assert section_fields(FILE_SYNC_SECTION), f"{FILE_SYNC_SECTION} declares no fields."

    # A field filed under a section the navigation no longer names is never drawn.
    stray = sorted(
        section_id
        for section_id in fields_module.get_admin_settings_fields()
        if section_id.startswith("file-sync") and section_id not in FILE_SYNC_SECTIONS
    )
    assert not stray, (
        f"These File Sync sections are declared but not in ADMIN_NAV, so their "
        f"fields would never render: {stray}"
    )

    print(f"  The tab is one card with {len(section_fields(FILE_SYNC_SECTION))} fields.")
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


def test_workspace_types_nest_under_file_sync():
    """A workspace type only works while File Sync is on, and should read that way."""
    print("\nTesting the workspace type switches...")

    fields = section_fields(FILE_SYNC_SECTION)
    keys = [field.get("key") for field in fields]

    capabilities = [field for field in fields if field.get("role") == "capability"]
    assert [field.get("key") for field in capabilities] == ["enable_file_sync"], (
        "Enable File Sync should be the card's only capability switch; a second one "
        f"would compete with it for the header: {[f.get('key') for f in capabilities]}"
    )
    assert keys[0] == "enable_file_sync", f"The card should open with its switch: {keys[:3]}"

    # deriveFieldHierarchy nests an uninterrupted run under a switch, so anything
    # declared between these would leave the switches after it un-nested.
    assert tuple(keys[1:4]) == SCOPE_SWITCHES, (
        "The workspace type switches must follow Enable File Sync directly and in "
        f"order, or they stop drawing as nested beneath it: {keys[1:4]}"
    )

    for key in SCOPE_SWITCHES:
        field = field_in(FILE_SYNC_SECTION, key)
        assert field["type"] == "switch", f"{key} should be a switch: {field['type']}"
        assert not field.get("group"), f"{key} should be ungrouped so it can nest."
        assert field.get("depends_on") == {"key": "enable_file_sync", "equals": True}, (
            f"{key} should appear only while File Sync is on, because "
            "functions_file_sync.py ignores it otherwise: "
            f"{field.get('depends_on')}"
        )
        assert evaluate(field["depends_on"], reader(enable_file_sync=True))
        assert not evaluate(field["depends_on"], reader(enable_file_sync=False))

    print(f"  {len(SCOPE_SWITCHES)} workspace type switch(es) nest under File Sync.")
    return True


def test_each_workspace_type_has_an_anchored_access_panel():
    """Access rules belong beside the switch they qualify, not at the foot of the card."""
    print("\nTesting the per-type Access panels...")

    group_ids = set()
    for scope in SCOPE_SWITCHES:
        panel = anchored_to(scope)
        assert panel, f"{scope} has no Access panel anchored beneath it."

        declared = {
            (group_of(field).get("id"), group_of(field).get("label"), group_of(field).get("variant"))
            for field in panel
        }
        assert len(declared) == 1, (
            f"Every field under {scope} should share one group descriptor, or the "
            f"panel splits: {sorted(declared)}"
        )
        group_id, label, variant = declared.pop()
        assert label == "Access" and variant == "access", (
            f"{scope}: expected an 'Access' panel with the access variant, got "
            f"{label!r} / {variant!r}."
        )
        assert group_id not in group_ids, f"{scope} reuses panel id {group_id!r}."
        group_ids.add(group_id)

        admin_only = [field for field in panel if field.get("key", "").endswith("_admin_only")]
        assert len(admin_only) == 1, (
            f"{scope} should offer one administrators-only control like the other "
            "workspace types."
        )

        # Visibility is not transitive in either renderer, so each field must carry
        # the File Sync condition itself or the panel outlives the switch above it.
        for field in panel:
            dependency = field.get("depends_on")
            key = field.get("key")
            assert not evaluate(dependency, reader(**{scope: True})), (
                f"{key} would stay visible with File Sync off."
            )
            assert not evaluate(dependency, reader(enable_file_sync=True)), (
                f"{key} would stay visible with {scope} off."
            )

    role = next(
        (
            requirement
            for requirement in roles_module.APP_ROLE_REQUIREMENTS
            if requirement["key"] == "file_sync_personal_require_app_role"
        ),
        None,
    )
    assert role, "The PersonalFileSyncUser requirement is missing from the registry."
    assert role["section_id"] == FILE_SYNC_SECTION, (
        "'Go to setting' for PersonalFileSyncUser should land on the File Sync card: "
        f"{role['section_id']!r}"
    )
    assert field_in(FILE_SYNC_SECTION, "file_sync_personal_require_app_role") in anchored_to(
        "enable_file_sync_personal"
    ), "The app role switch should sit in the Personal workspaces Access panel."

    print(f"  {len(group_ids)} Access panel(s), each anchored and gated by File Sync.")
    return True


def test_assignment_lists_are_editable_and_gated():
    """These have never been editable from the server-rendered pane."""
    print("\nTesting the assignment lists...")

    cases = (
        (
            "file_sync_allowed_group_ids",
            "enable_file_sync_group",
            "require_group_assignment_for_file_sync",
        ),
        (
            "file_sync_allowed_public_workspace_ids",
            "enable_file_sync_public",
            "require_public_workspace_assignment_for_file_sync",
        ),
    )

    for key, capability, requirement in cases:
        field = field_in(FILE_SYNC_SECTION, key)
        assert field, f"{key} is not declared."
        assert field["type"] == "id_list", field["type"]
        assert field.get("search_endpoint"), (
            f"{key} has no search endpoint, so it could only be edited by typing "
            "opaque identifiers from memory."
        )
        assert field.get("results_key"), f"{key} does not say how to read the response."

        dependency = field["depends_on"]
        assert not evaluate(
            dependency, reader(enable_file_sync=True, **{capability: True})
        ), f"{key} shows while its restriction is off, where it has no effect."
        assert evaluate(
            dependency,
            reader(enable_file_sync=True, **{capability: True, requirement: True}),
        ), f"{key} stays hidden with the restriction on, so it could not be set."
        assert not evaluate(
            dependency, reader(enable_file_sync=True, **{requirement: True})
        ), f"{key} shows while the whole workspace type is disabled."
        assert not evaluate(
            dependency, reader(**{capability: True, requirement: True})
        ), f"{key} shows while File Sync itself is off."

        # Sharing the restriction switch's panel is what nests the list beneath it.
        restriction = field_in(FILE_SYNC_SECTION, requirement)
        assert group_of(field) == group_of(restriction), (
            f"{key} should sit in the same Access panel as {requirement}, directly "
            "under the switch that reveals it."
        )
        assert group_of(field).get("anchor") == capability, (
            f"{key} should be in the panel anchored to {capability}."
        )

    print("  Both assignment lists are searchable and shown only where they apply.")
    return True


def test_assignment_lists_round_trip():
    """The stored shape is a JSON array, and V1 wrote it as a string."""
    print("\nTesting assignment list storage...")

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
    assert dropped["file_sync_allowed_group_ids"] == [], dropped

    # Public workspace identifiers are not UUID-constrained.
    from_records, errors, _ = normalize(
        {"file_sync_allowed_public_workspace_ids": [{"id": "ws-1"}, "ws-2", "ws-1"]}, {},
    )
    assert not errors, errors
    assert from_records["file_sync_allowed_public_workspace_ids"] == ["ws-1", "ws-2"], from_records

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


def test_run_limits_and_source_types_are_panels():
    """Both read as panels of the File Sync card, like Run limits always has."""
    print("\nTesting the Run limits and Source types panels...")

    for key in RUN_LIMIT_KEYS:
        field = field_in(FILE_SYNC_SECTION, key)
        assert field, f"{key} is not declared."
        group = group_of(field)
        assert (group.get("id"), group.get("label")) == ("limits", "Run limits"), (
            f"{key} should be in the Run limits panel: {group}"
        )
        assert not group.get("anchor"), f"{key}: Run limits apply to every workspace type."

    field = field_in(FILE_SYNC_SECTION, "file_sync_visible_source_types")
    assert field, "file_sync_visible_source_types is not declared."
    group = group_of(field)
    assert (group.get("id"), group.get("label")) == ("source-types", "Source types"), (
        f"Source types should be its own panel called 'Source types': {group}"
    )
    assert not group.get("anchor"), "Source types apply to every workspace type."
    assert field.get("depends_on") == {"key": "enable_file_sync", "equals": True}, (
        field.get("depends_on")
    )

    # The panel summarises its selection while closed, which only works while the
    # choice list is the panel's single field.
    in_panel = [
        other
        for other in section_fields(FILE_SYNC_SECTION)
        if group_of(other).get("id") == "source-types"
    ]
    assert in_panel == [field], (
        "Source types should hold only the choice list, so its closed header can "
        "say how many are selected."
    )

    print("  Run limits and Source types are panels shared by every workspace type.")
    return True


def test_unreleased_source_types_are_shown_disabled():
    """Omitting them would read as the connector having been removed."""
    print("\nTesting the source type options...")

    field = field_in(FILE_SYNC_SECTION, "file_sync_visible_source_types")
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
        test_the_tab_is_one_card,
        test_the_redis_prerequisite_is_declared,
        test_the_per_run_size_limit_converts_between_gb_and_bytes,
        test_workspace_types_nest_under_file_sync,
        test_each_workspace_type_has_an_anchored_access_panel,
        test_assignment_lists_are_editable_and_gated,
        test_assignment_lists_round_trip,
        test_run_limits_and_source_types_are_panels,
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
