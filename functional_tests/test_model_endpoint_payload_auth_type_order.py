# test_model_endpoint_payload_auth_type_order.py
#!/usr/bin/env python3
"""
Functional test for model endpoint payload auth type ordering.
Version: 0.236.020
Implemented in: 0.236.020

This test ensures authType is defined before validation checks in buildEndpointPayload,
so per-model test and fetch actions do not throw a reference error.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoint_payload_auth_type_order():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')

    content = read_file_text(js_path)
    auth_type_index = content.find("const authType = endpointAuthTypeSelect")
    foundry_check_index = content.find("provider === \"aifoundry\" && authType")
    aoai_check_index = content.find("provider === \"aoai\" && authType")

    assert auth_type_index != -1, "Expected authType assignment in buildEndpointPayload."
    assert foundry_check_index != -1, "Expected Foundry validation using authType."
    assert aoai_check_index != -1, "Expected AOAI validation using authType."
    assert auth_type_index < foundry_check_index, "authType must be defined before Foundry validation."
    assert auth_type_index < aoai_check_index, "authType must be defined before AOAI validation."

    print("✅ buildEndpointPayload defines authType before validation checks.")


if __name__ == "__main__":
    test_model_endpoint_payload_auth_type_order()
