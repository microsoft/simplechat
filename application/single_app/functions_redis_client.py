# functions_redis_client.py
"""Redis client construction shared by session, cache, and admin diagnostics code paths.

SimpleChat supports two Azure Redis offerings side by side:

* Azure Cache for Redis (``*.redis.cache.windows.net`` and sovereign equivalents), which
  listens for TLS traffic on port 6380.
* Azure Managed Redis (``*.<region>.redis.azure.net``), which listens on port 10000.

The service in use is detected from the configured host name so existing deployments keep
working untouched, and administrators can override the detection when a custom DNS name or
private endpoint hides the Azure suffix.

NOTE: This module intentionally avoids importing ``config`` and ``functions_settings`` at
module scope. ``app_settings_cache`` imports this module during early application start up,
before those modules are ready, and ``functions_keyvault`` imports ``app_settings_cache``.
Both are imported locally inside the functions that need them.
"""

import base64
import json
import logging
import os
import threading
import time

from redis import Redis
from redis.credentials import CredentialProvider
from azure.identity import DefaultAzureCredential

SERVICE_TYPE_AUTO = 'auto'
SERVICE_TYPE_AZURE_CACHE_FOR_REDIS = 'azure_cache_for_redis'
SERVICE_TYPE_AZURE_MANAGED_REDIS = 'azure_managed_redis'

SUPPORTED_SERVICE_TYPES = (
    SERVICE_TYPE_AUTO,
    SERVICE_TYPE_AZURE_CACHE_FOR_REDIS,
    SERVICE_TYPE_AZURE_MANAGED_REDIS,
)

AZURE_CACHE_FOR_REDIS_PORT = 6380
AZURE_MANAGED_REDIS_PORT = 10000

# Azure Managed Redis and the retiring Azure Cache for Redis Enterprise tiers both run the
# Redis Enterprise stack and both answer on port 10000.
AZURE_MANAGED_REDIS_HOST_SUFFIXES = (
    '.redis.azure.net',
    '.redisenterprise.cache.azure.net',
)

AZURE_CACHE_FOR_REDIS_HOST_SUFFIXES = (
    '.redis.cache.windows.net',
    '.redis.cache.usgovcloudapi.net',
    '.redis.cache.chinacloudapi.cn',
)

REDIS_ENTRA_TOKEN_SCOPE = 'https://redis.azure.com/.default'
REDIS_TOKEN_REFRESH_BUFFER_SECONDS = 300

AUTH_TYPE_MANAGED_IDENTITY = 'managed_identity'
AUTH_TYPE_KEY_VAULT = 'key_vault'
AUTH_TYPE_KEY = 'key'

# Long-lived clients that each need their own streaming credential provider. redis-entraid's
# provider keeps a single re-authentication callback slot, so two clients sharing one provider
# would leave the first client's pooled connections without proactive re-AUTH.
CREDENTIAL_PURPOSE_APP_CACHE = 'app_cache'
CREDENTIAL_PURPOSE_SESSION = 'session'
DEFAULT_CREDENTIAL_PURPOSE = CREDENTIAL_PURPOSE_APP_CACHE

_logger = logging.getLogger(__name__)

_streaming_credential_providers = {}
_streaming_credential_provider_lock = threading.Lock()


def normalize_redis_host(redis_url):
    """Return a bare Redis host name, tolerating scheme and port decorations."""
    host = str(redis_url or '').strip()
    if not host:
        return ''
    if '://' in host:
        host = host.split('://', 1)[1]
    host = host.split('/', 1)[0]
    # Strip a trailing ":<port>" but leave bracketed IPv6 literals alone.
    if ']' not in host and host.count(':') == 1:
        host = host.split(':', 1)[0]
    return host.strip().rstrip('.').lower()


def detect_redis_service_type(redis_url):
    """Infer the Azure Redis offering from a host name suffix.

    Returns ``SERVICE_TYPE_AUTO`` when the host name does not match a documented Azure
    suffix, which lets callers fall back to the historical Azure Cache for Redis behavior.
    """
    host = normalize_redis_host(redis_url)
    if not host:
        return SERVICE_TYPE_AUTO
    if host.endswith(AZURE_MANAGED_REDIS_HOST_SUFFIXES):
        return SERVICE_TYPE_AZURE_MANAGED_REDIS
    if host.endswith(AZURE_CACHE_FOR_REDIS_HOST_SUFFIXES):
        return SERVICE_TYPE_AZURE_CACHE_FOR_REDIS
    return SERVICE_TYPE_AUTO


