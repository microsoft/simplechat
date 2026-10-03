# functions_document_merge_workbook.py
"""Workbook assembly for V2 file merge: each source file becomes its own sheet.

Version: 0.261.221

Excel sources keep their cell types — numbers stay numbers and dates stay dates with
their number format — while CSV sources are copied as text so codes keep their leading
zeros. Formulas contribute their last calculated values. Strings that look like formulas
are written as text and never evaluated. Control characters, which Excel can't store, are
removed and counted. Styles, column widths, merged cells, charts and images are not
copied. The workbook carries fixed dates, so the same files give the same bytes.
"""

from datetime import date, datetime, time, timedelta
import io
import re
import zipfile

from functions_document_merge import (
    DocumentMergeError,
    WORKBOOK_SHEETS_ALL,
    finish_output,
    guard_ooxml_package,
    new_output_spool,
    normalized_package,
)


_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_INVALID_SHEET_CHARACTERS = set('[]:*?/\\')
# XML 1.0 can't hold these, so openpyxl refuses them with an error that quotes the cell.
_ILLEGAL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAX_SHEET_NAME = 31
_MAX_CELL_CHARACTERS = 32_767
_GENERAL_FORMATS = ("General", None, "")
_PACKAGE_DATE = datetime(2000, 1, 1)


def assemble_workbook(context):
    """Copy each part's selected sheets, in order, into one new workbook."""
    # openpyxl loads only when a workbook merge runs.
    from openpyxl import Workbook

    output = Workbook(write_only=True)
    try:
        return _assemble_into(output, context)
    except BaseException:
        _discard_workbook(output)
        raise


def _assemble_into(output, context):
    used_names = set()
    totals = {"sheets": 0, "cells": 0}
    every_sheet = context.options.sheets == WORKBOOK_SHEETS_ALL and context.options.sheet is None
    for index, part in enumerate(context.parts):
        content = context.load(index)
        try:
            _copy_part(output, context, index, part, content, used_names, totals, every_sheet)
        except DocumentMergeError:
            raise
        except Exception as exc:
            if not context.blames_file(exc):
                raise
            # Library errors can quote cell text, so only the file's name is reported.
            raise DocumentMergeError(
                "unreadable_document", f"{part.display_name()} couldn't be copied into the workbook.",
            ) from exc
        context.progress(index)

    context.report["totals"]["sheets"] = totals["sheets"]
    context.report["totals"]["cells"] = totals["cells"]
    context.limit(
        "Cell values and number formats are copied. Styles, column widths, merged cells, charts, images "
        "and formulas are not; formulas contribute their last calculated values."
    )
    if any(part.resolved_extension() == ".csv" for part in context.parts):
        context.limit("CSV files are copied as text, so codes keep their leading zeros.")
    return finish_output(context, _write_package(output, context))


def _copy_part(output, context, index, part, content, used_names, totals, every_sheet):
    extension = part.resolved_extension()
    if extension == ".csv":
        sheets = _csv_sheets(part, content)
    elif extension == ".xls":
        sheets = _xls_sheets(part, content, context)
    else:
        guard_ooxml_package(content, part, context.limits, "Excel workbook")
        sheets = _xlsx_sheets(part, content, context)
    entry = context.part_entry(index)
    entry["sheets"] = 0
    entry["rows"] = 0
    removed = 0
    for sheet_label, rows in sheets:
        context.check_cancel()
        if totals["sheets"] >= context.limits.max_sheets:
            raise DocumentMergeError(
                "sheet_limit_exceeded", f"The merged workbook would have more than {context.limits.max_sheets} sheets.",
            )
        # One sheet per file is named after the file; every-sheet mode adds the sheet name.
        name = _unique_sheet_name(_sheet_base_name(part, sheet_label if every_sheet else None), used_names)
        worksheet = output.create_sheet(title=name)
        written, stripped = _write_rows(worksheet, rows, context, totals, part)
        entry["sheets"] += 1
        entry["rows"] += written
        entry.setdefault("sheet_names", []).append(name)
        totals["sheets"] += 1
        removed += stripped
    if entry["sheets"] == 0:
        raise DocumentMergeError("empty_source", f"{part.display_name()} has no sheets to merge.")
    if removed:
        context.warn(
            "control_characters_removed", f"{removed:,} control character(s) that Excel can't store were removed.",
            index,
        )


