# engine.py
"""Map operations: who may do what, and how every change becomes one new, logged map version."""

import asyncio
import copy
import logging
import random
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import validation
from .auth import Actor
from .errors import conflict, forbidden, invalid, not_found, precondition_failed, store_unavailable
from .models import (
    AddFeaturesRequest,
    CreateMapRequest,
    RetractFeatureRequest,
    StartPhaseRequest,
    UpdateFeatureRequest,
    UpdateMapRequest,
    UpdatePhaseRequest,
)
from .settings import Settings
from .store import MAX_BATCH_OPERATIONS, ConflictError, MapStore, StoreError

LOGGER = logging.getLogger("mapserver.engine")

SCHEMA_VERSION = 1
MAX_WRITE_ATTEMPTS = 6
MAX_PHASES = 50
MAX_LINKS = 50
MAX_LISTED_MAPS = 200
MAX_CHANGE_LABELS = 5
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 500
MAX_CHANGES_PAGE = 500
MAX_CURSOR = 10_000_000
DEFAULT_LINE_WIDTH = 4
TILE_ATTRIBUTION = "© Microsoft Corporation © OpenStreetMap contributors"
BACKGROUND_COLOR = "#000000"
PHASE_COLORS = ("#0d6efd", "#fd7e14", "#20c997", "#d63384", "#6f42c1", "#ffc107", "#198754", "#dc3545", "#0dcaf0", "#6610f2")
ZERO_COUNTS = {"active": 0, "retracted": 0, "point": 0, "path": 0, "area": 0}
PHASE_OUTPUT_FIELDS = (
    "id", "order", "name", "description", "color", "status",
    "started_at", "started_by", "started_version", "closed_at", "closed_version",
)
FEATURE_OUTPUT_FIELDS = (
    "id", "kind", "geometry", "label", "category", "description", "observed_at", "source", "media", "fields", "style",
    "status", "phase_id", "last_phase_id", "revision", "created_version", "retracted_version", "retract_reason",
    "created_by", "created_at", "updated_by", "updated_at",
)
CHANGE_OUTPUT_FIELDS = (
    "id", "version", "action", "phase_id", "added", "updated", "retracted", "skipped", "labels", "note", "actor", "at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class WritePlan:
    """What one write changes, besides the map document itself."""

    phase_id: str = ""
    creates: List[Dict[str, Any]] = field(default_factory=list)
    replaces: List[Dict[str, Any]] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    retracted: List[str] = field(default_factory=list)
    skipped: int = 0
    labels: List[str] = field(default_factory=list)
    note: str = ""
    no_op: bool = False
    result: Dict[str, Any] = field(default_factory=dict)


Build = Callable[[Dict[str, Any], int, str, str], Awaitable[WritePlan]]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _translucent(color: str) -> str:
    hex_digits = color.lstrip("#") if color.startswith("#") else ""
    if len(hex_digits) == 3:
        hex_digits = "".join(digit * 2 for digit in hex_digits)
    if len(hex_digits) in (6, 8):
        red, green, blue = (int(hex_digits[index:index + 2], 16) for index in (0, 2, 4))
        return f"rgba({red}, {green}, {blue}, 0.20)"
    return "rgba(13, 110, 253, 0.20)"


def _who(summary: Optional[Dict[str, Any]]) -> str:
    summary = summary or {}
    return str((summary.get("agent") or {}).get("name") or summary.get("display_name") or "")


class MapEngine:
    def __init__(self, store: MapStore, settings: Settings, *, clock: Callable[[], str] = utc_now):
        self._store = store
        self._settings = settings
        self._clock = clock

    # ------------------------------------------------------------------------------------------
    # Access and writes
    # ------------------------------------------------------------------------------------------

    async def _guard(self, awaitable: Awaitable[Any]) -> Any:
        try:
            return await awaitable
        except StoreError as exc:
            LOGGER.error(f"[MAP_SERVER_STORE] A store call failed ({type(exc).__name__}).")
            raise store_unavailable() from exc

    async def _load(self, actor: Actor, map_id: str, *, write: bool = False) -> Tuple[Dict[str, Any], str]:
        """The map, if the actor's scope owns it. Other scopes get the same answer as a missing map."""
        validation.require_map_id(map_id)
        loaded = await self._guard(self._store.read_map(map_id))
        if loaded is None or loaded[0].get("owner_scope") != actor.scope:
            raise not_found()
        if write and not actor.can_write:
            raise forbidden("read_only", "This request can only read the map.")
        return loaded

    async def _commit(
        self,
        map_id: str,
        map_doc: Dict[str, Any],
        etag: Optional[str],
        creates: Sequence[Dict[str, Any]],
        replaces: Sequence[Dict[str, Any]],
    ) -> str:
        try:
            return await self._store.commit(map_id, map_doc, etag, creates, replaces)
        except StoreError as exc:
            LOGGER.error(f"[MAP_SERVER_STORE] A map write failed ({type(exc).__name__}).")
            raise store_unavailable() from exc

    async def _write(self, actor: Actor, map_id: str, action: str, build: Build) -> Dict[str, Any]:
        """Apply one change as the next map version, retrying from a fresh read when another write lands first."""
        for attempt in range(MAX_WRITE_ATTEMPTS):
            map_doc, etag = await self._load(actor, map_id, write=True)
            version = int(map_doc.get("version") or 0) + 1
            now = self._clock()
            plan = await build(map_doc, version, now, etag)
            if plan.no_op:
                return {"map_id": map_id, "version": map_doc["version"], "change_id": None, "unchanged": True, **plan.result}
            change = self._change_doc(map_id, version, action, actor, now, plan, map_doc)
            map_doc["version"] = version
            map_doc["updated_at"] = now
            map_doc["updated_by"] = actor.summary()
            try:
                await self._commit(map_id, map_doc, etag, [*plan.creates, change], plan.replaces)
            except ConflictError:
                await asyncio.sleep(random.uniform(0.005, 0.02) * (attempt + 1))
                continue
            return {"map_id": map_id, "version": version, "change_id": change["id"], **plan.result}
        LOGGER.warning(f"[MAP_SERVER] A write kept conflicting and gave up (map {map_id}, action {action}).")
        raise conflict("map_busy", "The map kept changing while saving. Try again.")

    def _change_doc(
        self, map_id: str, version: int, action: str, actor: Actor, now: str, plan: WritePlan, map_doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "id": f"C-{version:06d}",
            "map_id": map_id,
            "type": "change",
            "schema_version": SCHEMA_VERSION,
            "version": version,
            "action": action,
            "phase_id": plan.phase_id or map_doc.get("current_phase_id", ""),
            "added": plan.added,
            "updated": plan.updated,
            "retracted": plan.retracted,
            "skipped": plan.skipped,
            "labels": plan.labels[:MAX_CHANGE_LABELS],
            "note": plan.note,
            "actor": actor.summary(),
            "at": now,
        }

    async def _index(self, map_id: str, scope_key: str, now: str) -> None:
        # The index is written before the map, so a failed write leaves a row that reads ignore, never a hidden map.
        await self._guard(self._store.upsert_link({"id": map_id, "scope_key": scope_key, "map_id": map_id, "at": now}))

    # ------------------------------------------------------------------------------------------
    # Shapes returned to callers
    # ------------------------------------------------------------------------------------------

    @staticmethod
    def _phase(map_doc: Dict[str, Any], phase_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((phase for phase in map_doc.get("phases", []) if phase["id"] == phase_id), None)

    @staticmethod
    def _public_phase(phase: Dict[str, Any]) -> Dict[str, Any]:
        return {name: phase.get(name) for name in PHASE_OUTPUT_FIELDS}

    @staticmethod
    def _linked_ids(map_doc: Dict[str, Any]) -> List[str]:
        return [link["conversation_id"] for link in map_doc.get("links", [])]

    def _map_view(self, map_doc: Dict[str, Any], etag: str) -> Dict[str, Any]:
        return {
            "map_id": map_doc["map_id"],
            "title": map_doc["title"],
            "description": map_doc.get("description", ""),
            "owner_scope": map_doc["owner_scope"],
            "basemap": map_doc["basemap"],
            "version": map_doc["version"],
            "current_phase_id": map_doc["current_phase_id"],
            "phases": [self._public_phase(phase) for phase in map_doc.get("phases", [])],
            "counts": dict(ZERO_COUNTS, **map_doc.get("counts", {})),
            "links": self._linked_ids(map_doc),
            "created_at": map_doc.get("created_at"),
            "created_by": map_doc.get("created_by"),
            "updated_at": map_doc.get("updated_at"),
            "updated_by": map_doc.get("updated_by"),
            "etag": etag,
        }

    def _map_summary(self, map_doc: Dict[str, Any]) -> Dict[str, Any]:
        current = self._phase(map_doc, map_doc.get("current_phase_id")) or {}
        return {
            "map_id": map_doc["map_id"],
            "title": map_doc["title"],
            "version": map_doc["version"],
            "counts": dict(ZERO_COUNTS, **map_doc.get("counts", {})),
            "current_phase": {"id": current.get("id"), "name": current.get("name"), "color": current.get("color")},
            "updated_at": map_doc.get("updated_at"),
        }

    @staticmethod
    def _public_feature(feature: Dict[str, Any], phases_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        output = {name: copy.deepcopy(feature.get(name)) for name in FEATURE_OUTPUT_FIELDS}
        output["updated_version"] = feature.get("version_start")
        output["phase_name"] = (phases_by_id.get(feature.get("phase_id")) or {}).get("name", "")
        return output

    @staticmethod
    def _public_change(change: Dict[str, Any]) -> Dict[str, Any]:
        return {name: copy.deepcopy(change.get(name)) for name in CHANGE_OUTPUT_FIELDS}

    @staticmethod
    def _brief(feature: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": feature["id"], "label": feature["label"], "kind": feature["kind"]}

    @staticmethod
    def _content(content: Dict[str, Any]) -> Dict[str, Any]:
        return {name: copy.deepcopy(content.get(name)) for name in validation.CONTENT_FIELDS}

    @staticmethod
    def _new_phase(order: int, name: str, description: str, color: str, actor: Actor, now: str, version: int) -> Dict[str, Any]:
        return {
            "id": f"P{order}",
            "order": order,
            "name": name,
            "description": description,
            "color": color or PHASE_COLORS[(order - 1) % len(PHASE_COLORS)],
            "status": "open",
            "started_by": actor.summary(),
            "started_at": now,
            "started_version": version,
            "closed_at": None,
            "closed_version": None,
        }

    def _writable_phase(self, map_doc: Dict[str, Any], phase_id: str) -> Dict[str, Any]:
        if not phase_id:
            return self._phase(map_doc, map_doc["current_phase_id"])
        validation.require_phase_id(phase_id)
        phase = self._phase(map_doc, phase_id)
        if phase is None:
            raise not_found("phase_not_found", "Phase not found.")
        if phase["status"] != "open":
            raise conflict("phase_closed", f"Phase {phase['id']} is closed. Use the current phase or start a new one.")
        return phase

    @staticmethod
    def _revision_doc(feature: Dict[str, Any], version: int) -> Dict[str, Any]:
        revision = copy.deepcopy(feature)
        revision.update({
            "id": f"{feature['id']}@r{feature['revision']}",
            "type": "feature_rev",
            "feature_id": feature["id"],
            "valid_from_version": feature["version_start"],
            "valid_to_version": version - 1,
        })
        revision.pop("dup_key", None)
        return revision

    async def _read_feature(self, map_id: str, feature_id: str) -> Dict[str, Any]:
        item = await self._guard(self._store.read_item(map_id, feature_id))
        if not item or item.get("type") != "feature":
            raise not_found("feature_not_found", "Feature not found.")
        return item

    # ------------------------------------------------------------------------------------------
    # Maps and links
    # ------------------------------------------------------------------------------------------

    async def create_map(self, actor: Actor, request: CreateMapRequest) -> Dict[str, Any]:
        if not actor.can_write:
            raise forbidden("read_only", "This request can only read maps.")
        title = validation.require_text(request.title, validation.TITLE_MAX, "A map needs a title.")
        description = validation.normalize_text(request.description, validation.MAP_DESCRIPTION_MAX, multiline=True)
        basemap = validation.normalize_tileset(request.basemap or self._settings.default_basemap)
        phase_name = validation.normalize_text(request.first_phase_name, validation.PHASE_NAME_MAX) or "Phase 1"
        phase_description = validation.normalize_text(
            request.first_phase_description, validation.PHASE_DESCRIPTION_MAX, multiline=True,
        )
        conversation_id = validation.normalize_conversation_id(request.conversation_id)

        now = self._clock()
        map_id = f"map-{secrets.token_hex(10)}"
        phase = self._new_phase(1, phase_name, phase_description, "", actor, now, 1)
        links = [{"conversation_id": conversation_id, "linked_at": now, "linked_by": actor.summary()}] if conversation_id else []
        map_doc = {
            "id": map_id,
            "map_id": map_id,
            "type": "map",
            "schema_version": SCHEMA_VERSION,
            "title": title,
            "description": description,
            "owner_scope": actor.scope,
            "basemap": basemap,
            "version": 1,
            "phases": [phase],
            "current_phase_id": phase["id"],
            "phase_seq": 1,
            "feature_seq": 0,
            "counts": dict(ZERO_COUNTS),
            "links": links,
            "created_by": actor.summary(),
            "created_at": now,
            "updated_by": actor.summary(),
            "updated_at": now,
        }
        change = self._change_doc(map_id, 1, "create_map", actor, now, WritePlan(phase_id=phase["id"], note=title), map_doc)
        await self._index(map_id, actor.scope, now)
        if conversation_id:
            await self._index(map_id, f"conversation:{conversation_id}", now)
        try:
            etag = await self._commit(map_id, map_doc, None, [change], [])
        except ConflictError as exc:
            raise conflict("map_exists", "Couldn't create the map. Try again.") from exc
        return self._map_view(map_doc, etag)

    async def list_maps(self, actor: Actor, conversation_id: str = "") -> Dict[str, Any]:
        conversation_id = validation.normalize_conversation_id(conversation_id)
        scope_key = f"conversation:{conversation_id}" if conversation_id else actor.scope
        rows = await self._guard(self._store.list_links(scope_key))
        items = []
        for row in rows[:MAX_LISTED_MAPS]:
            map_id = str(row.get("map_id") or "")
            if not validation.MAP_ID_PATTERN.fullmatch(map_id):
                continue
            loaded = await self._guard(self._store.read_map(map_id))
            if loaded is None or loaded[0].get("owner_scope") != actor.scope:
                continue
            if conversation_id and conversation_id not in self._linked_ids(loaded[0]):
                continue
            items.append(self._map_summary(loaded[0]))
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return {"items": items}

    async def get_map(self, actor: Actor, map_id: str) -> Dict[str, Any]:
        map_doc, etag = await self._load(actor, map_id)
        return self._map_view(map_doc, etag)

    async def update_map(self, actor: Actor, map_id: str, request: UpdateMapRequest, if_match: str = "") -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        if request.title is not None:
            changes["title"] = validation.require_text(request.title, validation.TITLE_MAX, "A map needs a title.")
        if request.description is not None:
            changes["description"] = validation.normalize_text(
                request.description, validation.MAP_DESCRIPTION_MAX, multiline=True,
            )
        if request.basemap is not None:
            changes["basemap"] = validation.normalize_tileset(request.basemap)
        if not changes:
            raise invalid("Send a title, description or basemap to change.")

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            if if_match and if_match != etag:
                raise precondition_failed("map_changed", "The map changed since you read it.")
            if all(map_doc.get(name) == value for name, value in changes.items()):
                return WritePlan(no_op=True)
            map_doc.update(changes)
            return WritePlan(note=", ".join(sorted(changes)))

        await self._write(actor, map_id, "update_map", build)
        return await self.get_map(actor, map_id)

    async def link_conversation(self, actor: Actor, map_id: str, conversation_id: str) -> Dict[str, Any]:
        conversation_id = validation.normalize_conversation_id(conversation_id)
        if not conversation_id:
            raise invalid("conversation_id is required.")
        for attempt in range(MAX_WRITE_ATTEMPTS):
            map_doc, etag = await self._load(actor, map_id, write=True)
            if conversation_id in self._linked_ids(map_doc):
                return {"map_id": map_id, "conversation_id": conversation_id, "links": self._linked_ids(map_doc)}
            if len(map_doc.get("links", [])) >= MAX_LINKS:
                raise conflict("too_many_links", f"A map can be linked to up to {MAX_LINKS} conversations.")
            now = self._clock()
            await self._index(map_id, f"conversation:{conversation_id}", now)
            map_doc.setdefault("links", []).append(
                {"conversation_id": conversation_id, "linked_at": now, "linked_by": actor.summary()}
            )
            try:
                await self._commit(map_id, map_doc, etag, [], [])
            except ConflictError:
                await asyncio.sleep(random.uniform(0.005, 0.02) * (attempt + 1))
                continue
            return {"map_id": map_id, "conversation_id": conversation_id, "links": self._linked_ids(map_doc)}
        raise conflict("map_busy", "The map kept changing while saving. Try again.")

    async def unlink_conversation(self, actor: Actor, map_id: str, conversation_id: str) -> Dict[str, Any]:
        conversation_id = validation.normalize_conversation_id(conversation_id)
        if not conversation_id:
            raise invalid("conversation_id is required.")
        for attempt in range(MAX_WRITE_ATTEMPTS):
            map_doc, etag = await self._load(actor, map_id, write=True)
            remaining = [link for link in map_doc.get("links", []) if link["conversation_id"] != conversation_id]
            if len(remaining) == len(map_doc.get("links", [])):
                break
            map_doc["links"] = remaining
            try:
                await self._commit(map_id, map_doc, etag, [], [])
            except ConflictError:
                await asyncio.sleep(random.uniform(0.005, 0.02) * (attempt + 1))
                continue
            break
        else:
            raise conflict("map_busy", "The map kept changing while saving. Try again.")
        await self._guard(self._store.delete_link(f"conversation:{conversation_id}", map_id))
        return {"map_id": map_id, "conversation_id": conversation_id, "links": self._linked_ids(map_doc)}

    # ------------------------------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------------------------------

    async def start_phase(self, actor: Actor, map_id: str, request: StartPhaseRequest) -> Dict[str, Any]:
        name = validation.require_text(request.name, validation.PHASE_NAME_MAX, "A phase needs a name.")
        description = validation.normalize_text(request.description, validation.PHASE_DESCRIPTION_MAX, multiline=True)
        color = validation.normalize_color(request.color)
        if request.color and not color:
            raise invalid("color must be a hex or rgba color, such as #0d6efd.")

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            phases = map_doc.setdefault("phases", [])
            if len(phases) >= MAX_PHASES:
                raise conflict("too_many_phases", f"A map can have up to {MAX_PHASES} phases.")
            current = self._phase(map_doc, map_doc.get("current_phase_id"))
            if current and current["status"] == "open":
                current.update({"status": "closed", "closed_at": now, "closed_version": version})
            order = int(map_doc.get("phase_seq") or len(phases)) + 1
            map_doc["phase_seq"] = order
            phase = self._new_phase(order, name, description, color, actor, now, version)
            phases.append(phase)
            map_doc["current_phase_id"] = phase["id"]
            return WritePlan(phase_id=phase["id"], note=name, result={"phase": self._public_phase(phase)})

        return await self._write(actor, map_id, "start_phase", build)

    async def update_phase(self, actor: Actor, map_id: str, phase_id: str, request: UpdatePhaseRequest) -> Dict[str, Any]:
        validation.require_phase_id(phase_id)
        changes: Dict[str, Any] = {}
        if request.name is not None:
            changes["name"] = validation.require_text(request.name, validation.PHASE_NAME_MAX, "A phase needs a name.")
        if request.description is not None:
            changes["description"] = validation.normalize_text(
                request.description, validation.PHASE_DESCRIPTION_MAX, multiline=True,
            )
        if request.color is not None:
            changes["color"] = validation.normalize_color(request.color)
            if not changes["color"]:
                raise invalid("color must be a hex or rgba color, such as #0d6efd.")
        if not changes:
            raise invalid("Send a name, description or color to change.")

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            phase = self._phase(map_doc, phase_id)
            if phase is None:
                raise not_found("phase_not_found", "Phase not found.")
            if all(phase.get(name) == value for name, value in changes.items()):
                return WritePlan(no_op=True, result={"phase": self._public_phase(phase)})
            phase.update(changes)
            return WritePlan(phase_id=phase_id, note=phase["name"], result={"phase": self._public_phase(phase)})

        return await self._write(actor, map_id, "update_phase", build)

    # ------------------------------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------------------------------

    async def add_features(self, actor: Actor, map_id: str, request: AddFeaturesRequest) -> Dict[str, Any]:
        limit = self._settings.max_features_per_call
        if len(request.features) > limit:
            raise invalid(f"Send up to {limit} features per call, and split larger sets.", code="too_many_features")
        normalized = [validation.normalize_feature(raw, index) for index, raw in enumerate(request.features)]
        contents = [content for content, _ in normalized]
        images_dropped = sum(1 for _, dropped in normalized if dropped)
        update_duplicates = request.on_duplicate == "update"

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            phase = self._writable_phase(map_doc, request.phase_id)
            keys = sorted({content["dup_key"] for content in contents if content["dup_key"]})
            existing: Dict[str, Dict[str, Any]] = {}
            if keys:
                for feature in await self._guard(self._store.query_features(map_id, dup_keys=keys)):
                    existing.setdefault(feature["dup_key"], feature)

            counts = dict(ZERO_COUNTS, **map_doc.get("counts", {}))
            created: Dict[str, Dict[str, Any]] = {}
            new_docs: List[Dict[str, Any]] = []
            updates: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
            skipped: Dict[str, Dict[str, Any]] = {}
            for content in contents:
                key = content["dup_key"]
                if key and key in created:
                    if update_duplicates:
                        created[key].update(self._content(content))
                    else:
                        skipped[created[key]["id"]] = created[key]
                    continue
                if key and key in existing:
                    original = existing[key]
                    current = updates[original["id"]][1] if original["id"] in updates else copy.deepcopy(original)
                    if update_duplicates and not validation.content_equal(current, content):
                        current.update(self._content(content))
                        updates[original["id"]] = (original, current)
                    elif original["id"] not in updates:
                        skipped[original["id"]] = original
                    continue
                if counts["active"] >= self._settings.max_active_features:
                    raise conflict(
                        "map_full",
                        f"A map holds up to {self._settings.max_active_features} active features. Retract ones that no longer matter.",
                    )
                sequence = int(map_doc.get("feature_seq") or 0) + 1
                map_doc["feature_seq"] = sequence
                doc = {
                    "id": f"F-{sequence:04d}",
                    "map_id": map_id,
                    "type": "feature",
                    "schema_version": SCHEMA_VERSION,
                    "kind": content["kind"],
                    **self._content(content),
                    "phase_id": phase["id"],
                    "last_phase_id": phase["id"],
                    "status": "active",
                    "created_version": version,
                    "version_start": version,
                    "retracted_version": None,
                    "retract_reason": None,
                    "revision": 1,
                    "created_by": actor.summary(),
                    "created_at": now,
                    "updated_by": actor.summary(),
                    "updated_at": now,
                }
                new_docs.append(doc)
                counts["active"] += 1
                counts[content["kind"]] += 1
                if key:
                    created[key] = doc

            plan = WritePlan(phase_id=phase["id"])
            for original, current in updates.values():
                plan.creates.append(self._revision_doc(original, version))
                current.update({
                    "revision": original["revision"] + 1,
                    "version_start": version,
                    "last_phase_id": phase["id"],
                    "updated_by": actor.summary(),
                    "updated_at": now,
                })
                plan.replaces.append(current)
            plan.creates.extend(new_docs)
            if 2 + len(plan.creates) + len(plan.replaces) > MAX_BATCH_OPERATIONS:
                raise invalid("Too many changes for one call. Send fewer features.", code="too_many_changes")

            updated_docs = [current for _, current in updates.values()]
            plan.no_op = not new_docs and not updated_docs
            map_doc["counts"] = counts
            plan.added = [doc["id"] for doc in new_docs]
            plan.updated = [doc["id"] for doc in updated_docs]
            plan.skipped = len(skipped)
            plan.labels = [doc["label"] for doc in [*new_docs, *updated_docs]]
            plan.result = {
                "phase": self._public_phase(phase),
                "added": [self._brief(doc) for doc in new_docs],
                "updated": [self._brief(doc) for doc in updated_docs],
                "skipped": [self._brief(doc) for doc in skipped.values()],
                "images_dropped": images_dropped,
                "counts": counts,
            }
            return plan

        return await self._write(actor, map_id, "add_features", build)

    async def update_feature(
        self, actor: Actor, map_id: str, feature_id: str, request: UpdateFeatureRequest
    ) -> Dict[str, Any]:
        validation.require_feature_id(feature_id)

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            phase = self._writable_phase(map_doc, request.phase_id)
            phases_by_id = {item["id"]: item for item in map_doc.get("phases", [])}
            current = await self._read_feature(map_id, feature_id)
            if current["status"] != "active":
                raise conflict("feature_retracted", "This feature was retracted and can't be changed.")
            if request.expected_revision is not None and request.expected_revision != current["revision"]:
                raise precondition_failed("revision_mismatch", "The feature changed since you read it.")
            content, image_dropped = validation.apply_changes(current, request.changes)
            if validation.content_equal(current, content):
                return WritePlan(no_op=True, result={"updated": [], "feature": self._public_feature(current, phases_by_id)})
            if content["dup_key"] and content["dup_key"] != current.get("dup_key"):
                clashes = await self._guard(self._store.query_features(map_id, dup_keys=[content["dup_key"]]))
                if any(item["id"] != feature_id for item in clashes):
                    raise conflict("duplicate_source", "Another feature on this map already has that source record.")

            updated = copy.deepcopy(current)
            updated.update(self._content(content))
            updated.update({
                "revision": current["revision"] + 1,
                "version_start": version,
                "last_phase_id": phase["id"],
                "updated_by": actor.summary(),
                "updated_at": now,
            })
            return WritePlan(
                phase_id=phase["id"],
                creates=[self._revision_doc(current, version)],
                replaces=[updated],
                updated=[feature_id],
                labels=[updated["label"]],
                result={
                    "phase": self._public_phase(phase),
                    "updated": [self._brief(updated)],
                    "feature": self._public_feature(updated, phases_by_id),
                    "images_dropped": int(image_dropped),
                },
            )

        return await self._write(actor, map_id, "update_feature", build)

    async def retract_feature(
        self, actor: Actor, map_id: str, feature_id: str, request: RetractFeatureRequest
    ) -> Dict[str, Any]:
        validation.require_feature_id(feature_id)
        reason = validation.require_text(request.reason, validation.REASON_MAX, "Say why the feature is being retracted.")

        async def build(map_doc: Dict[str, Any], version: int, now: str, etag: str) -> WritePlan:
            phase = self._writable_phase(map_doc, request.phase_id)
            current = await self._read_feature(map_id, feature_id)
            if current["status"] != "active":
                return WritePlan(no_op=True, result={"retracted": []})
            updated = copy.deepcopy(current)
            updated.update({
                "status": "retracted",
                "retracted_version": version,
                "retract_reason": reason,
                "last_phase_id": phase["id"],
                "updated_by": actor.summary(),
                "updated_at": now,
            })
            counts = dict(ZERO_COUNTS, **map_doc.get("counts", {}))
            counts["active"] = max(0, counts["active"] - 1)
            counts[current["kind"]] = max(0, counts[current["kind"]] - 1)
            counts["retracted"] += 1
            map_doc["counts"] = counts
            return WritePlan(
                phase_id=phase["id"],
                replaces=[updated],
                retracted=[feature_id],
                labels=[current["label"]],
                note=reason,
                result={"phase": self._public_phase(phase), "retracted": [self._brief(updated)], "counts": counts},
            )

        return await self._write(actor, map_id, "retract_feature", build)

    # ------------------------------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------------------------------

    @staticmethod
    def _cursor_offset(cursor: str) -> int:
        if not cursor:
            return 0
        if not cursor.isdigit() or int(cursor) > MAX_CURSOR:
            raise invalid("cursor isn't valid.")
        return int(cursor)

    @staticmethod
    def _intersects(geometry: Dict[str, Any], box: Tuple[float, float, float, float]) -> bool:
        points = validation.feature_points(geometry)
        if not points:
            return False
        longitudes = [point[0] for point in points]
        latitudes = [point[1] for point in points]
        west, south, east, north = box
        return min(longitudes) <= east and max(longitudes) >= west and min(latitudes) <= north and max(latitudes) >= south

    async def list_features(
        self,
        actor: Actor,
        map_id: str,
        *,
        phase_id: str = "",
        category: str = "",
        kind: str = "",
        status: str = "active",
        since_version: Optional[int] = None,
        bbox: str = "",
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str = "",
    ) -> Dict[str, Any]:
        map_doc, _ = await self._load(actor, map_id)
        if status not in ("active", "retracted", "all"):
            raise invalid("status must be active, retracted or all.")
        if kind and kind not in validation.FEATURE_KINDS:
            raise invalid("kind must be point, path or area.")
        if phase_id and not validation.PHASE_ID_PATTERN.fullmatch(phase_id):
            raise invalid("phase_id must be a phase ID such as P1.")
        wanted_category = validation.normalize_category(category) if category else ""
        box = validation.parse_bbox(bbox)
        page_size = max(1, min(MAX_PAGE_SIZE, int(limit)))
        offset = self._cursor_offset(cursor)

        selected = []
        for feature in await self._guard(self._store.query_features(map_id)):
            if status != "all" and feature["status"] != status:
                continue
            if phase_id and feature["phase_id"] != phase_id:
                continue
            if wanted_category and feature["category"] != wanted_category:
                continue
            if kind and feature["kind"] != kind:
                continue
            if since_version is not None and max(feature["version_start"], feature.get("retracted_version") or 0) <= since_version:
                continue
            if box and not self._intersects(feature["geometry"], box):
                continue
            selected.append(feature)
        selected.sort(key=lambda feature: (feature["created_version"], feature["id"]))
        page = selected[offset:offset + page_size]
        phases_by_id = {phase["id"]: phase for phase in map_doc.get("phases", [])}
        return {
            "items": [self._public_feature(feature, phases_by_id) for feature in page],
            "next_cursor": str(offset + page_size) if offset + page_size < len(selected) else None,
            "total": len(selected),
            "version": map_doc["version"],
        }

    @staticmethod
    def _as_of(feature: Dict[str, Any], revision: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if revision is None:
            return feature
        restored = dict(feature)
        for name in (*validation.CONTENT_FIELDS, "revision", "last_phase_id", "updated_by", "updated_at"):
            restored[name] = revision.get(name)
        restored["version_start"] = revision["valid_from_version"]
        return restored

    def _render_entry(self, feature: Dict[str, Any], phase: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """One feature in the marker, path and area shapes the chat's inline map renderers already draw."""
        style = feature.get("style") or {}
        color = style.get("color") or phase.get("color") or PHASE_COLORS[0]
        entry: Dict[str, Any] = {
            "id": feature["id"],
            "feature_id": feature["id"],
            "label": feature["label"],
            "description": feature.get("description") or "",
            "category": feature.get("category"),
            "phase_id": feature["phase_id"],
            "phase_name": phase.get("name", ""),
            "observed_at": feature.get("observed_at"),
            "source": feature.get("source"),
            "added_by": _who(feature.get("created_by")),
            "created_version": feature["created_version"],
            "updated_version": feature["version_start"],
        }
        if feature.get("fields"):
            entry["fields"] = feature["fields"]
        geometry = feature["geometry"]
        if feature["kind"] == "point":
            longitude, latitude = geometry["coordinates"]
            entry.update({"latitude": latitude, "longitude": longitude, "color": color, "icon_name": ""})
            media = feature.get("media") or {}
            if media.get("image_url"):
                entry["image_url"] = media["image_url"]
                if media.get("caption"):
                    entry["image_caption"] = media["caption"]
            return "markers", entry
        if feature["kind"] == "path":
            entry.update({
                "coordinates": geometry["coordinates"],
                "stroke_color": color,
                "line_width": style.get("line_width") or DEFAULT_LINE_WIDTH,
            })
            return "paths", entry
        entry.update({
            "coordinates": geometry["coordinates"][0],
            "stroke_color": color,
            "fill_color": style.get("fill_color") or _translucent(color),
        })
        return "areas", entry

    @staticmethod
    def _view(markers: List[Dict[str, Any]], paths: List[Dict[str, Any]], areas: List[Dict[str, Any]]) -> Dict[str, Any]:
        points: List[Tuple[float, float]] = [(marker["longitude"], marker["latitude"]) for marker in markers]
        for shape in [*paths, *areas]:
            points.extend((point[0], point[1]) for point in shape["coordinates"])
        if not points:
            return {"center": [0.0, 20.0], "zoom": 2, "max_zoom": 15, "fit_to_features": False}
        center = [round(sum(point[0] for point in points) / len(points), 6), round(sum(point[1] for point in points) / len(points), 6)]
        zoom = 14 if len(markers) == 1 and not paths and not areas else 10
        return {"center": center, "zoom": zoom, "max_zoom": 15, "fit_to_features": True}

    @staticmethod
    def _summary_text(markers: Sequence[Any], paths: Sequence[Any], areas: Sequence[Any], phase_count: int, target: int, current: int) -> str:
        parts = [
            _plural(len(items), noun)
            for items, noun in ((markers, "place"), (paths, "route"), (areas, "area"))
            if items
        ]
        if not parts:
            text = "No features yet"
        elif len(parts) == 1:
            text = parts[0]
        else:
            text = f"{', '.join(parts[:-1])} and {parts[-1]}"
        text = f"{text} in {_plural(phase_count, 'phase')}"
        if target != current:
            text = f"{text}, as of version {target}"
        return f"{text}."

    async def snapshot(
        self, actor: Actor, map_id: str, *, as_of_version: Optional[int] = None, phase_ids: Iterable[str] = ()
    ) -> Dict[str, Any]:
        """The map as it stood at a version, in the shape today's inline map renderers draw."""
        map_doc, _ = await self._load(actor, map_id)
        current_version = int(map_doc["version"])
        target = current_version if as_of_version is None else int(as_of_version)
        if not 1 <= target <= current_version:
            raise invalid(f"as_of_version must be between 1 and {current_version}.")
        wanted = {phase_id for phase_id in phase_ids if phase_id}
        for phase_id in wanted:
            if not validation.PHASE_ID_PATTERN.fullmatch(phase_id):
                raise invalid("phases must be phase IDs such as P1,P2.")

        features = await self._guard(self._store.query_features(map_id))
        visible = [
            feature for feature in features
            if feature["created_version"] <= target
            and (feature.get("retracted_version") is None or feature["retracted_version"] > target)
        ]
        stale_ids = [feature["id"] for feature in visible if feature["version_start"] > target]
        if stale_ids:
            revisions = await self._guard(self._store.query_feature_revisions(map_id, stale_ids, target))
            by_feature = {revision["feature_id"]: revision for revision in revisions}
            visible = [self._as_of(feature, by_feature.get(feature["id"])) for feature in visible]
        if wanted:
            visible = [feature for feature in visible if feature["phase_id"] in wanted]
        visible.sort(key=lambda feature: (feature["created_version"], feature["id"]))

        phases = [phase for phase in map_doc.get("phases", []) if phase["started_version"] <= target]
        phases_by_id = {phase["id"]: phase for phase in phases}
        shapes: Dict[str, List[Dict[str, Any]]] = {"markers": [], "paths": [], "areas": []}
        phase_counts: Dict[str, int] = {}
        for feature in visible:
            bucket, entry = self._render_entry(feature, phases_by_id.get(feature["phase_id"]) or {})
            shapes[bucket].append(entry)
            phase_counts[feature["phase_id"]] = phase_counts.get(feature["phase_id"], 0) + 1

        public_phases = []
        for phase in phases:
            public = self._public_phase(phase)
            closed = phase.get("closed_version") is not None and phase["closed_version"] <= target
            public["status"] = "closed" if closed else "open"
            public["feature_count"] = phase_counts.get(phase["id"], 0)
            public_phases.append(public)

        return {
            "map_id": map_id,
            "title": map_doc["title"],
            "summary": self._summary_text(
                shapes["markers"], shapes["paths"], shapes["areas"], len(phases), target, current_version,
            ),
            "map_provider": "azure_maps",
            "map_library": "openlayers",
            "tileset_id": map_doc["basemap"],
            "tile_attribution": TILE_ATTRIBUTION,
            "background_color": BACKGROUND_COLOR,
            "view": self._view(shapes["markers"], shapes["paths"], shapes["areas"]),
            "markers": shapes["markers"],
            "paths": shapes["paths"],
            "areas": shapes["areas"],
            "phases": public_phases,
            "version": current_version,
            "as_of_version": target,
        }

    async def list_changes(self, actor: Actor, map_id: str, *, since_version: int = 0, limit: int = 100) -> Dict[str, Any]:
        map_doc, _ = await self._load(actor, map_id)
        since = max(0, int(since_version))
        page_size = max(1, min(MAX_CHANGES_PAGE, int(limit)))
        changes = await self._guard(self._store.query_changes(map_id, since, page_size + 1))
        more = len(changes) > page_size
        changes = changes[:page_size]
        return {
            "items": [self._public_change(change) for change in changes],
            "version": map_doc["version"],
            "next_since_version": changes[-1]["version"] if more else None,
        }

    async def current_version(self, actor: Actor, map_id: str) -> int:
        map_doc, _ = await self._load(actor, map_id)
        return int(map_doc["version"])
