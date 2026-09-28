# test_document_provenance_publication.py
"""
Functional tests for document provenance on published chat and workflow artifacts.
Version: 0.261.194
Implemented in: 0.261.194

This test ensures that every artifact publication path stamps the destination
document with the right server-derived origin: ordinary chat artifacts and
orchestration outputs are stamped ``chat``; workflow task outputs, workflow saved
outputs, and artifacts a workflow run publishes through the chat pipeline in its
workflow conversation are stamped ``workflow``. Only workflow-saved documents get
the removable ``workflow`` tag, and only when the publishing user may manage tags
in the destination. Replays never restamp the origin or duplicate the tag, and
group approval keeps the origin.

Runs the real functions_artifact_publication and functions_document_provenance
modules against the in-memory publication harness from
test_analysis_artifact_publication.py. No Azure resources or model calls are used.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import sys
import types
import uuid

import pytest

from test_analysis_artifact_publication import publication, publish, saved_analysis  # noqa: F401
from test_support.versioning import assert_app_version_at_least


WORKFLOW_ID = "workflow-1"
RUN_ID = "run-1"
REVISION = "d" * 64
RUN_CONVERSATION_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-conversation:{WORKFLOW_ID}:{RUN_ID}"))
ORIGIN_KEYS = {"origin", "origin_kind", "origin_summary"}
PRODUCER = {
    "kind": "workflow", "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze",
    "node_id": "analyze", "execution_id": "a" * 64, "attempt": 1, "iteration_path": [],
}
RECEIPT = {
    "producer": {key: value for key, value in PRODUCER.items() if key != "kind"},
    "output_name": "records", "result_ref": {"sha256": "b" * 64},
    "output_ref": {"sha256": "c" * 64}, "analysis_result": True,
}
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")


def install(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def provenance(publication, monkeypatch):
    """Back the provenance module's lazy imports with the harness state."""
    state = types.SimpleNamespace(
        tags=[], logs=[], personal_workflows={}, group_workflows={}, latest_runs={}, runtime_controls={},
    )

    def get_or_create_tag_definition(
        user_id, tag_name, workspace_type="personal", color=None, group_id=None, public_workspace_id=None,
    ):
        state.tags.append({
            "user_id": user_id, "tag_name": tag_name, "workspace_type": workspace_type,
            "group_id": group_id, "public_workspace_id": public_workspace_id,
        })
        return {"name": tag_name}

    def manage_tags_check(role_key):
        def require(user_id, workspace_id, operation):
            if operation != "manage_tags" or publication.state[role_key] not in MANAGER_ROLES:
                raise PermissionError("You do not have permission to manage this workspace's documents.")
            return {"role": publication.state[role_key]}
        return require

    def latest_run(scope_id, conversation_id, workflow_id=None):
        return deepcopy(state.latest_runs.get((scope_id, conversation_id, workflow_id)))

    def runtime_store(workflow, run_id):
        def read():
            if run_id not in state.runtime_controls:
                raise RuntimeError("Runtime journal unavailable")
            return deepcopy(state.runtime_controls[run_id])
        return types.SimpleNamespace(read=read)

    @contextmanager
    def open_stream(artifact, check=None):
        yield publication.state["content"]

    def log_event(message, extra=None, level=None, **kwargs):
        state.logs.append({"message": message, "extra": deepcopy(extra), "level": level})

    monkeypatch.setattr(sys.modules["functions_appinsights"], "log_event", log_event)
    monkeypatch.setattr(
        sys.modules["functions_documents"], "get_or_create_tag_definition", get_or_create_tag_definition, raising=False,
    )
    personal = sys.modules["functions_personal_workflows"]
    monkeypatch.setattr(
        personal, "get_personal_workflow",
        lambda user_id, workflow_id: deepcopy(state.personal_workflows.get((user_id, workflow_id))), raising=False,
    )
    monkeypatch.setattr(personal, "get_latest_personal_workflow_run_for_conversation", latest_run, raising=False)
    install(
        monkeypatch, "functions_group_workflows",
        get_group_workflow=lambda group_id, workflow_id: deepcopy(state.group_workflows.get((group_id, workflow_id))),
        get_latest_group_workflow_run_for_conversation=latest_run,
    )
    install(monkeypatch, "functions_workflow_runtime_store", workflow_runtime_store=runtime_store)
    install(
        monkeypatch, "functions_group_document_access",
        require_group_document_management_context=manage_tags_check("group_role"),
    )
    install(
        monkeypatch, "functions_public_document_access",
        require_public_document_management_context=manage_tags_check("public_role"),
    )
    monkeypatch.setattr(
        sys.modules["functions_simplechat_operations"], "open_generated_chat_artifact_stream", open_stream,
        raising=False,
    )
    return state


