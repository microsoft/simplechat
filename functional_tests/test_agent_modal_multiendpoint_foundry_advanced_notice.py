# test_agent_modal_multiendpoint_foundry_advanced_notice.py
#!/usr/bin/env python3
"""
Functional test for agent modal multi-endpoint and Foundry advanced notice.
Version: 0.236.054
Implemented in: 0.236.054

This test ensures the agent modal hides custom connection fields when
multi-endpoint model management is enabled and shows an advanced
settings notice for Azure AI Foundry agents.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_agent_modal_multiendpoint_and_foundry_notice():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    modal_path = os.path.join(repo_root, "application", "single_app", "templates", "_agent_modal.html")
    stepper_path = os.path.join(repo_root, "application", "single_app", "static", "js", "agent_modal_stepper.js")

    modal_content = read_file_text(modal_path)
    stepper_content = read_file_text(stepper_path)

    assert "agent-custom-connection-toggle" in modal_content, "Expected custom connection toggle markup."
    assert "settings.enable_multi_model_endpoints" in modal_content, (
        "Expected Jinja gating for custom connection fields when multi-endpoint is enabled."
    )
    assert "agent-advanced-foundry-note" in modal_content, (
        "Expected Foundry advanced settings notice in the modal."
    )
    assert "agent-advanced-foundry-note" in stepper_content, (
        "Expected JS toggling for Foundry advanced settings notice."
    )

    print("✅ Agent modal multi-endpoint and Foundry advanced notice verified.")


def run_tests():
    tests = [test_agent_modal_multiendpoint_and_foundry_notice]
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
