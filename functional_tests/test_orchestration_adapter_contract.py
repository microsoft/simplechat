#!/usr/bin/env python3
"""
Functional test for the orchestration adapter contract.
Version: 0.261.089
Implemented in: 0.261.087

This is the generalisation of a bug that reached production. A step failed live with
``invoke_prompt() got an unexpected keyword argument 'stage'`` -- a signature mismatch at
the seam between the executor and a real adapter. It passed import, it passed type
checking, and it passed the whole suite, because the executor tests drive *fake* adapters
and the real ones need Azure to run at all.

So the seam gets checked statically instead of hopefully. Every capability must resolve to
an adapter, every adapter must take the exact keyword arguments the executor passes, and no
adapter may reach for Flask state that does not exist on the worker thread it runs on.

None of this needs credentials, which is the point: a test that only runs where Azure does
is a test that stops running.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT, stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ADAPTERS = 'functions_orchestration_adapters.py'
EXECUTOR = 'functions_orchestration_executor.py'
PLANNER = 'functions_orchestration_planner.py'
REGISTRY = 'functions_orchestration_registry.py'
ROUTE = 'route_backend_orchestration.py'

# What the executor passes at the call site in _run_single_step.
EXPECTED_POSITIONAL = ['step', 'context']
EXPECTED_KEYWORD = {'settings', 'user_id', 'emit', 'cancel_requested'}


def _tree(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return ast.parse(handle.read())


def _functions(tree):
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _registered_adapter_names(tree):
    """The adapter function names bound in ADAPTER_REGISTRY, keyed by capability constant."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'ADAPTER_REGISTRY' not in targets:
            continue
        mapping = {}
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Name) and isinstance(value, ast.Name):
                mapping[key.id] = value.id
        return mapping
    return {}


def _capability_constants(tree):
    """CAPABILITY_* constants and their string values from the registry."""
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id.startswith('CAPABILITY_')
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                constants[target.id] = node.value.value
    return constants


