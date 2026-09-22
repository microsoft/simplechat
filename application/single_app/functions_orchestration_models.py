# functions_orchestration_models.py
"""Authorized model bindings for orchestration planning and execution.

Version: 0.261.127

Planner construction evidence is private runtime metadata, captured from the
client's actual construction inputs. It is not public model metadata, credentials,
or a reconstruction from settings read after the client was created.
get_planner_acquisition_configuration returns only the eight-field descriptor for
the exact owned planner adapter. Parameters describe its construction-bound
controls, not arbitrary overrides supplied to a later completion call.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from functions_model_capabilities import resolve_model_reasoning_effort
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    ModelEndpointBehavior,
    create_completion_with_reasoning,
    infer_model_endpoint_protocol,
)


REASONING_COMPLETION_BUDGET = 8192
MODEL_IDENTITY_FIELDS = ('model_deployment', 'model_id', 'model_endpoint_id', 'model_provider')
PLANNER_MODEL_FIELDS = {
    'model_deployment': 'chat_orchestration_planner_deployment',
    'model_id': 'chat_orchestration_planner_model_id',
    'model_endpoint_id': 'chat_orchestration_planner_model_endpoint_id',
    'model_provider': 'chat_orchestration_planner_model_provider',
}


class OrchestrationModelError(ValueError):
    """The requested model cannot be used without changing the user's selection."""

    def __init__(self):
        super().__init__('The selected model is unavailable. Choose an enabled model you can access.')


def _text(value):
    return str(value or '').strip()


class _PlannerCompletions:
    def __init__(self, model):
        self.model = model
        self._constructed_model = model
        self._construction = model._construction
        self._planner_client = None
        self._chat = None

    def create(self, **kwargs):
        return self.model.create_completion(**kwargs)


@dataclass(frozen=True)
class _ModelConstruction:
    client: Any = field(repr=False)
    binding: tuple = field(repr=False)
    endpoint: str | None = field(repr=False)
    api_version: str | None = field(repr=False)
    protocol: str = field(repr=False)


def _binding_signature(model):
    return (
        model.provider, model.deployment, model.endpoint_id, model.model_id,
        model.behavior_name, model.response_length, model.reasoning_effort,
    )


def _record_construction(model, *, endpoint, api_version, protocol):
    model._construction = _ModelConstruction(
        model.client, _binding_signature(model), endpoint, api_version, protocol,
    )
    return model


def get_planner_acquisition_configuration(planner_client):
    """Return a detached private descriptor for this unchanged constructed client."""
    if type(planner_client) is not SimpleNamespace:
        raise OrchestrationModelError()
    chat = getattr(planner_client, 'chat', None)
    completions = getattr(chat, 'completions', None) if type(chat) is SimpleNamespace else None
    if (
        type(completions) is not _PlannerCompletions
        or completions._planner_client is not planner_client or completions._chat is not chat
    ):
        raise OrchestrationModelError()
    model, construction = completions.model, completions._construction
    if (
        type(model) is not OrchestrationModel or model is not completions._constructed_model or model._closed
        or type(construction) is not _ModelConstruction or model._construction is not construction
        or model.client is not construction.client or _binding_signature(model) != construction.binding
        or any(type(value) is not str or not value.strip() for value in (
            construction.endpoint, construction.protocol, model.provider, model.deployment,
        ))
        or construction.api_version is not None and type(construction.api_version) is not str
        or construction.protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
        and not construction.api_version
    ):
        raise OrchestrationModelError()
    (
        provider, deployment, endpoint_id, model_id, _behavior_name, response_length, reasoning_effort,
    ) = construction.binding
    parameters = {}
    if response_length is not None:
        parameters['response_length'] = response_length
    if reasoning_effort:
        parameters['reasoning_effort'] = reasoning_effort
    return {
        'provider': provider, 'protocol': construction.protocol,
        'endpoint': construction.endpoint, 'api_version': construction.api_version,
        'deployment': deployment, 'endpoint_id': endpoint_id, 'model_id': model_id,
        'parameters': parameters,
    }


