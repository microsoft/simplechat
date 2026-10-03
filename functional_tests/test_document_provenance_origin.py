# test_document_provenance_origin.py
"""
Functional tests for server-owned document provenance (origin).
Version: 0.261.231
Implemented in: 0.261.194
Run links stopped re-checking the run's saved results in: 0.261.231

This test ensures that document origins are derived only from server-held
workflow, orchestration, and chat bindings; that only workflow-saved documents
receive the removable ``workflow`` tag and only when the actor may manage tags;
that clients can never name an origin field; that origin summaries are resolved
per reader with a plain-text fallback that discloses no names or ids; that a run
link takes its access from its workflow; and that origin list filters are
parameterized and access checked.

Exercises the real functions_document_provenance module against in-memory
conversation, workflow, run, collaboration, and tag stores. No Azure resources,
credentials, or application startup are used.
"""

from copy import deepcopy
from importlib.metadata import version
import json
import logging
from pathlib import Path
import sys
import types
import uuid

from flask import Flask
import pytest
import werkzeug
from werkzeug.datastructures import MultiDict

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# The module under test imports only Flask at load time; its application
# dependencies are resolved lazily, so the fakes below are installed per test.
import functions_document_provenance as provenance
from test_support.versioning import assert_app_version_at_least


REVISION = "a" * 64
WORKFLOW_ID = "workflow-1"
RUN_ID = "run-1"


