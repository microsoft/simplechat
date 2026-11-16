# test_conversation_references.py
"""Runtime tests for private conversation evidence.

Version: 0.261.381
Implemented in: 0.261.381

Validate real service boundaries with SDK-shaped storage, without cloud bootstrap.
"""

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_conversation_references import (
    ConversationReferenceError,
    ConversationReferenceService,
    is_private_owned_conversation,
    normalize_conversation_references,
)
from test_support.m365 import CosmosContainer


class ReferenceContainer(CosmosContainer):
    """SDK-default point responses with query evaluation for this service's bounded SQL."""

    def __init__(self, partition_field):
        super().__init__(partition_field)
        self.queries = []
        self.after_query = None

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False, max_item_count=100):
        values = {item["name"]: item["value"] for item in parameters or []}
        self.queries.append((query, values, partition_key))
        rows = copy.deepcopy(list(self.items.values()))
        if partition_key is not None:
            rows = [row for row in rows if row[self.partition_field] == partition_key]
        elif not enable_cross_partition_query:
            raise AssertionError("Unscoped query")
        if "@user_id" in values:
            rows = [row for row in rows if row.get("user_id") == values["@user_id"]]
        if "@id" in values:
            rows = [row for row in rows if row.get("conversation_id") == values["@id"]]
        if "@query" in values:
            rows = [row for row in rows if values["@query"] in row.get("title", "").lower()]
        if "@message_ids" in values:
            rows = [row for row in rows if row["id"] in values["@message_ids"]]
        field = "timestamp" if partition_key else "last_updated"
        rows.sort(key=lambda row: row.get(field, ""), reverse=True)
        top = re.search(r"SELECT TOP (\d+)", query)
        if top:
            rows = rows[:int(top[1])]
        if "@offset" in values:
            rows = rows[values["@offset"]:values["@offset"] + values["@limit"]]
        if self.after_query:
            self.after_query()
        return rows


@pytest.fixture
def setup():
    conversations = ReferenceContainer("id")
    messages = ReferenceContainer("conversation_id")
    for identifier in ("source", "target"):
        conversations.create_item({
            "id": identifier, "user_id": "owner", "title": f"Title {identifier}",
            "chat_type": "personal_single_user", "last_updated": "2026-01-01",
            "tags": [{"category": "participant", "user_id": "owner"}],
        })
    messages.create_item({"id": "message-1", "conversation_id": "source", "role": "user", "timestamp": "2026-01-01", "content": "The project budget is 4500."})
    service = ConversationReferenceService(conversations, messages, project_messages=lambda rows: rows)
    return service, conversations, messages


def refs(identifier="source", **kwargs):
    return [{"kind": "conversation", "id": identifier, **kwargs}]


def test_sdk_read_is_normalized_and_owner_tag_is_not_sharing(setup):
    service, conversations, _ = setup
    raw = conversations.read_item("source", "source")
    owned = service.authorize("owner", "source")
    assert isinstance(raw, CosmosDict)
    assert type(owned) is dict and owned["_etag"] == raw["_etag"]
    assert is_private_owned_conversation(owned, "owner")


@pytest.mark.parametrize("changes", [
    {"user_id": "foreign"}, {"collaboration_conversation_id": "shared"},
    {"conversation_kind": "collaboration_source"}, {"chat_type": "personal_multi_user"},
    {"chat_type": "group"}, {"chat_type": "public"}, {"is_deleted": True},
    {"tags": [{"category": "participant", "user_id": "another"}]},
    {"scope": {"type": "group"}}, {"shared_with": ["another"]},
])
def test_ineligible_source_refused_before_message_read(setup, changes):
    service, conversations, messages = setup
    source = conversations.read_item("source", "source")
    conversations.upsert_item({**source, **changes})
    with pytest.raises(ConversationReferenceError) as error:
        service.resolve("owner", refs())
    assert error.value.status_code == 404
    assert not messages.queries


@pytest.mark.parametrize("raw", ["source", ["source"], [{}], [{"kind": "document", "id": "source"}], refs("../escape"), refs() * 2, refs(message_ids=[False]), refs() * 6])
def test_reference_contract_rejects_untrusted_shapes(raw):
    with pytest.raises(ConversationReferenceError):
        normalize_conversation_references(raw)


def test_visible_projection_precedes_matching_and_snippets(setup):
    service, _, messages = setup
    hidden = [
        {"metadata": {"masked": True}}, {"metadata": {"is_deleted": True}},
        {"metadata": {"thread_info": {"active_thread": False}}},
        {"metadata": {"is_generated_chat_artifact": True}},
        {"metadata": {"chat_content_checks": {"decision": "block"}}},
        {"metadata": {"content_moderation": {"removed": True}}},
        {"role": "assistant_artifact"}, {"role": "system"}, {"role": "file"},
    ]
    for index, changes in enumerate(hidden):
        messages.create_item({"id": f"hidden-{index}", "conversation_id": "source", "role": "assistant", "timestamp": "2026-02-01", "content": "uniquesecret", **changes})
    messages.create_item({"id": "range", "conversation_id": "source", "role": "assistant", "timestamp": "2026-03-01", "content": "safe uniquesecret end", "metadata": {"masked_ranges": [{"start": 5, "end": 17}]}})
    searched = service.search("owner", "uniquesecret", search_content=True)
    evidence = service.resolve("owner", refs(), query="uniquesecret")
    assert searched["conversations"] == []
    assert "uniquesecret" not in json.dumps(evidence)
    assert {row["message_id"] for row in evidence["excerpts"]} == {"range", "message-1"}


def test_deleted_selected_message_fails_instead_of_widening(setup):
    service, _, _ = setup
    with pytest.raises(ConversationReferenceError) as error:
        service.resolve("owner", refs(message_ids=["not-available"]))
    assert error.value.code == "conversation_evidence_unavailable"


