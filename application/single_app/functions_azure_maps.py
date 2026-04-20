# functions_azure_maps.py
"""Shared Azure Maps constants and secure tile proxy helpers."""

import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY
from functions_appinsights import log_event


AZURE_MAPS_PLUGIN_TYPE = "azure_maps_openlayers"
AZURE_MAPS_PLUGIN_DISPLAY_NAME = "Azure Maps (OpenLayers)"
AZURE_MAPS_RENDER_TYPE = "azure_maps_openlayers"
AZURE_MAPS_DEFAULT_ENDPOINT = "https://atlas.microsoft.com"
AZURE_MAPS_TILE_API_VERSION = "2024-04-01"
AZURE_MAPS_DEFAULT_TILESET_ID = "microsoft.base.road"
AZURE_MAPS_DEFAULT_LANGUAGE = "en-US"
AZURE_MAPS_DEFAULT_VIEW = "Auto"
AZURE_MAPS_TILE_PROXY_ROUTE = "/api/azure-maps/tile"
AZURE_MAPS_TILE_TOKEN_TTL_MINUTES = 240
AZURE_MAPS_TILE_ATTRIBUTION = "© Microsoft Corporation © OpenStreetMap contributors"


def _build_fernet_cipher() -> Fernet:
    normalized_secret = str(SECRET_KEY or "").encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(normalized_secret).digest())
    return Fernet(derived_key)


def create_tile_proxy_token(
    subscription_key: str,
    *,
    expires_in_minutes: int = AZURE_MAPS_TILE_TOKEN_TTL_MINUTES,
) -> str:
    normalized_key = str(subscription_key or "").strip()
    if not normalized_key:
        raise ValueError("Azure Maps subscription key is required.")

    ttl_minutes = max(1, int(expires_in_minutes or AZURE_MAPS_TILE_TOKEN_TTL_MINUTES))
    payload = {
        "subscription_key": normalized_key,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(),
    }
    encrypted_payload = _build_fernet_cipher().encrypt(json.dumps(payload).encode("utf-8"))
    return encrypted_payload.decode("utf-8")


def decode_tile_proxy_token(tile_proxy_token: str) -> Optional[Dict[str, Any]]:
    normalized_token = str(tile_proxy_token or "").strip()
    if not normalized_token:
        return None

    try:
        decrypted_payload = _build_fernet_cipher().decrypt(normalized_token.encode("utf-8"))
        payload = json.loads(decrypted_payload.decode("utf-8"))
    except InvalidToken:
        log_event("[AzureMaps] Rejected an invalid Azure Maps tile proxy token.", level=logging.WARNING)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log_event(f"[AzureMaps] Failed to decode Azure Maps tile proxy token payload: {exc}", level=logging.WARNING)
        return None

    subscription_key = str(payload.get("subscription_key") or "").strip()
    expires_at_raw = str(payload.get("expires_at") or "").strip()
    if not subscription_key or not expires_at_raw:
        return None

    try:
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
    except ValueError:
        log_event("[AzureMaps] Azure Maps tile proxy token had an invalid expiration timestamp.", level=logging.WARNING)
        return None

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= datetime.now(timezone.utc):
        log_event("[AzureMaps] Rejected an expired Azure Maps tile proxy token.", level=logging.INFO)
        return None

    return {
        "subscription_key": subscription_key,
        "expires_at": expires_at.isoformat(),
    }


def build_tile_proxy_url_template(
    tile_proxy_token: str,
    *,
    tileset_id: str = AZURE_MAPS_DEFAULT_TILESET_ID,
    language: str = AZURE_MAPS_DEFAULT_LANGUAGE,
    view: str = AZURE_MAPS_DEFAULT_VIEW,
    tile_size: int = 256,
) -> str:
    normalized_tile_size = 512 if int(tile_size or 256) == 512 else 256
    encoded_token = quote_plus(str(tile_proxy_token or "").strip())
    encoded_tileset = quote_plus(str(tileset_id or AZURE_MAPS_DEFAULT_TILESET_ID).strip())
    encoded_language = quote_plus(str(language or AZURE_MAPS_DEFAULT_LANGUAGE).strip())
    encoded_view = quote_plus(str(view or AZURE_MAPS_DEFAULT_VIEW).strip())

    return (
        f"{AZURE_MAPS_TILE_PROXY_ROUTE}"
        f"?token={encoded_token}"
        f"&api-version={AZURE_MAPS_TILE_API_VERSION}"
        f"&tilesetId={encoded_tileset}"
        f"&zoom={{z}}"
        f"&x={{x}}"
        f"&y={{y}}"
        f"&tileSize={normalized_tile_size}"
        f"&language={encoded_language}"
        f"&view={encoded_view}"
    )