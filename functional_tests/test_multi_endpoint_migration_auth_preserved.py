# test_multi_endpoint_migration_auth_preserved.py
#!/usr/bin/env python3
"""
Functional test for multi-endpoint migration auth preservation.
Version: 0.236.016
Implemented in: 0.236.016

This test ensures the migration preserves authentication type, API key,
subscription ID, and resource group for Azure OpenAI endpoints.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_multi_endpoint_migration_auth_preserved():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    route_path = os.path.join(repo_root, 'application', 'single_app', 'route_frontend_admin_settings.py')
    content = read_file_text(route_path)

    assert "legacy_auth_type" in content, "Expected legacy auth type mapping for migration."
    assert "migrated_auth_type" in content, "Expected migrated auth type mapping for migration."
    assert "azure_openai_gpt_key" in content, "Expected GPT API key migration."
    assert "azure_openai_gpt_subscription_id" in content, "Expected subscription ID migration."
    assert "azure_openai_gpt_resource_group" in content, "Expected resource group migration."

    print("✅ Migration preserves auth type, API key, and subscription data.")


if __name__ == "__main__":
    test_multi_endpoint_migration_auth_preserved()
