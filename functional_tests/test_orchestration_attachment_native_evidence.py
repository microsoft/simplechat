# test_orchestration_attachment_native_evidence.py
"""Real planning, inventory paging, retained evidence and composition regressions.

Version: 0.261.422
Implemented in: 0.261.416
Word-native comment routing and evidence delivery: 0.261.422
Only external storage/model I/O is replaced; no provider calls are made.
"""

import importlib
import json
import base64
import hashlib
import logging
import zipfile
from io import BytesIO
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image
from azure.core import MatchConditions
from openpyxl import Workbook
from openpyxl.comments import Comment
from flask import Blueprint
from types import SimpleNamespace

from test_orchestration_harness_routes import modules, real_http_harness
from test_orchestration_dependency_runtime import runtime, execute, compose, binding, source_input
from test_excel_inventory_persistence import inventory_store, review_workbook
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_results import source
from functions_workflow_result_store import WorkflowResultIntegrityError


__all__ = ["modules", "real_http_harness", "runtime", "inventory_store", "review_workbook"]


@pytest.fixture(scope="module", autouse=True)
def offline_native_modules(modules):
    """Native tests must also work alone, without an earlier image test importing config."""
    yield modules


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


def word_comment_package(*, comments=True, extended=True, malformed=False, anchor="15000", closed_anchor=True):
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    range_end = '<w:commentRangeEnd w:id="0"/>' if closed_anchor else ''
    document = (
        f'<w:document xmlns:w="{namespace}"><w:body><w:p>'
        '<w:r><w:t>Budget cap </w:t></w:r><w:commentRangeStart w:id="0"/>'
        f'<w:r><w:t>{anchor}</w:t></w:r>{range_end}'
        '<w:r><w:commentReference w:id="0"/></w:r></w:p></w:body></w:document>'
    )
    comment_xml = (
        f'<w:comments xmlns:w="{namespace}" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        '<w:comment w:id="0" w:author="Reviewer" w:date="2026-01-01T10:00:00Z">'
        '<w:p w14:paraId="00000001"><w:r><w:t>Raise cap to 19500.</w:t></w:r></w:p></w:comment>'
        '<w:comment w:id="1" w:author="Author" w:date="2026-01-01T11:00:00Z">'
        '<w:p w14:paraId="00000002"><w:r><w:t>Keep cap at 15000.</w:t></w:r></w:p></w:comment>'
        '</w:comments>'
    )
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", document)
        if comments:
            archive.writestr("word/comments.xml", "<malformed" if malformed else comment_xml)
            if extended:
                archive.writestr("word/commentsExtended.xml", (
                    '<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
                    '<w15:commentEx w15:paraId="00000001" w15:done="0"/>'
                    '<w15:commentEx w15:paraId="00000002" w15:paraIdParent="00000001" w15:done="1"/>'
                    '</w15:commentsEx>'
                ))
    return stream.getvalue()


def configure_word_inventory(runtime, monkeypatch, content, *, extension="docx"):
    document = {
        "id": "document-1", "user_id": "owner", "version": 1,
        "file_name": f"review.{extension}", "accessibility_metadata": {"format": extension},
    }
    service = importlib.import_module("functions_search_service")
    monkeypatch.setattr(service, "resolve_document_context", lambda **kwargs: {
        "document": deepcopy(document), "scope": "personal",
    })
    monkeypatch.setattr(service, "assert_document_available", lambda value, **kwargs: value)
    monkeypatch.setattr(service, "assert_evidence_available", lambda *args, **kwargs: None)
    calls = []

    def read_bytes(value, **kwargs):
        calls.append(deepcopy(kwargs))
        if isinstance(content, Exception):
            raise content
        return deepcopy(value), content

    monkeypatch.setattr(service.screening_access, "read_available_document_bytes", read_bytes)
    step = {
        "step_id": "comments", "capability_id": "document_search",
        "arguments": {"query": "Read every Word review comment and reply.",
                      "document_ids": ["document-1"], "native_section": "comments"},
    }
    return step, calls, document


def test_word_metadata_reader_uses_original_comments_not_stored_style_metadata(runtime, monkeypatch):
    _, calls, _ = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    service = importlib.import_module("functions_search_service")
    report = service.get_document_accessibility_payload("document-1", "owner", sections="comments")
    assert report["word_inspection"]["records"][0]["text"] == "Raise cap to 19500."
    assert len(calls) == 1


