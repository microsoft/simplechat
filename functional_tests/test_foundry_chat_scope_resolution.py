# test_foundry_chat_scope_resolution.py
#!/usr/bin/env python3
"""
Functional test for Foundry chat scope resolution.
Version: 0.236.030
Implemented in: 0.236.030

This test ensures multi-endpoint chat inference uses cloud-aware Foundry scopes.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_foundry_chat_scope_resolution():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_chats.py')
    content = read_file_text(backend_path)

    assert "def resolve_foundry_scope_for_auth" in content, "Missing Foundry scope resolver for chat routes."
    assert "https://ai.azure.com/.default" in content, "Expected public Foundry scope constant."
    assert "https://ai.azure.us/.default" in content, "Expected government Foundry scope constant."
    assert "foundry_scope" in content, "Expected custom Foundry scope override field."
    assert "Multi-endpoint SP scope" in content, "Expected Foundry scope debug logging for service principal."

    print("✅ Foundry chat scope resolution verified.")


if __name__ == "__main__":
    test_foundry_chat_scope_resolution()
