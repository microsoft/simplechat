#!/usr/bin/env python3
# test_workflow_auto_invoke_attempt_settings.py
"""
Functional test for workflow auto-invoke attempt settings.
Version: 0.241.194
Implemented in: 0.241.193
Updated in: 0.241.194

This test ensures workflow agent action limits are admin-configurable instead
of using a hard-coded Semantic Kernel auto-invoke ceiling, and that admins see
capacity guidance when raising the limit.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_auto_invoke_attempt_settings_wiring() -> None:
    print("Testing workflow auto-invoke attempt settings wiring...")

    config_content = read_text("application/single_app/config.py")
    settings_content = read_text("application/single_app/functions_settings.py")
    admin_route_content = read_text("application/single_app/route_frontend_admin_settings.py")
    admin_template_content = read_text("application/single_app/templates/admin_settings.html")
    loader_content = read_text("application/single_app/semantic_kernel_loader.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")

    assert 'VERSION = "0.241.194"' in config_content, (
        "Expected config.py version 0.241.194 for workflow action limit settings."
    )
    assert "'workflow_max_auto_invoke_attempts': 60" in settings_content, (
        "Expected app settings defaults to persist the workflow action limit."
    )
    assert "workflow_max_auto_invoke_attempts = min(" in admin_route_content, (
        "Expected the admin settings route to clamp workflow action limit input."
    )
    assert "'workflow_max_auto_invoke_attempts': workflow_max_auto_invoke_attempts" in admin_route_content, (
        "Expected the admin settings route to save workflow action limit input."
    )
    assert 'id="workflow_max_auto_invoke_attempts"' in admin_template_content, (
        "Expected the admin settings UI to expose the workflow action limit."
    )
    assert "Values above 100 are capacity-sensitive" in admin_template_content, (
        "Expected the admin settings UI to warn about high workflow action limits."
    )
    assert "Enable Cosmos DB Throughput automation in SimpleChat" in admin_template_content, (
        "Expected the admin settings UI to recommend Cosmos throughput automation above 100."
    )
    assert "maximum_auto_invoke_attempts=60" not in loader_content, (
        "Expected Semantic Kernel auto-invoke attempts to avoid hard-coded 60 values."
    )
    assert "def get_max_auto_invoke_attempts(settings=None):" in loader_content, (
        "Expected a shared Semantic Kernel auto-invoke attempt normalizer."
    )
    assert "maximum_auto_invoke_attempts=get_max_auto_invoke_attempts(settings)" in loader_content, (
        "Expected agent construction to use the configured auto-invoke attempt limit."
    )
    assert "maximum_auto_invoke_attempts=get_max_auto_invoke_attempts(agent_config)" in loader_content, (
        "Expected prompt execution settings to use the configured auto-invoke attempt limit."
    )
    assert "def get_workflow_kernel_settings(settings):" in workflow_runner_content, (
        "Expected workflow runner to map workflow settings into Semantic Kernel settings."
    )
    assert "load_user_semantic_kernel(kernel, get_workflow_kernel_settings(settings), user_id, None)" in workflow_runner_content, (
        "Expected workflow agent loads to use the configured workflow action limit."
    )

    print("Workflow auto-invoke attempt settings wiring verified.")


def run_tests() -> bool:
    tests = [test_workflow_auto_invoke_attempt_settings_wiring]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)