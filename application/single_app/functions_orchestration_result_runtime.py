# functions_orchestration_result_runtime.py
"""Typed runtime handoffs; no clients, model calls, publication, or new storage.

Version: 0.261.365
"""

from copy import deepcopy
from dataclasses import replace

from content_screening.contracts import DocumentHeldError, ScreeningError
from functions_analysis_access import analysis_source_snapshot
from functions_evidence_status import evidence_status_from_sources
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationControlError, OrchestrationInvocationServiceError,
)
from functions_orchestration_registry import (
    DEPENDENCY_PLAN_CONTRACT_VERSION, get_capability, get_capability_result_outputs,
)
from functions_orchestration_result_contracts import (
    IMAGE_ASSET_KIND, MAX_DESCRIPTOR_BYTES, MAX_EXTERNAL_SOURCES, Completeness, Coverage, ExternalSourceRef,
    InputBinding, PartialInputNotAcceptedError, ResultContractError, ResultNotReadyError, ResultRef, TaskResult,
    canonical_bytes, canonical_digest, output_name,
)
from functions_orchestration_results import (
    MAX_LINEAGE_RESULTS, MAX_VALUE_BYTES, NamedOutput, OrchestrationResults, ResultUnavailableError, _reference,
)
from functions_orchestration_schema import step_input_specs


def raise_source_service_failure(error):
    """Preserve typed authority, cancellation and lifecycle controls, not a definite hold."""
    if isinstance(error, (
        OrchestrationInvocationServiceError, OrchestrationInvocationCancelledError, OrchestrationInvocationControlError,
    )):
        raise error
    if isinstance(error, ScreeningError) and not isinstance(error, DocumentHeldError):
        raise error


def require_result_service(context):
    service = getattr(context, 'result_service', None)
    if not isinstance(service, OrchestrationResults):
        raise ResultContractError('result_service_required')
    return service


def reuse_alias(reference):
    return f'reused_{canonical_digest(reference.to_dict())[:48]}'


def _bound_reference(spec, context):
    """The already-admitted reference a binding names, for diagnostics only."""
    binding = spec.binding
    if binding.existing_result is not None:
        reference = (getattr(context, 'result_aliases', None) or {}).get(binding.existing_result)
        return reference if type(reference) is ResultRef else None
    task = context.task_results.get(binding.step_id)
    if type(task) is not TaskResult:
        return None
    try:
        return task.output(binding.output_name)
    except ResultContractError:
        return None


def resolve_step_inputs(step, context):
    """Only declared, authorized inputs; a recovered old attempt needs an admitted alias."""
    service = require_result_service(context)
    consumer = context.result_producer(step)
    readers = {}
    for spec in step_input_specs(step):
        if spec.optional and spec.binding.step_id is not None and spec.binding.step_id not in context.task_results:
            # The optional producer did not complete. Its consumer runs without a reader and
            # discloses the gap; a failed or partial result is never made readable.
            continue
        producer_step_id = spec.binding.step_id
        if spec.binding.step_id is not None:
            task = context.task_results.get(spec.binding.step_id)
            if isinstance(task, TaskResult) and (
                task.producer.run_id != consumer.run_id or task.producer.attempt_index != consumer.attempt_index
            ):
                reference = task.output(spec.binding.output_name)
                alias = reuse_alias(reference)
                if context.result_aliases.get(alias) != reference:
                    raise ResultContractError('result_attempt_mismatch')
                spec = replace(spec, binding=InputBinding(existing_result=alias))
        try:
            reader = service.resolve_input(
                spec, consumer=consumer, task_results=context.task_results,
                existing_results=context.result_aliases,
            )
            reader = service.open_result(
                reader.reference, allow_partial=spec.allow_partial, require_current_sources=True,
            )
        except ResultNotReadyError as exc:
            # A complete-only input is never opened on a partial result; say which producer.
            if exc.status == 'partial' and not exc.preview and not spec.allow_partial:
                raise PartialInputNotAcceptedError(
                    _bound_reference(spec, context), producer_step_id=producer_step_id,
                ) from exc
            raise
        reader.recheck()
        readers[spec.name] = reader
    return readers


