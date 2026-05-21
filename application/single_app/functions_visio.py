# functions_visio.py
"""Helpers for parsing and previewing Visio VSDX documents."""

import io
import os
import re
import zipfile
from posixpath import dirname, normpath
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont


VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

DEFAULT_PREVIEW_MAX_EDGE_PX = 3200
PREVIEW_MARGIN_PX = 56


def parse_vsdx_pages(
    file_path: str,
    include_media: bool = False,
    include_master_shapes: bool = False,
) -> List[Dict[str, Any]]:
    """Parse a VSDX file into page-level structured content."""
    with zipfile.ZipFile(file_path) as archive:
        master_catalog = _parse_master_catalog(archive)
        page_entries = _parse_page_catalog(archive)
        pages = []

        for page_number, page_entry in enumerate(page_entries, start=1):
            page_part = page_entry.get("part_name")
            if not page_part:
                continue

            try:
                page_root = _parse_xml_part(archive, page_part)
            except KeyError:
                continue

            page_rels = _parse_relationships(archive, _relationship_part_for(page_part))
            shapes = _parse_shapes(
                page_root,
                master_catalog,
                archive=archive,
                page_part=page_part,
                page_rels=page_rels,
                include_media=include_media,
                include_master_shapes=include_master_shapes,
            )
            connections = _parse_connections(page_root)
            width = page_entry.get("width") or _infer_page_extent(shapes, "x", "width")
            height = page_entry.get("height") or _infer_page_extent(shapes, "y", "height")

            pages.append({
                "page_number": page_number,
                "page_id": page_entry.get("id") or str(page_number),
                "name": page_entry.get("name") or f"Page {page_number}",
                "part_name": page_part,
                "width": width or 11.0,
                "height": height or 8.5,
                "shapes": shapes,
                "connections": connections,
            })

    return pages


def build_visio_page_markdown(original_filename: str, page: Dict[str, Any]) -> str:
    """Render a parsed Visio page as Markdown for indexing."""
    page_name = str(page.get("name") or f"Page {page.get('page_number') or ''}").strip()
    page_number = page.get("page_number") or 1
    shapes = page.get("shapes") or []
    connections = page.get("connections") or []
    text_shapes = [shape for shape in shapes if shape.get("text")]
    notable_shapes = [shape for shape in shapes if _is_notable_shape(shape)]
    connection_summaries = _summarize_connections(connections, shapes)

    lines = [
        f"# Visio page {page_number}: {page_name}",
        "",
        f"Source file: {original_filename}",
        f"Page dimensions: {_format_number(page.get('width'))} x {_format_number(page.get('height'))} inches",
        f"Shape count: {len(shapes)}",
        f"Text-bearing shape count: {len(text_shapes)}",
        f"Connection count: {len(connections)}",
        "",
    ]

    if text_shapes:
        lines.extend(["## Visible text", ""])
        for shape in text_shapes:
            lines.append(f"- {shape.get('text')}")
        lines.append("")

    if notable_shapes:
        lines.extend(["## Shapes", ""])
        for shape in notable_shapes:
            shape_label = _shape_label(shape)
            details = [
                f"id={shape.get('id')}",
                f"name={shape.get('name') or 'unnamed'}",
            ]
            if shape.get("master_name"):
                details.append(f"master={shape.get('master_name')}")
            if shape.get("x") is not None and shape.get("y") is not None:
                details.append(
                    "position="
                    f"({_format_number(shape.get('x'))}, {_format_number(shape.get('y'))})"
                )
            if shape.get("width") is not None and shape.get("height") is not None:
                details.append(
                    "size="
                    f"{_format_number(shape.get('width'))} x {_format_number(shape.get('height'))}"
                )
            lines.append(f"- {shape_label} ({'; '.join(details)})")
            for key, value in (shape.get("shape_data") or {}).items():
                lines.append(f"  - {key}: {value}")
        lines.append("")

    if connection_summaries:
        lines.extend(["## Connections", ""])
        for summary in connection_summaries:
            lines.append(f"- {summary}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_vsdx_page_preview(
    file_path: str,
    page_number: int,
    max_edge_px: int = DEFAULT_PREVIEW_MAX_EDGE_PX,
) -> bytes:
    """Render a parsed Visio page to a structural PNG preview."""
    normalized_page_number = max(1, int(page_number or 1))
    pages = parse_vsdx_pages(file_path, include_media=True, include_master_shapes=True)
    if not pages:
        raise ValueError("No Visio pages were found in the document")

    if normalized_page_number > len(pages):
        raise ValueError("Requested Visio page is out of range")

    page = pages[normalized_page_number - 1]
    return _render_page_to_png(page, max_edge_px=max_edge_px)


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _parse_xml_part(archive: zipfile.ZipFile, part_name: str) -> ElementTree.Element:
    with archive.open(part_name) as stream:
        return ElementTree.fromstring(stream.read())


def _parse_relationships(archive: zipfile.ZipFile, part_name: str) -> Dict[str, str]:
    try:
        root = _parse_xml_part(archive, part_name)
    except KeyError:
        return {}

    relationships = {}
    for rel in root.findall(_q(PACKAGE_REL_NS, "Relationship")):
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def _relationship_part_for(part_name: str) -> str:
    part_directory = dirname(part_name)
    part_basename = part_name.rsplit("/", 1)[-1]
    return f"{part_directory}/_rels/{part_basename}.rels"


def _resolve_part_path(source_part: str, target: str) -> str:
    normalized_target = str(target or "").strip()
    if not normalized_target:
        return ""
    if normalized_target.startswith("/"):
        return normalized_target.lstrip("/")
    return normpath(f"{dirname(source_part)}/{normalized_target}")


def _parse_page_catalog(archive: zipfile.ZipFile) -> List[Dict[str, Any]]:
    pages_part = "visio/pages/pages.xml"
    try:
        root = _parse_xml_part(archive, pages_part)
    except KeyError:
        return _fallback_page_catalog(archive)

    rels = _parse_relationships(archive, "visio/pages/_rels/pages.xml.rels")
    page_entries = []
    for page_elem in root.findall(_q(VISIO_NS, "Page")):
        rel_elem = page_elem.find(_q(VISIO_NS, "Rel"))
        rel_id = rel_elem.get(_q(OFFICE_REL_NS, "id")) if rel_elem is not None else ""
        target = rels.get(rel_id, "")
        page_entries.append({
            "id": page_elem.get("ID"),
            "name": page_elem.get("Name") or page_elem.get("NameU"),
            "part_name": _resolve_part_path(pages_part, target),
            "width": _get_cell_number(page_elem, "PageWidth"),
            "height": _get_cell_number(page_elem, "PageHeight"),
        })

    return [entry for entry in page_entries if entry.get("part_name")] or _fallback_page_catalog(archive)


def _fallback_page_catalog(archive: zipfile.ZipFile) -> List[Dict[str, Any]]:
    page_parts = sorted(
        name for name in archive.namelist()
        if re.fullmatch(r"visio/pages/page\d+\.xml", name)
    )
    return [
        {
            "id": str(index),
            "name": f"Page {index}",
            "part_name": part_name,
            "width": None,
            "height": None,
        }
        for index, part_name in enumerate(page_parts, start=1)
    ]


