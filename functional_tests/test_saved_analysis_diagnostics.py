# test_saved_analysis_diagnostics.py
"""
Explicit, bounded, source-authorized saved Analyze diagnostic audit reads.
Version: 0.261.109
Implemented in: 0.261.109

Use the real shared Cosmos/Blob store and saved readers with SDK doubles.
Diagnostics remain separate from accepted values, reports and model input.
"""

from copy import deepcopy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from test_saved_analysis_store_integration import (
    SOURCE, analysis_result, authorize_run, resolve_sources, save_chat,
    save_orchestration, sdk_store, saved,
)
from test_workflow_result_contract import (
    RUN_ID, TASK, WORKFLOW, build_workflow_task_result, workflow_result_summary,
)


def diagnostic_result(*, status="valid", execution="succeeded"):
    result = analysis_result(count=2, validation=status)
    result["execution_status"] = execution
    result["analysis_result"]["raw_analysis_items"] = [{
        "text": "AUDIT-ONLY-RAW-START " + '\u03bb\\"' * 15000 + " AUDIT-ONLY-RAW-END",
        "reported_value": 99998765,
    }]
    return result


def chat_diagnostics(store, **options):
    descriptor, readers = save_chat(store, diagnostic_result(**options))
    return saved.saved_analysis_context(descriptor), readers


def page_reader(store, calls=None, after_read=None):
    def read(user_id, binding, reference, *, offset, limit, **kwargs):
        if calls is not None:
            calls.append((deepcopy(binding), dict(reference), offset, limit))
        if binding["kind"] == "chat":
            page = store.read_chat_page(
                binding["user_id"], binding["conversation_id"], binding["message_id"],
                reference, offset=offset, limit=limit,
            )
        elif binding["kind"] == "orchestration":
            page = store.read_orchestration_page(
                binding["user_id"], binding["conversation_id"], binding["run_id"], binding["step_id"],
                reference, offset=offset, limit=limit,
            )
        else:
            page = store.read_page(WORKFLOW, binding["run_id"], binding["task_id"], reference, offset=offset, limit=limit)
        if after_read:
            after_read()
        return page
    return read


def test_diagnostic_byte_pages_reconstruct_the_exact_separate_audit(sdk_store):
    context, options = chat_diagnostics(sdk_store)
    calls = []
    pages = []
    offset = 0
    while True:
        page = saved.read_saved_analysis_page(
            "owner", context, representation="diagnostics", offset=offset, limit=4096,
            diagnostics_page_reader=page_reader(sdk_store, calls), **options,
        )
        pages.append(page)
        assert page["audit_only"] is True and page["canonical_model_input"] is False
        assert page["representation"] == page["output_name"] == "diagnostics"
        assert page["result_sha256"] == context["result_sha256"]
        assert page["transport"]["offset_unit"] == "bytes"
        assert page["transport"]["complete_means"] == "end_of_section"
        assert len(page["content"].encode("ascii")) <= 4096
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert len(pages) > 1
    content = "".join(page["content"] for page in pages)
    assert hashlib.sha256(content.encode("ascii")).hexdigest() == pages[0]["sha256"]
    section = json.loads(content)
    assert section["kind"] == section["output_name"] == "diagnostics"
    assert "AUDIT-ONLY-RAW-START" in section["value"]["analysis"]["raw_analysis_items"][0]["text"]
    assert "AUDIT-ONLY-RAW-END" in content
    assert section["value"]["analysis"]["raw_analysis_items"][0]["reported_value"] == 99998765
    manifest, _, _ = saved.load_saved_analysis("owner", context, **options)
    assert {reference["sha256"] for _, reference, _, _ in calls} == {manifest["outputs"]["diagnostics"]["result_ref"]["sha256"]}
    with pytest.raises(json.JSONDecodeError):
        json.loads(pages[0]["content"])
    assert pages[-1]["complete"] is True
    assert pages[-1]["integrity"]["full_sha256_verified"] is False


def test_default_records_and_model_input_never_include_the_diagnostic_audit(sdk_store):
    context, options = chat_diagnostics(sdk_store)
    records = saved.read_saved_analysis_page("owner", context, **options)
    prompt, _ = saved.load_saved_analysis_input("owner", context, **options)
    assert "AUDIT-ONLY" not in json.dumps(records) + prompt
    assert "99998765" not in json.dumps(records) + prompt
    assert records["total_records"] == 2


@pytest.mark.parametrize("status,execution", [("invalid", "failed"), ("pending", "pending"), ("partial", "incomplete")])
def test_unfinished_or_invalid_results_can_be_audited_without_becoming_final_data(sdk_store, status, execution):
    context, options = chat_diagnostics(sdk_store, status=status, execution=execution)
    audit = saved.read_saved_analysis_diagnostics(
        "owner", context, page_reader=page_reader(sdk_store), **options,
    )
    assert audit["audit_only"] is True and audit["canonical_model_input"] is False
    if status != "partial":
        with pytest.raises(ValueError):
            saved.load_saved_analysis_input("owner", context, **options)


