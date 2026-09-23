# test_generated_file_structured_renderers.py
"""
Functional tests for explicit complete-source generated-file serializers.
Version: 0.261.127
Implemented in: 0.261.126

Exercise production dispatch, independent readback, bounds, authorization,
cancellation, cleanup, and cold imports without cloud or provider services.
"""

import csv
import hashlib
import io
import json
import math
import subprocess
import sys
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from defusedxml import ElementTree

# Standalone tests add the application directory before importing production code.
ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / 'application' / 'single_app'
sys.path.insert(0, str(APP_ROOT))

import functions_structured_file_renderers as renderers  # noqa: E402
from functions_export_cleanup import ClosingExportResource, close_export_resource  # noqa: E402
from functions_generated_file_exports import (  # noqa: E402
    GeneratedFileExportError,
    GeneratedFileExportLimits,
    GeneratedFileExportReadiness,
    GeneratedFileExportRequest,
    build_generated_file_export,
    get_generated_file_export_catalog,
)


READY = GeneratedFileExportReadiness()
RECORD_FORMATS = (
    ('json', 'exact_records_v1'),
    ('json', 'structured_records_v1'),
    ('csv', 'tabular_records_v1'),
    ('xml', 'typed_xml_v1'),
    ('yaml', 'structured_records_v1'),
)
VALUE_FORMATS = (
    ('json', 'structured_value_v1'),
    ('xml', 'typed_xml_v1'),
    ('yaml', 'structured_value_v1'),
)


class RecordSource:
    kind = 'records'

    def __init__(self, records, count, readiness=READY):
        self.records = records
        self.record_count = count
        self.readiness = readiness
        self.reads = 0
        self.checks = 0
        self.iterations = 0
        self.closed = False
        self.on_recheck = None

    def iter_records(self):
        self.iterations += 1
        try:
            for record in self.records:
                self.reads += 1
                yield record
        finally:
            self.closed = True

    def recheck(self):
        self.checks += 1
        if self.on_recheck is not None:
            self.on_recheck()


class ValueSource:
    kind = 'structured_value'

    def __init__(self, value, readiness=READY):
        self.value = value
        self.readiness = readiness
        self.reads = 0
        self.checks = 0
        self.on_recheck = None

    def read_value(self):
        self.reads += 1
        return self.value

    def recheck(self):
        self.checks += 1
        if self.on_recheck is not None:
            self.on_recheck()


class TextSource(RecordSource):
    def __init__(self, fragments, character_count, kind='text', readiness=READY):
        super().__init__(fragments, 0, readiness)
        self.kind = kind
        self.character_count = character_count

    def iter_text(self):
        yield from self.iter_records()


class CleanupFailingIterator:
    def __init__(self, items, *, primary=None, cause=None):
        self.items = items
        self.primary = primary
        self.cause = cause
        self.reads = 0
        self.close_calls = 0
        self.cleanup_error = OSError('private cleanup details must not replace the primary error')

    def __iter__(self):
        return self

    def __next__(self):
        if self.reads == len(self.items):
            if self.primary is not None:
                raise self.primary from self.cause
            raise StopIteration
        item = self.items[self.reads]
        self.reads += 1
        return item

    def close(self):
        self.close_calls += 1
        raise self.cleanup_error


def cleanup_source(output_format, iterator, count):
    if output_format in ('md', 'txt'):
        source = TextSource([], count, 'markdown' if output_format == 'md' else 'text')
        source.iter_text = lambda: iterator
    else:
        source = RecordSource([], count)
        source.iter_records = lambda: iterator
    return source


def render(source, output_format, profile, *, columns=None, limit=32 * 1024 * 1024, **options):
    return build_generated_file_export(
        source=source,
        export_request=GeneratedFileExportRequest(output_format, profile, columns),
        max_output_bytes=limit,
        **options,
    )


def decode_xml_value(element):
    if element.tag == 'object':
        return {child.attrib['name']: decode_xml_value(child[0]) for child in element}
    if element.tag == 'array':
        return [decode_xml_value(child[0]) for child in element]
    if element.tag == 'null':
        return None
    if element.tag == 'boolean':
        return element.text == 'true'
    if element.tag == 'integer':
        return int(element.text)
    if element.tag == 'number':
        return float(element.text)
    if element.tag == 'string':
        return element.text or ''
    raise AssertionError(f'Unexpected typed XML node: {element.tag}')


def readback(payload, output_format, *, records=False):
    if output_format == 'json':
        return json.loads(payload)
    if output_format in ('yaml', 'yml'):
        return yaml.safe_load(payload)
    if output_format == 'csv':
        return list(csv.reader(io.StringIO(payload.decode('utf-8'), newline='')))
    if output_format == 'xml':
        root = ElementTree.fromstring(payload, forbid_dtd=True, forbid_entities=True)
        return [decode_xml_value(record[0]) for record in root] if records else decode_xml_value(root[0])
    return payload.decode('utf-8')


