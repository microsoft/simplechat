#!/usr/bin/env python3
# test_v2_admin_governance_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings governance group.
Version: 0.261.273
Implemented in: 0.261.273

Before this, the V2 admin page had no governance section at all. One switch, MCP
destination governance, surfaced through the generic fallback as "Mcp destination
governance", and the feature policies, delegated item policies, MCP destination
policies, and inbound MCP source policies could only be managed on the
server-rendered page.

The V2 group is declared in the schema and backed by the existing governance API,
with a few additions. The ways it can go wrong are quiet ones:

* A V1 governance field with no V2 equivalent simply disappears from the new page.
* The server-rendered save writes a governance audit entry whenever a governance
  switch changes. The V2 page saves through the settings PATCH, so without its own
  audit write a governance change made there would leave no record.
* The server-rendered save clears a governance switch whose feature is off. V2
  deliberately keeps it, so turning a feature off and on again cannot silently drop
  governance, and says the switch is waiting instead. Coercing here would undo that.
* The review list now takes several entity types and one exact item. A misspelled
  type that was ignored would answer with every policy, so it is refused.
* ``transport:streamable-http``, which the classic examples suggested, never matches,
  because transports are stored with an underscore. The V2 editor flags it, and the
  server check below is why.

The behavioural half of the editors lives in ``lib/governance.ts`` and is executed by
the companion TypeScript checks this file bundles and runs.
"""

import ast
import importlib
import json
import os
import re
import subprocess
import sys
import types
from contextlib import ExitStack, contextmanager
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import patch

import werkzeug

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_governance_logic.ts"

GOVERNANCE_SECTIONS = (
    "governance-feature-toggles-section",
    "governance-feature-policies-section",
    "governance-item-policies-section",
    "governance-mcp-destination-section",
    "governance-inbound-mcp-section",
)
GOVERNANCE_PANES = ("feature-governance.html", "governance-policies.html", "mcp-governance.html")
TOGGLES_SECTION = "governance-feature-toggles-section"

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

fields_module = import_app_module("admin_settings_fields")


def read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def all_fields():
    return fields_module.get_admin_settings_fields()


def nav_sections():
    return {
        section["id"]: (group["id"], tab["id"])
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }


def declared_keys():
    return {
        field["key"]: section_id
        for section_id, fields in all_fields().items()
        for field in fields
        if field.get("key")
    }


def governance_switches():
    return [field for field in all_fields()[TOGGLES_SECTION] if field.get("type") == "switch"]


def audited_setting_keys():
    """Read GOVERNANCE_AUDITED_SETTING_KEYS without importing functions_governance.

    That module builds Cosmos containers through config at import, so the tuple is read
    from its source, which is exactly what the V2 PATCH imports.
    """
    tree = ast.parse(read(APP_ROOT / "functions_governance.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GOVERNANCE_AUDITED_SETTING_KEYS"
            for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("GOVERNANCE_AUDITED_SETTING_KEYS is no longer defined")


def test_every_governance_section_is_declared():
    """An undeclared section falls back to guessing a switch from the key name."""
    print("Testing the governance section declarations...")

    assert_app_version_at_least("0.261.273")

    group = next((group for group in ADMIN_NAV if group["id"] == "governance"), None)
    assert group, "ADMIN_NAV no longer defines a governance group."
    sections = [section["id"] for tab in group["tabs"] for section in tab["sections"]]
    assert sorted(sections) == sorted(GOVERNANCE_SECTIONS), (
        f"The governance group's sections changed: {sections}"
    )

    fields = all_fields()
    empty = [section_id for section_id in GOVERNANCE_SECTIONS if not fields.get(section_id)]
    assert not empty, f"These governance sections declare nothing: {empty}"

    destination = {
        field.get("key"): field for field in fields["governance-mcp-destination-section"]
    }["enable_mcp_destination_governance"]
    assert destination["label"] == "Enforce MCP Destination Allowlist", (
        "The MCP destination switch is back to a fallback label."
    )
    assert destination.get("role") == "capability"

    print(f"  {len(GOVERNANCE_SECTIONS)} governance sections are declared.")
    return True


def test_every_governance_pane_field_is_claimed_by_the_schema():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 governance field is claimed...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)
    keys = declared_keys()

    names = set()
    for pane in GOVERNANCE_PANES:
        names |= {
            name
            for name in FIELD_NAME_RE.findall(read(PANES_DIR / pane))
            if not JINJA_RE.search(name)
        }

    missing = sorted(names - claimed - documented)
    assert not missing, (
        "These V1 governance fields have no V2 equivalent and no recorded reason:\n  "
        + "\n  ".join(missing)
    )

    misplaced = sorted(
        name for name in names
        if name in keys and not keys[name].startswith("governance-")
    )
    assert not misplaced, (
        f"These governance settings are declared outside the governance group: {misplaced}"
    )

    print(f"  All {len(names)} V1 governance field name(s) are claimed.")
    return True


def test_governance_switches_are_kept_while_their_feature_is_off():
    """Fail-closed: a switch keeps its value and says it is waiting."""
    print("\nTesting governance prerequisites...")

    keys = declared_keys()
    sections = nav_sections()

    for field in governance_switches():
        if field.get("readonly"):
            continue
        requirement = field.get("requires")
        assert requirement, f"{field['key']} does not say which feature it governs."
        assert requirement.get("mode") == "warn", (
            f"{field['key']} must warn rather than block. Blocking would hide or disable "
            "a governance switch whenever its feature is off, which is the coercion V2 avoids."
        )
        assert requirement["key"] in keys, f"{field['key']} waits on an undeclared key."
        target = requirement.get("target_section")
        assert target in sections, f"{field['key']} links to an unknown section {target!r}."
        assert keys[requirement["key"]] == target, (
            f"{field['key']} links to {target}, but {requirement['key']} is declared in "
            f"{keys[requirement['key']]}, so the link would land on the wrong card."
        )

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"governance_group_agents": True}, {"allow_group_agents": False}
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert normalized == {"governance_group_agents": True}, (
        "A governance switch was changed or refused because its feature is off."
    )

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"allow_group_agents": False}, {"governance_group_agents": True}
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert "governance_group_agents" not in normalized, (
        "Turning a feature off cleared the governance configured for it."
    )

    print("  Each switch warns, links to its feature, and is never coerced.")
    return True


def test_global_endpoint_governance_cannot_be_turned_off():
    """The runtime always enforces it, so a switch could only mislead."""
    print("\nTesting the always-enforced global endpoint switch...")

    field = next(
        field for field in governance_switches() if field["key"] == "governance_global_endpoints"
    )
    assert field.get("readonly") is True and field.get("managed_by"), (
        "governance_global_endpoints must be reported as managed, not offered."
    )

    normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"governance_global_endpoints": False}, {}
    )
    assert not normalized and "governance_global_endpoints" in errors, (
        "A PATCH was able to turn global endpoint governance off."
    )

    print("  The switch is read-only and a write is refused.")
    return True


def _load_audit_helper(namespace):
    source = read(APP_ROOT / "route_backend_v2.py")
    tree = ast.parse(source)
    node = next(
        (
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_log_governance_setting_changes"
        ),
        None,
    )
    assert node, "_log_governance_setting_changes is no longer a module-level helper."
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, "route_backend_v2.py", "exec"), namespace)
    return namespace["_log_governance_setting_changes"]


def test_v2_saves_are_audited_like_classic_saves():
    """A governance change made in V2 must leave the same record as one made in V1."""
    print("\nTesting governance audit records for V2 saves...")

    classic = read(APP_ROOT / "route_frontend_admin_settings.py")
    match = re.search(r"governance_toggle_keys = \[(.*?)\]", classic, re.DOTALL)
    assert match, "Could not read the classic save's governance_toggle_keys."
    classic_keys = tuple(re.findall(r"'([a-z_]+)'", match.group(1)))
    audited = audited_setting_keys()
    assert audited == classic_keys, (
        "V1 and V2 audit different governance settings:\n"
        f"  V1: {classic_keys}\n  V2: {audited}"
    )

    calls = []
    logged = []

    def record_change(**payload):
        calls.append(payload)

    namespace = {
        "GOVERNANCE_AUDITED_SETTING_KEYS": audited,
        "log_governance_change": record_change,
        "get_current_user_info": lambda: {"email": "admin@contoso.com"},
        "get_current_user_id": lambda: "admin-1",
        "log_event": lambda *args, **kwargs: logged.append((args, kwargs)),
        "logging": __import__("logging"),
    }
    helper = _load_audit_helper(namespace)

    helper({"governance_user_agents": False}, {"governance_user_agents": True, "show_logo": True})
    assert len(calls) == 1, f"Expected one audit entry, got {len(calls)}."
    entry = calls[0]
    assert entry["action"] == "governance_feature_toggles_updated"
    assert entry["scope"] == "feature_policy"
    assert entry["target_id"] == "governance_feature_toggles"
    assert entry["admin_user_id"] == "admin-1" and entry["admin_email"] == "admin@contoso.com"
    assert entry["change_details"] == {
        "changed_toggles": {"governance_user_agents": {"before": False, "after": True}}
    }
    assert set(entry["before_state"]) == set(audited) == set(entry["after_state"])
    assert entry["after_state"]["governance_user_agents"] is True

    calls.clear()
    helper({"governance_user_agents": True}, {"governance_user_agents": True, "show_logo": False})
    helper({}, {"allow_group_agents": False})
    assert not calls, "An unchanged or non-governance save wrote a governance audit entry."

    def failing_change(**payload):
        raise RuntimeError("activity log unavailable")

    namespace["log_governance_change"] = failing_change
    helper = _load_audit_helper(namespace)
    helper({}, {"enable_mcp_destination_governance": True})
    assert logged, "A failed audit write was swallowed without being reported."

    patch_source = read(APP_ROOT / "route_backend_v2.py")
    body = re.search(
        r"\n    def v2_admin_patch_settings\(\):(.*?)(?=\n    @bp\.route\(|\Z)",
        patch_source,
        re.DOTALL,
    )
    assert body, "Could not find the V2 settings PATCH handler."
    persisted = body.group(1).find("if not update_settings(normalized):")
    audited_at = body.group(1).find("_log_governance_setting_changes(current_settings, normalized)")
    assert 0 <= persisted < audited_at, (
        "The PATCH handler must write the audit entry after the settings are saved, so "
        "a failed save is not recorded as a change."
    )

    print(f"  {len(audited)} setting(s) audited, matching the classic save.")
    return True


def _is_app_module(module):
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        return Path(module_file).resolve().is_relative_to(APP_ROOT.resolve())
    except (OSError, ValueError):
        return False


@contextmanager
def _isolated_modules(stubs, fresh=()):
    """Install stand-in modules and import ``fresh`` against them, then put everything back.

    Application modules imported while the stubs are installed are dropped afterwards,
    so a later test in the same process is never served a copy wired to these stubs.
    """
    tracked = set(stubs) | set(fresh)
    originals = {name: sys.modules[name] for name in tracked if name in sys.modules}
    before = set(sys.modules)
    for name in fresh:
        sys.modules.pop(name, None)
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name in list(sys.modules):
            imported_here = name not in before and _is_app_module(sys.modules[name])
            if name in tracked or imported_here:
                sys.modules.pop(name, None)
        sys.modules.update(originals)


def _module(name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return module


ITEM_POLICIES = [
    {"entity_type": "mcp_personal_destination", "item_id": "preconfiguration:microsoft_learn", "policy_id": "p-learn", "policy_name": "Learn"},
    {"entity_type": "mcp_group_destination", "item_id": "group:g-1::*.contoso.com", "policy_id": "p-group", "policy_name": "Contoso for one group"},
    {"entity_type": "mcp_global_destination", "item_id": "*", "policy_id": "p-global", "policy_name": "Everything published"},
    {"entity_type": "global_endpoint", "item_id": "conn-1", "policy_id": "p-research", "policy_name": "Primary for research"},
    {"entity_type": "global_endpoint", "item_id": "conn-1", "policy_id": "p-ops", "policy_name": "Primary for operations"},
    {"entity_type": "global_endpoint", "item_id": "conn-10", "policy_id": "p-other", "policy_name": "Another connection"},
]

GROUPS = {"g-1": {"id": "g-1", "name": "Research", "description": "Research team", "member_count": 4}}
PUBLIC_WORKSPACES = {"pw-1": {"id": "pw-1", "name": "Handbook", "description": "", "member_count": "n/a"}}


@contextmanager
def governance_client():
    """A Flask client for the real governance blueprint over in-memory data."""
    from flask import Blueprint, Flask

    directory_calls = []

    def search_rows(rows, search_query, limit):
        directory_calls.append((search_query, limit))
        needle = str(search_query or "").lower()
        matched = [row for row in rows.values() if needle in row["name"].lower() or needle in row["id"]]
        return matched[:limit], len(matched) > limit

    identity = lambda function: function  # noqa: E731
    stubs = {
        "config": _module(
            "config",
            cosmos_governance_item_policies_container=object(),
            cosmos_governance_policies_container=object(),
        ),
        "functions_activity_logging": _module(
            "functions_activity_logging", log_governance_change=lambda **payload: None
        ),
        "functions_appinsights": _module(
            "functions_appinsights",
            log_event=lambda *args, **kwargs: None,
            debug_print=lambda *args, **kwargs: None,
        ),
        "functions_settings": _module("functions_settings", get_settings=lambda: {}),
        "functions_authentication": _module(
            "functions_authentication",
            admin_required=identity,
            login_required=identity,
            get_current_user_id=lambda: "admin-1",
        ),
        "swagger_wrapper": _module(
            "swagger_wrapper",
            swagger_route=lambda **kwargs: identity,
            get_auth_security=lambda: [],
        ),
        "functions_group": _module(
            "functions_group",
            get_user_groups=lambda user_id: [],
            find_groups_by_ids=lambda ids: [GROUPS[group_id] for group_id in ids if group_id in GROUPS],
            list_groups_for_admin_directory=lambda search_query="", limit=25: search_rows(GROUPS, search_query, limit),
        ),
        "functions_public_workspaces": _module(
            "functions_public_workspaces",
            get_user_public_workspaces=lambda user_id: [],
            find_public_workspaces_by_ids=lambda ids: [
                PUBLIC_WORKSPACES[workspace_id] for workspace_id in ids if workspace_id in PUBLIC_WORKSPACES
            ],
            list_public_workspaces_for_admin_directory=lambda search_query="", limit=25: search_rows(
                PUBLIC_WORKSPACES, search_query, limit
            ),
        ),
        "functions_mcp_preconfigurations": _module(
            "functions_mcp_preconfigurations",
            build_mcp_preconfiguration_policy_catalog=lambda: [{"id": "microsoft_learn", "label": "Microsoft Learn"}],
        ),
        "functions_mcp_presets": _module(
            "functions_mcp_presets",
            load_mcp_server_presets=lambda: [{"id": "generic", "displayName": "Generic"}, {"id": ""}],
        ),
    }

    with _isolated_modules(stubs, fresh=("functions_governance", "route_backend_governance")):
        governance = importlib.import_module("functions_governance")

        def list_item_policies(entity_type=None):
            return sorted(
                (dict(row) for row in ITEM_POLICIES if entity_type in (None, row["entity_type"])),
                key=governance._item_policy_list_sort_key,
            )

        governance.list_item_policies = list_item_policies
        routes = importlib.import_module("route_backend_governance")

        app = Flask(__name__)
        app.secret_key = "governance-parity"
        blueprint = Blueprint("governance_parity", __name__)
        routes.register_route_backend_governance(blueprint)
        app.register_blueprint(blueprint)
        # Flask's test client reads werkzeug.__version__, which newer werkzeug releases
        # no longer define; patched only for the life of this client.
        with ExitStack() as stack:
            if not hasattr(werkzeug, "__version__"):
                stack.enter_context(
                    patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True)
                )
            yield app.test_client(), directory_calls


def review(client, query):
    response = client.get(f"/api/admin/governance/item-policies/review?{query}")
    return response.status_code, response.get_json()


def test_review_list_takes_several_types_and_one_item():
    """Embedded lists ask for several scopes, or one resource, in a single request."""
    print("\nTesting the delegated item policy review filters...")

    with governance_client() as (client, _calls):
        status, payload = review(
            client,
            "entity_type=mcp_personal_destination,mcp_group_destination,mcp_global_destination",
        )
        assert status == 200, payload
        assert {row["policy_id"] for row in payload["item_policies"]} == {"p-learn", "p-group", "p-global"}
        assert payload["entity_types"] == [
            "mcp_personal_destination",
            "mcp_group_destination",
            "mcp_global_destination",
        ]

        status, payload = review(client, "entity_type=endpoint&item_id=conn-1")
        assert status == 200, payload
        assert sorted(row["policy_id"] for row in payload["item_policies"]) == ["p-ops", "p-research"], (
            "The item filter must match the stored id exactly; conn-10 is a different connection."
        )
        assert payload["entity_types"] == ["global_endpoint"], "The legacy endpoint alias stopped resolving."
        assert payload["item_id"] == "conn-1"

        status, payload = review(client, "entity_type=mcp_personal_destination,mcp_destination")
        assert status == 400, "A misspelled type was ignored, which answers with the wrong policies."

        status, payload = review(client, "per_page=2&page=2")
        assert status == 200 and payload["pagination"]["total_items"] == len(ITEM_POLICIES)
        assert len(payload["item_policies"]) == 2 and payload["entity_types"] == []

    print("  Several types, one exact item, aliases, and unknown types behave as intended.")
    return True


def test_principal_group_directory_covers_groups_and_public_workspaces():
    """A user's governance groups come from both kinds of membership."""
    print("\nTesting the governance group directory...")

    with governance_client() as (client, calls):
        response = client.get("/api/admin/governance/principal-groups?ids=pw-1,g-1,gone,g-1")
        assert response.status_code == 200
        groups = response.get_json()["groups"]
        assert [(row["id"], row["kind"]) for row in groups] == [
            ("pw-1", "public_workspace"),
            ("g-1", "group"),
        ], "Resolved ids must keep the requested order, drop repeats, and omit deleted ids."
        assert groups[1]["member_count"] == 4 and groups[0]["member_count"] is None

        response = client.get("/api/admin/governance/principal-groups?search=")
        payload = response.get_json()
        assert [row["name"] for row in payload["groups"]] == ["Handbook", "Research"]
        assert payload["truncated"] is False
        assert all(limit == 25 for _query, limit in calls), "Each kind is searched with its own limit."

        too_many = ",".join(f"id-{index}" for index in range(101))
        response = client.get(f"/api/admin/governance/principal-groups?ids={too_many}")
        assert response.status_code == 400, "Resolving ids is not bounded."

    print("  Groups and public workspaces resolve and search together, within limits.")
    return True


