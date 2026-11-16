#!/usr/bin/env python3
# test_pptx_render_file_mitigation.py
"""
Functional test for PPTX render_file overflow mitigation, pre-persistence validation,
OfficeRenderError classification, and invisible Unicode URL stripping.
Version: 0.261.380
Implemented in: 0.261.380

This test ensures that:
1. Pasted URLs containing trailing invisible Unicode format characters (such as U+200C ZWNJ,
   U+200B ZWSP, or U+FEFF BOM) are normalized cleanly by extract_urls_from_text,
   normalize_review_url, and _extract_urls instead of producing 404 requests.
2. LLM-composed prepared_slide_deck_v1 decks with single-line titles > 45 chars, URLs/hyphenated
   tokens in narrow columns, and slightly oversized body fonts or tight boxes are deterministically
   fitted during prepare_generated_slide_deck and rendered by render_prepared_pptx.
3. Un-fittable slide text overflow or unsafe links are rejected by prepare_generated_slide_deck
   with layout_overflow / unsupported_content before persistence so compose triggers its
   corrective retry instead of failing downstream in render_file.
4. output_failure preserves OfficeRenderError classifications and retryability instead of
   collapsing them into ValueError -> output_invalid.
"""

from copy import deepcopy
from pathlib import Path
import sys

import pytest
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_generated_office_adapters as adapters
import functions_office_file_renderers as office
from functions_orchestration_composition import _compose_correction
from functions_orchestration_rendering import output_failure
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_services import validate_composition_profile
from functions_source_review import extract_urls_from_text, normalize_review_url
from test_support.versioning import assert_app_version_at_least