def assert_same_value(actual, expected):
    assert type(actual) is type(expected)
    if type(expected) is dict:
        assert list(actual) == list(expected)
        for key, value in expected.items():
            assert_same_value(actual[key], value)
    elif type(expected) is list:
        assert len(actual) == len(expected)
        for actual_child, expected_child in zip(actual, expected):
            assert_same_value(actual_child, expected_child)
    else:
        assert actual == expected
        if type(expected) is float and expected == 0:
            assert math.copysign(1, actual) == math.copysign(1, expected)


@pytest.fixture
def opened_streams(monkeypatch):
    original = renderers.tempfile.TemporaryFile
    opened = []

    def tracked(*args, **kwargs):
        assert kwargs.get('dir') == '.'
        stream = original(*args, **kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(renderers.tempfile, 'TemporaryFile', tracked)
    return opened


def test_catalog_is_stable_json_safe_and_does_not_admit_runtime_capabilities():
    catalog = get_generated_file_export_catalog()
    encoded = json.dumps(catalog)
    decoded = json.loads(encoded)
    assert [entry['format_id'] for entry in decoded] == [
        'csv', 'json', 'xml', 'yaml', 'md', 'txt', 'xlsx', 'docx', 'pdf', 'pptx',
    ]
    profile = decoded[1]['profiles'][0]
    assert {key: profile[key] for key in (
        'profile', 'source_kinds', 'required_options', 'supported_options', 'requires_complete',
    )} == {
        'profile': 'exact_records_v1', 'source_kinds': ['records'],
        'required_options': [], 'supported_options': [], 'requires_complete': True,
    }
    assert decoded[0]['profiles'][0]['required_options'] == ['columns']
    assert all(entry['max_output_bytes_required'] for entry in decoded)
    assert all(entry['streaming'] for entry in decoded[:7])
    assert all(not entry['validation_failures_retryable'] for entry in decoded)
    catalog[0]['aliases'].append('unsafe')
    catalog[0]['default_limits']['max_records'] = 0
    fresh = get_generated_file_export_catalog()
    assert fresh == decoded


@pytest.mark.parametrize('output_format,profile', VALUE_FORMATS)
@pytest.mark.parametrize('value', [
    None, True, False, 0, 9007199254740993, -0.0, 0.125, '', [], {},
    {
        'z': [None, False, 0, 0.0, True, '001', 'yes', 'on', 'null', '2026-09-21'],
        'a': {'λ': '😀\n<&>"\r\nnext', 'empty': {}, 'list': []},
    },
])
def test_structured_values_round_trip_with_exact_types_and_key_order(output_format, profile, value):
    source = ValueSource(value)
    with render(source, output_format, profile) as result:
        payload = result.file_content.read()
        restored = readback(payload, output_format)
        assert_same_value(restored, value)
        assert result.record_count == 0 and result.source_kind == 'structured_value'
        assert result.size_bytes == len(payload)
        assert result.content_sha256 == hashlib.sha256(payload).hexdigest()
    assert source.reads == 1 and source.checks >= 2
    assert result.file_content.closed
    if output_format == 'yaml':
        assert b'!!python' not in payload and b'&id' not in payload


@pytest.mark.parametrize('output_format,profile', [
    ('json', 'structured_records_v1'), ('xml', 'typed_xml_v1'), ('yaml', 'structured_records_v1'),
])
def test_nested_records_preserve_row_order_duplicates_and_distinct_shapes(output_format, profile):
    shared = {'b': 1, 'a': [None, False, {'unicode': 'λ😀'}]}
    expected = [{'second': shared, 'first': shared}, {'other': []}, {'second': shared, 'first': shared}]
    source = RecordSource(iter(expected), len(expected))
    with render(source, output_format, profile) as result:
        payload = result.file_content.read()
        restored = readback(payload, output_format, records=True)
        assert_same_value(restored, expected)
        assert result.record_count == 3
    assert source.reads == 3 and source.iterations == 1 and source.closed
    if output_format == 'yaml':
        assert b'!!python' not in payload and b'&id' not in payload


def test_legacy_json_keeps_compact_sorted_ascii_bytes_including_escaped_surrogates():
    records = [{'z': 'λ😀\ud800', 'b': [False, None, 1.0, -0.0], 'a': {'y': 2, 'x': 1}}]
    expected = json.dumps(
        records, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False,
    ).encode('ascii')
    with render(RecordSource(records, 1), 'json', 'exact_records_v1') as result:
        actual = result.file_content.read()
        assert actual == expected
        assert result.media_type == 'application/json'


def test_csv_order_escaping_multiline_unicode_and_formula_safety():
    columns = ('identifier', '=header', 'description', 'amount', 'enabled', 'empty')
    description = 'comma, "quotes"\r\nline two\nline three\rlast λ😀'
    records = [
        {'empty': None, 'enabled': False, 'amount': -3.5, 'description': description,
         '=header': '=SUM(A1:A2)', 'identifier': '001'},
        {'identifier': '+001', '=header': '\t @SUM(A1:A2)', 'description': ' plain ',
         'amount': 0, 'enabled': True, 'empty': ''},
    ]
    with render(RecordSource(records, 2), 'csv', 'tabular_records_v1', columns=columns) as result:
        payload = result.file_content.read()
        restored = readback(payload, 'csv')
        assert restored == [
            ['identifier', "'=header", 'description', 'amount', 'enabled', 'empty'],
            ['001', "'=SUM(A1:A2)", description, '-3.5', 'false', ''],
            ['+001', "'\t @SUM(A1:A2)", ' plain ', '0', 'true', ''],
        ]
        assert result.record_count == 2
        assert payload.endswith(b'\r\n')


@pytest.mark.parametrize('value,expected', [
    ('=1+1', "'=1+1"), ('+SUM(A1:A2)', "'+SUM(A1:A2)"),
    ('-SUM(A1:A2)', "'-SUM(A1:A2)"), ('@cmd', "'@cmd"),
    ('\t=1', "'\t=1"), ('\r=1', "'\r=1"), ('  =1', "'  =1"),
    ('-1.5', '-1.5'), ('+12', '+12'), ('-1e3', '-1e3'), ('001', '001'),
])
def test_csv_reuses_existing_spreadsheet_cell_policy(value, expected):
    with render(
        RecordSource([{'value': value}], 1), 'csv', 'tabular_records_v1', columns=('value',),
    ) as result:
        payload = result.file_content.read()
        restored = readback(payload, 'csv')
    assert restored == [['value'], [expected]]


@pytest.mark.parametrize('columns', [
    None, (), 'value', ('',), ('  ',), (1,), ('a', 'a'), ('a', 'A'), ('=a', "'=a"),
])
def test_csv_requires_unambiguous_explicit_ordered_headers(columns, opened_streams):
    source = RecordSource([{'a': 1}], 1)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'csv', 'tabular_records_v1', columns=columns)
    assert failure.value.code == 'invalid_options'
    assert source.reads == 0
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('bad_record', [
    {}, {'a': 1, 'extra': 2}, {'a': [1]}, {'a': {'nested': True}}, {'a': (1,)}, ['not', 'object'],
])
def test_csv_never_drops_fields_or_stringifies_nested_or_heterogeneous_rows(bad_record, opened_streams):
    source = RecordSource([{'a': 1}, bad_record], 2)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'csv', 'tabular_records_v1', columns=('a',))
    assert failure.value.code == 'invalid_data'
    assert source.closed and all(stream.closed for stream in opened_streams)