def run_conversation_id(workflow_id, run_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-conversation:{workflow_id}:{run_id}"))


class NotFound(Exception):
    status_code = 404


class ConversationStore:
    def __init__(self):
        self.records = {}
        self.reads = 0
        self.failure = None

    def read_item(self, item, partition_key):
        assert item == partition_key
        self.reads += 1
        if self.failure is not None:
            raise self.failure
        if item not in self.records:
            raise NotFound(item)
        return deepcopy(self.records[item])


class World:
    """In-memory application stores behind the provenance module's lazy imports."""

    def __init__(self):
        self.settings = {"enable_group_workspaces": True, "enable_collaborative_conversations": False}
        self.user_workflows_enabled = True
        self.disabled_group_workflows = set()
        self.conversations = ConversationStore()
        self.collaborations = {}
        self.collaboration_members = set()
        self.personal_workflows = {}
        self.group_workflows = {}
        self.personal_runs = {}
        self.group_runs = {}
        self.latest_runs = {}
        self.runtime_controls = {}
        self.run_readers = set()
        self.group_roles = {}
        self.tag_managers = set()
        self.tag_definitions = []
        self.tag_failure = None
        self.store_failure = None
        self.logs = []

    # Settings policy ------------------------------------------------------------------
    def is_user_workflows_enabled_for_user(self, settings, user_roles=None, authorization_prechecked=False):
        return self.user_workflows_enabled

    def is_group_workflows_enabled_for_group(self, settings, group_id):
        return group_id not in self.disabled_group_workflows

    # Conversations and collaboration ---------------------------------------------------
    def build_conversation_participation_context(self, user_id, conversation):
        collaboration_id = str(conversation.get("collaboration_conversation_id") or "")
        if conversation.get("user_id") == user_id:
            return {"is_owner": True, "collaboration_conversation_id": collaboration_id}
        if collaboration_id and (user_id, collaboration_id) in self.collaboration_members:
            return {"is_owner": False, "collaboration_conversation_id": collaboration_id}
        raise PermissionError("You can only access your own conversations")

    def get_collaboration_conversation(self, conversation_id):
        if conversation_id not in self.collaborations:
            raise NotFound(conversation_id)
        return deepcopy(self.collaborations[conversation_id])

    def assert_user_can_participate(self, user_id, collaboration):
        if (user_id, collaboration["id"]) not in self.collaboration_members:
            raise PermissionError("Not a participant")
        return {"role": "participant"}

    # Workflows and runs ----------------------------------------------------------------
    def _check_store(self):
        if self.store_failure is not None:
            raise self.store_failure

    def get_personal_workflow(self, user_id, workflow_id):
        self._check_store()
        return deepcopy(self.personal_workflows.get((user_id, workflow_id)))

    def get_group_workflow(self, group_id, workflow_id):
        self._check_store()
        return deepcopy(self.group_workflows.get((group_id, workflow_id)))

    def get_personal_workflow_run(self, user_id, run_id):
        return deepcopy(self.personal_runs.get((user_id, run_id)))

    def get_group_workflow_run(self, group_id, run_id):
        return deepcopy(self.group_runs.get((group_id, run_id)))

    def get_latest_run_for_conversation(self, scope_id, conversation_id, workflow_id=None):
        return deepcopy(self.latest_runs.get((scope_id, conversation_id, workflow_id)))

    def workflow_runtime_store(self, workflow, run_id):
        control = self.runtime_controls.get(run_id)

        def read():
            if control is None:
                raise RuntimeError("Runtime journal unavailable")
            return deepcopy(control)
        return types.SimpleNamespace(read=read)

    def authorize_workflow_run_read(self, workflow, run_id, *, reader_user_id=None, **kwargs):
        if (reader_user_id, run_id) not in self.run_readers:
            raise PermissionError("Run is not readable")
        return True

    # Groups, public workspaces, and tags -----------------------------------------------
    def assert_group_role(self, user_id, group_id, allowed_roles=("Owner", "Admin")):
        role = self.group_roles.get((user_id, group_id))
        if role is None:
            raise LookupError("Not a member")
        if role not in allowed_roles:
            raise PermissionError("Role not allowed")
        return role

    def require_manage_tags(self, user_id, scope_id, operation):
        assert operation == "manage_tags"
        if (user_id, scope_id) not in self.tag_managers:
            raise PermissionError("Cannot manage tags")
        return {"role": "DocumentManager"}

    def get_or_create_tag_definition(
        self, user_id, tag_name, workspace_type="personal", color=None, group_id=None, public_workspace_id=None,
    ):
        if self.tag_failure is not None:
            raise self.tag_failure
        self.tag_definitions.append({
            "user_id": user_id, "tag_name": tag_name, "workspace_type": workspace_type,
            "group_id": group_id, "public_workspace_id": public_workspace_id,
        })
        return {"name": tag_name}

    def log_event(self, message, extra=None, level=logging.INFO, **kwargs):
        self.logs.append({"message": message, "extra": deepcopy(extra), "level": level})


def fake_module(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


@pytest.fixture
def world(monkeypatch):
    if not hasattr(werkzeug, "__version__"):
        monkeypatch.setattr(werkzeug, "__version__", version("werkzeug"), raising=False)
    state = World()
    modules = {
        "config": fake_module("config", cosmos_conversations_container=state.conversations),
        "functions_appinsights": fake_module("functions_appinsights", log_event=state.log_event),
        "functions_settings": fake_module(
            "functions_settings",
            get_settings=lambda: state.settings,
            is_user_workflows_enabled_for_user=state.is_user_workflows_enabled_for_user,
            is_group_workflows_enabled_for_group=state.is_group_workflows_enabled_for_group,
        ),
        "functions_collaboration": fake_module(
            "functions_collaboration",
            build_conversation_participation_context=state.build_conversation_participation_context,
            get_collaboration_conversation=state.get_collaboration_conversation,
            assert_user_can_participate_in_collaboration_conversation=state.assert_user_can_participate,
        ),
        "functions_personal_workflows": fake_module(
            "functions_personal_workflows",
            get_personal_workflow=state.get_personal_workflow,
            get_personal_workflow_run=state.get_personal_workflow_run,
            get_latest_personal_workflow_run_for_conversation=state.get_latest_run_for_conversation,
        ),
        "functions_group_workflows": fake_module(
            "functions_group_workflows",
            get_group_workflow=state.get_group_workflow,
            get_group_workflow_run=state.get_group_workflow_run,
            get_latest_group_workflow_run_for_conversation=state.get_latest_run_for_conversation,
        ),
        "functions_workflow_runtime_store": fake_module(
            "functions_workflow_runtime_store", workflow_runtime_store=state.workflow_runtime_store,
        ),
        "functions_workflow_results": fake_module(
            "functions_workflow_results", authorize_workflow_run_read=state.authorize_workflow_run_read,
        ),
        "functions_group_workflow_policy": fake_module(
            "functions_group_workflow_policy", GROUP_WORKFLOW_MEMBER_ROLES=("Owner", "Admin", "DocumentManager", "User"),
        ),
        "functions_group": fake_module("functions_group", assert_group_role=state.assert_group_role),
        "functions_group_document_access": fake_module(
            "functions_group_document_access", require_group_document_management_context=state.require_manage_tags,
        ),
        "functions_public_document_access": fake_module(
            "functions_public_document_access", require_public_document_management_context=state.require_manage_tags,
        ),
        "functions_documents": fake_module(
            "functions_documents", get_or_create_tag_definition=state.get_or_create_tag_definition,
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return state


def saved_output_artifact(scope_type="personal", scope_id="actor", *, output_name="records", receipt_producer=None):
    producer = {
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "analyze-node",
        "execution_id": "e" * 64, "attempt": 1, "iteration_path": [],
    }
    receipt = {
        "producer": deepcopy(receipt_producer or producer), "output_name": output_name,
        "result_ref": {"sha256": "b" * 64}, "output_ref": {"sha256": "c" * 64},
    }
    return {
        "id": "artifact-1", "conversation_id": "conversation-unread",
        "metadata": {"generated_artifact_source": {
            "version": 1, "kind": "workflow_saved_output",
            "scope": {"type": scope_type, "id": scope_id},
            "producer": producer, "source_receipt": receipt,
        }},
    }


def chat_artifact(conversation_id="conversation-1", **metadata):
    return {"id": "artifact-1", "conversation_id": conversation_id, "metadata": metadata}


def personal_workflow(world, *, name="Quarterly summary", definition_version=3, owner="actor"):
    workflow = {"id": WORKFLOW_ID, "user_id": owner, "name": name, "definition_version": definition_version}
    world.personal_workflows[(owner, WORKFLOW_ID)] = workflow
    return workflow


def group_workflow(world, *, group_id="group-1", name="Team digest"):
    workflow = {"id": WORKFLOW_ID, "group_id": group_id, "user_id": "creator", "name": name, "definition_version": 3}
    world.group_workflows[(group_id, WORKFLOW_ID)] = workflow
    return workflow


def workflow_document(scope_type="personal", scope_id="actor", run_id=RUN_ID):
    return {"id": "document-1", "origin": provenance.build_workflow_origin(
        scope_type=scope_type, scope_id=scope_id, workflow_id=WORKFLOW_ID, run_id=run_id,
    )}


def chat_document(conversation_id="conversation-1", **fields):
    return {"id": "document-1", "origin": provenance.build_chat_origin(conversation_id=conversation_id, **fields)}


def summary_for(reader, document, world, roles=()):
    return provenance.resolve_origin_summary(reader, document, settings=world.settings, user_roles=list(roles))


def test_version_supports_document_provenance():
    assert_app_version_at_least("0.261.194")


# --- Origin records -------------------------------------------------------------------


def test_workflow_and_chat_origins_are_small_versioned_records():
    workflow = provenance.build_workflow_origin(
        scope_type="group", scope_id="group-1", workflow_id=WORKFLOW_ID, run_id=RUN_ID,
        task_id="analyze", node_id="node", output_key="records", definition_revision=REVISION,
    )
    assert workflow == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": "group", "id": "group-1"},
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "node",
        "output_key": "records", "definition_revision": REVISION,
    }
    chat = provenance.build_chat_origin(
        conversation_id="conversation-1", message_id="message-1",
        orchestration_run_id="orchestration-1", orchestration_step_id="step-1",
    )
    assert chat == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "message-1",
        "orchestration_run_id": "orchestration-1", "orchestration_step_id": "step-1",
    }
    minimal = provenance.build_workflow_origin(scope_type="personal", scope_id="actor", workflow_id=WORKFLOW_ID)
    assert set(minimal) == {"version", "kind", "workflow_scope", "workflow_id"}


def test_a_chat_origin_keeps_an_orchestration_step_only_with_its_run():
    origin = provenance.build_chat_origin(conversation_id="conversation-1", orchestration_step_id="step-1")
    assert "orchestration_step_id" not in origin
    with pytest.raises(provenance.DocumentOriginError):
        provenance.validate_origin({
            "version": 1, "kind": "chat", "conversation_id": "conversation-1", "orchestration_step_id": "step-1",
        })


VALID_WORKFLOW_ORIGIN = {
    "version": 1, "kind": "workflow", "workflow_scope": {"type": "personal", "id": "actor"}, "workflow_id": WORKFLOW_ID,
}


@pytest.mark.parametrize("change", [
    {"kind": "upload"},
    {"version": 2},
    {"version": True},
    {"version": "1"},
    {"owner_user_id": "attacker"},
    {"workflow_scope": {"type": "public", "id": "workspace-1"}},
    {"workflow_scope": {"type": "personal", "id": "actor", "extra": True}},
    {"workflow_id": ""},
    {"workflow_id": " padded"},
    {"workflow_id": "line\nbreak"},
    {"workflow_id": "x" * 1025},
    {"workflow_id": 42},
    {"run_id": None},
    {"definition_revision": "not-a-digest"},
    {"definition_revision": "A" * 64},
])
def test_validation_rejects_unknown_kinds_fields_versions_and_unsafe_text(change):
    origin = {**VALID_WORKFLOW_ORIGIN, **change}
    with pytest.raises(provenance.DocumentOriginError):
        provenance.validate_origin(origin)


def test_validation_rejects_missing_required_fields_and_non_objects():
    for origin in ({"version": 1, "kind": "workflow", "workflow_id": WORKFLOW_ID}, ["origin"], "workflow", None):
        with pytest.raises(provenance.DocumentOriginError):
            provenance.validate_origin(origin)


def test_stored_origins_are_revalidated_before_use():
    kinds = [
        provenance.document_origin_kind(document) for document in (
            {"origin": deepcopy(VALID_WORKFLOW_ORIGIN)},
            {"origin": {**VALID_WORKFLOW_ORIGIN, "kind": "upload"}},
            {"origin_kind": "workflow"},
            {},
        )
    ]
    assert kinds == ["workflow", None, None, None]


def test_chat_upload_origin_uses_only_the_authorized_conversation_and_server_message_id(world):
    origin = provenance.chat_upload_origin(
        conversation_id="conversation-1", message_id="conversation-1_file_abc", collaboration_conversation_id=None,
    )
    assert origin == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "conversation-1_file_abc",
    }
    rejected = provenance.chat_upload_origin(conversation_id="bad\nid", message_id="m")
    assert rejected is None
    assert world.logs and world.logs[-1]["level"] == logging.WARNING
    dropped = provenance.chat_upload_origin(conversation_id="conversation-1", message_id="bad\x00id")
    assert dropped == {"version": 1, "kind": "chat", "conversation_id": "conversation-1"}


# --- Stamping new versions ------------------------------------------------------------


def test_each_version_keeps_only_the_origin_its_creator_supplied():
    carried = {
        "id": "document-2", "tags": ["workflow"], "origin": deepcopy(VALID_WORKFLOW_ORIGIN),
        "origin_kind": "workflow", "origin_summary": {"kind": "workflow", "label": "stale"},
    }
    manual = provenance.apply_document_provenance(deepcopy(carried))
    assert not any(field in manual for field in provenance.ORIGIN_FIELD_NAMES)
    assert manual["tags"] == ["workflow"]

    supplied = provenance.build_chat_origin(conversation_id="conversation-1")
    chat = provenance.apply_document_provenance(deepcopy(carried), origin=supplied)
    assert chat["origin"] == supplied and chat["origin"] is not supplied
    assert "origin_kind" not in chat and "origin_summary" not in chat


def test_server_tags_merge_once_and_ignore_invalid_names():
    metadata = {"tags": ["finance", "workflow"]}
    provenance.apply_document_provenance(metadata, origin=VALID_WORKFLOW_ORIGIN, server_tags=["workflow"])
    provenance.apply_document_provenance(metadata, origin=VALID_WORKFLOW_ORIGIN, server_tags=["workflow"])
    assert metadata["tags"] == ["finance", "workflow"]
    untagged = provenance.apply_document_provenance({}, origin=VALID_WORKFLOW_ORIGIN, server_tags=["workflow"])
    assert untagged["tags"] == ["workflow"]
    ignored = provenance.apply_document_provenance(
        {"tags": []}, origin=VALID_WORKFLOW_ORIGIN, server_tags=["Bad Tag", "<b>", 7, None],
    )
    assert ignored["tags"] == []


def test_a_malformed_server_origin_fails_before_any_write():
    with pytest.raises(provenance.DocumentOriginError):
        provenance.apply_document_provenance({}, origin={**VALID_WORKFLOW_ORIGIN, "kind": "upload"})


# --- Client input can never name an origin --------------------------------------------


@pytest.mark.parametrize("payload", [
    {"origin": {}},
    {"Origin": "workflow"},
    {"origin_kind": "chat"},
    {"originKind": "chat"},
    {"ORIGIN-SUMMARY": {"label": "x"}},
    {"metadata": {"origin": {"kind": "workflow"}}},
    {"documents": [{"id": "document-1", "origin_kind": "workflow"}]},
    [[{"origin": 1}]],
])
def test_client_payloads_naming_an_origin_field_at_any_depth_are_rejected(payload):
    with pytest.raises(provenance.DocumentOriginError) as raised:
        provenance.reject_origin_fields(payload)
    assert raised.value.code == "document_origin_server_managed"
    assert raised.value.status_code == 400


@pytest.mark.parametrize("payload", [
    {"original_file_name": "report.md"},
    {"originator": "someone"},
    {"title": "origin", "tags": ["origin", "workflow"]},
    {"filter": {"origin_workflow_id": "not-a-document-field"}},
    None,
    "origin",
    [],
])
def test_ordinary_payloads_pass_the_origin_guard(payload):
    provenance.reject_origin_fields(payload)


# --- Deriving a published artifact's origin -------------------------------------------


def test_a_personal_saved_output_is_stamped_from_its_binding_without_reading_the_chat(world):
    personal_workflow(world)
    world.runtime_controls[RUN_ID] = {"definition_revision": REVISION}
    origin = provenance.derive_publication_origin(saved_output_artifact())
    assert origin == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": "personal", "id": "actor"},
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "analyze-node",
        "output_key": "records", "definition_revision": REVISION,
    }
    assert world.conversations.reads == 0


