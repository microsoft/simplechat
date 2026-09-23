# test_orchestration_output_lifecycle.py
"""
Real retained-result/render/transport/commit/download lifecycle integration.
Version: 0.261.127
Implemented in: 0.261.127

Production modules (including the complete upload and download modules) run with
external Azure I/O doubled. No AST-extracted service, model call, or provider is
used. The transactional Cosmos fixture applies the installed SDK's batch format.
"""

import builtins
import csv
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from flask import Flask, g

from content_screening.contracts import (
    ScreeningConfigurationError,
    ScreeningError,
    SourceAuthorityUnavailableError,
    SourceAuthorityUnverifiedError,
)
from functions_generated_export_contracts import GeneratedFileExportError, GeneratedFileExportRequest
from functions_generated_file_exports import build_generated_file_export
from functions_orchestration_artifacts import (
    OrchestrationArtifactTransport,
    configure_orchestration_artifact_service,
)
from functions_orchestration_output_store import (
    MAX_AUTOMATIC_ATTEMPTS,
    OUTPUT_RECORD_TYPE,
    OrchestrationOutputStore,
    OutputConflictError,
    OutputError,
    OutputStorageError,
    OutputUnavailableError,
    enumerate_due_outputs,
    parse_time,
)
from functions_orchestration_rendering import OrchestrationRenderingService, execute_render_file
from functions_orchestration_results import NamedOutput, OrchestrationResultReader
from test_support import offline_bootstrap
from test_support.orchestration_results import COLUMNS, ROWS, ResultFixture, complete, source
from test_support.orchestration_revisions import AtomicMemoryContainer


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


class Crash(BaseException):
    """A process-loss boundary, not a recoverable Python application exception."""


class OutputContainer(AtomicMemoryContainer):
    def __init__(self):
        super().__init__("conversation_id")

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        params = {entry["name"]: entry["value"] for entry in parameters or []}
        if "c.output_cleanup.state" in query:
            rows = super().query_items(query, parameters, partition_key, **kwargs)
            matching = [
                row for row in rows
                if type(row.get("plan")) is dict
                and type(row["plan"].get("planner_contract_version")) is int
                and row["plan"]["planner_contract_version"] == 2
                and row.get("checkpoints_deleted") is True
                and type(row.get("output_cleanup")) is dict
                and type(row["output_cleanup"].get("version")) is int
                and row["output_cleanup"]["version"] == 1
                and row["output_cleanup"].get("state") == "pending"
            ]
            return [
                {key: row[key] for key in ("id", "user_id", "conversation_id")}
                for row in matching[:kwargs.get("max_item_count", 64)]
            ]
        if params.get("@record_type") != OUTPUT_RECORD_TYPE:
            return super().query_items(query, parameters, partition_key, **kwargs)
        self.queries.append((query, deepcopy(parameters), partition_key))
        if self.fail_queries:
            raise AzureError("Private query failure")
        now = params["@now"]
        with self._lock:
            rows = [
                deepcopy(row) for row in self.items.values()
                if row.get("record_type") == OUTPUT_RECORD_TYPE and (
                    (
                        row["state"] in {"waiting", "retry_scheduled"}
                        and (not row.get("next_retry_at") or row["next_retry_at"] <= now)
                    )
                    or (row["state"] == "rendering" and row["lease"]["expires_at"] <= now)
                    or (
                        row["state"] in {"cancelled", "failed", "completed"}
                        and row.get("cleanup_pending") and row["cleanup_after"] <= now
                    )
                )
            ]
        return [
            {name: row[name] for name in ("id", "user_id", "conversation_id", "run_id")}
            for row in rows[:kwargs.get("max_item_count", 64)]
        ]


class MessageContainer(AtomicMemoryContainer):
    def __init__(self):
        super().__init__("conversation_id")
        self.before_create = None
        self.after_create = None

    def create_item(self, body):
        self._hook("before_create")
        saved = super().create_item(body)
        self._hook("after_create")
        return saved

    def delete_item(self, item, partition_key, **kwargs):
        if "etag" not in kwargs:
            kwargs["etag"] = self.read_item(item, partition_key)["_etag"]
        return super().delete_item(item, partition_key, **kwargs)


class ArtifactBlobIO:
    def __init__(self):
        self.data = {}
        self.uploads = 0
        self.deletes = 0
        self.before_upload = None
        self.after_upload = None
        self.read_hook = None
        self.lock = threading.RLock()

    def fire(self, name):
        callback = getattr(self, name)
        if callback is not None:
            setattr(self, name, None)
            callback()

    def get_blob_client(self, *, container, blob):
        service, key = self, (container, blob)

        class Blob:
            def exists(self):
                return key in service.data

            def upload_blob(self, stream, *, overwrite, **kwargs):
                service.fire("before_upload")
                with service.lock:
                    if key in service.data and not overwrite:
                        raise ResourceExistsError("Fixture immutable blob exists.")
                    if not hasattr(stream, "read"):
                        raise AssertionError("The production path must upload a bounded stream.")
                    service.data[key] = b"".join(iter(lambda: stream.read(65536), b""))
                    service.uploads += 1
                service.fire("after_upload")

            def download_blob(self):
                if key not in service.data:
                    raise ResourceNotFoundError("Fixture blob is absent.")
                value = service.data[key]

                def chunks():
                    for offset in range(0, len(value), 4096):
                        if service.read_hook is not None:
                            service.read_hook()
                        yield value[offset:offset + 4096]

                return SimpleNamespace(chunks=chunks)

            def delete_blob(self, **kwargs):
                with service.lock:
                    if key not in service.data:
                        raise ResourceNotFoundError("Fixture blob is absent.")
                    del service.data[key]
                    service.deletes += 1

        return Blob()


@pytest.fixture(scope="module")
def production_modules():
    # Keep CacheLib initialization and session files in isolated, scoped storage.
    before = set(sys.modules)
    with patch.object(
        offline_bootstrap, "TemporaryDirectory",
        lambda: tempfile.TemporaryDirectory(dir=ROOT, prefix="orchestration-output-test-"),
    ), offline_bootstrap.offline_app_imports() as environment:
        modules = SimpleNamespace(
            operations=importlib.import_module("functions_simplechat_operations"),
            sources=importlib.import_module("functions_generated_artifact_sources"),
            routes=importlib.import_module("route_enhanced_citations"),
            config=importlib.import_module("config"),
            schema=importlib.import_module("functions_orchestration_schema"),
        )
        for module in (modules.operations, modules.sources, modules.routes):
            if Path(module.__file__).resolve().parent != APP:
                raise AssertionError("The lifecycle test did not import a real production module.")
        yield modules
        if environment.network_attempts:
            raise AssertionError("A provider was called during the lifecycle tests.")
    for name in set(sys.modules) - before:
        module_path = getattr(sys.modules[name], "__file__", "") or ""
        if str(APP) in module_path:
            sys.modules.pop(name, None)


def test_production_module_session_cache_is_scoped(production_modules):
    session_dir = Path(os.environ["SESSION_FILE_DIR"]).resolve()
    exists = session_dir.is_dir()
    assert exists and session_dir != ROOT and session_dir.parent == ROOT
    assert session_dir.name.startswith("orchestration-output-test-")


