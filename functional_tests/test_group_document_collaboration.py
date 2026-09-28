# test_group_document_collaboration.py
"""
Functional tests for immutable group document sharing and repair.
Version: 0.261.131
Implemented in: 0.261.131

Real Flask routes, policy, conditional source writes, Search write guards, access
index projections and notification persistence run against local service seams.
The management fixture blocks sockets and restores its module replacements.
No Azure, model or active-workspace preference calls are permitted.
"""

from contextlib import nullcontext
from copy import deepcopy
import logging
from pathlib import Path
import re
import sys
from unittest.mock import Mock

from azure.core.exceptions import ServiceRequestError, ServiceResponseError
import pytest

from test_group_document_management import MutableContainer, StoreFailure, management
from test_group_document_read_apis import (
    MissingRecord, document, environment, get, load_real_module,
)
from test_support.agent_delegation import execute_functions, module_stub


OPERATION = "group_document_collaboration_operation"
WRITER = "group_document_projection_writer"
DOCUMENT_ID = "document-a"
PRIVATE = "PRIVATE-COLLABORATION-DATA"
ACTIONS = ("share", "unshare", "approve_share", "remove_share")
MANAGERS = ("owner", "admin", "manager")
SHARING_FIELDS = {
    "schema_version", "group_id", "document_id", "document_version", "etag",
    "owner_group", "relationship", "actions", "recipients", "publication",
}


class NotificationStore(MutableContainer):
    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append((query, deepcopy(parameters or []), kwargs))
        if self.failure:
            raise self.failure
        values = {item["name"]: item["value"] for item in parameters or []}
        types = [value for key, value in values.items() if key.startswith("@notification_type_")]
        filters = {key.removeprefix("@metadata_"): value for key, value in values.items() if key.startswith("@metadata_")}
        absent = re.findall(r"NOT IS_DEFINED\(c\.metadata\.(\w+)\)", query)
        return [
            deepcopy(record) for record in self.records.values()
            if (not types or record["notification_type"] in types)
            and all(record.get("metadata", {}).get(key) == value for key, value in filters.items())
            and all(key not in record.get("metadata", {}) for key in absent)
        ]

    def read_item(self, item, partition_key):
        result = super().read_item(item, partition_key)
        if partition_key != result["user_id"]:
            raise AssertionError("Notification reads must use the actual user partition.")
        return result

    def delete_item(self, item, partition_key, **kwargs):
        if item in self.records and partition_key != self.records[item]["user_id"]:
            raise AssertionError("Notification cleanup must use the actual user partition.")
        return super().delete_item(item, partition_key, **kwargs)


class CacheStore(NotificationStore):
    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append((query, deepcopy(parameters or []), kwargs))
        if self.failure:
            raise self.failure
        values = {item["name"]: item["value"] for item in parameters or []}
        group_id, document_id = values["@group_id"], values.get("@document_id")
        return [
            deepcopy(record) for record in self.records.values()
            if group_id in record.get("doc_scope", "")
            or document_id is not None and (
                group_id in record["user_id"]
                or any(
                    result.get("document_id") == document_id
                    or result.get("source_document_id") == document_id
                    or (result.get("screening_provenance") or {}).get("document_id") == document_id
                    for result in record.get("results", [])
                )
            )
        ]


class SearchStore:
    def __init__(self, documents):
        self.records = {
            f"{item['id']}-chunk": {
                "id": f"{item['id']}-chunk", "document_id": item["id"],
                "group_id": item["group_id"], "version": item["version"],
                "shared_group_ids": deepcopy(item["shared_group_ids"]),
            }
            for item in documents
        }
        self.queries = []
        self.writes = []
        self.failure = None
        self.after_query = None
        self.result_override = None

    def search(self, **kwargs):
        self.queries.append(deepcopy(kwargs))
        match = re.fullmatch(r"document_id eq '((?:[^']|'')*)'", kwargs["filter"])
        if not match:
            raise AssertionError("Search ACL work must target exactly one document.")
        target = match.group(1).replace("''", "'")
        result = [
            deepcopy(item) for item in self.records.values() if item["document_id"] == target
        ] if self.result_override is None else deepcopy(self.result_override)
        if self.after_query:
            self.after_query()
        return result

    def merge_documents(self, documents, **kwargs):
        if kwargs.get("retry_total") != 0:
            raise AssertionError("Unknown Search writes must not automatically replay.")
        self.writes.append(deepcopy(documents))
        if self.failure:
            raise self.failure
        for update in documents:
            self.records[update["id"]].update(deepcopy(update))
        return [{"succeeded": True} for _item in documents]


@pytest.fixture
def sharing(management):
    env = management
    patch = env.scoped_monkeypatch
    patch.setattr(env.collaboration, "cosmos_group_documents_container", env.source)
    patch.setattr(env.index, "cosmos_group_documents_container", env.source)
    fence = sys.modules["functions_group_document_projection_fence"]
    patch.setattr(env.index, "hold_group_document_projection", fence.hold_group_document_projection)

    original_query = env.group_container.query_items

    def directory_query(query, parameters=None, **kwargs):
        if "c.type = 'group'" not in query:
            return original_query(query, parameters, **kwargs)
        env.group_container.queries.append((query, deepcopy(parameters or []), kwargs))
        if env.group_container.failure:
            raise env.group_container.failure
        return [
            deepcopy(item) for item in env.group_container.records.values()
            if item.get("type", "group") == "group"
        ]

    patch.setattr(env.group_container, "query_items", directory_query)
    env.search = SearchStore(env.source.records.values())
    search_helpers = {
        "nullcontext": nullcontext,
        "cosmos_group_documents_container": env.source,
        "cosmos_data_management_jobs_container": object(),
        "hold_data_management_search_write_slot": lambda *_args, **_kwargs: nullcontext(),
        "hold_group_document_projection": fence.hold_group_document_projection,
        "GroupDocumentProjectionConflict": fence.GroupDocumentProjectionConflict,
        "log_event": env.logs,
    }
    execute_functions("functions_documents.py", {
        "_search_indexing_results_succeeded", "_execute_document_search_write", "_build_archived_scope_value",
    }, search_helpers)
    patch.setattr(env.collaboration, "_get_search_client", lambda **_kwargs: env.search)
    patch.setattr(env.collaboration, "_execute_document_search_write", search_helpers["_execute_document_search_write"])
    env.index_write = Mock(wraps=env.index_container.upsert_item)
    patch.setattr(env.index_container, "upsert_item", env.index_write)

    env.notices = NotificationStore({})
    patch.setattr(env.config, "cosmos_notifications_container", env.notices, raising=False)
    patch.setitem(sys.modules, "functions_public_workspaces", module_stub(
        "functions_public_workspaces", find_public_workspace_by_id=Mock(),
        get_user_public_workspaces=Mock(),
    ))
    patch.setitem(sys.modules, "functions_workflow_alert_safety", module_stub(
        "functions_workflow_alert_safety", sanitize_workflow_alert_record=Mock(
            side_effect=AssertionError("Sharing must not enter workflow alert rendering."),
        ),
    ))
    env.notifications = load_real_module(patch, "functions_notifications")
    patch.setattr(env.collaboration, "create_notification", env.notifications.create_notification)
    patch.setattr(env.collaboration, "delete_notifications_by_metadata", env.notifications.delete_notifications_by_metadata)
    env.cache = CacheStore({})
    cache_helpers = {
        "cosmos_search_cache_container": env.cache, "logger": logging.getLogger(__name__),
        "_debug_print": env.logs,
    }
    execute_functions("utils_cache.py", {"invalidate_group_search_cache"}, cache_helpers)
    env.invalidate_cache = Mock(wraps=cache_helpers["invalidate_group_search_cache"])
    patch.setattr(env.collaboration, "invalidate_group_search_cache", env.invalidate_cache)
    yield env
    env.user_settings.assert_not_called()
    assert not env.queue.jobs
    assert not env.blobs.downloads
    assert not env.personal.reads


