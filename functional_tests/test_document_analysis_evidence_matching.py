# test_document_analysis_evidence_matching.py
"""
Functional tests for general Analyze evidence matching, caveats, notes and validation logging.
Version: 0.261.191
Implemented in: 0.261.191

Refs #1540. A model quoting table-heavy or formatted source text must be located in its
original chunk when the only differences are presentation: markup, table rules, entities,
typographic quotes and dashes, compatibility forms, invisible characters, the amount of
whitespace, or case. The stored evidence must remain the verbatim source span. Presentation
separates tokens but never merges them, and written signs, symbols, list markers, superscripts
and literal asterisks stay content, so a merged number or word, a changed sign or a dropped
marker is not a match. A normalized match never begins or ends inside a word, including its
vowel signs and other marks, or inside a number whose digits are joined by a separator or a
grouping space, and it never ends before an apostrophe suffix such as the 't of can't. It may
leave out an elided prefix such as the l' of l'augmentation. Paraphrases, partial words and
numbers, cross-chunk joins, ambiguous passages and
wrong citations must stay unresolved with a diagnostic reason. Finding caveats and slice notes
must not make a supported result partial, and the final validation log must carry only
application codes, counts and a hashed conversation correlation.

The real candidate collector, finalizer, report and producer run against original fixture
documents and deterministic model responses; no Azure resources are used.
"""

import hashlib
import importlib
import json
import logging
import sys

import pytest

from test_support.document_analysis import (
    USER_ID,
    FixtureAnalysisClient,
    document_analysis_runtime,
    extract_fixture_findings,
    original_document,
)
from test_support.versioning import assert_app_version_at_least


SOURCE = {'document_id': 'matcher-source', 'file_name': 'matcher-source.txt'}
WORK_UNIT = {'work_unit_id': 'matcher-window'}
MATCH_COUNT_NAMES = (
    'exact', 'normalized', 'normalized_casefold',
    'missing_quote', 'missing_location', 'ambiguous', 'not_in_cited_location', 'not_in_window',
)
SUMMARY_MESSAGE = '[DOCUMENT_ANALYSIS] Final findings validated'


def window_chunks(*texts, pages=None):
    pages = pages or list(range(1, len(texts) + 1))
    return [
        {'id': f'chunk-{index}', 'chunk_sequence': index, 'page_number': page, 'chunk_text': text}
        for index, (page, text) in enumerate(zip(pages, texts), start=1)
    ]


def supported_finding(*passages, **fields):
    return {
        'finding_key': 'revenue', 'status': 'supported', 'issues': [],
        'values': {'finding': 'Reported revenue', 'explanation': 'The slice reports a revenue figure.'},
        'evidence': list(passages), **fields,
    }


def collect(runtime, chunks, *findings, **payload):
    response = json.dumps({'findings': list(findings), **payload})
    return runtime.results.collect_analysis_window_candidates(response, SOURCE, WORK_UNIT, {'chunks': chunks})


def match_counts(**counts):
    return {**dict.fromkeys(MATCH_COUNT_NAMES, 0), **counts}


def run_analysis(runtime, documents, client=None, **options):
    client = client or FixtureAnalysisClient()
    arguments = {
        'user_id': USER_ID,
        'analysis_prompt': 'Explain the findings in these documents.',
        'document_ids': list(documents),
        'invoke_prompt': client.invoke_prompt,
        'doc_scope': 'all',
        'window_size': 1,
        'max_documents': max(10, len(documents)),
        'max_retries_per_window': 0,
        'result_version': 'analyze-final-v1',
    }
    arguments.update(options)
    return runtime.producer.run_document_analysis(**arguments), client


def capture_producer_logs(monkeypatch, runtime):
    logs = []
    monkeypatch.setattr(
        runtime.producer, 'log_event',
        lambda message, *args, **kwargs: logs.append({'message': message, **kwargs}),
    )
    return logs


def real_logger_extra(message, extra):
    """Run the production App Insights allowlist, without leaving it in place of a test stub."""
    original = sys.modules.pop('functions_appinsights', None)
    try:
        return importlib.import_module('functions_appinsights')._build_logger_extra(message, extra)
    finally:
        if original is None:
            sys.modules.pop('functions_appinsights', None)
        else:
            sys.modules['functions_appinsights'] = original


