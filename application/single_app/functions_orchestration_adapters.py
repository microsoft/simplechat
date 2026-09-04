# functions_orchestration_adapters.py

"""
The bridge between a planned step and the function that already does the work.

Every capability the planner can name maps to one adapter here, and every adapter has the
same signature so the executor never special-cases a capability:

    run(step, context, *, settings, user_id, emit, cancel_requested) -> StepResult

The adapters wrap functions that predate this framework -- hybrid search, document analysis,
document comparison, the tabular orchestrator, the route's web search -- rather than
reimplementing them. That is the point of the whole design: the planner chooses among
described capabilities and an adapter translates one described step into one existing call,
so the surface the model reasons over stays tiny while the machinery underneath stays the
proven machinery.

Three rules hold for all of them, because the executor depends on them and cannot check them:

**An adapter never raises.** A wrapped function that throws becomes a ``failed`` step result,
not an exception out of the executor. One capability failing must not abandon a plan that
could still answer from the others.

**An adapter returns only through ``build_step_result``.** That is the single shape the
executor merges and the schema owns; an adapter that returned a bare dict would drift from it
silently.

**Web search is not evidence.** It fits no evidence-envelope engine -- it is neither a
tabular tool nor a document analysis over an authorized source -- so its results ride
``notes`` and ``citations`` instead. Forcing it into an envelope would put unauthorized
web text through the authorized-source coverage ledger, which is exactly the confusion the
envelope contract exists to prevent.

The heavy wrapped functions are imported lazily inside each adapter body. Two of them would
otherwise make this module unimportable without Azure and config -- and ``perform_web_search``
lives in ``route_backend_chats``, importing which at module load would be a circular import --
so the same lazy pattern is used uniformly rather than only where it is strictly forced.

Version: 0.261.085
"""

import logging

from functions_appinsights import log_event
from functions_mixed_source_orchestration import (
    AUTHORIZATION_STATUS_AUTHORIZED,
    EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
    EVIDENCE_ENGINE_TABULAR_TOOLS,
    EVIDENCE_STATUS_COMPLETED,
    EVIDENCE_STATUS_FAILED,
    EVIDENCE_STATUS_PARTIAL,
    MixedSourceCancellationError,
    SELECTION_MODE_SELECTED,
    SOURCE_KIND_NARRATIVE,
    SOURCE_KIND_TABULAR,
    build_evidence_envelope,
    build_mixed_source_evidence_handoff,
    build_narrative_evidence_envelopes,
    build_tabular_file_contexts_from_manifest,
    partition_source_manifest,
)
from functions_orchestration_registry import (
    CAPABILITY_DOCUMENT_ANALYZE,
    CAPABILITY_DOCUMENT_COMPARE,
    CAPABILITY_DOCUMENT_SEARCH,
    CAPABILITY_RESPOND,
    CAPABILITY_TABULAR_ANALYZE,
    CAPABILITY_WEB_SEARCH,
    DOCUMENT_ACTION_TYPE_COMPARISON,
)
from functions_orchestration_schema import (
    STEP_STATUS_CANCELLED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    build_step_result,
)

_LOG_PREFIX = '[ORCHESTRATION_ADAPTERS]'

# The synthesis fallback when the model returns nothing. A visible sentence beats an empty
# assistant turn, which reads as the feature having silently broken.
_EMPTY_ANSWER = "I wasn't able to produce an answer for this request."


# --------------------------------------------------------------------------------------
# Small shared helpers. Adapters read the context by duck typing rather than importing the
# executor's RunContext, which would be a circular import; anything the context does not
# carry simply falls back to a default.
# --------------------------------------------------------------------------------------

def _ctx(context, name, default=None):
    return getattr(context, name, default)


def _text(value, limit=None):
    if value is None:
        return ''
    text = str(value).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    out = []
    seen = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _arguments(step):
    arguments = (step or {}).get('arguments')
    return arguments if isinstance(arguments, dict) else {}


def _selection_mode(context):
    return _text(_ctx(context, 'selection_mode', None)) or SELECTION_MODE_SELECTED