def set_actor(env, user_id):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": ["User"]}


def seed_share(env, status="not_approved", *, target="group-b", legacy=False):
    record = env.source.records[DOCUMENT_ID]
    record["shared_group_ids"] = [
        entry for entry in record["shared_group_ids"] if entry.split(",", 1)[0] != target
    ] + [f"{target},{status}"]
    detail = {
        "status": status, "source_group_id": "group-a", "target_group_id": target,
        "document_id": DOCUMENT_ID, "document_version": 1,
        "request_id": f"request-{target}", "shared_by_user_id": "sharer",
    }
    if legacy:
        detail.pop("request_id")
        detail.pop("document_version")
    record.setdefault("document_share_details", {}).setdefault("groups", {})[target] = detail
    env.search.records[f"{DOCUMENT_ID}-chunk"]["shared_group_ids"] = deepcopy(record["shared_group_ids"])


def invoke(env, action, *, etag=None, target="group-b", group_id=None, document_id=DOCUMENT_ID, **kwargs):
    group_id = group_id or ("group-b" if action in {"approve_share", "remove_share"} else "group-a")
    method, suffix = {
        "share": ("POST", "share"), "unshare": ("DELETE", f"share/{target}"),
        "approve_share": ("POST", "approve-share"), "remove_share": ("DELETE", "received-share"),
    }[action]
    payload = {"expected_etag": env.source.records[document_id]["_etag"] if etag is None else etag}
    if action == "share":
        payload["target_group_id"] = target
    kwargs.setdefault("json", payload)
    return env.client.open(
        f"/api/groups/{group_id}/documents/{document_id}/{suffix}", method=method, **kwargs,
    )


def state(env, group_id="group-a", document_id=DOCUMENT_ID):
    return env.client.get(f"/api/groups/{group_id}/documents/{document_id}/sharing")


def assert_receipt(response, action, *, status="applied", resulting_state=None, group_id=None, target="group-b"):
    body = response.get_json()
    group_id = group_id or ("group-b" if action in {"approve_share", "remove_share"} else "group-a")
    expected = {
        "schema_version": 1, "group_id": group_id, "document_id": DOCUMENT_ID,
        "action": action, "status": status, "state": resulting_state or {
            "share": "not_approved", "unshare": "removed", "approve_share": "approved", "remove_share": "denied",
        }[action],
        "errors": [],
    }
    if action in {"share", "unshare"}:
        expected["target_group_id"] = target
    assert response.status_code == 200, body
    assert body == expected


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("actor", [*MANAGERS, "reader", "pending-member", "stranger"])
def test_sharing_mutations_require_current_selected_group_managers(sharing, action, actor):
    env = sharing
    seed_share(env)
    set_actor(env, actor)
    before = deepcopy(env.source.records)
    response = invoke(env, action)
    if actor in MANAGERS:
        assert response.status_code == 200, response.get_json()
    else:
        assert response.status_code == 403
        assert env.source.records == before
        assert not env.search.writes and not env.index_write.call_count and not env.notices.records


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", ["active", "upload_disabled", "locked", "inactive", "unknown"])
def test_selected_group_status_gates_actual_actions(sharing, action, status):
    env = sharing
    seed_share(env)
    selected = "group-b" if action in {"approve_share", "remove_share"} else "group-a"
    env.groups[selected]["status"] = status
    response = invoke(env, action)
    assert response.status_code == (200 if status in {"active", "upload_disabled"} else 403), response.get_json()
    if status not in {"active", "upload_disabled"}:
        assert not env.source.writes and not env.search.writes


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("other_status", ["active", "upload_disabled", "locked", "inactive", "unknown"])
def test_only_positive_actions_require_both_groups_to_remain_mutable(sharing, action, other_status):
    env = sharing
    seed_share(env)
    other = "group-a" if action in {"approve_share", "remove_share"} else "group-b"
    env.groups[other]["status"] = other_status
    response = invoke(env, action)
    allowed = action in {"unshare", "remove_share"} or other_status in {"active", "upload_disabled"}
    assert response.status_code == (200 if allowed else 403), response.get_json()


