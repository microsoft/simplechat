# functions_document_analysis_results.py
"""Pure candidate collection and presentation for the built-in Analyze result."""

import hashlib
import html
import json
import re
import unicodedata
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable, analysis_source_snapshot
from functions_analysis_deliverables import apply_analysis_calculations
from functions_tabular_transformations import normalize_tabular_transformation_spec


ANALYSIS_RESULT_VERSION = 'analyze-final-v1'
ANALYSIS_OPTIONS_VERSION = 'analysis-options-v1'
EVIDENCE_MATCHER_VERSION = 'evidence-matcher-v2'
EVIDENCE_MATCH_TIERS = ('exact', 'normalized', 'normalized_casefold')
EVIDENCE_MISS_REASONS = ('missing_quote', 'missing_location', 'ambiguous', 'not_in_cited_location', 'not_in_window')
_EVIDENCE_SELECTORS = ('chunk_sequence', 'page_number', 'chunk_id')
_EVIDENCE_MARKUP = re.compile(r'<!--.*?-->|</?([A-Za-z][A-Za-z0-9:-]*)(?:[\s/][^<>]*)?>', re.DOTALL)
_EVIDENCE_LINE = re.compile(r'[^\n]+')
# Inline formatting renders no gap. Every other tag, comment or table rule separates words.
_EVIDENCE_INLINE_TAGS = frozenset((
    'a', 'abbr', 'b', 'bdi', 'bdo', 'big', 'cite', 'code', 'data', 'del', 'dfn', 'em', 'font', 'i', 'ins',
    'kbd', 'mark', 'q', 's', 'samp', 'small', 'span', 'strike', 'strong', 'time', 'tt', 'u', 'var', 'wbr',
))
_EVIDENCE_ENTITY = re.compile(r'&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')
# The window prompt labels each chunk this way; a quote may repeat the label.
_EVIDENCE_PROMPT_LABEL = re.compile(
    r'\s*\[(?:Page [^\[\],]{1,64}(?:, Chunk [^\[\]]{1,64})?|Chunk [^\[\]]{1,64})\]\s*'
)
_EVIDENCE_INVISIBLE = frozenset(
    '\u00ad\u061c\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\u2066\u2067\u2068\u2069\ufeff'
)
_EVIDENCE_EMPHASIS = frozenset('*_`')
# Digits joined by one of these, or by a single no-break or thin space, are one number, for example
# 1,200,000, 4.5, 1'200 or 1 200 000.
_EVIDENCE_NUMBER_JOINERS = frozenset(",.'\u066b\u066c")
_EVIDENCE_GROUPING_SPACES = frozenset('\u00a0\u2007\u2009\u202f')
# Plain equivalents of these compatibility forms would change a value, for example 10⁶ to 106.
_EVIDENCE_KEPT_FORMS = ('<super>', '<sub>', '<fraction>', '<circle>', '<square>')
_EVIDENCE_FOLDS = str.maketrans({
    **dict.fromkeys('\u00b4\u2018\u2019\u201a\u201b\u2032', "'"),
    **dict.fromkeys('\u201c\u201d\u201e\u201f\u2033', '"'),
    **dict.fromkeys('\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d', '-'),
})


def normalize_analysis_options(analysis_options=None, transformation_spec=None):
    """Keep ordinary narrative simple; accept only explicitly supported requirements."""
    options = {} if analysis_options is None else deepcopy(analysis_options)
    if not isinstance(options, dict) or set(options) - {
        'version', 'mode', 'required_fields', 'transformation_spec',
    }:
        raise ValueError('Unsupported analysis options. Declare required field names or supported calculation rules.')
    if options.get('version', ANALYSIS_OPTIONS_VERSION) != ANALYSIS_OPTIONS_VERSION:
        raise ValueError('Unsupported analysis options version.')
    if options.get('mode', 'narrative_findings') != 'narrative_findings':
        raise ValueError('This Analyze path supports narrative findings, not a required row cardinality or custom schema.')
    fields = options.get('required_fields', [])
    if (
        not isinstance(fields, list) or len(fields) > 200
        or any(not isinstance(field, str) or not field.strip() or len(field) > 128 for field in fields)
        or len({field.strip() for field in fields}) != len(fields)
    ):
        raise ValueError('Required analysis fields must be a unique list of at most 200 nonempty field names.')
    supplied_spec = options.get('transformation_spec')
    if supplied_spec is not None and not isinstance(supplied_spec, dict):
        raise ValueError('Explicit analysis calculation rules must be a supported rule object.')
    if transformation_spec is not None:
        if not isinstance(transformation_spec, dict):
            raise ValueError('Explicit analysis calculation rules must be a supported rule object.')
        normalized_explicit = normalize_tabular_transformation_spec(transformation_spec)
        if supplied_spec is not None and normalize_tabular_transformation_spec(supplied_spec) != normalized_explicit:
            raise ValueError('Conflicting explicit analysis calculation rules were supplied.')
        supplied_spec = transformation_spec
    normalized_spec = normalize_tabular_transformation_spec(supplied_spec)
    return {
        'version': ANALYSIS_OPTIONS_VERSION,
        'mode': 'narrative_findings',
        'required_fields': [field.strip() for field in fields],
        'transformation_spec': normalized_spec,
    }


