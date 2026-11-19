# agent_credential_contracts.py
"""Bootstrap-free, owner-bound agent credential contracts."""

import hashlib
import hmac
import json

from functions_model_endpoint_validation import ModelEndpointValidationError

AGENT_CREDENTIAL_REVISION = 1
AGENT_CREDENTIAL_BINDINGS = "_agent_credential_bindings"
AGENT_CREDENTIAL_STATUS = "credential_reentry_required"
AGENT_SECRET_LABELS = {
    ("azure_openai_gpt_key",): "Azure OpenAI API key",
    ("azure_agent_apim_gpt_subscription_key",): "APIM subscription key",
    ("azure_apim_gpt_subscription_key",): "Legacy APIM subscription key",
    ("other_settings", "azure_ai_foundry", "client_secret"): "Foundry client secret",
    ("other_settings", "new_foundry", "client_secret"): "New Foundry client secret",
    ("other_settings", "foundry_workflow", "client_secret"): "Foundry Workflow client secret",
}
AGENT_SECRET_MASKS = frozenset({
    "Stored_In_KeyVault", "***REDACTED***", "[REDACTED]", "********", "**********",
})


class AgentCredentialReentryRequired(ModelEndpointValidationError):
    """A stable, secret-free error for legacy or unavailable agent credentials."""

    def __init__(self, *, incomplete=False, agent_id=None, scope=None, owner_id=None):
        message = (
            "Custom agent connections require their own endpoint, credential, deployment, "
            "and API version. Complete the connection in the agent editor or choose an approved saved connection."
            if incomplete else
            "Agent credentials need updating. Re-enter the affected credentials in "
            "the agent editor, or ask the agent's owner or an administrator to update them."
        )
        super().__init__(message)
        self.incomplete = incomplete
        self.agent_id = agent_id
        self.agent_scope = scope
        self.agent_owner_id = owner_id


def credential_value(record, path):
    value = record
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def set_credential_value(record, path, value):
    parent = record
    for part in path[:-1]:
        child = parent.get(part)
        if not isinstance(child, dict):
            child = {}
            parent[part] = child
        parent = child
    parent[path[-1]] = value


def agent_credential_scope(scope, owner_id, agent_id, path):
    """Hash the complete binding, never truncate identity components."""
    if scope not in {"user", "group", "global"} or not owner_id or not agent_id:
        raise ValueError("An authorized agent credential scope is required.")
    if path not in AGENT_SECRET_LABELS:
        raise ValueError("Unsupported agent credential field.")
    encoded = json.dumps([scope, str(owner_id), str(agent_id), list(path)], separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def agent_credential_target(record, path):
    """Keep a saved credential from following an edited endpoint or token authority."""
    if path[0] == "other_settings":
        section = credential_value(record, path[:2]) or {}
        values = [
            section.get(field) for field in (
                "endpoint", "authority", "cloud", "tenant_id", "client_id", "foundry_scope",
            )
        ]
        values.append(record.get("azure_openai_gpt_endpoint"))
    else:
        endpoint_field = {
            "azure_openai_gpt_key": "azure_openai_gpt_endpoint",
            "azure_agent_apim_gpt_subscription_key": "azure_agent_apim_gpt_endpoint",
            "azure_apim_gpt_subscription_key": "azure_apim_gpt_endpoint",
        }[path[0]]
        values = [record.get(endpoint_field)]
    return tuple(
        value.strip().rstrip("/") if isinstance(value, str) else "" if value is None else value
        for value in values
    )


def _credential_digest(value, binding, target):
    encoded = json.dumps([AGENT_CREDENTIAL_REVISION, binding, value, target], separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def agent_credential_is_ready(record, path, scope, owner_id):
    value = credential_value(record, path)
    if not isinstance(value, str) or not value or value in AGENT_SECRET_MASKS:
        return False
    binding = agent_credential_scope(scope, owner_id, record.get("id"), path)
    bindings = record.get(AGENT_CREDENTIAL_BINDINGS)
    if not isinstance(bindings, dict):
        return False
    stored = bindings.get("/" + "/".join(path))
    return (
        isinstance(stored, str) and stored.isascii() and len(stored) == 64
        and hmac.compare_digest(stored, _credential_digest(value, binding, agent_credential_target(record, path)))
    )


def bind_agent_credential(record, path, scope, owner_id):
    binding = agent_credential_scope(scope, owner_id, record.get("id"), path)
    bindings = dict(record.get(AGENT_CREDENTIAL_BINDINGS) or {})
    bindings["/" + "/".join(path)] = _credential_digest(
        credential_value(record, path), binding, agent_credential_target(record, path),
    )
    record[AGENT_CREDENTIAL_BINDINGS] = bindings


def agent_credential_status(record, scope, owner_id):
    return [
        {"path": "/" + "/".join(path), "label": label}
        for path, label in AGENT_SECRET_LABELS.items()
        if credential_value(record, path) not in (None, "")
        and not agent_credential_is_ready(record, path, scope, owner_id)
    ]
