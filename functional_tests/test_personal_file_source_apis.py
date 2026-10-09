# test_personal_file_source_apis.py
"""
Functional tests for native personal File Sync configuration.
Version: 0.261.311
Implemented in: 0.261.310

Real routes and the real storage/credential engine run against isolated Cosmos and
Key Vault doubles, with network access blocked by the shared file-source harness.
"""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from test_support import group_file_source_harness, personal_file_source_harness
from test_support.group_file_source_harness import as_user, smb_payload
from test_support.personal_file_source_harness import (
    LIST_PATH, OPTIONS_PATH, create_personal_source,
)


# Register both fixtures in this test module, including the personal fixture's dependency.
environment = group_file_source_harness.environment
personal_environment = personal_file_source_harness.personal_environment


def stored(env, source):
    return env.sources_container.get("owner", source["id"])


def test_personal_options_are_safe_and_authoritative(personal_environment):
    env = personal_environment
    env.settings.update({
        "file_sync_visible_source_types": ["smb", "azure_blob", "onedrive", "google_workspace"],
        "file_sync_min_schedule_interval_minutes": 17,
        "file_sync_allow_recursive_sources": False,
        "file_sync_default_remote_delete_policy": "hard_delete",
    })
    response = env.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    options = response.get_json()
    assert [item["value"] for item in options["source_types"] if item["visible"]] == ["smb", "azure_blob"]
    assert options["schedule"] == {"min_interval_minutes": 17, "max_interval_minutes": 10080}
    assert options["recursive_allowed"] is False
    assert options["default_remote_delete_policy"] == "hard_delete"
    assert "key_vault_name" not in options and "redis_url" not in options


@pytest.mark.parametrize("path", [LIST_PATH, OPTIONS_PATH, f"{LIST_PATH}/foreign"])
@pytest.mark.parametrize("setting", ["enable_file_sync", "enable_file_sync_personal", "file_sync_personal_admin_only", "file_sync_personal_require_app_role"])
def test_personal_capability_is_rechecked(personal_environment, path, setting):
    env = personal_environment
    env.settings[setting] = setting.endswith("admin_only") or setting.endswith("require_app_role")
    response = env.client.get(path)
    assert response.status_code == (400 if setting == "enable_file_sync" else 403)


def test_app_role_allows_options(personal_environment):
    env = personal_environment
    env.settings["file_sync_personal_require_app_role"] = True
    as_user(env, "owner", roles=("User", env.filesync.FILE_SYNC_PERSONAL_APP_ROLE))
    response = env.client.get(OPTIONS_PATH)
    assert response.status_code == 200


def test_sources_are_owner_bound_and_masked(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    assert source["config_revision"] and "_etag" not in source and "auth" not in source
    read = env.client.get(f"{LIST_PATH}/{source['id']}")
    assert read.get_json()["source"]["config_revision"] == source["config_revision"]
    assert read.get_json()["source"]["credentials"]["password_stored"] is True
    as_user(env, "stranger")
    listing = env.client.get(LIST_PATH)
    read = env.client.get(f"{LIST_PATH}/{source['id']}")
    update = env.client.patch(f"{LIST_PATH}/{source['id']}", json={"name": "Stolen"})
    assert listing.get_json()["sources"] == []
    assert read.status_code == 404 and update.status_code == 404


@pytest.mark.parametrize("source_type,connection,credentials", [
    ("smb", {"unc_path": "\\\\files\\share"}, {"auth_type": "anonymous"}),
    ("azure_files", {"account_url": "https://storage.file.core.windows.net", "share_name": "reports", "directory_path": "2026"}, {"auth_type": "managed_identity", "managed_identity_client_id": "managed-client"}),
    ("azure_blob", {"account_url": "https://storage.blob.core.windows.net", "container_name": "reports", "blob_prefix": "2026"}, {"auth_type": "managed_identity"}),
    ("azure_files", {"account_url": "https://storage.file.core.windows.net", "share_name": "reports"}, {"auth_type": "client_secret", "identity": "client", "tenant_id": "tenant", "secret": "fixture-client-secret"}),
    ("azure_files", {"account_url": "https://storage.file.core.windows.net", "share_name": "reports"}, {"auth_type": "connection_string", "connection_string": "fixture-connection-string"}),
    ("azure_blob", {"account_url": "https://storage.blob.core.windows.net", "container_name": "reports"}, {"auth_type": "client_secret", "identity": "client", "tenant_id": "tenant", "secret": "fixture-client-secret"}),
    ("azure_blob", {"account_url": "https://storage.blob.core.windows.net", "container_name": "reports"}, {"auth_type": "connection_string", "connection_string": "DefaultEndpointsProtocol=https;AccountName=storage;AccountKey=Zml4dHVyZS1vbmx5;EndpointSuffix=core.windows.net"}),
])
def test_connector_configuration_round_trip(personal_environment, source_type, connection, credentials):
    env = personal_environment
    write = {
        "name": f"{source_type} reports", "source_type": source_type, "connection": {
            **connection, "selected_paths": ["Quarterly/report.pdf"],
        }, "credentials": credentials, "recursive": True,
        "filters": {"fixed_tags": ["finance"], "folder_tag_mode": "full_path", "include_patterns": ["*.pdf"], "exclude_patterns": ["drafts/*"], "allowed_extensions": ["pdf"]},
        "schedule": {"enabled": True, "interval_minutes": 60}, "remote_delete_policy": "hard_delete",
    }
    source = create_personal_source(env, write)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"], "name": "Renamed",
    })
    assert response.status_code == 200, response.get_json()
    reopened = response.get_json()["source"]
    for field in ("connection", "filters", "remote_delete_policy", "credentials"):
        assert reopened[field] == source[field]
    assert reopened["schedule"]["interval_minutes"] == 60
    assert reopened["config_revision"] != source["config_revision"]


