# functions_excel_accessibility.py
"""Bounded, read-only Excel native inspection; never executes workbook content."""

import json
import os
import posixpath
import re
import struct
import zipfile
from collections import Counter
from itertools import islice

import olefile
import xlrd
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError
from defusedxml.ElementTree import fromstring
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.styles.numbers import BUILTIN_FORMATS
from openpyxl.utils.cell import get_column_letter

from functions_appinsights import log_event
from functions_document_style import StyleAccumulator
from functions_office_media import OFFICE_ZIP_MAX_ENTRIES, _read_zip_entry_bounded


EXCEL_MAX_PART_BYTES = 16 * 1024 * 1024
EXCEL_MAX_TOTAL_BYTES = 64 * 1024 * 1024
EXCEL_MAX_SHEETS = 100
EXCEL_MAX_CELLS = 20000
EXCEL_MAX_STYLE_DEFINITIONS = 20000
EXCEL_MAX_RECORDS = 2000
EXCEL_MAX_TEXT = 4000
EXCEL_MAX_EVIDENCE_CHARS = 1000000
EXCEL_MAX_PARENT_BYTES = 500000
EXCEL_EVIDENCE_MARKER = "### Excel native inspection"
EXCEL_COVERAGE_NOTES = [
    "Saved native state only; no Excel rendering, formula or macro execution.",
    "Conditional formatting is inventoried, not evaluated; effective appearance may differ.",
    "ActiveX, embedded OLE content and unsupported control representations are not inspected.",
]
_THEME_COLORS = ("lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3",
                 "accent4", "accent5", "accent6", "hlink", "folHlink")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _attr(element, name, default=""):
    return next((value for key, value in element.attrib.items() if _local(key) == name), default)


def _first(element, name):
    return next((child for child in element.iter() if _local(child.tag) == name), None)


def _text(element):
    return "".join(element.itertext()) if element is not None else ""


def _on(value):
    return str(value).lower() in ("1", "true", "on")


