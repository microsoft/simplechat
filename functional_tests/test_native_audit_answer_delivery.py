# test_native_audit_answer_delivery.py
"""Selected-file native audits through Auto routing, checked correction and delivery.

Version: 0.261.425
Implemented in: 0.261.425
Only external storage/configuration and provider replies are isolated. Real
ownership, native readers, routing, retention, checking and publication execute.
"""

import hashlib
import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent

from functions_model_catalog import find_profile
from functions_native_audit import NATIVE_AUDIT_ANSWER_VERSION, NATIVE_AUDIT_VERSION, native_audit_contract
from test_native_document_fidelity_http import (
    inventory_store, modules, native_http, native_source, real_http_harness, source_runtime,
)
from test_orchestration_document_action_end_to_end import LEFT, TURN, action_proposal, frames
from test_native_inspection_request_contract import change_cursor
from test_support.versioning import assert_app_version_at_least


__all__ = ["inventory_store", "modules", "native_http", "native_source", "real_http_harness", "source_runtime"]
PROMPTS = {
    ".pdf": (
        "Inspect the selected PDF's native document title, author and keywords. Is it tagged? "
        "Identify supporting catalog or structure-tree evidence, not just selectable text. Review "
        "all visible content for appropriate semantic tags and logical reading order, citing page "
        "and element. Enumerate every image and chart, its Figure tag and exact native alt text, "
        "or whether it is appropriately marked as an artifact/decorative. Identify omitted content, "
        "wrong tag types, missing alternatives and reading-order defects. Distinguish native alt "
        "text from an AI-generated description. State exactly which native structures you cannot "
        "access. Do not infer compliance or tagged status from appearance. Use only the selected "
        "file. Separate native file evidence from visual inference. Distinguish a property absent "
        "in the source from a property inaccessible to this chat. Do not invent unavailable "
        "information; cite the source location for each finding."
    ),
    ".xlsx": (
        "Inspect the workbook's native file properties: Document Title, Author and keywords/tags. "
        "Do not substitute the filename or an AI-generated title. Inventory every image, chart and "
        "actual form/checkbox control with worksheet, location, object type, exact native alt text "
        "and explicit decorative state where available. Distinguish a Boolean cell or drawn shape "
        "from a real checkbox. Describe fonts, sizes, bold/color/fill, merged cells, frozen panes "
        "and layout, including Budget!B4. Report actual print headers and footers on every sheet, "
        "distinguishing them from cell content and resolving page fields only when possible. State "
        "inaccessible fields explicitly. Use only the selected file. Separate native file evidence "
        "from visual inference. Distinguish a property absent in the source from a property "
        "inaccessible to this chat. Do not invent unavailable information; cite the source location "
        "for each finding."
    ),
    ".pptx": (
        "Inspect the presentation's native Document Title, Author and keywords/tags, not the "
        "filename or an inferred title. Inventory each image, chart, shape and form control by slide "
        "and object type. Give exact native alt text and explicit decorative marking; distinguish "
        "a visual description from stored alt text and a drawn shape from an interactive control. "
        "Describe font family/size/weight/color, layout and contrast issues. Report headers, footers, "
        "slide numbers and master-derived content separately from slide body text; distinguish slide "
        "content from notes/handout headers where applicable. Explain what you cannot inspect. Use "
        "only the selected file. Separate native file evidence from visual inference. Distinguish "
        "a property absent in the source from a property inaccessible to this chat. Do not invent "
        "unavailable information; cite the source location for each finding."
    ),
}
SOURCES = [
    "SC-C03.pdf", "SC-C04.pdf", "SC-C05.pdf", "SC-C08.xlsx",
    "SC-C11.xlsx", "SC-C09-R3.pptx", "SC-C10-R3.pptx",
]


def test_native_audit_delivery_version():
    assert_app_version_at_least("0.261.425")


