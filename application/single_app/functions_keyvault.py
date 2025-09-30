# functions_keyvault.py

import re
from config import *
from functions_authentication import *
from functions_settings import *

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
    'model_deployment',
    'speech_service',
    'storage_account',
    'cognitive_service',
    'action',
    'agent'
]

supported_scopes = [
    'global',
    'user',
    'group'
]

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
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")

    full_secret_name = build_full_secret_name(secret_name, scope_value, source, scope)
    return retrieve_secret_by_full_name(full_secret_name)

def retrieve_secret_from_keyvault_by_full_name(full_secret_name):
    """
    Retrieve a secret from Key Vault using a preformatted full secret name.

    Args:
        full_secret_name (str): The full secret name (already formatted).

    Returns:
        str: The value of the retrieved secret.
    Raises:
        Exception: If retrieval fails or configuration is invalid.
    """
    settings = get_settings()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    if not enable_key_vault_secret_storage:
        raise Exception("Key Vault secret storage is not enabled.")

    key_vault_name = settings.get("key_vault_name", None)
    if not key_vault_name:
        raise Exception("Key Vault name is not configured.")

    try:
        key_vault_identity = settings.get("key_vault_identity", None)
        if key_vault_identity is not None:
            credential = DefaultAzureCredential(managed_identity_client_id=key_vault_identity)
        else:
            credential = DefaultAzureCredential()
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

        retrieved_secret = secret_client.get_secret(full_secret_name)
        print(f"Secret '{full_secret_name}' retrieved successfully from Key Vault.")
        return retrieved_secret.value
    except Exception as e:
        raise Exception(f"Failed to retrieve secret '{full_secret_name}' from Key Vault: {str(e)}") from e

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
    settings = get_settings()
    enable_key_vault_secret_storage = settings.get("enable_key_vault_secret_storage", False)
    if not enable_key_vault_secret_storage:
        raise Exception("Key Vault secret storage is not enabled.")

    key_vault_name = settings.get("key_vault_name", None)
    if not key_vault_name:
        raise Exception("Key Vault name is not configured.")

    if source not in supported_sources:
        raise ValueError(f"Source '{source}' is not supported. Supported sources: {supported_sources}")
    if scope not in supported_scopes:
        raise ValueError(f"Scope '{scope}' is not supported. Supported scopes: {supported_scopes}")


    full_secret_name = build_full_secret_name(secret_name, scope_value, source, scope)

    try:
        key_vault_identity = settings.get("key_vault_identity", None)
        if key_vault_identity is not None:
            credential = DefaultAzureCredential(managed_identity_client_id=key_vault_identity)
        else:
            credential = DefaultAzureCredential()
        key_vault_url = f"https://{key_vault_name}{KEY_VAULT_DOMAIN}"
        secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

        secret_client.set_secret(full_secret_name, secret_value)
        print(f"Secret '{full_secret_name}' stored successfully in Key Vault.")
        return full_secret_name
    except Exception as e:
        raise Exception(f"Failed to store secret '{full_secret_name}' in Key Vault: {str(e)}") from e

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
    full_secret_name = f"{scope_value}--{source}--{scope}--{secret_name}"
    if len(full_secret_name) > 127:
        raise ValueError(f"The full secret name '{full_secret_name}' exceeds the maximum length of 127 characters.")
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
    source = "agent"
    updated = dict(agent_dict)
    agent_name = updated.get('name', 'agent')
    # Decide which key to store based on enable_agent_gpt_apim
    use_apim = updated.get('enable_agent_gpt_apim', False)
    if use_apim:
        key = 'azure_agent_apim_gpt_subscription_key'
    else:
        key = 'azure_openai_gpt_key'

    if key in updated and updated[key]:
        value = updated[key]
        # If already a Key Vault reference, skip (simple heuristic: if value matches secret name pattern)
        if not validate_secret_name_dynamic(value):
            # Store in Key Vault and replace value with secret name
            secret_name = agent_name
            try:
                full_secret_name = store_secret_in_key_vault(secret_name, value, scope_value, source=source, scope=scope)
                updated[key] = full_secret_name
            except Exception as e:
                raise Exception(f"Failed to store agent key '{key}' in Key Vault: {e}")
    return updated

def keyvault_plugin_save_helper(plugin_dict, scope_value, scope="global"):
    """
    For plugin dicts, store the auth.key in Key Vault if auth.type is 'key' or 'servicePrincipal',
    and replace its value with the Key Vault secret name.

    Args:
        plugin_dict (dict): The plugin dictionary to process.
        scope_value (str): The value for the scope (e.g., plugin id).
        scope (str): The scope (e.g., 'user', 'global').

    Returns:
        dict: A new plugin dict with sensitive values replaced by Key Vault references.
    Raises:
        Exception: If storing a key in Key Vault fails.
    """
    source = "plugin"
    updated = dict(plugin_dict)
    plugin_name = updated.get('name', 'plugin')
    auth = updated.get('auth', {})
    if not isinstance(auth, dict):
        return updated
    auth_type = auth.get('type', None)
    if auth_type in ('key', 'servicePrincipal') and 'key' in auth and auth['key']:
        value = auth['key']
        # If already a Key Vault reference, skip
        if not validate_secret_name_dynamic(value):
            secret_name = plugin_name
            try:
                full_secret_name = store_secret_in_key_vault(secret_name, value, scope_value, source=source, scope=scope)
                # Update the auth dict with the Key Vault reference
                new_auth = dict(auth)
                new_auth['key'] = full_secret_name
                updated['auth'] = new_auth
            except Exception as e:
                raise Exception(f"Failed to store plugin key in Key Vault: {e}")
    return updated