class _Inspection:
    def __init__(self, extension):
        self.meta = {
            "format": extension.lstrip("."), "schema_version": "1.0",
            "coverage": "partial", "coverage_notes": list(EXCEL_COVERAGE_NOTES),
            "properties": {}, "sheets": [], "comments": [], "objects": [], "issues": [],
        }
        self.evidence = []
        self.evidence_chars = 0
        self.bytes_read = 0
        self.records = 0
        self.cells = 0
        self.cache = {}
        self.parent_record_bytes = 0
        self.styles = StyleAccumulator("sheet_cell")
        self.counts = Counter()

    def note(self, message):
        if message not in self.meta["coverage_notes"] and len(self.meta["coverage_notes"]) < 40:
            self.meta["coverage_notes"].append(message)
            inventory = self.meta.get("style_inventory")
            if inventory is not None and message not in inventory["coverage_notes"]:
                inventory["coverage_notes"].append(message)

    def clean(self, value):
        text = str(value or "")
        if len(text) > EXCEL_MAX_TEXT:
            self.note("Long native strings were truncated to the per-field limit.")
            return text[:EXCEL_MAX_TEXT] + " [truncated]"
        return text

    def xml(self, archive, part, required=False):
        if part in self.cache:
            return self.cache[part]
        if part not in archive.namelist():
            if required:
                raise ValueError("Missing required workbook part")
            return None
        remaining = EXCEL_MAX_TOTAL_BYTES - self.bytes_read
        data = _read_zip_entry_bounded(archive, part, min(EXCEL_MAX_PART_BYTES, remaining))
        if data is None:
            raise ValueError("Workbook XML exceeds inspection limits or is unreadable")
        self.bytes_read += len(data)
        root = fromstring(data)
        self.cache[part] = root
        return root

    def rels(self, archive, part):
        path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        root = self.xml(archive, path)
        result = {}
        if root is None:
            return result
        for element in root:
            if _attr(element, "TargetMode").lower() == "external":
                self.note("External relationships were not followed.")
                continue
            target = _attr(element, "Target")
            if "\\" in target or ":" in target or "?" in target or "#" in target:
                self.note("Invalid package relationship targets were not followed.")
                continue
            resolved = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else
                posixpath.join(posixpath.dirname(part), target)
            )
            if resolved.startswith("../") or resolved in ("..", "."):
                self.note("Out-of-package relationship targets were not followed.")
                continue
            result[_attr(element, "Id")] = (_attr(element, "Type").rsplit("/", 1)[-1], resolved)
        return result

    def emit(self, sheet, kind, value):
        content = f"{EXCEL_EVIDENCE_MARKER}\nSheet: {self.clean(sheet)}\n{kind}: {json.dumps(value, ensure_ascii=True)}"
        if self.evidence_chars + len(content) > EXCEL_MAX_EVIDENCE_CHARS:
            self.note("Native search evidence was truncated at the aggregate evidence limit.")
            return
        location = value.get("cell") or value.get("id") or "" if isinstance(value, dict) else ""
        self.evidence.append({
            "content": content, "sheet_name": sheet, "kind": kind,
            "location": str(location)[:128],
        })
        self.evidence_chars += len(content)

    def record(self, collection, sheet, record):
        self.counts[collection] += 1
        if self.records >= EXCEL_MAX_RECORDS:
            self.note("Native comment/object records were truncated at the record limit.")
            return
        self.records += 1
        record = {"sheet": sheet, **record}
        record_bytes = len(json.dumps(record, ensure_ascii=True).encode("utf-8"))
        if self.parent_record_bytes + record_bytes <= EXCEL_MAX_PARENT_BYTES // 2:
            self.meta[collection].append(record)
            self.parent_record_bytes += record_bytes
        else:
            self.note("Parent comment/object inventory was capped; location-specific search evidence is separate.")
        self.emit(sheet, collection, record)

    def finish(self):
        self.meta["observed_counts"] = dict(self.counts)
        self.meta["inspected_cells"] = self.cells
        if len(self.meta["sheets"]) > 10:
            self.note("The style section includes layout/print examples for the first 10 inspected sheets; the accessibility section and search evidence cover more.")
        self.meta["style_inventory"] = self.styles.build_inventory(
            coverage="partial", notes=self.meta["coverage_notes"],
            page_setup={"sheets": [
                {"name": sheet["name"], "print_setup": [
                    record for record in sheet.get("layout", [])
                    if record.get("type") in ("pageMargins", "pageSetup", "printOptions")
                ]}
                for sheet in self.meta["sheets"][:10]
            ]},
            extra={
                "location_kind": "sheet_cell", "weighting": "first 60 saved-value characters per inspected cell",
                "layout": {"sheets": [
                    {"name": sheet["name"], "state": sheet.get("state"),
                     "range_examples": sheet.get("layout", [])[:10]}
                    for sheet in self.meta["sheets"][:10]
                ]},
            },
        )
        objects = self.meta["objects"]
        self.meta["figures_summary"] = {
            "total": self.counts["objects"],
            "with_alt": sum(bool(item.get("alt_text") or item.get("title")) for item in objects),
            "decorative": sum(item.get("is_decorative") is True for item in objects),
            "missing_alt": sum(
                item.get("alt_inspected") is True and not item.get("alt_text")
                and not item.get("title") and item.get("is_decorative") is not True
                for item in objects
            ),
            "counts_scope": "alt/decorative counts cover retained inspected objects only",
        }
        self.meta["forms_summary"] = {
            "controls_inspected": sum(item.get("type", "").lower() in ("checkbox", "check box", "button", "radio") for item in objects),
            "coverage": "partial; unsupported control types are not accessibility failures",
        }
        # Search evidence keeps the location-specific records; Cosmos remains a bounded inventory.
        while len(json.dumps(self.meta, ensure_ascii=True).encode("utf-8")) > EXCEL_MAX_PARENT_BYTES - 1024:
            style = self.meta["style_inventory"]
            candidates = [self.meta[key] for key in ("comments", "objects", "sheets") if self.meta[key]]
            candidates.extend(style[key] for key in ("outliers", "colors") if style[key])
            candidates.extend(value["sheets"] for value in (style["layout"], style["page_setup"]) if value["sheets"])
            if not candidates:
                raise ValueError("Workbook parent metadata exceeds its size limit")
            collection = max(candidates, key=lambda records: len(json.dumps(records)))
            removed = collection.pop()
            if collection is self.meta["objects"]:
                figures = self.meta["figures_summary"]
                figures["with_alt"] -= bool(removed.get("alt_text") or removed.get("title"))
                figures["decorative"] -= removed.get("is_decorative") is True
                figures["missing_alt"] -= (
                    removed.get("alt_inspected") is True and not removed.get("alt_text")
                    and not removed.get("title") and removed.get("is_decorative") is not True
                )
                self.meta["forms_summary"]["controls_inspected"] -= removed.get("type", "").lower() in ("checkbox", "check box", "button", "radio")
            style["outliers_truncated"] = len(style["outliers"]) < style["outlier_run_count"]
            self.note("Parent inventory was truncated at its serialized byte limit; search evidence is separate.")

        def coverage_content():
            return f"{EXCEL_EVIDENCE_MARKER}\nWorkbook properties and inspection coverage:\n" + json.dumps({
                "properties": self.meta["properties"],
                "coverage": self.meta["coverage"],
                "coverage_notes": self.meta["coverage_notes"],
                "observed_counts": self.meta["observed_counts"],
            }, ensure_ascii=True)

        while self.evidence and self.evidence_chars + len(coverage_content()) > EXCEL_MAX_EVIDENCE_CHARS:
            removed = self.evidence.pop()
            self.evidence_chars -= len(removed["content"])
            self.note("Native search evidence was truncated at the aggregate evidence limit.")
        self.evidence.insert(0, {"content": coverage_content(), "sheet_name": "(workbook)"})
        return self.meta, self.evidence


