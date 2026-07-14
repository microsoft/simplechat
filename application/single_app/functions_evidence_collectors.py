# functions_evidence_collectors.py
"""Normalize authorized chat source outputs into the shared evidence ledger."""

from collections.abc import Mapping
from typing import TypedDict

from functions_evidence_ledger import (
    add_artifact,
    add_citation,
    add_evidence_source,
    add_execution_failure,
    add_fact,
    add_missing_evidence,
    set_evidence_ledger_status,
)


COLLECTOR_STATUSES = frozenset({
    'not_requested',
    'skipped',
    'succeeded',
    'partial',
    'not_found',
    'failed',
    'unauthorized',
})
COLLECTOR_SOURCE_ALIASES = {
    'conversation_history': ('conversation_history', 'conversation_evidence'),
    'prior_lineage': ('prior_citations', 'conversation_evidence'),
    'selected_documents': ('selected_documents',),
    'conversation_documents': ('conversation_documents',),
    'workspace_search': ('workspace_search', 'user_workspace_context'),
    'web_search': ('web_search', 'public_web'),
    'source_review': ('source_review', 'url_access'),
    'deep_research': ('deep_research',),
    'selected_image': ('selected_images', 'selected_image'),
}
MAX_COLLECTOR_ITEMS = 24
MAX_FACT_CHARS = 2000


class EvidenceCollectorResult(TypedDict):
    """Output-neutral result returned by every source collector."""

    source_type: str
    status: str
    summary: str
    facts: list[dict]
    citations: list[dict]
    artifacts: list[dict]
    missing_or_failed: list[dict]
    metadata: dict


def _normalize_text(value, *, max_chars=MAX_FACT_CHARS):
    normalized = ' '.join(str(value or '').split())
    if len(normalized) <= max_chars:
        return normalized
    return f'{normalized[:max_chars - 3]}...'


def _normalize_ids(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]

    normalized = []
    for value in values:
        identifier = str(value or '').strip()
        if identifier and identifier not in normalized:
            normalized.append(identifier)
    return normalized


def _mapping_items(values, *, from_end=False):
    if not isinstance(values, (list, tuple)):
        return []
    bounded_values = values[-MAX_COLLECTOR_ITEMS:] if from_end else values[:MAX_COLLECTOR_ITEMS]
    return [value for value in bounded_values if isinstance(value, Mapping)]


def _collector_result(
    source_type,
    status,
    summary,
    *,
    facts=None,
    citations=None,
    artifacts=None,
    missing_or_failed=None,
    metadata=None,
):
    normalized_source_type = str(source_type or '').strip()
    normalized_status = str(status or '').strip().lower()
    if not normalized_source_type:
        raise ValueError('source_type is required')
    if normalized_status not in COLLECTOR_STATUSES:
        expected = ', '.join(sorted(COLLECTOR_STATUSES))
        raise ValueError(f'collector status must be one of: {expected}')
    return EvidenceCollectorResult(
        source_type=normalized_source_type,
        status=normalized_status,
        summary=_normalize_text(summary, max_chars=1000),
        facts=list(facts or [])[:MAX_COLLECTOR_ITEMS],
        citations=list(citations or [])[:MAX_COLLECTOR_ITEMS],
        artifacts=list(artifacts or [])[:MAX_COLLECTOR_ITEMS],
        missing_or_failed=list(missing_or_failed or [])[:MAX_COLLECTOR_ITEMS],
        metadata=dict(metadata or {}),
    )


def _not_requested_result(source_type):
    return _collector_result(
        source_type,
        'not_requested',
        f'{source_type.replace("_", " ").capitalize()} was not requested.',
        metadata={'authorization_status': 'not_required'},
    )


def _unauthorized_result(source_type):
    return _collector_result(
        source_type,
        'unauthorized',
        f'{source_type.replace("_", " ").capitalize()} was not authorized.',
        missing_or_failed=[{
            'kind': 'execution_failure',
            'status': 'unauthorized',
            'message': 'The current user is not authorized to collect this source.',
        }],
        metadata={'authorization_status': 'denied'},
    )


def collect_conversation_history_evidence(
    messages,
    *,
    current_user_message_id=None,
    requested=False,
    authorized=False,
):
    """Collect prior user-stated facts without promoting assistant text to evidence."""
    if not requested:
        return _not_requested_result('conversation_history')
    if not authorized:
        return _unauthorized_result('conversation_history')

    current_message_id = str(current_user_message_id or '').strip()
    facts = []
    user_message_count = 0
    assistant_message_count = 0
    skipped_message_count = 0
    seen_fact_text = set()
    for message in _mapping_items(messages, from_end=True):
        if str(message.get('id') or '').strip() == current_message_id:
            continue
        thread_info = (message.get('metadata') or {}).get('thread_info')
        if isinstance(thread_info, Mapping) and thread_info.get('active_thread') is False:
            skipped_message_count += 1
            continue
        role = str(message.get('role') or '').strip().lower()
        if role == 'assistant':
            assistant_message_count += 1
            continue
        if role != 'user':
            continue
        user_message_count += 1
        fact_text = _normalize_text(message.get('content'))
        if not fact_text or fact_text in seen_fact_text:
            continue
        seen_fact_text.add(fact_text)
        facts.append({
            'text': fact_text,
            'confidence': 'user_provided',
            'metadata': {'message_id': str(message.get('id') or '').strip() or None},
        })

    status = 'succeeded' if facts else 'not_found'
    missing = [] if facts else [{
        'kind': 'missing_evidence',
        'status': 'not_found',
        'message': 'No prior user-provided facts were available in the authorized conversation history.',
    }]
    return _collector_result(
        'conversation_history',
        status,
        f'Collected {len(facts)} prior user-provided fact(s).',
        facts=facts,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'authorized',
            'user_message_count': user_message_count,
            'assistant_message_count': assistant_message_count,
            'skipped_message_count': skipped_message_count,
        },
    )


