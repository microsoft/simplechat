# test_native_tabular_compute_service.py
"""
Real native query, transformation, checkpoint and data-only service regressions.
Version: 0.261.141
Implemented in: 0.261.127
Replay-location revision identity check added in: 0.261.141

Provider, Cosmos, Blob and document metadata I/O are local doubles. The native
plugin/query/transform/runner/readers and screening rules execute for real.
"""

from contextlib import contextmanager
from copy import deepcopy
import csv
import importlib
import io
import json
import logging
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
import pandas as pd
import pytest

from test_support.app_stubs import stubbed_config


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
USER = "native-user"
CONVERSATION = "native-conversation"


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.revision = 0
        self.created = 0

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="Missing fixture item.")
        return deepcopy(self.items[key])

    def _save(self, body):
        self.revision += 1
        saved = {**deepcopy(body), "_etag": str(self.revision)}
        self.items[(saved[self.partition_field], saved["id"])] = saved
        return deepcopy(saved)

    def create_item(self, body):
        key = (body[self.partition_field], body["id"])
        if key in self.items:
            raise CosmosResourceExistsError(status_code=409, message="Existing fixture item.")
        self.created += 1
        return self._save(body)

    def replace_item(self, item, body, etag=None, **kwargs):
        current = self.read_item(item, body[self.partition_field])
        if etag is not None and current["_etag"] != etag:
            raise ResourceModifiedError(message="Fixture ETag changed.")
        return self._save(body)

    def query_items(self, query, parameters=None, **kwargs):
        params = {item["name"]: item["value"] for item in parameters or []}
        return [
            deepcopy(item) for item in self.items.values()
            if all(item.get(name) == params[f"@{name}"] for name in ("status", "type") if f"@{name}" in params)
        ]


class MemoryBlobs:
    def __init__(self):
        self.values = {}
        self.reads = []
        self.writes = []

    def get_blob_client(self, container, blob):
        owner = self
        key = (container, blob)

        class Blob:
            def exists(self):
                return key in owner.values

            def get_blob_properties(self):
                if key not in owner.values:
                    raise FileNotFoundError("Missing fixture blob.")
                value = owner.values[key]
                return SimpleNamespace(
                    etag=value["etag"], size=len(value["bytes"]), metadata=deepcopy(value["metadata"]),
                )

            def download_blob(self, etag=None, **kwargs):
                value = owner.values[key]
                if etag is not None and value["etag"] != etag:
                    raise ResourceModifiedError(message="Fixture source changed.")
                owner.reads.append(key)
                data = value["bytes"]
                return SimpleNamespace(readall=lambda: data, readinto=lambda target: target.write(data))

            def upload_blob(self, data, overwrite=False, metadata=None, **kwargs):
                if key in owner.values and not overwrite:
                    raise ResourceExistsError(message="Existing fixture checkpoint.")
                if hasattr(data, "read"):
                    data = data.read()
                owner.values[key] = {
                    "bytes": data, "metadata": dict(metadata or {}), "etag": f"blob-{len(owner.writes) + 1}",
                }
                owner.writes.append(key)

            def delete_blob(self, **kwargs):
                owner.values.pop(key, None)

        return Blob()

    def get_container_client(self, container):
        return SimpleNamespace(list_blobs=lambda name_starts_with: [
            {"name": blob, "metadata": deepcopy(value["metadata"])}
            for (stored_container, blob), value in self.values.items()
            if stored_container == container and blob.startswith(name_starts_with)
        ])


