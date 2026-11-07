#!/usr/bin/env python3
# test_group_details_payload_projection_fix.py
"""
Functional test for the group details payload projection fix.
Version: 0.261.143
Implemented in: 0.261.143

GET /api/groups/<group_id> returned the stored group document to every member.
That exposed the group's model endpoints, with their credentials inline when Key
Vault storage is off, along with pending join requests, the member list and Cosmos
system fields. This test ensures the route returns an allow-listed projection:
only the fields the classic group management page reads, plus the caller's role,
with the retention policy limited to Owners and Admins.
"""

import ast
import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP = os.path.join(ROOT_DIR, "application", "single_app")
GROUP_ROUTES_FILE = os.path.join(SINGLE_APP, "route_backend_groups.py")
BRANDING_FILE = os.path.join(SINGLE_APP, "functions_workspace_branding.py")
MANAGE_GROUP_JS = os.path.join(SINGLE_APP, "static", "js", "group", "manage_group.js")

SECRET = "sk-inline-plaintext-secret"
ALLOWED_KEYS = {
    "id", "name", "description", "owner", "admins", "documentManagers", "status",
    "createdDate", "modifiedDate", "heroColor", "disable_file_downloads",
    "file_downloads_admin_enabled", "file_downloads_enabled", "userRole",
    "hasLogo", "logoVersion",
}


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _load(path, names, namespace):
    tree = ast.parse(_read(path), filename=path)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == set(names), f"missing functions in {path}"
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), namespace)
    return namespace


def _function_source(path, name):
    source = _read(path)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found in {path}")


def _builder():
    branding = _load(BRANDING_FILE, {"normalize_workspace_hero_color", "get_workspace_logo_metadata"}, {
        "re": re,
        "DEFAULT_WORKSPACE_HERO_COLOR": "#0078d4",
        "WORKSPACE_HERO_COLOR_PATTERN": re.compile(r"^#(?:[0-9a-fA-F]{6})$"),
    })
    namespace = _load(GROUP_ROUTES_FILE, {"build_group_details_payload"}, {
        "GROUP_DETAILS_SETTINGS_ROLES": ("Owner", "Admin"),
        "DEFAULT_WORKSPACE_HERO_COLOR": "#0078d4",
        "normalize_workspace_hero_color": branding["normalize_workspace_hero_color"],
        "get_workspace_logo_metadata": branding["get_workspace_logo_metadata"],
        "is_group_workspace_file_download_admin_enabled": lambda settings, group: bool(settings.get("downloads_admin")),
        "is_group_workspace_file_download_enabled": lambda settings, group: bool(settings.get("downloads_admin"))
        and not group.get("disable_file_downloads"),
    })
    return namespace["build_group_details_payload"]


def _group_document():
    return {
        "id": "group-a",
        "name": "Research",
        "description": "Shared research",
        "heroColor": "#112233",
        "logoBase64": "aW1hZ2U=",
        "logoVersion": 3,
        "owner": {"id": "owner-1", "email": "owner@example.com", "displayName": "Owner"},
        "admins": ["admin-1"],
        "documentManagers": ["manager-1"],
        "users": [{"userId": "member-1", "email": "member@example.com", "displayName": "Member"}],
        "pendingUsers": [{"userId": "applicant-1", "email": "applicant@example.com", "displayName": "Applicant"}],
        "model_endpoints": [{
            "id": "ep-1",
            "provider": "aoai",
            "connection": {"endpoint": "https://contoso.openai.azure.com"},
            "auth": {"type": "api_key", "api_key": SECRET},
        }],
        "retention_policy": {"conversation_retention_days": 30, "document_retention_days": "default"},
        "statusHistory": [{"status": "active", "changed_by": "admin@example.com"}],
        "tag_definitions": {"finance": {"color": "#ff0000"}},
        "status": "active",
        "disable_file_downloads": False,
        "createdDate": "2026-01-01T00:00:00Z",
        "modifiedDate": "2026-01-02T00:00:00Z",
        "_rid": "rid", "_self": "self", "_etag": '"etag"', "_attachments": "attachments/", "_ts": 1,
    }


def test_member_payload_is_allow_listed():
    """An ordinary member sees only the allow-listed fields, never credentials."""
    print("Testing the member projection...")
    payload = _builder()(_group_document(), "User", {"downloads_admin": True})
    assert set(payload) == ALLOWED_KEYS, sorted(set(payload) ^ ALLOWED_KEYS)
    assert SECRET not in json.dumps(payload)
    assert payload["userRole"] == "User"
    assert payload["owner"] == {"id": "owner-1", "displayName": "Owner", "email": "owner@example.com"}
    assert payload["hasLogo"] is True and payload["logoVersion"] == 3
    assert payload["heroColor"] == "#112233"
    assert payload["file_downloads_admin_enabled"] is True and payload["file_downloads_enabled"] is True
    print("Member projection passed")
    return True


def test_settings_roles_also_get_the_retention_policy():
    """Owners and Admins, who manage retention, also receive the retention policy."""
    print("Testing the settings-role projection...")
    build = _builder()
    for role in ("Owner", "Admin"):
        payload = build(_group_document(), role, {})
        assert set(payload) == ALLOWED_KEYS | {"retention_policy"}, role
        assert payload["retention_policy"] == {"conversation_retention_days": 30, "document_retention_days": "default"}
        assert SECRET not in json.dumps(payload)
    manager = build(_group_document(), "DocumentManager", {})
    assert "retention_policy" not in manager
    print("Settings-role projection passed")
    return True


def test_route_returns_the_projection():
    """The details route returns the projection, never the stored document."""
    print("Testing the route wiring...")
    source = _function_source(GROUP_ROUTES_FILE, "api_get_group_details")
    assert "role = get_user_role_in_group(group_doc, user_id)" in source
    assert "You are not a member of this group" in source
    assert "build_group_details_payload(group_doc, role, get_settings())" in source
    assert "dict(group_doc)" not in source
    assert "jsonify(group_doc)" not in source
    print("Route wiring passed")
    return True


def test_manage_page_fields_are_all_projected():
    """Every field the classic management page reads is still in the projection."""
    print("Testing the classic management page contract...")
    script = _read(MANAGE_GROUP_JS)
    read_fields = set(re.findall(r"\b(?:group|groupData)\??\.(\w+)", script))
    projected = ALLOWED_KEYS | {"retention_policy"}
    assert read_fields, "no group fields found in manage_group.js"
    assert read_fields <= projected, sorted(read_fields - projected)
    print("Management page contract passed")
    return True


if __name__ == "__main__":
    tests = [
        test_member_payload_is_allow_listed,
        test_settings_roles_also_get_the_retention_policy,
        test_route_returns_the_projection,
        test_manage_page_fields_are_all_projected,
    ]
    results = [test() for test in tests]
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
