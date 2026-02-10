# test_model_endpoints_api_key_manual_models.py
#!/usr/bin/env python3
"""
Functional test for API key manual model entry in endpoint modal.
Version: 0.236.019
Implemented in: 0.236.019

This test ensures the API key flow exposes manual model entry UI,
per-model test buttons, and management cloud fields for service principal.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoints_api_key_manual_models():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    template_path = os.path.join(repo_root, 'application', 'single_app', 'templates', 'admin_settings.html')
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')

    template_content = read_file_text(template_path)
    js_content = read_file_text(js_path)
    backend_content = read_file_text(backend_path)

    assert 'id="model-endpoint-api-key-note"' in template_content, "Missing API key inference-only note."
    assert 'id="model-endpoint-add-model-btn"' in template_content, "Missing Add Model button for API key flow."
    assert 'id="model-endpoint-management-cloud"' in template_content, "Missing management cloud selector."
    assert 'id="model-endpoint-custom-authority"' in template_content, "Missing custom authority input."

    assert 'addManualModel' in js_content, "Missing manual model add handler."
    assert 'test-model' in js_content, "Missing per-model test action wiring."
    assert 'management_cloud' in js_content, "Missing management cloud payload wiring."

    assert '/api/models/test-model' in backend_content, "Missing backend test-model endpoint."

    print("✅ API key manual model entry and per-model test wiring verified.")


if __name__ == "__main__":
    test_model_endpoints_api_key_manual_models()
