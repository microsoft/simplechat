# test_assistant_table_csv_artifact.py
#!/usr/bin/env python3
"""
Functional test for assistant-rendered table CSV artifacts.
Version: 0.241.051
Implemented in: 0.241.050

This test ensures that explicit table-format requests with assistant-rendered
tables and natural CSV/table conversion requests are converted into
downloadable CSV artifact metadata for the chat UI.
"""

import csv
import io
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'application' / 'single_app'
CONFIG_FILE = APP_DIR / 'config.py'
CHAT_ROUTE_FILE = APP_DIR / 'route_backend_chats.py'
EXPECTED_VERSION = '0.241.051'

sys.path.append(str(APP_DIR))

from functions_assistant_table_exports import (  # noqa: E402
    assistant_table_export_requested,
    build_assistant_table_csv_export,
    extract_assistant_table_entries,
)


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def read_current_version() -> str:
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError('Expected config.py to define VERSION')


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def parse_csv_rows(csv_content):
    return list(csv.DictReader(io.StringIO(csv_content)))


def test_markdown_table_response_builds_csv_export():
    print('Testing Markdown table response CSV export creation...')

    assistant_content = """Sure, here it is in table format:

| Name | Email | Date |
| --- | --- | --- |
| Jonathan Roundy | jonathan.roundy@orau.org | December 11, 2025 at 1:56 PM |
| Andy Cowley | andy.cowley@orau.org | December 11, 2025 at 1:58 PM |
| Fernando Prado | feprado@microsoft.com | December 11, 2025 at 10:38 AM |

If you want, I can also turn this into a CSV.
"""

    export_payload = build_assistant_table_csv_export(
        'turn this into a table for me',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected a table request with a Markdown table to produce an export payload.')
    assert_true(export_payload.get('file_name', '').endswith('.csv'), 'Expected generated export file name to end with .csv.')
    assert_true(export_payload.get('row_count') == 3, 'Expected the export row count to match the table data rows.')
    assert_true(len(export_payload.get('preview_rows') or []) == 3, 'Expected up to three preview rows in export metadata.')

    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(csv_rows[0]['Name'] == 'Jonathan Roundy', 'Expected first CSV row to preserve the Name column.')
    assert_true(csv_rows[1]['Email'] == 'andy.cowley@orau.org', 'Expected CSV output to preserve email values.')
    assert_true(csv_rows[2]['Date'] == 'December 11, 2025 at 10:38 AM', 'Expected CSV output to preserve date values.')


def test_tab_separated_table_response_builds_rows():
    print('Testing tab-separated table response parsing...')

    assistant_content = """Name\tEmail\tDate
Jonathan Roundy\tjonathan.roundy@orau.org\tDecember 11, 2025 at 1:56 PM
Andy Cowley\tandy.cowley@orau.org\tDecember 11, 2025 at 1:58 PM
"""

    table_rows = extract_assistant_table_entries(assistant_content)

    assert_true(len(table_rows) == 2, 'Expected tab-separated assistant tables to parse into data rows.')
    assert_true(table_rows[0]['Name'] == 'Jonathan Roundy', 'Expected TSV table parser to preserve the Name column.')
    assert_true(table_rows[1]['Date'] == 'December 11, 2025 at 1:58 PM', 'Expected TSV table parser to preserve the Date column.')


def test_non_table_requests_do_not_create_exports():
    print('Testing non-table request exclusion...')

    assistant_content = """| Name | Email |
| --- | --- |
| Jonathan Roundy | jonathan.roundy@orau.org |
"""

    assert_true(
        assistant_table_export_requested('summarize these contacts') is False,
        'Expected non-table requests not to request assistant table exports.',
    )
    assert_true(
        build_assistant_table_csv_export('summarize these contacts', assistant_content) is None,
        'Expected non-table requests not to create CSV exports even when a table is present.',
    )


def test_natural_table_request_phrase_is_recognized():
    print('Testing natural table request phrasing...')

    assistant_content = """| Comment ID | Summary |
| --- | --- |
| 114070 | Attachment-backed summary. |
"""

    assert_true(
        assistant_table_export_requested('put that into a table and include the comment id'),
        "Expected 'put that into a table' phrasing to trigger assistant table export detection.",
    )
    assert_true(
        build_assistant_table_csv_export(
            'put that into a table and include the comment id',
            assistant_content,
        ) is not None,
        "Expected natural table phrasing to produce an assistant table CSV export.",
    )


def test_natural_csv_and_create_table_phrases_are_recognized():
    print('Testing natural CSV and create-table request phrasing...')

    assistant_content = """| Day | Type |
| --- | --- |
| Monday | Weekday |
| Saturday | Weekend |
"""

    request_phrases = [
        'turn that into a csv',
        'turn this into csv',
        'convert that to csv',
        'export as csv',
        'create a table of the days of the week',
    ]

    for request_phrase in request_phrases:
        assert_true(
            assistant_table_export_requested(request_phrase),
            f"Expected '{request_phrase}' to trigger assistant table export detection.",
        )
        assert_true(
            build_assistant_table_csv_export(request_phrase, assistant_content) is not None,
            f"Expected '{request_phrase}' to produce an assistant table CSV export.",
        )


def test_chat_route_wires_assistant_table_artifacts():
    print('Testing chat route assistant-table artifact plumbing...')

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert_true(current_version == EXPECTED_VERSION, f'Expected config.py version {EXPECTED_VERSION}.')
    assert_true(
        'TABLE_EXPORT_REQUEST_MARKERS' in chat_route_content,
        'Expected route_backend_chats.py to reuse assistant table export request markers.',
    )
    assert_true(
        'def maybe_create_assistant_table_generated_output(' in chat_route_content,
        'Expected route_backend_chats.py to expose assistant table artifact creation.',
    )
    assert_true(
        'document_generated_analysis_artifacts.append(assistant_table_generated_output)' in chat_route_content,
        'Expected document-action assistant messages to include assistant table CSV artifacts.',
    )
    assert_true(
        'generated_analysis_artifacts_list.append(assistant_table_generated_output)' in chat_route_content,
        'Expected normal and streaming assistant messages to include assistant table CSV artifacts.',
    )
    assert_true(
        'csv_markers = TABLE_EXPORT_REQUEST_MARKERS' in chat_route_content,
        'Expected tabular output intent detection to use shared CSV/table request markers.',
    )
    assert_true(
        "requested_format == 'csv'" in chat_route_content,
        'Expected CSV request markers to create tabular generated outputs when available.',
    )


def run_tests() -> bool:
    tests = [
        test_markdown_table_response_builds_csv_export,
        test_tab_separated_table_response_builds_rows,
        test_non_table_requests_do_not_create_exports,
        test_natural_table_request_phrase_is_recognized,
        test_natural_csv_and_create_table_phrases_are_recognized,
        test_chat_route_wires_assistant_table_artifacts,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print(f'{test.__name__} passed')
            results.append(True)
        except Exception as exc:
            print(f'{test.__name__} failed: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'\nResults: {passed}/{len(tests)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)
