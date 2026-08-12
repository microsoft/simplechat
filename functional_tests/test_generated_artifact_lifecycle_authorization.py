# test_generated_artifact_lifecycle_authorization.py
#!/usr/bin/env python3
"""
Functional test for generated artifact lifecycle authorization.
Version: 0.250.180
Implemented in: 0.250.180

This test ensures staged artifact-set members are not directly downloadable or
promotable, committed members require a completed artifact-set manifest, and
legacy generated artifacts without artifact-set metadata remain compatible.
"""

import ast
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
OPERATIONS_FILE = APP_ROOT / "functions_simplechat_operations.py"
ROUTE_FILE = APP_ROOT / "route_enhanced_citations.py"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"
IMPLEMENTED_VERSION = "0.250.180"


class FakeNotFound(Exception):
    pass


class FakeContainer:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.upserted = []

    def read_item(self, item, partition_key):
        del partition_key
        if item not in self.items:
            raise FakeNotFound(item)
        return self.items[item]

    def upsert_item(self, body):
        self.items[body["id"]] = body
        self.upserted.append(body)
        return body


def load_operation_helpers(conversation_item, message_item, run_item=None):
    source = OPERATIONS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(OPERATIONS_FILE))
    helper_names = {
        "_safe_positive_int",
        "_build_generated_chat_artifact_lifecycle_metadata",
        "_build_generated_chat_artifact_lifecycle_response",
        "_generated_artifact_has_lifecycle_contract",
        "assert_generated_chat_artifact_is_published_for_user",
        "commit_generated_chat_artifact_publication_for_user",
    }
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigned_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if any(name.startswith("GENERATED_CHAT_ARTIFACT_") for name in assigned_names):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in helper_names:
            selected_nodes.append(node)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Optional": Optional,
        "datetime": datetime,
        "timezone": timezone,
        "CosmosResourceNotFoundError": FakeNotFound,
        "cosmos_conversations_container": FakeContainer({"conversation-1": conversation_item}),
        "cosmos_messages_container": FakeContainer({"message-1": message_item}),
        "cosmos_tabular_export_runs_container": FakeContainer({"run-1": run_item} if run_item else {}),
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(OPERATIONS_FILE), "exec"), namespace)
    return namespace


def load_route_helper(message_item, publication_assertion):
    source = ROUTE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ROUTE_FILE))
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_authorized_chat_artifact_message"
    )
    namespace = {
        "CosmosResourceNotFoundError": FakeNotFound,
        "cosmos_conversations_container": FakeContainer({"conversation-1": {"user_id": "user-1"}}),
        "cosmos_messages_container": FakeContainer({"message-1": message_item}),
        "assert_generated_chat_artifact_is_published_for_user": publication_assertion,
    }
    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(ROUTE_FILE), "exec"), namespace)
    return namespace["_get_authorized_chat_artifact_message"]


