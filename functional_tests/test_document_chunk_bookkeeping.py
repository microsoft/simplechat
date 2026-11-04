# test_document_chunk_bookkeeping.py
"""
Functional regressions for indexed chunk counts and obsolete metadata warnings.
Version: 0.261.400
Implemented in: 0.261.400

Execute the real single/batch/video writers, upload/reprocess finalizers, detail
projection and conditional metadata update with offline Search and Cosmos.
Counts come from version/scoped keys and acknowledged mutations, not estimates.
"""

import copy
import json
import math
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosHttpResponseError
from flask import Flask, jsonify

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from document_chunk_counts import (
    begin_chunk_tracking,
    count_indexed_chunks,
    end_chunk_tracking,
    record_chunk_deletions,
    record_chunk_uploads,
    chunk_count_for_response,
)
from content_screening import access
from test_document_search_metadata_sync import Harness
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: F401
from test_support.app_source import run_definitions
from test_cosmos_wave6_document_access_cache import (
    FakeRedisClient, _load_document_access_index_module as cache_module,
)
from test_workspace_metadata_outcomes import SdkProjectionContainer


class Search:
    """Key-paged Search with per-item acknowledgements and delayed search visibility."""

    def __init__(self):
        self.chunks = {}
        self.visible = None
        self.fail_keys = set()
        self.searches = []

    def upload_documents(self, documents, **kwargs):
        results = []
        for document in documents:
            succeeded = document["id"] not in self.fail_keys
            if succeeded:
                self.chunks[document["id"]] = copy.deepcopy(document)
            results.append(SimpleNamespace(key=document["id"], succeeded=succeeded))
        return results

    def search(self, **kwargs):
        self.searches.append(kwargs)
        assert kwargs["select"] == ["id"]
        assert kwargs["order_by"] == ["id asc"]
        clauses = re.findall(r"(\w+) (eq|gt) ('(?:[^']|'')*'|\d+)", kwargs["filter"])
        assert len(clauses) in (3, 4), kwargs["filter"]
        rows = list((self.chunks if self.visible is None else self.visible).values())
        for field, operator, raw in clauses:
            value = raw[1:-1].replace("''", "'") if raw.startswith("'") else int(raw)
            rows = [
                row for row in rows
                if (row.get(field) == value if operator == "eq" else row[field] > value)
            ]
        return [{"id": row["id"]} for row in sorted(rows, key=lambda row: row["id"])[:kwargs["top"]]]


@pytest.fixture(params=["personal", "group", "public"])
def runtime(request, monkeypatch):
    harness = Harness()
    scope = {"document_id": "doc", "user_id": "owner"}
    if request.param == "group":
        scope["group_id"] = "group"
        document = harness.add_group_document("doc", "group", chunk_count=0)
        container = harness.group_documents
    elif request.param == "public":
        scope["public_workspace_id"] = "public"
        container = harness.public_documents
        document = {
            "id": "doc", "public_workspace_id": "public", "user_id": "owner",
            "status": "Processing complete", "percentage_complete": 100, "_etag": "etag-1",
        }
        container.documents["doc"] = document
    else:
        document = harness.add_personal_document("doc", "owner", chunk_count=0)
        container = harness.user_documents
    document.update({
        "version": 2, "num_chunks": 0, "num_file_chunks": 0,
        "title": "User title", "abstract": "Keep this abstract", "file_name": "sample.pdf",
    })
    search = Search()
    harness.user_search = harness.group_search = harness.public_search = search
    namespace = harness.namespace
    namespace.update({
        "CLIENTS": {f"search_client_{name}": search for name in ("user", "group", "public")},
        "get_document_metadata": lambda *args, **kwargs: copy.deepcopy(container.documents["doc"]),
        "get_settings": lambda: {},
        "generate_embedding": lambda text: ([0.1, 0.2], {"total_tokens": 3}),
        "get_embedding_safe_chunk_characters": lambda *args: 10000,
        "debug_print": lambda *args: None,
        "VISION_ANALYSIS_CONTENT_FIELDS": ("description", "text", "analysis", "objects"),
        "begin_chunk_tracking": begin_chunk_tracking, "end_chunk_tracking": end_chunk_tracking,
        "count_indexed_chunks": count_indexed_chunks, "record_chunk_deletions": record_chunk_deletions,
        "os": os, "math": math,
    })
    content = ModuleType("functions_content")
    content.generate_embeddings_batch = lambda texts: [([0.1, 0.2], {"total_tokens": 3}) for text in texts]
    monkeypatch.setitem(sys.modules, "functions_content", content)
    debug = ModuleType("functions_debug")
    debug.debug_print = lambda *args: None
    monkeypatch.setitem(sys.modules, "functions_debug", debug)
    run_definitions("functions_documents.py", {
        "save_chunks", "save_chunks_batch", "save_video_chunk",
        "_is_usable_vision_analysis", "_format_vision_analysis_block",
        "_append_vision_block_to_chunk_text", "_require_screening_chunk_write",
        "_indexed_chunk_count_for_document", "_document_with_current_bookkeeping",
        "_resolve_processing_complete_status", "_build_document_scope_args",
        "_update_document_for_job",
        "_update_failed_document_chunk_count", "is_effectively_empty",
    }, namespace)
    return SimpleNamespace(
        scope=scope, document=document, container=container, namespace=namespace,
        search=search, harness=harness,
    )


