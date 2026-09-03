#!/usr/bin/env python3
"""
Functional test for per-item REST on personal agents, actions and model endpoints.

Version: 0.261.041
Implemented in: 0.261.041

Before this, saving or removing one of these meant POSTing the entire collection. That is
lossy in two ways that never surface as an error: a client which omits a row deletes it, and
a client holding a stale copy silently reverts another tab's edit. This test pins the
per-item routes that replaced it, and the compatibility branch that keeps the classic
interface's whole-collection save working.

It also guards two specific defects in the personal agent delete route.

The first is an ordering bug. The route deleted the agent and *then* checked whether the
remaining agents matched `global_selected_agent`, returning 400 when none did. With that
setting unset the comparison was against None, so it matched nothing and reported failure
for a delete that had already happened -- on every delete where any agent remained. The
classic interface worked around it by never calling the route. The guard now runs before the
delete, so a refusal means nothing was removed.

The second is a missing authorization check. The collection save calls
`ensure_governance_access('governance_user_agents', ...)` but the delete did not, and neither
does `delete_personal_agent`, so a user governance had denied could still delete agents.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body(source, name):
    """Return the source of one top-level or nested def, up to the next def at its indent."""
    match = re.search(rf"^(\s*)def {re.escape(name)}\(", source, re.MULTILINE)
    assert match, f"Could not find def {name}("
    indent = match.group(1)
    start = match.start()
    following = re.compile(rf"^{indent}(?:@|def )", re.MULTILINE)
    next_match = following.search(source, match.end())
    return source[start : next_match.start() if next_match else len(source)]


def test_agent_delete_checks_before_it_deletes():
    """The guard must precede the delete, so a refusal leaves the agent in place."""
    print("Testing agent delete ordering...")

    body = _function_body(_read(APP_DIR / "route_backend_agents.py"), "delete_user_agent")

    guard = body.find("global_selected_agent")
    delete_call = body.find("delete_personal_agent(")
    assert guard != -1, "The global_selected_agent guard is gone entirely"
    assert delete_call != -1, "The route no longer deletes anything"
    assert guard < delete_call, (
        "The global_selected_agent guard must run before the delete. Checking afterwards is "
        "what made the route report 400 for work it had already done."
    )

    # And nothing may refuse the request after the record has been removed.
    after_delete = body[delete_call:]
    assert "400" not in after_delete, (
        "A 400 after the delete tells the caller the operation failed when it succeeded; "
        "that is the defect this route had."
    )

    # The specific message from the old post-delete branch must not come back.
    assert "There must be at least one agent matching" not in body, (
        "The post-delete global_selected_agent check has returned"
    )

    print("Agent delete ordering test passed!")
    return True


def test_agent_delete_enforces_governance():
    """Deleting is as destructive as saving, and the save path checks governance."""
    print("Testing agent delete governance...")

    body = _function_body(_read(APP_DIR / "route_backend_agents.py"), "delete_user_agent")

    assert "ensure_governance_access('governance_user_agents'" in body, (
        "The delete route must check governance; delete_personal_agent does not, so "
        "without this a denied user can still remove agents"
    )
    governance = body.find("ensure_governance_access")
    delete_call = body.find("delete_personal_agent(")
    assert governance < delete_call, "Governance must be checked before the delete"
    assert "403" in body, "A governance refusal should answer 403"

    print("Agent delete governance test passed!")
    return True


def test_per_item_routes_resolve_by_id_or_name():
    """New clients send ids; the classic interface still sends names."""
    print("Testing identifier resolution...")

    agents = _read(APP_DIR / "route_backend_agents.py")
    resolver = _function_body(agents, "_find_personal_agent")

    assert "agent.get('id')" in resolver, "Resolution must try the id"
    assert "agent.get('name')" in resolver, "Resolution must fall back to the name"
    assert resolver.find("agent.get('id')") < resolver.find("agent.get('name')"), (
        "The id must be tried first: GET /api/user/agents can merge personal and global "
        "agents, and names are neither unique across that set nor immutable"
    )

    # The actions container helper already accepts either, so the route just passes through.
    actions_helper = _function_body(
        _read(APP_DIR / "functions_personal_actions.py"), "delete_personal_action"
    )
    assert "OR name" in actions_helper, (
        "delete_personal_action is documented as accepting an id or a name; the route "
        "relies on that"
    )

    print("Identifier resolution test passed!")
    return True


def test_post_still_accepts_the_legacy_collection_body():
    """The classic interface saves the whole list, and must keep working."""
    print("Testing bulk compatibility...")

    agents = _function_body(_read(APP_DIR / "route_backend_agents.py"), "set_user_agents")
    plugins = _function_body(_read(APP_DIR / "route_backend_plugins.py"), "set_user_plugins")

    for name, body, creator in (
        ("agents", agents, "_create_personal_agent"),
        ("actions", plugins, "_create_personal_action"),
    ):
        assert "isinstance(payload, dict)" in body, (
            f"The {name} POST must detect an object body and create a single record"
        )
        assert creator in body, f"The {name} POST must delegate single creates to {creator}"
        assert "isinstance(payload, list)" in body, (
            f"The {name} POST must still accept an array body; workspace_agents.js and "
            f"workspace_plugins.js both save that way"
        )
        assert "deprecated" in body.lower(), (
            f"The {name} bulk form should be documented as deprecated"
        )

    endpoints = _function_body(
        _read(APP_DIR / "route_backend_models.py"), "save_user_model_endpoints"
    )
    assert '"endpoints" not in data' in endpoints, (
        "The endpoints POST must distinguish a single endpoint from the legacy "
        "{'endpoints': [...]} collection body"
    )
    assert "merge_model_endpoints_with_existing" in endpoints, (
        "The collection path must keep its merge, which preserves endpoints the frontend "
        "cannot see"
    )

    print("Bulk compatibility test passed!")
    return True


def test_endpoint_delete_cleans_up_secrets():
    """An endpoint's Key Vault secrets must not outlive it."""
    print("Testing endpoint secret cleanup...")

    models = _read(APP_DIR / "route_backend_models.py")
    persist = _function_body(models, "_persist_personal_endpoints")

    assert "keyvault_model_endpoint_delete_helper" in persist, (
        "Removing an endpoint must delete its stored secrets, or they are orphaned"
    )
    assert "keyvault_model_endpoint_cleanup_helper" in persist, (
        "A changed endpoint's superseded secret must be cleaned up"
    )

    delete_route = _function_body(models, "delete_user_model_endpoint")
    assert "ensure_governance_access" in delete_route, "Delete must check governance"
    assert "_persist_personal_endpoints" in delete_route, (
        "Delete must go through the shared persistence path so secrets are handled"
    )
    assert "404" in delete_route, "Deleting an unknown endpoint should answer 404"

    # The update path must merge server-side, since the client's copy has no secrets in it.
    patch_route = _function_body(models, "update_user_model_endpoint")
    assert "merge_model_endpoint_payload" in patch_route, (
        "PATCH must merge onto the stored endpoint; the values the client holds are "
        "sanitized, so replacing wholesale would blank the credentials"
    )

    print("Endpoint secret cleanup test passed!")
    return True


