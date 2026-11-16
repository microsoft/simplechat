# test_personal_identity_transport.py
"""
Native personal identity URLs cannot fall through to classic mutation routes.
Version: 0.261.315
Implemented in: 0.261.315
"""

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/user/identities"), ("POST", "/api/user/identities"),
    ("GET", "/api/user/identities/identity-id"),
    ("PATCH", "/api/user/identities/identity-id"),
    ("DELETE", "/api/user/identities/identity-id"),
])
def test_native_personal_identity_url_does_not_match_classic_routes(method, path):
    routes = [route for route in iter_route_functions() if not route.path.startswith("/api/user/identities")]
    paths = {route.path for route in routes}
    assert "/api/workspace-identities/personal/identities" in paths
    assert "/api/workspace-identities/personal/identities/<identity_id>" in paths
    router = Map([Rule(route.path, endpoint=f"classic-{index}") for index, route in enumerate(routes)]).bind("simplechat.test")
    with pytest.raises(NotFound):
        router.match(path, method=method)
