# test_workspace_metadata_outcomes.py
"""
Runtime regressions for shared automatic and manual workspace metadata analysis.
Version: 0.261.354
Implemented in: 0.261.347

Execute the real extraction, merge, worker, and final-upload functions with only
external storage/search/provider boundaries replaced. No Azure calls are made.
"""

import copy
import json
import logging
import os
import re
import sys
from functools import partial
from types import ModuleType, SimpleNamespace

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

from test_support.app_source import run_definitions
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: F401
from test_cosmos_wave5a_document_access_read_switch import (
    FakeCosmosContainer, _load_document_access_index_module, _succeeded_backfill_state,
)
from functions_document_status import is_document_processing_failure


class SdkProjectionContainer(FakeCosmosContainer):
    """Existing ETag/partition/failure model with installed-SDK point responses."""

    def read_item(self, item, partition_key):
        return CosmosDict(super().read_item(item, partition_key), response_headers={})

    def upsert_item(self, body):
        return CosmosDict(super().upsert_item(body), response_headers={})

    def replace_item(self, **arguments):
        return CosmosDict(super().replace_item(**arguments), response_headers={})


@pytest.fixture(params=["personal", "group", "public"])
def metadata_env(request):
    scope = {"document_id": "document-1", "user_id": "owner"}
    if request.param == "group":
        scope["group_id"] = "group-1"
    elif request.param == "public":
        scope["public_workspace_id"] = "workspace-1"
    document = {
        "id": "document-1", **scope, "title": "User title", "authors": [],
        "status": "Processing complete", "percentage_complete": 100, "_etag": "etag-1",
    }
    settings = {
        "enable_extract_meta_data": True,
        {"personal": "enable_user_workspace", "group": "enable_group_workspaces",
         "public": "enable_public_workspaces"}[request.param]: True,
    }
    env = SimpleNamespace(
        scope=scope, document=document, settings=settings, writes=[], searches=[],
        queries=[], logs=[], response=json.dumps({"title": "Generated title", "abstract": "Generated abstract"}),
        provider_error=None, search_results=[{"content": "One indexed Markdown chunk."}],
    )

    def query_items(**arguments):
        env.queries.append(arguments)
        return [copy.deepcopy(document)]

    def update_document(**arguments):
        env.writes.append(copy.deepcopy(arguments))
        document.update({key: value for key, value in arguments.items() if key not in {
            "document_id", "user_id", "group_id", "public_workspace_id",
            "strict", "expected_etag", "operation_guard",
        }})
        return copy.deepcopy(document)

    def search(*args, **arguments):
        env.searches.append(arguments)
        return env.search_results

    def complete(**arguments):
        if env.provider_error:
            raise env.provider_error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=env.response))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    namespace = {
        "is_document_processing_failure": is_document_processing_failure,
        "json": json, "logging": logging, "re": re, "partial": partial,
        "get_settings": lambda: settings, "get_document_metadata": lambda *args, **kwargs: copy.deepcopy(document),
        "update_document": update_document, "hybrid_search": search,
        "detect_doc_type": lambda *args: ("personal", "owner"),
        "_resolve_metadata_extraction_client": lambda *args, **kwargs: (client, "configured-model"),
        "add_file_task_to_file_processing_log": lambda **kwargs: None,
        "log_event": lambda *args, **kwargs: env.logs.append((args, kwargs)),
        "SCREENING_FIELD": "content_screening", "CLIENTS": {},
        "document_is_available": lambda value: True,
        "TEMPLATE_EXTENSIONS": (),
    }
    for name in ("user", "group", "public"):
        namespace[f"cosmos_{name}_documents_container"] = SimpleNamespace(query_items=query_items)
    run_definitions("functions_documents.py", {
        "process_metadata_extraction_background", "extract_document_metadata",
        "_run_final_metadata_extraction", "_resolve_processing_complete_status",
        "_update_document_for_job", "_build_document_scope_args",
        "ensure_list", "is_effectively_empty", "clean_json_codeFence",
    }, namespace)
    env.functions = namespace
    return env


def run_metadata(env, automatic=False, guarded=False):
    guard = (lambda: copy.deepcopy(env.document)) if guarded else None
    if automatic:
        scope = dict(env.scope)
        return env.functions["_run_final_metadata_extraction"](
            total_chunks_saved=1, enable_extract_meta_data=env.settings["enable_extract_meta_data"],
            update_callback=lambda **updates: env.functions["_update_document_for_job"](
                **scope, **updates, operation_guard=guard, safe_errors=guarded,
            ), **scope, operation_guard=guard, safe_errors=guarded,
        )
    return env.functions["process_metadata_extraction_background"](
        **env.scope, operation_guard=guard, safe_errors=guarded,
    )


