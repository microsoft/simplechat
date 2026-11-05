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

from excel_workbook_reader import (
    EXCEL_WORKBOOK_SCHEMA_VERSION,
    ExcelWorkbookReader,
    cell_coordinates,
)
from functions_appinsights import log_event
from functions_document_style import StyleAccumulator, format_style_inventory_for_chat
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
    def __init__(self, extension, record_sink=None, progress_callback=None):
        self.meta = {
            "format": extension.lstrip("."), "schema_version": EXCEL_WORKBOOK_SCHEMA_VERSION,
            "coverage": "partial", "coverage_notes": list(EXCEL_COVERAGE_NOTES),
            "properties": {}, "sheets": [], "comments": [], "objects": [], "issues": [],
            "tables": [], "defined_names": [], "hyperlinks": [], "validations": [],
            "property_records": [], "custom_properties": [], "extended_properties": [],
            "comment_summary": {
                "legacy_notes": 0, "thread_roots": 0, "replies": 0,
                "thread_messages": 0, "compatibility_copies": 0, "raw_records": 0,
            },
        }
        self.record_sink = record_sink
        self.progress_callback = progress_callback
        self.evidence = []
        self.evidence_chars = 0
        self.bytes_read = 0
        self.records = 0
        self.cells = 0
        self.cache = {}
        self.parent_record_bytes = 0
        self.image_placement_count = 0
        self.image_map_bytes = 0
        self.styles = StyleAccumulator("sheet_cell")
        self.counts = Counter()

    def note(self, message):
        if message not in self.meta["coverage_notes"] and len(self.meta["coverage_notes"]) < 40:
            self.meta["coverage_notes"].append(message)
            inventory = self.meta.get("style_inventory")
            if inventory is not None and message not in inventory["coverage_notes"]:
                inventory["coverage_notes"].append(message)

    def clean(self, value):
        text = str(value) if value is not None else ""
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
        record = {"sheet": sheet, **record}
        if collection == "objects" and record.get("media_part"):
            if self.image_placement_count < 100:
                images = self.meta.setdefault("image_locations", {})
                existing = images.get(record["media_part"])
                image = dict(existing) if existing else {
                    "alt_text": str(record.get("alt_text") or "")[:1000],
                    "title_text": str(record.get("title") or "")[:1000],
                    "is_decorative": record.get("is_decorative"), "sheet_name": sheet,
                    "cell": record.get("cell"), "object_id": record.get("id"), "placements": [],
                }
                image["placements"] = list(image["placements"]) + [{
                    "sheet_name": sheet, "cell": record.get("cell"), "object_id": record.get("id"),
                }]
                size = len(json.dumps(image, ensure_ascii=True).encode())
                previous = len(json.dumps(existing, ensure_ascii=True).encode()) if existing else 0
                if self.image_map_bytes + size - previous <= 65536:
                    images[record["media_part"]] = image
                    self.image_map_bytes += size - previous
                    self.image_placement_count += 1
                else:
                    self.note("The embedded-image placement preview reached its byte limit; full native object records are separate.")
            else:
                self.note("The embedded-image analysis placement map is limited to 100 anchors; the full object inventory is separate.")
        if self.record_sink is not None:
            self.record_sink(collection, record)
        self.emit(sheet, collection, record)
        if self.records >= EXCEL_MAX_RECORDS:
            self.note("Parent native records were truncated at the record limit; full inventory requires its paged source.")
            return
        self.records += 1
        preview = self.preview(record)
        record_bytes = len(json.dumps(preview, ensure_ascii=True).encode("utf-8"))
        if self.parent_record_bytes + record_bytes <= EXCEL_MAX_PARENT_BYTES // 2:
            self.meta.setdefault(collection, []).append(preview)
            self.parent_record_bytes += record_bytes
        else:
            self.note("Parent native inventory was capped; location-specific search evidence and full inventory are separate.")

    def preview(self, value):
        if isinstance(value, dict):
            result = {key: self.preview(item) for key, item in value.items()}
            for key, item in value.items():
                if (
                    isinstance(item, str) and len(item) > EXCEL_MAX_TEXT
                    or isinstance(item, list) and len(item) > 100
                ):
                    result[f"{key}_truncated"] = True
            return result
        if isinstance(value, list):
            if len(value) > 100:
                self.note("Parent native collection previews show at most 100 entries; use the full inventory for the remainder.")
            return [self.preview(item) for item in value[:100]]
        if isinstance(value, str):
            return self.clean(value)
        return value

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
        reserve = min(8192, EXCEL_MAX_PARENT_BYTES // 6)
        while len(json.dumps(self.meta, ensure_ascii=True).encode("utf-8")) > EXCEL_MAX_PARENT_BYTES - reserve:
            style = self.meta["style_inventory"]
            candidates = [
                self.meta[key] for key in (
                    "comments", "objects", "sheets", "tables", "defined_names", "hyperlinks",
                    "validations", "property_records", "custom_properties", "extended_properties",
                ) if self.meta[key]
            ]
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

        self.meta["inventory_coverage"] = {
            key: {
                "observed": count, "retained": len(self.meta.get(key) or []),
                "complete": count == len(self.meta.get(key) or []) and not any(
                    any(name.endswith("_truncated") and value is True for name, value in item.items())
                    for item in self.meta.get(key) or []
                ),
            }
            for key, count in self.counts.items()
        }

        def coverage_content():
            return f"{EXCEL_EVIDENCE_MARKER}\nWorkbook properties and inspection coverage:\n" + json.dumps({
                "properties": self.meta["properties"],
                "coverage": self.meta["coverage"],
                "coverage_notes": self.meta["coverage_notes"],
                "observed_counts": self.meta["observed_counts"],
                "comment_summary": self.meta["comment_summary"],
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
             "category", "created", "modified", "lastModifiedBy", "identifier",
             "version", "revision", "lastPrinted", "contentStatus"}
    properties = {_local(item.tag): state.clean(item.text) for item in root if _local(item.tag) in names}
    state.meta["properties"] = properties
    for key in ("title", "subject", "description", "language", "category"):
        state.meta[key] = properties.get(key, "")
    state.meta["authors"] = [part.strip() for part in re.split(r"[;,]", properties.get("creator", "")) if part.strip()]
    state.meta["keywords"] = [part.strip() for part in re.split(r"[;,]", properties.get("keywords", "")) if part.strip()]
    for element in root:
        if _local(element.tag) in names:
            state.record("property_records", "(workbook)", {
                "kind": "core", "name": _local(element.tag), "value": element.text or "",
            })


def _additional_properties(state, archive, relationships):
    for kind, fallback, collection in (
        ("extended-properties", "docProps/app.xml", "extended_properties"),
        ("custom-properties", "docProps/custom.xml", "custom_properties"),
    ):
        part = next((path for relation, path in relationships.values() if relation == kind), fallback)
        root = state.xml(archive, part)
        if root is None:
            continue
        for element in root:
            name = element.get("name") or _local(element.tag)
            children = list(element)
            values = [
                {"type": _local(child.tag), "value": _text(child)}
                for child in children
            ]
            state.record(collection, "(workbook)", {
                "name": name, "value": values if children else element.text or "",
                "property_id": element.get("pid"),
            })


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


def normalize_excel_comments(records):
    """Correlate only identifiable same-cell compatibility copies of real threads."""
    threaded, notes = [], []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("A stored Excel comment record is invalid.")
        record = dict(item)
        (threaded if record.get("kind") == "threaded_comment" else notes).append(record)
    roots = {
        (record.get("sheet"), str(record["id"]).casefold()): record
        for record in threaded if record.get("id") and not record.get("parent_id")
    }
    summary = {
        "legacy_notes": 0, "thread_roots": sum(not record.get("parent_id") for record in threaded),
        "replies": sum(bool(record.get("parent_id")) for record in threaded),
        "thread_messages": len(threaded), "compatibility_copies": 0,
        "raw_records": len(threaded) + len(notes),
    }
    genuine_notes = []
    for note in notes:
        author = str(note.get("author") or "")
        root = roots.get((note.get("sheet"), author[3:].strip().casefold())) if author.lower().startswith("tc=") else None
        text = str(note.get("text") or "")
        compatibility = (
            root is not None and root.get("cell") == note.get("cell")
            and text.lstrip().casefold().startswith("[threaded comment]")
            and bool(str(root.get("text") or "").strip())
            and str(root["text"]).strip() in text
        )
        if compatibility:
            summary["compatibility_copies"] += 1
        else:
            genuine_notes.append(note)
    summary["legacy_notes"] = len(genuine_notes)
    return threaded + genuine_notes, summary


def format_excel_comment_for_chat(record):
    """Keep feedback, saved values, and unavailable fields separate in model evidence."""
    if record.get("record_fragment"):
        return (
            f"### Partial native record at {record.get('sheet')}!{record.get('cell')}\n"
            "This is an explicitly continued JSON record, not a complete comment. "
            "Use the supplied continuation cursor to read the remainder.\n"
            f"{record.get('record_json_fragment') or ''}"
        )
    location = f"{record.get('sheet', '?')}!{record.get('cell', '?')}"
    kind = "thread reply" if record.get("parent_id") else "thread root" if record.get("kind") == "threaded_comment" else "legacy note"
    saved = {
        "value": record.get("cell_value"), "value_type": record.get("cell_value_type"),
        "status": record.get("cell_value_status", "not inspected"),
        "formula": record.get("formula"), "cached_value_available": record.get("cached_value_available"),
    }
    details = {
        key: record.get(key) for key in ("author", "date", "id", "parent_id", "resolved")
    }
    text = (
        f"### Reviewer feedback: {kind} at {location}\n"
        f"Saved cell evidence (not the requested change): {json.dumps(saved, ensure_ascii=False)}\n"
        f"Saved comment fields (null means unknown): {json.dumps(details, ensure_ascii=False)}\n"
        f"Reviewer feedback text:\n{record.get('text') or ''}"
    )
    if record.get("text_truncated"):
        text += "\n[Parent text preview is shortened; retrieve the full native inventory text.]"
    return text


def excel_native_question_sections(question):
    text = str(question or "").lower()
    sections = []
    for section, expression in (
        ("comments", r"\b(comments?|notes?|reviewer|feedback|replies|threaded)\b"),
        ("custom_properties", r"\bcustom propert"),
        ("extended_properties", r"\b(extended propert|application propert|company|manager)\b"),
        ("property_records", r"\b(propert|metadata|authors?|keywords?|document title)"),
        ("tables", r"\b(tables?|columns?|schema|named ranges?)\b"),
        ("objects", r"\b(objects?|charts?|images?|pictures?|alt[- ]?text|decorative|shapes?)\b"),
        ("image_analyses", r"\b(images?|pictures?|figures?)\b"),
        ("hyperlinks", r"\b(hyperlinks?|links?)\b"),
        ("validations", r"\bvalidations?\b"),
        ("defined_names", r"\b(defined names?|named ranges?|print areas?|print titles?)\b"),
    ):
        if re.search(expression, text):
            sections.append(section)
    return sections or ["comments"]


def build_excel_native_chat_evidence(report, question, *, max_bytes=15000):
    """Include whole requested records before optional layout/style summaries."""
    metadata = report.get("accessibility_metadata") or {}
    inspection = report.get("excel_inspection") or {}
    page = inspection.get("page") or {}
    pages = inspection.get("pages") or ([page] if page else [])
    comments, counts = normalize_excel_comments(metadata.get("comments") or [])
    counts = metadata.get("comment_summary") or counts
    header = (
        f"{EXCEL_EVIDENCE_MARKER}\n"
        f"Workbook: {(report.get('document') or {}).get('file_name') or 'Selected workbook'}\n"
        f"Canonical comment counts: {json.dumps(counts, ensure_ascii=True)}\n"
        f"Native coverage: {metadata.get('coverage', 'unknown')}. "
        "Saved native state is not rendered appearance or a conformance certificate. "
        "Reviewer feedback is not the workbook's saved data. "
        "No formulas, macros, or external links were executed.\n"
    )
    parts, used, included, omitted = [header], len(header.encode("utf-8")), 0, 0

    def append(value, record=False):
        nonlocal used, included, omitted
        size = len(value.encode("utf-8")) + 2
        if used + size > max_bytes - 1024:
            if record:
                omitted += 1
            return False
        parts.append(value)
        used += size
        included += int(record)
        return True

    requested = excel_native_question_sections(question)
    for section in requested:
        section_page = next((item for item in pages if item.get("section") == section), {})
        records = section_page.get("records") if section_page else metadata.get(section)
        if section == "comments":
            records = section_page.get("records") if section_page else comments
        for record in records or []:
            content = format_excel_comment_for_chat(record) if section == "comments" else (
                f"### Saved native {section}\n{json.dumps(record, ensure_ascii=False)}"
            )
            append(content, record=True)
    for cell in inspection.get("cells") or []:
        append(
            f"### Saved cell {cell.get('sheet')}!{cell.get('cell')}\n{json.dumps(cell, ensure_ascii=True)}",
            record=True,
        )
    append(f"Saved workbook properties: {json.dumps(metadata.get('properties') or {}, ensure_ascii=True)}")
    if "image_analyses" in requested:
        append(
            "Image-analysis coverage (not saved alt text): "
            + json.dumps(metadata.get("image_analysis_summary") or {
                "status": "not_generated", "guidance": "Configured image analysis may require document reprocessing; saved native object metadata is separate.",
            }, ensure_ascii=True)
        )
    for sheet in metadata.get("sheets") or []:
        append(
            f"Sheet {sheet.get('name')}: state={sheet.get('state')}; "
            f"headers/footers={json.dumps(sheet.get('header_footer') or {}, ensure_ascii=True)}"
        )
    for note in metadata.get("coverage_notes") or []:
        append(f"Coverage limitation: {note}")
    if re.search(r"\b(font|format|style|size|colou?r)", str(question or ""), re.IGNORECASE):
        for line in format_style_inventory_for_chat(report.get("style_inventory") or metadata.get("style_inventory")):
            append(line)
    incomplete = bool(any(item.get("has_more") for item in pages) or omitted)
    if incomplete:
        parts.append(
            f"Returned {included} complete records/fragments in this bounded handoff; "
            f"{omitted} additional selected records did not fit. Do not call this an exhaustive list. "
            f"Native page continuations: {json.dumps({item['section']: item.get('next_cursor') for item in pages if item.get('has_more')}, ensure_ascii=True)}."
        )
    return {
        "summary": "\n\n".join(parts), "returned_records": included,
        "records_omitted": omitted, "partial": incomplete,
        "next_cursor": page.get("next_cursor"), "total_records": page.get("total_records"),
        "worksheet_data_read": bool(inspection.get("cells")) or any("cell_value_status" in record for record in comments),
    }


def has_excel_native_inspection_intent(question, file_names=None):
    """Recognize native requirements independently from a simultaneous calculation."""
    text = re.sub(
        r"\b(sum|average|median|aggregate|calculate|compute)\b|\btotal\s+(sales|revenue|tax|amount|cost)",
        "", str(question or ""), flags=re.IGNORECASE,
    )
    return is_excel_native_inspection_question(text, file_names=file_names)


def merge_excel_native_evidence(result, native_result, question):
    """Keep both evidence kinds within the existing per-source summary budget."""
    if not native_result:
        return result
    result = dict(result)
    native_by_source = {
        envelope["document_id"]: envelope for envelope in native_result.get("evidence_envelopes") or []
    }
    reports = {
        citation.get("function_arguments", {}).get("document_id"): citation.get("function_result")
        for citation in native_result.get("agent_citations") or []
        if citation.get("function_name") == "get_document_accessibility_report"
    }
    envelopes = []
    for existing in result.get("evidence_envelopes") or []:
        envelope = dict(existing)
        native = native_by_source.get(envelope.get("document_id"))
        if native is None:
            envelopes.append(envelope)
            continue
        summary = str(envelope.get("summary") or "")
        computed_lines, computed_size = [], 0
        for line in summary.splitlines(keepends=True):
            size = len(line.encode("utf-8"))
            if computed_size + size > 10000:
                break
            computed_lines.append(line)
            computed_size += size
        computed = "".join(computed_lines)
        computed_shortened = computed != summary
        report = reports.get(envelope["document_id"])
        if isinstance(report, dict):
            evidence = build_excel_native_chat_evidence(
                report, question, max_bytes=max(2500, 15000 - computed_size),
            )
            native_summary = evidence["summary"]
            native_partial = evidence["partial"]
        else:
            native_summary = str(native.get("summary") or "Native inspection was unavailable.")
            native_partial = True
        envelope["summary"] = (
            f"{native_summary}\n\nComputed tabular evidence:\n{computed}"
            + ("\n[Computed summary is shortened; the full tool result remains available.]" if computed_shortened else "")
        )
        envelope["coverage"] = {
            **dict(envelope.get("coverage") or {}),
            "native_inspection_included": True, "native_records_partial": native_partial,
            "native_status": native.get("status"), "computed_summary_shortened": computed_shortened,
        }
        envelope["citations"] = list(envelope.get("citations") or []) + list(native.get("citations") or [])
        envelopes.append(envelope)
    result["evidence_envelopes"] = envelopes
    result["agent_citations"] = list(result.get("agent_citations") or []) + list(native_result.get("agent_citations") or [])
    return result


def _comments(state, archive, sheet, relationships, persons):
    threaded, notes = [], []
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
            record = {
                "sheet": sheet,
                "kind": "note" if name == "comment" else "threaded_comment",
                "cell": state.clean(item.get("ref")), "text": text,
                "author": author, "date": state.clean(item.get("dT")) or None,
                "id": state.clean(item.get("id")) or None,
                "parent_id": state.clean(item.get("parentId")) or None,
                "resolved": _on(item.get("done")) if "done" in item.attrib else None,
                "source_part": path,
            }
            (notes if name == "comment" else threaded).append(record)
    records, summary = normalize_excel_comments(threaded + notes)
    for key, count in summary.items():
        state.meta["comment_summary"][key] += count
    return records


def _chart_content(state, archive, chart_part):
    root = state.xml(archive, chart_part, required=True)
    series = []
    for element in root.iter():
        if _local(element.tag) != "ser":
            continue
        values = []
        references = []
        for item in element.iter():
            if _local(item.tag) == "f":
                references.append(item.text or "")
            elif _local(item.tag) == "pt":
                value = _first(item, "v")
                values.append({"index": item.get("idx"), "value": _text(value)})
        series.append({
            "references": references, "cached_points": values,
            "cached_point_count": len(values),
        })
    return {
        "chart_part": chart_part,
        "chart_text": "\n".join(
            item.text for item in root.iter() if _local(item.tag) == "t" and item.text
        ),
        "series": series,
        "coverage": "Saved chart text, references and caches only; chart formulas are not evaluated.",
    }


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
                    "alt_text": shape.get("alt") or "", "title": _attr(shape, "title") or "",
                    "saved_control_properties": {
                        _local(item.tag): _text(item) for item in client
                    } if client is not None else {},
                    "is_decorative": None, "alt_inspected": True,
                })
            state.note("VML decorative status is unavailable; absent marking remains unknown.")
            continue
        parents = {child: parent for parent in root.iter() for child in parent}
        drawing_relationships = state.rels(archive, path)
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
                record = {
                    "type": object_type, "id": state.clean(properties.get("id")),
                    "name": state.clean(properties.get("name")), "cell": cell,
                    "alt_text": properties.get("descr") or "", "title": properties.get("title") or "",
                    "is_decorative": _on(decorative.get("val")) if decorative is not None else None,
                    "alt_inspected": True,
                    "text": "\n".join(
                        item.text for item in owner.iter()
                        if _local(item.tag) == "t" and item.text
                    ) if owner is not None else "",
                    "drawing_part": path,
                }
                chart = _first(owner, "chart") if owner is not None else None
                if chart is not None:
                    relationship = drawing_relationships.get(_attr(chart, "id"))
                    if relationship and relationship[0] == "chart":
                        record.update(_chart_content(state, archive, relationship[1]))
                    else:
                        record["chart_coverage"] = "The saved chart part was unavailable."
                        state.note("A drawing referenced a chart without an available internal chart relationship.")
                image = _first(owner, "blip") if owner is not None else None
                if image is not None:
                    relationship = drawing_relationships.get(_attr(image, "embed"))
                    if relationship and relationship[0] == "image":
                        record["media_part"] = relationship[1]
                state.record("objects", sheet, record)