def test_evidence_matching_fix_is_in_the_application_version():
    assert_app_version_at_least('0.261.191')


@pytest.mark.parametrize('chunk_text,quote,expected_text,tier', [
    pytest.param(
        '<table><tr><th>Region</th><th>Revenue</th></tr><tr><td>North</td><td>$1,200</td></tr></table>',
        'North $1,200', 'North</td><td>$1,200', 'normalized', id='html_table_cells_in_reading_order',
    ),
    pytest.param(
        '| Region | Revenue |\n| --- | ---: |\n| North | 1,200 |',
        'Region Revenue North 1,200', 'Region | Revenue |\n| --- | ---: |\n| North | 1,200',
        'normalized', id='markdown_table_with_rule_row',
    ),
    pytest.param(
        '## Revenue summary\n- North grew 12%\n- South fell 3%',
        'Revenue summary - North grew 12%', 'Revenue summary\n- North grew 12%',
        'normalized', id='heading_and_bullet_across_lines',
    ),
    pytest.param(
        'Share of cases\n>50% of\ncases', '>50% of cases', '>50% of\ncases',
        'normalized', id='comparison_symbol_across_line_break',
    ),
    pytest.param(
        '**Note**: the rate is 4%.', 'Note: the rate is 4%.', 'Note**: the rate is 4%.',
        'normalized', id='emphasis_marks_at_word_edges',
    ),
    pytest.param(
        'Use <b>bold</b>face type.', 'Use boldface type.', 'Use <b>bold</b>face type.',
        'normalized', id='inline_formatting_tag',
    ),
    pytest.param(
        'Menu of the cafe\u0301 costs 4.', 'caf\u00e9 costs 4', 'cafe\u0301 costs 4',
        'normalized', id='decomposed_accent',
    ),
    pytest.param(
        '\u0995\u09c7\u09be\u09a8\n\u09ac\u0987', '\u0995\u09cb\u09a8 \u09ac\u0987',
        '\u0995\u09c7\u09be\u09a8\n\u09ac\u0987', 'normalized', id='two_part_vowel_sign',
    ),
    pytest.param(
        '\u092c\u0947\u0915\u093e\u0930\n\u0939\u0948', '\u092c\u0947\u0915\u093e\u0930 \u0939\u0948',
        '\u092c\u0947\u0915\u093e\u0930\n\u0939\u0948', 'normalized', id='whole_words_with_vowel_signs',
    ),
    pytest.param(
        'Profit &amp; loss: 5&nbsp;% margin', 'Profit & loss: 5 % margin',
        'Profit &amp; loss: 5&nbsp;% margin', 'normalized', id='html_entities',
    ),
    pytest.param(
        'The \u201cnet\u201d margin rose 2\u20133 points.', 'The "net" margin rose 2-3 points.',
        'The \u201cnet\u201d margin rose 2\u20133 points.', 'normalized', id='typographic_quotes_and_dashes',
    ),
    pytest.param(
        'The \ufb01nal revenue was \uff14\uff15 units.', 'final revenue was 45 units',
        '\ufb01nal revenue was \uff14\uff15 units', 'normalized', id='compatibility_forms',
    ),
    pytest.param(
        'Total\u200b revenue\u00ad 4,500', 'Total revenue 4,500',
        'Total\u200b revenue\u00ad 4,500', 'normalized', id='invisible_characters',
    ),
    pytest.param(
        'Total   revenue\n\n  4,500 units', 'Total revenue 4,500',
        'Total   revenue\n\n  4,500', 'normalized', id='whitespace_and_line_breaks',
    ),
    pytest.param(
        'Revenue\n1,200. Costs fell.', 'Revenue 1,200', 'Revenue\n1,200',
        'normalized', id='number_before_sentence_period',
    ),
    pytest.param(
        'Values\n1.5, 2.5 and 3.5', 'Values 1.5', 'Values\n1.5', 'normalized', id='number_before_list_comma',
    ),
    pytest.param(
        'Total\n1\u202f200\u202f000 units', 'Total 1 200 000 units', 'Total\n1\u202f200\u202f000 units',
        'normalized', id='whole_number_with_grouping_spaces',
    ),
    pytest.param(
        'Harborview\nNational Bank\u2019s report', "Harborview National Bank's report",
        'Harborview\nNational Bank\u2019s report', 'normalized', id='whole_possessive',
    ),
    pytest.param(
        'They\ncan\u2019t renew the lease', "They can't renew", 'They\ncan\u2019t renew',
        'normalized', id='whole_contraction',
    ),
    pytest.param(
        'They can\u00b4t renew', "They can't renew", 'They can\u00b4t renew',
        'normalized', id='acute_accent_as_apostrophe',
    ),
    pytest.param(
        "Selon le rapport, l'augmentation\ndes prix", 'augmentation des prix', 'augmentation\ndes prix',
        'normalized', id='elided_prefix_left_out',
    ),
    pytest.param(
        'TOTAL REVENUE 4,500', 'Total revenue 4,500', 'TOTAL REVENUE 4,500',
        'normalized_casefold', id='case_only_difference',
    ),
    pytest.param(
        'Net revenue rose 4%.', '[Page 1, Chunk 1] Net revenue rose 4%.', 'Net revenue rose 4%.',
        'normalized', id='repeated_prompt_label',
    ),
    pytest.param(
        'There is a sole supplier for this service.', 'sole supplier', 'sole supplier',
        'exact', id='exact_quote',
    ),
])
def test_presentation_only_differences_locate_the_verbatim_source_span(chunk_text, quote, expected_text, tier):
    with document_analysis_runtime({}) as runtime:
        result = collect(runtime, window_chunks(chunk_text), supported_finding({'chunk_sequence': 1, 'quote': quote}))
    [candidate] = result['candidates']
    assert candidate['status'] == 'candidate'
    assert candidate['issues'] == []
    [passage] = result['evidence']
    location = passage['location']
    assert passage['text'] == expected_text
    assert chunk_text[location['start_char']:location['end_char']] == expected_text
    assert location['match'] == tier
    assert (location['chunk_id'], location['chunk_sequence'], location['page_number']) == ('chunk-1', 1, 1)
    assert candidate['evidence_refs'] == [passage['evidence_id']]
    assert result['evidence_matcher_version'] == 'evidence-matcher-v2'
    assert result['evidence_matching'] == match_counts(**{tier: 1})


