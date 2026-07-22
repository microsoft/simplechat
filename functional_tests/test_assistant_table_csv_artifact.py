# test_assistant_table_csv_artifact.py
#!/usr/bin/env python3
"""
Functional test for assistant-rendered table CSV artifacts.
Version: 0.250.065
Implemented in: 0.241.050; non-tabular document CSV parsing in 0.250.065

This test ensures that explicit table-format requests with assistant-rendered
tables, including CSV rows extracted from non-tabular documents, are converted
into downloadable CSV artifact metadata for the chat UI.
"""

import ast
import csv
import io
import json
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'application' / 'single_app'
CONFIG_FILE = APP_DIR / 'config.py'
CHAT_ROUTE_FILE = APP_DIR / 'route_backend_chats.py'
BACKGROUND_EXPORT_FILE = APP_DIR / 'functions_tabular_generated_exports.py'
WORKFLOW_RUNNER_FILE = APP_DIR / 'functions_workflow_runner.py'
EXPECTED_VERSION = '0.250.065'

sys.path.append(str(APP_DIR))

from functions_assistant_table_exports import (  # noqa: E402
    assistant_table_export_requested,
    build_safe_csv_headers,
    build_assistant_table_csv_export,
    extract_assistant_table_entries,
    neutralize_csv_spreadsheet_formula,
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


def load_csv_writer_helpers(source_file, function_names):
    module_tree = ast.parse(read_text(source_file), filename=str(source_file))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    if len(selected_nodes) != len(function_names):
        raise AssertionError(f'Expected CSV writer helpers {sorted(function_names)} in {source_file.name}.')

    namespace = {
        'build_safe_csv_headers': build_safe_csv_headers,
        'csv': csv,
        'io': io,
        'json': json,
        'neutralize_csv_spreadsheet_formula': neutralize_csv_spreadsheet_formula,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(source_file), 'exec'), namespace)
    return {function_name: namespace[function_name] for function_name in function_names}


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


def test_non_tabular_document_csv_response_builds_export():
    print('Testing non-tabular document CSV response export creation...')

    assistant_content = '''```csv
Name,Invoice Number,Description,Notes
Paul Lizer,DCAW1366188,"PassPark Premium Reserve - South","Includes parking, taxes, and fees"
```

Source: ParkingPrint.pdf, Page: 1
'''

    export_payload = build_assistant_table_csv_export(
        'generate a csv from this file',
        assistant_content,
    )

    assert_true(
        export_payload is not None,
        'Expected comma-delimited output from a non-tabular document to produce an export payload.',
    )
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected the PDF citation outside the CSV block to be excluded.')
    assert_true(csv_rows[0]['Invoice Number'] == 'DCAW1366188', 'Expected the invoice number to be preserved.')
    assert_true(
        csv_rows[0]['Notes'] == 'Includes parking, taxes, and fees',
        'Expected quoted commas in generated CSV values to be preserved.',
    )


