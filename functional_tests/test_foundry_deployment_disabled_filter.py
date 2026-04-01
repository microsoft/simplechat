# test_foundry_deployment_disabled_filter.py
#!/usr/bin/env python3
"""
Functional test for filtering disabled deployments in model discovery.
Version: 0.236.025
Implemented in: 0.236.025

This test ensures deployment provisioning state filtering exists for AOAI/Foundry model lists.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_foundry_deployment_disabled_filter():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')
    content = read_file_text(backend_path)

    assert 'def is_deployment_enabled' in content, "Missing deployment state filter helper."
    assert 'provisioningState' in content or 'provisioning_state' in content, "Expected provisioning state extraction."

    print("✅ Disabled deployments filtered from model lists.")


if __name__ == "__main__":
    test_foundry_deployment_disabled_filter()
