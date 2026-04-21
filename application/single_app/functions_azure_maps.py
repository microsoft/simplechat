# functions_azure_maps.py
"""Shared Azure Maps constants and secure tile proxy helpers."""

import base64
import hashlib
import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

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
AZURE_MAPS_INLINE_BLOCK_PREFIX = "{{map:"


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


def decode_tile_proxy_token(tile_proxy_token: str, *, allow_expired: bool = False) -> Optional[Dict[str, Any]]:
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

    is_expired = expires_at <= datetime.now(timezone.utc)
    if is_expired and not allow_expired:
        log_event("[AzureMaps] Rejected an expired Azure Maps tile proxy token.", level=logging.INFO)
        return None

    return {
        "subscription_key": subscription_key,
        "expires_at": expires_at.isoformat(),
        "is_expired": is_expired,
    }


def refresh_tile_proxy_token(
    tile_proxy_token: str,
    *,
    expires_in_minutes: int = AZURE_MAPS_TILE_TOKEN_TTL_MINUTES,
) -> Optional[str]:
    token_payload = decode_tile_proxy_token(tile_proxy_token, allow_expired=True)
    if not token_payload:
        return None

    subscription_key = str(token_payload.get("subscription_key") or "").strip()
    if not subscription_key:
        return None

    return create_tile_proxy_token(subscription_key, expires_in_minutes=expires_in_minutes)


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


def refresh_tile_proxy_url_template(tile_url_template: str) -> Optional[str]:
    normalized_tile_url_template = str(tile_url_template or "").strip()
    if not normalized_tile_url_template:
        return None

    parsed_url = urlparse(normalized_tile_url_template)
    query_params = parse_qs(parsed_url.query)
    current_token = str((query_params.get("token") or [""])[0] or "").strip()
    if not current_token:
        return None

    refreshed_token = refresh_tile_proxy_token(current_token)
    if not refreshed_token:
        return None

    raw_tile_size = str((query_params.get("tileSize") or ["256"])[0] or "256").strip()
    try:
        tile_size = int(raw_tile_size)
    except ValueError:
        tile_size = 256

    return build_tile_proxy_url_template(
        refreshed_token,
        tileset_id=str((query_params.get("tilesetId") or [AZURE_MAPS_DEFAULT_TILESET_ID])[0] or AZURE_MAPS_DEFAULT_TILESET_ID).strip(),
        language=str((query_params.get("language") or [AZURE_MAPS_DEFAULT_LANGUAGE])[0] or AZURE_MAPS_DEFAULT_LANGUAGE).strip(),
        view=str((query_params.get("view") or [AZURE_MAPS_DEFAULT_VIEW])[0] or AZURE_MAPS_DEFAULT_VIEW).strip(),
        tile_size=tile_size,
    )


def refresh_azure_maps_map_payload(map_payload: Any) -> Any:
    if not isinstance(map_payload, dict):
        return map_payload

    refreshed_tile_url_template = refresh_tile_proxy_url_template(map_payload.get("tile_url_template"))
    if not refreshed_tile_url_template:
        return map_payload

    refreshed_payload = deepcopy(map_payload)
    refreshed_payload["tile_url_template"] = refreshed_tile_url_template
    return refreshed_payload


def refresh_azure_maps_function_result(function_result: Any) -> Any:
    if function_result is None:
        return function_result

    parsed_result = function_result
    was_serialized = False
    if isinstance(function_result, str):
        try:
            parsed_result = json.loads(function_result)
            was_serialized = True
        except json.JSONDecodeError:
            return function_result

    if not isinstance(parsed_result, dict):
        return function_result

    if parsed_result.get("render_type") != AZURE_MAPS_RENDER_TYPE:
        return function_result

    map_payload = parsed_result.get("map_payload")
    refreshed_map_payload = refresh_azure_maps_map_payload(map_payload)
    if refreshed_map_payload == map_payload:
        return function_result

    refreshed_result = deepcopy(parsed_result)
    refreshed_result["map_payload"] = refreshed_map_payload
    if was_serialized:
        return json.dumps(refreshed_result, ensure_ascii=False)

    return refreshed_result


def refresh_azure_maps_citation_payload(citation: Any) -> Any:
    if not isinstance(citation, dict):
        return citation

    refreshed_function_result = refresh_azure_maps_function_result(citation.get("function_result"))
    if refreshed_function_result == citation.get("function_result"):
        return citation

    refreshed_citation = deepcopy(citation)
    refreshed_citation["function_result"] = refreshed_function_result
    return refreshed_citation


def refresh_azure_maps_citation_payloads(citations: Any) -> Any:
    if not isinstance(citations, list):
        return citations

    return [refresh_azure_maps_citation_payload(citation) for citation in citations]


def _find_inline_map_block_end(message_content: str, start_index: int) -> Optional[int]:
    payload_index = start_index + len(AZURE_MAPS_INLINE_BLOCK_PREFIX)
    if payload_index >= len(message_content) or message_content[payload_index] != "{":
        return None

    brace_depth = 0
    in_string = False
    is_escaped = False

    for current_index in range(payload_index, len(message_content)):
        current_character = message_content[current_index]

        if in_string:
            if is_escaped:
                is_escaped = False
            elif current_character == "\\":
                is_escaped = True
            elif current_character == '"':
                in_string = False
            continue

        if current_character == '"':
            in_string = True
            continue

        if current_character == "{":
            brace_depth += 1
            continue

        if current_character != "}":
            continue

        brace_depth -= 1
        if brace_depth == 0:
            closing_index = current_index + 1
            if closing_index < len(message_content) and message_content[closing_index] == "}":
                return closing_index + 1
            return None

    return None


def refresh_azure_maps_message_content(message_content: Any) -> Any:
    if not isinstance(message_content, str) or AZURE_MAPS_INLINE_BLOCK_PREFIX not in message_content:
        return message_content

    refreshed_content_parts = []
    current_position = 0
    content_changed = False

    while current_position < len(message_content):
        block_start = message_content.find(AZURE_MAPS_INLINE_BLOCK_PREFIX, current_position)
        if block_start == -1:
            refreshed_content_parts.append(message_content[current_position:])
            break

        refreshed_content_parts.append(message_content[current_position:block_start])
        block_end = _find_inline_map_block_end(message_content, block_start)
        if block_end is None:
            refreshed_content_parts.append(message_content[block_start:])
            break

        payload_start = block_start + len(AZURE_MAPS_INLINE_BLOCK_PREFIX)
        payload_text = message_content[payload_start:block_end - 1]

        try:
            parsed_payload = json.loads(payload_text)
        except json.JSONDecodeError:
            refreshed_content_parts.append(message_content[block_start:block_end])
            current_position = block_end
            continue

        refreshed_payload = refresh_azure_maps_map_payload(parsed_payload)
        if refreshed_payload != parsed_payload:
            content_changed = True

        refreshed_content_parts.append(
            f"{AZURE_MAPS_INLINE_BLOCK_PREFIX}{json.dumps(refreshed_payload, ensure_ascii=False)}}}"
        )
        current_position = block_end

    if not content_changed:
        return message_content

    return "".join(refreshed_content_parts)