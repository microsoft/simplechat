# app_settings_cache.py
"""
WARNING: NEVER 'from app_settings_cache import' settings or any other module that imports settings.
ALWAYS import app_settings_cache and use app_settings_cache.get_settings_cache() to get settings.
This supports the dynamic selection of redis or in-memory caching of settings.
"""
import json
from redis import Redis
from azure.identity import DefaultAzureCredential

_settings = None
APP_SETTINGS_CACHE = {}
update_settings_cache = None
get_settings_cache = None
app_cache_is_using_redis = False

def configure_app_cache(settings, redis_cache_endpoint=None):
    global _settings, update_settings_cache, get_settings_cache, APP_SETTINGS_CACHE, app_cache_is_using_redis
    _settings = settings
    use_redis = _settings.get('enable_redis_cache', False)

    if use_redis:
        app_cache_is_using_redis = True
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()
        if redis_auth_type == 'managed_identity':
            print("[ASC] Redis enabled using Managed Identity")
            credential = DefaultAzureCredential()
            redis_hostname = redis_url.split('.')[0]
            cache_endpoint = redis_cache_endpoint
            token = credential.get_token(cache_endpoint)
            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=token.token,
                ssl=True
            )
        else:
            redis_key = settings.get('redis_key', '').strip()
            print("[ASC] Redis enabled using Access Key")
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