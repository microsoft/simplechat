# test_orchestration_action_runtime.py
"""Functional coverage for isolated multi-function action execution.

Version: 0.261.096
Implemented in: 0.261.096

Runs the real Semantic Kernel auto-invocation loop and function filters with a
scripted model and local plugins. No Azure or external service calls are made.
"""

import ast
import asyncio
import importlib
import json
import logging
import sys
import typing
from contextlib import nullcontext
from copy import deepcopy
from types import ModuleType, SimpleNamespace

import pytest
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel import Kernel
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from test_support.app_stubs import APP_ROOT, stubbed_app_imports


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


@pytest.fixture
def runtime(monkeypatch):
    with stubbed_app_imports():
        monkeypatch.setitem(sys.modules, 'functions_action_catalog', module(
            'functions_action_catalog', resolve_action_manifest=lambda *args, **kwargs: None,
        ))
        monkeypatch.delitem(sys.modules, 'functions_orchestration_actions', raising=False)
        service_module = importlib.import_module('functions_orchestration_actions')
        contexts = importlib.import_module('agent_execution_context')
        state = SimpleNamespace(
            settings={
                'enable_chat_orchestration': True,
                'enable_chat_orchestration_actions': True,
                'enable_semantic_kernel': True,
                'max_auto_invoke_attempts': 5,
            },
            calls=[], loads=[], prepared=[], instances=[], requests=[], replies=[],
            cancelled=False, fail=False, after_call=None, block=False, close_error=False,
        )
        state.action = {
            'action_ref': 'personal:actor:tickets', 'id': 'tickets', 'name': 'tickets',
            'display_name': 'Tickets', 'description': 'Find ticket details.',
            'type': 'openapi', 'scope_type': 'personal', 'scope_id': 'actor',
        }
        state.manifest = {**state.action, 'auth': {'api_key': 'PRIVATE_CONFIG'}}
        state.context = SimpleNamespace(
            action_catalog=[state.action], active_group_ids=[], token_usage={}, notes=[],
            agent_execution_identity=contexts.ExecutionIdentity(
                'actor', 'conversation', bridge=lambda reference: nullcontext(),
            ),
            delegation_budget=contexts.DelegationBudget(),
        )
        state.contexts = contexts
        state.runtime = service_module
        state.build_model = service_module._build_action_model

        class Plugin:
            def __init__(self):
                self.closed = False

            @kernel_function(description='Look up a ticket.')
            async def lookup(self, ticket: str) -> str:
                frame = contexts.current_agent_execution()
                state.calls.append((ticket, frame.identity.user_id))
                if state.fail:
                    raise RuntimeError('PRIVATE_PROVIDER_FAILURE')
                value = {'ticket': ticket, 'status': 'open'}
                frame.budget.record_tool_invocation(SimpleNamespace(
                    plugin_name='tickets', function_name='lookup', parameters={'ticket': ticket},
                    result=value, user_id=frame.identity.user_id, success=True,
                    provenance={'root_id': frame.budget.root_id},
                ))
                if state.after_call:
                    state.after_call()
                return json.dumps(value)

            def close(self):
                self.closed = True
                if state.close_error:
                    raise RuntimeError('PRIVATE_CLEANUP_FAILURE')

        class Loader:
            def __init__(self, kernel):
                self.kernel = kernel
                self.plugin_instances = []

            def load_plugin_from_manifest(self, manifest, user_id):
                state.loads.append((manifest['id'], user_id))
                instance = Plugin()
                state.instances.append(instance)
                self.plugin_instances.append(instance)
                self.kernel.add_plugin(instance, plugin_name='tickets')
                return True

        def prepare(manifest, settings):
            state.prepared.append(deepcopy(manifest))
            return deepcopy(manifest)

        monkeypatch.setitem(sys.modules, 'semantic_kernel_loader', module(
            'semantic_kernel_loader',
            get_max_auto_invoke_attempts=lambda settings: settings['max_auto_invoke_attempts'],
            prepare_action_plugin_manifest=prepare,
        ))
        monkeypatch.setitem(sys.modules, 'semantic_kernel_plugins.logged_plugin_loader', module(
            'semantic_kernel_plugins.logged_plugin_loader', create_logged_plugin_loader=Loader,
        ))
        monkeypatch.setattr(sys.modules['functions_settings'], 'get_settings', lambda: deepcopy(state.settings))
        monkeypatch.setattr(service_module, 'resolve_action_manifest', lambda *args, **kwargs: deepcopy(state.manifest))
        state.service = AzureChatCompletion(
            service_id='orchestration-action', deployment_name='test-model',
            endpoint='https://example.invalid', api_key='not-a-real-key', api_version='2024-10-21',
        )
        monkeypatch.setattr(service_module, '_build_action_model', lambda *args: state.service)

        async def reply(self, history, settings):
            state.requests.append(str(history))
            if state.block:
                await asyncio.sleep(60)
            if state.replies:
                return [state.replies.pop(0)]
            return [ChatMessageContent(
                role=AuthorRole.ASSISTANT, content='The requested tickets are open.',
                metadata={'usage': {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3}},
            )]

        monkeypatch.setattr(AzureChatCompletion, '_inner_get_chat_message_contents', reply)
        yield state
        if not state.service.client.is_closed():
            asyncio.run(state.service.client.close())
        sys.modules.pop('functions_orchestration_actions', None)


