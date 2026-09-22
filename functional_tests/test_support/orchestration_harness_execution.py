# orchestration_harness_execution.py
"""Initialized headless harness fixtures; only external storage/model I/O is doubled.

Version: 0.261.127
Implemented in: 0.261.127

Bootstrap keeps its real strict source callbacks. Source-specific fixtures replace
underlying document/blob I/O, not the authority wrappers or their model fence.
"""

import csv
import importlib
import io
import json
import shutil
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from functions_orchestration_context import build_conversation_snapshot, normalize_history_message
from functions_orchestration_memory import validate_memory_audience
from test_native_tabular_compute_service import MemoryBlobs, MemoryContainer, transformation_spec
from test_support.orchestration_results import ResultFixture
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_workflow_result_store import FakeBlobService


@contextmanager
def project_session_cache():
    directory = Path(f".orchestration-harness-session-{uuid.uuid4().hex}")
    directory.mkdir()
    try:
        yield str(directory.resolve())
    finally:
        shutil.rmtree(directory)


def input_binding(step_id, output_name="answer"):
    return {
        "version": "orchestration-input-binding-v1",
        "step_id": step_id, "output_name": output_name, "existing_result": None,
    }


def compose_step(step_id="prepare", *, inputs=None, outputs=None):
    return {
        "step_id": step_id, "capability_id": "compose",
        "arguments": {"instruction": "Prepare the complete requested content."},
        "inputs": inputs or {},
        "outputs": outputs or [{"name": "answer", "kind": "markdown-v1"}],
    }


def native_step():
    return {
        "step_id": "compute", "capability_id": "tabular_analyze",
        "arguments": {
            "question": "Compute doubled amounts.", "document_ids": ["document-1"],
            "native_operation": "transform", "columns": ["Item_ID", "doubled"],
            "transformation_spec": transformation_spec(),
        },
    }


def render_step(step_id, output_format, *, source="prepare", output="answer", profile=None):
    profiles = {
        "csv": "tabular_records_v1", "json": "exact_records_v1", "md": "prepared_text_v1",
    }
    return {
        "step_id": step_id, "capability_id": "render_file",
        "arguments": {
            "file_name": f"{step_id}.{output_format}",
            "output_format": output_format, "profile": profile or profiles[output_format],
        },
        "inputs": {"source": {"binding": input_binding(source, output), "allow_partial": False}},
    }


def decoded_frames(frames):
    return [json.loads(frame.partition("data:")[2].strip()) for frame in frames]


class CompletionClient:
    def __init__(self, environment):
        self.environment = environment
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.environment.model_calls.append(deepcopy(kwargs))
        if not self.environment.replies:
            raise AssertionError("An extra content-generation call was attempted.")
        reply = self.environment.replies.pop(0)
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
            choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=reply, refusal=None),
            )],
        )

    def close(self):
        self.closed = True


class HarnessBlobIO(FakeBlobService):
    """Support immutable retained bytes and the real uploader's bounded stream."""

    def __init__(self):
        super().__init__()
        self.file_uploads = 0
        self.before_file_upload = None

    def get_blob_client(self, *, container, blob):
        original = super().get_blob_client(container=container, blob=blob)
        service = self

        class Blob:
            def exists(self):
                return original.key in service.records

            def upload_blob(self, stream=None, *, data=None, overwrite, **kwargs):
                is_artifact = stream is not None
                if is_artifact:
                    if service.before_file_upload is not None:
                        callback, service.before_file_upload = service.before_file_upload, None
                        callback()
                    if not hasattr(stream, "read"):
                        raise AssertionError("Generated artifacts must use the production stream uploader.")
                    data = b"".join(iter(lambda: stream.read(65536), b""))
                original.upload_blob(
                    data=data, overwrite=overwrite,
                    metadata=kwargs.get("metadata") or {},
                    content_settings=kwargs.get("content_settings") or SimpleNamespace(
                        content_type="application/octet-stream",
                    ),
                )
                if is_artifact:
                    service.file_uploads += 1

            def download_blob(self, **kwargs):
                return original.download_blob(**kwargs)

            def get_blob_properties(self):
                return original.get_blob_properties()

            def delete_blob(self, **kwargs):
                return original.delete_blob(
                    delete_snapshots=kwargs.pop("delete_snapshots", "include"), **kwargs,
                )

        return Blob()