@pytest.mark.parametrize("metadata", [None, {}])
def test_word_comment_only_inspection_does_not_need_stored_metadata(runtime, monkeypatch, metadata):
    _, calls, document = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    document["accessibility_metadata"] = metadata
    service = importlib.import_module("functions_search_service")
    report = service.get_document_accessibility_payload("document-1", "owner", sections="comments")
    assert report["word_inspection"]["records"][0]["text"] == "Raise cap to 19500."
    assert report["format"] == "docx" and len(calls) == 1
    assert not set(report).intersection({"accessibility_metadata", "style_inventory", "issues"})


@pytest.mark.parametrize("metadata", [None, {}])
@pytest.mark.parametrize("section", ["accessibility", "style", "issues"])
def test_word_comments_do_not_certify_missing_stored_sections(runtime, monkeypatch, metadata, section):
    _, _, document = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    document["accessibility_metadata"] = metadata
    service = importlib.import_module("functions_search_service")
    with pytest.raises(LookupError, match="No accessibility metadata is stored"):
        service.get_document_accessibility_payload("document-1", "owner", sections=f"comments,{section}")


@pytest.mark.parametrize("metadata", [None, {}])
def test_word_default_metadata_requests_do_not_read_the_original(runtime, monkeypatch, metadata):
    _, calls, document = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    document["accessibility_metadata"] = metadata
    service = importlib.import_module("functions_search_service")
    with pytest.raises(LookupError, match="No accessibility metadata is stored"):
        service.get_document_accessibility_payload("document-1", "owner")
    assert calls == []


