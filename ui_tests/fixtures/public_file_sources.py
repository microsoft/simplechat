# public_file_sources.py
"""
Closed M10B public file source HTTP fixtures for the real production V2 SPA.
Version: 0.261.179
Implemented in: 0.261.179

The fixture serves the immutable `/api/public-workspaces/<workspace_id>/file-sources[...]` family and
the `/api/public-workspaces/<workspace_id>/file-source-options` route, and injects the
`file_source_management` context hint that gates create plus the per-row `source_actions` projection
that gates edit, sync, delete and test. It mirrors the group M5B file source fixture
(`ui_tests/fixtures/group_file_sources.py`) for public scope: file sources are a manager-only surface
for reads and writes, so an ordinary `User` workspace's section is unavailable and every file source
route answers 403; it never falls back to personal or group behaviour. Writes carry
`expected_config_revision` in the JSON body, secrets stay masked server-side, and every returned
source identifies the requested workspace with `public_workspace_id` exactly as the reader validates.

pub-a is a manager workspace carrying three file sources: a fully editable SMB share whose stored
password proves masking survives an edit, a withheld one whose empty `source_actions` hides every row
control, and one bound to a reusable public workspace identity so the list row shows the identity name.
pub-b is an ordinary reader: file sources are manager-only, so its section is unavailable and its file
source routes answer 403.

The live File Sync engine, run history, connection tests and browse are exercised byte-for-byte by
the group M5B suite because the public routes drive the same scope-generic engine; this fixture and
its per-route parity pin (`functional_tests/test_public_file_source_fixture_parity.py`) cover the
public envelope, projection, credentials, conflict codes and management gating.
"""

import copy

import pytest

from ui_tests.fixtures.public_workspace import (
    PublicWorkspaceFixture, public_context,  # noqa: F401
)


MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
FILE_SOURCE_OPERATIONS = ("create", "edit", "delete", "sync", "test")
FILE_SOURCE_ITEM_ACTIONS = ("edit", "delete", "sync", "test")
FILE_SOURCE_TRIGGER_WORD = "Stored_In_KeyVault"
FILE_SOURCE_READ_STATUSES = ("active", "locked", "upload_disabled")

EDITABLE_SOURCE_ID = "pub-a-editable-source"
WITHHELD_SOURCE_ID = "pub-a-withheld-source"
IDENTITY_SOURCE_ID = "pub-a-identity-source"
FILE_SYNC_IDENTITY_ID = "pub-a-file-sync-identity"

# The exact conflict, busy and not-found bodies the scoped public file source route returns, mirrored
# so the per-route parity pin holds. The text and codes are shared byte-for-byte with group M5B.
FILE_SOURCE_CONFLICT_BODY = {
    "error": "This file source changed while it was being saved. Reload it and try again.",
    "error_code": "config_conflict",
}
FILE_SOURCE_BUSY_BODY = {
    "error": "Wait for the running sync to finish, then delete the source.",
    "error_code": "source_busy",
}
FILE_SOURCE_NOT_FOUND_BODY = {"error": "The requested File Sync resource was not found."}


def _file_source_credentials(*, auth_type, username="", domain="", identity="", tenant_id="",
                             managed_identity_client_id="", secret_stored=False):
    """The sanitized `credentials` block the public file source projector returns.

    Mirrors `_file_source_credentials`/`sanitize_file_sync_source`: no plaintext leaves the server, a
    stored secret shows the `Stored_In_KeyVault` placeholder with its `*_stored` flag set, and the
    non-secret identifiers `tenant_id` and `managed_identity_client_id` round-trip.
    """
    uses_password = auth_type == "username_password"
    stored = bool(secret_stored) and auth_type not in ("anonymous", "managed_identity")
    placeholder = FILE_SOURCE_TRIGGER_WORD if stored else ""
    return {
        "auth_type": auth_type,
        "username": username,
        "domain": domain,
        "identity": identity,
        "tenant_id": tenant_id,
        "managed_identity_client_id": managed_identity_client_id,
        "password_stored": stored and uses_password,
        "secret_stored": stored and not uses_password,
        "password": placeholder if uses_password else "",
        "secret": "" if uses_password else placeholder,
    }