@pytest.mark.parametrize('passage,reason', [
    pytest.param({'chunk_sequence': 3, 'quote': 'Early cancellation carries a penalty.'}, 'not_in_window', id='paraphrase'),
    pytest.param({'chunk_sequence': 3, 'quote': 'An exit penalty ... cancellation.'}, 'not_in_window', id='ellipsis'),
    pytest.param({'chunk_sequence': 3, 'quote': 'xit  penalty'}, 'not_in_window', id='partial_leading_word'),
    pytest.param({'chunk_sequence': 3, 'quote': 'exit  pen'}, 'not_in_window', id='partial_trailing_word'),
    pytest.param(
        {'page_number': 1, 'quote': 'for this service. There is a sole supplier'}, 'not_in_window',
        id='join_across_chunks',
    ),
    pytest.param({'page_number': 1, 'quote': 'sole supplier'}, 'ambiguous', id='same_passage_in_two_cited_chunks'),
    pytest.param({'chunk_sequence': 3, 'quote': 'sole supplier'}, 'not_in_cited_location', id='wrong_chunk'),
    pytest.param({'chunk_sequence': 9, 'quote': 'sole supplier'}, 'not_in_cited_location', id='chunk_outside_window'),
    pytest.param({'quote': 'sole supplier'}, 'missing_location', id='no_selector'),
    pytest.param({'chunk_sequence': 1, 'quote': '   '}, 'missing_quote', id='blank_quote'),
    pytest.param({'chunk_sequence': 1}, 'missing_quote', id='no_quote'),
    pytest.param({'chunk_sequence': 1, 'quote': '<td></td>'}, 'missing_quote', id='markup_only_quote'),
    pytest.param({'chunk_sequence': 1, 'quote': '[Page 1, Chunk 1]'}, 'missing_quote', id='label_only_quote'),
    pytest.param('sole supplier', 'missing_quote', id='passage_is_not_an_object'),
])
def test_unsupported_quotes_stay_unresolved_with_a_reason(passage, reason):
    chunks = window_chunks(
        'There is a sole supplier for this service.',
        'There is a sole supplier for this service.',
        'An exit penalty applies to early cancellation.',
        pages=[1, 1, 2],
    )
    with document_analysis_runtime({}) as runtime:
        result = collect(runtime, chunks, supported_finding(passage))
    [candidate] = result['candidates']
    assert candidate['status'] == 'unresolved'
    assert candidate['evidence_refs'] == []
    assert result['evidence'] == []
    unmatched = [issue for issue in candidate['issues'] if issue['code'] == 'unmatched_evidence']
    assert [issue['reason'] for issue in unmatched] == [reason]
    assert result['evidence_matching'] == match_counts(**{reason: 1})