def _is_cancelled(cancel_requested):
    # A cancellation probe that itself throws must not be read as "cancelled"; the run keeps
    # going rather than aborting on a flaky signal.
    if not callable(cancel_requested):
        return False
    try:
        return bool(cancel_requested())
    except Exception:
        return False


def _emit(emit, event):
    if not callable(emit):
        return
    try:
        emit(event)
    except Exception:
        # Progress is advisory. A failed emit must never turn into a failed step.
        pass


def _first_line(text):
    for line in _text(text).splitlines():
        line = line.strip()
        if line:
            return line[:280]
    return ''


def _cancelled_result(summary):
    return build_step_result(status=STEP_STATUS_CANCELLED, summary=summary)


def _failed_result(summary, error, replan_hint=None):
    return build_step_result(
        status=STEP_STATUS_FAILED,
        summary=summary,
        error=error,
        replan_hint=replan_hint,
    )


def _progress(step, capability_id, label, status='running'):
    step = step or {}
    return {
        'phase': status,
        'capability_id': capability_id,
        'step_id': step.get('step_id'),
        'title': step.get('title') or label,
        'label': label,
    }


# --------------------------------------------------------------------------------------
# Source manifest resolution, shared with the executor's re-authorization.
# --------------------------------------------------------------------------------------

def resolve_context_source_manifest(
    context,
    document_ids,
    *,
    settings=None,
    user_id=None,
    cancel_requested=None,
    selection_mode=None,
):
    """Resolve document ids into an authorized source manifest.

    A resolver injected on the context wins, which is how the route hands in a pre-scoped
    resolver and how the executor's tests simulate access being revoked mid-run without an
    Azure round trip. Only when none is present does this fall back to the real resolver,
    imported lazily so this module stays importable without config.
    """
    ids = _string_list(document_ids)
    if not ids:
        return []

    resolver = _ctx(context, 'resolve_source_manifest', None)
    selection = selection_mode or _selection_mode(context)
    if callable(resolver):
        return list(resolver(ids) or [])

    from functions_mixed_source_orchestration import resolve_authorized_source_manifest

    return list(resolve_authorized_source_manifest(
        ids,
        user_id or _ctx(context, 'user_id', None),
        selection_mode=selection,
        conversation_id=_ctx(context, 'conversation_id', None),
        active_group_ids=_ctx(context, 'active_group_ids', None),
        active_public_workspace_ids=_ctx(context, 'active_public_workspace_id', None),
        doc_scope=_ctx(context, 'doc_scope', 'all'),
        cancel_requested=cancel_requested,
        request_correlation_id=_ctx(context, 'request_correlation_id', None),
    ) or [])


def synthesize_source_manifest_from_evidence(evidence_envelopes):
    """A minimal authorized manifest that just names the documents evidence came from.

    The coverage ledger only carries an envelope whose document is present in the manifest;
    an empty manifest would drop every envelope as unexpected. When no real manifest is
    available -- a search-only turn, or a resolver that could not run -- this lets the
    handoff still carry the evidence the adapters actually gathered, using each envelope's
    own source_kind so the ledger's kind check still matches. It is a fallback, not an
    authorization decision: the executor uses it only after re-authorization has run or been
    found unavailable.
    """
    manifest = []
    seen = set()
    for envelope in evidence_envelopes or ():
        if not isinstance(envelope, dict):
            continue
        document_id = _text(envelope.get('document_id'))
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        source_kind = envelope.get('source_kind')
        if source_kind not in (SOURCE_KIND_TABULAR, SOURCE_KIND_NARRATIVE):
            source_kind = SOURCE_KIND_NARRATIVE
        manifest.append({
            'document_id': document_id,
            'display_name': envelope.get('display_name'),
            'source_kind': source_kind,
            'scope': None,
            'scope_id': None,
            'source_version': None,
            'authorization_status': AUTHORIZATION_STATUS_AUTHORIZED,
        })
    return manifest