def apply_document_analysis_options(result, analysis_options):
    """Apply declared rules before any presentation; rejected values stay non-authoritative."""
    options = normalize_analysis_options(analysis_options)
    if not options['required_fields'] and not options['transformation_spec']:
        return result
    validation = result['analysis_validation']
    diagnostics = result['analysis_diagnostics']
    calculation = apply_analysis_calculations(
        _final_records(result), options['transformation_spec'],
    )
    accepted = []
    rejected = deepcopy(calculation['rejected_records'])
    safe_issues = []
    messages = {
        'analysis_calculation_value_corrected': 'A reported value was replaced by the declared calculation.',
        'analysis_calculation_failed': 'A finding could not satisfy its declared calculation and was excluded.',
        'analysis_calculation_record_invalid': 'A finding had invalid calculation inputs and was excluded.',
        'analysis_calculation_spec_invalid': 'The declared calculation rules could not be validated.',
    }
    for issue in calculation['issues']:
        safe_issues.append({
            **{key: issue[key] for key in ('code', 'record_id', 'document_id', 'field') if key in issue},
            'message': messages[issue['code']],
        })
    for record in calculation['accepted_records']:
        missing = [field for field in options['required_fields'] if field not in record['values']]
        if missing:
            rejected.append({
                'record_id': record['record_id'], 'document_id': record['document_id'],
                'source': deepcopy(record['source']), 'evidence_refs': list(record['evidence_refs']),
                'issue_codes': ['analysis_required_field_missing'], 'fields': missing,
            })
            safe_issues.extend({
                'code': 'analysis_required_field_missing', 'record_id': record['record_id'],
                'document_id': record['document_id'], 'field': field,
                'message': 'A finding is missing an explicitly required field and was excluded.',
            } for field in missing)
        else:
            accepted.append(record)
    result['authoritative_result']['value'] = accepted
    diagnostics['calculations'] = {
        'issues': calculation['issues'], 'rejected_records': rejected,
    }
    validation['issues'].extend(safe_issues)
    validation['finalized_record_count'] = len(accepted)
    validation['rejected_record_count'] = len(rejected)
    if rejected or any(issue['code'] == 'analysis_calculation_spec_invalid' for issue in calculation['issues']):
        validation['status'] = 'partial' if accepted else 'invalid'
    deterministic = bool(options['transformation_spec'].get('deterministic_field_order'))
    for check in validation['checks']:
        if check['name'] == 'mathematical_correctness' and deterministic:
            check['name'] = 'declared_calculations'
            check['status'] = (
                'failed' if calculation['rejected_records']
                else 'passed' if accepted else 'not_applicable'
            )
        elif check['name'] == 'requested_field_completeness' and options['required_fields']:
            check['status'] = (
                'failed' if any('analysis_required_field_missing' in item['issue_codes'] for item in rejected)
                else 'passed' if accepted else 'not_applicable'
            )
    if deterministic:
        validation['limitations'] = [
            item for item in validation['limitations']
            if item != 'Calculations, scoring rules and derived values have not been independently verified.'
        ]
        validation['limitations'].append(
            'Only explicitly declared calculations were checked. Model judgments, numeric prose, and undeclared rules were not independently verified.'
        )
    if options['required_fields']:
        validation['limitations'].append(
            'Required-field checks establish field presence only, not correct types, non-null values, factual accuracy, or a complete set of findings.'
        )
    return result