def test_a_group_saved_output_is_stamped_with_the_group_workflow_scope(world):
    group_workflow(world)
    origin = provenance.derive_publication_origin(saved_output_artifact("group", "group-1"))
    assert origin["workflow_scope"] == {"type": "group", "id": "group-1"}
    assert origin["run_id"] == RUN_ID
    assert "definition_revision" not in origin


def test_unproven_revisions_and_mismatched_receipts_are_omitted(world):
    workflow = personal_workflow(world, definition_version=2)
    world.runtime_controls[RUN_ID] = {"definition_revision": REVISION}
    other_run = {"workflow_id": WORKFLOW_ID, "run_id": "another-run"}
    origin = provenance.derive_publication_origin(saved_output_artifact(receipt_producer=other_run))
    assert "definition_revision" not in origin and "output_key" not in origin
    workflow["definition_version"] = 3
    world.runtime_controls[RUN_ID] = {"definition_revision": "not-a-digest"}
    unproven = provenance.derive_publication_origin(saved_output_artifact())
    assert "definition_revision" not in unproven


def test_a_workflow_producer_in_its_workflow_conversation_is_stamped_workflow(world):
    conversation_id = run_conversation_id(WORKFLOW_ID, RUN_ID)
    world.conversations.records[conversation_id] = {
        "id": conversation_id, "user_id": "creator", "chat_type": "workflow",
        "workflow_id": WORKFLOW_ID, "group_id": "group-1",
    }
    producer = {"kind": "workflow", "workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "task_id": "analyze", "node_id": "n"}
    receipt = {"producer": {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID}, "output_name": "summary"}
    origin = provenance.derive_publication_origin(
        chat_artifact(conversation_id, analysis_producer=producer), source_receipt=receipt,
    )
    assert origin["kind"] == "workflow"
    assert origin["workflow_scope"] == {"type": "group", "id": "group-1"}
    assert (origin["run_id"], origin["task_id"], origin["output_key"]) == (RUN_ID, "analyze", "summary")


def test_a_workflow_producer_outside_a_workflow_conversation_gets_no_origin(world):
    world.conversations.records["conversation-1"] = {"id": "conversation-1", "user_id": "actor"}
    producer = {"kind": "workflow", "workflow_id": WORKFLOW_ID, "run_id": RUN_ID}
    origin = provenance.derive_publication_origin(chat_artifact(analysis_producer=producer))
    assert origin is None
    assert world.logs[-1]["level"] == logging.WARNING


def test_a_chat_pipeline_artifact_in_a_workflow_run_conversation_is_stamped_workflow(world):
    """A workflow run publishes through the chat artifact pipeline in its own conversation."""
    conversation_id = run_conversation_id(WORKFLOW_ID, RUN_ID)
    world.conversations.records[conversation_id] = {
        "id": conversation_id, "user_id": "actor", "chat_type": "workflow", "workflow_id": WORKFLOW_ID,
    }
    world.latest_runs[("actor", conversation_id, WORKFLOW_ID)] = {"id": RUN_ID}
    producer = {"kind": "chat", "conversation_id": conversation_id, "message_id": "assistant-1"}
    origin = provenance.derive_publication_origin(chat_artifact(conversation_id, analysis_producer=producer))
    assert origin == {
        "version": 1, "kind": "workflow", "workflow_scope": {"type": "personal", "id": "actor"},
        "workflow_id": WORKFLOW_ID, "run_id": RUN_ID,
    }


def test_a_reused_workflow_conversation_never_attributes_a_run_it_cannot_prove(world):
    world.conversations.records["conversation-reused"] = {
        "id": "conversation-reused", "user_id": "actor", "chat_type": "workflow", "workflow_id": WORKFLOW_ID,
    }
    world.latest_runs[("actor", "conversation-reused", WORKFLOW_ID)] = {"id": RUN_ID}
    receipt = {"producer": {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID}, "output_name": "summary"}
    origin = provenance.derive_publication_origin(chat_artifact("conversation-reused"), source_receipt=receipt)
    assert origin["kind"] == "workflow"
    assert "run_id" not in origin and "output_key" not in origin


def test_orchestration_outputs_are_chat_origins_with_their_run_and_step(world):
    world.conversations.records["conversation-1"] = {"id": "conversation-1", "user_id": "actor"}
    bound = chat_artifact(generated_artifact_source={
        "kind": "orchestration_retained_output",
        "producer": {"user_id": "actor", "conversation_id": "conversation-1", "run_id": "orch-1", "step_id": "step-2"},
    })
    bound_origin = provenance.derive_publication_origin(bound)
    assert bound_origin == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "artifact-1",
        "orchestration_run_id": "orch-1", "orchestration_step_id": "step-2",
    }
    produced = chat_artifact(analysis_producer={"kind": "orchestration", "run_id": "orch-3", "step_id": "step-4"})
    origin = provenance.derive_publication_origin(produced)
    assert (origin["orchestration_run_id"], origin["orchestration_step_id"]) == ("orch-3", "step-4")