def read_complete_input(reader, *, max_bytes=MAX_VALUE_BYTES):
    """Exhaust the authoritative reader, including its final integrity/access checks."""
    if reader.reference.size_bytes > max_bytes:
        raise ResultContractError('result_requires_streaming')
    kind = reader.result_kind
    if kind in ('text-v1', 'markdown-v1'):
        return reader.read_text(max_bytes=max_bytes)
    if kind in ('structured-v1', 'comparison-v1', IMAGE_ASSET_KIND):
        return reader.read_value(max_bytes=max_bytes)
    values = []
    size = 2
    iterator = reader.iter_records() if kind == 'records-v1' else reader.iter_items()
    for item in iterator:
        size += len(canonical_bytes(item)) + int(bool(values))
        if size > max_bytes:
            raise ResultContractError('result_requires_streaming')
        values.append(item)
    return values


def _search_evidence_citations(reader, prepared):
    """Associate the selected excerpts with locators from their exact producer sidecar."""
    if 'search_results' not in prepared:
        # Older bounded envelopes did not retain the hit-to-excerpt association.
        return []
    hits = prepared['search_results']
    citations = prepared['citations']
    if type(hits) is not list or len(hits) != len(citations):
        raise ResultContractError('result_citations_invalid')
    evidence = read_complete_input(reader)
    if len(evidence) != len(hits):
        raise ResultContractError('result_citations_invalid')
    associated = []
    for index, (excerpt, hit, citation) in enumerate(zip(evidence, hits, citations)):
        if (
            type(hit) is not dict or type(citation) is not dict
            or excerpt['evidence_id'] != f'excerpt-{index}'
            or excerpt['source']['document_id'] != hit.get('document_id')
            or excerpt['text'] != hit.get('chunk_text')
            or citation.get('document_id') != hit.get('document_id')
            or citation.get('citation_id') != (hit.get('id') or hit.get('chunk_id'))
            or any(
                citation.get(field) != hit.get(field)
                for field in ('page_number', 'chunk_sequence')
            )
        ):
            raise ResultContractError('result_citations_invalid')
        associated.append({**citation, 'evidence_id': excerpt['evidence_id']})
    return associated


def read_result_document_citations(context, reference, *, evidence_status_out=None):
    """Project document provenance from the exact final result, never ambient work."""
    service = require_result_service(context)
    with service.read_operation():
        return _read_result_document_citations(service, reference, evidence_status_out=evidence_status_out)


def read_result_evidence_status(context, reference):
    """Read returned Search evidence from the answer's verified lineage, not ambient work."""
    service = require_result_service(context)
    outcome = {}
    with service.read_operation():
        _read_result_document_citations(service, reference, evidence_status_out=outcome)
    return outcome.get("value")


