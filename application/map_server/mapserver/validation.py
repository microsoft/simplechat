# validation.py
"""Turns what a caller sends into the map's stored shapes, enforcing limits and safe links."""

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .errors import invalid, not_found

TITLE_MAX = 160
MAP_DESCRIPTION_MAX = 1000
PHASE_NAME_MAX = 80
PHASE_DESCRIPTION_MAX = 500
LABEL_MAX = 160
DESCRIPTION_MAX = 1000
CATEGORY_MAX = 40
FIELD_LIMIT = 12
FIELD_LABEL_MAX = 60
FIELD_VALUE_MAX = 300
IMAGE_URL_MAX = 2048
CAPTION_MAX = 200
SOURCE_SYSTEM_MAX = 80
SOURCE_RECORD_MAX = 120
REASON_MAX = 500
OBSERVED_AT_MAX = 64
MAX_VERTICES = 2000
MIN_LINE_WIDTH = 1
MAX_LINE_WIDTH = 12
DEFAULT_CATEGORY = "general"
FEATURE_KINDS = ("point", "path", "area")
GEOMETRY_KINDS = {"Point": "point", "LineString": "path", "Polygon": "area"}
GEOMETRY_KEYS = ("geometry", "latitude", "longitude", "lat", "lon", "lng", "coordinates")
CONTENT_FIELDS = ("geometry", "label", "category", "description", "observed_at", "source", "media", "fields", "style", "dup_key")

UNSAFE_URL_CHARACTERS = re.compile(r"[\s\"'<>\\]")
CATEGORY_UNSAFE = re.compile(r"[^a-z0-9_-]+")
COLOR_PATTERN = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
    r"|^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$"
)
TILESET_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAP_ID_PATTERN = re.compile(r"^map-[0-9a-f]{20}$")
FEATURE_ID_PATTERN = re.compile(r"^F-\d{4,7}$")
PHASE_ID_PATTERN = re.compile(r"^P\d{1,3}$")
CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")


def normalize_text(value: Any, max_length: int, *, multiline: bool = False) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = str(value).strip() if multiline else " ".join(str(value).split())
    return text[:max_length]


def require_text(value: Any, max_length: int, message: str) -> str:
    text = normalize_text(value, max_length)
    if not text:
        raise invalid(message)
    return text


def require_map_id(map_id: str) -> str:
    if not MAP_ID_PATTERN.fullmatch(str(map_id or "")):
        raise not_found()
    return map_id


def require_feature_id(feature_id: str) -> str:
    if not FEATURE_ID_PATTERN.fullmatch(str(feature_id or "")):
        raise not_found("feature_not_found", "Feature not found.")
    return feature_id


def require_phase_id(phase_id: str) -> str:
    if not PHASE_ID_PATTERN.fullmatch(str(phase_id or "")):
        raise not_found("phase_not_found", "Phase not found.")
    return phase_id


def normalize_conversation_id(value: Any) -> str:
    conversation_id = str(value or "").strip()
    if conversation_id and not CONVERSATION_ID_PATTERN.fullmatch(conversation_id):
        raise invalid("conversation_id isn't valid.")
    return conversation_id


def normalize_tileset(value: Any) -> str:
    tileset = str(value or "").strip()
    if not TILESET_PATTERN.fullmatch(tileset):
        raise invalid("The basemap must be an Azure Maps tileset ID such as microsoft.base.road.")
    return tileset


def normalize_color(value: Any) -> str:
    color = str(value or "").strip()
    return color if color and COLOR_PATTERN.fullmatch(color) else ""


def normalize_category(value: Any) -> str:
    category = CATEGORY_UNSAFE.sub("_", str(value or "").strip().lower()).strip("_")[:CATEGORY_MAX]
    return category or DEFAULT_CATEGORY


def normalize_https_url(value: Any) -> str:
    """An https link the viewer can load, or an empty string."""
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > IMAGE_URL_MAX or UNSAFE_URL_CHARACTERS.search(candidate):
        return ""
    try:
        parsed = urlparse(candidate)
        host = parsed.hostname
    except ValueError:
        return ""
    if parsed.scheme.lower() != "https" or not host:
        return ""
    return candidate


def normalize_fields(raw_fields: Any) -> List[Dict[str, str]]:
    if isinstance(raw_fields, dict):
        pairs = list(raw_fields.items())
    elif isinstance(raw_fields, list):
        pairs = [(item.get("label") or item.get("name"), item.get("value")) for item in raw_fields if isinstance(item, dict)]
    else:
        return []

    fields: List[Dict[str, str]] = []
    for raw_label, raw_value in pairs:
        if isinstance(raw_value, bool):
            raw_value = "Yes" if raw_value else "No"
        if not isinstance(raw_value, (str, int, float)):
            continue
        label = normalize_text(raw_label, FIELD_LABEL_MAX)
        value = normalize_text(raw_value, FIELD_VALUE_MAX)
        if label and value:
            fields.append({"label": label, "value": value})
        if len(fields) == FIELD_LIMIT:
            break
    return fields