@pytest.mark.parametrize('chunk_text,quote', [
    pytest.param('<table><tr><td>Units</td><td>1</td><td>200</td></tr></table>', 'Units 1200', id='table_cells_do_not_merge'),
    pytest.param('| Units | 1 | 200 |', 'Units 1200', id='pipe_cells_do_not_merge'),
    pytest.param('Units 1 200 in stock', 'Units 1200', id='spaced_digits_do_not_merge'),
    pytest.param('Sizes offered: 1, 200 and 300.', '1,200', id='list_is_not_a_thousands_value'),
    pytest.param('The contract is in valid form.', 'The contract is invalid', id='words_do_not_merge'),
    pytest.param('Population 10\u2076 people', 'Population 106 people', id='superscript_is_not_a_digit'),
    pytest.param('Population 10<sup>6</sup> people', 'Population 106 people', id='sup_tag_is_not_a_digit'),
    pytest.param('Risk share <50% of cases', '>50% of cases', id='greater_than_is_not_less_than'),
    pytest.param('Rate \u226450% of cases', '>50% of cases', id='greater_than_is_not_at_most'),
    pytest.param('Quarterly change\n\u2013 5% net', '+ 5% net', id='line_start_sign_is_kept'),
    pytest.param('\u25a1 Option A selected', '\u25a0 Option A selected', id='checkbox_state_is_kept'),
    pytest.param('Result 2*3 units', 'Result 23 units', id='joined_asterisk_is_kept'),
    pytest.param('Result 2 * 3 units', 'Result 2 3 units', id='standalone_asterisk_is_kept'),
    pytest.param('## Revenue summary\n- North grew 12%', 'Revenue summary North grew 12%', id='list_marker_is_kept'),
    pytest.param('The sepa\u00adrate  fee applies.', 'rate fee', id='soft_hyphen_partial_word'),
    pytest.param('<td>Total revenue</td><td>1,200,000</td>', 'Total revenue 1,200', id='truncated_number_in_table_cell'),
    pytest.param('| North | 1,200,000 |', 'North 1,200', id='truncated_number_in_pipe_row'),
    pytest.param('Revenue 1,200\nunits', '200 units', id='number_tail_after_grouping_comma'),
    pytest.param('Rate 0.5\npercent', '5 percent', id='decimal_tail'),
    pytest.param('Rate\n4.5%', 'Rate 4', id='decimal_head'),
    pytest.param('Rate\n4.5%', 'Rate 4.', id='quote_ends_on_decimal_point'),
    pytest.param('Rate 4.5%\nnow', '.5% now', id='quote_starts_on_decimal_point'),
    pytest.param('Total\n1\u202f200\u202f000', 'Total 1 200', id='narrow_no_break_space_grouping'),
    pytest.param('Total\n1&nbsp;200&nbsp;000', 'Total 1 200', id='no_break_space_entity_grouping'),
    pytest.param(
        '\u0661\u066c\u0662\u0660\u0660\u066c\u0660\u0660\u0660\n\u0648\u062d\u062f\u0629',
        '\u0662\u0660\u0660\u066c\u0660\u0660\u0660 \u0648\u062d\u062f\u0629', id='arabic_thousands_separator',
    ),
    pytest.param('Set snake_case_name\nnow', 'case_name now', id='identifier_tail'),
    pytest.param('Set\nsnake_case_name', 'Set snake', id='identifier_head'),
    pytest.param(
        '\u092c\u0947\u0915\u093e\u0930\n\u0939\u0948', '\u0915\u093e\u0930 \u0939\u0948',
        id='word_tail_after_vowel_sign',
    ),
    pytest.param(
        '\u092f\u094b\u091c\u0928\u093e\n\u0928\u093e\u0915\u093e\u092e', '\u092f\u094b\u091c\u0928\u093e \u0928\u093e\u0915',
        id='word_head_before_vowel_sign',
    ),
    pytest.param(
        '\u0643\u064e\u062a\u064e\u0628\u064e\n\u0632\u064a\u062f', '\u062a\u064e\u0628\u064e \u0632\u064a\u062f',
        id='word_tail_after_diacritic',
    ),
    pytest.param(
        '\u03c4\u03b1\u0390\u03b6\u03c9\n\u03c4\u03ce\u03c1\u03b1', '\u03b6\u03c9 \u03c4\u03ce\u03c1\u03b1',
        id='casefold_expansion_mark',
    ),
    pytest.param('\u0130stanbul\nport', 'STANBUL port', id='casefold_dotted_capital'),
    pytest.param("<td>Vendor</td><td>can't comply</td>", 'Vendor can', id='contraction_suffix_in_table_cell'),
    pytest.param("They\ncan't renew the lease", 'They can', id='contraction_suffix'),
    pytest.param('They\ncan\u2019t renew', 'They can', id='typographic_contraction_suffix'),
    pytest.param('They\ncan\u00b4t renew', 'They can', id='acute_accent_contraction_suffix'),
    pytest.param("The bid\nwon't be accepted", 'The bid won', id='negated_contraction_suffix'),
    pytest.param("They\ncan't renew", "They can'", id='quote_ends_on_apostrophe'),
    pytest.param("The\n1990's trend", 'The 1990', id='decade_suffix'),
    pytest.param('Harborview\nNational Bank\u2019s report', 'Harborview National Bank', id='possessive_suffix'),
])
def test_token_and_symbol_changes_are_not_presentation(chunk_text, quote):
    with document_analysis_runtime({}) as runtime:
        result = collect(runtime, window_chunks(chunk_text), supported_finding({'chunk_sequence': 1, 'quote': quote}))
    [candidate] = result['candidates']
    assert candidate['status'] == 'unresolved'
    assert result['evidence'] == []
    assert [issue.get('reason') for issue in candidate['issues']] == ['not_in_window']
    assert result['evidence_matching'] == match_counts(not_in_window=1)


