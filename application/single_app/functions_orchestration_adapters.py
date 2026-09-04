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

**External content is not evidence.** Web search, reading a pasted URL, deep research over
discovered sources, and an invoked agent's reply all fit no evidence-envelope engine -- none
is a tabular tool or a document analysis over an authorized source -- so their results ride
``notes`` and ``citations`` instead. Forcing any of it into an envelope would put unauthorized
external text through the authorized-source coverage ledger, which is exactly the confusion
the envelope contract exists to prevent.

**A run adapter cannot touch Flask.** ``execute_plan`` runs in a worker thread with no request
context, so an adapter must never read ``g``, ``session`` or ``current_app``. Anything about
the caller a step needs -- their roles, their email, the agents they may invoke -- is read off
the ``context`` (a ``RunContext`` the route populated on the request thread), never from Flask.
The URL and agent adapters below exist precisely because the classic chat path for the same
work leans on ``g``; they re-express it against the context instead.

The heavy wrapped functions are imported lazily inside each adapter body. Several would
otherwise make this module unimportable without Azure and config -- and ``perform_web_search``
lives in ``route_backend_chats``, importing which at module load would be a circular import --
so the same lazy pattern is used uniformly rather than only where it is strictly forced.

Version: 0.261.087
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
    CAPABILITY_AGENT_INVOKE,
    CAPABILITY_DEEP_RESEARCH,
    CAPABILITY_DOCUMENT_ANALYZE,
    CAPABILITY_DOCUMENT_COMPARE,
    CAPABILITY_DOCUMENT_SEARCH,
    CAPABILITY_RESPOND,
    CAPABILITY_TABULAR_ANALYZE,
    CAPABILITY_URL_FETCH,
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
            # Which workspace the hit came from. The search index selects these per scope
            # and they were being dropped here, which left a found document with no home:
            # the composer groups its context chips by workspace, so a document the run
            # discovered could not be offered back to the user without one.
            'group_id': result.get('group_id'),
            'public_workspace_id': result.get('public_workspace_id'),
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
            # The tags the user picked, applied to every search in the run. A step is free
            # to choose its own query, but not to widen the shelf the user narrowed to.
            tags_filter=_ctx(context, 'tags', None) or None,
            document_filter_mode=_ctx(context, 'document_filter_mode', 'intersection'),
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
# url_fetch and deep_research -> functions_source_review.perform_source_review
#
# One function backs both capabilities. In url_access_only mode it reads only the links the
# user pasted; with that flag off it plans and crawls several pages toward a research question.
# Both return the same shape, so a single finalizer turns either into notes and citations.
# perform_source_review is imported lazily: it drags in aiohttp and the whole crawl stack, and
# routing that through module import would make this file unimportable without them.
# --------------------------------------------------------------------------------------

def _notes_from_source_review(result):
    """Notes for the answer: the untrusted-evidence block, then a short reviewed-pages index.

    ``system_message['content']`` is the same ``[SOURCE_REVIEW_EVIDENCE]`` block the classic
    chat path folds into the model prompt -- the page excerpts, clearly labelled as untrusted
    input. We add one ``Reviewed: title (url)`` line per page so a glance at the notes shows
    what was actually read. This stays notes, never evidence: a web page is not an authorized
    document source and must not enter the evidence coverage ledger.
    """
    notes = []
    system_message = result.get('system_message')
    if isinstance(system_message, dict):
        content = _text(system_message.get('content'))
        if content:
            notes.append(content)
    reviewed = []
    for page in result.get('pages') or ():
        if not isinstance(page, dict):
            continue
        url = _text(page.get('url'))
        if not url:
            continue
        title = _text(page.get('title')) or url
        reviewed.append(f'Reviewed: {title} ({url})')
    if reviewed:
        notes.append('\n'.join(reviewed))
    return notes


def _citations_from_source_review(result):
    # perform_source_review already shapes each citation as {url, title, source, published_date};
    # we pass them through untouched but drop any that carry no URL, since a citation the reader
    # cannot open is noise rather than a source.
    citations = []
    for citation in result.get('citations') or ():
        if isinstance(citation, dict) and _text(citation.get('url')):
            citations.append(citation)
    return citations


