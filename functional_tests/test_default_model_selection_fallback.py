# test_default_model_selection_fallback.py
# test_default_model_selection_fallback.py
#!/usr/bin/env python3
"""
Functional test for default model selection fallback.
Version: 0.261.042
Implemented in: 0.240.071; updated in 0.261.042

This test ensures default model selection is surfaced in admin settings
and used for fallback GPT initialization when legacy agents omit or lose
multi-endpoint model bindings. It also verifies the admin override that
starts new non-agent conversations with the configured default model and
reasoning effort.
"""

import os
import ast
from test_support.templates import compose_if_admin_settings


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return compose_if_admin_settings(file_path, file.read())


def test_default_model_selection_wiring():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    admin_template_path = os.path.join(
        repo_root, "application", "single_app", "templates", "admin_settings.html"
    )
    admin_route_path = os.path.join(
        repo_root, "application", "single_app", "route_frontend_admin_settings.py"
    )
    chat_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_chats.py"
    )
    loader_path = os.path.join(
        repo_root, "application", "single_app", "semantic_kernel_loader.py"
    )

    admin_template = read_file_text(admin_template_path)
    admin_route = read_file_text(admin_route_path)
    chat_route = read_file_text(chat_path)
    loader_content = read_file_text(loader_path)

    assert "default_model_selection_json" in admin_template, (
        "Expected default model selection input in admin settings template."
    )
    assert "default-model-selection" in admin_template, (
        "Expected default model selection dropdown in admin settings template."
    )
    assert "Default model for fallbacks and new chats" in admin_template, (
        "Expected admin settings to label the default model as applying to new chats."
    )
    assert "enable_default_model_for_new_conversations" in admin_template, (
        "Expected admin toggle for applying the default model to new conversations."
    )
    assert "default_reasoning_effort" in admin_template, (
        "Expected admin default reasoning effort selector in admin settings template."
    )
    assert "default_model_selection" in admin_route, (
        "Expected default model selection to be handled in admin settings save." 
    )
    assert "enable_default_model_for_new_conversations" in admin_route, (
        "Expected admin settings save to persist the new-conversation default toggle."
    )
    assert "default_reasoning_effort" in admin_route, (
        "Expected admin settings save to persist the default reasoning effort."
    )
    assert "resolve_streaming_multi_endpoint_gpt_config" in chat_route, (
        "Expected streaming default model fallback logic in chat route."
    )
    assert "settings.get('default_model_selection'" in chat_route, (
        "Expected streaming model resolution to read the saved default model selection."
    )
    assert "selection_source = 'default' if data.get('_admin_default_model_applied') else 'request'" in chat_route, (
        "Expected admin-applied defaults to fall back safely when the saved default is stale."
    )
    assert "_apply_admin_new_conversation_model_defaults" in chat_route, (
        "Expected chat requests to apply admin defaults for new conversations."
    )
    assert "admin_default_applied" in chat_route, (
        "Expected model metadata to record when the admin default was applied."
    )
    assert 'can_agent_use_default_multi_endpoint_model' in loader_content, (
        "Expected the shared agent loader to gate default-model fallback to inherited agents."
    )
    assert 'Using saved admin default multi-endpoint model for agent' in loader_content, (
        "Expected the shared agent loader to use the saved admin default model when agent bindings are missing or stale."
    )

    print("✅ Default model selection wiring verified.")


def test_admin_new_conversation_default_helper_behavior():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    chat_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_chats.py"
    )
    chat_route = read_file_text(chat_path)

    route_ast = ast.parse(chat_route, filename=chat_path)
    helper_names = [
        "_normalize_default_reasoning_effort",
        "_apply_admin_new_conversation_model_defaults",
    ]
    helper_nodes = [
        node for node in route_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    assert len(helper_nodes) == len(helper_names), "Expected both admin default helper functions."

    required_snippets = [
        "conversation_id\n        or is_retry",
        "or _has_chat_agent_selection(request_agent_info)",
        "not settings.get('enable_default_model_for_new_conversations', False)",
        "data['model_endpoint_id'] = default_endpoint_id",
        "data['model_id'] = default_model_id",
        "data['model_provider'] = default_provider",
        "data['model_deployment'] = ''",
        "data['reasoning_effort'] = None if default_reasoning_effort == 'none' else default_reasoning_effort",
        "data['_admin_default_model_applied'] = True",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in chat_route]
    assert not missing, f"Missing admin new-conversation default helper snippets: {missing}"

    print("✅ Admin new conversation default helper behavior verified.")


def run_tests():
    tests = [
        test_default_model_selection_wiring,
        test_admin_new_conversation_default_helper_behavior,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except AssertionError as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