@pytest.fixture
def delivery(native_http, native_source, inventory_store, monkeypatch, name):
    state = native_http
    runtime, harness = state.runtime, state.runtime.harness
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    path = native_source(name)
    data = path.read_bytes()
    documents = harness.config.cosmos_user_documents_container
    document = documents.read_item(LEFT, LEFT)
    document.update({
        "file_name": name, "blob_path": "synthetic-retained-source/" + name,
        "source_file_available": True, "enhanced_citations": True,
        "accessibility_metadata": {"format": path.suffix[1:], "schema_version": "1.0"},
    })
    documents.upsert_item(document)
    harness.blobs.records[(document["blob_container"], document["blob_path"])] = {
        "data": data, "metadata": {"document_id": LEFT}, "etag": "native-source-etag",
    }
    downloads = []

    def download(container, blob_path, current):
        downloads.append(current["id"])
        return data

    monkeypatch.setattr(importlib.import_module("content_screening.access"), "_download_available_blob", download)
    if path.suffix == ".xlsx":
        monkeypatch.setattr(
            importlib.import_module("functions_search_service"), "ScreeningStorage",
            lambda **kwargs: inventory_store[0],
        )
    profile = find_profile(harness.settings["gpt_model"]["selected"][0], harness.settings)
    assert profile is not None
    candidates = [{
        "key": "legacy:aoai:gpt-4o", "label": "Native audit model",
        "selection": {"model_deployment": "gpt-4o", "model_provider": "aoai"},
        "profile": profile, "capabilities": profile["capabilities"], "effective_revision": None,
    }]
    # This is the external authorized-connection inventory, not routing or binding validation.
    monkeypatch.setattr(harness.planner, "authorized_routing_candidates", lambda *args, **kwargs: deepcopy(candidates))
    result = SimpleNamespace(
        state=state, runtime=runtime, harness=harness, path=path, name=name,
        request=PROMPTS[path.suffix], downloads=downloads, contract=None, executions=[],
        candidate_payloads=[], original_fact_digests=[], execution_frames=[], raw_facts={}, retained_facts={},
    )
    prepare = harness.execution.prepare_harness_execution

    def observe_execution(*args, **kwargs):
        execution = prepare(*args, **kwargs)
        result.executions.append(execution)
        execute = execution.execute

        def observe_frames(*frame_args, **frame_kwargs):
            for frame in execute(*frame_args, **frame_kwargs):
                if frame.startswith("data:"):
                    result.execution_frames.append(json.loads(frame.partition("data:")[2]))
                yield frame

        execution.execute = observe_frames
        return execution

    monkeypatch.setattr(harness.execution, "prepare_harness_execution", observe_execution)
    original_reply = AzureChatCompletion._inner_get_chat_message_contents

    async def native_reply(self, history, settings):
        replies = await original_reply(self, history, settings)
        if len(state.native_calls) == 1:
            for reply in replies:
                for item in reply.items:
                    if isinstance(item, FunctionCallContent):
                        item.arguments = json.dumps({
                            **json.loads(item.arguments), "native_section": "all",
                            "sections": "accessibility,style,issues", "native_page_size": 200,
                            **({"sheet_name": "Budget", "cell_range": "B4:D5"} if path.suffix == ".xlsx" else {}),
                        })
            return replies
        values = [
            item.result for message in history.messages for item in message.items if hasattr(item, "result")
        ]
        value = values[-1]
        value = json.loads(value) if isinstance(value, str) else value
        audit = value["native_audit"]
        result.raw_facts.update({fact["id"]: deepcopy(fact) for fact in audit["facts"]})
        result.original_fact_digests.extend((fact["id"], fact["value_sha256"]) for fact in audit["facts"])
        page = (value.get("native_inspection") or value.get("excel_inspection"))["page"]
        if page["has_more"]:
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[FunctionCallContent(
                id=f"native-page-{len(state.native_calls)}",
                name="document_search-get_document_accessibility_report",
                arguments=json.dumps({
                    "document_id": LEFT, "doc_scope": "personal", "native_section": "all",
                    "sections": "accessibility,style,issues", "native_page_size": 200,
                    "native_cursor": page["next_cursor"],
                }),
            )])]
        return replies

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", native_reply)
    return result