def trust_artifact_sources(publication, monkeypatch):
    """Source authorization has its own tests; these tests exercise provenance only."""
    monkeypatch.setattr(publication.module, "authorize_generated_artifact_source", lambda *args, **kwargs: None)


def add_workflow_conversation(publication, conversation_id=RUN_CONVERSATION_ID, *, group_id=None):
    conversation = {"id": conversation_id, "user_id": "actor", "chat_type": "workflow", "workflow_id": WORKFLOW_ID}
    if group_id:
        conversation["group_id"] = group_id
    publication.conversations.put(conversation)
    return conversation


def add_artifact(publication, message_id, conversation_id, metadata=None, **fields):
    artifact = deepcopy(publication.artifact)
    artifact.update(
        id=message_id, conversation_id=conversation_id, blob_path=f"actor/{conversation_id}/{message_id}.md", **fields,
    )
    artifact["metadata"].pop("analysis_producer", None)
    artifact["metadata"].pop("analysis_result_required", None)
    artifact["metadata"].update(metadata or {})
    publication.messages.put(artifact)
    return artifact


def add_saved_output_artifact(publication, scope_type, scope_id):
    content = b'{"records": [{"total": 12.34}]}'
    publication.state["content"] = content
    binding = {
        "version": 1, "kind": "workflow_saved_output", "scope": {"type": scope_type, "id": scope_id},
        "producer": deepcopy(RECEIPT["producer"]), "source_receipt": deepcopy(RECEIPT),
        "allow_partial": False, "export_key": "records", "profile": "records", "output_format": "json",
        "materialization": {"version": 1},
    }
    return add_artifact(publication, "artifact-saved", RUN_CONVERSATION_ID, {
        "is_generated_chat_artifact": True,
        "generated_artifact_output_format": "json",
        "generated_artifact_content_sha256": hashlib.sha256(content).hexdigest(),
        "generated_artifact_source": binding,
    }, filename="records.json")


def publish_message(publication, conversation_id, message_id, scope="personal", **kwargs):
    destination = {"workspace_scope": scope}
    if scope != "personal":
        destination["group_id" if scope == "group" else "public_workspace_id"] = f"fixed-{scope}"
    return publication.module.publish_generated_chat_artifact_for_user(
        "actor", conversation_id=conversation_id, message_id=message_id,
        destination=destination, request_id=f"provenance:{message_id}:{scope}", **kwargs,
    )


def publish_workflow_task(publication, scope="personal", **publication_fields):
    request = {"artifact_format": "md", "workspace_scope": scope, **publication_fields}
    if scope != "personal":
        request["group_id" if scope == "group" else "public_workspace_id"] = f"fixed-{scope}"
    return publication.module.publish_workflow_artifact(
        "actor", publication=request,
        artifact_reference={
            "conversation_id": RUN_CONVERSATION_ID, "artifact_message_id": "artifact-run",
            "producer": saved_analysis.analysis_artifact_metadata(PRODUCER)["analysis_producer"],
        },
        request_id=f"{WORKFLOW_ID}:{RUN_ID}:publish-{scope}", source_receipt=deepcopy(RECEIPT),
    )


def add_workflow_task_artifact(publication, *, group_id=None):
    add_workflow_conversation(publication, group_id=group_id)
    return add_artifact(
        publication, "artifact-run", RUN_CONVERSATION_ID, saved_analysis.analysis_artifact_metadata(PRODUCER),
    )


def stored(publication, scope, result):
    document_id = result["document"]["id"] if "document" in result else result["publication"]["document_id"]
    return deepcopy(publication.destinations[scope].records[document_id])


def only_create(publication):
    assert len(publication.calls["create"]) == 1
    return publication.calls["create"][0]


def assert_no_update_names_an_origin(publication):
    assert not any(ORIGIN_KEYS & set(call) for call in publication.calls["update"])


def test_version_supports_document_provenance():
    assert_app_version_at_least("0.261.194")


# --- Chat artifacts -------------------------------------------------------------------


def test_a_personal_chat_publication_is_stamped_chat_without_a_tag(publication, provenance):
    result = publish(publication)
    create = only_create(publication)
    assert create["origin"] == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "artifact-1",
    }
    assert "server_tags" not in create
    assert provenance.tags == []
    assert stored(publication, "personal", result)["origin"] == create["origin"]
    assert_no_update_names_an_origin(publication)


def test_a_group_chat_publication_gets_no_tag_even_for_a_tag_manager(publication, provenance):
    publication.state["group_role"] = "DocumentManager"
    publish(publication, "group")
    create = only_create(publication)
    assert create["origin"]["kind"] == "chat"
    assert "server_tags" not in create
    assert provenance.tags == []


