# functions_orchestration_result_runtime.py
"""Typed runtime handoffs; no clients, model calls, publication, or new storage.

Version: 0.261.130
"""

from copy import deepcopy
from dataclasses import replace

from content_screening.contracts import DocumentHeldError, ScreeningError
from functions_analysis_access import analysis_source_snapshot
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationControlError, OrchestrationInvocationServiceError,
)
from functions_orchestration_registry import (
    DEPENDENCY_PLAN_CONTRACT_VERSION, get_capability, get_capability_result_outputs,
)
from functions_orchestration_result_contracts import (
    MAX_DESCRIPTOR_BYTES, MAX_EXTERNAL_SOURCES, Completeness, Coverage, ExternalSourceRef, InputBinding,
    ResultContractError, ResultRef, TaskResult, canonical_bytes, canonical_digest, output_name,
)
from functions_orchestration_results import MAX_LINEAGE_RESULTS, MAX_VALUE_BYTES, NamedOutput, OrchestrationResults
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


def resolve_step_inputs(step, context):
    """Only declared, authorized inputs; a recovered old attempt needs an admitted alias."""
    service = require_result_service(context)
    consumer = context.result_producer(step)
    readers = {}
    for spec in step_input_specs(step):
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
        reader = service.resolve_input(
            spec, consumer=consumer, task_results=context.task_results,
            existing_results=context.result_aliases,
        )
        reader = service.open_result(
            reader.reference, allow_partial=spec.allow_partial, require_current_sources=True,
        )
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
    if kind in ('structured-v1', 'comparison-v1'):
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


def read_result_document_citations(context, reference):
    """Project document provenance from the exact final result, never ambient work."""
    service = require_result_service(context)
    root = service.open_result(reference, allow_partial=True, require_current_sources=True)
    if root.metadata()['source_count'] == 0:
        return []
    sources, citations, visited, expanded = {}, {}, set(), set()
    citation_fields = (
        'citation_id', 'chunk_id', 'file_name', 'title', 'page_number', 'chunk_sequence',
        'sheet_name', 'location_label', 'location_value', 'classification', 'document_classification', 'score',
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
        # This public lookup selects the original digest; the facade owns all authorization.
        manifest = service.store.load_committed_orchestration_result(
            producer.user_id, producer.conversation_id, producer.run_id,
            producer.step_id, current.manifest_sha256,
        )
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
        if (
            producer.capability_id == 'document_search'
            and current.output_name == 'prepared' and current.kind == 'structured-v1'
        ):
            prepared = read_complete_input(reader)
            if (
                type(prepared) is not dict
                or prepared.get('version') != 'orchestration-gathered-content-v1'
                or prepared.get('capability_id') != 'document_search'
                or prepared.get('content_scope') != 'returned_excerpts'
                or type(prepared.get('citations')) is not list
            ):
                raise ResultContractError('result_citations_invalid')
            for citation in prepared['citations']:
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
                citations.setdefault(source_key(matches[0]), {}).setdefault(
                    canonical_digest(projected), projected,
                )
        reader.recheck()

    visit(reference)
    projected = []
    for key, source in sources.items():
        projected.extend(citations[key].values() if key in citations else [project(source)])
    if len(canonical_bytes(projected)) > MAX_DESCRIPTOR_BYTES:
        raise ResultContractError('result_citations_too_large')
    root.recheck()
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
        **({'external_sources': external_sources} if external_sources else {}),
    )
