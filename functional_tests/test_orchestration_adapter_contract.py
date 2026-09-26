# test_orchestration_adapter_contract.py
"""
Functional test for the orchestration adapter contract.
Version: 0.261.139
Implemented in: 0.261.087
Single orchestration contract updated in: 0.261.139

Every executable capability must resolve to the callable shape the dependency executor
uses. Render is the one extension handled directly by the executor; ``respond`` is removed.
Adapters must also stay off Flask request state because they run on worker threads.
"""

import ast
import inspect
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT, stubbed_app_imports  # noqa: E402
from test_support.orchestration_research import stubbed_orchestration_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ADAPTERS = 'functions_orchestration_adapters.py'
EXECUTOR = 'functions_orchestration_executor.py'
PLANNER = 'functions_orchestration_planner.py'
REGISTRY = 'functions_orchestration_registry.py'
ROUTE = 'route_backend_orchestration.py'

EXPECTED_POSITIONAL = ['step', 'context']
EXPECTED_KEYWORD = {'settings', 'user_id', 'emit', 'cancel_requested'}


def _tree(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return ast.parse(handle.read())


def _functions(tree):
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _registered_adapter_names(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if 'ADAPTER_REGISTRY' not in [t.id for t in node.targets if isinstance(t, ast.Name)]:
            continue
        mapping = {}
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Name) and isinstance(value, ast.Name):
                mapping[key.id] = value.id
        return mapping
    return {}


def _capability_constants(tree):
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


def _assert_signature(callable_obj):
    signature = inspect.signature(callable_obj)
    parameters = list(signature.parameters.values())
    assert [parameter.name for parameter in parameters[:2]] == EXPECTED_POSITIONAL
    for name in EXPECTED_KEYWORD:
        parameter = signature.parameters.get(name)
        assert parameter is not None, f'{callable_obj} missing {name}'
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_every_executable_capability_resolves_to_an_adapter_or_executor_extension():
    assert_app_version_at_least('0.261.139')
    registry_tree = _tree(REGISTRY)
    constants = _capability_constants(registry_tree)
    registered = _registered_adapter_names(_tree(ADAPTERS))
    registered_ids = {constants[name] for name in registered}
    assert 'respond' not in registered_ids

    with stubbed_app_imports():
        from functions_orchestration_adapters import get_adapter
        from functions_orchestration_executor import _dependency_adapter, _render_dependency_step
        from functions_orchestration_registry import all_capability_ids

        ids = all_capability_ids(contract_version=2)
        for capability_id in ids:
            adapter = get_adapter(capability_id, contract_version=2)
            if capability_id == 'render_file':
                assert adapter is None
                assert _dependency_adapter(capability_id) is _render_dependency_step
            else:
                assert callable(adapter), f'{capability_id} did not resolve to an adapter'
        assert get_adapter('compose', contract_version=1) is None

    missing = sorted(set(ids) - registered_ids - {'compose', 'generate_image', 'render_file'})
    assert not missing, f'these capabilities have no adapter path: {missing}'


def test_adapters_match_the_dependency_executor_call_signature():
    adapters_tree = _tree(ADAPTERS)
    functions = _functions(adapters_tree)
    registered = _registered_adapter_names(adapters_tree)
    for capability_constant, adapter_name in sorted(registered.items()):
        node = functions.get(adapter_name)
        assert node is not None, f'{adapter_name} is registered for {capability_constant} but not defined'
        positional = [a.arg for a in node.args.args]
        assert positional == EXPECTED_POSITIONAL
        keyword_only = {a.arg for a in node.args.kwonlyargs}
        missing = EXPECTED_KEYWORD - keyword_only
        assert not missing, f'{adapter_name} does not accept {sorted(missing)}'
        extra = keyword_only - EXPECTED_KEYWORD
        if extra:
            defaulted = {arg.arg for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults) if default is not None}
            assert not (extra - defaulted)

    with stubbed_app_imports():
        from functions_orchestration_adapters import get_adapter

        _assert_signature(get_adapter('compose', contract_version=2))
        _assert_signature(get_adapter('generate_image', contract_version=2))


