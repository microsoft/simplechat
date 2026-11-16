# test_storage_container_repair_policy.py
"""Admin-only Blueprint and Swagger policy for explicit storage container repair.

Version: 0.261.396
Implemented in: 0.261.396
"""

from test_route_unauthenticated_policy_contract import expected_policy, iter_route_functions


def test_storage_repair_is_explicit_admin_post():
    matches = [
        route for route in iter_route_functions()
        if route.path == "/api/admin/settings/storage/repair-containers"
    ]
    assert len(matches) == 1
    route = matches[0]
    assert route.file_name == "route_backend_settings.py"
    assert route.route_target == "bp"
    assert route.decorator_names == ("bp.route", "swagger_route", "login_required", "admin_required")
    assert expected_policy(route.path) == "session_admin_401_or_redirect"