def test_xml_uses_fixed_typed_tags_without_lossy_name_normalization():
    value = {
        'a b': {'a-b': 1, 'a_b': 2, '1st': 3, ':prefix': 4},
        '<field/>': '<!DOCTYPE root [<!ENTITY x SYSTEM "file:///unread">]>&x;',
        '\t\r\n"\'&': '',
        '': None,
    }
    with render(ValueSource(value), 'xml', 'typed_xml_v1') as result:
        payload = result.file_content.read()
        restored = readback(payload, 'xml')
    assert_same_value(restored, value)
    assert payload.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<value><object>')
    assert b'<!DOCTYPE' not in payload and b'&lt;!DOCTYPE' in payload
    assert b'&#13;' in payload and b'&#10;' in payload and b'&#9;' in payload


@pytest.mark.parametrize('value', [{'bad\x00key': 1}, {'key': 'bad\x08text'}, '\ufffe'])
def test_xml_rejects_characters_that_cannot_round_trip_in_xml_10(value, opened_streams):
    with pytest.raises(GeneratedFileExportError) as failure:
        render(ValueSource(value), 'xml', 'typed_xml_v1')
    assert failure.value.code == 'invalid_data'
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,kind', [
    ('txt', 'text'), ('text', 'text'), ('md', 'markdown'), ('markdown', 'markdown'),
])
def test_prepared_text_preserves_utf8_markup_newlines_and_whitespace(output_format, kind):
    fragments = ['  # Title\r', '\n\nλ😀\n', '<tag>literal</tag>\t', ' trailing  ']
    expected = ''.join(fragments).encode('utf-8')
    source = TextSource(iter(fragments), sum(len(fragment) for fragment in fragments), kind)
    with render(source, output_format, 'prepared_text_v1') as result:
        actual = result.file_content.read()
        assert actual == expected
        assert result.character_count == source.character_count
        assert result.record_count == 0
        assert result.file_extension == ('md' if kind == 'markdown' else 'txt')
    assert source.reads == 4 and source.closed


@pytest.mark.parametrize('aliases,profile,source_factory,canonical', [
    (('yaml', 'yml'), 'structured_records_v1', lambda: RecordSource([{'a': 'λ'}], 1), 'yaml'),
    (('md', 'markdown'), 'prepared_text_v1', lambda: TextSource(['# λ'], 3, 'markdown'), 'md'),
    (('txt', 'text'), 'prepared_text_v1', lambda: TextSource(['λ'], 1), 'txt'),
])
def test_aliases_select_identical_bytes_and_canonical_metadata(aliases, profile, source_factory, canonical):
    observed = []
    for alias in aliases:
        with render(source_factory(), alias, profile) as result:
            payload = result.file_content.read()
            observed.append((payload, result.output_format, result.file_extension, result.media_type))
    assert observed[0] == observed[1]
    assert observed[0][1:3] == (canonical, canonical)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS)
