# test_document_source_scope_identity.py
"""
Regression tests for chat-associated workspace source identity.
Version: 0.261.347
Implemented in: 0.261.347

Real retrieval, source authorization, Analyze and Compare consume SDK-shaped
storage responses. A conversation association must not become a workspace ID.
Only external document/chunk, membership, model and result-storage I/O is doubled.
"""

from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from content_screening import access
from content_screening.contracts import DocumentHeldError, ScreeningConflictError
from test_orchestration_dependency_runtime import (  # noqa: F401 - shared offline runtime fixture
    binding,
    compose,
    execute,
    runtime,
    source_input,
)
from test_support import document_analysis as sources
from test_support.orchestration_research import document_action_policy_module
from test_support.orchestration_revisions import AtomicMemoryContainer


UPLOAD_CONVERSATION = "upload-conversation"
CURRENT_CONVERSATION = "conversation-1"


@contextmanager
def source_world(monkeypatch, scope, *, associated=True, shared=False):
    scope_id = {"personal": sources.USER_ID, "group": "reading-group", "public": "public-workspace"}[scope]
    owner_scope_id = "owning-group" if shared else scope_id
    documents = {
        document_id: sources.original_document(document_id, [text], scope, owner_scope_id)
        for document_id, text in (
            ("policy-old", "Threshold: 125000. Review: 10 days. The service owner is Mira. Marker: POLICY-ALPHA."),
            ("policy-new", "Threshold: 150000. Review: 7 days. The service owner is Mira. Marker: POLICY-BETA."),
        )
    }
    for value in documents.values():
        if associated:
            value["document"]["conversation_id"] = UPLOAD_CONVERSATION
        if shared:
            value["document"]["shared_group_ids"] = [f"{scope_id},approved"]

    with sources.document_analysis_runtime(documents) as native:
        with monkeypatch.context() as patcher:
            config = sys.modules["config"]
            containers = {}
            for source_scope in ("personal", "group", "public"):
                container = AtomicMemoryContainer("id")
                containers[source_scope] = container
                name = f"cosmos_{'user' if source_scope == 'personal' else source_scope}_documents_container"
                patcher.setattr(config, name, container)
            for value in documents.values():
                saved = containers[scope].upsert_item(value["document"])
                value["document"]["_etag"] = saved["_etag"]
            groups = sys.modules["functions_group"]
            memberships = {scope_id}

            def require_membership(user_id, group_id, **kwargs):
                if user_id != sources.USER_ID or group_id not in memberships:
                    raise PermissionError("Membership denied by the source fixture.")

            patcher.setattr(groups, "assert_group_role", require_membership)
            patcher.setattr(groups, "get_user_groups", lambda user_id: [{"id": key} for key in memberships])
            patcher.setitem(sys.modules, "functions_document_actions", document_action_policy_module())
            comparison = importlib.import_module("functions_document_comparison")
            patcher.setattr(comparison, "run_document_analysis", native.producer.run_document_analysis)
            # Search imports these external-I/O functions by value.
            patcher.setattr(native.search, "get_user_groups", groups.get_user_groups)
            patcher.setattr(native.search, "cosmos_conversations_container", AtomicMemoryContainer("id"))
            patcher.setattr(native.search, "cosmos_messages_container", AtomicMemoryContainer("conversation_id"))
            manifest = [
                {
                    "document_id": document_id, "scope": scope, "scope_id": scope_id,
                    "source_kind": "narrative", "file_name": value["document"]["file_name"],
                    "source_version": 1, "source_revision": value["document"]["_etag"],
                    "authorization_status": "authorized",
                }
                for document_id, value in documents.items()
            ]
            yield SimpleNamespace(
                native=native, comparison=comparison, documents=documents, containers=containers,
                scope=scope, scope_id=scope_id, manifest=manifest, memberships=memberships,
                options={
                    "doc_scope": scope, "active_group_ids": [scope_id] if scope == "group" else None,
                    "active_public_workspace_id": [scope_id] if scope == "public" else None,
                    "conversation_id": CURRENT_CONVERSATION,
                },
            )


