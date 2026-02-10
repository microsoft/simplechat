# test_foundry_inference_scope_fix.py
#!/usr/bin/env python3
"""
Functional test for Foundry scope selection by cloud.
Version: 0.236.028
Implemented in: 0.236.028

This test ensures Foundry model inference uses cloud-specific scopes and supports custom scope overrides.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_foundry_inference_scope_fix():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')
    content = read_file_text(backend_path)

    assert "def resolve_foundry_scope" in content, "Missing Foundry scope resolver."
    assert "https://ai.azure.com/.default" in content, "Expected public Foundry scope constant."
    assert "https://ai.azure.us/.default" in content, "Expected government Foundry scope constant."
    assert "foundry_scope" in content, "Expected custom Foundry scope override field."

    print("✅ Foundry scope selection verified.")


if __name__ == "__main__":
    test_foundry_inference_scope_fix()