def read_result_source_coverage(context, reference):
    """Project bounded source/page coverage from the exact producer manifest when available."""
    service = require_result_service(context)
    producer = getattr(reference, 'producer', None)
    capability_id = getattr(producer, 'capability_id', None)
    if capability_id not in ('document_search', 'document_analyze', 'document_compare'):
        return None
    if getattr(reference, 'output_name', None) in ('prepared', 'coverage'):
        return None
    try:
        manifest = service._load_manifest(reference)
        if manifest.get('producer') != producer.to_dict():
            return None
        if capability_id == 'document_search':
            descriptor = (manifest.get('outputs') or {}).get('prepared')
            if descriptor is None:
                return None
            prepared_reader = service.open_result(
                _reference(producer, 'prepared', descriptor, reference.manifest_sha256),
                allow_partial=True, require_current_sources=True,
            )
            prepared = read_complete_input(prepared_reader)
            if type(prepared) is dict and type(prepared.get('coverage')) is dict:
                return deepcopy(prepared['coverage'])
        elif capability_id in ('document_analyze', 'document_compare'):
            descriptor = (manifest.get('outputs') or {}).get('coverage')
            if descriptor is None:
                return None
            coverage_reader = service.open_result(
                _reference(producer, 'coverage', descriptor, reference.manifest_sha256),
                allow_partial=True, require_current_sources=True,
            )
            coverage_payload = read_complete_input(coverage_reader)
            if type(coverage_payload) is dict:
                summary = {}
                if type(coverage_payload.get('coverage')) is dict:
                    raw_cov = coverage_payload['coverage']
                    summary['coverage'] = {
                        key: deepcopy(raw_cov[key])
                        for key in (
                            'document_count', 'total_windows', 'processed_windows', 'failed_windows',
                            'total_chunks', 'processed_chunks', 'window_unit',
                            'assigned_sources', 'completed_sources', 'assigned_work_units', 'completed_work_units',
                        )
                        if key in raw_cov
                    }
                    if isinstance(raw_cov.get('documents'), list):
                        summary['documents'] = [
                            {
                                key: doc.get(key)
                                for key in (
                                    'document_id', 'file_name', 'document_name', 'total_pages',
                                    'total_windows', 'processed_windows', 'total_chunks', 'processed_chunks', 'status',
                                )
                                if isinstance(doc, dict) and doc.get(key) is not None
                            }
                            for doc in raw_cov['documents'] if isinstance(doc, dict)
                        ]
                if type(coverage_payload.get('validation')) is dict:
                    val_cov = coverage_payload['validation'].get('coverage')
                    if type(val_cov) is dict and 'coverage' not in summary:
                        summary['coverage'] = {
                            key: deepcopy(val_cov[key])
                            for key in (
                                'assigned_sources', 'completed_sources',
                                'assigned_work_units', 'completed_work_units', 'failed_work_units',
                            )
                            if key in val_cov
                        }
                if isinstance(coverage_payload.get('sources'), list):
                    summary['sources'] = [
                        {
                            key: src.get(key)
                            for key in ('document_id', 'file_name', 'scope')
                            if isinstance(src, dict) and src.get(key) is not None
                        }
                        for src in coverage_payload['sources'] if isinstance(src, dict)
                    ]
                return summary or None
    except Exception:
        return None
    return None


