# functions_model_endpoint_app_identity.py
"""The one rule for group and personal model endpoints that use the application identity.

Group and personal (``user`` scope) model endpoints are configured by
non-administrators. When an endpoint's authentication resolves to the application's
own credential (``DefaultAzureCredential``: managed identity, a missing auth type, or
any type other than the caller's own API key or service principal), its owner must not
choose where that token goes, what it is for, or which of the application's identities
issues it. In those two scopes only:

- the endpoint host must be an Azure AI service host of the configured cloud
  (``AZURE_AI_ENDPOINT_SUFFIXES``; a custom cloud has none, so nothing qualifies);
- a token audience (``foundry_scope``), authority (``custom_authority``) or ``custom``
  management cloud other than the deployment's own is refused;
- ``managed_identity_client_id`` is never honoured: the deployment's own identity
  selection is used.

``application_identity_violation`` is the one predicate. It is applied:

- to transient discovery and model-test requests, which are refused
  (``check_application_identity_request``);
- at save time, for native create and PATCH and the legacy group and personal saves:
  a new or changed endpoint that breaks the rule is refused with a stable 400
  (``check_application_identity_save``);
- at use time, from the Key Vault hydration every stored-configuration consumer goes
  through (fetch, test-model, Foundry discovery, chat, the Semantic Kernel loader,
  workflows and summaries), where a record stored before this rule fails closed and a
  stored identity selection is dropped (``resolve_application_identity_for_use``).

Global (admin) endpoints are unchanged.
"""

import logging

from functions_ai_connections import AIConnectionError
from functions_appinsights import log_event
from functions_azure_endpoint_validation import validate_azure_ai_endpoint_host
from functions_model_endpoint_types import MODEL_ENDPOINT_PROVIDER_CUSTOM


APPLICATION_IDENTITY_SCOPES = frozenset({"group", "user"})
# Authentication types that carry the caller's own credential. Every other type,
# including a missing one, resolves to the application's ``DefaultAzureCredential``.
CALLER_CREDENTIAL_AUTH_TYPES = frozenset({"api_key", "service_principal"})
# Connections that never use the application identity.
CALLER_CREDENTIAL_PROVIDERS = frozenset({MODEL_ENDPOINT_PROVIDER_CUSTOM, "openai_compatible"})
# The configuration the rule reads. A save that leaves all of it unchanged is not
# judged again; the stored record is judged when it is used.
APPLICATION_IDENTITY_FIELDS = (
    ("provider",),
    ("auth", "type"),
    ("connection", "endpoint"),
    ("auth", "foundry_scope"),
    ("auth", "custom_authority"),
    ("auth", "management_cloud"),
    ("auth", "managed_identity_client_id"),
)

APPLICATION_IDENTITY_ENDPOINT_REFUSED = "server_credential_endpoint_refused"
APPLICATION_IDENTITY_OVERRIDE_REFUSED = "server_credential_override_refused"
APPLICATION_IDENTITY_SELECTION_REFUSED = "server_credential_identity_refused"
APPLICATION_IDENTITY_MESSAGES = {
    APPLICATION_IDENTITY_ENDPOINT_REFUSED: (
        "The application identity can be used only with an Azure AI endpoint in this cloud. "
        "Use an API key or a service principal for other endpoints."
    ),
    APPLICATION_IDENTITY_OVERRIDE_REFUSED: (
        "The application identity uses this deployment's own token audience and authority. "
        "Remove the Foundry scope, custom authority and custom cloud, or use an API key or a service principal."
    ),
    APPLICATION_IDENTITY_SELECTION_REFUSED: (
        "The application identity is selected by this deployment. "
        "Remove the managed identity client ID, or use an API key or a service principal."
    ),
}


class ApplicationIdentityPolicyError(AIConnectionError):
    """A group or personal model endpoint may not use the application identity as configured."""


def _section(endpoint, name):
    value = (endpoint or {}).get(name) if isinstance(endpoint, dict) else None
    return value if isinstance(value, dict) else {}


def _text(value):
    return str(value or "").strip()


def uses_application_identity(endpoint):
    """Whether an endpoint's authentication resolves to the application's own credential."""
    if not isinstance(endpoint, dict):
        return False
    if _text(endpoint.get("provider") or "aoai").lower() in CALLER_CREDENTIAL_PROVIDERS:
        return False
    auth_type = _text(_section(endpoint, "auth").get("type") or "managed_identity").lower()
    return auth_type not in CALLER_CREDENTIAL_AUTH_TYPES


