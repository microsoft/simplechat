# test_public_file_source_apis.py
"""
Functional tests for the immutable-target public workspace file source APIs (M10B).
Version: 0.261.179
Implemented in: 0.261.179

The real policy, access, projection, service and route modules run unchanged
against an in-memory Cosmos stub that honours ETag conditional writes and an
in-memory Key Vault, with the real ``functions_keyvault`` staging helpers and the
real public workspace role/status logic. The workspace is always taken from the
path, so a stale active workspace can never redirect or widen a request. Public
file sources are a manager-only surface for both reads and writes. Network access
is prohibited.

Coverage mirrors ``test_group_file_source_apis.py`` adapted to public rules: the
role/status/availability matrix for every route; the list envelope and single
resource shape carrying ``public_workspace_id`` with a fresh ``config_revision``
and ``source_actions``; the feature gate (``enable_public_workspaces``) and the
File Sync availability predicate; ``expected_config_revision`` conflict detection;
the busy 409 on delete; the DELETE body contract; fresh-name secret staging under
the public Key Vault scope that keeps a refused write from rotating the live
credential; create-failure cleanup; delete counts and the partial outcome; the
sync 202 and runs read; ignore-path; the manager-plus-active gate on the saved
and unsaved test/browse so nobody can pair a destination with a stored identity's
credentials; cross-workspace identity refusal; and the server-decided options.
"""

import sys
import uuid
from copy import deepcopy
from unittest.mock import Mock

import pytest

from test_support.public_file_source_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    OPTIONS_PATH,
    PLACEHOLDER,
    UNC_PATH,
    MANAGER_ROLES,
    NON_MANAGER_ROLES,
    ROLE_USER,
    as_user,
    create_source,
    environment,
    full_secret_name,
    seed_identity,
    seed_synced_document,
    smb_payload,
)


# --------------------------------------------------------------------------
# Reads: role, status, availability
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_manager_roles_can_list_and_read(environment, role):
    source = create_source(environment)
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["file_sources"]] == [source["id"]]
    single = environment.client.get(f"{LIST_PATH}/{source['id']}")
    assert single.status_code == 200
    assert single.get_json()["file_source"]["id"] == source["id"]


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_roles_cannot_read(environment, role):
    create_source(environment)
    as_user(environment, ROLE_USER[role])
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/whatever").status_code == 403


def test_non_member_is_forbidden(environment):
    create_source(environment)
    as_user(environment, "stranger")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert response.get_json()["error"] == "You do not have access to the selected public workspace."


def test_unknown_workspace_is_404(environment):
    as_user(environment, "owner")
    response = environment.client.get("/api/public-workspaces/no-such-ws/file-sources")
    assert response.status_code == 404
    assert response.get_json()["error"] == "The selected public workspace was not found."


def test_list_envelope_and_single_resource_shape(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"file_sources", "file_source_management"}
    assert body["file_source_management"] == {
        "schema_version": 1, "operations": ["create", "edit", "delete", "sync", "test"],
    }
    item = body["file_sources"][0]
    assert item["id"] == source["id"] and item["public_workspace_id"] == "public-a"
    assert item["config_revision"] and item["source_actions"] == ["edit", "delete", "sync", "test"]
    assert "auth" not in item and "_etag" not in item
    # A public source must never leak a foreign scope identifier.
    assert "group_id" not in item and "user_id" not in item
    single = environment.client.get(f"{LIST_PATH}/{source['id']}").get_json()
    assert set(single) == {"file_source"}
    assert single["file_source"]["id"] == source["id"]


@pytest.mark.parametrize("workspace_id,readable", [
    ("public-a", True),
    ("locked-ws", True),
    ("upload-disabled-ws", True),
    ("inactive-ws", False),
    ("haunted-ws", False),
])
def test_read_status_matrix(environment, workspace_id, readable):
    as_user(environment, "owner")
    response = environment.client.get(f"/api/public-workspaces/{workspace_id}/file-sources")
    assert response.status_code == (200 if readable else 403)


