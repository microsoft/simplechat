# test_document_action_phase_progress_status.py
#!/usr/bin/env python3
"""
Functional test for document action phase-aware progress.
Version: 0.241.023
Implemented in: 0.241.096

This test ensures analysis and document comparison expose phase
metadata so the overall chat progress bar stays below 100 percent until the
final response is actually ready.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_action_phase_progress_wiring():
    config_content = read_text("application/single_app/config.py")
    analysis_service_content = read_text("application/single_app/functions_document_analysis.py")
    comparison_service_content = read_text("application/single_app/functions_document_comparison.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    chat_thoughts_content = read_text("application/single_app/static/js/chat/chat-thoughts.js")

    assert 'VERSION = "0.241.023"' in config_content, (
        "Expected config.py version 0.241.023 for phase-aware document action progress."
    )
    assert "'phase_label': progress_meta.get('phase_label')" in analysis_service_content, (
        "Expected analysis progress snapshots to expose the current phase label."
    )
    assert "'phase_detail': progress_meta.get('phase_detail')" in analysis_service_content, (
        "Expected analysis progress snapshots to expose phase detail text."
    )
    assert "'type': 'reduction_started'" in analysis_service_content, (
        "Expected analysis activity callbacks to publish reduction-phase updates."
    )
    assert "phase='summarizing'" in comparison_service_content, (
        "Expected document comparison to track the summary phase explicitly."
    )
    assert "phase='comparing'" in comparison_service_content, (
        "Expected document comparison to track pairwise comparison progress explicitly."
    )
    assert "phase='reducing'" in comparison_service_content, (
        "Expected document comparison to track the final reduction phase explicitly."
    )
    assert 'overall.status' in chat_thoughts_content, (
        "Expected the chat thought renderer to respect backend overall status instead of inferring completion."
    )
    assert 'overall.phase_label' in chat_thoughts_content, (
        "Expected the chat thought renderer to surface the current phase label."
    )
    assert 'overall.phase_detail' in chat_thoughts_content, (
        "Expected the chat thought renderer to surface the current phase detail."
    )
    assert 'Combining analysis findings into the final response' in chat_route_content, (
        "Expected the chat route to describe the analysis reduction phase."
    )
    assert 'Combining comparison findings into the final response' in chat_route_content, (
        "Expected the chat route to describe the comparison reduction phase."
    )
    assert 'Combining analysis findings into the final response' in workflow_runner_content, (
        "Expected workflow thoughts to describe the analysis reduction phase."
    )

    print("✅ Document action phase-aware progress wiring verified.")


def run_tests():
    tests = [test_document_action_phase_progress_wiring]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)