def current_payload(delivery):
    return json.loads(delivery.harness.model_calls[-1]["messages"][-1]["content"])


def customer_answer(contract, name):
    facts, citation = contract["facts"], contract["citations"][0]

    def records(fields):
        return "\n".join(
            f"- {fact['location']}: {fact['field']} ({fact['state']}) = "
            f"{json.dumps(fact['value'], ensure_ascii=True)}"
            for fact in facts if fact["field"] in fields
        )

    sections = [
        "## Audit findings",
        "### Native document properties\n" + records({"title", "author", "keywords"}) + "\n" + citation,
    ]
    if name.endswith(".pdf"):
        catalog = next(fact["value"] for fact in facts if fact["field"] == "catalog_and_tagged_state")
        tagged = catalog["is_tagged"] is True and catalog["has_struct_tree"] is True
        order = [
            fact["value"]["text"].strip() for fact in facts
            if fact["field"] == "logical_element" and isinstance(fact["value"].get("text"), str)
            and fact["value"]["text"].strip().startswith("Step ")
        ]
        tagging = (
            "Tagged: yes. The catalog and structure-tree records support native tagging."
            if tagged else "Tagged: no. Raw marked content does not establish a logical structure tree."
        )
        order_text = "Native step order: " + " then ".join(order) if order else "Native logical order cannot be established."
        sections.extend([
            "### Tags, logical reading order and omitted content\n" + tagging + "\n" + order_text + "\n"
            + records({"catalog_and_tagged_state", "logical_element", "unmarked_text", "native_table"})
            + "\nThese are native bindings, not inferred visual order.\n" + citation,
            "### Images, charts and footer artifacts\n"
            + records({"observed_graphics", "native_graphic", "alt", "artifact_text", "type", "subtype"})
            + "\nNative alternatives are distinct from AI-generated descriptions.\n" + citation,
            "### Supported defects\n" + records({"reported_issue"}) + "\n" + citation,
        ])
    else:
        objects = [fact for fact in facts if fact["field"] == "native_object"]
        controls = [
            fact for fact in objects if fact["value"].get("control_representation") == "in_cell"
        ]
        inventory_summary = f"{len(objects)} supported native objects were returned. "
        if name.endswith(".xlsx"):
            inventory_summary += (
                "The returned native control inventory binds the checked checkbox to Budget!D3; "
                "D4/D5 values alone are not checkbox bindings."
                if controls else
                "No supported native checkbox binding was returned; a Boolean alone is not a control."
            )
        else:
            decorative = [fact["value"]["name"] for fact in objects if fact["value"].get("is_decorative") is True]
            inventory_summary += "Explicit decorative objects: " + ", ".join(decorative) + "."
        sections.extend([
            "### Object inventory, alternatives and decorative states\n" + inventory_summary + "\n"
            + records({"native_object", "description", "title", "decorative", "inventory_section_counts"})
            + "\nA Boolean or ordinary shape alone does not establish an interactive checkbox.\n" + citation,
            "### Formatting, layout and print or placeholder content\n"
            + records({"text_style", "saved_cell_style", "saved_cell_record", "saved_layout_and_print", "reported_issue"})
            + "\nSlide-local placeholder content is not automatically master-derived. "
            "Saved print expressions are distinct from cell content; physical page fields are not recalculated.\n" + citation,
        ])
    sections.append(
        "### What cannot be established\n"
        "That information is not in the data provided for rendered visibility, unsupported native "
        "structures or a full conformance assessment. This is what the supported native inspection "
        "found to answer your questions; it is not WCAG or PDF/UA certification. "
        "Absent means not stored in the inspected source; present_empty means a stored blank; "
        "inaccessible means this inspection cannot establish the value. "
        "Native solid-color contrast is not a full rendered-background assessment."
    )
    return "\n\n".join(sections)


