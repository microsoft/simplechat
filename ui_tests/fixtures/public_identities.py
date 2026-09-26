# public_identities.py
"""
Closed M10B public identity HTTP fixtures for the real production V2 SPA.
Version: 0.261.179
Implemented in: 0.261.179

The fixture serves the immutable `/api/public-workspaces/<workspace_id>/identities[...]` family and
injects the `identity_management` context hint that gates create, and the per-row `identity_actions`
projection that gates edit and delete. It mirrors the group M5A identity fixture
(`ui_tests/fixtures/group_identities.py`) for public scope: identities are a manager-only surface
for reads and writes, so an ordinary `User` workspace's section is unavailable and every identity
route answers 403; it never falls back to personal or group behaviour. Writes carry `expected_etag`
in the JSON body, secrets stay masked server-side, and every returned identity identifies the
requested workspace with `public_workspace_id` exactly as the reader validates.

pub-a is a manager workspace carrying three identities: a fully editable one whose stored secret
proves masking survives a rename, a withheld one whose empty `identity_actions` hides edit and delete
beside the editable control, and one still referenced by a File Sync source so a delete returns the
in-use 409 with its references. pub-b is an ordinary reader: identities are manager-only, so its
section is unavailable and its identity routes answer 403.
"""

import copy
from datetime import datetime, timezone

import pytest

from ui_tests.fixtures.public_workspace import (
    PublicWorkspaceFixture, public_context,  # noqa: F401
)


IDENTITY_ACTIONS = ("edit", "delete")
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")

EDITABLE_IDENTITY_ID = "pub-a-editable-identity"
WITHHELD_IDENTITY_ID = "pub-a-withheld-identity"
IN_USE_IDENTITY_ID = "pub-a-in-use-identity"

# The exact conflict and in-use bodies the scoped public identity route returns, mirrored so the
# per-route parity pin (functional_tests/test_public_identity_fixture_parity.py) holds. The etag
# conflict text and code are shared byte-for-byte with the group identity family.
IDENTITY_ETAG_CONFLICT_BODY = {
    "error": "This workspace identity was modified. Reload and try again.",
    "error_code": "etag_conflict",
}
IDENTITY_IN_USE_ERROR = "This workspace identity is still in use."
IDENTITY_NOT_FOUND_BODY = {"error": "The workspace identity was not found."}


def _credentials(*, auth_type, username="", domain="", identity="", tenant_id="",
                 managed_identity_client_id="", secret_stored=False):
    """The sanitized `credentials` block the public identity projector returns.

    Mirrors `sanitize_workspace_identity`: no plaintext leaves the server, a stored secret shows the
    `Stored_In_KeyVault` placeholder with its `*_stored` flag set, and the non-secret identifiers
    `tenant_id` and `managed_identity_client_id` round-trip so a managed identity's user-assigned
    client ID and a service principal's tenant survive an edit.
    """
    uses_password = auth_type in ("username_password", "basic")
    return {
        "auth_type": auth_type,
        "username": username,
        "domain": domain,
        "identity": identity,
        "tenant_id": tenant_id,
        "managed_identity_client_id": managed_identity_client_id,
        "password": "Stored_In_KeyVault" if (uses_password and secret_stored) else "",
        "password_stored": bool(uses_password and secret_stored),
        "secret": "Stored_In_KeyVault" if (not uses_password and secret_stored) else "",
        "secret_stored": bool(not uses_password and secret_stored),
    }


