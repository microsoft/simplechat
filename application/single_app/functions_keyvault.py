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

class SecretReturnType(Enum):
    VALUE = "value"
    TRIGGER = "trigger"
    NAME = "name"

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
        logging.error(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        logging.error(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
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
        print(f"Secret '{full_secret_name}' retrieved successfully from Key Vault.")
        return retrieved_secret.value
    except Exception as e:
        logging.error(f"Failed to retrieve secret '{full_secret_name}' from Key Vault: {str(e)}")
        return full_secret_name
        

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
        logging.warn(f"Key Vault secret storage is not enabled.")
        return secret_value

    key_vault_name = settings.get("key_vault_name", None)
    if not key_vault_name:
        logging.warn(f"Key Vault name is not configured.")
        return secret_value

    if source not in supported_sources:
        logging.error(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        logging.error(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")


    full_secret_name = build_full_secret_name(secret_name, scope_value, source, scope)

    try:
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        secret_client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
        secret_client.set_secret(full_secret_name, secret_value)
        print(f"Secret '{full_secret_name}' stored successfully in Key Vault.")
        return full_secret_name
    except Exception as e:
        logging.error(f"Failed to store secret '{full_secret_name}' in Key Vault: {str(e)}")
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
        logging.error(f"The full secret name '{full_secret_name}' is invalid.")
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
                logging.error(f"Failed to store agent key '{key}' in Key Vault: {e}")
                raise Exception(f"Failed to store agent key '{key}' in Key Vault: {e}")
    else:
        log_event(f"Agent key '{key}' not found while APIM is '{use_apim}' or empty in agent '{agent_name}'. No action taken.", level="INFO")
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
                logging.error(f"Failed to retrieve agent key '{key}' for agent '{agent_name}' from Key Vault: {e}")
                return updated
    return updated

def keyvault_plugin_save_helper(plugin_dict, scope_value, scope="global"):
    """
    For plugin dicts, store the auth.key in Key Vault if auth.type is 'key', 'servicePrincipal', 'basic', or 'connection_string',
    and replace its value with the Key Vault secret name. Also supports dynamic secret storage for any additionalFields key ending with '__Secret'.

    Args:
        plugin_dict (dict): The plugin dictionary to process.
        scope_value (str): The value for the scope (e.g., plugin id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        dict: A new plugin dict with sensitive values replaced by Key Vault references.
    Raises:
        Exception: If storing a key in Key Vault fails.

    Feature:
        Any key in additionalFields ending with '__Secret' will be stored in Key Vault and replaced with a Key Vault reference.
        This allows plugin writers to dynamically store secrets without custom code.
    """
    if scope not in supported_scopes:
        logging.error(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    source = "action"  # Use 'action' for plugins per app convention
    updated = dict(plugin_dict)
    plugin_name = updated.get('name', 'plugin')
    auth = updated.get('auth', {})
    if isinstance(auth, dict):
        auth_type = auth.get('type', None)
        if auth_type in supported_action_auth_types and 'key' in auth and auth['key']:
            value = auth['key']
            if value == ui_trigger_word:
                auth['key'] = build_full_secret_name(plugin_name, scope_value, source, scope)
                updated['auth'] = auth
            elif validate_secret_name_dynamic(value):
                auth['key'] = build_full_secret_name(plugin_name, scope_value, source, scope)
                updated['auth'] = auth
            else:
                try:
                    full_secret_name = store_secret_in_key_vault(plugin_name, value, scope_value, source=source, scope=scope)
                    new_auth = dict(auth)
                    new_auth['key'] = full_secret_name
                    updated['auth'] = new_auth
                except Exception as e:
                    logging.error(f"Failed to store plugin key in Key Vault: {e}")
                    raise Exception(f"Failed to store plugin key in Key Vault: {e}")
        else:
            print(f"Auth type '{auth_type}' does not require Key Vault storage. Does not match ")

    # Handle additionalFields dynamic secrets
    additional_fields = updated.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        new_additional_fields = dict(additional_fields)
        for k, v in additional_fields.items():
            if k.endswith('__Secret') and v:
                addset_source = 'action-addset'
                base_field = k[:-8]  # Remove '__Secret'
                akv_key = f"{plugin_name}-{base_field}".replace('__', '-')
                full_secret_name = build_full_secret_name(akv_key, scope_value, addset_source, scope)
                if v == ui_trigger_word:
                    new_additional_fields[k] = full_secret_name
                    continue
                elif validate_secret_name_dynamic(v):
                    new_additional_fields[k] = full_secret_name
                    continue
                else:
                    try:
                        full_secret_name = store_secret_in_key_vault(akv_key, v, scope_value, source=addset_source, scope=scope)
                        new_additional_fields[k] = full_secret_name
                    except Exception as e:
                        logging.error(f"Failed to store plugin additionalField secret '{k}' in Key Vault: {e}")
                        raise Exception(f"Failed to store plugin additionalField secret '{k}' in Key Vault: {e}")
        updated['additionalFields'] = new_additional_fields
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
        logging.error(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    updated = dict(plugin_dict)
    plugin_name = updated.get('name', 'plugin')
    auth = updated.get('auth', {})
    if isinstance(auth, dict):
        if 'key' in auth and auth['key']:
            value = auth['key']
            if validate_secret_name_dynamic(value):
                try:
                    if return_type == SecretReturnType.VALUE:
                        actual_key = retrieve_secret_from_key_vault_by_full_name(value)
                        new_auth = dict(auth)
                        new_auth['key'] = actual_key
                        updated['auth'] = new_auth
                    elif return_type == SecretReturnType.NAME:
                        new_auth = dict(auth)
                        new_auth['key'] = value
                        updated['auth'] = new_auth
                    else:
                        new_auth = dict(auth)
                        new_auth['key'] = ui_trigger_word
                        updated['auth'] = new_auth
                except Exception as e:
                    logging.error(f"Failed to retrieve action {plugin_name} key from Key Vault: {e}")
                    raise Exception(f"Failed to retrieve action {plugin_name} key from Key Vault: {e}")

    additional_fields = updated.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        new_additional_fields = dict(additional_fields)
        for k, v in additional_fields.items():
            if k.endswith('__Secret') and v and validate_secret_name_dynamic(v):
                addset_source = 'action-addset'
                base_field = k[:-8]  # Remove '__Secret'
                akv_key = f"{plugin_name}-{base_field}".replace('__', '-')
                try:
                    if return_type == SecretReturnType.VALUE:
                        actual_secret = retrieve_secret_from_key_vault(f"{akv_key}", scope_value, scope, addset_source)
                        new_additional_fields[k] = actual_secret
                    elif return_type == SecretReturnType.NAME:
                        new_additional_fields[k] = v
                    else:
                        new_additional_fields[k] = ui_trigger_word
                except Exception as e:
                    logging.error(f"Failed to retrieve action additionalField secret '{k}' from Key Vault: {e}")
                    raise Exception(f"Failed to retrieve action additionalField secret '{k}' from Key Vault: {e}")
        updated['additionalFields'] = new_additional_fields
    return updated
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
        log_event(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}", level="WARNING")
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")
    settings = app_settings_cache.get_settings_cache()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    key_vault_name = settings.get("key_vault_name", None)
    if not enable_key_vault_secret_storage or not key_vault_name:
        log_event(f"Key Vault secret storage is not enabled or key vault name is missing.", level="WARNING")
        return plugin_dict
    source = "action"
    plugin_name = plugin_dict.get('name', 'plugin')
    auth = plugin_dict.get('auth', {})
    if isinstance(auth, dict):
        if 'key' in auth and auth['key']:
            secret_name = auth['key']
            if validate_secret_name_dynamic(secret_name):
                try:
                    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
                    log_event(f"Deleting action secret '{secret_name}' for action '{plugin_name}' for '{scope}' '{scope_value}'", level="INFO")
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(secret_name)
                except Exception as e:
                    logging.error(f"Error deleting action secret '{secret_name}' for action '{plugin_name}': {e}")
                    raise Exception(f"Error deleting action secret '{secret_name}' for action '{plugin_name}': {e}")

    additional_fields = plugin_dict.get('additionalFields', {})
    if isinstance(additional_fields, dict):
        for k, v in additional_fields.items():
            if k.endswith('__Secret') and v and validate_secret_name_dynamic(v):
                addset_source = 'action-addset'
                base_field = k[:-8]  # Remove '__Secret'
                akv_key = f"{plugin_name}-{base_field}".replace('__', '-')
                try:
                    keyvault_secret_name = build_full_secret_name(akv_key, scope_value, addset_source, scope)
                    key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
                    log_event(f"Deleting action additionalField secret '{k}' for action '{plugin_name}' for '{scope}' '{scope_value}'", level="INFO")
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(keyvault_secret_name)
                except Exception as e:
                    logging.error(f"Error deleting action additionalField secret '{k}' for action '{plugin_name}': {e}")
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
                    log_event(f"Deleting agent secret '{secret_name}' for agent '{agent_name}' for '{scope}' '{scope_value}'", level="INFO")
                    client = SecretClient(vault_url=key_vault_url, credential=get_keyvault_credential())
                    client.begin_delete_secret(secret_name)
                except Exception as e:
                    logging.error(f"Error deleting secret '{secret_name}' for agent '{agent_name}': {e}")
                    raise Exception(f"Error deleting secret '{secret_name}' for agent '{agent_name}': {e}")
    return agent_dict

def get_keyvault_credential():
    """
    Get the Key Vault credential using DefaultAzureCredential, optionally with a managed identity client ID.

    Returns:
        DefaultAzureCredential: The credential object for Key Vault access.
    """
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