def _server_identity(endpoint_url):
    """``(cloud, authority, audience)`` derived from this deployment's settings only."""
    # Read only once the application identity is in play: this module is consulted
    # from the Key Vault hydration helper for every group and personal endpoint.
    from functions_settings import (
        get_model_endpoint_default_custom_authority,
        get_model_endpoint_management_cloud_for_environment,
        resolve_model_endpoint_foundry_scope,
    )

    cloud = get_model_endpoint_management_cloud_for_environment()
    try:
        audience = resolve_model_endpoint_foundry_scope({"management_cloud": cloud}, endpoint=endpoint_url)
    except ValueError:
        audience = ""
    return cloud, get_model_endpoint_default_custom_authority(), audience


def application_identity_violation(endpoint, *, include_identity_selection=True):
    """Return the refusal code for an endpoint that breaks the rule, or ``None``.

    Only endpoints that use the application identity can break it. A requested value
    equal to the deployment's own (for example the default audience) is not an override.
    ``include_identity_selection`` is off at use time, where a stored
    ``managed_identity_client_id`` is dropped rather than refused.
    """
    if not uses_application_identity(endpoint):
        return None
    from functions_settings import normalize_model_endpoint_management_cloud

    auth = _section(endpoint, "auth")
    endpoint_url = _section(endpoint, "connection").get("endpoint")
    cloud, authority, audience = _server_identity(endpoint_url)
    requested_audience = _text(auth.get("foundry_scope"))
    requested_authority = _text(auth.get("custom_authority"))
    requested_cloud = normalize_model_endpoint_management_cloud(auth.get("management_cloud"))
    if (
        (requested_audience and requested_audience != audience)
        or (requested_authority and requested_authority != authority)
        or (requested_cloud == "custom" and cloud != "custom")
    ):
        return APPLICATION_IDENTITY_OVERRIDE_REFUSED
    if include_identity_selection and _text(auth.get("managed_identity_client_id")):
        return APPLICATION_IDENTITY_SELECTION_REFUSED
    try:
        validate_azure_ai_endpoint_host(endpoint_url, cloud)
    except ValueError:
        return APPLICATION_IDENTITY_ENDPOINT_REFUSED
    return None


def with_server_identity(endpoint):
    """The endpoint with its identity settings taken from the deployment only."""
    if not uses_application_identity(endpoint):
        return endpoint
    cloud, authority, _audience = _server_identity(_section(endpoint, "connection").get("endpoint"))
    auth = {
        key: value for key, value in _section(endpoint, "auth").items()
        if key not in ("foundry_scope", "custom_authority", "managed_identity_client_id")
    }
    auth["management_cloud"] = cloud
    if authority:
        auth["custom_authority"] = authority
    return {**endpoint, "auth": auth}


def _refuse(code, scope, stage, endpoint):
    log_event(
        "[MODELS] Refused the application identity for a group or personal model endpoint.",
        extra={
            "scope": scope,
            "stage": stage,
            "reason": code,
            "provider": _text((endpoint or {}).get("provider") or "aoai").lower(),
            "endpoint_id": _text((endpoint or {}).get("id")),
        },
        level=logging.WARNING,
    )
    raise ApplicationIdentityPolicyError(APPLICATION_IDENTITY_MESSAGES[code], code)


def _identity_fields(endpoint):
    values = []
    for path in APPLICATION_IDENTITY_FIELDS:
        value = endpoint if isinstance(endpoint, dict) else {}
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        values.append(_text(value))
    return tuple(values)


def check_application_identity_request(endpoint, scope):
    """A transient (unsaved) discovery or test request: refuse any breach, else use the server's values."""
    if scope not in APPLICATION_IDENTITY_SCOPES:
        return endpoint
    code = application_identity_violation(endpoint)
    if code:
        _refuse(code, scope, "request", endpoint)
    return with_server_identity(endpoint)


def check_application_identity_save(endpoint, previous, scope):
    """A save: refuse a new endpoint, or a change to one, that breaks the rule.

    An endpoint whose rule-relevant configuration is unchanged from its stored version
    is left to the use-time check, so a record stored before this rule neither blocks an
    unrelated edit nor becomes usable.
    """
    if scope not in APPLICATION_IDENTITY_SCOPES:
        return
    if previous is not None and _identity_fields(endpoint) == _identity_fields(previous):
        return
    code = application_identity_violation(endpoint)
    if code:
        _refuse(code, scope, "save", endpoint)


def resolve_application_identity_for_use(endpoint, scope):
    """A stored endpoint about to be used: fail closed on a breach, and never honour a stored identity selection."""
    if scope not in APPLICATION_IDENTITY_SCOPES:
        return endpoint
    code = application_identity_violation(endpoint, include_identity_selection=False)
    if code:
        _refuse(code, scope, "use", endpoint)
    return with_server_identity(endpoint)
