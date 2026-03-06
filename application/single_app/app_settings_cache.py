# app_settings_cache.py
"""
WARNING: NEVER 'from app_settings_cache import' settings or any other module that imports settings.
ALWAYS import app_settings_cache and use app_settings_cache.get_settings_cache() to get settings.
This supports the dynamic selection of redis or in-memory caching of settings.
"""
import json
import logging
from redis import Redis
from azure.identity import DefaultAzureCredential

# NOTE: functions_keyvault is imported locally inside configure_app_cache to avoid a circular
# import (functions_keyvault -> app_settings_cache -> functions_keyvault).
# functions_appinsights is also imported locally for the same reason.

_settings = None
APP_SETTINGS_CACHE = {}
update_settings_cache = None
get_settings_cache = None
app_cache_is_using_redis = False

def configure_app_cache(settings, redis_cache_endpoint=None):
    global _settings, update_settings_cache, get_settings_cache, APP_SETTINGS_CACHE, app_cache_is_using_redis
    # Local import to avoid circular dependency: functions_keyvault imports app_settings_cache.
    from functions_appinsights import log_event
    _settings = settings
    use_redis = _settings.get('enable_redis_cache', False)

    if use_redis:
        app_cache_is_using_redis = True
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()
        if redis_auth_type == 'managed_identity':
            log_event("[ASC] Redis enabled using Managed Identity", level=logging.INFO)
            credential = DefaultAzureCredential()
            cache_endpoint = redis_cache_endpoint
            token = credential.get_token(cache_endpoint)
            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=token.token,
                ssl=True
            )
        elif redis_auth_type == 'key_vault':
            log_event("[ASC] Redis enabled using Key Vault Secret", level=logging.INFO)
            # Local import to avoid circular dependency: functions_keyvault imports app_settings_cache.
            from functions_keyvault import retrieve_secret_direct
            redis_key_secret_name = settings.get('redis_key', '').strip()
            try:
                # Pass settings directly: get_settings_cache() is still None at this point
                # because configure_app_cache has not finished initialising the cache yet.
                redis_password = retrieve_secret_direct(redis_key_secret_name, settings=settings)
                if redis_password:
                    redis_password = redis_password.strip()
                log_event("[ASC] Redis key retrieved from Key Vault successfully", level=logging.INFO)
            except Exception as kv_err:
                log_event(f"[ASC] ERROR: Failed to retrieve Redis key from Key Vault: {kv_err}", level=logging.ERROR, exceptionTraceback=True)
                raise

            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=redis_password,
                ssl=True
            )
        else:
            redis_key = settings.get('redis_key', '').strip()
            log_event("[ASC] Redis enabled using Access Key", level=logging.INFO)
            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=redis_key,
                ssl=True
            )

        def update_settings_cache_redis(new_settings):
            redis_client.set('APP_SETTINGS_CACHE', json.dumps(new_settings))

        def get_settings_cache_redis():
            cached = redis_client.get('APP_SETTINGS_CACHE')
            return json.loads(cached) if cached else {}

        update_settings_cache = update_settings_cache_redis
        get_settings_cache = get_settings_cache_redis

    else:
        def update_settings_cache_mem(new_settings):
            global APP_SETTINGS_CACHE
            APP_SETTINGS_CACHE = new_settings

        def get_settings_cache_mem():
            return APP_SETTINGS_CACHE

        update_settings_cache = update_settings_cache_mem
        get_settings_cache = get_settings_cache_mem