def test_an_orchestration_output_keeps_its_run_and_step(publication, provenance, monkeypatch):
    trust_artifact_sources(publication, monkeypatch)
    content = publication.state["content"]
    add_artifact(publication, "artifact-orchestration", "conversation-1", {
        "generated_artifact_content_sha256": hashlib.sha256(content).hexdigest(),
        "generated_artifact_source": {
            "version": 1, "kind": "orchestration_retained_output",
            "producer": {"user_id": "actor", "conversation_id": "conversation-1", "run_id": "orch-1", "step_id": "step-2"},
        },
    })
    publish_message(publication, "conversation-1", "artifact-orchestration")
    create = only_create(publication)
    assert create["origin"] == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "artifact-orchestration",
        "orchestration_run_id": "orch-1", "orchestration_step_id": "step-2",
    }
    assert "server_tags" not in create


def test_an_unreadable_conversation_never_blocks_publication(publication, provenance, monkeypatch):
    class UnavailableConversations:
        def read_item(self, item, partition_key):
            raise TimeoutError("Conversation read timed out")

    # Publication keeps its own authorized container; only the provenance read fails.
    monkeypatch.setattr(sys.modules["config"], "cosmos_conversations_container", UnavailableConversations())
    result = publish(publication)
    create = only_create(publication)
    assert "origin" not in create and "server_tags" not in create
    assert result["publication"]["state"] == "queued"
    assert any("without an origin" in entry["message"] for entry in provenance.logs)


# --- Workflow runs --------------------------------------------------------------------


@pytest.mark.parametrize("latest_run_id,expected_run", [(RUN_ID, {"run_id": RUN_ID}), ("run-other", {})])
def test_a_workflow_run_publishing_through_the_chat_pipeline_is_stamped_workflow(
    publication, provenance, monkeypatch, latest_run_id, expected_run,
):
    """The run's own conversation proves the workflow, even for a chat producer.

    The run is recorded only when the per-run conversation id proves it.
    """
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_conversation(publication)
    provenance.latest_runs[("actor", RUN_CONVERSATION_ID, WORKFLOW_ID)] = {"id": latest_run_id}
    add_artifact(publication, "artifact-run-chat", RUN_CONVERSATION_ID, saved_analysis.analysis_artifact_metadata({
        "kind": "chat", "conversation_id": RUN_CONVERSATION_ID, "message_id": "assistant-run",
    }))
    result = publish_message(publication, RUN_CONVERSATION_ID, "artifact-run-chat")
    create = only_create(publication)
    assert create["origin"] == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": "personal", "id": "actor"},
        "workflow_id": WORKFLOW_ID, **expected_run,
    }
    assert create["origin"]["kind"] != "chat"
    assert create["server_tags"] == ["workflow"]
    assert stored(publication, "personal", result)["origin"]["kind"] == "workflow"


def test_a_workflow_producer_outside_a_workflow_conversation_gets_no_origin(publication, provenance, monkeypatch):
    trust_artifact_sources(publication, monkeypatch)
    add_artifact(publication, "artifact-run", "conversation-1", saved_analysis.analysis_artifact_metadata(PRODUCER))
    publication.module.publish_workflow_artifact(
        "actor", publication={"artifact_format": "md", "workspace_scope": "personal"},
        artifact_reference={
            "conversation_id": "conversation-1", "artifact_message_id": "artifact-run",
            "producer": saved_analysis.analysis_artifact_metadata(PRODUCER)["analysis_producer"],
        },
        request_id=f"{WORKFLOW_ID}:{RUN_ID}:publish-outside", source_receipt=deepcopy(RECEIPT),
    )
    create = only_create(publication)
    assert "origin" not in create and "server_tags" not in create
    assert provenance.tags == []
    assert any("outside a workflow conversation" in entry["message"] for entry in provenance.logs)


def test_a_workflow_task_publication_records_the_run_task_and_output(publication, provenance, monkeypatch):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_task_artifact(publication)
    provenance.personal_workflows[("actor", WORKFLOW_ID)] = {"id": WORKFLOW_ID, "definition_version": 3}
    provenance.runtime_controls[RUN_ID] = {"definition_revision": REVISION}
    result = publish_workflow_task(publication)
    create = only_create(publication)
    assert create["origin"] == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": "personal", "id": "actor"},
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "analyze",
        "output_key": "records", "definition_revision": REVISION,
    }
    assert create["server_tags"] == ["workflow"]
    assert provenance.tags == [{
        "user_id": "actor", "tag_name": "workflow", "workspace_type": "personal",
        "group_id": None, "public_workspace_id": None,
    }]
    assert result["publication"]["state"] == "queued"