def tool_message(*tickets, function='tickets-lookup'):
    return ChatMessageContent(
        role=AuthorRole.ASSISTANT,
        items=[
            FunctionCallContent(id=f'call-{ticket}', name=function, arguments=json.dumps({'ticket': ticket}))
            for ticket in tickets
        ],
        metadata={'usage': {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3}},
    )


async def execute(state):
    return await state.runtime.invoke_action(
        state.action['action_ref'], 'Look up the tickets.', state.context,
        settings=state.settings, user_id='actor', cancel_requested=lambda: state.cancelled,
    )


def test_multiple_function_calls_load_one_action_and_accumulate_findings(runtime):
    runtime.replies = [tool_message('42'), tool_message('43')]
    result = asyncio.run(execute(runtime))
    assert runtime.calls == [('42', 'actor'), ('43', 'actor')]
    assert runtime.loads == [('tickets', 'actor')]
    assert len(runtime.prepared) == 1
    assert result['calls'] == 2
    assert len(result['invocations']) == 2
    assert result['root_id'] == runtime.context.delegation_budget.root_id
    assert 'open' in result['findings']
    assert runtime.context.token_usage['total_tokens'] == 9
    assert all(instance.closed for instance in runtime.instances)
    assert runtime.service.client.is_closed()
    assert runtime.contexts.current_agent_execution() is None
    assert all('PRIVATE_CONFIG' not in request for request in runtime.requests)


def test_batched_calls_cannot_exceed_function_budget(runtime):
    runtime.settings['max_auto_invoke_attempts'] = 1
    runtime.replies = [tool_message('42', '43')]
    with pytest.raises(runtime.runtime.ActionExecutionError):
        asyncio.run(execute(runtime))
    assert runtime.calls == [('42', 'actor')]
    assert len(runtime.requests) == 1
    assert runtime.instances[0].closed


def test_unregistered_tools_are_not_invoked(runtime):
    runtime.replies = [tool_message('42', function='another_action-lookup')]
    with pytest.raises(runtime.runtime.ActionExecutionError):
        asyncio.run(execute(runtime))
    assert not runtime.calls


def test_provider_cannot_claim_success_without_a_tool_result(runtime):
    with pytest.raises(runtime.runtime.ActionExecutionError):
        asyncio.run(execute(runtime))
    assert not runtime.calls


