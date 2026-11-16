# test_control_center_orchestration_roles.py
"""
Functional test for authenticated Control Center roles in orchestration workers.
Version: 0.261.329
Implemented in: 0.261.329

The real external-source provider, action catalog and exact manifest resolver run
without a Flask request context. Signed-in roles must reach both authorization
boundaries before execution, on admission and on fresh-provider retained reads.
Current access changes still refuse the action; saved or ambient roles cannot
grant access. Existing storage fixtures block networking and restore module seams.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sys
from unittest.mock import Mock, patch

import pytest
from flask import Flask, has_request_context, session

from test_orchestration_external_sources import ExternalSourceWorld
from test_v2_control_center_action import _auth_functions
from functions_action_catalog import _action_ref, build_accessible_action_catalog, resolve_action_manifest
from functions_orchestration_context import resolve_action_catalog
from functions_orchestration_results import ResultUnavailableError
from test_support.versioning import assert_app_version_at_least


@pytest.fixture
def control_center_world():
    with ExternalSourceWorld("action_invoke") as world:
        world.roles = ("Admin",)
        world.settings.update(
            per_user_semantic_kernel=False, allow_user_plugins=False, allow_group_plugins=False,
        )
        world.control_center_action = world.services.add("actions", "global", "global", {
            "id": "control-center", "name": "Control Center", "type": "control_center", "is_enabled": True,
        })
        world.services.add("actions", "global", "global", {
            "id": "tickets", "name": "Tickets", "type": "openapi", "is_enabled": True,
        })
        world.action_selector = _action_ref("global", "global", "control-center")
        world.run["plan"]["steps"][0]["arguments"]["action_ref"] = world.action_selector
        world.services.containers["actions", "global"].query_items.side_effect = lambda **_kwargs: [
            deepcopy(action) for action in world.services.records["actions", "global"].values()
        ]
        world.services.governance.filter_governed_global_actions_for_user = Mock(
            side_effect=lambda _actor, actions: [
                action for action in actions if action["id"] not in world.services.denied_actions
            ],
        )
        world.stack.enter_context(patch.dict(sys.modules, {"functions_authentication": _auth_functions()}))
        yield world


def provider(world, **overrides):
    return world.provider(**{
        "action_catalog_reader": resolve_action_catalog,
        "action_resolver": resolve_action_manifest,
        **overrides,
    })


def saved_output(world, current):
    admitted = world.admit(current)
    service = world.service(current, admitted)
    task = world.persist(service, admitted)
    return task.output("prepared")


def read_output(world, current, output):
    return world.service(current).open_result(output, require_current_sources=True).read_value()


def test_version_includes_control_center_role_propagation():
    assert_app_version_at_least("0.261.329")


@pytest.mark.parametrize(("roles", "settings"), [
    (("Admin",), {}),
    (("User", "ControlCenterAdmin"), {"require_member_of_control_center_admin": True}),
    (("User", "ControlCenterDashboardReader"), {
        "require_member_of_control_center_admin": True,
        "require_member_of_control_center_dashboard_reader": True,
    }),
])
def test_worker_can_preflight_admit_and_reopen_control_center_results(control_center_world, roles, settings):
    world = control_center_world
    world.roles = roles
    world.settings.update(settings)
    catalog_reader = Mock(wraps=resolve_action_catalog)
    resolver = Mock(wraps=resolve_action_manifest)

    def worker():
        if has_request_context():
            raise AssertionError("The worker must not inherit a Flask request context.")
        current = provider(world, action_catalog_reader=catalog_reader, action_resolver=resolver)
        world.preflight(current)
        current.preflight_session_acquisition(
            "action", producer=world.fixture.producer, selector=world.action_selector,
        )
        output = saved_output(world, current)
        return read_output(
            world, provider(world, action_catalog_reader=catalog_reader, action_resolver=resolver), output,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        retained = executor.submit(worker).result()

    assert retained == world.prepared
    assert catalog_reader.call_count >= 4
    assert resolver.call_count >= 4
    assert all(call.kwargs["user_roles"] == list(roles) for call in catalog_reader.call_args_list)
    assert all(call.kwargs["user_roles"] == list(roles) for call in resolver.call_args_list)


def test_exact_resolution_receives_roles_independently_of_catalog_discovery(control_center_world):
    world = control_center_world
    catalog = build_accessible_action_catalog(
        "owner", settings=world.settings, user_roles=list(world.roles),
    )
    resolver = Mock(wraps=resolve_action_manifest)
    current = provider(world, action_catalog_reader=Mock(return_value=catalog), action_resolver=resolver)

    world.preflight(current)

    assert resolver.call_count == 1
    assert resolver.call_args.kwargs["user_roles"] == ["Admin"]


def test_exact_resolution_refuses_a_stale_catalog_after_dashboard_access_changes(control_center_world):
    world = control_center_world
    catalog = build_accessible_action_catalog(
        "owner", settings=world.settings, user_roles=list(world.roles),
    )
    world.roles = ("User",)
    resolver = Mock(wraps=resolve_action_manifest)
    current = provider(world, action_catalog_reader=Mock(return_value=catalog), action_resolver=resolver)

    with pytest.raises(ResultUnavailableError) as raised:
        world.preflight(current)

    assert raised.value.refusal_check == "integration_access_denied"
    assert resolver.call_args.kwargs["user_roles"] == ["User"]


@pytest.mark.parametrize(("roles", "settings"), [
    (("User",), {}),
    ((), {}),
    (("User", "ControlCenterDashboardReader"), {}),
    (("Admin",), {"require_member_of_control_center_admin": True}),
])
def test_roles_without_dashboard_access_are_refused(control_center_world, roles, settings):
    world = control_center_world
    world.roles = roles
    world.settings.update(settings)
    resolver = Mock(wraps=resolve_action_manifest)
    current = provider(world, action_resolver=resolver)

    with pytest.raises(ResultUnavailableError):
        world.preflight(current)
    with pytest.raises(ResultUnavailableError):
        world.admit(current)

    resolver.assert_not_called()


def test_saved_and_ambient_admin_roles_cannot_override_the_authenticated_identity(control_center_world):
    world = control_center_world
    world.roles = ("User",)
    world.run["user_roles"] = ["Admin"]
    world.run["plan"]["user_roles"] = ["Admin"]
    catalog_reader = Mock(wraps=resolve_action_catalog)
    current = provider(world, action_catalog_reader=catalog_reader)
    app = Flask("control_center_role_authority_test")
    app.secret_key = "test-only"

    with app.test_request_context("/"):
        session["user"] = {"oid": "owner", "roles": ["Admin"]}
        with pytest.raises(ResultUnavailableError) as raised:
            world.preflight(current)

    assert raised.value.code == "result_external_source_unavailable"
    assert catalog_reader.call_args.kwargs["user_roles"] == ["User"]


@pytest.mark.parametrize("change", [
    "roles", "no_session_roles", "disabled", "deleted", "governance", "dashboard_role_setting",
])
def test_current_access_changes_refuse_preflight_and_fresh_retained_reads(control_center_world, change):
    world = control_center_world
    current = provider(world)
    world.preflight(current)
    output = saved_output(world, current)
    retained = read_output(world, provider(world), output)
    assert retained == world.prepared

    if change == "roles":
        world.roles = ("User",)
    elif change == "no_session_roles":
        world.roles = ()
    elif change == "disabled":
        world.control_center_action["is_enabled"] = False
    elif change == "deleted":
        del world.services.records["actions", "global"]["control-center", "control-center"]
    elif change == "governance":
        world.services.denied_actions.add("control-center")
    elif change == "dashboard_role_setting":
        world.settings["require_member_of_control_center_admin"] = True
    else:
        raise AssertionError("Unknown access change.")

    with pytest.raises(ResultUnavailableError):
        world.preflight(current)
    with pytest.raises(ResultUnavailableError):
        read_output(world, provider(world), output)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
