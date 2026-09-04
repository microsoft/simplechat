# test_new_foundry_endpoint_api_version_handling.py
#!/usr/bin/env python3
"""
Functional test for New Foundry endpoint API version handling.
Version: 0.250.006
Implemented in: 0.250.003; updated in 0.250.006

This test ensures that New Foundry endpoints default to a dated preview
inference API, expose custom version fields, detect project names from Project
endpoints, and preserve existing agent Responses API version handling.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_new_foundry_endpoint_api_version_handling() -> None:
    print("Testing New Foundry endpoint API version handling...")

    endpoint_js = ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_model_endpoints.js"
    workspace_endpoint_js = ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_model_endpoints.js"
    agent_modal_js = ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"
    loader_py = ROOT / "application" / "single_app" / "semantic_kernel_loader.py"
    endpoint_modal = ROOT / "application" / "single_app" / "templates" / "_multiendpoint_modal.html"
    config_file = ROOT / "application" / "single_app" / "config.py"

    assert_contains(endpoint_js, 'const DEFAULT_AOAI_OPENAI_API_VERSION = "2024-05-01-preview";')
    assert_contains(endpoint_js, 'const DEFAULT_FOUNDRY_OPENAI_API_VERSION = "v1";')
    assert_contains(endpoint_js, 'const DEFAULT_FOUNDRY_PROJECT_API_VERSION = "v1";')
    assert_contains(endpoint_js, 'return isFoundryProvider(provider) ? DEFAULT_FOUNDRY_OPENAI_API_VERSION : DEFAULT_AOAI_OPENAI_API_VERSION;')
    assert_contains(endpoint_js, 'function getProjectNameFromEndpoint(endpoint) {')
    assert_contains(endpoint_js, 'syncProjectNameFromEndpoint();')
    assert_contains(endpoint_js, 'Claude deployments are detected from the model name')
    assert_contains(workspace_endpoint_js, 'const DEFAULT_FOUNDRY_OPENAI_API_VERSION = "v1";')
    assert_contains(workspace_endpoint_js, 'const DEFAULT_FOUNDRY_PROJECT_API_VERSION = "v1";')
    assert_contains(workspace_endpoint_js, 'return isFoundryProvider(provider) ? DEFAULT_FOUNDRY_OPENAI_API_VERSION : DEFAULT_AOAI_OPENAI_API_VERSION;')
    assert_contains(workspace_endpoint_js, 'function getProjectNameFromEndpoint(endpoint) {')
    assert_contains(agent_modal_js, "const fetchedResponsesApiVersion = payload.responses_api_version || '';")
    assert_contains(agent_modal_js, 'const preserveCurrentSelection = this.shouldPreserveCurrentFoundrySelection(endpointId);')
    assert_contains(agent_modal_js, "const storedResponsesApiVersion = currentFoundrySettings.responses_api_version || '';")
    assert_contains(loader_py, 'stored_responses_api_version = (')
    assert_contains(loader_py, 'or agent.get("azure_openai_gpt_api_version")')
    assert_contains(agent_modal_js, "if (responsesApiVersionInput && selected.responses_api_version) {")
    assert_contains(endpoint_modal, 'id="model-endpoint-project-api-version-custom"')
    assert_contains(endpoint_modal, 'id="model-endpoint-openai-api-version-custom"')
    assert_contains(endpoint_modal, 'the /v1 path does not allow an api-version query')
    assert_contains(endpoint_modal, 'Split model families into separate endpoints')
    assert_contains(endpoint_modal, 'Claude deployments are detected from the model name')
    assert_contains(endpoint_modal, 'If the project endpoint includes /api/projects/&lt;project&gt;')
    assert_contains(config_file, 'VERSION = "0.250.006"')

    print("✅ New Foundry endpoint API version handling verified.")


if __name__ == "__main__":
    success = True
    try:
        test_new_foundry_endpoint_api_version_handling()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)