def _identity(kind, value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return f'{kind}-{hashlib.sha256(encoded.encode("utf-8")).hexdigest()}'


def _chunk_content(chunk):
    return {
        'chunk_id': chunk.get('id') or chunk.get('chunk_id'),
        'chunk_sequence': chunk.get('chunk_sequence'),
        'page_number': chunk.get('page_number'),
        'text': str(chunk.get('chunk_text') or ''),
    }


def get_unassigned_analysis_chunks(chunks, windows):
    """Find original chunks omitted by a page-based window (for example, unpaged text)."""
    assigned = {
        _identity('chunk', _chunk_content(chunk))
        for window in windows for chunk in window.get('chunks', [])
    }
    return [chunk for chunk in chunks if _identity('chunk', _chunk_content(chunk)) not in assigned]


def index_analysis_source_manifest(source_manifest, document_ids):
    """Select assigned snapshots; they do not replace the normal source access check."""
    if source_manifest is None:
        return None
    if not isinstance(source_manifest, list):
        raise AnalysisResultUnavailable('analysis_source_manifest_invalid')
    assigned_ids = set(document_ids)
    snapshots = {}
    for source in source_manifest:
        if not isinstance(source, dict) or not isinstance(source.get('document_id'), str):
            raise AnalysisResultUnavailable('analysis_source_manifest_invalid')
        if source['document_id'].strip() not in assigned_ids:
            continue
        if 'authorization_status' in source and source['authorization_status'] != 'authorized':
            raise AnalysisResultUnavailable('analysis_source_manifest_invalid')
        snapshot = analysis_source_snapshot([source])[0]
        previous = snapshots.get(snapshot['document_id'])
        if previous is not None and previous != snapshot:
            raise AnalysisResultUnavailable('analysis_source_manifest_conflict')
        snapshots[snapshot['document_id']] = snapshot
    if set(snapshots) != assigned_ids:
        raise AnalysisResultUnavailable('analysis_source_manifest_missing')
    return snapshots


def build_analysis_source(document_id, document_payload, source_snapshot=None):
    """Bind retrieved content to optional outer metadata; final ACL/revision checks stay with the caller."""
    document = document_payload.get('document') or {}
    file_name = (
        str(document.get('file_name') or '').strip()
        or str(document.get('title') or '').strip()
        or str(document_id)
    )
    content_fingerprint = _identity('sha256', [
        _chunk_content(chunk) for chunk in document_payload.get('chunks', [])
    ])
    source = {
        'document_id': document_id,
        'scope': document_payload.get('scope'),
        'scope_id': document_payload.get('scope_id'),
        'file_name': file_name,
        'source_version': document.get('version'),
        'source_revision': content_fingerprint,
    }
    if source_snapshot is not None:
        if any(source[field] != source_snapshot[field] for field in ('document_id', 'scope', 'scope_id')):
            raise AnalysisResultUnavailable('analysis_source_manifest_changed')
        retrieved_revision = document.get('_etag') or document.get('updated_at') or document.get('last_updated')
        for retrieved, expected in (
            (document.get('version'), source_snapshot.get('source_version')),
            (retrieved_revision, source_snapshot.get('source_revision')),
        ):
            if retrieved is not None and expected is not None and str(retrieved) != str(expected):
                raise AnalysisResultUnavailable('analysis_source_snapshot_changed')
        source.update({
            'source_version': source_snapshot.get('source_version'),
            'source_revision': source_snapshot.get('source_revision'),
            'content_fingerprint': content_fingerprint,
        })
        if 'content_sha256' in source_snapshot:
            source['content_sha256'] = source_snapshot['content_sha256']
    return source


def build_analysis_work_unit(source, window_payload, window_range, analysis_prompt=None, analysis_options=None):
    """Retries of the same source slice share an identity, not an attempt number."""
    content = [_chunk_content(chunk) for chunk in window_payload.get('chunks', [])]
    return {
        'work_unit_id': _identity('window', [source, content, str(analysis_prompt or ''), analysis_options]),
        'document_id': source['document_id'],
        'source': deepcopy(source),
        'window_range': deepcopy(window_range),
        'status': 'pending',
        'candidate_count': 0,
        'issues': [],
    }


def _reject_json_constant(value):
    raise ValueError('Non-finite JSON values are not supported.')


def _unique_json_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON fields are not supported.')
        value[key] = item
    return value


def _issue(code, message, **context):
    return {'code': code, 'message': message, **context}


def _public_issue(issue):
    public = {
        key: deepcopy(issue[key])
        for key in ('code', 'message', 'record_id', 'document_id', 'work_unit_id', 'field', 'fields')
        if key in issue
    }
    if issue['code'] == 'unresolved_finding':
        public['message'] = 'A source slice did not support a final conclusion; its details remain in diagnostics.'
    elif issue['code'] == 'window_requirement_unresolved':
        public['message'] = 'A source window reported an unresolved task requirement; review its details in diagnostics.'
    return public


def _evidence_word_character(character):
    """Letters, digits, combining marks such as vowel signs, and connectors such as _ continue a word."""
    category = unicodedata.category(character)
    return character.isalnum() or category[0] == 'M' or category == 'Pc'


def _evidence_markup(text):
    """Presentation markup as (start, end, separates): tags, comments and table rule lines."""
    spans = [
        (match.start(), match.end(), (match.group(1) or '').lower() not in _EVIDENCE_INLINE_TAGS)
        for match in _EVIDENCE_MARKUP.finditer(text)
    ]
    for line in _EVIDENCE_LINE.finditer(text):
        content = line.group(0).strip()
        if (
            content and '-' in content and not content.strip('|:- \t')
            and ('|' in content or content.count('-') >= 3)
        ):
            spans.append((line.start(), line.end(), True))
    merged = []
    for start, end, separates in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = merged[-1][2] or separates
        else:
            merged.append([start, end, separates])
    return merged


def _evidence_form(text):
    """Return comparable characters, each mapped to the original span it came from.

    Words and numbers keep their boundaries: whitespace, table pipes, rule lines, comments and
    structural tags become one space. Only marks that render as nothing are dropped, and nothing
    written in the text, such as a sign, bullet or comparison symbol, is removed.
    """
    units = []

    def add(character, start, end):
        character = character.translate(_EVIDENCE_FOLDS)
        if character in _EVIDENCE_INVISIBLE:
            return
        # Marks, including vowel signs with no combining class, stay with their base character.
        if units and units[-1][0] == 'text' and unicodedata.category(character)[0] == 'M':
            units[-1][1] += character
            units[-1][3] = end
        else:
            units.append(['text', character, start, end])

    position = 0
    for start, end, separates in [*_evidence_markup(text), (len(text), len(text), False)]:
        if start > position:
            index = position
            # Entities are decoded only after markup removal, so escaped text never becomes markup.
            for entity in _EVIDENCE_ENTITY.finditer(text, position, start):
                for offset in range(index, entity.start()):
                    add(text[offset], offset, offset + 1)
                value = html.unescape(entity.group(0))
                if value == entity.group(0):
                    for offset in range(entity.start(), entity.end()):
                        add(text[offset], offset, offset + 1)
                else:
                    for character in value:
                        add(character, entity.start(), entity.end())
                index = entity.end()
            for offset in range(index, start):
                add(text[offset], offset, offset + 1)
        if separates:
            units.append(['gap', ' ', start, end])
        position = max(position, end)

    items = []
    for kind, characters, start, end in units:
        if kind == 'text' and not characters.isascii():
            kept = any(
                unicodedata.decomposition(character).startswith(_EVIDENCE_KEPT_FORMS)
                for character in characters
            )
            characters = unicodedata.normalize('NFC' if kept else 'NFKC', characters).translate(_EVIDENCE_FOLDS)
        for character in characters:
            if kind == 'gap' or character.isspace() or character == '|':
                items.append(('gap', ' ', start, end))
            elif character in _EVIDENCE_EMPHASIS:
                items.append(('mark', character, start, end))
            elif character not in _EVIDENCE_INVISIBLE:
                items.append(('char', character, start, end))

    characters = []
    spans = []
    gap = None

    def emit(character, start, end):
        if gap is not None and characters:
            characters.append(' ')
            spans.append(gap)
        characters.append(character)
        spans.append((start, end))

    index = 0
    while index < len(items):
        kind, character, start, end = items[index]
        if kind == 'gap':
            gap = (start, end) if gap is None else (gap[0], end)
            index += 1
            continue
        if kind == 'char':
            emit(character, start, end)
            gap = None
            index += 1
            continue
        run_end = index
        while run_end < len(items) and items[run_end][0] == 'mark':
            run_end += 1
        before = items[index - 1] if index else None
        after = items[run_end] if run_end < len(items) else None
        # Emphasis and code marks at a word edge render as nothing. Marks standing alone or
        # between two letters or digits are written text, for example 2 * 3, 2*3 or snake_case.
        standalone = (before is None or before[0] == 'gap') and (after is None or after[0] == 'gap')
        joined = (
            before is not None and after is not None and before[0] == 'char' and after[0] == 'char'
            and _evidence_word_character(before[1]) and _evidence_word_character(after[1])
        )
        if standalone or joined:
            for _, mark, mark_start, mark_end in items[index:run_end]:
                emit(mark, mark_start, mark_end)
                gap = None
        index = run_end
    return ''.join(characters), spans


def _evidence_forms(text):
    normalized, spans = _evidence_form(text)
    folded = normalized.casefold()
    if len(folded) != len(normalized):
        folded_spans = [span for character, span in zip(normalized, spans) for _ in character.casefold()]
    else:
        folded_spans = spans
    return {'normalized': (normalized, spans), 'normalized_casefold': (folded, folded_spans)}


def _evidence_joined(form, text, position):
    """What comparable position joins into one token with its neighbours: 'number', 'word' or None."""
    comparable, spans = form
    if position <= 0 or position + 1 >= len(comparable):
        return None
    before, character, after = comparable[position - 1:position + 2]
    if before.isdecimal() and after.isdecimal():
        start, end = spans[position]
        if character in _EVIDENCE_NUMBER_JOINERS or (
            character == ' ' and html.unescape(text[start:end]) in _EVIDENCE_GROUPING_SPACES
        ):
            return 'number'
    if character == "'" and _evidence_word_character(before) and _evidence_word_character(after):
        return 'word'
    return None


def _evidence_edge_allowed(form, text, index, closing):
    """Whether a match may start, or when closing end, between comparable positions index - 1 and index."""
    comparable, spans = form
    if index <= 0 or index >= len(comparable):
        return True
    if spans[index - 1] == spans[index]:
        return False
    if _evidence_word_character(comparable[index - 1]) and _evidence_word_character(comparable[index]):
        return False
    # Numbers are never split. A match may leave out an elided prefix such as the l' of
    # l'augmentation, but it never ends before a suffix such as the 't of can't.
    blocked = ('number', 'word') if closing else ('number',)
    return not any(_evidence_joined(form, text, position) in blocked for position in (index - 1, index))


def _evidence_occurrence(form, needle, text):
    """First occurrence covering whole original characters, never starting or ending inside a word or number."""
    comparable, spans = form
    position = comparable.find(needle)
    while position >= 0:
        end = position + len(needle)
        if (
            _evidence_edge_allowed(form, text, position, closing=False)
            and _evidence_edge_allowed(form, text, end, closing=True)
        ):
            return spans[position][0], spans[end - 1][1]
        position = comparable.find(needle, position + 1)
    return None


def _locate_analysis_evidence(passage, contents, forms):
    """Locate a cited passage in exactly one cited chunk, or return why it was not accepted."""
    quote = passage.get('quote')
    if not isinstance(quote, str) or not quote.strip():
        return None, 'missing_quote'
    label = _EVIDENCE_PROMPT_LABEL.match(quote)
    needles = {
        tier: form[0]
        for tier, form in _evidence_forms(quote[label.end():] if label else quote).items()
    }
    if not needles['normalized']:
        return None, 'missing_quote'
    if not any(passage.get(key) is not None for key in _EVIDENCE_SELECTORS):
        return None, 'missing_location'

    def occurrence(index, tier):
        text = contents[index]['text']
        if tier == 'exact':
            offset = text.find(quote)
            return (offset, offset + len(quote)) if offset >= 0 else None
        if index not in forms:
            forms[index] = _evidence_forms(text)
        return _evidence_occurrence(forms[index][tier], needles[tier], text)

    selected = {
        index for index, content in enumerate(contents)
        if all(
            passage.get(key) is None or str(passage[key]) == str(content.get(key))
            for key in _EVIDENCE_SELECTORS
        )
    }
    for tier in EVIDENCE_MATCH_TIERS:
        hits = [
            (index, span) for index in sorted(selected)
            for span in [occurrence(index, tier)] if span is not None
        ]
        if len(hits) > 1:
            return None, 'ambiguous'
        if hits:
            index, (start, end) = hits[0]
            return (contents[index], start, end, tier), None
    # Diagnostics only: a quote found under another chunk still fails its citation.
    if any(
        occurrence(index, tier) is not None
        for index in range(len(contents)) if index not in selected
        for tier in EVIDENCE_MATCH_TIERS
    ):
        return None, 'not_in_cited_location'
    return None, 'not_in_window'


def collect_analysis_window_candidates(analysis_text, source, work_unit, window_payload):
    """Check an extraction response against its assigned original source window."""
    cleaned = str(analysis_text or '').strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1)
    payload = json.loads(cleaned, parse_constant=_reject_json_constant, object_pairs_hook=_unique_json_keys)
    if not isinstance(payload, dict) or not isinstance(payload.get('findings'), list):
        raise ValueError('The analysis response must contain a findings list.')
    # Also catches exponent overflow (for example 1e999), not only JSON NaN literals.
    _identity('response', payload)
    window_issues = payload.get('issues', [])
    if not isinstance(window_issues, list) or any(not isinstance(item, str) for item in window_issues):
        raise ValueError('Analysis issues must be a list of text descriptions.')
    window_notes = payload.get('notes')
    window_notes = [] if window_notes is None else window_notes
    if not isinstance(window_notes, list) or any(not isinstance(item, str) for item in window_notes):
        raise ValueError('Analysis notes must be a list of text descriptions.')

    contents = [_chunk_content(chunk) for chunk in window_payload.get('chunks', [])]
    comparison_forms = {}
    matching = dict.fromkeys((*EVIDENCE_MATCH_TIERS, *EVIDENCE_MISS_REASONS), 0)
    candidates = []
    evidence = {}
    for index, finding in enumerate(payload['findings']):
        finding = finding if isinstance(finding, dict) else {}
        finding_key = finding.get('finding_key')
        values = finding.get('values')
        issues = []
        if not isinstance(finding_key, str) or not finding_key.strip():
            issues.append(_issue('invalid_identity', 'A finding is missing its source-local identity.'))
            finding_key = f'unresolved-{work_unit["work_unit_id"]}-{index}'
        if not isinstance(values, dict) or not values:
            issues.append(_issue('invalid_values', 'A finding did not supply an object of requested values.'))
            values = {}
        if finding.get('status') != 'supported':
            issues.append(_issue('unresolved_finding', 'The source slice did not support a final conclusion.'))
        finding_issues = finding.get('issues', [])
        if not isinstance(finding_issues, list) or any(not isinstance(item, str) for item in finding_issues):
            issues.append(_issue('invalid_issues', 'A finding supplied an invalid uncertainty description.'))
        else:
            issues.extend(_issue('unresolved_finding', item) for item in finding_issues if item.strip())
        caveats = finding.get('caveats')
        caveats = [] if caveats is None else caveats
        if not isinstance(caveats, list) or any(not isinstance(item, str) for item in caveats):
            issues.append(_issue('invalid_caveats', 'A finding supplied an invalid caveat description.'))
            caveats = []
        caveats = sorted({item.strip() for item in caveats if item.strip()})

        evidence_refs = []
        passages = finding.get('evidence')
        if not isinstance(passages, list) or not passages:
            issues.append(_issue('missing_evidence', 'A finding has no supporting source passage.'))
            passages = []
        for passage in passages:
            located, reason = _locate_analysis_evidence(
                passage if isinstance(passage, dict) else {}, contents, comparison_forms,
            )
            if located is None:
                matching[reason] += 1
                issues.append(_issue(
                    'unmatched_evidence',
                    'A supporting passage could not be located uniquely in the assigned source window.',
                    reason=reason,
                ))
                continue
            content, start, end, tier = located
            matching[tier] += 1
            location = {
                'chunk_id': content['chunk_id'],
                'chunk_sequence': content['chunk_sequence'],
                'page_number': content['page_number'],
                'start_char': start,
                'end_char': end,
                'match': tier,
            }
            # Keep the verbatim source span, never the model's wording of it.
            text = content['text'][start:end]
            evidence_id = _identity('evidence', [source, location, text])
            evidence[evidence_id] = {
                'evidence_id': evidence_id,
                'document_id': source['document_id'],
                'source': deepcopy(source),
                'work_unit_ids': [work_unit['work_unit_id']],
                'location': location,
                'text': text,
            }
            evidence_refs.append(evidence_id)

        candidate = {
            'record_id': _identity('record', [source, finding_key.strip()]),
            'document_id': source['document_id'],
            'source': deepcopy(source),
            'work_unit_id': work_unit['work_unit_id'],
            'finding_key': finding_key.strip(),
            'values': deepcopy(values),
            'evidence_refs': sorted(set(evidence_refs)),
            'status': 'candidate' if not issues else 'unresolved',
            'issues': issues,
        }
        if caveats:
            candidate['caveats'] = caveats
        candidate['candidate_id'] = _identity('candidate', candidate)
        candidates.append(candidate)

    return {
        'candidates': candidates,
        'evidence': list(evidence.values()),
        'issues': [
            _issue('window_requirement_unresolved', text, work_unit_id=work_unit['work_unit_id'],
                   document_id=source['document_id'])
            for text in window_issues if text.strip()
        ],
        'notes': list(dict.fromkeys(text.strip() for text in window_notes if text.strip())),
        'evidence_matcher_version': EVIDENCE_MATCHER_VERSION,
        'evidence_matching': matching,
    }