def test_empty_complete_record_collection_is_valid(output_format, profile):
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with render(RecordSource([], 0), output_format, profile, **options) as result:
        payload = result.file_content.read()
        restored = readback(payload, output_format, records=True)
        assert result.record_count == 0
    assert restored == ([['value']] if output_format == 'csv' else [])


@pytest.mark.parametrize('output_format,kind', [('md', 'markdown'), ('txt', 'text')])
def test_empty_prepared_text_is_a_valid_zero_byte_stream(output_format, kind):
    with render(TextSource([], 0, kind), output_format, 'prepared_text_v1', limit=1) as result:
        payload = result.file_content.read()
        assert payload == b''
        assert result.size_bytes == 0
        assert result.content_sha256 == hashlib.sha256(b'').hexdigest()


@pytest.mark.parametrize('output_format', ['', 'JSON', '.json', 'YAML', 'html', 'docx', 'pdf', 'unknown'])
def test_unknown_explicit_formats_never_fall_back_to_json(output_format):
    source = RecordSource([{'a': 1}], 1)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, 'exact_records_v1')
    expected_code = 'unsupported_profile' if output_format in ('docx', 'pdf') else 'unsupported_format'
    assert failure.value.code == expected_code and failure.value.retryable is False
    assert source.reads == source.checks == 0


@pytest.mark.parametrize('source,output_format,profile,code', [
    (RecordSource([], 0), 'yaml', 'exact_records_v1', 'unsupported_profile'),
    (RecordSource([], 0), 'json', 'unknown', 'unsupported_profile'),
    (RecordSource([], 0), 'json', [], 'unsupported_profile'),
    (RecordSource([], 0), 'json', 'structured_value_v1', 'unsupported_source'),
    (ValueSource({}), 'json', 'exact_records_v1', 'unsupported_source'),
    (RecordSource([], 0), 'txt', 'prepared_text_v1', 'unsupported_source'),
    (TextSource([], 0, 'markdown'), 'txt', 'prepared_text_v1', 'unsupported_source'),
    (TextSource([], 0), 'md', 'prepared_text_v1', 'unsupported_source'),
])
def test_format_profile_source_combinations_are_strict(source, output_format, profile, code):
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile)
    assert failure.value.code == code
    assert source.reads == source.checks == 0


def test_unsupported_options_do_not_get_ignored():
    source = RecordSource([], 0)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'json', 'exact_records_v1', columns=('a',))
    assert failure.value.code == 'invalid_options'
    assert source.reads == source.checks == 0


def test_explicit_source_does_not_use_prompt_preview_or_function_result_fallbacks():
    source = RecordSource([{'complete': 'λ'}], 1)

    def forbidden_loader():
        raise AssertionError('An explicit renderer must not reload function results')

    with build_generated_file_export(
        'Create a Word document', 'Incomplete preview',
        function_results=[{'result': {'rows': [{'preview': True}]}}],
        prior_function_results_loader=forbidden_loader,
        pending_output_format='csv',
        source=source,
        export_request=GeneratedFileExportRequest('json'),
        max_output_bytes=1024,
    ) as result:
        payload = result.file_content.read()
        restored = json.loads(payload)
    assert restored == [{'complete': 'λ'}]
    assert result.output_format == 'json' and source.iterations == 1


@pytest.mark.parametrize('readiness', [
    GeneratedFileExportReadiness(state='pending'),
    GeneratedFileExportReadiness(state='partial'),
    GeneratedFileExportReadiness(state='cancelled'),
    GeneratedFileExportReadiness(state='failed'),
    GeneratedFileExportReadiness(state='invalid'),
    GeneratedFileExportReadiness(is_complete=False),
    GeneratedFileExportReadiness(is_preview=True),
    GeneratedFileExportReadiness(is_complete=1),
    GeneratedFileExportReadiness(is_preview=0),
    None, {},
])
@pytest.mark.parametrize('source_kind', ['records', 'structured_value', 'text'])
def test_noncomplete_or_malformed_readiness_is_rejected_before_reading(readiness, source_kind, opened_streams):
    if source_kind == 'records':
        source, output_format, profile = RecordSource([], 0, readiness), 'json', 'exact_records_v1'
    elif source_kind == 'structured_value':
        source, output_format, profile = ValueSource({}, readiness), 'json', 'structured_value_v1'
    else:
        source, output_format, profile = TextSource([], 0, readiness=readiness), 'txt', 'prepared_text_v1'
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile)
    assert failure.value.code in ('invalid_source', 'incomplete_source')
    assert source.reads == 0 and not opened_streams


