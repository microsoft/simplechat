# functions_tabular_merge.py
"""Deterministic merging of same-structure CSV and Excel files into one table.

Version: 0.261.218

The engine is pure: it receives already-authorized byte loaders, never resolves
documents, settings, storage, routes, or models, and performs no model work.
Values are kept as text so leading zeros, codes, and identifiers survive exactly.
Rows are spooled to a bounded temporary file during the single parse, so callers
learn the exact row count before they persist or render the merged result.
"""

import codecs
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import io
import json
import os
import tempfile
from typing import Callable, Iterator, List, Optional, Sequence, Tuple
import unicodedata
import zipfile


TABULAR_MERGE_REPORT_VERSION = "tabular-merge-report-v1"

SCHEMA_POLICY_BY_NAME = "by_name"
SCHEMA_POLICY_EXACT_ORDER = "exact_order"
TABULAR_MERGE_SCHEMA_POLICIES = (SCHEMA_POLICY_BY_NAME, SCHEMA_POLICY_EXACT_ORDER)

TABULAR_MERGE_FORMAT_CSV = "csv"
TABULAR_MERGE_FORMAT_XLSX = "xlsx"
TABULAR_MERGE_FORMAT_XLS = "xls"
TABULAR_MERGE_EXTENSION_FORMATS = {
    ".csv": TABULAR_MERGE_FORMAT_CSV,
    ".xlsx": TABULAR_MERGE_FORMAT_XLSX,
    ".xlsm": TABULAR_MERGE_FORMAT_XLSX,
    ".xls": TABULAR_MERGE_FORMAT_XLS,
}
TABULAR_MERGE_SUPPORTED_EXTENSIONS = tuple(TABULAR_MERGE_EXTENSION_FORMATS)

DEFAULT_SOURCE_COLUMN_NAME = "Source File"
MAX_SOURCE_COLUMN_NAME_CHARS = 128
MAX_SHEET_NAME_CHARS = 31

SOURCE_STATUS_MERGED = "merged"
SOURCE_STATUS_COMPATIBLE = "compatible"
SOURCE_STATUS_SCHEMA_MISMATCH = "schema_mismatch"
SOURCE_STATUS_NOT_PROCESSED = "not_processed"

_CSV_DELIMITERS = (",", ";", "\t", "|")
_CSV_SNIFF_BYTES = 64 * 1024
_SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
_CANCEL_CHECK_INTERVAL = 1000
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MAX_EXACT_INTEGER_FLOAT = float(2 ** 53)

_EXCEL_LIMITATIONS = (
    "Excel formulas are merged as their last calculated values; a workbook saved without "
    "calculated values merges those cells as blanks.",
    "Excel numbers, booleans and dates are written as plain text, with dates in ISO 8601 form.",
)