def test_blank_secret_is_kept_and_rotation_is_committed(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    old_name = stored(env, source)["auth"]["password_secret_name"]
    old_secret = env.state.vault[old_name]
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"],
        "credentials": {"auth_type": "username_password", "username": "svc", "password": ""},
    })
    assert response.status_code == 200
    assert stored(env, source)["auth"]["password_secret_name"] == old_name
    revision = response.get_json()["source"]["config_revision"]
    rotated = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": revision,
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "fixture-rotated-password"},
    })
    assert rotated.status_code == 200
    new_name = stored(env, source)["auth"]["password_secret_name"]
    assert new_name != old_name and old_name not in env.state.vault
    assert env.state.vault[new_name] == "fixture-rotated-password" != old_secret


def test_conflict_preserves_live_secret_and_discards_staged_secret(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    before = deepcopy(env.state.vault)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": "stale",
        "credentials": {"auth_type": "username_password", "password": "fixture-refused-password"},
    })
    assert response.status_code == 409 and response.get_json()["error_code"] == "config_conflict"
    assert env.state.vault == before
    assert stored(env, source)["name"] == source["name"]
    assert env.state.secret_writes[-1][0] in env.state.secret_deletes


def test_engine_progress_does_not_conflict_with_edit(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    def progress_underneath():
        record = env.sources_container.records[("owner", source["id"])]
        record["last_run_status"] = "completed"
        record["_etag"] = '"engine-progress"'

    env.sources_container.before_replace.append(progress_underneath)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"], "name": "Renamed",
    })
    assert response.status_code == 200
    assert stored(env, source)["last_run_status"] == "completed"


def test_classic_no_token_update_and_delete_remain_supported(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={"name": "Classic edit"})
    deleted = env.client.delete(f"{LIST_PATH}/{source['id']}", json={"delete_associated_files": False})
    assert response.status_code == 200 and response.get_json()["source"]["name"] == "Classic edit"
    assert deleted.status_code == 200
    assert deleted.get_json()["delete_result"]["associated_files_requested"] is False


def test_hidden_type_is_not_created_and_bad_revision_is_refused(personal_environment):
    env = personal_environment
    env.settings["file_sync_visible_source_types"] = ["azure_files"]
    response = env.client.post(LIST_PATH, json=smb_payload())
    assert response.status_code == 403
    env.settings["file_sync_visible_source_types"] = ["smb"]
    source = create_personal_source(env)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={"expected_config_revision": "", "name": "No"})
    assert response.status_code == 400 and stored(env, source)["name"] == source["name"]


def test_personal_identity_options_and_binding_reject_other_owner(personal_environment):
    env = personal_environment
    identities = env.identities._get_identities_container("personal")
    for user_id, identifier in [("owner", "own-identity"), ("stranger", "foreign-identity")]:
        identities.seed({
            "id": identifier, "user_id": user_id, "scope_type": "personal", "name": identifier,
            "provider": "smb", "usage_contexts": ["file_sync"], "supported_source_types": ["smb"],
            "auth": {"auth_type": "username_password", "username": "svc", "password": "fixture-identity-password"},
        })
    options = env.client.get(OPTIONS_PATH).get_json()
    assert options["eligible_identity_ids"]["smb"] == ["own-identity"]
    write = {**smb_payload(), "identity_id": "foreign-identity"}
    response = env.client.post(LIST_PATH, json=write)
    assert response.status_code in (400, 404)
    write["identity_id"] = "own-identity"
    source = create_personal_source(env, write)
    assert source["identity_name"] == "own-identity"