@pytest.mark.parametrize('output_format,profile', VALUE_FORMATS)
@pytest.mark.parametrize('value', [
    {1: 'bad key'}, {'nested': (1, 2)}, {'nested': {1, 2}}, object(),
    float('nan'), float('inf'), float('-inf'), b'bytes', {'bad': '\ud800'},
])
def test_nonfinite_nonjson_and_invalid_unicode_values_are_rejected(output_format, profile, value, opened_streams):
    with pytest.raises(GeneratedFileExportError) as failure:
        render(ValueSource(value), output_format, profile)
    assert failure.value.code == 'invalid_data'
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS)
@pytest.mark.parametrize('count', [0, 2])
def test_mismatched_record_counts_never_return_a_complete_prefix(output_format, profile, count, opened_streams):
    source = RecordSource([{'value': 'λ'}], count)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile, **options)
    assert failure.value.code == 'count_mismatch'
    assert source.closed and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('count', [0, 2])
def test_mismatched_prepared_text_counts_are_rejected(count, opened_streams):
    source = TextSource(['λ'], count)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'txt', 'prepared_text_v1')
    assert failure.value.code == 'count_mismatch'
    assert source.closed and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('count', [-1, True, None, '1', 0.5])
@pytest.mark.parametrize('source_kind', ['records', 'text'])
def test_declared_counts_must_be_nonnegative_integers(count, source_kind):
    if source_kind == 'records':
        source = RecordSource([], count)
        output_format, profile = 'json', 'exact_records_v1'
    else:
        source = TextSource([], count)
        output_format, profile = 'txt', 'prepared_text_v1'
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile)
    assert failure.value.code == 'invalid_source'
    assert source.reads == source.checks == 0


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS)
def test_byte_limit_counts_actual_encoding_delimiters_and_escaping(output_format, profile, opened_streams):
    records = [{'value': 'λ😀, "<&>\n=12'}]
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with render(RecordSource(records, 1), output_format, profile, **options) as result:
        payload = result.file_content.read()
    with render(RecordSource(records, 1), output_format, profile, limit=len(payload), **options) as exact:
        actual = exact.file_content.read()
        assert actual == payload
    with pytest.raises(GeneratedFileExportError) as failure:
        render(RecordSource(records, 1), output_format, profile, limit=len(payload) - 1, **options)
    assert failure.value.code == 'size_limit'
    assert all(stream.closed for stream in opened_streams)


def test_text_size_limit_counts_utf8_bytes_not_characters(opened_streams):
    with pytest.raises(GeneratedFileExportError) as failure:
        render(TextSource(['😀'], 1), 'txt', 'prepared_text_v1', limit=3)
    assert failure.value.code == 'size_limit'
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS)
@pytest.mark.parametrize('boundary', ['source', 'cancellation', 'final_source', 'final_cancellation'])
def test_revocation_and_cancellation_are_honored_and_close_streams(output_format, profile, boundary, opened_streams):
    count = 1 if boundary.startswith('final') else 500
    source = RecordSource(({'value': index} for index in range(count)), count)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    reason = PermissionError('revoked by the owner')

    def revoke():
        if source.reads >= (1 if boundary.startswith('final') else 100):
            raise reason

    if boundary in ('source', 'final_source'):
        source.on_recheck = revoke
    else:
        options['check'] = revoke
    with pytest.raises(PermissionError) as failure:
        render(source, output_format, profile, **options)
    assert failure.value is reason
    assert source.reads == (1 if boundary.startswith('final') else 100)
    assert source.closed and opened_streams and all(stream.closed for stream in opened_streams)


def test_source_readiness_is_rechecked_midstream(opened_streams):
    source = RecordSource(({'value': index} for index in range(500)), 500)

    def invalidate():
        if source.reads >= 100:
            source.readiness = GeneratedFileExportReadiness(is_complete=False)

    source.on_recheck = invalidate
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'json', 'exact_records_v1')
    assert failure.value.code == 'incomplete_source'
    assert source.reads == 100 and source.closed
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('source_kind', ['records', 'text'])
def test_declared_count_cannot_change_during_the_final_recheck(source_kind, opened_streams):
    if source_kind == 'records':
        source = RecordSource([{'value': 1}], 1)
        output_format, profile, attribute = 'json', 'exact_records_v1', 'record_count'
    else:
        source = TextSource(['λ'], 1)
        output_format, profile, attribute = 'txt', 'prepared_text_v1', 'character_count'

    def change_count():
        if source.reads:
            setattr(source, attribute, 2)

    source.on_recheck = change_count
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile)
    assert failure.value.code == 'count_mismatch'
    assert source.closed and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('source_kind', ['records', 'text'])