def _normalize_document_citation(citation):
    citation_id = str(citation.get('citation_id') or citation.get('id') or '').strip()
    page_number = citation.get('page_number')
    locator = str(citation.get('location_value') or '').strip()
    if not locator and page_number not in (None, ''):
        locator = f'Page {page_number}'
    return {
        'citation_id': citation_id or None,
        'title': str(citation.get('file_name') or citation.get('title') or 'Document source').strip(),
        'uri': str(citation.get('url') or citation.get('uri') or '').strip(),
        'locator': locator,
        'excerpt': _normalize_text(
            citation.get('excerpt')
            or citation.get('snippet')
            or citation.get('metadata_content'),
        ),
        'metadata': {
            'document_id': str(citation.get('document_id') or '').strip() or None,
            'chunk_id': str(citation.get('chunk_id') or '').strip() or None,
            'group_id': str(citation.get('group_id') or '').strip() or None,
            'public_workspace_id': str(citation.get('public_workspace_id') or '').strip() or None,
            'classification': citation.get('classification'),
            'metadata_type': citation.get('metadata_type'),
        },
    }


def _normalize_web_citation(citation):
    return {
        'citation_id': str(citation.get('citation_id') or citation.get('id') or '').strip() or None,
        'title': str(citation.get('title') or citation.get('name') or citation.get('url') or 'Web source').strip(),
        'uri': str(citation.get('url') or citation.get('uri') or citation.get('href') or '').strip(),
        'locator': str(citation.get('locator') or '').strip(),
        'excerpt': _normalize_text(citation.get('snippet') or citation.get('excerpt')),
        'metadata': {
            'source': citation.get('source'),
            'published_date': citation.get('published_date'),
        },
    }


def _normalize_artifact(artifact, *, default_type='artifact'):
    artifact_type = str(artifact.get('artifact_type') or artifact.get('type') or default_type).strip()
    return {
        'artifact_id': str(artifact.get('id') or artifact.get('artifact_id') or '').strip() or None,
        'artifact_type': artifact_type,
        'name': str(
            artifact.get('name')
            or artifact.get('file_name')
            or artifact.get('title')
            or artifact_type.replace('_', ' ').capitalize()
        ).strip(),
        'reference': str(
            artifact.get('reference')
            or artifact.get('document_id')
            or artifact.get('message_id')
            or ''
        ).strip(),
        'metadata': {
            key: artifact.get(key)
            for key in (
                'document_id',
                'message_id',
                'workspace_scope',
                'mime_type',
                'source_assistant_message_id',
            )
            if artifact.get(key) not in (None, '')
        },
    }


def collect_prior_lineage_evidence(messages, *, requested=False, authorized=False):
    """Collect prior citation and artifact lineage without reusing assistant claims."""
    if not requested:
        return _not_requested_result('prior_lineage')
    if not authorized:
        return _unauthorized_result('prior_lineage')

    citations = []
    artifacts = []
    seen_citations = set()
    seen_artifacts = set()
    for message in _mapping_items(messages, from_end=True):
        role = str(message.get('role') or '').strip().lower()
        if role == 'assistant':
            for citation in _mapping_items(message.get('hybrid_citations')):
                normalized = _normalize_document_citation(citation)
                identity = (
                    normalized.get('citation_id'),
                    normalized.get('metadata', {}).get('document_id'),
                    normalized.get('locator'),
                )
                if identity in seen_citations:
                    continue
                seen_citations.add(identity)
                citations.append(normalized)
            for citation in _mapping_items(message.get('web_search_citations')):
                normalized = _normalize_web_citation(citation)
                identity = (normalized.get('uri'), normalized.get('title'))
                if identity in seen_citations:
                    continue
                seen_citations.add(identity)
                citations.append(normalized)

            metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
            artifact_candidates = []
            for metadata_key in ('generated_analysis_artifacts', 'generated_tabular_outputs'):
                artifact_candidates.extend(_mapping_items(metadata.get(metadata_key)))
            prior_ledger = metadata.get('evidence_ledger')
            if isinstance(prior_ledger, Mapping):
                artifact_candidates.extend(_mapping_items(prior_ledger.get('artifacts')))
            for artifact in artifact_candidates:
                normalized = _normalize_artifact(artifact)
                identity = (
                    normalized.get('artifact_id'),
                    normalized.get('reference'),
                    normalized.get('name'),
                )
                if identity in seen_artifacts:
                    continue
                seen_artifacts.add(identity)
                artifacts.append(normalized)
        elif role == 'image':
            image_artifact = _normalize_artifact({
                'id': message.get('id'),
                'type': 'generated_image' if not (message.get('metadata') or {}).get('is_user_upload') else 'uploaded_image',
                'name': message.get('filename') or 'Conversation image',
                'message_id': message.get('id'),
                'mime_type': message.get('mime_type'),
                'source_assistant_message_id': (
                    ((message.get('metadata') or {}).get('image_proposal') or {}).get('source_assistant_message_id')
                ),
            })
            identity = (image_artifact.get('artifact_id'), image_artifact.get('reference'))
            if identity not in seen_artifacts:
                seen_artifacts.add(identity)
                artifacts.append(image_artifact)

    status = 'succeeded' if citations or artifacts else 'not_found'
    missing = [] if status == 'succeeded' else [{
        'kind': 'missing_evidence',
        'status': 'not_found',
        'message': 'No prior citation or artifact lineage was available.',
    }]
    return _collector_result(
        'prior_lineage',
        status,
        f'Collected {len(citations)} prior citation(s) and {len(artifacts)} artifact reference(s).',
        citations=citations,
        artifacts=artifacts,
        missing_or_failed=missing,
        metadata={'authorization_status': 'authorized'},
    )