def read_payload(world, document_id="policy-old"):
    return world.native.search.get_document_chunks_payload(
        document_id, sources.USER_ID, **world.options,
    )


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("associated", [False, True])
def test_workspace_scope_is_not_its_upload_conversation(monkeypatch, scope, associated):
    with source_world(monkeypatch, scope, associated=associated) as world, access.strict_source_authority():
        payload = read_payload(world)
        built = world.native.results.build_analysis_source(
            "policy-old", payload, source_snapshot=world.manifest[0],
        )
        assert payload["scope"] == built["scope"] == scope
        assert payload["scope_id"] == built["scope_id"] == world.scope_id
        assert payload["conversation_id"] == (UPLOAD_CONVERSATION if associated else None)
        assert payload["document"][access.PROVENANCE_FIELD]["scope_id"] == world.scope_id


def test_approved_shared_group_keeps_the_authorized_access_path(monkeypatch):
    with source_world(monkeypatch, "group", shared=True) as world, access.strict_source_authority():
        payload = read_payload(world)
        built = world.native.results.build_analysis_source(
            "policy-old", payload, source_snapshot=world.manifest[0],
        )
        assert payload["scope_id"] == built["scope_id"] == "reading-group"
        assert payload["document"][access.PROVENANCE_FIELD]["scope_id"] == "owning-group"
        world.memberships.clear()
        with pytest.raises((LookupError, PermissionError)):
            read_payload(world)


def test_personal_share_keeps_owner_not_actor_identity(monkeypatch):
    with source_world(monkeypatch, "personal") as world, access.strict_source_authority():
        document = world.documents["policy-old"]["document"]
        document.update(user_id="source-owner", shared_user_ids=[f"{sources.USER_ID},approved"])
        world.containers["personal"].upsert_item(document)
        payload = read_payload(world)
        assert payload["scope"] == "personal"
        assert payload["scope_id"] == payload["document"]["user_id"] == "source-owner"


def test_actual_chat_source_keeps_its_authorized_conversation(monkeypatch):
    with source_world(monkeypatch, "personal") as world, access.strict_source_authority():
        conversations = AtomicMemoryContainer("id")
        conversations.upsert_item({"id": CURRENT_CONVERSATION, "user_id": sources.USER_ID})
        messages = AtomicMemoryContainer("conversation_id")
        messages.upsert_item({
            "id": "chat-file", "conversation_id": CURRENT_CONVERSATION,
            "role": "file", "filename": "chat-only.txt", "file_content": "An original chat-only attachment.",
        })
        monkeypatch.setattr(world.native.search, "cosmos_conversations_container", conversations)
        monkeypatch.setattr(world.native.search, "cosmos_messages_container", messages)
        payload = read_payload(world, "chat-file")
        assert payload["scope"] == "chat"
        assert payload["scope_id"] == payload["conversation_id"] == CURRENT_CONVERSATION
        assert payload["document"]["source_type"] == "chat_upload"
        with pytest.raises(LookupError):
            world.native.search.get_document_chunks_payload(
                "chat-file", "not-the-owner", **world.options,
            )


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_linked_workspace_upload_resolves_as_workspace_not_chat(monkeypatch, scope):
    with source_world(monkeypatch, scope) as world, access.strict_source_authority():
        def no_chat_fallback(*args, **kwargs):
            raise AssertionError("A resolved workspace document must not fall back to a chat blob.")

        monkeypatch.setattr(world.native.search, "_resolve_chat_upload_context", no_chat_fallback)
        payload = read_payload(world)
        assert payload["scope"] == scope
        assert payload["scope_id"] == world.scope_id
        assert payload["document"]["source_type"] == "workspace_document"


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_explicit_analyze_accepts_chat_association_without_changing_source_identity(monkeypatch, scope):
    with source_world(monkeypatch, scope) as world, access.strict_source_authority():
        client = sources.FixtureAnalysisClient()
        result = world.native.producer.run_document_analysis(
            sources.USER_ID, "Identify the service owner.", ["policy-old"], client.invoke_prompt,
            result_version="analyze-final-v1", source_manifest=[world.manifest[0]],
            **world.options,
        )
        assert result["analysis_validation"]["status"] == "valid"
        assert result["analysis_sources"][0]["scope_id"] == world.scope_id
        assert result["authoritative_result"]["value"][0]["values"] == {"owner": "Mira"}
        assert len(client.calls) == 1
        assert "POLICY-ALPHA" in client.calls[0]["prompt"]


