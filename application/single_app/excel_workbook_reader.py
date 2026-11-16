# excel_workbook_reader.py
"""Read saved workbook cells and table boundaries without executing Excel."""

from collections import Counter, OrderedDict
from copy import deepcopy
import hashlib
import io
import json
import math
import os
import posixpath
import re
import zipfile
from threading import RLock

from defusedxml.ElementTree import iterparse
from defusedxml.ElementTree import fromstring
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel
import xlrd

from functions_office_media import (
    OFFICE_ZIP_ALLOWED_COMPRESSION,
    OFFICE_ZIP_MAX_ENTRIES,
    _read_zip_entry_bounded,
)


EXCEL_WORKBOOK_SCHEMA_VERSION = "2.0"
EXCEL_XML_PART_MAX_BYTES = 16 * 1024 * 1024
EXCEL_SHEET_MAX_BYTES = 256 * 1024 * 1024
EXCEL_SCAN_MAX_BYTES = 512 * 1024 * 1024
EXCEL_SHARED_STRINGS_MAX_CHARS = 64 * 1024 * 1024
EXCEL_MAX_SHEETS = 100
EXCEL_MAX_TABLES = 5000
EXCEL_MAX_PREVIEW_ROWS = 500
EXCEL_PREVIEW_MAX_BYTES = 1024 * 1024
EXCEL_PREVIEW_MAX_COLUMNS = 128
EXCEL_MAX_COLUMNS = 16384
EXCEL_MAX_ROWS = 1048576
_INTEGER = re.compile(r"^[+-]?\d+$")
_CELL = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9]\d*)$")
_LAYOUT_ELEMENTS = {
    "mergeCell", "col", "pane", "pageMargins", "pageSetup", "printOptions",
    "sheetFormatPr", "sheetView", "autoFilter", "sheetPr",
}
_MANIFEST_CACHE = OrderedDict()
_MANIFEST_LOCK = RLock()
_MANIFEST_CACHE_MAX_BYTES = 16 * 1024 * 1024


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def local_attribute(element, name, default=""):
    return next((value for key, value in element.attrib.items() if local_name(key) == name), default)


def first_element(element, name):
    return next((child for child in element.iter() if local_name(child.tag) == name), None)


def element_text(element):
    return "".join(element.itertext()) if element is not None else ""


def cell_coordinates(reference):
    match = _CELL.fullmatch(str(reference or "").upper())
    if not match:
        raise ValueError("Invalid Excel cell reference.")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(match[2])
    if column > EXCEL_MAX_COLUMNS or row > EXCEL_MAX_ROWS:
        raise ValueError("Excel cell reference is outside worksheet bounds.")
    return row, column


