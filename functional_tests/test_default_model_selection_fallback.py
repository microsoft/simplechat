# test_default_model_selection_fallback.py
#!/usr/bin/env python3
"""
Functional test for default model selection fallback.
Version: 0.236.053
Implemented in: 0.236.053

This test ensures default model selection is surfaced in admin settings
and used for fallback GPT initialization when agent requests omit model info.
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

    admin_template = read_file_text(admin_template_path)
    admin_route = read_file_text(admin_route_path)
    chat_route = read_file_text(chat_path)

    assert "default_model_selection_json" in admin_template, (
        "Expected default model selection input in admin settings template."
    )
    assert "default-model-selection" in admin_template, (
        "Expected default model selection dropdown in admin settings template."
    )
    assert "default_model_selection" in admin_route, (
        "Expected default model selection to be handled in admin settings save." 
    )
    assert "resolve_default_model_gpt_config" in chat_route, (
        "Expected default model fallback logic in chat route."
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
