# test_orchestration_attachment_native_evidence.py
"""Real planning, inventory paging, retained evidence and composition regressions.

Version: 0.261.416
Implemented in: 0.261.416
Only external storage/model I/O is replaced; no provider calls are made.
"""

import importlib
import json
import base64
from io import BytesIO
from copy import deepcopy

import pytest
from PIL import Image
from azure.core import MatchConditions
from openpyxl import Workbook
from openpyxl.comments import Comment

from test_orchestration_harness_routes import modules, real_http_harness
from test_orchestration_dependency_runtime import runtime, execute, compose, binding, source_input
from test_excel_inventory_persistence import inventory_store, review_workbook
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_results import source


__all__ = ["modules", "real_http_harness", "runtime", "inventory_store", "review_workbook"]


def frames(response):
    return [
        json.loads(part.partition("data:")[2])
        for part in response.get_data(as_text=True).split("\n\n") if part.startswith("data:")
    ]


def image(harness, identifier="image-1", **changes):
    value = {
        "id": identifier, "conversation_id": "conversation-1", "role": "image",
        "filename": f"{identifier}.png", "metadata": {"is_user_upload": True},
        "vision_analysis": "Meeting at 14:30. Bring the signed budget.",
        "timestamp": "2026-09-21T18:01:00+00:00",
    }
    value.update(changes)
    harness.messages.create_item(value)
    return value


def attachment_io(harness, monkeypatch):
    service = importlib.import_module("functions_search_service")
    monkeypatch.setattr(service, "cosmos_messages_container", harness.messages)
    monkeypatch.setattr(service, "cosmos_conversations_container", harness.conversations)
    monkeypatch.setattr(service, "get_user_settings", lambda user_id: {"settings": {}})
    original_query = harness.messages.query_items

    def query(*args, **kwargs):
        sql = kwargs.get("query", args[0] if args else "")
        if 'c.role IN ("file", "image")' in sql:
            kwargs["query"] = sql.replace('c.role IN ("file", "image")', 'true')
            rows = original_query(**kwargs)
            return [row for row in rows if row.get("role") in ("file", "image")]
        parameters = {item["name"]: item["value"] for item in kwargs.get("parameters") or []}
        if "@document_id" in parameters:
            kwargs["query"] = sql.replace("SELECT TOP 1", "SELECT")
            return [row for row in original_query(**kwargs) if row["id"] == parameters["@document_id"]]
        return original_query(*args, **kwargs)

    monkeypatch.setattr(harness.messages, "query_items", query)
    return importlib.import_module("functions_orchestration_context")