def resolve_redis_service_type(settings=None, redis_url=None):
    """Resolve the effective Redis service type from settings, then host name detection."""
    source = settings or {}
    configured = str(source.get('redis_service_type') or '').strip().lower()
    if configured in (SERVICE_TYPE_AZURE_CACHE_FOR_REDIS, SERVICE_TYPE_AZURE_MANAGED_REDIS):
        return configured

    host = redis_url if redis_url is not None else source.get('redis_url')
    detected = detect_redis_service_type(host)
    if detected != SERVICE_TYPE_AUTO:
        return detected

    # Unrecognized host names keep the pre-Managed-Redis behavior so existing deployments
    # that front Azure Cache for Redis with a custom DNS name are unaffected.
    return SERVICE_TYPE_AZURE_CACHE_FOR_REDIS


def resolve_redis_port(settings=None, redis_url=None, service_type=None):
    """Resolve the TLS port for the configured Redis service, honoring an admin override."""
    source = settings or {}
    configured_port = str(source.get('redis_port') or '').strip()
    if configured_port:
        try:
            port = int(configured_port)
        except (TypeError, ValueError):
            _logger.warning('Ignoring non-numeric redis_port override: %r', configured_port)
        else:
            if 1 <= port <= 65535:
                return port
            _logger.warning('Ignoring out-of-range redis_port override: %r', configured_port)

    effective_service_type = service_type or resolve_redis_service_type(source, redis_url=redis_url)
    if effective_service_type == SERVICE_TYPE_AZURE_MANAGED_REDIS:
        return AZURE_MANAGED_REDIS_PORT
    return AZURE_CACHE_FOR_REDIS_PORT


def get_redis_entra_token_scope(settings=None):
    """Return the Microsoft Entra scope used to authenticate against Redis."""
    configured_scope = (settings or {}).get('redis_entra_token_scope') or os.getenv('REDIS_ENTRA_TOKEN_SCOPE')
    return (configured_scope or REDIS_ENTRA_TOKEN_SCOPE).strip()


def get_entra_authority():
    """Return the Microsoft Entra authority host for the active Azure environment."""
    try:
        from config import authority
    except Exception:
        return None
    normalized_authority = str(authority or '').strip()
    return normalized_authority or None


def _build_streaming_credential_provider(scope, authority_host):
    """Create a redis-entraid streaming provider that re-AUTHs pooled connections."""
    from redis_entraid.cred_provider import create_from_default_azure_credential

    return create_from_default_azure_credential(
        (scope,),
        authority=authority_host,
    )


def get_redis_credential_provider(settings=None, streaming=True, purpose=DEFAULT_CREDENTIAL_PURPOSE):
    """Return a redis-py credential provider for Microsoft Entra authentication.

    ``streaming=True`` returns a ``redis-entraid`` provider that renews the Entra token in the
    background and re-issues ``AUTH`` on live pooled connections. One provider is cached per
    ``purpose`` because redis-entraid holds a single re-authentication callback slot: handing
    the same provider to two clients would leave the first client's pool without proactive
    re-AUTH, and creating one per call would leak a thread on every reconfiguration.

    ``streaming=False`` returns the connect-time-only provider, which starts no background
    refresh thread. Ad-hoc diagnostic connections use it so an admin clicking "Test" cannot
    accumulate threads, event loops, and recurring token requests for the life of the worker.

    Falls back to the in-repo credential provider when ``redis-entraid`` is unavailable, so
    an application updated without reinstalling requirements still starts.
    """
    scope = get_redis_entra_token_scope(settings)
    authority_host = get_entra_authority()

    if not streaming:
        return _build_fallback_credential_provider(scope)

    provider_key = (str(purpose or DEFAULT_CREDENTIAL_PURPOSE), scope, authority_host)
    with _streaming_credential_provider_lock:
        cached_provider = _streaming_credential_providers.get(provider_key)
        if cached_provider is not None:
            return cached_provider

        try:
            provider = _build_streaming_credential_provider(scope, authority_host)
        except Exception as provider_error:
            _logger.warning(
                'redis-entraid credential provider unavailable, falling back: %s',
                provider_error,
            )
            provider = _build_fallback_credential_provider(scope)

        # A scope or authority change means the previous provider for this purpose is stale.
        for stale_key in [key for key in _streaming_credential_providers if key[0] == provider_key[0]]:
            _streaming_credential_providers.pop(stale_key, None)
        _streaming_credential_providers[provider_key] = provider
        return provider


def _decode_token_claims(access_token):
    parts = access_token.split('.')
    if len(parts) < 2:
        raise ValueError('Redis Microsoft Entra token did not contain JWT claims.')

    payload = parts[1]
    payload += '=' * (-len(payload) % 4)
    decoded_payload = base64.urlsafe_b64decode(payload.encode('utf-8')).decode('utf-8')
    return json.loads(decoded_payload)


def _get_redis_username_from_claims(access_token):
    claims = _decode_token_claims(access_token)
    username = claims.get('oid') or claims.get('appid')
    if not username:
        raise ValueError('Redis Microsoft Entra token did not include an object ID claim.')
    return username