def test_self_reference_and_unowned_destination_are_refused(setup):
    service, _, messages = setup
    with pytest.raises(ConversationReferenceError):
        service.resolve("owner", refs(), destination_id="source")
    with pytest.raises(ConversationReferenceError):
        service.resolve("foreign", refs(), destination_id="target")
    assert not messages.queries


def test_source_sharing_during_read_revokes_result(setup):
    service, conversations, messages = setup
    def share():
        source = conversations.read_item("source", "source")
        conversations.upsert_item({**source, "collaboration_conversation_id": "shared"})
    messages.after_query = share
    with pytest.raises(ConversationReferenceError):
        service.resolve("owner", refs())


def test_runtime_policy_projection_runs_before_evidence(setup):
    _, conversations, messages = setup
    called = []
    def project(rows):
        called.append(len(rows))
        return []
    service = ConversationReferenceService(conversations, messages, project_messages=project)
    with pytest.raises(ConversationReferenceError):
        service.resolve("owner", refs())
    assert called == [1]


def test_bounded_scan_and_prompt_report_partial_coverage(setup):
    service, _, messages = setup
    for index in range(205):
        messages.create_item({"id": f"long-{index}", "conversation_id": "source", "role": "assistant", "timestamp": f"2026-{index:04d}", "content": "budget " + "x" * 1800})
    result = service.resolve("owner", refs(), query="budget", max_tokens=4000)
    assert result["partial"]
    assert len(result["prompt"].encode("utf-8")) <= 4000
    assert 0 < len(result["excerpts"]) < 200
    assert all("TOP 201" in query for query, _, _ in messages.queries)


def test_authorized_search_is_paged_and_parameterized(setup):
    service, conversations, _ = setup
    for index in range(15):
        conversations.create_item({"id": f"c-{index}", "user_id": "owner", "title": "needle", "last_updated": "2026-05-01"})
    result = service.search("owner", "needle", limit=10)
    assert len(result["conversations"]) == 10
    assert result["has_more"] and result["next_offset"] == 10
    query, parameters, _ = conversations.queries[-1]
    assert "needle" not in query and parameters["@query"] == "needle"
    assert parameters["@user_id"] == "owner" and parameters["@limit"] == 11


def test_reference_refresh_changes_revision_without_copying_raw_metadata(setup):
    service, _, messages = setup
    before = service.resolve("owner", refs())
    message = messages.read_item("message-1", "source")
    messages.upsert_item({**message, "content": "Budget is now 6000.", "metadata": {"secret": "never-copy"}})
    after = service.resolve("owner", refs())
    assert before["revision"] != after["revision"]
    assert "never-copy" not in json.dumps(after)


def test_small_and_invalid_budgets_are_not_silently_expanded(setup):
    service, _, _ = setup
    for value in (0, -1, 511, 4001, True, "4000"):
        with pytest.raises(ConversationReferenceError):
            service.resolve("owner", refs(), max_tokens=value)


def test_http_routes_search_and_resolve_with_no_store_headers(setup):
    import werkzeug
    from flask import Blueprint, Flask, jsonify, request
    from functions_conversation_references import ConversationReferenceError

    if not hasattr(werkzeug, "__version__"):
        werkzeug.__version__ = "3"

    service, _, _ = setup
    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = Blueprint("conversations_test", __name__)

    def reference_error_response(error):
        if isinstance(error, ConversationReferenceError):
            return jsonify({"error": error.public_message, "code": error.code}), error.status_code
        return jsonify({"error": "Conversation reference is unavailable.", "code": "conversation_reference_unavailable"}), 503

    @bp.route("/api/conversation-references", methods=["GET"])
    def search_route():
        try:
            search_content = request.args.get("search_content", "false")
            if search_content not in ("true", "false"):
                raise ConversationReferenceError()
            payload = service.search(
                "owner",
                request.args.get("query", ""),
                offset=request.args.get("offset", "0"),
                limit=request.args.get("limit", "10"),
                search_content=search_content == "true",
                exclude_conversation_id=request.args.get("exclude_conversation_id"),
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as error:
            return reference_error_response(error)

    @bp.route("/api/conversation-references/resolve", methods=["POST"])
    def resolve_route():
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ConversationReferenceError()
            payload = service.resolve(
                "owner",
                data.get("conversation_references"),
                data.get("query", ""),
                destination_id=data.get("destination_conversation_id"),
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as error:
            return reference_error_response(error)

    app.register_blueprint(bp)
    with app.test_client() as client:
        search_res = client.get("/api/conversation-references?query=Title&exclude_conversation_id=target")
        assert search_res.status_code == 200
        assert search_res.headers.get("Cache-Control") == "no-store"
        search_json = search_res.get_json()
        assert [row["id"] for row in search_json["conversations"]] == ["source"]

        bad_bool = client.get("/api/conversation-references?search_content=maybe")
        assert bad_bool.status_code == 400

        resolve_res = client.post(
            "/api/conversation-references/resolve",
            json={
                "conversation_references": [{"kind": "conversation", "id": "source"}],
                "query": "budget",
                "destination_conversation_id": "target",
            },
        )
        assert resolve_res.status_code == 200
        assert resolve_res.headers.get("Cache-Control") == "no-store"
        resolved = resolve_res.get_json()
        assert resolved["references"][0]["id"] == "source"
        assert resolved["excerpts"][0]["message_id"] == "message-1"

        self_res = client.post(
            "/api/conversation-references/resolve",
            json={
                "conversation_references": [{"kind": "conversation", "id": "source"}],
                "destination_conversation_id": "source",
            },
        )
        assert self_res.status_code == 400



if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
