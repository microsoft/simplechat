# test_assistant_table_csv_artifact.py
#!/usr/bin/env python3
"""
Functional test for assistant-rendered table CSV artifacts.
Version: 0.260.005
Implemented in: 0.241.050; non-tabular document CSV parsing in 0.250.065; generated file export framework in 0.250.072; updated in 0.250.073; linear fence parsing coverage in 0.250.112; version assertion compatibility updated in 0.250.172; Word function-result serialization restored in 0.250.178; CSV assistant-text preservation in 0.260.005

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

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'application' / 'single_app'
CONFIG_FILE = APP_DIR / 'config.py'
CHAT_ROUTE_FILE = APP_DIR / 'route_backend_chats.py'
BACKGROUND_EXPORT_FILE = APP_DIR / 'functions_tabular_generated_exports.py'
GENERATED_EXPORTS_FILE = APP_DIR / 'functions_generated_file_exports.py'
TABULAR_ORCHESTRATION_FILE = APP_DIR / 'functions_tabular_orchestration.py'
WORKFLOW_RUNNER_FILE = APP_DIR / 'functions_workflow_runner.py'
IMPLEMENTED_VERSION = '0.250.112'

sys.path.append(str(APP_DIR))

from functions_assistant_table_exports import (  # noqa: E402
    assistant_table_export_requested,
    build_csv_output_clarification_guidance,
    build_safe_csv_headers,
    build_assistant_table_csv_export,
    extract_assistant_table_entries,
    neutralize_csv_spreadsheet_formula,
)
from functions_generated_file_exports import (  # noqa: E402
    build_generated_file_artifact_metadata,
    build_generated_file_export,
    get_generated_file_export_content,
    get_requested_generated_file_format,
    has_generated_file_output,
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


def load_workflow_generated_file_export_helper(namespace):
    module_tree = ast.parse(read_text(WORKFLOW_RUNNER_FILE), filename=str(WORKFLOW_RUNNER_FILE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_maybe_create_workflow_generated_file_output'
    ]
    if len(selected_nodes) != 1:
        raise AssertionError('Expected workflow generated-file artifact helper.')

    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(WORKFLOW_RUNNER_FILE), 'exec'), namespace)
    return namespace['_maybe_create_workflow_generated_file_output']


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


def test_document_action_analysis_reply_builds_csv_export():
    print('Testing structured document-action CSV source selection...')

    assistant_result = {
        'reply': 'The detailed analysis is available in the attached artifact.',
        'analysis_result': {
            'analysis_reply': '''```csv
Name,Invoice Number
Contoso,DCAW1366188
```''',
        },
    }
    selected_content = get_generated_file_export_content(assistant_result)
    export_payload = build_assistant_table_csv_export(
        'turn these into a single CSV',
        selected_content,
    )

    assert_true(
        export_payload is not None,
        'Expected a structured document-action analysis reply to produce a CSV artifact.',
    )
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(csv_rows[0]['Invoice Number'] == 'DCAW1366188', 'Expected the analysis reply row to be exported.')


def test_structured_action_result_builds_csv_when_assistant_summarizes():
    print('Testing structured action-result CSV export fallback...')

    action_results = [{
        'plugin_name': 'BillingPlugin',
        'function_name': 'list_invoices',
        'success': True,
        'function_result': {
            'rows': [
                {'Invoice Number': 'DCAW1366188', 'Amount': '=42.50', 'api_key': 'must-not-export'},
                {'Invoice Number': 'DCAW1366189', 'Amount': '-10.00', 'api_key': 'must-not-export'},
            ],
        },
    }]
    export_payload = build_generated_file_export(
        'save the action results as one CSV',
        'The billing action returned two invoices.',
        function_results=action_results,
    )

    assert_true(export_payload is not None, 'Expected structured action data to produce a CSV when the assistant summarizes it.')
    assert_true(export_payload.get('row_source') == 'structured function result', 'Expected function-result CSV provenance.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 2, 'Expected both action result rows in the CSV artifact.')
    assert_true(csv_rows[0]['Invoice Number'] == 'DCAW1366188', 'Expected action result fields to be preserved.')
    assert_true(csv_rows[0]['Amount'].startswith("'="), 'Expected action result formulas to be neutralized.')
    assert_true('api_key' not in csv_rows[0], 'Expected sensitive action result fields to be omitted.')


def test_structured_action_results_combine_and_preserve_assistant_priority():
    print('Testing combined action-result CSV rows and assistant table priority...')

    action_results = [
        {
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_people',
            'success': True,
            'function_result': '{"value":[{"Name":"Ada","Department":"Engineering"}]}',
        },
        {
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_contractors',
            'success': True,
            'function_result': {'items': [{'Name': 'Grace', 'Department': 'Operations'}]},
        },
    ]
    action_export = build_generated_file_export(
        'create a combined CSV',
        'The directory actions completed.',
        function_results=action_results,
    )
    action_rows = parse_csv_rows(action_export.get('file_content'))
    assert_true(len(action_rows) == 2, 'Expected data rows from both action results.')
    assert_true(
        {row['Source action'] for row in action_rows} == {'list_people', 'list_contractors'},
        'Expected combined action rows to retain their source action.',
    )

    assistant_export = build_generated_file_export(
        'create a combined CSV',
        '''| Name | Department |
| --- | --- |
| Assistant-selected | Finance |
''',
        function_results=action_results,
    )
    assistant_rows = parse_csv_rows(assistant_export.get('file_content'))
    assert_true(len(assistant_rows) == 1, 'Expected a valid assistant table to take priority over action rows.')
    assert_true(assistant_rows[0]['Name'] == 'Assistant-selected', 'Expected assistant-selected table data to remain authoritative.')


def test_tabular_action_result_does_not_bypass_coverage_aware_exports():
    print('Testing tabular action-result exclusion...')

    export_payload = build_generated_file_export(
        'download CSV',
        'The table query returned a partial page.',
        function_results=[{
            'plugin_name': 'TabularProcessingPlugin',
            'function_name': 'query_tabular_data',
            'success': True,
            'function_result': {'data': [{'Case ID': 'SC-1'}]},
        }],
    )
    assert_true(
        export_payload is None,
        'Expected tabular action rows to remain on their coverage-aware export path.',
    )


def test_function_results_render_docx_and_pdf_capabilities():
    print('Testing DOCX and PDF function-result export capabilities...')
    assert_app_version_at_least('0.250.178')

    function_results = [{
        'plugin_name': 'DirectoryPlugin',
        'function_name': 'list_people',
        'success': True,
        'function_result': {'value': [{'Name': 'Ada', 'Department': 'Engineering'}]},
    }]
    docx_export = build_generated_file_export(
        'create a Word document from the action results',
        'The directory action completed successfully.',
        function_results=function_results,
    )
    pdf_export = build_generated_file_export(
        'export the action results to PDF',
        'The directory action completed successfully.',
        function_results=function_results,
    )

    assert_true(get_requested_generated_file_format('create a Word document') == 'docx', 'Expected DOCX output intent.')
    assert_true(get_requested_generated_file_format('export to PDF') == 'pdf', 'Expected PDF output intent.')
    assert_true(get_requested_generated_file_format('I need a DOCX') == 'docx', 'Expected natural DOCX output intent.')
    assert_true(get_requested_generated_file_format('Give me a PDF') == 'pdf', 'Expected natural PDF output intent.')
    assert_true(docx_export is not None and docx_export['file_content'].startswith(b'PK'), 'Expected a DOCX file export.')
    assert_true(pdf_export is not None and pdf_export['file_content'].startswith(b'%PDF'), 'Expected a PDF file export.')
    assert_true(docx_export['row_source'] == 'structured function result', 'Expected DOCX to include function-result rows.')
    assert_true(pdf_export['row_source'] == 'structured function result', 'Expected PDF to include function-result rows.')
    assert_true(
        docx_export.get('passthrough_reason_code') == 'explicit_format_conversion',
        'Expected Word function-result serialization to record its explicit format-conversion contract.',
    )
    assert_true(
        pdf_export.get('passthrough_reason_code') == 'explicit_format_conversion',
        'Expected PDF function-result serialization to record its explicit format-conversion contract.',
    )


def test_derived_word_export_does_not_serialize_function_rows():
    print('Testing derived Word export function-result exclusion...')
    assert_app_version_at_least('0.250.178')

    export_payload = build_generated_file_export(
        'create a Word document from the action results and classify each person by risk',
        'The directory action completed successfully.',
        function_results=[{
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_people',
            'success': True,
            'function_result': {'value': [{'Name': 'Ada', 'Department': 'Engineering'}]},
        }],
    )

    assert_true(export_payload is not None, 'Expected the assistant response to remain exportable as a Word document.')
    assert_true(export_payload['row_source'] == 'assistant response', 'Expected derived function rows to remain excluded.')
    assert_true(export_payload['row_count'] == 0, 'Expected no untransformed function rows in the derived Word export.')
    assert_true('passthrough_reason_code' not in export_payload, 'Expected no passthrough claim for a derived request.')


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


def test_generic_fenced_csv_like_content_builds_export():
    print('Testing generic fenced CSV-like content parsing...')

    assistant_content = '''```
Name,Value
Generic,7
```
'''

    export_payload = build_assistant_table_csv_export('return CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected unlabeled fenced CSV-like content to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(len(csv_rows) == 1, 'Expected one row from generic fenced CSV-like content.')
    assert_true(csv_rows[0]['Name'] == 'Generic', 'Expected generic fenced row to be preserved.')


def test_unterminated_csv_fence_allows_unfenced_fallback():
    print('Testing unterminated CSV fence fallback behavior...')

    assistant_content = '''```csv
Incomplete,Header,Only
Broken

Name,Value
Fallback,9
'''

    export_payload = build_assistant_table_csv_export('download CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected valid unfenced CSV after an unterminated fence to produce an export.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(csv_rows[0]['Name'] == 'Fallback', 'Expected unfenced fallback rows to remain available.')


def test_adversarial_fence_opening_uses_linear_csv_parsing():
    print('Testing adversarial fence opening CSV parsing...')

    assistant_content = f'''```{' \t' * 200}csv
Name,Value
Linear,1
```
'''

    export_payload = build_assistant_table_csv_export('create a CSV', assistant_content)

    assert_true(export_payload is not None, 'Expected long whitespace before the CSV fence label to parse.')
    csv_rows = parse_csv_rows(export_payload.get('file_content'))
    assert_true(csv_rows[0]['Name'] == 'Linear', 'Expected adversarial fence opening not to change CSV rows.')


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


def test_universal_csv_request_variants_are_recognized():
    print('Testing universal CSV request variants...')

    assistant_content = """| Name | Amount |
