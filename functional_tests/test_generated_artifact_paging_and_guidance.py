# test_generated_artifact_paging_and_guidance.py
#!/usr/bin/env python3
"""
Functional test for paged action rows, truncation disclosure, and carried guidance.
Version: 0.260.011
Implemented in: 0.260.011

A deployment test produced three defects that the log confirmed:

  1. An agent answered "yes and all columns" to a schema clarification, replied
     "I cannot create or attach a CSV file in this interface", and the server
     published the CSV anyway. The publication contract was resolved from the
     current user message only, so the answer turn injected no guidance at all
     even though 0.260.008 already carried the format forward for publishing.
  2. Two `list_parameter_history` calls in one turn both started at the same
     timestamp, so the second page re-read rows the first page already held.
     The action grouping added in 0.260.008 concatenated them, producing a
     1,000-row file for a window that held roughly 500 distinct samples.
  3. Those same calls reported `truncated=True`, yet the published file gave no
     indication that it covered only part of the matching data.

This test ensures overlapping pages collapse to distinct rows, truncated source
results are disclosed on the artifact, and the guidance format falls back to the
clarification the reply is answering.
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'application' / 'single_app'
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

from functions_generated_file_exports import (  # noqa: E402
    GENERATED_FILE_PAGING_GUIDANCE,
    GENERATED_FILE_TRUNCATED_ROWS_NOTE,
    build_generated_file_artifact_metadata,
    build_generated_file_export,
    build_generated_file_output_guidance,
    build_structured_artifact_rows_payload,
    extract_authorized_function_result_rows,
    function_results_report_truncated_rows,
)


def _telemetry_rows(start_index, count):
    return [
        {
            'generation_time': f'2026-08-19T20:40:{index % 60:02d}.000Z',
            'eng_value': round(11.0 + (index * 0.001), 4),
            'raw_value': index,
            'monitoring_result': 'IN_LIMITS',
        }
        for index in range(start_index, start_index + count)
    ]


def _history_call(rows, truncated):
    return {
        'success': True,
        'plugin_name': 'yamcs_plugin',
        'function_name': 'list_parameter_history',
        'function_result': {
            'instance': 'simulator',
            'row_count': len(rows),
            'truncated': truncated,
            'rows': rows,
        },
    }


def test_overlapping_pages_collapse_to_distinct_rows():
    """Re-reading an action from the same start must not double the dataset."""
    print("Testing overlapping paged action results...")
    try:
        full_page = _telemetry_rows(0, 500)
        # The agent narrowed only the stop time, so this page repeats the first 300 rows.
        overlapping_page = _telemetry_rows(0, 300)
        rows = extract_authorized_function_result_rows([
            _history_call(full_page, True),
            _history_call(overlapping_page, False),
        ])

        assert len(rows) == 500, f'expected 500 distinct rows, got {len(rows)}'
        signatures = {tuple(sorted(row.items())) for row in rows}
        assert len(signatures) == 500, 'distinct row signatures were not preserved'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_non_overlapping_pages_still_combine():
    """Genuine continuation pages must still extend the dataset."""
    print("Testing non-overlapping paged action results...")
    try:
        rows = extract_authorized_function_result_rows([
            _history_call(_telemetry_rows(0, 500), True),
            _history_call(_telemetry_rows(500, 401), False),
        ])

        assert len(rows) == 901, f'expected 901 combined rows, got {len(rows)}'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_truncated_source_is_reported():
    """A capped action result must be recognizable as partial."""
    print("Testing truncation detection...")
    try:
        assert function_results_report_truncated_rows([
            _history_call(_telemetry_rows(0, 500), True),
        ]) is True, 'truncated result was not detected'
        assert function_results_report_truncated_rows([
            _history_call(_telemetry_rows(0, 401), False),
        ]) is False, 'complete result was reported as truncated'
        assert function_results_report_truncated_rows([]) is False, 'empty results reported truncation'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_csv_export_discloses_truncated_rows():
    """The CSV artifact must say the source action returned only part of the data."""
    print("Testing CSV truncation disclosure...")
    try:
        export_payload = build_generated_file_export(
            'convert the parameter history to csv without changes',
            'Here is the telemetry export.',
            function_results=[_history_call(_telemetry_rows(0, 500), True)],
        )

        assert export_payload is not None, 'no CSV export was produced'
        assert export_payload['row_count'] == 500, f"unexpected row count {export_payload['row_count']}"
        assert export_payload['rows_truncated'] is True, 'truncation flag missing from payload'
        assert GENERATED_FILE_TRUNCATED_ROWS_NOTE in export_payload['summary'], (
            'summary did not disclose the truncation'
        )

        artifact_metadata = build_generated_file_artifact_metadata(
            export_payload,
            {'message': {'id': 'artifact-1', 'file_name': export_payload['file_name']}},
            'conversation-1',
        )
        assert artifact_metadata is not None, 'no artifact metadata was produced'
        assert artifact_metadata.get('rows_truncated') is True, 'truncation flag missing from artifact'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_complete_export_is_not_marked_partial():
    """A complete action result must not be labeled partial."""
    print("Testing complete export labeling...")
    try:
        export_payload = build_generated_file_export(
            'convert the parameter history to csv without changes',
            'Here is the telemetry export.',
            function_results=[_history_call(_telemetry_rows(0, 401), False)],
        )

        assert export_payload is not None, 'no CSV export was produced'
        assert export_payload['rows_truncated'] is False, 'complete export was flagged as truncated'
        assert GENERATED_FILE_TRUNCATED_ROWS_NOTE not in export_payload['summary'], (
            'complete export summary claimed truncation'
        )
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_structured_payload_reports_truncation():
    """JSON and XML artifacts must carry the same truncation signal as CSV."""
    print("Testing structured artifact truncation signal...")
    try:
        for output_format in ('json', 'xml'):
            payload = build_structured_artifact_rows_payload(
                f'convert the parameter history to {output_format} without changes',
                output_format,
                function_results=[_history_call(_telemetry_rows(0, 500), True)],
            )
            assert payload is not None, f'no {output_format} payload was produced'
            assert payload['rows_truncated'] is True, f'{output_format} payload lost the truncation flag'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_reachback_rows_carry_prior_truncation():
    """Rows recovered from an earlier turn must keep that turn's truncation signal."""
    print("Testing reach-back truncation signal...")
    try:
        prior_results = [_history_call(_telemetry_rows(0, 500), True)]
        export_payload = build_generated_file_export(
            'convert those results to csv without changes',
            'Using the telemetry already retrieved.',
            function_results=[],
            prior_function_results_loader=lambda: prior_results,
        )

        assert export_payload is not None, 'no CSV export was produced from prior rows'
        assert export_payload['row_source'] == 'earlier action result', (
            f"unexpected row source {export_payload['row_source']}"
        )
        assert export_payload['rows_truncated'] is True, 'reach-back lost the truncation flag'
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_guidance_carries_pending_format():
    """A clarification answer must still receive the publication contract."""
    print("Testing carried guidance format...")
    try:
        answer_guidance = build_generated_file_output_guidance(
            'yes and all columns',
            requested_format='csv',
        )
        assert 'cannot create or attach files' in answer_guidance, (
            'carried guidance omitted the publication contract'
        )

        # Without a carried format the answer turn has no artifact contract to state.
        assert build_generated_file_output_guidance('yes and all columns') == '', (
            'guidance was emitted without a requested or pending format'
        )
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_paging_guidance_reaches_prose_formats():
    """Formats that can explain themselves must be told how to page past truncation."""
    print("Testing paging guidance coverage...")
    try:
        for output_format in ('csv', 'docx', 'pdf'):
            guidance = build_generated_file_output_guidance(
                f'create a {output_format} of the parameter history',
            )
            assert GENERATED_FILE_PAGING_GUIDANCE in guidance, (
                f'{output_format} guidance omitted the paging instruction'
            )

        # JSON and XML must return only the payload, so prose paging advice would conflict.
        for output_format in ('json', 'xml'):
            guidance = build_generated_file_output_guidance(
                f'create a {output_format} of the parameter history',
            )
            assert GENERATED_FILE_PAGING_GUIDANCE not in guidance, (
                f'{output_format} guidance added prose that conflicts with payload-only output'
            )
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_route_resolves_guidance_format_from_clarification():
    """The chat routes must resolve guidance from the pending format, not the raw message."""
    print("Testing route guidance format resolution...")
    try:
        route_source = (APP_DIR / 'route_backend_chats.py').read_text(encoding='utf-8')

        assert route_source.count('_resolve_generated_file_guidance_format(') == 3, (
            'expected one helper definition and both chat paths to use it'
        )
        assert 'requested_format=get_tabular_generated_output_format(user_message)' not in route_source, (
            'a guidance call still resolves the format from the current message only'
        )
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_artifact_card_renders_the_partial_badge():
    """The completed-artifact card hides the summary, so truncation needs a visible badge."""
    print("Testing artifact card truncation badge...")
    try:
        card_source = (
            APP_DIR / 'static' / 'js' / 'chat' / 'chat-messages.js'
        ).read_text(encoding='utf-8')

        assert "outputMetadata?.rows_truncated" in card_source, (
            'the artifact card never reads the truncation flag'
        )
        assert "truncatedBadge.textContent = 'Partial'" in card_source, (
            'the artifact card does not render a partial badge'
        )
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.260.011")

    tests = [
        test_overlapping_pages_collapse_to_distinct_rows,
        test_non_overlapping_pages_still_combine,
        test_truncated_source_is_reported,
        test_csv_export_discloses_truncated_rows,
        test_complete_export_is_not_marked_partial,
        test_structured_payload_reports_truncation,
        test_reachback_rows_carry_prior_truncation,
        test_guidance_carries_pending_format,
        test_paging_guidance_reaches_prose_formats,
        test_route_resolves_guidance_format_from_clarification,
        test_artifact_card_renders_the_partial_badge,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