@pytest.mark.parametrize("actor,role", [("owner", "Owner"), ("admin", "Admin"), ("manager", "DocumentManager"), ("reader", "User")])
@pytest.mark.parametrize("status", ["active", "upload_disabled", "locked", "inactive", "unknown"])
def test_workspace_collaboration_vocabulary_is_separate_from_management(sharing, actor, role, status):
    env = sharing
    set_actor(env, actor)
    env.groups["group-a"]["status"] = status
    policy = sys.modules["functions_group_document_policy"]
    operations = policy.group_document_collaboration_operations(env.groups["group-a"], role, env.settings)
    response = state(env)
    expected = [] if status in {"inactive", "unknown"} else ["inspect"]
    if status in {"active", "upload_disabled"}:
        expected += (["share", "unshare", "approve_share", "remove_share"] if actor in MANAGERS else [])
        expected += (["approve_artifact"] if actor in MANAGERS and status == "active" else [])
        expected += (["reject_artifact"] if actor in MANAGERS else []) + ["cancel_artifact"]
    assert operations == expected
    assert response.status_code == (403 if not expected else 200)
    if expected:
        body = response.get_json()
        assert body["actions"] == (["inspect", "share"] if actor in MANAGERS and status != "locked" else ["inspect"])


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("source_state", ["historical", "superseded", "pending_artifact", "pending_status_gap", "held"])
def test_positive_actions_never_grant_historical_pending_or_held_sources(sharing, action, source_state):
    env = sharing
    seed_share(env)
    record = env.source.records[DOCUMENT_ID]
    if source_state == "historical":
        record["is_current_version"] = False
    elif source_state == "superseded":
        env.source.records["new-revision"] = document("new-revision", revision_family_id=DOCUMENT_ID, version=2)
    elif source_state == "pending_artifact":
        record["generated_artifact_promotion_status"] = "pending_approval"
    elif source_state == "pending_status_gap":
        record["status"] = "Pending approval"
    else:
        record["content_screening"] = {"state": "pending_review", "scan_id": "held", "source_revision": "1"}
    response = invoke(env, action)
    assert response.status_code == (409 if action in {"share", "approve_share"} else 200), response.get_json()
    if action in {"share", "approve_share"}:
        assert not env.source.writes and not env.search.writes
    else:
        assert record.get("content_screening") == env.source.records[DOCUMENT_ID].get("content_screening")


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("query", [
    "group_id=group-b", "group_id=group-a&group_id=group-b", "target_group_id=source-group",
    "expected_etag=forged", "document_id=document-b", "group_ids=group-a", "unexpected=1",
])
def test_mutation_query_overrides_are_rejected_before_any_effect(sharing, action, query):
    env = sharing
    seed_share(env)
    response = invoke(env, action, query_string=query)
    assert response.status_code == 400, response.get_json()
    assert not env.source.writes and not env.search.queries


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("body", [
    None, [], {}, {"expected_etag": ""}, {"expected_etag": " padded "},
    {"expected_etag": 7}, {"expected_etag": "etag-document-a", "group_id": "group-b"},
    {"expected_etag": "etag-document-a", "document_id": "document-b"},
    {"expected_etag": "etag-document-a", "document_collaboration_actions": ["share"]},
])
def test_mutation_bodies_are_explicit_and_allowlisted(sharing, action, body):
    env = sharing
    seed_share(env)
    payload = deepcopy(body)
    if action == "share" and isinstance(payload, dict):
        payload["target_group_id"] = "group-b"
    response = invoke(env, action, json=payload)
    assert response.status_code == 400, response.get_json()
    assert not env.source.writes and not env.search.writes


