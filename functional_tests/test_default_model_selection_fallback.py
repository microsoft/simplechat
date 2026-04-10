# test_default_model_selection_fallback.py
#!/usr/bin/env python3
"""
Functional test for default model selection fallback.
Version: 0.240.073
Implemented in: 0.240.071

This test ensures default model selection is surfaced in admin settings
and used for fallback GPT initialization when legacy agents omit or lose
multi-endpoint model bindings.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


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
    config_path = os.path.join(
        repo_root, "application", "single_app", "config.py"
    )

    admin_template = read_file_text(admin_template_path)
    admin_route = read_file_text(admin_route_path)
    chat_route = read_file_text(chat_path)
    loader_content = read_file_text(loader_path)
    config_content = read_file_text(config_path)

    assert "default_model_selection_json" in admin_template, (
        "Expected default model selection input in admin settings template."
    )
    assert "default-model-selection" in admin_template, (
        "Expected default model selection dropdown in admin settings template."
    )
    assert "default_model_selection" in admin_route, (
        "Expected default model selection to be handled in admin settings save." 
    )
    assert "resolve_streaming_multi_endpoint_gpt_config" in chat_route, (
        "Expected streaming default model fallback logic in chat route."
    )
    assert "settings.get('default_model_selection'" in chat_route, (
        "Expected streaming model resolution to read the saved default model selection."
    )
    assert 'can_agent_use_default_multi_endpoint_model' in loader_content, (
        "Expected the shared agent loader to gate default-model fallback to inherited agents."
    )
    assert 'Using saved admin default multi-endpoint model for agent' in loader_content, (
        "Expected the shared agent loader to use the saved admin default model when agent bindings are missing or stale."
    )
    assert 'VERSION = "0.240.073"' in config_content, (
        "Expected config.py version 0.240.073 after the loader fallback and migration UI updates."
    )

    print("✅ Default model selection wiring verified.")


def run_tests():
    tests = [test_default_model_selection_wiring]
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
