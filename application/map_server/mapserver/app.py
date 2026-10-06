# app.py
"""HTTP API for the map server. Every route but the health check needs a caller holding the map server role."""

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from azure.identity.aio import DefaultAzureCredential
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import MutableHeaders

from . import __version__
from .auth import ACTOR_HEADER, Actor, Caller, TokenValidator, parse_actor
from .cosmos_store import CosmosMapStore
from .engine import MapEngine
from .errors import MapServerError
from .models import (
    AddFeaturesRequest,
    CreateMapRequest,
    LinkConversationRequest,
    RetractFeatureRequest,
    StartPhaseRequest,
    UpdateFeatureRequest,
    UpdateMapRequest,
    UpdatePhaseRequest,
)
from .settings import STORE_COSMOS, STORE_MEMORY, Settings
from .store import InMemoryMapStore
from .tiles import TileService

LOGGER = logging.getLogger("mapserver")

MAX_BODY_BYTES = 1_048_576
MAX_VALIDATION_DETAILS = 20
EVENT_RETRY_MILLISECONDS = 5000


def _configure_logging() -> None:
    logger = logging.getLogger("mapserver")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


class RequestGuard:
    """Caps request bodies and adds security headers, without buffering streamed responses."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope.get("headers") or []).get(b"content-length", b"")
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            response = JSONResponse(
                status_code=413, content={"error": "request_too_large", "message": "The request body is too large."},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("x-content-type-options", "nosniff")
                if "cache-control" not in headers:
                    headers["cache-control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _sse(event: str, data: Dict[str, Any], event_id: str = "") -> str:
    lines = [f"id: {event_id}"] if event_id else []
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


async def _event_stream(
    request: Request, engine: MapEngine, actor: Actor, map_id: str, start_version: int, settings: Settings
) -> AsyncIterator[str]:
    """One event per map change. Access is checked again on every poll."""
    last_version = start_version
    started = last_sent = time.monotonic()
    yield f"retry: {EVENT_RETRY_MILLISECONDS}\n\n"
    while True:
        try:
            if await engine.current_version(actor, map_id) > last_version:
                page = await engine.list_changes(actor, map_id, since_version=last_version, limit=100)
                for change in page["items"]:
                    yield _sse("change", change, event_id=str(change["version"]))
                    last_version = change["version"]
                last_sent = time.monotonic()
        except MapServerError as exc:
            yield _sse("error", {"error": exc.code, "message": exc.message})
            return
        now = time.monotonic()
        if now - started >= settings.events_max_seconds:
            yield _sse("end", {"version": last_version})
            return
        if now - last_sent >= settings.events_keepalive_seconds:
            yield ": keepalive\n\n"
            last_sent = now
        if await request.is_disconnected():
            return
        await asyncio.sleep(settings.events_poll_seconds)


def create_app(
    settings: Optional[Settings] = None,
    *,
    store: Optional[Any] = None,
    token_validator: Optional[TokenValidator] = None,
    tile_service: Optional[TileService] = None,
    credential: Optional[Any] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned_credential = None
        app_credential = credential
        needs_credential = (settings.store == STORE_COSMOS and not settings.cosmos_key) or (
            settings.azure_maps_client_id and not settings.azure_maps_key
        )
        if app_credential is None and needs_credential:
            app_credential = DefaultAzureCredential(managed_identity_client_id=settings.managed_identity_client_id or None)
            owned_credential = app_credential

        map_store = store
        if map_store is None:
            map_store = InMemoryMapStore() if settings.store == STORE_MEMORY else CosmosMapStore.from_settings(settings, app_credential)
        tiles = tile_service or TileService(settings, credential=app_credential)
        app.state.settings = settings
        app.state.engine = MapEngine(map_store, settings)
        app.state.tiles = tiles
        app.state.validator = token_validator or TokenValidator(settings)
        if settings.local_dev_key:
            LOGGER.warning("[MAP_SERVER] Running with the local developer key and the in-memory store. Don't expose this server.")
        LOGGER.info(f"[MAP_SERVER] Map server {__version__} started with the {settings.store} store.")
        try:
            yield
        finally:
            if store is None:
                await map_store.close()
            if tile_service is None:
                await tiles.close()
            if owned_credential is not None:
                await owned_credential.close()

    app = FastAPI(
        title="SimpleChat map server",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestGuard)

    @app.exception_handler(MapServerError)
    async def handle_map_error(request: Request, exc: MapServerError) -> JSONResponse:
        body: Dict[str, Any] = {"error": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": ".".join(str(part) for part in error.get("loc", ())), "problem": str(error.get("msg", ""))}
            for error in exc.errors()[:MAX_VALIDATION_DETAILS]
        ]
        return JSONResponse(
            status_code=400, content={"error": "invalid_request", "message": "The request isn't valid.", "details": details},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.error(f"[MAP_SERVER] Unexpected error ({type(exc).__name__}).")
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Unexpected error."})

    def get_caller(request: Request) -> Caller:
        return request.app.state.validator.validate(request.headers.get("authorization"))

    def get_actor(request: Request, caller: Caller = Depends(get_caller)) -> Actor:
        return parse_actor(request.headers.get(ACTOR_HEADER))

    def get_engine(request: Request) -> MapEngine:
        return request.app.state.engine

    @app.get("/healthz", include_in_schema=False)
    async def health() -> Dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/maps", status_code=201)
    async def create_map(body: CreateMapRequest, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine)):
        return await engine.create_map(actor, body)

    @app.get("/v1/maps")
    async def list_maps(
        conversation_id: str = Query(default="", max_length=128),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.list_maps(actor, conversation_id)

    @app.get("/v1/maps/{map_id}")
    async def get_map(map_id: str, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine)):
        return await engine.get_map(actor, map_id)

    @app.patch("/v1/maps/{map_id}")
    async def update_map(
        map_id: str,
        body: UpdateMapRequest,
        if_match: str = Header(default="", alias="If-Match", max_length=128),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.update_map(actor, map_id, body, if_match)

    @app.post("/v1/maps/{map_id}/links")
    async def link_conversation(
        map_id: str, body: LinkConversationRequest, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine),
    ):
        return await engine.link_conversation(actor, map_id, body.conversation_id)

    @app.delete("/v1/maps/{map_id}/links/{conversation_id}")
    async def unlink_conversation(
        map_id: str, conversation_id: str, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine),
    ):
        return await engine.unlink_conversation(actor, map_id, conversation_id)

    @app.post("/v1/maps/{map_id}/phases", status_code=201)
    async def start_phase(
        map_id: str, body: StartPhaseRequest, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine),
    ):
        return await engine.start_phase(actor, map_id, body)

    @app.patch("/v1/maps/{map_id}/phases/{phase_id}")
    async def update_phase(
        map_id: str,
        phase_id: str,
        body: UpdatePhaseRequest,
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.update_phase(actor, map_id, phase_id, body)

    @app.post("/v1/maps/{map_id}/features:batch")
    async def add_features(
        map_id: str, body: AddFeaturesRequest, actor: Actor = Depends(get_actor), engine: MapEngine = Depends(get_engine),
    ):
        return await engine.add_features(actor, map_id, body)

    @app.patch("/v1/maps/{map_id}/features/{feature_id}")
    async def update_feature(
        map_id: str,
        feature_id: str,
        body: UpdateFeatureRequest,
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.update_feature(actor, map_id, feature_id, body)

    @app.post("/v1/maps/{map_id}/features/{feature_id}:retract")
    async def retract_feature(
        map_id: str,
        feature_id: str,
        body: RetractFeatureRequest,
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.retract_feature(actor, map_id, feature_id, body)

    @app.get("/v1/maps/{map_id}/features")
    async def list_features(
        map_id: str,
        phase_id: str = Query(default="", max_length=8),
        category: str = Query(default="", max_length=40),
        kind: str = Query(default="", max_length=8),
        status: str = Query(default="active", max_length=10),
        since_version: Optional[int] = Query(default=None, ge=0),
        bbox: str = Query(default="", max_length=128),
        limit: int = Query(default=200, ge=1, le=500),
        cursor: str = Query(default="", max_length=16),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.list_features(
            actor, map_id, phase_id=phase_id, category=category, kind=kind, status=status,
            since_version=since_version, bbox=bbox, limit=limit, cursor=cursor,
        )

    @app.get("/v1/maps/{map_id}/snapshot")
    async def snapshot(
        map_id: str,
        as_of_version: Optional[int] = Query(default=None, ge=1),
        phases: str = Query(default="", max_length=400),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        phase_ids = [phase.strip() for phase in phases.split(",") if phase.strip()]
        return await engine.snapshot(actor, map_id, as_of_version=as_of_version, phase_ids=phase_ids)

    @app.get("/v1/maps/{map_id}/changes")
    async def list_changes(
        map_id: str,
        since_version: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        return await engine.list_changes(actor, map_id, since_version=since_version, limit=limit)

    @app.get("/v1/maps/{map_id}/events")
    async def map_events(
        map_id: str,
        request: Request,
        since_version: Optional[int] = Query(default=None, ge=0),
        last_event_id: str = Header(default="", alias="Last-Event-ID", max_length=16),
        actor: Actor = Depends(get_actor),
        engine: MapEngine = Depends(get_engine),
    ):
        current = await engine.current_version(actor, map_id)
        if last_event_id.isdigit():
            start = int(last_event_id)
        elif since_version is not None:
            start = since_version
        else:
            start = current
        return StreamingResponse(
            _event_stream(request, engine, actor, map_id, min(start, current), settings),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/tiles/{tileset}/{z}/{x}/{y}")
    async def tile(tileset: str, z: int, x: int, y: int, request: Request, caller: Caller = Depends(get_caller)):
        content, media_type = await request.app.state.tiles.get_tile(tileset, z, x, y)
        return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

    return app