@pytest.mark.parametrize("suffix,method,body", [
    ("share", "POST", '{"expected_etag":"etag-document-a","target_group_id":"source-group","target_group_id":"group-b"}'),
    ("share/group-b", "DELETE", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
    ("approve-share", "POST", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
    ("received-share", "DELETE", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
    ("artifact/approve", "POST", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
    ("artifact/reject", "POST", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
    ("artifact/cancel", "POST", '{"expected_etag":"forged","expected_etag":"etag-document-a"}'),
])
def test_duplicate_json_fields_cannot_change_the_captured_target_or_etag(sharing, suffix, method, body):
    env = sharing
    seed_share(env)
    group_id = "group-b" if suffix in {"approve-share", "received-share"} else "group-a"
    response = env.client.open(
        f"/api/groups/{group_id}/documents/{DOCUMENT_ID}/{suffix}", method=method,
        data=body, content_type="application/json",
    )
    assert response.status_code == 400, response.get_json()
    assert not env.source.writes and not env.search.writes


@pytest.mark.parametrize("target", ["group-a", "", " group-b", ".", "..", "group/b", "group\\b", "group-b,approved", None, []])
def test_share_target_must_be_explicit_valid_and_not_self(sharing, target):
    response = invoke(sharing, "share", target=target)
    assert response.status_code == 400, response.get_json()
    assert not sharing.source.writes


@pytest.mark.parametrize("action", ACTIONS)
def test_exact_path_cannot_borrow_an_unrelated_owned_or_personal_record(sharing, action):
    env = sharing
    env.source.records["foreign"] = document("foreign", "source-group")
    env.personal.records["foreign"] = document("foreign", user_id="owner")
    response = invoke(env, action, document_id="foreign")
    assert response.status_code == 404
    assert not env.source.writes and not env.search.writes


@pytest.mark.parametrize("action,group_id,status_code", [
    ("share", "group-b", 403), ("unshare", "group-b", 403),
    ("approve_share", "group-a", 400), ("remove_share", "group-a", 400),
])
def test_owner_and_recipient_authority_are_not_interchangeable(sharing, action, group_id, status_code):
    seed_share(sharing)
    response = invoke(sharing, action, group_id=group_id, target="source-group")
    assert response.status_code == status_code
    assert not sharing.source.writes


@pytest.mark.parametrize("action", ACTIONS)
def test_successful_receipts_and_projections_change_only_the_exact_revision_and_recipient(sharing, action):
    env = sharing
    if action != "share":
        seed_share(env)
    seed_share(env, "approved", target="source-group")
    env.source.records["old"] = document("old", revision_family_id=DOCUMENT_ID, is_current_version=False)
    others = {key: deepcopy(item) for key, item in env.source.records.items() if key != DOCUMENT_ID}
    before = deepcopy(env.source.records[DOCUMENT_ID])
    response = invoke(env, action)
    assert_receipt(response, action)
    current = env.source.records[DOCUMENT_ID]
    assert all(env.source.records[key] == value for key, value in others.items())
    assert "source-group,approved" in current["shared_group_ids"]
    assert current["document_share_details"]["groups"]["source-group"] == before["document_share_details"]["groups"]["source-group"]
    assert all(current[key] == before[key] for key in ("group_id", "user_id", "version", "file_name", "title", "abstract"))
    assert current[OPERATION]["phase"] == "complete"
    assert set(current[OPERATION]["effects"].values()) == {"complete"}
    assert env.search.records[f"{DOCUMENT_ID}-chunk"]["shared_group_ids"] == current["shared_group_ids"]
    indexed = [item for item in env.index_container.items.values() if item.get("source_document_id") == DOCUMENT_ID]
    recipient = [item for item in indexed if item.get("scope_key") == "group:group-b"]
    assert len(recipient) == (1 if action in {"share", "approve_share"} else 0)
    if recipient:
        assert recipient[0]["access_granted"] is (action == "approve_share")
    assert {call.args[0] for call in env.invalidate_cache.call_args_list} == {"group-a", "group-b"}
    assert all(call.kwargs == {"document_id": DOCUMENT_ID, "strict": True} for call in env.invalidate_cache.call_args_list)


@pytest.mark.parametrize("action", ACTIONS)
def test_stale_etags_including_blind_repeats_never_replay_mutations(sharing, action):
    env = sharing
    if action != "share":
        seed_share(env)
    stale = env.source.records[DOCUMENT_ID]["_etag"]
    first = invoke(env, action)
    before = deepcopy(env.source.records)
    writes = len(env.search.writes), env.index_write.call_count, len(env.notices.writes)
    second = invoke(env, action, etag=stale)
    assert first.status_code == 200
    assert second.status_code in ({404} if action == "remove_share" else {409})
    assert env.source.records == before
    assert (len(env.search.writes), env.index_write.call_count, len(env.notices.writes)) == writes


@pytest.mark.parametrize("action", ["share", "approve_share", "unshare"])
def test_fresh_desired_state_repeats_do_not_reset_approval_or_duplicate_effects(sharing, action):
    env = sharing
    seed_share(env, "approved" if action == "share" else "not_approved")
    first = invoke(env, action)
    before = deepcopy(env.source.records)
    writes = len(env.search.writes), env.index_write.call_count, len(env.notices.writes)
    second = invoke(env, action)
    assert first.status_code == 200
    assert_receipt(second, action, status="unchanged", resulting_state="approved" if action != "unshare" else "removed")
    assert env.source.records == before
    assert (len(env.search.writes), env.index_write.call_count, len(env.notices.writes)) == writes


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("race", ["granted", "approved", "revoked", "deleted"])
def test_losing_conditional_claim_never_publishes_the_losers_acl(sharing, action, race):
    env = sharing
    if action != "share":
        seed_share(env)

    def concurrent_winner(operation, item, body):
        if operation != "replace" or (body or {}).get(OPERATION, {}).get("phase") != "claimed":
            return
        env.source.before_write = None
        if race == "deleted":
            del env.source.records[item]
        else:
            entries = {
                "granted": ["group-b,not_approved", "source-group,approved"],
                "approved": ["group-b,approved"], "revoked": [],
            }[race]
            env.source.change(item, shared_group_ids=entries)

    env.source.before_write = concurrent_winner
    response = invoke(env, action)
    assert response.status_code == 409, response.get_json()
    assert not env.search.writes and not env.index_write.call_count and not env.notices.writes
    assert not env.source.writes


@pytest.mark.parametrize("action", ACTIONS)
def test_pre_effect_membership_refusal_retains_a_repairable_claim(sharing, action):
    env = sharing
    if action != "share":
        seed_share(env)
    actor_group = "group-b" if action in {"approve_share", "remove_share"} else "group-a"

    def revoke_after_claim(operation, _item, body):
        if operation == "replace" and (body or {}).get(OPERATION, {}).get("phase") == "executing":
            env.source.before_write = None
            env.groups[actor_group]["owner"] = {"id": "replacement-owner"}

    env.source.before_write = revoke_after_claim
    response = invoke(env, action)
    stored = env.source.records[DOCUMENT_ID][OPERATION]
    assert response.status_code == 207, response.get_json()
    assert stored["phase"] == "repair"
    assert stored["effects"]["search"] == "pending"
    assert not env.search.writes and not env.index_write.call_count
    env.groups[actor_group]["owner"] = {"id": "owner"}
    retry = invoke(env, action)
    assert_receipt(retry, action, status="unchanged")
    assert env.source.records[DOCUMENT_ID][OPERATION]["phase"] == "complete"


@pytest.mark.parametrize("changed", ["execution_token", "id", "version", "membership"])
def test_late_search_projection_rechecks_execution_identity_and_authority(sharing, changed):
    env = sharing

    def change_after_query():
        env.search.after_query = None
        current = env.source.records[DOCUMENT_ID]
        if changed == "membership":
            env.groups["group-a"]["owner"] = {"id": "new-owner"}
        elif changed == "version":
            env.source.change(DOCUMENT_ID, version=2)
        else:
            operation = {**current[OPERATION], changed: "another-execution"}
            env.source.change(DOCUMENT_ID, **{OPERATION: operation})

    env.search.after_query = change_after_query
    response = invoke(env, "share")
    assert response.status_code in {207, 409, 503}, response.get_json()
    assert not env.search.writes
    assert not env.index_write.call_count and not env.notices.writes


@pytest.mark.parametrize("field,value", [
    ("document_id", "another-document"), ("version", 2), ("group_id", "source-group"), ("id", None),
])
def test_search_projection_must_confirm_exact_source_chunk_identity(sharing, field, value):
    env = sharing
    chunk = deepcopy(env.search.records[f"{DOCUMENT_ID}-chunk"])
    if value is None:
        chunk.pop(field)
    else:
        chunk[field] = value
    env.search.result_override = [chunk]
    response = invoke(env, "share")
    assert response.status_code == 207
    assert response.get_json()["errors"][0]["stage"] == "search"
    assert not env.search.writes and not env.index_write.call_count


def test_only_one_fresh_request_can_win_an_unexecuted_claim(sharing):
    env = sharing
    competing_responses = []

    def execute_competitor(operation, _item, body):
        if operation == "replace" and (body or {}).get(OPERATION, {}).get("phase") == "executing":
            env.source.before_write = None
            competing_responses.append(invoke(env, "share"))

    env.source.before_write = execute_competitor
    loser = invoke(env, "share")
    assert loser.status_code == 409
    assert len(competing_responses) == 1
    assert_receipt(competing_responses[0], "share", status="unchanged")
    assert env.source.records[DOCUMENT_ID][OPERATION]["phase"] == "complete"
    assert len(env.search.writes) == 1 and len(env.notices.records) == 3


@pytest.mark.parametrize("stage", ["search", "index", "cache", "notifications"])
def test_lost_effect_checkpoint_acknowledgement_never_replays_completed_work(sharing, stage):
    env = sharing
    original_replace = env.source.replace_item
    lost_ack = []

    def save_then_lose_ack(item, body, **kwargs):
        saved = original_replace(item, body, **kwargs)
        operation = body.get(OPERATION, {})
        if not lost_ack and operation.get("phase") == "executing" and operation.get("effects", {}).get(stage) == "complete":
            lost_ack.append(True)
            raise ServiceResponseError(PRIVATE)
        return saved

    env.scoped_monkeypatch.setattr(env.source, "replace_item", save_then_lose_ack)
    first = invoke(env, "share")
    checkpoint = deepcopy(env.source.records[DOCUMENT_ID][OPERATION])
    writes = len(env.search.writes), env.index_write.call_count, len(env.notices.records)
    refreshed = state(env)
    repeated = invoke(env, "share")
    assert lost_ack == [True]
    assert first.status_code == 207, first.get_json()
    assert checkpoint["effects"][stage] == "complete"
    assert checkpoint["phase"] == "uncertain"
    assert refreshed.get_json()["actions"] == ["inspect"]
    assert repeated.status_code == 409
    assert (len(env.search.writes), env.index_write.call_count, len(env.notices.records)) == writes


@pytest.mark.parametrize("action", [None, *ACTIONS])
def test_membership_lost_after_the_source_snapshot_refuses_access_before_mutation(sharing, action):
    env = sharing
    seed_share(env)
    selected = "group-b" if action in {"approve_share", "remove_share"} else "group-a"
    env.source.after_read = lambda _item: env.groups[selected].update(owner={"id": "replacement"})
    response = state(env) if action is None else invoke(env, action)
    assert response.status_code == 403
    assert not env.source.writes and not env.search.writes


@pytest.mark.parametrize("stage", ["search", "index", "cache", "notifications"])
@pytest.mark.parametrize("failure_type", [ServiceRequestError, ServiceResponseError, TimeoutError])
def test_ambiguous_effects_keep_the_claim_uncertain_and_never_replay(sharing, stage, failure_type):
    env = sharing
    failure = failure_type(PRIVATE)
    if stage == "search":
        wrapped = RuntimeError("Search transport wrapper")
        wrapped.__cause__ = failure
        env.search.failure = wrapped
    elif stage == "index":
        env.index_write.side_effect = failure
    elif stage == "cache":
        env.cache.failure = failure
    else:
        env.notices.failure = failure
    first = invoke(env, "share")
    first_body = first.get_json()
    stored = env.source.records[DOCUMENT_ID][OPERATION]
    writes = len(env.search.writes), env.index_write.call_count, len(env.notices.attempts)
    env.search.failure = env.cache.failure = env.notices.failure = None
    env.index_write.side_effect = None
    env.source.records[DOCUMENT_ID][OPERATION]["created_at"] = "2000-01-01T00:00:00Z"
    fresh = state(env)
    retry = invoke(env, "share")
    assert first.status_code == 207, first_body
    assert first_body["status"] == "partial" and first_body["errors"][0]["stage"] == stage
    assert PRIVATE not in str(first_body)
    assert stored["phase"] == "uncertain"
    assert fresh.get_json()["actions"] == ["inspect"]
    assert retry.status_code == 409
    assert (len(env.search.writes), env.index_write.call_count, len(env.notices.attempts)) == writes


@pytest.mark.parametrize("stage", ["search", "index", "cache", "notifications"])
def test_known_effect_failure_repairs_only_unfinished_stages(sharing, stage):
    env = sharing
    failure = StoreFailure(403)
    if stage == "search":
        env.search.failure = failure
    elif stage == "index":
        env.index_write.side_effect = failure
    elif stage == "cache":
        env.cache.failure = failure
    else:
        env.notices.failure = failure
    first = invoke(env, "share")
    completed = deepcopy(env.source.records[DOCUMENT_ID][OPERATION])
    writes = len(env.search.writes), env.index_write.call_count
    env.search.failure = env.cache.failure = env.notices.failure = None
    env.index_write.side_effect = None
    second = invoke(env, "share")
    assert first.status_code == 207
    assert completed["phase"] == "repair"
    assert_receipt(second, "share", status="unchanged")
    assert env.source.records[DOCUMENT_ID][OPERATION]["phase"] == "complete"
    if stage != "search":
        assert len(env.search.writes) == writes[0]
    if stage in {"cache", "notifications"}:
        assert env.index_write.call_count == writes[1]


@pytest.mark.parametrize("status,expected", [("not_approved", "denied"), ("approved", "removed")])
def test_terminal_recipient_repairs_are_private_exact_and_disappear_when_complete(sharing, status, expected):
    env = sharing
    seed_share(env, status)
    seed_share(env, "approved", target="source-group")
    env.source.records[DOCUMENT_ID]["abstract"] = PRIVATE
    env.cache.failure = StoreFailure(403)
    removal = invoke(env, "remove_share")
    inspect = state(env, "group-b")
    body = inspect.get_json()
    ordinary = get(env, f"/api/group_documents/{DOCUMENT_ID}", group_id="group-b")
    env.cache.failure = None
    retry = invoke(env, "remove_share")
    finished = state(env, "group-b")
    assert removal.status_code == 207
    assert inspect.status_code == 200 and set(body) == SHARING_FIELDS
    assert body["relationship"] == expected
    assert body["recipients"] == [] and body["publication"] is None
    assert body["actions"] == ["inspect", "remove_share"]
    assert PRIVATE not in inspect.get_data(as_text=True)
    assert "source-group" not in inspect.get_data(as_text=True)
    assert ordinary.status_code == 404
    assert_receipt(retry, "remove_share", status="unchanged", resulting_state=expected)
    assert finished.status_code == 404


@pytest.mark.parametrize("tamper", [
    "document_id", "document_version", "source_group_id", "target_group_id",
    "request_id", "had_relationship", "detail_document_id", "detail_document_version", "detail_request_id",
])
def test_terminal_repair_requires_complete_server_bound_tombstone_evidence(sharing, tamper):
    env = sharing
    seed_share(env)
    env.cache.failure = StoreFailure(403)
    removal = invoke(env, "remove_share")
    record = env.source.records[DOCUMENT_ID]
    if tamper.startswith("detail_"):
        record["document_share_details"]["groups"]["group-b"][tamper.removeprefix("detail_")] = "forged"
    else:
        record[OPERATION][tamper] = "forged"
    response = state(env, "group-b")
    assert removal.status_code == 207
    assert response.status_code == 404


def test_terminal_repair_does_not_grant_ordinary_members_or_revoked_managers_access(sharing):
    env = sharing
    seed_share(env)
    env.cache.failure = StoreFailure(403)
    removal = invoke(env, "remove_share")
    set_actor(env, "reader")
    reader = state(env, "group-b")
    set_actor(env, "owner")
    env.groups["group-b"]["owner"] = {"id": "replacement"}
    revoked = state(env, "group-b")
    assert removal.status_code == 207
    assert reader.status_code == 404
    assert revoked.status_code == 403


@pytest.mark.parametrize("action", ["unshare", "remove_share"])
def test_uncertain_negative_tombstone_allows_inspection_but_not_automatic_repair(sharing, action):
    env = sharing
    seed_share(env, "approved")
    env.search.failure = ServiceResponseError(PRIVATE)
    removal = invoke(env, action)
    fresh = state(env, "group-b")
    env.search.failure = None
    retry = invoke(env, "remove_share")
    assert removal.status_code == 207
    assert fresh.status_code == 200
    assert fresh.get_json()["relationship"] == "removed"
    assert fresh.get_json()["recipients"] == [] and fresh.get_json()["publication"] is None
    assert fresh.get_json()["actions"] == ["inspect"]
    assert retry.status_code == 409
    assert len(env.search.writes) == 1


def test_a_siblings_grant_cannot_supply_missing_historical_relationship_evidence(sharing):
    env = sharing
    seed_share(env, "approved")
    env.source.records["old-revision"] = document(
        "old-revision", revision_family_id=DOCUMENT_ID, is_current_version=False,
    )
    read = state(env, "group-b", "old-revision")
    approve = invoke(env, "approve_share", document_id="old-revision")
    remove = invoke(env, "remove_share", document_id="old-revision")
    assert read.status_code == approve.status_code == remove.status_code == 404
    assert not env.source.writes


def test_owner_partial_unshare_retains_same_target_repair_without_regrant(sharing):
    env = sharing
    seed_share(env, "approved")
    env.cache.failure = StoreFailure(403)
    first = invoke(env, "unshare")
    inspect = state(env)
    before = deepcopy(env.source.records[DOCUMENT_ID]["shared_group_ids"])
    wrong_target = invoke(env, "unshare", target="source-group")
    env.cache.failure = None
    retry = invoke(env, "unshare")
    assert first.status_code == 207
    assert first.get_json()["target_group_id"] == "group-b"
    assert inspect.get_json()["recipients"] == []
    assert "unshare" in inspect.get_json()["actions"]
    assert wrong_target.status_code == 409
    assert_receipt(retry, "unshare", status="unchanged")
    assert env.source.records[DOCUMENT_ID]["shared_group_ids"] == before == []


def test_sharing_state_allowlists_fields_and_hides_other_recipients_from_non_managers(sharing):
    env = sharing
    seed_share(env)
    seed_share(env, "approved", target="source-group")
    env.groups["group-b"].update(description="Recipient description", api_key=PRIVATE)
    env.source.records[DOCUMENT_ID].update(abstract=PRIVATE, content=PRIVATE)
    owner = state(env)
    recipient = state(env, "group-b")
    set_actor(env, "reader")
    member = state(env)
    for response in (owner, recipient, member):
        body = response.get_json()
        assert response.status_code == 200
        assert set(body) == SHARING_FIELDS
        assert set(body["owner_group"]) == {"id", "name"}
        assert PRIVATE not in response.get_data(as_text=True)
        assert all(set(item) == {"id", "name", "description", "approval_status"} for item in body["recipients"])
    assert {item["id"] for item in owner.get_json()["recipients"]} == {"group-b", "source-group"}
    assert [item["id"] for item in recipient.get_json()["recipients"]] == ["group-b"]
    assert member.get_json()["recipients"] == []
    assert member.get_json()["actions"] == ["inspect"]


@pytest.mark.parametrize("path,key", [
    ("/api/group_documents", "documents"),
    (f"/api/group_documents/{DOCUMENT_ID}", None),
    (f"/api/group_documents/{DOCUMENT_ID}/versions", "versions"),
])
@pytest.mark.parametrize("actor,group_id", [("owner", "group-a"), ("reader", "group-a"), ("owner", "group-b")])
def test_strict_reads_strip_private_collaboration_and_original_artifact_pointers(sharing, path, key, actor, group_id):
    env = sharing
    seed_share(env, "approved")
    seed_share(env, "approved", target="source-group")
    private_fields = {
        OPERATION, WRITER, "document_share_details", "generated_artifact_source_conversation_id",
        "generated_artifact_source_message_id", "generated_artifact_source_blob_container",
        "generated_artifact_source_blob_path", "generated_artifact_publication_receipt_id",
    }
    for field in private_fields:
        env.source.records[DOCUMENT_ID][field] = {"private": PRIVATE} if field in {OPERATION, WRITER, "document_share_details"} else PRIVATE
    env.source.records[DOCUMENT_ID]["document_collaboration_actions"] = ["forged"]
    set_actor(env, actor)
    response = get(env, path, group_id=group_id)
    body = response.get_json()
    records = body[key] if key else [body]
    record = next(item for item in records if item["id"] == DOCUMENT_ID)
    assert response.status_code == 200, body
    assert not private_fields.intersection(record)
    assert "forged" not in record["document_collaboration_actions"]
    assert PRIVATE not in response.get_data(as_text=True)
    if actor != "owner" or group_id != "group-a":
        assert record["shared_group_ids"] == (["group-b,approved"] if group_id == "group-b" else [])


def test_facets_and_tags_never_probe_private_collaboration_and_only_final_records_get_actions(sharing):
    env = sharing
    for index in range(15):
        key = f"extra-{index:02}"
        env.source.records[key] = document(key)
    actions = Mock(wraps=env.helper.get_group_document_collaboration_actions)
    env.scoped_monkeypatch.setattr(env.helper, "get_group_document_collaboration_actions", actions)
    env.scoped_monkeypatch.setattr(env.collaboration, "_publication_view", Mock(return_value=None))
    facets = get(env, "/api/group_documents/facets")
    tags = get(env, "/api/group_documents/tags")
    no_probe_count = actions.call_count
    listing = get(env, page_size=2, page=2)
    listed = listing.get_json()["documents"]
    assert facets.status_code == tags.status_code == listing.status_code == 200
    assert no_probe_count == 0
    assert actions.call_count == len(listed) == 2
    assert {call.args[0]["id"] for call in actions.call_args_list} == {item["id"] for item in listed}


def test_recipient_directory_filters_before_pagination_and_exposes_no_membership(sharing):
    env = sharing
    for index in range(25):
        key = f"target-{index:02}"
        env.groups[key] = {
            "id": key, "name": f"Eligible {index:02}", "description": f"needle {index:02}",
            "type": "group", "status": "active", "owner": {"id": PRIVATE}, "users": [PRIVATE], "api_key": PRIVATE,
        }
    env.groups["target-00"]["status"] = "locked"
    env.groups["target-01"]["status"] = "inactive"
    env.groups["target-02"]["type"] = "public"
    response = env.client.get(
        f"/api/groups/group-a/documents/{DOCUMENT_ID}/sharing/targets?search=NEEDLE&page=2&page_size=2",
    )
    body = response.get_json()
    assert response.status_code == 200, body
    assert set(body) == {"groups", "page", "page_size", "total_count"}
    assert body["total_count"] == 22 and body["page"] == 2 and body["page_size"] == 2
    assert [item["id"] for item in body["groups"]] == ["target-05", "target-06"]
    assert all(set(item) == {"id", "name", "description"} for item in body["groups"])
    assert PRIVATE not in response.get_data(as_text=True)
    env.groups["target-05"]["status"] = "locked"
    share = invoke(env, "share", target="target-05")
    assert share.status_code == 403
    assert not env.source.writes


@pytest.mark.parametrize("actor,group_id", [("reader", "group-a"), ("owner", "group-b")])
def test_sharing_directory_does_not_follow_recipient_or_ordinary_member_authority(sharing, actor, group_id):
    env = sharing
    seed_share(env, "approved")
    set_actor(env, actor)
    response = env.client.get(f"/api/groups/{group_id}/documents/{DOCUMENT_ID}/sharing/targets")
    assert response.status_code == 403
    assert not env.group_container.queries


@pytest.mark.parametrize("guard,expected_status", [
    ("logged_out", 401), ("app_role", 403), ("feature_disabled", 400),
])
def test_every_new_collaboration_route_retains_app_authentication_and_feature_guards(sharing, guard, expected_status):
    env = sharing
    if guard == "feature_disabled":
        env.settings["enable_group_workspaces"] = False
    else:
        with env.client.session_transaction() as session_state:
            session_state.clear()
            if guard == "app_role":
                session_state["user"] = {"oid": "owner", "roles": []}
    requests = [
        ("GET", "sharing"), ("GET", "sharing/targets"), ("POST", "share"),
        ("DELETE", "share/group-b"), ("POST", "approve-share"), ("DELETE", "received-share"),
        ("POST", "artifact/approve"), ("POST", "artifact/reject"), ("POST", "artifact/cancel"),
    ]
    for method, suffix in requests:
        response = env.client.open(
            f"/api/groups/group-a/documents/{DOCUMENT_ID}/{suffix}", method=method,
            json=None if method == "GET" else {"expected_etag": "etag-document-a", "target_group_id": "group-b"},
        )
        assert response.status_code == expected_status, (suffix, response.get_json())
    assert not env.source.reads and not env.source.writes


@pytest.mark.parametrize("suffix,query,body", [
    ("sharing", "group_id=group-a", None), ("sharing", "", {"group_id": "group-a"}),
    ("sharing/targets", "search=x&search=y", None), ("sharing/targets", "page=1&page=2", None),
    ("sharing/targets", "page=0", None), ("sharing/targets", "page_size=0", None),
    ("sharing/targets", "page=no", None), ("sharing/targets", "unknown=value", None),
    ("sharing/targets", "", {"target_group_id": "group-b"}),
])
def test_read_contract_rejects_duplicate_scope_pagination_and_bodies(sharing, suffix, query, body):
    response = sharing.client.get(
        f"/api/groups/group-a/documents/{DOCUMENT_ID}/{suffix}", query_string=query, json=body,
    )
    assert response.status_code == 400
    assert not sharing.source.writes


def test_pending_notices_use_current_reviewers_exact_metadata_and_native_scope_links(sharing):
    env = sharing
    env.groups["group-b"]["admins"] = ["admin", "owner", "admin"]
    env.groups["group-b"]["documentManagers"] = ["manager", "new-manager"]
    response = invoke(env, "share")
    notices = list(env.notices.records.values())
    operation = env.source.records[DOCUMENT_ID][OPERATION]
    assert_receipt(response, "share")
    assert {item["user_id"] for item in notices} == {"owner", "admin", "manager", "new-manager"}
    assert len(notices) == 4
    for notice in notices:
        assert notice["notification_type"] == "group_document_share_pending"
        assert notice["link_url"] == f"/v2/groups/group-b/documents?document_id={DOCUMENT_ID}"
        assert notice["link_context"] == {"workspace_type": "group", "group_id": "group-b", "document_id": DOCUMENT_ID}
        assert notice["metadata"] == {
            "share_scope": "group", "document_id": DOCUMENT_ID, "document_version": 1,
            "source_group_id": "group-a", "target_group_id": "group-b", "request_id": operation["request_id"],
        }
        assert "reader" not in notice["user_id"]


@pytest.mark.parametrize("action,status,notice_type", [
    ("approve_share", "not_approved", "group_document_share_approved"),
    ("remove_share", "not_approved", "group_document_share_denied"),
    ("remove_share", "approved", "group_document_share_removed"),
    ("unshare", "not_approved", None),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_decisions_clean_only_exact_pending_generation_and_send_the_correct_audience(sharing, action, status, notice_type, legacy):
    env = sharing
    seed_share(env, status, legacy=legacy)
    metadata = {
        "share_scope": "group", "document_id": DOCUMENT_ID, "source_group_id": "group-a",
        "target_group_id": "group-b", "document_version": 1, "request_id": "request-group-b",
    }
    if legacy:
        metadata.pop("request_id")
        metadata.pop("document_version")
    records = {
        "matching": metadata,
        "other-document": {**metadata, "document_id": "document-b"},
        "other-source": {**metadata, "source_group_id": "other-source"},
        "other-target": {**metadata, "target_group_id": "source-group"},
        "other-request": {**metadata, "request_id": "other-generation"},
        "other-version": {**metadata, "document_version": 2},
        "null-request": {**metadata, "request_id": None},
        "null-version": {**metadata, "document_version": None},
    }
    for key, fields in records.items():
        env.notices.records[key] = {
            "id": key, "user_id": "reviewer", "notification_type": "group_document_share_pending", "metadata": fields,
        }
    env.notices.records["other-type"] = {
        **env.notices.records["matching"], "id": "other-type", "notification_type": "approval_request_pending",
    }
    response = invoke(env, action)
    assert response.status_code == 200, response.get_json()
    assert "matching" not in env.notices.records
    assert set(records).difference({"matching"}).issubset(env.notices.records)
    assert "other-type" in env.notices.records
    feedback = [item for key, item in env.notices.records.items() if key not in records and key != "other-type"]
    assert len(feedback) == (1 if notice_type else 0)
    if feedback:
        assert feedback[0]["notification_type"] == notice_type
        assert feedback[0]["user_id"] == "sharer"
        assert feedback[0]["link_context"] == {"workspace_type": "group", "group_id": "group-a", "document_id": DOCUMENT_ID}


def test_legacy_feedback_uses_owner_fallback_and_removed_type_registry(sharing):
    env = sharing
    seed_share(env, "approved", legacy=True)
    env.source.records[DOCUMENT_ID]["document_share_details"]["groups"]["group-b"].pop("shared_by_user_id")
    response = invoke(env, "remove_share")
    notices = list(env.notices.records.values())
    presentation = env.notifications._get_notification_type_config(notices[0])
    assert_receipt(response, "remove_share", resulting_state="removed")
    assert notices[0]["user_id"] == "owner"
    assert notices[0]["notification_type"] == "group_document_share_removed"
    assert presentation == {"icon": "bi-folder-minus", "color": "info"}
    assert notices[0]["assignment"] is None and notices[0]["scope"] == "personal"


def test_notification_retry_preserves_existing_read_state_and_creates_no_duplicates(sharing):
    env = sharing
    attempts = []

    def fail_second_create(operation, _item, body):
        if operation == "create":
            attempts.append(body["user_id"])
            if len(attempts) == 2:
                raise StoreFailure(403)

    env.notices.before_write = fail_second_create
    first = invoke(env, "share")
    delivered_id = next(iter(env.notices.records))
    env.notices.records[delivered_id].update(read_by=["admin"], dismissed_by=["admin"])
    delivered = deepcopy(env.notices.records[delivered_id])
    env.notices.before_write = None
    retry = invoke(env, "share")
    assert first.status_code == 207
    assert_receipt(retry, "share", status="unchanged")
    assert len(env.notices.records) == 3
    assert env.notices.records[delivered_id] == delivered
    assert len(env.search.writes) == 1


def test_notifications_reauthorize_before_each_delivery_in_a_longer_effect(sharing):
    env = sharing
    delivered = []

    def revoke_on_first_notice(operation, _item, body):
        if operation == "create":
            delivered.append(body["user_id"])
            env.groups["group-a"]["owner"] = {"id": "replacement-owner"}

    env.notices.before_write = revoke_on_first_notice
    response = invoke(env, "share")
    assert response.status_code == 207
    assert len(delivered) == 1
    assert env.source.records[DOCUMENT_ID][OPERATION]["phase"] == "repair"
    assert env.source.records[DOCUMENT_ID][OPERATION]["effects"]["notifications"] == "pending"


def test_reviewers_removed_during_notification_delivery_do_not_receive_new_notices(sharing):
    env = sharing

    def remove_later_reviewer(operation, _item, _body):
        if operation == "create":
            env.groups["group-b"]["documentManagers"] = []

    env.notices.before_write = remove_later_reviewer
    response = invoke(env, "share")
    assert_receipt(response, "share")
    assert {item["user_id"] for item in env.notices.records.values()} == {"admin", "owner"}


def test_unknown_notification_create_acknowledgement_is_not_a_replayable_refusal(sharing):
    env = sharing
    original_create = env.notices.create_item

    def save_then_lose_ack(body):
        original_create(body)
        raise ServiceResponseError(PRIVATE)

    env.scoped_monkeypatch.setattr(env.notices, "create_item", save_then_lose_ack)
    first = invoke(env, "share")
    env.scoped_monkeypatch.setattr(env.notices, "create_item", original_create)
    retry = invoke(env, "share")
    assert first.status_code == 207
    assert env.source.records[DOCUMENT_ID][OPERATION]["phase"] == "uncertain"
    assert retry.status_code == 409
    assert len(env.notices.records) == 1


def test_notification_cleanup_reauthorizes_before_each_delete(sharing):
    env = sharing
    seed_share(env)
    metadata = {
        "share_scope": "group", "document_id": DOCUMENT_ID, "document_version": 1,
        "source_group_id": "group-a", "target_group_id": "group-b", "request_id": "request-group-b",
    }
    for user in ("admin", "manager"):
        env.notices.records[user] = {
            "id": user, "user_id": user, "notification_type": "group_document_share_pending", "metadata": metadata,
        }

    def revoke_after_first_delete(operation, _item, _body):
        if operation == "delete":
            env.groups["group-a"]["owner"] = {"id": "replacement"}

    env.notices.before_write = revoke_after_first_delete
    response = invoke(env, "unshare")
    assert response.status_code == 207
    assert len(env.notices.records) == 1
    assert env.source.records[DOCUMENT_ID][OPERATION]["effects"]["notifications"] == "pending"


def test_cache_cleanup_reaches_all_scope_results_without_touching_unrelated_entries(sharing):
    env = sharing
    seed_share(env, "approved")
    env.cache.records.update({
        key: {"id": key, "user_id": f"viewer-{key}", "doc_scope": scope, "results": results}
        for key, scope, results in [
            ("source", "group:group-a", []), ("recipient", "group:group-b", []),
            ("all-document", "all", [{"document_id": DOCUMENT_ID}]),
            ("all-source", "all", [{"source_document_id": DOCUMENT_ID}]),
            ("all-proof", "all", [{"screening_provenance": {"document_id": DOCUMENT_ID}}]),
            ("unrelated", "all", [{"document_id": "document-b"}]),
        ]
    })
    response = invoke(env, "unshare")
    assert_receipt(response, "unshare")
    assert set(env.cache.records) == {"unrelated"}
    assert all(kwargs.get("enable_cross_partition_query") is True for _query, _parameters, kwargs in env.cache.queries)


def test_strict_transport_reporting_preserves_legacy_fail_open_defaults(sharing):
    env = sharing
    env.notices.failure = ServiceResponseError(PRIVATE)
    ordinary_notice = env.notifications.create_notification(
        user_id="owner", notification_type="group_document_share_pending",
        idempotency_key="legacy-optional",
    )
    with pytest.raises(ServiceResponseError):
        env.notifications.create_notification(
            user_id="owner", notification_type="group_document_share_pending",
            idempotency_key="required-notice", strict=True,
        )
    env.index_write.side_effect = ServiceResponseError(PRIVATE)
    source = {"id": "personal-document", "user_id": "owner", "file_name": "owned.pdf", "version": 1}
    ordinary_index = env.index.sync_document_access_index_for_document_fail_open(source)
    with pytest.raises(env.index.DocumentAccessIndexProjectionMutationError) as raised:
        env.index.sync_document_access_index_for_document_fail_open(source, raise_on_error=True)
    assert ordinary_notice is None
    assert ordinary_index["success"] is False and ordinary_index["status"] == "repair_required"
    assert isinstance(raised.value.__cause__, ServiceResponseError)


@pytest.mark.parametrize("action", ACTIONS)
def test_projection_writer_claim_blocks_new_collaboration_before_source_cas(sharing, action):
    env = sharing
    if action != "share":
        seed_share(env)
    env.source.records[DOCUMENT_ID][WRITER] = {
        "schema_version": 1, "state": "uncertain", "token": "existing-writer",
        "document_id": DOCUMENT_ID, "group_id": "group-a", "document_version": 1,
        "started_at": "2000-01-01T00:00:00Z",
    }
    response = invoke(env, action)
    assert response.status_code == 409
    assert not env.source.writes and not env.search.writes and not env.index_write.call_count


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), *sys.argv[1:]]))