def _read_result_document_citations(service, reference, *, evidence_status_out=None):
    root = service.open_result(reference, allow_partial=True, require_current_sources=True)
    if root.metadata()['source_count'] == 0:
        return []
    sources, citations, visited, expanded = {}, {}, set(), set()
    coverage_values = {}
    search_counts, source_names = {}, {}
    citation_fields = (
        'citation_id', 'chunk_id', 'file_name', 'title', 'page_number', 'chunk_sequence',
        'sheet_name', 'location_label', 'location_value', 'classification', 'document_classification', 'score',
        'evidence_id',
    )

    def source_key(source):
        return source['scope'], source['scope_id'], source['document_id']

    def project(source, citation=None):
        value = {
            key: deepcopy(citation[key]) for key in citation_fields
            if citation is not None and key in citation
        }
        value.update({
            'source_type': 'document', 'document_id': source['document_id'],
            'scope': {'type': source['scope'], 'id': source['scope_id']},
            'group_id': source['scope_id'] if source['scope'] == 'group' else None,
            'public_workspace_id': source['scope_id'] if source['scope'] == 'public' else None,
        })
        return value

    def visit(current):
        if current in visited:
            return
        visited.add(current)
        reader = service.open_result(current, allow_partial=True, require_current_sources=True)
        producer = current.producer
        # Reuse only this operation's verified manifest, still checking each output descriptor.
        manifest = service._load_manifest(current)
        reader.recheck()
        if manifest['producer'] != producer.to_dict():
            raise ResultContractError('result_reference_mismatch')
        lineage = manifest['lineage']
        key = producer, current.manifest_sha256
        if key not in expanded:
            expanded.add(key)
            if len(expanded) > MAX_LINEAGE_RESULTS:
                raise ResultContractError('result_lineage_limit')
            for source in lineage['sources']:
                sources.setdefault(source_key(source), source)
            for parent in lineage['upstream']:
                visit(ResultRef.from_dict(parent))
        retained_citations = []
        if (
            producer.capability_id == 'document_search'
            and (current.output_name, current.kind) in (
                ('prepared', 'structured-v1'), ('evidence', 'evidence-set-v1'),
            )
        ):
            descriptor = manifest['outputs'].get('prepared')
            if descriptor is not None:
                # Like native coverage, this sidecar belongs to the selected producer
                # and digest, not an undeclared sibling task or a newer search result.
                prepared_reader = reader if current.output_name == 'prepared' else service.open_result(
                    _reference(producer, 'prepared', descriptor, current.manifest_sha256),
                    allow_partial=True, require_current_sources=True,
                )
                prepared = read_complete_input(prepared_reader)
                if (
                    prepared_reader.result_kind != 'structured-v1'
                    or type(prepared) is not dict
                    or prepared.get('version') != 'orchestration-gathered-content-v1'
                    or prepared.get('capability_id') != 'document_search'
                    or prepared.get('content_scope') != 'returned_excerpts'
                    or type(prepared.get('citations')) is not list
                ):
                    raise ResultContractError('result_citations_invalid')
                retained_citations = (
                    _search_evidence_citations(reader, prepared)
                    if current.output_name == 'evidence' else prepared['citations']
                )
                for source in lineage['sources']:
                    search_counts.setdefault(source_key(source), set())
        elif producer.capability_id in ('document_analyze', 'document_compare'):
            # Coverage is this producer's citation sidecar, not an implicit input from
            # another task. Reopen the exact committed digest, including after recovery.
            descriptor = manifest['outputs'].get('coverage')
            if descriptor is not None:
                if key not in coverage_values:
                    coverage_reader = service.open_result(
                        _reference(producer, 'coverage', descriptor, current.manifest_sha256),
                        allow_partial=True, require_current_sources=True,
                    )
                    coverage_values[key] = read_complete_input(coverage_reader)
                coverage = coverage_values[key]
                if type(coverage) is not dict or type(coverage.get('citations', [])) is not list:
                    raise ResultContractError('result_citations_invalid')
                retained_citations = coverage.get('citations', [])
        for citation in retained_citations:
            if type(citation) is not dict or citation.get('source_type') not in (None, 'document'):
                raise ResultContractError('result_citations_invalid')
            matches = [
                source for source in lineage['sources']
                if source['document_id'] == citation.get('document_id')
                and (not citation.get('group_id') or (
                    source['scope'] == 'group' and source['scope_id'] == citation['group_id']
                ))
                and (not citation.get('public_workspace_id') or (
                    source['scope'] == 'public' and source['scope_id'] == citation['public_workspace_id']
                ))
            ]
            if len(matches) != 1:
                raise ResultContractError('result_citation_source_invalid')
            projected = project(matches[0], citation)
            identity_key = source_key(matches[0])
            if isinstance(citation.get('file_name'), str) and citation['file_name'].strip():
                source_names[identity_key] = citation['file_name'].strip()
            if producer.capability_id == 'document_search' and identity_key in search_counts:
                search_counts[identity_key].add((
                    producer, current.manifest_sha256,
                    canonical_digest({name: value for name, value in projected.items() if name != 'evidence_id'}),
                ))
            identity = {key: value for key, value in projected.items() if key != 'evidence_id'}
            citations.setdefault(source_key(matches[0]), {}).setdefault(
                canonical_digest(identity), projected,
            )
        reader.recheck()

    visit(reference)
    projected = []
    for key, source in sources.items():
        projected.extend(citations[key].values() if key in citations else [project(source)])
    if len(canonical_bytes(projected)) > MAX_DESCRIPTOR_BYTES:
        raise ResultContractError('result_citations_too_large')
    root.recheck()
    if evidence_status_out is not None:
        rows = []
        for index, (identity, source) in enumerate(sources.items(), start=1):
            count = len(search_counts[identity]) if identity in search_counts else None
            row = {
                "name": str(source_names.get(identity) or source.get("file_name") or f"Selected source {index}")[:160],
                "document_id": source["document_id"],
                "state": "missing" if count == 0 else "complete" if count is not None else "unknown",
            }
            if count is not None:
                row["evidence_count"] = count
            rows.append(row)
        evidence_status_out["value"] = evidence_status_from_sources(rows)
    return projected