def test_plugin_errors_are_redacted_and_do_not_retry_the_action(runtime):
    runtime.fail = True
    runtime.replies = [tool_message('42', '43')]
    with pytest.raises(runtime.runtime.ActionExecutionError) as caught:
        asyncio.run(execute(runtime))
    assert 'PRIVATE_' not in str(caught.value)
    assert all('PRIVATE_PROVIDER_FAILURE' not in request for request in runtime.requests)
    assert runtime.calls == [('42', 'actor')]
    assert len(runtime.requests) == 1
    assert runtime.instances[0].closed
    assert runtime.service.client.is_closed()


@pytest.mark.parametrize('revocation', ['setting', 'manifest'])
def test_access_and_definition_changes_stop_subsequent_calls(runtime, revocation):
    runtime.replies = [tool_message('42', '43')]

    def revoke():
        if revocation == 'setting':
            runtime.settings['enable_chat_orchestration_actions'] = False
        else:
            runtime.manifest['enabled_functions'] = []

    runtime.after_call = revoke
    with pytest.raises(runtime.runtime.ActionExecutionError):
        asyncio.run(execute(runtime))
    assert runtime.calls == [('42', 'actor')]
    assert len(runtime.requests) == 1


def test_cancellation_between_calls_stops_remaining_batch(runtime):
    runtime.replies = [tool_message('42', '43')]
    runtime.after_call = lambda: setattr(runtime, 'cancelled', True)
    with pytest.raises(runtime.contexts.AgentExecutionCancelled):
        asyncio.run(execute(runtime))
    assert runtime.calls == [('42', 'actor')]
    assert len(runtime.requests) == 1
    assert runtime.instances[0].closed


def test_cancellation_interrupts_blocked_model_and_closes_resources(runtime):
    runtime.block = True

    async def run():
        task = asyncio.create_task(execute(runtime))
        await asyncio.sleep(0.02)
        runtime.cancelled = True
        with pytest.raises(runtime.contexts.AgentExecutionCancelled):
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())
    assert runtime.instances[0].closed
    assert runtime.service.client.is_closed()


def test_missing_identity_prevents_loading(runtime):
    runtime.context.agent_execution_identity = None
    with pytest.raises(PermissionError):
        asyncio.run(execute(runtime))
    assert not runtime.loads
    asyncio.run(runtime.service.client.close())


def test_call_agent_action_cannot_enter_the_runtime(runtime):
    runtime.action['type'] = 'agent'
    with pytest.raises(PermissionError):
        asyncio.run(execute(runtime))
    assert not runtime.loads
    asyncio.run(runtime.service.client.close())


def test_cleanup_failure_does_not_leak_the_model_client(runtime):
    runtime.close_error = True
    runtime.replies = [tool_message('42')]
    asyncio.run(execute(runtime))
    assert runtime.instances[0].closed
    assert runtime.service.client.is_closed()


def test_model_context_never_accepts_client_credentials_or_actor_overrides(runtime, monkeypatch):
    observed = []
    selected_service = object()

    def resolve(settings, context, *, authorize):
        assert authorize is True
        observed.append(dict(context))
        return {'id': 'selected-endpoint'}

    monkeypatch.setitem(sys.modules, 'functions_model_endpoint_runtime', module(
        'functions_model_endpoint_runtime',
        resolve_model_endpoint_from_context=resolve,
        build_semantic_kernel_chat_service_for_model=lambda *args, **kwargs: (selected_service, None),
    ))
    runtime.context.model_context = {
        'endpoint_id': 'selected-endpoint', 'model_id': 'selected-model',
        'endpoint': 'https://untrusted.invalid', 'auth': {'api_key': 'PRIVATE_OVERRIDE'},
        'user_id': 'another-user', 'active_group_ids': ['untrusted-group'],
    }
    runtime.context.active_group_ids = ['selected-group']
    assert runtime.build_model(runtime.settings, runtime.context, 'actor') is selected_service
    assert observed == [{
        'endpoint_id': 'selected-endpoint', 'model_id': 'selected-model',
        'user_id': 'actor', 'active_group_ids': ['selected-group'],
    }]


