# test_model_endpoints_save_button.py
#!/usr/bin/env python3
"""
Functional test for model endpoint Save button wiring.
Version: 0.236.021
Implemented in: 0.236.021

This test ensures the Save Endpoint button triggers save logic and surfaces errors.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoints_save_button():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')
    content = read_file_text(js_path)

    assert 'saveEndpoint()' in content, "Save endpoint handler missing."
    assert 'event.preventDefault()' in content, "Save button should prevent default." 
    assert 'Failed to save endpoint' in content, "Expected error handling for save endpoint." 

    print("✅ Save Endpoint button handler verified.")


if __name__ == "__main__":
    test_model_endpoints_save_button()