def _parse_master_catalog(archive: zipfile.ZipFile) -> Dict[str, Dict[str, Any]]:
    try:
        root = _parse_xml_part(archive, "visio/masters/masters.xml")
    except KeyError:
        return {}

    rels = _parse_relationships(archive, "visio/masters/_rels/masters.xml.rels")
    masters = {}
    for master in root.findall(_q(VISIO_NS, "Master")):
        master_id = master.get("ID")
        master_name = master.get("Name") or master.get("NameU")
        rel_elem = master.find(_q(VISIO_NS, "Rel"))
        rel_id = rel_elem.get(_q(OFFICE_REL_NS, "id")) if rel_elem is not None else ""
        part_name = _resolve_part_path("visio/masters/masters.xml", rels.get(rel_id or "", ""))
        root_shape = None
        master_rels = {}
        if part_name:
            try:
                master_root = _parse_xml_part(archive, part_name)
                root_shape = master_root.find(f"{_q(VISIO_NS, 'Shapes')}/{_q(VISIO_NS, 'Shape')}")
                master_rels = _parse_relationships(archive, _relationship_part_for(part_name))
            except KeyError:
                root_shape = None
                master_rels = {}
        if master_id:
            masters[master_id] = {
                "name": master_name or "",
                "part_name": part_name,
                "rels": master_rels,
                "root_shape": root_shape,
            }
    return masters


def _parse_shapes(
    root: ElementTree.Element,
    master_catalog: Dict[str, Dict[str, Any]],
    archive: Optional[zipfile.ZipFile] = None,
    page_part: str = "",
    page_rels: Optional[Dict[str, str]] = None,
    include_media: bool = False,
    include_master_shapes: bool = False,
) -> List[Dict[str, Any]]:
    shapes = []
    shapes_container = root.find(_q(VISIO_NS, "Shapes"))
    if shapes_container is None:
        return shapes

    for shape_elem in shapes_container.findall(_q(VISIO_NS, "Shape")):
        _parse_shape_recursive(
            shape_elem,
            shapes,
            master_catalog,
            archive=archive,
            page_part=page_part,
            page_rels=page_rels or {},
            include_media=include_media,
            include_master_shapes=include_master_shapes,
            parent_left=0.0,
            parent_bottom=0.0,
            depth=0,
        )
    return shapes


def _parse_shape_recursive(
    shape_elem: ElementTree.Element,
    shapes: List[Dict[str, Any]],
    master_catalog: Dict[str, Dict[str, Any]],
    archive: Optional[zipfile.ZipFile],
    page_part: str,
    page_rels: Dict[str, str],
    include_media: bool,
    include_master_shapes: bool,
    parent_left: float,
    parent_bottom: float,
    depth: int,
) -> Dict[str, Any]:
    master_id = shape_elem.get("Master")
    master_definition = master_catalog.get(master_id or "", {})
    master_root_shape = master_definition.get("root_shape")
    local_x = _get_direct_cell_number(shape_elem, "PinX")
    local_y = _get_direct_cell_number(shape_elem, "PinY")
    width = _get_direct_cell_number(shape_elem, "Width") or _get_direct_cell_number(master_root_shape, "Width")
    height = _get_direct_cell_number(shape_elem, "Height") or _get_direct_cell_number(master_root_shape, "Height")
    loc_pin_x = _get_direct_cell_number(shape_elem, "LocPinX") or _get_direct_cell_number(master_root_shape, "LocPinX")
    loc_pin_y = _get_direct_cell_number(shape_elem, "LocPinY") or _get_direct_cell_number(master_root_shape, "LocPinY")

    abs_x = parent_left + local_x if local_x is not None else None
    abs_y = parent_bottom + local_y if local_y is not None else None
    effective_width = abs(width) if width is not None else None
    effective_height = abs(height) if height is not None else None
    if loc_pin_x is None and effective_width is not None:
        loc_pin_x = effective_width / 2.0
    if loc_pin_y is None and effective_height is not None:
        loc_pin_y = effective_height / 2.0

    left = abs_x - loc_pin_x if abs_x is not None and loc_pin_x is not None else None
    bottom = abs_y - loc_pin_y if abs_y is not None and loc_pin_y is not None else None

    begin_x = _get_direct_cell_number(shape_elem, "BeginX")
    begin_y = _get_direct_cell_number(shape_elem, "BeginY")
    end_x = _get_direct_cell_number(shape_elem, "EndX")
    end_y = _get_direct_cell_number(shape_elem, "EndY")
    if depth > 0:
        begin_x = parent_left + begin_x if begin_x is not None else None
        begin_y = parent_bottom + begin_y if begin_y is not None else None
        end_x = parent_left + end_x if end_x is not None else None
        end_y = parent_bottom + end_y if end_y is not None else None

    shape = {
        "id": shape_elem.get("ID") or "",
        "name": shape_elem.get("NameU") or shape_elem.get("Name") or "",
        "type": shape_elem.get("Type") or "",
        "master_id": master_id or "",
        "master_name": master_definition.get("name", ""),
        "text": _normalize_text(_get_shape_text(shape_elem)),
        "x": abs_x,
        "y": abs_y,
        "local_x": local_x,
        "local_y": local_y,
        "width": effective_width,
        "height": effective_height,
        "raw_width": width,
        "raw_height": height,
        "left": left,
        "bottom": bottom,
        "right": left + effective_width if left is not None and effective_width is not None else None,
        "top": bottom + effective_height if bottom is not None and effective_height is not None else None,
        "loc_pin_x": loc_pin_x,
        "loc_pin_y": loc_pin_y,
        "angle": _get_direct_cell_number(shape_elem, "Angle"),
        "begin_x": begin_x,
        "begin_y": begin_y,
        "end_x": end_x,
        "end_y": end_y,
        "txt_pin_x": _get_direct_cell_number(shape_elem, "TxtPinX"),
        "txt_pin_y": _get_direct_cell_number(shape_elem, "TxtPinY"),
        "txt_width": _get_direct_cell_number(shape_elem, "TxtWidth"),
        "txt_height": _get_direct_cell_number(shape_elem, "TxtHeight"),
        "txt_loc_pin_x": _get_direct_cell_number(shape_elem, "TxtLocPinX"),
        "txt_loc_pin_y": _get_direct_cell_number(shape_elem, "TxtLocPinY"),
        "fill_color": _get_direct_cell_value(shape_elem, "FillForegnd"),
        "line_color": _get_direct_cell_value(shape_elem, "LineColor"),
        "fill_pattern": _get_direct_cell_value(shape_elem, "FillPattern"),
        "line_pattern": _get_direct_cell_value(shape_elem, "LinePattern"),
        "line_weight": _get_direct_cell_number(shape_elem, "LineWeight"),
        "rounding": _get_direct_cell_number(shape_elem, "Rounding"),
        "text_color": _get_section_cell_value(shape_elem, "Character", "Color"),
        "horizontal_align": _get_section_cell_value(shape_elem, "Paragraph", "HorzAlign"),
        "geometry": _parse_geometry(shape_elem),
        "image_part": _get_foreign_image_part(shape_elem, page_part, page_rels),
        "image_bytes": _get_foreign_image_bytes(shape_elem, archive, page_part, page_rels, include_media),
        "shape_data": _parse_shape_data(shape_elem),
        "depth": depth,
        "geometry_scale_x": 1.0,
        "geometry_scale_y": 1.0,
    }
    shapes.append(shape)

    child_shapes = []
    child_container = shape_elem.find(_q(VISIO_NS, "Shapes"))
    child_parent_left = left if left is not None else parent_left
    child_parent_bottom = bottom if bottom is not None else parent_bottom
    if child_container is not None:
        for child_elem in child_container.findall(_q(VISIO_NS, "Shape")):
            child_shapes.append(_parse_shape_recursive(
                child_elem,
                shapes,
                master_catalog,
                archive=archive,
                page_part=page_part,
                page_rels=page_rels,
                include_media=include_media,
                include_master_shapes=include_master_shapes,
                parent_left=child_parent_left,
                parent_bottom=child_parent_bottom,
                depth=depth + 1,
            ))

    if include_master_shapes and master_root_shape is not None and _has_shape_bounds(shape):
        child_shapes.extend(_parse_master_instance_shapes(
            master_root_shape,
            instance_shape=shape,
            shapes=shapes,
            archive=archive,
            master_part=str(master_definition.get("part_name") or ""),
            master_rels=master_definition.get("rels") or {},
            include_media=include_media,
            depth=depth + 1,
        ))

    if (shape.get("width") is None or shape.get("height") is None) and child_shapes:
        _apply_child_bounds(shape, child_shapes)

    return shape