def planner_client_construction_source(planner_client, planner_model):
    """Wrap the same private descriptor for callers using the acquisition envelope."""
    configuration = get_planner_acquisition_configuration(planner_client)
    if type(planner_model) is not str or planner_model != configuration['deployment']:
        raise OrchestrationModelError()
    return {
        'version': 'orchestration-external-acquisition-v1', 'kind': 'planner', 'phase': 'resolved',
        'model': configuration,
    }


@dataclass
class OrchestrationModel:
    client: Any = field(repr=False)
    deployment: str
    provider: str = 'aoai'
    endpoint_id: str = ''
    model_id: str = ''
    behavior_name: str = ''
    response_length: int | None = None
    reasoning_effort: str = ''
    source: str = 'legacy'
    model_metadata: dict[str, Any] = field(default_factory=dict, repr=False)
    _answer_selection: dict[str, str] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    reasoning_resolution: dict[str, Any] = field(default_factory=dict, init=False)
    _reasoning_rejected_efforts: set[str] = field(default_factory=set, init=False, repr=False)
    _construction: _ModelConstruction | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self.model_metadata = deepcopy(self.model_metadata)
        self.model_metadata.setdefault('deploymentName', self.deployment)
        if self.behavior_name:
            self.model_metadata.setdefault('modelName', self.behavior_name)
        if self.response_length is not None:
            self.model_metadata['responseLength'] = self.response_length
        self.reasoning_resolution = resolve_model_reasoning_effort(
            self.behavior_name or self.deployment, self.reasoning_effort
        )

    def answer_model_selection(self):
        """Pin the answer choice even when this binding is a separate planner."""
        return dict(self._answer_selection) if self._answer_selection is not None else {
            key: value for key, value in {
                'model_deployment': self.deployment,
                'model_provider': self.provider,
                'model_endpoint_id': self.endpoint_id,
                'model_id': self.model_id,
            }.items() if value
        }

    def metadata(self):
        return {
            key: value for key, value in {
                'model_deployment_name': self.deployment,
                'model_provider': self.provider,
                'model_endpoint_id': self.endpoint_id,
                'model_id': self.model_id,
            }.items() if value
        }

    def as_planner_client(self):
        """Keep the chat-completions interface used by planning and source review."""
        completions = _PlannerCompletions(self)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        completions._planner_client, completions._chat = client, client.chat
        return client

    def _record_reasoning_resolution(self, resolution):
        self.reasoning_resolution = dict(resolution)
        if resolution['adjustment_reason'] == 'reasoning_parameter_rejected':
            self._reasoning_rejected_efforts.add(resolution['requested_effort'])

    def create_completion(self, *, use_model_response_length=False, **kwargs):
        parameters = dict(kwargs)
        if parameters.get('model', self.deployment) != self.deployment:
            raise OrchestrationModelError()
        parameters['model'] = self.deployment
        behavior = ModelEndpointBehavior(self.provider, self.behavior_name or self.deployment)
        limit = parameters.pop('max_completion_tokens', None)
        legacy_limit = parameters.pop('max_tokens', None)
        limit = limit if limit is not None else legacy_limit
        if use_model_response_length and self.response_length is not None:
            limit = self.response_length
        elif behavior.is_openai_reasoning_model and limit is not None:
            # Reasoning tokens share the completion budget with the visible JSON or answer.
            limit = max(limit, REASONING_COMPLETION_BUDGET)
        if limit is not None:
            parameters[behavior.response_length_parameter] = limit
        if behavior.is_openai_reasoning_model:
            parameters.pop('temperature', None)
        parameters.setdefault('reasoning_effort', self.reasoning_effort)
        self.reasoning_resolution = resolve_model_reasoning_effort(
            self.behavior_name or self.deployment, parameters['reasoning_effort']
        )
        if self.reasoning_resolution['requested_effort'] in self._reasoning_rejected_efforts:
            # An outer JSON-format retry must not resend an effort already rejected
            # by this binding. Different explicit per-call efforts retain their policy.
            parameters.pop('reasoning_effort')
            self.reasoning_resolution.update(
                effective_effort=None, mode='model_default',
                adjustment_reason='reasoning_parameter_rejected',
            )
            return self.client.chat.completions.create(**parameters)
        completion, self.reasoning_resolution = create_completion_with_reasoning(
            self.client.chat.completions.create, parameters, self.behavior_name or self.deployment,
            on_resolution=self._record_reasoning_resolution,
        )
        return completion

    def close(self):
        if not self._closed:
            self._closed = True
            close = getattr(self.client, 'close', None)
            if callable(close):
                close()