def public_file_source(workspace_id, identifier, name, *, source_type="smb", enabled=True,
                       recursive=True, connection=None, filters=None, identity_id="",
                       auth_type="username_password", secret_stored=True, username="",
                       domain="", tenant_id="", managed_identity_client_id="",
                       schedule_enabled=False, interval_minutes=60,
                       actions=FILE_SOURCE_ITEM_ACTIONS, remote_delete_policy="ignore",
                       config_revision=None):
    """One public file source as the native projector returns it (the UI-read subset).

    Carries only keys the real projection also returns, so the parity pin's `fixture keys <= server
    keys` holds. The stored credential is a boolean plus a placeholder, never a plaintext secret.
    """
    conn = dict(connection or {})
    if source_type == "smb":
        conn.setdefault("unc_path", "\\\\files.example.test\\reports")
    conn.setdefault("selected_paths", [])
    resolved_filters = {
        "include_patterns": list((filters or {}).get("include_patterns", [])),
        "exclude_patterns": list((filters or {}).get("exclude_patterns", [])),
        "allowed_extensions": list((filters or {}).get("allowed_extensions", [])),
        "fixed_tags": list((filters or {}).get("fixed_tags", [])),
        "folder_tag_mode": (filters or {}).get("folder_tag_mode", "none"),
    }
    return {
        "id": identifier,
        "name": name,
        "public_workspace_id": workspace_id,
        "source_type": source_type,
        "enabled": enabled,
        "recursive": recursive,
        "connection": conn,
        "filters": resolved_filters,
        "schedule": {
            "enabled": schedule_enabled,
            "interval_minutes": interval_minutes,
            "next_run_at": None,
        },
        "remote_delete_policy": remote_delete_policy,
        "identity_id": identity_id or "",
        "credentials": _file_source_credentials(
            auth_type=auth_type, username=username, domain=domain, tenant_id=tenant_id,
            managed_identity_client_id=managed_identity_client_id, secret_stored=secret_stored,
        ),
        "config_revision": config_revision or f"rev-{identifier}-0",
        "source_actions": list(actions),
    }