def test_an_ordinary_chat_artifact_is_stamped_chat_with_its_message(world):
    world.conversations.records["conversation-1"] = {
        "id": "conversation-1", "user_id": "actor", "collaboration_conversation_id": "shared-1",
    }
    origin = provenance.derive_publication_origin(chat_artifact(analysis_producer={"kind": "chat"}))
    assert origin == {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "artifact-1",
        "collaboration_conversation_id": "shared-1",
    }


def test_an_unreadable_conversation_yields_no_origin(world):
    missing = provenance.derive_publication_origin(chat_artifact("missing"))
    assert missing is None
    world.conversations.failure = RuntimeError("Cosmos unavailable")
    fields = provenance.publication_origin_fields("actor", chat_artifact())
    assert fields == {}
    assert any(entry["level"] == logging.WARNING for entry in world.logs)


def test_publication_origin_fields_never_block_publication(world):
    artifact = saved_output_artifact()
    artifact["metadata"]["generated_artifact_source"]["producer"]["workflow_id"] = "bad\nid"
    fields = provenance.publication_origin_fields("actor", artifact, destination={"workspace_scope": "personal"})
    assert fields == {}
    assert world.logs[-1]["level"] == logging.WARNING


# --- The removable workflow tag -------------------------------------------------------


def test_a_personal_workflow_document_gets_the_workflow_tag(world):
    personal_workflow(world)
    fields = provenance.publication_origin_fields(
        "actor", saved_output_artifact(), destination={"workspace_scope": "personal"},
    )
    assert fields["origin"]["kind"] == "workflow"
    assert fields["server_tags"] == ["workflow"]
    assert world.tag_definitions == [{
        "user_id": "actor", "tag_name": "workflow", "workspace_type": "personal",
        "group_id": None, "public_workspace_id": None,
    }]