def collect_selected_document_evidence(
    documents,
    *,
    requested_document_ids=None,
    chat_upload_document_ids=None,
    requested=False,
    authorized=False,
    source_type='selected_documents',
):
    """Collect metadata for selected documents revalidated by the calling boundary."""
    if not requested:
        return _not_requested_result(source_type)
    if not authorized:
        return _unauthorized_result(source_type)

    requested_ids = _normalize_ids(requested_document_ids)
    chat_upload_ids = _normalize_ids(chat_upload_document_ids)
    authorized_documents = _mapping_items(documents)
    authorized_ids = _normalize_ids(document.get('id') for document in authorized_documents)
    missing_ids = [document_id for document_id in requested_ids if document_id not in authorized_ids]
    artifacts = []
    for document in authorized_documents:
        document_id = str(document.get('id') or '').strip()
        is_chat_upload = bool(
            document.get('created_from_chat_upload')
            or document_id in chat_upload_ids
        )
        artifacts.append(_normalize_artifact({
            'id': f'document-{document_id}',
            'type': 'conversation_upload_document' if is_chat_upload else 'workspace_document',
            'name': document.get('file_name') or document.get('title') or document_id,
            'document_id': document_id,
            'workspace_scope': document.get('workspace_scope') or document.get('source_hint'),
        }))

    if authorized_documents and missing_ids:
        status = 'partial'
    elif authorized_documents:
        status = 'succeeded'
    else:
        status = 'not_found'
    missing = []
    if missing_ids:
        missing.append({
            'kind': 'missing_evidence',
            'status': 'not_found',
            'message': f'{len(missing_ids)} selected document(s) were not available after authorization revalidation.',
            'metadata': {'missing_document_count': len(missing_ids)},
        })
    elif not authorized_documents:
        missing.append({
            'kind': 'missing_evidence',
            'status': 'not_found',
            'message': 'No authorized selected documents were available.',
        })

    return _collector_result(
        source_type,
        status,
        f'Collected {len(authorized_documents)} authorized selected document(s).',
        artifacts=artifacts,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'authorized',
            'selected_document_ids': authorized_ids,
            'chat_upload_document_ids': [
                document_id for document_id in chat_upload_ids if document_id in authorized_ids
            ],
            'requested_document_count': len(requested_ids),
        },
    )


def _workspace_locator(result):
    sheet_name = str(result.get('sheet_name') or '').strip()
    if sheet_name:
        return f'Sheet {sheet_name}'
    page_number = result.get('page_number') or result.get('chunk_sequence')
    if page_number not in (None, ''):
        return f'Page {page_number}'
    return ''


def collect_workspace_search_evidence(
    search_results,
    *,
    citations=None,
    requested=False,
    authorized=False,
    query='',
    selected_document_ids=None,
    failure=None,
):
    """Normalize authorized hybrid-search chunks into supported facts and citations."""
    if not requested:
        return _not_requested_result('workspace_search')
    if not authorized:
        return _unauthorized_result('workspace_search')
    if failure:
        return _collector_result(
            'workspace_search',
            'failed',
            'Workspace search failed.',
            missing_or_failed=[{
                'kind': 'execution_failure',
                'status': 'failed',
                'message': _normalize_text(failure, max_chars=500),
            }],
            metadata={'authorization_status': 'authorized', 'query': _normalize_text(query, max_chars=500)},
        )

    results = _mapping_items(search_results)
    normalized_citations = []
    facts = []
    seen_facts = set()
    for result in results:
        fact_text = _normalize_text(
            result.get('chunk_text')
            or result.get('metadata_content')
            or result.get('excerpt')
        )
        if fact_text and fact_text not in seen_facts:
            seen_facts.add(fact_text)
            facts.append({
                'text': fact_text,
                'confidence': 'source_supported',
                'metadata': {
                    'document_id': str(result.get('document_id') or '').strip() or None,
                    'chunk_id': str(result.get('chunk_id') or '').strip() or None,
                },
            })
        normalized_citations.append({
            'citation_id': str(result.get('citation_id') or result.get('id') or '').strip() or None,
            'title': str(result.get('file_name') or result.get('title') or 'Workspace document').strip(),
            'uri': '',
            'locator': _workspace_locator(result),
            'excerpt': fact_text,
            'metadata': {
                'document_id': str(result.get('document_id') or '').strip() or None,
                'chunk_id': str(result.get('chunk_id') or '').strip() or None,
                'score': result.get('score'),
                'classification': result.get('document_classification') or result.get('classification'),
                'tags': result.get('tags'),
                'group_id': result.get('group_id'),
                'public_workspace_id': result.get('public_workspace_id'),
            },
        })

    if citations:
        known_citation_keys = {
            (citation.get('citation_id'), citation.get('title'), citation.get('locator'))
            for citation in normalized_citations
        }
        for citation in _mapping_items(citations):
            normalized = _normalize_document_citation(citation)
            identity = (
                normalized.get('citation_id'),
                normalized.get('title'),
                normalized.get('locator'),
            )
            if identity not in known_citation_keys:
                known_citation_keys.add(identity)
                normalized_citations.append(normalized)

    evidence_available = bool(results or normalized_citations)
    status = 'succeeded' if evidence_available else 'not_found'
    missing = [] if evidence_available else [{
        'kind': 'missing_evidence',
        'status': 'not_found',
        'message': 'Workspace search completed but returned no matching evidence.',
    }]
    return _collector_result(
        'workspace_search',
        status,
        f'Workspace search returned {len(results)} result(s).',
        facts=facts,
        citations=normalized_citations,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'authorized',
            'query': _normalize_text(query, max_chars=500),
            'result_count': len(results),
            'selected_document_ids': _normalize_ids(selected_document_ids),
        },
    )


