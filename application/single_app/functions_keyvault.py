# functions_keyvault.py

import re
import logging
from functions_appinsights import log_event
from config import *
from functions_authentication import *
from functions_settings import *
from enum import Enum
import app_settings_cache

try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
except ImportError as e:
    raise ImportError("Required Azure SDK packages are not installed. Please install azure-identity and azure-keyvault-secrets.") from e

"""
KEY_VAULT_DOMAIN # ENV VAR from config.py
enable_key_vault_secret_storage # setting from functions_settings.py
key_vault_name # setting from functions_settings.py
key_vault_identity # setting from functions_settings.py
"""

supported_sources = [
    'action',
    'action-addset',
    'agent',
    'model-endpoint',
    'other'
]

supported_scopes = [
    'global',
    'user',
    'group'
]

supported_action_auth_types = [
    'key',
    'servicePrincipal',
    'basic',
    'username_password',
    'connection_string'
]

ui_trigger_word = "Stored_In_KeyVault"
SQL_PLUGIN_TYPES = {"sql_query", "sql_schema"}
SQL_PLUGIN_SENSITIVE_ADDITIONAL_FIELDS = {"connection_string", "password"}
SQL_PLUGIN_SENSITIVE_AUTH_FIELDS = {"client_secret"}
MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS = {
    "api_key": {"api_key"},
    "client_secret": {"service_principal"},
}
REDACTED_SECRET_VALUE = "***REDACTED***"

class SecretReturnType(Enum):
    VALUE = "value"
    TRIGGER = "trigger"
    NAME = "name"


def _get_nested_dict_value(data, path):
    """Return a nested dictionary value, or None when the path is missing."""
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current.get(key)
    return current


def _set_nested_dict_value(data, path, value):
    """Set a nested dictionary value while preserving dictionary copies."""
    current = data
    for key in path[:-1]:
        nested = current.get(key)
        if not isinstance(nested, dict):
            nested = {}
        else:
            nested = dict(nested)
        current[key] = nested
        current = nested
    current[path[-1]] = value


def _get_existing_secret_reference(existing_plugin, path):
    """Return an existing Key Vault reference for the provided path, when present."""
    existing_value = _get_nested_dict_value(existing_plugin or {}, path)
    if isinstance(existing_value, str) and validate_secret_name_dynamic(existing_value):
        return existing_value
    return None


def _build_plugin_additional_field_secret_name(plugin_name, field_name):
    """Build a stable Key Vault secret base name for plugin additional fields."""
    return f"{plugin_name}-{field_name}".replace("__", "-")


def _build_model_endpoint_secret_name(field_name):
    """Build a stable Key Vault secret base name for model endpoint auth fields."""
    return f"model-endpoint-{field_name}".replace("_", "-")


def _is_sql_plugin(plugin_dict):
    """Return True when the plugin manifest is a SQL action."""
    plugin_type = (plugin_dict or {}).get("type", "")
    return isinstance(plugin_type, str) and plugin_type.lower() in SQL_PLUGIN_TYPES


def _is_sql_sensitive_additional_field(plugin_dict, field_name):
    """Return True when the additional field should be treated as a SQL secret."""
    return _is_sql_plugin(plugin_dict) and field_name in SQL_PLUGIN_SENSITIVE_ADDITIONAL_FIELDS


def _store_plugin_secret_reference(updated_plugin, existing_plugin, path, secret_name, scope_value, source, scope):
    """Store or preserve a plugin secret reference for the provided nested path."""
    value = _get_nested_dict_value(updated_plugin, path)
    if not value:
        return

    existing_reference = _get_existing_secret_reference(existing_plugin, path)

    if value == ui_trigger_word:
        if existing_reference:
            _set_nested_dict_value(updated_plugin, path, existing_reference)
            return
        _set_nested_dict_value(
            updated_plugin,
            path,
            build_full_secret_name(secret_name, scope_value, source, scope),
        )
        return

    if validate_secret_name_dynamic(value):
        _set_nested_dict_value(updated_plugin, path, value)
        return

    full_secret_name = store_secret_in_key_vault(
        secret_name,
        value,
        scope_value,
        source=source,
        scope=scope,
    )
    _set_nested_dict_value(updated_plugin, path, full_secret_name)