def _finalize_source_review(
    result,
    *,
    capability_id,
    unavailable_summary,
    empty_summary,
    found_summary,
    empty_replan_hint=None,
):
    """Turn a source-review result into a StepResult of notes and citations, never evidence.

    ``enabled`` being false means the deployment setting or the caller's app role withdrew the
    capability between planning and running; access is re-checked at run time, so that is a
    clean failure the answer can still work around, not licence to invent web content. When it
    is enabled, the step completes even with no pages: an empty crawl is a real, reportable
    outcome (a link 404'd, a robots rule blocked it), and for deep research the replan hint
    points at running a web search first rather than treating emptiness as an error.
    """
    result = result if isinstance(result, dict) else {}
    if not bool(result.get('enabled')):
        reason = _text(result.get('skipped_reason')) or 'unknown'
        return _failed_result(
            unavailable_summary,
            f'{capability_id} reported it was not enabled (reason: {reason}).',
        )

    pages = [page for page in (result.get('pages') or ()) if isinstance(page, dict)]
    notes = _notes_from_source_review(result)
    citations = _citations_from_source_review(result)

    if pages:
        return build_step_result(
            status=STEP_STATUS_COMPLETED,
            summary=found_summary.format(count=len(pages)),
            notes=notes,
            citations=citations,
        )

    reason = _text(result.get('skipped_reason'))
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=empty_summary + (f' ({reason})' if reason else ''),
        notes=notes,
        citations=citations,
        replan_hint=empty_replan_hint,
    )


def _resolve_source_review_planner(settings):
    """The client and model deep research uses for its own link-selection planning.

    perform_source_review takes a planner client/model so it can decide which discovered links
    are worth reading. The context's ``invoke_prompt`` closure has already resolved a client,
    but it is a ``call(prompt) -> text`` seam by design and does not expose the client object,
    so we resolve one the same way the planner does. ``resolve_planner_client`` handles APIM,
    managed identity and key auth and returns the planner deployment -- the right model for an
    internal planning call rather than for writing the final answer.
    """
    from functions_orchestration_planner import resolve_planner_client

    return resolve_planner_client(settings)


def run_url_fetch(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    user_message = _text(_ctx(context, 'user_message', ''))
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before reading the linked pages.')

    _emit(emit, _progress(step, CAPABILITY_URL_FETCH, 'Reading the linked pages'))

    try:
        from functions_source_review import (
            URL_ACCESS_CONTEXT_CHAT,
            extract_urls_from_text,
            perform_source_review,
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} url_fetch is unavailable: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Reading linked pages is unavailable.', str(exc))

    # A step may narrow the read to specific links, but only links the user actually pasted may
    # be read -- never a URL the model produced. We intersect the requested set with the URLs
    # found in the message (normalizing both sides through extract_urls_from_text so the compare
    # is apples to apples) and seed only those, with direct extraction turned off so a
    # requested-but-absent URL cannot slip through the other seeding path.
    include_direct_user_urls = True
    additional_seed_urls = None
    requested = _string_list(arguments.get('urls'))
    if requested:
        message_urls = set(extract_urls_from_text(user_message))
        normalized_requested = []
        for candidate in requested:
            normalized_requested.extend(extract_urls_from_text(candidate))
        additional_seed_urls = [url for url in normalized_requested if url in message_urls]
        include_direct_user_urls = False
        if not additional_seed_urls:
            return build_step_result(
                status=STEP_STATUS_COMPLETED,
                summary='None of the requested links were present in the message.',
                replan_hint='The urls argument named links that are not in the user message; omit it to read every link the user pasted.',
            )

    try:
        result = perform_source_review(
            settings=settings,
            user_id=user_id,
            user_email=_ctx(context, 'user_email', None),
            user_roles=_ctx(context, 'user_roles', None),
            user_message=user_message,
            web_search_citations=[],
            conversation_id=_ctx(context, 'conversation_id', None),
            url_access_only=True,
            url_access_context=URL_ACCESS_CONTEXT_CHAT,
            include_direct_user_urls=include_direct_user_urls,
            additional_seed_urls=additional_seed_urls,
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} url_fetch failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('The linked pages could not be read.', str(exc))

    return _finalize_source_review(
        result,
        capability_id=CAPABILITY_URL_FETCH,
        unavailable_summary='Reading linked pages is not available for this user.',
        empty_summary='No linked pages could be read.',
        found_summary='Read {count} linked page(s).',
    )


def run_deep_research(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    user_message = _text(_ctx(context, 'user_message', ''))
    query = _text(arguments.get('query')) or user_message
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before deep research.')
    if not query:
        return _failed_result('No research question was available.', 'deep_research requires a query.')

    _emit(emit, _progress(step, CAPABILITY_DEEP_RESEARCH, 'Researching sources'))

    try:
        from functions_source_review import (
            URL_ACCESS_CONTEXT_CHAT,
            extract_urls_from_text,
            perform_source_review,
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} deep_research is unavailable: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Deep research is unavailable.', str(exc))

    # Deep research crawls seeds; it does not itself search the web. Its seeds are the citations
    # any earlier web_search or url_fetch step left on the context, plus URLs the user pasted.
    # We pass the research question as user_message so planning and relevance target the question
    # rather than the whole turn, and pass the message's own URLs explicitly so narrowing the
    # question does not drop a link the user gave us. Citations without a URL (document sources)
    # are ignored by the seed collector, so handing the whole citation list over is safe.
    prior_citations = [c for c in (_ctx(context, 'citations', []) or ()) if isinstance(c, dict)]
    message_seed_urls = extract_urls_from_text(user_message) or None

    try:
        planner_client, planner_model = _resolve_source_review_planner(settings)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} deep_research could not resolve a planner client: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Deep research could not start.', str(exc))

    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before deep research.')

    try:
        result = perform_source_review(
            settings=settings,
            user_id=user_id,
            user_email=_ctx(context, 'user_email', None),
            user_roles=_ctx(context, 'user_roles', None),
            user_message=query,
            web_search_citations=prior_citations,
            conversation_id=_ctx(context, 'conversation_id', None),
            source_review_planner_client=planner_client,
            source_review_planner_model=planner_model,
            url_access_only=False,
            url_access_context=URL_ACCESS_CONTEXT_CHAT,
            include_direct_user_urls=True,
            additional_seed_urls=message_seed_urls,
        )
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} deep_research failed: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('Deep research failed.', str(exc))

    return _finalize_source_review(
        result,
        capability_id=CAPABILITY_DEEP_RESEARCH,
        unavailable_summary='Deep research is not available for this user.',
        empty_summary='Deep research found no readable sources.',
        found_summary='Reviewed {count} source(s) for the research question.',
        empty_replan_hint='Run a web_search step first so deep_research has sources to read.',
    )