class PublicFileSourcesFixture(PublicWorkspaceFixture):
    """A small scripted public file source boundary; no live File Sync engine, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.revision_counter = {}
        self.created_counter = 0
        self.file_sources = {}
        self.file_source_policy = {}
        self.busy_sources = set()
        # pub-a: a manager workspace with File Sync available, so the File Sources section opens.
        self.set_file_source_policy("pub-a", name="Connections library", role="Owner", status="active")
        self.file_sources["pub-a"] = [
            # Fully editable: an inline stored secret proves an edit keeps it masked, and its
            # source_actions carry every operation so a manager reaches every control.
            public_file_source("pub-a", EDITABLE_SOURCE_ID, "Quarterly reports share",
                               source_type="smb", auth_type="username_password",
                               username="svc-reports", domain="CORP", secret_stored=True,
                               connection={"unc_path": "\\\\files.example.test\\reports"}),
            # Withheld: the workspace advertises the operations, but this row's empty source_actions
            # hide edit, sync and delete -- the per-row gate, not merely the workspace hint.
            public_file_source("pub-a", WITHHELD_SOURCE_ID, "Locked archive share",
                               source_type="smb", secret_stored=True, actions=()),
            # Bound to a reusable public workspace identity: the list row shows the identity binding.
            public_file_source("pub-a", IDENTITY_SOURCE_ID, "Shared drive via identity",
                               source_type="smb", identity_id=FILE_SYNC_IDENTITY_ID,
                               secret_stored=False,
                               connection={"unc_path": "\\\\files.example.test\\shared"}),
        ]
        # pub-b: an ordinary reader. File sources are manager-only, so the section is unavailable and
        # every file source route answers 403 -- never a personal file source read.
        self.set_file_source_policy("pub-b", name="Read-only library", role="User", status="active")

    def set_file_source_policy(self, workspace_id, *, name=None, role=None, status="active",
                              available=True):
        """Recompute a workspace's context and record its file source management operations.

        Operations follow `public_file_source_management_operations`: the surface must be available
        (File Sync for this workspace), the caller a manager, and the workspace `active`.
        """
        current = self.workspaces.get(workspace_id)
        name = name or (current["workspace"]["name"] if current else f"{workspace_id} workspace")
        role = role or (self.file_source_policy.get(workspace_id, {}).get("role") or "Owner")
        context = public_context(workspace_id, name, role=role, status=status, file_sync=available)
        self.workspaces[workspace_id] = context
        operations = []
        if available and role in MANAGER_ROLES and status == "active":
            operations = list(FILE_SOURCE_OPERATIONS)
        self.file_source_policy[workspace_id] = {
            "role": role, "status": status, "available": available, "operations": operations,
        }
        return context

    def record(self, workspace_id, identifier):
        return next(row for row in self.file_sources[workspace_id] if row["id"] == identifier)

    def _file_source_config_revision(self, workspace_id, identifier):
        return self.record(workspace_id, identifier)["config_revision"]

    def mark_source_busy(self, workspace_id, identifier):
        """Make the next delete of this source look like an active-run refusal."""
        self.busy_sources.add((workspace_id, identifier))

    def _bump_revision(self, record):
        identifier = record["id"]
        self.revision_counter[identifier] = self.revision_counter.get(identifier, 0) + 1
        record["config_revision"] = f"rev-{identifier}-{self.revision_counter[identifier]}"

    def _options_payload(self, workspace_id):
        identity_ids = [FILE_SYNC_IDENTITY_ID] if workspace_id == "pub-a" else []
        return {
            "source_types": ["smb", "azure_files", "azure_blob"],
            "eligible_identity_ids": identity_ids,
            "schedule": {"min_interval_minutes": 15, "default_interval_minutes": 60},
            "limits": {"max_sources": 10, "current_count": len(self.file_sources.get(workspace_id, []))},
            "recursive_allowed": True,
        }

    def _dispatch(self, route, entry):
        path = entry.path
        if path.startswith("/api/public-workspaces/") and "/file-source-options" in path:
            self._file_source_options(route, entry)
            return
        if path.startswith("/api/public-workspaces/") and "/file-sources" in path:
            self._file_sources(route, entry)
            return
        super()._dispatch(route, entry)

    def _guard(self, route, entry, workspace_id):
        """Refuse an unknown scope, a non-manager reader, or a non-readable status, exactly as
        require_public_file_source_read_context does -- never a personal fall back."""
        policy = self.file_source_policy.get(workspace_id)
        if policy is None or policy["role"] not in MANAGER_ROLES or not policy["available"]:
            self._json(route, {"error": "You do not have access to the selected public workspace."}, 403)
            return None
        if policy["status"] not in FILE_SOURCE_READ_STATUSES:
            self._json(route, {"error": "File sources are unavailable for this workspace's current status."}, 403)
            return None
        return policy

    def _file_source_options(self, route, entry):
        parts = entry.path.split("/")
        workspace_id = parts[3]
        if self._guard(route, entry, workspace_id) is None:
            return
        self._json(route, self._options_payload(workspace_id))

    def _file_sources(self, route, entry):
        parts = entry.path.split("/")
        # /api/public-workspaces/<workspace_id>/file-sources[/<source_id>]
        workspace_id = parts[3]
        identifier = parts[5] if len(parts) > 5 else None
        method = entry.method
        policy = self._guard(route, entry, workspace_id)
        if policy is None:
            return
        allowed = set(policy["operations"])
        if identifier is None:
            if method == "GET":
                if entry.query:
                    self._json(route, {"error": "This request does not accept query parameters."}, 400)
                    return
                self._json(route, {
                    "file_sources": copy.deepcopy(self.file_sources.get(workspace_id, [])),
                    "file_source_management": {
                        "schema_version": 1, "operations": list(policy["operations"]),
                    },
                })
                return
            if method == "POST":
                assert "create" in allowed, f"Create reached a read-only workspace: {entry}"
                self.created_counter += 1
                new_id = f"public-created-{self.created_counter}"
                credentials = entry.body.get("credentials") if isinstance(entry.body.get("credentials"), dict) else {}
                record = public_file_source(
                    workspace_id, new_id, entry.body.get("name", "New source"),
                    source_type=str(entry.body.get("source_type") or "smb"),
                    auth_type=str(credentials.get("auth_type") or "username_password"),
                    username=str(credentials.get("username") or ""),
                    domain=str(credentials.get("domain") or ""),
                    secret_stored=bool(credentials.get("password") or credentials.get("secret")),
                    connection=entry.body.get("connection") if isinstance(entry.body.get("connection"), dict) else None,
                )
                self.file_sources.setdefault(workspace_id, []).insert(0, record)
                self._json(route, {"file_source": copy.deepcopy(record)}, 201)
                return
        else:
            record = next((row for row in self.file_sources.get(workspace_id, []) if row["id"] == identifier), None)
            if record is None:
                self._json(route, copy.deepcopy(FILE_SOURCE_NOT_FOUND_BODY), 404)
                return
            if method == "GET":
                self._json(route, {"file_source": copy.deepcopy(record)})
                return
            if method == "PATCH":
                assert "edit" in allowed, f"Edit reached a read-only workspace: {entry}"
                revision = self._require_revision(route, entry.body)
                if revision is None:
                    return
                if revision != record["config_revision"]:
                    self._json(route, copy.deepcopy(FILE_SOURCE_CONFLICT_BODY), 409)
                    return
                self._bump_revision(record)
                if "name" in entry.body:
                    record["name"] = entry.body["name"]
                connection = entry.body.get("connection")
                if isinstance(connection, dict):
                    record["connection"] = {**record["connection"], **connection}
                filters = entry.body.get("filters")
                if isinstance(filters, dict):
                    record["filters"] = {**record["filters"], **filters}
                if "remote_delete_policy" in entry.body:
                    record["remote_delete_policy"] = entry.body["remote_delete_policy"]
                self._json(route, {"file_source": copy.deepcopy(record)})
                return
            if method == "DELETE":
                assert "delete" in allowed, f"Delete reached a read-only workspace: {entry}"
                revision = self._require_revision(route, entry.body)
                if revision is None:
                    return
                if not isinstance(entry.body.get("delete_associated_files"), bool):
                    self._json(route, {"error": "delete_associated_files must be provided as true or false."}, 400)
                    return
                if set(entry.body) - {"expected_config_revision", "delete_associated_files"}:
                    self._json(route, {"error": "Unknown fields are not supported."}, 400)
                    return
                if revision != record["config_revision"]:
                    self._json(route, copy.deepcopy(FILE_SOURCE_CONFLICT_BODY), 409)
                    return
                if (workspace_id, identifier) in self.busy_sources:
                    self._json(route, copy.deepcopy(FILE_SOURCE_BUSY_BODY), 409)
                    return
                self.file_sources[workspace_id] = [
                    row for row in self.file_sources[workspace_id] if row["id"] != identifier
                ]
                self._json(route, {
                    "success": True,
                    "delete_result": {
                        "associated_files_requested": bool(entry.body["delete_associated_files"]),
                        "documents_deleted": 0,
                        "documents_failed": 0,
                        "documents_skipped": 0,
                    },
                })
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected public file source request."}, 500)

    def _require_revision(self, route, body):
        """A write must carry a non-empty string expected_config_revision, exactly as
        `_require_expected_config_revision` demands."""
        if not isinstance(body, dict):
            self._json(route, {"error": "A JSON object is required for this action."}, 400)
            return None
        revision = body.get("expected_config_revision")
        if not isinstance(revision, str) or not revision.strip():
            self._json(route, {"error": "An expected_config_revision is required for this action."}, 400)
            return None
        return revision.strip()


@pytest.fixture
def public_file_sources_ui(page):
    fixture = PublicFileSourcesFixture(page)
    yield fixture
    fixture.assert_clean()