def _resolve_legacy_binding(settings, *, deployment='', reasoning_effort='', source='legacy',
                            answer_selection=None):
    # Keep the legacy client seam lazy to avoid an import cycle with the planner.
    from functions_orchestration_planner import resolve_planner_client

    settings = deepcopy(settings)
    apim = bool(settings.get('enable_gpt_apim', False))
    endpoint = settings.get('azure_apim_gpt_endpoint' if apim else 'azure_openai_gpt_endpoint')
    api_version = settings.get('azure_apim_gpt_api_version' if apim else 'azure_openai_gpt_api_version')
    client, resolved_deployment = resolve_planner_client(settings)
    deployment = deployment or resolved_deployment
    model = {}
    if not settings.get('enable_gpt_apim'):
        model = next((
            model
            for model in (settings.get('gpt_model') or {}).get('selected') or []
            if isinstance(model, dict) and _text(model.get('deploymentName')) == deployment
        ), {})
    response_length = model.get('responseLength')
    if type(response_length) is not int or response_length <= 0:
        response_length = None
    return _record_construction(OrchestrationModel(
        client, deployment, behavior_name=_text(model.get('modelName')),
        response_length=response_length, model_metadata=model,
        reasoning_effort=reasoning_effort,
        source=source, _answer_selection=answer_selection,
    ), endpoint=endpoint, api_version=api_version, protocol=MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI)


def has_planner_model_override(settings):
    return any(_text((settings or {}).get(key)) for key in PLANNER_MODEL_FIELDS.values())


def _resolve_planner_binding(settings, *, user_id, seeds, identity_context, answer_selection):
    selection = {
        field: _text(settings.get(key)) for field, key in PLANNER_MODEL_FIELDS.items()
    }
    if selection['model_endpoint_id'] or selection['model_id']:
        binding = resolve_orchestration_model(
            settings, user_id=user_id,
            seeds={**seeds, 'model': selection, 'reasoning_effort': ''},
            identity_context=identity_context,
        )
        binding.source = 'planner_override'
        binding._answer_selection = dict(answer_selection)
        return binding
    if not selection['model_deployment'] or selection['model_provider'].lower() not in ('', 'aoai'):
        raise OrchestrationModelError()
    return _resolve_legacy_binding(
        settings, source='planner_override', answer_selection=answer_selection,
    )