def test_revocation_blocks_each_diagnostic_read_before_transport(sdk_store):
    context, options = chat_diagnostics(sdk_store)
    calls = []
    options["source_resolver"] = lambda *args, **kwargs: [{**SOURCE, "authorization_status": "unresolved"}]
    with pytest.raises(PermissionError):
        saved.read_saved_analysis_diagnostics(
            "owner", context, page_reader=page_reader(sdk_store, calls), **options,
        )
    assert calls == []


def test_access_loss_during_transport_returns_no_diagnostic_page(sdk_store):
    context, options = chat_diagnostics(sdk_store)
    state = {"allowed": True}
    options["source_resolver"] = lambda *args, **kwargs: [{
        **SOURCE, "authorization_status": "authorized" if state["allowed"] else "unresolved",
    }]
    with pytest.raises(PermissionError):
        saved.read_saved_analysis_diagnostics(
            "owner", context,
            page_reader=page_reader(sdk_store, after_read=lambda: state.update(allowed=False)), **options,
        )


def test_stale_digest_and_masking_block_audit_transport(sdk_store):
    context, options = chat_diagnostics(sdk_store)
    calls = []
    with pytest.raises(ValueError):
        saved.read_saved_analysis_diagnostics(
            "owner", {**context, "result_sha256": "0" * 64},
            page_reader=page_reader(sdk_store, calls), **options,
        )
    message = options["message_loader"]()
    message["metadata"]["masked"] = True
    options["message_loader"] = lambda *args: message
    with pytest.raises(PermissionError):
        saved.read_saved_analysis_diagnostics(
            "owner", context, page_reader=page_reader(sdk_store, calls), **options,
        )
    assert calls == []


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, 65537), (True, 10), (0, True)])
def test_invalid_diagnostic_byte_limits_do_not_read_storage(sdk_store, offset, limit):
    context, options = chat_diagnostics(sdk_store)
    options["message_loader"] = lambda *args: pytest.fail("Reject invalid byte ranges before data access.")
    with pytest.raises(ValueError):
        saved.read_saved_analysis_diagnostics(
            "owner", context, offset=offset, limit=limit, page_reader=page_reader(sdk_store), **options,
        )


def test_orchestration_bound_audit_uses_the_same_authorized_reader(sdk_store):
    descriptor = save_orchestration(sdk_store, diagnostic_result())
    descriptor = {**descriptor, "message_id": "assistant-1"}
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": descriptor},
    }
    page = saved.read_saved_analysis_diagnostics(
        "owner", saved.saved_analysis_context(descriptor), limit=1024,
        message_loader=lambda *args: message, orchestration_authorizer=authorize_run,
        orchestration_loader=sdk_store.load_orchestration, source_resolver=resolve_sources,
        page_reader=page_reader(sdk_store),
    )
    assert page["output_name"] == "diagnostics"
    assert page["canonical_model_input"] is False


def test_workflow_bound_audit_does_not_materialize_canonical_records(sdk_store):
    envelope = build_workflow_task_result(
        diagnostic_result(), workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
    )
    manifest, reference = saved.persist_result_sections(
        envelope, lambda section: sdk_store.save(WORKFLOW, RUN_ID, TASK["id"], section),
    )
    summary = workflow_result_summary(manifest, reference)
    descriptor = saved.workflow_saved_analysis_descriptor(
        summary, WORKFLOW, conversation_id="conversation-1", message_id="assistant-1",
    )
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": descriptor},
    }
    calls = []
    page = saved.read_saved_analysis_diagnostics(
        "owner", saved.saved_analysis_context(descriptor), limit=1024,
        message_loader=lambda *args: message, workflow_getter=lambda *args: WORKFLOW,
        workflow_loader=sdk_store.load, source_resolver=resolve_sources,
        page_reader=page_reader(sdk_store, calls),
    )
    assert page["output_name"] == "diagnostics"
    assert calls[0][1] == manifest["outputs"]["diagnostics"]["result_ref"]


def test_default_diagnostic_transport_reuses_the_shared_chat_byte_reader(sdk_store, monkeypatch):
    context, options = chat_diagnostics(sdk_store)
    calls = []

    def read_chat(*args, **kwargs):
        calls.append(args)
        return sdk_store.read_chat_page(*args, **kwargs)

    monkeypatch.setitem(sys.modules, "functions_workflow_result_store", SimpleNamespace(
        read_chat_analysis_result_page=read_chat,
        read_orchestration_analysis_result_page=lambda *args, **kwargs: pytest.fail("Wrong producer."),
        read_workflow_task_result_page=lambda *args, **kwargs: pytest.fail("Wrong producer."),
    ))
    page = saved.read_saved_analysis_diagnostics("owner", context, limit=1024, **options)
    assert calls[0][:3] == ("owner", "conversation-1", "assistant-1")
    assert len(page["content"]) == 1024