@pytest.mark.parametrize("workspace_id,manageable", [
    ("public-a", True),
    ("locked-ws", False),
    ("upload-disabled-ws", False),
])
def test_management_only_when_active(environment, workspace_id, manageable):
    """A browsable but non-active workspace is read-only: management operations are
    empty and a create is refused even though the reader can list."""
    as_user(environment, "owner")
    listing = environment.client.get(f"/api/public-workspaces/{workspace_id}/file-sources")
    assert listing.status_code == 200
    operations = listing.get_json()["file_source_management"]["operations"]
    create = environment.client.post(f"/api/public-workspaces/{workspace_id}/file-sources", json=smb_payload())
    if manageable:
        assert operations == ["create", "edit", "delete", "sync", "test"]
        assert create.status_code == 201
    else:
        assert operations == []
        assert create.status_code == 403
        assert create.get_json()["error"] == "This operation is unavailable for the selected public workspace."


def test_surface_unavailable_when_file_sync_off(environment):
    environment.settings["enable_file_sync_public"] = False
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert response.get_json()["error"] == "File sources require File Sync."


def test_feature_gate_off_is_refused(environment):
    """With ``enable_public_workspaces`` off the whole native family is disabled at
    the route decorator, before any workspace is resolved."""
    environment.settings["enable_public_workspaces"] = False
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 400
    assert response.get_json()["error"] == "Enable Public Workspaces is disabled."


# --------------------------------------------------------------------------
# Create, staging and cleanup
# --------------------------------------------------------------------------

def test_create_stages_secret_under_public_scope_name(environment):
    source = create_source(environment)
    stored = environment.sources_container.get("public-a", source["id"])
    expected_name = full_secret_name(environment, source["id"])
    # The public Key Vault scope is used, the write reference and the vault agree
    # on the conventional name, and the plaintext never lands inline.
    assert expected_name.startswith("public-a--file-sync--public--file-sync-")
    assert stored["auth"]["password_secret_name"] == expected_name
    assert environment.state.vault[expected_name] == "hunter2"
    assert [name for name, _ in environment.state.secret_writes] == [expected_name]
    assert "password" not in stored["auth"]
    # The sanitized projection never carries the secret.
    assert "auth" not in source


def test_create_failure_discards_staged_secret(environment):
    environment.sources_container.fail_create = True
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=smb_payload())
    assert response.status_code == 500
    # A generic message, never the raw exception.
    assert response.get_json()["error"] == "An unexpected error occurred while processing the File Sync request."
    # The staged secret was minted then discarded: no orphan remains in the vault.
    assert environment.state.vault == {}
    assert len(environment.state.secret_writes) == 1
    assert len(environment.state.secret_deletes) == 1
    assert environment.state.secret_writes[0][0] == environment.state.secret_deletes[0]


# --------------------------------------------------------------------------
# Update: config_revision, fresh-name staging, engine-safety
# --------------------------------------------------------------------------

def test_update_password_change_supersedes_old_secret(environment):
    source = create_source(environment)
    old_name = full_secret_name(environment, source["id"])
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={
            "expected_config_revision": source["config_revision"],
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "rotated"},
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    stored = environment.sources_container.get("public-a", source["id"])
    new_name = stored["auth"]["password_secret_name"]
    # The rotated secret lives under a fresh public-scope name; the superseded one
    # is removed only after the write commits.
    assert new_name != old_name and new_name.startswith("public-a--file-sync--public--file-sync-")
    assert environment.state.vault.get(new_name) == "rotated"
    assert old_name in environment.state.secret_deletes and old_name not in environment.state.vault


def test_update_conflict_keeps_live_credential_and_leaves_no_orphan(environment):
    source = create_source(environment)
    old_name = full_secret_name(environment, source["id"])
    writes_before = len(environment.state.secret_writes)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={
            "expected_config_revision": "stale-revision-value",
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "rotated"},
        },
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    # The stored reference still points at the original secret, whose current value
    # is unchanged; the fresh staged secret was discarded, leaving no orphan.
    stored = environment.sources_container.get("public-a", source["id"])
    assert stored["auth"]["password_secret_name"] == old_name
    assert environment.state.vault[old_name] == "hunter2"
    staged = [name for name, _ in environment.state.secret_writes[writes_before:]]
    assert len(staged) == 1 and staged[0] not in environment.state.vault
    assert staged[0] in environment.state.secret_deletes


def test_update_missing_expected_config_revision_is_400(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}", json={"name": "Renamed"},
    )
    assert response.status_code == 400