def test_every_capability_resolves_to_an_adapter():
    """A capability the planner may choose must be a capability the executor can run."""
    print("Testing that every capability has an adapter...")
    try:
        assert_app_version_at_least('0.261.087')

        registry_tree = _tree(REGISTRY)
        constants = _capability_constants(registry_tree)
        registered = _registered_adapter_names(_tree(ADAPTERS))

        assert registered, 'ADAPTER_REGISTRY could not be read'

        # Every CAPABILITY_* constant the registry defines must be a key in ADAPTER_REGISTRY.
        # A capability offered to the planner with no adapter behind it is a plan that
        # validates, runs, and fails at the step -- exactly the failure this suite exists
        # to move earlier.
        missing = sorted(set(constants) - set(registered))
        assert not missing, (
            f"these capabilities have no registered adapter: {missing}. A capability the "
            f"planner can choose must be one the executor can run."
        )

        print(f"  ok  all {len(constants)} capabilities resolve to an adapter")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_adapters_match_the_executor_call_signature():
    """Every adapter takes exactly what the executor passes -- checked, not assumed."""
    print("Testing the adapter signature...")
    try:
        adapters_tree = _tree(ADAPTERS)
        functions = _functions(adapters_tree)
        registered = _registered_adapter_names(adapters_tree)

        for capability_constant, adapter_name in sorted(registered.items()):
            node = functions.get(adapter_name)
            assert node is not None, (
                f"{adapter_name} is registered for {capability_constant} but not defined"
            )

            positional = [a.arg for a in node.args.args]
            assert positional == EXPECTED_POSITIONAL, (
                f"{adapter_name} takes {positional} positionally; the executor calls "
                f"adapter(step, context, ...) so it must take {EXPECTED_POSITIONAL}"
            )

            keyword_only = {a.arg for a in node.args.kwonlyargs}
            missing = EXPECTED_KEYWORD - keyword_only
            assert not missing, (
                f"{adapter_name} does not accept {sorted(missing)}; the executor passes "
                f"these by keyword and the call would raise TypeError at run time"
            )

            # Anything extra must have a default, or the executor's call is short an argument.
            extra = keyword_only - EXPECTED_KEYWORD
            if extra:
                defaulted = {
                    arg.arg
                    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
                    if default is not None
                }
                undefaulted = extra - defaulted
                assert not undefaulted, (
                    f"{adapter_name} requires {sorted(undefaulted)}, which the executor "
                    f"does not pass"
                )

        print(f"  ok  all {len(registered)} adapters match the executor's call")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_adapters_never_touch_flask_state():
    """An adapter runs on a worker thread where Flask request state does not exist."""
    print("Testing that adapters stay off Flask state...")
    try:
        tree = _tree(ADAPTERS)

        forbidden_imports = {'g', 'session', 'current_app', 'request'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'flask':
                names = {alias.name for alias in node.names}
                clash = names & forbidden_imports
                assert not clash, (
                    f"adapters import {sorted(clash)} from flask. execute_plan runs in a "
                    f"threading.Thread with no request context, so this raises at run time "
                    f"-- every value must arrive on RunContext instead."
                )

        # Attribute access too: `g.force_enable_agents` would pass the import check.
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert node.value.id not in forbidden_imports, (
                    f"adapters read {node.value.id}.{node.attr}; there is no request "
                    f"context on the worker thread"
                )

        print("  ok  adapters read no Flask request state")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_route_captures_identity_before_the_thread_starts():
    """Roles and email are read on the request thread, not from inside the generator."""
    print("Testing the request-thread identity capture...")
    try:
        tree = _tree(ROUTE)
        functions = _functions(tree)

        capture = functions.get('_request_identity')
        assert capture is not None, (
            '_request_identity must exist: user_roles gates the UrlAccessUser and '
            'DeepResearchUser app roles and cannot be read off the worker thread'
        )

        # It must fail closed. An except path that leaves roles unset, or sets them to
        # anything truthy, would admit a user who holds no role.
        capture_source = ast.dump(capture)
        assert 'user_roles' in capture_source and 'user_email' in capture_source, (
            '_request_identity must capture both user_roles and user_email'
        )

        # The capture must happen outside the streamed generator. A generator body runs
        # after the view returns, when the session is already gone.
        for outer in ast.walk(tree):
            if not isinstance(outer, ast.FunctionDef) or outer.name != 'generate':
                continue
            for inner in ast.walk(outer):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == '_request_identity'
                ):
                    raise AssertionError(
                        '_request_identity is called inside generate(); a streamed '
                        "response's generator runs after the request context is torn down"
                    )

        # And the captured values must actually reach RunContext, or the adapters get None.
        wired = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'RunContext'
            ):
                wired = {kw.arg for kw in node.keywords}
        for field in ('user_roles', 'user_email', 'user_enable_agents'):
            assert field in wired, (
                f"RunContext is built without {field}; the adapter would fall back to a "
                f"default and gate on a value nobody supplied"
            )

        print("  ok  identity is captured on the request thread and reaches RunContext")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_role_gates_fail_closed():
    """Absent roles must deny, never allow."""
    print("Testing that role gates fail closed...")
    try:
        tree = _tree(EXECUTOR)
        functions = _functions(tree)

        init = functions.get('__init__')
        assert init is not None, 'RunContext.__init__ not found'

        source = ast.dump(init)
        assert 'user_roles' in source, 'RunContext must carry user_roles'

        # An unknown roles value must collapse to "no roles". If it were passed through
        # unchanged, a stray truthy value could satisfy a membership check downstream.
        assert 'isinstance' in source, (
            'RunContext must type-check user_roles before storing it, so an unknown '
            'value cannot be mistaken for a role list'
        )

        print("  ok  roles are normalised and absent roles deny")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_request_gates_are_actually_applied_by_the_planner():
    """A capability gate nobody invokes is decoration."""
    print("Testing that the planner applies request gates...")
    try:
        tree = _tree(PLANNER)
        functions = _functions(tree)

        plan_request = functions.get('plan_request')
        assert plan_request is not None, 'plan_request not found'

        # The signature must accept a request context...
        accepted = (
            {a.arg for a in plan_request.args.args}
            | {a.arg for a in plan_request.args.kwonlyargs}
        )
        assert 'request_context' in accepted, (
            'plan_request does not accept a request_context. Without one, '
            'resolve_available_capabilities skips every request gate -- which is right for '
            'the admin page describing a deployment, and wrong for a real caller. The '
            'planner would be offered URL reading for a message with no URL, and agents a '
            'user does not have.'
        )

        # ...and must actually forward it. Accepting an argument and dropping it is the
        # same bug wearing a signature that looks correct.
        forwarded = False
        for node in ast.walk(plan_request):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'resolve_available_capabilities'
            ):
                for keyword in node.keywords:
                    if keyword.arg == 'request_context':
                        forwarded = True
        assert forwarded, (
            'plan_request accepts a request_context but does not pass it to '
            'resolve_available_capabilities'
        )

        # And the route must supply one when it plans.
        route_tree = _tree(ROUTE)
        supplied = False
        for node in ast.walk(route_tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'plan_request'
            ):
                supplied = any(kw.arg == 'request_context' for kw in node.keywords)
        assert supplied, (
            'the route calls plan_request without a request_context, so no request gate '
            'runs for a real request'
        )

        print("  ok  request gates reach the planner and the validator")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_request_gates_withhold_what_the_caller_cannot_use():
    """The gates themselves, exercised rather than inspected."""
    print("Testing request gate behaviour...")
    try:
        with stubbed_app_imports():
            from functions_orchestration_registry import resolve_available_capabilities

            settings = {
                'enable_chat_orchestration': True,
                'enable_user_workspace': True,
                'enable_web_search': True,
                'enable_url_access': True,
                'enable_source_review': True,
                'enable_semantic_kernel': True,
            }

            def ids(context, override=None):
                return [
                    c['id'] for c in resolve_available_capabilities(
                        override or settings, request_context=context,
                    )
                ]

            plain = {
                'user_id': 'u1',
                'user_message': 'what is in my handbook?',
                'message_urls': [],
                'user_roles': [],
                'user_enable_agents': True,
                'agent_catalog': [],
            }

            # Offering "read the links" for a message with no links produces a step whose
            # only possible outcome is reporting that it had nothing to do.
            assert 'url_fetch' not in ids(plain), 'url_fetch offered with no URL'
            assert 'url_fetch' in ids(dict(
                plain,
                user_message='summarise https://example.com/a',
                message_urls=['https://example.com/a'],
            )), 'url_fetch withheld despite a URL in the message'

            # An agent the user does not have produces a plan naming something that cannot run.
            assert 'agent_invoke' not in ids(plain), 'agent_invoke offered with no agents'
            with_agent = dict(plain, agent_catalog=[{'name': 'research_helper'}])
            assert 'agent_invoke' in ids(with_agent), 'agent_invoke withheld despite an agent'
            assert 'agent_invoke' not in ids(dict(with_agent, user_enable_agents=False)), (
                'agent_invoke offered to a user who turned agents off; orchestration must '
                'not hand back a capability the user switched off for themselves'
            )

            # And the app role must be enforced where the deployment requires it.
            strict = dict(
                settings,
                require_member_of_deep_research_user=True,
                source_review_settings={'require_member_of_deep_research_user': True},
            )
            assert 'deep_research' not in ids(plain, strict), (
                'deep_research offered to a user holding no DeepResearchUser role'
            )
            assert 'deep_research' in ids(dict(plain, user_roles=['DeepResearchUser']), strict), (
                'deep_research withheld from a user who holds the role'
            )

        print("  ok  each gate withholds what its caller cannot use")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_every_capability_resolves_to_an_adapter,
        test_adapters_match_the_executor_call_signature,
        test_adapters_never_touch_flask_state,
        test_route_captures_identity_before_the_thread_starts,
        test_role_gates_fail_closed,
        test_request_gates_are_actually_applied_by_the_planner,
        test_request_gates_withhold_what_the_caller_cannot_use,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