def collect_web_search_evidence(citations, *, runs=None, requested=False):
    """Normalize public web citations while distinguishing no results from failures."""
    if not requested:
        return _not_requested_result('web_search')

    normalized_citations = []
    facts = []
    for citation in _mapping_items(citations):
        normalized = _normalize_web_citation(citation)
        normalized_citations.append(normalized)
        if normalized['excerpt']:
            facts.append({
                'text': normalized['excerpt'],
                'confidence': 'source_supported',
                'metadata': {'uri': normalized['uri']},
            })

    run_items = _mapping_items(runs)
    failed_runs = [run for run in run_items if run.get('success') is False]
    if normalized_citations and failed_runs:
        status = 'partial'
    elif normalized_citations:
        status = 'succeeded'
    elif failed_runs:
        status = 'failed'
    else:
        status = 'not_found'

    missing = []
    if failed_runs:
        missing.append({
            'kind': 'execution_failure',
            'status': 'failed' if status == 'failed' else 'partial',
            'message': f'{len(failed_runs)} web search run(s) failed.',
            'metadata': {
                'run_statuses': [str(run.get('status') or 'failed') for run in failed_runs],
            },
        })
    if not normalized_citations and not failed_runs:
        missing.append({
            'kind': 'missing_evidence',
            'status': 'not_found',
            'message': 'Web search completed but returned no verifiable public sources.',
        })

    return _collector_result(
        'web_search',
        status,
        f'Web search produced {len(normalized_citations)} citation(s) across {len(run_items)} run(s).',
        facts=facts,
        citations=normalized_citations,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'not_required',
            'run_count': len(run_items),
            'failed_run_count': len(failed_runs),
        },
    )


def collect_source_review_evidence(
    source_review_result,
    *,
    requested=False,
    authorized=False,
    source_type='source_review',
):
    """Normalize reviewed pages, excerpts, coverage, and skipped pages."""
    if not requested:
        return _not_requested_result(source_type)
    if not authorized:
        return _unauthorized_result(source_type)

    result = source_review_result if isinstance(source_review_result, Mapping) else {}
    pages = _mapping_items(result.get('pages'))
    skipped_pages = _mapping_items(result.get('skipped'))
    facts = []
    citations = []
    missing = []
    suspicious_page_count = 0
    for page in pages:
        page_url = str(page.get('url') or '').strip()
        citations.append({
            'citation_id': None,
            'title': str(page.get('title') or page_url or 'Reviewed source').strip(),
            'uri': page_url,
            'locator': '',
            'excerpt': _normalize_text(' '.join(str(item) for item in (page.get('excerpts') or [])[:3])),
            'metadata': {
                'published_date': page.get('published_date'),
                'depth': page.get('depth'),
                'content_type': page.get('content_type'),
            },
        })
        prompt_injection_markers = _normalize_ids(page.get('prompt_injection_markers'))
        if prompt_injection_markers:
            suspicious_page_count += 1
            missing.append({
                'kind': 'execution_failure',
                'status': 'partial',
                'message': 'Reviewed page excerpts were omitted because prompt-injection markers were detected.',
                'metadata': {
                    'uri': page_url,
                    'marker_count': len(prompt_injection_markers),
                },
            })
            continue
        for excerpt in (page.get('excerpts') or [])[:5]:
            fact_text = _normalize_text(excerpt)
            if fact_text:
                facts.append({
                    'text': fact_text,
                    'confidence': 'source_supported',
                    'metadata': {'uri': page_url},
                })

    for skipped_page in skipped_pages:
        reason = str(
            skipped_page.get('skip_reason')
            or skipped_page.get('reason')
            or skipped_page.get('status')
            or 'unknown_reason'
        ).strip()
        missing.append({
            'kind': 'execution_failure',
            'status': 'skipped',
            'message': f'Source page was skipped: {reason}.',
            'metadata': {'uri': str(skipped_page.get('url') or '').strip()},
        })

    skipped_reason = str(result.get('skipped_reason') or '').strip()
    if pages and (skipped_pages or skipped_reason or suspicious_page_count):
        status = 'partial'
    elif pages:
        status = 'succeeded'
    elif skipped_pages:
        status = 'failed'
    elif skipped_reason in {'no_source_urls_available', 'no_sources_available'}:
        status = 'not_found'
    elif skipped_reason:
        status = 'skipped'
    else:
        status = 'not_found'

    if not pages and not missing:
        missing.append({
            'kind': 'missing_evidence' if status == 'not_found' else 'execution_failure',
            'status': status,
            'message': (
                f'Source review did not produce page evidence: {skipped_reason}.'
                if skipped_reason
                else 'Source review completed but produced no page evidence.'
            ),
        })

    coverage = result.get('coverage') if isinstance(result.get('coverage'), Mapping) else {}
    return _collector_result(
        source_type,
        status,
        f'Source review collected {len(pages)} page(s) and skipped {len(skipped_pages)} page(s).',
        facts=facts,
        citations=citations,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'authorized',
            'mode': result.get('mode'),
            'coverage': dict(coverage),
            'skipped_reason': skipped_reason or None,
            'suspicious_page_count': suspicious_page_count,
        },
    )


