# test_generated_csv_uses_authorized_action_rows.py
#!/usr/bin/env python3
"""
Functional test for CSV artifacts built from authorized action rows.
Version: 0.260.009
Implemented in: 0.260.007; earlier-turn reach-back and clarification carry-forward in 0.260.008; history-limit window and compact-citation scan in 0.260.009

Two customer conversations asked a telemetry agent to retrieve BatteryVoltage1
and create a CSV. The agent retrieved 900 authorized samples, but the published
artifact held 3 rows in one conversation and 2 rows of server discovery metadata
in the other.

Three defects combined:
  1. build_generated_file_export() let any assistant-rendered table outrank the
     authorized action rows, so an illustrative excerpt replaced the dataset.
  2. CSV never received the publication contract JSON/XML already had, so the
     model said it could not attach files and pasted a sample instead.
  3. A turn whose reply was the schema clarification still published a CSV,
     built from whatever incidental discovery rows the turn happened to produce.
  4. Discovery and lookup calls were merged into the retrieved dataset, adding
     junk rows and a Source action column to the artifact.
  5. Nothing reached back to data an earlier turn already gathered, so a
     follow-up "create a csv" and an answered clarification both had no rows.

This test ensures the authorized rows win over an excerpt, a deliberate
assistant table still wins, a clarification turn publishes nothing, and an
answered clarification resumes the original request using the earlier rows.
"""

import json
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
    build_generated_file_export,
    build_generated_file_output_guidance,
    estimate_function_result_row_count,
    extract_authorized_function_result_rows,
    resolve_pending_generated_file_format,
    select_prior_turn_action_citations,
)

IMPLEMENTED_VERSION = '0.260.007'

TELEMETRY_COLUMNS = (
    'generation_time_utc',
    'reception_time_utc',
    'battery_voltage_1_v',
    'raw_value',
    'monitoring_result',
    'validity_status',
)
TELEMETRY_ROWS = [
    {
        # High-granularity telemetry carries a distinct acquisition time per sample, which is what
        # lets 0.260.011 tell a genuine continuation page apart from a re-read of the same window.
        'generation_time_utc': f'2026-08-19T15:{37 + index // 60:02d}:{index % 60:02d}.371000+00:00',
        'reception_time_utc': f'2026-08-19T15:{37 + index // 60:02d}:{index % 60:02d}.372000+00:00',
        'battery_voltage_1_v': 27 + (index % 5),
        'raw_value': 27 + (index % 5),
        'monitoring_result': 'CRITICAL',
        'validity_status': 'ACQUIRED',
    }
    for index in range(900)
]
TELEMETRY_FUNCTION_RESULTS = [{
    'plugin_name': 'YamcsPlugin',
    'function_name': 'list_parameter_history',
    'success': True,
    'function_result': {'row_count': 900, 'rows': TELEMETRY_ROWS},
}]
# The real turn also ran two discovery calls before paging the history.
FULL_TURN_FUNCTION_RESULTS = [
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_instances',
        'success': True,
        'function_result': {'rows': [{'name': 'simulator', 'state': 'RUNNING'}]},
    },
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_parameters',
        'success': True,
        'function_result': {'rows': [{'qualified_name': '/YSS/SIMULATOR/BatteryVoltage1', 'units': 'V'}]},
    },
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_parameter_history',
        'success': True,
        'function_result': {'rows': TELEMETRY_ROWS[:450]},
    },
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_parameter_history',
        'success': True,
        'function_result': {'rows': TELEMETRY_ROWS[450:]},
    },
]
TELEMETRY_QUESTION = (
    'grab BatteryVoltage1 over the last 15 minutes, provide high granularity and create a csv'
)

