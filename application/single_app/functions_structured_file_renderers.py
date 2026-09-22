# functions_structured_file_renderers.py
"""Bounded serializers used only by the shared generated-file dispatcher."""

import csv
import hashlib
import html
import json
import math
import re
import tempfile
from contextlib import ExitStack
from dataclasses import fields

import yaml

from functions_assistant_table_exports import neutralize_csv_spreadsheet_formula
from functions_export_cleanup import ClosingExportResource
from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportLimits,
    GeneratedFileExportReadiness,
    GeneratedFileExportStream,
)
from functions_generated_export_registry import resolve_generated_file_export_format


_CHUNK_CHARACTERS = 16384
_CHECK_BYTES = 65536
_MISSING = object()
_INVALID_XML_CHARACTERS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_COMPACT_JSON = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
_EXACT_JSON = json.JSONEncoder(
    sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'),
)


class _SourceChecks:
    def __init__(self, source, check):
        self.source = source
        self.kind = source.kind
        self.count_attribute = (
            'record_count' if self.kind == 'records'
            else 'character_count' if self.kind in ('text', 'markdown') else None
        )
        self.expected_count = getattr(source, self.count_attribute) if self.count_attribute else None
        self.check = check

    def run(self):
        if self.check is not None:
            self.check()
        self.source.recheck()
        if self.source.kind != self.kind:
            raise GeneratedFileExportError('invalid_source', 'The source kind changed during rendering.')
        if self.count_attribute:
            count = getattr(self.source, self.count_attribute, None)
            if type(count) is not int or count != self.expected_count:
                raise GeneratedFileExportError('count_mismatch', 'The declared source count changed during rendering.')
        readiness = getattr(self.source, 'readiness', _MISSING)
        if readiness is _MISSING and self.kind == 'records':
            return
        if not isinstance(readiness, GeneratedFileExportReadiness):
            raise GeneratedFileExportError('invalid_source', 'Explicit source readiness is required.')
        if (
            readiness.state != 'ready'
            or readiness.is_complete is not True
            or readiness.is_preview is not False
        ):
            raise GeneratedFileExportError(
                'incomplete_source', 'Only ready, complete, non-preview sources can be exported.',
            )


class _OutputWriter:
    def __init__(
        self, stream, limit, checks, *, limit_code='size_limit',
        limit_message='The complete saved-output file exceeds the configured artifact size limit.',
    ):
        self.stream = stream
        self.limit = limit
        self.checks = checks
        self.size = 0
        self.checked_size = 0
        self.digest = hashlib.sha256()
        self.limit_code = limit_code
        self.limit_message = limit_message

    def write(self, text):
        for offset in range(0, len(text), _CHUNK_CHARACTERS):
            try:
                chunk = text[offset:offset + _CHUNK_CHARACTERS].encode('utf-8')
            except UnicodeError as exc:
                raise GeneratedFileExportError('invalid_data', 'Source text must be valid Unicode.') from exc
            if self.size + len(chunk) > self.limit:
                raise GeneratedFileExportError(self.limit_code, self.limit_message)
            self.stream.write(chunk)
            self.digest.update(chunk)
            self.size += len(chunk)
            if self.size - self.checked_size >= _CHECK_BYTES:
                self.checks.run()
                self.checked_size = self.size
        return len(text)


