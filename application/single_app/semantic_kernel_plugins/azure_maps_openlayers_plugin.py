# azure_maps_openlayers_plugin.py
"""Semantic Kernel plugin for inline Azure Maps visualizations rendered with OpenLayers."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_azure_maps import (
    AZURE_MAPS_DEFAULT_TILESET_ID,
    AZURE_MAPS_DEFAULT_LANGUAGE,
    AZURE_MAPS_DEFAULT_VIEW,
    AZURE_MAPS_PLUGIN_DISPLAY_NAME,
    AZURE_MAPS_PLUGIN_TYPE,
    AZURE_MAPS_RENDER_TYPE,
    AZURE_MAPS_TILE_ATTRIBUTION,
    build_tile_proxy_url_template,
    create_tile_proxy_token,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class AzureMapsOpenLayersPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}

    @property
    def display_name(self) -> str:
        return AZURE_MAPS_PLUGIN_DISPLAY_NAME

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", AZURE_MAPS_PLUGIN_TYPE),
            "type": AZURE_MAPS_PLUGIN_TYPE,
            "description": (
                "Prepare structured Azure Maps visualizations that the chat UI renders inline with OpenLayers. "
                "Use this when you already know the locations or polygon coordinates to show on an interactive map."
            ),
            "methods": [
                {
                    "name": "create_map_visualization",
                    "description": "Create an interactive Azure Maps visualization for chat. Supply location markers plus optional path and polygon overlays as JSON using longitude/latitude coordinates.",
                    "parameters": [
                        {
                            "name": "title",
                            "type": "str",
                            "description": "Short title displayed above the map card.",
                            "required": True,
                        },
                        {
                            "name": "summary",
                            "type": "str",
                            "description": "Optional one or two sentence summary shown above the map.",
                            "required": False,
                        },
                        {
                            "name": "locations_json",
                            "type": "str",
                            "description": "JSON array of point objects. Each item should include longitude and latitude, plus optional label, description, color, and icon_name.",
                            "required": False,
                        },
                        {
                            "name": "areas_json",
                            "type": "str",
                            "description": "JSON array of polygon area objects. Each item should include coordinates as longitude/latitude pairs, plus optional label, description, stroke_color, and fill_color.",
                            "required": False,
                        },
                        {
                            "name": "paths_json",
                            "type": "str",
                            "description": "JSON array of path objects. Each item should include ordered coordinates as longitude/latitude pairs, plus optional label, description, stroke_color, and line_width.",
                            "required": False,
                        },
                        {
                            "name": "view_json",
                            "type": "str",
                            "description": "Optional JSON object with preferred center, zoom, max_zoom, and fit_to_features settings.",
                            "required": False,
                        },
                        {
                            "name": "tileset_id",
                            "type": "str",
                            "description": "Optional Azure Maps raster tileset ID such as microsoft.base.road or microsoft.imagery.",
                            "required": False,
                        },
                    ],
                    "returns": {
                        "type": "dict",
                        "description": "Structured visualization payload with a secure tile proxy URL template for inline chat rendering.",
                    },
                }
            ],
        }

    def _parse_json(self, raw_value: Any, field_name: str, expected_type: type, default_value: Any) -> Any:
        if raw_value in (None, ""):
            return default_value

        if isinstance(raw_value, expected_type):
            return raw_value

        try:
            parsed_value = json.loads(str(raw_value))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON.") from exc

        if not isinstance(parsed_value, expected_type):
            raise ValueError(f"{field_name} must decode to {expected_type.__name__}.")

        return parsed_value

    def _coerce_float(self, value: Any, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid number.") from exc

    def _normalize_label(self, raw_label: Any, fallback_label: str) -> str:
        normalized_label = str(raw_label or "").strip()
        return normalized_label or fallback_label

    def _normalize_marker(self, marker: Dict[str, Any], index: int) -> Dict[str, Any]:
        latitude = marker.get("latitude", marker.get("lat"))
        longitude = marker.get("longitude", marker.get("lon", marker.get("lng")))
        if latitude is None or longitude is None:
            raise ValueError(f"locations_json[{index}] must include latitude and longitude.")

        return {
            "id": str(marker.get("id") or f"marker-{index + 1}"),
            "label": self._normalize_label(
                marker.get("label") or marker.get("title") or marker.get("name"),
                f"Location {index + 1}",
            ),
            "description": str(
                marker.get("description") or marker.get("popup") or marker.get("details") or ""
            ).strip(),
            "latitude": self._coerce_float(latitude, f"locations_json[{index}].latitude"),
            "longitude": self._coerce_float(longitude, f"locations_json[{index}].longitude"),
            "color": str(marker.get("color") or "#0d6efd").strip() or "#0d6efd",
            "icon_name": str(marker.get("icon_name") or marker.get("icon") or "").strip(),
        }

    def _normalize_area_ring(self, coordinates: Any, index: int) -> List[List[float]]:
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError(f"areas_json[{index}].coordinates must be a JSON array of longitude/latitude pairs.")

        first_item = coordinates[0]
        if isinstance(first_item, list) and first_item and isinstance(first_item[0], list):
            coordinates = first_item

        normalized_ring: List[List[float]] = []
        for point_index, point in enumerate(coordinates):
            if not isinstance(point, Sequence) or len(point) < 2:
                raise ValueError(
                    f"areas_json[{index}].coordinates[{point_index}] must contain longitude and latitude."
                )
            normalized_ring.append([
                self._coerce_float(point[0], f"areas_json[{index}].coordinates[{point_index}].longitude"),
                self._coerce_float(point[1], f"areas_json[{index}].coordinates[{point_index}].latitude"),
            ])

        if len(normalized_ring) < 3:
            raise ValueError(f"areas_json[{index}] must contain at least three coordinate pairs.")

        if normalized_ring[0] != normalized_ring[-1]:
            normalized_ring.append(list(normalized_ring[0]))

        return normalized_ring

    def _normalize_area(self, area: Dict[str, Any], index: int) -> Dict[str, Any]:
        return {
            "id": str(area.get("id") or f"area-{index + 1}"),
            "label": self._normalize_label(
                area.get("label") or area.get("title") or area.get("name"),
                f"Area {index + 1}",
            ),
            "description": str(
                area.get("description") or area.get("popup") or area.get("details") or ""
            ).strip(),
            "coordinates": self._normalize_area_ring(area.get("coordinates"), index),
            "stroke_color": str(area.get("stroke_color") or area.get("strokeColor") or "#b02a37").strip() or "#b02a37",
            "fill_color": str(area.get("fill_color") or area.get("fillColor") or "rgba(176, 42, 55, 0.20)").strip() or "rgba(176, 42, 55, 0.20)",
        }

    def _normalize_path_coordinates(self, coordinates: Any, index: int) -> List[List[float]]:
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError(f"paths_json[{index}].coordinates must be a JSON array of longitude/latitude pairs.")

        if isinstance(coordinates[0], list) and coordinates[0] and isinstance(coordinates[0][0], list):
            coordinates = coordinates[0]

        normalized_path: List[List[float]] = []
        for point_index, point in enumerate(coordinates):
            if not isinstance(point, Sequence) or len(point) < 2:
                raise ValueError(
                    f"paths_json[{index}].coordinates[{point_index}] must contain longitude and latitude."
                )
            normalized_path.append([
                self._coerce_float(point[0], f"paths_json[{index}].coordinates[{point_index}].longitude"),
                self._coerce_float(point[1], f"paths_json[{index}].coordinates[{point_index}].latitude"),
            ])

        if len(normalized_path) < 2:
            raise ValueError(f"paths_json[{index}] must contain at least two coordinate pairs.")

        return normalized_path

    def _normalize_path(self, path: Dict[str, Any], index: int) -> Dict[str, Any]:
        raw_line_width = path.get("line_width", path.get("lineWidth", path.get("width", 4)))
        line_width = int(self._coerce_float(raw_line_width, f"paths_json[{index}].line_width"))
        return {
            "id": str(path.get("id") or f"path-{index + 1}"),
            "label": self._normalize_label(
                path.get("label") or path.get("title") or path.get("name"),
                f"Path {index + 1}",
            ),
            "description": str(
                path.get("description") or path.get("popup") or path.get("details") or ""
            ).strip(),
            "coordinates": self._normalize_path_coordinates(path.get("coordinates"), index),
            "stroke_color": str(path.get("stroke_color") or path.get("strokeColor") or "#0b5ed7").strip() or "#0b5ed7",
            "line_width": max(1, min(12, line_width)),
        }

    def _collect_reference_points(
        self,
        markers: List[Dict[str, Any]],
        areas: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
    ) -> List[Tuple[float, float]]:
        points = [
            (marker["longitude"], marker["latitude"])
            for marker in markers
        ]

        for area in areas:
            for longitude, latitude in area.get("coordinates", []):
                points.append((float(longitude), float(latitude)))

        for path in paths:
            for longitude, latitude in path.get("coordinates", []):
                points.append((float(longitude), float(latitude)))

        return points

    def _normalize_view(
        self,
        raw_view: Dict[str, Any],
        markers: List[Dict[str, Any]],
        areas: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        reference_points = self._collect_reference_points(markers, areas, paths)
        provided_center = raw_view.get("center")

        if isinstance(provided_center, Sequence) and len(provided_center) >= 2:
            center = [
                self._coerce_float(provided_center[0], "view_json.center[0]"),
                self._coerce_float(provided_center[1], "view_json.center[1]"),
            ]
        elif reference_points:
            avg_longitude = sum(point[0] for point in reference_points) / len(reference_points)
            avg_latitude = sum(point[1] for point in reference_points) / len(reference_points)
            center = [round(avg_longitude, 6), round(avg_latitude, 6)]
        else:
            center = [0.0, 20.0]

        raw_zoom = raw_view.get("zoom")
        if raw_zoom in (None, ""):
            zoom = 14 if len(markers) == 1 and not areas and not paths else 10
        else:
            zoom = int(self._coerce_float(raw_zoom, "view_json.zoom"))

        raw_max_zoom = raw_view.get("max_zoom", raw_view.get("maxZoom"))
        if raw_max_zoom in (None, ""):
            max_zoom = 15
        else:
            max_zoom = int(self._coerce_float(raw_max_zoom, "view_json.max_zoom"))

        fit_to_features = raw_view.get("fit_to_features", raw_view.get("fitToFeatures", True))

        return {
            "center": center,
            "zoom": max(1, min(22, zoom)),
            "max_zoom": max(1, min(22, max_zoom)),
            "fit_to_features": bool(fit_to_features),
        }

    def _normalize_tileset_id(self, tileset_id: str) -> str:
        normalized_tileset_id = str(tileset_id or AZURE_MAPS_DEFAULT_TILESET_ID).strip()
        if not normalized_tileset_id:
            return AZURE_MAPS_DEFAULT_TILESET_ID
        if not re.fullmatch(r"[A-Za-z0-9._-]+", normalized_tileset_id):
            raise ValueError("tileset_id contains unsupported characters.")
        return normalized_tileset_id

    @plugin_function_logger("AzureMapsOpenLayersPlugin")
    @kernel_function(
        description=(
            "Create an inline Azure Maps visualization for chat using OpenLayers. "
            "Provide locations_json as a JSON array with longitude and latitude for each point, "
            "and optionally provide polygon areas_json or ordered paths_json using longitude/latitude coordinate pairs."
        )
    )
    def create_map_visualization(
        self,
        title: str,
        summary: str = "",
        locations_json: str = "[]",
        areas_json: str = "[]",
        paths_json: str = "[]",
        view_json: str = "{}",
        tileset_id: str = AZURE_MAPS_DEFAULT_TILESET_ID,
    ) -> dict:
        try:
            azure_maps_key = str((self.manifest.get("auth") or {}).get("key") or "").strip()
            if not azure_maps_key:
                raise ValueError("This action is missing its Azure Maps subscription key.")

            raw_locations = self._parse_json(locations_json, "locations_json", list, [])
            raw_areas = self._parse_json(areas_json, "areas_json", list, [])
            raw_paths = self._parse_json(paths_json, "paths_json", list, [])
            raw_view = self._parse_json(view_json, "view_json", dict, {})

            markers = [self._normalize_marker(marker, index) for index, marker in enumerate(raw_locations)]
            areas = [self._normalize_area(area, index) for index, area in enumerate(raw_areas)]
            paths = [self._normalize_path(path, index) for index, path in enumerate(raw_paths)]
            if not markers and not areas and not paths:
                raise ValueError("Provide at least one marker in locations_json, one path in paths_json, or one polygon in areas_json.")

            normalized_title = str(title or "").strip() or "Interactive Map"
            normalized_summary = str(summary or "").strip()
            normalized_tileset_id = self._normalize_tileset_id(tileset_id)
            view = self._normalize_view(raw_view, markers, areas, paths)
            tile_proxy_token = create_tile_proxy_token(azure_maps_key)

            map_payload = {
                "title": normalized_title,
                "summary": normalized_summary,
                "map_provider": "azure_maps",
                "map_library": "openlayers",
                "tileset_id": normalized_tileset_id,
                "tile_url_template": build_tile_proxy_url_template(
                    tile_proxy_token,
                    tileset_id=normalized_tileset_id,
                    language=AZURE_MAPS_DEFAULT_LANGUAGE,
                    view=AZURE_MAPS_DEFAULT_VIEW,
                    tile_size=256,
                ),
                "tile_attribution": AZURE_MAPS_TILE_ATTRIBUTION,
                "view": view,
                "markers": markers,
                "paths": paths,
                "areas": areas,
                "source_action_name": str(self.manifest.get("name") or AZURE_MAPS_PLUGIN_TYPE),
            }

            marker_count = len(markers)
            path_count = len(paths)
            area_count = len(areas)
            feature_counts = []
            if marker_count:
                feature_counts.append(f"{marker_count} marker{'s' if marker_count != 1 else ''}")
            if path_count:
                feature_counts.append(f"{path_count} path{'s' if path_count != 1 else ''}")
            if area_count:
                feature_counts.append(f"{area_count} area{'s' if area_count != 1 else ''}")
            feature_summary = ', '.join(feature_counts) if feature_counts else '0 features'
            return {
                "success": True,
                "render_type": AZURE_MAPS_RENDER_TYPE,
                "summary": f"Prepared an interactive Azure Maps view with {feature_summary}.",
                "map_payload": map_payload,
            }
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_type": "validation",
            }
        except Exception as exc:
            log_event(
                f"[AzureMapsPlugin] Failed to build Azure Maps visualization: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return {
                "success": False,
                "error": "Failed to build Azure Maps visualization.",
                "error_type": "unexpected",
                "details": str(exc),
            }