def test_engine_run_finishing_is_not_a_false_conflict(environment):
    """An engine writing last_run_* between the read and the conditional write does
    not change the editable projection, so a correct expected_config_revision still
    commits after the etag guard re-reads."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def land_engine_write():
        record = environment.sources_container.records[key]
        record["last_run_status"] = "success"
        record["_etag"] = '"etag-engine"'

    environment.sources_container.before_replace.append(land_engine_write)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed Source"},
    )
    assert response.status_code == 200
    stored = environment.sources_container.get("public-a", source["id"])
    assert stored["name"] == "Renamed Source"
    assert stored["last_run_status"] == "success"


def test_update_deleted_source_is_404(environment):
    source = create_source(environment)
    key = ("public-a", source["id"])

    def delete_underneath():
        environment.sources_container.records.pop(key, None)

    environment.sources_container.before_replace.append(delete_underneath)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# config_revision covers every non-secret auth field (rotation safety)
# --------------------------------------------------------------------------

def test_config_revision_covers_every_non_secret_auth_field(environment):
    """The conflict hash must cover every non-secret auth field a preparer writes,
    including the secret *reference* names, so a rotation that lands between a
    PATCH's read and its conditional write is a clean conflict. It must never
    cover the inline ``password``/``secret`` plaintext (Key Vault off)."""
    base = {
        "scope_type": "public", "public_workspace_id": "public-a", "name": "S", "source_type": "smb",
        "connection": {"unc_path": UNC_PATH},
        "auth": {
            "auth_type": "username_password", "username": "svc", "domain": "CORP",
            "identity": "id-x", "tenant_id": "tenant-x", "managed_identity_client_id": "mi-x",
            "password_secret_name": "ref-password", "secret_secret_name": "ref-secret",
        },
    }
    base_revision = environment.filesync.compute_file_sync_config_revision(base)
    covered = (
        "auth_type", "username", "domain", "identity", "tenant_id",
        "managed_identity_client_id", "password_secret_name", "secret_secret_name",
    )
    for auth_field in covered:
        changed = deepcopy(base)
        changed["auth"][auth_field] = "different-value"
        assert environment.filesync.compute_file_sync_config_revision(changed) != base_revision, auth_field
    for secret_field in ("password", "secret"):
        changed = deepcopy(base)
        changed["auth"][secret_field] = "PLAINTEXT-ROTATED"
        assert environment.filesync.compute_file_sync_config_revision(changed) == base_revision, secret_field


def test_rotation_in_flight_is_a_config_conflict(environment):
    """A concurrent write that rotates the secret reference between a PATCH's read
    and its conditional write is refused with config_conflict, because the
    reference name is part of config_revision."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def rotate_reference():
        record = environment.sources_container.records[key]
        record["auth"]["password_secret_name"] = "public-a--file-sync--public--file-sync-rotated-elsewhere"
        record["_etag"] = '"etag-rotated"'

    environment.sources_container.before_replace.append(rotate_reference)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    # The concurrent writer's rotation stands; the stale snapshot was not committed.
    stored = environment.sources_container.get("public-a", source["id"])
    assert stored["auth"]["password_secret_name"] == "public-a--file-sync--public--file-sync-rotated-elsewhere"


# --------------------------------------------------------------------------
# Delete: body contract, busy, associated files, conflict
# --------------------------------------------------------------------------

def test_delete_requires_body_fields(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    # Missing expected_config_revision.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}", json={"delete_associated_files": False},
    ).status_code == 400
    # Missing delete_associated_files.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}", json={"expected_config_revision": source["config_revision"]},
    ).status_code == 400
    # Unknown field.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False, "surprise": 1},
    ).status_code == 400


def test_delete_refused_while_run_active(environment):
    source = create_source(environment)
    environment.runs_container.seed({
        "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "public",
        "public_workspace_id": "public-a", "status": "running",
    })
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "source_busy"
    assert environment.sources_container.get("public-a", source["id"]) is not None