@pytest.mark.parametrize("extension", ["docx", "docm", "dotx"])
@pytest.mark.parametrize("repair_checker", [False, True])
@pytest.mark.parametrize("prepared_text", [False, True])
def test_word_comments_use_the_real_word_reader_and_reach_retained_answers(
    runtime, monkeypatch, caplog, extension, repair_checker, prepared_text,
):
    content = word_comment_package()
    step, calls, document = configure_word_inventory(runtime, monkeypatch, content, extension=extension)
    candidate = "The reviewer requests 19500; the author replies to keep 15000."
    completeness = importlib.import_module("functions_task_completeness")
    assessment_item = {
        "status": "satisfied", "reason": "", "evidence_refs": ["comments"], "answer_quote": candidate,
    }
    assessment = {"requirements": {
        identifier: deepcopy(assessment_item) for identifier, _ in completeness.NARRATIVE_OBLIGATIONS
    } if prepared_text else [
        {"id": "review", "requirement": "Explain the reviewer comment and reply.", **assessment_item},
    ]}
    invalid_assessment = deepcopy(assessment)
    for item in (
        invalid_assessment["requirements"].values() if prepared_text else invalid_assessment["requirements"]
    ):
        item["evidence_refs"] = ["PRIVATE_INVALID_SOURCE_LABEL"]
    replies = [candidate]
    if repair_checker:
        replies.extend([json.dumps(invalid_assessment), json.dumps(assessment)])
    answer_step = compose("answer", inputs={"comments": source_input("comments", "prepared")})
    if prepared_text:
        answer_step["arguments"]["response_policy"] = "available_information"
    case = runtime.make([
        step, answer_step,
    ], replies, final_response=binding("answer"),
        settings={"enable_chat_orchestration_completeness_check": repair_checker})
    case.fixture.sources["document-1"] = {**source(), "file_name": document["file_name"]}
    spec = importlib.util.spec_from_file_location(
        "native_comment_telemetry",
        Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_appinsights.py",
    )
    telemetry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(telemetry)
    adapters = importlib.import_module("functions_orchestration_adapters")
    logger = logging.getLogger("test.orchestration.native_comments")
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": False})
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(adapters, "log_event", telemetry.log_event)
    monkeypatch.setattr(adapters, "workflow_log_context", telemetry.workflow_log_context)
    monkeypatch.setattr(runtime.composition, "log_event", telemetry.log_event)
    monkeypatch.setattr(runtime.composition, "workflow_log_context", telemetry.workflow_log_context)
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = execute(runtime, case)
    assert result["status"] == "completed", {
        row["step_id"]: row.get("failure") for row in result["steps"]
    }
    assert len(calls) == 1 and calls[0]["user_id"] == "owner" and calls[0]["purpose"] == "accessibility"
    task = case.context.task_results["comments"]
    prepared = case.fixture.restart().open_result(task.output("prepared")).read_value()
    assert prepared["content_scope"] == "native_document_annotations"
    record = json.loads(prepared["search_results"][1]["chunk_text"])["word_annotation"]
    assert record["id"] == "0" and record["author"] == "Reviewer"
    assert record["text"] == "Raise cap to 19500." and record["anchor_text"] == "15000"
    assert record["date"] == "2026-01-01T10:00:00Z"
    assert record["resolution_available"] and record["done"] is False
    assert record["anchor_complete"] and record["position_known"]
    assert record["replies"][0]["text"] == "Keep cap at 15000."
    assert record["replies"][0]["author"] == "Author" and record["replies"][0]["done"] is True
    coverage = prepared["coverage"]["native_inspection"][0]
    assert coverage["total_records"] == coverage["returned_records"] == 1
    assert coverage["total_replies"] == 1 and not coverage["partial"]
    assert coverage["source_sha256"] == hashlib.sha256(content).hexdigest()
    payload = json.loads(case.model.calls[0][0][-1]["content"])
    assert "Raise cap to 19500." in json.dumps(payload) and "Keep cap at 15000." in json.dumps(payload)
    reader = importlib.import_module("functions_orchestration_result_runtime")
    citations = reader.read_result_document_citations(case.context, task.output("prepared"))
    citation = next(item for item in citations if item.get("evidence_kind") == "native_word_annotation")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    cited = reader.read_native_citation_evidence(
        case.fixture.restart(), contracts.ResultRef.from_dict(citation["native_evidence"]),
        citation_id=citation["citation_id"], document_id="document-1",
    )
    assert cited["native_annotation"] == record and cited["evidence_kind"] == "native_word_annotation"
    checkpoints = [entry for entry in caplog.records if getattr(entry, "sc_stage", None) == "native_comment_read"]
    assert [entry.sc_outcome for entry in checkpoints] == ["started", "completed"]
    assert all(entry.sc_source_format == extension and entry.sc_run_id_hash and entry.sc_step_id_hash for entry in checkpoints)
    serialized = json.dumps([{key: value for key, value in entry.__dict__.items() if key.startswith("sc_")} for entry in checkpoints])
    assert "Raise cap" not in serialized and document["file_name"] not in serialized
    assert len(case.model.calls) == (3 if repair_checker else 1)
    if repair_checker:
        feedback = json.loads(case.model.calls[2][0][-1]["content"])["assessment_problem"]
        assert feedback["allowed_evidence_refs"] == ["comments", "user_provided_content"]
        diagnostics = [entry for entry in caplog.records if getattr(entry, "sc_stage", None) == "task_completeness_assessment"]
        assert len(diagnostics) == 1
        assert diagnostics[0].sc_validation_code == "completeness_evidence_invalid"
        assert diagnostics[0].sc_run_id_hash and diagnostics[0].sc_step_id_hash
        assert diagnostics[0].sc_report_repair_count == 0 and diagnostics[0].sc_evidence_key_count == 2
        assert diagnostics[0].sc_evidence_ref_count == 1 and diagnostics[0].sc_evidence_refs_list is True
        safe_fields = {key: value for key, value in diagnostics[0].__dict__.items() if key.startswith("sc_")}
        assert "PRIVATE_INVALID_SOURCE_LABEL" not in json.dumps(safe_fields)
        answer = case.fixture.restart().open_result(case.context.task_results["answer"].output("answer")).read_text()
        assert answer == candidate


def test_word_evidence_does_not_bypass_repeated_unsupported_answer_findings(runtime, monkeypatch):
    step, _, _ = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    candidate = "The author accepted the higher cap of 19500."
    assessment = json.dumps({"requirements": [{
        "id": "grounding", "requirement": "Describe what the author actually replied.",
        "status": "missing", "reason": "The source says to keep 15000, not accept 19500.",
        "evidence_refs": ["comments"], "answer_quote": "",
    }]})
    case = runtime.make([
        step, compose("answer", inputs={"comments": source_input("comments", "prepared")}),
    ], [
        candidate, assessment, "The higher cap of 19500 was approved.", assessment,
        "The final approved policy cap is 19500.", assessment,
    ], final_response=binding("answer"),
        settings={"enable_chat_orchestration_completeness_check": True})
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.docx"}
    result = execute(runtime, case)
    assert result["status"] == "failed"
    answer = next(row for row in result["steps"] if row["step_id"] == "answer")
    assert answer["failure"]["code"] == "completeness_incomplete"
    assert len(case.model.calls) == 6
    assert "comments" in case.context.task_results and "answer" not in case.context.task_results