def _merge_complementary_values(target, incoming, path=''):
    conflicts = []
    for key, value in incoming.items():
        field_path = f'{path}.{key}' if path else key
        if key not in target:
            target[key] = deepcopy(value)
        elif isinstance(target[key], dict) and isinstance(value, dict):
            conflicts.extend(_merge_complementary_values(target[key], value, field_path))
        elif _identity('value', target[key]) != _identity('value', value):
            # Different lists, nulls and numeric types are not silently reconciled.
            conflicts.append(field_path)
    return conflicts


def finalize_document_analysis_result(sources, work_units, candidates, evidence):
    """Accept only locally checked, conflict-free candidates; never rewrite them."""
    unit_versions = {}
    for unit in work_units:
        unit_versions.setdefault(unit['work_unit_id'], {})[_identity('unit', unit)] = unit
    units = {}
    for work_unit_id, versions in unit_versions.items():
        retained = deepcopy(versions[sorted(versions)[0]])
        if len(versions) > 1:
            retained['status'] = 'failed'
            retained['issues'].append(_issue(
                'work_unit_replay_conflict', 'Replayed source-window outcomes disagree.',
                work_unit_id=work_unit_id, document_id=retained['document_id'],
            ))
        units[work_unit_id] = retained
    evidence_by_id = {}
    for item in evidence:
        expected_id = _identity('evidence', [item['source'], item['location'], item['text']])
        if item['evidence_id'] != expected_id:
            continue
        retained = evidence_by_id.setdefault(expected_id, deepcopy(item))
        retained['work_unit_ids'] = sorted(set(retained['work_unit_ids'] + item['work_unit_ids']))
    unique_candidates = {}
    candidate_replays = {}
    for candidate in candidates:
        original = {key: value for key, value in candidate.items() if key not in {'resolution', 'resolution_issues'}}
        fingerprint = _identity('payload', original)
        unique_candidates[fingerprint] = deepcopy(original)
        candidate_replays.setdefault(candidate['candidate_id'], set()).add(fingerprint)

    grouped = {}
    for candidate in unique_candidates.values():
        candidate['resolution_issues'] = []
        unit = units.get(candidate['work_unit_id'])
        if not unit or unit['status'] != 'completed' or unit['source'] != candidate['source']:
            candidate['resolution_issues'].append(_issue('unassigned_candidate', 'A finding has no completed assigned source window.'))
        if len(candidate_replays[candidate['candidate_id']]) > 1:
            candidate['resolution_issues'].append(_issue('candidate_replay_conflict', 'Replayed candidate identities disagree.'))
        if not candidate['evidence_refs'] or any(
            ref not in evidence_by_id or evidence_by_id[ref]['source'] != candidate['source']
            or candidate['work_unit_id'] not in evidence_by_id[ref]['work_unit_ids']
            for ref in candidate['evidence_refs']
        ):
            candidate['resolution_issues'].append(_issue('invalid_evidence_reference', 'A finding has unavailable source evidence.'))
        grouped.setdefault(candidate['record_id'], []).append(candidate)

    records = []
    issues = [deepcopy(issue) for unit in units.values() for issue in unit.get('issues', [])]
    for record_id, group in sorted(grouped.items()):
        values = {}
        conflicts = set()
        for candidate in group:
            conflicts.update(_merge_complementary_values(values, candidate['values']))
        unresolved = conflicts or any(
            item['status'] != 'candidate' or item['issues'] or item['resolution_issues'] for item in group
        )
        if conflicts:
            issues.append(_issue(
                'conflicting_values', 'Source windows disagree on values; this finding remains unresolved.',
                record_id=record_id, document_id=group[0]['document_id'], fields=sorted(conflicts),
            ))
        for candidate in group:
            candidate['resolution'] = 'unresolved' if unresolved else 'accepted'
            issues.extend(
                {**issue, 'record_id': record_id, 'document_id': candidate['document_id'],
                 'work_unit_id': candidate['work_unit_id']}
                for issue in candidate['issues'] + candidate['resolution_issues']
            )
        if not unresolved:
            record = {
                'record_id': record_id,
                'document_id': group[0]['document_id'],
                'source': deepcopy(group[0]['source']),
                'values': values,
                'evidence_refs': sorted({ref for candidate in group for ref in candidate['evidence_refs']}),
            }
            caveats = sorted({caveat for candidate in group for caveat in candidate.get('caveats', [])})
            if caveats:
                record['caveats'] = caveats
            records.append(record)

    source_order = {source['document_id']: index for index, source in enumerate(sources)}
    records.sort(key=lambda item: (source_order[item['document_id']], item['record_id']))
    source_coverage = []
    for source in sources:
        assigned = [unit for unit in units.values() if unit['source'] == source]
        completed = sum(unit['status'] == 'completed' for unit in assigned)
        failed = sum(unit['status'] == 'failed' for unit in assigned)
        pending = len(assigned) - completed - failed
        source_coverage.append({
            'document_id': source['document_id'],
            'source': deepcopy(source),
            'assigned_work_units': len(assigned),
            'completed_work_units': completed,
            'failed_work_units': failed,
            'pending_work_units': pending,
            'status': 'complete' if assigned and completed == len(assigned) else 'incomplete',
        })
        if not assigned:
            issues.append(_issue('no_source_windows', 'No readable source windows were available.',
                                 document_id=source['document_id']))
        elif failed or pending:
            issues.append(_issue('incomplete_source', 'Some assigned source windows were not analyzed successfully.',
                                 document_id=source['document_id']))

    completed_units = sum(unit['status'] == 'completed' for unit in units.values())
    failed_units = sum(unit['status'] == 'failed' for unit in units.values())
    pending_units = len(units) - completed_units - failed_units
    complete_sources = sum(item['status'] == 'complete' for item in source_coverage)
    coverage_complete = bool(sources) and complete_sources == len(sources)
    unresolved_count = sum(item['resolution'] == 'unresolved' for item in unique_candidates.values())
    status = 'valid'
    if not coverage_complete or unresolved_count or issues:
        status = 'partial' if completed_units else ('pending' if pending_units and not failed_units else 'invalid')
    coverage = {
        'assigned_sources': len(sources),
        'completed_sources': complete_sources,
        'assigned_work_units': len(units),
        'completed_work_units': completed_units,
        'failed_work_units': failed_units,
        'pending_work_units': pending_units,
        'status': 'complete' if coverage_complete else 'incomplete',
        'sources': source_coverage,
        # Model-authored notes stay in diagnostics; validation carries only application messages.
        'work_units': [
            {
                **{key: deepcopy(value) for key, value in unit.items() if key != 'notes'},
                'issues': [_public_issue(issue) for issue in unit.get('issues', [])],
            }
            for unit in units.values()
        ],
    }
    noted_units = [unit for unit in units.values() if unit['status'] == 'completed' and unit.get('notes')]
    return {
        'analysis_result_version': ANALYSIS_RESULT_VERSION,
        'analysis_sources': deepcopy(sources),
        'authoritative_result': {'kind': 'records', 'value': records},
        'analysis_evidence': [evidence_by_id[key] for key in sorted(evidence_by_id)],
        'analysis_validation': {
            'status': status,
            'checks': [
                {'name': 'assigned_source_coverage', 'status': 'passed' if coverage_complete else 'incomplete'},
                {'name': 'window_response_structure', 'status': (
                    'failed' if failed_units else ('pending' if pending_units else ('passed' if units else 'not_performed'))
                )},
                {'name': 'candidate_structure_and_evidence_locations',
                 'status': (
                     'unresolved' if unresolved_count else ('passed' if unique_candidates else 'not_applicable')
                 )},
                {'name': 'conflicting_values', 'status': (
                    'unresolved' if any(
                        issue['code'] in {'conflicting_values', 'candidate_replay_conflict', 'work_unit_replay_conflict'}
                        for issue in issues
                    ) else ('passed' if unique_candidates else 'not_applicable')
                )},
                {'name': 'factual_accuracy_and_entailment', 'status': 'not_performed'},
                {'name': 'mathematical_correctness', 'status': 'not_performed'},
                {'name': 'requested_field_completeness', 'status': 'not_performed'},
            ],
            'limitations': [
                'Findings are model judgments. Evidence checks locate quoted passages; they do not verify factual accuracy or entailment.',
                'Reading every source window does not establish that every possible finding was identified.',
                'Different finding keys and cross-document entities are not semantically reconciled.',
                'Calculations, scoring rules and derived values have not been independently verified.',
            ],
            'issues': [_public_issue(issue) for issue in issues],
            'coverage': coverage,
            'finalized_record_count': len(records),
            'unresolved_candidate_count': unresolved_count,
            'evidence_matcher_version': EVIDENCE_MATCHER_VERSION,
        },
        'analysis_diagnostics': {
            'candidates': list(unique_candidates.values()),
            **({
                'work_unit_issues': [
                    {'work_unit_id': unit['work_unit_id'], 'issues': deepcopy(unit['issues'])}
                    for unit in units.values() if unit.get('issues')
                ],
            } if any(unit.get('issues') for unit in units.values()) else {}),
            **({
                'work_unit_notes': [
                    {
                        'work_unit_id': unit['work_unit_id'], 'document_id': unit['document_id'],
                        'window_range': deepcopy(unit.get('window_range') or {}), 'notes': list(unit['notes']),
                    }
                    for unit in noted_units
                ],
            } if noted_units else {}),
        },
    }