def _write_package(output, context):
    """Write the workbook with fixed dates, so the same files always give the same bytes."""
    from openpyxl.writer.excel import ExcelWriter

    output.properties.creator = "SimpleChat"
    output.properties.created = output.properties.modified = _PACKAGE_DATE
    package = new_output_spool()
    try:
        # Workbook.save() would stamp the current time as the modified date.
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            ExcelWriter(output, archive).write_data()
        return normalized_package(package, context)
    except DocumentMergeError:
        raise
    except Exception as exc:
        if not context.blames_file(exc):
            raise
        raise DocumentMergeError("merge_failed", "The merged workbook couldn't be written.") from exc
    finally:
        package.close()


def _discard_workbook(workbook):
    """Finish and delete the temporary sheet streams of a write-only workbook that won't be saved."""
    for worksheet in list(getattr(workbook, "_sheets", ())):
        try:
            worksheet.close()
        except Exception:
            pass
        writer = getattr(worksheet, "_writer", None)
        if writer is not None:
            try:
                writer.cleanup()
            except Exception:
                pass


def _csv_sheets(part, content):
    # The merge engine owns CSV encoding and delimiter detection.
    from functions_tabular_merge import TabularMergeError, iter_csv_rows

    try:
        _encoding, _delimiter, rows = iter_csv_rows(content, part.display_name())
    except TabularMergeError as exc:
        raise DocumentMergeError("unreadable_document", exc.message) from exc

    def checked_rows():
        try:
            for values in rows:
                yield [(value, None) for value in values]
        except TabularMergeError as exc:
            raise DocumentMergeError("unreadable_document", exc.message) from exc

    yield None, checked_rows()


def _xlsx_sheets(part, content, context):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        raise DocumentMergeError(
            "unreadable_document", f"{part.display_name()} couldn't be opened as an Excel workbook.",
        ) from exc
    try:
        names = _chosen_sheets(
            part, [(sheet.title, getattr(sheet, "sheet_state", "visible")) for sheet in workbook.worksheets],
            context,
        )
        for name in names:
            worksheet = workbook[name]
            worksheet.reset_dimensions()
            yield name, _xlsx_rows(worksheet, part)
    finally:
        workbook.close()


def _xlsx_rows(worksheet, part):
    try:
        for row in worksheet.iter_rows():
            yield [(cell.value, getattr(cell, "number_format", None)) for cell in row]
    except DocumentMergeError:
        raise
    except Exception as exc:
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} couldn't be read.") from exc


def _xls_sheets(part, content, context):
    if content[:8] != _OLE_MAGIC:
        raise DocumentMergeError(
            "unreadable_document", f"{part.display_name()} isn't a valid Excel 97-2003 (.xls) workbook.",
        )
    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except Exception as exc:
        code = "encrypted_document" if "encrypt" in str(exc).lower() else "unreadable_document"
        message = (
            f"{part.display_name()} is password-protected or encrypted, so it can't be merged."
            if code == "encrypted_document" else f"{part.display_name()} couldn't be opened as an Excel workbook."
        )
        raise DocumentMergeError(code, message) from exc
    try:
        names = book.sheet_names()
        # The workbook header records visibility, so no sheet is parsed just to read it.
        visibility = getattr(book, "_sheet_visibility", None)
        if not isinstance(visibility, list) or len(visibility) != len(names):
            visibility = [getattr(book.sheet_by_index(position), "visibility", 0) for position in range(len(names))]
        states = [(name, "visible" if state == 0 else "hidden") for name, state in zip(names, visibility)]
        for name in _chosen_sheets(part, states, context):
            sheet = book.sheet_by_name(name)
            yield name, _xls_rows(xlrd, sheet, book.datemode)
            # The sheet's rows were written before the next sheet was asked for.
            book.unload_sheet(name)
    finally:
        try:
            book.release_resources()
        except Exception:
            pass