@pytest.mark.parametrize("anchor,closed", [(" " + "x" * 400, True), ("15000", False)])
def test_word_anchor_completeness_requires_an_unclipped_closed_range(runtime, monkeypatch, anchor, closed):
    configure_word_inventory(runtime, monkeypatch, word_comment_package(anchor=anchor, closed_anchor=closed))
    service = importlib.import_module("functions_search_service")
    payload = service.get_document_accessibility_payload("document-1", "owner", sections="comments")
    annotation = payload["word_inspection"]["records"][0]
    assert annotation["anchor_text"] and not annotation["anchor_complete"]


def test_comment_only_metadata_request_rejects_an_unsupported_format(runtime, monkeypatch):
    _, calls, _ = configure_word_inventory(runtime, monkeypatch, word_comment_package(), extension="pdf")
    service = importlib.import_module("functions_search_service")
    with pytest.raises(LookupError, match="native comment inventory is unavailable"):
        service.get_document_accessibility_payload("document-1", "owner", sections="comments")
    assert calls == []


@pytest.mark.parametrize("problem", ["empty", "missing", "malformed", "revoked", "changed", "limit"])
def test_word_native_unavailable_sources_never_become_empty_success(runtime, monkeypatch, problem):
    content = (
        LookupError("PRIVATE_ORIGINAL_UNAVAILABLE") if problem == "missing"
        else word_comment_package(comments=problem != "empty", malformed=problem == "malformed")
    )
    step, _, _ = configure_word_inventory(runtime, monkeypatch, content)
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.docx"}
    service = importlib.import_module("functions_search_service")
    original = service.screening_access.read_available_document_bytes

    def read_then_change(*args, **kwargs):
        value = original(*args, **kwargs)
        if problem == "revoked":
            case.fixture.denied.add("document-1")
        elif problem == "changed":
            case.fixture.sources["document-1"]["source_revision"] = "new-revision"
        return value

    monkeypatch.setattr(service.screening_access, "read_available_document_bytes", read_then_change)
    if problem == "limit":
        collector = importlib.import_module("functions_orchestration_excel")
        monkeypatch.setattr(collector, "MAX_VALUE_BYTES", 4)
    result = execute(runtime, case)
    if problem in ("empty", "limit"):
        assert "comments" in case.context.task_results, result["steps"]
        task = case.context.task_results["comments"]
        prepared = case.fixture.restart().open_result(task.output("prepared"), allow_partial=True).read_value()
        coverage = prepared["coverage"]["native_inspection"][0]
        assert coverage["returned_records"] == 0 and coverage["partial"] is (problem == "limit")
        assert task.output("prepared").completeness.status == ("partial" if problem == "limit" else "complete")
    else:
        assert result["status"] != "completed" and "comments" not in case.context.task_results
        assert "PRIVATE_ORIGINAL" not in json.dumps(result)


def test_word_resolution_and_bounded_anchor_remain_explicitly_unavailable(runtime, monkeypatch):
    step, _, _ = configure_word_inventory(
        runtime, monkeypatch, word_comment_package(extended=False, anchor="a" * 400),
    )
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.docx"}
    result = execute(runtime, case)
    assert result["status"] == "completed", result["steps"]
    prepared = case.fixture.restart().open_result(case.context.task_results["comments"].output("prepared")).read_value()
    record = json.loads(prepared["search_results"][1]["chunk_text"])["word_annotation"]
    assert record["done"] is None and record["resolution_available"] is False
    assert len(record["anchor_text"]) == 300 and record["anchor_complete"] is False
    assert prepared["coverage"]["native_inspection"][0]["total_records"] == 2


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
    citations = runtime.composition.read_result_document_citations(case.context, task.output("prepared"))
    annotated = [citation for citation in citations if citation.get("evidence_kind") == "native_excel_annotation"]
    assert len(annotated) == 5
    assert all(citation["location_label"] == "Location" for citation in annotated)
    assert all(citation["document_id"] == "document-1" and citation["native_evidence"] for citation in annotated)
    reader = importlib.import_module("functions_orchestration_result_runtime")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    for citation in citations:
        evidence = reader.read_native_citation_evidence(
            case.fixture.restart(), contracts.ResultRef.from_dict(citation["native_evidence"]),
            citation_id=citation["citation_id"], document_id=citation["document_id"],
        )
        if citation.get("evidence_kind") == "native_excel_annotation":
            assert evidence["native_annotation"].get("id") == citation.get("annotation_id")
            assert evidence["native_annotation"]["sheet"] == citation["sheet_name"]
        else:
            assert evidence["native_coverage"]["returned_records"] == 5
            assert "native_annotation" not in evidence
    assert "native_evidence" not in json.dumps(payload)