def test_malformed_reader_results_are_classified(source_kind, opened_streams):
    if source_kind == 'records':
        source = RecordSource([], 0)
        source.iter_records = lambda: None
        output_format, profile = 'json', 'exact_records_v1'
    else:
        source = TextSource([], 0)
        source.iter_text = lambda: None
        output_format, profile = 'txt', 'prepared_text_v1'
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile)
    assert failure.value.code == 'invalid_source'
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('kind', ['text', 'markdown', 'structured_value'])
def test_large_single_value_rechecks_access_before_rendering_finishes(kind, opened_streams):
    content = 'λ' * 200_000
    if kind == 'structured_value':
        source = ValueSource({'value': content})
        output_format, profile = 'json', 'structured_value_v1'
    else:
        source = TextSource([content], len(content), kind)
        output_format, profile = ('md' if kind == 'markdown' else 'txt'), 'prepared_text_v1'

    def revoke():
        if source.checks >= 3:
            raise PermissionError('revoked during a large value')

    source.on_recheck = revoke
    with pytest.raises(PermissionError):
        render(source, output_format, profile)
    assert source.reads == 1
    assert all(stream.closed for stream in opened_streams)


def test_unexpected_reader_failure_closes_reader_and_output(opened_streams):
    def broken_records():
        yield {'value': 1}
        raise RuntimeError('reader failed')

    source = RecordSource(broken_records(), 2)
    with pytest.raises(RuntimeError, match='reader failed'):
        render(source, 'json', 'exact_records_v1')
    assert source.closed and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS + (
    ('md', 'prepared_text_v1'), ('txt', 'prepared_text_v1'),
))
@pytest.mark.parametrize('exception_type', [PermissionError, InterruptedError])
def test_primary_iterator_error_survives_cleanup_failure(output_format, profile, exception_type, opened_streams):
    primary = exception_type('primary source failure')
    cause = ValueError('original cause')
    items = ['x'] if output_format in ('md', 'txt') else [{'value': 'x'}]
    iterator = CleanupFailingIterator(items, primary=primary, cause=cause)
    source = cleanup_source(output_format, iterator, 2)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with pytest.raises(exception_type) as failure:
        render(source, output_format, profile, **options)
    assert failure.value is primary and failure.value.__cause__ is cause
    assert iterator.close_calls == 1 and opened_streams
    assert all(stream.closed for stream in opened_streams)
    notes = getattr(primary, '__notes__', [])
    assert any('cleanup' in note for note in notes)
    assert all('private cleanup details' not in note for note in notes)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS + (
    ('md', 'prepared_text_v1'), ('txt', 'prepared_text_v1'),
))
@pytest.mark.parametrize('exception_type', [PermissionError, InterruptedError])
def test_render_error_survives_suspended_iterator_cleanup(
    output_format, profile, exception_type, opened_streams, monkeypatch,
):
    primary = exception_type('primary render failure')
    cause = ValueError('original render cause')
    items = ['x'] if output_format in ('md', 'txt') else [{'value': 'x'}]
    iterator = CleanupFailingIterator(items)
    source = cleanup_source(output_format, iterator, 1)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    original = renderers._OutputWriter.write

    def revoked_write(writer, fragment):
        if iterator.reads:
            raise primary from cause
        return original(writer, fragment)

    monkeypatch.setattr(renderers._OutputWriter, 'write', revoked_write)
    with pytest.raises(exception_type) as failure:
        render(source, output_format, profile, **options)
    assert failure.value is primary and failure.value.__cause__ is cause
    assert iterator.close_calls == 1 and all(stream.closed for stream in opened_streams)
    assert any('cleanup' in note for note in getattr(primary, '__notes__', []))


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS + (
    ('md', 'prepared_text_v1'), ('txt', 'prepared_text_v1'),
))
def test_count_failure_is_not_replaced_by_cleanup(output_format, profile, opened_streams):
    items = ['x'] if output_format in ('md', 'txt') else [{'value': 'x'}]
    iterator = CleanupFailingIterator(items)
    source = cleanup_source(output_format, iterator, 2)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, output_format, profile, **options)
    assert failure.value.code == 'count_mismatch'
    assert iterator.close_calls == 1 and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS + (
    ('md', 'prepared_text_v1'), ('txt', 'prepared_text_v1'),
))
def test_cleanup_only_failure_is_not_silently_suppressed(output_format, profile, opened_streams):
    items = ['x'] if output_format in ('md', 'txt') else [{'value': 'x'}]
    iterator = CleanupFailingIterator(items)
    source = cleanup_source(output_format, iterator, 1)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    with pytest.raises(OSError) as failure:
        render(source, output_format, profile, **options)
    assert failure.value is iterator.cleanup_error
    assert iterator.close_calls == 1 and opened_streams
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS + (
    ('md', 'prepared_text_v1'), ('txt', 'prepared_text_v1'),
))
def test_outer_handled_exception_does_not_hide_cleanup_failure(output_format, profile, opened_streams):
    outer = ValueError('already handled by the caller')
    items = ['x'] if output_format in ('md', 'txt') else [{'value': 'x'}]
    iterator = CleanupFailingIterator(items)
    source = cleanup_source(output_format, iterator, 1)
    options = {'columns': ('value',)} if output_format == 'csv' else {}
    try:
        raise outer
    except ValueError:
        with pytest.raises(OSError) as failure:
            render(source, output_format, profile, **options)
    assert failure.value is iterator.cleanup_error
    assert iterator.close_calls == 1
    assert not getattr(outer, '__notes__', [])
    assert opened_streams and all(stream.closed for stream in opened_streams)