def _module(name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    return module


def _no_network(*args, **kwargs):
    raise AssertionError("Native service tests must not use network I/O.")


@contextmanager
def native_runtime(monkeypatch, row_count=25, scope="personal", filename="source.csv"):
    conversations = MemoryContainer("id")
    parents = MemoryContainer("conversation_id")
    jobs = MemoryContainer("user_id")
    blobs = MemoryBlobs()
    publications = []
    state = {"allowed": True}
    source_container = {"personal": "user-documents", "group": "group-documents", "public": "public-documents"}[scope]
    scope_id = USER if scope == "personal" else f"{scope}-1"
    source_path = f"{scope_id}/{filename}"
    document = {
        "id": "source-1", "file_name": filename, "user_id": USER,
        "version": 1, "_etag": "source-revision-1",
        "blob_container": source_container, "blob_path": source_path,
    }
    if scope != "personal":
        document["group_id" if scope == "group" else "public_workspace_id"] = scope_id
    source_text = io.StringIO()
    writer = csv.DictWriter(source_text, fieldnames=["Item_ID", "amount"], lineterminator="\n")
    writer.writeheader()
    writer.writerows({"Item_ID": f"item-{index:06}", "amount": index} for index in range(1, row_count + 1))
    blobs.values[(source_container, source_path)] = {
        "bytes": source_text.getvalue().encode("utf-8"), "etag": "source-blob-1", "metadata": {},
    }
    conversations.create_item({"id": CONVERSATION, "user_id": USER})
    producer = {
        "user_id": USER, "conversation_id": CONVERSATION, "run_id": "parent-run",
        "attempt_index": 1, "step_id": "compute", "capability_id": "tabular_analyze",
        "contract_version": "orchestration-task-result-v1",
    }
    parents.create_item({
        "id": producer["run_id"], "user_id": USER, "conversation_id": CONVERSATION,
        "attempt_index": 1, "status": "running",
        "plan": {"steps": [{"step_id": "compute", "capability_id": "tabular_analyze", "enabled": True}]},
    })
    settings = {
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 500,
        "tabular_generated_output_inline_max_batches": 75,
        "tabular_generated_output_max_batch_rows": 500,
        "tabular_generated_output_batch_concurrency": 4,
    }

    def read_document(document_id, user_id, **kwargs):
        if not state["allowed"] or user_id != USER or document_id != document["id"]:
            raise PermissionError("Fixture source access revoked.")
        return deepcopy(document)

    def read_blob_document(container, blob, user_id):
        if (container, blob) != (source_container, source_path):
            raise PermissionError("Fixture source location denied.")
        return read_document(document["id"], user_id)

    def assert_group_role(user_id, group_id, **kwargs):
        if user_id != USER or group_id != scope_id or not state["allowed"]:
            raise PermissionError("Fixture group access revoked.")

    def publish(*args, **kwargs):
        publications.append((args, kwargs))
        raise AssertionError("A data-only computation reached user publication.")

    original_connect = socket.socket.connect

    def offline_connect(client, address):
        # Windows asyncio builds its internal wake-up socket pair over loopback.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(client, address)
        return _no_network()

    stubs = {
        "functions_authentication": _module("functions_authentication", get_current_user_id=lambda: None),
        "functions_group": _module(
            "functions_group", assert_group_role=assert_group_role,
            find_group_by_id=lambda *args: {"id": scope_id}, get_user_role_in_group=lambda *args: "User",
        ),
        "functions_public_workspaces": _module(
            "functions_public_workspaces", find_public_workspace_by_id=lambda *args: {"id": scope_id},
            get_user_visible_public_workspace_ids_from_settings=lambda *args: [scope_id] if state["allowed"] else [],
        ),
        "functions_simplechat_operations": _module(
            "functions_simplechat_operations",
            commit_generated_chat_artifact_publication_for_user=publish,
            upload_generated_analysis_artifact_stream_for_user=publish,
        ),
        "functions_documents": _module(
            "functions_documents",
            get_document_blob_storage_info=lambda value, **kwargs: (value["blob_container"], value["blob_path"]),
        ),
        "functions_model_endpoint_runtime": _module(
            "functions_model_endpoint_runtime",
            build_semantic_kernel_chat_service_for_model=_no_network,
            resolve_model_endpoint_from_context=lambda *args, **kwargs: None,
        ),
    }
    targets = (
        # Older AST suites leave partial helper modules in sys.modules.
        "functions_assistant_table_exports", "functions_generated_file_exports", "functions_analysis_deliverables",
        "functions_tabular_generated_exports", "functions_native_tabular_compute",
        "functions_native_analysis_results", "functions_tabular_analysis", "functions_tabular_orchestration",
        "semantic_kernel_plugins.tabular_processing_plugin",
    )
    before = dict(sys.modules)
    with monkeypatch.context() as patcher, stubbed_config(
        CLIENTS={"storage_account_office_docs_client": blobs},
        TABULAR_EXTENSIONS={"csv", "xlsx", "xls", "xlsm"},
        cosmos_conversations_container=conversations, cosmos_tabular_export_runs_container=jobs,
        cosmos_orchestration_runs_container=parents,
        storage_account_group_documents_container_name="group-documents",
        storage_account_personal_chat_container_name="personal-chat",
        storage_account_public_documents_container_name="public-documents",
        storage_account_user_documents_container_name="user-documents",
    ):
        patcher.setattr(socket.socket, "connect", offline_connect)
        patcher.setattr(socket, "create_connection", _no_network)
        patcher.setattr(
            sys.modules["functions_appinsights"], "get_appinsights_logger",
            lambda: logging.getLogger("native-fixture"), raising=False,
        )
        for name, module in stubs.items():
            patcher.setitem(sys.modules, name, module)
        for name in targets:
            patcher.delitem(sys.modules, name, raising=False)
        try:
            screening = importlib.import_module("content_screening.access")
            patcher.setattr(screening, "_read_authorized_document", read_document)
            patcher.setattr(screening, "_resolve_blob_document", read_blob_document)
            mixed = importlib.import_module("functions_mixed_source_orchestration")
            patcher.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
                {
                    "document": read_document(identifier, kwargs["user_id"]), "scope": scope,
                    "group_id": scope_id if scope == "group" else None,
                    "public_workspace_id": scope_id if scope == "public" else None,
                }
                for identifier in kwargs["document_ids"]
            ])
            service = importlib.import_module("functions_native_tabular_compute")
            results = importlib.import_module("functions_native_analysis_results")
            planner = importlib.import_module("functions_tabular_orchestration")
            engine = importlib.import_module("functions_tabular_generated_exports")
            patcher.setattr(engine, "get_settings", lambda: deepcopy(settings))
            patcher.setattr(engine, "submit_tabular_generated_output_run", lambda *args: False)
            source_manifest = mixed.resolve_authorized_source_manifest(
                ["source-1"], USER, doc_scope=scope,
                active_group_ids=[scope_id] if scope == "group" else [],
                active_public_workspace_ids=[scope_id] if scope == "public" else [],
            )
            yield SimpleNamespace(
                service=service, results=results, planner=planner, engine=engine,
                producer=producer, source_manifest=source_manifest, document=document, state=state,
                settings=settings, jobs=jobs, parents=parents, conversations=conversations,
                blobs=blobs, publications=publications, patcher=patcher, screening=screening,
            )
        finally:
            for name, module in list(sys.modules.items()):
                filename = getattr(module, "__file__", "") or ""
                if name not in before and str(APP).lower() in filename.lower():
                    sys.modules.pop(name, None)
            for name in targets:
                if name in before:
                    sys.modules[name] = before[name]
                else:
                    sys.modules.pop(name, None)