| --- | --- |
| Contoso | 42 |
"""
    request_phrases = (
        'turn these into a single CSV',
        'turn these into one CSV',
        'turn these into a combined CSV',
        'create a single CSV file',
        'save one CSV',
    )

    for request_phrase in request_phrases:
        assert_true(
            assistant_table_export_requested(request_phrase),
            f"Expected '{request_phrase}' to request a CSV artifact.",
        )
        assert_true(
            build_assistant_table_csv_export(request_phrase, assistant_content) is not None,
            f"Expected '{request_phrase}' to produce an assistant table CSV export.",
        )


def test_csv_schema_clarification_guidance_is_specific_and_resumable():
    print('Testing CSV schema clarification guidance...')

    ambiguous_guidance = build_csv_output_clarification_guidance('turn these into a single CSV')
    assert_true(
        'ask exactly one concise clarification' in ambiguous_guidance,
        'Expected ambiguous CSV requests to instruct one schema clarification.',
    )
    assert_true(
        'latest answer instead of asking again' in ambiguous_guidance,
        'Expected a prior CSV clarification to be resumed from conversation history.',
    )

    explicit_guidance = build_csv_output_clarification_guidance(
        'Create a CSV with one row per document and columns: file name, invoice number, amount.',
    )
    assert_true(
        'explicitly specified CSV row or column structure' in explicit_guidance,
        'Expected explicit row and column instructions to bypass a schema clarification.',
    )
    assert_true(
        'ask exactly one concise clarification' not in explicit_guidance,
        'Expected explicit schema requests not to request a clarification.',
    )
    assert_true(
        build_csv_output_clarification_guidance('Summarize the selected sources.') == '',
        'Expected non-CSV requests not to receive CSV clarification guidance.',
    )


def test_workflow_generated_file_artifacts_reuse_shared_contract():
    print('Testing workflow generated-file artifact finalization...')

    uploaded_requests = []
    queue_requests = []
    shared_namespace = {
        'build_generated_file_artifact_metadata': build_generated_file_artifact_metadata,
        'build_generated_file_export': build_generated_file_export,
        'get_requested_generated_file_format': get_requested_generated_file_format,
        'has_generated_file_output': has_generated_file_output,
        'has_generated_tabular_csv_output': lambda outputs: any(
            output.get('output_format') == 'csv'
            for output in outputs or []
            if isinstance(output, dict)
        ),
        'get_settings': lambda: {},
        'build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        'should_queue_tabular_generated_output_background': lambda *args: False,
        'queue_tabular_generated_output_run': lambda **kwargs: queue_requests.append(kwargs),
        'build_background_tabular_generated_output_metadata': lambda run: run,
        'upload_generated_analysis_artifact_for_user': (
            lambda **kwargs: uploaded_requests.append(kwargs) or {
                'message': {'id': 'workflow-csv-artifact', 'file_name': kwargs['file_name']},
            }
        ),
        'log_event': lambda *args, **kwargs: None,
        'logging': type('Logging', (), {'ERROR': 'ERROR'}),
        'storage_account_personal_chat_container_name': 'personal-chat',
    }
    helper = load_workflow_generated_file_export_helper(shared_namespace)
    workflow = {
        'id': 'workflow-1',
        'user_id': 'user-1',
        'task_prompt': 'turn these into a single CSV',
    }
    assistant_content = '''| Name | Invoice Number |
| --- | --- |
| Contoso | DCAW1366188 |

Source: ParkingPrint.pdf, Page: 1
'''

    artifact = helper(
        workflow,
        'conversation-1',
        workflow['task_prompt'],
        assistant_content,
    )
    assert_true(artifact is not None, 'Expected a workflow CSV artifact for valid assistant rows.')
    assert_true(artifact['artifact_message_id'] == 'workflow-csv-artifact', 'Expected uploaded workflow artifact metadata.')
    assert_true(len(uploaded_requests) == 1, 'Expected one authorized artifact upload.')
    assert_true(uploaded_requests[0]['current_user_id'] == 'user-1', 'Expected upload to use the workflow owner.')
    assert_true(uploaded_requests[0]['output_format'] == 'csv', 'Expected a CSV artifact upload.')

    word_workflow = {
        **workflow,
        'task_prompt': 'create a Word document from the action results',
    }
    word_artifact = helper(
        word_workflow,
        'conversation-1',
        word_workflow['task_prompt'],
        'The directory action completed successfully.',
        function_results=[{
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_people',
            'success': True,
            'function_result': {'rows': [{'Name': 'Ada', 'Department': 'Engineering'}]},
        }],
    )
    assert_true(word_artifact is not None, 'Expected a workflow DOCX artifact from structured function results.')
    assert_true(uploaded_requests[-1]['output_format'] == 'docx', 'Expected workflow DOCX artifact metadata.')
    assert_true(uploaded_requests[-1]['capability'] == 'file_export', 'Expected generic file-export capability metadata.')
    assert_true(uploaded_requests[-1]['file_content'].startswith(b'PK'), 'Expected a rendered DOCX upload payload.')
    assert_true(
        helper(
            workflow,
            'conversation-1',
            workflow['task_prompt'],
            assistant_content,
            existing_outputs=[{'capability': 'tabular', 'output_format': 'csv'}],
        ) is None,
        'Expected existing tabular CSV output to suppress a duplicate workflow artifact.',
    )

    background_namespace = dict(shared_namespace)
    background_namespace.update({
        'should_queue_tabular_generated_output_background': lambda *args: True,
        'queue_tabular_generated_output_run': (
            lambda **kwargs: queue_requests.append(kwargs) or {'id': 'workflow-export-run'}
        ),
        'build_background_tabular_generated_output_metadata': (
            lambda run: {
                'background_export': True,
                'export_run_id': run['id'],
                'suppress_assistant_table_export': True,
            }
        ),
    })
    background_helper = load_workflow_generated_file_export_helper(background_namespace)
    background_artifact = background_helper(
        workflow,
        'conversation-1',
        workflow['task_prompt'],
        assistant_content,
    )
    assert_true(background_artifact['background_export'] is True, 'Expected large workflow exports to queue durably.')
    assert_true(queue_requests[-1]['passthrough_input_rows'] is True, 'Expected workflow rows to avoid a second model call.')
    assert_true(
        queue_requests[-1]['source_candidate']['source_authorization'] == {'source': 'chat'},
        'Expected staged workflow rows to use valid chat authorization without a source blob path.',
    )

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)
    assert_true(
        'generated_file_output = _maybe_create_workflow_generated_file_output(' in workflow_runner_content,
        'Expected workflow assistant messages to finalize shared file artifacts.',
    )
    assert_true(
        'generated_analysis_artifacts.append(generated_file_output)' in workflow_runner_content,
        'Expected workflow generated-file metadata to reach the generic artifact UI.',
    )


def test_csv_artifact_card_appends_below_assistant_response():
    """CSV narratives stream intact, so their card must never hide the assistant message."""
    print('Testing CSV artifact assistant-text preservation...')
    assert_app_version_at_least('0.260.005')

    csv_metadata = build_generated_file_artifact_metadata(
        {
            'capability': 'file_export',
            'file_name': 'generated_output_20260819_153747.csv',
            'output_format': 'csv',
            'row_count': 3,
            'summary': 'Generated CSV artifact.',
        },
        {'message': {'id': 'artifact-csv', 'file_name': 'generated_output_20260819_153747.csv'}},
        'conversation-1',
    )
    assert_true(
        csv_metadata['suppress_assistant_text'] is False,
        'Expected the CSV artifact card to append below the assistant response, not replace it.',
    )

    background_export_content = read_text(BACKGROUND_EXPORT_FILE)
    assert_true(
        'suppress_assistant_text=output_format in ASSISTANT_TEXT_SUPPRESSING_FORMATS' in background_export_content,
        'Expected background structured exports to reuse the shared assistant-text suppression contract.',
    )

    chat_route_content = read_text(CHAT_ROUTE_FILE)
    assert_true(
        "suppress_streamed_file_payload = requested_streamed_file_format in {'json', 'xml'}" in chat_route_content,
        'Expected only JSON/XML payloads to be withheld from the streamed assistant text.',
    )


def test_chat_route_wires_assistant_table_artifacts():
    print('Testing chat route assistant-table artifact plumbing...')

    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert_app_version_at_least(IMPLEMENTED_VERSION)
    assert_true(
        'assistant_table_export_requested' in chat_route_content,
        'Expected route_backend_chats.py to reuse the shared assistant table export intent predicate.',
    )
    assert_true(
        'def maybe_create_generated_file_output(' in chat_route_content,
        'Expected route_backend_chats.py to expose generic generated-file artifact creation.',
    )
    assert_true(
        "output_format == 'csv' and should_queue_tabular_generated_output_background(" in chat_route_content,
        'Expected large generated CSV artifacts to use the durable background export threshold.',
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
        'document_generated_analysis_artifacts.append(generated_file_output)' in chat_route_content,
        'Expected document-action assistant messages to include generated file artifacts.',
    )
    assert_true(
        'generated_analysis_artifacts_list.append(generated_file_output)' in chat_route_content,
        'Expected normal and streaming assistant messages to include generated file artifacts.',
    )
    assert_true(
        'document_action_reply_content = get_generated_file_export_content(execution_result)' in chat_route_content
        and 'assistant_content=document_action_reply_content' in chat_route_content,
        'Expected document-action file exports to use the structured analysis reply when available.',
    )
    assert_true(
        'assistant_content=get_generated_file_export_content(result)' in read_text(WORKFLOW_RUNNER_FILE),
        'Expected workflow file exports to use the structured analysis reply when available.',
    )
    assert_true(
        chat_route_content.count('build_generated_file_output_guidance(') == 2,
        'Expected normal and streaming Chat to apply the same file-output guidance.',
    )
    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)
    generated_exports_content = read_text(GENERATED_EXPORTS_FILE)
    tabular_orchestration_content = read_text(TABULAR_ORCHESTRATION_FILE)
    assert_true(
        workflow_runner_content.count('build_generated_file_output_guidance(prompt_text)') == 2,
        'Expected workflow model and agent execution to apply the same file-output guidance.',
    )
    assert_true(
        chat_route_content.count('function_results=agent_citations_list') == 2,
        'Expected normal and streaming Chat to pass current-turn action results to generated-file exports.',
    )
    assert_true(
        'function_results=execution_result.get(\'agent_citations\') or []' in chat_route_content,
        'Expected document actions to pass current-turn action results to generated-file exports.',
    )
    assert_true(
        'function_results=raw_agent_citations' in workflow_runner_content,
        'Expected workflows to pass current-turn action results to generated-file exports.',
    )
    assert_true(
        'if not assistant_table_export_requested(user_question):' in generated_exports_content,
        'Expected tabular output format detection to use the shared CSV/table intent predicate.',
    )
    assert_true(
        'return get_requested_structured_artifact_formats(user_question)' in tabular_orchestration_content,
        'Expected CSV request markers to create tabular generated outputs when available.',
    )


def run_tests() -> bool:
    tests = [
        test_markdown_table_response_builds_csv_export,
        test_tab_separated_table_response_builds_rows,
        test_non_tabular_document_csv_response_builds_export,
        test_document_action_analysis_reply_builds_csv_export,
        test_structured_action_result_builds_csv_when_assistant_summarizes,
        test_structured_action_results_combine_and_preserve_assistant_priority,
        test_tabular_action_result_does_not_bypass_coverage_aware_exports,
        test_function_results_render_docx_and_pdf_capabilities,
        test_derived_word_export_does_not_serialize_function_rows,
        test_plain_document_csv_response_excludes_surrounding_prose_and_citation,
        test_document_csv_response_preserves_multiline_and_escaped_quotes,
        test_fenced_document_csv_preserves_sentence_shaped_rows,
        test_fenced_document_csv_wins_over_larger_markdown_table,
        test_explicit_csv_fence_wins_over_larger_generic_fence,
        test_generic_fenced_csv_like_content_builds_export,
        test_unterminated_csv_fence_allows_unfenced_fallback,
        test_adversarial_fence_opening_uses_linear_csv_parsing,
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
        test_universal_csv_request_variants_are_recognized,
        test_csv_schema_clarification_guidance_is_specific_and_resumable,
        test_workflow_generated_file_artifacts_reuse_shared_contract,
        test_csv_artifact_card_appends_below_assistant_response,
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