def save(runtime, page_number=1, text="Real indexed text"):
    return runtime.namespace["save_chunks"](
        **runtime.scope, page_text_content=text, page_number=page_number, file_name="sample.pdf",
    )


def count(runtime):
    return runtime.namespace["_indexed_chunk_count_for_document"](runtime.container.documents["doc"])


def test_single_batch_and_video_count_unique_acknowledged_keys_despite_search_lag(runtime):
    runtime.search.visible = {}
    token = begin_chunk_tracking()
    try:
        save(runtime)
        save(runtime)  # Same key is an overwrite, not another indexed chunk.
        skipped = save(runtime, 9, "")
        runtime.namespace["save_chunks_batch"]([
            {"page_number": 1, "page_text_content": "Overwrite", "file_name": "sample.pdf"},
            {"page_number": 2, "page_text_content": "Second key", "file_name": "sample.pdf"},
            {"page_number": 3, "page_text_content": "", "file_name": "sample.pdf"},
        ], **runtime.scope)
        runtime.namespace["save_video_chunk"](
            **{"group_id": None, **runtime.scope}, page_text_content="Video transcript", ocr_chunk_text="",
            start_time="00:00:30.000", file_name="sample.mp4",
        )
        actual = count(runtime)
        assert skipped is None
        assert actual == 3
    finally:
        end_chunk_tracking(token)
    actual = count(runtime)
    assert actual == 0  # No job state leaks; historical reads use the visible index.
    runtime.search.visible = None
    actual = count(runtime)
    assert actual == 3


def test_partial_batch_does_not_count_failed_writes(runtime):
    runtime.search.visible = {}
    runtime.search.fail_keys.add("doc_2")
    token = begin_chunk_tracking()
    try:
        with pytest.raises(RuntimeError, match="did not acknowledge"):
            runtime.namespace["save_chunks_batch"]([
                {"page_number": i, "page_text_content": "Text", "file_name": "sample.pdf"}
                for i in (1, 2)
            ], **runtime.scope)
        actual = count(runtime)
        assert actual == 1
        assert "doc_2" not in runtime.search.chunks
    finally:
        end_chunk_tracking(token)


def test_acknowledged_count_survives_write_fence_cleanup_failure(runtime):
    runtime.search.visible = {}

    @contextmanager
    def failing_release(*args, **kwargs):
        yield
        raise RuntimeError("Write fence cleanup failed")

    runtime.namespace["hold_data_management_search_write_slot"] = failing_release
    token = begin_chunk_tracking()
    try:
        with pytest.raises(RuntimeError, match="Write fence cleanup failed"):
            save(runtime)
        actual = count(runtime)
        assert actual == 1
    finally:
        end_chunk_tracking(token)


def test_failed_processing_persists_partial_count_without_changing_failure(runtime):
    runtime.document["status"] = "Error: ingestion failed"
    runtime.search.visible = {}
    runtime.search.fail_keys.add("doc_2")
    token = begin_chunk_tracking()
    try:
        save(runtime)
        with pytest.raises(RuntimeError, match="did not acknowledge"):
            save(runtime, 2)
        runtime.namespace["_update_failed_document_chunk_count"](
            **runtime.scope, update_callback=lambda **updates: runtime.namespace["update_document"](
                **runtime.scope, **updates,
            ),
        )
        saved = runtime.container.documents["doc"]
        assert saved["num_chunks"] == 1
        assert saved["status"] == "Error: ingestion failed"
    finally:
        end_chunk_tracking(token)