SCORE_DECK_PAYLOAD = {
    "schema_version": "prepared_slide_deck_v1",
    "size": "wide",
    "slide_count": 8,
    "title": "Score: Structured, Auditable AI Evaluation",
    "slides": [
        {
            "layout": "title_and_content",
            "title": "Score: Structured, Auditable AI Evaluation",
            "notes": "Key message: Score overview. Source target: https://github.com/paullizer/score.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.8, "top": 1.55, "width": 7.6, "height": 1.0},
                    "font_size": 28,
                    "paragraphs": [{
                        "bold": True,
                        "text": "A decision-ready framework for making AI evaluations more structured, reviewable, and traceable.",
                    }],
                },
                {
                    "type": "text_box",
                    "box": {"left": 0.8, "top": 3.0, "width": 5.9, "height": 2.1},
                    "font_size": 19,
                    "paragraphs": [
                        {"bold": True, "text": "Problem to address"},
                        {
                            "list_kind": "bullet",
                            "text": "Unstructured evaluation can make criteria, evidence, and reviewer judgment difficult to compare or audit.",
                        },
                        {"bold": True, "text": "Intended value"},
                        {
                            "list_kind": "bullet",
                            "text": "A consistent evaluation process can support clearer decisions, review, and reporting.",
                        },
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 7.25, "top": 2.95, "width": 5.05, "height": 2.15},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Evidence status"},
                        {
                            "list_kind": "bullet",
                            "text": "No repository content was provided in the retrieved material. Detailed Score behavior is not asserted in this deck.",
                        },
                        {
                            "list_kind": "bullet",
                            "text": "This deck separates unknown product facts from recommended operating practices.",
                        },
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Score at a glance",
            "notes": "Key message: documented capabilities and explicit boundaries.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.7, "top": 1.4, "width": 5.95, "height": 4.7},
                    "font_size": 19,
                    "paragraphs": [
                        {"bold": True, "text": "What is documented in the supplied material"},
                        {
                            "list_kind": "bullet",
                            "text": "The retrieved material identifies a GitHub repository target, but includes no source excerpts or capability evidence.",
                        },
                        {"list_kind": "bullet", "text": "Supported capability claims: none available for verification."},
                        {
                            "list_kind": "bullet",
                            "text": "Supported implementation, deployment, integration, or model claims: none available for verification.",
                        },
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 6.95, "top": 1.4, "width": 5.65, "height": 4.7},
                    "font_size": 19,
                    "paragraphs": [
                        {"bold": True, "text": "Explicit boundaries for this deck"},
                        {
                            "list_kind": "bullet",
                            "text": "Do not represent Score as performing automated scoring, rubric management, reporting, or bias mitigation until repository evidence confirms it.",
                        },
                        {"list_kind": "bullet", "text": "Non-goals and limitations are unknown from the supplied material."},
                        {
                            "list_kind": "bullet",
                            "text": "Validation needed: README, architecture documentation, examples, configuration, tests, and output artifacts.",
                        },
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Architecture: evidence-bound view",
            "notes": "Key message: reference architecture.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 11.85, "height": 0.6},
                    "font_size": 18,
                    "paragraphs": [{
                        "bold": True,
                        "text": "Repository-supported architecture: not available in supplied evidence. Reference pattern below is recommended, not a verified Score design.",
                    }],
                },
                {
                    "type": "text_box",
                    "box": {"left": 0.8, "top": 2.3, "width": 2.2, "height": 1.5},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Inputs"},
                        {"text": "Items to evaluate\nRubric\nEvaluation context"},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 3.25, "top": 2.3, "width": 2.35, "height": 1.5},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Evaluation logic"},
                        {"text": "Criterion application\nEvidence capture\nScore calculation"},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 5.9, "top": 2.3, "width": 2.2, "height": 1.5},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Review controls"},
                        {"text": "Validation\nExceptions\nHuman review"},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 8.4, "top": 2.3, "width": 2.2, "height": 1.5},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Outputs"},
                        {"text": "Scores\nRationales\nDecision views"},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 10.9, "top": 2.3, "width": 1.55, "height": 1.5},
                    "font_size": 16,
                    "paragraphs": [
                        {"bold": True, "text": "Oversight"},
                        {"text": "Approve\nchallenge\nimprove"},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 0.9, "top": 4.45, "width": 11.3, "height": 1.1},
                    "font_size": 20,
                    "paragraphs": [{
                        "bold": True,
                        "text": "Text flow: Inputs \u2192 evaluation logic \u2192 review controls \u2192 outputs \u2192 human oversight \u2192 rubric and process improvement",
                    }],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "End-to-end workflow: recommended operating pattern",
            "notes": "Key message: governance workflow.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 3.75, "height": 4.85},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "1. Set up the evaluation"},
                        {"list_kind": "bullet", "text": "Define the decision, population, owners, and acceptable use."},
                        {"bold": True, "text": "2. Design the rubric"},
                        {"list_kind": "bullet", "text": "Specify criteria, scale anchors, evidence expectations, and escalation rules."},
                        {"bold": True, "text": "3. Prepare the evaluation set"},
                        {"list_kind": "bullet", "text": "Check completeness, provenance, and handling requirements."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 4.8, "top": 1.35, "width": 3.75, "height": 4.85},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "4. Evaluate and capture evidence"},
                        {"list_kind": "bullet", "text": "Apply criteria consistently and retain rationale with each result."},
                        {"bold": True, "text": "5. Analyze results"},
                        {"list_kind": "bullet", "text": "Review distributions, exceptions, disagreements, and decision relevance."},
                        {"bold": True, "text": "6. Conduct human review"},
                        {"list_kind": "bullet", "text": "Resolve material uncertainty, overrides, and policy-sensitive cases."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 8.85, "top": 1.35, "width": 3.75, "height": 4.85},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "7. Report and decide"},
                        {"list_kind": "bullet", "text": "Communicate findings, caveats, and actions to the accountable owner."},
                        {"bold": True, "text": "8. Improve the system"},
                        {"list_kind": "bullet", "text": "Use review outcomes to refine rubrics, controls, and evaluation coverage."},
                        {"bold": True, "text": "Status"},
                        {"list_kind": "bullet", "text": "Recommended workflow. Score-specific implementation is unknown."},
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Rubrics, scoring, and analysis",
            "notes": "Key message: rubric and scoring design.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 5.8, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Score-specific facts to verify in the repository"},
                        {"list_kind": "bullet", "text": "How criteria are defined and versioned."},
                        {"list_kind": "bullet", "text": "Which score scales, anchors, and thresholds are supported."},
                        {"list_kind": "bullet", "text": "How evaluator evidence and rationale are captured."},
                        {"list_kind": "bullet", "text": "Whether and how criterion scores are weighted or aggregated."},
                        {"list_kind": "bullet", "text": "Which analytic views or exports are implemented."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 6.85, "top": 1.35, "width": 5.75, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Recommended evaluation design"},
                        {"list_kind": "bullet", "text": "Use observable, decision-relevant criteria with explicit scale anchors."},
                        {"list_kind": "bullet", "text": "Require evidence or rationale for consequential judgments."},
                        {"list_kind": "bullet", "text": "Treat aggregate scores as summaries, not substitutes for review of material exceptions."},
                        {"list_kind": "bullet", "text": "Interpret results by criterion, segment, and uncertainty where appropriate."},
                        {"list_kind": "bullet", "text": "Document the rubric version and decision rule with every result set."},
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Bias mitigation and responsible-use guardrails",
            "notes": "Key message: bias mitigation.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 5.8, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Repository-supported mechanisms"},
                        {
                            "list_kind": "bullet",
                            "text": "No model-bias mitigation feature, fairness measure, protected-attribute analysis, or safety control is evidenced in the supplied material.",
                        },
                        {"list_kind": "bullet", "text": "Do not infer that structured scoring alone mitigates bias."},
                        {
                            "list_kind": "bullet",
                            "text": "Confirm any implemented controls directly from repository documentation and tests before relying on them.",
                        },
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 6.85, "top": 1.35, "width": 5.75, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Recommended operating practices"},
                        {"list_kind": "bullet", "text": "Define intended use, prohibited use, and accountable decision owners."},
                        {"list_kind": "bullet", "text": "Test rubric clarity and outcome consistency across relevant cases before deployment."},
                        {"list_kind": "bullet", "text": "Use calibrated human review for high-impact, ambiguous, or contested outcomes."},
                        {"list_kind": "bullet", "text": "Monitor exceptions and material disparities, then revise criteria or process when warranted."},
                        {"list_kind": "bullet", "text": "Preserve uncertainty and do not present model output as final fact."},
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Quality control and QC checks",
            "notes": "Key message: QC checklist.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 5.8, "height": 4.95},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Recommended QC control set"},
                        {"list_kind": "bullet", "text": "Validate required inputs, rubric completeness, and permitted score values."},
                        {"list_kind": "bullet", "text": "Check that criterion scores have corresponding evidence or rationale when required."},
                        {"list_kind": "bullet", "text": "Run calibration or agreement checks among reviewers for material decisions."},
                        {"list_kind": "bullet", "text": "Route invalid, incomplete, low-confidence, or policy-sensitive cases to review."},
                        {"list_kind": "bullet", "text": "Record overrides, decisions, and remediation actions."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 6.85, "top": 1.35, "width": 5.75, "height": 4.95},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Evidence needed for a Score-specific QC map"},
                        {"list_kind": "bullet", "text": "Automated validation rules and error behavior."},
                        {"list_kind": "bullet", "text": "Test coverage, fixtures, and reproducible run instructions."},
                        {"list_kind": "bullet", "text": "Persistence of inputs, rubric versions, scores, and rationales."},
                        {"list_kind": "bullet", "text": "Human-review workflows and exception states."},
                        {"list_kind": "bullet", "text": "Audit logs, access controls, and output retention behavior."},
                        {"list_kind": "bullet", "text": "None of these features are confirmed by the supplied repository material."},
                    ],
                },
            ],
        },
        {
            "layout": "title_and_content",
            "title": "Reporting, summary, and next steps",
            "notes": "Key message: summary and next steps.",
            "shapes": [
                {
                    "type": "text_box",
                    "box": {"left": 0.75, "top": 1.35, "width": 4.0, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Feasible report views"},
                        {"list_kind": "bullet", "text": "Executive summary: decision, headline results, caveats, and owner actions."},
                        {"list_kind": "bullet", "text": "Criterion view: scores, evidence, rationale, and exceptions."},
                        {"list_kind": "bullet", "text": "Quality view: completeness, agreement, overrides, and open issues."},
                        {"list_kind": "bullet", "text": "Trend view: outcomes by period, rubric version, or evaluation cohort."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 4.95, "top": 1.35, "width": 4.0, "height": 4.9},
                    "font_size": 18,
                    "paragraphs": [
                        {"bold": True, "text": "Practical adoption actions"},
                        {"list_kind": "bullet", "text": "Review the repository README, code, examples, tests, and output artifacts."},
                        {"list_kind": "bullet", "text": "Create a verified capability and limitation inventory."},
                        {"list_kind": "bullet", "text": "Pilot one bounded use case with a versioned rubric and human review."},
                        {"list_kind": "bullet", "text": "Define decision ownership, escalation, and evidence-retention requirements."},
                    ],
                },
                {
                    "type": "text_box",
                    "box": {"left": 9.15, "top": 1.35, "width": 3.45, "height": 4.9},
                    "font_size": 17,
                    "paragraphs": [
                        {"bold": True, "text": "Bottom line"},
                        {
                            "list_kind": "bullet",
                            "text": "Structured evaluation can improve clarity and accountability when criteria, evidence, review, and reporting are governed together.",
                        },
                        {"list_kind": "bullet", "text": "Score-specific conclusions remain unknown until repository content is examined."},
                        {"bold": True, "text": "Source note"},
                        {"list_kind": "bullet", "text": "Repository target supplied by requester: https://github.com/paullizer/score"},
                    ],
                },
            ],
        },
    ],
}