@pytest.mark.parametrize("scope,field", [("group", "group_id"), ("public", "public_workspace_id")])
def test_the_workflow_tag_requires_tag_management_in_the_destination(world, scope, field):
    destination = {"workspace_scope": scope, field: "target-1"}
    denied = provenance.publication_origin_fields("actor", saved_output_artifact(), destination=destination)
    assert denied["origin"]["kind"] == "workflow" and "server_tags" not in denied
    assert world.tag_definitions == []
    assert world.logs[-1]["level"] == logging.INFO
    assert "target-1" not in json.dumps(world.logs[-1])

    world.tag_managers.add(("actor", "target-1"))
    allowed = provenance.publication_origin_fields("actor", saved_output_artifact(), destination=destination)
    assert allowed["server_tags"] == ["workflow"]
    assert world.tag_definitions[-1]["workspace_type"] == scope
    assert world.tag_definitions[-1][field] == "target-1"


def test_a_tag_definition_failure_keeps_the_origin_without_the_tag(world):
    world.tag_failure = RuntimeError("Settings write failed")
    fields = provenance.publication_origin_fields(
        "actor", saved_output_artifact(), destination={"workspace_scope": "personal"},
    )
    assert fields["origin"]["kind"] == "workflow" and "server_tags" not in fields
    assert world.logs[-1]["level"] == logging.WARNING