def test_multiple_upload_sub_batches_count_distinct_keys(runtime):
    runtime.search.visible = {}
    token = begin_chunk_tracking()
    try:
        runtime.namespace["save_chunks_batch"]([
            {"page_number": i, "page_text_content": "Indexed content", "file_name": "sample.pdf"}
            for i in range(1, 68)
        ], **runtime.scope)
        save(runtime, 32)
        actual = count(runtime)
        assert actual == 67
    finally:
        end_chunk_tracking(token)


def test_count_pages_every_key_and_excludes_other_documents_scopes_and_versions():
    search = Search()
    document_id, owner = "doc'quoted", "owner'quoted"
    for i in range(2507):
        search.chunks[str(i)] = {
            "id": f"key-{i:05d}", "document_id": document_id, "version": 4, "user_id": owner,
        }
    for name, changes in {
        "old": {"version": 3}, "other": {"document_id": "other"}, "scope": {"user_id": "other"},
        "archived": {"user_id": f"archived_{owner}"},
    }.items():
        search.chunks[name] = {
            "id": name, "document_id": document_id, "version": 4, "user_id": owner, **changes,
        }
    actual = count_indexed_chunks(search, document_id, 4, "user_id", owner)
    assert actual == 2507
    assert len(search.searches) == 3
    assert all("version eq 4" in query["filter"] for query in search.searches)
    assert all("doc''quoted" in query["filter"] for query in search.searches)


def test_deleted_keys_are_not_recounted_while_search_is_stale(runtime):
    save(runtime)
    runtime.search.visible = copy.deepcopy(runtime.search.chunks)
    token = begin_chunk_tracking()
    try:
        record_chunk_deletions(runtime.search, ["doc_1"])
        save(runtime, 2)
        actual = count(runtime)
        assert actual == 1
    finally:
        end_chunk_tracking(token)


def test_historical_detail_recovers_actual_count_and_warning_without_writing(runtime):
    save(runtime, 2)
    before = copy.deepcopy(runtime.container.documents["doc"])
    before.update({
        "status": "Processing complete (metadata extraction warning)",
        "metadata_extraction_status": "succeeded", "number_of_pages": 999, "num_file_chunks": 0,
    })
    projected = runtime.namespace["_document_with_current_bookkeeping"](before)
    assert projected["num_chunks"] == 1
    assert projected["status"] == "Processing complete - final metadata extracted"
    assert projected["number_of_pages"] == 999
    assert projected["num_file_chunks"] == 0  # Cannot reconstruct physical file splits from Search.
    assert before["num_chunks"] == 0
    assert before["status"] == "Processing complete (metadata extraction warning)"


@pytest.mark.parametrize("status", [
    "Error: ingestion failed", "Content review required", "Queued for processing",
    "Extracting again with Enhanced...", "Processing complete - no content indexed",
])
def test_success_does_not_overwrite_unrelated_or_newer_status(runtime, status):
    runtime.document["status"] = status
    runtime.namespace["update_document"](**runtime.scope, metadata_extraction_status="succeeded")
    saved = runtime.container.documents["doc"]
    assert saved["status"] == status
    assert saved["abstract"] == "Keep this abstract"


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "empty", "running", "disabled"])
def test_only_successful_retry_retires_exact_obsolete_warning(runtime, outcome):
    warning = "Processing complete (metadata extraction warning)"
    runtime.document["status"] = warning
    runtime.namespace["update_document"](**runtime.scope, metadata_extraction_status=outcome)
    saved = runtime.container.documents["doc"]
    assert saved["status"] == (
        "Processing complete - final metadata extracted" if outcome == "succeeded" else warning
    )
    assert saved["abstract"] == "Keep this abstract"
    assert saved["title"] == "User title"