def _authorize_task_result(step, context, task, *, reused=False):
    if type(task) is not TaskResult:
        raise ResultContractError('result_contract_invalid')
    capability = get_capability(step['capability_id'], contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)
    expected = context.result_producer(step)
    if task.role != capability['role'] or (not reused and task.producer != expected):
        raise ResultContractError('result_producer_mismatch')
    if reused and any(
        getattr(task.producer, field) != getattr(expected, field)
        for field in ('user_id', 'conversation_id', 'step_id', 'capability_id', 'contract_version')
    ):
        raise ResultContractError('result_producer_mismatch')
    if reused and (task.producer.run_id, task.producer.attempt_index) != (expected.run_id, expected.attempt_index):
        if any(context.result_aliases.get(reuse_alias(reference)) != reference for reference in task.outputs):
            raise ResultContractError('result_attempt_mismatch')
    service = require_result_service(context)
    service.access.authorize_producer(task.producer)
    return capability, service


def _allowed_task_outputs(step, capability):
    if capability['id'] == 'compose':
        return {output['name']: output['kind'] for output in step['outputs']}
    required, optional = get_capability_result_outputs(capability, step.get('arguments') or {})
    return {**required, **optional}


def validate_task_diagnostics(step, context, task):
    """Authorize a failed descriptor without treating its references as readable results."""
    capability, _ = _authorize_task_result(step, context, task)
    if task.status != 'failed':
        raise ResultContractError('result_contract_invalid')
    allowed = _allowed_task_outputs(step, capability)
    if any(allowed.get(reference.output_name) != reference.kind for reference in task.outputs):
        raise ResultContractError('result_output_missing')
    return task


def validate_task_outputs(step, context, task, *, reused=False):
    capability, service = _authorize_task_result(step, context, task, reused=reused)
    if task.status in ('complete', 'partial'):
        declared = {output['name']: output['kind'] for output in step['outputs']}
        actual = {reference.output_name: reference.kind for reference in task.outputs}
        allowed = _allowed_task_outputs(step, capability)
        if any(actual.get(name) != kind for name, kind in declared.items()) or any(
            allowed.get(name) != kind for name, kind in actual.items()
        ):
            raise ResultContractError('result_output_missing')
        for reference in task.outputs:
            service.open_result(
                reference, allow_partial=task.status == 'partial', require_current_sources=True,
            ).recheck()
    elif task.status != 'pending' or task.outputs:
        raise ResultContractError('result_not_ready')
    return task


def encode_step_result(result, *, retained_only=False):
    encoded = deepcopy(result)
    task = encoded.get('task_result')
    if task is not None:
        if type(task) is not TaskResult:
            raise ResultContractError('result_contract_invalid')
        encoded['task_result'] = task.to_dict()
    if retained_only:
        for key in ('evidence', 'notes', 'citations'):
            encoded[key] = []
        encoded.pop('message', None)
    return encoded


def decode_step_result(result):
    decoded = deepcopy(result)
    if 'task_result' in decoded:
        decoded['task_result'] = TaskResult.from_dict(decoded['task_result'])
    return decoded


def _complete(count, limitations=(), *, partial=False):
    return Completeness(
        'partial' if partial else 'complete', count, count,
        Coverage(None if partial else 1, 0 if partial else 1, 'work_units'),
        'partial' if partial else 'valid', ('retained_adapter_output',), tuple(limitations),
    )


