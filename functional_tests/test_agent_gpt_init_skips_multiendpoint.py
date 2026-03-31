# test_agent_gpt_init_skips_multiendpoint.py
#!/usr/bin/env python3
"""
Functional test for agent streaming default model resolution.
Version: 0.239.200
Implemented in: 0.239.200

This test ensures agent streaming requests can use the default multi-endpoint
model selection when explicit model fields are not provided.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_agent_gpt_init_gating():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    chat_path = os.path.join(repo_root, "application", "single_app", "route_backend_chats.py")

    chat_content = read_file_text(chat_path)

    assert "resolve_streaming_multi_endpoint_gpt_config" in chat_content, (
        "Expected streaming requests to use the multi-endpoint resolver."
    )
    assert "Using default multi-endpoint model for agent streaming request." in chat_content, (
        "Expected agent streaming requests without model info to use the saved default selection."
    )
    assert "allow_default_selection=should_use_default_model" in chat_content, (
        "Expected the streaming route to wire default model selection through the multi-endpoint resolver."
    )

    print("✅ Agent streaming default model resolution verified.")


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