def transformation_spec():
    return {
        "version": "tabular-transform-v2",
        "fields": [
            {
                "name": "Item_ID", "mode": "deterministic", "type": "string", "nullable": False,
                "expression": {"op": "copy", "source": "Item_ID"},
            },
            {
                "name": "doubled", "mode": "deterministic", "type": "number", "nullable": False,
                "expression": {"op": "add", "left": {"source": "amount"}, "right": {"source": "amount"}},
            },
        ],
    }


def compute_plan(runtime, *, durable=False, query="index == index"):
    plan = runtime.planner.plan_tabular_request(
        "Compute doubled amounts.", [{"file_name": runtime.document["file_name"], "document_id": "source-1"}],
        settings=runtime.settings,
        requested_output_hints={
            "public_output_schema": ["Item_ID", "doubled"],
            "transformation_spec": transformation_spec(), "query_expression": query,
        },
    )
    if durable:
        plan.update({
            "execution_contract": "structured_export", "durable_task_type": "structured_export",
            "reason_code": "durable_intent",
        })
    return plan


def submit(runtime, plan, **factory_options):
    callback = runtime.service.build_native_tabular_compute_callback(
        user_id=USER, conversation_id=CONVERSATION, producer=runtime.producer,
        source_manifest=runtime.source_manifest, gpt_model="gpt-4o", settings=runtime.settings,
        **factory_options,
    )
    return callback(plan=plan, user_question="Compute doubled amounts.")


def open_result(runtime, handle, **kwargs):
    return runtime.results.open_native_tabular_result(
        user_id=USER, conversation_id=CONVERSATION, handle=handle, producer=runtime.producer, **kwargs,
    )


class NativeModelFixture:
    def __init__(self, *, invalid=False):
        self.calls = []
        self.invalid = invalid

    async def get_chat_message_contents(self, chat_history, settings):
        prompt = chat_history.messages[-1].content
        self.calls.append(prompt)
        if self.invalid:
            value = [{"incorrect_field": "not an output"}]
        elif "Input summaries:\n" in prompt:
            summaries = json.loads(prompt.split("Input summaries:\n", 1)[1])
            total = sum(item["counts"]["sum"] for item in summaries)
            value = {"summary": f"Computed total: {total}", "findings": [], "counts": {"sum": total}, "notable_rows": []}
        else:
            rows = json.loads(prompt.split("Input rows:\n", 1)[1])
            total = sum(int(row["amount"]) for row in rows)
            summary = {
                "summary": f"Computed total: {total}", "findings": [],
                "counts": {"sum": total}, "notable_rows": [],
            }
            match = re.search(r"Use exactly these (?:output fields|structured row fields).*?: (\[.*?\])\.", prompt)
            fields = json.loads(match.group(1)) if match else ["Item_ID", "doubled"]
            transformed = []
            for row in rows:
                values = {
                    "Item_ID": row["Item_ID"], "doubled": int(row["amount"]) * 2, "Risk": "Low",
                }
                transformed.append({name: values[name] for name in fields})
            if "structured_rows" in prompt:
                value = {"structured_rows": transformed, "analysis_summary": summary}
            elif prompt.startswith("Analyze the bounded tabular chunk"):
                value = summary
            else:
                value = transformed
        return [SimpleNamespace(content=json.dumps(value), metadata={})]