def public_identity(workspace_id, identifier, name, *, auth_type="username_password",
                    usage=("file_sync",), actions=IDENTITY_ACTIONS, secret_stored=True,
                    username="", domain="", tenant_id="", managed_identity_client_id="",
                    **overrides):
    """One shared public identity as the public projector returns it, carrying its own etag."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": identifier,
        "name": name,
        "description": f"Stored credential for {name}.",
        "public_workspace_id": workspace_id,
        "provider": "smb",
        "source_type": "smb",
        "usage_contexts": list(usage),
        "supported_source_types": ["smb", "azure_files", "azure_blob"],
        "metadata": {},
        "credentials": _credentials(
            auth_type=auth_type, username=username, domain=domain, tenant_id=tenant_id,
            managed_identity_client_id=managed_identity_client_id, secret_stored=secret_stored,
        ),
        "etag": f'"etag-{identifier}-0"',
        "identity_actions": list(actions),
        "created_at": now,
        "updated_at": now,
    }
    record.update(copy.deepcopy(overrides))
    return record


class PublicIdentitiesFixture(PublicWorkspaceFixture):
    """A small scripted public identity boundary; no second identity service, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.etag_counter = {}
        self.created_counter = 0
        self.identities = {}
        self.identity_policy = {}
        self.identity_references = {}
        # Identifiers removed to stage a "deleted while editing" conflict: a stale PATCH on one of
        # these still answers the etag 409 (never a bare 404), so the editor rebases and shows the
        # deleted notice, exactly as the group family does.
        self.deleted_identity_conflicts = set()
        # pub-a: a manager workspace with File Sync available, so the Identities section opens.
        self.set_identity_policy("pub-a", name="Connections library", role="Owner", status="active")
        self.identities["pub-a"] = [
            # Fully editable: an inline stored secret proves a rename keeps it masked, and its
            # identity_actions carry edit and delete so a manager reaches every control.
            public_identity("pub-a", EDITABLE_IDENTITY_ID, "Reporting service account",
                            auth_type="username_password", username="svc-report", domain="CORP",
                            secret_stored=True),
            # Withheld: the workspace advertises the operations, but this row's empty identity_actions
            # hide its edit and delete beside the editable control -- the per-row gate, not the hint.
            public_identity("pub-a", WITHHELD_IDENTITY_ID, "Locked platform credential",
                            auth_type="api_key", secret_stored=True, actions=()),
            # Still referenced by a File Sync source, so a delete is refused with the in-use 409 and
            # its references, and nothing is removed.
            public_identity("pub-a", IN_USE_IDENTITY_ID, "Bound archive credential",
                            auth_type="username_password", username="svc-archive", secret_stored=True),
        ]
        self.identity_references[("pub-a", IN_USE_IDENTITY_ID)] = [
            {"kind": "file_source", "id": "pub-a-archive-source", "name": "Archive share"},
        ]
        # pub-b: an ordinary reader. Identities are manager-only, so the section is unavailable and
        # every identity route answers 403 -- never a personal identity read.
        self.set_identity_policy("pub-b", name="Read-only library", role="User", status="active")

    def set_identity_policy(self, workspace_id, *, name=None, role=None, status="active",
                            available=True):
        """Recompute a workspace's context and record its identity management operations.

        Operations follow `public_identity_management_operations`: the surface must be available
        (File Sync for this workspace), the caller a manager, and the workspace `active`.
        """
        current = self.workspaces.get(workspace_id)
        name = name or (current["workspace"]["name"] if current else f"{workspace_id} workspace")
        role = role or (self.identity_policy.get(workspace_id, {}).get("role") or "Owner")
        context = public_context(workspace_id, name, role=role, status=status, file_sync=available)
        self.workspaces[workspace_id] = context
        operations = []
        if available and role in MANAGER_ROLES and status == "active":
            operations = ["create", "edit", "delete"]
        self.identity_policy[workspace_id] = {
            "role": role, "status": status, "available": available, "operations": operations,
        }
        return context

    def _identity_etag(self, workspace_id, identifier):
        return self.record(workspace_id, identifier)["etag"]

    def record(self, workspace_id, identifier):
        return next(row for row in self.identities[workspace_id] if row["id"] == identifier)

    def _identity_validation_error(self, body, prior):
        """The reviewed field message the scoped public identity route raises as a validation error,
        served verbatim so a test proves the editor renders the server's own text rather than a
        client-invented string. Only the case a strict client can still reach is modelled: a required
        password blank with nothing stored to keep."""
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        auth_type = str(credentials.get("auth_type") or "")
        stored = False
        if prior is not None:
            prior_credentials = prior.get("credentials") or {}
            stored = bool(prior_credentials.get("password_stored") or prior_credentials.get("secret_stored"))
        if auth_type == "username_password":
            if not str(credentials.get("password") or "") and not stored:
                return "Username/password identities require a password"
        elif auth_type not in ("anonymous", "managed_identity"):
            if not str(credentials.get("secret") or "") and not stored:
                return "This identity type requires a secret value"
        return None

    def touch_identity(self, workspace_id, identifier):
        """Simulate a concurrent edit by another manager: the stored identity etag moves on."""
        record = self.record(workspace_id, identifier)
        self.etag_counter[identifier] = self.etag_counter.get(identifier, 0) + 1
        record["etag"] = f'"etag-{identifier}-moved-{self.etag_counter[identifier]}"'
        return record["etag"]

    def drop_identity_for_conflict(self, workspace_id, identifier):
        """Remove an identity while making the next stale save look like a conditional conflict."""
        self.identities[workspace_id] = [
            row for row in self.identities[workspace_id] if row["id"] != identifier
        ]
        self.deleted_identity_conflicts.add((workspace_id, identifier))

    def _dispatch(self, route, entry):
        if entry.path.startswith("/api/public-workspaces/") and "/identities" in entry.path:
            self._identities(route, entry)
            return
        super()._dispatch(route, entry)

    def _identities(self, route, entry):
        parts = entry.path.split("/")
        # /api/public-workspaces/<workspace_id>/identities[/<identity_id>]
        workspace_id = parts[3]
        identifier = parts[5] if len(parts) > 5 else None
        method = entry.method
        policy = self.identity_policy.get(workspace_id)
        # Identities are manager-only: an unknown scope or a non-manager reader is a 403, exactly as
        # require_public_identity_read_context refuses one -- never a personal fall back.
        if policy is None or policy["role"] not in MANAGER_ROLES or not policy["available"]:
            self._json(route, {"error": "You do not have access to the selected public workspace."}, 403)
            return
        # A readable status is a precondition for every identity request.
        if policy["status"] not in ("active", "locked", "upload_disabled"):
            self._json(route, {"error": "Identities are unavailable for this workspace's current status."}, 403)
            return
        allowed = set(policy["operations"])
        if identifier is None:
            if method == "GET":
                if entry.query:
                    self._json(route, {"error": "This request does not accept query parameters."}, 400)
                    return
                self._json(route, {
                    "identities": copy.deepcopy(self.identities.get(workspace_id, [])),
                    "identity_management": {"schema_version": 1, "operations": list(policy["operations"])},
                })
                return
            if method == "POST":
                assert "create" in allowed, f"Create reached a read-only workspace: {entry}"
                assert "auth" not in entry.body, "A create must not smuggle an auth block."
                validation = self._identity_validation_error(entry.body, None)
                if validation is not None:
                    self._json(route, {"error": validation}, 400)
                    return
                self.created_counter += 1
                new_id = f"public-created-{self.created_counter}"
                credentials = entry.body.get("credentials") if isinstance(entry.body.get("credentials"), dict) else {}
                record = public_identity(
                    workspace_id, new_id, entry.body.get("name", "New identity"),
                    auth_type=str(credentials.get("auth_type") or "username_password"),
                    username=str(credentials.get("username") or ""),
                    domain=str(credentials.get("domain") or ""),
                    secret_stored=bool(credentials.get("password") or credentials.get("secret")),
                )
                self.identities.setdefault(workspace_id, []).insert(0, record)
                self._json(route, {"identity": copy.deepcopy(record)}, 201)
                return
        else:
            record = next((row for row in self.identities.get(workspace_id, []) if row["id"] == identifier), None)
            if record is None:
                # A stale write on an identity another manager just deleted answers the etag 409 so
                # the editor rebases to "deleted"; any other missing identity is a plain 404.
                if method in ("PATCH", "DELETE") and (workspace_id, identifier) in self.deleted_identity_conflicts:
                    self._json(route, copy.deepcopy(IDENTITY_ETAG_CONFLICT_BODY), 409)
                    return
                self._json(route, copy.deepcopy(IDENTITY_NOT_FOUND_BODY), 404)
                return
            if method == "GET":
                self._json(route, {"identity": copy.deepcopy(record)})
                return
            if method == "PATCH":
                assert "edit" in allowed, f"Edit reached a read-only workspace: {entry}"
                assert "expected_etag" in entry.body, "A conditional edit must carry expected_etag."
                assert "auth" not in entry.body, "An edit must not smuggle an auth block."
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, copy.deepcopy(IDENTITY_ETAG_CONFLICT_BODY), 409)
                    return
                validation = self._identity_validation_error(entry.body, record)
                if validation is not None:
                    self._json(route, {"error": validation}, 400)
                    return
                self.etag_counter[identifier] = self.etag_counter.get(identifier, 0) + 1
                record["etag"] = f'"etag-{identifier}-{self.etag_counter[identifier]}"'
                if "name" in entry.body:
                    record["name"] = entry.body["name"]
                if "description" in entry.body:
                    record["description"] = entry.body["description"]
                credentials = entry.body.get("credentials")
                if isinstance(credentials, dict):
                    merged = dict(record["credentials"])
                    for key in ("auth_type", "username", "domain", "identity", "tenant_id",
                                "managed_identity_client_id"):
                        if key in credentials:
                            merged[key] = credentials[key]
                    record["credentials"] = merged
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._json(route, {"identity": copy.deepcopy(record)})
                return
            if method == "DELETE":
                assert "delete" in allowed, f"Delete reached a read-only workspace: {entry}"
                assert isinstance(entry.body, dict) and "expected_etag" in entry.body, (
                    "A conditional delete must carry expected_etag in its JSON body."
                )
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, copy.deepcopy(IDENTITY_ETAG_CONFLICT_BODY), 409)
                    return
                references = self.identity_references.get((workspace_id, identifier))
                if references:
                    self._json(route, {
                        "error": IDENTITY_IN_USE_ERROR,
                        "error_code": "identity_in_use",
                        "references": copy.deepcopy(references),
                    }, 409)
                    return
                self.identities[workspace_id] = [
                    row for row in self.identities[workspace_id] if row["id"] != identifier
                ]
                self._json(route, {"success": True})
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected public identity request."}, 500)


@pytest.fixture
def public_identities_ui(page):
    fixture = PublicIdentitiesFixture(page)
    yield fixture
    fixture.assert_clean()