@pytest.mark.parametrize("read_case,mask_after_plan", [
    ("saved", False), ("saved", True), ("pixels", False), ("pixels", True),
    ("missing", False), ("nonvision", False), ("masked_bytes", False), ("masked_model", False),
])
def test_http_existing_image_repairs_redundant_choice_then_reads_authorized_text(
    real_http_harness, monkeypatch, mask_after_plan, read_case,
):
    runtime_http, harness = real_http_harness, real_http_harness.harness
    attachment_io(harness, monkeypatch)
    saved_text = read_case == "saved"
    image_id = "conversation-1_image-1"
    pixels = BytesIO()
    Image.new("RGB", (12, 8), "white").save(pixels, format="PNG")
    image(harness, image_id, **({} if saved_text else {
        "vision_analysis": None, "content": (
            None if read_case == "missing"
            else "data:image/png;base64," + base64.b64encode(pixels.getvalue()).decode()
        ),
    }))
    request = "Transcribe the image."
    question = {
        "relationship": "clarification", "resolved_message": request, "message_ids": [],
        "requires_retrieval": True, "clarification": "Which image should I read?",
        "clarification_context": {"reason": "source_selection", "document_ids": [image_id]},
    }
    resolved = {**question, "relationship": "new_topic", "clarification": ""}
    answer = compose_step("answer", inputs={
        "evidence": {"binding": input_binding("read", "prepared"), "allow_partial": False},
    })
    answer["arguments"]["knowledge_basis"] = "sources"
    proposal = {
        "kind": "plan", "steps": [
            {"step_id": "read", "capability_id": "document_search",
             "arguments": {"query": request, "document_ids": [image_id]}},
            answer,
        ], "final_response": input_binding("answer"),
    }
    harness.replies = [
        json.dumps(question), json.dumps(resolved), json.dumps(proposal),
        "Meeting at 14:30. Bring the signed budget.",
    ]
    if not saved_text:
        harness.replies.append("Meeting at 14:30. Bring the signed budget.")
    response = runtime_http.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "read-attached-image",
        "message": request, "approval_mode": "manual",
    }, buffered=True)
    planned = frames(response)
    assert response.status_code == 200 and "plan" in planned[-1], planned
    assert not any(item.get("elicitation") for item in planned)
    plan = planned[-1]["plan"]
    record = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert record["seeds"]["document_ids"] == [image_id]
    assert record["seeds"]["image_reference_messages"] == []
    assert len(harness.model_calls) == 3
    payload = json.loads(harness.model_calls[0]["messages"][1]["content"])
    assert payload["selected_sources"][0]["resolved_attachment"] is True
    assert "vision_analysis" not in json.dumps(payload)
    def mask_image():
        stored = harness.messages.read_item(image_id, "conversation-1")
        stored["metadata"]["masked"] = True
        harness.messages.replace_item(
            image_id, stored, etag=stored["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    if mask_after_plan:
        mask_image()
    if read_case == "nonvision":
        capabilities = importlib.import_module("functions_model_capabilities")
        monkeypatch.setattr(capabilities, "is_vision_capable_model", lambda *args: False)
    elif read_case == "masked_bytes":
        vision = importlib.import_module("functions_chat_vision")
        build_parts = vision.build_vision_image_parts

        def masked_parts(*args, **kwargs):
            parts = build_parts(*args, **kwargs)
            mask_image()
            return parts

        monkeypatch.setattr(vision, "build_vision_image_parts", masked_parts)
    elif read_case == "masked_model":
        def masked_answer():
            mask_image()
            return "Meeting at 14:30. Bring the signed budget."

        harness.replies[0] = masked_answer
    done = frames(runtime_http.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": plan["run_id"],
    }, buffered=True))
    if mask_after_plan or read_case in ("missing", "nonvision", "masked_bytes", "masked_model"):
        assert done[-1]["status"] == "failed", done
        assert len(harness.model_calls) == (4 if read_case == "masked_model" else 3)
        return
    assert done[-1]["status"] == "completed", done
    retained = json.dumps(harness.model_calls[-1]["messages"], ensure_ascii=False)
    assert "Meeting at 14:30" in retained
    assert harness.blobs.file_uploads == 0
    if not saved_text:
        vision_input = harness.model_calls[-2]["messages"][0]["content"]
        assert vision_input[0]["type"] == "text"
        image_url = vision_input[1]["image_url"]["url"]
        actual_pixels = Image.open(BytesIO(base64.b64decode(image_url.split(",", 1)[1])))
        assert actual_pixels.size == (12, 8)
        assert "data:image/" not in retained
        assert len(harness.model_calls) == 5


@pytest.mark.parametrize("excluded", [
    {"metadata": {"is_user_upload": True, "masked": True}},
    {"metadata": {"is_user_upload": True, "masked_ranges": [{"start": 0, "end": 1}]}},
    {"metadata": {"is_user_upload": True, "thread_info": {"active_thread": False}}},
    {"metadata": {"is_user_upload": True, "content_moderation": {"removed": True}}},
    {"status": "processing", "percentage_complete": 20},
])
def test_invisible_or_unready_image_is_never_selected(real_http_harness, monkeypatch, excluded):
    harness = real_http_harness.harness
    context = attachment_io(harness, monkeypatch)
    image(harness, **excluded)
    result = context.resolve_conversation_attachments(
        "Read the image.", "owner", "conversation-1", seeds={},
    )
    assert result.get("document_ids", []) == []
    assert result["conversation_attachments"] == []


