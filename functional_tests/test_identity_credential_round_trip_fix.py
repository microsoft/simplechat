#!/usr/bin/env python3
# test_identity_credential_round_trip_fix.py
"""
Functional test for the workspace identity credential round trip fix.
Version: 0.261.169
Implemented in: 0.261.169

The V2 and classic group identity editors open a saved identity from its sanitized projection
and save back everything they show. That projection (``sanitize_workspace_identity``) left out
two non-secret identifiers: a service principal's ``tenant_id`` and a managed identity's
``managed_identity_client_id``. The V2 editor sent ``client_id: ""`` for every auth type but
client_secret, and the classic editor did the same; the server's normalizer keeps a stored
managed identity client ID only when the request leaves both ``managed_identity_client_id`` and
``client_id`` out, and a present-but-empty ``client_id`` cleared it. So any V2 or classic edit
of a managed identity erased its API-set user-assigned client ID, and the identity silently fell
back to the system-assigned managed identity on its next sign-in.

This is the identity twin of the file source fix (``test_file_source_credential_round_trip_fix``).
It runs the real native group identity routes and the real ``functions_workspace_identities``
through ``test_support/group_identity_harness.py``. It pins:
- the projection carries both identifiers, and still masks every secret;
- a V2 rename keeps the stored managed identity client ID;
- the classic editor's payload keeps the managed identity client ID too;
- a client_secret identity's tenant survives an edit (neither editor sends the key);
- a switch away from ``managed_identity`` drops the stored client ID, as the auth type changed.

The V2 body below is a port of ``draftFromIdentity`` followed by ``buildCredentialsWrite`` in
``application/v2_ui/src/lib/identityFields.ts``. ``ui_tests/test_v2_group_identities.py`` pins
that the real editor sends it.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_support.group_identity_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    PLACEHOLDER,
    as_user,
    environment,
    read_etag,
)
from test_support.versioning import assert_app_version_at_least


GROUP = "group-a"
TENANT = "11111111-2222-3333-4444-555555555555"
SP_CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MI_CLIENT = "99999999-8888-7777-6666-555555555555"


def create(env, credentials, *, name="Reusable credential", provider="generic"):
    as_user(env, "owner")
    response = env.client.post(LIST_PATH, json={
        "name": name, "provider": provider, "credentials": credentials,
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["identity"]


def read(env, identity_id):
    response = env.client.get(f"{LIST_PATH}/{identity_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["identity"]


def stored_auth(env, identity_id):
    return env.identities.get_workspace_identity("group", GROUP, identity_id)["auth"]


def managed_identity(env):
    return create(env, {"auth_type": "managed_identity", "managed_identity_client_id": MI_CLIENT})


def service_principal(env):
    return create(env, {
        "auth_type": "client_secret", "client_id": SP_CLIENT, "tenant_id": TENANT, "secret": "sp-secret-value",
    })


def v2_write(env, identity, **changes):
    """The body the V2 editor sends for a saved identity it opened, with only ``changes`` edited.

    A port of ``draftFromIdentity`` then ``buildIdentityWrite``/``buildCredentialsWrite``: the
    managed identity client ID rides in ``managed_identity_client_id`` (there is no visible field
    for it), a client_secret identity rides its client ID in ``identity``/``client_id`` and never
    sends a tenant, and the secret opens blank so it means "keep".
    """
    credentials = identity["credentials"]
    auth_type = credentials["auth_type"]
    uses_client_secret = auth_type == "client_secret"
    client_id = credentials.get("identity", "").strip() if uses_client_secret else ""
    inline = {
        "auth_type": auth_type,
        "username": credentials.get("username", "").strip(),
        "domain": credentials.get("domain", "").strip(),
        "identity": client_id,
        "client_id": client_id,
    }
    if auth_type == "managed_identity":
        inline["managed_identity_client_id"] = credentials.get("managed_identity_client_id", "").strip()
    if auth_type == "username_password":
        inline["password"] = ""
    else:
        inline["secret"] = ""
    body = {
        "expected_etag": read_etag(env, identity["id"]),
        "name": identity["name"],
        "description": identity.get("description", ""),
        "provider": identity.get("provider", "generic"),
        "source_type": identity.get("source_type", identity.get("provider", "generic")),
        "usage_contexts": list(identity.get("usage_contexts", ["action"])),
        "supported_source_types": list(identity.get("supported_source_types", [])),
        "credentials": inline,
    }
    body.update(changes)
    return body


def classic_write(env, identity, **changes):
    """The body the classic editor (``workspace-identities.js``) sends for a managed identity it
    opened and renamed: ``client_id`` is blank for every auth type but client_secret, and the
    stored ``managed_identity_client_id`` rides back for a managed identity."""
    credentials = identity["credentials"]
    body = {
        "expected_etag": read_etag(env, identity["id"]),
        "name": identity["name"],
        "description": identity.get("description", ""),
        "provider": identity.get("provider", "generic"),
        "source_type": identity.get("source_type", identity.get("provider", "generic")),
        "usage_contexts": list(identity.get("usage_contexts", ["action"])),
        "supported_source_types": list(identity.get("supported_source_types", [])),
        "credentials": {
            "auth_type": "managed_identity", "username": "", "domain": "",
            "identity": "", "client_id": "", "secret": "",
            "managed_identity_client_id": credentials.get("managed_identity_client_id", ""),
        },
    }
    body.update(changes)
    return body


def patch(env, identity_id, body):
    response = env.client.patch(f"{LIST_PATH}/{identity_id}", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["identity"]


def test_the_version_carries_the_fix():
    assert_app_version_at_least("0.261.165")


def test_the_projection_carries_the_tenant_and_the_managed_identity_client_id(environment):
    principal = read(environment, service_principal(environment)["id"])["credentials"]
    assert principal["tenant_id"] == TENANT
    assert principal["identity"] == SP_CLIENT
    assert principal["managed_identity_client_id"] == ""
    # Every secret stays masked: a placeholder and a stored flag, never the value.
    assert principal["secret_stored"] is True and principal["secret"] == PLACEHOLDER
    assert "sp-secret-value" not in str(principal)

    identity = read(environment, managed_identity(environment)["id"])["credentials"]
    assert identity["managed_identity_client_id"] == MI_CLIENT
    assert identity["identity"] == "" and identity["tenant_id"] == ""
    assert identity["secret_stored"] is False and identity["secret"] == ""


def test_a_v2_rename_keeps_the_managed_identity_client_id(environment):
    created = managed_identity(environment)
    renamed = patch(environment, created["id"], v2_write(
        environment, read(environment, created["id"]), name="Reusable credential (2024)",
    ))
    assert renamed["name"] == "Reusable credential (2024)"
    assert stored_auth(environment, created["id"])["managed_identity_client_id"] == MI_CLIENT


def test_the_classic_editor_keeps_the_managed_identity_client_id(environment):
    created = managed_identity(environment)
    patch(environment, created["id"], classic_write(
        environment, read(environment, created["id"]), name="Reusable credential (renamed)",
    ))
    assert stored_auth(environment, created["id"])["managed_identity_client_id"] == MI_CLIENT
    classic = (ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-identities.js")
    # The classic editor round-trips the stored managed identity client ID it opened with.
    assert "credentials.managed_identity_client_id" in classic.read_text(encoding="utf-8")


def test_a_v2_rename_keeps_the_service_principal_tenant(environment):
    created = service_principal(environment)
    patch(environment, created["id"], v2_write(
        environment, read(environment, created["id"]), name="Reusable credential (2024)",
    ))
    auth = stored_auth(environment, created["id"])
    # The editor sends no tenant field, so the normalizer keeps the stored one.
    assert auth["tenant_id"] == TENANT
    assert auth["identity"] == SP_CLIENT


def test_a_switch_away_from_managed_identity_drops_the_client_id(environment):
    """Saving a managed identity as an api_key drops its client ID: the auth type changed, and no
    visible field re-enters it. This documents the one path that still clears it."""
    created = managed_identity(environment)
    body = v2_write(environment, read(environment, created["id"]))
    body["credentials"] = {
        "auth_type": "api_key", "username": "", "domain": "",
        "identity": "", "client_id": "", "secret": "fresh-api-key",
    }
    patch(environment, created["id"], body)
    assert "managed_identity_client_id" not in stored_auth(environment, created["id"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