class TabularMergeError(ValueError):
    """A safe, user-presentable merge failure with a stable code."""

    def __init__(self, code, message, *, report=None, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.report = report
        self.details = dict(details or {})


class TabularMergeCancelled(TabularMergeError):
    """The caller asked the merge to stop."""

    def __init__(self):
        super().__init__("cancelled", "The merge was cancelled.")


@dataclass(frozen=True)
class TabularMergeLimits:
    """Bounds for one merge; every value must be a positive integer."""

    max_sources: int = 10
    max_total_rows: int = 250_000
    max_source_bytes: int = 100 * 1024 * 1024
    max_columns: int = 256
    max_header_bytes: int = 256
    max_cell_chars: int = 32_767
    max_workbook_uncompressed_bytes: int = 512 * 1024 * 1024
    max_workbook_entries: int = 10_000

    def __post_init__(self):
        for name in (
            "max_sources", "max_total_rows", "max_source_bytes", "max_columns",
            "max_header_bytes", "max_cell_chars", "max_workbook_uncompressed_bytes",
            "max_workbook_entries",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if self.max_sources < 2:
            raise ValueError("max_sources must allow at least two sources.")


@dataclass(frozen=True)
class TabularMergeOptions:
    """How sources are matched and how provenance is recorded."""

    schema_policy: str = SCHEMA_POLICY_BY_NAME
    sheet: Optional[str] = None
    include_source_column: bool = True
    source_column_name: str = DEFAULT_SOURCE_COLUMN_NAME

    def __post_init__(self):
        if self.schema_policy not in TABULAR_MERGE_SCHEMA_POLICIES:
            raise TabularMergeError(
                "invalid_options",
                f"Schema policy must be one of: {', '.join(TABULAR_MERGE_SCHEMA_POLICIES)}.",
            )
        if self.sheet is not None:
            if not isinstance(self.sheet, str) or not self.sheet.strip():
                raise TabularMergeError("invalid_options", "A sheet name must be nonempty text.")
            if len(self.sheet) > MAX_SHEET_NAME_CHARS:
                raise TabularMergeError(
                    "invalid_options", f"A sheet name has at most {MAX_SHEET_NAME_CHARS} characters.",
                )
        if type(self.include_source_column) is not bool:
            raise TabularMergeError("invalid_options", "include_source_column must be true or false.")
        name = _display_header(self.source_column_name) if isinstance(self.source_column_name, str) else ""
        if not name or len(name) > MAX_SOURCE_COLUMN_NAME_CHARS or len(name.encode("utf-8")) > 240:
            raise TabularMergeError(
                "invalid_options",
                f"The source column name must be 1 to {MAX_SOURCE_COLUMN_NAME_CHARS} characters.",
            )


@dataclass(frozen=True)
class TabularMergeSource:
    """One authorized source. ``load_bytes`` returns the original file bytes."""

    source_id: str
    file_name: str
    load_bytes: Callable[[], bytes] = field(repr=False)
    extension: str = ""

    def resolved_extension(self):
        extension = (self.extension or os.path.splitext(self.file_name or "")[1]).strip().lower()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        return extension


def tabular_merge_format_for_file_name(file_name):
    """The merge reader format for a file name, or None when unsupported."""
    extension = os.path.splitext(str(file_name or ""))[1].strip().lower()
    return TABULAR_MERGE_EXTENSION_FORMATS.get(extension)


def iter_csv_rows(content, file_name="A selected file"):
    """Decode CSV bytes; return ``(encoding, delimiter, rows)`` where rows yields lists of text."""
    source = TabularMergeSource(file_name, file_name, lambda: content)
    text, encoding = _decode_csv(content, source)
    delimiter = _detect_delimiter(text)
    reader = csv.reader(
        io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"', doublequote=True, strict=False,
    )

    def rows():
        try:
            for values in reader:
                yield values
        except csv.Error as exc:
            raise TabularMergeError(
                "unreadable_csv", f"{_safe_name(source)} couldn't be read as CSV near line {reader.line_num}.",
            ) from exc

    return encoding, delimiter, rows()


def normalize_header_name(value):
    """The comparison key for a header: NFC, collapsed whitespace, casefolded."""
    return _display_header(value).casefold()


def _display_header(value):
    text = unicodedata.normalize("NFC", str(value if value is not None else ""))
    return " ".join(text.split())


class _RowSpool:
    """Validated rows as compact JSON lines; small merges stay in memory."""

    def __init__(self):
        self._file = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b")
        self.count = 0
        self.closed = False

    def append(self, values):
        self._file.write(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self._file.write(b"\n")
        self.count += 1

    def iter_rows(self):
        if self.closed:
            raise TabularMergeError("result_closed", "The merged rows are no longer available.")
        self._file.flush()
        self._file.seek(0)
        yielded = 0
        for line in self._file:
            if not line.strip():
                continue
            yielded += 1
            yield json.loads(line)
        if yielded != self.count:
            raise TabularMergeError("count_mismatch", "The merged rows could not be read back completely.")

    def close(self):
        if not self.closed:
            self.closed = True
            self._file.close()


class TabularMergeResult:
    """The merged table: ordered columns, an exact row count, rows and a report.

    Rows can be iterated more than once until ``close()``; each pass verifies the
    count. Use it as a context manager so the spooled rows are always released.
    """

    def __init__(self, columns, report, spool):
        self._columns = tuple(columns)
        self._report = report
        self._spool = spool

    @property
    def columns(self):
        return self._columns

    @property
    def row_count(self):
        return self._spool.count

    @property
    def report(self):
        return json.loads(json.dumps(self._report))

    def iter_rows(self):
        return self._spool.iter_rows()

    def iter_records(self):
        columns = self._columns
        for values in self._spool.iter_rows():
            yield dict(zip(columns, values))

    def close(self):
        self._spool.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


def merge_tabular_sources(
    sources: Sequence[TabularMergeSource],
    *,
    options: Optional[TabularMergeOptions] = None,
    limits: Optional[TabularMergeLimits] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> TabularMergeResult:
    """Append the rows of same-structure sources, in the given order, into one table.

    The first source defines the column order. ``by_name`` accepts the same columns in
    any order after header normalization; ``exact_order`` also requires the same order.
    A schema mismatch reads every remaining header so the report lists all mismatches.
    """
    options = options or TabularMergeOptions()
    limits = limits or TabularMergeLimits()
    sources = list(sources or ())
    _validate_sources(sources, limits)

    report = _new_report(options, len(sources))
    spool = _RowSpool()
    reference = None
    output_columns = ()
    source_column = None
    mismatch_found = False
    blank_rows_total = 0
    try:
        for index, source in enumerate(sources):
            _check_cancel(cancel_requested)
            entry = _new_source_entry(source)
            report["sources"].append(entry)
            content = _load_source_bytes(source, limits)
            table = _open_table(source, content, options, limits)
            try:
                entry.update(table.describe())
                header = _header_names(table.header, source, limits, entry)
                if reference is None:
                    reference = header
                    source_column = _source_column_name(options, header, report)
                    output_columns = ((source_column,) if source_column else ()) + tuple(
                        display for display, _ in header
                    )
                    if len(output_columns) > limits.max_columns:
                        raise TabularMergeError(
                            "too_many_columns",
                            f"The merged table would have {len(output_columns)} columns; "
                            f"at most {limits.max_columns} are supported.",
                        )
                    report["columns"] = list(output_columns)
                    report["source_column"] = source_column
                    column_map = list(range(len(header)))
                else:
                    column_map = _match_header(reference, header, options.schema_policy, entry)
                    if column_map is None:
                        mismatch_found = True
                        entry["status"] = SOURCE_STATUS_SCHEMA_MISMATCH
                        continue

                if mismatch_found:
                    entry["status"] = SOURCE_STATUS_NOT_PROCESSED
                    continue

                rows, blank_rows = _append_rows(
                    table, source, column_map, len(header), source_column, spool, limits,
                    cancel_requested, entry,
                )
                blank_rows_total += blank_rows
                entry["rows"] = rows
                entry["blank_rows_skipped"] = blank_rows
                entry["status"] = SOURCE_STATUS_MERGED
            finally:
                table.close()
            if on_progress is not None:
                on_progress({
                    "index": index + 1, "total": len(sources),
                    "file_name": source.file_name, "rows": entry.get("rows", 0),
                })

        if mismatch_found:
            report["status"] = "failed"
            for entry in report["sources"]:
                if entry["status"] in (SOURCE_STATUS_MERGED, SOURCE_STATUS_NOT_PROCESSED):
                    entry["status"] = SOURCE_STATUS_COMPATIBLE
                    entry["rows"] = 0
                    entry["blank_rows_skipped"] = 0
                    entry["short_rows_padded"] = 0
            raise TabularMergeError(
                "schema_mismatch", _mismatch_message(report), report=report,
            )

        report["status"] = "merged"
        report["totals"] = {
            "sources": len(sources),
            "rows": spool.count,
            "columns": len(output_columns),
            "blank_rows_skipped": blank_rows_total,
        }
        if any(entry.get("format") != TABULAR_MERGE_FORMAT_CSV for entry in report["sources"]):
            report["limitations"] = list(_EXCEL_LIMITATIONS)
        return TabularMergeResult(output_columns, report, spool)
    except BaseException:
        spool.close()
        raise


def _validate_sources(sources, limits):
    if len(sources) < 2:
        raise TabularMergeError("too_few_sources", "Merging needs at least two files.")
    if len(sources) > limits.max_sources:
        raise TabularMergeError(
            "too_many_sources",
            f"{len(sources)} files were selected; at most {limits.max_sources} can be merged here.",
        )
    seen = set()
    for source in sources:
        if not isinstance(source, TabularMergeSource):
            raise TabularMergeError("invalid_source", "Each merge source must be a TabularMergeSource.")
        if not isinstance(source.source_id, str) or not source.source_id.strip():
            raise TabularMergeError("invalid_source", "Each merge source needs an identifier.")
        if source.source_id in seen:
            raise TabularMergeError("duplicate_source", "The same file was selected more than once.")
        seen.add(source.source_id)
        if not callable(source.load_bytes):
            raise TabularMergeError("invalid_source", "Each merge source needs a byte loader.")
        if TABULAR_MERGE_EXTENSION_FORMATS.get(source.resolved_extension()) is None:
            raise TabularMergeError(
                "unsupported_format",
                f"{_safe_name(source)} isn't a CSV or Excel file (.csv, .xlsx, .xlsm, .xls).",
            )


def _new_report(options, source_count):
    return {
        "version": TABULAR_MERGE_REPORT_VERSION,
        "status": "running",
        "policy": {
            "schema_policy": options.schema_policy,
            "sheet": options.sheet,
            "include_source_column": options.include_source_column,
            "source_column_name": _display_header(options.source_column_name) if options.include_source_column else None,
        },
        "columns": [],
        "source_column": None,
        "totals": {"sources": source_count, "rows": 0, "columns": 0, "blank_rows_skipped": 0},
        "sources": [],
        "warnings": [],
        "limitations": [],
    }


def _new_source_entry(source):
    return {
        "source_id": source.source_id,
        "file_name": _safe_name(source),
        "format": TABULAR_MERGE_EXTENSION_FORMATS.get(source.resolved_extension()),
        "sheet": None,
        "encoding": None,
        "delimiter": None,
        "rows": 0,
        "blank_rows_skipped": 0,
        "short_rows_padded": 0,
        "status": SOURCE_STATUS_NOT_PROCESSED,
        "missing_columns": [],
        "extra_columns": [],
        "order_differs": False,
        "warnings": [],
    }


def _safe_name(source):
    name = str(getattr(source, "file_name", "") or "").strip()
    return name or "A selected file"


def _check_cancel(cancel_requested):
    if cancel_requested is not None and cancel_requested():
        raise TabularMergeCancelled()


def _load_source_bytes(source, limits):
    content = source.load_bytes()
    if isinstance(content, bytearray):
        content = bytes(content)
    if not isinstance(content, bytes):
        raise TabularMergeError("source_unavailable", f"{_safe_name(source)} could not be read.")
    if len(content) > limits.max_source_bytes:
        raise TabularMergeError(
            "source_too_large",
            f"{_safe_name(source)} is larger than the {limits.max_source_bytes // (1024 * 1024)} MB merge limit.",
        )
    return content


def _source_column_name(options, header, report):
    if not options.include_source_column:
        return None
    base = _display_header(options.source_column_name)
    taken = {normalized for _, normalized in header}
    candidate = base
    suffix = 2
    while candidate.casefold() in taken:
        candidate = f"{base} ({suffix})"
        suffix += 1
    if candidate != base:
        report["warnings"].append({
            "code": "source_column_renamed",
            "message": f'The files already have a "{base}" column, so the file name column is "{candidate}".',
        })
    return candidate


def _header_names(raw_header, source, limits, entry):
    """Display and comparison names for one header row; trailing blanks are dropped."""
    cells = list(raw_header)
    while cells and not _display_header(cells[-1]):
        cells.pop()
    if not cells:
        raise TabularMergeError("empty_source", f"{_safe_name(source)} has no header row.")
    names = []
    seen = {}
    for position, value in enumerate(cells, start=1):
        display = _display_header(value)
        if not display:
            display = f"Column {position}"
            entry["warnings"].append({
                "code": "blank_header",
                "message": f'Column {position} has no header, so it is named "{display}".',
            })
        if len(display.encode("utf-8")) > limits.max_header_bytes:
            raise TabularMergeError(
                "header_too_long",
                f"A column header in {_safe_name(source)} is longer than {limits.max_header_bytes} bytes.",
            )
        normalized = display.casefold()
        if normalized in seen:
            raise TabularMergeError(
                "duplicate_columns",
                f'{_safe_name(source)} has more than one "{display}" column.',
            )
        seen[normalized] = position
        names.append((display, normalized))
    return names


def _match_header(reference, header, schema_policy, entry):
    """Positions in ``header`` for each reference column, or None on a mismatch."""
    reference_keys = [normalized for _, normalized in reference]
    header_keys = [normalized for _, normalized in header]
    positions = {key: index for index, key in enumerate(header_keys)}
    missing = [display for display, key in reference if key not in positions]
    reference_set = set(reference_keys)
    extra = [display for display, key in header if key not in reference_set]
    entry["missing_columns"] = missing
    entry["extra_columns"] = extra
    if missing or extra:
        return None
    if reference_keys != header_keys:
        entry["order_differs"] = True
        if schema_policy == SCHEMA_POLICY_EXACT_ORDER:
            return None
    return [positions[key] for key in reference_keys]


def _mismatch_message(report):
    reference = report["sources"][0]["file_name"] if report["sources"] else "the first file"
    parts = []
    for entry in report["sources"]:
        if entry["status"] != SOURCE_STATUS_SCHEMA_MISMATCH:
            continue
        details = []
        if entry["missing_columns"]:
            details.append(f"missing {', '.join(_quoted(entry['missing_columns']))}")
        if entry["extra_columns"]:
            details.append(f"extra {', '.join(_quoted(entry['extra_columns']))}")
        if not details and entry["order_differs"]:
            details.append("columns in a different order")
        parts.append(f"{entry['file_name']} ({'; '.join(details)})")
    return (
        f"These files don't have the same columns as {reference}: {'; '.join(parts)}. "
        "Nothing was merged."
    )


def _quoted(values, limit=8):
    shown = [f'"{value}"' for value in values[:limit]]
    if len(values) > limit:
        shown.append(f"and {len(values) - limit} more")
    return shown


def _append_rows(table, source, column_map, width, source_column, spool, limits, cancel_requested, entry):
    rows = 0
    blank_rows = 0
    for row_number, values in table.rows():
        if rows % _CANCEL_CHECK_INTERVAL == 0:
            _check_cancel(cancel_requested)
        cells = list(values)
        if len(cells) > width:
            if any(_cell_has_content(value) for value in cells[width:]):
                raise TabularMergeError(
                    "row_has_extra_values",
                    f"Row {row_number} in {_safe_name(source)} has more values than there are columns.",
                )
            cells = cells[:width]
        if not any(_cell_has_content(value) for value in cells):
            blank_rows += 1
            continue
        if len(cells) < width:
            entry["short_rows_padded"] += 1
            cells.extend([""] * (width - len(cells)))
        for value in cells:
            if len(value) > limits.max_cell_chars:
                raise TabularMergeError(
                    "cell_too_large",
                    f"Row {row_number} in {_safe_name(source)} has a value longer than "
                    f"{limits.max_cell_chars} characters.",
                )
        if spool.count >= limits.max_total_rows:
            raise TabularMergeError(
                "row_limit_exceeded",
                f"The merged table would have more than {limits.max_total_rows:,} rows. "
                "Merge fewer files here, or use a workflow for larger merges.",
            )
        ordered = [cells[position] for position in column_map]
        spool.append(([source.file_name] if source_column else []) + ordered)
        rows += 1
    return rows, blank_rows


def _cell_has_content(value):
    return bool(value) and bool(str(value).strip())


# ---------------------------------------------------------------------------
# Table readers
# ---------------------------------------------------------------------------


class _Table:
    """A header plus a row iterator over one sheet or CSV body."""

    format = ""

    def describe(self):
        return {}

    @property
    def header(self):
        raise NotImplementedError

    def rows(self):
        raise NotImplementedError

    def close(self):
        return None


def _open_table(source, content, options, limits):
    table_format = TABULAR_MERGE_EXTENSION_FORMATS[source.resolved_extension()]
    if table_format == TABULAR_MERGE_FORMAT_CSV:
        return _CsvTable(source, content)
    if table_format == TABULAR_MERGE_FORMAT_XLSX:
        return _XlsxTable(source, content, options.sheet, limits)
    return _XlsTable(source, content, options.sheet)


class _CsvTable(_Table):
    format = TABULAR_MERGE_FORMAT_CSV

    def __init__(self, source, content):
        self._source = source
        text, self._encoding = _decode_csv(content, source)
        self._delimiter = _detect_delimiter(text)
        self._reader = csv.reader(
            io.StringIO(text, newline=""), delimiter=self._delimiter, quotechar='"',
            doublequote=True, strict=False,
        )
        self._header = None
        self._header_line = 0
        try:
            for values in self._reader:
                if any(_cell_has_content(value) for value in values):
                    self._header = values
                    self._header_line = self._reader.line_num
                    break
        except csv.Error as exc:
            raise TabularMergeError(
                "unreadable_csv", f"{_safe_name(source)} couldn't be read as CSV near line {self._reader.line_num}.",
            ) from exc
        if self._header is None:
            raise TabularMergeError("empty_source", f"{_safe_name(source)} has no header row.")

    def describe(self):
        return {"encoding": self._encoding, "delimiter": self._delimiter}

    @property
    def header(self):
        return self._header

    def rows(self):
        reader = self._reader
        try:
            for values in reader:
                yield reader.line_num, values
        except csv.Error as exc:
            raise TabularMergeError(
                "unreadable_csv", f"{_safe_name(self._source)} couldn't be read as CSV near line {reader.line_num}.",
            ) from exc


def _decode_csv(content, source):
    for bom, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if content.startswith(bom):
            try:
                return content.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                raise TabularMergeError(
                    "unreadable_csv", f"{_safe_name(source)} has text that doesn't match its encoding.",
                ) from exc
    if b"\x00" in content[:_CSV_SNIFF_BYTES]:
        raise TabularMergeError("unreadable_csv", f"{_safe_name(source)} doesn't look like a text CSV file.")
    for encoding in ("utf-8", "cp1252"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1"), "latin-1"


def _detect_delimiter(text):
    """The most frequent supported delimiter outside quotes on the first nonblank line."""
    counts = {delimiter: 0 for delimiter in _CSV_DELIMITERS}
    in_quotes = False
    seen_content = False
    for character in text[:_CSV_SNIFF_BYTES]:
        if character == '"':
            in_quotes = not in_quotes
            seen_content = True
            continue
        if in_quotes:
            continue
        if character in "\r\n":
            if seen_content:
                break
            continue
        if character in counts:
            counts[character] += 1
        if not character.isspace():
            seen_content = True
    best = max(_CSV_DELIMITERS, key=lambda delimiter: (counts[delimiter], -_CSV_DELIMITERS.index(delimiter)))
    return best if counts[best] else ","


class _XlsxTable(_Table):
    format = TABULAR_MERGE_FORMAT_XLSX

    def __init__(self, source, content, sheet, limits):
        self._source = source
        _guard_workbook_archive(content, source, limits)
        # openpyxl is imported only when a workbook is merged; it is a large binary dependency.
        from openpyxl import load_workbook

        try:
            self._workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=True, keep_links=False,
            )
        except Exception as exc:
            raise TabularMergeError(
                "unreadable_workbook", f"{_safe_name(source)} couldn't be opened as an Excel workbook.",
            ) from exc
        try:
            self._sheet = _select_sheet(
                [(worksheet.title, getattr(worksheet, "sheet_state", "visible")) for worksheet in self._workbook.worksheets],
                sheet, source,
            )
            self._worksheet = self._workbook[self._sheet]
            self._worksheet.reset_dimensions()
            self._iterator = self._worksheet.iter_rows(values_only=True)
            self._row_number = 0
            self._header = None
            for values in self._iterator:
                self._row_number += 1
                cells = [_excel_text(value) for value in values]
                if any(_cell_has_content(value) for value in cells):
                    self._header = cells
                    break
        except TabularMergeError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise TabularMergeError(
                "unreadable_workbook", f"{_safe_name(source)} couldn't be read as an Excel workbook.",
            ) from exc
        if self._header is None:
            self.close()
            raise TabularMergeError(
                "empty_source", f'Sheet "{self._sheet}" in {_safe_name(source)} has no header row.',
            )

    def describe(self):
        return {"sheet": self._sheet}

    @property
    def header(self):
        return self._header

    def rows(self):
        try:
            for values in self._iterator:
                self._row_number += 1
                yield self._row_number, [_excel_text(value) for value in values]
        except TabularMergeError:
            raise
        except Exception as exc:
            raise TabularMergeError(
                "unreadable_workbook", f"{_safe_name(self._source)} couldn't be read near row {self._row_number}.",
            ) from exc

    def close(self):
        workbook = getattr(self, "_workbook", None)
        if workbook is not None:
            self._workbook = None
            try:
                workbook.close()
            except Exception:
                pass


def _guard_workbook_archive(content, source, limits):
    if content[:8] == _OLE_MAGIC:
        raise TabularMergeError(
            "encrypted_workbook",
            f"{_safe_name(source)} is password-protected or encrypted, so it can't be merged.",
        )
    if content[:4] != _ZIP_MAGIC:
        raise TabularMergeError("unreadable_workbook", f"{_safe_name(source)} isn't a valid Excel workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise TabularMergeError(
            "unreadable_workbook", f"{_safe_name(source)} isn't a valid Excel workbook.",
        ) from exc
    if len(entries) > limits.max_workbook_entries:
        raise TabularMergeError("workbook_too_large", f"{_safe_name(source)} has too many internal parts to merge.")
    if sum(entry.file_size for entry in entries) > limits.max_workbook_uncompressed_bytes:
        raise TabularMergeError("workbook_too_large", f"{_safe_name(source)} is too large to merge once uncompressed.")


class _XlsTable(_Table):
    format = TABULAR_MERGE_FORMAT_XLS

    def __init__(self, source, content, sheet):
        self._source = source
        if content[:8] != _OLE_MAGIC:
            raise TabularMergeError(
                "unreadable_workbook", f"{_safe_name(source)} isn't a valid Excel 97-2003 (.xls) workbook.",
            )
        # xlrd is imported only when a legacy workbook is merged.
        import xlrd

        self._xlrd = xlrd
        try:
            self._book = xlrd.open_workbook(file_contents=content, on_demand=True)
        except Exception as exc:
            code = "encrypted_workbook" if "encrypt" in str(exc).lower() else "unreadable_workbook"
            message = (
                f"{_safe_name(source)} is password-protected or encrypted, so it can't be merged."
                if code == "encrypted_workbook"
                else f"{_safe_name(source)} couldn't be opened as an Excel workbook."
            )
            raise TabularMergeError(code, message) from exc
        try:
            names = self._book.sheet_names()
            states = []
            for index, name in enumerate(names):
                visibility = 0
                if sheet is None:
                    visibility = getattr(self._book.sheet_by_index(index), "visibility", 0)
                states.append((name, "visible" if visibility == 0 else "hidden"))
            self._sheet = _select_sheet(states, sheet, source)
            self._worksheet = self._book.sheet_by_name(self._sheet)
            self._datemode = self._book.datemode
            self._next_row = 0
            self._header = None
            while self._next_row < self._worksheet.nrows:
                cells = self._row_values(self._next_row)
                self._next_row += 1
                if any(_cell_has_content(value) for value in cells):
                    self._header = cells
                    break
        except TabularMergeError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise TabularMergeError(
                "unreadable_workbook", f"{_safe_name(source)} couldn't be read as an Excel workbook.",
            ) from exc
        if self._header is None:
            self.close()
            raise TabularMergeError(
                "empty_source", f'Sheet "{self._sheet}" in {_safe_name(source)} has no header row.',
            )

    def describe(self):
        return {"sheet": self._sheet}

    @property
    def header(self):
        return self._header

    def rows(self):
        while self._next_row < self._worksheet.nrows:
            row_number = self._next_row + 1
            cells = self._row_values(self._next_row)
            self._next_row += 1
            yield row_number, cells

    def _row_values(self, row_index):
        xlrd = self._xlrd
        values = []
        for cell in self._worksheet.row(row_index):
            if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                values.append("")
            elif cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    values.append(_excel_text(xlrd.xldate_as_datetime(cell.value, self._datemode)))
                except Exception:
                    values.append(_excel_text(cell.value))
            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                values.append("TRUE" if cell.value else "FALSE")
            elif cell.ctype == xlrd.XL_CELL_ERROR:
                values.append(xlrd.error_text_from_code.get(cell.value, "#ERROR"))
            else:
                values.append(_excel_text(cell.value))
        return values

    def close(self):
        book = getattr(self, "_book", None)
        if book is not None:
            self._book = None
            try:
                book.release_resources()
            except Exception:
                pass


def _select_sheet(sheets: List[Tuple[str, str]], requested, source):
    names = [name for name, _ in sheets]
    if not names:
        raise TabularMergeError("empty_source", f"{_safe_name(source)} has no worksheets.")
    if requested is not None:
        if requested in names:
            return requested
        folded = requested.casefold()
        for name in names:
            if name.casefold() == folded:
                return name
        raise TabularMergeError(
            "sheet_not_found",
            f'{_safe_name(source)} has no sheet named "{requested}". Its sheets are: '
            f"{', '.join(_quoted(names))}.",
            details={"available_sheets": names},
        )
    for name, state in sheets:
        if state == "visible":
            return name
    return names[0]


def _excel_text(value):
    """Canonical text for one Excel cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < _MAX_EXACT_INTEGER_FLOAT:
            return str(int(value))
        return repr(value)
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(timespec="seconds" if value.microsecond == 0 else "microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds" if value.microsecond == 0 else "microseconds")
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        sign = "-" if total_seconds < 0 else ""
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{sign}{hours}:{minutes:02d}:{seconds:02d}"
    return str(value)


__all__ = [
    "DEFAULT_SOURCE_COLUMN_NAME",
    "SCHEMA_POLICY_BY_NAME",
    "SCHEMA_POLICY_EXACT_ORDER",
    "TABULAR_MERGE_REPORT_VERSION",
    "TABULAR_MERGE_SCHEMA_POLICIES",
    "TABULAR_MERGE_SUPPORTED_EXTENSIONS",
    "TabularMergeCancelled",
    "TabularMergeError",
    "TabularMergeLimits",
    "TabularMergeOptions",
    "TabularMergeResult",
    "TabularMergeSource",
    "iter_csv_rows",
    "merge_tabular_sources",
    "normalize_header_name",
    "tabular_merge_format_for_file_name",
]