def prepared_reply(delivery, *, brief=False, forged=False, invalid_hash=False, reference_only=False):
    payload = current_payload(delivery)
    contract = payload.get("native_audit_contract") or payload["evidence"]["native_audit_contract"]
    delivery.contract = contract
    for entry in payload.get("inputs", {}).values():
        value = entry.get("value") or {}
        for citation in value.get("citations", []):
            audit = (citation.get("function_result") or {}).get("native_audit") or {}
            delivery.retained_facts.update({fact["id"]: fact for fact in audit.get("facts", [])})
    answer = (
        "## Audit findings\nThe source was inspected."
        if brief else customer_answer(contract, delivery.name)
    )
    if forged:
        delivery.forged_claim = (
            "An absent description is stored as an empty string in the native source."
            if delivery.name.endswith(".xlsx") else
            "The decorative ellipse is absent and all footers are master-derived."
            if delivery.name.endswith(".pptx") else
            "The native logical order is Step 1 BEFORE Step 2."
        )
        answer = "## Audit findings\n" + delivery.forged_claim
    reply = {
        "native_claims": {
            "scope": "all_returned",
            "fact_set_sha256": "0" * 64 if invalid_hash else contract["fact_set_sha256"],
        },
        "answer": answer,
    }
    if reference_only:
        reply.pop("answer")
    return json.dumps(reply)


def assessment_reply(delivery, *, status="satisfied"):
    payload = current_payload(delivery)
    delivery.candidate_payloads.append(payload)
    assert payload["contract"]["native_answer_version"] == NATIVE_AUDIT_ANSWER_VERSION
    assert payload["evidence"]["native_audit_contract"]["fact_set_sha256"] == delivery.contract["fact_set_sha256"]
    assert payload["candidate"].startswith("## Audit findings")
    assert payload["candidate"].count("## Native file evidence") == 1
    requirements = {
        item["id"]: {
            "status": status if index == 0 else "satisfied",
            "reason": "The requested interpretation is missing or contradicts native facts." if status != "satisfied" and index == 0 else "",
            "evidence_refs": ["native_audit_contract"],
            "answer_quote": "" if status != "satisfied" and index == 0 else "## Audit findings",
        }
        for index, item in enumerate(payload["previous_requirements"])
    }
    return json.dumps({"requirements": requirements})


def submit(delivery, replies):
    proposal = action_proposal((LEFT,), action=delivery.state.action)
    proposal["steps"][0]["arguments"]["task"] = delivery.request
    proposal["steps"][1]["arguments"]["instruction"] = delivery.request
    delivery.harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": delivery.request, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal), *replies,
    ]
    response = delivery.runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": TURN, "message": delivery.request,
        "planning_submission_id": "native-answer-delivery", "approval_mode": "auto",
        "model_routing": "auto", "selected_document_ids": [LEFT],
    }, buffered=True)
    events = frames(response)
    plans = [event["plan"] for event in events if event.get("type") == "orchestration_plan"]
    assert plans, events
    plan = plans[-1]
    delivery.harness.run_id = plan["run_id"]
    return delivery.harness.read(), events


