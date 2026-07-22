#!/usr/bin/env python3
# test_mixed_source_manifest_contracts.py
"""
Functional test for authorized mixed-source manifest and evidence contracts.
Version: 0.250.062
Implemented in: 0.250.062

This test ensures Phase 1 of #1056 resolves requested sources once through
current authorization boundaries, preserves ordering, partitions mixed source
types, and bounds engine-neutral evidence without implementing #1057-#1061.
Parent initiative: #1055.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

from azure.cosmos.exceptions import CosmosResourceNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SEARCH_SERVICE_PATH = APP_ROOT / "functions_search_service.py"
sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration

ORIGINAL_ORCHESTRATION_LOG_EVENT = orchestration.log_event


def setup_module(module=None):
    orchestration.log_event = lambda *args, **kwargs: None


def teardown_module(module=None):
    orchestration.log_event = ORIGINAL_ORCHESTRATION_LOG_EVENT


class FakeItemContainer:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.read_calls = []
        self.query_calls = []

    def read_item(self, item, partition_key):
        self.read_calls.append((partition_key, item))
        key = (partition_key, item)
        if key not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        return dict(self.items[key])

    def query_items(self, query, parameters, partition_key):
        self.query_calls.append({
            "query": query,
            "parameters": list(parameters or []),
            "partition_key": partition_key,
        })
        parameter_values = {
            parameter.get("name"): parameter.get("value")
            for parameter in list(parameters or [])
        }
        document_id = parameter_values.get("@document_id")
        message_item = self.items.get((partition_key, document_id))
        if not message_item:
            return []
        metadata = message_item.get("metadata", {}) or {}
        return [{
            "id": message_item.get("id"),
            "role": message_item.get("role"),
            "filename": message_item.get("filename"),
            "title": message_item.get("title"),
            "version": message_item.get("version"),
            "is_user_upload": metadata.get("is_user_upload"),
            "is_generated_chat_artifact": metadata.get("is_generated_chat_artifact"),
            "generated_artifact_capability": metadata.get("generated_artifact_capability"),
            "generated_artifact_output_format": metadata.get("generated_artifact_output_format"),
        }]


def _normalize_id_list(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    normalized_values = []
    for value in list(values):
        normalized_value = str(value or "").strip()
        if normalized_value and normalized_value not in normalized_values:
            normalized_values.append(normalized_value)
    return normalized_values


def load_isolated_search_service():
    config_stub = types.ModuleType("config")
    config_stub.CLIENTS = {}
    config_stub.cognitive_services_scope = "https://example.invalid/.default"
    config_stub.cosmos_conversations_container = FakeItemContainer()
    config_stub.cosmos_messages_container = FakeItemContainer()

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    debug_stub = types.ModuleType("functions_debug")
    debug_stub.debug_print = lambda *args, **kwargs: None

    documents_stub = types.ModuleType("functions_documents")
    documents_stub.get_document_record = lambda **kwargs: None
    documents_stub.get_ordered_document_chunks = lambda **kwargs: []

    group_stub = types.ModuleType("functions_group")
    group_stub.get_user_groups = lambda user_id: []

    public_stub = types.ModuleType("functions_public_workspaces")
    public_stub.get_user_visible_public_workspace_ids_from_settings = lambda user_id: []

    search_stub = types.ModuleType("functions_search")
    search_stub.SEARCH_DEFAULT_TOP_N = 12
    search_stub.SEARCH_MAX_TOP_N = 500
    search_stub.hybrid_search = lambda **kwargs: []
    search_stub.normalize_search_id_list = _normalize_id_list
    search_stub.normalize_search_scope = (
        lambda value: str(value or "all").strip().lower()
        if str(value or "all").strip().lower() in {"all", "personal", "group", "public"}
        else "all"
    )
    search_stub.normalize_search_top_n = (
        lambda value, default_value, max_value: default_value if value is None else int(value)
    )

    settings_stub = types.ModuleType("functions_settings")
    settings_stub.get_settings = lambda: {}
    settings_stub.get_user_settings = lambda user_id: {"settings": {}}

    module_stubs = {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "functions_debug": debug_stub,
        "functions_documents": documents_stub,
        "functions_group": group_stub,
        "functions_public_workspaces": public_stub,
        "functions_search": search_stub,
        "functions_settings": settings_stub,
    }
    previous_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in module_stubs
    }
    sys.modules.update(module_stubs)

    try:
        module_spec = importlib.util.spec_from_file_location(
            "functions_search_service_mixed_source_test",
            SEARCH_SERVICE_PATH,
        )
        search_service = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(search_service)
    finally:
        for module_name, previous_module in previous_modules.items():
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

    return search_service


def build_authorized_resolver_fixture():
    search_service = load_isolated_search_service()
    state = {
        "group_ids": {"group-a"},
        "public_workspace_ids": {"public-a"},
        "group_authorization_count": 0,
        "public_authorization_count": 0,
    }
    personal_documents = {
        "personal-pdf": {
            "id": "personal-pdf",
            "user_id": "user-1",
            "title": "Personal report",
            "file_name": "report.pdf",
            "version": 3,
        },
        "personal-xlsx": {
            "id": "personal-xlsx",
            "user_id": "user-1",
            "title": "Personal workbook",
            "file_name": "data.xlsx",
            "version": 4,
        },
        "personal-docx": {
            "id": "personal-docx",
            "user_id": "user-1",
            "title": "Personal narrative",
            "file_name": "narrative.docx",
            "version": 1,
        },
        "personal-csv": {
            "id": "personal-csv",
            "user_id": "user-1",
            "title": "Personal data",
            "file_name": "data.csv",
            "version": 2,
        },
        "personal-unsupported": {
            "id": "personal-unsupported",
            "user_id": "user-1",
            "title": "Unsupported archive",
            "file_name": "archive.zip",
        },
    }
    group_documents = {
        ("group-a", "group-csv"): {
            "id": "group-csv",
            "group_id": "group-a",
            "title": "Shared group data",
            "file_name": "shared.csv",
            "version": 5,
        },
    }
    public_documents = {
        ("public-a", "public-csv"): {
            "id": "public-csv",
            "public_workspace_id": "public-a",
            "title": "Shared public data",
            "file_name": "shared.csv",
            "version": 6,
        },
    }

    def get_document_record(user_id, document_id, group_id=None, public_workspace_id=None):
        if group_id is not None:
            return group_documents.get((group_id, document_id))
        if public_workspace_id is not None:
            return public_documents.get((public_workspace_id, document_id))
        document_item = personal_documents.get(document_id)
        if document_item and document_item.get("user_id") == user_id:
            return dict(document_item)
        return None

    search_service.get_document_record = get_document_record
    def get_user_groups(user_id):
        state["group_authorization_count"] += 1
        return (
            [{"id": group_id} for group_id in sorted(state["group_ids"])]
            if user_id == "user-1"
            else []
        )

    def get_visible_public_workspace_ids(user_id):
        state["public_authorization_count"] += 1
        return (
            sorted(state["public_workspace_ids"])
            if user_id == "user-1"
            else []
        )

    search_service.get_user_groups = get_user_groups
    search_service.get_user_visible_public_workspace_ids_from_settings = (
        get_visible_public_workspace_ids
    )
    search_service.get_user_settings = lambda user_id: {"settings": {}}
    search_service.cosmos_conversations_container = FakeItemContainer({
        ("conversation-1", "conversation-1"): {
            "id": "conversation-1",
            "user_id": "user-1",
        },
    })
    search_service.cosmos_messages_container = FakeItemContainer({
        ("conversation-1", "chat-csv"): {
            "id": "chat-csv",
            "role": "file",
            "filename": "chat.csv",
            "file_content": "name,value\nalpha,1",
        },
    })

    resolver_calls = []

    def resolver(**resolver_arguments):
        resolver_calls.append(resolver_arguments["document_id"])
        return search_service.resolve_document_context(**resolver_arguments)

    return search_service, state, resolver, resolver_calls


def resolve_manifest(document_ids, resolver, user_id="user-1", conversation_id="conversation-1"):
    return orchestration.resolve_authorized_source_manifest(
        document_ids,
        user_id=user_id,
        conversation_id=conversation_id,
        context_resolver=resolver,
    )


def test_mixed_classification_order_and_partition():
    _, _, resolver, _ = build_authorized_resolver_fixture()

    pdf_xlsx_manifest = resolve_manifest(
        ["personal-pdf", "personal-xlsx"],
        resolver,
    )
    assert [entry["document_id"] for entry in pdf_xlsx_manifest] == [
        "personal-pdf",
        "personal-xlsx",
    ]
    assert [entry["source_kind"] for entry in pdf_xlsx_manifest] == [
        "narrative",
        "tabular",
    ]

    for document_ids in (
        ["personal-docx", "personal-csv"],
        ["personal-csv", "personal-docx"],
    ):
        manifest = resolve_manifest(document_ids, resolver)
        assert [entry["document_id"] for entry in manifest] == document_ids
        partitions = orchestration.partition_source_manifest(manifest)
        assert [entry["document_id"] for entry in partitions["tabular_sources"]] == [
            "personal-csv",
        ]
        assert [entry["document_id"] for entry in partitions["narrative_sources"]] == [
            "personal-docx",
        ]


def test_duplicates_and_cross_scope_filename_identity():
    _, _, resolver, resolver_calls = build_authorized_resolver_fixture()
    manifest = resolve_manifest(
        [
            "personal-xlsx",
            "personal-xlsx",
            "group-csv",
            "public-csv",
        ],
        resolver,
    )

    assert resolver_calls.count("personal-xlsx") == 1
    assert [entry["document_id"] for entry in manifest] == [
        "personal-xlsx",
        "group-csv",
        "public-csv",
    ]
    duplicate_name_entries = [
        entry for entry in manifest if entry["file_name"] == "shared.csv"
    ]
    assert len(duplicate_name_entries) == 2
    assert {
        (entry["scope"], entry["scope_id"], entry["document_id"])
        for entry in duplicate_name_entries
    } == {
        ("group", "group-a", "group-csv"),
        ("public", "public-a", "public-csv"),
    }


def test_unresolved_and_unsupported_do_not_erase_valid_sources():
    _, _, resolver, _ = build_authorized_resolver_fixture()
    manifest = resolve_manifest(
        ["personal-csv", "missing-source", "personal-unsupported", "personal-pdf"],
        resolver,
    )
    partitions = orchestration.partition_source_manifest(manifest)

    assert [entry["document_id"] for entry in manifest] == [
        "personal-csv",
        "missing-source",
        "personal-unsupported",
        "personal-pdf",
    ]
    assert [entry["document_id"] for entry in partitions["tabular_sources"]] == [
        "personal-csv",
    ]
    assert [entry["document_id"] for entry in partitions["narrative_sources"]] == [
        "personal-pdf",
    ]
    assert [entry["document_id"] for entry in partitions["unsupported_sources"]] == [
        "personal-unsupported",
    ]
    assert [entry["document_id"] for entry in partitions["unresolved_sources"]] == [
        "missing-source",
    ]
    unresolved_entry = partitions["unresolved_sources"][0]
    assert unresolved_entry["authorization_status"] == "unresolved"
    assert unresolved_entry["file_name"] is None
    assert unresolved_entry["scope"] is None
    assert unresolved_entry["scope_id"] is None


def test_personal_group_public_and_chat_authorization():
    search_service, state, resolver, _ = build_authorized_resolver_fixture()
    manifest = resolve_manifest(
        ["personal-pdf", "group-csv", "public-csv", "chat-csv"],
        resolver,
    )
    assert [entry["scope"] for entry in manifest] == [
        "personal",
        "group",
        "public",
        "chat",
    ]
    assert manifest[3]["conversation_id"] == "conversation-1"
    assert manifest[3]["scope_id"] == "conversation-1"

    original_search_service_module = sys.modules.get("functions_search_service")
    original_content_coercer = search_service._coerce_chat_upload_text
    search_service.cosmos_messages_container.read_calls.clear()
    search_service.cosmos_messages_container.query_calls.clear()
    search_service._coerce_chat_upload_text = lambda message_item: (_ for _ in ()).throw(
        AssertionError("Manifest resolution must not load chat-upload content")
    )
    sys.modules["functions_search_service"] = search_service
    try:
        metadata_only_chat_manifest = orchestration.resolve_authorized_source_manifest(
            ["chat-csv"],
            user_id="user-1",
            conversation_id="conversation-1",
        )
    finally:
        search_service._coerce_chat_upload_text = original_content_coercer
        if original_search_service_module is None:
            sys.modules.pop("functions_search_service", None)
        else:
            sys.modules["functions_search_service"] = original_search_service_module
    assert metadata_only_chat_manifest[0]["source_kind"] == "tabular"
    assert metadata_only_chat_manifest[0]["authorization_status"] == "authorized"
    assert search_service.cosmos_messages_container.read_calls == []
    assert len(search_service.cosmos_messages_container.query_calls) == 1
    assert "c.file_content" not in search_service.cosmos_messages_container.query_calls[0]["query"]
    assert "c.extracted_text" not in search_service.cosmos_messages_container.query_calls[0]["query"]

    caller_scope_payload = [{
        "document_id": "personal-pdf",
        "scope": "public",
        "public_workspace_id": "caller-controlled-workspace",
    }]
    caller_scope_manifest = resolve_manifest(caller_scope_payload, resolver)
    assert caller_scope_manifest[0]["scope"] == "personal"
    assert caller_scope_manifest[0]["public_workspace_id"] is None

    state["group_ids"].clear()
    state["public_workspace_ids"].clear()
    search_service.cosmos_conversations_container.items[
        ("conversation-1", "conversation-1")
    ]["user_id"] = "different-user"
    search_service.cosmos_messages_container.read_calls.clear()
    search_service.cosmos_messages_container.query_calls.clear()

    authorization_loss_manifest = resolve_manifest(
        ["group-csv", "public-csv", "chat-csv"],
        resolver,
    )
    assert all(
        entry["source_kind"] == "unresolved"
        and entry["authorization_status"] == "unresolved"
        and entry["file_name"] is None
        and entry["scope"] is None
        for entry in authorization_loss_manifest
    )
    assert search_service.cosmos_messages_container.read_calls == []
    assert search_service.cosmos_messages_container.query_calls == []

    personal_authorization_loss = resolve_manifest(
        ["personal-pdf"],
        resolver,
        user_id="different-user",
    )
    assert personal_authorization_loss[0]["source_kind"] == "unresolved"
    assert personal_authorization_loss[0]["display_name"] is None


def test_selection_mode_normalization():
    for selection_mode in ("selected", "all", "history", "relevance"):
        assert orchestration.normalize_selection_mode(
            f"  {selection_mode.upper()}  "
        ) == selection_mode
    assert orchestration.normalize_selection_mode(None) == "selected"

    try:
        orchestration.normalize_selection_mode("everything")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid selection_mode must fail validation")


def test_batch_authorization_snapshot_and_source_limit():
    search_service, state, _, _ = build_authorized_resolver_fixture()
    state["group_authorization_count"] = 0
    state["public_authorization_count"] = 0
    search_service.cosmos_conversations_container.read_calls.clear()

    original_search_service_module = sys.modules.get("functions_search_service")
    sys.modules["functions_search_service"] = search_service
    try:
        manifest = orchestration.resolve_authorized_source_manifest(
            ["personal-pdf", "group-csv", "public-csv", "chat-csv"],
            user_id="user-1",
            conversation_id="conversation-1",
        )
    finally:
        if original_search_service_module is None:
            sys.modules.pop("functions_search_service", None)
        else:
            sys.modules["functions_search_service"] = original_search_service_module

    assert [entry["scope"] for entry in manifest] == [
        "personal",
        "group",
        "public",
        "chat",
    ]
    assert state["group_authorization_count"] == 1
    assert state["public_authorization_count"] == 1
    assert search_service.cosmos_conversations_container.read_calls == [
        ("conversation-1", "conversation-1"),
    ]

    over_limit_resolver_calls = []
    over_limit_sources = [
        f"source-{source_index}"
        for source_index in range(orchestration.SOURCE_MANIFEST_MAX_SOURCES + 1)
    ]
    try:
        orchestration.resolve_authorized_source_manifest(
            over_limit_sources,
            user_id="user-1",
            context_resolver=lambda **kwargs: over_limit_resolver_calls.append(kwargs),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Over-limit source manifests must fail validation")
    assert over_limit_resolver_calls == []


def test_evidence_envelope_serialization_and_bounds():
    oversized_item = {
        "rows": [
            {"column": "x" * 5000, "value": row_number}
            for row_number in range(50)
        ]
    }
    envelope = orchestration.build_evidence_envelope(
        document_id="personal-xlsx",
        source_kind="tabular",
        engine="tabular_tools",
        status="partial",
        summary="s" * 20000,
        evidence=[oversized_item for _ in range(25)],
        citations=[oversized_item for _ in range(25)],
        generated_artifacts=[oversized_item for _ in range(25)],
        coverage={"requested_rows": 1000000, "processed_rows": 500000},
        error="e" * 5000,
    )
    serialized_envelope = orchestration.serialize_evidence_envelope(envelope)
    round_tripped_envelope = json.loads(serialized_envelope)

    assert len(serialized_envelope.encode("utf-8")) <= (
        orchestration.EVIDENCE_ENVELOPE_MAX_BYTES
    )
    assert len(round_tripped_envelope["evidence"]) <= (
        orchestration.EVIDENCE_LIST_MAX_ITEMS
    )
    assert len(round_tripped_envelope["citations"]) <= (
        orchestration.EVIDENCE_LIST_MAX_ITEMS
    )
    assert len(round_tripped_envelope["generated_artifacts"]) <= (
        orchestration.EVIDENCE_LIST_MAX_ITEMS
    )
    assert round_tripped_envelope["coverage"]["evidence_envelope_truncated"] is True
    assert round_tripped_envelope["summary"].endswith("...")
    assert round_tripped_envelope["error"].endswith("...")

    direct_envelope = {
        "document_id": "personal-xlsx",
        "source_kind": "tabular",
        "engine": "tabular_tools",
        "status": "completed",
        "summary": "direct",
        "evidence": [
            {"score": float("nan"), "value": item_number}
            for item_number in range(orchestration.EVIDENCE_LIST_MAX_ITEMS + 5)
        ],
        "citations": [],
        "generated_artifacts": [],
        "coverage": {},
        "error": None,
    }
    direct_serialized = orchestration.serialize_evidence_envelope(direct_envelope)
    direct_round_trip = json.loads(direct_serialized)
    assert len(direct_round_trip["evidence"]) == orchestration.EVIDENCE_LIST_MAX_ITEMS
    assert direct_round_trip["evidence"][0]["score"] is None
    assert direct_round_trip["coverage"]["evidence_envelope_truncated"] is True
    assert "NaN" not in direct_serialized

    nested_bound_envelope = orchestration.build_evidence_envelope(
        document_id="personal-xlsx",
        source_kind="tabular",
        engine="tabular_tools",
        status="completed",
        evidence=[{
            "values": list(
                range(orchestration.EVIDENCE_JSON_MAX_COLLECTION_ITEMS + 1)
            ),
        }],
        coverage={"bounded": True},
    )
    assert len(nested_bound_envelope["evidence"][0]["values"]) == (
        orchestration.EVIDENCE_JSON_MAX_COLLECTION_ITEMS
    )
    assert nested_bound_envelope["coverage"]["evidence_envelope_truncated"] is True
    assert len(json.dumps(nested_bound_envelope["coverage"]).encode("utf-8")) <= (
        orchestration.EVIDENCE_COVERAGE_MAX_BYTES
    )

    try:
        orchestration.serialize_evidence_envelope({
            **direct_envelope,
            "extra_content": "not part of the contract",
        })
    except ValueError:
        pass
    else:
        raise AssertionError("Evidence serializer must reject undeclared fields")


def test_manifest_diagnostics_are_aggregate_only():
    _, _, resolver, _ = build_authorized_resolver_fixture()
    captured_events = []
    original_log_event = orchestration.log_event
    orchestration.log_event = lambda message, **kwargs: captured_events.append(
        {"message": message, **kwargs}
    )
    try:
        resolve_manifest(
            ["personal-pdf", "personal-pdf", "group-csv", "missing-source"],
            resolver,
        )
    finally:
        orchestration.log_event = original_log_event

    assert len(captured_events) == 1
    diagnostics = captured_events[0]["extra"]
    assert diagnostics["requested_source_count"] == 4
    assert diagnostics["unique_source_count"] == 3
    assert diagnostics["duplicate_ids_removed"] == 1
    assert diagnostics["narrative_source_count"] == 1
    assert diagnostics["tabular_source_count"] == 1
    assert diagnostics["unresolved_or_unauthorized_count"] == 1
    serialized_diagnostics = json.dumps(diagnostics, sort_keys=True)
    for sensitive_value in (
        "personal-pdf",
        "group-csv",
        "missing-source",
        "report.pdf",
        "shared.csv",
        "conversation-1",
    ):
        assert sensitive_value not in serialized_diagnostics


def run_tests():
    tests = [
        test_mixed_classification_order_and_partition,
        test_duplicates_and_cross_scope_filename_identity,
        test_unresolved_and_unsupported_do_not_erase_valid_sources,
        test_personal_group_public_and_chat_authorization,
        test_selection_mode_normalization,
        test_batch_authorization_snapshot_and_source_limit,
        test_evidence_envelope_serialization_and_bounds,
        test_manifest_diagnostics_are_aggregate_only,
    ]
    results = []
    setup_module()
    try:
        for test in tests:
            try:
                test()
                print(f"PASS {test.__name__}")
                results.append(True)
            except Exception as exc:
                print(f"FAIL {test.__name__}: {exc}")
                results.append(False)
    finally:
        teardown_module()
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)