@pytest.mark.parametrize("automatic", [False, True])
def test_analysis_uses_own_scope_and_preserves_existing_values(metadata_env, automatic):
    env = metadata_env
    run_metadata(env, automatic)
    assert env.document["metadata_extraction_status"] == "succeeded"
    assert env.document["title"] == "User title"
    assert env.document["abstract"] == "Generated abstract"
    assert env.document["authors"] == []  # Unknown authors must not be fabricated.
    [search] = env.searches
    assert search["document_id"] == env.scope["document_id"]
    expected = "public" if "public_workspace_id" in env.scope else "group" if "group_id" in env.scope else "personal"
    assert search["doc_scope"] == expected
    for key, value in env.scope.items():
        assert all(write[key] == value for write in env.writes)
    assert env.document["status"] == "Processing complete"
    assert env.document["percentage_complete"] == 100
    assert not any("status" in write or "percentage_complete" in write for write in env.writes)


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("failure", ["provider", "parse", "empty", "shape", "search"])
def test_failed_retry_preserves_metadata_and_index_readiness(metadata_env, automatic, failure):
    env = metadata_env
    env.document["abstract"] = "Previous successful analysis"
    if failure == "provider":
        env.provider_error = RuntimeError("private-provider-detail")
    elif failure == "parse":
        env.response = "not JSON"
    elif failure == "empty":
        env.response = "{}"
    elif failure == "shape":
        env.response = '{"title": {"invalid": "shape"}}'
    else:
        env.search_results = []
    run_metadata(env, automatic)
    assert env.document["metadata_extraction_status"] == ("empty" if failure == "empty" else "failed")
    assert env.document["abstract"] == "Previous successful analysis"
    assert env.document["title"] == "User title"
    assert env.document["status"] == "Processing complete"
    assert env.document["percentage_complete"] == 100
    assert "private-provider-detail" not in repr(env.writes) + repr(env.logs)


@pytest.mark.parametrize("automatic", [False, True])
def test_disabled_metadata_does_not_call_provider_or_search(metadata_env, automatic):
    env = metadata_env
    env.settings["enable_extract_meta_data"] = False
    run_metadata(env, automatic)
    assert env.document["metadata_extraction_status"] == "disabled"
    assert env.searches == []
    assert env.document["status"] == "Processing complete"


def test_guarded_final_extraction_rechecks_authorization(metadata_env):
    env = metadata_env
    calls = []

    def revoked():
        calls.append(True)
        raise PermissionError("operation no longer allowed")

    with pytest.raises(PermissionError):
        env.functions["_run_final_metadata_extraction"](
            **env.scope, total_chunks_saved=1, enable_extract_meta_data=True,
            operation_guard=revoked, safe_errors=True,
            update_callback=lambda **updates: env.functions["_update_document_for_job"](
                **env.scope, **updates, operation_guard=revoked, safe_errors=True,
            ),
        )
    assert calls
    assert env.writes == []
    assert env.searches == []


def test_guarded_manual_failure_is_safe_and_job_does_not_report_success(metadata_env):
    env = metadata_env
    env.provider_error = RuntimeError("private-provider-detail")
    with pytest.raises(RuntimeError, match="^Metadata analysis failed\\.$"):
        run_metadata(env, guarded=True)
    assert env.document["metadata_extraction_status"] == "failed"
    assert env.document["status"] == "Processing complete"


def test_no_chunks_is_observable_without_analysis(metadata_env):
    env = metadata_env
    result = env.functions["_run_final_metadata_extraction"](
        **env.scope, total_chunks_saved=0, enable_extract_meta_data=True,
        update_callback=lambda **updates: env.functions["update_document"](**env.scope, **updates),
    )
    assert result == "skipped_no_chunks"
    assert env.document["metadata_extraction_status"] == "empty"
    assert env.searches == []


def test_metadata_warning_does_not_have_a_content_failure_status(metadata_env):
    resolve = metadata_env.functions["_resolve_processing_complete_status"]
    status = resolve(1, ".md", (), (), "returned_empty")
    assert "failed" not in status.lower() and "error" not in status.lower()