class _ValueBudget:
    def __init__(self, limits, checks, allow_surrogates=False):
        self.limits = limits
        self.checks = checks
        self.allow_surrogates = allow_surrogates
        self.size = 0
        self.nodes = 0
        self.checked_size = 0
        self.active = set()

    def add_text(self, value):
        if len(value) > self.limits.max_value_bytes - self.size:
            self.exceeded()
        for offset in range(0, len(value), _CHUNK_CHARACTERS):
            fragment = value[offset:offset + _CHUNK_CHARACTERS]
            try:
                encoded = fragment.encode('utf-8', errors='surrogatepass' if self.allow_surrogates else 'strict')
            except UnicodeError as exc:
                raise GeneratedFileExportError('invalid_data', 'Source values must be valid Unicode.') from exc
            self.size += len(encoded)
            if self.size > self.limits.max_value_bytes:
                self.exceeded()
            if self.size - self.checked_size >= _CHECK_BYTES:
                self.checks.run()
                self.checked_size = self.size

    def exceeded(self):
        raise GeneratedFileExportError('value_limit', 'A source value exceeds the bounded value limits.')

    def validate(self, value, depth=0):
        self.nodes += 1
        if self.nodes > self.limits.max_value_nodes or depth > self.limits.max_depth:
            self.exceeded()
        if self.nodes % 1024 == 0:
            self.checks.run()
        value_type = type(value)
        if value_type in (dict, list):
            identity = id(value)
            if identity in self.active:
                raise GeneratedFileExportError('invalid_data', 'Cyclic source values are not supported.')
            self.active.add(identity)
            try:
                if value_type is dict:
                    for key, child in value.items():
                        if type(key) is not str:
                            raise GeneratedFileExportError('invalid_data', 'Object keys must be strings.')
                        self.validate(key, depth + 1)
                        self.validate(child, depth + 1)
                else:
                    for child in value:
                        self.validate(child, depth + 1)
            finally:
                self.active.remove(identity)
        elif value_type is str:
            self.add_text(value)
        elif value_type is int:
            if value.bit_length() > self.limits.max_value_bytes * 4:
                self.exceeded()
            try:
                self.add_text(str(value))
            except ValueError as exc:
                if isinstance(exc, GeneratedFileExportError):
                    raise
                raise GeneratedFileExportError('value_limit', 'An integer exceeds the numeric size limit.') from exc
        elif value_type is float:
            if not math.isfinite(value):
                raise GeneratedFileExportError('invalid_data', 'Only finite JSON-domain values are supported.')
            self.add_text(str(value))
        elif value_type not in (bool, type(None)):
            raise GeneratedFileExportError('invalid_data', 'Only finite JSON-domain values are supported.')


def _validate_value(value, limits, checks, profile):
    budget = _ValueBudget(limits, checks, allow_surrogates=profile == 'exact_records_v1')
    budget.validate(value)


def _iter_records(source, limits, checks, profile):
    expected_count = source.record_count
    records = source.iter_records()
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise GeneratedFileExportError('invalid_source', 'A complete records iterator is required.') from exc
    count = 0
    with ClosingExportResource(iterator):
        for record in iterator:
            if type(record) is not dict:
                raise GeneratedFileExportError('invalid_data', 'Every exported record must be an object.')
            if count >= expected_count:
                raise GeneratedFileExportError('count_mismatch', 'The saved record count is inconsistent.')
            _validate_value(record, limits, checks, profile)
            yield record
            count += 1
            if count % 100 == 0:
                checks.run()
        if count != expected_count or source.record_count != expected_count:
            raise GeneratedFileExportError(
                'count_mismatch', 'The complete saved record count does not match the exported file.',
            )


def _read_value(source, limits, checks, profile):
    value = source.read_value()
    _validate_value(value, limits, checks, profile)
    return value


def _write_json_value(writer, value, encoder):
    for fragment in encoder.iterencode(value):
        writer.write(fragment)


def _render_json(writer, source, request, limits, checks):
    encoder = _EXACT_JSON if request.profile == 'exact_records_v1' else _COMPACT_JSON
    if source.kind == 'structured_value':
        _write_json_value(writer, _read_value(source, limits, checks, request.profile), encoder)
        return 0
    writer.write('[')
    count = 0
    with ClosingExportResource(_iter_records(source, limits, checks, request.profile)) as records:
        for record in records:
            if count:
                writer.write(',')
            _write_json_value(writer, record, encoder)
            count += 1
    writer.write(']')
    return count


def _validate_column_names(columns, limits, checks, label='CSV'):
    if type(columns) not in (tuple, list) or not columns:
        raise GeneratedFileExportError('invalid_options', f'{label} requires explicit ordered columns.')
    if len(columns) >= limits.max_value_nodes:
        raise GeneratedFileExportError('value_limit', 'The column count exceeds the source value limit.')
    if any(type(column) is not str or not column.strip() for column in columns):
        raise GeneratedFileExportError('invalid_options', f'{label} columns must be non-empty strings.')
    _validate_value(list(columns), limits, checks, 'tabular_records_v1')
    if len(set(columns)) != len(columns):
        raise GeneratedFileExportError('invalid_options', f'{label} columns must be distinct.')
    return tuple(columns)


