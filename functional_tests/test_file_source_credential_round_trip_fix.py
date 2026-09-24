#!/usr/bin/env python3
# test_file_source_credential_round_trip_fix.py
"""
Functional test for the file source credential round trip fix.
Version: 0.261.156
Implemented in: 0.261.156

The V2 group file source editor opens a saved source from its sanitized projection and saves
back everything it shows. That projection (``sanitize_file_sync_source``) left out two
non-secret identifiers: a service principal's ``tenant_id`` and a managed identity's
``managed_identity_client_id``. The editor therefore opened them blank and sent them back
blank. The server keeps a stored value only when the request leaves the key out; a
present-but-empty value clears it. So renaming a service principal source in V2 erased its
tenant, and its next sync signed in against the application's own tenant instead. The classic
editor never sends a tenant, but it reads ``managed_identity_client_id`` and sent it back
blank for the same reason.

This test runs the real native group file source routes and the real ``functions_file_sync``
through ``test_support/group_file_source_harness.py``. It pins:
- the projection carries both identifiers, and still masks every secret;
- a V2 rename keeps the stored tenant and the stored managed identity client ID;
- the classic editor's payload keeps the managed identity client ID too;
- an explicitly cleared tenant is still cleared, so a user can remove one;
- an identity-bound source projects the identity's own identifiers, as it already projected
  the identity's client ID.

The V2 bodies below are a port of ``draftFromSource`` followed by ``buildFileSourceWrite`` in
``application/v2_ui/src/lib/fileSourceFields.ts``. ``ui_tests/test_v2_group_file_sources.py``
pins that the real editor sends them.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_support.group_file_source_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    PLACEHOLDER,
    as_user,
    environment,
)
from test_support.versioning import assert_app_version_at_least


GROUP = "group-a"
ACCOUNT_URL = "https://contoso.file.core.windows.net"
TENANT = "11111111-2222-3333-4444-555555555555"
SP_CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MI_CLIENT = "99999999-8888-7777-6666-555555555555"


def azure_files_payload(name, credentials):
    return {
        "name": name,
        "source_type": "azure_files",
        "connection": {"account_url": ACCOUNT_URL, "share_name": "reports", "directory_path": "quarterly"},
        "credentials": credentials,
    }


def create(env, payload):
    as_user(env, "owner")
    response = env.client.post(LIST_PATH, json=payload)
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def read(env, source_id):
    response = env.client.get(f"{LIST_PATH}/{source_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def stored_auth(env, source_id):
    return env.sources_container.get(GROUP, source_id)["auth"]


def service_principal_source(env):
    return create(env, azure_files_payload("Finance share", {
        "auth_type": "client_secret", "client_id": SP_CLIENT, "tenant_id": TENANT, "secret": "sp-secret-value",
    }))


def managed_identity_source(env):
    return create(env, azure_files_payload("Archive share", {
        "auth_type": "managed_identity", "managed_identity_client_id": MI_CLIENT,
    }))


def v2_write(source, **changes):
    """The body the V2 editor sends for a saved source it opened, with only ``changes`` edited."""
    credentials = source["credentials"]
    auth_type = credentials["auth_type"]
    client_id = str(credentials.get("identity") or credentials.get("managed_identity_client_id") or "").strip()
    if auth_type == "managed_identity":
        inline = {"auth_type": auth_type, "managed_identity_client_id": client_id}
    elif auth_type == "client_secret":
        inline = {
            "auth_type": auth_type, "client_id": client_id, "identity": client_id,
            "tenant_id": str(credentials.get("tenant_id") or "").strip(), "secret": "",
        }
    else:
        raise AssertionError(f"Unexpected auth type for this test: {auth_type}")
    connection, filters, schedule = source["connection"], source["filters"], source["schedule"]
    body = {
        "expected_config_revision": source["config_revision"],
        "name": source["name"],
        "source_type": source["source_type"],
        "enabled": source["enabled"],
        "recursive": source["recursive"],
        "connection": {
            "account_url": connection["account_url"],
            "share_name": connection["share_name"],
            "directory_path": connection["directory_path"],
        },
        "filters": {
            "include_patterns": list(filters.get("include_patterns", [])),
            "exclude_patterns": list(filters.get("exclude_patterns", [])),
            "allowed_extensions": list(filters.get("allowed_extensions", [])),
        },
        "schedule": {"enabled": bool(schedule.get("enabled")), "interval_minutes": schedule.get("interval_minutes") or 60},
        "identity_id": "",
        "credentials": inline,
    }
    body.update(changes)
    return body


def classic_write(source, **changes):
    """The body the classic editor (``workspace-file-sync.js`` ``buildPayload``) sends for a
    managed identity source it opened and renamed."""
    credentials = source["credentials"]
    client_id = str(credentials.get("identity") or credentials.get("managed_identity_client_id") or "").strip()
    body = {
        "expected_config_revision": source["config_revision"],
        "name": source["name"],
        "source_type": source["source_type"],
        "connection": {
            "account_url": source["connection"]["account_url"],
            "share_name": source["connection"]["share_name"],
            "directory_path": source["connection"]["directory_path"],
        },
        "identity_id": "",
        "credentials": {
            "auth_type": "managed_identity", "username": "", "domain": "", "password": "", "secret": "",
            "client_secret": "", "connection_string": "", "identity": client_id, "client_id": client_id,
        },
    }
    body.update(changes)
    return body


def patch(env, source_id, body):
    response = env.client.patch(f"{LIST_PATH}/{source_id}", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def test_the_version_carries_the_fix():
    assert_app_version_at_least("0.261.156")


def test_the_projection_carries_the_tenant_and_the_managed_identity_client_id(environment):
    service_principal = read(environment, service_principal_source(environment)["id"])["credentials"]
    assert service_principal["tenant_id"] == TENANT
    assert service_principal["identity"] == SP_CLIENT
    assert service_principal["managed_identity_client_id"] == ""
    # Every secret stays masked: a placeholder and a stored flag, never the value.
    assert service_principal["secret_stored"] is True and service_principal["secret"] == PLACEHOLDER
    assert "sp-secret-value" not in str(service_principal)

    managed_identity = read(environment, managed_identity_source(environment)["id"])["credentials"]
    assert managed_identity["managed_identity_client_id"] == MI_CLIENT
    assert managed_identity["identity"] == "" and managed_identity["tenant_id"] == ""
    assert managed_identity["secret_stored"] is False and managed_identity["secret"] == ""


def test_a_v2_rename_keeps_the_service_principal_tenant(environment):
    created = service_principal_source(environment)
    secret_reference = stored_auth(environment, created["id"])["secret_secret_name"]
    renamed = patch(environment, created["id"], v2_write(read(environment, created["id"]), name="Finance share (2024)"))
    assert renamed["name"] == "Finance share (2024)"
    auth = stored_auth(environment, created["id"])
    assert auth["tenant_id"] == TENANT
    assert auth["identity"] == SP_CLIENT
    assert auth["secret_secret_name"] == secret_reference


def test_a_v2_rename_keeps_the_managed_identity_client_id(environment):
    created = managed_identity_source(environment)
    patch(environment, created["id"], v2_write(read(environment, created["id"]), name="Archive share (2024)"))
    assert stored_auth(environment, created["id"])["managed_identity_client_id"] == MI_CLIENT


def test_the_classic_editor_keeps_the_managed_identity_client_id(environment):
    created = managed_identity_source(environment)
    patch(environment, created["id"], classic_write(read(environment, created["id"]), name="Archive share (renamed)"))
    assert stored_auth(environment, created["id"])["managed_identity_client_id"] == MI_CLIENT
    classic = (ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-file-sync.js")
    # The classic editor prefills its client ID from the projected managed identity client ID.
    assert "source.credentials?.managed_identity_client_id" in classic.read_text(encoding="utf-8")


def test_an_explicitly_cleared_tenant_is_still_cleared(environment):
    created = service_principal_source(environment)
    source = read(environment, created["id"])
    body = v2_write(source)
    body["credentials"]["tenant_id"] = ""
    patch(environment, created["id"], body)
    assert "tenant_id" not in stored_auth(environment, created["id"])


def test_an_identity_bound_source_projects_the_identity_identifiers(environment):
    environment.identities._get_identities_container("group").seed({
        "id": "archive-identity", "group_id": GROUP, "scope_type": "group", "name": "Archive identity",
        "provider": "generic", "usage_contexts": ["file_sync"], "supported_source_types": ["azure_files"],
        "auth": {"auth_type": "managed_identity", "managed_identity_client_id": MI_CLIENT},
    })
    created = create(environment, {
        "name": "Archive via identity", "source_type": "azure_files", "identity_id": "archive-identity",
        "connection": {"account_url": ACCOUNT_URL, "share_name": "archive", "directory_path": ""},
    })
    credentials = read(environment, created["id"])["credentials"]
    assert credentials["auth_type"] == "managed_identity"
    assert credentials["managed_identity_client_id"] == MI_CLIENT


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