def test_unavailable_selected_model_does_not_fall_back(runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, 'functions_model_endpoint_runtime', module(
        'functions_model_endpoint_runtime',
        resolve_model_endpoint_from_context=lambda *args, **kwargs: None,
        build_semantic_kernel_chat_service_for_model=lambda *args, **kwargs: pytest.fail('No fallback allowed'),
    ))
    runtime.context.model_context = {'endpoint_id': 'revoked', 'model_id': 'model'}
    with pytest.raises(PermissionError):
        runtime.build_model(runtime.settings, runtime.context, 'actor')


@pytest.mark.parametrize('scope,feature', [
    ('personal', 'governance_user_endpoints'),
    ('group', 'governance_group_endpoints'),
    ('global', 'governance_global_endpoints'),
])
def test_selected_model_governance_precedes_secret_hydration(monkeypatch, scope, feature):
    tree = ast.parse((APP_ROOT / 'functions_model_endpoint_runtime.py').read_text(encoding='utf-8'))
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name in ('_append_model_endpoint_candidate', 'resolve_model_endpoint_from_context')
    ]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<model-resolution>', 'exec'), namespace)
    endpoint = {'id': 'endpoint', 'provider': 'aoai', 'models': [{'id': 'model', 'deploymentName': 'model'}]}
    settings = {
        'enable_multi_model_endpoints': True,
        'allow_user_custom_endpoints': scope == 'personal',
        'allow_group_custom_endpoints': scope == 'group',
        'model_endpoints': [endpoint] if scope == 'global' else [],
    }
    reads = []
    policies = []
    roles = []
    allow = False

    def filter_endpoints(user_id, endpoints, feature_key):
        policies.append((user_id, feature_key))
        return endpoints if allow else []

    monkeypatch.setitem(sys.modules, 'functions_group', module(
        'functions_group',
        get_group_model_endpoints=lambda group_id: [endpoint],
        assert_group_role=lambda user, group, **kwargs: roles.append((user, group)),
    ))
    monkeypatch.setitem(sys.modules, 'functions_governance', module(
        'functions_governance', filter_governed_model_endpoints=filter_endpoints,
    ))
    monkeypatch.setitem(sys.modules, 'functions_keyvault', module(
        'functions_keyvault', SecretReturnType=SimpleNamespace(VALUE='value'),
        keyvault_model_endpoint_get_helper=lambda value, *args, **kwargs: reads.append(value) or value,
    ))
    monkeypatch.setitem(sys.modules, 'functions_settings', module(
        'functions_settings',
        get_user_settings=lambda user: {'settings': {'personal_model_endpoints': [endpoint]}},
        normalize_model_endpoints=lambda values: (values, False),
    ))
    context = {'user_id': 'actor', 'endpoint_id': 'endpoint', 'model_id': 'model', 'active_group_ids': ['team']}
    assert namespace['resolve_model_endpoint_from_context'](settings, context, authorize=True) is None
    assert not reads
    assert ('actor', feature) in policies
    if scope == 'group':
        assert roles == [('actor', 'team')]
    allow = True
    assert namespace['resolve_model_endpoint_from_context'](settings, context, authorize=True)['id'] == 'endpoint'
    assert len(reads) == 1