def load_recovery_helpers():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    helper_names = {
        "_is_artifact_publication_recoverable",
        "_can_resume_run",
        "_can_cancel_run",
    }
    selected_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    namespace = {
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_EXPORT_STATUS_CANCELED": "canceled",
        "TABULAR_EXPORT_STATUS_FAILED": "failed",
        "TABULAR_EXPORT_STATUS_QUEUED": "queued",
        "TABULAR_EXPORT_STATUS_RUNNING": "running",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_VALIDATING": "validating",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_PUBLISHING": "publishing",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_ROLLBACK_REQUIRED": "rollback_required",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_FAILED": "failed",
        "_is_waiting_for_retry": lambda run: False,
        "_is_due_queued_retry_run": lambda run: False,
        "_is_stale_queued_run": lambda run, settings: False,
        "_is_stale_running_run": lambda run, settings: False,
        "_is_retryable_failed_run": lambda run: False,
        "_has_exhausted_independent_batch_retries": lambda run: False,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace


def build_message(metadata):
    return {
        "id": "message-1",
        "conversation_id": "conversation-1",
        "role": "file",
        "file_content_source": "blob",
        "blob_container": "chat",
        "blob_path": "user-1/conversation-1/generated/message-1/output.csv",
        "metadata": {
            "is_generated_chat_artifact": True,
            **metadata,
        },
    }


def test_lifecycle_metadata_defaults_to_staged_and_legacy_is_visible():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_operation_helpers({"user_id": "user-1"}, build_message({}))
    metadata = helpers["_build_generated_chat_artifact_lifecycle_metadata"]({
        "artifact_run_id": "run-1",
        "artifact_set_id": "set-1",
        "artifact_member_id": "requested-csv",
    })
    assert metadata["generated_artifact_lifecycle_state"] == "staged"
    assert metadata["generated_artifact_publication_generation"] == 0

    helpers["assert_generated_chat_artifact_is_published_for_user"]("user-1", build_message({}))


def test_staged_artifact_is_not_published_until_manifest_commits():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    staged_message = build_message({
        "generated_artifact_run_id": "run-1",
        "generated_artifact_set_id": "set-1",
        "generated_artifact_member_id": "requested-csv",
        "generated_artifact_lifecycle_state": "staged",
        "generated_artifact_validation_state": "staged",
        "generated_artifact_publication_generation": 0,
    })
    helpers = load_operation_helpers({"user_id": "user-1"}, staged_message)
    try:
        helpers["assert_generated_chat_artifact_is_published_for_user"]("user-1", staged_message)
    except PermissionError:
        pass
    else:
        raise AssertionError("Staged artifact was authorized for direct access")


def test_committed_artifact_requires_completed_manifest_member():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    published_message = build_message({
        "generated_artifact_run_id": "run-1",
        "generated_artifact_set_id": "set-1",
        "generated_artifact_member_id": "requested-csv",
        "generated_artifact_lifecycle_state": "published",
        "generated_artifact_validation_state": "validated",
        "generated_artifact_publication_generation": 2,
    })
    run = {
        "id": "run-1",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "artifact_set_manifest": {
            "set_id": "set-1",
            "lifecycle_state": "completed",
            "validation_state": "validated",
            "publication_generation": 2,
            "members": [{
                "member_id": "requested-csv",
                "artifact_message_id": "message-1",
                "lifecycle_state": "published",
                "validation_state": "validated",
            }],
        },
    }
    helpers = load_operation_helpers({"user_id": "user-1"}, published_message, run)
    helpers["assert_generated_chat_artifact_is_published_for_user"]("user-1", published_message)


def test_commit_updates_message_lifecycle_metadata():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    staged_message = build_message({
        "generated_artifact_run_id": "run-1",
        "generated_artifact_set_id": "set-1",
        "generated_artifact_member_id": "analysis",
        "generated_artifact_lifecycle_state": "staged",
        "generated_artifact_validation_state": "staged",
        "generated_artifact_publication_generation": 0,
    })
    helpers = load_operation_helpers({"user_id": "user-1"}, staged_message)
    committed = helpers["commit_generated_chat_artifact_publication_for_user"](
        "user-1",
        "conversation-1",
        "message-1",
        "set-1",
        "analysis",
        3,
    )
    metadata = committed["metadata"]
    assert metadata["generated_artifact_lifecycle_state"] == "published"
    assert metadata["generated_artifact_validation_state"] == "validated"
    assert metadata["generated_artifact_publication_generation"] == 3
    assert metadata["generated_artifact_committed_at"]


def test_route_helper_enforces_publication_gate():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    calls = []

    def deny_staged(user_id, message_item):
        calls.append((user_id, message_item["id"]))
        raise PermissionError("Artifact is not published")

    route_helper = load_route_helper(build_message({"generated_artifact_lifecycle_state": "staged"}), deny_staged)
    try:
        route_helper("user-1", "conversation-1", "message-1")
    except PermissionError:
        pass
    else:
        raise AssertionError("Route helper returned a staged artifact")
    assert calls == [("user-1", "message-1")]


def test_failed_post_staging_runs_can_resume_or_cancel():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_recovery_helpers()
    recoverable_run = {
        "status": "failed",
        "publishing_started_at": "2026-08-12T00:00:00+00:00",
        "artifact_set_manifest": {"lifecycle_state": "rollback_required"},
    }
    completed_failed_run = {
        "status": "failed",
        "publishing_started_at": "2026-08-12T00:00:00+00:00",
        "artifact_set_manifest": {"lifecycle_state": "completed"},
    }
    running_publish_run = {
        "status": "running",
        "publishing_started_at": "2026-08-12T00:00:00+00:00",
        "artifact_set_manifest": {"lifecycle_state": "publishing"},
    }

    assert helpers["_is_artifact_publication_recoverable"](recoverable_run) is True
    assert helpers["_can_resume_run"](recoverable_run, {}) is True
    assert helpers["_can_cancel_run"](recoverable_run) is True
    assert helpers["_can_resume_run"](completed_failed_run, {}) is False
    assert helpers["_can_cancel_run"](running_publish_run) is False


if __name__ == "__main__":
    tests = [
        test_lifecycle_metadata_defaults_to_staged_and_legacy_is_visible,
        test_staged_artifact_is_not_published_until_manifest_commits,
        test_committed_artifact_requires_completed_manifest_member,
        test_commit_updates_message_lifecycle_metadata,
        test_route_helper_enforces_publication_gate,
        test_failed_post_staging_runs_can_resume_or_cancel,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
        print(f"PASS {test.__name__}")
    print(f"Results: {len(tests)}/{len(tests)} tests passed")