def test_chat_documents_never_get_a_visible_tag(world):
    world.conversations.records["conversation-1"] = {"id": "conversation-1", "user_id": "actor"}
    world.tag_managers.add(("actor", "target-1"))
    fields = provenance.publication_origin_fields(
        "actor", chat_artifact(), destination={"workspace_scope": "group", "group_id": "target-1"},
    )
    assert fields == {"origin": {
        "version": 1, "kind": "chat", "conversation_id": "conversation-1", "message_id": "artifact-1",
    }}
    assert world.tag_definitions == []


# --- Access-checked summaries ---------------------------------------------------------


def test_the_workflow_owner_sees_the_workflow_and_run(world):
    personal_workflow(world, name="Quarterly <summary>")
    world.personal_runs[("actor", RUN_ID)] = {"id": RUN_ID, "workflow_id": WORKFLOW_ID, "started_at": "2026-01-02T03:04:05Z"}
    world.run_readers.add(("actor", RUN_ID))
    summary = summary_for("actor", workflow_document(), world)
    assert summary == {
        "kind": "workflow", "label": "Created by Quarterly <summary>",
        "href": f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={RUN_ID}",
        "run_started_at": "2026-01-02T03:04:05Z",
    }


def test_a_missing_or_foreign_run_links_only_the_workflow(world):
    personal_workflow(world)
    missing = summary_for("actor", workflow_document(), world)
    assert missing["href"] == f"/workspace/workflows?workflow_id={WORKFLOW_ID}"
    assert "run_started_at" not in missing
    world.personal_runs[("actor", RUN_ID)] = {
        "id": RUN_ID, "workflow_id": "another-workflow", "started_at": "2026-01-02T03:04:05Z",
    }
    foreign = summary_for("actor", workflow_document(), world)
    assert "run_id" not in foreign["href"]
    assert "run_started_at" not in foreign


def test_the_run_link_takes_its_access_from_the_workflow_not_the_runs_results(world):
    personal_workflow(world)
    world.personal_runs[("actor", RUN_ID)] = {"id": RUN_ID, "workflow_id": WORKFLOW_ID, "started_at": "2026-01-02T03:04:05Z"}
    # No run-read grant is recorded: the run's saved results and their sources are not re-checked.
    assert ("actor", RUN_ID) not in world.run_readers
    summary = summary_for("actor", workflow_document(), world)
    assert summary["href"] == f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={RUN_ID}"
    assert summary["run_started_at"] == "2026-01-02T03:04:05Z"


def test_a_reader_without_access_gets_plain_text_with_no_names_or_ids(world):
    personal_workflow(world, name="Private payroll run")
    world.personal_runs[("actor", RUN_ID)] = {"id": RUN_ID, "workflow_id": WORKFLOW_ID}
    world.run_readers.add(("member", RUN_ID))
    summary = summary_for("member", workflow_document(), world)
    assert summary == {"kind": "workflow", "label": "Created by a workflow"}
    serialized = json.dumps(summary)
    for private in ("Private payroll run", WORKFLOW_ID, RUN_ID, "actor"):
        assert private not in serialized


def test_a_group_member_sees_a_group_workflow_and_others_do_not(world):
    group_workflow(world)
    document = workflow_document("group", "group-1")
    outsider = summary_for("member", document, world)
    assert outsider["label"] == "Created by a workflow"
    world.group_roles[("member", "group-1")] = "User"
    member = summary_for("member", document, world)
    assert member["label"] == "Created by Team digest"
    assert member["href"] == f"/groups/group-1/workflows?workflow_id={WORKFLOW_ID}"
    world.disabled_group_workflows.add("group-1")
    workflows_disabled = summary_for("member", document, world)
    assert "href" not in workflows_disabled
    world.disabled_group_workflows.clear()
    world.settings["enable_group_workspaces"] = False
    groups_disabled = summary_for("member", document, world)
    assert "href" not in groups_disabled