def test_held_document_does_not_clear_warning_or_query_search(runtime):
    runtime.document.update({
        "status": "Processing complete (metadata extraction warning)",
        "metadata_extraction_status": "succeeded",
        "content_screening": {"state": "review_required"},
    })
    projected = runtime.namespace["_document_with_current_bookkeeping"](runtime.document)
    assert projected["status"] == runtime.document["status"]
    assert runtime.search.searches == []
    runtime.namespace["update_document"](**runtime.scope, metadata_extraction_status="succeeded")
    assert runtime.container.documents["doc"]["status"] == runtime.document["status"]


def test_warning_cleanup_is_conditional_and_cannot_erase_racing_ingestion(runtime, monkeypatch):
    runtime.document["status"] = "Processing complete (metadata extraction warning)"
    replace = runtime.container.replace_item

    def race(**arguments):
        runtime.container.documents["doc"]["status"] = "Extracting again with Enhanced..."
        runtime.container.documents["doc"]["_etag"] = "newer-etag"
        return replace(**arguments)

    monkeypatch.setattr(runtime.container, "replace_item", race)
    with pytest.raises(CosmosHttpResponseError):
        runtime.namespace["update_document"](**runtime.scope, metadata_extraction_status="succeeded")
    assert runtime.container.documents["doc"]["status"] == "Extracting again with Enhanced..."


@pytest.mark.parametrize("suffix", [".pdf", ".md", ".wav", ".mp4"])
def test_upload_finalizer_persists_actual_not_processor_estimated_count(runtime, suffix, tmp_path, monkeypatch):
    namespace = runtime.namespace
    for name in ("TABULAR", "IMAGE", "DOCUMENT", "VIDEO", "AUDIO", "VISIO", "EMAIL", "ONENOTE"):
        namespace[f"{name}_EXTENSIONS"] = set()
    namespace["DOCUMENT_EXTENSIONS"] = {"pdf"}
    namespace["VIDEO_EXTENSIONS"] = {"mp4"}
    namespace["AUDIO_EXTENSIONS"] = {"wav"}
    namespace.update({
        "allowed_file": lambda value: True, "TEMPLATE_EXTENSIONS": (),
        "PUBLICATION_BINDING": "generated_artifact_publication_binding",
        "_run_final_metadata_extraction": lambda *args, **kwargs: "disabled",
        "sync_chat_upload_workspace_attachment_status": lambda value: None,
    })
    runtime.search.visible = {}

    def processor(**arguments):
        save(runtime)
        save(runtime)
        save(runtime, 2, "")
        return 999 if suffix in (".wav", ".mp4") else (999, 6, "embedding")

    namespace["process_di_document"] = processor
    namespace["process_video_document"] = processor
    namespace["process_audio_document"] = processor
    namespace["_process_markdown_with_ordered_dict_retry"] = lambda arguments, callback: processor(**arguments)
    for module_name, names in {
        "functions_activity_logging": ("log_document_creation_transaction", "log_token_usage"),
        "functions_notifications": ("create_notification", "create_group_notification", "create_public_workspace_notification"),
    }.items():
        module = ModuleType(module_name)
        for name in names:
            setattr(module, name, lambda **kwargs: None)
        monkeypatch.setitem(sys.modules, module_name, module)
    groups = ModuleType("functions_group")
    groups.find_group_by_id = lambda group: {"name": "Group"}
    monkeypatch.setitem(sys.modules, "functions_group", groups)
    run_definitions("functions_documents.py", {"_process_document_upload_background_impl"}, namespace)
    source = tmp_path / f"sample{suffix}"
    source.write_bytes(b"synthetic source")
    namespace["_process_document_upload_background_impl"](
        **runtime.scope, temp_file_path=str(source), original_filename=source.name, safe_errors=True,
    )
    saved = runtime.container.documents["doc"]
    assert saved["num_chunks"] == 1
    assert saved["num_file_chunks"] == 1
    assert saved["status"] == "Processing complete"
    assert saved["version"] == 2
    assert saved["abstract"] == "Keep this abstract"
    assert not source.exists()