def _core_properties(state, root):
    if root is None:
        return
    names = {"title", "creator", "subject", "keywords", "description", "language",
             "category", "created", "modified", "lastModifiedBy"}
    properties = {_local(item.tag): state.clean(item.text) for item in root if _local(item.tag) in names}
    state.meta["properties"] = properties
    for key in ("title", "subject", "description", "language", "category"):
        state.meta[key] = properties.get(key, "")
    state.meta["authors"] = [part.strip() for part in re.split(r"[;,]", properties.get("creator", "")) if part.strip()]
    state.meta["keywords"] = [part.strip() for part in re.split(r"[;,]", properties.get("keywords", "")) if part.strip()]


def _color(element, theme, state, palette=COLOR_INDEX):
    if element is None:
        return None
    rgb = element.get("rgb")
    if rgb:
        value = "#" + rgb[-6:].upper()
    elif "indexed" in element.attrib:
        index = int(element.get("indexed"))
        value = "#" + palette[index][-6:] if 0 <= index < len(palette) else None
    elif "theme" in element.attrib:
        index = int(element.get("theme"))
        value = theme.get(_THEME_COLORS[index]) if 0 <= index < len(_THEME_COLORS) else None
    else:
        value = None
    if value and element.get("tint"):
        tint = float(element.get("tint"))
        if not -1 <= tint <= 1:
            value = None
        else:
            channels = [int(value[index:index + 2], 16) for index in (1, 3, 5)]
            channels = [round(channel * (1 + tint) if tint < 0 else channel * (1 - tint) + 255 * tint)
                        for channel in channels]
            value = "#" + "".join(f"{channel:02X}" for channel in channels)
            state.note("Theme tint colors are approximated from saved RGB; Excel rendering is not reproduced.")
    if value is None:
        state.note("Some automatic, system or unresolved colors have no known RGB value.")
        return "unresolved:" + state.clean(json.dumps(element.attrib, sort_keys=True))
    return value