def test_cleanup_guard_uses_the_with_body_error_not_the_callers_handler():
    outer = ValueError('already handled by the caller')
    iterator = CleanupFailingIterator([])
    try:
        raise outer
    except ValueError:
        with pytest.raises(OSError) as failure:
            with ClosingExportResource(iterator):
                pass
    assert failure.value is iterator.cleanup_error and iterator.close_calls == 1
    assert not getattr(outer, '__notes__', [])


@pytest.mark.parametrize('exception_type', [PermissionError, InterruptedError, KeyboardInterrupt])
def test_cleanup_guard_preserves_active_control_errors_and_their_cause(exception_type):
    primary = exception_type('primary control failure')
    cause = ValueError('original cause')
    iterator = CleanupFailingIterator([])
    with pytest.raises(exception_type) as failure:
        with ClosingExportResource(iterator):
            raise primary from cause
    assert failure.value is primary and failure.value.__cause__ is cause
    assert iterator.close_calls == 1


def test_normal_early_generator_close_does_not_hide_cleanup_failure():
    iterator = CleanupFailingIterator([1, 2])

    def values():
        with ClosingExportResource(iterator):
            for value in iterator:
                yield value

    generated = values()
    first = next(generated)
    with pytest.raises(OSError) as failure:
        close_export_resource(generated)
    assert first == 1 and failure.value is iterator.cleanup_error
    assert iterator.close_calls == 1


def test_optional_iterator_close_method_is_not_required():
    iterator = iter([1])
    with ClosingExportResource(iterator) as values:
        actual = list(values)
    assert actual == [1]


def test_failed_output_close_does_not_replace_the_source_error(monkeypatch, opened_streams):
    primary = PermissionError('primary source access failure')
    original = renderers.tempfile.TemporaryFile

    class FailingOutputClose:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.stream.close()
            raise OSError('private output cleanup details')

    def stream_factory(*args, **kwargs):
        return FailingOutputClose(original(*args, **kwargs))

    def records():
        yield {'value': 1}
        raise primary

    monkeypatch.setattr(renderers.tempfile, 'TemporaryFile', stream_factory)
    with pytest.raises(PermissionError) as failure:
        render(RecordSource(records(), 2), 'json', 'exact_records_v1')
    assert failure.value is primary
    assert opened_streams and all(stream.closed for stream in opened_streams)
    assert any('cleanup' in note for note in getattr(primary, '__notes__', []))
    assert all('private output cleanup details' not in note for note in primary.__notes__)


def test_output_initialization_failure_also_closes_the_allocated_stream(monkeypatch, opened_streams):
    def fail_writer(*args, **kwargs):
        raise OSError('output initialization failed')

    monkeypatch.setattr(renderers, '_OutputWriter', fail_writer)
    source = RecordSource([], 0)
    with pytest.raises(OSError, match='output initialization failed'):
        render(source, 'json', 'exact_records_v1')
    assert source.reads == 0 and opened_streams and all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('limits', [
    GeneratedFileExportLimits(max_records=0), GeneratedFileExportLimits(max_value_bytes=True),
    GeneratedFileExportLimits(max_depth=65), GeneratedFileExportLimits(max_text_chunks=-1), {},
])
def test_malformed_limits_are_rejected_before_reading(limits):
    source = RecordSource([], 0)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'json', 'exact_records_v1', limits=limits)
    assert failure.value.code == 'invalid_limit' and source.reads == source.checks == 0


def test_declared_record_cap_is_configurable_and_not_a_preview_limit():
    source = RecordSource(({'value': index} for index in range(4)), 4)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'json', 'exact_records_v1', limits=GeneratedFileExportLimits(max_records=3))
    assert failure.value.code == 'record_limit' and source.reads == source.checks == 0


@pytest.mark.parametrize('field,maximum,value', [
    ('max_value_bytes', 100, 'λ' * 100),
    ('max_value_nodes', 3, [1, 2, 3]),
    ('max_depth', 2, [[[[]]]]),
])
def test_per_value_memory_and_depth_bounds(field, maximum, value, opened_streams):
    limits = replace(GeneratedFileExportLimits(), **{field: maximum})
    with pytest.raises(GeneratedFileExportError) as failure:
        render(ValueSource(value), 'json', 'structured_value_v1', limits=limits)
    assert failure.value.code == 'value_limit'
    assert all(stream.closed for stream in opened_streams)


def test_cyclic_data_is_rejected_instead_of_stringified(opened_streams):
    value = []
    value.append(value)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(ValueSource(value), 'yaml', 'structured_value_v1')
    assert failure.value.code == 'invalid_data'
    assert all(stream.closed for stream in opened_streams)