def _final_records(result):
    if not isinstance(result, dict) or result.get('analysis_result_version') != ANALYSIS_RESULT_VERSION:
        raise ValueError('A finalized Analyze result is required.')
    authoritative = result.get('authoritative_result') or {}
    records = authoritative.get('value')
    if authoritative.get('kind') != 'records' or not isinstance(records, list) or any(
        not isinstance(record, dict) or not isinstance(record.get('values'), dict) for record in records
    ):
        raise ValueError('The Analyze result does not contain finalized records.')
    return records


def get_document_analysis_export_rows(result):
    """Return public requested values without turning internal lineage into columns."""
    return [deepcopy(record['values']) for record in _final_records(result)]


def _markdown_text(value):
    text = html.escape(str(value), quote=False).replace('\r', ' ').replace('\n', ' ')
    return re.sub(r'([\\`*_\[\]{}()#!|])', r'\\\1', text)


def _value_lines(value, indent=''):
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f'{indent}- **{_markdown_text(key)}:**')
                lines.extend(_value_lines(item, indent + '  '))
            else:
                lines.append(f'{indent}- **{_markdown_text(key)}:** {_display_value(item)}')
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f'{indent}-')
                lines.extend(_value_lines(item, indent + '  '))
            else:
                lines.append(f'{indent}- {_display_value(item)}')
        return lines or [f'{indent}- None reported']
    return [f'{indent}- {_display_value(value)}']