def _extract_vision_analysis(image_reference):
    vision_analysis = image_reference.get('vision_analysis')
    if isinstance(vision_analysis, Mapping):
        return vision_analysis
    metadata = image_reference.get('metadata')
    if isinstance(metadata, Mapping) and isinstance(metadata.get('vision_analysis'), Mapping):
        return metadata.get('vision_analysis')
    return {}


def collect_selected_image_evidence(image_references, *, requested=False, authorized=False):
    """Collect selected image lineage and any available AI vision facts."""
    if not requested:
        return _not_requested_result('selected_image')
    if not authorized:
        return _unauthorized_result('selected_image')

    references = _mapping_items(image_references)
    facts = []
    artifacts = []
    missing = []
    for image_reference in references:
        reference_id = str(
            image_reference.get('document_id')
            or image_reference.get('message_id')
            or image_reference.get('id')
            or ''
        ).strip()
        artifacts.append(_normalize_artifact({
            'id': f'image-reference-{reference_id}',
            'type': 'image_reference',
            'name': image_reference.get('file_name') or image_reference.get('filename') or 'Selected image',
            'reference': reference_id,
            'document_id': image_reference.get('document_id'),
            'message_id': image_reference.get('message_id'),
            'workspace_scope': image_reference.get('workspace_scope'),
            'mime_type': image_reference.get('mime_type'),
        }))
        vision_analysis = _extract_vision_analysis(image_reference)
        description = _normalize_text(vision_analysis.get('description'))
        objects = [
            _normalize_text(item, max_chars=200)
            for item in (vision_analysis.get('objects') or [])[:20]
            if _normalize_text(item, max_chars=200)
        ]
        visible_text = _normalize_text(vision_analysis.get('text') or vision_analysis.get('visible_text'))
        contextual_analysis = _normalize_text(
            vision_analysis.get('contextual_analysis') or vision_analysis.get('analysis')
        )
        vision_facts = [
            description,
            f'Detected objects: {", ".join(objects)}' if objects else '',
            f'Visible text: {visible_text}' if visible_text else '',
            contextual_analysis,
        ]
        for fact_text in vision_facts:
            if not fact_text:
                continue
            facts.append({
                'text': fact_text,
                'confidence': 'source_supported',
                'metadata': {'reference_id': reference_id},
            })
        if not any(vision_facts):
            missing.append({
                'kind': 'missing_evidence',
                'status': 'partial',
                'message': 'Selected image is available, but no vision metadata has been extracted yet.',
                'metadata': {'reference_id': reference_id},
            })

    if references and missing:
        status = 'partial'
    elif references:
        status = 'succeeded'
    else:
        status = 'not_found'
        missing.append({
            'kind': 'missing_evidence',
            'status': 'not_found',
            'message': 'No authorized selected image reference was available.',
        })
    return _collector_result(
        'selected_image',
        status,
        f'Collected {len(references)} selected image reference(s).',
        facts=facts,
        artifacts=artifacts,
        missing_or_failed=missing,
        metadata={
            'authorization_status': 'authorized',
            'reference_count': len(references),
            'vision_reference_count': len(references) - len(missing),
        },
    )


def _resolve_ledger_source_id(ledger, source_type, requested_source_id=None):
    source_ids = {
        str(source.get('id') or '').strip()
        for source in ledger.get('sources', [])
        if isinstance(source, Mapping)
    }
    normalized_requested_id = str(requested_source_id or '').strip()
    if normalized_requested_id:
        return normalized_requested_id
    for candidate in COLLECTOR_SOURCE_ALIASES.get(source_type, (source_type,)):
        if candidate in source_ids:
            return candidate
    return source_type


def _infer_requirement_ids(ledger, source_id, source_type):
    existing_source = next(
        (
            source
            for source in ledger.get('sources', [])
            if isinstance(source, Mapping) and source.get('id') == source_id
        ),
        None,
    )
    if existing_source:
        return _normalize_ids(existing_source.get('requirement_ids'))

    aliases = set(COLLECTOR_SOURCE_ALIASES.get(source_type, (source_type,)))
    aliases.add(source_type)
    return [
        str(requirement.get('id'))
        for requirement in ledger.get('requirements', [])
        if isinstance(requirement, Mapping)
        and aliases.intersection(_normalize_ids(requirement.get('source_types')))
    ]


def _unique_requested_id(entries, requested_id, prefix):
    normalized_requested_id = str(requested_id or '').strip()
    if normalized_requested_id and not any(entry.get('id') == normalized_requested_id for entry in entries):
        return normalized_requested_id
    index = len(entries) + 1
    identifier = f'{prefix}_{index}'
    while any(entry.get('id') == identifier for entry in entries):
        index += 1
        identifier = f'{prefix}_{index}'
    return identifier