def test_destination_catalog_route_lists_what_a_policy_can_name():
    """The pattern builder offers ids and transports instead of free text."""
    print("\nTesting the MCP destination catalog route...")

    with governance_client() as (client, _calls):
        response = client.get("/api/admin/governance/mcp-destination-catalog")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["preconfigurations"] == [{"id": "microsoft_learn", "label": "Microsoft Learn"}]
    assert payload["presets"] == [{"id": "generic", "label": "Generic"}], "A preset without an id was offered."
    assert payload["transports"] == ["sse", "streamable_http", "websocket"]

    print(f"  Transports offered: {', '.join(payload['transports'])}.")
    return True


def test_new_governance_routes_are_admin_guarded():
    """Both routes read directory or catalog data an ordinary user should not."""
    print("\nTesting governance route guards...")

    source = read(APP_ROOT / "route_backend_governance.py")
    for path, function in (
        ("/api/admin/governance/principal-groups", "get_governance_principal_groups_route"),
        ("/api/admin/governance/mcp-destination-catalog", "get_governance_mcp_destination_catalog_route"),
    ):
        match = re.search(
            rf"@bp\.route\('{re.escape(path)}', methods=\['GET'\]\)(.*?)\n    def {function}\(",
            source,
            re.DOTALL,
        )
        assert match, f"{path} is not registered as a GET route on the governance blueprint."
        decorators = match.group(1)
        for decorator in ("@swagger_route(security=get_auth_security())", "@login_required", "@admin_required"):
            assert decorator in decorators, f"{path} is missing {decorator}."

    print("  Both routes are documented and require the Admin role.")
    return True