# --------------------------------------------------------------------------------------
# document_search -> functions_search.hybrid_search
# --------------------------------------------------------------------------------------

def _citations_from_search_results(results):
    citations = []
    for result in results or ():
        if not isinstance(result, dict):
            continue
        citations.append({
            'source_type': 'document',
            'document_id': result.get('document_id'),
            'citation_id': result.get('id') or result.get('chunk_id'),
            'file_name': result.get('file_name'),
            'title': result.get('title'),
            'page_number': result.get('page_number'),
            'chunk_sequence': result.get('chunk_sequence'),
            'score': result.get('score'),
        })
    return citations


def run_document_search(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    query = _text(arguments.get('query')) or _text(_ctx(context, 'user_message', ''))
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before searching documents.')
    if not query:
        return _failed_result('No search query was available.', 'document_search requires a query.')

    _emit(emit, _progress(step, CAPABILITY_DOCUMENT_SEARCH, 'Searching documents'))
    try:
        from functions_search import hybrid_search

        requested_ids = _string_list(arguments.get('document_ids'))
        results = hybrid_search(
            query,
            user_id,
            document_ids=requested_ids or None,
            top_n=_coerce_int(arguments.get('top_n'), 12),
            doc_scope=_text(arguments.get('doc_scope')) or _ctx(context, 'doc_scope', 'all'),
            active_group_ids=_ctx(context, 'active_group_ids', None) or None,
            active_public_workspace_id=_ctx(context, 'active_public_workspace_id', None),
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} document_search failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Document search failed.', str(exc))

    results = list(results or [])
    document_ids = []
    for result in results:
        document_id = _text((result or {}).get('document_id'))
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)

    narrative_sources = [{'document_id': document_id} for document_id in document_ids]
    envelopes = build_narrative_evidence_envelopes(
        narrative_sources, results, _selection_mode(context)
    )
    summary = (
        f'Retrieved {len(results)} excerpt(s) across {len(document_ids)} document(s).'
        if results
        else 'No matching document excerpts were found.'
    )
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=summary,
        evidence=envelopes,
        citations=_citations_from_search_results(results),
    )


# --------------------------------------------------------------------------------------
# document_analyze -> functions_document_analysis.run_document_analysis
# --------------------------------------------------------------------------------------

def _analysis_envelopes(result, requested_document_ids):
    result = result if isinstance(result, dict) else {}
    coverage_documents = (result.get('coverage') or {}).get('documents') or []
    documents_by_id = {
        _text(document.get('document_id')): document
        for document in coverage_documents
        if isinstance(document, dict)
    }
    items_by_id = {
        _text(item.get('document_id')): item
        for item in result.get('document_analysis_items') or []
        if isinstance(item, dict)
    }

    # The analysis may have expanded the requested ids (doc_scope='all'); trust what it
    # reports it actually covered, and only fall back to the request when it reports nothing.
    effective_ids = _string_list(result.get('document_ids')) or _string_list(requested_document_ids)

    envelopes = []
    for document_id in effective_ids:
        coverage = documents_by_id.get(document_id, {})
        item = items_by_id.get(document_id, {})
        total_windows = _coerce_int(coverage.get('total_windows'), 0)
        processed_windows = _coerce_int(coverage.get('processed_windows'), 0)
        failed_windows = _coerce_int(coverage.get('failed_windows'), 0)

        if total_windows and processed_windows >= total_windows and not failed_windows:
            status = EVIDENCE_STATUS_COMPLETED
        elif processed_windows:
            status = EVIDENCE_STATUS_PARTIAL
        else:
            status = EVIDENCE_STATUS_FAILED

        summary = _text(item.get('text'))
        envelopes.append(build_evidence_envelope(
            document_id=document_id,
            source_kind=SOURCE_KIND_NARRATIVE,
            engine=EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
            status=status,
            summary=summary or 'Document analysis produced no extractable summary for this source.',
            coverage={
                'terminal': True,
                'processed_windows': processed_windows,
                'total_windows': total_windows,
                'failed_windows': failed_windows,
            },
        ))
    return envelopes