def redact_plugin_secret_values(plugin_dict, redaction_value=REDACTED_SECRET_VALUE):
    """Return a copy of the plugin manifest with secret-bearing values redacted."""
    if not isinstance(plugin_dict, dict):
        return plugin_dict

    redacted = dict(plugin_dict)
    auth = redacted.get("auth", {})
    if isinstance(auth, dict):
        new_auth = dict(auth)
        if new_auth.get("key"):
            new_auth["key"] = redaction_value
        for auth_field in SQL_PLUGIN_SENSITIVE_AUTH_FIELDS:
            if new_auth.get(auth_field):
                new_auth[auth_field] = redaction_value
        redacted["auth"] = new_auth

    additional_fields = redacted.get("additionalFields", {})
    if isinstance(additional_fields, dict):
        new_additional_fields = dict(additional_fields)
        for key, value in additional_fields.items():
            if not value:
                continue
            if key.endswith("__Secret") or _is_sql_sensitive_additional_field(redacted, key):
                new_additional_fields[key] = redaction_value
        redacted["additionalFields"] = new_additional_fields

    return redacted


def redact_model_endpoint_secret_values(endpoint_dict, redaction_value=REDACTED_SECRET_VALUE):
    """Return a copy of a model endpoint manifest with secret-bearing auth values redacted."""
    if not isinstance(endpoint_dict, dict):
        return endpoint_dict

    redacted = dict(endpoint_dict)
    auth = redacted.get("auth", {})
    if isinstance(auth, dict):
        new_auth = dict(auth)
        for auth_field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS:
            if new_auth.get(auth_field):
                new_auth[auth_field] = redaction_value
        redacted["auth"] = new_auth

    return redacted

def retrieve_secret_from_key_vault(secret_name, scope_value, scope="global", source="global"):
    """
    Retrieve a secret from Key Vault using a dynamic name based on source, scope, and scope_value.

    Args:
        secret_name (str): The base name of the secret.
        scope_value (str): The value for the scope (e.g., user id).
        scope (str): The scope (e.g., 'user', 'global').
        source (str): The source (e.g., 'agent', 'plugin').

    Returns:
        str: The value of the retrieved secret.
    Raises:
        Exception: If retrieval fails or configuration is invalid.
    """
    if source not in supported_sources:
        log_event(f"Source '{source}' is not supported. Supported sources: {supported_sources}", level=logging.ERROR)
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    full_secret_name = build_full_secret_name(secret_name, scope_value, source, scope)
    return retrieve_secret_from_key_vault_by_full_name(full_secret_name)

def retrieve_secret_from_key_vault_by_full_name(full_secret_name):
    """
    Retrieve a secret from Key Vault using a preformatted full secret name.

    Args:
        full_secret_name (str): The full secret name (already formatted).

    Returns:
        str: The value of the retrieved secret.
    Raises:
        Exception: If retrieval fails or configuration is invalid.
    """
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    if not enable_key_vault_secret_storage:
        return full_secret_name

    key_vault_name = settings.get("key_vault_name", None)
    if not key_vault_name:
        return full_secret_name

    if not validate_secret_name_dynamic(full_secret_name):
        return full_secret_name

    try:
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        secret_client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())

        retrieved_secret = secret_client.get_secret(full_secret_name)
        log_event(f"Secret '{full_secret_name}' retrieved successfully from Key Vault.", level=logging.INFO)
        return retrieved_secret.value
    except Exception as e:
        log_event(f"Failed to retrieve secret '{full_secret_name}' from Key Vault: {str(e)}", level=logging.ERROR, exceptionTraceback=True)
        return full_secret_name
        