def _validate_columns(columns, limits, checks):
    columns = _validate_column_names(columns, limits, checks)
    safe_columns = [neutralize_csv_spreadsheet_formula(column) for column in columns]
    if len({column.casefold() for column in safe_columns}) != len(safe_columns):
        raise GeneratedFileExportError('invalid_options', 'CSV columns must have distinct safe headers.')
    return tuple(columns), safe_columns


def _csv_cell(value):
    if value is None:
        return ''
    if type(value) is str:
        return neutralize_csv_spreadsheet_formula(value)
    if type(value) in (bool, int, float):
        return _COMPACT_JSON.encode(value)
    raise GeneratedFileExportError(
        'invalid_data', 'CSV requires scalar cells; nested values need an explicit upstream projection.',
    )


def _render_csv(writer, source, request, limits, checks):
    columns, safe_columns = _validate_columns(request.columns, limits, checks)
    expected_keys = set(columns)
    csv_writer = csv.writer(writer, lineterminator='\r\n')
    csv_writer.writerow(safe_columns)
    count = 0
    with ClosingExportResource(_iter_records(source, limits, checks, request.profile)) as records:
        for record in records:
            if set(record) != expected_keys:
                raise GeneratedFileExportError('invalid_data', 'Every CSV row must match the declared columns.')
            csv_writer.writerow([_csv_cell(record[column]) for column in columns])
            count += 1
    return count


def _write_xml_string(writer, value, *, attribute=False):
    for offset in range(0, len(value), _CHUNK_CHARACTERS):
        fragment = value[offset:offset + _CHUNK_CHARACTERS]
        if _INVALID_XML_CHARACTERS.search(fragment):
            raise GeneratedFileExportError('invalid_data', 'The source contains an invalid XML character.')
        escaped = html.escape(fragment, quote=attribute).replace('\r', '&#13;')
        if attribute:
            escaped = escaped.replace('\n', '&#10;').replace('\t', '&#9;')
        writer.write(escaped)


def _write_xml_value(writer, value):
    value_type = type(value)
    if value_type is dict:
        writer.write('<object>')
        for key, child in value.items():
            writer.write('<member name="')
            _write_xml_string(writer, key, attribute=True)
            writer.write('">')
            _write_xml_value(writer, child)
            writer.write('</member>')
        writer.write('</object>')
    elif value_type is list:
        writer.write('<array>')
        for child in value:
            writer.write('<item>')
            _write_xml_value(writer, child)
            writer.write('</item>')
        writer.write('</array>')
    elif value is None:
        writer.write('<null/>')
    elif value_type is str:
        writer.write('<string>')
        _write_xml_string(writer, value)
        writer.write('</string>')
    else:
        tag = 'boolean' if value_type is bool else 'integer' if value_type is int else 'number'
        writer.write(f'<{tag}>{_COMPACT_JSON.encode(value)}</{tag}>')


def _render_xml(writer, source, request, limits, checks):
    writer.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    if source.kind == 'structured_value':
        value = _read_value(source, limits, checks, request.profile)
        writer.write('<value>')
        _write_xml_value(writer, value)
        writer.write('</value>')
        return 0
    writer.write('<records>')
    count = 0
    with ClosingExportResource(_iter_records(source, limits, checks, request.profile)) as records:
        for record in records:
            writer.write('<record>')
            _write_xml_value(writer, record)
            writer.write('</record>')
            count += 1
    writer.write('</records>')
    return count


class _ValueSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _dump_yaml(writer, value, *, document=False):
    yaml.dump(
        value, stream=writer, Dumper=_ValueSafeDumper, allow_unicode=True, sort_keys=False,
        default_flow_style=True, explicit_start=document, explicit_end=document,
    )


def _render_yaml(writer, source, request, limits, checks):
    if source.kind == 'structured_value':
        _dump_yaml(writer, _read_value(source, limits, checks, request.profile), document=True)
        return 0
    writer.write('---\n[\n')
    count = 0
    with ClosingExportResource(_iter_records(source, limits, checks, request.profile)) as records:
        for record in records:
            if count:
                writer.write(',\n')
            _dump_yaml(writer, record)
            count += 1
    writer.write(']\n...\n')
    return count