DISCOVERY_FUNCTION_RESULTS = [
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_instances',
        'success': True,
        'function_result': {'rows': [{'name': 'simulator', 'state': 'RUNNING'}]},
    },
    {
        'plugin_name': 'YamcsPlugin',
        'function_name': 'list_parameters',
        'success': True,
        'function_result': {'rows': [{'qualified_name': '/YSS/SIMULATOR/BatteryVoltage1', 'units': 'V'}]},
    },
]
CLARIFICATION_REPLY = (
    'Paul, should each CSV row represent an extracted BatteryVoltage1 telemetry sample, '
    'and which columns should it include, for example: generation time, voltage (V), '
    'monitoring result, and validity status?'
)


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def build_sample_excerpt_reply(excerpt_row_count=3):
    """Rebuild the assistant reply that pasted real rows as an illustrative sample."""
    sample_lines = [','.join(TELEMETRY_COLUMNS)]
    for row in TELEMETRY_ROWS[:excerpt_row_count]:
        sample_lines.append(','.join(str(row[column]) for column in TELEMETRY_COLUMNS))
    rendered_sample = '\n'.join(sample_lines)
    return (
        'Paul, I retrieved **BatteryVoltage1** at 1 Hz. Samples: 900. Observed range 27 to 31 V.\n\n'
        'I do not have a file-creation or attachment capability in this session, so I cannot '
        'deliver a downloadable CSV artifact. The CSV schema is:\n\n'
        f'```\n{rendered_sample}\n```\n\n'
        'The archive response establishes the full 900-row dataset.\n'
    )


def test_pasted_sample_does_not_replace_authorized_rows():
    """An excerpt of the authorized rows must not shrink the published artifact."""
    print('Testing pasted-sample precedence...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        TELEMETRY_QUESTION,
        build_sample_excerpt_reply(),
        function_results=TELEMETRY_FUNCTION_RESULTS,
    )

    assert_true(export_payload is not None, 'Expected the telemetry request to publish a CSV artifact.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        f"Expected all {len(TELEMETRY_ROWS)} authorized rows; got {export_payload['row_count']}.",
    )
    assert_true(
        export_payload['row_source'] == 'structured function result',
        'Expected the authorized action rows to supply the artifact.',
    )
    assert_true(
        list(export_payload['preview_rows'][0]) == list(TELEMETRY_COLUMNS),
        'Expected the artifact to keep the telemetry column schema.',
    )


def test_deliberate_assistant_table_still_wins():
    """A table the model composed itself is not an excerpt and must stay authoritative."""
    print('Testing deliberate assistant table precedence...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    directory_results = [
        {
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_people',
            'success': True,
            'function_result': {'value': [{'Name': 'Ada', 'Department': 'Engineering'}]},
        },
        {
            'plugin_name': 'DirectoryPlugin',
            'function_name': 'list_contractors',
            'success': True,
            'function_result': {'items': [{'Name': 'Grace', 'Department': 'Operations'}]},
        },
    ]
    export_payload = build_generated_file_export(
        'create a combined CSV',
        '| Name | Department |\n| --- | --- |\n| Assistant-selected | Finance |\n',
        function_results=directory_results,
    )

    assert_true(export_payload is not None, 'Expected the combined CSV request to publish an artifact.')
    assert_true(
        export_payload['row_source'] == 'assistant response',
        'Expected a model-composed table to remain authoritative over action rows.',
    )
    assert_true(export_payload['row_count'] == 1, 'Expected the model-composed row to be preserved.')


def test_partial_excerpt_of_larger_result_is_still_replaced():
    """A longer excerpt is still an excerpt, not a derived answer."""
    print('Testing multi-row excerpt precedence...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        TELEMETRY_QUESTION,
        build_sample_excerpt_reply(excerpt_row_count=25),
        function_results=TELEMETRY_FUNCTION_RESULTS,
    )

    assert_true(export_payload is not None, 'Expected the telemetry request to publish a CSV artifact.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        'Expected a 25-row excerpt to be replaced by the full authorized result set.',
    )


def test_clarification_turn_publishes_no_artifact():
    """The turn that asks the schema clarification must not publish a CSV."""
    print('Testing clarification-turn suppression...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        'create a csv',
        CLARIFICATION_REPLY,
        function_results=DISCOVERY_FUNCTION_RESULTS,
    )

    assert_true(
        export_payload is None,
        'Expected a clarifying question to publish no artifact instead of discovery metadata.',
    )