def test_new_routes_carry_the_required_decorators():
    """Repo policy: every route declares its swagger security and its auth."""
    print("Testing route decorators...")

    checks = [
        ("route_backend_agents.py", "/api/user/agents/<agent_id>"),
        ("route_backend_plugins.py", "/api/user/plugins/<action_id>"),
        ("route_backend_models.py", "/api/user/model-endpoints/<endpoint_id>"),
    ]

    for route_file, path in checks:
        source = _read(APP_DIR / route_file)
        for match in re.finditer(re.escape(path) + r"['\"],\s*methods=\[[^\]]*\]\)", source):
            trailing = source[match.end() : match.end() + 400]
            assert "@swagger_route(" in trailing, (
                f"{path} in {route_file} is missing @swagger_route"
            )
            assert "@login_required" in trailing, f"{path} in {route_file} is missing auth"
            assert "@user_required" in trailing, (
                f"{path} in {route_file} is missing @user_required"
            )

    print("Route decorator test passed!")
    return True


def test_action_delete_is_not_gated_on_the_creation_flag():
    """Removing an action must stay possible after the capability is switched off."""
    print("Testing action delete gating...")

    body = _function_body(_read(APP_DIR / "route_backend_plugins.py"), "delete_user_plugin")

    assert '@enabled_required("allow_user_plugins")' not in body, (
        "Gating delete on allow_user_plugins strands existing actions with no way to "
        "remove them once an administrator turns the capability off. Creating and editing "
        "are gated; removing only reduces what is configured."
    )
    assert "PermissionError" in body, (
        "Governance is enforced inside delete_personal_action and must be surfaced"
    )
    assert "403" in body, "A governance refusal should answer 403"

    print("Action delete gating test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.041")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_agent_delete_checks_before_it_deletes,
        test_agent_delete_enforces_governance,
        test_per_item_routes_resolve_by_id_or_name,
        test_post_still_accepts_the_legacy_collection_body,
        test_endpoint_delete_cleans_up_secrets,
        test_new_routes_carry_the_required_decorators,
        test_action_delete_is_not_gated_on_the_creation_flag,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