@pytest.mark.parametrize('plugin_type', ['openapi', 'mcp', 'sql_query'])
def test_single_manifest_loader_preserves_enabled_functions_and_tracks_companions(runtime, plugin_type):
    """Exercise the real loader seam without importing its live connection factories."""
    tree = ast.parse((APP_ROOT / 'semantic_kernel_plugins' / 'logged_plugin_loader.py').read_text(encoding='utf-8'))
    loader_class = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                        and node.name == 'LoggedPluginLoader')
    methods = {'__init__', 'load_plugin_from_manifest', '_register_plugin_with_kernel',
               '_auto_create_companion_schema_plugin'}
    loader_class.body = [
        node for node in loader_class.body if isinstance(node, ast.FunctionDef) and node.name in methods
    ]

    class Plugin:
        def __init__(self, manifest):
            self.manifest = manifest
            self.closed = False

        @kernel_function(description='An enabled operation.')
        def enabled(self) -> str:
            return 'result'

        @kernel_function(description='A disabled operation.')
        def disabled(self) -> str:
            raise AssertionError('This operation must not be registered.')

        def get_kernel_plugin(self, name):
            plugin = KernelPlugin.from_object(name, self)
            plugin.functions.pop('disabled')
            return plugin

        def close(self):
            self.closed = True

    namespace = {
        'Kernel': Kernel, 'KernelPlugin': KernelPlugin, 'Dict': typing.Dict, 'Any': typing.Any,
        'Optional': typing.Optional, 'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'debug_print': lambda *args, **kwargs: None,
        'get_plugin_logger': lambda: None, 'BasePlugin': Plugin, 'SQLSchemaPlugin': Plugin,
    }
    exec(compile(ast.Module(body=[loader_class], type_ignores=[]), '<single-action-loader>', 'exec'), namespace)
    kernel = Kernel()
    loader = namespace['LoggedPluginLoader'](kernel)
    loaded = []

    def create(manifest):
        loaded.append(manifest['id'])
        return Plugin(manifest)

    loader._create_plugin_instance = create
    loader._wrap_plugin_functions = lambda *args: None
    assert loader.load_plugin_from_manifest({'id': 'one-action', 'name': 'chosen', 'type': plugin_type}, 'actor')
    assert loaded == ['one-action']
    expected = {'chosen', 'chosen_schema'} if plugin_type == 'sql_query' else {'chosen'}
    assert set(kernel.plugins) == expected
    assert {function.name for function in kernel.get_list_of_function_metadata({})} == {'enabled'}
    assert len(loader.plugin_instances) == len(expected)
    asyncio.run(runtime.runtime._close_resources(kernel, loader.plugin_instances))
    assert all(plugin.closed for plugin in loader.plugin_instances)


def test_sql_connections_are_closed_without_waiting_for_garbage_collection(runtime):
    closed = []
    connection = SimpleNamespace(close=lambda: closed.append(True))
    plugin = SimpleNamespace(manifest={'type': 'sql_query'}, _connection=connection)
    asyncio.run(runtime.runtime._close_resources(Kernel(), [plugin]))
    assert closed == [True]
    assert plugin._connection is None


def test_selected_action_preparation_reuses_overlays_and_secret_identity_resolution():
    tree = ast.parse((APP_ROOT / 'semantic_kernel_loader.py').read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'prepare_action_plugin_manifest')
    stages = []

    def secrets(manifest, settings):
        stages.append(('secrets', manifest['id']))
        manifest['auth']['api_key'] = 'resolved'
        return manifest

    namespace = {
        'deepcopy': deepcopy,
        '_apply_agent_plugin_runtime_overlays': lambda manifests, group_id: (
            stages.append(('overlays', group_id)) or [dict(manifests[0], enabled_functions=['lookup'])]
        ),
        'resolve_key_vault_secrets_in_plugins': secrets,
        'hydrate_workspace_identity_in_plugin': lambda manifest: (
            stages.append(('identity', manifest['id'])) or manifest
        ),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<prepare-action>', 'exec'), namespace)
    manifest = {
        'id': 'chosen', 'name': 'chosen', 'type': 'msgraph', 'group_id': 'team',
        'auth': {'api_key': 'reference'},
    }
    settings = {'enable_key_vault_secret_storage': True, 'key_vault_name': 'vault'}
    prepared = namespace['prepare_action_plugin_manifest'](manifest, settings)
    assert prepared['enabled_functions'] == ['lookup']
    assert stages == [('overlays', 'team'), ('secrets', 'chosen'), ('identity', 'chosen')]
    assert 'enabled_functions' not in manifest
    assert manifest['auth']['api_key'] == 'reference'
    stages.clear()
    with pytest.raises(PermissionError):
        namespace['prepare_action_plugin_manifest']({'type': 'agent'}, settings)
    assert not stages


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