def test_sdk_conditional_warning_cleanup(runtime, cosmos_factory, monkeypatch):
    http, container = cosmos_factory("id")
    http.seed({**runtime.document, **runtime.scope, "status": "Processing complete (metadata extraction warning)"})

    def query_items(**arguments):
        document = container.read_item("doc", partition_key="doc")
        return [dict(document)]

    monkeypatch.setattr(container, "query_items", query_items)
    namespace = runtime.namespace
    field = (
        "public_workspace_id" if "public_workspace_id" in runtime.scope
        else "group_id" if "group_id" in runtime.scope else "user_id"
    )
    namespace[f"cosmos_{'public' if field == 'public_workspace_id' else 'group' if field == 'group_id' else 'user'}_documents_container"] = container
    namespace["update_document"](**runtime.scope, metadata_extraction_status="succeeded")
    saved = container.read_item("doc", partition_key="doc")
    assert type(saved) is CosmosDict
    assert saved["status"] == "Processing complete - final metadata extracted"
    assert any(method == "PUT" and headers.get("If-Match") for method, _, headers in http.calls)


def test_group_source_query_retains_plain_sdk_rows(cosmos_factory):
    http, container = cosmos_factory("id")
    http.seed({"id": "doc", "group_id": "group", "version": 1})
    query = container.query_items

    def scoped_rows(**arguments):
        parameters = {entry["name"]: entry["value"] for entry in arguments["parameters"]}
        assert parameters["@group_id"] == "group"
        assert parameters["@document_ids"] == ["doc"]
        assert "c.group_id = @group_id" in arguments["query"]
        return query(query="SELECT * FROM c", partition_key="doc")

    namespace = {
        "cosmos_group_documents_container": SimpleNamespace(query_items=scoped_rows),
        "_group_document_share_status": lambda document, group: "owner" if document["group_id"] == group else None,
    }
    run_definitions("functions_group_document_reads.py", {"_query_group_document_records"}, namespace)
    rows = namespace["_query_group_document_records"]("group", document_ids=["doc"])
    assert len(rows) == 1
    assert type(rows[0]) is dict
    assert rows[0]["id"] == "doc"


def test_manual_metadata_retry_clears_obsolete_warning_without_reingestion(runtime):
    runtime.document["status"] = "Processing complete (metadata extraction warning)"
    namespace = runtime.namespace
    namespace.update({
        "get_settings": lambda: {"enable_extract_meta_data": True},
        "extract_document_metadata": lambda **kwargs: {"abstract": "Keep this abstract"},
    })
    run_definitions("functions_documents.py", {"process_metadata_extraction_background"}, namespace)
    namespace["process_metadata_extraction_background"](**runtime.scope)
    saved = runtime.container.documents["doc"]
    assert saved["metadata_extraction_status"] == "succeeded"
    assert saved["status"] == "Processing complete - final metadata extracted"
    assert runtime.search.chunks == {}


def test_reprocess_replaces_old_count_without_recounting_deleted_keys(runtime, tmp_path):
    save(runtime)
    save(runtime, 2)
    runtime.search.visible = copy.deepcopy(runtime.search.chunks)
    namespace = runtime.namespace
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")

    def delete_chunks(*args, **kwargs):
        record_chunk_deletions(runtime.search, list(runtime.search.chunks))
        runtime.search.chunks.clear()

    def process(**kwargs):
        save(runtime)
        return 999, 3, "embedding"

    namespace.update({
        "normalize_document_intelligence_manual_extraction_mode": lambda mode: mode,
        "validate_document_reprocess_source": lambda *args, **kwargs: (True, None),
        "_resolve_extraction_engine_for_mode": lambda *args: ("content_understanding", "configured"),
        "EXTRACTION_ENGINE_CONTENT_UNDERSTANDING": "content_understanding",
        "get_document_intelligence_auto_sample_pages": lambda settings: 3,
        "_download_document_source_to_temp_file": lambda *args, **kwargs: str(source),
        "delete_document_chunks": delete_chunks, "process_di_document": process,
        "IMAGE_EXTENSIONS": set(), "TABULAR_EXTENSIONS": set(), "TEMPLATE_EXTENSIONS": (),
    })
    run_definitions("functions_documents.py", {"_process_document_reprocess_extraction_background_impl"}, namespace)
    namespace["_process_document_reprocess_extraction_background_impl"](
        **runtime.scope, target_extraction_mode="layout", safe_errors=True,
    )
    saved = runtime.container.documents["doc"]
    assert saved["num_chunks"] == 1
    assert saved["status"] == "Processing complete"
    assert saved["version"] == 2
    assert saved["abstract"] == "Keep this abstract"
    assert not source.exists()