# --------------------------------------------------------------------------------------
# agent_invoke -> a single Semantic Kernel agent, reconstructed for the worker thread
#
# There is no reusable perform_agent_invoke; the classic path lives inline in the chat route
# and leans on Flask g (g.kernel, g.kernel_agents, g.force_enable_agents). None of that exists
# here, so this adapter composes the same steps against the context instead: resolve the agent
# from the catalog the route captured, re-check the gates, build a one-agent kernel with the
# loader's DRY seam, invoke it synchronously, and read usage and tool calls back out the same
# way the route does. Everything Semantic Kernel is imported lazily -- it is a large, optional
# dependency, and this module must import without it.
# --------------------------------------------------------------------------------------

class _AgentEventLoopError(Exception):
    """Raised when the worker thread unexpectedly already has a running event loop."""


def _agent_message_history(task):
    # The agent is self-contained: it runs its own tools, so we hand it only the task and let
    # it work, exactly as the route hands the agent a user turn. We deliberately do not fold the
    # run's accumulated notes into its context -- that would both bloat the agent and pipe
    # untrusted gathered web text into a tool-using agent's own prompt.
    from semantic_kernel.contents.chat_message_content import ChatMessageContent

    return [ChatMessageContent(role='user', content=task)]


async def _await_agent_invoke(invoke, messages):
    # Mirrors the core of the route's run_sk_call: an agent's invoke may return a value, a
    # coroutine, or an async generator, and we take the first item of a generator just as the
    # route does. The chat path stringifies the result afterward, so we return it raw.
    import asyncio
    from types import AsyncGeneratorType

    result = invoke(messages)
    if asyncio.iscoroutine(result):
        result = await result
    if isinstance(result, AsyncGeneratorType):
        async for item in result:
            return item
        return None
    return result


def _invoke_agent_sync(selected_agent, task):
    import asyncio

    # asyncio.run needs no already-running loop. The executor's worker thread is synchronous, so
    # normally there is none -- but we verify, because asyncio.run inside a running loop raises a
    # confusing RuntimeError, and we would rather fail with a clear, attributable reason.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # No running loop, which is exactly what we need.
    else:
        raise _AgentEventLoopError('an event loop is already running in the worker thread')

    messages = _agent_message_history(task)
    raw = asyncio.run(_await_agent_invoke(selected_agent.invoke, messages))
    return _text(raw) if raw is not None else ''