class Lifecycle:
    def __init__(self, modules, monkeypatch):
        self.modules = modules
        self.monkeypatch = monkeypatch
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.deadline = self.now + timedelta(hours=1)
        self.runs = OutputContainer()
        self.messages = MessageContainer()
        self.conversations = AtomicMemoryContainer("id")
        self.blobs = ArtifactBlobIO()
        self.results = ResultFixture(blob=True)
        self.saved = self.results.save()
        self.producer_writes = self.results.container.sequence
        self.conversations.create_item(self.results.conversation)
        run = deepcopy(self.results.runs["run-1"])
        run.update(
            record_type="run", execution_deadline_at=self.deadline.isoformat(),
            approval={"state": "approved"},
        )
        self.runs.create_item(run)
        self.capabilities = True
        self.failures = {}
        self.render_calls = []
        self.output_streams = []
        self.authorization_calls = []
        self.app = Flask("orchestration-output-lifecycle")
        for module in (modules.operations, modules.routes, modules.config):
            monkeypatch.setattr(module, "cosmos_conversations_container", self.conversations)
            monkeypatch.setattr(module, "cosmos_messages_container", self.messages)
        monkeypatch.setitem(modules.config.CLIENTS, "storage_account_office_docs_client", self.blobs)
        monkeypatch.setattr(modules.operations, "storage_account_personal_chat_container_name", "chat")
        monkeypatch.setattr(modules.operations, "log_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(modules.sources, "log_event", lambda *args, **kwargs: None)
        self.service = self.restart()
        monkeypatch.setattr(
            importlib.import_module("functions_orchestration_artifacts"), "_service_factory", self.factory,
        )

    def factory(self, user_id, conversation_id):
        if user_id != "owner" or conversation_id != "conversation-1":
            raise PermissionError("Fixture factory owner mismatch")
        return self.service

    def authorize(self, record, *, operation):
        self.authorization_calls.append(operation)
        if not self.capabilities:
            return False
        return None

    def render(self, **kwargs):
        request = kwargs["export_request"]
        self.render_calls.append((request.output_format, request.profile))
        failures = self.failures.get(request.output_format) or []
        if failures:
            failure = failures.pop(0)
            if callable(failure):
                failure()
            else:
                raise failure
        rendered = build_generated_file_export(**kwargs)
        self.output_streams.append(rendered.file_content)
        return rendered

    def restart(self, *, max_output_bytes=1024 * 1024):
        result_service = self.results.restart()
        result_service.access.read_conversation = lambda conversation_id: self.conversations.read_item(
            item=conversation_id, partition_key=conversation_id,
        )
        result_service.access.read_run = lambda run_id: self.runs.read_item(
            item=run_id, partition_key="conversation-1",
        )
        store = OrchestrationOutputStore(
            self.runs, user_id="owner", conversation_id="conversation-1",
            read_conversation=result_service.access.read_conversation,
            clock=lambda: self.now, lease_seconds=10,
        )
        operations = self.modules.operations
        transport = OrchestrationArtifactTransport(
            upload=operations.upload_generated_file_artifact_stream_for_user,
            read_message=lambda conversation_id, message_id: self.messages.read_item(
                item=message_id, partition_key=conversation_id,
            ),
            open_stream=operations.open_generated_chat_artifact_stream,
            delete=operations.delete_staged_orchestration_chat_artifact_for_user,
            blob_container="chat",
        )
        service = OrchestrationRenderingService(
            store, result_service, transport, authorize_execution=self.authorize,
            max_output_bytes=max_output_bytes, renderer=self.render, jitter=lambda: 0.5,
        )
        self.service = service
        return service

    def add_render_step(self, name):
        producer = replace(
            self.results.producer, step_id=name, capability_id="render_file",
            contract_version="render-file-v1",
        )
        run = self.runs.read_item("run-1", "conversation-1")
        if not any(step["step_id"] == name for step in run["plan"]["steps"]):
            run["plan"]["steps"].append({
                "step_id": name, "enabled": True, "capability_id": "render_file", "role": "render",
            })
            self.runs.upsert_item(run)
        return producer

    def retain_source(self, document_id):
        producer = replace(self.results.producer, run_id=f"source-{document_id}")
        self.results.add_producer(producer)
        snapshot = {**source(document_id), "content_sha256": "1" * 64}
        self.results.sources[document_id] = deepcopy(snapshot)
        self.runs.create_item({**self.results.runs[producer.run_id], "record_type": "run"})
        saved = self.results.service.persist_task_result(
            producer=producer, role="reason", status="complete",
            outputs=[NamedOutput("findings", "records-v1", deepcopy(ROWS), complete(3), COLUMNS)],
            sources=[snapshot], origin="grounded", guard_token="server-attempt-token",
        )
        return saved.output("findings")

    def prepare(self, output_format="json", *, step_id=None, reference=None, profile=None, file_name=None, **options):
        step_id = step_id or f"{output_format}_file"
        if profile is None:
            profile = {
                "json": "exact_records_v1", "csv": "tabular_records_v1",
                "md": "prepared_text_v1", "txt": "prepared_text_v1", "pdf": "prepared_report_v1",
                "yaml": "structured_records_v1", "yml": "structured_records_v1",
                "markdown": "prepared_text_v1", "text": "prepared_text_v1",
            }[output_format]
        if output_format == "csv":
            options.setdefault("columns", ("id", "amount", "enabled"))
        return self.service.ensure_output(
            producer=self.add_render_step(step_id),
            source_ref=reference or self.saved.output("findings"),
            export_request=GeneratedFileExportRequest(output_format, profile, **options),
            file_name=file_name if file_name is not None else f"{step_id}.{output_format}",
            approved_work_id="run-1",
            deadline_at=self.deadline.isoformat(),
        )

    def raw(self, output):
        output_id = output["output_id"] if isinstance(output, dict) else output
        return self.service.store.get(output_id)

    def advance_due(self, output):
        record = self.raw(output)
        self.now = parse_time(record["next_retry_at"]) if record.get("next_retry_at") else self.now + timedelta(seconds=11)

    def run(self, output):
        return self.service.render_attempt(output["output_id"])

    def download(self, output):
        with self.app.test_request_context():
            response = self.modules.routes._serve_chat_artifact_download(
                "owner", "conversation-1", output["artifact_message_id"],
            )
            try:
                return b"".join(response.response)
            finally:
                response.close()

    def change_run(self, **changes):
        run = self.runs.read_item("run-1", "conversation-1")
        run.update(changes)
        self.runs.upsert_item(run)

    def output_history(self, *, with_cards=True):
        message = {
            "id": "assistant-summary", "conversation_id": "conversation-1", "role": "assistant",
            "content": "The requested files are ready.",
            "metadata": {
                "orchestration": {
                    "run_id": "run-1", "turn_id": "turn-1", "status": "completed",
                    "outputs": self.service.list_public_outputs("run-1"),
                },
            },
        }
        if with_cards:
            message["generated_artifacts"] = self.service.committed_artifacts("run-1")
        return message


@pytest.fixture
def lifecycle(production_modules, monkeypatch):
    fixture = Lifecycle(production_modules, monkeypatch)
    yield fixture
    if any(not stream.closed for stream in fixture.output_streams):
        raise AssertionError("An output render stream escaped its lifecycle owner.")


def test_two_independent_files_render_once_and_download_every_record(lifecycle, monkeypatch):
    csv_output = lifecycle.prepare("csv")
    json_output = lifecycle.prepare("json")

    def no_preview(*args, **kwargs):
        raise AssertionError("A preview must never become an export input.")

    monkeypatch.setattr(OrchestrationResultReader, "preview", no_preview)
    writes = lifecycle.results.container.sequence
    completed_csv = lifecycle.run(csv_output)
    completed_json = lifecycle.run(json_output)
    assert completed_csv["state"] == completed_json["state"] == "completed"
    assert completed_csv["output_id"] != completed_json["output_id"]
    csv_rows = list(csv.reader(io.StringIO(lifecycle.download(completed_csv).decode("utf-8"))))
    json_rows = json.loads(lifecycle.download(completed_json))
    assert csv_rows[-1] == ["last", "", "false"]
    assert csv_rows[2][0].startswith("'=SUM(")
    assert json_rows == ROWS
    assert lifecycle.blobs.uploads == 2
    assert lifecycle.results.container.sequence == writes
    cards = lifecycle.service.committed_artifacts("run-1")
    assert len(cards) == 2
    for output in (completed_csv, completed_json):
        for private in ("blob_path", "source_ref", "producer", "manifest", "content_sha256", "lease"):
            assert private not in json.dumps(output)
        duplicate = lifecycle.run(output)
        initial_again = lifecycle.prepare(output["output_format"])
        assert duplicate == output
        assert initial_again == output
    assert len(lifecycle.render_calls) == 2


@pytest.mark.parametrize("output_format", ["yaml", "yml"])
@pytest.mark.parametrize("file_name", ["data.yml", "data.yaml", "Data.YML"])
def test_yaml_filename_alias_preserves_complete_transport_readback(lifecycle, output_format, file_name):
    output = lifecycle.prepare(output_format, step_id="yaml_file", file_name=file_name)
    completed = lifecycle.run(output)
    record = lifecycle.raw(completed)
    artifact = lifecycle.service.transport.message(record, committed=True)
    payload = lifecycle.download(completed)
    restored = yaml.safe_load(payload)
    duplicate = lifecycle.prepare("yaml", step_id="yaml_file", file_name=file_name)
    assert completed["state"] == "completed"
    assert completed["file_name"] == record["file_name"] == artifact["filename"] == file_name
    assert completed["output_format"] == record["render_spec"]["output_format"] == "yaml"
    assert record["committed_intent"]["media_type"] == "application/yaml"
    assert artifact["metadata"]["generated_artifact_output_format"] == "yaml"
    assert restored == ROWS and completed["row_count"] == len(ROWS)
    assert duplicate == completed and lifecycle.blobs.uploads == 1
    assert lifecycle.render_calls == [("yaml", "structured_records_v1")]


@pytest.mark.parametrize("output_format,extension,canonical,kind,media_type", [
    ("markdown", "markdown", "md", "markdown-v1", "text/markdown; charset=utf-8"),
    ("md", "markdown", "md", "markdown-v1", "text/markdown; charset=utf-8"),
    ("text", "text", "txt", "text-v1", "text/plain; charset=utf-8"),
    ("txt", "text", "txt", "text-v1", "text/plain; charset=utf-8"),
])
@pytest.mark.parametrize("content", ["Prepared content stays complete.\n", ""])
def test_prepared_text_filename_aliases_preserve_bytes_and_legacy_limits(
    lifecycle, output_format, extension, canonical, kind, media_type, content,
):
    producer = replace(lifecycle.results.producer, step_id="prepared_text")
    lifecycle.results.add_producer(producer)
    saved = lifecycle.results.save(
        producer=producer, grounded=False,
        outputs=[NamedOutput("prepared", kind, content, complete(1))],
    )
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({
        "step_id": "prepared_text", "enabled": True, "capability_id": "document_analyze",
    })
    lifecycle.runs.upsert_item(run)
    filename = f"Prepared.{extension}"
    output = lifecycle.prepare(
        output_format, reference=saved.output("prepared"), file_name=filename,
    )
    completed = lifecycle.run(output)
    record = lifecycle.raw(completed)
    artifact = lifecycle.service.transport.message(record, committed=True)
    payload = lifecycle.download(completed)
    assert completed["state"] == "completed"
    assert completed["file_name"] == artifact["filename"] == filename
    assert completed["output_format"] == record["render_spec"]["output_format"] == canonical
    assert record["committed_intent"]["media_type"] == media_type
    assert artifact["metadata"]["generated_artifact_output_format"] == canonical
    assert payload == content.encode("utf-8")
    assert completed["size_bytes"] == len(payload) and completed["character_count"] == len(content)
    with pytest.raises(ValueError, match="type is not supported"):
        lifecycle.modules.operations.upload_generated_file_artifact_stream_for_user(
            "owner", "conversation-1", filename, io.BytesIO(b"legacy"), 6,
            output_format=canonical,
        )


@pytest.mark.parametrize("filename", [
    "data.json", "data.yml.exe", "data.yamlx", "data.py", "data.html", "yaml", "",
])
def test_filename_rejects_suffixes_outside_the_selected_catalog_entry(lifecycle, filename):
    with pytest.raises(OutputError) as failure:
        lifecycle.prepare("yml", file_name=filename)
    assert failure.value.code == "output_filename_invalid"
    assert not lifecycle.render_calls and not lifecycle.blobs.data and not lifecycle.messages.items
    assert not any(row.get("record_type") == OUTPUT_RECORD_TYPE for row in lifecycle.runs.items.values())


def test_three_automatic_attempts_and_one_idempotent_manual_survive_restarts(lifecycle):
    good = lifecycle.run(lifecycle.prepare("csv"))
    output = lifecycle.prepare("json")
    lifecycle.failures["json"] = [TimeoutError("private-provider-secret")] * 3
    for attempt in range(1, 4):
        state = lifecycle.run(output)
        if attempt < 3:
            assert state["state"] == "retry_scheduled"
            assert state["attempt_count"] == attempt + 1
            assert state["can_retry"] is False and state["artifact_message_id"] is None
            calls = len(lifecycle.render_calls)
            duplicate = lifecycle.run(output)
            assert duplicate == state and len(lifecycle.render_calls) == calls
            lifecycle.restart()
            restored = lifecycle.service.read(output["output_id"])
            assert restored == state
            lifecycle.advance_due(output)
        else:
            assert state["state"] == "failed" and state["can_retry"] is True
            assert state["attempt_count"] == state["automatic_attempts"] == MAX_AUTOMATIC_ATTEMPTS
    lifecycle.change_run(status="failed")
    sibling_content = lifecycle.download(good)
    assert b"last" in sibling_content
    writes = lifecycle.results.container.sequence
    manual = lifecycle.service.manual_retry(output["output_id"], "request-one")
    repeated = lifecycle.service.manual_retry(output["output_id"], "request-one")
    assert repeated == manual and manual["attempt_count"] == 4
    assert manual["automatic_attempts"] == 3 and manual["state"] == "waiting"
    lifecycle.restart()
    repeated_after_restart = lifecycle.service.manual_retry(output["output_id"], "request-one")
    assert repeated_after_restart == manual
    completed = lifecycle.run(output)
    assert completed["state"] == "completed" and completed["attempt_count"] == 4
    assert completed["automatic_attempts"] == 3
    saved = lifecycle.raw(output)
    assert [attempt["kind"] for attempt in saved["attempts"]] == ["automatic"] * 3 + ["manual"]
    assert len(saved["manual_requests"]) == 1
    assert lifecycle.render_calls.count(("json", "exact_records_v1")) == 4
    assert lifecycle.render_calls.count(("csv", "tabular_records_v1")) == 1
    assert lifecycle.results.container.sequence == writes
    completed_rows = json.loads(lifecycle.download(completed))
    assert completed_rows == ROWS
    assert "private-provider-secret" not in json.dumps(completed)


def test_real_prepared_report_and_empty_text_are_valid_artifacts(lifecycle):
    report = "# Prepared findings\n\nThe final retained finding is **complete**.\n"
    producer = replace(lifecycle.results.producer, step_id="prepared")
    lifecycle.results.add_producer(producer)
    saved = lifecycle.results.save(
        grounded=False,
        outputs=[
            NamedOutput("report", "markdown-v1", report, complete(1)),
            NamedOutput("empty_text", "text-v1", "", complete(1)),
            NamedOutput("empty_markdown", "markdown-v1", "", complete(1)),
        ],
        producer=producer,
    )
    # A separate producer retains prepared content once; file attempts never call it.
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({"step_id": "prepared", "enabled": True, "capability_id": "document_analyze"})
    lifecycle.runs.upsert_item(run)
    report_output = lifecycle.prepare("pdf", reference=saved.output("report"))
    text_output = lifecycle.prepare("txt", reference=saved.output("empty_text"))
    markdown_output = lifecycle.prepare("md", reference=saved.output("empty_markdown"))
    completed_report = lifecycle.run(report_output)
    completed_text = lifecycle.run(text_output)
    completed_markdown = lifecycle.run(markdown_output)
    assert completed_report["state"] == "completed"
    assert completed_text["state"] == completed_markdown["state"] == "completed"
    pdf_bytes = lifecycle.download(completed_report)
    assert pdf_bytes.startswith(b"%PDF-")
    text_bytes = lifecycle.download(completed_text)
    markdown_bytes = lifecycle.download(completed_markdown)
    assert text_bytes == markdown_bytes == b""
    assert completed_text["size_bytes"] == completed_markdown["size_bytes"] == 0
    operations = lifecycle.modules.operations
    with pytest.raises(ValueError, match="empty"):
        operations.upload_generated_file_artifact_stream_for_user(
            "owner", "conversation-1", "legacy.txt", io.BytesIO(b""), 0,
        )


@pytest.mark.parametrize("boundary", ["before_blob", "after_blob", "after_message", "before_commit", "after_commit"])
def test_process_loss_reconciles_intent_without_duplicate_visibility(lifecycle, boundary):
    output = lifecycle.prepare()

    def crash():
        raise Crash(boundary)

    if boundary == "before_blob":
        lifecycle.blobs.before_upload = crash
    elif boundary == "after_blob":
        lifecycle.blobs.after_upload = crash
    elif boundary == "after_message":
        lifecycle.messages.after_create = crash
    else:
        original = lifecycle.runs.execute_item_batch

        def batch(batch_operations, partition_key, **kwargs):
            operation = batch_operations[-1]
            body = operation[1][-1]
            is_commit = isinstance(body, dict) and body.get("state") == "completed"
            if is_commit and boundary == "before_commit":
                lifecycle.runs.execute_item_batch = original
                crash()
            result = original(batch_operations, partition_key, **kwargs)
            if is_commit and boundary == "after_commit":
                lifecycle.runs.execute_item_batch = original
                crash()
            return result

        lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", batch)
    with pytest.raises(Crash):
        lifecycle.run(output)
    assert all(stream.closed for stream in lifecycle.output_streams)
    lifecycle.restart()
    lifecycle.now += timedelta(seconds=11)
    state = lifecycle.service.reconcile(output["output_id"])
    if boundary != "after_commit":
        assert state["state"] == "retry_scheduled"
        lifecycle.advance_due(output)
        state = lifecycle.run(output)
    if boundary == "before_blob":
        assert len(lifecycle.render_calls) == 2
    else:
        assert len(lifecycle.render_calls) == 1
    assert state["state"] == "completed"
    assert len(lifecycle.messages.items) == lifecycle.blobs.uploads == 1
    recovered_rows = json.loads(lifecycle.download(state))
    assert recovered_rows == ROWS


@pytest.mark.parametrize("boundary", ["blob_ack", "message_ack", "commit_ack"])
def test_uncertain_acknowledgements_are_success_only_after_authoritative_read(lifecycle, boundary):
    output = lifecycle.prepare()

    def lost_ack():
        raise TimeoutError("Private acknowledgement loss.")

    if boundary == "blob_ack":
        lifecycle.blobs.after_upload = lost_ack
    elif boundary == "message_ack":
        lifecycle.messages.after_create = lost_ack
    else:
        original = lifecycle.runs.execute_item_batch

        def batch(batch_operations, partition_key, **kwargs):
            result = original(batch_operations, partition_key, **kwargs)
            body = batch_operations[-1][1][-1]
            if isinstance(body, dict) and body.get("state") == "completed":
                lifecycle.runs.execute_item_batch = original
                lost_ack()
            return result

        lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", batch)
    state = lifecycle.run(output)
    if boundary == "blob_ack":
        assert state["state"] == "retry_scheduled"
        lifecycle.advance_due(output)
        state = lifecycle.run(output)
    assert state["state"] == "completed"
    assert state["attempt_count"] == state["automatic_attempts"] == (2 if boundary == "blob_ack" else 1)
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == len(lifecycle.messages.items) == 1


def test_staged_history_and_download_are_withheld_until_output_commit(lifecycle):
    output = lifecycle.prepare()
    observations = []

    def while_staged():
        message = next(iter(lifecycle.messages.items.values()))
        with lifecycle.app.test_request_context():
            with pytest.raises(PermissionError):
                lifecycle.modules.routes._get_authorized_chat_artifact_message(
                    "owner", "conversation-1", message["id"],
                )
            safe = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
        observations.append(safe)
        outputs = lifecycle.service.list_public_outputs("run-1")
        committed = lifecycle.service.committed_artifacts("run-1")
        assert safe["content_unavailable"] is True
        assert "blob_path" not in safe
        assert safe["metadata"] == {"generated_artifact_origin": "orchestration_retained_output"}
        assert outputs[0]["state"] == "rendering" and outputs[0]["artifact_message_id"] is None
        assert committed == []

    lifecycle.messages.after_create = while_staged
    state = lifecycle.run(output)
    assert state["state"] == "completed" and len(observations) == 1
    message = lifecycle.service.transport.message(lifecycle.raw(output), committed=True)
    with lifecycle.app.test_request_context():
        safe = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    encoded = json.dumps(safe)
    assert "generated_artifact_source" not in encoded and "blob_path" not in encoded
    assert safe["filename"] == state["file_name"]
    lifecycle.results.denied.add("document-1")
    with lifecycle.app.test_request_context():
        blocked = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
        blocked_cache = lifecycle.modules.sources.sanitize_generated_artifact_history(safe, "owner")
    assert blocked["content_unavailable"] is True
    assert blocked_cache["content_unavailable"] is True
    assert "Saved workflow" not in blocked_cache["content"]
    with pytest.raises(PermissionError):
        lifecycle.download(state)
    with pytest.raises(PermissionError):
        lifecycle.service.manual_retry(output["output_id"], "revoked-retry")
    lifecycle.results.denied.clear()
    with lifecycle.app.test_request_context():
        restored = lifecycle.modules.sources.sanitize_generated_artifact_history(blocked_cache, "owner")
    assert not restored.get("content_unavailable") and restored["filename"] == state["file_name"]


def test_concurrent_request_does_not_start_another_attempt(lifecycle):
    output = lifecycle.prepare()
    entered, release = threading.Event(), threading.Event()
    original = lifecycle.service.renderer

    def blocked_renderer(**kwargs):
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("Concurrent fixture did not release the renderer.")
        return original(**kwargs)

    lifecycle.service.renderer = blocked_renderer
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(lifecycle.run, output)
        if not entered.wait(timeout=10):
            raise AssertionError("The first worker never entered rendering.")
        try:
            duplicate = lifecycle.run(output)
            duplicate_admission = lifecycle.prepare()
            assert duplicate["state"] == duplicate_admission["state"] == "rendering"
            assert duplicate["attempt_count"] == 1
        finally:
            release.set()
        completed = running.result(timeout=20)
    assert completed["state"] == "completed"
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


def test_stolen_or_expired_output_lease_cannot_commit_or_advance(lifecycle):
    output = lifecycle.prepare()
    stale = lifecycle.service.claim_due(output["output_id"], worker_id="old-worker")
    lifecycle.now += timedelta(seconds=11)
    current = lifecycle.service.claim_due(output["output_id"], worker_id="new-worker")
    before = lifecycle.raw(output)
    with pytest.raises(OutputConflictError):
        lifecycle.service.store.commit(stale, intent_id="guessed", check=lambda record: None)
    stale_result = lifecycle.service.render_attempt(output["output_id"], claim=stale)
    after = lifecycle.raw(output)
    assert stale_result["state"] == "rendering"
    assert before == after and after["lease"]["token"] == current.token
    recovered = lifecycle.service.render_attempt(output["output_id"], claim=current)
    assert recovered["state"] == "retry_scheduled" and recovered["attempt_count"] == 2
    assert not lifecycle.blobs.data and not lifecycle.render_calls


def test_scheduler_selects_non_run_rows_and_durable_retry_due_times(lifecycle):
    output = lifecycle.prepare()
    due = enumerate_due_outputs(lifecycle.runs, now=lifecycle.now)
    assert due == [{
        "output_id": output["output_id"], "run_id": "run-1",
        "user_id": "owner", "conversation_id": "conversation-1",
    }]
    lifecycle.failures["json"] = [TimeoutError("Private transient failure")]
    waiting = lifecycle.run(output)
    not_due = enumerate_due_outputs(lifecycle.runs, now=lifecycle.now)
    assert waiting["state"] == "retry_scheduled" and not_due == []
    lifecycle.advance_due(output)
    due_again = enumerate_due_outputs(lifecycle.runs, now=lifecycle.now)
    assert due_again == due


@pytest.mark.parametrize("boundary", ["before_blob", "after_blob", "after_message", "commit_batch"])
def test_stop_fences_every_publication_boundary_and_cleans_staging(lifecycle, boundary):
    output = lifecycle.prepare()

    def stop():
        lifecycle.change_run(cancellation_requested_at=lifecycle.now.isoformat())

    if boundary == "before_blob":
        lifecycle.blobs.before_upload = stop
    elif boundary == "after_blob":
        lifecycle.blobs.after_upload = stop
    elif boundary == "after_message":
        lifecycle.messages.after_create = stop
    else:
        original = lifecycle.runs.execute_item_batch

        def batch(batch_operations, partition_key, **kwargs):
            body = batch_operations[-1][1][-1]
            if isinstance(body, dict) and body.get("state") == "completed":
                lifecycle.runs.execute_item_batch = original
                stop()
            return original(batch_operations, partition_key, **kwargs)

        lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", batch)
    state = lifecycle.run(output)
    assert state["state"] == "cancelled" and state["can_retry"] is False
    assert state["artifact_message_id"] is None and state["attempt_count"] == 1
    private = lifecycle.raw(output)
    assert private["committed_intent"] is None
    for message in list(lifecycle.messages.items.values()):
        with lifecycle.app.test_request_context():
            with pytest.raises(PermissionError):
                lifecycle.modules.routes._get_authorized_chat_artifact_message(
                    "owner", "conversation-1", message["id"],
                )
            hidden = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
        assert hidden["content_unavailable"] is True
    lifecycle.now += timedelta(seconds=11)
    cleaned = lifecycle.service.reconcile(output["output_id"])
    assert cleaned["state"] == "cancelled"
    assert not lifecycle.messages.items and not lifecycle.blobs.data
    repeated = lifecycle.run(output)
    assert repeated["state"] == "cancelled" and len(lifecycle.render_calls) == 1


@pytest.mark.parametrize("revocation", ["source", "screening", "capability"])
@pytest.mark.parametrize("boundary", ["after_render", "after_blob"])
def test_current_access_is_rechecked_after_render_and_before_commit(lifecycle, revocation, boundary):
    output = lifecycle.prepare()

    def revoke():
        if revocation == "source":
            lifecycle.results.denied.add("document-1")
        elif revocation == "screening":
            lifecycle.results.held.add("document-1")
        else:
            lifecycle.capabilities = False

    if boundary == "after_render":
        real = lifecycle.service.renderer

        def renderer(**kwargs):
            rendered = real(**kwargs)
            revoke()
            return rendered

        lifecycle.service.renderer = renderer
    else:
        lifecycle.blobs.after_upload = revoke
    state = lifecycle.run(output)
    assert state["state"] == "failed" and state["automatic_attempts"] == 1
    assert state["can_retry"] is False and state["artifact_message_id"] is None
    assert state["error_code"] == {
        "source": "output_access_denied", "screening": "output_screening_hold",
        "capability": "output_capability_disabled",
    }[revocation]
    with pytest.raises((PermissionError, OutputError, ScreeningError)):
        lifecycle.service.manual_retry(output["output_id"], "not-eligible")
    lifecycle.now += timedelta(seconds=11)
    lifecycle.service.reconcile(output["output_id"])
    assert not lifecycle.messages.items and not lifecycle.blobs.data


@pytest.mark.parametrize("revocation", [
    "source", "screening", "source_deleted", "capability", "owner",
    "conversation_deleted", "run_deleted", "superseded", "step_disabled",
])
def test_completed_download_history_and_retry_reauthorize_current_state(lifecycle, revocation):
    output = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(output)
    message = lifecycle.service.transport.message(record, committed=True)
    if revocation == "source":
        lifecycle.results.denied.add("document-1")
    elif revocation == "screening":
        lifecycle.results.held.add("document-1")
    elif revocation == "source_deleted":
        lifecycle.results.sources.clear()
    elif revocation == "capability":
        lifecycle.capabilities = False
    elif revocation in {"owner", "conversation_deleted"}:
        conversation = lifecycle.conversations.read_item("conversation-1", "conversation-1")
        conversation.update(
            {"user_id": "new-owner"} if revocation == "owner" else {"orchestration_deleted": True},
        )
        lifecycle.conversations.upsert_item(conversation)
    elif revocation == "run_deleted":
        lifecycle.change_run(checkpoints_deleted=True)
    elif revocation == "superseded":
        lifecycle.change_run(latest_attempt_run_id="replacement-run")
    else:
        run = lifecycle.runs.read_item("run-1", "conversation-1")
        next(step for step in run["plan"]["steps"] if step["step_id"] == "json_file")["enabled"] = False
        lifecycle.runs.upsert_item(run)
    with pytest.raises((PermissionError, ValueError, ScreeningError)):
        lifecycle.download(output)
    with pytest.raises((PermissionError, ValueError, ScreeningError)):
        lifecycle.service.manual_retry(output["output_id"], "revoked-manual")
    with lifecycle.app.test_request_context():
        safe = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    assert safe["content_unavailable"] is True
    assert safe["metadata"] == {"generated_artifact_origin": "orchestration_retained_output"}
    assert "blob_path" not in safe
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


@pytest.mark.parametrize("revocation,reason", [
    ("source", "output_access_denied"),
    ("screening", "output_screening_hold"),
    ("source_deleted", "output_source_changed"),
    ("source_changed", "output_source_changed"),
    ("source_digest_changed", "output_source_changed"),
    ("retained_deleted", "output_source_unavailable"),
    ("retained_guard_missing", "output_source_unavailable"),
    ("retained_commit_missing", "output_source_unavailable"),
    ("retained_manifest_missing", "output_source_unavailable"),
    ("source_producer_deleted", "output_source_unavailable"),
    ("source_metadata_missing", "output_source_unavailable"),
    ("message_missing", "output_artifact_missing"),
    ("capability", "output_capability_disabled"),
])
def test_public_output_list_preserves_authorized_siblings(lifecycle, revocation, reason):
    second_source = lifecycle.retain_source("document-2")
    hidden = lifecycle.run(lifecycle.prepare("json", reference=second_source))
    visible = lifecycle.run(lifecycle.prepare("csv"))
    cached_cards = lifecycle.service.committed_artifacts("run-1")
    lifecycle.change_run(artifacts=[
        *cached_cards,
        {"capability": "render_file", "artifact_message_id": "not-an-authorized-output"},
    ])
    hidden_before = lifecycle.raw(hidden)
    visible_before = lifecycle.raw(visible)
    source_run = second_source.producer.run_id
    store = lifecycle.service.results.store
    if revocation == "source":
        lifecycle.results.denied.add("document-2")
    elif revocation == "screening":
        lifecycle.results.held.add("document-2")
    elif revocation == "source_deleted":
        del lifecycle.results.sources["document-2"]
    elif revocation == "source_changed":
        lifecycle.results.sources["document-2"]["source_version"] = 2
    elif revocation == "source_digest_changed":
        lifecycle.results.sources["document-2"]["content_sha256"] = "2" * 64
    elif revocation == "retained_deleted":
        binding = store.prepare_orchestration_result(
            "owner", "conversation-1", source_run, "analyze", guard_token="server-attempt-token",
        )
        store.fence_analysis_attempt(binding["binding"])
    elif revocation in {"retained_guard_missing", "retained_commit_missing", "retained_manifest_missing"}:
        kind = {
            "retained_guard_missing": "lifecycle",
            "retained_commit_missing": "final",
            "retained_manifest_missing": "manifest",
        }[revocation]
        rows = [
            row for row in lifecycle.results.container.items.values()
            if row["run_id"] == source_run and (
                row.get("record_kind") == kind or row.get("id", "").endswith(f":{kind}")
            )
        ]
        if not rows:
            raise AssertionError(f"The fixture did not create the expected {kind} records.")
        for row in rows:
            lifecycle.results.container.delete_item(row["id"], source_run)
    elif revocation == "source_producer_deleted":
        run = lifecycle.runs.read_item(source_run, "conversation-1")
        run["checkpoints_deleted"] = True
        lifecycle.runs.upsert_item(run)
    elif revocation == "source_metadata_missing":
        original = lifecycle.service.results.access.source_metadata_reader

        def metadata(document_id, **kwargs):
            if document_id == "document-2":
                raise LookupError("Private source disappeared between current ACL and metadata reads.")
            return original(document_id, **kwargs)

        lifecycle.service.results.access.source_metadata_reader = metadata
    elif revocation == "message_missing":
        message = lifecycle.messages.read_item(hidden["artifact_message_id"], "conversation-1")
        lifecycle.messages.delete_item(message["id"], "conversation-1", etag=message["_etag"])
    elif revocation == "capability":
        lifecycle.service.authorize_execution = lambda record, **kwargs: record["id"] != hidden["output_id"]
    projections = lifecycle.service.list_public_outputs("run-1")
    by_id = {projection["output_id"]: projection for projection in projections}
    denied = by_id[hidden["output_id"]]
    allowed = by_id[visible["output_id"]]
    cards = lifecycle.service.committed_artifacts("run-1")
    data = lifecycle.download(visible)
    hidden_after = lifecycle.raw(hidden)
    visible_after = lifecycle.raw(visible)
    assert len(projections) == 2
    assert denied["state"] == "completed" and denied["available"] is False
    assert denied["error_code"] == reason and denied["message"] != "This file is ready."
    assert denied["artifact_message_id"] is denied["next_retry_at"] is None
    assert denied["can_retry"] is False
    assert denied["row_count"] is denied["character_count"] is denied["size_bytes"] is None
    assert denied["file_name"] == hidden["file_name"]
    assert denied["attempt_count"] == denied["automatic_attempts"] == 1
    assert allowed["available"] is True and allowed["artifact_message_id"] == visible["artifact_message_id"]
    assert [card["artifact_message_id"] for card in cards] == [visible["artifact_message_id"]]
    assert b"last" in data
    assert hidden_before == hidden_after and visible_before == visible_after
    assert lifecycle.render_calls == [("json", "exact_records_v1"), ("csv", "tabular_records_v1")]
    for private in ("source_ref", "source_digest", "producer", "manifest", "blob_path", "lease", "document-2"):
        assert private not in json.dumps(projections)


@pytest.mark.parametrize("revocation", ["source", "screening"])
def test_public_outputs_restore_current_access_without_rerendering(lifecycle, revocation):
    hidden = lifecycle.run(lifecycle.prepare())
    collection = lifecycle.results.denied if revocation == "source" else lifecycle.results.held
    collection.add("document-1")
    denied = lifecycle.service.list_public_outputs("run-1")
    unavailable_cards = lifecycle.service.committed_artifacts("run-1")
    collection.clear()
    lifecycle.restart()
    writes = lifecycle.results.container.sequence
    restored = lifecycle.service.list_public_outputs("run-1")
    cards = lifecycle.service.committed_artifacts("run-1")
    downloaded = lifecycle.download(restored[0])
    assert denied[0]["available"] is False and unavailable_cards == []
    assert restored[0]["available"] is True and restored[0] == hidden
    assert [card["artifact_message_id"] for card in cards] == [hidden["artifact_message_id"]]
    assert json.loads(downloaded) == ROWS
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1
    assert lifecycle.results.container.sequence == writes


@pytest.mark.parametrize("state", ["waiting", "retry_scheduled", "failed"])
def test_public_outputs_withhold_retry_controls_after_source_revocation(lifecycle, state):
    output = lifecycle.prepare()
    lifecycle.failures["json"] = [TimeoutError("Private transport failure")] * 3
    for _ in range({"waiting": 0, "retry_scheduled": 1, "failed": 3}[state]):
        output = lifecycle.run(output)
        lifecycle.advance_due(output)
    lifecycle.results.denied.add("document-1")
    projections = lifecycle.service.list_public_outputs("run-1")
    cards = lifecycle.service.committed_artifacts("run-1")
    assert projections[0]["state"] == state and projections[0]["available"] is False
    assert projections[0]["can_retry"] is False and projections[0]["next_retry_at"] is None
    assert projections[0]["artifact_message_id"] is None and cards == []
    with pytest.raises(OutputUnavailableError):
        lifecycle.service.manual_retry(output["output_id"], "denied-request")


@pytest.mark.parametrize("boundary", [
    "outputs", "results", "messages", "source_network", "source_wrapped_network",
    "screening_configuration", "screening_service", "unexpected_callback", "source_reader_missing",
    "metadata_key_error",
])
@pytest.mark.parametrize("operation", [
    "list_public_outputs", "committed_artifacts", "history_file", "history_cached_file", "history_card",
    "history_outputs", "history_cached_outputs", "history_top_level_card",
])
def test_public_output_reads_propagate_infrastructure_failures(lifecycle, boundary, operation):
    completed = lifecycle.run(lifecycle.prepare())
    message = lifecycle.service.transport.message(lifecycle.raw(completed), committed=True)
    if operation == "history_cached_file":
        with lifecycle.app.test_request_context():
            message = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    elif operation == "history_card":
        cards = lifecycle.service.committed_artifacts("run-1")
        message = {
            "id": "assistant-summary", "conversation_id": "conversation-1", "role": "assistant",
            "content": "The requested files are ready.",
            "metadata": {"generated_orchestration_outputs": cards},
        }
    elif operation in {"history_outputs", "history_cached_outputs"}:
        message = lifecycle.output_history()
        if operation == "history_cached_outputs":
            with lifecycle.app.test_request_context():
                message = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    elif operation == "history_top_level_card":
        message = lifecycle.output_history()
        del message["metadata"]["orchestration"]["outputs"]
    expected = (AzureError, OutputStorageError)
    if boundary == "outputs":
        lifecycle.runs.fail_reads = True
    elif boundary == "results":
        lifecycle.results.container.fail_reads = True
    elif boundary == "messages":
        lifecycle.messages.fail_reads = True
    elif boundary == "source_reader_missing":
        lifecycle.service.results.access.source_resolver = None
        expected = OutputError
    else:
        def fail(*args, **kwargs):
            if boundary == "source_network":
                raise TimeoutError("private-source-endpoint")
            if boundary == "source_wrapped_network":
                raise PermissionError("private-wrapper-message") from TimeoutError("private-source-endpoint")
            if boundary == "screening_configuration":
                raise ScreeningConfigurationError()
            if boundary == "screening_service":
                raise ScreeningError()
            if boundary == "metadata_key_error":
                raise KeyError("private unexpected metadata field")
            raise RuntimeError("private unexpected callback details")

        lifecycle.service.results.access.source_metadata_reader = fail
        expected = {
            "source_network": SourceAuthorityUnavailableError, "source_wrapped_network": OutputStorageError,
            "screening_configuration": ScreeningConfigurationError, "screening_service": ScreeningError,
            "unexpected_callback": SourceAuthorityUnverifiedError,
            "metadata_key_error": SourceAuthorityUnverifiedError,
        }[boundary]
    with pytest.raises(expected):
        if operation.startswith("history_"):
            with lifecycle.app.test_request_context():
                lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
        else:
            getattr(lifecycle.service, operation)("run-1")
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


@pytest.mark.parametrize("failure_type,retryable,code", [
    (TimeoutError, True, "source_authority_unavailable"),
    (RuntimeError, False, "source_authority_unverified"),
    (ScreeningError, True, "output_screening_unavailable"),
    (ScreeningConfigurationError, False, "output_screening_unavailable"),
])
def test_current_source_service_failures_preserve_retry_classification(lifecycle, failure_type, retryable, code):
    output = lifecycle.prepare()

    def unavailable(*args, **kwargs):
        raise failure_type("Private source service details")

    lifecycle.service.results.access.source_metadata_reader = unavailable
    for attempt in range(1, 4 if retryable else 2):
        result = lifecycle.run(output)
        if retryable and attempt < 3:
            assert result["state"] == "retry_scheduled" and result["automatic_attempts"] == attempt + 1
            lifecycle.advance_due(output)
        else:
            assert result["state"] == "failed" and result["can_retry"] is retryable
    assert result["error_code"] == code and "Private source" not in json.dumps(result)
    assert not lifecycle.render_calls and not lifecycle.blobs.data


@pytest.mark.parametrize("change", ["owner", "conversation_deleted"])
def test_public_output_list_never_downgrades_conversation_denial_to_file_placeholder(lifecycle, change):
    lifecycle.run(lifecycle.prepare())
    conversation = lifecycle.conversations.read_item("conversation-1", "conversation-1")
    conversation.update({"user_id": "other-owner"} if change == "owner" else {"orchestration_deleted": True})
    lifecycle.conversations.upsert_item(conversation)
    with pytest.raises(OutputUnavailableError):
        lifecycle.service.list_public_outputs("run-1")
    with pytest.raises(OutputUnavailableError):
        lifecycle.service.committed_artifacts("run-1")


@pytest.mark.parametrize("card_location", ["none", "legacy", "top_level", "both"])
@pytest.mark.parametrize("revocation", ["source", "screening", "source_deleted"])
def test_nested_output_history_refreshes_denied_siblings_before_hydration(lifecycle, card_location, revocation):
    second_source = lifecycle.retain_source("document-2")
    hidden = lifecycle.run(lifecycle.prepare("json", reference=second_source))
    visible = lifecycle.run(lifecycle.prepare("csv"))
    message = lifecycle.output_history(with_cards=card_location in {"top_level", "both"})
    if card_location in {"legacy", "both"}:
        message["metadata"]["generated_orchestration_outputs"] = lifecycle.service.committed_artifacts("run-1")
    message["metadata"]["orchestration"]["outputs"][0]["source_ref"] = {"blob_path": "private-cache-locator"}
    message["metadata"]["orchestration"]["outputs"][0]["can_retry"] = True
    before = deepcopy(message)
    if revocation == "source":
        lifecycle.results.denied.add("document-2")
    elif revocation == "screening":
        lifecycle.results.held.add("document-2")
    else:
        del lifecycle.results.sources["document-2"]
    with lifecycle.app.test_request_context():
        safe = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
        screening_error = getattr(g, "content_screening_error", None)
    outputs = safe["metadata"]["orchestration"]["outputs"]
    by_id = {output["output_id"]: output for output in outputs}
    denied = by_id[hidden["output_id"]]
    allowed = by_id[visible["output_id"]]
    assert denied["state"] == "completed" and denied["available"] is False
    assert denied["artifact_message_id"] is None and denied["can_retry"] is False
    assert denied["next_retry_at"] is denied["row_count"] is denied["character_count"] is denied["size_bytes"] is None
    assert denied["error_code"] and denied["message"] != "This file is ready."
    assert allowed["available"] is True and allowed["artifact_message_id"] == visible["artifact_message_id"]
    assert "private-cache-locator" not in json.dumps(safe) and "source_ref" not in json.dumps(outputs)
    assert message == before and screening_error is None
    if card_location in {"top_level", "both"}:
        assert [card["artifact_message_id"] for card in safe["generated_artifacts"]] == [visible["artifact_message_id"]]
    if card_location in {"legacy", "both"}:
        cards = safe["metadata"]["generated_orchestration_outputs"]
        assert cards[0]["status"] == "unavailable" and "artifact_message_id" not in cards[0]
        assert cards[1]["artifact_message_id"] == visible["artifact_message_id"]
    lifecycle.results.denied.clear()
    lifecycle.results.held.clear()
    lifecycle.results.sources["document-2"] = {**source("document-2"), "content_sha256": "1" * 64}
    with lifecycle.app.test_request_context():
        restored = lifecycle.modules.sources.sanitize_generated_artifact_history(safe, "owner")
    restored_by_id = {
        output["output_id"]: output for output in restored["metadata"]["orchestration"]["outputs"]
    }
    assert restored_by_id[hidden["output_id"]]["artifact_message_id"] == hidden["artifact_message_id"]
    assert restored_by_id[hidden["output_id"]]["available"] is True
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 2
    if card_location in {"top_level", "both"}:
        assert len(restored["generated_artifacts"]) == 2


@pytest.mark.parametrize("with_cards", [False, True])
def test_nested_history_refreshes_empty_cache_without_importing_routes(lifecycle, with_cards, monkeypatch):
    cached = lifecycle.output_history(with_cards=with_cards)
    completed = lifecycle.run(lifecycle.prepare())
    expected = lifecycle.service.list_public_outputs("run-1")
    real_import = builtins.__import__

    def reject_route_import(name, *args, **kwargs):
        if name.startswith("route_"):
            raise AssertionError("Status-only history must not import a route owner.")
        return real_import(name, *args, **kwargs)

    with lifecycle.app.test_request_context():
        prior_error = ScreeningConfigurationError()
        prior_sources = {"preserved": {"document_id": "prior-document"}}
        g.content_screening_error = prior_error
        g.content_screening_sources = deepcopy(prior_sources)
        with monkeypatch.context() as scoped:
            scoped.setattr(builtins, "__import__", reject_route_import)
            refreshed = lifecycle.modules.sources.sanitize_generated_artifact_history(cached, "owner")
        error = g.content_screening_error
        sources = g.content_screening_sources
    assert cached["metadata"]["orchestration"]["outputs"] == []
    assert refreshed["metadata"]["orchestration"]["outputs"] == expected
    assert error is prior_error and sources == prior_sources
    if with_cards:
        assert refreshed["generated_artifacts"][0]["artifact_message_id"] == completed["artifact_message_id"]


@pytest.mark.parametrize("state", ["retry_scheduled", "failed"])
def test_nested_history_rechecks_saved_retry_controls(lifecycle, state):
    output = lifecycle.prepare()
    lifecycle.failures["json"] = [TimeoutError("Private transport failure")] * 3
    for _ in range(1 if state == "retry_scheduled" else 3):
        output = lifecycle.run(output)
        lifecycle.advance_due(output)
    cached = lifecycle.output_history(with_cards=False)
    lifecycle.results.denied.add("document-1")
    with lifecycle.app.test_request_context():
        safe = lifecycle.modules.sources.sanitize_generated_artifact_history(cached, "owner")
    masked = safe["metadata"]["orchestration"]["outputs"][0]
    assert masked["state"] == state and masked["available"] is False
    assert masked["can_retry"] is False and masked["next_retry_at"] is None
    lifecycle.results.denied.clear()
    lifecycle.now = lifecycle.deadline + timedelta(seconds=1)
    with lifecycle.app.test_request_context():
        expired = lifecycle.modules.sources.sanitize_generated_artifact_history(cached, "owner")
    current = expired["metadata"]["orchestration"]["outputs"][0]
    assert current["state"] == "failed" and current["can_retry"] is False
    assert current["error_code"] == "output_deadline_exceeded"
    assert current["next_retry_at"] is None and current["artifact_message_id"] is None


@pytest.mark.parametrize("change", ["owner", "conversation_deleted", "run_missing"])
def test_nested_history_clears_links_when_the_owning_scope_is_unavailable(lifecycle, change):
    lifecycle.run(lifecycle.prepare())
    cached = lifecycle.output_history()
    if change == "run_missing":
        run = lifecycle.runs.read_item("run-1", "conversation-1")
        lifecycle.runs.delete_item("run-1", "conversation-1", etag=run["_etag"])
    else:
        conversation = lifecycle.conversations.read_item("conversation-1", "conversation-1")
        conversation.update({"user_id": "other-owner"} if change == "owner" else {"orchestration_deleted": True})
        lifecycle.conversations.upsert_item(conversation)
    with lifecycle.app.test_request_context():
        safe = lifecycle.modules.sources.sanitize_generated_artifact_history(cached, "owner")
    assert safe["metadata"]["orchestration"]["outputs"] == []
    assert safe["generated_artifacts"] == []


def test_nested_history_requires_registered_service_instead_of_trusting_cache(lifecycle, monkeypatch):
    lifecycle.run(lifecycle.prepare())
    cached = lifecycle.output_history()
    monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", None)
    with lifecycle.app.test_request_context():
        with pytest.raises(OutputError) as failure:
            lifecycle.modules.sources.sanitize_generated_artifact_history(cached, "owner")
    assert failure.value.code == "output_service_required"


def test_stolen_parent_execution_lease_fences_output_owner(lifecycle):
    lifecycle.change_run(execution_lease={
        "token": "parent-one", "expires_at": (lifecycle.now + timedelta(minutes=10)).isoformat(),
    })
    output = lifecycle.prepare()
    claim = lifecycle.service.claim_due(output["output_id"], worker_id="render-one")
    lifecycle.change_run(execution_lease={
        "token": "parent-two", "expires_at": (lifecycle.now + timedelta(minutes=10)).isoformat(),
    })
    with pytest.raises(OutputConflictError):
        lifecycle.service.store.owned(claim)
    before = lifecycle.raw(output)
    stopped_worker = lifecycle.service.render_attempt(output["output_id"], claim=claim)
    after = lifecycle.raw(output)
    assert stopped_worker["state"] == "rendering" and before == after
    assert not lifecycle.render_calls and not lifecycle.blobs.data


def test_output_and_run_deletion_never_recreate_admitted_output(lifecycle):
    output = lifecycle.prepare()
    claim = lifecycle.service.claim_due(output["output_id"], worker_id="late-worker")
    cancelled = lifecycle.service.cancel(output["output_id"], deleted=True)
    assert cancelled["state"] == "cancelled"
    with pytest.raises(OutputUnavailableError):
        lifecycle.prepare()
    resumed = lifecycle.service.render_attempt(output["output_id"], claim=claim)
    assert resumed["state"] == "cancelled" and not lifecycle.blobs.data
    private = lifecycle.raw(output)
    lifecycle.runs.delete_item(
        item=output["output_id"], partition_key="conversation-1", etag=private["_etag"],
    )
    with pytest.raises(OutputUnavailableError, match="unavailable"):
        lifecycle.prepare()
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    assert output["output_id"] in run["render_output_ids"]
    lifecycle.runs.delete_item(item="run-1", partition_key="conversation-1", etag=run["_etag"])
    with pytest.raises(OutputUnavailableError):
        lifecycle.service.render_attempt(output["output_id"])


def test_user_artifact_delete_tombstones_before_removing_bytes(lifecycle):
    output = lifecycle.run(lifecycle.prepare())
    removed = lifecycle.modules.operations.delete_generated_chat_artifact_for_user(
        "owner", "conversation-1", output["artifact_message_id"],
    )
    private = lifecycle.raw(output)
    assert removed is True and private["state"] == "cancelled" and private["deleted_at"]
    with pytest.raises(OutputUnavailableError):
        lifecycle.prepare()
    with pytest.raises((PermissionError, LookupError)):
        lifecycle.download(output)


@pytest.mark.parametrize("boundary", ["before_attempt", "during_render", "backoff"])
def test_deadline_is_persistent_and_never_reset_by_restart(lifecycle, boundary):
    lifecycle.deadline = lifecycle.now + timedelta(seconds=1)
    output = lifecycle.prepare()
    if boundary == "before_attempt":
        lifecycle.now += timedelta(seconds=2)
        lifecycle.restart()
    elif boundary == "during_render":
        real = lifecycle.service.renderer

        def renderer(**kwargs):
            rendered = real(**kwargs)
            lifecycle.now += timedelta(seconds=2)
            return rendered

        lifecycle.service.renderer = renderer
    else:
        error = TimeoutError("private retry advice")
        error.retry_after = 10
        lifecycle.failures["json"] = [error]
    state = lifecycle.run(output)
    assert state["state"] in {"failed", "cancelled"}
    assert state["error_code"] == "output_deadline_exceeded" and not state["can_retry"]
    assert state["attempt_count"] == 1 and not lifecycle.blobs.data
    with pytest.raises((OutputUnavailableError, OutputError)):
        lifecycle.service.manual_retry(output["output_id"], "deadline-retry")


def test_committed_file_remains_available_after_deadline_and_sibling_stop(lifecycle):
    good = lifecycle.run(lifecycle.prepare("csv"))
    sibling = lifecycle.prepare("json")
    lifecycle.service.cancel(sibling["output_id"])
    lifecycle.change_run(status="cancelled", cancellation_requested_at=lifecycle.now.isoformat())
    lifecycle.now = lifecycle.deadline + timedelta(hours=1)
    content = lifecycle.download(good)
    assert b"last" in content
    complete = lifecycle.service.read(good["output_id"])
    assert complete["state"] == "completed" and complete["can_retry"] is False


def test_transport_failures_retry_three_times_without_recomputing_sources(lifecycle):
    good = lifecycle.run(lifecycle.prepare("csv"))
    output = lifecycle.prepare()
    writes = lifecycle.results.container.sequence

    def transport_down():
        raise TimeoutError("Private network endpoint failure.")

    for index in range(3):
        lifecycle.blobs.before_upload = transport_down
        state = lifecycle.run(output)
        if index < 2:
            assert state["state"] == "retry_scheduled"
            lifecycle.advance_due(output)
            lifecycle.restart()
        else:
            assert state["state"] == "failed" and state["can_retry"]
    assert state["attempt_count"] == state["automatic_attempts"] == 3
    assert lifecycle.results.container.sequence == writes
    lifecycle.service.manual_retry(output["output_id"], "single-manual-transport")
    completed = lifecycle.run(output)
    assert completed["state"] == "completed" and completed["attempt_count"] == 4
    assert len(lifecycle.messages.items) == 2 and lifecycle.blobs.uploads == 2
    private = lifecycle.raw(output)
    assert len(private["intents"]) == 4
    lifecycle.now += timedelta(seconds=11)
    reconciled = lifecycle.service.reconcile(output["output_id"])
    assert reconciled["state"] == "completed"
    assert len(lifecycle.messages.items) == len(lifecycle.blobs.data) == 2
    sibling_content = lifecycle.download(good)
    assert b"last" in sibling_content
    assert lifecycle.results.container.sequence == writes


def test_safe_retry_guidance_is_honored_and_bounded(lifecycle):
    output = lifecycle.prepare()
    error = AzureError("Provider endpoint and credential must never be public.")
    error.status_code = 429
    error.headers = {"Retry-After": "7"}
    lifecycle.failures["json"] = [error]
    state = lifecycle.run(output)
    delay = (parse_time(state["next_retry_at"]) - lifecycle.now).total_seconds()
    assert delay == 7 and state["state"] == "retry_scheduled"
    assert "credential" not in json.dumps(state) and state["error_code"] == "output_storage_unavailable"


@pytest.mark.parametrize("failure", [
    PermissionError("private deny details"),
    GeneratedFileExportError("invalid_options", "private invalid option details"),
    GeneratedFileExportError("layout_overflow", "private layout details"),
    GeneratedFileExportError("incomplete_source", "private partial data"),
    ValueError("private deterministic error"),
])
def test_nonretryable_failures_never_schedule_automatic_or_manual_replay(lifecycle, failure):
    output = lifecycle.prepare()
    lifecycle.failures["json"] = [failure]
    failed = lifecycle.run(output)
    assert failed["state"] == "failed" and failed["automatic_attempts"] == 1
    assert failed["can_retry"] is False and failed["next_retry_at"] is None
    with pytest.raises(OutputError):
        lifecycle.service.manual_retry(output["output_id"], "invalid-retry")
    duplicate = lifecycle.run(output)
    expected = {
        **failed, "available": True, "message": "This file could not be created.",
    } if isinstance(failure, PermissionError) else failed
    assert duplicate == expected and len(lifecycle.render_calls) == 1
    assert "private" not in json.dumps(failed)


def test_office_transient_retryability_is_preserved(lifecycle):
    output = lifecycle.prepare()
    error = GeneratedFileExportError("render_io", "Private renderer I/O condition.")
    error.retryable = True
    lifecycle.failures["json"] = [error]
    state = lifecycle.run(output)
    assert state["state"] == "retry_scheduled" and state["attempt_count"] == 2


@pytest.mark.parametrize("mutation", ["digest", "count", "truncated_blob", "missing_blob"])
def test_invalid_bytes_or_orphan_messages_are_never_committed(lifecycle, mutation):
    output = lifecycle.prepare()
    if mutation in {"digest", "count"}:
        real = lifecycle.service.renderer

        def renderer(**kwargs):
            rendered = real(**kwargs)
            if mutation == "digest":
                rendered.content_sha256 = "0" * 64
            else:
                rendered.record_count -= 1
            return rendered

        lifecycle.service.renderer = renderer
    elif mutation == "truncated_blob":
        def corrupt():
            key = next(iter(lifecycle.blobs.data))
            lifecycle.blobs.data[key] = lifecycle.blobs.data[key][:-1]

        lifecycle.blobs.after_upload = corrupt
    else:
        lifecycle.messages.after_create = lifecycle.blobs.data.clear
    state = lifecycle.run(output)
    assert state["state"] == "failed" and state["can_retry"] is False
    assert state["artifact_message_id"] is None and state["attempt_count"] == 1
    private = lifecycle.raw(output)
    assert private["committed_intent"] is None
    lifecycle.now += timedelta(seconds=11)
    lifecycle.service.reconcile(output["output_id"])
    assert not lifecycle.blobs.data and not lifecycle.messages.items


def test_commit_ack_and_recovery_read_loss_does_not_admit_another_attempt(lifecycle):
    output = lifecycle.prepare()
    original = lifecycle.runs.execute_item_batch

    def batch(batch_operations, partition_key, **kwargs):
        result = original(batch_operations, partition_key, **kwargs)
        body = batch_operations[-1][1][-1]
        if isinstance(body, dict) and body.get("state") == "completed":
            lifecycle.runs.execute_item_batch = original
            lifecycle.runs.fail_reads = True
            raise TimeoutError("Commit happened but both acknowledgement and read failed.")
        return result

    lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", batch)
    with pytest.raises(OutputStorageError):
        lifecycle.run(output)
    lifecycle.runs.fail_reads = False
    lifecycle.restart()
    reconciled = lifecycle.service.reconcile(output["output_id"])
    assert reconciled["state"] == "completed" and reconciled["attempt_count"] == 1
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1
    manual = lifecycle.service.manual_retry(output["output_id"], "uncertain-old-commit")
    assert manual == reconciled


@pytest.mark.parametrize("boundary", ["message", "commit"])
def test_persistent_manifest_failures_are_bounded_and_manual_reuses_exact_bytes(lifecycle, boundary):
    output = lifecycle.prepare()
    original = lifecycle.runs.execute_item_batch

    def commit_down(batch_operations, partition_key, **kwargs):
        body = batch_operations[-1][1][-1]
        if isinstance(body, dict) and body.get("state") == "completed":
            raise TimeoutError("Fixture commit transport failed before its write.")
        return original(batch_operations, partition_key, **kwargs)

    def message_down():
        raise TimeoutError("Fixture message transport failed before its write.")

    if boundary == "commit":
        lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", commit_down)
    for index in range(3):
        if boundary == "message":
            lifecycle.messages.before_create = message_down
        state = lifecycle.run(output)
        if index < 2:
            assert state["state"] == "retry_scheduled" and state["attempt_count"] == index + 2
            lifecycle.advance_due(output)
            lifecycle.restart()
        else:
            assert state["state"] == "failed" and state["can_retry"]
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1
    private = lifecycle.raw(output)
    assert private["committed_intent"] is None
    assert [attempt["state"] for attempt in private["attempts"]] == ["failed"] * 3
    lifecycle.monkeypatch.setattr(lifecycle.runs, "execute_item_batch", original)
    # A readonly reconciliation cannot silently create a fourth automatic attempt.
    still_failed = lifecycle.service.reconcile(output["output_id"])
    assert still_failed["state"] == "failed" and still_failed["attempt_count"] == 3
    manual = lifecycle.service.manual_retry(output["output_id"], "manual-manifest")
    assert manual["attempt_count"] == 4 and manual["automatic_attempts"] == 3
    completed = lifecycle.run(output)
    private = lifecycle.raw(output)
    assert completed["state"] == "completed" and completed["attempt_count"] == 4
    assert private["committed_attempt_number"] == 4
    assert [attempt["state"] for attempt in private["attempts"]] == ["failed"] * 3 + ["completed"]
    assert private["attempts"][-1]["reused_render_attempt"] == 1
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == len(lifecycle.messages.items) == 1


def test_repeated_process_loss_consumes_only_three_automatic_admissions(lifecycle):
    output = lifecycle.prepare()

    def crash():
        raise Crash("Fixture worker disappeared before blob upload.")

    for index in range(3):
        lifecycle.blobs.before_upload = crash
        with pytest.raises(Crash):
            lifecycle.run(output)
        lifecycle.now += timedelta(seconds=11)
        lifecycle.restart()
        recovered = lifecycle.service.reconcile(output["output_id"])
        if index < 2:
            assert recovered["state"] == "retry_scheduled"
            lifecycle.advance_due(output)
        else:
            assert recovered["state"] == "failed" and recovered["can_retry"]
    assert recovered["attempt_count"] == recovered["automatic_attempts"] == 3
    assert len(lifecycle.render_calls) == 3
    repeated = lifecycle.service.reconcile(output["output_id"])
    assert repeated == recovered
    assert not lifecycle.messages.items and not lifecycle.blobs.data


def test_changed_projection_or_source_is_a_new_identity_not_a_retry(lifecycle):
    original = lifecycle.run(lifecycle.prepare("csv"))
    changed_projection = lifecycle.prepare("csv", columns=("id",))
    producer = replace(lifecycle.results.producer, step_id="second_source")
    lifecycle.results.add_producer(producer)
    new_result = lifecycle.results.save(producer=producer, grounded=False)
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({"step_id": "second_source", "capability_id": "document_analyze", "enabled": True})
    lifecycle.runs.upsert_item(run)
    changed_source = lifecycle.prepare("csv", reference=new_result.output("findings"))
    assert len({item["output_id"] for item in (original, changed_projection, changed_source)}) == 3
    assert changed_projection["attempt_count"] == changed_source["attempt_count"] == 1
    immutable_original = lifecycle.service.read(original["output_id"])
    assert immutable_original == original
    assert len(lifecycle.render_calls) == 1


@pytest.mark.parametrize("mutation", ["path", "version", "attempt", "owner", "digest", "source_kind", "native_mix"])
def test_artifact_binding_is_strict_and_cannot_guess_paths_or_other_producers(lifecycle, mutation):
    completed = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(completed)
    message = lifecycle.service.transport.message(record, committed=True)
    forged = deepcopy(message)
    binding = forged["metadata"]["generated_artifact_source"]
    if mutation == "path":
        binding["blob_path"] = "other-owner/secret"
    elif mutation == "version":
        binding["version"] = True
    elif mutation == "attempt":
        binding["attempt_number"] += 1
    elif mutation == "owner":
        binding["producer"]["user_id"] = "other-owner"
    elif mutation == "digest":
        binding["source_digest"] = "0" * 64
    elif mutation == "source_kind":
        binding["kind"] = "workflow_saved_output"
    else:
        forged["metadata"]["analysis_producer"] = {"kind": "chat"}
    with pytest.raises((PermissionError, ValueError)):
        lifecycle.modules.sources.authorize_generated_artifact_source("owner", forged)
    assert lifecycle.blobs.uploads == 1


def test_factory_is_fail_closed_and_original_owner_scope_is_not_broadened(lifecycle):
    completed = lifecycle.run(lifecycle.prepare())
    message = lifecycle.service.transport.message(lifecycle.raw(completed), committed=True)
    previous = configure_orchestration_artifact_service(None)
    try:
        with pytest.raises(OutputUnavailableError):
            lifecycle.modules.sources.authorize_generated_artifact_source("owner", message)
    finally:
        configure_orchestration_artifact_service(previous)
    with pytest.raises(OutputUnavailableError):
        lifecycle.modules.sources.authorize_generated_artifact_source("participant", message)
    context = lifecycle.modules.sources.authorize_generated_artifact_source("owner", message, for_publication=True)
    assert context["binding"]["kind"] == "orchestration_retained_output"
    assert context["binding"]["producer"]["capability_id"] == "render_file"


def test_output_bounds_and_all_private_streams_close_on_failure(lifecycle, monkeypatch):
    created = []
    original = tempfile.TemporaryFile

    def tracked(*args, **kwargs):
        if kwargs.get("dir") != ".":
            raise AssertionError("Output scratch files must stay in the project.")
        stream = original(*args, **kwargs)
        created.append(stream)
        return stream

    monkeypatch.setattr(tempfile, "TemporaryFile", tracked)
    lifecycle.restart(max_output_bytes=8)
    output = lifecycle.prepare()
    failed = lifecycle.run(output)
    assert failed["state"] == "failed" and failed["automatic_attempts"] == 1
    assert created and all(stream.closed for stream in created)
    assert not lifecycle.blobs.data
    with pytest.raises(OutputError):
        enumerate_due_outputs(lifecycle.runs, limit=0)
    with pytest.raises(OutputError):
        OrchestrationOutputStore(None, user_id="owner", conversation_id="conversation-1", read_conversation=None)
    with pytest.raises(OutputError):
        lifecycle.restart(max_output_bytes=True)


def test_durable_output_admission_has_a_per_run_bound(lifecycle):
    outputs = [lifecycle.prepare(step_id=f"file_{index}") for index in range(32)]
    with pytest.raises(OutputError) as failure:
        lifecycle.prepare(step_id="file_overflow")
    assert failure.value.code == "output_limit_exceeded"
    assert len({output["output_id"] for output in outputs}) == 32
    assert not lifecycle.render_calls and not lifecycle.blobs.data


def test_duplicate_initial_and_manual_admissions_are_atomic(lifecycle):
    producer = lifecycle.add_render_step("json_file")

    def admit():
        return lifecycle.service.ensure_output(
            producer=producer, source_ref=lifecycle.saved.output("findings"),
            export_request=GeneratedFileExportRequest("json"),
            file_name="json_file.json", approved_work_id="run-1",
            deadline_at=lifecycle.deadline.isoformat(),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        admissions = list(pool.map(lambda value: admit(), range(8)))
    assert len({value["output_id"] for value in admissions}) == 1
    assert all(value["attempt_count"] == 1 for value in admissions)
    output = admissions[0]
    lifecycle.failures["json"] = [TimeoutError("fixture transient")] * 3
    for attempt in range(3):
        failed = lifecycle.run(output)
        if attempt < 2:
            lifecycle.advance_due(output)
    assert failed["can_retry"] is True
    with ThreadPoolExecutor(max_workers=4) as pool:
        manual = list(pool.map(
            lambda value: lifecycle.service.manual_retry(output["output_id"], "same-request"),
            range(8),
        ))
    assert all(value["attempt_count"] == 4 and value["automatic_attempts"] == 3 for value in manual)
    record = lifecycle.raw(output)
    assert len(record["manual_requests"]) == 1 and len(record["attempts"]) == 4


def test_manual_failures_are_single_attempts_with_a_durable_bound(lifecycle):
    output = lifecycle.prepare()
    lifecycle.failures["json"] = [TimeoutError("fixture transient")] * 19
    for attempt in range(3):
        state = lifecycle.run(output)
        if attempt < 2:
            lifecycle.advance_due(output)
    for index in range(16):
        admitted = lifecycle.service.manual_retry(output["output_id"], f"manual-{index}")
        assert admitted["automatic_attempts"] == 3 and admitted["attempt_count"] == index + 4
        state = lifecycle.run(output)
        assert state["state"] == "failed" and state["next_retry_at"] is None
    assert state["attempt_count"] == 19 and not state["can_retry"]
    lifecycle.restart()
    with pytest.raises(OutputError):
        lifecycle.service.manual_retry(output["output_id"], "manual-overflow")
    final = lifecycle.raw(output)
    assert len(final["manual_requests"]) == 16 and len(lifecycle.render_calls) == 19


def test_full_larger_retained_result_is_not_replaced_by_a_preview(lifecycle):
    producer = replace(lifecycle.results.producer, step_id="many_records")
    lifecycle.results.add_producer(producer)
    rows = [{**deepcopy(ROWS[0]), "id": f"record-{index}"} for index in range(1001)]
    saved = lifecycle.results.save(
        producer=producer, outputs=[NamedOutput("findings", "records-v1", rows, complete(len(rows)), COLUMNS)],
    )
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({"step_id": "many_records", "capability_id": "document_analyze", "enabled": True})
    lifecycle.runs.upsert_item(run)
    output = lifecycle.prepare(reference=saved.output("findings"))
    completed = lifecycle.run(output)
    actual = json.loads(lifecycle.download(completed))
    assert actual == rows and actual[-1]["id"] == "record-1000"
    assert completed["row_count"] == 1001


def test_partial_results_and_unsupported_requests_never_reach_transport(lifecycle):
    producer = replace(lifecycle.results.producer, step_id="partial_records")
    lifecycle.results.add_producer(producer)
    saved = lifecycle.results.save(
        producer=producer, status="partial",
        outputs=[NamedOutput("findings", "records-v1", ROWS, complete(3, status="partial"), COLUMNS)],
    )
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"].append({"step_id": "partial_records", "capability_id": "document_analyze", "enabled": True})
    lifecycle.runs.upsert_item(run)
    with pytest.raises(ValueError):
        lifecycle.prepare(reference=saved.output("findings"))
    for request in (
        GeneratedFileExportRequest("exe"),
        GeneratedFileExportRequest("json", "invented-profile"),
        GeneratedFileExportRequest("csv", "tabular_records_v1"),
    ):
        with pytest.raises(GeneratedFileExportError):
            lifecycle.service.ensure_output(
                producer=lifecycle.add_render_step("invalid_request"),
                source_ref=lifecycle.saved.output("findings"), export_request=request,
                file_name="requested.json", approved_work_id="run-1",
                deadline_at=lifecycle.deadline.isoformat(),
            )
    with pytest.raises(OutputError):
        lifecycle.service.ensure_output(
            producer=lifecycle.add_render_step("path_request"),
            source_ref={"blob_path": "guessed/source"},
            export_request=GeneratedFileExportRequest("json"), file_name="requested.json",
            approved_work_id="run-1", deadline_at=lifecycle.deadline.isoformat(),
        )
    assert not lifecycle.render_calls and not lifecycle.blobs.data
    assert not any(row.get("record_type") == OUTPUT_RECORD_TYPE for row in lifecycle.runs.items.values())


def test_original_work_identity_cannot_be_adopted_by_another_producer(lifecycle):
    original = lifecycle.run(lifecycle.prepare())
    run = lifecycle.runs.read_item("run-1", "conversation-1")
    run.update(id="run-2", run_id="run-2", attempt_index=2, render_output_ids=[])
    lifecycle.runs.create_item(run)
    other = replace(
        lifecycle.add_render_step("json_file"), run_id="run-2", attempt_index=2,
    )
    with pytest.raises(OutputUnavailableError) as failure:
        lifecycle.service.ensure_output(
            producer=other, source_ref=lifecycle.saved.output("findings"),
            export_request=GeneratedFileExportRequest("json"),
            file_name="json_file.json", approved_work_id="run-1",
            deadline_at=lifecycle.deadline.isoformat(),
        )
    assert failure.value.code == "output_producer_changed"
    same = lifecycle.service.read(original["output_id"])
    assert same == original and lifecycle.blobs.uploads == 1
    assert sum(row.get("record_type") == OUTPUT_RECORD_TYPE for row in lifecycle.runs.items.values()) == 1


def test_corrupt_private_descriptor_cannot_redirect_artifact_reads(lifecycle):
    completed = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(completed)
    message = lifecycle.service.transport.message(record, committed=True)
    for descriptor in [record["intent"], record["committed_intent"], *record["intents"]]:
        descriptor["artifact"]["blob_path"] = "somebody-else/private-file"
    lifecycle.runs.upsert_item(record)
    with pytest.raises(OutputUnavailableError) as failure:
        lifecycle.modules.sources.authorize_generated_artifact_source("owner", message)
    assert failure.value.code == "output_intent_invalid"


def test_expired_read_persists_timeout_without_admitting_an_attempt(lifecycle):
    lifecycle.deadline = lifecycle.now + timedelta(seconds=1)
    output = lifecycle.prepare()
    lifecycle.now += timedelta(seconds=2)
    state = lifecycle.service.read(output["output_id"])
    restored = lifecycle.restart().read(output["output_id"])
    assert state == restored and state["state"] == "failed"
    assert state["error_code"] == "output_deadline_exceeded"
    assert state["attempt_count"] == 1 and not lifecycle.render_calls


def test_real_step_result_marks_retries_waiting_and_only_committed_artifacts(lifecycle):
    producer = lifecycle.add_render_step("json_file")
    reader = lifecycle.service.results.open_result(lifecycle.saved.output("findings"))
    context = SimpleNamespace(
        plan_contract_version=2, execution_deadline_at=lifecycle.deadline.isoformat(),
        result_producer=lambda step: producer,
    )
    step = {
        "step_id": "json_file", "capability_id": "render_file",
        "arguments": {"file_name": "json_file.json", "output_format": "json", "profile": "exact_records_v1"},
    }
    lifecycle.failures["json"] = [TimeoutError("Private renderer transient.")]
    result = execute_render_file(
        step, context, service_factory=lambda *args, **kwargs: lifecycle.service,
        resolve_inputs=lambda step, context: {"source": reader},
        build_step_result=lifecycle.modules.schema.build_step_result,
        build_failure=lifecycle.modules.schema.build_failure, settings={}, user_id="owner",
    )
    assert result["status"] == "waiting" and result["failure"] is None and result["artifacts"] == []
    assert result["wait"]["kind"] == "orchestration_output"
    output = result["outputs"][0]
    lifecycle.advance_due(output)
    complete_result = execute_render_file(
        step, context, service_factory=lambda *args, **kwargs: lifecycle.service,
        resolve_inputs=lambda step, context: {"source": reader},
        build_step_result=lifecycle.modules.schema.build_step_result,
        build_failure=lifecycle.modules.schema.build_failure, settings={}, user_id="owner",
    )
    assert complete_result["status"] == "completed" and len(complete_result["artifacts"]) == 1
    assert complete_result["artifacts"][0]["artifact_message_id"]


_IMPORT_PROBE = r'''
import builtins
import importlib
import socket
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
forbidden = {
    "config", "functions_settings", "functions_appinsights",
    "functions_simplechat_operations", "functions_orchestration_adapters",
    "functions_orchestration_executor", "background_tasks",
    "functions_orchestration_external_identity", "functions_orchestration_external_configuration",
}
real_import = builtins.__import__
attempts = []

def deny_network(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("A pure output service attempted external I/O.")

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("A lower-level output service imported its owner: " + name)
    return real_import(name, globals, locals, fromlist, level)

with patch.object(socket.socket, "connect", deny_network), patch.object(builtins, "__import__", guarded_import):
    for name in sys.argv[3:]:
        importlib.import_module(name)
    from functions_orchestration_output_store import OrchestrationOutputStore, OutputError
    try:
        OrchestrationOutputStore(None, user_id="owner", conversation_id="conversation-1", read_conversation=None)
    except OutputError:
        pass
    else:
        raise AssertionError("An uninitialized output store silently initialized an owner.")
    from functions_orchestration_rendering import output_failure, raise_output_read_infrastructure_failure
    ordinary_failure = output_failure(RuntimeError("An ordinary failure before owner initialization."))
    if ordinary_failure != ("output_failed", False):
        raise AssertionError("Ordinary error classification changed.")
    raise_output_read_infrastructure_failure(PermissionError("An ordinary denial before owner initialization."))
    from test_support.orchestration_results import ResultFixture, ROWS
    fixture = ResultFixture()
    task = fixture.save(grounded=False)
    reader = fixture.restart().open_result(task.output("findings"))
    from functions_orchestration_export_sources import build_orchestration_export_source
    from functions_generated_file_exports import build_generated_file_export, GeneratedFileExportRequest
    source = build_orchestration_export_source(reader)
    with build_generated_file_export(
        source=source, export_request=GeneratedFileExportRequest("json"),
        max_output_bytes=1048576,
    ) as output:
        import json
        records = json.load(output.file_content)
        source.require_complete_consumption()
        if records != ROWS or fixture.container.sequence == 0:
            raise AssertionError("Required operations disappeared under optimization.")
    if not output.file_content.closed:
        raise AssertionError("An output stream escaped cold-import validation.")
    if attempts or forbidden.intersection(sys.modules):
        raise AssertionError("A cold output import reached an application owner or network.")
print("PASS: owner-free output services and explicit optimized-path operations")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_output_services_cold_import_without_owners_or_network(optimized, reverse):
    modules = [
        "functions_orchestration_output_store",
        "functions_orchestration_artifacts",
        "functions_orchestration_rendering",
    ]
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    completed = subprocess.run(
        command + ["-c", _IMPORT_PROBE, str(APP), str(TESTS), *(reversed(modules) if reverse else modules)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout[-6000:] + completed.stderr[-6000:]
    assert "PASS:" in completed.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