def test_destination_catalog_describes_templates_without_endpoints():
    """Endpoints in shipped definitions are placeholders, not something to allow."""
    print("\nTesting the MCP preconfiguration policy catalog...")

    from functions_mcp_preconfigurations import build_mcp_preconfiguration_policy_catalog

    catalog = build_mcp_preconfiguration_policy_catalog()
    assert catalog, "No preconfigurations were found to describe."
    expected_keys = {
        "id",
        "label",
        "catalog_tier",
        "scopes",
        "requires_explicit_policy",
        "requires_endpoint_review",
    }
    for entry in catalog:
        assert set(entry) == expected_keys, f"Unexpected catalog fields: {sorted(entry)}"
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", entry["id"]), entry["id"]
        assert set(entry["scopes"]) <= {"personal", "group", "global"}, entry["scopes"]

    print(f"  {len(catalog)} template(s) described by id, scope, and review needs.")
    return True


def test_the_hyphenated_transport_never_matches_on_the_server():
    """Why the V2 pattern builder refuses ``transport:streamable-http``."""
    print("\nTesting transport pattern matching...")

    import functions_mcp_destinations as destinations

    descriptor = {"transport": "streamable_http"}
    assert not destinations._pattern_matches_destination("transport:streamable-http", descriptor), (
        "The hyphenated transport now matches. The V2 check that refuses it can be relaxed."
    )
    assert destinations._pattern_matches_destination("transport:streamable_http", descriptor)

    print("  Only the underscore form matches, as the V2 editor requires.")
    return True