def test_ambiguous_images_and_explicit_selection_are_not_overridden(real_http_harness, monkeypatch):
    harness = real_http_harness.harness
    context = attachment_io(harness, monkeypatch)
    image(harness)
    image(harness, "image-2")
    ambiguous = context.resolve_conversation_attachments(
        "Read the image.", "owner", "conversation-1", seeds={},
    )
    assert ambiguous.get("document_ids", []) == []
    assert len(ambiguous["conversation_attachments"]) == 2
    named = context.resolve_conversation_attachments(
        "Read image-2.png.", "owner", "conversation-1", seeds={},
    )
    assert named["document_ids"] == ["image-2"]
    explicit = context.resolve_conversation_attachments(
        "Read the image.", "owner", "conversation-1", seeds={"document_ids": ["selected-report"]},
    )
    assert explicit["document_ids"] == ["selected-report"]
    with pytest.raises(context.ElicitationContextError):
        context.resolve_conversation_attachments(
            "Read the image.", "another-user", "conversation-1", seeds={},
        )


def configure_inventory(runtime, monkeypatch, inventory_store, workbook):
    excel_inventory = importlib.import_module("functions_excel_inventory")
    contracts = importlib.import_module("content_screening.contracts")
    store, _ = inventory_store
    _, _, reference = excel_inventory.persist_excel_inventory(
        workbook, ".xlsx", subject=contracts.Subject("personal", "owner", "document-1", "1"), storage=store,
    )
    document = {
        "id": "document-1", "user_id": "owner", "version": 1, "file_name": "review.xlsx",
        "excel_native_inventory": reference, "accessibility_metadata": {"format": "xlsx"},
    }
    service = importlib.import_module("functions_search_service")
    monkeypatch.setattr(service, "resolve_document_context", lambda **kwargs: {
        "document": deepcopy(document), "scope": "personal",
    })
    monkeypatch.setattr(service, "assert_document_available", lambda value, **kwargs: value)
    monkeypatch.setattr(service, "assert_evidence_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "get_ordered_document_chunks", lambda **kwargs: [])
    monkeypatch.setattr(service, "ScreeningStorage", lambda **kwargs: store)
    original = service.get_document_accessibility_payload
    calls = []

    def small_pages(*args, **kwargs):
        calls.append(deepcopy(kwargs))
        kwargs["native_page_size"] = 2
        kwargs["_native_max_bytes"] = 4096
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "get_document_accessibility_payload", small_pages)
    step = {
        "step_id": "comments", "capability_id": "document_search",
        "arguments": {"query": "Review all Notes and threaded comments.", "document_ids": ["document-1"],
                      "native_section": "comments"},
    }
    return step, calls, document


def test_native_workbook_comments_reach_retained_evidence_and_composition(
    runtime, monkeypatch, inventory_store, review_workbook,
):
    step, calls, _ = configure_inventory(runtime, monkeypatch, inventory_store, review_workbook)
    case = runtime.make([
        step, compose("answer", inputs={"comments": source_input("comments", "prepared")}),
    ], ["Budget!B4 is saved as 15000; the reviewer requests 19500."], final_response=binding("answer"))
    case.fixture.sources["document-1"] = {
        **source(), "file_name": "review.xlsx", "source_kind": "tabular",
    }
    failures = []
    monkeypatch.setattr(runtime.composition, "log_event", lambda *args, **kwargs: failures.append(kwargs))
    result = execute(runtime, case)
    assert result["status"] == "completed", failures
    assert len(calls) == 3 and calls[1]["native_cursor"]
    task = case.context.task_results["comments"]
    prepared = case.fixture.restart().open_result(task.output("prepared")).read_value()
    rows = [json.loads(hit["chunk_text"])["excel_annotation"] for hit in prepared["search_results"][1:]]
    assert len(rows) == 5
    assert sum(row["kind"] == "note" for row in rows) == 1
    assert any(row.get("parent_id") == "{root-budget}" for row in rows)
    budget = next(row for row in rows if row.get("id") == "{root-budget}")
    assert budget["sheet"] == "Budget" and budget["cell"] == "B4"
    assert budget["cell_value"] == 15000 and budget["author"] == "Reviewer A"
    assert budget["date"] == "2026-01-01T10:00:00Z"
    assert any(row.get("resolved") is True for row in rows)
    assert any(row.get("cell_value_status") == "blank" and row["cell"] == "D12" for row in rows)
    coverage = prepared["coverage"]["native_inspection"][0]
    assert coverage["returned_records"] == 5 and not coverage["partial"]
    payload = json.loads(case.model.calls[-1][0][-1]["content"])
    assert "Set cap to 19500." in json.dumps(payload)
    assert "Keep cap at 15000." in json.dumps(payload)
    assert task.output("prepared").completeness.status == "complete"


