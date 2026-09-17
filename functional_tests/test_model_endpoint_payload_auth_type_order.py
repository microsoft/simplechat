# test_model_endpoint_payload_auth_type_order.py
#!/usr/bin/env python3
"""
Functional test for model endpoint payload auth type ordering.
Version: 0.261.108
Implemented in: 0.236.020; updated in 0.261.106

This test ensures authType is defined before validation checks in buildEndpointPayload,
so per-model test and fetch actions do not throw a reference error. The check is
scoped to the payload builder and accepts its conditional custom-provider auth
assignment and shared Foundry-provider helper.
"""

import os
import re


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoint_payload_auth_type_order():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')

    content = read_file_text(js_path)
    payload_match = re.search(
        r"^function buildEndpointPayload\([^)]*\)\s*\{.*?(?=^(?:async\s+)?function\s|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert payload_match is not None, "Expected the buildEndpointPayload function."
    payload_source = payload_match.group(0)
    auth_type = re.search(r"\b(?:const|let|var)\s+authType\s*=", payload_source)
    foundry_check = re.search(
        r"\bisFoundryProvider\s*\(\s*provider\s*\)\s*&&\s*authType\b",
        payload_source,
    )
    aoai_check = re.search(
        r"\bprovider\s*===\s*['\"]aoai['\"]\s*&&\s*authType\b",
        payload_source,
    )

    assert auth_type is not None, "Expected authType assignment in buildEndpointPayload."
    assert foundry_check is not None, "Expected Foundry validation using authType."
    assert aoai_check is not None, "Expected AOAI validation using authType."
    assert auth_type.start() < foundry_check.start(), "authType must be defined before Foundry validation."
    assert auth_type.start() < aoai_check.start(), "authType must be defined before AOAI validation."

    print("✅ buildEndpointPayload defines authType before validation checks.")


if __name__ == "__main__":
    test_model_endpoint_payload_auth_type_order()