def test_deployment_floor_is_reported_without_its_patterns():
    """An administrator needs to know a floor exists, not to read it back out."""
    print("\nTesting the deployment destination readout...")

    import functions_mcp_destinations as destinations

    names = (
        destinations.ENABLE_MCP_DESTINATION_GOVERNANCE_ENV,
        destinations.MCP_BLOCK_UNSAFE_DESTINATIONS_ENV,
        destinations.MCP_ALLOWED_DESTINATIONS_ENV,
        destinations.MCP_ALLOWED_GROUP_DESTINATIONS_ENV,
    )
    saved = {name: os.environ.get(name) for name in names}
    try:
        os.environ[destinations.ENABLE_MCP_DESTINATION_GOVERNANCE_ENV] = "true"
        os.environ[destinations.MCP_BLOCK_UNSAFE_DESTINATIONS_ENV] = "false"
        os.environ[destinations.MCP_ALLOWED_DESTINATIONS_ENV] = "secret-host.contoso.com"
        os.environ[destinations.MCP_ALLOWED_GROUP_DESTINATIONS_ENV] = "a.contoso.com,b.contoso.com"
        floor = destinations.describe_mcp_destination_environment_policy()
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    assert floor == {
        "enforcement_required": True,
        "unsafe_blocking_required": False,
        "allowed_pattern_count": 3,
    }, floor
    assert "contoso" not in json.dumps(floor), "The readout leaked a deployment pattern."

    status_fields = [
        field for field in all_fields()["governance-mcp-destination-section"]
        if field.get("type") == "status"
    ]
    assert [field.get("status_source") for field in status_fields] == ["mcp_destination_environment_policy"]
    assert 'readouts["mcp_destination_environment_policy"]' in read(APP_ROOT / "route_backend_v2.py"), (
        "The status field reads a readout the settings API no longer sends."
    )

    print("  Booleans and a count only, wired to the section's status field.")
    return True