def bounded_range(reference):
    try:
        bounds = range_boundaries(str(reference or "").replace("$", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid Excel table range.") from error
    low_column, low_row, high_column, high_row = bounds
    if (
        any(type(value) is not int for value in bounds)
        or not 1 <= low_column <= high_column <= EXCEL_MAX_COLUMNS
        or not 1 <= low_row <= high_row <= EXCEL_MAX_ROWS
    ):
        raise ValueError("Excel table range is outside worksheet bounds.")
    return bounds


def _range_reference(low_column, low_row, high_column, high_row):
    return f"{get_column_letter(low_column)}{low_row}:{get_column_letter(high_column)}{high_row}"


def _blank_cell(reference):
    return {
        "cell": reference, "value": None, "raw_value": None, "value_type": "blank",
        "value_status": "blank", "formula": None, "formula_type": None,
        "formula_reference": None, "cached_value_available": True, "style_id": 0,
    }


class _BoundedXmlStream:
    def __init__(self, stream, reader, limit):
        self.stream = stream
        self.reader = reader
        self.limit = limit
        self.bytes_read = 0

    def read(self, size=-1):
        size = min(65536, size) if size >= 0 else 65536
        data = self.stream.read(size)
        self.bytes_read += len(data)
        self.reader.scanned_xml_bytes += len(data)
        if self.bytes_read > self.limit or self.reader.scanned_xml_bytes > EXCEL_SCAN_MAX_BYTES:
            raise ValueError("Excel XML scan exceeded its supported byte limit.")
        return data


class _Region:
    """An inferred occupied region, retaining samples but never all its rows."""

    def __init__(self, row, low_column, high_column):
        self.low_row = row
        self.high_row = row
        self.low_column = low_column
        self.high_column = high_column
        self.row_count = 0
        self.samples = []
        self.header_signature = None
        self.repeated_header_rows = []
        self.repeated_header_count = 0
        self.ambiguous = False
        self._last_row = None

    def observe(self, row, cells):
        if self._last_row == row:
            return
        self._last_row = row
        self.high_row = row
        self.row_count += 1
        occupied = {
            column: cell for column, cell in cells.items()
            if self.low_column <= column <= self.high_column
        }
        if len(self.samples) < 8:
            self.samples.append((row, deepcopy(occupied)))
            self._choose_header()
        signature = self._signature(occupied)
        if (
            self.header_signature is not None and signature == self.header_signature
            and row != self.header_row
        ):
            self.repeated_header_count += 1
            if len(self.repeated_header_rows) < 100:
                self.repeated_header_rows.append(row)

    def _signature(self, cells):
        return tuple(
            (cells.get(column) or {}).get("value")
            for column in range(self.low_column, self.high_column + 1)
        )

    def _choose_header(self):
        self.header_row = None
        self.title_rows = []
        self.header_status = "absent"
        if not self.samples:
            return
        index = 0
        if len(self.samples[0][1]) == 1 and self.high_column > self.low_column:
            if len(self.samples) < 2:
                return
            self.title_rows.append(self.samples[0][0])
            index = 1
        row, cells = self.samples[index]
        values = self._signature(cells)
        nonblank = [value for value in values if value is not None and value != ""]
        if not nonblank or not all(isinstance(value, str) for value in nonblank):
            return
        if len(nonblank) == 1:
            later = self.samples[index + 1:]
            if not any(
                any(cell["value_type"] not in ("text", "blank") for cell in sample.values())
                for _, sample in later
            ):
                self.header_status = "ambiguous"
                return
        self.header_row = row
        self.header_status = "ambiguous" if self.ambiguous else "inferred"
        self.header_signature = values

    def descriptor(self, sheet):
        self._choose_header()
        header_cells = next((cells for row, cells in self.samples if row == self.header_row), {})
        labels = []
        for column in range(self.low_column, self.high_column + 1):
            value = (header_cells.get(column) or {}).get("value")
            labels.append(str(value) if value is not None and value != "" else get_column_letter(column))
        names = _unique_column_names(labels, self.low_column)
        reference = _range_reference(self.low_column, self.low_row, self.high_column, self.high_row)
        identity = hashlib.sha256(f"{sheet['part']}\0{reference}".encode()).hexdigest()[:20]
        return {
            "id": f"region-{identity}", "name": f"Data block {reference}", "sheet": sheet["name"],
            "origin": "inferred", "range": reference, "min_row": self.low_row,
            "max_row": self.high_row, "min_column": self.low_column,
            "max_column": self.high_column, "header_row": self.header_row,
            "header_row_count": int(self.header_row is not None), "header_status": self.header_status,
            "title_rows": self.title_rows, "totals_row_count": 0,
            "data_start_row": (self.header_row + 1) if self.header_row else self.low_row,
            "data_end_row": self.high_row,
            "row_count": self.row_count - len(self.title_rows) - int(self.header_row is not None) - self.repeated_header_count,
            "repeated_header_rows": self.repeated_header_rows,
            "repeated_header_count": self.repeated_header_count,
            "header_signature": list(self.header_signature) if self.header_signature is not None else None,
            "columns": [
                {"id": get_column_letter(column), "name": name, "column": column}
                for column, name in zip(range(self.low_column, self.high_column + 1), names)
            ],
        }


def _unique_column_names(labels, low_column):
    counts = Counter(labels)
    return [
        f"{label} [{get_column_letter(low_column + index)}]" if counts[label] > 1 else label
        for index, label in enumerate(labels)
    ]


class _Regions:
    def __init__(self):
        self.active = []
        self.finished = []
        self.last_row = None

    def add(self, row, cells):
        occupied = sorted(
            column for column, cell in cells.items()
            if cell["value_status"] != "blank"
        )
        if not occupied:
            self._close()
            self.last_row = row
            return
        if self.last_row is not None and row > self.last_row + 1:
            self._close()
        runs = []
        start = end = occupied[0]
        for column in occupied[1:]:
            if column == end + 1:
                end = column
            else:
                runs.append((start, end))
                start = end = column
        runs.append((start, end))
        touched = []
        for low, high in runs:
            matches = [region for region in self.active if low <= region.high_column and high >= region.low_column]
            if len(matches) == 1:
                region = matches[0]
                region.low_column = min(region.low_column, low)
                region.high_column = max(region.high_column, high)
            elif not matches:
                region = _Region(row, low, high)
                self.active.append(region)
            else:
                region = matches[0]
                region.ambiguous = True
                for other in matches[1:]:
                    self.active.remove(other)
                    self.finished.append(other)
            if region not in touched:
                touched.append(region)
        for region in list(self.active):
            if region not in touched:
                self.active.remove(region)
                self.finished.append(region)
        for region in touched:
            region.observe(row, cells)
        self.last_row = row
        if len(self.active) + len(self.finished) > EXCEL_MAX_TABLES:
            raise ValueError("Workbook contains more supported data regions than can be inspected.")

    def _close(self):
        self.finished.extend(self.active)
        self.active = []

    def finish(self, sheet):
        self._close()
        return [region.descriptor(sheet) for region in self.finished]


class ExcelWorkbookReader:
    """A bounded source reader shared by inspection, previews, and analytical replay."""

    def __init__(self, source, extension=None):
        self.source = source
        self.extension = (extension or os.path.splitext(os.fspath(source))[1] if isinstance(source, (str, os.PathLike)) else extension or ".xlsx").lower()
        self.archive = None
        self.legacy = None
        self._owns_archive = not isinstance(source, zipfile.ZipFile)
        self._xml_cache = {}
        self._shared_strings = None
        self._number_formats = None
        self._manifest = None
        self._sheet_cache = {}
        self.scanned_xml_bytes = 0
        self.epoch = CALENDAR_WINDOWS_1900
        self.coverage_notes = []
        if self.extension == ".xls":
            if isinstance(source, (bytes, bytearray)):
                self.legacy = xlrd.open_workbook(file_contents=bytes(source), on_demand=True, formatting_info=True, ragged_rows=True)
            else:
                self.legacy = xlrd.open_workbook(source, on_demand=True, formatting_info=True, ragged_rows=True)
            self.sheets = [
                {"name": self.legacy.sheet_names()[index], "part": f"biff-sheet-{index}", "index": index,
                 "type": "worksheet", "state": self.legacy.sheet_by_index(index).visibility}
                for index in range(min(self.legacy.nsheets, EXCEL_MAX_SHEETS))
            ]
            self.workbook_relationships = {}
        else:
            self.archive = source if isinstance(source, zipfile.ZipFile) else zipfile.ZipFile(
                io.BytesIO(bytes(source)) if isinstance(source, (bytes, bytearray)) else source
            )
            names = self.archive.namelist()
            if len(names) > OFFICE_ZIP_MAX_ENTRIES or len(names) != len(set(names)):
                self.close()
                raise ValueError("Invalid or oversized workbook package.")
            relationships = self.relationships("")
            workbook_part = next((value["part"] for value in relationships.values() if value["kind"] == "officeDocument" and not value["external"]), "xl/workbook.xml")
            root = self.read_xml(workbook_part)
            self.workbook_relationships = self.relationships(workbook_part)
            properties = first_element(root, "workbookPr")
            if properties is not None and properties.get("date1904") in ("1", "true"):
                self.epoch = CALENDAR_MAC_1904
            self.sheets = []
            entries = first_element(root, "sheets")
            entries = list(entries) if entries is not None else []
            if len(entries) > EXCEL_MAX_SHEETS:
                self.coverage_notes.append(f"Only the first {EXCEL_MAX_SHEETS} sheets were inspected.")
            for entry in entries[:EXCEL_MAX_SHEETS]:
                relation = self.workbook_relationships.get(local_attribute(entry, "id"))
                if not relation or relation["external"] or relation["kind"] not in ("worksheet", "chartsheet"):
                    self.coverage_notes.append("A sheet relationship was unavailable or unsupported.")
                    continue
                if not entry.get("name") or len(entry.get("name")) > 128:
                    raise ValueError("A worksheet name exceeds its supported bound.")
                self.sheets.append({
                    "name": entry.get("name", ""), "part": relation["part"],
                    "type": relation["kind"], "state": entry.get("state", "visible"),
                })

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self.archive is not None and self._owns_archive:
            self.archive.close()
        if self.legacy is not None:
            self.legacy.release_resources()

    @property
    def sheet_names(self):
        return [sheet["name"] for sheet in self.sheets]

    def read_xml(self, part, required=True):
        if part in self._xml_cache:
            return self._xml_cache[part]
        if part not in self.archive.namelist():
            if not required:
                return None
            raise ValueError("A required workbook part is missing.")
        data = _read_zip_entry_bounded(self.archive, part, EXCEL_XML_PART_MAX_BYTES)
        if data is None:
            raise ValueError("Workbook metadata XML exceeds its supported byte limit.")
        self.scanned_xml_bytes += len(data)
        if self.scanned_xml_bytes > EXCEL_SCAN_MAX_BYTES:
            raise ValueError("Excel XML scan exceeded its supported byte limit.")
        root = fromstring(data)
        self._xml_cache[part] = root
        return root

    def relationships(self, part):
        path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        root = self.read_xml(path, required=False)
        result = {}
        for element in root if root is not None else []:
            target = local_attribute(element, "Target")
            external = local_attribute(element, "TargetMode").lower() == "external"
            resolved = None
            if not external:
                if any(character in target for character in ("\\", ":", "?", "#")):
                    self.coverage_notes.append("Invalid package relationship targets were not followed.")
                    continue
                resolved = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(part), target))
                if resolved.startswith("../") or resolved in ("..", ".", ""):
                    self.coverage_notes.append("Out-of-package relationship targets were not followed.")
                    continue
            result[local_attribute(element, "Id")] = {
                "kind": local_attribute(element, "Type").rsplit("/", 1)[-1],
                "part": resolved, "external": external, "target": target,
            }
        return result

    def resolve_sheet(self, name):
        exact = next((sheet for sheet in self.sheets if sheet["name"] == name), None)
        if exact:
            return exact
        matches = [sheet for sheet in self.sheets if sheet["name"].strip().casefold() == str(name or "").strip().casefold()]
        if len(matches) != 1:
            raise ValueError("The requested worksheet was not found or is ambiguous.")
        return matches[0]

    def _strings(self):
        if self._shared_strings is not None:
            return self._shared_strings
        self._shared_strings = []
        relation = next((value for value in self.workbook_relationships.values() if value["kind"] == "sharedStrings" and not value["external"]), None)
        if relation is None:
            return self._shared_strings
        count = 0
        root = None
        with self._xml_events(relation["part"], EXCEL_SHEET_MAX_BYTES) as events:
            for event, element in events:
                if root is None and event == "start":
                    root = element
                if event == "end" and local_name(element.tag) == "si":
                    value = element_text(element)
                    count += len(value)
                    if count > EXCEL_SHARED_STRINGS_MAX_CHARS or len(self._shared_strings) >= 1000000:
                        raise ValueError("Workbook shared strings exceed their supported memory bound.")
                    self._shared_strings.append(value)
                    element.clear()
                    if root is not None:
                        root.clear()
        return self._shared_strings

    def _formats(self):
        if self._number_formats is not None:
            return self._number_formats
        self._number_formats = ["General"]
        relation = next((value for value in self.workbook_relationships.values() if value["kind"] == "styles" and not value["external"]), None)
        if relation is None:
            return self._number_formats
        root = self.read_xml(relation["part"])
        custom = {int(element.get("numFmtId")): element.get("formatCode", "") for element in root.iter() if local_name(element.tag) == "numFmt"}
        xfs = first_element(root, "cellXfs")
        if xfs is not None:
            if len(xfs) > 20000:
                raise ValueError("Workbook styles exceed their supported count.")
            self._number_formats = [
                custom.get(int(xf.get("numFmtId", 0)), BUILTIN_FORMATS.get(int(xf.get("numFmtId", 0)), "General"))
                for xf in xfs
            ] or ["General"]
        return self._number_formats

    def _xml_events(self, part, limit):
        return _XmlEvents(self, part, limit)

    def _cell(self, element, row_style, column_styles, shared_formulas):
        reference = element.get("r")
        _, column = cell_coordinates(reference)
        style = element.get("s")
        if style is None:
            style = row_style or next((value for low, high, value in column_styles if low <= column <= high), "0")
        result = _blank_cell(reference)
        result["style_id"] = int(style)
        formats = self._formats()
        result["number_format"] = formats[result["style_id"]] if 0 <= result["style_id"] < len(formats) else None
        formula = next((child for child in element if local_name(child.tag) == "f"), None)
        value_element = next((child for child in element if local_name(child.tag) == "v"), None)
        raw = value_element.text if value_element is not None else None
        kind = element.get("t", "n")
        if formula is not None:
            text = formula.text or ""
            result["formula_type"] = formula.get("t", "normal")
            result["formula_reference"] = formula.get("ref")
            identifier = formula.get("si")
            if result["formula_type"] == "shared" and identifier is not None:
                if text:
                    shared_formulas[identifier] = (reference, "=" + text)
                elif identifier in shared_formulas:
                    origin, original = shared_formulas[identifier]
                    try:
                        text = Translator(original, origin=origin).translate_formula(reference).lstrip("=")
                    except TranslatorError as error:
                        raise ValueError("A shared formula reference could not be inspected.") from error
                else:
                    result["formula_type"] = "unresolved_shared"
            result["formula"] = "=" + text if text else None
            result["cached_value_available"] = raw is not None
            if raw is None:
                result["value_status"] = "cache_missing"
        if kind == "inlineStr":
            raw = element_text(first_element(element, "is"))
            value, value_type = raw, "text"
        elif kind == "s":
            strings = self._strings()
            index = int(raw) if raw is not None else -1
            if not 0 <= index < len(strings):
                raise ValueError("A workbook shared string reference is invalid.")
            value, value_type = strings[index], "text"
        elif raw is None:
            value, value_type = None, "blank"
        elif kind == "b":
            if raw not in ("0", "1"):
                raise ValueError("A saved workbook Boolean is invalid.")
            value, value_type = raw == "1", "boolean"
        elif kind in ("str", "d", "e"):
            value = raw
            value_type = {"str": "text", "d": "date", "e": "error"}[kind]
        else:
            try:
                value = int(raw) if _INTEGER.fullmatch(raw) else float(raw)
            except ValueError as error:
                raise ValueError("A saved workbook numeric value is invalid.") from error
            if not math.isfinite(value):
                raise ValueError("A saved workbook numeric value is not finite.")
            value_type = "number"
            if result["number_format"] and is_date_format(result["number_format"]):
                try:
                    value = from_excel(value, self.epoch).isoformat()
                except (OverflowError, ValueError) as error:
                    raise ValueError("A saved workbook date is invalid.") from error
                value_type = "date"
        result.update(value=value, raw_value=raw, value_type=value_type)
        if result["value_status"] != "cache_missing":
            result["value_status"] = "blank" if value is None or value == "" else "error" if value_type == "error" else "saved"
        return result

    def iter_sheet_rows(self, sheet, metadata=None):
        sheet = self.resolve_sheet(sheet) if isinstance(sheet, str) else sheet
        if self.legacy is not None:
            legacy = self.legacy.sheet_by_index(sheet["index"])
            for row_index in range(legacy.nrows):
                cells = {}
                for column in range(legacy.row_len(row_index)):
                    cell = legacy.cell(row_index, column)
                    reference = f"{get_column_letter(column + 1)}{row_index + 1}"
                    value = cell.value
                    result = _blank_cell(reference)
                    if cell.ctype not in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        value_type = {xlrd.XL_CELL_TEXT: "text", xlrd.XL_CELL_BOOLEAN: "boolean", xlrd.XL_CELL_DATE: "date", xlrd.XL_CELL_ERROR: "error"}.get(cell.ctype, "number")
                        if value_type == "boolean":
                            value = bool(value)
                        elif value_type == "date":
                            value = xlrd.xldate.xldate_as_datetime(value, self.legacy.datemode).isoformat()
                        result.update(value=value, raw_value=cell.value, value_type=value_type, value_status="saved")
                    cells[column + 1] = result
                yield row_index + 1, cells, {}
            self.legacy.unload_sheet(sheet["index"])
            return
        metadata = metadata if metadata is not None else {}
        column_styles, shared_formulas = [], {}
        stack = []
        previous_row = 0
        with self._xml_events(sheet["part"], EXCEL_SHEET_MAX_BYTES) as events:
            for event, element in events:
                name = local_name(element.tag)
                if event == "start":
                    stack.append(element)
                    if len(stack) > 64:
                        raise ValueError("Workbook XML nesting exceeds its supported depth.")
                    continue
                if name == "row":
                    row = int(element.get("r"))
                    if not previous_row < row <= EXCEL_MAX_ROWS:
                        raise ValueError("A worksheet row is outside supported bounds.")
                    previous_row = row
                    cells = {}
                    for child in element:
                        if local_name(child.tag) == "c":
                            cell = self._cell(child, element.get("s"), column_styles, shared_formulas)
                            cell_row, column = cell_coordinates(cell["cell"])
                            if cell_row != row or column in cells:
                                raise ValueError("Worksheet cell coordinates are inconsistent.")
                            cells[column] = cell
                    yield row, cells, dict(element.attrib)
                    if len(stack) > 1:
                        stack[-2].remove(element)
                    element.clear()
                elif name == "col":
                    if element.get("style") is not None:
                        column_styles.append((int(element.get("min")), int(element.get("max")), element.get("style")))
                if name in _LAYOUT_ELEMENTS:
                    layout = metadata.setdefault("layout", [])
                    if len(layout) < 200:
                        layout.append({"type": name, **dict(element.attrib)})
                elif name == "headerFooter":
                    metadata["header_footer"] = {
                        "flags": dict(element.attrib),
                        "expressions": {local_name(child.tag): child.text or "" for child in element},
                    }
                elif name == "cfRule":
                    metadata["conditional_format_rules"] = metadata.get("conditional_format_rules", 0) + 1
                elif name == "hyperlink":
                    metadata.setdefault("hyperlinks", []).append(dict(element.attrib))
                elif name == "dataValidation":
                    metadata.setdefault("validations", []).append({
                        **dict(element.attrib),
                        "formulas": {local_name(child.tag): child.text or "" for child in element},
                    })
                elif name == "tablePart":
                    metadata.setdefault("table_relationship_ids", []).append(local_attribute(element, "id"))
                elif name in ("oleObjects", "cellControl", "featurePropertyBag"):
                    metadata.setdefault("unsupported_controls", []).append(name)
                stack.pop()

    def _named_tables(self, sheet, metadata):
        if self.archive is None:
            return []
        relationships = self.relationships(sheet["part"])
        tables = []
        for identifier in metadata.get("table_relationship_ids", []):
            relation = relationships.get(identifier)
            if not relation or relation["kind"] != "table" or relation["external"]:
                raise ValueError("A worksheet table relationship is unavailable.")
            root = self.read_xml(relation["part"])
            low_column, low_row, high_column, high_row = bounded_range(root.get("ref"))
            header_count = int(root.get("headerRowCount", "1"))
            totals_count = int(root.get("totalsRowCount", "0"))
            if header_count not in (0, 1) or totals_count not in (0, 1) or low_row + header_count + totals_count > high_row + 1:
                raise ValueError("A named Excel table has an invalid header or totals range.")
            table_columns = first_element(root, "tableColumns")
            labels = [item.get("name") or get_column_letter(low_column + index) for index, item in enumerate(table_columns if table_columns is not None else [])]
            if len(labels) != high_column - low_column + 1:
                raise ValueError("A named Excel table has inconsistent column definitions.")
            names = _unique_column_names(labels, low_column)
            identity = hashlib.sha256(f"{sheet['part']}\0{relation['part']}\0{root.get('id')}".encode()).hexdigest()[:20]
            tables.append({
                "id": f"table-{identity}", "name": root.get("displayName") or root.get("name") or "Named table",
                "sheet": sheet["name"], "origin": "named", "part": relation["part"],
                "range": root.get("ref"), "min_row": low_row, "max_row": high_row,
                "min_column": low_column, "max_column": high_column,
                "header_row": low_row if header_count else None, "header_row_count": header_count,
                "header_status": "declared" if header_count else "absent",
                "data_start_row": low_row + header_count, "data_end_row": high_row - totals_count,
                "totals_row_count": totals_count, "title_rows": [],
                "row_count": high_row - low_row + 1 - header_count - totals_count,
                "repeated_header_rows": [], "repeated_header_count": 0,
                "header_signature": None,
                "columns": [
                    {"id": get_column_letter(column), "name": name, "column": column}
                    for column, name in zip(range(low_column, high_column + 1), names)
                ],
            })
        return tables

    def scan_sheet(self, sheet, row_callback=None, wanted_cells=None):
        sheet = self.resolve_sheet(sheet) if isinstance(sheet, str) else sheet
        if sheet["part"] in self._sheet_cache and row_callback is None and not wanted_cells:
            return deepcopy(self._sheet_cache[sheet["part"]]), {}
        metadata = {"layout": [], "header_footer": {}, "conditional_format_rules": 0}
        regions = _Regions()
        wanted = set(wanted_cells or [])
        saved_cells = {reference: _blank_cell(reference) for reference in wanted}
        scanned_cells = 0
        for row, cells, attributes in self.iter_sheet_rows(sheet, metadata):
            scanned_cells += len(cells)
            regions.add(row, cells)
            for cell in cells.values():
                if cell["cell"] in wanted:
                    saved_cells[cell["cell"]] = cell
            if row_callback:
                row_callback(row, cells, attributes)
            if any(key in attributes for key in ("ht", "hidden", "s")) and len(metadata["layout"]) < 200:
                metadata["layout"].append({"type": "row", **attributes})
        named = self._named_tables(sheet, metadata)
        inferred = [
            table for table in regions.finish(sheet)
            if not any(
                table["min_row"] <= declared["max_row"] and table["max_row"] >= declared["min_row"]
                and table["min_column"] <= declared["max_column"] and table["max_column"] >= declared["min_column"]
                for declared in named
            )
        ]
        tables = sorted(named + inferred, key=lambda item: (item["min_row"], item["min_column"], item["id"]))
        if len(tables) > EXCEL_MAX_TABLES:
            raise ValueError("Workbook table inventory exceeds its supported count.")
        result = {**sheet, **metadata, "tables": tables, "scanned_cells": scanned_cells}
        self._sheet_cache[sheet["part"]] = result
        return deepcopy(result), saved_cells

    def build_manifest(self):
        cache_key = None
        if self._manifest is None and isinstance(self.source, (bytes, bytearray)):
            cache_key = (hashlib.sha256(self.source).hexdigest(), self.extension, EXCEL_WORKBOOK_SCHEMA_VERSION)
            with _MANIFEST_LOCK:
                cached = _MANIFEST_CACHE.get(cache_key)
                if cached is not None:
                    _MANIFEST_CACHE.move_to_end(cache_key)
                    self._manifest = deepcopy(cached[0])
        if self._manifest is None:
            sheets = [self.scan_sheet(sheet)[0] for sheet in self.sheets]
            self._manifest = {
                "schema_version": EXCEL_WORKBOOK_SCHEMA_VERSION,
                "format": self.extension.lstrip("."), "sheet_count": len(sheets),
                "table_count": sum(len(sheet["tables"]) for sheet in sheets),
                "coverage": "complete" if not self.coverage_notes else "partial",
                "coverage_notes": list(self.coverage_notes),
                "sheets": sheets,
            }
            if cache_key is not None:
                self._manifest["source_sha256"] = cache_key[0]
                size = len(json.dumps(self._manifest, ensure_ascii=True).encode("utf-8"))
                if size <= _MANIFEST_CACHE_MAX_BYTES:
                    with _MANIFEST_LOCK:
                        while _MANIFEST_CACHE and (
                            len(_MANIFEST_CACHE) >= 16
                            or sum(item[1] for item in _MANIFEST_CACHE.values()) + size > _MANIFEST_CACHE_MAX_BYTES
                        ):
                            _MANIFEST_CACHE.popitem(last=False)
                        _MANIFEST_CACHE[cache_key] = deepcopy(self._manifest), size
        return deepcopy(self._manifest)

    def use_manifest(self, manifest):
        """Reuse only a structural scan bound to these exact source bytes."""
        if not isinstance(self.source, (bytes, bytearray)):
            raise TypeError("Reusable workbook manifests require immutable source bytes.")
        expected = hashlib.sha256(self.source).hexdigest()
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != EXCEL_WORKBOOK_SCHEMA_VERSION
            or manifest.get("source_sha256") != expected
            or [(item.get("name"), item.get("part")) for item in manifest.get("sheets") or []]
            != [(item["name"], item["part"]) for item in self.sheets]
        ):
            raise ValueError("The workbook manifest belongs to a different source.")
        self._manifest = deepcopy(manifest)

    def resolve_table(self, table_id=None, sheet_name=None):
        manifest = self.build_manifest()
        sheets = [self.resolve_sheet(sheet_name)["name"]] if sheet_name else self.sheet_names
        tables = [table for sheet in manifest["sheets"] if sheet["name"] in sheets for table in sheet["tables"]]
        if table_id:
            matches = [table for table in tables if table["id"] == table_id or table["name"] == table_id]
            if len(matches) != 1:
                raise ValueError("The requested table was not found or is ambiguous.")
            return matches[0]
        if len(tables) != 1:
            raise ValueError("The worksheet has multiple tables or no data table; select a table.")
        return tables[0]

    def select_table(self, table_id=None, sheet_name=None, cell_range=None, header_row=None):
        """Resolve a declared/inferred table or an explicitly requested analytical range."""
        if header_row is not None:
            if isinstance(header_row, bool) or not str(header_row).isascii() or not str(header_row).isdigit():
                raise ValueError("header_row must be an actual worksheet row number or zero.")
            header_row = int(header_row)
        if cell_range:
            if not sheet_name:
                if len(self.sheets) != 1:
                    raise ValueError("Select a worksheet for an explicit table range.")
                sheet_name = self.sheets[0]["name"]
            low_column, low_row, high_column, high_row = bounded_range(cell_range)
            table = {
                "id": "range-" + hashlib.sha256(f"{sheet_name}\0{cell_range}".encode()).hexdigest()[:20],
                "name": f"Selected range {cell_range}", "sheet": self.resolve_sheet(sheet_name)["name"],
                "origin": "range", "range": cell_range, "min_row": low_row, "max_row": high_row,
                "min_column": low_column, "max_column": high_column,
                "header_row": None, "header_row_count": 0, "header_status": "absent",
                "title_rows": [], "totals_row_count": 0, "data_start_row": low_row,
                "data_end_row": high_row, "row_count": high_row - low_row + 1,
                "repeated_header_rows": [], "repeated_header_count": 0, "header_signature": None,
                "columns": [
                    {"id": get_column_letter(column), "name": get_column_letter(column), "column": column}
                    for column in range(low_column, high_column + 1)
                ],
            }
            if header_row is None:
                raise ValueError("Specify header_row for an explicit range; zero means no header.")
        else:
            table = deepcopy(self.resolve_table(table_id, sheet_name))
        if header_row is None:
            return table
        if header_row and not table["min_row"] <= header_row <= table["max_row"]:
            raise ValueError("The selected header row is outside the table range.")
        low_column, high_column = table["min_column"], table["max_column"]
        labels = [get_column_letter(column) for column in range(low_column, high_column + 1)]
        if header_row:
            references = [f"{get_column_letter(column)}{header_row}" for column in range(low_column, high_column + 1)]
            cells = self.read_cells(table["sheet"], references)
            labels = [
                str(cells[reference]["value"]) if cells[reference]["value"] not in (None, "") else label
                for reference, label in zip(references, labels)
            ]
        names = _unique_column_names(labels, low_column)
        table.update({
            "header_row": header_row or None, "header_row_count": int(bool(header_row)),
            "header_status": "explicit", "title_rows": [],
            "data_start_row": header_row + 1 if header_row else table["min_row"],
            "header_signature": labels if header_row else None,
            "columns": [
                {"id": get_column_letter(column), "name": name, "column": column}
                for column, name in zip(range(low_column, high_column + 1), names)
            ],
        })
        table["row_count"] = sum(1 for _ in self.iter_table_rows(table))
        return table

    def iter_table_rows(self, table):
        sheet = self.resolve_sheet(table["sheet"])
        header = tuple(table["header_signature"]) if table.get("header_signature") is not None else None
        low, high = table["min_column"], table["max_column"]
        next_row = table["data_start_row"]
        for row, cells, _ in self.iter_sheet_rows(sheet):
            if row < table["data_start_row"]:
                continue
            if row > table["data_end_row"]:
                break
            if table["origin"] in ("named", "range"):
                while next_row < row:
                    yield next_row, [_blank_cell(f"{get_column_letter(column)}{next_row}") for column in range(low, high + 1)]
                    next_row += 1
            values = [cells.get(column) or _blank_cell(f"{get_column_letter(column)}{row}") for column in range(low, high + 1)]
            next_row = row + 1
            if table["origin"] == "inferred":
                if not any(cell["value_status"] != "blank" for cell in values):
                    continue
                if header is not None and tuple(cell["value"] for cell in values) == header:
                    continue
            yield row, values
        if table["origin"] in ("named", "range"):
            while next_row <= table["data_end_row"]:
                yield next_row, [_blank_cell(f"{get_column_letter(column)}{next_row}") for column in range(low, high + 1)]
                next_row += 1

    def read_table_page(self, table_id=None, sheet_name=None, start_row=0, max_rows=200, *, cell_range=None, header_row=None):
        if type(start_row) is not int or start_row < 0:
            raise ValueError("start_row must be a nonnegative integer.")
        if type(max_rows) is not int or not 1 <= max_rows <= EXCEL_MAX_PREVIEW_ROWS:
            raise ValueError("max_rows must be between 1 and 500.")
        table = self.select_table(table_id, sheet_name, cell_range, header_row)
        rows, row_numbers, text_truncated = [], [], False
        size = 0
        for ordinal, (row, cells) in enumerate(self.iter_table_rows(table)):
            if ordinal < start_row:
                continue
            if len(rows) >= max_rows:
                break
            values = []
            for cell in cells[:EXCEL_PREVIEW_MAX_COLUMNS]:
                value = cell["value"]
                if isinstance(value, str) and len(value) > 4000:
                    value = value[:4000] + " [preview shortened]"
                    text_truncated = True
                values.append(value)
            row_size = len(json.dumps(values, ensure_ascii=True, allow_nan=False).encode("utf-8"))
            if rows and size + row_size > EXCEL_PREVIEW_MAX_BYTES:
                break
            if row_size > EXCEL_PREVIEW_MAX_BYTES:
                raise ValueError("A worksheet row exceeds the supported preview byte budget; select a smaller range.")
            size += row_size
            rows.append(values)
            row_numbers.append(row)
        has_more = start_row + len(rows) < table["row_count"]
        return {
            "selected_sheet": table["sheet"], "sheet_names": self.sheet_names,
            "sheet_count": len(self.sheets), "table_id": table["id"], "table_name": table["name"],
            "table_range": table["range"], "header_row": table["header_row"],
            "header_status": table["header_status"], "columns": [column["name"] for column in table["columns"][:EXCEL_PREVIEW_MAX_COLUMNS]],
            "rows": rows, "row_numbers": row_numbers, "total_rows": table["row_count"],
            "total_columns": len(table["columns"]), "start_row": start_row, "has_more": has_more,
            "truncated": has_more, "next_start_row": start_row + len(rows) if has_more else None,
            "columns_truncated": len(table["columns"]) > EXCEL_PREVIEW_MAX_COLUMNS,
            "cell_text_truncated": text_truncated,
        }

    def read_table_previews(self, tables, max_rows=3):
        """Gather small previews of many tables in one sequential pass per sheet."""
        if type(max_rows) is not int or not 1 <= max_rows <= 20:
            raise ValueError("The schema preview row limit is invalid.")
        results = {table["id"]: [] for table in tables}
        for sheet_name in dict.fromkeys(table["sheet"] for table in tables):
            selected = [table for table in tables if table["sheet"] == sheet_name]
            remaining = {table["id"] for table in selected if table["row_count"] > 0}
            for row, cells, _ in self.iter_sheet_rows(self.resolve_sheet(sheet_name)):
                for table in selected:
                    records = results[table["id"]]
                    if table["id"] not in remaining or not table["data_start_row"] <= row <= table["data_end_row"]:
                        continue
                    if table["origin"] in ("named", "range"):
                        next_row = table["data_start_row"] + len(records)
                        while next_row < row and len(records) < min(max_rows, table["row_count"]):
                            records.append({"row": next_row, "values": [None] * len(table["columns"])})
                            next_row += 1
                    values = [
                        (cells.get(column) or {}).get("value")
                        for column in range(table["min_column"], table["max_column"] + 1)
                    ]
                    if table["origin"] == "inferred":
                        if all(value in (None, "") for value in values):
                            continue
                        if table.get("header_signature") is not None and values == table["header_signature"]:
                            continue
                    if len(records) < min(max_rows, table["row_count"]):
                        records.append({"row": row, "values": values})
                    if len(records) >= min(max_rows, table["row_count"]):
                        remaining.discard(table["id"])
                if not remaining:
                    break
            for table in selected:
                if table["origin"] not in ("named", "range"):
                    continue
                records = results[table["id"]]
                while len(records) < min(max_rows, table["row_count"]):
                    records.append({
                        "row": table["data_start_row"] + len(records),
                        "values": [None] * len(table["columns"]),
                    })
        return results

    def read_cells(self, sheet_name, references):
        wanted = {str(reference).replace("$", "").upper() for reference in references}
        if len(wanted) > 2000:
            raise ValueError("A cell inspection request exceeds its supported page size.")
        positions = {reference: cell_coordinates(reference)[0] for reference in wanted}
        result = {reference: _blank_cell(reference) for reference in wanted}
        if not wanted:
            return result
        for row, cells, _ in self.iter_sheet_rows(self.resolve_sheet(sheet_name)):
            if row > max(positions.values()):
                break
            for cell in cells.values():
                if cell["cell"] in wanted:
                    result[cell["cell"]] = cell
        return result