def _record_agent_token_usage(context, kernel):
    """Fold the kernel services' token counts into the run's usage accumulator.

    The agent result carries no usage; the counts live on the chat-completion services the
    kernel holds, populated as a side effect of the call. Chat reads them the same way, taking
    the first service that reports any. We add them onto ``context.token_usage`` -- the run's
    accumulator the executor already surfaces -- using the field names every other model call in
    this framework uses, so an agent step is no longer billed as free. Token accounting must
    never break an answer, so any failure here is swallowed after logging.
    """
    try:
        usage = _ctx(context, 'token_usage', None)
        if not isinstance(usage, dict):
            return
        for service in (getattr(kernel, 'services', {}) or {}).values():
            prompt_tokens = getattr(service, 'prompt_tokens', None)
            completion_tokens = getattr(service, 'completion_tokens', None)
            total_tokens = getattr(service, 'total_tokens', None)
            if prompt_tokens or completion_tokens or total_tokens:
                for field, value in (
                    ('prompt_tokens', prompt_tokens),
                    ('completion_tokens', completion_tokens),
                    ('total_tokens', total_tokens),
                ):
                    if isinstance(value, int):
                        usage[field] = usage.get(field, 0) + value
                return  # First service with usage wins, matching the chat path.
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Could not read agent token usage: {exc}',
            level=logging.WARNING,
        )


def _agent_citations(plugin_logger, user_id, conversation_id, seen_before):
    """The tool calls this invocation made, shaped exactly like the chat route's agent citations.

    The plugin logger accumulates every tool call for a conversation, so we snapshot which
    invocations existed before this step and keep only the new ones -- otherwise a second agent
    step would re-cite the first step's tools. The citation shape matches the chat route field
    for field so the same UI renders it. make_json_serializable and the label builder are
    imported lazily and degraded past on failure, because losing a citation must never lose the
    answer.
    """
    if plugin_logger is None:
        return []
    try:
        invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Could not read agent tool invocations: {exc}',
            level=logging.WARNING,
        )
        return []

    try:
        from functions_message_artifacts import (
            build_agent_citation_tool_label,
            make_json_serializable,
        )
    except Exception:
        build_agent_citation_tool_label = None
        make_json_serializable = None

    def _serialize(value):
        if make_json_serializable:
            try:
                return make_json_serializable(value)
            except Exception:
                pass
        return _text(value) if value is not None else None

    citations = []
    for inv in invocations or ():
        if id(inv) in seen_before:
            continue  # A tool call from before this step, not ours to cite.
        timestamp = getattr(inv, 'timestamp', None)
        if hasattr(timestamp, 'isoformat'):
            timestamp_str = timestamp.isoformat()
        else:
            timestamp_str = _text(timestamp) or None
        plugin_name = getattr(inv, 'plugin_name', None)
        function_name = getattr(inv, 'function_name', None)
        parameters = getattr(inv, 'parameters', None)
        inv_result = getattr(inv, 'result', None)
        if build_agent_citation_tool_label:
            try:
                tool_name = build_agent_citation_tool_label(plugin_name, function_name, parameters, inv_result)
            except Exception:
                tool_name = '.'.join(part for part in (_text(plugin_name), _text(function_name)) if part)
        else:
            tool_name = '.'.join(part for part in (_text(plugin_name), _text(function_name)) if part)
        citations.append({
            'tool_name': tool_name,
            'function_name': function_name,
            'plugin_name': plugin_name,
            'function_arguments': _serialize(parameters),
            'function_result': _serialize(inv_result),
            'duration_ms': getattr(inv, 'duration_ms', None),
            'timestamp': timestamp_str,
            'success': getattr(inv, 'success', None),
            'error_message': _serialize(getattr(inv, 'error_message', None)),
            'user_id': getattr(inv, 'user_id', None),
        })
    return citations