def _display_value(value):
    if value is None:
        return 'Not specified'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return _markdown_text(value)


def build_document_analysis_report(result):
    """Re-render saved final values, without extraction, model calls or side effects."""
    records = _final_records(result)
    validation = result.get('analysis_validation') or {}
    coverage = validation.get('coverage') or {}
    evidence = {item['evidence_id']: item for item in result.get('analysis_evidence', [])}
    lines = ['# Document analysis', '']
    if validation.get('status') != 'valid':
        status_label = {
            'partial': 'Partial result',
            'pending': 'Analysis pending',
            'invalid': 'Analysis unavailable',
        }.get(validation.get('status'), 'Analysis status unavailable')
        lines.extend([
            f'> {status_label}. Only finalized findings are shown; unresolved work may change the conclusions.',
            '',
        ])
    lines.extend(['## Findings', ''])
    if not records:
        lines.append('No finalized findings were returned. This does not establish the absence of relevant issues.')
    previous_source = None
    for record in records:
        source = record.get('source') or {}
        if source != previous_source:
            lines.extend(['', f'### {_markdown_text(source.get("file_name") or record["document_id"])}', ''])
            previous_source = source
        lines.extend(_value_lines(record['values']))
        locations = []
        for ref in record.get('evidence_refs', []):
            location = (evidence.get(ref) or {}).get('location') or {}
            label = ', '.join(
                f'{name} {_markdown_text(location[key])}'
                for name, key in [('page', 'page_number'), ('chunk', 'chunk_sequence')]
                if location.get(key) is not None
            )
            if label and label not in locations:
                locations.append(label)
        if locations:
            lines.append(f'  Supporting locations: {"; ".join(locations)}.')
        caveats = record.get('caveats')
        if isinstance(caveats, list):
            lines.extend(
                f'  Caveat: {_markdown_text(caveat)}' for caveat in caveats
                if isinstance(caveat, str) and caveat.strip()
            )
        lines.append('')
    lines.extend([
        '', '## Coverage', '',
        f'- Sources fully processed: {coverage.get("completed_sources", 0)}/{coverage.get("assigned_sources", 0)}.',
        f'- Windows processed: {coverage.get("completed_work_units", 0)}/{coverage.get("assigned_work_units", 0)}; '
        f'failed: {coverage.get("failed_work_units", 0)}; pending: {coverage.get("pending_work_units", 0)}.',
        f'- Finalized findings: {len(records)}; unresolved candidates: {validation.get("unresolved_candidate_count", 0)}.',
    ])
    for source_coverage in coverage.get('sources', []):
        lines.append(
            f'- {_markdown_text(source_coverage["source"]["file_name"])}: '
            f'{source_coverage["completed_work_units"]}/{source_coverage["assigned_work_units"]} windows processed.'
        )
    names = {
        item['document_id']: item['source']['file_name'] for item in coverage.get('sources', [])
    }
    note_lines = []
    for item in (result.get('analysis_diagnostics') or {}).get('work_unit_notes') or []:
        if not isinstance(item, dict) or not isinstance(item.get('notes'), list):
            continue
        prefix = _markdown_text(names.get(item.get('document_id')) or item.get('document_id') or 'Source')
        window_range = item.get('window_range') if isinstance(item.get('window_range'), dict) else {}
        for first, last, label in (
            ('start_page', 'end_page', 'page'), ('start_chunk_sequence', 'end_chunk_sequence', 'chunk'),
        ):
            if window_range.get(first) is not None and window_range.get(last) is not None:
                span = (
                    f'{label} {window_range[first]}' if window_range[first] == window_range[last]
                    else f'{label}s {window_range[first]} to {window_range[last]}'
                )
                prefix = f'{prefix}, {_markdown_text(span)}'
                break
        note_lines.extend(
            f'- {prefix}: {_markdown_text(note)}' for note in item['notes']
            if isinstance(note, str) and note.strip()
        )
    if note_lines:
        lines.extend(['', '## Analysis notes', '', *note_lines])
    if validation.get('issues'):
        lines.extend(['', '## Validation notes' if validation.get('status') == 'valid' else '## Unresolved work', ''])
        for issue in validation['issues']:
            name = names.get(issue.get('document_id'))
            prefix = f'{_markdown_text(name)}: ' if name else ''
            lines.append(f'- {prefix}{_markdown_text(issue["message"])}')
    lines.extend(['', '## Limitations', ''])
    lines.extend(f'- {_markdown_text(item)}' for item in validation.get('limitations', []))
    return '\n'.join(lines).strip()