class _XmlEvents:
    def __init__(self, reader, part, limit):
        self.reader = reader
        self.part = part
        self.limit = limit
        self.stream = None

    def __enter__(self):
        info = self.reader.archive.getinfo(self.part)
        if info.compress_type not in OFFICE_ZIP_ALLOWED_COMPRESSION or info.file_size > self.limit:
            raise ValueError("Workbook XML exceeds its supported byte/compression policy.")
        self.stream = self.reader.archive.open(self.part)
        return iterparse(
            _BoundedXmlStream(self.stream, self.reader, self.limit),
            events=("start", "end"), forbid_dtd=True, forbid_entities=True, forbid_external=True,
        )

    def __exit__(self, exc_type, exc_value, traceback):
        if self.stream is not None:
            self.stream.close()


def build_excel_table_preview(
    source_bytes, extension, *, sheet_name=None, sheet_index=None, table_id=None,
    start_row=0, max_rows=200, cell_range=None, header_row=None,
):
    """Choose a visible preview explicitly; analytical reads never default among tables."""
    with ExcelWorkbookReader(source_bytes, extension=extension) as reader:
        manifest = reader.build_manifest()
        names = reader.sheet_names
        if not names:
            raise ValueError("The workbook has no readable worksheets.")
        if sheet_name:
            selected = reader.resolve_sheet(sheet_name)["name"]
        elif sheet_index is not None:
            if isinstance(sheet_index, bool) or not str(sheet_index).isdigit() or int(sheet_index) >= len(names):
                raise ValueError("The worksheet index is invalid.")
            selected = names[int(sheet_index)]
        else:
            selected = names[0]
        sheet = next(item for item in manifest["sheets"] if item["name"] == selected)
        tables = sheet["tables"]
        options = [
            {key: table[key] for key in ("id", "name", "range", "origin", "header_row", "header_status", "row_count")}
            for table in tables
        ]
        if not tables and not cell_range:
            if table_id:
                raise ValueError("The requested table was not found.")
            return {
                "selected_sheet": selected, "sheet_names": names, "sheet_count": len(names),
                "tables": [], "table_count": 0, "rows": [], "columns": [], "row_numbers": [],
                "total_rows": 0, "total_columns": 0, "start_row": 0, "has_more": False,
                "truncated": False, "next_start_row": None,
            }
        selected_table = table_id or (tables[0]["id"] if tables and not cell_range else None)
        page = reader.read_table_page(
            table_id=selected_table, sheet_name=selected, start_row=start_row, max_rows=max_rows,
            cell_range=cell_range, header_row=header_row,
        )
        return {**page, "tables": options, "table_count": len(tables), "coverage": manifest["coverage"]}