def _parse_master_instance_shapes(
    master_root_shape: ElementTree.Element,
    instance_shape: Dict[str, Any],
    shapes: List[Dict[str, Any]],
    archive: Optional[zipfile.ZipFile],
    master_part: str,
    master_rels: Dict[str, str],
    include_media: bool,
    depth: int,
) -> List[Dict[str, Any]]:
    child_container = master_root_shape.find(_q(VISIO_NS, "Shapes"))
    if child_container is None:
        return []

    master_width = _get_direct_cell_number(master_root_shape, "Width") or instance_shape.get("width") or 1.0
    master_height = _get_direct_cell_number(master_root_shape, "Height") or instance_shape.get("height") or 1.0
    instance_width = float(instance_shape.get("width") or master_width or 1.0)
    instance_height = float(instance_shape.get("height") or master_height or 1.0)
    scale_x = instance_width / float(master_width or instance_width or 1.0)
    scale_y = instance_height / float(master_height or instance_height or 1.0)
    parsed_children = []
    for child_elem in child_container.findall(_q(VISIO_NS, "Shape")):
        parsed_children.append(_parse_master_shape_recursive(
            child_elem,
            instance_shape=instance_shape,
            shapes=shapes,
            archive=archive,
            master_part=master_part,
            master_rels=master_rels,
            include_media=include_media,
            parent_left=float(instance_shape["left"]),
            parent_bottom=float(instance_shape["bottom"]),
            scale_x=scale_x,
            scale_y=scale_y,
            depth=depth,
        ))
    return parsed_children


def _parse_master_shape_recursive(
    shape_elem: ElementTree.Element,
    instance_shape: Dict[str, Any],
    shapes: List[Dict[str, Any]],
    archive: Optional[zipfile.ZipFile],
    master_part: str,
    master_rels: Dict[str, str],
    include_media: bool,
    parent_left: float,
    parent_bottom: float,
    scale_x: float,
    scale_y: float,
    depth: int,
) -> Dict[str, Any]:
    local_x = _scale_optional(_get_direct_cell_number(shape_elem, "PinX"), scale_x)
    local_y = _scale_optional(_get_direct_cell_number(shape_elem, "PinY"), scale_y)
    width = _scale_optional(_get_direct_cell_number(shape_elem, "Width"), scale_x)
    height = _scale_optional(_get_direct_cell_number(shape_elem, "Height"), scale_y)
    loc_pin_x = _scale_optional(_get_direct_cell_number(shape_elem, "LocPinX"), scale_x)
    loc_pin_y = _scale_optional(_get_direct_cell_number(shape_elem, "LocPinY"), scale_y)

    abs_x = parent_left + local_x if local_x is not None else None
    abs_y = parent_bottom + local_y if local_y is not None else None
    effective_width = abs(width) if width is not None else None
    effective_height = abs(height) if height is not None else None
    if loc_pin_x is None and effective_width is not None:
        loc_pin_x = effective_width / 2.0
    if loc_pin_y is None and effective_height is not None:
        loc_pin_y = effective_height / 2.0

    left = abs_x - loc_pin_x if abs_x is not None and loc_pin_x is not None else None
    bottom = abs_y - loc_pin_y if abs_y is not None and loc_pin_y is not None else None
    instance_fill = instance_shape.get("fill_color")
    shape = {
        "id": f"{instance_shape.get('id')}:master:{shape_elem.get('ID') or ''}",
        "name": shape_elem.get("NameU") or shape_elem.get("Name") or "",
        "type": shape_elem.get("Type") or "",
        "master_id": instance_shape.get("master_id") or "",
        "master_name": instance_shape.get("master_name") or "",
        "text": "",
        "x": abs_x,
        "y": abs_y,
        "local_x": local_x,
        "local_y": local_y,
        "width": effective_width,
        "height": effective_height,
        "raw_width": width,
        "raw_height": height,
        "left": left,
        "bottom": bottom,
        "right": left + effective_width if left is not None and effective_width is not None else None,
        "top": bottom + effective_height if bottom is not None and effective_height is not None else None,
        "loc_pin_x": loc_pin_x,
        "loc_pin_y": loc_pin_y,
        "angle": _get_direct_cell_number(shape_elem, "Angle"),
        "begin_x": None,
        "begin_y": None,
        "end_x": None,
        "end_y": None,
        "txt_pin_x": None,
        "txt_pin_y": None,
        "txt_width": None,
        "txt_height": None,
        "txt_loc_pin_x": None,
        "txt_loc_pin_y": None,
        "fill_color": _get_direct_cell_value(shape_elem, "FillForegnd") or instance_fill,
        "line_color": _get_direct_cell_value(shape_elem, "LineColor"),
        "fill_pattern": _get_direct_cell_value(shape_elem, "FillPattern"),
        "line_pattern": _get_direct_cell_value(shape_elem, "LinePattern"),
        "line_weight": _get_direct_cell_number(shape_elem, "LineWeight"),
        "rounding": _get_direct_cell_number(shape_elem, "Rounding"),
        "text_color": _get_section_cell_value(shape_elem, "Character", "Color"),
        "horizontal_align": _get_section_cell_value(shape_elem, "Paragraph", "HorzAlign"),
        "geometry": _parse_geometry(shape_elem),
        "image_part": _get_foreign_image_part(shape_elem, master_part, master_rels),
        "image_bytes": _get_foreign_image_bytes(shape_elem, archive, master_part, master_rels, include_media),
        "shape_data": {},
        "depth": depth,
        "from_master": True,
        "geometry_scale_x": scale_x,
        "geometry_scale_y": scale_y,
    }
    shapes.append(shape)

    child_shapes = []
    child_container = shape_elem.find(_q(VISIO_NS, "Shapes"))
    child_parent_left = left if left is not None else parent_left
    child_parent_bottom = bottom if bottom is not None else parent_bottom
    if child_container is not None:
        for child_elem in child_container.findall(_q(VISIO_NS, "Shape")):
            child_shapes.append(_parse_master_shape_recursive(
                child_elem,
                instance_shape=instance_shape,
                shapes=shapes,
                archive=archive,
                master_part=master_part,
                master_rels=master_rels,
                include_media=include_media,
                parent_left=child_parent_left,
                parent_bottom=child_parent_bottom,
                scale_x=scale_x,
                scale_y=scale_y,
                depth=depth + 1,
            ))

    if (shape.get("width") is None or shape.get("height") is None) and child_shapes:
        _apply_child_bounds(shape, child_shapes)

    return shape