def test_disabled_user_workflows_and_deleted_workflows_fall_back(world):
    personal_workflow(world)
    world.user_workflows_enabled = False
    disabled = summary_for("actor", workflow_document(), world)
    assert disabled == {"kind": "workflow", "label": "Created by a workflow"}
    world.user_workflows_enabled = True
    world.personal_workflows.clear()
    deleted = summary_for("actor", workflow_document(), world)
    assert deleted == {"kind": "workflow", "label": "Created by a workflow"}


def test_the_chat_owner_sees_the_conversation_and_others_do_not(world):
    world.conversations.records["conversation-1"] = {"id": "conversation-1", "user_id": "actor", "title": "Budget review"}
    owner = summary_for("actor", chat_document(message_id="m-1"), world)
    assert owner == {
        "kind": "chat", "label": "Created in chat \u00b7 Budget review", "href": "/chat?conversationId=conversation-1",
    }
    other = summary_for("member", chat_document(), world)
    assert other == {"kind": "chat", "label": "Created in a chat"}
    world.conversations.records.clear()
    deleted = summary_for("actor", chat_document(), world)
    assert deleted == {"kind": "chat", "label": "Created in a chat"}


def test_shared_conversations_link_only_when_collaboration_is_enabled(world):
    world.conversations.records["conversation-1"] = {
        "id": "conversation-1", "user_id": "actor", "title": "Private copy", "collaboration_conversation_id": "shared-1",
    }
    world.collaborations["shared-1"] = {"id": "shared-1", "title": "Shared planning"}
    world.collaboration_members.add(("member", "shared-1"))
    document = chat_document(collaboration_conversation_id="shared-1")
    collaboration_disabled = summary_for("member", document, world)
    assert collaboration_disabled == {"kind": "chat", "label": "Created in a chat"}
    world.settings["enable_collaborative_conversations"] = True
    collaboration_enabled = summary_for("member", document, world)
    assert collaboration_enabled == {
        "kind": "chat", "label": "Created in chat \u00b7 Shared planning", "href": "/chat?conversationId=shared-1",
    }


def test_labels_are_bounded_single_line_text(world):
    personal_workflow(world, name="Line one\nline\ttwo " + "x" * 400)
    label = summary_for("actor", workflow_document(run_id=None), world)["label"]
    assert "\n" not in label and "\t" not in label
    assert label.startswith("Created by Line one line two x")
    assert len(label) <= len("Created by ") + 200
    assert label.endswith("\u2026")


def test_store_failures_resolve_to_plain_text(world):
    personal_workflow(world)
    world.store_failure = RuntimeError("Cosmos unavailable")
    failed = summary_for("actor", workflow_document(), world)
    assert failed == {"kind": "workflow", "label": "Created by a workflow"}
    unstamped = provenance.resolve_origin_summary("actor", {"id": "document-1"})
    assert unstamped is None


def test_summaries_attach_only_to_the_matching_single_document_payload(world):
    world.conversations.records["conversation-1"] = {"id": "conversation-1", "user_id": "actor", "title": "Budget"}
    app = Flask(__name__)
    record = chat_document()
    outside_a_request = provenance.attached_origin_summary({"id": "document-1", "origin_kind": "chat"})
    assert outside_a_request == {"id": "document-1", "origin_kind": "chat"}
    with app.test_request_context("/api/documents/document-1?origin_summary=1"):
        remembered = provenance.remember_document_origin_summary("actor", record)
        assert remembered["label"] == "Created in chat \u00b7 Budget"
        attached = provenance.attached_origin_summary({"id": "document-1", "origin_kind": "chat"})
        assert attached["origin_summary"] == remembered
        mismatched = [
            provenance.attached_origin_summary(payload) for payload in (
                {"id": "document-1", "origin_kind": "workflow"},
                {"id": "document-1"},
                {"id": "document-2", "origin_kind": "chat"},
            )
        ]
        assert all("origin_summary" not in payload for payload in mismatched)
        unstamped = provenance.remember_document_origin_summary("actor", {"id": "document-3"})
        assert unstamped is None


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), (" TRUE ", True), ("0", False), ("", False), ("yes", False), (None, False),
])
def test_the_summary_is_opt_in(value, expected):
    args = {} if value is None else {"origin_summary": value}
    requested = provenance.summary_requested(args)
    assert requested is expected


# --- Origin list filters --------------------------------------------------------------


def filter_for(reader, world, group_id=None, **params):
    return provenance.origin_list_filter(
        reader, MultiDict(params), group_id=group_id, settings=world.settings, user_roles=[],
    )


def test_no_filter_parameters_means_no_filter(world):
    unfiltered = filter_for("actor", world)
    assert unfiltered is None
    empty_value = provenance.origin_filter_requested(MultiDict({"origin_run_id": ""}))
    unrelated = provenance.origin_filter_requested(MultiDict({"search": "origin"}))
    assert empty_value
    assert not unrelated


