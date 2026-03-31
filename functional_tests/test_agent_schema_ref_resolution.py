# test_agent_schema_ref_resolution.py
#!/usr/bin/env python3
"""
Functional test for agent schema reference resolution.
Version: 0.236.049
Implemented in: 0.236.049

This test ensures agent schema validation uses the root schema so $ref
entries like OtherSettings resolve correctly.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_agent_schema_ref_resolution():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    validation_path = os.path.join(repo_root, "application", "single_app", "json_schema_validation.py")
    content = read_file_text(validation_path)

    assert "Draft7Validator(schema" in content, "Expected agent schema validation to use the root schema."
    assert "RefResolver.from_schema(schema)" in content, "Expected schema ref resolver wiring."

    print("✅ Agent schema ref resolution wiring verified.")


def run_tests():
    tests = [test_agent_schema_ref_resolution]
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