def _scale_optional(value: Optional[float], scale: float) -> Optional[float]:
    return value * scale if value is not None else None


def _parse_connections(root: ElementTree.Element) -> List[Dict[str, str]]:
    connections = []
    for connect_elem in root.findall(f".//{_q(VISIO_NS, 'Connect')}"):
        connections.append({
            "from_sheet": connect_elem.get("FromSheet") or "",
            "from_cell": connect_elem.get("FromCell") or "",
            "to_sheet": connect_elem.get("ToSheet") or "",
            "to_cell": connect_elem.get("ToCell") or "",
        })
    return connections


def _get_shape_text(shape_elem: ElementTree.Element) -> str:
    text_elem = shape_elem.find(_q(VISIO_NS, "Text"))
    if text_elem is None:
        return ""
    return " ".join(text_elem.itertext())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _get_direct_cell_value(element: ElementTree.Element, cell_name: str) -> Optional[str]:
    if element is None:
        return None
    for cell in element.findall(_q(VISIO_NS, "Cell")):
        if cell.get("N") == cell_name:
            return cell.get("V") or cell.get("F")
    return None


def _get_direct_cell_number(element: ElementTree.Element, cell_name: str) -> Optional[float]:
    raw_value = _get_direct_cell_value(element, cell_name)
    if raw_value in (None, ""):
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _get_cell_value(element: ElementTree.Element, cell_name: str) -> Optional[str]:
    if element is None:
        return None
    for cell in element.findall(_q(VISIO_NS, "Cell")):
        if cell.get("N") == cell_name:
            return cell.get("V") or cell.get("F")
    for cell in element.findall(f".//{_q(VISIO_NS, 'Cell')}"):
        if cell.get("N") == cell_name:
            return cell.get("V") or cell.get("F")
    return None


def _get_section_cell_value(element: ElementTree.Element, section_name: str, cell_name: str) -> Optional[str]:
    if element is None:
        return None
    section = element.find(f"{_q(VISIO_NS, 'Section')}[@N='{section_name}']")
    if section is None:
        return None
    for row in section.findall(_q(VISIO_NS, "Row")):
        value = _get_direct_cell_value(row, cell_name)
        if value not in (None, ""):
            return value
    return None


def _get_cell_number(element: ElementTree.Element, cell_name: str) -> Optional[float]:
    raw_value = _get_cell_value(element, cell_name)
    if raw_value in (None, ""):
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _parse_shape_data(shape_elem: ElementTree.Element) -> Dict[str, str]:
    shape_data = {}
    for section in shape_elem.findall(_q(VISIO_NS, "Section")):
        if section.get("N") != "Prop":
            continue
        for row in section.findall(_q(VISIO_NS, "Row")):
            row_name = row.get("N") or row.get("IX") or "Property"
            label = _get_cell_value(row, "Label") or row_name
            value = _get_cell_value(row, "Value") or ""
            normalized_label = _normalize_text(label)
            normalized_value = _normalize_text(value)
            if normalized_label and normalized_value:
                shape_data[normalized_label] = normalized_value
    return shape_data


def _parse_geometry(shape_elem: ElementTree.Element) -> List[Dict[str, Any]]:
    geometry = []
    for section in shape_elem.findall(_q(VISIO_NS, "Section")):
        if section.get("N") != "Geometry":
            continue
        for row in section.findall(_q(VISIO_NS, "Row")):
            row_cells = {}
            for cell in row.findall(_q(VISIO_NS, "Cell")):
                name = cell.get("N")
                if name:
                    row_cells[name] = cell.get("V") or cell.get("F")
            geometry.append({
                "type": row.get("T") or row.get("N") or "",
                "index": row.get("IX") or "",
                "cells": row_cells,
            })
    return geometry


def _get_foreign_image_part(
    shape_elem: ElementTree.Element,
    page_part: str,
    page_rels: Dict[str, str],
) -> str:
    foreign_data = shape_elem.find(_q(VISIO_NS, "ForeignData"))
    if foreign_data is None:
        return ""
    rel_elem = foreign_data.find(_q(VISIO_NS, "Rel"))
    rel_id = rel_elem.get(_q(OFFICE_REL_NS, "id")) if rel_elem is not None else ""
    target = page_rels.get(rel_id or "", "")
    return _resolve_part_path(page_part, target) if target else ""


def _get_foreign_image_bytes(
    shape_elem: ElementTree.Element,
    archive: Optional[zipfile.ZipFile],
    page_part: str,
    page_rels: Dict[str, str],
    include_media: bool,
) -> Optional[bytes]:
    if not include_media or archive is None:
        return None
    image_part = _get_foreign_image_part(shape_elem, page_part, page_rels)
    if not image_part:
        return None
    try:
        return archive.read(image_part)
    except KeyError:
        return None


def _apply_child_bounds(shape: Dict[str, Any], child_shapes: List[Dict[str, Any]]) -> None:
    bounded_children = [
        child for child in child_shapes
        if child.get("left") is not None
        and child.get("bottom") is not None
        and child.get("right") is not None
        and child.get("top") is not None
    ]
    if not bounded_children:
        return

    left = min(float(child["left"]) for child in bounded_children)
    bottom = min(float(child["bottom"]) for child in bounded_children)
    right = max(float(child["right"]) for child in bounded_children)
    top = max(float(child["top"]) for child in bounded_children)

    shape["left"] = left
    shape["bottom"] = bottom
    shape["right"] = right
    shape["top"] = top
    shape["width"] = right - left
    shape["height"] = top - bottom
    shape["x"] = left + (shape["width"] / 2.0)
    shape["y"] = bottom + (shape["height"] / 2.0)


def _infer_page_extent(shapes: List[Dict[str, Any]], center_key: str, size_key: str) -> Optional[float]:
    extent = 0.0
    for shape in shapes:
        center = shape.get(center_key)
        size = shape.get(size_key) or 0.0
        if center is None:
            continue
        extent = max(extent, float(center) + (float(size) / 2.0))
    return extent or None


def _format_number(value: Any) -> str:
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "unknown"


