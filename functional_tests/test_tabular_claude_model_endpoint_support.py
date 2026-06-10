# test_tabular_claude_model_endpoint_support.py
#!/usr/bin/env python3
"""
Functional test for tabular Claude model endpoint support.
Version: 0.241.186
Implemented in: 0.241.186

This test ensures tabular analysis and generated tabular exports preserve the
selected Claude/Anthropic model endpoint context, use provider-aware Semantic
Kernel services, avoid Anthropic-incompatible SK auto tool calling, and keep
summary helper prompts compatible with Anthropic's user-message requirement.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CHAT_ROUTE = APP_ROOT / "route_backend_chats.py"
RUNTIME_HELPER = APP_ROOT / "functions_model_endpoint_runtime.py"
CONFIG = APP_ROOT / "config.py"


def read_text(path):
    """Read source text as UTF-8."""
    return path.read_text(encoding="utf-8")


def assert_contains(source_text, needle, description):
    """Assert that source_text contains the expected marker."""
    if needle not in source_text:
        raise AssertionError(f"Missing {description}: {needle}")


def parse_python(path):
    """Parse a Python file and return its AST."""
    return ast.parse(read_text(path), filename=str(path))


def get_function(module_tree, function_name):
    """Return a top-level function node by name."""
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def test_tabular_helpers_accept_model_context():
    """Validate tabular helper signatures include model_context."""
    module_tree = parse_python(CHAT_ROUTE)
    expected_functions = {
        "_generate_tabular_structured_output_entries",
        "maybe_create_tabular_generated_output",
        "run_tabular_sk_analysis",
        "run_tabular_analysis_with_multi_file_support",
        "run_tabular_analysis_with_thought_tracking",
    }
    for function_name in expected_functions:
        function_node = get_function(module_tree, function_name)
        if function_node is None:
            raise AssertionError(f"Missing {function_name}")
        argument_names = [argument.arg for argument in function_node.args.args]
        if "model_context" not in argument_names:
            raise AssertionError(f"{function_name} must accept model_context")


def test_chat_route_threads_selected_model_context():
    """Validate selected model context reaches tabular foreground and export paths."""
    source_text = read_text(CHAT_ROUTE)
    assert_contains(source_text, "build_model_endpoint_context(", "model context construction")
    assert_contains(source_text, "endpoint_id=gpt_endpoint_id or data.get('model_endpoint_id')", "non-streaming endpoint id context")
    assert_contains(source_text, "endpoint_id=gpt_endpoint_id or frontend_model_endpoint_id", "streaming endpoint id context")
    assert_contains(source_text, "model_context=tabular_model_context", "tabular model context call-site handoff")
    if source_text.count("model_context=tabular_model_context") < 8:
        raise AssertionError("Expected all foreground/background tabular call sites to receive tabular_model_context")


def test_claude_tabular_uses_direct_planner_fallback():
    """Validate Claude tabular analysis does not rely on SK auto function calling."""
    source_text = read_text(CHAT_ROUTE)
    assert_contains(source_text, "tabular_model_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC", "Anthropic tabular branch")
    assert_contains(source_text, "maybe_recover_tabular_analysis_with_llm_reviewer(", "Claude JSON planner fallback")
    assert_contains(source_text, "await tabular_plugin.describe_tabular_file", "Claude direct schema summary execution")
    assert_contains(source_text, "build_tabular_schema_summary_fallback_from_invocations", "schema summary fallback handoff")
    assert_contains(source_text, "build_semantic_kernel_chat_service_for_model(", "provider-aware SK service builder")


def test_runtime_helper_supports_claude_sk_services():
    """Validate runtime helper can build Anthropic SK services from context."""
    source_text = read_text(RUNTIME_HELPER)
    assert_contains(source_text, "MODEL_ENDPOINT_PROVIDER_ALLOWLIST = {'aoai', 'aifoundry', 'new_foundry', 'anthropic', 'claude'}", "Claude provider allowlist")
    assert_contains(source_text, "resolve_model_endpoint_from_context", "model context re-resolution")
    assert_contains(source_text, "AnthropicSemanticKernelChatCompletion", "Anthropic SK adapter")
    assert_contains(source_text, "sanitize_model_endpoint_auth_for_context", "non-secret auth context")
    assert_contains(source_text, "'client_secret'", "service principal secret use")
    if "'client_secret'" in source_text.split("MODEL_CONTEXT_AUTH_FIELDS", 1)[1].split(")", 1)[0]:
        raise AssertionError("MODEL_CONTEXT_AUTH_FIELDS must not persist client_secret")


def test_summary_helpers_are_anthropic_message_safe():
    """Validate route-level summaries include a user message for Anthropic requests."""
    source_text = read_text(CHAT_ROUTE)
    assert_contains(source_text, '"Summarize recent conversation context for search query rewriting."', "search summary system instruction")
    assert_contains(source_text, '{"role": "user", "content": summary_prompt_search}', "search summary user payload")
    assert_contains(source_text, '"Summarize older conversation context for future chat turns."', "older summary system instruction")
    assert_contains(source_text, '{"role": "user", "content": summary_prompt_older}', "older summary user payload")
    assert_contains(source_text, "assessment_messages.append({'role': 'user', 'content': assessment_prompt})", "history assessment user payload")


def test_version_bumped_for_fix():
    """Validate config.py version was bumped for the fix."""
    source_text = read_text(CONFIG)
    assert_contains(source_text, 'VERSION = "0.241.186"', "fix version")


def main():
    """Run all test checks."""
    tests = [
        test_tabular_helpers_accept_model_context,
        test_chat_route_threads_selected_model_context,
        test_claude_tabular_uses_direct_planner_fallback,
        test_runtime_helper_supports_claude_sk_services,
        test_summary_helpers_are_anthropic_message_safe,
        test_version_bumped_for_fix,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
