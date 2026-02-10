# test_model_endpoints_aoai_fetch_fix.py
#!/usr/bin/env python3
"""
Functional test for Azure OpenAI model discovery in multi-endpoint modal.
Version: 0.236.015
Implemented in: 0.236.015

This test ensures AOAI model discovery wiring includes resource group input in the modal,
payload support in admin JS, and backend handling for AOAI in the models fetch route.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoints_aoai_fetch_fix():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    template_path = os.path.join(repo_root, 'application', 'single_app', 'templates', 'admin_settings.html')
    admin_js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')
    models_route_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')

    template_content = read_file_text(template_path)
    admin_js_content = read_file_text(admin_js_path)
    route_content = read_file_text(models_route_path)

    assert 'id="model-endpoint-resource-group"' in template_content, "Resource group input missing from endpoint modal."
    assert 'resource_group' in admin_js_content, "Admin endpoint payload missing resource_group handling."
    assert 'provider == "aoai"' in route_content, "AOAI handling missing in model fetch route."
    assert 'resource_group' in route_content, "Backend AOAI discovery missing resource group requirement."

    print("✅ AOAI model discovery wiring validated.")


if __name__ == "__main__":
    test_model_endpoints_aoai_fetch_fix()
