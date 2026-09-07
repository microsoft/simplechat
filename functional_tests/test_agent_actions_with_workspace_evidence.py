#!/usr/bin/env python3
# test_agent_actions_with_workspace_evidence.py
"""
Functional test for additive evidence gathering when a workspace is in scope.
Version: 0.260.025
Implemented in: 0.260.025

This test ensures that selecting an agent with actions and enabling a workspace
no longer degrades into a retrieval-only turn. It validates that:

1. An authorized tabular source is computed even when narrative sources are also
   in scope, instead of being skipped by a keyword heuristic.
2. A skipped tabular source tells the model the full table was never read and
   that preview rows cannot support numeric conclusions.
3. The retrieval augmentation prompt permits, rather than forbids, calling the
   agent's actions when the retrieved excerpts are insufficient.
4. The mixed-source evidence handoff carries the same permission and the same
   preview-row guard.

Regression context: a question about battery telemetry with a spreadsheet in the
workspace returned fabricated numbers because the tabular engine was skipped and
the model was told to answer only from the 3-row indexed schema preview.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
sys.path.insert(0, APP_ROOT)

from test_support.versioning import assert_app_version_at_least

import functions_mixed_source_orchestration as orchestration

ROUTE_FILE = os.path.join(APP_ROOT, 'route_backend_chats.py')
TARGET_FUNCTIONS = {'build_search_augmentation_system_prompt'}


def load_search_prompt_helper():
    """Load the retrieval augmentation prompt helper from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace['build_search_augmentation_system_prompt']


def test_tabular_evidence_runs_alongside_narrative_sources():
    """Narrative sources in scope must not suppress computing a tabular source."""
    print("🔍 Testing additive tabular evidence gating...")

    try:
        assert_app_version_at_least("0.260.025")

        # The reported regression: a specific quantitative question that uses none
        # of the hardcoded tabular keywords, asked while narrative sources are also
        # in relevance scope.
        assert orchestration.should_run_tabular_evidence(
            "What was the battery telemetry during the descent?",
            has_narrative_sources=True,
        ) is True, "Quantitative question was skipped because narrative sources existed"

        # Topic words describe subject matter, not which engine can answer.
        for topic_question in (
            "Give me a report on battery performance.",
            "What does the policy say about battery thresholds?",
            "Summarize the memo and the battery readings.",
        ):
            assert orchestration.should_run_tabular_evidence(
                topic_question,
                has_narrative_sources=True,
            ) is True, f"Topic word suppressed tabular computation: {topic_question}"

        # An unambiguous narrative-artifact request still skips computation.
        assert orchestration.should_run_tabular_evidence(
            "What policy does the PDF state?",
            has_narrative_sources=True,
        ) is False, "Narrative-artifact request should still skip tabular computation"

        # Explicit tabular intent always computes, with or without narrative sources.
        assert orchestration.should_run_tabular_evidence(
            "Calculate the total and average from the spreadsheet.",
            has_narrative_sources=True,
        ) is True
        assert orchestration.should_run_tabular_evidence(
            "Summarize all selected documents.",
            has_narrative_sources=True,
        ) is True

        # With no narrative sources at all, computation is always appropriate.
        assert orchestration.should_run_tabular_evidence(
            "What does the PDF say?",
            has_narrative_sources=False,
        ) is True

        print("✅ Additive tabular evidence gating passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_skipped_tabular_envelope_blocks_preview_row_math():
    """A skipped tabular source must warn against computing from preview rows."""
    print("🔍 Testing skipped tabular evidence envelope guidance...")

    try:
        executor_calls = []
        envelopes = orchestration.execute_tabular_evidence_sources(
            [{"document_id": "personal-xlsx"}],
            lambda source: executor_calls.append(source),
            "selected",
            execute=False,
        )

        assert executor_calls == [], "Executor should not run when execution is skipped"
        assert len(envelopes) == 1, envelopes
        envelope = envelopes[0]

        assert envelope["status"] == orchestration.EVIDENCE_STATUS_SKIPPED
        assert envelope["coverage"]["terminal"] is True

        summary = envelope["summary"]
        assert "truncated schema preview" in summary, summary
        assert "Do not derive counts" in summary, summary
        assert "tabular analysis action" in summary, summary
        assert "was not needed" not in summary, (
            "Skipped summary must not imply the source was irrelevant"
        )

        print("✅ Skipped tabular envelope guidance passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_search_prompt_permits_action_invocation():
    """The retrieval prompt must not forbid the agent from calling its actions."""
    print("🔍 Testing retrieval augmentation prompt action permission...")

    try:
        build_search_prompt = load_search_prompt_helper()
        prompt = build_search_prompt('Excerpt A')

        # The closed-book instruction that suppressed action invocation.
        assert 'Base your answer only on information supported by' not in prompt, prompt

        # Actions are now explicitly permitted and expected.
        assert 'starting evidence, not your only means of gathering evidence' in prompt, prompt
        assert 'call the appropriate action' in prompt, prompt
        assert 'before declining to answer' in prompt, prompt

        # Anti-fabrication guarantee is preserved.
        assert 'Never estimate, infer, or fabricate values' in prompt, prompt

        # Preview rows can never support numeric conclusions.
        assert 'truncated schema preview' in prompt, prompt
        assert 'Never derive counts' in prompt, prompt

        # Existing contracts asserted by
        # test_tabular_computed_results_prompt_priority.py must still hold.
        assert 'computed tool-backed results included elsewhere in this conversation context' in prompt, prompt
        assert 'Do not say that you lack direct access to the data' in prompt, prompt
        assert "If the answer isn't in the excerpts, say so." not in prompt, prompt

        print("✅ Retrieval augmentation prompt action permission passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_mixed_source_handoff_permits_action_invocation():
    """The mixed-source handoff must permit actions and guard preview-row math."""
    print("🔍 Testing mixed-source handoff action permission...")

    try:
        manifest = [{
            "document_id": "personal-xlsx",
            "display_name": "battery_telemetry.xlsx",
            "source_kind": orchestration.SOURCE_KIND_TABULAR,
            "scope": orchestration.SOURCE_SCOPE_PERSONAL,
            "authorization_status": orchestration.AUTHORIZATION_STATUS_AUTHORIZED,
        }]
        evidence_envelopes = orchestration.execute_tabular_evidence_sources(
            [{"document_id": "personal-xlsx"}],
            lambda source: None,
            "selected",
            execute=False,
        )

        handoff = orchestration.build_mixed_source_evidence_handoff(
            manifest,
            evidence_envelopes,
            "selected",
        )
        content = handoff["content"]

        assert 'starting evidence, not your only means of gathering evidence' in content, content
        assert 'call the appropriate action' in content, content
        assert 'Never derive numeric conclusions from an indexed preview' in content, content

        # Synthesis and citation contracts are preserved.
        assert 'Synthesize one answer' in content, content
        assert 'Preserve narrative source citations' in content, content

        print("✅ Mixed-source handoff action permission passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    original_log_event = orchestration.log_event
    orchestration.log_event = lambda *args, **kwargs: None

    tests = [
        test_tabular_evidence_runs_alongside_narrative_sources,
        test_skipped_tabular_envelope_blocks_preview_row_math,
        test_search_prompt_permits_action_invocation,
        test_mixed_source_handoff_permits_action_invocation,
    ]
    results = []

    try:
        for test in tests:
            print(f"\n🧪 Running {test.__name__}...")
            results.append(test())
    finally:
        orchestration.log_event = original_log_event

    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