def run_document_analyze(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    invoke_prompt = _ctx(context, 'invoke_prompt', None)
    if not callable(invoke_prompt):
        return _failed_result(
            'Document analysis is unavailable.',
            'document_analyze requires a callable invoke_prompt on the context.',
        )

    document_ids = _string_list(arguments.get('document_ids'))
    analysis_prompt = (
        _text(arguments.get('analysis_prompt'))
        or _text(arguments.get('prompt'))
        or _text(arguments.get('question'))
        or _text(_ctx(context, 'user_message', ''))
    )
    if not document_ids:
        return _failed_result('No documents were provided to analyze.', 'document_analyze requires document_ids.')
    if not analysis_prompt:
        return _failed_result('No analysis prompt was provided.', 'document_analyze requires an analysis prompt.')
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before document analysis.')

    _emit(emit, _progress(step, CAPABILITY_DOCUMENT_ANALYZE, 'Analyzing documents'))
    try:
        from functions_document_analysis import run_document_analysis

        result = run_document_analysis(
            user_id,
            analysis_prompt,
            document_ids,
            invoke_prompt,
            doc_scope=_text(arguments.get('doc_scope')) or _ctx(context, 'doc_scope', 'all'),
            active_group_ids=_ctx(context, 'active_group_ids', None),
            active_public_workspace_id=_ctx(context, 'active_public_workspace_id', None),
            conversation_id=_ctx(context, 'conversation_id', None),
            cancel_requested=cancel_requested,
            request_correlation_id=_ctx(context, 'request_correlation_id', None),
        )
    except MixedSourceCancellationError:
        return _cancelled_result('Document analysis was cancelled.')
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} document_analyze failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Document analysis failed.', str(exc))

    envelopes = _analysis_envelopes(result, document_ids)
    reply = _text((result or {}).get('reply') or (result or {}).get('analysis_reply'))
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=_first_line(reply) or 'Document analysis complete.',
        evidence=envelopes,
    )


# --------------------------------------------------------------------------------------
# document_compare -> functions_document_comparison.run_document_comparison
# --------------------------------------------------------------------------------------

def run_document_compare(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    invoke_prompt = _ctx(context, 'invoke_prompt', None)
    if not callable(invoke_prompt):
        return _failed_result(
            'Document comparison is unavailable.',
            'document_compare requires a callable invoke_prompt on the context.',
        )

    left_document_id = (
        _text(arguments.get('left_document_id'))
        or _text(arguments.get('source_document_id'))
    )
    right_document_ids = (
        _string_list(arguments.get('right_document_ids'))
        or _string_list(arguments.get('target_document_ids'))
    )
    comparison_prompt = (
        _text(arguments.get('comparison_prompt'))
        or _text(arguments.get('prompt'))
        or _text(arguments.get('question'))
        or _text(_ctx(context, 'user_message', ''))
    )
    if not left_document_id or not right_document_ids:
        return _failed_result(
            'Comparison needs a source document and at least one target document.',
            'document_compare requires left_document_id and right_document_ids.',
        )
    if not comparison_prompt:
        return _failed_result('No comparison prompt was provided.', 'document_compare requires a comparison prompt.')
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before document comparison.')

    action_config = {
        'type': DOCUMENT_ACTION_TYPE_COMPARISON,
        'left_document_id': left_document_id,
        'right_document_ids': right_document_ids,
        'doc_scope': _text(arguments.get('doc_scope')) or _ctx(context, 'doc_scope', 'all'),
        'active_group_ids': _ctx(context, 'active_group_ids', None),
        'active_public_workspace_id': _ctx(context, 'active_public_workspace_id', None),
    }

    _emit(emit, _progress(step, CAPABILITY_DOCUMENT_COMPARE, 'Comparing documents'))
    try:
        from functions_document_comparison import run_document_comparison

        result = run_document_comparison(
            user_id,
            comparison_prompt,
            action_config,
            invoke_prompt,
            conversation_id=_ctx(context, 'conversation_id', None),
            cancel_requested=cancel_requested,
            request_correlation_id=_ctx(context, 'request_correlation_id', None),
        )
    except MixedSourceCancellationError:
        return _cancelled_result('Document comparison was cancelled.')
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} document_compare failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Document comparison failed.', str(exc))

    result = result if isinstance(result, dict) else {}
    reply = _text(result.get('reply') or result.get('analysis_reply'))
    left = result.get('left_document') if isinstance(result.get('left_document'), dict) else {}
    resolved_left_id = _text(left.get('document_id')) or left_document_id
    left_label = _text(left.get('document_name')) or resolved_left_id

    # The comparison narrative belongs to the source document's envelope; each target gets a
    # light envelope so it is present in the coverage set and survives re-authorization,
    # rather than being invisible to the ledger despite having been compared.
    envelopes = [build_evidence_envelope(
        document_id=resolved_left_id,
        source_kind=SOURCE_KIND_NARRATIVE,
        engine=EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
        status=EVIDENCE_STATUS_COMPLETED if reply else EVIDENCE_STATUS_PARTIAL,
        summary=reply or 'Document comparison produced no narrative summary.',
        coverage={'terminal': True, 'comparison_role': 'source'},
    )]
    for right in result.get('right_documents') or []:
        right_id = _text((right or {}).get('document_id'))
        if not right_id:
            continue
        envelopes.append(build_evidence_envelope(
            document_id=right_id,
            source_kind=SOURCE_KIND_NARRATIVE,
            engine=EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
            status=EVIDENCE_STATUS_COMPLETED if reply else EVIDENCE_STATUS_PARTIAL,
            summary=f'Compared against source document {left_label}.',
            coverage={'terminal': True, 'comparison_role': 'target'},
        ))

    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=_first_line(reply) or 'Document comparison complete.',
        evidence=envelopes,
    )


