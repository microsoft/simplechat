#!/usr/bin/env python3
# test_orchestration_unfound_source_handling.py
"""
Functional test for orchestrator unfound source information handling and linked PDF page coverage.
Version: 0.261.384
Implemented in: 0.261.384

This test ensures that when a user asks a question about a linked PDF or document
and the searched content does not contain the requested information:
1. Source Review and url_fetch support linked PDFs (application/pdf), extracting
   text per page and reporting total pages and pages inspected.
2. Empty document_search / document_analyze inputs surface source_coverage to
   compose so page/window/excerpt coverage is available for the final answer.
3. Compose guidance and Task Completeness policies treat an evidence-backed
   "not found in the searched content" response (stating total pages, pages
   inspected, and what the content covers) as a completed answer rather than
   failing with completeness_incomplete.
"""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import fitz
import pytest

TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(APP_ROOT))

from test_orchestration_dependency_runtime import binding, compose, execute, runtime, source_input  # noqa: E402
from test_orchestration_harness_execution import harness, initialized_application  # noqa: E402
from test_support.orchestration_harness_execution import compose_step, input_binding  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _build_sample_manual_pdf_bytes(page_texts):
    document = fitz.open()
    try:
        document.set_metadata({"title": "Cycle Timer User Manual"})
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


def test_version_at_least_0_261_384():
    assert_app_version_at_least("0.261.384")


def test_source_review_extracts_pdf_pages_and_reports_page_coverage():
    from functions_source_review import (
        _compact_page_for_evidence,
        _is_supported_content_type,
        build_source_review_system_message,
        extract_source_review_evidence_from_pdf,
    )
    from functions_orchestration_adapters import _finalize_source_review
    from functions_orchestration_registry import CAPABILITY_URL_FETCH

    pdf_url = "https://manuals.plus/m/424434ca86b98b99896c17803f6de3f46f2c85dd399ceff15e8b769086f4b467_optim.pdf"
    assert _is_supported_content_type("application/pdf") is True
    assert _is_supported_content_type("application/octet-stream", url=pdf_url) is True

    pages = [
        "Page 1: Safety Instructions and Device Overview.",
        "Page 2: Program P1 alternates 30 seconds on and 30 seconds off.",
        "Page 3: Program P2 alternates 60 seconds on and 60 seconds off.",
        "Page 4: Program P3 runs continuously for 15 minutes.",
        "Page 5: Troubleshooting, Maintenance, and Specifications.",
    ]
    pdf_bytes = _build_sample_manual_pdf_bytes(pages)
    evidence = extract_source_review_evidence_from_pdf(
        pdf_bytes=pdf_bytes,
        url=pdf_url,
        user_message="Which program is 10 seconds on and 10 seconds off?",
    )

    assert evidence["status"] == "reviewed"
    assert evidence["content_type"] == "application/pdf"
    assert evidence["pdf_page_count"] == 5
    assert evidence["pdf_pages_inspected"] == 5
    assert evidence["pdf_pages_with_text"] == 5
    combined_excerpts = "\n".join(evidence["excerpts"])
    assert "PDF coverage: Inspected 5 of 5 total page(s)" in combined_excerpts
    for page_num in range(1, 6):
        assert f"[Page {page_num} of 5]" in combined_excerpts

    compacted = _compact_page_for_evidence(evidence)
    assert compacted["pdf_page_count"] == 5
    assert compacted["pdf_pages_inspected"] == 5

    review_result = {
        "enabled": True,
        "retrieved_at": "2026-10-26T16:00:00+00:00",
        "query": "Which program is 10 seconds on and 10 seconds off?",
        "coverage": {
            "pages_reviewed": 1,
            "pages_skipped": 0,
            "pdf_pages_total": 5,
            "pdf_pages_inspected": 5,
        },
        "pages": [compacted],
        "skipped": [],
        "citations": [{"url": pdf_url, "title": compacted["title"], "source": "source_review"}],
    }
    review_result["system_message"] = build_source_review_system_message(review_result)
    step_result = _finalize_source_review(
        review_result,
        capability_id=CAPABILITY_URL_FETCH,
        unavailable_summary="Reading linked pages is not available for this user.",
        empty_summary="No linked pages could be read.",
        found_summary="Read {count} linked page(s).",
    )

    assert step_result["status"] == "completed"
    assert "5 of 5 PDF page(s) inspected" in step_result["summary"]
    assert any("inspected 5 of 5 PDF page(s)" in note for note in step_result["notes"])