def test_version_at_least_0_261_380():
    assert_app_version_at_least("0.261.380")


def test_invisible_unicode_characters_are_stripped_from_pasted_urls():
    msg = (
        "https://github.com/paullizer/score\u200c\n\n"
        "Also check https://example.com/docs\u200b. And (https://example.org/path\ufeff)"
    )
    extracted = extract_urls_from_text(msg)
    assert extracted == [
        "https://github.com/paullizer/score",
        "https://example.com/docs",
        "https://example.org/path",
    ]
    normalized, reason = normalize_review_url("https://github.com/paullizer/score\u200c")
    assert normalized == "https://github.com/paullizer/score" and reason is None


def test_score_deck_renders_end_to_end_without_mutating_source_json():
    snapshot = deepcopy(SCORE_DECK_PAYLOAD)
    validated = validate_composition_profile("prepared_slide_deck_v1", SCORE_DECK_PAYLOAD)
    assert validated is True
    assert SCORE_DECK_PAYLOAD == snapshot

    prepared = adapters.prepare_generated_slide_deck(SCORE_DECK_PAYLOAD)
    assert SCORE_DECK_PAYLOAD == snapshot
    assert len(prepared.slides) == 8

    with office.render_prepared_pptx(prepared) as rendered:
        assert rendered.size_bytes > 0
        assert rendered.metadata["slide_count"] == 8
        assert rendered.metadata["shape_count"] == 24
        rendered.file_content.seek(0)
        presentation = Presentation(rendered.file_content)
        assert len(presentation.slides) == 8
        slide4_title = presentation.slides[3].shapes.title.text
        assert slide4_title == "End-to-end workflow: recommended operating pattern"