def _style_definitions(state, archive, workbook_rels):
    theme, theme_fonts = {}, {}
    for kind, path in workbook_rels.values():
        if kind != "theme":
            continue
        root = state.xml(archive, path, required=True)
        scheme = _first(root, "clrScheme")
        for child in scheme if scheme is not None else []:
            color = next(iter(child), None)
            if color is not None:
                raw = color.get("val") if _local(color.tag) == "srgbClr" else color.get("lastClr")
                if raw:
                    theme[_local(child.tag)] = "#" + raw[-6:]
        for kind in ("major", "minor"):
            container = _first(root, kind + "Font")
            latin = _first(container, "latin") if container is not None else None
            if latin is not None:
                theme_fonts[kind] = latin.get("typeface")
    style_path = next((path for kind, path in workbook_rels.values() if kind == "styles"), None)
    if not style_path:
        state.note("No saved workbook style definitions were available.")
        return [{}]
    root = state.xml(archive, style_path, required=True)
    indexed = _first(root, "indexedColors")
    palette = [item.get("rgb", "") for item in indexed] if indexed is not None else COLOR_INDEX
    fonts_root, fills_root = _first(root, "fonts"), _first(root, "fills")
    fonts = list(fonts_root) if fonts_root is not None else []
    fills = list(fills_root) if fills_root is not None else []
    custom_formats = {item.get("numFmtId"): state.clean(item.get("formatCode"))
                      for item in root.iter() if _local(item.tag) == "numFmt"}
    xfs = _first(root, "cellXfs")
    if any(len(table) > EXCEL_MAX_STYLE_DEFINITIONS for table in (fonts, fills, xfs if xfs is not None else [])):
        raise ValueError("Workbook style definitions exceed inspection limits")
    definitions = []
    base_root = _first(root, "cellStyleXfs")
    base_styles = list(base_root) if base_root is not None else []
    for xf in xfs if xfs is not None else []:
        base_index = int(xf.get("xfId", "0"))
        base = base_styles[base_index] if 0 <= base_index < len(base_styles) else None
        attributes = {**(base.attrib if base is not None else {}), **xf.attrib}
        for flag, attribute in (("applyFont", "fontId"), ("applyFill", "fillId"), ("applyNumberFormat", "numFmtId")):
            if base is not None and xf.get(flag) in ("0", "false"):
                attributes[attribute] = base.get(attribute, "0")
        font_index, fill_index = int(attributes.get("fontId", 0)), int(attributes.get("fillId", 0))
        font = fonts[font_index] if 0 <= font_index < len(fonts) else None
        fill = fills[fill_index] if 0 <= fill_index < len(fills) else None
        spec = {}
        if font is not None:
            for child in font:
                name = _local(child.tag)
                if name == "name":
                    spec["font"] = state.clean(child.get("val"))[:256]
                elif name == "scheme" and theme_fonts.get(child.get("val")):
                    spec["font"] = state.clean(theme_fonts[child.get("val")])[:256]
                elif name == "sz":
                    spec["size_pt"] = float(child.get("val"))
                elif name in ("b", "i", "u"):
                    spec[{"b": "bold", "i": "italic", "u": "underline"}[name]] = child.get("val", "1") not in ("0", "false", "none")
                elif name == "color":
                    spec["color"] = _color(child, theme, state, palette)
        if fill is not None:
            spec["fill"] = _color(_first(fill, "fgColor"), theme, state, palette)
            pattern = _first(fill, "patternFill")
            if pattern is not None:
                spec["fill_pattern"] = pattern.get("patternType")
        alignment = _first(xf, "alignment") if xf.get("applyAlignment") not in ("0", "false") else None
        if alignment is None and base is not None:
            alignment = _first(base, "alignment")
        if alignment is not None:
            spec["alignment"] = {key: state.clean(value) for key, value in alignment.attrib.items()}
        number_id = attributes.get("numFmtId", "0")
        spec["number_format"] = custom_formats.get(number_id, BUILTIN_FORMATS.get(int(number_id), f"unresolved:{number_id}"))
        definitions.append(spec)
    state.note("Cell XF values are inspected; table-style effects and rich-text run overrides are not resolved.")
    return definitions or [{}]


def _header_sections(expression):
    """Keep Excel control codes intact while separating explicit L/C/R sections."""
    sections = {}
    section, start = "center", 0
    for token in re.finditer(r"&&|&[LCR]", expression):
        if token[0] == "&&":
            continue
        sections[section] = sections.get(section, "") + expression[start:token.start()]
        section = {"L": "left", "C": "center", "R": "right"}[token[0][1]]
        start = token.end()
    sections[section] = sections.get(section, "") + expression[start:]
    return {key: value for key, value in sections.items() if value}


def _comments(state, archive, sheet, relationships, persons):
    for kind, path in relationships.values():
        if kind not in ("comments", "threadedComment", "threadedComments"):
            continue
        root = state.xml(archive, path, required=True)
        authors = [state.clean(item.text) for item in root.iter() if _local(item.tag) == "author"]
        for item in root.iter():
            name = _local(item.tag)
            if name not in ("comment", "threadedComment"):
                continue
            if name == "comment":
                index = int(item.get("authorId", "-1"))
                author = authors[index] if 0 <= index < len(authors) else None
            else:
                author = persons.get(item.get("personId"))
            text = "".join(_text(child) for child in item if _local(child.tag) == "text")
            state.record("comments", sheet, {
                "kind": "note" if name == "comment" else "threaded_comment",
                "cell": state.clean(item.get("ref")), "text": state.clean(text),
                "author": author, "date": state.clean(item.get("dT")) or None,
                "id": state.clean(item.get("id")) or None,
                "parent_id": state.clean(item.get("parentId")) or None,
                "resolved": _on(item.get("done")) if "done" in item.attrib else None,
            })