# --------------------------------------------------------------------------------------
# tabular_analyze -> functions_tabular_analysis.orchestrate_tabular_request
# --------------------------------------------------------------------------------------

def _tabular_evidence_status(execution_state, reply, artifacts):
    if reply or artifacts:
        return EVIDENCE_STATUS_COMPLETED
    if execution_state in ('declined', 'failed', 'error'):
        return EVIDENCE_STATUS_FAILED
    return EVIDENCE_STATUS_PARTIAL


def run_tabular_analyze(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    document_ids = _string_list(arguments.get('document_ids'))
    question = (
        _text(arguments.get('question'))
        or _text(arguments.get('analysis_prompt'))
        or _text(arguments.get('prompt'))
        or _text(_ctx(context, 'user_message', ''))
    )
    if not document_ids:
        return _failed_result('No tabular documents were provided.', 'tabular_analyze requires document_ids.')
    if not question:
        return _failed_result('No question was provided for tabular analysis.', 'tabular_analyze requires a question.')
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before tabular analysis.')

    _emit(emit, _progress(step, CAPABILITY_TABULAR_ANALYZE, 'Analyzing tabular data'))
    try:
        manifest = resolve_context_source_manifest(
            context,
            document_ids,
            settings=settings,
            user_id=user_id,
            cancel_requested=cancel_requested,
        )
        tabular_sources = partition_source_manifest(manifest).get('tabular_sources') or []
        if not tabular_sources:
            # The planner named tabular sources but none resolved to authorized tabular files;
            # a replan hint lets the route try a narrative path rather than looping here.
            return _failed_result(
                'No authorized tabular sources were available for analysis.',
                'tabular_analyze resolved no authorized tabular sources.',
                replan_hint='The requested tabular sources were not available; consider a document analysis or search instead.',
            )

        file_contexts = build_tabular_file_contexts_from_manifest(tabular_sources)

        from functions_tabular_analysis import orchestrate_tabular_request

        result = orchestrate_tabular_request(
            question,
            file_contexts,
            action_mode='analyze',
            settings=settings,
            caller='chat_orchestration',
            durable_execution_callback=_ctx(context, 'durable_execution_callback', None),
            cancel_requested=cancel_requested,
            user_id=user_id,
            conversation_id=_ctx(context, 'conversation_id', None),
            gpt_model=_ctx(context, 'gpt_model', None),
            model_context=_ctx(context, 'model_context', None),
            request_correlation_id=_ctx(context, 'request_correlation_id', None),
        )
    except MixedSourceCancellationError:
        return _cancelled_result('Tabular analysis was cancelled.')
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} tabular_analyze failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Tabular analysis failed.', str(exc))

    result = result if isinstance(result, dict) else {}
    reply = _text(result.get('analysis_reply') or result.get('reply'))
    generated = result.get('generated_output_metadata')
    artifacts = [generated] if isinstance(generated, dict) else []
    execution_state = _text(result.get('execution_state')).lower()
    envelope_status = _tabular_evidence_status(execution_state, reply, artifacts)

    envelopes = []
    for index, source in enumerate(tabular_sources):
        document_id = _text((source or {}).get('document_id'))
        if not document_id:
            continue
        envelopes.append(build_evidence_envelope(
            document_id=document_id,
            source_kind=SOURCE_KIND_TABULAR,
            engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
            status=envelope_status,
            summary=(reply if index == 0 else 'See the combined tabular result for this source.'),
            generated_artifacts=artifacts if index == 0 else None,
            coverage={'terminal': True, 'tool_call_count': 1, 'execution_state': execution_state},
        ))

    step_status = STEP_STATUS_COMPLETED if (reply or artifacts) else STEP_STATUS_FAILED
    return build_step_result(
        status=step_status,
        summary=_first_line(reply) or 'Tabular analysis produced no result.',
        evidence=envelopes,
        artifacts=artifacts,
        error=None if step_status == STEP_STATUS_COMPLETED else 'Tabular analysis returned no answer or artifact.',
    )