@pytest.mark.parametrize("count", [0, 37, 30000])
def test_real_query_and_derived_rows_are_complete_and_never_published(monkeypatch, count):
    with native_runtime(monkeypatch, max(1, count)) as runtime:
        plan = compute_plan(runtime, query="amount < 0" if count == 0 else "amount > 0")
        result = submit(runtime, plan)
        if count > 500:
            assert result["status"] == "pending"
            assert result["reader"] is None
            finished = runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
            assert finished["status"] == "completed", finished.get("last_error")
            result = open_result(runtime, result["handle"])
        assert result["status"] == "completed"
        reader = result["reader"]
        rows = list(reader.iter_records())
        assert len(rows) == count
        assert reader.schema == ("Item_ID", "doubled")
        assert reader.completeness["status"] == "complete"
        assert reader.completeness["actual_count"] == count
        if count:
            assert rows[0] == {"Item_ID": "item-000001", "doubled": 2}
            assert rows[-1] == {"Item_ID": f"item-{count:06}", "doubled": count * 2}
            assert all(list(row) == ["Item_ID", "doubled"] for row in rows)
            assert all(row["doubled"] == index * 2 for index, row in enumerate(rows, start=1))
        stored = runtime.engine._read_run(USER, result["handle"]["job_id"])
        assert stored["execution_policy"] == "data_only"
        assert stored["computation_state"] == "complete"
        assert "artifact_set_manifest" not in stored
        assert not stored["final_artifact"] and not stored["combined_artifacts"]
        assert runtime.publications == []
        assert all("/tabular_runs/" in path for container, path in runtime.blobs.writes)
        assert set(result["handle"]) == {"version", "job_id", "request_fingerprint"}


def test_foreground_durable_equivalence_and_restart_reader(monkeypatch):
    with native_runtime(monkeypatch, 61) as runtime:
        result = submit(runtime, compute_plan(runtime))
        foreground = list(result["reader"].iter_records())
    with native_runtime(monkeypatch, 61) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        assert result["status"] == "pending"
        handle = json.loads(json.dumps(result["handle"]))
        finished = runtime.engine.process_tabular_generated_output_run(handle["job_id"], USER)
        assert finished["status"] == "completed", finished.get("last_error")
        del result
        runtime.settings.clear()
        resumed = open_result(runtime, handle)
        durable = list(resumed["reader"].iter_records())
        assert durable == foreground
        assert runtime.publications == []