def _objects(state, archive, sheet, relationships):
    for kind, path in relationships.values():
        if kind not in ("drawing", "vmlDrawing", "ctrlProp", "control"):
            continue
        root = state.xml(archive, path, required=True)
        if kind in ("ctrlProp", "control"):
            state.note("Control properties are retained without inspecting executable control content.")
            state.emit(sheet, "Control properties", {key: state.clean(value) for key, value in root.attrib.items()})
            state.record("objects", sheet, {
                "type": state.clean(root.get("objectType")) or "unsupported_control",
                "part": path, "alt_inspected": False, "is_decorative": None,
                "alt_text": None, "title": None,
            })
            continue
        if kind == "vmlDrawing":
            for shape in root.iter():
                if _local(shape.tag) != "shape":
                    continue
                client = _first(shape, "ClientData")
                control_type = client.get("ObjectType") if client is not None else None
                if control_type == "Note":
                    continue
                row = _first(client, "Row") if client is not None else None
                column = _first(client, "Column") if client is not None else None
                state.record("objects", sheet, {
                    "type": control_type or "vml_shape", "id": state.clean(shape.get("id")),
                    "cell": f"{get_column_letter(int(column.text) + 1)}{int(row.text) + 1}" if row is not None and column is not None else None,
                    "alt_text": state.clean(shape.get("alt")), "title": state.clean(_attr(shape, "title")),
                    "is_decorative": None, "alt_inspected": True,
                })
            state.note("VML decorative status is unavailable; absent marking remains unknown.")
            continue
        parents = {child: parent for parent in root.iter() for child in parent}
        for anchor in root:
            start = _first(anchor, "from")
            row = _first(start, "row") if start is not None else None
            column = _first(start, "col") if start is not None else None
            cell = f"{get_column_letter(int(column.text) + 1)}{int(row.text) + 1}" if row is not None and column is not None else None
            for properties in anchor.iter():
                if _local(properties.tag) != "cNvPr":
                    continue
                decorative = _first(properties, "decorative")
                owner = parents.get(parents.get(properties))
                owner_type = _local(owner.tag) if owner is not None else ""
                object_type = (
                    "image" if owner_type == "pic" else
                    "chart" if owner is not None and owner_type == "graphicFrame" and _first(owner, "chart") is not None else
                    "group" if owner_type == "grpSp" else "shape"
                )
                state.record("objects", sheet, {
                    "type": object_type, "id": state.clean(properties.get("id")),
                    "name": state.clean(properties.get("name")), "cell": cell,
                    "alt_text": state.clean(properties.get("descr")), "title": state.clean(properties.get("title")),
                    "is_decorative": _on(decorative.get("val")) if decorative is not None else None,
                    "alt_inspected": True,
                })