@pytest.mark.parametrize("split", [True, False])
def test_audio_file_chunk_count_is_not_search_chunk_count(runtime, tmp_path, split):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic source")
    paths = [tmp_path / f"part-{i}.wav" for i in (1, 2)] if split else []
    for path in paths:
        path.write_bytes(b"synthetic split")

    def split_audio(*args, **kwargs):
        if not split:
            raise RuntimeError("FFmpeg unavailable")
        return [str(path) for path in paths]

    namespace = runtime.namespace
    namespace.update({
        "_split_audio_file": split_audio, "_is_missing_ffmpeg_error": lambda error: True,
        "AZURE_ENVIRONMENT": "public", "_get_content_type": lambda name: "audio/wav",
        "_transcribe_audio_with_fast_api": lambda *args: ["Three red boxes and seven blue boxes."],
        "get_chunk_size_config": lambda settings: {"transcript": {"value": 400}},
    })
    run_definitions("functions_documents.py", {"process_audio_document"}, namespace)
    namespace["process_audio_document"](
        **runtime.scope, temp_file_path=str(source), original_filename="source.wav",
        update_callback=lambda **kwargs: namespace["update_document"](**runtime.scope, **kwargs),
        auto_extract_metadata=False,
    )
    saved = runtime.container.documents["doc"]
    actual = count(runtime)
    assert saved["num_file_chunks"] == (2 if split else 1)
    assert actual == 1
    assert all(not path.exists() for path in paths)


def test_detail_repair_checks_access_and_reports_search_outage_safely(runtime):
    namespace = runtime.namespace
    namespace.update({"jsonify": jsonify, "public_document_payload": lambda value: value})
    run_definitions("functions_documents.py", {"get_document"}, namespace)
    app = Flask(__name__)
    with app.app_context():
        namespace["get_document_record"] = lambda **kwargs: None
        response, status = namespace["get_document"]("outsider", "doc")
        assert status == 404
        assert runtime.search.searches == []
        namespace["get_document_record"] = lambda **kwargs: runtime.document

        def unavailable(**kwargs):
            raise RuntimeError("private-search-connection-detail")

        runtime.search.search = unavailable
        response, status = namespace["get_document"]("owner", "doc")
        assert status == 500
        assert response.get_json() == {"error": "Unable to retrieve document details."}
        assert "private-search-connection-detail" not in repr(runtime.harness.logs)


def test_detail_requires_release_proof_before_search_count_lookup(runtime, monkeypatch):
    runtime.document["content_screening"] = {
        "state": "cleared", "scan_id": "missing-proof", "source_revision": "2",
        "content_fingerprint": "fingerprint",
    }

    def missing_proof(*args):
        raise access.DocumentHeldError()

    monkeypatch.setattr(access, "_require_available_metadata", lambda document: None)
    monkeypatch.setattr(access, "_require_release_proof", missing_proof)
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(cosmos_content_screening_container=object()))
    namespace = runtime.namespace
    namespace.update({
        "jsonify": jsonify, "public_document_payload": access.public_document_payload,
        "get_document_record": lambda **kwargs: runtime.document,
    })
    run_definitions("functions_documents.py", {"get_document"}, namespace)
    app = Flask(__name__)
    with app.test_request_context():
        response, status = namespace["get_document"]("owner", "doc")
    assert status == 200
    assert response.get_json()["content_screening"]["available"] is False
    assert response.get_json()["status"] == "Content screening: document unavailable"
    assert runtime.search.searches == []


def test_list_unknown_and_verified_detail_survive_fresh_source_response_projection(runtime):
    save(runtime)
    original = copy.deepcopy(runtime.container.documents["doc"])
    original["status"] = "Processing complete (metadata extraction warning)"
    original["metadata_extraction_status"] = "succeeded"
    app = Flask(__name__)
    with app.test_request_context():
        listed = access.public_document_payload(original)
        assert listed["num_chunks"] is None
        assert listed["status"] == "Processing complete - final metadata extracted"
        detail = runtime.namespace["_document_with_current_bookkeeping"](original)
        assert detail["num_chunks"] == 1
        refreshed = access.public_documents_payload(
            [detail], runtime.scope["user_id"], metadata_reader=lambda **kwargs: copy.deepcopy(original),
        )
        assert refreshed[0]["num_chunks"] == 1
        changed = {**original, "_etag": "new-version-etag", "version": 3}
        assert access.public_document_payload(changed)["num_chunks"] is None
        other_scope = {**original, "public_workspace_id": "unrelated-public"}
        assert access.public_document_payload(other_scope)["num_chunks"] is None
    with app.test_request_context():
        assert access.public_document_payload(original)["num_chunks"] is None
    assert original["num_chunks"] == 0