def retrieve_secret_direct(secret_name, settings=None):
    """
    Retrieve a secret directly from Key Vault by its exact name, bypassing source/scope name
    validation and the enable_key_vault_secret_storage guard. Use this for infrastructure
    secrets (e.g. Redis key) where the secret name is arbitrary and not controlled by the
    scope_value--source--scope--secret_name convention.

    Args:
        secret_name (str): The exact Key Vault secret name.
        settings (dict, optional): Settings dict to use directly. If None, falls back to
            app_settings_cache.get_settings_cache(). Pass settings explicitly when calling
            before the cache is initialised (e.g. during configure_app_cache bootstrap).

    Returns:
        str: The secret value.

    Raises:
        ValueError: If Key Vault is not configured in settings.
        Exception: If the secret cannot be retrieved.
    """
    # Use provided settings directly when supplied (e.g. during bootstrap before the
    # settings cache is initialised), otherwise fall back to the cache.
    if settings is None:
        settings = app_settings_cache.get_settings_cache()

    
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)

    if not enable_key_vault_secret_storage:
        raise ValueError("Key Vault secret storage is not enabled in settings.")

    key_vault_name = settings.get("key_vault_name", "").strip()
    if not key_vault_name:
        raise ValueError("Key Vault name is not configured in settings (key_vault_name).")
    if not secret_name:
        raise ValueError("secret_name must not be empty.")

    try:
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        # Pass settings through so get_keyvault_credential doesn't call the uninitialised cache.
        secret_client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential(settings=settings))
        retrieved = secret_client.get_secret(secret_name)
        log_event(f"Secret '{secret_name}' retrieved successfully from Key Vault.", level=logging.INFO)
        return retrieved.value
    except Exception as e:
        log_event(f"Failed to retrieve secret '{secret_name}' from Key Vault: {str(e)}", level=logging.ERROR, exceptionTraceback=True)
        raise

def store_secret_in_key_vault(secret_name, secret_value, scope_value, source="global", scope="global"):
    """
    Store a secret in Key Vault using a dynamic name based on source, scope, and scope_value.

    Args:
        secret_name (str): The base name of the secret.
        secret_value (str): The value to store in Key Vault.
        scope_value (str): The value for the scope (e.g., user id).
        source (str): The source (e.g., 'agent', 'plugin').
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        str: The full secret name used in Key Vault.
    Raises:
        Exception: If storing fails or configuration is invalid.
    """
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    if not enable_key_vault_secret_storage:
        log_event("Key Vault secret storage is not enabled.", level=logging.WARNING)
        return secret_value

    key_vault_name = settings.get("key_vault_name", None)
    if not key_vault_name:
        log_event("Key Vault name is not configured.", level=logging.WARNING)
        return secret_value

    if source not in supported_sources:
        log_event(f"Source '{source}' is not supported. Supported sources: {supported_sources}", level=logging.ERROR)
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    full_secret_name = build_full_secret_name(secret_name, scope_value, source, scope)

    try:
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        secret_client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
        secret_client.set_secret(full_secret_name, secret_value)
        log_event(f"Secret '{full_secret_name}' stored successfully in Key Vault.", level=logging.INFO)
        return full_secret_name
    except Exception as e:
        log_event(f"Failed to store secret '{full_secret_name}' in Key Vault: {str(e)}", level=logging.ERROR, exceptionTraceback=True)
        return secret_value

def build_full_secret_name(secret_name, scope_value, source, scope):
    """
    Build the full secret name for Key Vault and check its length.

    Args:
        secret_name (str): The base name of the secret.
        scope_value (str): The value for the scope (e.g., user id).
        source (str): The source (e.g., 'agent', 'plugin').
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        str: The constructed full secret name.
    Raises:
        ValueError: If the name exceeds 127 characters.
    """
    full_secret_name = f"{clean_name_for_keyvault(scope_value)}--{source}--{scope}--{clean_name_for_keyvault(secret_name)}"
    if not validate_secret_name_dynamic(full_secret_name):
        log_event(f"The full secret name '{full_secret_name}' is invalid.", level=logging.ERROR)
        raise ValueError(f"The full secret name '{full_secret_name}' is invalid.")
    return full_secret_name