def test_analyze_still_refuses_a_different_manifest_scope(monkeypatch):
    with source_world(monkeypatch, "group") as world, access.strict_source_authority():
        payload = read_payload(world)
        changed = {**world.manifest[0], "scope_id": "another-group"}
        with pytest.raises(world.native.results.AnalysisResultUnavailable):
            world.native.results.build_analysis_source("policy-old", payload, source_snapshot=changed)


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("mutation", ["revoked", "deleted", "held", "revision"])
def test_comparison_rechecks_sources_after_model_work(monkeypatch, scope, mutation):
    with source_world(monkeypatch, scope) as world, access.strict_source_authority():
        stages = []

        def invoke(prompt, stage=None, metadata=None):
            stages.append(stage)
            if stage == "comparison":
                container = world.containers[scope]
                document = container.read_item("policy-old", "policy-old")
                if mutation == "revoked":
                    if scope == "group":
                        world.memberships.clear()
                    else:
                        monkeypatch.setattr(
                            sys.modules["functions_public_workspaces"], "find_public_workspace_by_id",
                            lambda workspace_id: None,
                        )
                elif mutation == "deleted":
                    container.delete_item("policy-old", "policy-old", etag=document["_etag"])
                else:
                    document["content_screening" if mutation == "held" else "version"] = (
                        {"state": "pending_review"} if mutation == "held" else 2
                    )
                    container.upsert_item(document)
            return "Complete summary or comparison."

        with pytest.raises((PermissionError, LookupError, DocumentHeldError, ScreeningConflictError)):
            world.comparison.run_document_comparison(
                sources.USER_ID, "Compare both revisions.",
                {
                    "type": world.comparison.DOCUMENT_ACTION_TYPE_COMPARISON,
                    "left_document_id": "policy-old", "right_document_ids": ["policy-new"],
                    **world.options,
                },
                invoke, conversation_id=CURRENT_CONVERSATION, result_version="comparison-v1",
            )
        assert stages == ["window_analysis", "window_analysis", "comparison"]


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("provider_failed", [False, True])
def test_comparison_and_dependent_composition_use_complete_workspace_sources(
    runtime, monkeypatch, scope, provider_failed,
):
    monkeypatch.setattr(sources, "USER_ID", "owner")
    summaries = [
        "Threshold: 125000. Review: 10 days. Owner: Mira. Marker: POLICY-ALPHA.",
        "Threshold: 150000. Review: 7 days. Owner: Mira. Marker: POLICY-BETA.",
    ]
    answer = (
        "Threshold: 125000 to 150000 (+25000). Review: 10 to 7 days (-3). Owner remains Mira. "
        "[POLICY-ALPHA](#policy-old) and [POLICY-BETA](#policy-new)."
    )
    capability = runtime.registry.get_capability("document_compare", contract_version=2)
    steps = [
        {
            "step_id": "compare", "capability_id": "document_compare",
            "arguments": {
                "left_document_id": "policy-old", "right_document_ids": ["policy-new"],
                "comparison_prompt": "Compare thresholds, review deadlines, owner and exact markers; cite both.",
            },
            "outputs": [
                {"name": name, "kind": kind}
                for name, kind in {
                    **capability["result_outputs"], **capability["optional_result_outputs"],
                }.items()
            ],
        },
        compose("answer", inputs={"source": source_input("compare", "report")}),
    ]
    case = runtime.make(
        steps, [*summaries, RuntimeError("Synthetic provider failure") if provider_failed else answer, answer],
        final_response=binding("answer"),
    )
    with source_world(monkeypatch, scope) as world, access.strict_source_authority():
        case.fixture.sources = {item["document_id"]: item for item in world.manifest}
        case.fixture.service.access.source_metadata_reader = access._read_authorized_document
        case.context.active_group_ids = world.options["active_group_ids"]
        case.context.active_public_workspace_id = world.options["active_public_workspace_id"]
        result = execute(runtime, case)
        assert [step["status"] for step in result["steps"]] == (
            ["failed", "skipped"] if provider_failed else ["completed", "completed"]
        ), result
        assert result["status"] == ("failed" if provider_failed else "completed")
        assert "POLICY-ALPHA" in case.model.calls[0][0]
        assert "POLICY-BETA" in case.model.calls[1][0]
        assert case.model.calls[2][1]["stage"] == "comparison"
        if not provider_failed:
            composed_input = json.dumps(case.model.calls[3][0])
            assert answer in composed_input
            assert result["message"] == answer
            task = runtime.contracts.TaskResult.from_dict(result["task_results"]["compare"])
            retained = case.fixture.service.open_result(task.output("report")).read_text()
            assert retained == answer
        assert len(case.model.calls) == (3 if provider_failed else 4)
        assert result["artifacts"] == result["outputs"] == []
        assert {step["capability_id"] for step in result["steps"]} == {"document_compare", "compose"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