def test_duplicate_submission_reuses_job_and_rejects_changed_request(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        plan = compute_plan(runtime, durable=True)
        first = submit(runtime, plan)
        writes = len(runtime.blobs.writes)
        second = submit(runtime, plan)
        assert first["handle"] == second["handle"]
        assert runtime.jobs.created == 1
        assert len(runtime.blobs.writes) == writes
        with pytest.raises(runtime.service.NativeTabularComputeError) as error:
            submit(runtime, compute_plan(runtime, durable=True, query="amount > 10"))
        assert error.value.code == "native_compute_request_changed"
        assert runtime.jobs.created == 1


def test_replay_location_owned_by_another_revision_is_refused_before_work(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        archived = {**deepcopy(runtime.document), "id": "source-archived", "_etag": "source-revision-0"}

        def resolve_other_revision(container, blob, user_id):
            if user_id != USER:
                raise PermissionError("Fixture source location denied.")
            return deepcopy(archived)

        runtime.patcher.setattr(runtime.screening, "_resolve_blob_document", resolve_other_revision)
        with pytest.raises(runtime.service.NativeTabularComputeError) as error:
            submit(runtime, compute_plan(runtime))
        assert error.value.code == "native_compute_source_identity_mismatch"
        assert runtime.jobs.created == 0
        assert runtime.blobs.writes == []
        assert runtime.publications == []


def test_snapshot_read_is_historical_but_current_read_and_resume_refuse_change(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime))
        runtime.document.update({"version": 2, "_etag": "source-revision-2"})
        runtime.blobs.values[("user-documents", f"{USER}/source.csv")]["etag"] = "source-blob-2"
        snapshot = open_result(runtime, result["handle"])
        rows = list(snapshot["reader"].iter_records())
        assert rows[-1]["doubled"] == 50
        assert snapshot["reader"].sources[0]["source_version"] == 1
        with pytest.raises(PermissionError):
            open_result(runtime, result["handle"], require_current_sources=True)
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        runtime.document["version"] = 2
        finished = runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        assert finished["status"] == "failed"
        assert runtime.blobs.writes == []


@pytest.mark.parametrize("revocation", ["acl", "screening", "cancel", "deleted", "attempt", "disabled"])
def test_live_revocation_stops_readers_and_background_workers(monkeypatch, revocation):
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        parent = runtime.parents.read_item("parent-run", CONVERSATION)
        if revocation == "acl":
            runtime.state["allowed"] = False
        elif revocation == "screening":
            runtime.document["content_screening"] = {"state": "blocked"}
        elif revocation == "cancel":
            parent["cancellation_requested_at"] = "2026-09-21T00:00:00Z"
        elif revocation == "deleted":
            parent["checkpoints_deleted"] = True
        elif revocation == "attempt":
            parent["attempt_index"] = 2
        else:
            parent["plan"]["steps"][0]["enabled"] = False
        runtime.parents.replace_item(parent["id"], parent)
        with pytest.raises((PermissionError, ValueError, runtime.screening.DocumentHeldError)):
            open_result(runtime, result["handle"])
        finished = runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        assert finished["status"] == "failed"
        assert runtime.blobs.writes == []
        assert runtime.publications == []


def test_partial_or_corrupted_outputs_are_not_complete_results(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime))
        handle = result["handle"]
        key = ("personal-chat", runtime.engine._output_blob_path(USER, CONVERSATION, handle["job_id"], 1))
        rows = json.loads(runtime.blobs.values[key]["bytes"])
        rows[-1]["doubled"] = -1
        runtime.blobs.values[key]["bytes"] = json.dumps(rows).encode("utf-8")
        with pytest.raises(ValueError, match="integrity"):
            list(result["reader"].iter_records())
        run = runtime.engine._read_run(USER, handle["job_id"])
        run["computation_state"] = "pending"
        runtime.jobs.replace_item(run["id"], run)
        with pytest.raises(ValueError, match="complete result"):
            open_result(runtime, handle)