def validate_secret_name_dynamic(secret_name):
    """
    Validate a Key Vault secret name using a dynamically built regex based on supported scopes and sources.
    The secret_name and scope_value can be wildcards, but scope and source must match supported lists.

    Args:
        secret_name (str): The full secret name to validate.

    Returns:
        bool: True if valid, False otherwise.
    """
    # Build regex pattern dynamically
    scopes_pattern = '|'.join(re.escape(scope) for scope in supported_scopes)
    sources_pattern = '|'.join(re.escape(source) for source in supported_sources)
    # Wildcards for secret_name and scope_value
    pattern = rf"^(.+)--({sources_pattern})--({scopes_pattern})--(.+)$"
    match = re.match(pattern, secret_name)
    if not match:
        return False
    # Optionally, check length
    if len(secret_name) > 127:
        return False
    return True

def keyvault_agent_save_helper(agent_dict, scope_value, scope="global"):
    """
    For agent dicts, store sensitive keys in Key Vault and replace their values with the Key Vault secret name.
    Only processes 'azure_agent_apim_gpt_subscription_key' and 'azure_openai_gpt_key'.

    Args:
        agent_dict (dict): The agent dictionary to process.
        scope_value (str): The value for the scope (e.g., agent id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        dict: A new agent dict with sensitive values replaced by Key Vault references.
    Raises:
        Exception: If storing a key in Key Vault fails.
    """
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return agent_dict
    source = "agent"
    updated = dict(agent_dict)
    agent_name = updated.get('name', 'agent')
    use_apim = updated.get('enable_agent_gpt_apim', False)
    key = 'azure_agent_apim_gpt_subscription_key' if use_apim else 'azure_openai_gpt_key'
    if key in updated and updated[key]:
        value = updated[key]
        secret_name = agent_name
        if value == ui_trigger_word:
            updated[key] = build_full_secret_name(secret_name, scope_value, source, scope)
        elif validate_secret_name_dynamic(value):
            updated[key] = build_full_secret_name(secret_name, scope_value, source, scope)
        else:
            try:
                full_secret_name = store_secret_in_key_vault(secret_name, value, scope_value, source=source, scope=scope)
                updated[key] = full_secret_name
            except Exception as e:
                log_event(f"Failed to store agent key '{key}' in Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                raise Exception(f"Failed to store agent key '{key}' in Key Vault: {e}")
    else:
        log_event(f"Agent key '{key}' not found while APIM is '{use_apim}' or empty in agent '{agent_name}'. No action taken.", level=logging.INFO)
    return updated

def keyvault_agent_get_helper(agent_dict, scope_value, scope="global", return_type=SecretReturnType.TRIGGER):
    """
    For agent dicts, retrieve sensitive keys from Key Vault if they are stored as Key Vault references.
    Only processes 'azure_agent_apim_gpt_subscription_key' and 'azure_openai_gpt_key'.

    Args:
        agent_dict (dict): The agent dictionary to process.
        scope_value (str): The value for the scope (e.g., agent id).
        scope (str): The scope (e.g., 'user', 'global').
        return_actual_key (bool): If True, retrieves the actual secret value from Key Vault. If False, replaces with ui_trigger_word.

    Returns:
        dict: A new agent dict with sensitive values replaced by Key Vault references.
    Raises:
        Exception: If retrieving a key from Key Vault fails.
    """
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return agent_dict
    updated = dict(agent_dict)
    agent_name = updated.get('name', 'agent')
    use_apim = updated.get('enable_agent_gpt_apim', False)
    key = 'azure_agent_apim_gpt_subscription_key' if use_apim else 'azure_openai_gpt_key'
    if key in updated and updated[key]:
        value = updated[key]
        if validate_secret_name_dynamic(value):
            try:
                if return_type == SecretReturnType.VALUE:
                    actual_key = retrieve_secret_from_key_vault_by_full_name(value)
                    updated[key] = actual_key
                elif return_type == SecretReturnType.NAME:
                    updated[key] = value
                else:
                    updated[key] = ui_trigger_word
            except Exception as e:
                log_event(f"Failed to retrieve agent key '{key}' for agent '{agent_name}' from Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                return updated
    return updated

def keyvault_plugin_save_helper(plugin_dict, scope_value, scope="global", existing_plugin=None):
    """
    For plugin dicts, store the auth.key in Key Vault if auth.type is 'key', 'servicePrincipal', 'basic', or 'connection_string',
    and replace its value with the Key Vault secret name. Also supports dynamic secret storage for any additionalFields key ending with '__Secret',
    along with SQL plugin secret-bearing additional fields such as connection strings and passwords.

    Args:
        plugin_dict (dict): The plugin dictionary to process.
        scope_value (str): The value for the scope (e.g., plugin id).
        scope (str): The scope (e.g., 'user', 'global').
        existing_plugin (dict, optional): Existing stored plugin manifest used to preserve Key Vault references during edit flows.

    Returns:
        dict: A new plugin dict with sensitive values replaced by Key Vault references.
    Raises:
        Exception: If storing a key in Key Vault fails.

    Feature:
        Any key in additionalFields ending with '__Secret' will be stored in Key Vault and replaced with a Key Vault reference.
        This allows plugin writers to dynamically store secrets without custom code.
    """
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    source = "action"  # Use 'action' for plugins per app convention
    updated = dict(plugin_dict)
    plugin_name = updated.get('name', 'plugin')
    auth = updated.get('auth', {})
    if isinstance(auth, dict):
        auth = dict(auth)
        updated['auth'] = auth
        auth_type = auth.get('type', None)
        if auth_type in supported_action_auth_types and 'key' in auth and auth['key']:
            try:
                _store_plugin_secret_reference(
                    updated,
                    existing_plugin,
                    ('auth', 'key'),
                    plugin_name,
                    scope_value,
                    source,
                    scope,
                )
            except Exception as e:
                log_event(f"Failed to store plugin key in Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                raise Exception(f"Failed to store plugin key in Key Vault: {e}")
        else:
            log_event(f"Auth type '{auth_type}' does not require Key Vault storage for plugin '{plugin_name}'.", level=logging.INFO)

        for auth_field in SQL_PLUGIN_SENSITIVE_AUTH_FIELDS:
            if auth.get(auth_field):
                try:
                    _store_plugin_secret_reference(
                        updated,
                        existing_plugin,
                        ('auth', auth_field),
                        f"{plugin_name}-{auth_field}",
                        scope_value,
                        source,
                        scope,
                    )
                except Exception as e:
                    log_event(
                        f"Failed to store plugin auth secret '{auth_field}' in Key Vault: {e}",
                        level=logging.ERROR,
                        exceptionTraceback=True,
                    )
                    raise Exception(f"Failed to store plugin auth secret '{auth_field}' in Key Vault: {e}")

    # Handle additionalFields dynamic secrets
    additional_fields = updated.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        new_additional_fields = dict(additional_fields)
        updated['additionalFields'] = new_additional_fields
        for k, v in additional_fields.items():
            if not v:
                continue
            if k.endswith('__Secret'):
                addset_source = 'action-addset'
                base_field = k[:-8]  # Remove '__Secret'
                akv_key = _build_plugin_additional_field_secret_name(plugin_name, base_field)
                try:
                    _store_plugin_secret_reference(
                        updated,
                        existing_plugin,
                        ('additionalFields', k),
                        akv_key,
                        scope_value,
                        addset_source,
                        scope,
                    )
                except Exception as e:
                    log_event(f"Failed to store plugin additionalField secret '{k}' in Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Failed to store plugin additionalField secret '{k}' in Key Vault: {e}")
            elif _is_sql_sensitive_additional_field(updated, k):
                addset_source = 'action-addset'
                akv_key = _build_plugin_additional_field_secret_name(plugin_name, k)
                try:
                    _store_plugin_secret_reference(
                        updated,
                        existing_plugin,
                        ('additionalFields', k),
                        akv_key,
                        scope_value,
                        addset_source,
                        scope,
                    )
                except Exception as e:
                    log_event(
                        f"Failed to store SQL plugin additionalField secret '{k}' in Key Vault: {e}",
                        level=logging.ERROR,
                        exceptionTraceback=True,
                    )
                    raise Exception(f"Failed to store SQL plugin additionalField secret '{k}' in Key Vault: {e}")
    return updated
# Helper to retrieve plugin secrets from Key Vault
def keyvault_plugin_get_helper(plugin_dict, scope_value, scope="global", return_type=SecretReturnType.TRIGGER):
    """
    For plugin dicts, retrieve secrets from Key Vault for auth.key and any additionalFields key ending with '__Secret'.
    If the value is a Key Vault reference, retrieve the actual secret and replace with ui_trigger_word.

    Args:
        plugin_dict (dict): The plugin dictionary to process.
        scope_value (str): The value for the scope (e.g., plugin id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        dict: A new plugin dict with sensitive values replaced by ui_trigger_word if stored in Key Vault.
    """
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    updated = dict(plugin_dict)
    plugin_name = updated.get('name', 'plugin')
    auth = updated.get('auth', {})
    if isinstance(auth, dict):
        new_auth = dict(auth)
        auth_updated = False
        for auth_field in ('key', *SQL_PLUGIN_SENSITIVE_AUTH_FIELDS):
            value = auth.get(auth_field)
            if value and validate_secret_name_dynamic(value):
                try:
                    if return_type == SecretReturnType.VALUE:
                        new_auth[auth_field] = retrieve_secret_from_key_vault_by_full_name(value)
                    elif return_type == SecretReturnType.NAME:
                        new_auth[auth_field] = value
                    else:
                        new_auth[auth_field] = ui_trigger_word
                    auth_updated = True
                except Exception as e:
                    log_event(f"Failed to retrieve action {plugin_name} auth field '{auth_field}' from Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Failed to retrieve action {plugin_name} auth field '{auth_field}' from Key Vault: {e}")
        if auth_updated:
            updated['auth'] = new_auth

    additional_fields = updated.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        new_additional_fields = dict(additional_fields)
        for k, v in additional_fields.items():
            if (k.endswith('__Secret') or _is_sql_sensitive_additional_field(updated, k)) and v and validate_secret_name_dynamic(v):
                try:
                    if return_type == SecretReturnType.VALUE:
                        new_additional_fields[k] = retrieve_secret_from_key_vault_by_full_name(v)
                    elif return_type == SecretReturnType.NAME:
                        new_additional_fields[k] = v
                    else:
                        new_additional_fields[k] = ui_trigger_word
                except Exception as e:
                    log_event(f"Failed to retrieve action additionalField secret '{k}' from Key Vault: {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Failed to retrieve action additionalField secret '{k}' from Key Vault: {e}")
        updated['additionalFields'] = new_additional_fields
    return updated


def keyvault_model_endpoint_save_helper(endpoint_dict, scope_value, scope="global", existing_endpoint=None):
    """Store model endpoint auth secrets in Key Vault and replace them with references."""
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return endpoint_dict

    updated = dict(endpoint_dict)
    auth = updated.get("auth", {})
    if not isinstance(auth, dict):
        return updated

    updated_auth = dict(auth)
    updated["auth"] = updated_auth
    auth_type = (updated_auth.get("type") or "managed_identity").lower()
    source = "model-endpoint"

    for auth_field, supported_auth_types in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS.items():
        existing_reference = _get_existing_secret_reference(existing_endpoint, ("auth", auth_field))
        value = updated_auth.get(auth_field)

        if auth_type not in supported_auth_types:
            updated_auth.pop(auth_field, None)
            continue

        if value in (None, ""):
            if existing_reference:
                updated_auth[auth_field] = existing_reference
            else:
                updated_auth.pop(auth_field, None)
            continue

        if value == ui_trigger_word:
            if existing_reference:
                updated_auth[auth_field] = existing_reference
            else:
                updated_auth.pop(auth_field, None)
            continue

        if validate_secret_name_dynamic(value):
            updated_auth[auth_field] = value
            continue

        secret_name = _build_model_endpoint_secret_name(auth_field)
        updated_auth[auth_field] = store_secret_in_key_vault(
            secret_name,
            value,
            scope_value,
            source=source,
            scope=scope,
        )

    return updated


def keyvault_model_endpoint_get_helper(endpoint_dict, scope_value, scope="global", return_type=SecretReturnType.TRIGGER):
    """Resolve model endpoint auth secrets from Key Vault for backend or frontend use."""
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.ERROR)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return endpoint_dict

    updated = dict(endpoint_dict)
    auth = updated.get("auth", {})
    if not isinstance(auth, dict):
        return updated

    updated_auth = dict(auth)
    auth_updated = False
    for auth_field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS:
        value = updated_auth.get(auth_field)
        if not value or not validate_secret_name_dynamic(value):
            continue
        if return_type == SecretReturnType.VALUE:
            updated_auth[auth_field] = retrieve_secret_from_key_vault_by_full_name(value)
        elif return_type == SecretReturnType.NAME:
            updated_auth[auth_field] = value
        else:
            updated_auth[auth_field] = ui_trigger_word
        auth_updated = True

    if auth_updated:
        updated["auth"] = updated_auth
    return updated


def keyvault_model_endpoint_delete_helper(endpoint_dict, scope_value, scope="global"):
    """Delete Key Vault-backed model endpoint auth secrets referenced by an endpoint."""
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.WARNING)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return endpoint_dict

    auth = endpoint_dict.get("auth", {})
    if not isinstance(auth, dict):
        return endpoint_dict

    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
    for auth_field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS:
        secret_name = auth.get(auth_field)
        if not secret_name or not validate_secret_name_dynamic(secret_name):
            continue
        try:
            log_event(
                f"Deleting model endpoint auth secret '{auth_field}' for '{scope}' '{scope_value}'",
                level=logging.INFO,
            )
            client.begin_delete_secret(secret_name)
        except Exception as e:
            log_event(
                f"Error deleting model endpoint auth secret '{auth_field}' for '{scope}' '{scope_value}': {e}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            raise Exception(f"Error deleting model endpoint auth secret '{auth_field}' for '{scope}' '{scope_value}': {e}")

    return endpoint_dict


def keyvault_model_endpoint_cleanup_helper(previous_endpoint, current_endpoint, scope_value, scope="global"):
    """Delete obsolete Key Vault-backed endpoint auth secrets that are no longer referenced."""
    previous_auth = (previous_endpoint or {}).get("auth", {})
    current_auth = (current_endpoint or {}).get("auth", {})
    if not isinstance(previous_auth, dict) or not isinstance(current_auth, dict):
        return current_endpoint

    obsolete_auth = {}
    for auth_field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS:
        previous_secret = previous_auth.get(auth_field)
        current_secret = current_auth.get(auth_field)
        if previous_secret and validate_secret_name_dynamic(previous_secret) and previous_secret != current_secret:
            obsolete_auth[auth_field] = previous_secret

    if obsolete_auth:
        keyvault_model_endpoint_delete_helper({"auth": obsolete_auth}, scope_value, scope=scope)

    return current_endpoint


# Helper to delete plugin secrets from Key Vault
def keyvault_plugin_delete_helper(plugin_dict, scope_value, scope="global"):
    """
    For plugin dicts, delete secrets from Key Vault for auth.key and any additionalFields key ending with '__Secret'.
    Only deletes if the value is a Key Vault reference.

    Args:
        plugin_dict (dict): The plugin dictionary to process.
        scope_value (str): The value for the scope (e.g., plugin id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        plugin_dict (dict): The original plugin dict.
    Raises:
    """
    if scope not in supported_scopes:
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level=logging.WARNING)
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        log_event("Key Vault secret storage is not enabled or key vault name is missing.", level=logging.WARNING)
        return plugin_dict
    source = "action"
    plugin_name = plugin_dict.get('name', 'plugin')
    auth = plugin_dict.get('auth', {})
    if isinstance(auth, dict):
        for auth_field in ('key', *SQL_PLUGIN_SENSITIVE_AUTH_FIELDS):
            secret_name = auth.get(auth_field)
            if secret_name and validate_secret_name_dynamic(secret_name):
                try:
                    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
                    log_event(f"Deleting action auth secret '{auth_field}' for action '{plugin_name}' for '{scope}' '{scope_value}'", level=logging.INFO)
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(secret_name)
                except Exception as e:
                    log_event(f"Error deleting action auth secret '{auth_field}' for action '{plugin_name}': {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Error deleting action auth secret '{auth_field}' for action '{plugin_name}': {e}")

    additional_fields = plugin_dict.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        for k, v in additional_fields.items():
            if (k.endswith('__Secret') or _is_sql_sensitive_additional_field(plugin_dict, k)) and v and validate_secret_name_dynamic(v):
                try:
                    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
                    log_event(f"Deleting action additionalField secret '{k}' for action '{plugin_name}' for '{scope}' '{scope_value}'", level=logging.INFO)
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(v)
                except Exception as e:
                    log_event(f"Error deleting action additionalField secret '{k}' for action '{plugin_name}': {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Error deleting action additionalField secret '{k}' for action '{plugin_name}': {e}")
    return plugin_dict

# Helper to delete agent secrets from Key Vault
def keyvault_agent_delete_helper(agent_dict, scope_value, scope="global"):
    """
    For agent dicts, delete sensitive keys from Key Vault if they are stored as Key Vault references.
    Only processes 'azure_agent_apim_gpt_subscription_key' and 'azure_openai_gpt_key'.

    Args:
        agent_dict (dict): The agent dictionary to process.
        scope_value (str): The value for the scope (e.g., agent id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        agent_dict (dict): The original agent dict.
    """
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        return agent_dict
    source = "agent"
    updated = dict(agent_dict)
    agent_name = updated.get('name', 'agent')
    use_apim = updated.get('enable_agent_gpt_apim', False)
    keys = ['azure_agent_apim_gpt_subscription_key'] if use_apim else ['azure_openai_gpt_key']
    for key in keys:
        if key in updated and updated[key]:
            secret_name = updated[key]
            if validate_secret_name_dynamic(secret_name):
                try:
                    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
                    log_event(f"Deleting agent secret '{secret_name}' for agent '{agent_name}' for '{scope}' '{scope_value}'", level=logging.INFO)
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(secret_name)
                except Exception as e:
                    log_event(f"Error deleting secret '{secret_name}' for agent '{agent_name}': {e}", level=logging.ERROR, exceptionTraceback=True)
                    raise Exception(f"Error deleting secret '{secret_name}' for agent '{agent_name}': {e}")
    return agent_dict

def get_keyvault_credential(settings=None):
    """
    Get the Key Vault credential using DefaultAzureCredential, optionally with a managed identity client ID.

    Args:
        settings (dict, optional): Settings dict to use directly. If None, falls back to
            app_settings_cache.get_settings_cache(). Pass settings explicitly when calling
            before the cache is initialised (e.g. during configure_app_cache bootstrap).

    Returns:
        DefaultAzureCredential: The credential object for Key Vault access.
    """
    if settings is None:
        settings = app_settings_cache.get_settings_cache()

    key_vault_identity = settings.get("key_vault_identity", None)
    if key_vault_identity is not None:
        credential = DefaultAzureCredential(managed_identity_client_id=key_vault_identity)
    else:
        credential = DefaultAzureCredential()
    return credential

def clean_name_for_keyvault(name):
    """
    Clean a name to be used as a Key Vault secret name by removing invalid characters and truncating to 127 characters.

    Args:
        name (str): The name to clean.

    Returns:
        str: The cleaned name.
    """
    # Remove invalid characters
    cleaned_name = re.sub(r"[^a-zA-Z0-9-]", "-", name)
    # Truncate to 127 characters
    return cleaned_name[:127]