def test_plain_document_csv_response_excludes_surrounding_prose_and_citation():
    print('Testing plain document CSV response boundary detection...')

    assistant_content = '''I extracted the requested invoice fields, including the billed service.

Name,Invoice Number,Description
Paul Lizer,DCAW1366188,PassPark Premium Reserve - South
(Source: ParkingPrint.pdf, Page: 1)

The values reflect the uploaded file, not an external source.
'''

    export_payload = build_assistant_table_csv_export(
        'turn this into a CSV',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected plain comma-delimited document output to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected surrounding prose and the PDF citation to be excluded from CSV rows.')
    assert_true(csv_rows[0]['Name'] == 'Paul Lizer', 'Expected the extracted document row to be preserved.')


def test_document_csv_response_preserves_multiline_and_escaped_quotes():
    print('Testing lossless document CSV value parsing...')

    assistant_content = '''```csv
Name,Description
Contoso,"First line
Second ""quoted"" line"
```

Source: Contract.docx, Page: 2
'''

    export_payload = build_assistant_table_csv_export(
        'create a csv from this word file',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected Word-derived CSV output to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(
        csv_rows[0]['Description'] == 'First line\nSecond "quoted" line',
        'Expected multiline values and escaped quotes to survive the CSV artifact round trip.',
    )


def test_fenced_document_csv_preserves_sentence_shaped_rows():
    print('Testing sentence-shaped rows inside trusted CSV fences...')

    assistant_content = '''```csv
Name,Description
Contoso,This is a primary service contract.
Fabrikam,This is a secondary support agreement.
```
'''

    export_payload = build_assistant_table_csv_export('respond as CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected valid sentence-shaped fenced CSV rows to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 2, 'Expected trusted fenced CSV not to truncate sentence-shaped rows.')
    assert_true(csv_rows[1]['Name'] == 'Fabrikam', 'Expected all trusted fenced rows to remain ordered.')


def test_fenced_document_csv_wins_over_larger_markdown_table():
    print('Testing fenced CSV precedence over larger Markdown tables...')

    assistant_content = '''| Name | Value |
| --- | --- |
| Wrong 1 | 11 |
| Wrong 2 | 12 |
| Wrong 3 | 13 |

```csv
Name,Value
Right,1
```
'''

    export_payload = build_assistant_table_csv_export('create a CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected the explicit fenced CSV to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected larger Markdown tables not to override explicit fenced CSV.')
    assert_true(csv_rows[0]['Name'] == 'Right', 'Expected the fenced CSV row to be authoritative.')


def test_explicit_csv_fence_wins_over_larger_generic_fence():
    print('Testing explicit CSV fence precedence over generic fences...')

    assistant_content = '''```text
Name,Value
Wrong 1,11
Wrong 2,12
Wrong 3,13
```

```csv
Name,Value
Right,1
```
'''

    export_payload = build_assistant_table_csv_export('download CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected the explicitly labeled CSV fence to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected generic text fences not to override explicit CSV fences.')
    assert_true(csv_rows[0]['Name'] == 'Right', 'Expected the explicitly labeled CSV row to be authoritative.')


def test_plain_document_csv_preserves_quoted_blank_lines_and_ignores_comma_prose():
    print('Testing plain document CSV quoted blank lines and prose exclusion...')

    assistant_content = '''I extracted the requested invoice fields, including the billed service.
Name,Description
Contoso,"First paragraph

Second paragraph"
Source: Contract.docx, Page: 2
'''

    export_payload = build_assistant_table_csv_export(
        'provide the extracted rows as CSV',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected valid plain CSV after comma-bearing prose to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(list(csv_rows[0]) == ['Name', 'Description'], 'Expected prose before the header to be excluded.')
    assert_true(
        csv_rows[0]['Description'] == 'First paragraph\n\nSecond paragraph',
        'Expected blank lines inside quoted CSV values to be preserved.',
    )


def test_plain_document_csv_preserves_long_headers_and_sentence_values():
    print('Testing long headers and sentence-shaped values in plain CSV...')

    assistant_content = '''Official Full Legal Name Used for Payroll and Tax Reporting,Primary Work Location Description
Alice,This is a complete sentence.
Here is the requested information.,Open
'''

    export_payload = build_assistant_table_csv_export('return the results in CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected valid plain CSV with long headers to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 2, 'Expected sentence-shaped plain CSV values not to truncate data rows.')
    assert_true(
        list(csv_rows[0]) == [
            'Official Full Legal Name Used for Payroll and Tax Reporting',
            'Primary Work Location Description',
        ],
        'Expected the earliest structural header not to be replaced by a shorter data row.',
    )
    assert_true(
        csv_rows[0]['Official Full Legal Name Used for Payroll and Tax Reporting'] == 'Alice',
        'Expected the first data row to remain intact.',
    )
    assert_true(
        csv_rows[1]['Official Full Legal Name Used for Payroll and Tax Reporting'] == 'Here is the requested information.',
        'Expected discourse-like first-column values to remain valid data.',
    )


def test_plain_document_csv_excludes_prose_and_short_page_citations():
    print('Testing plain document CSV prose and short citation boundaries...')

    assistant_content = '''For clarity, see below
Name,Description
Contoso,Primary contract
For context, this came from page one.
Source: Contract.docx, p. 2
'''

    export_payload = build_assistant_table_csv_export(
        'CSV version, please',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected CSV-version phrasing to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected comma-bearing prose and short page citations to be excluded.')
    assert_true(list(csv_rows[0]) == ['Name', 'Description'], 'Expected the actual CSV header to be selected.')


def test_plain_document_csv_excludes_generic_prose_and_non_page_citations():
    print('Testing generic prose and non-page citation boundaries...')

    assistant_content = '''CSV data, ready for download.
Name,Description
Contoso,Primary contract
In summary, the extraction is complete.
(Source: Contract.docx, Section: Fees)
'''

    export_payload = build_assistant_table_csv_export(
        'download this as CSV',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected plain CSV surrounded by generic prose to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected generic prose and non-page citations to be excluded.')
    assert_true(list(csv_rows[0]) == ['Name', 'Description'], 'Expected generic prose not to become CSV headers.')


def test_plain_document_csv_normalizes_preambles_and_citation_variants():
    print('Testing scored preambles and citation variants...')

    citation_rows = (
        'Sources: Contract.docx, Section: Fees',
        '[Source: Contract.docx, Section: Fees]',
        '[1] Source: Contract.docx, Section: Fees',
        '(1) Source: Contract.docx, Section: Fees',
        '[Source]: Contract.docx, Section: Fees',
        '(Citation): Contract.docx, Section: Fees',
        '* Citation: Contract.docx, Section: Fees',
        'Citation: Contract.docx, Section: Fees',
        '- (Source: Contract.docx, Section: Fees)',
    )
    for citation_row in citation_rows:
        assistant_content = f'''The requested export is ready, with the fields below
Name,Description
Contoso,Primary contract
{citation_row}
'''
        export_payload = build_assistant_table_csv_export('put the extracted fields in CSV', assistant_content)
        assert_true(export_payload is not None, f'Expected CSV before citation variant {citation_row!r}.')
        csv_rows = parse_csv_rows(export_payload.get('file_content'))
        assert_true(len(csv_rows) == 1, f'Expected citation variant {citation_row!r} to be excluded.')
        assert_true(list(csv_rows[0]) == ['Name', 'Description'], 'Expected the scored table header to beat prose.')


def test_document_csv_supports_alternate_text_fences():
    print('Testing alternate CSV fence labels...')

    for fence_language in ('txt', 'text/csv', 'markdown', 'md'):
        assistant_content = f'''```{fence_language}
Name,Amount
Contoso,42
```
'''
        export_payload = build_assistant_table_csv_export(
            'return CSV for this Word document',
            assistant_content,
        )
        assert_true(export_payload is not None, f'Expected the {fence_language} fence to support valid CSV output.')


def test_document_csv_neutralizes_spreadsheet_formulas():
    print('Testing spreadsheet formula neutralization...')

    assistant_content = '''```csv
Name,Value
External input,"=HYPERLINK(""https://example.invalid"",""Open"")"
Command,@SUM(1+1)
Balance,-42.50
Grouped balance,"-1,234.50"
```
'''

    export_payload = build_assistant_table_csv_export(
        'output the extracted values in CSV format',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected formula-prefixed document values to produce a safe export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(csv_rows[0]['Value'].startswith("'="), 'Expected equals-prefixed formulas to be neutralized.')
    assert_true(csv_rows[1]['Value'].startswith("'@"), 'Expected at-prefixed formulas to be neutralized.')
    assert_true(csv_rows[2]['Value'] == '-42.50', 'Expected signed numeric values to remain numeric text.')
    assert_true(csv_rows[3]['Value'] == '-1,234.50', 'Expected grouped signed numeric values to remain numeric text.')


def test_document_csv_accepts_punctuation_and_duplicate_headers():
    print('Testing punctuation and duplicate CSV headers...')

    assistant_content = '''```csv
Invoice No.,Approved?,Amount,Amount
DCAW1366188,Yes,10,20
```
'''

    export_payload = build_assistant_table_csv_export(
        'Can I get a CSV of this?',
        assistant_content,
    )

    assert_true(export_payload is not None, 'Expected punctuation and duplicate headers to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(
        list(csv_rows[0]) == ['Invoice No.', 'Approved?', 'Amount', 'Amount 2'],
        'Expected punctuation to be preserved and duplicate headers to be disambiguated.',
    )


def test_document_csv_preserves_header_suffix_collisions():
    print('Testing generated header suffix collisions...')

    assistant_content = '''```csv
Amount,Amount,Amount 2
10,20,30
```
'''

    export_payload = build_assistant_table_csv_export('create a CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected colliding duplicate headers to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows[0]) == 3, 'Expected all colliding header columns to remain present.')
    assert_true(list(csv_rows[0].values()) == ['10', '20', '30'], 'Expected no colliding column value to be overwritten.')


def test_document_csv_neutralizes_formula_headers_without_losing_rows():
    print('Testing formula-like CSV header parsing...')

    assistant_content = '''```csv
=Name,Value
Alice,1
Bob,2
```
'''

    export_payload = build_assistant_table_csv_export('I need the results in CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected formula-like headers to produce a safe export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 2, 'Expected formula header safety not to discard the first data row.')
    assert_true("'=Name" in csv_rows[0], 'Expected the formula-like header to be neutralized.')
    assert_true(csv_rows[0]["'=Name"] == 'Alice', 'Expected the first data row to remain intact.')


def test_all_generated_csv_writers_neutralize_formulas():
    print('Testing formula safety across generated CSV writers...')

    writer_specs = (
        (
            CHAT_ROUTE_FILE,
            {'_serialize_tabular_generated_output_value', '_build_tabular_generated_output_csv'},
            '_build_tabular_generated_output_csv',
        ),
        (
            BACKGROUND_EXPORT_FILE,
            {'_serialize_generated_output_value', '_build_generated_output_csv'},
            '_build_generated_output_csv',
        ),
        (
            WORKFLOW_RUNNER_FILE,
            {'_serialize_document_analysis_csv_value', '_build_document_analysis_rows_csv'},
            '_build_document_analysis_rows_csv',
        ),
    )
    entries = [
        {
            '=Header': '=WEBSERVICE("https://example.invalid")',
            'Amount': '-1,234.50',
            'Count': 0,
            'Enabled': False,
        },
    ]

    for source_file, function_names, writer_name in writer_specs:
        helpers = load_csv_writer_helpers(source_file, function_names)
        csv_content = helpers[writer_name](entries)
        csv_rows = parse_csv_rows(csv_content)
        safe_header = next(header for header in csv_rows[0] if header.startswith("'="))
        assert_true(csv_rows[0][safe_header].startswith("'="), f'Expected {source_file.name} to neutralize formula values.')
        assert_true(csv_rows[0]['Amount'] == '-1,234.50', f'Expected {source_file.name} to preserve signed numbers.')
        assert_true(csv_rows[0]['Count'] == '0', f'Expected {source_file.name} to preserve zero values.')
        assert_true(csv_rows[0]['Enabled'] == 'False', f'Expected {source_file.name} to preserve boolean values.')


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
    for non_export_request in (
        "Don't respond as CSV; summarize this document.",
        'I do not want CSV output.',
        'Get the totals from CSV and explain them.',
        'Get the totals from the CSV file and explain them.',
        'Summarize this CSV file.',
        'Analyze this spreadsheet.',
        'I need to analyze the CSV file and explain the totals.',
        'Please provide JSON, not CSV.',
    ):
        assert_true(
            assistant_table_export_requested(non_export_request) is False,
            f'Expected {non_export_request!r} not to request a CSV artifact.',
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
        'provide the extracted rows as CSV',
        'return CSV for this Word document',
        'output the invoice fields in CSV format',
        'give me a CSV',
        'Can I get a CSV of this?',
        'CSV version, please',
        'Please respond as CSV',
        'I need the results in CSV',
        'Put the extracted fields in CSV',
        'I want CSV output',
        'I need a direct CSV file.',
        'Do not summarize; create a CSV.',
        'CSV file, please.',
        'Make a spreadsheet from this document.',
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
        'assistant_table_export_requested' in chat_route_content,
        'Expected route_backend_chats.py to reuse the shared assistant table export intent predicate.',
    )
    assert_true(
        'def maybe_create_assistant_table_generated_output(' in chat_route_content,
        'Expected route_backend_chats.py to expose assistant table artifact creation.',
    )
    assert_true(
        'should_queue_tabular_generated_output_background(row_count, len(row_batches), settings)' in chat_route_content,
        'Expected large assistant-derived CSV artifacts to use the durable background export threshold.',
    )
    assert_true(
        'queue_tabular_generated_output_run(' in chat_route_content,
        'Expected large assistant-derived CSV artifacts to queue through the background tabular exporter.',
    )
    assert_true(
        'passthrough_input_rows=True' in chat_route_content,
        'Expected large assistant-derived CSV artifacts to avoid a second model transformation.',
    )
    assert_true(
        "'background_export': True" in read_text(BACKGROUND_EXPORT_FILE),
        'Expected queued assistant exports to reuse standard background-export metadata.',
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
        'if assistant_table_export_requested(user_question):' in chat_route_content,
        'Expected tabular output format detection to use the shared CSV/table intent predicate.',
    )
    assert_true(
        "requested_format == 'csv'" in chat_route_content,
        'Expected CSV request markers to create tabular generated outputs when available.',
    )


def run_tests() -> bool:
    tests = [
        test_markdown_table_response_builds_csv_export,
        test_tab_separated_table_response_builds_rows,
        test_non_tabular_document_csv_response_builds_export,
        test_plain_document_csv_response_excludes_surrounding_prose_and_citation,
        test_document_csv_response_preserves_multiline_and_escaped_quotes,
        test_fenced_document_csv_preserves_sentence_shaped_rows,
        test_fenced_document_csv_wins_over_larger_markdown_table,
        test_explicit_csv_fence_wins_over_larger_generic_fence,
        test_plain_document_csv_preserves_quoted_blank_lines_and_ignores_comma_prose,
        test_plain_document_csv_preserves_long_headers_and_sentence_values,
        test_plain_document_csv_excludes_prose_and_short_page_citations,
        test_plain_document_csv_excludes_generic_prose_and_non_page_citations,
        test_plain_document_csv_normalizes_preambles_and_citation_variants,
        test_document_csv_supports_alternate_text_fences,
        test_document_csv_neutralizes_spreadsheet_formulas,
        test_document_csv_accepts_punctuation_and_duplicate_headers,
        test_document_csv_preserves_header_suffix_collisions,
        test_document_csv_neutralizes_formula_headers_without_losing_rows,
        test_all_generated_csv_writers_neutralize_formulas,
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