@pytest.mark.parametrize("name", SOURCES)
def test_selected_file_auto_audit_delivers_supported_answers_and_honest_limits(delivery, name):
    saved, events = submit(delivery, [
        lambda: prepared_reply(delivery),
        lambda: assessment_reply(delivery),
    ])
    answers = delivery.harness.assistant_messages()
    assert saved["status"] == "completed", (saved.get("failure"), delivery.state.failures, events[-3:])
    assert saved["plan"]["model_routing"] == "auto"
    assert {step["capability_id"] for step in saved["plan"]["steps"]} == {"action_invoke", "compose"}
    assert all(step["model_binding"]["profile_id"] for step in saved["plan"]["steps"])
    assert saved["plan"]["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert len(answers) == 1
    text = answers[0]["content"]
    assert text.startswith("## Audit findings") and "### What cannot be established" in text
    assert "That information is not in the data provided" in text
    assert "The request was only partially completed" not in text
    assert "The request could not be completed" not in text
    assert text.count("## Native file evidence") == 1
    assert delivery.downloads and set(delivery.downloads) == {LEFT}
    changed = [
        {
            "field": fact["field"], "location": fact["location"],
            "raw": delivery.raw_facts.get(fact["id"], {}).get("value"),
            "retained": delivery.retained_facts.get(fact["id"], {}).get("value"),
        }
        for fact in delivery.contract["facts"] if fact["reason"] == "transport_value_changed"
    ]
    assert not changed, changed
    retained_digests = {(fact["id"], fact["value_sha256"]) for fact in delivery.contract["facts"]}
    assert set(delivery.original_fact_digests) <= retained_digests
    assert answers[0]["agent_citations"]
    assert any(event.get("server_managed") is True for event in events)
    assert any(event.get("full_content") == text for event in delivery.execution_frames)
    if name == "SC-C04.pdf":
        assert text.index("Step 2: release") < text.index("Step 1: approve")
        assert "PDF_NO_HEADINGS" in text and "unmarked_text" in text
    if name.endswith(".pdf"):
        assert ("Tagged: no." if name == "SC-C05.pdf" else "Tagged: yes.") in text
    if name == "SC-C11.xlsx":
        assert "Budget!B4" in text and "15000" in text
        assert "checkbox" in text and "D3" in text and "absent" in text
    if name.endswith(".pptx"):
        objects = [fact for fact in delivery.contract["facts"] if fact["field"] == "native_object"]
        assert {str(fact["value"]["object_id"]) for fact in objects} == {str(number) for number in range(2, 10)}
        assert len(objects) == 8
    elif name.endswith(".xlsx"):
        assert sum(fact["field"] == "native_object" for fact in delivery.contract["facts"]) == (
            3 if name == "SC-C11.xlsx" else 2
        )
    if name == "SC-C10-R3.pptx":
        assert "Decorative teal ellipse" in text and "present_empty" in text
        assert "#E8E8E8" in text and "#FCFAF6" in text and "1.18" in text


@pytest.mark.parametrize("name", ["SC-C03.pdf", "SC-C10-R3.pptx", "SC-C11.xlsx"])
@pytest.mark.parametrize("initial", ["brief", "forged", "invalid_hash", "reference_only"])
def test_native_audit_correction_can_change_explanation_without_changing_facts(delivery, name, initial):
    first = lambda: prepared_reply(
        delivery, brief=initial == "brief", forged=initial == "forged",
        invalid_hash=initial == "invalid_hash", reference_only=initial == "reference_only",
    )
    replies = [first]
    if initial not in ("invalid_hash", "reference_only"):
        replies.append(lambda: assessment_reply(delivery, status="unsupported" if initial == "forged" else "missing"))
    replies.extend([lambda: prepared_reply(delivery), lambda: assessment_reply(delivery)])
    saved, _ = submit(delivery, replies)
    assert saved["status"] == "completed", (saved.get("failure"), delivery.state.failures)
    steps = delivery.harness.run_store.list_run_steps(saved["id"], "owner", "conversation-1")
    assert steps[1]["task_completeness"]["corrections"] == 1
    text = delivery.harness.assistant_messages()[0]["content"]
    assert "### What cannot be established" in text
    assert "Step 1 BEFORE Step 2" not in text
    if initial == "forged":
        assert delivery.forged_claim not in text
    assert text.count("## Native file evidence") == 1
    assert delivery.harness.replies == []


@pytest.mark.parametrize("name", ["SC-C04.pdf"])
@pytest.mark.parametrize("legacy_checkpoint", [False, True])
def test_explicit_native_check_retry_reuses_gathered_source_without_repeating_reads(delivery, monkeypatch, name, legacy_checkpoint):
    original, _ = submit(delivery, [
        lambda: prepared_reply(delivery), '{"requirements":[]}', '{"requirements":[]}',
    ])
    assert original["status"] == "failed"
    assert original["failure"]["code"] == "completeness_unavailable"
    assert delivery.executions
    harness = delivery.harness
    execution = delivery.executions[0]
    if legacy_checkpoint:
        store_type = type(execution.context.completeness_store)
        original_load = store_type.load_completeness

        def load_legacy(store, step_id, *, binding):
            state = original_load(store, step_id, binding=binding)
            if state is not None and store.identity["run_id"] == original["id"]:
                state.pop("native_audit_preparation", None)
            return state

        monkeypatch.setattr(store_type, "load_completeness", load_legacy)

    retry = delivery.runtime.client.post(f"/api/v2/orchestration/runs/{original['id']}/retry", json={
        "conversation_id": "conversation-1", "expected_version": original["recovery_version"],
        "submission_id": "native-check-retry",
    })
    retry_payload = retry.get_json()
    assert retry.status_code == 200, retry_payload
    child_id = retry_payload["run"]["run_id"]
    child_record = harness.runs.read_item(child_id, "conversation-1")
    before_reads, before_calls = len(delivery.downloads), len(harness.model_calls)
    harness.run_id = child_id
    harness.replies = [
        *([lambda: prepared_reply(delivery)] if legacy_checkpoint else []),
        lambda: assessment_reply(delivery),
    ]
    response = delivery.runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": child_id,
        "expected_version": child_record["edit_version"],
    }, buffered=True)
    events = frames(response)
    saved = harness.read()
    assert response.status_code == 200, (response.get_json(silent=True), events)
    assert saved["status"] == "completed", (saved.get("failure"), delivery.state.failures, events[-2:])
    assert len(delivery.downloads) == before_reads
    assert len(harness.model_calls) == before_calls + (2 if legacy_checkpoint else 1)
    assert harness.replies == []