def test_delete_config_conflict_leaves_source(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": "stale", "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    assert environment.sources_container.get("public-a", source["id"]) is not None


def test_delete_success_without_associated_files(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["delete_result"]["associated_files_requested"] is False
    assert environment.sources_container.get("public-a", source["id"]) is None


def test_delete_etag_only_change_retries_to_success(environment):
    """An etag-only change between the read and the conditional delete (a run
    finishing, which bumps the etag but no editable field) must retry against the
    fresh etag and succeed, not surface a false 409."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def bump_etag_only():
        environment.sources_container.records[key]["_etag"] = '"etag-raced"'

    environment.sources_container.before_delete.append(bump_etag_only)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 200
    assert environment.sources_container.get("public-a", source["id"]) is None


def test_delete_config_change_mid_flight_is_conflict(environment):
    """An editable change landing between the read and the conditional delete
    changes the config revision, so the re-read refuses with config_conflict and
    keeps the source."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def edit_underneath():
        record = environment.sources_container.records[key]
        record["name"] = "Renamed By Someone Else"
        record["_etag"] = '"etag-edited"'

    environment.sources_container.before_delete.append(edit_underneath)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    assert environment.sources_container.get("public-a", source["id"]) is not None


def test_delete_run_starting_mid_flight_is_busy(environment):
    """A run that starts between the read and the conditional delete is caught on
    the retry's active-run re-check and refused as busy."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def start_run_underneath():
        environment.runs_container.seed({
            "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "public",
            "public_workspace_id": "public-a", "status": "running",
        })
        environment.sources_container.records[key]["_etag"] = '"etag-run-started"'

    environment.sources_container.before_delete.append(start_run_underneath)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "source_busy"
    assert environment.sources_container.get("public-a", source["id"]) is not None


def test_delete_gone_mid_flight_is_404(environment):
    """A source removed underneath the conditional delete is a 404, never a
    recreate."""
    source = create_source(environment)
    key = ("public-a", source["id"])

    def remove_underneath():
        environment.sources_container.records.pop(key, None)

    environment.sources_container.before_delete.append(remove_underneath)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 404


def test_delete_with_associated_files_reports_counts(environment):
    """A successful delete that removes associated files reports the counts and
    removes the source."""
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-1")
    seed_synced_document(environment, source["id"], "doc-2")
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )
    assert response.status_code == 200
    result = response.get_json()["delete_result"]
    assert result["associated_files_requested"] is True
    assert result["documents_deleted"] == 2
    assert result["documents_failed"] == 0
    assert environment.sources_container.get("public-a", source["id"]) is None


def test_delete_incomplete_when_a_document_cannot_be_removed(environment):
    """If an associated document cannot be deleted, the source is kept and the
    caller gets a 409 delete_incomplete with the counts, so it never looks like a
    clean delete."""
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-ok")
    seed_synced_document(environment, source["id"], "doc-bad")

    def maybe_fail(*_args, document_id=None, **_kwargs):
        if document_id == "doc-bad":
            raise RuntimeError("provider rejected the delete")

    environment.filesync.delete_document_revision = Mock(side_effect=maybe_fail)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "delete_incomplete"
    assert body["partial"] is True
    assert body["delete_result"]["documents_deleted"] == 1
    assert body["delete_result"]["documents_failed"] == 1
    assert environment.sources_container.get("public-a", source["id"]) is not None


def test_delete_partial_conflict_after_documents_removed(environment):
    """When the associated documents are deleted but the source then changes before
    it can be removed, the refusal is honest: config_conflict with ``partial`` and
    the delete counts, not a clean success."""
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-1")
    key = ("public-a", source["id"])

    def edit_underneath():
        record = environment.sources_container.records[key]
        record["name"] = "Renamed Mid Delete"
        record["_etag"] = '"etag-edited"'

    environment.sources_container.before_delete.append(edit_underneath)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "config_conflict"
    assert body["partial"] is True
    assert body["delete_result"]["documents_deleted"] == 1
    assert "documents were deleted" in body["error"]
    assert environment.sources_container.get("public-a", source["id"]) is not None


# --------------------------------------------------------------------------
# Key Vault secrets removed after a committed delete, never on a refusal
# --------------------------------------------------------------------------

def test_delete_removes_key_vault_secrets_after_commit(environment):
    source = create_source(environment)
    secret_name = full_secret_name(environment, source["id"])
    assert secret_name in environment.state.vault
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 200
    assert secret_name in environment.state.secret_deletes
    assert secret_name not in environment.state.vault


def test_delete_refusal_keeps_key_vault_secrets(environment):
    source = create_source(environment)
    secret_name = full_secret_name(environment, source["id"])
    deletes_before = list(environment.state.secret_deletes)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": "stale", "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert environment.state.secret_deletes == deletes_before
    assert secret_name in environment.state.vault


# --------------------------------------------------------------------------
# Sync, runs, ignore-path
# --------------------------------------------------------------------------

def test_sync_queues_a_run_without_inline_processing(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/sync")
    assert response.status_code == 202
    run = response.get_json()["run"]
    assert run["source_id"] == source["id"] and run["status"] == "queued"
    environment.executor.submit_stored.assert_called_once()


def test_runs_list_is_readable(environment):
    source = create_source(environment)
    environment.runs_container.seed({
        "id": "run-1", "source_id": source["id"], "scope_type": "public", "public_workspace_id": "public-a",
        "status": "success", "error_message": "raw internal detail",
    })
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/{source['id']}/runs")
    assert response.status_code == 200
    runs = response.get_json()["runs"]
    assert [run["id"] for run in runs] == ["run-1"]
    # The raw provider error is replaced by the public run error message.
    assert runs[0]["error_message"] != "raw internal detail"


def test_ignore_path_marks_item_ignored(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.post(
        f"{LIST_PATH}/{source['id']}/ignore-path",
        json={"remote_path": f"{UNC_PATH}\\old.txt", "ignored": True},
    )
    assert response.status_code == 200
    assert response.get_json()["item"]["status"] == "ignored"


def test_sync_rejects_non_manager(environment):
    source = create_source(environment)
    as_user(environment, "stranger")
    assert environment.client.post(f"{LIST_PATH}/{source['id']}/sync").status_code == 403


# --------------------------------------------------------------------------
# Test / browse gating (manager-only, active-only, no network on refusal)
# --------------------------------------------------------------------------

def test_saved_test_connection_is_manager_only(environment):
    source = create_source(environment)
    as_user(environment, "stranger")
    # Refused before any connector runs, so no network is attempted.
    assert environment.client.post(f"{LIST_PATH}/{source['id']}/test-connection").status_code == 403


def test_saved_test_connection_reaches_service_for_manager(environment):
    source = create_source(environment)
    environment.access.test_file_sync_source_connection = Mock(return_value={"ok": True})
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/test-connection")
    assert response.status_code == 200
    assert response.get_json()["connection"] == {"ok": True}
    scope, workspace_id, _payload, user_id = environment.access.test_file_sync_source_connection.call_args.args
    assert scope == "public" and workspace_id == "public-a" and user_id == "owner"
    assert environment.access.test_file_sync_source_connection.call_args.kwargs["source_id"] == source["id"]


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

def test_options_offers_scope_valid_types_only(environment):
    as_user(environment, "owner")
    response = environment.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    body = response.get_json()
    values = {entry["value"] for entry in body["source_types"]}
    assert "smb" in values
    # OneDrive is personal-only and must never be offered for a public scope.
    assert "onedrive" not in values
    assert body["eligible_identity_ids"] == {value: [] for value in values}
    assert body["limits"]["max_sources"] == 10


def test_options_requires_manager(environment):
    as_user(environment, "stranger")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


# --------------------------------------------------------------------------
# Identity binding and options ⇔ save-time eligibility
# --------------------------------------------------------------------------

def test_options_eligible_identities_match_save_time_validation(environment):
    """Over a seeded identity matrix, ``eligible_identity_ids[source_type]`` must
    list exactly the identities the save-time gate ``_get_file_sync_identity``
    would accept for that type, so a client's identity picker never offers an
    identity the server would then reject (nor hides one it would accept)."""
    seed_identity(environment, "id-smb", usage_contexts=("file_sync",), supported_source_types=("smb",), auth_type="username_password")
    seed_identity(environment, "id-generic", usage_contexts=("file_sync",), supported_source_types=("generic",), auth_type="username_password")
    seed_identity(environment, "id-azure", usage_contexts=("file_sync",), supported_source_types=("azure_files",), auth_type="managed_identity")
    seed_identity(environment, "id-action-only", usage_contexts=("action",), supported_source_types=("smb",), auth_type="username_password")
    seed_identity(environment, "id-missing-usage", usage_contexts=None, supported_source_types=("smb",), auth_type="username_password")

    as_user(environment, "owner")
    eligible = environment.client.get(OPTIONS_PATH).get_json()["eligible_identity_ids"]

    identity_ids = ["id-smb", "id-generic", "id-azure", "id-action-only", "id-missing-usage"]
    for source_type in eligible:
        for identity_id in identity_ids:
            try:
                environment.filesync._get_file_sync_identity("public", "public-a", identity_id, source_type)
                save_time_accepts = True
            except (ValueError, LookupError, PermissionError):
                save_time_accepts = False
            assert (identity_id in eligible[source_type]) == save_time_accepts, (source_type, identity_id)


def test_create_with_another_workspaces_identity_is_refused(environment):
    """An identity that belongs to a different public workspace is not visible in
    this workspace's partition, so binding it on create is refused rather than
    silently reaching across the workspace boundary."""
    seed_identity(environment, "wb-identity", workspace_id="public-b")
    payload = smb_payload()
    payload["identity_id"] = "wb-identity"
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=payload)
    assert response.status_code == 404
    assert not environment.sources_container.records


def test_update_with_another_workspaces_identity_is_refused(environment):
    source = create_source(environment)
    seed_identity(environment, "wb-identity", workspace_id="public-b")
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "identity_id": "wb-identity"},
    )
    assert response.status_code == 404


def test_unsaved_test_with_another_workspaces_identity_is_refused(environment):
    seed_identity(environment, "wb-identity", workspace_id="public-b")
    payload = smb_payload()
    payload["identity_id"] = "wb-identity"
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/test-connection", json=payload)
    assert response.status_code == 404


def test_unsaved_browse_with_another_workspaces_identity_is_refused(environment):
    seed_identity(environment, "wb-identity", workspace_id="public-b")
    payload = smb_payload()
    payload["identity_id"] = "wb-identity"
    payload["browse_path"] = UNC_PATH
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/browse", json=payload)
    assert response.status_code == 404


def test_unsaved_test_and_browse_refuse_non_manager(environment):
    """The unsaved test and browse are manager-only and refuse before any identity
    is resolved or connector runs, so a non-manager can never pair a destination
    with a stored identity's credentials."""
    as_user(environment, "stranger")
    assert environment.client.post(f"{LIST_PATH}/test-connection", json=smb_payload()).status_code == 403
    payload = smb_payload()
    payload["browse_path"] = UNC_PATH
    assert environment.client.post(f"{LIST_PATH}/browse", json=payload).status_code == 403


def test_unsaved_test_and_browse_refuse_in_locked_workspace(environment):
    """A locked workspace is read-only: even a manager cannot run an unsaved test
    or browse, so a non-active workspace can never be used to exercise
    credentials."""
    as_user(environment, "owner")
    locked_list = "/api/public-workspaces/locked-ws/file-sources"
    assert environment.client.post(f"{locked_list}/test-connection", json=smb_payload()).status_code == 403
    payload = smb_payload()
    payload["browse_path"] = UNC_PATH
    assert environment.client.post(f"{locked_list}/browse", json=payload).status_code == 403


# --------------------------------------------------------------------------
# Queue refusals are public validation errors on both routes
# --------------------------------------------------------------------------

def test_sync_reports_already_running_as_public_message(environment):
    """A second sync while one is queued or running is a 400 with the reviewed
    public message, not a leaked internal error."""
    source = create_source(environment)
    environment.runs_container.seed({
        "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "public",
        "public_workspace_id": "public-a", "status": "running",
    })
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/sync")
    assert response.status_code == 400
    assert response.get_json()["error"] == "This source already has a queued or running sync."


def test_sync_reports_concurrent_limit_as_public_message(environment, monkeypatch):
    """Reaching the concurrent-run limit is a 400 with the reviewed public
    message."""
    source = create_source(environment)
    monkeypatch.setattr(environment.filesync, "_count_active_runs", lambda *a, **k: 9999)
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/sync")
    assert response.status_code == 400
    assert response.get_json()["error"] == "The File Sync concurrent run limit has been reached. Try again later."


# --------------------------------------------------------------------------
# Query-parameter and body rejection
# --------------------------------------------------------------------------

def test_read_routes_reject_query_parameters(environment):
    create_source(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?unexpected=1").status_code == 400
    assert environment.client.get(f"{OPTIONS_PATH}?x=1").status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH,
        data='{"name": "a", "name": "b", "source_type": "smb"}',
        content_type="application/json",
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Audit parity
# --------------------------------------------------------------------------

def test_committed_writes_log_activity(environment):
    environment.filesync._log_file_sync_activity = Mock()
    source = create_source(environment)
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_created"

    as_user(environment, "owner")
    environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_updated"

    updated = environment.sources_container.get("public-a", source["id"])
    revision = environment.filesync.compute_file_sync_config_revision(updated)
    environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": revision, "delete_associated_files": False},
    )
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_deleted"


def test_refused_write_logs_no_activity(environment):
    source = create_source(environment)
    environment.filesync._log_file_sync_activity = Mock()
    as_user(environment, "owner")
    environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": "stale", "name": "Renamed"},
    )
    environment.filesync._log_file_sync_activity.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
