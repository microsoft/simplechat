# tiles.py
"""Azure Maps raster tiles for the map viewer, fetched with the server's own credentials and cached in memory."""

import collections
import logging
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from azure.core.exceptions import AzureError

from .errors import MapServerError, invalid
from .settings import Settings

LOGGER = logging.getLogger("mapserver.tiles")

TILE_API_VERSION = "2024-04-01"
TILE_LANGUAGE = "en-US"
TILE_VIEW = "Auto"
TILE_SIZE = 256
MAX_ZOOM = 22
TILE_TIMEOUT_SECONDS = 15
TOKEN_REFRESH_MARGIN_SECONDS = 300
MAPS_TOKEN_SCOPE = "https://atlas.microsoft.com/.default"
TILESET_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class TileService:
    def __init__(self, settings: Settings, *, http_client: Optional[httpx.AsyncClient] = None, credential: Optional[Any] = None):
        self._settings = settings
        self._http = http_client
        self._owns_http = http_client is None
        self._credential = credential
        self._cache: "collections.OrderedDict[str, Tuple[bytes, str]]" = collections.OrderedDict()
        self._cache_lock = threading.Lock()
        self._token = ""
        self._token_expires_on = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._settings.azure_maps_key or (self._settings.azure_maps_client_id and self._credential))

    async def get_tile(self, tileset: str, z: int, x: int, y: int) -> Tuple[bytes, str]:
        if not TILESET_PATTERN.fullmatch(tileset or ""):
            raise invalid("The tileset isn't valid.", code="invalid_tile")
        if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
            raise invalid("The tile coordinates are out of range.", code="invalid_tile")
        if not self.configured:
            raise MapServerError(404, "tiles_unavailable", "Map tiles aren't configured, so the map shows a black background.")

        cache_key = f"{tileset}/{z}/{x}/{y}"
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached

        params = {
            "api-version": TILE_API_VERSION,
            "tilesetId": tileset,
            "zoom": z,
            "x": x,
            "y": y,
            "tileSize": TILE_SIZE,
            "language": TILE_LANGUAGE,
            "view": TILE_VIEW,
        }
        headers = await self._auth_headers()
        try:
            response = await self._client().get(
                f"{self._settings.azure_maps_endpoint}/map/tile", params=params, headers=headers, timeout=TILE_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            LOGGER.warning(f"[MAP_SERVER_TILES] The tile request failed ({type(exc).__name__}).")
            raise MapServerError(502, "tile_upstream_error", "The map tile service didn't respond.") from exc

        media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if response.status_code != 200 or not media_type.startswith("image/"):
            LOGGER.warning(f"[MAP_SERVER_TILES] The tile service answered {response.status_code} ({media_type or 'no type'}).")
            raise MapServerError(502, "tile_upstream_error", "The map tile service returned an error.")

        tile = (response.content, media_type)
        if self._settings.tile_cache_entries:
            with self._cache_lock:
                self._cache[cache_key] = tile
                while len(self._cache) > self._settings.tile_cache_entries:
                    self._cache.popitem(last=False)
        return tile

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient()
        return self._http

    async def _auth_headers(self) -> Dict[str, str]:
        if self._settings.azure_maps_key:
            return {"subscription-key": self._settings.azure_maps_key}
        if time.time() > self._token_expires_on - TOKEN_REFRESH_MARGIN_SECONDS:
            try:
                access = await self._credential.get_token(MAPS_TOKEN_SCOPE)
            except AzureError as exc:
                LOGGER.error(f"[MAP_SERVER_TILES] Couldn't get an Azure Maps token ({type(exc).__name__}).")
                raise MapServerError(502, "tile_auth_failed", "The map server couldn't sign in to Azure Maps.") from exc
            self._token, self._token_expires_on = access.token, float(access.expires_on)
        return {"Authorization": f"Bearer {self._token}", "x-ms-client-id": self._settings.azure_maps_client_id}

    async def close(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None