def retain_document_search_result(step, context, results, *, source_manifest, citations, search_scope):
    """Commit returned hits before any presentation envelope can shorten them.

    Completion covers the returned response and its discovered identities, not every
    match in an index or the complete contents of the discovered documents.
    """
    service = require_result_service(context)
    sources = analysis_source_snapshot(source_manifest)
    by_id = {source['document_id']: source for source in sources}
    if (
        len(by_id) != len(sources)
        or any(source.get('authorization_status') != 'authorized' for source in source_manifest)
        or set(by_id) != {hit.get('document_id') for hit in results}
    ):
        raise ResultUnavailableError('result_source_unavailable')
    prior = {source['document_id']: source for source in context.execution_manifest}
    for source in sources:
        original = prior.get(source['document_id'])
        if original and any(
            original.get(key) != source.get(key)
            for key in ('scope', 'scope_id', 'source_version', 'source_revision', 'content_sha256')
        ):
            raise ResultUnavailableError('result_source_snapshot_changed')
    limitations = (
        'Complete only for the returned search response and its discovered source identities.',
        'Top-N retrieval is not exhaustive corpus discovery or whole-document coverage.',
    )
    retained, grouped = [], {}
    for index, hit in enumerate(results):
        if type(hit) is not dict or type(hit.get('chunk_text')) is not str:
            raise ResultContractError('result_evidence_invalid')
        source = by_id[hit['document_id']]
        retained.append({'evidence_id': f'excerpt-{index}', 'source': source, 'text': hit['chunk_text']})
        grouped.setdefault(hit['document_id'], []).append({
            key: deepcopy(hit.get(key)) for key in ('chunk_text', 'page_number', 'chunk_sequence', 'score')
        })
    returned_pages = []
    seen_pages = set()
    for hit in results:
        page_num = hit.get('page_number') if type(hit) is dict else None
        if page_num is not None and page_num != '' and not isinstance(page_num, bool) and page_num not in seen_pages:
            seen_pages.add(page_num)
            returned_pages.append(page_num)
    prepared = {
        'version': 'orchestration-gathered-content-v1', 'capability_id': 'document_search',
        'content_scope': 'returned_excerpts',
        'evidence': [
            {'document_id': document_id, 'status': 'completed', 'evidence': hits}
            for document_id, hits in grouped.items()
        ],
        'notes': [], 'citations': deepcopy(citations), 'limitations': list(limitations),
        'search_results': deepcopy(results),
        'search_scope': deepcopy(search_scope),
        'coverage': {
            'returned_excerpt_count': len(results), 'discovered_source_count': len(sources),
            'returned_page_count': len(returned_pages),
            'pages_in_returned_excerpts': returned_pages,
            'whole_document_coverage': False, 'exhaustive_corpus_coverage': False,
        },
    }
    return service.persist_task_result(
        producer=context.result_producer(step), role='gather', status='complete',
        outputs=[
            NamedOutput('evidence', 'evidence-set-v1', retained, Completeness(
                'complete', len(retained), len(retained), Coverage(len(retained), len(retained), 'items'),
                'valid', ('lossless_search_response',), limitations,
            )),
            NamedOutput('sources', 'source-set-v1', sources, Completeness(
                'complete', len(sources), len(sources), Coverage(len(sources), len(sources), 'sources'),
                'valid', ('authorized_discovered_source_identities',), limitations,
            )),
            NamedOutput('prepared', 'structured-v1', prepared, _complete(1, limitations)),
        ],
        sources=sources, origin='grounded' if sources else 'generated',
        guard_token=context.result_guard_token_for_step(step['step_id']),
        input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
    )


def source_selection_provenance(context):
    """Keep a search-selected Analyze scoped to those sources, not an entire corpus."""
    reader = getattr(context, 'source_selection_reader', None)
    if reader is None:
        return (), ()
    if reader.result_kind != 'source-set-v1':
        raise ResultContractError('result_input_kind_mismatch')
    reader.completeness.require_readable()
    reader.recheck()
    return (reader.reference,), reader.completeness.limitations