def _shape_label(shape: Dict[str, Any]) -> str:
    return (
        str(shape.get("text") or "").strip()
        or str(shape.get("name") or "").strip()
        or str(shape.get("master_name") or "").strip()
        or f"Shape {shape.get('id')}"
    )


def _is_connector_shape(shape: Dict[str, Any]) -> bool:
    name = f"{shape.get('name') or ''} {shape.get('master_name') or ''}".lower()
    return "connector" in name or "dynamic connector" in name


def _is_notable_shape(shape: Dict[str, Any]) -> bool:
    if _is_connector_shape(shape):
        return False
    if shape.get("from_master") and not shape.get("text") and not shape.get("shape_data"):
        return False
    return bool(shape.get("text") or shape.get("shape_data") or shape.get("master_name"))


def _summarize_connections(connections: List[Dict[str, str]], shapes: List[Dict[str, Any]]) -> List[str]:
    shapes_by_id = {str(shape.get("id")): shape for shape in shapes if shape.get("id")}
    grouped: Dict[str, Dict[str, str]] = {}
    raw_summaries = []

    for connection in connections:
        connector_id = connection.get("from_sheet") or ""
        from_cell = connection.get("from_cell") or ""
        to_sheet = connection.get("to_sheet") or ""
        if connector_id and (from_cell.startswith("Begin") or from_cell.startswith("End")):
            grouped.setdefault(connector_id, {})["begin" if from_cell.startswith("Begin") else "end"] = to_sheet
        else:
            raw_summaries.append(
                f"{connector_id or 'Connection'} {from_cell or 'connects'} to shape {to_sheet}"
            )

    summaries = []
    for connector_id, endpoints in grouped.items():
        begin = endpoints.get("begin")
        end = endpoints.get("end")
        if begin and end:
            summaries.append(
                f"{_shape_label(shapes_by_id.get(begin, {'id': begin}))} -> "
                f"{_shape_label(shapes_by_id.get(end, {'id': end}))} "
                f"(connector {connector_id})"
            )
    summaries.extend(raw_summaries)
    return summaries