def _render_text(writer, source, request, limits, checks):
    expected_count = source.character_count
    count = 0
    fragments = source.iter_text()
    try:
        iterator = iter(fragments)
    except TypeError as exc:
        raise GeneratedFileExportError('invalid_source', 'A complete text iterator is required.') from exc
    with ClosingExportResource(iterator):
        for chunk_count, fragment in enumerate(iterator, start=1):
            if chunk_count > limits.max_text_chunks:
                raise GeneratedFileExportError('value_limit', 'The text chunk count exceeds the source limit.')
            if type(fragment) is not str:
                raise GeneratedFileExportError('invalid_data', 'Prepared text chunks must be strings.')
            count += len(fragment)
            if count > expected_count:
                raise GeneratedFileExportError('count_mismatch', 'The declared text character count is inconsistent.')
            writer.write(fragment)
            if chunk_count % 100 == 0:
                checks.run()
        if count != expected_count or source.character_count != expected_count:
            raise GeneratedFileExportError('count_mismatch', 'The complete text character count is inconsistent.')
    return 0


_RENDERERS = {
    'csv': _render_csv,
    'json': _render_json,
    'xml': _render_xml,
    'yaml': _render_yaml,
    'text': _render_text,
}


def _validate_export_limits(limits, max_output_bytes):
    if type(max_output_bytes) is not int or max_output_bytes < 1:
        raise GeneratedFileExportError('invalid_limit', 'A positive saved-output byte limit is required.')
    if not isinstance(limits, GeneratedFileExportLimits) or any(
        type(getattr(limits, field.name)) is not int or getattr(limits, field.name) < 1
        for field in fields(GeneratedFileExportLimits)
    ) or limits.max_depth > 64:
        raise GeneratedFileExportError('invalid_limit', 'Positive source limits and depth at most 64 are required.')


def _validate_source_limits(source, limits, max_output_bytes, check):
    _validate_export_limits(limits, max_output_bytes)
    if not callable(getattr(source, 'recheck', None)) or (check is not None and not callable(check)):
        raise GeneratedFileExportError('invalid_source', 'Source and execution rechecks must be callable.')
    method = {
        'records': 'iter_records', 'structured_value': 'read_value',
        'text': 'iter_text', 'markdown': 'iter_text',
    }[source.kind]
    if not callable(getattr(source, method, None)):
        raise GeneratedFileExportError('invalid_source', 'A complete source reader is required.')
    if source.kind == 'records':
        count = getattr(source, 'record_count', None)
        if type(count) is not int or count < 0:
            raise GeneratedFileExportError('invalid_source', 'The saved record count is invalid.')
        if count > limits.max_records:
            raise GeneratedFileExportError('record_limit', 'The declared record count exceeds the source limit.')
    elif source.kind in ('text', 'markdown'):
        count = getattr(source, 'character_count', None)
        if type(count) is not int or count < 0:
            raise GeneratedFileExportError('invalid_source', 'The declared text character count is invalid.')


def _render_generated_file_source(source, request, *, max_output_bytes, check=None, limits=None):
    """Serialize behind the existing facade; transfer ownership only on success."""
    entry = resolve_generated_file_export_format(request, getattr(source, 'kind', None))
    limits = GeneratedFileExportLimits() if limits is None else limits
    _validate_source_limits(source, limits, max_output_bytes, check)
    checks = _SourceChecks(source, check)
    checks.run()
    with ExitStack() as resources:
        stream = resources.enter_context(ClosingExportResource(tempfile.TemporaryFile(mode='w+b', dir='.')))
        try:
            writer = _OutputWriter(stream, max_output_bytes, checks)
            count = _RENDERERS[entry.renderer_id](writer, source, request, limits, checks)
            stream.flush()
            stream.seek(0)
            checks.run()
            result = GeneratedFileExportStream(
                file_content=stream, output_format=entry.format_id, media_type=entry.media_type,
                size_bytes=writer.size, content_sha256=writer.digest.hexdigest(),
                record_count=count, profile=request.profile, source_kind=source.kind,
                file_extension=entry.file_extension,
                character_count=source.character_count if source.kind in ('text', 'markdown') else None,
            )
        except (RecursionError, UnicodeError) as exc:
            raise GeneratedFileExportError('invalid_data', 'Source values must be bounded valid Unicode data.') from exc
        resources.pop_all()
        return result
