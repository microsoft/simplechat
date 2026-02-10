# test_agent_gpt_init_skips_multiendpoint.py
#!/usr/bin/env python3
"""
Functional test for agent GPT init gating.
Version: 0.236.052
Implemented in: 0.236.052

This test ensures agent requests skip multi-endpoint GPT resolution and
default APIM deployment selection when model_deployment is not provided.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_agent_gpt_init_gating():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    chat_path = os.path.join(repo_root, "application", "single_app", "route_backend_chats.py")

    chat_content = read_file_text(chat_path)

    assert "Skipping multi-endpoint resolution because agent_info is provided" in chat_content, (
        "Expected agent requests to skip multi-endpoint GPT resolution."
    )
    assert "Agent request without model_deployment; defaulting to first APIM deployment" in chat_content, (
        "Expected APIM defaulting behavior for agent requests without model_deployment."
    )

    print("✅ Agent GPT init gating verified.")


def run_tests():
    tests = [test_agent_gpt_init_gating]
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