class RedisManagedIdentityCredentialProvider(CredentialProvider):
    """Provides Redis ACL username and Microsoft Entra token credentials.

    Used only when ``redis-entraid`` is unavailable. Unlike the redis-entraid provider this
    supplies credentials at connect time only, so a pooled connection is re-authenticated
    when the server drops it rather than proactively before token expiry.
    """

    def __init__(self, credential=None, scope=None):
        self.credential = credential or DefaultAzureCredential()
        self.scope = scope or REDIS_ENTRA_TOKEN_SCOPE
        self._cached_credentials = None
        self._expires_on = 0

    def get_credentials(self):
        now = time.time()
        if self._cached_credentials and now < self._expires_on - REDIS_TOKEN_REFRESH_BUFFER_SECONDS:
            return self._cached_credentials

        token = self.credential.get_token(self.scope)
        username = _get_redis_username_from_claims(token.token)
        self._cached_credentials = (username, token.token)
        self._expires_on = token.expires_on
        return self._cached_credentials


def _build_fallback_credential_provider(scope):
    """Return the in-repo credential provider used when redis-entraid is missing."""
    return RedisManagedIdentityCredentialProvider(scope=scope)


def reset_redis_credential_provider_cache():
    """Drop cached streaming credential providers so the next call rebuilds them."""
    with _streaming_credential_provider_lock:
        _streaming_credential_providers.clear()


def resolve_redis_password(settings=None, auth_type=None, redis_key=None):
    """Return the password for key or Key Vault authentication."""
    source = settings or {}
    normalized_auth_type = str(
        auth_type if auth_type is not None else source.get('redis_auth_type') or AUTH_TYPE_KEY
    ).strip().lower()
    secret_value = str(redis_key if redis_key is not None else source.get('redis_key') or '').strip()

    if normalized_auth_type == AUTH_TYPE_KEY_VAULT:
        if not secret_value:
            raise ValueError('Key Vault secret name is required for Key Vault authentication.')
        # Local import to avoid a circular dependency at module load time.
        from functions_keyvault import retrieve_secret_direct

        password = retrieve_secret_direct(secret_value, settings=source)
        if not password:
            raise ValueError('Key Vault returned an empty Redis access key.')
        return password.strip()

    if not secret_value:
        raise ValueError('Redis access key is required for key authentication.')
    return secret_value


def create_redis_client(
    settings=None,
    redis_url=None,
    auth_type=None,
    redis_key=None,
    streaming_credentials=True,
    credential_purpose=DEFAULT_CREDENTIAL_PURPOSE,
    **redis_kwargs
):
    """Build a ``redis.Redis`` client for either Azure Redis offering.

    Host name, authentication type, and access key default to the values in ``settings`` but
    can be overridden so the admin connection test can validate unsaved form input.

    ``credential_purpose`` identifies the long-lived client being built so each one receives
    its own streaming credential provider; see ``get_redis_credential_provider``.
    """
    source = settings or {}
    host = normalize_redis_host(redis_url if redis_url is not None else source.get('redis_url'))
    if not host:
        raise ValueError('Redis host name is required.')

    service_type = resolve_redis_service_type(source, redis_url=host)
    port = resolve_redis_port(source, redis_url=host, service_type=service_type)
    normalized_auth_type = str(
        auth_type if auth_type is not None else source.get('redis_auth_type') or AUTH_TYPE_KEY
    ).strip().lower()

    client_kwargs = {
        'host': host,
        'port': port,
        # Azure Managed Redis exposes a single database; redis-py only emits SELECT for a
        # non-zero index, so db=0 is correct for both services.
        'db': 0,
        'ssl': True,
    }
    client_kwargs.update(redis_kwargs)

    if normalized_auth_type == AUTH_TYPE_MANAGED_IDENTITY:
        client_kwargs['credential_provider'] = get_redis_credential_provider(
            source,
            streaming=streaming_credentials,
            purpose=credential_purpose,
        )
    else:
        client_kwargs['password'] = resolve_redis_password(
            source,
            auth_type=normalized_auth_type,
            redis_key=redis_key,
        )

    return Redis(**client_kwargs)


def describe_redis_connection(settings=None, redis_url=None):
    """Return non-sensitive connection facts for diagnostics and admin monitoring."""
    source = settings or {}
    host = normalize_redis_host(redis_url if redis_url is not None else source.get('redis_url'))
    service_type = resolve_redis_service_type(source, redis_url=host)
    return {
        'host': host,
        'service_type': service_type,
        'service_type_detected': detect_redis_service_type(host),
        'service_type_source': (
            'setting'
            if str(source.get('redis_service_type') or '').strip().lower() in (
                SERVICE_TYPE_AZURE_CACHE_FOR_REDIS,
                SERVICE_TYPE_AZURE_MANAGED_REDIS,
            )
            else 'detected'
        ),
        'port': resolve_redis_port(source, redis_url=host, service_type=service_type),
    }