def resolve_orchestration_model(settings, *, user_id, seeds=None, planner=False, identity_context=None):
    """Resolve a request selection, then the admin default, without retargeting failures."""
    settings = settings or {}
    seeds = seeds or {}
    supplied = seeds.get('model') or {}
    if not isinstance(supplied, dict):
        raise OrchestrationModelError()
    selection = {key: _text(supplied.get(key)) for key in MODEL_IDENTITY_FIELDS}
    reasoning_effort = _text(seeds.get('reasoning_effort'))
    override = planner and has_planner_model_override(settings)

    if selection['model_id'] and not selection['model_endpoint_id']:
        raise OrchestrationModelError()
    if selection['model_endpoint_id'] and not (selection['model_id'] or selection['model_deployment']):
        raise OrchestrationModelError()
    if any(selection.values()) and not (selection['model_endpoint_id'] or selection['model_deployment']):
        raise OrchestrationModelError()

    multi_endpoint = bool(settings.get('enable_multi_model_endpoints'))
    explicit = any(selection.values())
    source = 'request' if explicit else 'legacy'
    if not explicit and multi_endpoint:
        default = settings.get('default_model_selection') or {}
        if not isinstance(default, dict):
            raise OrchestrationModelError()
        if any(default.get(key) for key in ('endpoint_id', 'model_id', 'provider')):
            if not _text(default.get('endpoint_id')) or not _text(default.get('model_id')):
                raise OrchestrationModelError()
            selection.update({
                'model_endpoint_id': _text(default['endpoint_id']),
                'model_id': _text(default['model_id']),
                'model_provider': _text(default.get('provider')),
            })
            source = 'default'

    if selection['model_endpoint_id']:
        if not multi_endpoint or not user_id:
            raise OrchestrationModelError()
        # Endpoint and credential dependencies are only loaded when that runtime is needed.
        from functions_model_endpoint_runtime import (
            MODEL_ENDPOINT_PROVIDER_ALLOWLIST,
            build_model_endpoint_sync_chat_client,
            resolve_model_endpoint_from_context,
        )

        context = {
            'endpoint_id': selection['model_endpoint_id'],
            'model_id': selection['model_id'],
            'model_deployment': selection['model_deployment'],
            'provider': selection['model_provider'],
            'user_id': user_id,
            'active_group_ids': seeds.get('active_group_ids') or [],
        }
        endpoint = resolve_model_endpoint_from_context(settings, context, authorize=True)
        if not endpoint or not endpoint.get('enabled', True):
            raise OrchestrationModelError()
        models = endpoint.get('models') or []
        model = next((
            item for item in models if isinstance(item, dict) and (
                _text(item.get('id')) == selection['model_id'] if selection['model_id']
                else resolve_model_endpoint_request_model(endpoint, item) == selection['model_deployment']
            )
        ), None)
        if not model or not model.get('enabled', True):
            raise OrchestrationModelError()
        deployment = resolve_model_endpoint_request_model(endpoint, model)
        provider = _text(endpoint.get('provider')).lower()
        if (
            not deployment or provider not in MODEL_ENDPOINT_PROVIDER_ALLOWLIST
            or _text(endpoint.get('id')) != selection['model_endpoint_id']
            or (selection['model_provider'] and selection['model_provider'].lower() != provider)
            or (selection['model_deployment'] and selection['model_deployment'] != deployment)
        ):
            raise OrchestrationModelError()
        connection = endpoint.get('connection') or {}
        address = _text(connection.get('endpoint'))
        api_version = _text(connection.get('openai_api_version') or connection.get('api_version'))
        protocol = infer_model_endpoint_protocol(provider, address, deployment, get_model_endpoint_api_type(endpoint))
        if not address or (protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI and not api_version):
            raise OrchestrationModelError()
        answer_selection = {
            'model_deployment': deployment, 'model_provider': provider,
            'model_endpoint_id': selection['model_endpoint_id'], 'model_id': _text(model.get('id')),
        }
        if override:
            return _resolve_planner_binding(
                settings, user_id=user_id, seeds=seeds, identity_context=identity_context,
                answer_selection=answer_selection,
            )
        client, constructed_protocol = build_model_endpoint_sync_chat_client(
            endpoint.get('auth') or {}, provider, address, api_version, deployment,
            settings=settings, endpoint_config=endpoint,
            identity_context={**(identity_context or {}), 'user_id': user_id},
        )
        response_length = model.get('responseLength')
        if not isinstance(response_length, int) or isinstance(response_length, bool) or response_length <= 0:
            response_length = None
        return _record_construction(OrchestrationModel(
            client, deployment, provider=provider, endpoint_id=selection['model_endpoint_id'],
            model_id=_text(model.get('id')), behavior_name=_text(model.get('modelName')) or deployment,
            response_length=response_length, reasoning_effort=reasoning_effort, source=source,
            model_metadata=model,
        ), endpoint=address, api_version=api_version, protocol=constructed_protocol)

    if selection['model_provider'] and selection['model_provider'].lower() != 'aoai':
        raise OrchestrationModelError()
    if settings.get('enable_gpt_apim'):
        deployments = [
            value.strip() for value in (settings.get('azure_apim_gpt_deployment') or '').split(',')
            if value.strip()
        ]
    else:
        deployments = [
            _text(model.get('deploymentName'))
            for model in (settings.get('gpt_model') or {}).get('selected') or []
            if isinstance(model, dict) and _text(model.get('deploymentName'))
        ]
    deployment = selection['model_deployment'] or next(iter(deployments), '')
    if not deployment or deployment not in deployments:
        raise OrchestrationModelError()
    if override:
        return _resolve_planner_binding(
            settings, user_id=user_id, seeds=seeds, identity_context=identity_context,
            answer_selection={'model_deployment': deployment, 'model_provider': 'aoai'},
        )
    # Legacy models share one connection; the answer must not inherit a planner override.
    return _resolve_legacy_binding(
        {**settings, 'chat_orchestration_planner_deployment': ''}, deployment=deployment,
        reasoning_effort=reasoning_effort, source=source,
    )