def _sheet(state, archive, entry, path, kind, definitions, shared_strings, persons):
    name = state.clean(entry.get("name"))[:128]
    root = state.xml(archive, path, required=True)
    sheet = {"name": name, "state": entry.get("state", "visible"), "type": kind, "part": path}
    state.meta["sheets"].append(sheet)
    layout_names = {"mergeCell", "col", "pane", "pageMargins", "pageSetup", "printOptions",
                    "sheetFormatPr", "sheetView", "autoFilter", "sheetPr"}
    layout = []
    for element in root.iter():
        local = _local(element.tag)
        if local in layout_names or local == "row" and any(key in element.attrib for key in ("ht", "hidden", "s")):
            if len(layout) < 200:
                record = {"type": local, **{key: state.clean(value) for key, value in element.attrib.items()}}
                style_id = element.get("style") if local == "col" else element.get("s") if local == "row" else None
                if style_id is not None and 0 <= int(style_id) < len(definitions):
                    record["saved_style"] = definitions[int(style_id)]
                layout.append(record)
            else:
                state.note("Sheet layout ranges were truncated to 200 records per sheet.")
    sheet["layout"] = layout
    sheet["conditional_format_rules"] = sum(_local(element.tag) == "cfRule" for element in root.iter())
    header_footer = _first(root, "headerFooter")
    sheet["header_footer"] = {}
    if header_footer is not None:
        sheet["header_footer"] = {
            "flags": dict(header_footer.attrib),
            "expressions": {_local(child.tag): state.clean(child.text) for child in header_footer},
            "sections": {_local(child.tag): _header_sections(state.clean(child.text)) for child in header_footer},
        }
    state.emit(name, "Sheet layout, headers and footers (raw Excel control codes; not evaluated)", sheet)
    relationships = state.rels(archive, path)
    _comments(state, archive, name, relationships, persons)
    _objects(state, archive, name, relationships)
    if _first(root, "oleObjects") is not None or any(kind in ("oleObject", "activeXControl", "control") for kind, _ in relationships.values()):
        state.note("This workbook contains unsupported OLE/ActiveX controls; their alt text was not inspected.")
    if any(_local(element.tag) in ("cellControl", "featurePropertyBag") for element in root.iter()):
        state.note("Modern in-cell controls were detected; their accessibility metadata is unsupported.")
    column_styles = [(int(column.get("min")), int(column.get("max")), column.get("style"))
                     for column in root.iter() if _local(column.tag) == "col" and column.get("style") is not None]
    row_styles = {row.get("r"): row.get("s") for row in root.iter()
                  if _local(row.tag) == "row" and row.get("s") is not None}
    saved_styles = {}
    for element in root.iter():
        if _local(element.tag) != "c":
            continue
        if state.cells >= EXCEL_MAX_CELLS:
            state.note(f"Cell formatting inspection sampled the first {EXCEL_MAX_CELLS} saved cells.")
            break
        state.cells += 1
        ref = state.clean(element.get("r"))[:32]
        column_match = re.match(r"([A-Z]+)(\d+)$", ref)
        inherited_style = None
        if column_match:
            column_index = 0
            for letter in column_match[1]:
                column_index = column_index * 26 + ord(letter) - ord("A") + 1
            inherited_style = next((style for low, high, style in column_styles if low <= column_index <= high), None)
            inherited_style = row_styles.get(column_match[2], inherited_style)
        style_index = int(element.get("s", inherited_style or 0))
        spec = definitions[style_index] if 0 <= style_index < len(definitions) else {}
        if not spec:
            state.note("Some cell style references could not be resolved.")
        value = _first(element, "v")
        raw = _text(value)
        if element.get("t") == "s":
            index = int(raw) if raw else -1
            raw = shared_strings[index] if 0 <= index < len(shared_strings) else "[unresolved shared string]"
        elif element.get("t") == "inlineStr":
            raw = _text(_first(element, "is"))
        # Text is used only for the bounded style accumulator, not copied to search evidence.
        snippet = state.clean(raw)[:60]
        if raw == "[unresolved shared string]":
            state.note("Some shared-string references were outside the inspected string range.")
        location = f"{name}!{ref}"
        state.styles.add(location, snippet, **{key: spec.get(key) for key in (
            "font", "size_pt", "color", "bold", "italic", "underline"
        )})
        if style_index not in saved_styles:
            if len(saved_styles) >= 100:
                state.note("Per-sheet formatting evidence was capped at 100 distinct cell styles.")
                continue
            saved_styles[style_index] = {"style_id": style_index, "cells": [], "observed_cell_count": 0, **spec}
        group = saved_styles[style_index]
        group["observed_cell_count"] += 1
        if len(group["cells"]) < 30:
            group["cells"].append(ref)
        else:
            state.note("Style location lists show the first 30 cells per saved style per sheet.")
    for group in saved_styles.values():
        state.emit(name, "Saved cell formatting (not worksheet data)", group)