def test_exact_offsets_are_unchanged_and_one_unsupported_passage_still_unresolves_the_finding():
    text = 'There is a sole supplier for this service. The contract names no alternative.'
    with document_analysis_runtime({}) as runtime:
        result = collect(runtime, window_chunks(text), supported_finding(
            {'chunk_sequence': 1, 'quote': 'sole supplier'},
            {'chunk_sequence': 1, 'quote': 'THE CONTRACT names  no alternative'},
            {'chunk_sequence': 1, 'quote': 'A second supplier is available.'},
        ))
    [candidate] = result['candidates']
    by_tier = {item['location']['match']: item for item in result['evidence']}
    exact = by_tier['exact']['location']
    assert (exact['start_char'], exact['end_char']) == (text.find('sole supplier'), text.find('sole supplier') + 13)
    assert by_tier['normalized_casefold']['text'] == 'The contract names no alternative'
    assert candidate['status'] == 'unresolved'
    assert [issue.get('reason') for issue in candidate['issues']] == ['not_in_window']
    assert result['evidence_matching'] == match_counts(exact=1, normalized_casefold=1, not_in_window=1)


def test_formatted_table_quote_finalizes_with_caveats_and_notes_outside_validation(monkeypatch):
    table = '<table><tr><th>Region</th><th>Revenue</th></tr><tr><td>North</td><td>$1,200</td></tr></table>'
    documents = {'revenue': original_document('revenue', [table])}
    caveat = 'The reporting period is not stated.'
    note = 'The table has no period column.'

    def response(prompt):
        assert f'[Page 1, Chunk 1] {table}' in prompt
        return json.dumps({
            'findings': [supported_finding(
                {'chunk_sequence': 1, 'quote': 'North $1,200'},
                finding_key='north_revenue', caveats=[caveat, f'  {caveat}  ', ''],
            )],
            'notes': [note, note, ' '],
        })

    with document_analysis_runtime(documents) as runtime:
        logs = capture_producer_logs(monkeypatch, runtime)
        result, client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
    assert len(client.calls) == 1
    validation = result['analysis_validation']
    assert validation['status'] == 'valid'
    assert validation['issues'] == []
    assert validation['unresolved_candidate_count'] == 0
    assert validation['evidence_matcher_version'] == 'evidence-matcher-v2'
    [record] = result['authoritative_result']['value']
    assert record['caveats'] == [caveat]
    [passage] = result['analysis_evidence']
    assert passage['text'] == 'North</td><td>$1,200'
    assert passage['location']['match'] == 'normalized'
    assert table[passage['location']['start_char']:passage['location']['end_char']] == passage['text']
    [noted] = result['analysis_diagnostics']['work_unit_notes']
    assert noted['notes'] == [note]
    assert noted['document_id'] == 'revenue'
    assert all('notes' not in unit for unit in validation['coverage']['work_units'])
    assert note not in json.dumps(validation)
    assert caveat not in json.dumps(validation)
    reply = result['analysis_reply']
    assert f'  Caveat: {caveat}' in reply
    assert f'## Analysis notes\n\n- revenue.txt, page 1: {note}' in reply
    assert '## Unresolved work' not in reply
    assert runtime.results.build_document_analysis_report(result) == reply
    [summary] = [entry for entry in logs if entry['message'] == SUMMARY_MESSAGE]
    assert summary['level'] == logging.INFO
    assert summary['extra']['validation_code'] == 'valid'
    assert summary['extra']['evidence_normalized_count'] == 1
    assert summary['extra']['caveat_count'] == summary['extra']['note_count'] == 1