@pytest.mark.parametrize("name", ["SC-C08.xlsx", "SC-C11.xlsx"])
def test_native_fact_transport_preserves_values_without_relaxing_redaction_or_global_depth(delivery, name):
    saved, _ = submit(delivery, [
        lambda: prepared_reply(delivery), lambda: assessment_reply(delivery),
    ])
    assert saved["status"] == "completed"
    sanitizer = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger").sanitize_plugin_invocation_value
    secret = "PRIVATE_NATIVE_SECRET_CANARY"
    value = {"api_key": secret, "saved_style": {"color": {"rgb": "112233"}}}
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    secret_fact = {
        "id": "f" * 24, "location": "Synthetic secret control", "field": "synthetic_secret",
        "state": "present_value", "value": value,
        "value_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "reason": None,
    }
    nested = {"ordinary": "deep value"}
    for _ in range(12):
        inner = {**secret_fact, "value": nested}
        inner["value_sha256"] = hashlib.sha256(json.dumps(
            nested, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        nested = {"native_audit": {
            "version": NATIVE_AUDIT_VERSION, "file_name": "nested.xlsx", "source_sha256": "a" * 64,
            "facts": [inner], "facts_omitted": False, "has_more": False,
        }}
    nested_fact = {
        **secret_fact, "id": "e" * 24, "field": "synthetic_nested", "value": nested,
        "value_sha256": hashlib.sha256(json.dumps(
            nested, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
    }
    audit = {
        "version": NATIVE_AUDIT_VERSION, "file_name": name,
        "source_sha256": hashlib.sha256(delivery.path.read_bytes()).hexdigest(),
        "facts": [*deepcopy(list(delivery.raw_facts.values())), nested_fact, secret_fact],
        "facts_omitted": False, "has_more": False,
    }
    citation = {
        "function_name": "get_document_accessibility_report",
        "function_result": {"document": {"id": LEFT}, "native_audit": audit},
    }
    ordinary = {"value": "unchanged"}
    for _ in range(12):
        ordinary = {"nested": ordinary}
    wrapped = {"responses": [{"messages": [{"agent_citations": [citation]}]}], "ordinary": ordinary}
    sanitized = sanitizer(wrapped)
    native_citation = sanitized["responses"][0]["messages"][0]["agent_citations"][0]
    transported = native_citation["function_result"]["native_audit"]
    assert secret not in json.dumps(sanitized)
    assert "[truncated: nested value too deep]" in json.dumps(sanitized["ordinary"])
    original_count = len(delivery.raw_facts)
    assert transported["facts"][:original_count] == audit["facts"][:original_count]
    assert "[truncated: nested value too deep]" in json.dumps(transported["facts"][original_count]["value"])
    assert transported["facts"][-1]["value"]["api_key"] == "***REDACTED***"
    assert transported["facts"][-1]["value_sha256"] == secret_fact["value_sha256"]
    contract = native_audit_contract({"native": {"value": {
        "capability_id": "action_invoke", "citations": [native_citation],
    }}})
    redacted = next(fact for fact in contract["facts"] if fact["id"] == secret_fact["id"])
    assert redacted["state"] == "inaccessible" and redacted["value"] is None
    assert redacted["reason"] == "transport_value_changed"


@pytest.mark.parametrize("name", ["SC-C04.pdf"])
def test_second_native_read_failure_has_safe_correlated_cursor_diagnostics(delivery, monkeypatch, caplog, name):
    delivery.harness.settings["enable_debug_logging"] = True
    original_reply = AzureChatCompletion._inner_get_chat_message_contents
    supplied = []

    async def changed_cursor(self, history, settings):
        replies = await original_reply(self, history, settings)
        if len(delivery.state.native_calls) == 2:
            for reply in replies:
                for item in reply.items:
                    if isinstance(item, FunctionCallContent):
                        arguments = json.loads(item.arguments)
                        arguments["native_cursor"] = change_cursor(
                            arguments["native_cursor"], source_sha256="0" * 64,
                        )
                        supplied.append(arguments["native_cursor"])
                        item.arguments = json.dumps(arguments)
        return replies

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", changed_cursor)
    with caplog.at_level("INFO", logger=delivery.state.logger.name):
        saved, _ = submit(delivery, [])
    assert saved["status"] == "failed"
    assert saved["failure"]["code"] == "document_action_read_failed"
    reads = [
        record for record in caplog.records
        if getattr(record, "sc_message", None) == "[ORCHESTRATION_ADAPTERS] Document action read checkpoint."
    ]
    assert [record.sc_outcome for record in reads] == ["started", "completed", "started", "failed"]
    assert reads[-1].sc_validation_code == "native_cursor_source_changed"
    assert reads[-1].sc_validation_rule == "native_cursor_source_sha256_changed"
    assert reads[1].sc_next_native_cursor_hash != reads[2].sc_native_cursor_hash
    diagnostic = json.dumps([
        {key: value for key, value in record.__dict__.items() if key.startswith("sc_")}
        for record in reads
    ])
    assert supplied and supplied[0] not in diagnostic
    assert LEFT not in diagnostic and delivery.name not in diagnostic
    assert delivery.candidate_payloads == []


@pytest.mark.parametrize("name", ["SC-C11.xlsx"])
def test_unrepaired_false_native_claim_is_not_published_as_a_data_gap(delivery, name):
    saved, _ = submit(delivery, [
        lambda: prepared_reply(delivery, forged=True),
        lambda: assessment_reply(delivery, status="unsupported"),
        lambda: prepared_reply(delivery, forged=True),
    ])
    assert saved["status"] == "failed"
    assert saved["failure"]["code"] == "completeness_incomplete"
    assert not any(
        delivery.forged_claim in message["content"] for message in delivery.harness.assistant_messages()
    )


@pytest.mark.parametrize("name", ["SC-C03.pdf"])
def test_genuine_native_read_failure_is_not_reported_as_missing_source_data(delivery, name):
    delivery.state.fail_report = True
    saved, _ = submit(delivery, [])
    assert saved["status"] == "failed"
    assert saved["failure"]["code"] == "document_action_read_failed"
    text = delivery.harness.assistant_messages()[0]["content"]
    assert "could not" in text
    assert "That information is not in the data provided" not in text