@pytest.mark.parametrize("role,tagged", [("User", False), ("DocumentManager", True), ("Admin", True)])
def test_a_group_workflow_publication_is_tagged_only_for_tag_managers(
    publication, provenance, monkeypatch, role, tagged,
):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_task_artifact(publication, group_id="group-1")
    publication.state["group_role"] = role
    publish_workflow_task(publication, "group")
    create = only_create(publication)
    assert create["origin"]["kind"] == "workflow"
    assert create["origin"]["workflow_scope"] == {"type": "group", "id": "group-1"}
    if tagged:
        assert create["server_tags"] == ["workflow"]
        assert provenance.tags == [{
            "user_id": "actor", "tag_name": "workflow", "workspace_type": "group",
            "group_id": "fixed-group", "public_workspace_id": None,
        }]
    else:
        assert "server_tags" not in create
        assert provenance.tags == []
        skipped = [entry for entry in provenance.logs if "workflow tag was skipped" in entry["message"]]
        assert len(skipped) == 1 and skipped[0]["extra"]["workspace_scope"] == "group"


def test_a_public_workflow_publication_tags_the_public_workspace(publication, provenance, monkeypatch):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_task_artifact(publication)
    publish_workflow_task(publication, "public")
    create = only_create(publication)
    assert create["origin"]["kind"] == "workflow"
    assert create["server_tags"] == ["workflow"]
    assert provenance.tags[0]["workspace_type"] == "public"
    assert provenance.tags[0]["public_workspace_id"] == "fixed-public"


@pytest.mark.parametrize("scope_type,scope_id,destination", [
    ("personal", "actor", "personal"),
    ("group", "group-1", "group"),
])
def test_a_saved_output_is_stamped_from_its_binding(
    publication, provenance, monkeypatch, scope_type, scope_id, destination,
):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_conversation(publication, group_id=scope_id if scope_type == "group" else None)
    add_saved_output_artifact(publication, scope_type, scope_id)
    workflow = {"id": WORKFLOW_ID, "definition_version": 3, "group_id": scope_id if scope_type == "group" else None}
    if scope_type == "group":
        provenance.group_workflows[(scope_id, WORKFLOW_ID)] = workflow
    else:
        provenance.personal_workflows[(scope_id, WORKFLOW_ID)] = workflow
    provenance.runtime_controls[RUN_ID] = {"definition_revision": REVISION}
    publication.state["group_role"] = "DocumentManager"
    publish_message(publication, RUN_CONVERSATION_ID, "artifact-saved", destination)
    create = only_create(publication)
    assert create["origin"] == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": scope_type, "id": scope_id},
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "analyze",
        "output_key": "records", "definition_revision": REVISION,
    }
    assert create["server_tags"] == ["workflow"]
    assert provenance.tags[0]["workspace_type"] == destination


# --- Replays and approval -------------------------------------------------------------


@pytest.mark.parametrize("failure", [None, "create_after"])
def test_replays_never_restamp_the_origin_or_duplicate_the_tag(publication, provenance, monkeypatch, failure):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_task_artifact(publication)
    publication.state["failure"] = failure
    first = publish_workflow_task(publication)
    publication.state["failure"] = None
    second = publish_workflow_task(publication)
    third = publish_workflow_task(publication)
    assert first["publication"]["id"] == second["publication"]["id"] == third["publication"]["id"]
    create = only_create(publication)
    assert len(provenance.tags) == 1
    document = next(iter(publication.destinations["personal"].records.values()))
    assert document["origin"] == create["origin"]
    assert document["server_tags"] == ["workflow"]
    assert_no_update_names_an_origin(publication)


def test_group_approval_keeps_the_origin(publication, provenance, monkeypatch):
    trust_artifact_sources(publication, monkeypatch)
    add_workflow_task_artifact(publication, group_id="group-1")
    publication.state["group_role"] = "DocumentManager"
    publish_workflow_task(publication, "group", completion_policy="approved")
    create = only_create(publication)
    pending = next(iter(publication.destinations["group"].records.values()))
    assert pending["generated_artifact_promotion_status"] == "pending_approval"
    assert pending["origin"] == create["origin"] and pending["origin"]["kind"] == "workflow"
    assert publication.calls["queue"] == []

    publication.module.decide_artifact_publication("reviewer", deepcopy(pending), "approved")
    publication.module.decide_artifact_publication("reviewer", deepcopy(pending), "approved")
    approved = publication.destinations["group"].records[pending["id"]]
    assert approved["generated_artifact_promotion_status"] == "approved"
    assert approved["origin"] == create["origin"]
    assert len(publication.calls["queue"]) == 1
    assert len(publication.calls["create"]) == 1
    assert len(provenance.tags) == 1
    assert_no_update_names_an_origin(publication)
