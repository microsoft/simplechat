# test_group_model_endpoint_membership_guard.py
"""
Functional test for group model endpoint membership enforcement.
Version: 0.239.188
Implemented in: 0.239.188

This test ensures the group model endpoint read route validates current
group membership before returning sanitized endpoint metadata.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_group_model_endpoint_read_requires_current_membership():
    """Ensure the group model endpoint GET route verifies current membership."""
    print("🔍 Validating group model endpoint read authorization...")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_path = os.path.join(repo_root, "application", "single_app", "route_backend_models.py")
    backend_content = read_file_text(backend_path)

    route_block_start = backend_content.index("def get_group_model_endpoints_route():")
    route_block_end = backend_content.index("@app.route('/api/group/model-endpoints', methods=['POST'])")
    route_block = backend_content[route_block_start:route_block_end]

    expected_guard = '''        assert_group_role(
                user_id,
                group_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )'''

    assert expected_guard in route_block, (
        "Group model endpoint GET route must enforce membership using read-allowed group roles."
    )
    assert "except LookupError as exc:" in route_block, (
        "Group model endpoint GET route must translate missing groups into a 404 response."
    )
    assert "except PermissionError as exc:" in route_block, (
        "Group model endpoint GET route must translate non-members into a 403 response."
    )

    print("✅ Group model endpoint read authorization passed.")


if __name__ == "__main__":
    test_group_model_endpoint_read_requires_current_membership()