def _sheet(state, archive, entry, path, kind, definitions, reader, persons):
    name = state.clean(entry.get("name"))[:128]
    relationships = state.rels(archive, path)
    comments = _comments(state, archive, name, relationships, persons)
    saved_styles = {}

    def inspect_styles(row, cells, attributes):
        if state.progress_callback is not None and row % 1024 == 0:
            state.progress_callback()
        for cell in cells.values():
            if state.cells >= EXCEL_MAX_CELLS:
                state.note(f"Cell formatting inspection sampled the first {EXCEL_MAX_CELLS} saved cells.")
                return
            state.cells += 1
            style_index = cell["style_id"]
            spec = definitions[style_index] if 0 <= style_index < len(definitions) else {}
            if not spec:
                state.note("Some cell style references could not be resolved.")
            reference = cell["cell"]
            state.styles.add(
                f"{name}!{reference}", state.clean(cell["value"])[:60],
                **{key: spec.get(key) for key in ("font", "size_pt", "color", "bold", "italic", "underline")},
            )
            if style_index not in saved_styles:
                if len(saved_styles) >= 100:
                    state.note("Per-sheet formatting evidence was capped at 100 distinct cell styles.")
                    continue
                saved_styles[style_index] = {"style_id": style_index, "cells": [], "observed_cell_count": 0, **spec}
            group = saved_styles[style_index]
            group["observed_cell_count"] += 1
            if len(group["cells"]) < 30:
                group["cells"].append(reference)
            else:
                state.note("Style location lists show the first 30 cells per saved style per sheet.")

    sheet, cells = reader.scan_sheet(
        name, row_callback=inspect_styles, wanted_cells={record["cell"] for record in comments},
    )
    expressions = sheet.get("header_footer", {}).get("expressions") or {}
    if expressions:
        sheet["header_footer"]["sections"] = {
            key: _header_sections(value) for key, value in expressions.items()
        }
    for record in sheet["layout"]:
        style_id = record.get("style") if record["type"] == "col" else record.get("s")
        if style_id is not None and 0 <= int(style_id) < len(definitions):
            record["saved_style"] = definitions[int(style_id)]
    state.meta["sheets"].append(state.preview(sheet))
    state.meta["scanned_sheet_count"] = state.meta.get("scanned_sheet_count", 0) + 1
    state.meta["scanned_cells"] = state.meta.get("scanned_cells", 0) + sheet["scanned_cells"]
    state.emit(name, "Sheet layout, headers and footers (raw Excel control codes; not evaluated)", sheet)
    for table in sheet["tables"]:
        state.record("tables", name, table)
    for key in ("hyperlinks", "validations"):
        for record in sheet.get(key) or []:
            state.record(key, name, record)
    for record in comments:
        cell = cells[record["cell"]]
        row, column = cell_coordinates(record["cell"])
        record.update({
            "cell_value": cell["value"], "cell_value_raw": cell["raw_value"],
            "cell_value_type": cell["value_type"], "cell_value_status": cell["value_status"],
            "formula": cell["formula"], "formula_type": cell["formula_type"],
            "formula_reference": cell["formula_reference"],
            "cached_value_available": cell["cached_value_available"],
            "number_format": cell.get("number_format"),
            "table_ids": [
                table["id"] for table in sheet["tables"]
                if table["min_row"] <= row <= table["max_row"]
                and table["min_column"] <= column <= table["max_column"]
            ],
        })
        state.record("comments", name, record)
    _objects(state, archive, name, relationships)
    if sheet.get("unsupported_controls") or any(kind in ("oleObject", "activeXControl", "control") for kind, _ in relationships.values()):
        state.note("This workbook contains unsupported OLE/ActiveX controls; their alt text was not inspected.")
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
        _additional_properties(state, archive, relationships)
        workbook = state.xml(archive, workbook_path, required=True)
        workbook_rels = state.rels(archive, workbook_path)
        definitions = _style_definitions(state, archive, workbook_rels)
        state.emit("(workbook)", "Saved default cell style", definitions[0])
        persons = {}
        for kind, path in workbook_rels.values():
            if kind in ("person", "persons"):
                root = state.xml(archive, path, required=True)
                persons = {element.get("id"): state.clean(element.get("displayName"))
                           for element in root.iter() if _local(element.tag) == "person"}
        sheets_root = _first(workbook, "sheets")
        entries = list(sheets_root) if sheets_root is not None else []
        state.meta["sheet_count"] = len(entries)
        if len(entries) > EXCEL_MAX_SHEETS:
            state.note(f"Only the first {EXCEL_MAX_SHEETS} sheets were inspected.")
        with ExcelWorkbookReader(archive, extension="." + state.meta["format"]) as reader:
            for entry in entries[:EXCEL_MAX_SHEETS]:
                relationship = workbook_rels.get(_attr(entry, "id"))
                if not relationship or relationship[0] not in ("worksheet", "chartsheet"):
                    state.note("A sheet relationship is unsupported or unavailable.")
                    continue
                try:
                    _sheet(state, archive, entry, relationship[1], relationship[0], definitions, reader, persons)
                except (ValueError, KeyError, OSError, ParseError, DefusedXmlException, zipfile.BadZipFile) as exc:
                    state.note(f"A sheet could not be completely inspected ({type(exc).__name__}).")
                    state.meta.setdefault("incomplete_sheets", []).append(state.clean(entry.get("name")))
                    log_event("[DOCUMENT_METADATA] Excel sheet inspection incomplete.", level=30,
                              extra={"error_type": type(exc).__name__})
            state.meta["xml_scan_bytes"] = reader.scanned_xml_bytes
            for note in reader.coverage_notes:
                state.note(note)
        defined_names = [
            {"name": state.clean(item.get("name")), "sheet_index": item.get("localSheetId"),
             "expression": item.text or "", "hidden": item.get("hidden") in ("1", "true")}
            for item in workbook.iter() if _local(item.tag) == "definedName"
        ]
        for record in defined_names:
            state.record("defined_names", "(workbook)", record)
        state.meta["print_defined_names"] = [
            record for record in defined_names if record["name"] in ("_xlnm.Print_Titles", "_xlnm.Print_Area")
        ][:EXCEL_MAX_SHEETS * 2]
        if state.meta["print_defined_names"]:
            state.emit("(workbook)", "Print titles and print areas (not header/footer text)", state.meta["print_defined_names"])
        state.meta["table_count"] = state.counts["tables"]


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
                value = sheet.cell_value(row, column) if row < sheet.nrows and column < sheet.row_len(row) else None
                state.meta["comment_summary"]["raw_records"] += 1
                state.meta["comment_summary"]["legacy_notes"] += 1
                state.record("comments", name, {
                    "kind": "note", "cell": f"{get_column_letter(column + 1)}{row + 1}",
                    "text": note.text, "author": state.clean(note.author),
                    "date": None, "resolved": None,
                    "cell_value": value, "cell_value_status": "blank" if value is None or value == "" else "saved",
                    "formula": None, "cached_value_available": None,
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


def extract_excel_accessibility_metadata(file_path, extension, *, record_sink=None, progress_callback=None):
    """Return bounded parent metadata and location-specific native evidence."""
    state = _Inspection(extension, record_sink=record_sink, progress_callback=progress_callback)
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
        r"checkbox(?:es)?|check boxes|fill colo[u]?r|number formats?|"
        r"custom properties|metadata|named ranges?|defined names?|hyperlinks?|data validation|"
        r"cell values?|cell formulas?|saved formulas?|cached values?)\b", text,
    ) or re.search(r"\bcells?\s+[a-z]{1,3}[1-9]\d*|!\$?[a-z]{1,3}\$?[1-9]\d*", text))