def test_feature_settings_link_to_the_governance_that_applies_to_them():
    """Each related link must land on a real governance switch."""
    print("\nTesting related settings links...")

    governance_fields = {
        field["key"]: field
        for section_id in GOVERNANCE_SECTIONS
        for field in all_fields()[section_id]
        if field.get("key")
    }
    linked = {}
    for section_id, fields in all_fields().items():
        for field in fields:
            for related in field.get("related_settings") or []:
                key = related.get("key")
                assert key in governance_fields, (
                    f"{field.get('key')} links to {key!r}, which is not a governance setting."
                )
                assert related.get("label") == governance_fields[key]["label"], (
                    f"{field.get('key')} labels its link {related.get('label')!r}, but the "
                    f"setting is called {governance_fields[key]['label']!r}."
                )
                linked.setdefault(key, []).append(field.get("key"))

    unlinked = sorted(
        field["key"]
        for field in governance_switches()
        if not field.get("readonly") and field["key"] not in linked
    )
    assert not unlinked, f"These governance switches are not linked from their feature: {unlinked}"

    print(f"  {sum(len(sources) for sources in linked.values())} link(s) resolve to governance switches.")
    return True


def test_inbound_shortcut_is_offered_only_with_inbound_mcp():
    """The shortcut is pointless, and confusing, where inbound MCP cannot be enabled."""
    print("\nTesting the Inbound MCP governance shortcut...")

    shortcut = next(
        (
            field for field in all_fields()["inbound-mcp-configuration"]
            if field.get("component") == "inbound-mcp-governance-shortcut"
        ),
        None,
    )
    assert shortcut, "The Inbound MCP tab no longer links to its source governance."
    flags = {
        (dependency.get("flag"), dependency.get("equals"))
        for dependency in fields_module.iter_field_dependencies(shortcut)
        if dependency.get("flag")
    }
    assert ("mcp_ui_enabled", True) in flags

    print("  The shortcut is gated on the inbound MCP runtime flag.")
    return True