def normalize_observed_at(value: Any, where: str) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) > OBSERVED_AT_MAX:
        raise invalid(f"{where}.observed_at must be an ISO 8601 date and time.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise invalid(f"{where}.observed_at must be an ISO 8601 date and time.") from exc
    return parsed.isoformat(timespec="seconds")


def _finite(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise invalid(f"{where} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise invalid(f"{where} must be a number.") from exc
    if not math.isfinite(number):
        raise invalid(f"{where} must be a finite number.")
    return number


def _coordinate(point: Any, where: str) -> List[float]:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        raise invalid(f"{where} must be a [longitude, latitude] pair.")
    longitude = _finite(point[0], f"{where}[0]")
    latitude = _finite(point[1], f"{where}[1]")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise invalid(f"{where} is out of range: longitude must be -180 to 180 and latitude -90 to 90.")
    return [round(longitude, 6), round(latitude, 6)]


def _coordinate_list(coordinates: Any, where: str) -> List[List[float]]:
    if not isinstance(coordinates, (list, tuple)) or not coordinates:
        raise invalid(f"{where}.coordinates must be a list of [longitude, latitude] pairs.")
    first = coordinates[0]
    if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
        coordinates = first
    if len(coordinates) > MAX_VERTICES + 1:
        raise invalid(f"{where} has more than {MAX_VERTICES} points.")
    return [_coordinate(point, f"{where}.coordinates[{index}]") for index, point in enumerate(coordinates)]


def normalize_geometry(raw: Dict[str, Any], where: str) -> Tuple[str, Dict[str, Any]]:
    """The feature kind and its GeoJSON geometry, from GeoJSON, latitude and longitude, or coordinates."""
    kind = str(raw.get("kind") or "").strip().lower()
    if kind and kind not in FEATURE_KINDS:
        raise invalid(f"{where}.kind must be point, path or area.")

    geometry = raw.get("geometry")
    latitude = raw.get("latitude", raw.get("lat"))
    longitude = raw.get("longitude", raw.get("lon", raw.get("lng")))
    if isinstance(geometry, dict):
        geometry_kind = GEOMETRY_KINDS.get(str(geometry.get("type") or ""))
        if not geometry_kind:
            raise invalid(f"{where}.geometry.type must be Point, LineString or Polygon.")
        if kind and kind != geometry_kind:
            raise invalid(f"{where}.kind doesn't match its geometry.")
        kind, coordinates = geometry_kind, geometry.get("coordinates")
    elif latitude is not None or longitude is not None:
        if kind and kind != "point":
            raise invalid(f"{where} uses latitude and longitude, which only a point can have.")
        kind, coordinates = "point", [longitude, latitude]
    elif raw.get("coordinates") is not None:
        if kind not in ("path", "area"):
            raise invalid(f"{where} needs kind 'path' or 'area' to go with its coordinates.")
        coordinates = raw.get("coordinates")
    else:
        raise invalid(f"{where} needs a geometry, latitude and longitude, or coordinates.")

    if kind == "point":
        return "point", {"type": "Point", "coordinates": _coordinate(coordinates, f"{where}.coordinates")}
    points = _coordinate_list(coordinates, where)
    if kind == "path":
        if len(points) < 2:
            raise invalid(f"{where} needs at least two points.")
        return "path", {"type": "LineString", "coordinates": points}
    if points[0] != points[-1]:
        points.append(list(points[0]))
    if len({tuple(point) for point in points}) < 3:
        raise invalid(f"{where} needs at least three distinct points.")
    return "area", {"type": "Polygon", "coordinates": [points]}


def normalize_source(raw: Dict[str, Any]) -> Optional[Dict[str, str]]:
    raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    system = normalize_text(raw_source.get("system") or raw.get("source_system"), SOURCE_SYSTEM_MAX)
    record_id = normalize_text(raw_source.get("record_id") or raw.get("source_record_id"), SOURCE_RECORD_MAX)
    url = normalize_https_url(raw_source.get("url") or raw.get("source_url"))
    source = {key: value for key, value in (("system", system), ("record_id", record_id), ("url", url)) if value}
    return source or None


def normalize_media(raw: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], bool]:
    """The photo for a feature, and whether a photo link was left out because it wasn't a safe https link."""
    raw_media = raw.get("media") if isinstance(raw.get("media"), dict) else {}
    raw_url = raw_media.get("image_url") or raw.get("image_url")
    if not raw_url:
        return None, False
    image_url = normalize_https_url(raw_url)
    if not image_url:
        return None, True
    media = {"image_url": image_url}
    caption = normalize_text(raw_media.get("caption") or raw.get("image_caption"), CAPTION_MAX)
    if caption:
        media["caption"] = caption
    return media, False


def normalize_style(raw: Dict[str, Any], kind: str) -> Dict[str, Any]:
    raw_style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
    style: Dict[str, Any] = {}
    color = normalize_color(raw_style.get("color") or raw.get("color") or raw.get("stroke_color"))
    if color:
        style["color"] = color
    if kind == "path":
        raw_width = raw_style.get("line_width", raw.get("line_width"))
        if raw_width not in (None, "") and not isinstance(raw_width, bool):
            try:
                style["line_width"] = max(MIN_LINE_WIDTH, min(MAX_LINE_WIDTH, int(float(raw_width))))
            except (TypeError, ValueError):
                pass
    if kind == "area":
        fill = normalize_color(raw_style.get("fill_color") or raw.get("fill_color"))
        if fill:
            style["fill_color"] = fill
    return style


def duplicate_key(kind: str, source: Optional[Dict[str, str]]) -> Optional[str]:
    if not source or not source.get("record_id"):
        return None
    return f"{kind}|{source.get('system', '').lower()}|{source['record_id']}"


def normalize_feature(raw: Any, index: int, where: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    """A feature's stored content, and whether its photo link was left out."""
    where = where or f"features[{index}]"
    if not isinstance(raw, dict):
        raise invalid(f"{where} must be an object.")
    kind, geometry = normalize_geometry(raw, where)
    label = require_text(raw.get("label") or raw.get("title") or raw.get("name"), LABEL_MAX, f"{where} needs a label.")
    source = normalize_source(raw)
    media, image_dropped = normalize_media(raw)
    content = {
        "kind": kind,
        "geometry": geometry,
        "label": label,
        "category": normalize_category(raw.get("category")),
        "description": normalize_text(raw.get("description"), DESCRIPTION_MAX, multiline=True),
        "observed_at": normalize_observed_at(raw.get("observed_at"), where),
        "source": source,
        "media": media,
        "fields": normalize_fields(raw.get("fields")),
        "style": normalize_style(raw, kind),
        "dup_key": duplicate_key(kind, source),
    }
    return content, image_dropped


def feature_to_input(feature: Dict[str, Any]) -> Dict[str, Any]:
    """A stored feature in the shape normalize_feature accepts, so a change can be validated in full."""
    raw = {
        "kind": feature["kind"],
        "geometry": feature["geometry"],
        "label": feature.get("label"),
        "category": feature.get("category"),
        "description": feature.get("description"),
        "observed_at": feature.get("observed_at"),
        "source": feature.get("source") or {},
        "fields": feature.get("fields") or [],
        "style": feature.get("style") or {},
    }
    if feature.get("media"):
        raw["media"] = dict(feature["media"])
    return raw


def apply_changes(feature: Dict[str, Any], changes: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """A feature's content with the requested changes applied and validated."""
    if not isinstance(changes, dict) or not changes:
        raise invalid("changes must name at least one field to change.")
    if "kind" in changes and str(changes.get("kind") or "").strip().lower() != feature["kind"]:
        raise invalid("A feature can't change kind. Retract it and add a new one.")
    merged = feature_to_input(feature)
    if any(key in changes for key in GEOMETRY_KEYS):
        merged.pop("geometry", None)
    if "media" in changes and not changes.get("media"):
        merged.pop("media", None)
        changes = {key: value for key, value in changes.items() if key != "media"}
    if any(key in changes for key in ("image_url", "image_caption")):
        merged.pop("media", None)
    merged.update(changes)
    merged["kind"] = feature["kind"]
    return normalize_feature(merged, 0, where="changes")


def content_equal(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return all(left.get(name) == right.get(name) for name in CONTENT_FIELDS)


def parse_bbox(value: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 4:
        raise invalid("bbox must be min_longitude,min_latitude,max_longitude,max_latitude.")
    west, south, east, north = (_finite(part, "bbox") for part in parts)
    if west > east or south > north:
        raise invalid("bbox must be min_longitude,min_latitude,max_longitude,max_latitude.")
    return west, south, east, north


def feature_points(geometry: Dict[str, Any]) -> Sequence[Sequence[float]]:
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        return [coordinates]
    if geometry.get("type") == "Polygon":
        return coordinates[0] if coordinates else []
    return coordinates