@pytest.mark.parametrize("unavailable", ["changed", "revision", "denied", "held", "foreign_document", "foreign_owner", "digest"])
def test_native_citation_lookup_rejects_stale_or_untrusted_evidence(
    runtime, monkeypatch, inventory_store, review_workbook, unavailable,
):
    step, _, _ = configure_inventory(runtime, monkeypatch, inventory_store, review_workbook)
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": "review.xlsx"}
    result = execute(runtime, case)
    assert result["status"] == "completed"
    task = case.context.task_results["comments"]
    reader = importlib.import_module("functions_orchestration_result_runtime")
    reference = task.output("prepared")
    citation = reader.read_result_document_citations(case.context, reference)[1]
    document_id = "document-1"
    if unavailable == "changed":
        case.fixture.sources[document_id]["source_version"] = 2
    elif unavailable == "revision":
        case.fixture.sources[document_id]["source_revision"] = "new-revision"
    elif unavailable == "denied":
        case.fixture.denied.add(document_id)
    elif unavailable == "held":
        case.fixture.held.add(document_id)
    elif unavailable == "foreign_document":
        document_id = "another-document"
    elif unavailable == "foreign_owner":
        case.fixture.conversation["user_id"] = "another-owner"
    else:
        from dataclasses import replace
        reference = replace(reference, manifest_sha256="a" * 64)
    with pytest.raises((PermissionError, reader.ResultContractError, reader.ScreeningError, WorkflowResultIntegrityError)):
        reader.read_native_citation_evidence(
            case.fixture.restart(), reference, citation_id=citation["citation_id"], document_id=document_id,
        )


@pytest.mark.parametrize("source_format", ["xlsx", "docx"])
def test_native_citation_http_lookup_uses_retained_result_not_search(
    runtime, real_http_harness, monkeypatch, inventory_store, review_workbook, source_format,
):
    if source_format == "docx":
        step, _, _ = configure_word_inventory(runtime, monkeypatch, word_comment_package())
    else:
        step, _, _ = configure_inventory(runtime, monkeypatch, inventory_store, review_workbook)
    case = runtime.make([step])
    case.fixture.sources["document-1"] = {**source(), "file_name": f"review.{source_format}"}
    result = execute(runtime, case)
    assert result["status"] == "completed"
    reader = importlib.import_module("functions_orchestration_result_runtime")
    citation = reader.read_result_document_citations(case.context, case.context.task_results["comments"].output("prepared"))[1]
    activity = importlib.import_module("functions_activity_logging")
    for name in ("log_document_upload", "log_document_metadata_update_transaction"):
        monkeypatch.setattr(activity, name, lambda *args, **kwargs: None, raising=False)
    route = importlib.import_module("route_backend_documents")
    bootstrap = importlib.import_module("functions_orchestration_bootstrap")
    screening = importlib.import_module("content_screening.access")
    monkeypatch.setattr(screening, "_read_authorized_document", lambda document_id, user_id, **kwargs: case.fixture.metadata(
        document_id, user_id, kwargs.get("group_id"), kwargs.get("public_workspace_id"),
    ))
    monkeypatch.setattr(bootstrap, "build_orchestration_services", lambda user_id, conversation_id: SimpleNamespace(results=case.fixture.restart()))
    monkeypatch.setattr(route, "_resolve_citation_chunk", lambda *args, **kwargs: pytest.fail("Native evidence must not enter Search."))
    blueprint = Blueprint("native_citation_documents", __name__)
    auth = importlib.import_module("functions_authentication")
    blueprint.before_request(auth.user_required_blueprint())
    route.register_route_backend_documents(blueprint)
    real_http_harness.app.register_blueprint(blueprint)
    body = {
        "citation_id": citation["citation_id"], "document_id": "document-1",
        "conversation_id": "conversation-1", "native_evidence": citation["native_evidence"],
    }
    response = real_http_harness.client.post("/api/get_citation", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["native_annotation"]["id"] == citation["annotation_id"]
    missing = {key: value for key, value in body.items() if key != "native_evidence"}
    response = real_http_harness.client.post("/api/get_citation", json=missing)
    assert response.status_code == 404
    foreign = deepcopy(body)
    foreign["native_evidence"]["producer"]["user_id"] = "foreign-owner"
    response = real_http_harness.client.post("/api/get_citation", json=foreign)
    assert response.status_code == 403
    case.fixture.denied.add("document-1")
    response = real_http_harness.client.post("/api/get_citation", json=body)
    assert response.status_code in (403, 404) and "native_annotation" not in response.json


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