def test_dependency_executor_passes_the_expected_adapter_keywords():
    tree = _tree(EXECUTOR)
    runner = _functions(tree)['_run_dependency_step']
    calls = [
        node for node in ast.walk(runner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'adapter'
    ]
    assert calls, 'executor no longer calls a resolved adapter'
    keywords = {keyword.arg for keyword in calls[0].keywords}
    assert EXPECTED_KEYWORD <= keywords


def test_adapters_never_touch_flask_state():
    tree = _tree(ADAPTERS)
    forbidden_imports = {'g', 'session', 'current_app', 'request'}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'flask':
            assert not ({alias.name for alias in node.names} & forbidden_imports)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id not in forbidden_imports


def test_route_captures_identity_before_the_thread_starts():
    tree = _tree(ROUTE)
    functions = _functions(tree)
    capture = functions.get('_request_identity')
    assert capture is not None
    capture_source = ast.dump(capture)
    assert 'user_roles' in capture_source and 'user_email' in capture_source

    for outer in ast.walk(tree):
        if not isinstance(outer, ast.FunctionDef) or outer.name != 'generate':
            continue
        for inner in ast.walk(outer):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == '_request_identity':
                raise AssertionError('_request_identity is called inside generate()')

    wired = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'RunContext':
            wired = {kw.arg for kw in node.keywords}
    for field in ('user_roles', 'user_email', 'user_enable_agents'):
        assert field in wired


def test_role_gates_fail_closed():
    init = _functions(_tree(EXECUTOR)).get('__init__')
    assert init is not None
    source = ast.dump(init)
    assert 'user_roles' in source
    assert 'isinstance' in source


def test_request_gates_are_applied_by_the_planner_and_registry():
    plan_request = _functions(_tree(PLANNER)).get('plan_request')
    assert plan_request is not None
    accepted = {a.arg for a in plan_request.args.args} | {a.arg for a in plan_request.args.kwonlyargs}
    assert 'request_context' in accepted
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'resolve_available_capabilities'
        and any(keyword.arg == 'request_context' for keyword in node.keywords)
        for node in ast.walk(plan_request)
    )
    route_tree = _tree(ROUTE)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'plan_request'
        and any(keyword.arg == 'request_context' for keyword in node.keywords)
        for node in ast.walk(route_tree)
    )


def test_request_gates_withhold_what_the_caller_cannot_use():
    with stubbed_orchestration_imports():
        from functions_orchestration_registry import resolve_available_capabilities

        settings = {
            'enable_chat_orchestration': True,
            'enable_user_workspace': True,
            'enable_web_search': True,
            'enable_url_access': True,
            'enable_source_review': True,
            'enable_semantic_kernel': True,
        }
        services = {
            'external_source_admission': object(),
            'external_source_preflight': object(),
            'capture_external_source_configuration': object(),
            'external_source_authorizer': object(),
        }

        def ids(context, override=None):
            return [capability['id'] for capability in resolve_available_capabilities(
                override or settings, request_context={**context, **services},
            )]

        plain = {
            'user_id': 'u1', 'user_message': 'what is in my handbook?', 'message_urls': [],
            'user_roles': [], 'user_enable_agents': True, 'agent_catalog': [], 'action_catalog': [],
        }
        assert 'url_fetch' not in ids(plain)
        assert 'agent_invoke' not in ids(plain)
        with_agent = {**plain, 'agent_catalog': [{'name': 'research_helper'}]}
        assert 'agent_invoke' not in ids({**with_agent, 'user_enable_agents': False})

        strict = {**settings, 'require_member_of_deep_research_user': True, 'source_review_settings': {'require_member_of_deep_research_user': True}}
        assert 'deep_research' not in ids(plain, strict)


def _run_script():
    tests = [
        test_every_executable_capability_resolves_to_an_adapter_or_executor_extension,
        test_adapters_match_the_dependency_executor_call_signature,
        test_dependency_executor_passes_the_expected_adapter_keywords,
        test_adapters_never_touch_flask_state,
        test_route_captures_identity_before_the_thread_starts,
        test_role_gates_fail_closed,
        test_request_gates_are_applied_by_the_planner_and_registry,
        test_request_gates_withhold_what_the_caller_cannot_use,
    ]
    passed = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            passed += 1
            print('Test passed!')
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
    print(f"\nResults: {passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == '__main__':
    sys.exit(0 if _run_script() else 1)
