# settings.py
"""Map server configuration, read once from environment variables and checked at startup."""

import os
from dataclasses import dataclass
from typing import FrozenSet, Mapping, Optional, Tuple

DEFAULT_REQUIRED_ROLE = "MapServer.ActOnBehalf"
DEFAULT_AUTHORITY_HOST = "login.microsoftonline.com"
DEFAULT_AZURE_MAPS_ENDPOINT = "https://atlas.microsoft.com"
DEFAULT_BASEMAP = "microsoft.base.road"
STORE_COSMOS = "cosmos"
STORE_MEMORY = "memory"
LOCAL_DEV_KEY_MIN_LENGTH = 32
# A transactional batch holds 100 operations; an update costs two (revision + replace) plus the map and change.
MAX_FEATURES_PER_CALL_LIMIT = 49


class SettingsError(ValueError):
    """The map server is misconfigured."""


def _split_list(raw: Optional[str]) -> Tuple[str, ...]:
    return tuple(item.strip() for item in (raw or "").split(",") if item.strip())


def _read_number(env: Mapping[str, str], name: str, default: float, minimum: float, maximum: float) -> float:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number.") from exc
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return value


@dataclass(frozen=True)
class Settings:
    tenant_id: str = ""
    audiences: Tuple[str, ...] = ()
    issuers: Tuple[str, ...] = ()
    jwks_url: str = ""
    required_role: str = DEFAULT_REQUIRED_ROLE
    allowed_caller_ids: FrozenSet[str] = frozenset()
    local_dev_key: str = ""
    store: str = STORE_COSMOS
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "mapserver"
    maps_container: str = "maps"
    links_container: str = "map_links"
    managed_identity_client_id: str = ""
    azure_maps_endpoint: str = DEFAULT_AZURE_MAPS_ENDPOINT
    azure_maps_key: str = ""
    azure_maps_client_id: str = ""
    default_basemap: str = DEFAULT_BASEMAP
    tile_cache_entries: int = 1024
    events_poll_seconds: float = 2.0
    events_keepalive_seconds: float = 15.0
    events_max_seconds: float = 600.0
    max_features_per_call: int = 40
    max_active_features: int = 10000

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        tenant_id = str(env.get("MAP_SERVER_TENANT_ID") or "").strip()
        authority_host = str(env.get("MAP_SERVER_AUTHORITY_HOST") or DEFAULT_AUTHORITY_HOST).strip()
        issuers = _split_list(env.get("MAP_SERVER_ISSUERS"))
        if not issuers and tenant_id:
            # Managed identity tokens carry the v1 issuer unless the API app requests v2 tokens.
            issuers = (f"https://sts.windows.net/{tenant_id}/", f"https://{authority_host}/{tenant_id}/v2.0")
        jwks_url = str(env.get("MAP_SERVER_JWKS_URL") or "").strip()
        if not jwks_url and tenant_id:
            jwks_url = f"https://{authority_host}/{tenant_id}/discovery/v2.0/keys"

        settings = cls(
            tenant_id=tenant_id,
            audiences=_split_list(env.get("MAP_SERVER_AUDIENCES")),
            issuers=issuers,
            jwks_url=jwks_url,
            required_role=str(env.get("MAP_SERVER_REQUIRED_ROLE") or DEFAULT_REQUIRED_ROLE).strip(),
            allowed_caller_ids=frozenset(_split_list(env.get("MAP_SERVER_ALLOWED_CALLER_IDS"))),
            local_dev_key=str(env.get("MAP_SERVER_LOCAL_DEV_KEY") or "").strip(),
            store=str(env.get("MAP_SERVER_STORE") or STORE_COSMOS).strip().lower(),
            cosmos_endpoint=str(env.get("MAP_SERVER_COSMOS_ENDPOINT") or "").strip(),
            cosmos_key=str(env.get("MAP_SERVER_COSMOS_KEY") or "").strip(),
            cosmos_database=str(env.get("MAP_SERVER_COSMOS_DATABASE") or "mapserver").strip(),
            maps_container=str(env.get("MAP_SERVER_MAPS_CONTAINER") or "maps").strip(),
            links_container=str(env.get("MAP_SERVER_LINKS_CONTAINER") or "map_links").strip(),
            managed_identity_client_id=str(env.get("AZURE_CLIENT_ID") or "").strip(),
            azure_maps_endpoint=str(env.get("AZURE_MAPS_ENDPOINT") or DEFAULT_AZURE_MAPS_ENDPOINT).strip().rstrip("/"),
            azure_maps_key=str(env.get("AZURE_MAPS_KEY") or "").strip(),
            azure_maps_client_id=str(env.get("AZURE_MAPS_CLIENT_ID") or "").strip(),
            default_basemap=str(env.get("MAP_SERVER_DEFAULT_BASEMAP") or DEFAULT_BASEMAP).strip(),
            tile_cache_entries=int(_read_number(env, "MAP_SERVER_TILE_CACHE_ENTRIES", 1024, 0, 100000)),
            events_poll_seconds=_read_number(env, "MAP_SERVER_EVENTS_POLL_SECONDS", 2.0, 0.05, 60),
            events_keepalive_seconds=_read_number(env, "MAP_SERVER_EVENTS_KEEPALIVE_SECONDS", 15.0, 1, 300),
            events_max_seconds=_read_number(env, "MAP_SERVER_EVENTS_MAX_SECONDS", 600.0, 1, 3600),
            max_features_per_call=int(_read_number(
                env, "MAP_SERVER_MAX_FEATURES_PER_CALL", 40, 1, MAX_FEATURES_PER_CALL_LIMIT,
            )),
            max_active_features=int(_read_number(env, "MAP_SERVER_MAX_ACTIVE_FEATURES", 10000, 1, 100000)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.store not in (STORE_COSMOS, STORE_MEMORY):
            raise SettingsError("MAP_SERVER_STORE must be 'cosmos' or 'memory'.")
        if self.local_dev_key:
            if self.store != STORE_MEMORY:
                raise SettingsError("MAP_SERVER_LOCAL_DEV_KEY only works with MAP_SERVER_STORE=memory.")
            if len(self.local_dev_key) < LOCAL_DEV_KEY_MIN_LENGTH:
                raise SettingsError(f"MAP_SERVER_LOCAL_DEV_KEY must be at least {LOCAL_DEV_KEY_MIN_LENGTH} characters.")
        elif not (self.tenant_id and self.audiences and self.issuers and self.jwks_url):
            raise SettingsError("MAP_SERVER_TENANT_ID and MAP_SERVER_AUDIENCES are required.")
        if not self.local_dev_key and not (self.required_role or self.allowed_caller_ids):
            raise SettingsError("Set MAP_SERVER_REQUIRED_ROLE or MAP_SERVER_ALLOWED_CALLER_IDS.")
        if self.store == STORE_COSMOS and not self.cosmos_endpoint:
            raise SettingsError("MAP_SERVER_COSMOS_ENDPOINT is required with the Cosmos store.")
        if not 1 <= self.max_features_per_call <= MAX_FEATURES_PER_CALL_LIMIT:
            raise SettingsError(f"max_features_per_call must be between 1 and {MAX_FEATURES_PER_CALL_LIMIT}.")