def _render_page_to_png(page: Dict[str, Any], max_edge_px: int) -> bytes:
    width_in = max(float(page.get("width") or 11.0), 1.0)
    height_in = max(float(page.get("height") or 8.5), 1.0)
    max_edge = max(800, int(max_edge_px or DEFAULT_PREVIEW_MAX_EDGE_PX))
    scale = max(25.0, (max_edge - (PREVIEW_MARGIN_PX * 2)) / max(width_in, height_in))
    image_width = int(width_in * scale) + (PREVIEW_MARGIN_PX * 2)
    image_height = int(height_in * scale) + (PREVIEW_MARGIN_PX * 2)
    render_factor = _preview_render_factor(image_width, image_height)
    render_scale = scale * render_factor
    render_margin = int(PREVIEW_MARGIN_PX * render_factor)
    render_width = int(image_width * render_factor)
    render_height = int(image_height * render_factor)
    render_page = dict(page)
    render_page["_preview_margin_px"] = render_margin

    image = Image.new("RGB", (render_width, render_height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(int(18 * render_factor))
    body_font = _load_font(int(13 * render_factor))
    small_font = _load_font(int(11 * render_factor))

    page_box = (
        render_margin,
        render_margin,
        render_width - render_margin,
        render_height - render_margin,
    )
    draw.rectangle(page_box, outline=(210, 215, 220), width=max(1, int(2 * render_factor)))
    draw.text(
        (render_margin, int(18 * render_factor)),
        f"Visio page {page.get('page_number')}: {page.get('name')}",
        fill=(20, 35, 50),
        font=title_font,
    )

    shapes = page.get("shapes") or []
    shapes_by_id = {str(shape.get("id")): shape for shape in shapes if shape.get("id")}
    _draw_connector_shape_lines(draw, render_page, shapes, render_scale)
    _draw_connection_lines(draw, render_page, shapes_by_id, render_scale)

    drawable_shapes = [shape for shape in shapes if _has_shape_bounds(shape) and not _is_connector_shape(shape)]
    for shape in sorted(drawable_shapes, key=lambda item: (-_shape_area(item), int(item.get("depth") or 0))):
        _draw_shape_geometry(image, draw, render_page, shape, render_scale)

    text_shapes = [shape for shape in shapes if shape.get("text") and shape.get("x") is not None and shape.get("y") is not None]
    if not text_shapes:
        _draw_text_only_fallback(draw, render_page, body_font)
    else:
        for shape in text_shapes:
            _draw_shape_text(draw, render_page, shape, render_scale, body_font, small_font)

    footer = f"{len(shapes)} shapes, {len(page.get('connections') or [])} connection records"
    draw.text((render_margin, render_height - int(34 * render_factor)), footer, fill=(90, 95, 105), font=small_font)

    if render_factor > 1.0:
        image = image.resize((image_width, image_height), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _preview_render_factor(image_width: int, image_height: int) -> float:
    max_dimension = max(image_width, image_height)
    if max_dimension <= 1800:
        return 2.0
    if max_dimension <= 3400:
        return 1.5
    return 1.0


def _preview_margin_px(page: Dict[str, Any]) -> int:
    return int(page.get("_preview_margin_px") or PREVIEW_MARGIN_PX)


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "DejaVuSans.ttf",
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            if os.path.isabs(candidate) and not os.path.exists(candidate):
                continue
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _shape_center_px(page: Dict[str, Any], shape: Dict[str, Any], scale: float) -> Optional[Tuple[float, float]]:
    if shape.get("x") is None or shape.get("y") is None:
        return None
    return _page_point_to_px(page, float(shape.get("x")), float(shape.get("y")), scale)


def _page_point_to_px(page: Dict[str, Any], x: float, y: float, scale: float) -> Tuple[float, float]:
    page_height = float(page.get("height") or 8.5)
    margin = _preview_margin_px(page)
    return margin + (x * scale), margin + ((page_height - y) * scale)


def _shape_bounds_px(page: Dict[str, Any], shape: Dict[str, Any], scale: float) -> Tuple[float, float, float, float]:
    if _has_shape_bounds(shape):
        page_height = float(page.get("height") or 8.5)
        left = float(shape.get("left"))
        right = float(shape.get("right"))
        bottom = float(shape.get("bottom"))
        top = float(shape.get("top"))
        margin = _preview_margin_px(page)
        x0 = margin + (left * scale)
        y0 = margin + ((page_height - top) * scale)
        x1 = margin + (right * scale)
        y1 = margin + ((page_height - bottom) * scale)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    margin = _preview_margin_px(page)
    center = _shape_center_px(page, shape, scale) or (margin, margin)
    width = max(float(shape.get("width") or 0.75) * scale, 96.0)
    height = max(float(shape.get("height") or 0.35) * scale, 38.0)
    x0 = center[0] - (width / 2.0)
    y0 = center[1] - (height / 2.0)
    x1 = center[0] + (width / 2.0)
    y1 = center[1] + (height / 2.0)
    return x0, y0, x1, y1


def _has_shape_bounds(shape: Dict[str, Any]) -> bool:
    return all(shape.get(key) is not None for key in ("left", "bottom", "right", "top"))


def _shape_area(shape: Dict[str, Any]) -> float:
    try:
        return float(shape.get("width") or 0.0) * float(shape.get("height") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parse_hex_color(raw_color: Any, default: Optional[Tuple[int, int, int]] = None) -> Optional[Tuple[int, int, int]]:
    value = str(raw_color or "").strip()
    if not value.startswith("#") or len(value) != 7:
        return default
    try:
        return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
    except ValueError:
        return default


def _is_ellipse_shape(shape: Dict[str, Any]) -> bool:
    if "circle" in str(shape.get("name") or "").lower():
        return True
    return any((row.get("type") or "").lower() == "ellipse" for row in shape.get("geometry") or [])


def _is_page_background(shape: Dict[str, Any]) -> bool:
    page_like = _shape_area(shape) > 80
    no_line = str(shape.get("line_pattern") or "") == "0"
    return page_like and no_line


def _should_draw_geometry(shape: Dict[str, Any]) -> bool:
    if _is_page_background(shape):
        return False
    if shape.get("type") == "Group" and not shape.get("geometry"):
        return False
    if shape.get("image_bytes"):
        return True
    if shape.get("geometry"):
        return True
    if shape.get("text") and _shape_area(shape) >= 1.0:
        return True
    return bool(shape.get("depth") and shape.get("width") and shape.get("height"))


def _is_dashed_container(shape: Dict[str, Any]) -> bool:
    return str(shape.get("line_pattern") or "") == "2" and _shape_area(shape) >= 1.0


def _draw_shape_geometry(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shape: Dict[str, Any],
    scale: float,
) -> None:
    if not _should_draw_geometry(shape):
        return

    bounds = _shape_bounds_px(page, shape, scale)
    if shape.get("image_bytes") and _draw_shape_image(image, shape, bounds):
        return

    if _is_dashed_container(shape):
        line_width = max(1, min(3, int((shape.get("line_weight") or 0.01) * scale)))
        _draw_dashed_rectangle(draw, bounds, _container_line_color(shape), line_width)
        return

    fill = _parse_hex_color(shape.get("fill_color"))
    line = _parse_hex_color(shape.get("line_color"))
    if shape.get("depth") and fill is None:
        fill = (0, 120, 212)
    elif fill is None and shape.get("text"):
        fill = (242, 247, 252)

    if str(shape.get("fill_pattern") or "") == "0":
        fill = None
    if str(shape.get("line_pattern") or "") == "0":
        line = None
    if line is None and not shape.get("depth"):
        line = (74, 116, 168)
    elif line is None and fill is None:
        line = (90, 130, 180)

    line_width = max(1, min(3, int((shape.get("line_weight") or 0.01) * scale))) if line else 1
    if _draw_geometry_rows(draw, page, shape, scale, fill, line, line_width):
        return
    if _is_ellipse_shape(shape):
        draw.ellipse(bounds, fill=fill, outline=line, width=line_width)
    elif _shape_area(shape) > 1.0:
        draw.rounded_rectangle(bounds, radius=4, fill=fill, outline=line, width=line_width)
    else:
        draw.rectangle(bounds, fill=fill, outline=line, width=line_width)


def _draw_geometry_rows(
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shape: Dict[str, Any],
    scale: float,
    fill: Optional[Tuple[int, int, int]],
    line: Optional[Tuple[int, int, int]],
    line_width: int,
) -> bool:
    geometry_rows = shape.get("geometry") or []
    if not geometry_rows or not _has_shape_bounds(shape):
        return False

    drew_geometry = False
    current_points = []
    subpaths = []
    for row in geometry_rows:
        row_type = str(row.get("type") or "")
        if row_type in {"MoveTo", "RelMoveTo"}:
            if len(current_points) > 1:
                subpaths.append(current_points)
            point = _geometry_row_point(page, shape, row, scale, relative=row_type.startswith("Rel"))
            current_points = [point] if point else []
        elif row_type in {"LineTo", "RelLineTo"}:
            point = _geometry_row_point(page, shape, row, scale, relative=row_type.startswith("Rel"))
            if point:
                if not current_points:
                    current_points = [point]
                else:
                    current_points.append(point)
        elif row_type in {"RelCubBezTo", "CubBezTo"}:
            curve_points = _geometry_cubic_points(page, shape, row, scale, current_points, row_type.startswith("Rel"))
            if curve_points:
                current_points.extend(curve_points)
        elif row_type in {"RelQuadBezTo", "QuadBezTo"}:
            curve_points = _geometry_quadratic_points(page, shape, row, scale, current_points, row_type.startswith("Rel"))
            if curve_points:
                current_points.extend(curve_points)
        elif row_type in {"RelEllipticalArcTo", "EllipticalArcTo"}:
            arc_points = _geometry_elliptical_arc_points(
                page,
                shape,
                row,
                scale,
                current_points,
                row_type.startswith("Rel"),
            )
            if arc_points:
                if not current_points:
                    current_points = [arc_points[-1]]
                else:
                    current_points.extend(arc_points)
        elif row_type == "Ellipse":
            draw.ellipse(_shape_bounds_px(page, shape, scale), fill=fill, outline=line, width=line_width)
            drew_geometry = True

    if len(current_points) > 1:
        subpaths.append(current_points)

    for points in subpaths:
        if len(points) < 2:
            continue
        is_closed = _points_are_close(points[0], points[-1]) and len(points) > 2
        if is_closed and fill is not None:
            draw.polygon(points, fill=fill)
        if line is not None:
            draw.line(points, fill=line, width=line_width, joint="curve")
        elif fill is not None and not is_closed:
            draw.line(points, fill=fill, width=line_width, joint="curve")
        drew_geometry = True

    return drew_geometry


def _geometry_row_point(
    page: Dict[str, Any],
    shape: Dict[str, Any],
    row: Dict[str, Any],
    scale: float,
    relative: bool,
    x_key: str = "X",
    y_key: str = "Y",
) -> Optional[Tuple[float, float]]:
    cells = row.get("cells") or {}
    raw_x = _number_or_none(cells.get(x_key))
    raw_y = _number_or_none(cells.get(y_key))
    if raw_x is None and raw_y is None:
        return None

    width = float(shape.get("width") or 0.0)
    height = float(shape.get("height") or 0.0)
    geometry_scale_x = float(shape.get("geometry_scale_x") or 1.0)
    geometry_scale_y = float(shape.get("geometry_scale_y") or 1.0)
    local_x = (raw_x or 0.0) * width if relative else (raw_x or 0.0) * geometry_scale_x
    local_y = (raw_y or 0.0) * height if relative else (raw_y or 0.0) * geometry_scale_y
    page_x = float(shape.get("left") or 0.0) + local_x
    page_y = float(shape.get("bottom") or 0.0) + local_y
    return _page_point_to_px(page, page_x, page_y, scale)


def _geometry_cubic_points(
    page: Dict[str, Any],
    shape: Dict[str, Any],
    row: Dict[str, Any],
    scale: float,
    current_points: List[Tuple[float, float]],
    relative: bool,
) -> List[Tuple[float, float]]:
    if not current_points:
        endpoint = _geometry_row_point(page, shape, row, scale, relative=relative)
        return [endpoint] if endpoint else []

    start = current_points[-1]
    control_one = _geometry_row_point(page, shape, row, scale, relative=relative, x_key="A", y_key="B")
    control_two = _geometry_row_point(page, shape, row, scale, relative=relative, x_key="C", y_key="D")
    endpoint = _geometry_row_point(page, shape, row, scale, relative=relative)
    if not control_one or not control_two or not endpoint:
        return [endpoint] if endpoint else []
    return [
        _cubic_bezier_point(start, control_one, control_two, endpoint, step / 12.0)
        for step in range(1, 13)
    ]


def _geometry_quadratic_points(
    page: Dict[str, Any],
    shape: Dict[str, Any],
    row: Dict[str, Any],
    scale: float,
    current_points: List[Tuple[float, float]],
    relative: bool,
) -> List[Tuple[float, float]]:
    if not current_points:
        endpoint = _geometry_row_point(page, shape, row, scale, relative=relative)
        return [endpoint] if endpoint else []

    start = current_points[-1]
    control = _geometry_row_point(page, shape, row, scale, relative=relative, x_key="A", y_key="B")
    endpoint = _geometry_row_point(page, shape, row, scale, relative=relative)
    if not control or not endpoint:
        return [endpoint] if endpoint else []
    return [
        _quadratic_bezier_point(start, control, endpoint, step / 10.0)
        for step in range(1, 11)
    ]


def _geometry_elliptical_arc_points(
    page: Dict[str, Any],
    shape: Dict[str, Any],
    row: Dict[str, Any],
    scale: float,
    current_points: List[Tuple[float, float]],
    relative: bool,
) -> List[Tuple[float, float]]:
    endpoint = _geometry_row_point(page, shape, row, scale, relative=relative)
    if not endpoint:
        return []
    if not current_points:
        return [endpoint]

    start = current_points[-1]
    control = _geometry_row_point(page, shape, row, scale, relative=relative, x_key="A", y_key="B")
    if not control or _points_are_close(start, control) or _points_are_close(control, endpoint):
        return [endpoint]

    return [
        _quadratic_bezier_point(start, control, endpoint, step / 10.0)
        for step in range(1, 11)
    ]


def _cubic_bezier_point(
    start: Tuple[float, float],
    control_one: Tuple[float, float],
    control_two: Tuple[float, float],
    end: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    inverse = 1.0 - t
    x = (
        (inverse ** 3 * start[0])
        + (3 * inverse * inverse * t * control_one[0])
        + (3 * inverse * t * t * control_two[0])
        + (t ** 3 * end[0])
    )
    y = (
        (inverse ** 3 * start[1])
        + (3 * inverse * inverse * t * control_one[1])
        + (3 * inverse * t * t * control_two[1])
        + (t ** 3 * end[1])
    )
    return x, y


def _quadratic_bezier_point(
    start: Tuple[float, float],
    control: Tuple[float, float],
    end: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    inverse = 1.0 - t
    x = (inverse * inverse * start[0]) + (2 * inverse * t * control[0]) + (t * t * end[0])
    y = (inverse * inverse * start[1]) + (2 * inverse * t * control[1]) + (t * t * end[1])
    return x, y


def _container_line_color(shape: Dict[str, Any]) -> Tuple[int, int, int]:
    text_color = _parse_hex_color(shape.get("text_color"))
    if text_color:
        return text_color
    return _parse_hex_color(shape.get("line_color"), (0, 0, 0)) or (0, 0, 0)


def _draw_dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    bounds: Tuple[float, float, float, float],
    color: Tuple[int, int, int],
    width: int,
) -> None:
    x0, y0, x1, y1 = bounds
    dash = max(10, width * 9)
    gap = max(6, width * 5)
    _draw_dashed_line(draw, (x0, y0), (x1, y0), color, width, dash, gap)
    _draw_dashed_line(draw, (x1, y0), (x1, y1), color, width, dash, gap)
    _draw_dashed_line(draw, (x1, y1), (x0, y1), color, width, dash, gap)
    _draw_dashed_line(draw, (x0, y1), (x0, y0), color, width, dash, gap)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Tuple[float, float],
    end: Tuple[float, float],
    color: Tuple[int, int, int],
    width: int,
    dash: int,
    gap: int,
) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return
    ux = dx / length
    uy = dy / length
    position = 0.0
    while position < length:
        dash_end = min(position + dash, length)
        segment_start = (start[0] + (ux * position), start[1] + (uy * position))
        segment_end = (start[0] + (ux * dash_end), start[1] + (uy * dash_end))
        draw.line([segment_start, segment_end], fill=color, width=width)
        position += dash + gap


def _number_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _points_are_close(first: Tuple[float, float], second: Tuple[float, float]) -> bool:
    return abs(first[0] - second[0]) <= 0.5 and abs(first[1] - second[1]) <= 0.5


def _draw_shape_image(image_canvas: Image.Image, shape: Dict[str, Any], bounds: Tuple[float, float, float, float]) -> bool:
    image_bytes = shape.get("image_bytes")
    if not image_bytes:
        return False
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        return False

    target_width = max(1, int(bounds[2] - bounds[0]))
    target_height = max(1, int(bounds[3] - bounds[1]))
    image.thumbnail((target_width, target_height), Image.LANCZOS)
    x = int(bounds[0] + ((target_width - image.width) / 2.0))
    y = int(bounds[1] + ((target_height - image.height) / 2.0))
    image_canvas.paste(image, (x, y), image)
    return True


def _draw_connector_shape_lines(
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shapes: List[Dict[str, Any]],
    scale: float,
) -> None:
    for shape in shapes:
        if not all(shape.get(key) is not None for key in ("begin_x", "begin_y", "end_x", "end_y")):
            continue
        begin = _page_point_to_px(page, float(shape["begin_x"]), float(shape["begin_y"]), scale)
        end = _page_point_to_px(page, float(shape["end_x"]), float(shape["end_y"]), scale)
        line_color = _parse_hex_color(shape.get("line_color"), (80, 88, 98))
        draw.line([begin, end], fill=line_color, width=3)
        _draw_arrowhead(draw, begin, end, line_color)


def _draw_arrowhead(
    draw: ImageDraw.ImageDraw,
    begin: Tuple[float, float],
    end: Tuple[float, float],
    color: Tuple[int, int, int],
) -> None:
    dx = end[0] - begin[0]
    dy = end[1] - begin[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 8:
        return
    ux = dx / length
    uy = dy / length
    size = 8
    wing = 4
    left = (end[0] - (ux * size) - (uy * wing), end[1] - (uy * size) + (ux * wing))
    right = (end[0] - (ux * size) + (uy * wing), end[1] - (uy * size) - (ux * wing))
    draw.polygon([end, left, right], fill=color)


def _draw_connection_lines(
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shapes_by_id: Dict[str, Dict[str, Any]],
    scale: float,
) -> None:
    for connector_id, begin_id, end_id in _connection_endpoint_pairs(page.get("connections") or []):
        connector_shape = shapes_by_id.get(connector_id)
        if connector_shape and all(connector_shape.get(key) is not None for key in ("begin_x", "begin_y", "end_x", "end_y")):
            continue
        begin_shape = shapes_by_id.get(begin_id)
        end_shape = shapes_by_id.get(end_id)
        if not begin_shape or not end_shape:
            continue
        begin = _shape_center_px(page, begin_shape, scale)
        end = _shape_center_px(page, end_shape, scale)
        if not begin or not end:
            continue
        draw.line([begin, end], fill=(120, 130, 145), width=3)


def _connection_endpoint_pairs(connections: List[Dict[str, str]]) -> List[Tuple[str, str, str]]:
    grouped: Dict[str, Dict[str, str]] = {}
    for connection in connections:
        connector_id = connection.get("from_sheet") or ""
        from_cell = connection.get("from_cell") or ""
        to_sheet = connection.get("to_sheet") or ""
        if not connector_id or not to_sheet:
            continue
        if from_cell.startswith("Begin"):
            grouped.setdefault(connector_id, {})["begin"] = to_sheet
        elif from_cell.startswith("End"):
            grouped.setdefault(connector_id, {})["end"] = to_sheet
    return [
        (connector_id, endpoints["begin"], endpoints["end"])
        for connector_id, endpoints in grouped.items()
        if endpoints.get("begin") and endpoints.get("end")
    ]


def _shape_text_bounds_px(
    page: Dict[str, Any],
    shape: Dict[str, Any],
    scale: float,
) -> Optional[Tuple[float, float, float, float]]:
    if not _has_shape_bounds(shape):
        return None

    txt_width = shape.get("txt_width")
    txt_height = shape.get("txt_height")
    if txt_width is None or txt_height is None or float(txt_width) <= 0 or float(txt_height) <= 0:
        return None

    txt_pin_x = shape.get("txt_pin_x")
    txt_pin_y = shape.get("txt_pin_y")
    txt_loc_pin_x = shape.get("txt_loc_pin_x")
    txt_loc_pin_y = shape.get("txt_loc_pin_y")

    if txt_pin_x is None:
        txt_pin_x = (shape.get("width") or 0.0) / 2.0
    if txt_pin_y is None:
        txt_pin_y = (shape.get("height") or 0.0) / 2.0
    if txt_loc_pin_x is None:
        txt_loc_pin_x = float(txt_width) / 2.0
    if txt_loc_pin_y is None:
        txt_loc_pin_y = float(txt_height) / 2.0

    left = float(shape["left"]) + float(txt_pin_x) - float(txt_loc_pin_x)
    bottom = float(shape["bottom"]) + float(txt_pin_y) - float(txt_loc_pin_y)
    text_shape = {
        "left": left,
        "bottom": bottom,
        "right": left + float(txt_width),
        "top": bottom + float(txt_height),
    }
    return _shape_bounds_px(page, text_shape, scale)


def _is_icon_label(shape: Dict[str, Any]) -> bool:
    if shape.get("type") == "Foreign":
        return True
    if shape.get("type") == "Group" and _shape_area(shape) <= 1.5:
        return True
    return bool(shape.get("master_name") and _shape_area(shape) <= 1.5)


def _draw_shape_text(
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shape: Dict[str, Any],
    scale: float,
    font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
) -> None:
    text = str(shape.get("text") or "").strip()
    if not text or _is_connector_shape(shape):
        return

    icon_label = _is_icon_label(shape)
    dashed_container = _is_dashed_container(shape)
    shape_bounds = _shape_bounds_px(page, shape, scale) if _has_shape_bounds(shape) else None
    bounds = None if icon_label or dashed_container else _shape_text_bounds_px(page, shape, scale)
    if bounds is None and shape_bounds:
        if icon_label:
            bounds = (
                shape_bounds[0] - 48,
                shape_bounds[3] + 8,
                shape_bounds[2] + 48,
                shape_bounds[3] + 92,
            )
        elif dashed_container:
            bounds = (
                shape_bounds[2] - min(220, max(120, shape_bounds[2] - shape_bounds[0] - 24)),
                shape_bounds[1] + 8,
                shape_bounds[2] - 8,
                shape_bounds[1] + 86,
            )
        else:
            bounds = shape_bounds
    elif bounds is None:
        center = _shape_center_px(page, shape, scale)
        if center is None:
            return
        bounds = (center[0] - 70, center[1] - 20, center[0] + 70, center[1] + 40)

    active_font = small_font if icon_label else font
    max_text_width = max(60, int((bounds[2] - bounds[0]) - 8))
    wrapped_lines = _wrap_text(draw, text, active_font, max_text_width)[:5]
    if not wrapped_lines:
        return

    line_height = _text_size(draw, "Ag", active_font)[1] + 3
    total_height = len(wrapped_lines) * line_height
    if icon_label or dashed_container:
        y = bounds[1] + 2
    else:
        y = bounds[1] + max(2, ((bounds[3] - bounds[1]) - total_height) / 2.0)
    text_color = _parse_hex_color(shape.get("text_color"), (32, 42, 54)) or (32, 42, 54)
    for line in wrapped_lines:
        line_width = _text_size(draw, line, active_font)[0]
        if dashed_container and str(shape.get("horizontal_align") or "") == "2":
            x = bounds[2] - line_width - 2
        else:
            x = bounds[0] + max(2, ((bounds[2] - bounds[0]) - line_width) / 2.0)
        draw.text((x, y), line, fill=text_color, font=active_font)
        y += line_height


def _draw_shape_box(
    draw: ImageDraw.ImageDraw,
    page: Dict[str, Any],
    shape: Dict[str, Any],
    scale: float,
    font: ImageFont.ImageFont,
) -> None:
    bounds = _shape_bounds_px(page, shape, scale)
    draw.rounded_rectangle(bounds, radius=8, fill=(242, 247, 252), outline=(74, 116, 168), width=2)
    text = str(shape.get("text") or "").strip()
    if not text:
        return
    max_text_width = max(60, int((bounds[2] - bounds[0]) - 12))
    wrapped_lines = _wrap_text(draw, text, font, max_text_width)[:4]
    line_height = _text_size(draw, "Ag", font)[1] + 3
    total_height = len(wrapped_lines) * line_height
    y = bounds[1] + max(6, ((bounds[3] - bounds[1]) - total_height) / 2.0)
    for line in wrapped_lines:
        line_width = _text_size(draw, line, font)[0]
        x = bounds[0] + max(6, ((bounds[2] - bounds[0]) - line_width) / 2.0)
        draw.text((x, y), line, fill=(22, 32, 45), font=font)
        y += line_height


def _draw_text_only_fallback(draw: ImageDraw.ImageDraw, page: Dict[str, Any], font: ImageFont.ImageFont) -> None:
    margin = _preview_margin_px(page)
    y = margin + 24
    draw.text((margin + 24, y), "No positioned text shapes were found.", fill=(65, 70, 80), font=font)
    y += 30
    for shape in [shape for shape in page.get("shapes") or [] if shape.get("text")][:40]:
        draw.text((margin + 24, y), f"- {shape.get('text')}", fill=(22, 32, 45), font=font)
        y += 22


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = str(text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]