def test_complementary_windows_union_caveats_without_unresolving_the_finding():
    documents = {'oversight': original_document('oversight', [
        'The service owner is Mira.',
        'Reviews take place every quarter.',
    ])}

    def response(prompt):
        payload = json.loads(extract_fixture_findings(prompt))
        payload['findings'][0]['caveats'] = (
            ['The year is not stated.', 'The team is not named.'] if '[Page 1, Chunk 1]' in prompt
            else ['The year is not stated.']
        )
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
    assert len(client.calls) == 2
    assert result['analysis_validation']['status'] == 'valid'
    [record] = result['authoritative_result']['value']
    assert record['values'] == {'owner': 'Mira', 'review_frequency': 'quarterly'}
    assert record['caveats'] == ['The team is not named.', 'The year is not stated.']
    assert result['analysis_reply'].count('Caveat: The year is not stated.') == 1


@pytest.mark.parametrize('uncertainty,code,records', [
    ('finding_issue', 'unresolved_finding', 0),
    ('window_issue', 'window_requirement_unresolved', 1),
    ('invalid_caveats', 'invalid_caveats', 0),
    ('invalid_caveat_item', 'invalid_caveats', 0),
])
def test_real_uncertainty_still_leaves_the_result_partial(uncertainty, code, records):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    private = 'Two different supplier names are given.'

    def response(prompt):
        payload = json.loads(extract_fixture_findings(prompt))
        finding = payload['findings'][0]
        if uncertainty == 'finding_issue':
            finding['issues'] = [private]
        elif uncertainty == 'window_issue':
            payload['issues'] = [private]
        elif uncertainty == 'invalid_caveats':
            finding['caveats'] = private
        else:
            finding['caveats'] = [private, 3]
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
    validation = result['analysis_validation']
    assert validation['status'] == 'partial'
    assert validation['coverage']['status'] == 'complete'
    assert code in {issue['code'] for issue in validation['issues']}
    assert len(result['authoritative_result']['value']) == records
    assert private not in json.dumps(validation)
    assert 'Unresolved work' in result['analysis_reply']


@pytest.mark.parametrize('notes', ['One note.', [1], [None], {'note': 'One note.'}])
def test_invalid_notes_are_an_invalid_window_response(notes):
    with document_analysis_runtime({}) as runtime:
        with pytest.raises(ValueError, match='notes'):
            collect(runtime, window_chunks('There is a sole supplier.'), notes=notes)
        accepted = collect(runtime, window_chunks('There is a sole supplier.'), notes=None)
    assert accepted['notes'] == []


def test_invalid_notes_fail_the_window_instead_of_being_ignored():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(
            lambda prompt: json.dumps({'findings': [], 'notes': 'Not a list.'}),
        ))
    assert result['analysis_validation']['status'] == 'invalid'
    assert result['coverage']['failed_windows'] == 1
    assert result['authoritative_result']['value'] == []


