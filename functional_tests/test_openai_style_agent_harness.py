# test_openai_style_agent_harness.py
#!/usr/bin/env python3
"""
Functional test for the OpenAI-style agent harness.
Version: 0.239.205
Implemented in: 0.239.205

This test ensures the standalone harness reads local me.json and agent.json
files, routes prompt execution settings through Semantic Kernel correctly, and
exercises a Semantic Kernel agent with OpenAI-style client wiring and function
choice settings.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, unexpected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if unexpected in content:
        raise AssertionError(f"Did not expect to find {unexpected!r} in {file_path}")


def test_openai_style_agent_harness_wiring() -> None:
    print("🧪 Running test_openai_style_agent_harness_wiring...")
    harness_path = ROOT / "scripts" / "openai_style_agent_harness.py"

    assert_contains(harness_path, 'MODEL_ENDPOINT_PATH = SCRIPT_DIR / "me.json"')
    assert_contains(harness_path, 'AGENT_CONFIG_PATH = SCRIPT_DIR / "agent.json"')
    assert_contains(harness_path, 'from openai import AsyncOpenAI')
    assert_contains(harness_path, 'from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion')
    assert_contains(harness_path, 'FunctionChoiceBehavior.Auto')
    assert_contains(harness_path, 'FunctionChoiceBehavior.Required')
    assert_contains(harness_path, 'FunctionChoiceBehavior.NoneInvoke()')
    assert_contains(harness_path, 'if normalized_mode == "off":')
    assert_contains(harness_path, 'return None')
    assert_contains(harness_path, 'service.get_prompt_execution_settings_class()')
    assert_contains(harness_path, 'def resolve_openai_style_request_api_version(raw_api_version: str) -> str:')
    assert_contains(harness_path, 'if normalized_api_version in ("preview", "latest"):')
    assert_contains(harness_path, 'Ignoring legacy Azure API version for OpenAI-style /openai/v1/ requests')
    assert_contains(harness_path, 'request_api_version = resolve_openai_style_request_api_version(api_version)')
    assert_contains(harness_path, 'client_kwargs["default_query"] = {"api-version": request_api_version}')
    assert_not_contains(harness_path, 'if api_version and api_version.lower() != "v1":')
    assert_contains(harness_path, 'request_model_name = deployment_name')
    assert_contains(harness_path, 'ai_model_id=request_model_name')
    assert_contains(harness_path, 'logging.info("Catalog model id: %s", model_id or "(none)")')
    assert_contains(harness_path, 'logging.info("Request deployment/model: %s", request_model_name)')
    assert_contains(harness_path, 'kernel.add_plugin(HarnessToolsPlugin(), plugin_name="harness_tools")')
    assert_contains(harness_path, 'agent_arguments = KernelArguments(settings=prompt_execution_settings)')
    assert_not_contains(harness_path, 'execution_settings={DEFAULT_SERVICE_ID: prompt_execution_settings}')
    assert_contains(harness_path, 'agent.invoke_stream(messages=message_history)')
    print("✅ OpenAI-style agent harness wiring verified.")


if __name__ == "__main__":
    try:
        test_openai_style_agent_harness_wiring()
        success = True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)