def test_nonprogressing_text_reader_has_a_finite_chunk_limit(opened_streams):
    source = TextSource(('' for _ in range(101)), 0)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'txt', 'prepared_text_v1', limits=GeneratedFileExportLimits(max_text_chunks=100))
    assert failure.value.code == 'value_limit' and source.closed
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('value', [None, b'bytes', 123])
def test_prepared_text_rejects_nonstring_chunks(value, opened_streams):
    source = TextSource([value], 1)
    with pytest.raises(GeneratedFileExportError) as failure:
        render(source, 'txt', 'prepared_text_v1')
    assert failure.value.code == 'invalid_data' and source.closed
    assert all(stream.closed for stream in opened_streams)


def test_text_cancellation_closes_the_owned_iterator(opened_streams):
    source = TextSource(('a' for _ in range(500)), 500)

    def cancel():
        if source.reads >= 100:
            raise InterruptedError('cancelled')

    with pytest.raises(InterruptedError):
        render(source, 'txt', 'prepared_text_v1', check=cancel)
    assert source.reads == 100 and source.closed
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize('output_format,profile', RECORD_FORMATS)
def test_complete_dataset_above_30000_records_has_first_last_count_and_digest(output_format, profile):
    count = 30_017
    source = RecordSource(
        ({'ordinal': index, 'identifier': f'{index:06d}', 'label': 'λ'} for index in range(count)),
        count,
    )
    observations = []
    options = {'columns': ('identifier', 'ordinal', 'label')} if output_format == 'csv' else {}
    with render(
        source, output_format, profile, check=lambda: observations.append(source.reads), **options,
    ) as result:
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: result.file_content.read(65536), b''):
            digest.update(chunk)
            size += len(chunk)
        result.file_content.seek(0)
        payload = result.file_content.read()
        restored = readback(payload, output_format, records=True)
        assert digest.hexdigest() == result.content_sha256
        assert size == result.size_bytes == len(payload)
        assert result.record_count == count
        assert not isinstance(result.file_content, io.BytesIO)
    if output_format == 'csv':
        assert restored[0] == ['identifier', 'ordinal', 'label']
        assert len(restored) == count + 1
        assert restored[1] == ['000000', '0', 'λ']
        assert restored[-1] == [f'{count - 1:06d}', str(count - 1), 'λ']
    else:
        assert len(restored) == count
        assert restored[0] == {'ordinal': 0, 'identifier': '000000', 'label': 'λ'}
        assert restored[-1] == {'ordinal': count - 1, 'identifier': f'{count - 1:06d}', 'label': 'λ'}
    assert source.reads == count and source.iterations == 1 and source.closed
    assert observations[0] == 0 and observations[-1] == count
    assert 0 < observations[1] < count


def test_large_record_collection_does_not_accumulate_in_renderer_memory():
    if tracemalloc.is_tracing():
        pytest.skip('This memory probe owns its isolated tracemalloc measurement.')
    count = 4096
    source = RecordSource(
        ({'ordinal': index, 'value': f'{index:06d}:' + 'λ' * 1024} for index in range(count)),
        count,
    )
    tracemalloc.start()
    try:
        with render(source, 'json', 'exact_records_v1') as result:
            _, peak = tracemalloc.get_traced_memory()
            size = result.size_bytes
    finally:
        tracemalloc.stop()
    assert size > 20 * 1024 * 1024
    assert peak < 2 * 1024 * 1024
    assert source.reads == count and source.closed


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_cold_imports_and_real_rendering_have_no_bootstrap_or_network_dependencies(optimized, reverse):
    modules = [
        'functions_export_cleanup', 'functions_generated_export_contracts', 'functions_generated_export_registry',
        'functions_structured_file_renderers', 'functions_generated_file_exports',
    ]
    if reverse:
        modules.reverse()
    probe = f'''
import importlib
import socket
import sys
sys.path.insert(0, {str(APP_ROOT)!r})
def denied(*args, **kwargs):
    raise RuntimeError("Network I/O is forbidden")
socket.create_connection = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.getaddrinfo = denied
socket.gethostbyname = denied
socket.gethostbyname_ex = denied
socket.gethostbyaddr = denied
for name in {modules!r}:
    importlib.import_module(name)
from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
class Source:
    kind = "records"
    record_count = 1
    def iter_records(self):
        yield {{"z": "λ", "a": False}}
    def recheck(self):
        return None
with build_generated_file_export(
    source=Source(), export_request=GeneratedFileExportRequest("json"), max_output_bytes=100,
) as result:
    actual = result.file_content.read()
    if actual != b'[{{"a":false,"z":"\\\\u03bb"}}]':
        raise RuntimeError("Rendering did not run with the exact legacy profile")
if not result.file_content.closed:
    raise RuntimeError("The output stream was not closed")
for name in sys.modules:
    if name in {{"config", "functions_settings", "functions_appinsights"}} or name.startswith("route_"):
        raise RuntimeError("Renderer imported an application bootstrap owner")
'''
    command = [sys.executable] + (['-O'] if optimized else []) + ['-c', probe]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