def run_agent_invoke(step, context, *, settings, user_id, emit, cancel_requested):
    arguments = _arguments(step)
    agent_name = _text(arguments.get('agent_name'))
    task = _text(arguments.get('task')) or _text(_ctx(context, 'user_message', ''))
    if not agent_name:
        return _failed_result('No agent was named.', 'agent_invoke requires an agent_name.')
    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before invoking the agent.')

    # An agent may only be invoked if the catalog offered it. The catalog is resolved per request
    # and carried on the context; refusing anything absent from it is what stops a plan -- or a
    # repaired plan -- from naming an agent this user cannot reach. Access is verified here, at
    # run time, not trusted from the plan-time request gate.
    catalog = [a for a in (_ctx(context, 'agent_catalog', None) or ()) if isinstance(a, dict)]
    selected_agent_data = next((a for a in catalog if _text(a.get('name')) == agent_name), None)
    if selected_agent_data is None:
        return _failed_result(
            f'No agent named "{agent_name}" is available to this user.',
            'agent_invoke was asked for an agent absent from the catalog.',
        )

    if not settings.get('enable_semantic_kernel', False):
        return _failed_result('Agents are not enabled.', 'agent_invoke requires enable_semantic_kernel.')
    if not _ctx(context, 'user_enable_agents', True):
        return _failed_result('Agents are turned off for this user.', 'agent_invoke requires user_enable_agents.')

    _emit(emit, _progress(step, CAPABILITY_AGENT_INVOKE, f'Asking agent {agent_name}'))

    try:
        from functions_agent_scope import find_agent_by_scope, is_selected_agent_scope_enabled

        if not is_selected_agent_scope_enabled(settings, selected_agent_data):
            return _failed_result(
                f'The scope of agent "{agent_name}" is not enabled.',
                'agent_invoke selected agent scope is disabled by settings.',
            )
        agent_cfg = find_agent_by_scope(catalog, selected_agent_data) or selected_agent_data
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} agent_invoke could not resolve agent scope: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('The agent could not be resolved.', str(exc))

    if _is_cancelled(cancel_requested):
        return _cancelled_result('Cancelled before invoking the agent.')

    # Build a kernel holding exactly this one agent. We deliberately avoid
    # initialize_semantic_kernel: in per-user mode it writes the kernel onto Flask g (absent in
    # this thread) and returns nothing, and it loads the entire agent catalog when we need only
    # one. load_single_agent_for_kernel is the DRY seam it calls internally; in 'global' mode it
    # never touches its context_obj argument, so a fresh Kernel and a None context are safe, and
    # it hands back {name: agent}. Its own plugin loading reads the current user id defensively
    # and tolerates there being none, which is the case off the request thread.
    try:
        from semantic_kernel import Kernel
        from semantic_kernel_loader import load_single_agent_for_kernel

        kernel, agent_objs = load_single_agent_for_kernel(
            Kernel(),
            agent_cfg,
            settings,
            None,
            redis_client=None,
            mode_label='global',
        )
        selected_agent = (agent_objs or {}).get(_text(agent_cfg.get('name'))) if kernel else None
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} agent_invoke could not load the agent: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('The agent could not be loaded.', str(exc))

    if not kernel or selected_agent is None:
        return _failed_result(
            f'Agent "{agent_name}" could not be initialized.',
            'load_single_agent_for_kernel returned no usable agent (check its endpoint and credentials).',
        )

    conversation_id = _ctx(context, 'conversation_id', None)
    try:
        from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger

        plugin_logger = get_plugin_logger()
        seen_before = {
            id(inv)
            for inv in (plugin_logger.get_invocations_for_conversation(user_id, conversation_id) or ())
        }
    except Exception:
        # The plugin logger is best-effort context for citations; its absence must not stop the
        # invocation. We simply produce no tool-call citations in that case.
        plugin_logger = None
        seen_before = set()

    try:
        reply = _invoke_agent_sync(selected_agent, task)
    except _AgentEventLoopError as exc:
        return _failed_result('The agent could not run in this context.', str(exc))
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} agent_invoke failed during invocation: {exc}',
            extra={'user_id': user_id, 'step_id': (step or {}).get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _failed_result('The agent invocation failed.', str(exc))

    _record_agent_token_usage(context, kernel)
    citations = _agent_citations(plugin_logger, user_id, conversation_id, seen_before)

    display_name = _text(agent_cfg.get('display_name')) or agent_name
    if not reply:
        # An agent that returned nothing is a completed-but-empty step, not a failure: the plan
        # still answers, and the tool-call citations we did gather stay attached.
        return build_step_result(
            status=STEP_STATUS_COMPLETED,
            summary=f'Agent {display_name} produced no reply.',
            citations=citations,
        )

    note = f'Agent "{display_name}" was asked: {task}\n\nThe agent replied:\n{reply}'
    return build_step_result(
        status=STEP_STATUS_COMPLETED,
        summary=_first_line(reply) or f'Agent {display_name} replied.',
        notes=[note],
        citations=citations,
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
    CAPABILITY_URL_FETCH: run_url_fetch,
    CAPABILITY_DEEP_RESEARCH: run_deep_research,
    CAPABILITY_AGENT_INVOKE: run_agent_invoke,
    CAPABILITY_RESPOND: run_respond,
}


def get_adapter(name):
    """The adapter callable for a capability/adapter name, or ``None`` if unknown."""
    return ADAPTER_REGISTRY.get(name)