def _xls_rows(xlrd, sheet, datemode):
    for row_index in range(sheet.nrows):
        values = []
        for cell in sheet.row(row_index):
            if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                values.append((None, None))
            elif cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    moment = xlrd.xldate_as_datetime(cell.value, datemode)
                    pattern = "yyyy-mm-dd" if moment.time() == time(0, 0) else "yyyy-mm-dd hh:mm:ss"
                    values.append((moment, pattern))
                except Exception:
                    values.append((cell.value, None))
            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                values.append((bool(cell.value), None))
            elif cell.ctype == xlrd.XL_CELL_ERROR:
                values.append((xlrd.error_text_from_code.get(cell.value, "#ERROR"), None))
            else:
                values.append((cell.value, None))
        yield values


def _chosen_sheets(part, sheets, context):
    names = [name for name, _ in sheets]
    if not names:
        raise DocumentMergeError("empty_source", f"{part.display_name()} has no worksheets.")
    requested = context.options.sheet
    if requested is not None:
        for name in names:
            if name == requested or name.casefold() == requested.casefold():
                return [name]
        raise DocumentMergeError(
            "sheet_not_found", f'{part.display_name()} has no sheet named "{requested}".',
            details={"available_sheets": names},
        )
    visible = [name for name, state in sheets if state == "visible"] or names[:1]
    if context.options.sheets == WORKBOOK_SHEETS_ALL:
        hidden = len(names) - len(visible)
        if hidden:
            context.warn("hidden_sheets_skipped", f"{hidden} hidden sheet(s) were not copied.")
        return visible
    return visible[:1]


def _write_rows(worksheet, rows, context, totals, part):
    """Append the rows; return how many were written and how many characters were removed."""
    from openpyxl.cell import WriteOnlyCell

    written = 0
    removed = 0
    for values in rows:
        if written >= context.limits.max_sheet_rows:
            raise DocumentMergeError(
                "row_limit_exceeded", f"A sheet from {part.display_name()} has more rows than Excel allows.",
            )
        totals["cells"] += len(values)
        if totals["cells"] > context.limits.max_total_cells:
            raise DocumentMergeError(
                "cell_limit_exceeded", f"The merged workbook would have more than {context.limits.max_total_cells:,} cells.",
            )
        cells = []
        for value, number_format in values:
            value, stripped = _cell_value(value, part)
            removed += stripped
            cell = WriteOnlyCell(worksheet, value=value)
            if isinstance(value, str):
                # Literal text, never a formula, even when it starts with "=".
                cell.data_type = "s"
            elif number_format not in _GENERAL_FORMATS and isinstance(value, (int, float, datetime, date, time)):
                cell.number_format = number_format
            cells.append(cell)
        worksheet.append(cells)
        written += 1
        if written % 1000 == 0:
            context.check_cancel()
    return written, removed


def _cell_value(value, part):
    """The value to write, and how many characters Excel can't store were removed from it."""
    if value is None or isinstance(value, (bool, int, float, datetime, date, time, timedelta)):
        if isinstance(value, float) and value != value:
            return None, 0
        return value, 0
    text, removed = _ILLEGAL_CHARACTERS.subn("", str(value))
    if len(text) > _MAX_CELL_CHARACTERS:
        raise DocumentMergeError(
            "cell_too_large", f"{part.display_name()} has a value longer than an Excel cell allows.",
        )
    return text, removed


def _sheet_base_name(part, sheet_label):
    stem = part.display_name()
    for extension in (".xlsx", ".xlsm", ".xls", ".csv"):
        if stem.lower().endswith(extension):
            stem = stem[: -len(extension)]
            break
    if sheet_label:
        stem = f"{stem} - {sheet_label}"
    return stem


def _unique_sheet_name(base, used_names):
    cleaned = _ILLEGAL_CHARACTERS.sub(" ", str(base))
    cleaned = "".join(" " if character in _INVALID_SHEET_CHARACTERS else character for character in cleaned)
    cleaned = " ".join(cleaned.split()).strip("'").strip() or "Sheet"
    candidate = cleaned[:_MAX_SHEET_NAME].strip("'").strip() or "Sheet"
    suffix = 2
    while candidate.casefold() in used_names:
        tail = f" ({suffix})"
        candidate = cleaned[: _MAX_SHEET_NAME - len(tail)].strip("'").strip() + tail
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


__all__ = ["assemble_workbook"]