def test_answered_turn_still_publishes_action_rows():
    """Suppression must be limited to clarification replies, not ordinary summaries."""
    print('Testing normal reply still publishes action rows...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        'create a csv',
        'Retrieved the BatteryVoltage1 archive window and prepared the export.',
        function_results=TELEMETRY_FUNCTION_RESULTS,
    )

    assert_true(export_payload is not None, 'Expected an ordinary reply to still publish the artifact.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        'Expected the full authorized result set for an ordinary reply.',
    )


def test_discovery_calls_do_not_dilute_the_retrieved_dataset():
    """Lookup and discovery calls in the same turn must not become artifact rows."""
    print('Testing dominant action-result selection...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    rows = extract_authorized_function_result_rows(FULL_TURN_FUNCTION_RESULTS)

    assert_true(
        len(rows) == len(TELEMETRY_ROWS),
        f'Expected only the {len(TELEMETRY_ROWS)} retrieved samples; got {len(rows)}.',
    )
    assert_true(
        list(rows[0]) == list(TELEMETRY_COLUMNS),
        'Expected the telemetry schema without a Source action column from discovery calls.',
    )


def test_paged_calls_to_one_action_stay_one_dataset():
    """Two pages of the same action are one dataset, not two labeled groups."""
    print('Testing paged action-result grouping...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    paged_results = [
        {
            'plugin_name': 'YamcsPlugin',
            'function_name': 'list_parameter_history',
            'success': True,
            'function_result': {'rows': TELEMETRY_ROWS[:450]},
        },
        {
            'plugin_name': 'YamcsPlugin',
            'function_name': 'list_parameter_history',
            'success': True,
            'function_result': {'rows': TELEMETRY_ROWS[450:]},
        },
    ]
    rows = extract_authorized_function_result_rows(paged_results)

    assert_true(len(rows) == len(TELEMETRY_ROWS), 'Expected both pages to be kept.')
    assert_true(
        'Source action' not in rows[0],
        'Expected one action to stay one dataset without a Source action column.',
    )


def test_followup_request_reuses_earlier_turn_rows():
    """'create a csv' must reach back to data an earlier turn already gathered."""
    print('Testing earlier-turn reach-back...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        'create a csv',
        'Here is the CSV of the BatteryVoltage1 samples I retrieved.',
        function_results=[],
        prior_function_results_loader=lambda: FULL_TURN_FUNCTION_RESULTS,
    )

    assert_true(export_payload is not None, 'Expected the follow-up request to publish an artifact.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        'Expected the earlier turn\'s full result set to be reused.',
    )
    assert_true(
        export_payload['row_source'] == 'earlier action result',
        'Expected reused rows to declare their earlier-turn provenance.',
    )


def test_current_turn_rows_are_never_double_counted():
    """The reach-back must not run when the turn gathered its own rows."""
    print('Testing reach-back suppression when the turn has data...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    export_payload = build_generated_file_export(
        'create a csv',
        'Retrieved the archive window and prepared the export.',
        function_results=FULL_TURN_FUNCTION_RESULTS,
        prior_function_results_loader=lambda: FULL_TURN_FUNCTION_RESULTS,
    )

    assert_true(export_payload is not None, 'Expected the request to publish an artifact.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        'Expected current-turn rows only, with no earlier-turn rows appended.',
    )
    assert_true(
        export_payload['row_source'] == 'structured function result',
        'Expected current-turn provenance when the turn gathered its own rows.',
    )


def test_answering_the_clarification_publishes_the_csv():
    """Answering the schema clarification must resume the original CSV request."""
    print('Testing clarification answer carry-forward...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    pending_format = resolve_pending_generated_file_format(
        'yes, one row per sample',
        CLARIFICATION_REPLY,
    )
    assert_true(pending_format == 'csv', 'Expected the answered clarification to resume a CSV request.')

    export_payload = build_generated_file_export(
        'yes, one row per sample',
        'Understood, one row per sample.',
        function_results=[],
        prior_function_results_loader=lambda: FULL_TURN_FUNCTION_RESULTS,
        pending_output_format=pending_format,
    )

    assert_true(export_payload is not None, 'Expected the answered clarification to publish the CSV.')
    assert_true(
        export_payload['row_count'] == len(TELEMETRY_ROWS),
        'Expected the answered clarification to export the already-gathered samples.',
    )


def test_pending_clarification_does_not_override_a_new_request():
    """A reply that asks for another format or follows no clarification carries nothing."""
    print('Testing pending clarification boundaries...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    assert_true(
        resolve_pending_generated_file_format('actually make it a pdf', CLARIFICATION_REPLY) is None,
        'Expected a different requested format to cancel the pending CSV request.',
    )
    assert_true(
        resolve_pending_generated_file_format('yes, one row per sample', 'Here are the results.') is None,
        'Expected no pending request when the previous turn asked nothing.',
    )
    assert_true(
        resolve_pending_generated_file_format('', CLARIFICATION_REPLY) is None,
        'Expected an empty reply to carry no pending request.',
    )


def _build_compact_citation(artifact_id, plugin_name, function_name, function_result):
    """Compact a citation exactly the way the chat pipeline stores it on a message."""
    import types

    if 'functions_azure_maps' not in sys.modules:
        # functions_message_artifacts only needs this for map payloads, and importing the real
        # module pulls in config.py and a live Cosmos client.
        azure_maps_stub = types.ModuleType('functions_azure_maps')
        azure_maps_stub.refresh_azure_maps_citation_payload = lambda payload: payload
        sys.modules['functions_azure_maps'] = azure_maps_stub

    from functions_message_artifacts import build_compact_agent_citation

    return build_compact_agent_citation(
        {
            'plugin_name': plugin_name,
            'function_name': function_name,
            'success': True,
            'function_result': function_result,
        },
        artifact_id=artifact_id,
    )


def test_row_count_estimate_survives_citation_compaction():
    """The cheap scan depends on compaction keeping a usable row signal on the message."""
    print('Testing compacted row-count estimate...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    compact_citation = _build_compact_citation(
        'm1_artifact_2',
        'YamcsPlugin',
        'list_parameter_history',
        {'instance': 'simulator', 'row_count': 900, 'rows': TELEMETRY_ROWS},
    )

    assert_true(
        len(json.dumps(compact_citation)) < 4000,
        'Expected the stored citation to stay compact.',
    )
    assert_true(
        estimate_function_result_row_count(compact_citation) == len(TELEMETRY_ROWS),
        'Expected the compacted citation to still report its full row count.',
    )

    unlabeled_citation = _build_compact_citation(
        'm1_artifact_3',
        'YamcsPlugin',
        'list_parameter_history',
        {'rows': TELEMETRY_ROWS},
    )
    assert_true(
        estimate_function_result_row_count(unlabeled_citation) == len(TELEMETRY_ROWS),
        'Expected the truncated row list marker to restore the full count.',
    )


def test_reach_back_prefers_the_dataset_over_newer_lookups():
    """A newer memory or discovery call must not outrank the dataset a request means."""
    print('Testing prior-turn action selection...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    assistant_messages = [
        {
            'id': 'm3',
            'agent_citations': [_build_compact_citation(
                'm3_artifact_1', 'FactMemoryPlugin', 'get_facts',
                {'facts': [{'key': 'name', 'value': 'Paul'}]},
            )],
        },
        {
            'id': 'm2',
            'agent_citations': [_build_compact_citation(
                'm2_artifact_1', 'YamcsPlugin', 'list_instances',
                {'rows': [{'name': 'simulator', 'state': 'RUNNING'}]},
            )],
        },
        {
            'id': 'm1',
            'agent_citations': [
                _build_compact_citation(
                    'm1_artifact_1', 'YamcsPlugin', 'list_instances',
                    {'rows': [{'name': 'simulator', 'state': 'RUNNING'}]},
                ),
                _build_compact_citation(
                    'm1_artifact_2', 'YamcsPlugin', 'list_parameter_history',
                    {'row_count': 450, 'rows': TELEMETRY_ROWS[:450]},
                ),
                _build_compact_citation(
                    'm1_artifact_3', 'YamcsPlugin', 'list_parameter_history',
                    {'row_count': 450, 'rows': TELEMETRY_ROWS[450:]},
                ),
            ],
        },
    ]

    selected_citations = select_prior_turn_action_citations(assistant_messages)

    assert_true(len(selected_citations) == 2, 'Expected both pages of the dataset action.')
    assert_true(
        [citation['artifact_id'] for citation in selected_citations] == ['m1_artifact_2', 'm1_artifact_3'],
        'Expected only the dataset artifacts to be selected for hydration.',
    )
    assert_true(
        all(citation['function_name'] == 'list_parameter_history' for citation in selected_citations),
        'Expected discovery and memory lookups to be skipped.',
    )


def test_reach_back_falls_back_to_the_only_rows_available():
    """When no turn holds a dataset, the most recent rows are still better than nothing."""
    print('Testing prior-turn fallback selection...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    assistant_messages = [
        {'id': 'm2', 'agent_citations': [_build_compact_citation(
            'm2_artifact_1', 'DirectoryPlugin', 'list_people',
            {'rows': [{'Name': 'Ada'}, {'Name': 'Grace'}]},
        )]},
        {'id': 'm1', 'agent_citations': []},
    ]

    selected_citations = select_prior_turn_action_citations(assistant_messages)

    assert_true(len(selected_citations) == 1, 'Expected the only available action to be selected.')
    assert_true(
        selected_citations[0]['artifact_id'] == 'm2_artifact_1',
        'Expected the most recent available rows to be used.',
    )
    assert_true(
        select_prior_turn_action_citations([]) == [],
        'Expected an empty history to select nothing.',
    )


def test_csv_guidance_states_the_publication_contract():
    """CSV must receive the same publication contract JSON and XML already state."""
    print('Testing CSV publication guidance parity...')
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    csv_guidance = build_generated_file_output_guidance('create a csv')
    assert_true(
        'attaches the file after generation' in csv_guidance,
        'Expected CSV guidance to state that the server attaches the artifact.',
    )
    assert_true(
        'cannot create or attach files' in csv_guidance,
        'Expected CSV guidance to forbid claiming files cannot be attached.',
    )
    assert_true(
        'do not paste a sample of the rows' in csv_guidance,
        'Expected CSV guidance to forbid pasting a row sample instead of the artifact.',
    )
    assert_true(
        'ask exactly one concise clarification' in csv_guidance,
        'Expected the existing one-clarification rule to survive.',
    )
    assert_true(
        build_generated_file_output_guidance('summarize the selected sources') == '',
        'Expected non-artifact requests to receive no generated-file guidance.',
    )


def run_tests() -> bool:
    tests = [
        test_pasted_sample_does_not_replace_authorized_rows,
        test_deliberate_assistant_table_still_wins,
        test_partial_excerpt_of_larger_result_is_still_replaced,
        test_clarification_turn_publishes_no_artifact,
        test_answered_turn_still_publishes_action_rows,
        test_discovery_calls_do_not_dilute_the_retrieved_dataset,
        test_paged_calls_to_one_action_stay_one_dataset,
        test_followup_request_reuses_earlier_turn_rows,
        test_current_turn_rows_are_never_double_counted,
        test_answering_the_clarification_publishes_the_csv,
        test_pending_clarification_does_not_override_a_new_request,
        test_row_count_estimate_survives_citation_compaction,
        test_reach_back_prefers_the_dataset_over_newer_lookups,
        test_reach_back_falls_back_to_the_only_rows_available,
        test_csv_guidance_states_the_publication_contract,
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
