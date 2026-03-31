# test_model_endpoint_scope_gate_enforcement.py
#!/usr/bin/env python3
"""
Functional test for user and group model endpoint scope enforcement.
Version: 0.239.187
Implemented in: 0.239.187

This test ensures non-admin model fetch and test routes require the
custom-endpoint feature gates while still allowing pre-save fetch/test
requests and restricting persisted endpoint IDs to authorized endpoints.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoint_scope_gate_enforcement():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')

    backend_content = read_file_text(backend_path)

    assert 'if scope in ("user", "group") and endpoint_id:' in backend_content, (
        "User/group persisted endpoint validation should only apply when an endpoint_id is supplied."
    )
    assert "raise LookupError(\"Model endpoint not found.\")" in backend_content, (
        "User/group model routes must reject unknown endpoint IDs."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint or {}, payload)' in backend_content, (
        "Feature-gated user/group model routes should still accept ad hoc payloads for pre-save fetch/test flows."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint, {})' in backend_content, (
        "User/group requests that reference a saved endpoint must resolve persisted endpoint configuration."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def fetch_model_list_user():" in backend_content, (
        "User model fetch route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def test_model_connection_user():" in backend_content, (
        "User model test route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def fetch_model_list_group():" in backend_content, (
        "Group model fetch route must require allow_group_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def test_model_connection_group():" in backend_content, (
        "Group model test route must require allow_group_custom_endpoints."
    )

    print("✅ Model endpoint scope gates, pre-save fetch/test flow, and persisted-endpoint enforcement verified.")


if __name__ == "__main__":
    test_model_endpoint_scope_gate_enforcement()