@pytest.mark.parametrize("count,recorded_version,version,status,expected", [
    (0, None, 2, "Processing complete", None),
    (0, 2, 2, "Processing complete", 0),
    (3, 2, 2, "Processing complete", 3),
    (3, 1, 2, "Processing complete", None),
    (0, 0, 2, "Extracting again...", None),
    (0, None, 2, "Processing complete - no content indexed", None),
    (0, 2, 2, "Processing complete - no content indexed", 0),
    (3, None, 2, "Processing complete", 3),
])
def test_response_count_distinguishes_unrecorded_zero_current_zero_and_stale_version(
    count, recorded_version, version, status, expected,
):
    document = {"num_chunks": count, "version": version, "status": status}
    if recorded_version is not None:
        document["indexed_chunk_count_version"] = recorded_version
    actual = chunk_count_for_response(document)
    assert actual == expected


@pytest.mark.parametrize("scope", ["personal", "public", "group"])
def test_access_index_and_redis_cache_keep_unknown_separate_from_known_counts(scope):
    redis = FakeRedisClient()
    index = SdkProjectionContainer()
    settings = SdkProjectionContainer()
    group_source = SdkProjectionContainer()
    source = {
        "id": "doc", "user_id": "owner", "version": 2, "_etag": "etag-1",
        "file_name": "sample.pdf", "status": "Processing complete", "percentage_complete": 100,
        "is_current_version": True, "num_chunks": 0,
    }
    arguments = {"source_scope": scope, "user_id": "owner"}
    if scope == "public":
        source["public_workspace_id"] = "public"
        arguments["public_workspace_ids"] = ["public"]
    elif scope == "group":
        source["group_id"] = "group"
        arguments["group_ids"] = ["group"]
    with cache_module(
        redis, index_container=index, settings_container=settings, group_documents_container=group_source,
    ) as (module, _, _):
        settings.upsert_item({
            "id": "document_access_index_backfill_state", "type": "document_access_index_backfill_state",
            "status": "succeeded", "completed_source_scopes": ["personal", "public", "group"],
            "schema_version": module.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        })

        def sync():
            if scope == "group":
                group_source.upsert_item(source)
            saved = module.sync_document_access_index_for_document(source, force=True)
            assert saved["success"] is True

        sync()
        first = module.query_document_access_index_documents(**arguments)
        cached = module.query_document_access_index_documents(**arguments)
        assert first["status"] == "served_from_index"
        assert cached["status"] == "served_from_cache"
        assert cached["documents"][0]["num_chunks"] is None
        # Model a cache written by the old implementation, before response normalization.
        for key, value in list(redis.values.items()):
            if key.startswith("DAI_LIST_CACHE:"):
                old_payload = json.loads(value)
                for document in old_payload.get("documents", []):
                    document["num_chunks"] = 0
                    document.pop("indexed_chunk_count_version", None)
                redis.values[key] = json.dumps(old_payload)
        legacy_cached = module.query_document_access_index_documents(**arguments)
        assert legacy_cached["documents"][0]["num_chunks"] is None
        for known_count in (0, 3):
            source.update(num_chunks=known_count, indexed_chunk_count_version=2)
            sync()
            refreshed = module.query_document_access_index_documents(**arguments)
            cached = module.query_document_access_index_documents(**arguments)
            assert refreshed["status"] == "served_from_index"
            assert cached["status"] == "served_from_cache"
            assert refreshed["documents"][0]["num_chunks"] == known_count
            assert cached["documents"][0]["num_chunks"] == known_count
        candidate_queries = [query["query"] for query in index.queries if "SELECT c.id, c.document_id" in query["query"]]
        assert candidate_queries
        assert all("c.num_chunks, c.indexed_chunk_count_version" in query for query in candidate_queries)

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