def schema_expectations():
    """Each governance switch's prerequisite, for the TypeScript enforcement check."""
    expectations = {}
    for field in governance_switches():
        requirement = field.get("requires")
        expectations[field["key"]] = (
            None
            if field.get("readonly")
            else {"key": requirement["key"], "section": requirement["target_section"]}
        )
    return expectations


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting governance editor logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-governance-check.mjs"
    environment = dict(os.environ, GOVERNANCE_SCHEMA_EXPECTATIONS=json.dumps(schema_expectations()))
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # apiClient reads import.meta.env defensively; the define keeps this
                # identical to the other logic-check runners.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            env=environment,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_every_governance_section_is_declared,
        test_every_governance_pane_field_is_claimed_by_the_schema,
        test_governance_switches_are_kept_while_their_feature_is_off,
        test_global_endpoint_governance_cannot_be_turned_off,
        test_v2_saves_are_audited_like_classic_saves,
        test_review_list_takes_several_types_and_one_item,
        test_principal_group_directory_covers_groups_and_public_workspaces,
        test_destination_catalog_route_lists_what_a_policy_can_name,
        test_new_governance_routes_are_admin_guarded,
        test_destination_catalog_describes_templates_without_endpoints,
        test_the_hyphenated_transport_never_matches_on_the_server,
        test_deployment_floor_is_reported_without_its_patterns,
        test_feature_settings_link_to_the_governance_that_applies_to_them,
        test_inbound_shortcut_is_offered_only_with_inbound_mcp,
        test_the_typescript_logic_checks_pass,
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