def retain_gather_result(step, context, result, *, source_manifest):
    """Retain exact returned excerpts/notes, never relabel them whole-document data."""
    if type(result) is not dict or result.get('status') not in ('completed', 'partial'):
        raise ResultContractError('result_not_ready')
    service = require_result_service(context)
    capability_id = step['capability_id']
    sources = analysis_source_snapshot(source_manifest)
    evidence = deepcopy(result.get('evidence') or [])
    citations = deepcopy(result.get('citations') or [])
    notes = deepcopy(result.get('notes') or [])
    partial = result.get('status') == 'partial' or any(
        entry.get('status') != 'completed'
        or (entry.get('coverage') or {}).get('evidence_envelope_truncated')
        or (entry.get('coverage') or {}).get('coverage_truncated')
        for entry in evidence
    )
    limitations = [
        'These are the returned search excerpts or integration findings, not whole-source coverage.',
    ]
    if partial:
        limitations.append('The producing service returned a bounded or incomplete evidence subset.')
    prepared = {
        'version': 'orchestration-gathered-content-v1',
        'capability_id': capability_id,
        'content_scope': 'returned_excerpts' if capability_id == 'document_search' else 'reported_external_content',
        'evidence': evidence, 'notes': notes, 'citations': citations,
        'limitations': limitations,
    }
    if result.get('operation_receipts'):
        prepared['operation_receipts'] = deepcopy(result['operation_receipts'])
    readers = getattr(context, 'integration_input_readers', {})
    for reader in readers.values():
        reader.recheck()
    outputs = []
    external_sources = ()
    if capability_id == 'document_search':
        by_id = {source['document_id']: source for source in sources}
        retained = []
        for envelope_index, envelope in enumerate(evidence):
            source = by_id.get(envelope.get('document_id'))
            if source is None:
                raise ResultContractError('result_source_not_in_lineage')
            for item_index, item in enumerate(envelope.get('evidence') or []):
                if type(item) is not dict or type(item.get('chunk_text')) is not str:
                    raise ResultContractError('result_evidence_invalid')
                retained.append({
                    'evidence_id': f'excerpt-{envelope_index}-{item_index}',
                    'source': source, 'text': item['chunk_text'],
                })
        outputs.extend((
            NamedOutput('evidence', 'evidence-set-v1', retained, _complete(len(retained), limitations, partial=partial)),
            NamedOutput('sources', 'source-set-v1', sources, _complete(len(sources), limitations, partial=partial)),
        ))
    else:
        admission = getattr(context, 'external_source_admission', None)
        if (
            sources or not callable(admission)
            or not callable(service.access.external_source_authorizer)
        ):
            raise ResultContractError('result_external_lineage_unsupported')
        admitted = admission(producer=context.result_producer(step), prepared=deepcopy(prepared))
        if type(admitted) is not dict or not admitted:
            raise ResultContractError('result_external_catalog_invalid')
        catalog = dict(service.access.external_source_catalog)
        for alias, reference in admitted.items():
            output_name(alias)
            if type(reference) is not ExternalSourceRef:
                raise ResultContractError('result_external_reference_untrusted')
            if alias in catalog and catalog[alias] != reference:
                raise ResultContractError('result_external_catalog_invalid')
            catalog[alias] = reference
        if len(catalog) > MAX_EXTERNAL_SOURCES:
            raise ResultContractError('result_external_catalog_invalid')
        service.access.external_source_catalog.update(admitted)
        external_sources = tuple(admitted)
    outputs.append(NamedOutput('prepared', 'structured-v1', prepared, _complete(1, limitations, partial=partial)))
    return service.persist_task_result(
        producer=context.result_producer(step), role='gather', status='partial' if partial else 'complete',
        outputs=outputs, sources=sources, origin='grounded' if sources or external_sources else 'generated',
        guard_token=context.result_guard_token_for_step(step['step_id']),
        input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
        upstream=tuple(dict.fromkeys(reader.reference for reader in readers.values())),
        **({'external_sources': external_sources} if external_sources else {}),
    )