def test_workflow_filters_are_parameterized_and_scoped_to_the_readers_workflow(world):
    hostile = "workflow' OR 1=1 --"
    world.personal_workflows[("actor", hostile)] = {"id": hostile, "user_id": "actor", "name": "Hostile"}
    conditions, parameters = filter_for("actor", world, origin_workflow_id=hostile)
    assert all(hostile not in condition for condition in conditions)
    assert {"name": "@origin_workflow_id", "value": hostile} in parameters
    assert {"name": "@origin_scope_type", "value": "personal"} in parameters
    assert {"name": "@origin_scope_id", "value": "actor"} in parameters
    assert conditions[-1] == "c.is_current_version = true"
    assert all(condition.startswith(("c.origin.", "(c.origin.", "c.is_current_version")) for condition in conditions)


def test_run_filters_require_a_run_of_that_workflow(world):
    personal_workflow(world)
    with pytest.raises(provenance.DocumentOriginFilterError) as raised:
        filter_for("actor", world, origin_workflow_id=WORKFLOW_ID, origin_run_id=RUN_ID)
    assert raised.value.status_code == 404
    world.personal_runs[("actor", RUN_ID)] = {"id": RUN_ID, "workflow_id": "another-workflow"}
    with pytest.raises(provenance.DocumentOriginFilterError) as foreign:
        filter_for("actor", world, origin_workflow_id=WORKFLOW_ID, origin_run_id=RUN_ID)
    assert foreign.value.status_code == 404
    world.personal_runs[("actor", RUN_ID)]["workflow_id"] = WORKFLOW_ID
    conditions, parameters = filter_for("actor", world, origin_workflow_id=WORKFLOW_ID, origin_run_id=RUN_ID)
    assert "c.origin.run_id = @origin_run_id" in conditions
    assert {"name": "@origin_run_id", "value": RUN_ID} in parameters


def test_group_workflow_filters_use_the_lists_group_only_for_members(world):
    group_workflow(world)
    with pytest.raises(provenance.DocumentOriginFilterError) as raised:
        filter_for("member", world, group_id="group-1", origin_workflow_id=WORKFLOW_ID)
    assert raised.value.status_code == 404
    world.group_roles[("member", "group-1")] = "User"
    _conditions, parameters = filter_for("member", world, group_id="group-1", origin_workflow_id=WORKFLOW_ID)
    assert {"name": "@origin_scope_type", "value": "group"} in parameters
    assert {"name": "@origin_scope_id", "value": "group-1"} in parameters
    with pytest.raises(provenance.DocumentOriginFilterError):
        filter_for("member", world, origin_workflow_id=WORKFLOW_ID)


@pytest.mark.parametrize("params", [
    {"origin_run_id": RUN_ID},
    {"origin_workflow_id": WORKFLOW_ID, "origin_conversation_id": "conversation-1"},
    {"origin_workflow_id": "bad\nid"},
    {"origin_conversation_id": "x" * 1025},
])
def test_malformed_filters_are_rejected(world, params):
    with pytest.raises(provenance.DocumentOriginFilterError) as raised:
        filter_for("actor", world, **params)
    assert raised.value.status_code == 400


def test_a_repeated_filter_parameter_is_rejected(world):
    args = MultiDict([("origin_workflow_id", "one"), ("origin_workflow_id", "two")])
    with pytest.raises(provenance.DocumentOriginFilterError) as raised:
        provenance.origin_list_filter("actor", args, settings=world.settings, user_roles=[])
    assert raised.value.status_code == 400


def test_conversation_filters_require_the_reader_to_own_or_share_the_chat(world):
    world.conversations.records["conversation-1"] = {
        "id": "conversation-1", "user_id": "actor", "collaboration_conversation_id": "shared-1",
    }
    world.collaborations["shared-1"] = {"id": "shared-1"}
    world.collaboration_members.add(("member", "shared-1"))
    conditions, parameters = filter_for("actor", world, origin_conversation_id="conversation-1")
    assert any("c.origin.collaboration_conversation_id = @origin_conversation_id" in item for item in conditions)
    assert {"name": "@origin_kind", "value": "chat"} in parameters
    for reader, conversation_id in (("stranger", "conversation-1"), ("member", "conversation-1"), ("member", "shared-1")):
        with pytest.raises(provenance.DocumentOriginFilterError) as raised:
            filter_for(reader, world, origin_conversation_id=conversation_id)
        assert raised.value.status_code == 404
    world.settings["enable_collaborative_conversations"] = True
    shared = filter_for("member", world, origin_conversation_id="shared-1")
    source_copy = filter_for("member", world, origin_conversation_id="conversation-1")
    assert shared is not None
    assert source_copy is not None


def test_links_quote_every_identifier():
    hrefs = (
        provenance.workflow_origin_href("group", "g/1?x", "w&1", "r#1"),
        provenance.workflow_origin_href("personal", "actor", "w 1"),
        provenance.chat_origin_href("c/1&x"),
    )
    assert hrefs == (
        "/groups/g%2F1%3Fx/workflows?workflow_id=w%261&run_id=r%231",
        "/workspace/workflows?workflow_id=w%201",
        "/chat?conversationId=c%2F1%26x",
    )