def _extract_ooxml(state, file_path):
    with zipfile.ZipFile(file_path) as archive:
        names = archive.namelist()
        if len(names) > OFFICE_ZIP_MAX_ENTRIES or len(names) != len(set(names)):
            raise ValueError("Workbook archive entry limit or duplicate part")
        relationships = state.rels(archive, "")
        if any("featurepropertybag" in name.lower() or "activeX/" in name for name in names):
            state.note("Newer in-cell controls or ActiveX parts are present and are not inspected.")
        workbook_path = next((path for kind, path in relationships.values() if kind == "officeDocument"), "xl/workbook.xml")
        core_path = next((path for kind, path in relationships.values() if kind == "core-properties"), "docProps/core.xml")
        _core_properties(state, state.xml(archive, core_path))
        workbook = state.xml(archive, workbook_path, required=True)
        workbook_rels = state.rels(archive, workbook_path)
        definitions = _style_definitions(state, archive, workbook_rels)
        state.emit("(workbook)", "Saved default cell style", definitions[0])
        shared_strings, persons = [], {}
        for kind, path in workbook_rels.values():
            if kind == "sharedStrings":
                root = state.xml(archive, path, required=True)
                shared_strings = [state.clean(_text(item)) for item in islice(root, EXCEL_MAX_CELLS)]
                if len(root) > EXCEL_MAX_CELLS:
                    state.note("Shared strings were truncated at the cell inspection limit.")
            elif kind in ("person", "persons"):
                root = state.xml(archive, path, required=True)
                persons = {element.get("id"): state.clean(element.get("displayName"))
                           for element in root.iter() if _local(element.tag) == "person"}
        sheets_root = _first(workbook, "sheets")
        entries = list(sheets_root) if sheets_root is not None else []
        state.meta["sheet_count"] = len(entries)
        if len(entries) > EXCEL_MAX_SHEETS:
            state.note(f"Only the first {EXCEL_MAX_SHEETS} sheets were inspected.")
        for entry in entries[:EXCEL_MAX_SHEETS]:
            relationship = workbook_rels.get(_attr(entry, "id"))
            if not relationship or relationship[0] not in ("worksheet", "chartsheet"):
                state.note("A sheet relationship is unsupported or unavailable.")
                continue
            try:
                _sheet(state, archive, entry, relationship[1], relationship[0], definitions, shared_strings, persons)
            except (ValueError, KeyError, OSError, ParseError, DefusedXmlException, zipfile.BadZipFile) as exc:
                state.note(f"A sheet could not be completely inspected ({type(exc).__name__}).")
                log_event("[DOCUMENT_METADATA] Excel sheet inspection incomplete.", level=30,
                          extra={"error_type": type(exc).__name__})
        defined_names = [
            {"name": state.clean(item.get("name")), "sheet_index": item.get("localSheetId"),
             "expression": state.clean(item.text)}
            for item in workbook.iter() if _local(item.tag) == "definedName"
            and item.get("name") in ("_xlnm.Print_Titles", "_xlnm.Print_Area")
        ][:EXCEL_MAX_SHEETS * 2]
        state.meta["print_defined_names"] = defined_names
        if defined_names:
            state.emit("(workbook)", "Print titles and print areas (not header/footer text)", defined_names)


def _extract_xls(state, file_path):
    state.note("Legacy XLS inspection is best effort; objects, decorative flags, threaded comments and headers/footers are unavailable.")
    if os.path.getsize(file_path) > EXCEL_MAX_TOTAL_BYTES:
        raise ValueError("Legacy workbook exceeds inspection size limit")
    if not olefile.isOleFile(file_path):
        raise ValueError("Not a legacy OLE workbook")
    with olefile.OleFileIO(file_path) as archive:
        summary = archive.get_metadata()
        for key in ("title", "author", "subject", "keywords", "comments"):
            value = getattr(summary, key, None)
            if isinstance(value, bytes):
                value = value.decode("cp1252", errors="replace")
                state.note("Legacy OLE byte-string properties use Windows-1252 decoding; original encoding may differ.")
            state.meta["properties"][key] = state.clean(value)
        for key in ("create_time", "last_saved_time"):
            value = getattr(summary, key, None)
            if value is not None:
                state.meta["properties"][key] = value.isoformat()
        state.meta["title"] = state.meta["properties"].get("title", "")
        state.meta["subject"] = state.meta["properties"].get("subject", "")
        state.meta["authors"] = [item.strip() for item in re.split(r"[;,]", state.meta["properties"].get("author", "")) if item.strip()]
        state.meta["keywords"] = [item.strip() for item in re.split(r"[;,]", state.meta["properties"].get("keywords", "")) if item.strip()]
    workbook = xlrd.open_workbook(file_path, on_demand=True, formatting_info=True, ragged_rows=True)
    try:
        state.meta["sheet_count"] = workbook.nsheets
        if workbook.nsheets > EXCEL_MAX_SHEETS:
            state.note(f"Only the first {EXCEL_MAX_SHEETS} sheets were inspected.")
        for index in range(min(workbook.nsheets, EXCEL_MAX_SHEETS)):
            sheet = workbook.sheet_by_index(index)
            name = state.clean(sheet.name)
            info = {
                "name": name, "state": sheet.visibility, "merged_ranges": sheet.merged_cells[:200],
                "columns": [{"column": key, "width": value.width, "hidden": value.hidden}
                            for key, value in islice(sheet.colinfo_map.items(), 200)],
                "rows": [{"row": key, "height": value.height, "hidden": value.hidden}
                         for key, value in islice(sheet.rowinfo_map.items(), 200)],
                "coverage": "first 200 layout records of each kind",
            }
            state.meta["sheets"].append(info)
            state.emit(name, "Legacy sheet layout", info)
            for (row, column), note in sheet.cell_note_map.items():
                state.record("comments", name, {
                    "kind": "note", "cell": f"{get_column_letter(column + 1)}{row + 1}",
                    "text": state.clean(note.text), "author": state.clean(note.author),
                    "date": None, "resolved": None,
                })
            for row in range(sheet.nrows):
                if state.cells >= EXCEL_MAX_CELLS:
                    state.note(f"Cell formatting inspection sampled the first {EXCEL_MAX_CELLS} saved cells.")
                    break
                for column in range(sheet.row_len(row)):
                    if state.cells >= EXCEL_MAX_CELLS:
                        break
                    cell = sheet.cell(row, column)
                    state.cells += 1
                    xf = workbook.xf_list[cell.xf_index]
                    font = workbook.font_list[xf.font_index]
                    rgb = workbook.colour_map.get(font.colour_index)
                    color = "#" + "".join(f"{channel:02X}" for channel in rgb) if rgb else None
                    ref = f"{get_column_letter(column + 1)}{row + 1}"
                    state.styles.add(f"{name}!{ref}", str(cell.value)[:60], font=font.name,
                                     size_pt=font.height / 20, color=color, bold=bool(font.bold),
                                     italic=bool(font.italic), underline=bool(font.underlined))
            summaries = state.styles.section_summaries(key_fn=lambda location: location.rsplit("!", 1)[0])
            state.emit(name, "Legacy saved formatting summary", summaries.get(name))
            workbook.unload_sheet(index)
    finally:
        workbook.release_resources()