@pytest.mark.parametrize("suffix", [".md", ".txt"])
def test_upload_dispatcher_preserves_ready_content_after_metadata_failure(
    metadata_env, suffix, tmp_path, monkeypatch, cosmos_factory,
):
    env = metadata_env
    namespace = env.functions
    source = tmp_path / f"source{suffix}"
    source.write_text("One source chunk", encoding="utf-8")
    http, container = cosmos_factory("id")
    http.seed(env.document)
    for name in ("user", "group", "public"):
        namespace[f"cosmos_{name}_documents_container"] = container
    for name in ("TABULAR", "IMAGE", "DOCUMENT", "VIDEO", "AUDIO", "VISIO", "EMAIL", "ONENOTE"):
        namespace[f"{name}_EXTENSIONS"] = set()
    namespace.update({
        "os": os, "allowed_file": lambda value: True, "current_extraction": lambda value: None,
        "PUBLICATION_BINDING": "generated_artifact_publication",
        "sync_chat_upload_workspace_attachment_status": lambda value: True,
    })
    processed = []

    def processor(**arguments):
        processed.append(arguments)
        return 1, 0, None

    namespace["process_txt"] = processor
    namespace["_process_markdown_with_ordered_dict_retry"] = lambda arguments, callback: processor(**arguments)

    def provider_failure(**arguments):
        assert arguments["operation_guard"] is guard
        raise RuntimeError("private-provider-detail")

    namespace["extract_document_metadata"] = provider_failure
    for module_name, functions in {
        "functions_activity_logging": ["log_document_creation_transaction", "log_token_usage"],
        "functions_notifications": ["create_notification", "create_group_notification", "create_public_workspace_notification"],
    }.items():
        module = ModuleType(module_name)
        for function in functions:
            setattr(module, function, lambda **kwargs: None)
        monkeypatch.setitem(sys.modules, module_name, module)
    group_module = ModuleType("functions_group")
    group_module.find_group_by_id = lambda value: {"name": "Group"}
    monkeypatch.setitem(sys.modules, "functions_group", group_module)
    guard = lambda: copy.deepcopy(env.document)
    run_definitions("functions_documents.py", {"_process_document_upload_background_impl"}, namespace)
    namespace["_process_document_upload_background_impl"](
        **env.scope, temp_file_path=str(source), original_filename=source.name,
        operation_guard=guard, safe_errors=True,
    )
    assert env.document["percentage_complete"] == 100
    assert env.document["metadata_extraction_status"] == "failed"
    assert "processing complete" in env.document["status"].lower()
    assert "error" not in env.document["status"].lower() and "failed" not in env.document["status"].lower()
    assert processed[0].get("public_workspace_id") == env.scope.get("public_workspace_id")
    if suffix == ".md":
        assert processed[0]["auto_extract_metadata"] is False
    saved = container.read_item("document-1", partition_key="document-1")
    assert type(saved) is CosmosDict
    assert saved["added_to_activity_log"] is True
    assert not source.exists()


def test_metadata_outcome_round_trips_through_sdk_access_projection():
    index = SdkProjectionContainer()
    settings = SdkProjectionContainer()
    point = settings.upsert_item(_succeeded_backfill_state())
    assert type(point) is CosmosDict
    point = settings.read_item(point["id"], point["id"])
    assert type(point) is CosmosDict
    source = CosmosDict({
        "id": "document-1", "user_id": "owner", "public_workspace_id": "public-1",
        "file_name": "guide.md", "title": "Guide", "version": 1, "_ts": 1,
        "status": "Processing complete", "percentage_complete": 100,
        "metadata_extraction_status": "failed",
    }, response_headers={})
    with _load_document_access_index_module(index_container=index, settings_container=settings) as (module, _, _):
        result = module.sync_document_access_index_for_document(source, force=True)
        listing = module.query_document_access_index_documents(
            source_scope="public", public_workspace_ids=["public-1"], user_id="reader",
        )
    assert result["success"] is True
    assert listing["success"] is True
    [document] = listing["documents"]
    assert document["metadata_extraction_status"] == "failed"
    assert document["status"] == "Processing complete"
    assert document["public_workspace_id"] == "public-1"


def test_public_picker_route_uses_sdk_projection_and_filtered_paging(monkeypatch):
    import test_public_chat_document_list_pending_artifacts as routes

    monkeypatch.setattr(
        routes, "_load_document_access_index_module",
        lambda: _load_document_access_index_module(
            index_container=SdkProjectionContainer(), settings_container=SdkProjectionContainer(),
        ),
    )
    documents = routes.released_documents()
    with routes.chat_routes(documents, index_ready=True) as env:
        env.args.update({"search": documents[-1]["file_name"].upper(), "page_size": "1"})
        result = routes.answer(env.list)
    assert result["total_count"] == 1
    assert result["page_size"] == 1
    assert [document["id"] for document in result["documents"]] == [documents[-1]["id"]]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