def test_url_fetch_skipped_link_populates_explanatory_note_for_compose():
    from functions_orchestration_adapters import _finalize_source_review
    from functions_orchestration_registry import CAPABILITY_URL_FETCH

    review_result = {
        "enabled": True,
        "pages": [],
        "skipped": [{"url": "https://manuals.plus/m/missing.pdf", "skip_reason": "http_404"}],
        "citations": [],
        "system_message": None,
    }
    step_result = _finalize_source_review(
        review_result,
        capability_id=CAPABILITY_URL_FETCH,
        unavailable_summary="Reading linked pages is not available for this user.",
        empty_summary="No linked pages could be read.",
        found_summary="Read {count} linked page(s).",
    )

    assert step_result["status"] == "completed"
    assert step_result["summary"] == "No linked pages could be read."
    assert len(step_result["notes"]) == 1
    assert "https://manuals.plus/m/missing.pdf" in step_result["notes"][0]
    assert "http_404" in step_result["notes"][0]


def test_completeness_and_compose_policies_accept_unfound_source_answer_with_coverage(harness):
    composition = importlib.import_module("functions_orchestration_composition")
    completeness = importlib.import_module("functions_task_completeness")

    assert "state that the searched content does not contain it" in composition.KNOWLEDGE_POLICIES["sources"]
    assert "report the inspected page or source coverage" in composition.KNOWLEDGE_POLICIES["sources"]
    assert "status:\n\"satisfied\"" in completeness.CHECK_POLICY or 'status: "satisfied"' in completeness.CHECK_POLICY
    assert "reports the available source/page coverage" in completeness.CHECK_POLICY
    assert "report the source\nand page or excerpt coverage" in completeness.CORRECTION_POLICY

    harness.settings["enable_chat_orchestration_completeness_check"] = True
    initial_draft = "The manual does not mention a 10-seconds-on and 10-seconds-off program."
    missing_coverage_report = json.dumps({"requirements": [{
        "id": "program_lookup",
        "requirement": "Identify the 10s-on/10s-off program or report that it is absent with page coverage and evidence.",
        "status": "missing",
        "reason": "The manual does not contain that setting, so the answer must also state how many pages were inspected and what programs were found.",
        "evidence_refs": [],
        "answer_quote": "",
    }]})
    corrected_answer = (
        "The provided Cycle Timer User Manual does not contain a program that alternates 10 seconds on and "
        "10 seconds off. I inspected all 5 of 5 pages in the manual: Page 2 covers Program P1 (30s on / 30s off), "
        "Page 3 covers Program P2 (60s on / 60s off), and Page 4 covers Program P3 (15 minutes continuous)."
    )
    satisfied_report = json.dumps({"requirements": [{
        "id": "program_lookup",
        "requirement": "Identify the 10s-on/10s-off program or report that it is absent with page coverage and evidence.",
        "status": "satisfied",
        "reason": "The answer accurately explains that the setting is not in the manual and cites all 5 of 5 inspected pages and the programs found.",
        "evidence_refs": [],
        "answer_quote": "I inspected all 5 of 5 pages in the manual",
    }]})

    step = compose_step()
    step["arguments"]["knowledge_basis"] = "sources"
    harness.create(
        [step],
        replies=[initial_draft, missing_coverage_report, corrected_answer, satisfied_report],
        final_response=input_binding("prepare", "answer"),
    )
    harness.prepare().execute()
    saved = harness.read()

    assert saved["status"] == "completed", saved.get("failure")
    assert "inspected all 5 of 5 pages" in saved["message"]


def test_empty_search_and_analyze_surface_source_coverage_to_compose(runtime, monkeypatch):
    from types import ModuleType

    search_module = ModuleType("functions_search")
    search_module.hybrid_search = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "functions_search", search_module)

    case = runtime.make(
        [
            {"step_id": "search", "capability_id": "document_search", "arguments": {"query": "10 seconds on 10 seconds off"}},
            compose("answer", inputs={"evidence": source_input("search", "evidence")}),
        ],
        ["No matching excerpts were found across the searched workspace scope."],
        final_response=binding("answer"),
    )
    result = execute(runtime, case)
    assert result["status"] == "completed", result
    payload = json.loads(case.model.calls[0][0][-1]["content"])
    evidence_input = payload["inputs"]["evidence"]
    assert evidence_input["value"] == []
    assert evidence_input["source_coverage"]["returned_excerpt_count"] == 0
    assert evidence_input["source_coverage"]["returned_page_count"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