def test_unfittable_deck_overflow_is_rejected_during_composition_validation():
    bad_deck = {
        "schema_version": "prepared_slide_deck_v1",
        "size": "wide",
        "slide_count": 1,
        "slides": [{
            "layout": "title_and_content",
            "title": "Valid Title",
            "shapes": [{
                "type": "text_box",
                "box": {"left": 0.8, "top": 1.5, "width": 3.0, "height": 0.3},
                "font_size": 18,
                "paragraphs": [{"text": "Too much text to fit in a 0.3 inch box even at 8pt."}],
            }],
        }],
    }
    with pytest.raises(ResultContractError) as exc_info:
        validate_composition_profile("prepared_slide_deck_v1", bad_deck)
    assert exc_info.value.code == "result_layout_invalid"

    err = exc_info.value
    err.output_name = "deck"
    correction = _compose_correction(
        err, [{"name": "deck", "kind": "structured-v1", "profile": "prepared_slide_deck_v1"}],
    )
    assert correction is not None
    assert "overflowed a title, text box, or table cell" in correction
    assert "keep slide titles to a single concise line" in correction


def test_multiline_slide_title_is_rejected_during_preparation():
    bad_title_deck = {
        "schema_version": "prepared_slide_deck_v1",
        "size": "wide",
        "slide_count": 1,
        "slides": [{
            "layout": "title_and_content",
            "title": "First line\nSecond line",
            "shapes": [],
        }],
    }
    with pytest.raises(ResultContractError) as exc_info:
        validate_composition_profile("prepared_slide_deck_v1", bad_title_deck)
    assert exc_info.value.code == "result_layout_invalid"


@pytest.mark.parametrize(
    ("code", "expected_code", "expected_retryable"),
    [
        ("layout_overflow", "layout_overflow", False),
        ("incomplete_source", "incomplete_source", False),
        ("limit_exceeded", "size_limit", False),
        ("invalid_input", "invalid_data", False),
        ("unsupported_content", "invalid_data", False),
        ("access_denied", "output_access_denied", False),
        ("source_changed", "output_source_changed", False),
        ("cancelled", "output_cancelled", False),
        ("render_io", "render_io", True),
        ("source_unavailable", "source_unavailable", True),
        ("render_failed", "render_validation_failed", False),
    ],
)
def test_output_failure_preserves_office_render_error_classifications(
    code, expected_code, expected_retryable,
):
    err = office.OfficeRenderError(code)
    assert output_failure(err) == (expected_code, expected_retryable)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