def test_unsupported_selection_and_missing_callbacks_fail_before_work(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        with pytest.raises(runtime.service.NativeTabularComputeError) as error:
            runtime.service.build_native_tabular_compute_callback(
                user_id=USER, conversation_id=CONVERSATION, producer=runtime.producer,
                source_manifest=runtime.source_manifest * 2, gpt_model="gpt-4o", settings=runtime.settings,
            )
        assert error.value.code == "native_compute_multi_source_unsupported"
        plan = compute_plan(runtime)
        declined = runtime.planner.execute_tabular_plan(plan, execution_policy="data_only")
        invalid = runtime.planner.execute_tabular_plan(
            plan, execution_policy="data_only", durable_execution_callback=lambda **kwargs: {"status": "completed"},
        )
        assert declined["execution_state"] == invalid["execution_state"] == "declined"
        assert runtime.jobs.created == 0
        assert runtime.blobs.reads == []
        assert runtime.blobs.writes == []
        assert runtime.publications == []


@pytest.mark.parametrize("task_type", ["structured_export", "hierarchical_analysis", "combined"])
def test_real_semantic_and_analysis_background_completion_has_no_publication(monkeypatch, task_type):
    with native_runtime(monkeypatch, 83) as runtime:
        model = NativeModelFixture()
        runtime.patcher.setattr(runtime.engine, "_build_chat_service", lambda *args, **kwargs: model)
        plan = compute_plan(runtime, durable=True)
        plan.update({"execution_contract": task_type, "durable_task_type": task_type})
        plan["deliverable_contract"]["transformation_spec"] = {}
        plan["requested_output_hints"].pop("transformation_spec")
        result = submit(runtime, plan)
        assert result["status"] == "pending"
        runtime.settings.clear()
        finished = runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        assert finished["status"] == "completed", finished.get("last_error")
        ready = open_result(runtime, result["handle"])
        if task_type != "hierarchical_analysis":
            rows = list(ready["readers"]["records"].iter_records())
            assert len(rows) == 83
            assert rows[-1] == {"Item_ID": "item-000083", "doubled": 166}
        if task_type != "structured_export":
            value = ready["readers"]["analysis"].read_value()
            assert value["row_count"] == 83
            assert value["counts"]["sum"] == sum(range(1, 84))
        assert model.calls
        assert runtime.publications == []
        assert "artifact_set_manifest" not in finished


def test_invalid_model_output_never_becomes_complete_or_published(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        runtime.settings["tabular_generated_output_model_validation_auto_retries"] = 0
        model = NativeModelFixture(invalid=True)
        runtime.patcher.setattr(runtime.engine, "_build_chat_service", lambda *args, **kwargs: model)
        plan = compute_plan(runtime, durable=True)
        plan["deliverable_contract"]["transformation_spec"] = {}
        plan["requested_output_hints"].pop("transformation_spec")
        result = submit(runtime, plan)
        finished = runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        unavailable = open_result(runtime, result["handle"])
        assert finished["status"] == "failed"
        assert unavailable["status"] == "failed" and unavailable["reader"] is None
        assert finished["native_result_manifest"] is None
        assert runtime.publications == []


def test_semantic_fields_do_not_replace_deterministic_calculations(monkeypatch):
    with native_runtime(monkeypatch, 83) as runtime:
        model = NativeModelFixture()
        runtime.patcher.setattr(runtime.engine, "_build_chat_service", lambda *args, **kwargs: model)
        spec = transformation_spec()
        spec["fields"].append({
            "name": "Risk", "mode": "semantic", "type": "string", "nullable": False,
            "allowed_values": ["High", "Medium", "Low"],
        })
        plan = runtime.planner.plan_tabular_request(
            "Compute doubled amounts and classify risk.",
            [{"file_name": "source.csv", "document_id": "source-1"}],
            requested_output_hints={
                "public_output_schema": ["Item_ID", "doubled", "Risk"], "transformation_spec": spec,
            },
        )
        result = submit(runtime, plan)
        rows = list(result["reader"].iter_records())
        assert rows[-1] == {"Item_ID": "item-000083", "doubled": 166, "Risk": "Low"}
        assert result["reader"].completeness["limitations"]
        assert model.calls
        assert runtime.publications == []


def test_native_batch_budget_controls_foreground_admission(monkeypatch):
    with native_runtime(monkeypatch, 83) as runtime:
        runtime.settings.update({
            "tabular_generated_output_max_batch_rows": 2,
            "tabular_generated_output_inline_max_batches": 2,
        })
        result = submit(runtime, compute_plan(runtime))
        run = runtime.engine._read_run(USER, result["handle"]["job_id"])
        assert result["status"] == "pending"
        assert run["batch_count"] > 2
        assert run["completed_batches"] == 0
        assert runtime.blobs.writes == []


@pytest.mark.parametrize("conflicting", [False, True])
def test_atomic_submission_race_preserves_one_owned_job(monkeypatch, conflicting):
    with native_runtime(monkeypatch) as runtime:
        create_item = runtime.jobs.create_item

        def raced_create(body):
            winner = deepcopy(body)
            if conflicting:
                winner["compute_context"]["request_fingerprint"] = "f" * 64
            create_item(winner)
            raise CosmosResourceExistsError(status_code=409, message="Fixture submission race.")

        runtime.patcher.setattr(runtime.jobs, "create_item", raced_create)
        if conflicting:
            with pytest.raises(ValueError, match="changed"):
                submit(runtime, compute_plan(runtime, durable=True))
        else:
            result = submit(runtime, compute_plan(runtime, durable=True))
            assert result["status"] == "pending"
        assert runtime.jobs.created == 1
        assert runtime.blobs.writes == []
        assert runtime.publications == []


def test_reads_reauthorize_between_batches_and_refuse_missing_parent(monkeypatch):
    with native_runtime(monkeypatch, 1200) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        ready = open_result(runtime, result["handle"])
        iterator = ready["reader"].iter_records()
        first = next(iterator)
        assert first["doubled"] == 2
        runtime.state["allowed"] = False
        with pytest.raises(PermissionError):
            list(iterator)
        runtime.state["allowed"] = True
        runtime.parents.items.pop((CONVERSATION, runtime.producer["run_id"]))
        with pytest.raises(PermissionError) as error:
            open_result(runtime, result["handle"])
        assert error.value.code == "native_compute_producer_unavailable"


@pytest.mark.parametrize("selected_sheet", [None, "Second"])
def test_real_workbook_replay_preserves_sheet_and_row_order(monkeypatch, selected_sheet):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        contents = io.BytesIO()
        with pd.ExcelWriter(contents, engine="openpyxl") as writer:
            pd.DataFrame({"Item_ID": ["a", "b"], "amount": [1, 2]}).to_excel(
                writer, sheet_name="First", index=False,
            )
            pd.DataFrame({"Item_ID": ["c", "d"], "amount": [3, 4]}).to_excel(
                writer, sheet_name="Second", index=False,
            )
        runtime.blobs.values[("user-documents", f"{USER}/source.xlsx")]["bytes"] = contents.getvalue()
        plan = compute_plan(runtime)
        if selected_sheet is not None:
            plan["requested_output_hints"]["selected_sheet"] = selected_sheet
        result = submit(runtime, plan)
        rows = list(result["reader"].iter_records())
        expected = [
            {"Item_ID": "a", "doubled": 2}, {"Item_ID": "b", "doubled": 4},
            {"Item_ID": "c", "doubled": 6}, {"Item_ID": "d", "doubled": 8},
        ]
        assert rows == (expected[2:] if selected_sheet else expected)
        assert result["reader"].schema == ("Item_ID", "doubled")
        assert runtime.publications == []


def test_durable_handle_reopens_without_callback_or_reader_state(monkeypatch):
    with native_runtime(monkeypatch, 31) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        handle = json.loads(json.dumps(result["handle"]))
        runtime.engine.process_tabular_generated_output_run(handle["job_id"], USER)
        del result
        importlib.reload(runtime.results)
        runtime.patcher.setattr(runtime.engine, "process_tabular_generated_output_run", _no_network)
        ready = open_result(runtime, handle)
        rows = list(ready["reader"].iter_records())
        assert len(rows) == 31
        assert rows[-1] == {"Item_ID": "item-000031", "doubled": 62}
        assert runtime.publications == []


def test_analysis_reader_enforces_byte_limit_and_integrity(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        model = NativeModelFixture()
        runtime.patcher.setattr(runtime.engine, "_build_chat_service", lambda *args, **kwargs: model)
        plan = compute_plan(runtime, durable=True)
        plan.update({"execution_contract": "hierarchical_analysis", "durable_task_type": "hierarchical_analysis"})
        plan["deliverable_contract"]["transformation_spec"] = {}
        plan["requested_output_hints"].pop("transformation_spec")
        result = submit(runtime, plan)
        runtime.engine.process_tabular_generated_output_run(result["handle"]["job_id"], USER)
        ready = open_result(runtime, result["handle"])
        reader = ready["reader"]
        before = len(runtime.blobs.reads)
        with pytest.raises(ValueError, match="read limit"):
            reader.read_value(max_bytes=1)
        assert len(runtime.blobs.reads) == before
        run = runtime.engine._read_run(USER, result["handle"]["job_id"])
        path = runtime.engine._analysis_final_blob_path(USER, CONVERSATION, run["id"])
        stored = runtime.blobs.values[("personal-chat", path)]
        value = json.loads(stored["bytes"])
        value["summary"] = "Changed after completion."
        stored["bytes"] = json.dumps(value).encode("utf-8")
        with pytest.raises(ValueError, match="integrity"):
            reader.read_value()


def test_user_publication_entry_points_refuse_data_only_jobs(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime))
        run = runtime.engine._read_run(USER, result["handle"]["job_id"])
        with pytest.raises(ValueError, match="Data-only"):
            runtime.engine._publish_structured_export_artifact(run)
        with pytest.raises(ValueError, match="Data-only"):
            runtime.engine._publish_analysis_artifact(run, {"summary": "Not a user artifact."})
        with pytest.raises(ValueError, match="Data-only"):
            runtime.engine._publish_artifact_set_members(run, [])
        assert runtime.publications == []


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_failed_callbacks_cannot_leak_storage_handles_or_preview_readers(monkeypatch, state):
    with native_runtime(monkeypatch) as runtime:
        plan = compute_plan(runtime)
        for invalid_result in (
            {"status": state, "handle": {"blob_path": "not-an-opaque-handle"}, "reader": None},
            {"status": state, "handle": None, "reader": ["not-computed"]},
        ):
            result = runtime.planner.execute_tabular_plan(
                plan, execution_policy="data_only",
                durable_execution_callback=lambda **kwargs: invalid_result,
            )
            assert result["reason_code"] == "native_compute_result_invalid"
            assert result["native_compute_result"] is None
        assert runtime.jobs.created == 0
        assert runtime.publications == []


def test_explicit_query_uses_complete_replay_but_bare_aggregate_is_not_rows(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        plan = runtime.planner.plan_tabular_request(
            "Find two rows.", [{"file_name": "source.csv", "document_id": "source-1"}],
            requested_output_hints={
                "native_operation": "query", "query_expression": "amount <= 2",
                "public_output_schema": ["Item_ID", "amount"],
            },
        )
        result = submit(runtime, plan)
        rows = list(result["reader"].iter_records())
        assert rows == [
            {"Item_ID": "item-000001", "amount": 1}, {"Item_ID": "item-000002", "amount": 2},
        ]
        assert result["reader"].item_count == 2
    with native_runtime(monkeypatch) as runtime:
        plan = runtime.planner.plan_tabular_request("What is the sum?", [{"file_name": "source.csv"}])
        with pytest.raises(runtime.service.NativeTabularComputeError) as error:
            submit(runtime, plan)
        assert error.value.code == "native_compute_foreground_contract_required"
        assert not runtime.blobs.reads and runtime.jobs.created == 0


@pytest.mark.parametrize("scope", ["group", "public"])
def test_workspace_access_revocation_applies_to_completed_readers(monkeypatch, scope):
    with native_runtime(monkeypatch, scope=scope) as runtime:
        result = submit(runtime, compute_plan(runtime))
        rows = list(result["reader"].iter_records())
        assert len(rows) == 25
        runtime.state["allowed"] = False
        with pytest.raises(PermissionError):
            list(result["reader"].iter_records())


@pytest.mark.parametrize("change", ["lease", "context", "deletion", "cancellation"])
def test_stale_workers_cannot_checkpoint_or_resurrect_results(monkeypatch, change):
    with native_runtime(monkeypatch) as runtime:
        result = submit(runtime, compute_plan(runtime, durable=True))
        job_id = result["handle"]["job_id"]
        claimed = runtime.engine._try_claim_run(USER, job_id, runtime.settings)
        current = runtime.engine._read_run(USER, job_id)
        if change == "deletion":
            runtime.jobs.items.pop((USER, job_id))
        else:
            if change == "lease":
                current["lease_generation"] += 1
            elif change == "context":
                current["compute_context"]["request_fingerprint"] = "f" * 64
            else:
                current["status"] = "canceled"
            runtime.jobs.replace_item(job_id, current)
        with pytest.raises((
            runtime.engine.TabularExportLeaseLostError, runtime.engine.TabularExportCanceledError,
            CosmosResourceNotFoundError,
        )):
            runtime.engine._checkpoint_source_input_batch(
                claimed, [{"Item_ID": "item-000001", "amount": 1}], 1,
            )
        assert runtime.blobs.writes == []
        assert runtime.publications == []
        if change == "deletion":
            with pytest.raises(PermissionError):
                open_result(runtime, result["handle"])


def test_planner_callback_runs_computation_and_does_not_accept_a_preview(monkeypatch):
    with native_runtime(monkeypatch) as runtime:
        plan = compute_plan(runtime)
        callback = runtime.service.build_native_tabular_compute_callback(
            user_id=USER, conversation_id=CONVERSATION, producer=runtime.producer,
            source_manifest=runtime.source_manifest, gpt_model="gpt-4o", settings=runtime.settings,
        )
        result = runtime.planner.execute_tabular_plan(
            plan, execution_policy="data_only", durable_execution_callback=callback,
            user_question="Compute doubled amounts.",
        )
        rows = list(result["native_compute_result"]["reader"].iter_records())
        assert result["execution_state"] == "completed"
        assert result["generated_output_metadata"] is None
        assert rows[-1]["doubled"] == 50
        cancelled = submit(runtime, plan, cancel_requested=lambda: True)
        assert cancelled["status"] == "cancelled"
        assert cancelled["reader"] is None
        assert runtime.jobs.created == 1


@pytest.mark.parametrize("optimized", [False, True])
def test_real_cold_imports_do_not_load_routes_or_bootstrap(optimized):
    script = (
        "import socket,sys\n"
        f"sys.path.insert(0, {str(APP)!r})\n"
        "def blocked(*args, **kwargs): raise RuntimeError('network disabled')\n"
        "socket.socket.connect=blocked\n"
        "socket.create_connection=blocked\n"
        "import functions_tabular_analysis, functions_native_analysis_results\n"
        "import functions_native_tabular_compute, functions_tabular_orchestration\n"
        "if 'config' in sys.modules or 'route_backend_chats' in sys.modules:\n"
        "    raise RuntimeError('native service imported a bootstrap/route owner')\n"
    )
    command = [sys.executable, *(["-O"] if optimized else []), "-c", script]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    assert completed.returncode == 0, completed.stderr
