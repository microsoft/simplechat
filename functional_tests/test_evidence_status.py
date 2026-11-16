# test_evidence_status.py
"""Functional tests for authoritative, sanitized per-answer evidence status.

Version: 0.261.389
Implemented in: 0.261.388

These tests never infer missing facts from absent citations or model wording.
"""

import json
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys

import pytest
from flask import Flask, copy_current_request_context, g, has_request_context, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_evidence_status import append_export_evidence_notice, build_mixed_source_evidence_status


def build(status="completed", count=1, *, authorized=True, terminal=True):
    source = {
        "document_id": "selected-document", "display_name": "Selected guide",
        "authorization_status": "authorized" if authorized else "unresolved",
        "password": "private-secret",
    }
    envelope = {
        "document_id": source["document_id"],
        "coverage": {"terminal": terminal, "result_count": count},
        "evidence": [{"text": "source excerpt"}] if type(count) is int and count > 0 else [],
        "error": "private provider failure",
    }
    return build_mixed_source_evidence_status(
        [source], [{"status": status}], [envelope],
    )


def test_zero_terminal_search_results_are_missing_not_an_exhaustive_corpus_claim():
    result = build(count=0, status="partial")
    assert result["state"] == "missing"
    assert result["scope"] == "returned_evidence"
    assert result["sources"][0]["evidence_count"] == 0
    assert result["suggestions"]


@pytest.mark.parametrize("status", ["failed", "skipped", "canceled"])
def test_failed_or_unread_sources_are_not_evidence_of_absence(status):
    result = build(count=0, status=status)
    assert result["state"] == "unavailable"
    assert result["sources"][0]["state"] == "unavailable"


def test_pending_work_is_not_reported_as_missing():
    result = build(count=0, status="pending", terminal=False)
    assert result["state"] == "pending"


@pytest.mark.parametrize("count", [None, False, "0", -1])
def test_invalid_or_unknown_counts_do_not_create_a_missing_evidence_claim(count):
    result = build(count=count)
    assert result["state"] == "unknown"
    assert "evidence_count" not in result["sources"][0]


def test_unauthorized_source_names_ids_and_provider_error_details_are_not_projected():
    result = build(authorized=False)
    rendered = json.dumps(result)
    assert "Selected guide" not in rendered
    assert "selected-document" not in rendered
    assert "private" not in rendered
    assert result["sources"][0]["name"] == "Unavailable selected source 1"


def test_available_evidence_and_unavailable_required_source_remain_partial():
    manifest = [
        {"document_id": "a", "display_name": "A", "authorization_status": "authorized"},
        {"document_id": "b", "display_name": "B", "authorization_status": "authorized"},
    ]
    result = build_mixed_source_evidence_status(
        manifest, [{"status": "completed"}, {"status": "failed"}],
        [{"document_id": "a", "coverage": {"terminal": True, "result_count": 1}}],
        partial=True,
    )
    assert result["state"] == "partial"
    assert [source["state"] for source in result["sources"]] == ["complete", "unavailable"]


def test_ambiguous_source_matches_do_not_borrow_another_scopes_counts():
    result = build_mixed_source_evidence_status(
        [{"document_id": "a", "authorization_status": "authorized"}],
        [{"status": "completed"}],
        [{"document_id": "a", "coverage": {"terminal": True, "result_count": 0}}] * 2,
    )
    assert result["state"] == "unknown"


def test_an_incomplete_ledger_cannot_silently_hide_a_source():
    with pytest.raises(ValueError):
        build_mixed_source_evidence_status([{"document_id": "a"}], [], [])


def test_general_chat_with_no_source_manifest_has_no_evidence_banner():
    result = build_mixed_source_evidence_status([], [], [])
    assert result is None


def test_export_preserves_a_static_material_notice_without_private_labels_or_duplicate_copy_text():
    message = {"role": "assistant", "metadata": {"evidence_status": build(count=0)}}
    exported = append_export_evidence_notice("The fact was not found.", message)
    assert exported.endswith("Evidence: No supporting document evidence returned.")
    repeated = append_export_evidence_notice(exported, message)
    assert repeated == exported
    assert "Selected guide" not in exported
    masked = append_export_evidence_notice("[masked]", message)
    assert masked == "[masked]"
    safety = append_export_evidence_notice("Blocked.", {**message, "role": "safety"})
    assert safety == "Blocked."


def test_stream_worker_metadata_is_bound_to_the_exact_answer_and_v2_request():
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_chats.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"_chat_coverage_presentation", "_record_chat_evidence_status", "_chat_evidence_metadata"}
    namespace = {"g": g, "request": request, "has_request_context": has_request_context, "deepcopy": deepcopy}
    exec(compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
                            type_ignores=[]), str(source), "exec"), namespace)
    app = Flask(__name__)
    expected = build(count=0, status="partial")
    with app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        @copy_current_request_context
        def worker():
            namespace["_record_chat_evidence_status"]({"evidence_status": expected}, "conversation", "answer")
            return (namespace["_chat_evidence_metadata"]("conversation", "answer"),
                    namespace["_chat_evidence_metadata"]("other-conversation", "answer"),
                    namespace["_chat_evidence_metadata"]("conversation", "another-answer"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            matched, other_conversation, other_answer = executor.submit(worker).result()
    assert matched["evidence_status"] == expected
    assert other_conversation == {} and other_answer == {}
    with app.test_request_context():
        namespace["_record_chat_evidence_status"]({"evidence_status": expected}, "conversation", "answer")
        classic = namespace["_chat_evidence_metadata"]("conversation", "answer")
    assert classic == {}