# --------------------------------------------------------------------------------------
# web_search -> route_backend_chats.perform_web_search (lazy: circular import otherwise)
# --------------------------------------------------------------------------------------

def run_web_search(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    query = _text(arguments.get('query')) or _text(_ctx(context, 'user_message', ''))
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before web search.')
    if not query:
        return _failed_result('No web search query was available.', 'web_search requires a query.')

    active_group_ids = _ctx(context, 'active_group_ids', None) or []
    active_group_id = active_group_ids[0] if active_group_ids else _ctx(context, 'active_group_id', None)

    _emit(emit, _progress(step, CAPABILITY_WEB_SEARCH, 'Searching the web'))

    # These four lists are mutated in place by perform_web_search; that is its contract, so
    # we own them here and read the results back out afterwards rather than from a return.
    augmentation_messages = []
    agent_citations = []
    web_citations = []
    web_runs = []
    try:
        from route_backend_chats import perform_web_search

        ok = perform_web_search(
            settings=settings,
            conversation_id=_ctx(context, 'conversation_id', None),
            user_id=user_id,
            user_message=_text(_ctx(context, 'user_message', '')),
            user_message_id=_ctx(context, 'user_message_id', None),
            chat_type=_text(_ctx(context, 'chat_type', 'personal')) or 'personal',
            document_scope=_ctx(context, 'doc_scope', 'all'),
            active_group_id=active_group_id,
            active_public_workspace_id=_ctx(context, 'active_public_workspace_id', None),
            web_search_query_text=query,
            system_messages_for_augmentation=augmentation_messages,
            agent_citations_list=agent_citations,
            web_search_citations_list=web_citations,
            web_search_runs_list=web_runs,
            search_context_label='chat_orchestration',
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} web_search failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Web search failed.', str(exc))

    notes = [
        _text(message.get('content'))
        for message in augmentation_messages
        if isinstance(message, dict) and _text(message.get('content'))
    ]

    if ok is False:
        # perform_web_search returns False only for a genuine failure/misconfiguration; its
        # own explanatory system message is already in notes for the answer to use.
        return build_step_result(
            status=STEP_STATUS_FAILED,
            summary='Web search was unavailable.',
            notes=notes,
            citations=web_citations,
            error='Web search failed or is not configured.',
        )

    summary = (
        f'Web search returned {len(web_citations)} source(s).'
        if web_citations
        else 'Web search returned no results.'
    )
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=summary,
        notes=notes,
        citations=web_citations,
    )