def apply_evidence_collector_result(
    ledger,
    collector_result,
    *,
    source_id=None,
    requirement_ids=None,
    origin='collector',
    required=None,
):
    """Apply one validated collector result to the shared ledger in place."""
    if not isinstance(collector_result, Mapping):
        raise ValueError('collector_result must be a mapping')
    normalized_result = _collector_result(
        collector_result.get('source_type'),
        collector_result.get('status'),
        collector_result.get('summary'),
        facts=collector_result.get('facts'),
        citations=collector_result.get('citations'),
        artifacts=collector_result.get('artifacts'),
        missing_or_failed=collector_result.get('missing_or_failed'),
        metadata=collector_result.get('metadata'),
    )
    normalized_source_type = normalized_result['source_type']
    normalized_source_id = _resolve_ledger_source_id(
        ledger,
        normalized_source_type,
        requested_source_id=source_id,
    )
    effective_requirement_ids = (
        _normalize_ids(requirement_ids)
        if requirement_ids is not None
        else _infer_requirement_ids(ledger, normalized_source_id, normalized_source_type)
    )
    authorization_status = normalized_result['metadata'].get('authorization_status')
    source = add_evidence_source(
        ledger,
        normalized_source_type,
        normalized_result['status'],
        source_id=normalized_source_id,
        origin=origin,
        required=required,
        summary=normalized_result['summary'],
        requirement_ids=effective_requirement_ids,
        metadata=normalized_result['metadata'],
        authorization_status=authorization_status,
    )

    citation_ids = []
    for citation in normalized_result['citations']:
        if not isinstance(citation, Mapping):
            continue
        signature = (
            normalized_source_id,
            str(citation.get('title') or '').strip(),
            str(citation.get('uri') or '').split('?', 1)[0],
            str(citation.get('locator') or '').strip(),
            str((citation.get('metadata') or {}).get('document_id') or '').strip(),
        )
        existing = next(
            (
                entry
                for entry in ledger.get('citations', [])
                if (
                    entry.get('source_id'),
                    entry.get('title'),
                    entry.get('uri'),
                    entry.get('locator'),
                    str((entry.get('metadata') or {}).get('document_id') or '').strip(),
                ) == signature
            ),
            None,
        )
        if existing:
            citation_ids.append(existing['id'])
            continue
        citation_entry = add_citation(
            ledger,
            normalized_source_id,
            citation_id=_unique_requested_id(
                ledger.get('citations', []),
                citation.get('citation_id') or citation.get('id'),
                'citation',
            ),
            title=citation.get('title'),
            uri=citation.get('uri'),
            locator=citation.get('locator'),
            excerpt=citation.get('excerpt'),
            metadata=citation.get('metadata'),
        )
        citation_ids.append(citation_entry['id'])

    artifact_ids = []
    for artifact in normalized_result['artifacts']:
        if not isinstance(artifact, Mapping):
            continue
        signature = (
            str(artifact.get('artifact_type') or artifact.get('type') or '').strip(),
            str(artifact.get('name') or '').strip(),
            str(artifact.get('reference') or '').split('?', 1)[0],
        )
        existing = next(
            (
                entry
                for entry in ledger.get('artifacts', [])
                if (
                    entry.get('type'),
                    entry.get('name'),
                    entry.get('reference'),
                ) == signature
            ),
            None,
        )
        if existing:
            if normalized_source_id not in existing.get('source_ids', []):
                existing['source_ids'].append(normalized_source_id)
            artifact_ids.append(existing['id'])
            continue
        artifact_entry = add_artifact(
            ledger,
            artifact.get('artifact_type') or artifact.get('type') or 'artifact',
            artifact_id=_unique_requested_id(
                ledger.get('artifacts', []),
                artifact.get('artifact_id') or artifact.get('id'),
                'artifact',
            ),
            name=artifact.get('name'),
            source_ids=[normalized_source_id],
            reference=artifact.get('reference'),
            metadata=artifact.get('metadata'),
        )
        artifact_ids.append(artifact_entry['id'])

    fact_ids = []
    for fact in normalized_result['facts']:
        if not isinstance(fact, Mapping):
            continue
        fact_text = _normalize_text(fact.get('text'))
        if not fact_text:
            continue
        fact_confidence = str(fact.get('confidence') or 'source_supported').strip().lower()
        existing = next(
            (
                entry
                for entry in ledger.get('facts', []) + ledger.get('unsupported_facts', [])
                if entry.get('text') == fact_text and entry.get('confidence') == fact_confidence
            ),
            None,
        )
        if existing:
            if normalized_source_id not in existing.get('source_ids', []):
                existing.setdefault('source_ids', []).append(normalized_source_id)
            for requirement_id in effective_requirement_ids:
                if requirement_id not in existing.get('requirement_ids', []):
                    existing.setdefault('requirement_ids', []).append(requirement_id)
            fact_ids.append(existing['id'])
            continue
        fact_entry = add_fact(
            ledger,
            fact_text,
            [normalized_source_id],
            requirement_ids=effective_requirement_ids,
            confidence=fact_confidence,
            fact_id=_unique_requested_id(
                ledger.get('facts', []) + ledger.get('unsupported_facts', []),
                fact.get('fact_id') or fact.get('id'),
                'fact',
            ),
        )
        fact_ids.append(fact_entry['id'])

    gap_ids = []
    for gap in normalized_result['missing_or_failed']:
        if not isinstance(gap, Mapping):
            continue
        gap_kind = str(gap.get('kind') or 'execution_failure').strip()
        gap_status = str(gap.get('status') or normalized_result['status']).strip().lower()
        gap_message = _normalize_text(gap.get('message'), max_chars=1000)
        if not gap_message:
            continue
        if gap_kind == 'missing_evidence':
            requirement_id = str(gap.get('requirement_id') or '').strip()
            if not requirement_id and effective_requirement_ids:
                requirement_id = effective_requirement_ids[0]
            gap_entry = add_missing_evidence(
                ledger,
                requirement_id or None,
                normalized_source_type,
                gap_status,
                gap_message,
                source_id=normalized_source_id,
                missing_id=_unique_requested_id(
                    ledger.get('missing_or_failed', []),
                    gap.get('id'),
                    'gap',
                ),
            )
        else:
            gap_entry = add_execution_failure(
                ledger,
                normalized_source_type,
                gap_status,
                gap_message,
                source_id=normalized_source_id,
                step_id=gap.get('step_id'),
                requirement_ids=effective_requirement_ids,
                failure_id=_unique_requested_id(
                    ledger.get('missing_or_failed', []),
                    gap.get('id'),
                    'gap',
                ),
            )
        gap_ids.append(gap_entry['id'])

    # Gap helpers apply each gap status to the source; restore the collector's aggregate status.
    add_evidence_source(
        ledger,
        normalized_source_type,
        normalized_result['status'],
        source_id=normalized_source_id,
        origin=origin,
        required=required,
        summary=normalized_result['summary'],
        requirement_ids=effective_requirement_ids,
        metadata=normalized_result['metadata'],
        authorization_status=authorization_status,
    )
    return {
        'source_id': source['id'],
        'fact_ids': fact_ids,
        'citation_ids': citation_ids,
        'artifact_ids': artifact_ids,
        'gap_ids': gap_ids,
    }