class HarnessMessageContainer(AtomicMemoryContainer):
    def __init__(self):
        super().__init__("conversation_id")

    def delete_item(self, item, partition_key, **kwargs):
        if "etag" not in kwargs:
            kwargs["etag"] = self.read_item(item, partition_key)["_etag"]
        return super().delete_item(item, partition_key, **kwargs)


class HarnessEnvironment:
    """Real bootstrap, model resolution, leases, checkpoints, runtime and services."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.bootstrap = importlib.import_module("functions_orchestration_bootstrap")
        self.execution = importlib.import_module("functions_orchestration_execution")
        self.recovery = importlib.import_module("functions_orchestration_recovery")
        self.revisions = importlib.import_module("functions_orchestration_plan_revisions")
        self.service_bindings = importlib.import_module("functions_orchestration_services")
        self.run_store = importlib.import_module("functions_orchestration_runs")
        self.schema = importlib.import_module("functions_orchestration_schema")
        self.operations = importlib.import_module("functions_simplechat_operations")
        self.config = importlib.import_module("config")
        self.artifacts = importlib.import_module("functions_orchestration_artifacts")
        self.planner = importlib.import_module("functions_orchestration_planner")
        self.settings = {
            "enable_chat_orchestration": True,
            "enable_user_workspace": True,
            "enable_fact_memory_plugin": False,
            "enable_semantic_kernel": False,
            "chat_orchestration_max_steps": 8,
            "chat_orchestration_total_timeout_seconds": 600,
            "chat_orchestration_step_timeout_seconds": 120,
            "gpt_model": {"selected": [{
                "deploymentName": "gpt-4o", "modelName": "gpt-4o", "responseLength": 1024,
            }]},
            "azure_openai_gpt_endpoint": "https://offline.invalid",
            "azure_openai_gpt_api_version": "2024-10-21",
            "azure_openai_gpt_key": "offline-fixture-not-a-credential",
        }
        self.conversations = AtomicMemoryContainer("id")
        self.messages = HarnessMessageContainer()
        self.runs = AtomicMemoryContainer("conversation_id")
        self.steps = AtomicMemoryContainer("run_id")
        self.results = ResultFixture()
        self.blobs = HarnessBlobIO()
        self.model_calls, self.clients, self.replies = [], [], []
        self.conversation = {"id": "conversation-1", "user_id": "owner", "title": "Harness test"}
        self.conversations.create_item(self.conversation)
        self.turn = {
            "id": "user-turn-1", "conversation_id": "conversation-1", "role": "user",
            "content": "Prepare the approved content and only the explicitly requested files.",
            "timestamp": "2026-09-21T18:00:00+00:00",
        }
        self.messages.create_item(self.turn)
        for module in (self.config, self.operations):
            monkeypatch.setattr(module, "cosmos_conversations_container", self.conversations)
            monkeypatch.setattr(module, "cosmos_messages_container", self.messages)
            monkeypatch.setattr(module, "storage_account_personal_chat_container_name", "harness-chat")
        for module in (self.config, self.run_store):
            monkeypatch.setattr(module, "cosmos_orchestration_runs_container", self.runs)
            monkeypatch.setattr(module, "cosmos_orchestration_run_steps_container", self.steps)
        monkeypatch.setattr(
            self.config, "cosmos_personal_workflow_run_items_container", self.results.container,
        )
        monkeypatch.setitem(self.config.CLIENTS, "storage_account_office_docs_client", self.blobs)
        monkeypatch.setattr(self.bootstrap, "get_settings", lambda: deepcopy(self.settings))
        monkeypatch.setattr(self.bootstrap, "get_user_settings", lambda user_id: {"settings": {}})
        monkeypatch.setattr(self.planner, "AzureOpenAI", self.client)
        monkeypatch.setattr(self.artifacts, "_service_factory", self.artifacts._service_factory)
        self.bootstrap.initialize_orchestration_artifact_access()

    def client(self, **kwargs):
        client = CompletionClient(self)
        self.clients.append(client)
        return client

    def create(self, steps=None, *, replies=(), final_response=None, history=(), **turn_updates):
        raw = {
            "run_id": "run-1", "plan_id": "plan-1", "turn_id": "turn-1",
            "steps": steps or [compose_step()],
        }
        if final_response is not None:
            raw["final_response"] = final_response
        plan = self.schema.normalize_plan(
            raw, "conversation-1", "owner", settings=self.settings, contract_version=2,
            available_capability_ids=[
                "compose", "render_file", "tabular_analyze", "document_search", "web_search", "url_fetch",
                "document_analyze", "document_compare",
            ],
        )
        for message in history:
            self.messages.create_item(message)
        normalized = normalize_history_message(self.turn)
        turn_context = {
            "turn_id": "turn-1", "user_message": self.turn["content"],
            "user_message_id": self.turn["id"], "user_message_fingerprint": normalized["fingerprint"],
            "resolved_message": self.turn["content"], "seeds": {}, "original_seeds": {},
            "answered_questions": [], "planning_token_usage": {},
            "conversation_context": build_conversation_snapshot(history, self.settings),
            "memory_audience": validate_memory_audience(self.conversation, "owner"),
            "memory_scope": None, **turn_updates,
        }
        self.replies = list(replies)
        return self.run_store.create_orchestration_run(
            plan, "owner", "conversation-1", turn_index=1, turn_context=turn_context,
        )

    def read(self):
        return self.runs.read_item("run-1", "conversation-1")

    def claim(self):
        record = self.read()
        services = self.services()
        claimed = self.revisions.claim_plan_run(
            record["id"], "owner", "conversation-1",
            expected_version=record.get("edit_version"),
            result_alias_resolver=lambda current: self.service_bindings.admitted_result_aliases(
                current, services.results,
            ),
        )
        lease = self.recovery.ExecutionLease(
            claimed, lambda: self.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=self.messages,
        )
        return claimed, lease

    def prepare(self, **kwargs):
        record, lease = self.claim()
        return self.execution.prepare_harness_execution(
            record, settings=self.settings, lease=lease, **kwargs,
        )

    def continue_waiting(self, submission_id):
        current = self.read()
        claimed = self.recovery.claim_waiting_continuation(
            current["id"], "owner", {
                "conversation_id": "conversation-1", "submission_id": submission_id,
                "expected_version": current["recovery_version"],
            },
            authorize=lambda: self.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=self.messages,
        )
        if claimed["acquired"] is not True:
            raise AssertionError("The fixture must acquire a fresh explicit continuation.")
        record = claimed["record"]
        lease = self.recovery.ExecutionLease(
            record, lambda: self.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=self.messages,
        )
        return self.execution.prepare_harness_execution(
            record, settings=self.settings, lease=lease,
        )

    @contextmanager
    def native_io(self, row_count=37):
        """Use real native computation and source policy with external I/O isolated."""
        engine = importlib.import_module("functions_tabular_generated_exports")
        plugin = importlib.import_module("semantic_kernel_plugins.tabular_processing_plugin")
        screening = importlib.import_module("content_screening.access")
        mixed = importlib.import_module("functions_mixed_source_orchestration")
        native = importlib.import_module("functions_native_tabular_compute")
        results = importlib.import_module("functions_native_analysis_results")
        resolve_other_blob = screening._resolve_blob_document
        jobs, blobs = MemoryContainer("user_id"), MemoryBlobs()
        document = {
            "id": "document-1", "user_id": "owner", "file_name": "source.csv",
            "version": 1, "_etag": "source-revision-1",
            "blob_container": "harness-documents", "blob_path": "owner/source.csv",
        }
        state = {"allowed": True}
        data = io.StringIO()
        writer = csv.DictWriter(data, fieldnames=["Item_ID", "amount"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {"Item_ID": f"item-{index:06}", "amount": index}
            for index in range(1, row_count + 1)
        )
        blobs.values[("harness-documents", "owner/source.csv")] = {
            "bytes": data.getvalue().encode("utf-8"), "etag": "source-blob-1", "metadata": {},
        }

        def read_document(document_id, user_id, **kwargs):
            if not state["allowed"] or user_id != "owner" or document_id != document["id"]:
                raise PermissionError("Fixture document access revoked.")
            if kwargs.get("group_id") is not None or kwargs.get("public_workspace_id") is not None:
                raise PermissionError("Fixture document scope does not match.")
            return deepcopy(document)

        def read_blob_document(container, blob, user_id):
            if (container, blob) != ("harness-documents", "owner/source.csv"):
                return resolve_other_blob(container, blob, user_id)
            return read_document(document["id"], user_id)

        clients = {**self.config.CLIENTS, "storage_account_office_docs_client": blobs}
        with self.monkeypatch.context() as patched:
            for module in (engine, plugin):
                patched.setattr(module, "CLIENTS", clients)
                patched.setattr(module, "storage_account_user_documents_container_name", "harness-documents")
                patched.setattr(module, "storage_account_personal_chat_container_name", "harness-chat")
            patched.setattr(engine, "cosmos_conversations_container", self.conversations)
            patched.setattr(engine, "cosmos_orchestration_runs_container", self.runs)
            patched.setattr(engine, "cosmos_tabular_export_runs_container", jobs)
            patched.setattr(engine, "get_settings", lambda: deepcopy(self.settings))
            patched.setattr(engine, "submit_tabular_generated_output_run", lambda *args: False)
            patched.setattr(screening, "_read_authorized_document", read_document)
            patched.setattr(screening, "_resolve_blob_document", read_blob_document)
            patched.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
                {
                    "document": read_document(identifier, kwargs["user_id"]), "scope": "personal",
                    "group_id": None, "public_workspace_id": None,
                }
                for identifier in kwargs["document_ids"]
            ])
            yield SimpleNamespace(
                engine=engine, native=native, results=results, jobs=jobs, blobs=blobs,
                document=document, state=state,
            )

    def run_engine(self, execution):
        return self.execution.execute_plan(
            execution.record["plan"], execution.context, settings=execution.settings,
            user_id="owner", cancel_requested=execution.lease.cancel_requested,
            persist=execution._persist,
            checkpoints=lambda context: self.recovery.ExecutionCheckpoints(
                execution.record, context, execution.settings, execution.lease,
            ),
        )

    @contextmanager
    def publication_only(self, services):
        def forbidden_execution(*args, **kwargs):
            raise AssertionError("Publication attempted model, producer, rendering or active-claim work.")

        continuation = importlib.import_module("functions_orchestration_continuation")
        native = importlib.import_module("functions_native_tabular_compute")
        native_results = importlib.import_module("functions_native_analysis_results")
        with self.monkeypatch.context() as guarded:
            for name in ("resolve_orchestration_model", "load_orchestration_memory", "execute_plan"):
                guarded.setattr(self.execution, name, forbidden_execution)
            guarded.setattr(continuation, "bind_orchestration_result_store", forbidden_execution)
            guarded.setattr(self.planner, "AzureOpenAI", forbidden_execution)
            guarded.setattr(native, "build_native_tabular_compute_callback", forbidden_execution)
            guarded.setattr(native_results, "open_native_tabular_result", forbidden_execution)
            for name in ("render_attempt", "reconcile", "claim_due", "manual_retry"):
                guarded.setattr(type(services.rendering), name, forbidden_execution)
            yield

    def services(self):
        return self.bootstrap.build_orchestration_services(
            "owner", "conversation-1", settings=self.settings,
        )

    def assistant_messages(self):
        return [
            deepcopy(message) for message in self.messages.items.values()
            if message.get("role") == "assistant"
        ]