def extract_excel_accessibility_metadata(file_path, extension):
    """Return bounded parent metadata and location-specific native evidence."""
    state = _Inspection(extension)
    try:
        if extension == ".xls":
            _extract_xls(state, file_path)
        else:
            _extract_ooxml(state, file_path)
    except (ValueError, KeyError, OSError, EOFError, RuntimeError, struct.error,
            ParseError, DefusedXmlException, zipfile.BadZipFile, xlrd.XLRDError) as exc:
        state.meta["coverage"] = "failed"
        state.note(f"Workbook inspection failed or exceeded its limits ({type(exc).__name__}).")
        state.meta["issues"].append({
            "code": "EXCEL_INSPECTION_INCOMPLETE", "severity": "warning",
            "message": "Native Excel inspection is incomplete; unavailable evidence is not proof of absence.",
        })
        log_event("[DOCUMENT_METADATA] Excel native inspection failed.", level=30,
                  extra={"error_type": type(exc).__name__})
    return state.finish()


def build_excel_evidence_chunks(evidence, file_name, max_characters):
    """Split native evidence without using physical print-page semantics."""
    header = f"{EXCEL_EVIDENCE_MARKER}\nWorkbook: {file_name}\nNative evidence segment (not a printed page).\n"
    available = max_characters - len(header)
    if available < 100:
        raise ValueError("Embedding budget is too small for Excel native evidence")
    chunks = []
    current = ""
    for item in evidence:
        content = item["content"]
        context = (
            f"Sheet: {item['sheet_name']}; Evidence: {item.get('kind', 'workbook coverage')}; "
            f"Cell/object: {item.get('location') or '(sheet/workbook)'}\n"
        )
        fragment_size = available - len(context)
        if fragment_size < 50:
            raise ValueError("Embedding budget is too small for Excel evidence locations")
        for start in range(0, len(content), fragment_size):
            piece = context + content[start:start + fragment_size]
            if current and len(current) + len(piece) + 2 > available:
                chunks.append(header + current)
                current = ""
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(header + current)
    return chunks


def is_excel_native_inspection_question(question, file_names=None):
    """Keep native inspection out of data-only analysis, not mixed calculation requests."""
    if file_names is not None:
        extensions = [os.path.splitext(str(name or ""))[1].lower() for name in file_names]
        if not extensions or any(extension not in (".xlsx", ".xlsm", ".xls") for extension in extensions):
            return False
    text = str(question or "").lower()
    if re.search(r"\b(sum|average|median|aggregate|calculate|compute)\b|\btotal\s+(sales|revenue|tax|amount|cost)", text):
        return False
    return bool(re.search(
        r"\b(alt[- ]?text|decorative|accessibility|formatting|font(?:s| size| colo[u]?r)?|"
        r"headers?|footers?|page setup|print titles?|print areas?|merged cells?|"
        r"hidden (?:rows?|columns?|sheets?)|freeze panes?|conditional formatting|"
        r"document (?:title|properties)|workbook properties|keywords|"
        r"(?:cell |threaded )?(?:comments|notes)|author(?:s|ship)?|"
        r"checkbox(?:es)?|check boxes|fill colo[u]?r|number formats?)\b", text,
    ))
