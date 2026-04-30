# test_foundry_model_list_fallback.py
#!/usr/bin/env python3
"""
Functional test for Foundry project deployments discovery.
Version: 0.236.026
Implemented in: 0.236.026

This test ensures Foundry model discovery uses the project deployments list endpoint.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_foundry_model_list_fallback():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')
    content = read_file_text(backend_path)

    assert "fetch_foundry_project_deployments" in content, "Expected project deployments discovery helper."
    assert "/deployments" in content, "Expected Foundry project deployments list endpoint."
    assert "https://ai.azure.com/.default" in content, "Expected Foundry project scope for discovery token."

    print("✅ Foundry project deployments discovery verified.")


if __name__ == "__main__":
    test_foundry_model_list_fallback()