# --------------------------------------------------------------------------------------
# respond -> synthesis over the accumulated evidence (terminal step)
# --------------------------------------------------------------------------------------

def _build_respond_prompt(user_message, instruction, notes, handoff_content):
    parts = []
    if instruction:
        parts.append(instruction)
    parts.append(
        f'User request:\n{user_message}' if user_message else 'User request: (not provided)'
    )
    if handoff_content:
        parts.append(handoff_content)
    extra_notes = [_text(note) for note in (notes or []) if _text(note)]
    if extra_notes:
        parts.append('Additional gathered context:\n' + '\n\n'.join(extra_notes))
    parts.append(
        'Write a single, well-structured answer for the user using only the evidence and '
        'context above. If the evidence is insufficient to answer, say so plainly rather '
        'than inventing details.'
    )
    return '\n\n'.join(parts)


def run_respond(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    invoke_prompt = _ctx(context, 'invoke_prompt', None)
    if not callable(invoke_prompt):
        return _failed_result(
            'The answer could not be written.',
            'respond requires a callable invoke_prompt on the context.',
        )
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before writing the answer.')

    _emit(emit, _progress(step, CAPABILITY_RESPOND, 'Writing the answer'))

    user_message = _text(_ctx(context, 'user_message', ''))
    instruction = _text(arguments.get('instruction') or arguments.get('prompt'))
    evidence = [envelope for envelope in (_ctx(context, 'evidence', []) or []) if isinstance(envelope, dict)]
    notes = list(_ctx(context, 'notes', []) or [])
    citations = list(_ctx(context, 'citations', []) or [])

    handoff_content = ''
    if evidence:
        # The executor sets source_manifest during re-authorization; the synthesized fallback
        # only fires when it could not, so the handoff still carries the gathered evidence.
        manifest = list(_ctx(context, 'source_manifest', []) or [])
        if not manifest:
            manifest = synthesize_source_manifest_from_evidence(evidence)
        try:
            handoff = build_mixed_source_evidence_handoff(
                manifest,
                evidence,
                _selection_mode(context),
                mode='chat_orchestration',
                telemetry_settings=settings,
                request_correlation_id=_ctx(context, 'request_correlation_id', None),
            )
            handoff_content = _text(handoff.get('content'))
        except Exception as exc:
            # A handoff that cannot be built must not lose the answer; fall back to notes.
            log_event(
                f'{_LOG_PREFIX} respond handoff build failed; answering without it: {exc}',
                extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
                level=logging.WARNING,
            )

    prompt = _build_respond_prompt(user_message, instruction, notes, handoff_content)
    try:
        reply = _text(invoke_prompt(
            prompt,
            stage='orchestration_respond',
            metadata={
                'run_id': _ctx(context, 'run_id', None),
                'step_id': (step or {}).get('step_id'),
            },
        ))
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} respond synthesis failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('The answer could not be written.', str(exc))

    reply = reply or _EMPTY_ANSWER
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=_first_line(reply),
        message=reply,
        citations=citations,
    )


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

# Keyed by capability id, which is also each descriptor's declared ``adapter`` name, so the
# executor can look an adapter up straight from the step's capability without a second map.
ADAPTER_REGISTRY = {
    CAPABILITY_DOCUMENT_SEARCH: run_document_search,
    CAPABILITY_DOCUMENT_ANALYZE: run_document_analyze,
    CAPABILITY_DOCUMENT_COMPARE: run_document_compare,
    CAPABILITY_TABULAR_ANALYZE: run_tabular_analyze,
    CAPABILITY_WEB_SEARCH: run_web_search,
    CAPABILITY_RESPOND: run_respond,
}


def get_adapter(name):
    """The adapter callable for a capability/adapter name, or ``None`` if unknown."""
    return ADAPTER_REGISTRY.get(name)