@pytest.mark.parametrize("annotated", [False, True])
def test_empty_inventory_and_fragmented_unicode_formula_note(
    runtime, monkeypatch, inventory_store, tmp_path, annotated,
):
    workbook = Workbook()
    workbook.active["A1"] = "=1+2"
    text = "Reviewer α\n" * 10000 + "LAST-ANNOTATION"
    if annotated:
        workbook.active["A1"].comment = Comment(text, "Reviewer")
    path = tmp_path / "long-note.xlsx"
    workbook.save(path)
    workbook.close()
    step, calls, _ = configure_inventory(runtime, monkeypatch, inventory_store, path)
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.xlsx"}
    result = execute(runtime, case)
    assert result["status"] == "completed", result["steps"]
    task = case.context.task_results["comments"]
    prepared = case.fixture.restart().open_result(task.output("prepared")).read_value()
    coverage = prepared["coverage"]["native_inspection"][0]
    assert coverage["returned_records"] == int(annotated) and not coverage["partial"]
    if annotated:
        assert len(calls) > 10
        record = json.loads(prepared["search_results"][1]["chunk_text"])["excel_annotation"]
        assert record["text"] == text
        assert record["cell_value"] is None
        assert record["cell_value_status"] == "cache_missing"
    else:
        assert len(calls) == 1
        assert len(prepared["search_results"]) == 1


@pytest.mark.parametrize("failure", ["revoked", "changed", "missing", "limit"])
def test_native_inventory_failures_are_not_empty_success_and_limits_remain_partial(
    runtime, monkeypatch, inventory_store, review_workbook, failure,
):
    step, calls, _ = configure_inventory(runtime, monkeypatch, inventory_store, review_workbook)
    service = importlib.import_module("functions_search_service")
    original = service.get_document_accessibility_payload

    def read(*args, **kwargs):
        if failure == "revoked" and calls:
            raise PermissionError("Workbook access was revoked.")
        report = original(*args, **kwargs)
        if failure == "changed" and len(calls) > 1:
            report["excel_inspection"]["page"]["source_sha256"] = "changed"
        if failure == "missing":
            report.pop("excel_inspection")
        return report

    monkeypatch.setattr(service, "get_document_accessibility_payload", read)
    if failure == "limit":
        collector = importlib.import_module("functions_orchestration_excel")
        monkeypatch.setattr(collector, "MAX_VALUE_BYTES", 2000)
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.xlsx"}
    result = execute(runtime, case)
    if failure == "limit":
        task = case.context.task_results["comments"]
        assert task.status == "partial"
        prepared = case.fixture.restart().open_result(task.output("prepared"), allow_partial=True).read_value()
        coverage = prepared["coverage"]["native_inspection"][0]
        assert coverage["partial"] and coverage["has_more"]
        assert coverage["returned_records"] < coverage["total_records"]
        assert task.output("prepared").completeness.status == "partial"
    else:
        assert result["status"] == "failed"
        assert "comments" not in case.context.task_results
        assert case.model.calls == []