def apply_evidence_collector_results(ledger, collector_results):
    """Apply collector results and derive the aggregate pre-finalization status."""
    applied = []
    terminal_statuses = []
    for collector_result in collector_results or []:
        applied.append(apply_evidence_collector_result(ledger, collector_result))
        terminal_statuses.append(str(collector_result.get('status') or '').strip().lower())

    relevant_statuses = [status for status in terminal_statuses if status != 'not_requested']
    if relevant_statuses and all(status in {'failed', 'unauthorized'} for status in relevant_statuses):
        set_evidence_ledger_status(ledger, 'failed')
    elif any(status in {'partial', 'failed', 'unauthorized', 'not_found', 'skipped'} for status in relevant_statuses):
        set_evidence_ledger_status(ledger, 'partial')
    else:
        set_evidence_ledger_status(ledger, 'ready')
    return applied


def _planned_source_ids(plan):
    if not isinstance(plan, Mapping):
        return []
    return _normalize_ids(
        source.get('id')
        for source in plan.get('sources', [])
        if isinstance(source, Mapping)
    )


def _authorized_documents_by_id(documents):
    return {
        str(document.get('id') or '').strip(): document
        for document in _mapping_items(documents)
        if str(document.get('id') or '').strip()
    }


def populate_evidence_ledger_from_chat_sources(
    ledger,
    plan,
    *,
    conversation_messages=None,
    current_user_message_id=None,
    authorized_selected_documents=None,
    selected_document_ids=None,
    authorized_chat_upload_documents=None,
    chat_upload_document_ids=None,
    workspace_search_results=None,
    workspace_citations=None,
    workspace_search_attempted=False,
    workspace_search_failure=None,
    web_search_citations=None,
    web_search_runs=None,
    web_search_attempted=False,
    source_review_result=None,
    source_review_attempted=False,
    source_review_authorized=False,
    deep_research_enabled=False,
    selected_image_references=None,
):
    """Populate a turn ledger from outputs already authorized by the chat route."""
    planned_source_ids = _planned_source_ids(plan)
    coordinated = bool(isinstance(plan, Mapping) and plan.get('mode') == 'coordinated')
    applied = []

    conversation_requested = coordinated and (
        'conversation_evidence' in planned_source_ids
        or any(
            str(message.get('role') or '').strip().lower() == 'user'
            and str(message.get('id') or '').strip() != str(current_user_message_id or '').strip()
            for message in _mapping_items(conversation_messages, from_end=True)
        )
    )
    if conversation_requested:
        history_result = collect_conversation_history_evidence(
            conversation_messages,
            current_user_message_id=current_user_message_id,
            requested=True,
            authorized=True,
        )
        history_source_id = (
            'conversation_evidence'
            if 'conversation_evidence' in planned_source_ids
            else 'conversation_history'
        )
        applied.append(apply_evidence_collector_result(
            ledger,
            history_result,
            source_id=history_source_id,
            required=True if history_source_id in planned_source_ids else False,
            origin='conversation',
        ))

    prior_lineage_available = any(
        (
            message.get('hybrid_citations')
            or message.get('web_search_citations')
            or str(message.get('role') or '').strip().lower() == 'image'
            or (
                isinstance(message.get('metadata'), Mapping)
                and (
                    message['metadata'].get('generated_analysis_artifacts')
                    or message['metadata'].get('generated_tabular_outputs')
                )
            )
        )
        for message in _mapping_items(conversation_messages, from_end=True)
    )
    if coordinated and prior_lineage_available:
        lineage_result = collect_prior_lineage_evidence(
            conversation_messages,
            requested=True,
            authorized=True,
        )
        applied.append(apply_evidence_collector_result(
            ledger,
            lineage_result,
            source_id='prior_citations',
            required=False,
            origin='conversation',
        ))

    selected_documents_by_id = _authorized_documents_by_id(authorized_selected_documents)
    normalized_selected_document_ids = _normalize_ids(selected_document_ids)
    if 'selected_documents' in planned_source_ids:
        selected_result = collect_selected_document_evidence(
            [
                selected_documents_by_id[document_id]
                for document_id in normalized_selected_document_ids
                if document_id in selected_documents_by_id
            ],
            requested_document_ids=normalized_selected_document_ids,
            requested=True,
            authorized=True,
        )
        applied.append(apply_evidence_collector_result(
            ledger,
            selected_result,
            source_id='selected_documents',
            origin='selection',
        ))

    chat_upload_documents_by_id = _authorized_documents_by_id(authorized_chat_upload_documents)
    normalized_chat_upload_document_ids = _normalize_ids(chat_upload_document_ids)
    if 'conversation_documents' in planned_source_ids:
        chat_upload_result = collect_selected_document_evidence(
            [
                chat_upload_documents_by_id[document_id]
                for document_id in normalized_chat_upload_document_ids
                if document_id in chat_upload_documents_by_id
            ],
            requested_document_ids=normalized_chat_upload_document_ids,
            chat_upload_document_ids=normalized_chat_upload_document_ids,
            requested=True,
            authorized=True,
            source_type='conversation_documents',
        )
        applied.append(apply_evidence_collector_result(
            ledger,
            chat_upload_result,
            source_id='conversation_documents',
            origin='conversation',
        ))

    workspace_source_ids = [
        source_id
        for source_id in ('workspace_search', 'user_workspace_context', 'assigned_knowledge')
        if source_id in planned_source_ids
    ]
    if workspace_search_attempted or workspace_source_ids:
        if workspace_search_attempted:
            workspace_result = collect_workspace_search_evidence(
                workspace_search_results,
                citations=workspace_citations,
                requested=True,
                authorized=True,
                selected_document_ids=normalized_selected_document_ids + normalized_chat_upload_document_ids,
                failure=workspace_search_failure,
            )
        else:
            workspace_result = _collector_result(
                'workspace_search',
                'skipped',
                'Workspace search was planned but was not attempted by the current route.',
                missing_or_failed=[{
                    'kind': 'execution_failure',
                    'status': 'skipped',
                    'message': 'Workspace search was planned but was not attempted.',
                }],
                metadata={'authorization_status': 'authorized'},
            )
        target_source_ids = workspace_source_ids or ['workspace_search']
        for target_source_id in target_source_ids:
            applied.append(apply_evidence_collector_result(
                ledger,
                workspace_result,
                source_id=target_source_id,
                required=True if target_source_id in planned_source_ids else False,
                origin='retrieval',
            ))

    web_source_ids = [
        source_id
        for source_id in ('web_search', 'public_web')
        if source_id in planned_source_ids
    ]
    if web_search_attempted or web_source_ids:
        if web_search_attempted:
            web_result = collect_web_search_evidence(
                web_search_citations,
                runs=web_search_runs,
                requested=True,
            )
        else:
            web_result = _collector_result(
                'web_search',
                'skipped',
                'Web search was planned but was not attempted by the current route.',
                missing_or_failed=[{
                    'kind': 'execution_failure',
                    'status': 'skipped',
                    'message': 'Web search was planned but was not attempted.',
                }],
                metadata={'authorization_status': 'not_required'},
            )
        target_source_ids = web_source_ids or ['web_search']
        for target_source_id in target_source_ids:
            applied.append(apply_evidence_collector_result(
                ledger,
                web_result,
                source_id=target_source_id,
                required=True if target_source_id in planned_source_ids else False,
                origin='retrieval',
            ))

    source_review_source_ids = [
        source_id
        for source_id in ('deep_research', 'source_review', 'url_access')
        if source_id in planned_source_ids
    ]
    if source_review_attempted or source_review_source_ids:
        source_type = 'deep_research' if deep_research_enabled else 'source_review'
        review_result = collect_source_review_evidence(
            source_review_result,
            requested=True,
            authorized=source_review_authorized,
            source_type=source_type,
        )
        target_source_ids = source_review_source_ids or [source_type]
        for target_source_id in target_source_ids:
            applied.append(apply_evidence_collector_result(
                ledger,
                review_result,
                source_id=target_source_id,
                required=True if target_source_id in planned_source_ids else False,
                origin='retrieval',
            ))

    selected_image_discovered = any(
        isinstance(image_reference, Mapping)
        and image_reference.get('selection_origin') == 'selected_document'
        for image_reference in (selected_image_references or [])
    )
    image_requested = 'selected_images' in planned_source_ids or selected_image_discovered
    if coordinated and image_requested:
        image_result = collect_selected_image_evidence(
            selected_image_references,
            requested=True,
            authorized=True,
        )
        applied.append(apply_evidence_collector_result(
            ledger,
            image_result,
            source_id='selected_images' if 'selected_images' in planned_source_ids else 'selected_image',
            required=True if 'selected_images' in planned_source_ids else False,
            origin='selection',
        ))

    required_sources = [
        source
        for source in ledger.get('sources', [])
        if isinstance(source, Mapping) and source.get('required')
    ]
    required_statuses = {
        str(source.get('status') or '').strip().lower()
        for source in required_sources
    }
    unresolved_statuses = {'planned', 'pending', 'running'}
    failed_statuses = {'failed', 'unauthorized', 'cancelled'}
    partial_statuses = {'partial', 'not_found', 'not_available', 'skipped'}
    if required_statuses and required_statuses.issubset(failed_statuses):
        set_evidence_ledger_status(ledger, 'failed')
    elif required_statuses.intersection(failed_statuses | partial_statuses):
        set_evidence_ledger_status(ledger, 'partial')
    elif required_statuses.intersection(unresolved_statuses):
        set_evidence_ledger_status(ledger, 'collecting')
    else:
        set_evidence_ledger_status(ledger, 'ready')

    return applied