def test_native_delete_conflict_and_busy_are_explicit(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    response = env.client.delete(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": "stale", "delete_associated_files": False,
    })
    assert response.status_code == 409 and response.get_json()["error_code"] == "config_conflict"
    env.runs_container.seed({"id": "queued-run", "source_id": source["id"], "status": "queued"})
    response = env.client.delete(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"], "delete_associated_files": False,
    })
    assert response.status_code == 409 and response.get_json()["error_code"] == "source_busy"
    assert stored(env, source) is not None


@pytest.mark.parametrize("gate", ["file_sync_personal_admin_only", "file_sync_personal_require_app_role"])
def test_authorized_roles_are_taken_from_the_authenticated_session(personal_environment, gate):
    env = personal_environment
    env.settings[gate] = True
    role = "Admin" if gate.endswith("admin_only") else env.filesync.FILE_SYNC_PERSONAL_APP_ROLE
    as_user(env, "owner", roles=("User", role))
    response = env.client.get(OPTIONS_PATH)
    assert response.status_code == 200


def test_new_reads_refuse_targets_and_request_bodies(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    for path in (OPTIONS_PATH, f"{LIST_PATH}/{source['id']}"):
        targeted = env.client.get(path + "?user_id=stranger")
        body = env.client.get(path, json={"user_id": "stranger"})
        assert targeted.status_code == 400 and body.status_code == 400


def test_edit_race_discards_new_secret_without_overwriting_other_writer(personal_environment):
    env = personal_environment
    source = create_personal_source(env)
    before = deepcopy(env.state.vault)

    def edit_underneath():
        record = env.sources_container.records[("owner", source["id"])]
        record["name"] = "Other writer"
        record["_etag"] = '"other-writer"'

    env.sources_container.before_replace.append(edit_underneath)
    response = env.client.patch(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"],
        "credentials": {"auth_type": "username_password", "password": "fixture-racing-password"},
    })
    assert response.status_code == 409 and response.get_json()["error_code"] == "config_conflict"
    assert stored(env, source)["name"] == "Other writer" and env.state.vault == before


@pytest.mark.parametrize("document_failure", [False, True])
def test_native_delete_reports_real_counts_and_partial_refusals(personal_environment, document_failure):
    env = personal_environment
    source = create_personal_source(env)
    for document_id in ("doc-one", "doc-two"):
        env.items_container.seed({
            "id": document_id, "type": "file_sync_item", "scope_type": "personal",
            "source_id": source["id"], "document_id": document_id, "user_id": "owner",
            "remote_path": f"\\\\files\\reports\\{document_id}.pdf", "status": "synced",
        })
    def delete_document(*_args, document_id=None, **_kwargs):
        if document_failure and document_id == "doc-two":
            raise RuntimeError("fixture delete refused")

    env.filesync.delete_document_revision = Mock(side_effect=delete_document)
    response = env.client.delete(f"{LIST_PATH}/{source['id']}", json={
        "expected_config_revision": source["config_revision"], "delete_associated_files": True,
    })
    result = response.get_json()["delete_result"]
    assert result["documents_deleted"] == (1 if document_failure else 2)
    assert result["documents_failed"] == (1 if document_failure else 0)
    assert response.status_code == (409 if document_failure else 200)
    if document_failure:
        assert response.get_json()["error_code"] == "delete_incomplete" and response.get_json()["partial"] is True


def test_unsaved_and_saved_test_browse_use_the_draft(personal_environment, monkeypatch):
    env = personal_environment
    source = create_personal_source(env)
    test = Mock(return_value=Mock(scandir=Mock(return_value=[])))
    browse = Mock(return_value=[])
    monkeypatch.setattr(env.filesync, "_register_smb_session", test)
    monkeypatch.setattr(env.filesync, "_browse_smb_path", browse)
    for path in (LIST_PATH, f"{LIST_PATH}/{source['id']}"):
        tested = env.client.post(f"{path}/test-connection", json=smb_payload(unc_path="\\\\files\\changed"))
        browsed = env.client.post(f"{path}/browse", json={
            **smb_payload(unc_path="\\\\files\\changed"), "browse_path": "Reports",
        })
        assert tested.status_code == 200 and browsed.status_code == 200
        assert test.call_args.args[0]["connection"]["unc_path"] == "\\\\files\\changed"
        assert browse.call_args.args[1] == "Reports"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