def test_validation_summary_log_counts_codes_without_model_text(monkeypatch):
    private = 'PRIVATE-MODEL-TEXT'
    documents = {'ledger': original_document('ledger', [
        '<table><tr><td>North</td><td>1,200</td></tr></table>',
        'There is a sole supplier for this service.',
    ])}

    def response(prompt):
        if '[Page 1, Chunk 1]' in prompt:
            return json.dumps({
                'findings': [supported_finding(
                    {'chunk_sequence': 1, 'quote': 'North 1,200'},
                    finding_key='north_total', caveats=[f'{private}: the unit is not stated.'],
                )],
                'notes': [f'{private}: the table has no period column.'],
            })
        return json.dumps({
            'findings': [
                supported_finding({'chunk_sequence': 2, 'quote': 'sole supplier'}, finding_key='supplier'),
                supported_finding(
                    {'chunk_sequence': 2, 'quote': f'{private} paraphrase'},
                    finding_key='unsupported', issues=[f'{private}: conflicting totals.'],
                ),
            ],
            'issues': [f'{private}: requirement.'],
        })

    with document_analysis_runtime(documents) as runtime:
        logs = capture_producer_logs(monkeypatch, runtime)
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
    assert result['analysis_validation']['status'] == 'partial'
    [summary] = [entry for entry in logs if entry['message'] == SUMMARY_MESSAGE]
    expected = {
        'validation_code': 'partial',
        'finalized_record_count': 2,
        'unresolved_candidate_count': 1,
        'candidate_count': 3,
        'window_count': 2,
        'completed_window_count': 2,
        'failed_window_count': 0,
        'pending_window_count': 0,
        'reused_window_count': 0,
        'caveat_count': 1,
        'note_count': 1,
        **{f'evidence_{name}_count': 0 for name in MATCH_COUNT_NAMES},
        'evidence_exact_count': 1,
        'evidence_normalized_count': 1,
        'evidence_not_in_window_count': 1,
        # The unsupported finding has no located passage, so finalization also flags its reference.
        'issue_invalid_evidence_reference_count': 1,
        'issue_unmatched_evidence_count': 1,
        'issue_unresolved_finding_count': 1,
        'issue_window_requirement_unresolved_count': 1,
    }
    assert summary['extra'] == expected
    assert summary['level'] == logging.WARNING
    assert private not in json.dumps(logs, default=str)
    # Every field must survive the production allowlist as itself, not collapse to a presence flag.
    properties = real_logger_extra(summary['message'], summary['extra'])
    assert {key: properties.get(f'sc_{key}') for key in expected} == expected


def test_validation_summary_correlates_by_conversation_hash_only(monkeypatch):
    conversation_id = 'conversation-private-1540'
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        logs = capture_producer_logs(monkeypatch, runtime)
        run_analysis(runtime, documents, conversation_id=conversation_id)
    [summary] = [entry for entry in logs if entry['message'] == SUMMARY_MESSAGE]
    expected_hash = hashlib.sha256(conversation_id.encode('utf-8')).hexdigest()
    assert summary['extra']['conversation_id_hash'] == expected_hash
    assert conversation_id not in json.dumps(summary, default=str)
    properties = real_logger_extra(summary['message'], summary['extra'])
    assert properties.get('sc_conversation_id_hash') == expected_hash
    assert conversation_id not in json.dumps(properties, default=str)


def test_window_prompt_scopes_each_slice_to_its_own_contribution():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        _result, client = run_analysis(
            runtime, documents, analysis_prompt='Compare the narrative budget with the ledger dataset.',
        )
    raw_prompt = client.calls[0]['prompt']
    prompt = ' '.join(raw_prompt.split())
    for guidance in (
        'optional top-level "issues" and "notes" lists',
        'Other slices, files and datasets in the task are analyzed separately and combined afterwards',
        'Do not compare it with another source, and do not decide whether other slices or sources are missing',
        'a short, contiguous passage copied from that one chunk',
        'keeping its words, numbers, signs and symbols as written',
        'Do not paraphrase, summarize, use ellipses or join text from different chunks',
        '"caveats": optional qualifications that do not stop the values being final',
        'Values absent from this slice are not issues',
        'put other observations about the slice in "notes"',
    ):
        assert guidance in prompt, guidance
    assert len(raw_prompt) < 4000
