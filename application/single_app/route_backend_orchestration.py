# route_backend_orchestration.py

"""
The V2 chat orchestration endpoints.

Two phases, deliberately two requests. The plan is durable in Cosmos between them, which
buys three things a single long-lived stream could not: a dropped connection cannot lose a
plan the user was reading, editing a plan before it runs is an ordinary request rather than
a message shoved back up a live stream, and re-planning after a question is answered is
just another call to the same endpoint.

It also means none of this touches ``route_backend_chats.py``. That file is over 24,000
lines and carries the entire existing chat contract; adding a second execution model to it
would put every existing conversation at risk for a feature that is off by default.

Request data is captured before streaming. The planning stream retains authenticated
request context for model authorization after canonical turn state is restored.
Execution workers receive explicit identity and model bindings, never Flask state.

Version: 0.261.104
"""

import hashlib
import json
import logging
import queue
import threading
import uuid
from copy import deepcopy
from agent_execution_context import capture_execution_identity
from datetime import datetime, timezone

from azure.cosmos import exceptions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Response, jsonify, request, session, stream_with_context
from openai import OpenAIError

from config import cosmos_conversations_container, cosmos_messages_container
from functions_appinsights import log_event
from functions_citation_tracking import merge_cited_documents_into_conversation
from functions_conversation_cache import invalidate_conversation_cache_for_item
from functions_authentication import (
    get_current_user_id,
    get_current_user_info,
    login_required,
    user_required,
)
from functions_orchestration_context import (
    ELICITATION_CONTEXT_BYTE_LIMIT,
    ElicitationContextError,
    HISTORY_MAX_MESSAGES,
    HISTORY_SCAN_LIMIT,
    CatalogResolutionError,
    ConversationContextError,
    build_capability_request_context as _capability_request_context,
    build_conversation_snapshot,
    build_conversation_signals,
    build_elicitation_user_request,
    build_planner_context,
    build_run_ledger,
    collect_answered_questions,
    merge_elicitation_context,
    normalize_elicitation_answer,
    conversation_user_urls,
    history_message_limit,
    normalize_history_message,
    resolve_action_catalog,
    resolve_agent_catalog,
    resolve_candidate_documents,
    resolve_elicitation_references,
    resolve_seeds,
    validate_clarification_answers,
    validate_conversation_snapshot,
)
from functions_orchestration_events import (
    build_cancelled_event,
    build_content_event,
    build_conversation_metadata_event,
    build_elicitation_event,
    build_error_event,
    build_model_reasoning_metadata,
    build_plan_event,
    build_planning_thought,
    build_reasoning_adjustment_event,
    build_run_done_event,
    build_step_event,
    build_step_thought,
    build_synthesis_thought,
    merge_reasoning_adjustments,
    serialize_sse,
)
from functions_orchestration_executor import RunContext, execute_plan
from functions_orchestration_memory import (
    OrchestrationMemoryError,
    load_orchestration_memory,
    validate_memory_context,
)
from functions_orchestration_plan_editing import (
    build_plan_edit_outcome,
    revision_allowed_urls,
    validate_edited_plan,
)
from functions_orchestration_plan_revisions import (
    PlanRevisionError,
    begin_plan_edit,
    claim_plan_revision,
    claim_plan_run,
    complete_plan_revision,
    plan_editor_state,
    read_revision_run,
    release_plan_revision,
)
from functions_orchestration_planner import (
    ConversationResolutionError,
    PlannerError,
    PlannerResponseError,
    plan_request,
    resolve_conversation_request,
    resolve_planner_client,
)
from functions_orchestration_models import (
    OrchestrationModel,
    OrchestrationModelError,
    has_planner_model_override,
    resolve_orchestration_model,
)
from functions_orchestration_registry import (
    CapabilityResolutionError,
    required_capability_ids,
    resolve_available_capability_ids,
)
from functions_orchestration_runs import (
    ElicitationStateError,
    claim_elicitation_submission,
    complete_elicitation_submission,
    create_orchestration_run,
    create_pending_elicitation,
    clear_pending_turn_context,
    get_latest_turn_run,
    get_pending_elicitation,
    get_pending_turn_context,
    get_orchestration_run,
    list_conversation_runs,
    list_run_steps,
    prepare_elicitation_outcome,
    release_elicitation_submission,
    save_orchestration_step,
    save_pending_turn_context,
    update_orchestration_run,
)
from functions_orchestration_schema import (
    ELICITATION_ACTION_ACCEPT,
    ELICITATION_ACTION_CANCEL,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_RUNNING,
    apply_plan_edits,
    normalize_elicitation,
    summarize_plan,
)
from functions_settings import get_settings, get_user_settings
from functions_prompt_metadata import build_prompt_selection_metadata
from model_endpoint_clients import extract_chat_completion_response_text
from swagger_wrapper import get_auth_security, swagger_route

# SSE responses must not be buffered by an intermediary, or progress arrives all at once at
# the end, which is indistinguishable from the feature not working.
SSE_HEADERS = {
    'Cache-Control': 'no-cache, no-transform',
    'X-Accel-Buffering': 'no',
    'Connection': 'keep-alive',
}

ANSWER_MAX_TOKENS = 4000
ANSWER_TEMPERATURE = 0.3

# How often the executor's cancel probe re-reads the run record. Cancellation is recorded in
# Cosmos rather than in process memory because the cancel request almost never lands on the
# worker running the stream; this is the same approach the workflow runner takes.
CANCEL_POLL_SECONDS = 3.0

# How long the response waits on a silent queue before sending an SSE comment. A single
# document analysis step can run for minutes without emitting, and an idle connection is
# what proxies close.
HEARTBEAT_SECONDS = 15.0

# The worker has already put its sentinel by the time this runs, so the join is only
# reclaiming the thread. Bounded anyway rather than trusted.
RUN_JOIN_TIMEOUT_SECONDS = 30.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit=None):
    if value is None:
        return ''
    value = str(value).strip()
    return value[:limit].rstrip() if limit and len(value) > limit else value


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sse(generator):
    return Response(generator, mimetype='text/event-stream', headers=dict(SSE_HEADERS))


def _orchestration_enabled(settings):
    return bool((settings or {}).get('enable_chat_orchestration'))


def _build_invoke_prompt(settings, token_usage=None, model=None):
    """A closure the adapters call to ask the model something.

    The signature is not ours to choose. ``run_document_analysis``,
    ``run_document_comparison`` and the respond adapter all call this as
    ``invoke_prompt(prompt_text, stage=..., metadata={...})``, which is the convention
    ``functions_workflow_runner.invoke_model_prompt`` established and every existing caller
    follows. Getting it wrong does not fail at import or in a unit test with fake adapters
    -- it fails at the moment a real step runs, with a TypeError that reads as a mystery,
    which is exactly how it was found.

    ``stage`` and ``metadata`` are accepted and deliberately unused beyond logging: they
    describe which phase of a multi-pass analysis is asking, and the answer is the same
    model call either way. They are named rather than swallowed by ``**kwargs`` so this
    file states the contract it is honouring.

    The run supplies an authorized model binding resolved from its saved selection or
    the administrator's default. The legacy branch remains for callers without a binding.
    """
    if model is None:
        client, planner_deployment = resolve_planner_client(settings)
        gpt_model = (settings or {}).get('gpt_model') or {}
        deployment = (
            (gpt_model['selected'][0] or {}).get('deploymentName')
            if gpt_model.get('selected') else None
        ) or planner_deployment
        model = OrchestrationModel(client, deployment)

    def invoke_prompt(prompt_text, stage='window_analysis', metadata=None):
        messages = (
            prompt_text
            if isinstance(prompt_text, list)
            else [{'role': 'user', 'content': str(prompt_text or '')}]
        )
        try:
            response = model.create_completion(
                messages=messages,
                temperature=ANSWER_TEMPERATURE,
                max_tokens=ANSWER_MAX_TOKENS,
                use_model_response_length=True,
            )
        except (OpenAIError, AzureError) as exc:
            log_event(
                '[ORCHESTRATION] The answer model request failed.',
                level=logging.WARNING, extra={'stage': stage, 'error_type': type(exc).__name__},
            )
            raise PlannerResponseError('model_request_failed') from exc

        # Accumulated here because this is the only place every model call an orchestration
        # run makes passes through. A run's cost was previously reported as zero for that
        # reason, not because it was free.
        usage = getattr(response, 'usage', None)
        if usage is not None and isinstance(token_usage, dict):
            for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                value = getattr(usage, field, None)
                if isinstance(value, int):
                    token_usage[field] = token_usage.get(field, 0) + value

        if not response or not response.choices:
            log_event(
                f"[ORCHESTRATION] The model returned no choices at stage '{stage}'.",
                level=logging.WARNING,
            )
            raise PlannerResponseError('empty_completion')
        choice = response.choices[0]
        if getattr(choice, 'finish_reason', None) == 'content_filter' or getattr(choice.message, 'refusal', None):
            raise PlannerResponseError('model_refusal')
        text = extract_chat_completion_response_text(response)
        if not text.strip():
            raise PlannerResponseError('empty_completion')
        return text

    return invoke_prompt


def _combined_token_usage(prompt_usage, step_usage):
    usage = dict(step_usage or {})
    usage.update(_sum_token_usage(prompt_usage, step_usage))
    return usage


def _authorized_document_ids(candidates, seeds):
    """Documents a plan is allowed to name.

    The candidate probe only returns documents this user can already read, so its results
    are an authorization answer as well as a relevance one. Seeded ids are included because
    the user selected them through a surface that had already checked access, and the
    executor re-authorizes everything again before the answer is composed regardless.
    """
    allowed = {
        _text(candidate.get('document_id'))
        for candidate in candidates or ()
        if _text(candidate.get('document_id'))
    }
    allowed.update(_text(value) for value in (seeds or {}).get('document_ids') or () if _text(value))
    return allowed


def _document_labels(candidates):
    return {
        _text(candidate.get('document_id')): (
            _text(candidate.get('title')) or _text(candidate.get('file_name'))
        )
        for candidate in candidates or ()
        if _text(candidate.get('document_id'))
    }


def _load_ledger(conversation_id, user_id, settings):
    """Earlier runs in this conversation, summarised for the planner.

    A ledger that cannot be read is not a reason to refuse to plan; it only means this turn
    plans without knowing what earlier turns found, which is the behaviour before the ledger
    existed rather than a failure.
    """
    if not conversation_id:
        return build_run_ledger([], settings=settings)
    try:
        limit = int(settings.get('chat_orchestration_ledger_max_runs', 10))
    except (TypeError, ValueError):
        limit = 10
    if limit <= 0:
        return build_run_ledger([], settings=settings)
    try:
        runs = list_conversation_runs(conversation_id, user_id, limit=min(limit, 50))
    except Exception as exc:
        log_event(
            f"[ORCHESTRATION] Could not read the run ledger; planning without it: {exc}",
            level=logging.WARNING,
        )
        return build_run_ledger([], settings=settings)
    # A derived intent or clarification can repeat redacted text even when the message
    # snapshot excludes it. Omit the whole ledger entry when its source turn is hidden.
    _authorize_context_conversation(conversation_id, user_id)
    source_ids = list({
        run[key] for run in runs for key in ('user_message_id', 'assistant_message_id')
        if isinstance(run.get(key), str) and run[key]
    })
    try:
        sources = list(cosmos_messages_container.query_items(
            query=(
                'SELECT c.id, c.role, c.metadata FROM c WHERE c.conversation_id = @conversation_id '
                'AND ARRAY_CONTAINS(@message_ids, c.id)'
            ),
            parameters=[
                {'name': '@conversation_id', 'value': conversation_id},
                {'name': '@message_ids', 'value': source_ids},
            ],
            partition_key=conversation_id,
        )) if source_ids else []
    except AzureError as exc:
        log_event(
            '[ORCHESTRATION] Could not revalidate earlier run context; omitting the ledger.',
            level=logging.WARNING, extra={'error_type': type(exc).__name__},
        )
        return {'runs': [], 'answered_questions': [], 'truncated': True}
    visible = set()
    for source in sources:
        metadata = source.get('metadata') or {}
        thread = (metadata.get('thread_info') or {}) if isinstance(metadata, dict) else None
        if (
            source.get('role') in ('user', 'assistant')
            and isinstance(metadata, dict) and isinstance(thread, dict)
            and not metadata.get('masked') and not metadata.get('masked_ranges')
            and not metadata.get('is_generated_chat_artifact')
            and thread.get('active_thread') is not False
        ):
            visible.add(source['id'])
    runs = [
        run for run in runs
        if run.get('user_message_id') in visible
        and (not run.get('assistant_message_id') or run['assistant_message_id'] in visible)
    ]
    return build_run_ledger(
        runs, settings=settings, answered_questions=collect_answered_questions(runs)
    )


def _authorize_context_conversation(conversation_id, user_id):
    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id
        )
    except CosmosResourceNotFoundError:
        raise ConversationContextError('That conversation could not be opened.') from None
    if conversation.get('user_id') != user_id:
        raise ConversationContextError('That conversation could not be opened.')
    return conversation


def _load_conversation_snapshot(
    conversation_id, user_id, settings, *, turn_id=None, before_message_id=None
):
    """Read history from the owned partition, never from the browser's loaded page."""
    _authorize_context_conversation(conversation_id, user_id)
    parameters = [{'name': '@conversation_id', 'value': conversation_id}]
    before_clause = ''
    if before_message_id:
        try:
            before = cosmos_messages_container.read_item(
                item=before_message_id, partition_key=conversation_id
            )
        except CosmosResourceNotFoundError:
            raise ConversationContextError('This request needs a new plan.') from None
        if (
            before.get('conversation_id') != conversation_id
            or before.get('role') != 'user'
            or not before.get('timestamp')
        ):
            raise ConversationContextError('This request needs a new plan.')
        before_clause = ' AND c.timestamp < @before_timestamp'
        parameters.append({'name': '@before_timestamp', 'value': before['timestamp']})

    limit = history_message_limit(settings)
    if not limit:
        return build_conversation_snapshot([], settings)
    scan_limit = min(HISTORY_SCAN_LIMIT, limit * 2 + 1)
    messages = list(cosmos_messages_container.query_items(
        query=(
            f'SELECT TOP {scan_limit} * FROM c '
            'WHERE c.conversation_id = @conversation_id '
            'AND c.role IN ("user", "assistant") '
            'AND (NOT IS_DEFINED(c.metadata.masked) OR c.metadata.masked != true) '
            'AND (NOT IS_DEFINED(c.metadata.is_generated_chat_artifact) '
            'OR c.metadata.is_generated_chat_artifact != true) '
            'AND (NOT IS_DEFINED(c.metadata.thread_info.active_thread) '
            'OR c.metadata.thread_info.active_thread != false)'
            f'{before_clause} ORDER BY c.timestamp DESC'
        ),
        parameters=parameters,
        partition_key=conversation_id,
    ))
    return build_conversation_snapshot(
        messages, settings, turn_id=turn_id, truncated=len(messages) >= scan_limit
    )


def _validate_saved_conversation_context(snapshot, conversation_id, user_id):
    _authorize_context_conversation(conversation_id, user_id)
    entries = snapshot.get('messages') if isinstance(snapshot, dict) else None
    if not isinstance(entries, list) or len(entries) > HISTORY_MAX_MESSAGES:
        raise ConversationContextError('This request needs a new plan.')
    message_ids = [
        entry['id'] for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get('id'), str) and entry['id']
    ]
    if len(message_ids) != len(entries) or len(set(message_ids)) != len(message_ids):
        raise ConversationContextError('This request needs a new plan.')
    messages = list(cosmos_messages_container.query_items(
        query=(
            'SELECT * FROM c WHERE c.conversation_id = @conversation_id '
            'AND ARRAY_CONTAINS(@message_ids, c.id)'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@message_ids', 'value': message_ids},
        ],
        partition_key=conversation_id,
    )) if message_ids else []
    return validate_conversation_snapshot(snapshot, messages)


def _conversation_context_for_run(record, user_id, settings):
    conversation_id = record['conversation_id']
    _authorize_context_conversation(conversation_id, user_id)
    if record.get('user_message_id'):
        try:
            current = cosmos_messages_container.read_item(
                item=record['user_message_id'], partition_key=conversation_id
            )
        except CosmosResourceNotFoundError:
            raise ConversationContextError('This request needs a new plan.') from None
        normalized = normalize_history_message(current)
        if (
            not normalized
            or normalized['role'] != 'user'
            or current.get('conversation_id') != conversation_id
            or (
                record.get('user_message_fingerprint')
                and normalized['fingerprint'] != record['user_message_fingerprint']
            )
            or (
                not record.get('user_message_fingerprint')
                and normalized['content'] != record.get('user_message')
            )
        ):
            raise ConversationContextError('This request needs a new plan.')
    if 'conversation_context' in record:
        return _validate_saved_conversation_context(
            record['conversation_context'], conversation_id, user_id
        )
    if not record.get('user_message_id'):
        raise ConversationContextError('This older request needs a new plan.')
    return _load_conversation_snapshot(
        conversation_id, user_id, settings, before_message_id=record['user_message_id']
    )


def _make_cancel_probe(run_id, user_id, conversation_id):
    """Poll the run record for a cancellation request.

    In-process state would not do. The stream is a blocking POST held by one worker while
    the cancel request is an ordinary POST that lands wherever the load balancer sends it,
    so the only place both can see is the record itself. Polled rather than read on every
    probe because the executor calls this between every step and inside adapters.
    """
    import time

    state = {'checked_at': 0.0, 'cancelled': False}

    def cancel_requested():
        if state['cancelled']:
            return True
        now = time.monotonic()
        if now - state['checked_at'] < CANCEL_POLL_SECONDS:
            return False
        state['checked_at'] = now
        try:
            record = get_orchestration_run(run_id, user_id, conversation_id=conversation_id)
        except Exception:
            # A transient read failure must not cancel a healthy run.
            return False
        if record and record.get('cancellation_requested_at'):
            state['cancelled'] = True
        return state['cancelled']

    return cancel_requested


def _ensure_conversation(conversation_id, user_id, title=''):
    """Make sure a conversation exists for this run to belong to.

    The first message of a new chat arrives with no conversation, exactly as it does for
    ordinary chat, and the run record is partitioned by conversation id -- so one has to
    exist before a plan can be stored against it. Created here with the same shape
    ``route_backend_chats`` uses, so a conversation started by orchestration is
    indistinguishable from any other and the classic interface can open it.
    """


    conversation_id = conversation_id or f"conv_{uuid.uuid4().hex}"
    now = _now_iso()

    try:
        existing = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id
        )
        if existing.get('user_id') != user_id:
            # Someone else's conversation. Treated as absent rather than reported, so an
            # id cannot be used to probe for conversations that exist.
            return None, False
        return conversation_id, False
    except CosmosResourceNotFoundError:
        pass
    except Exception as exc:
        log_event(
            '[ORCHESTRATION] Conversation ownership could not be verified.',
            extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
        )
        return None, False

    try:
        cosmos_conversations_container.create_item({
            'id': conversation_id,
            'user_id': user_id,
            'last_updated': now,
            'title': _text(title, 80) or 'New Conversation',
            'context': [],
            'tags': [],
            'strict': False,
            'chat_type': 'new',
        })
    except Exception as exc:
        log_event(
            f"[ORCHESTRATION] Could not create a conversation: {exc}",
            level=logging.ERROR, exceptionTraceback=True,
        )
        return None, False

    return conversation_id, True


def _request_identity(user_id=None, seeded_agent=None):
    """Capture the request-scoped identity a run needs, before any thread starts.

    ``execute_plan`` runs on a worker thread with no Flask request context: no ``g``, no
    ``session``, no ``current_app``. An adapter that reached for ``session`` there would
    raise, and one that quietly defaulted instead would be worse -- ``user_roles`` gates the
    ``UrlAccessUser`` and ``DeepResearchUser`` app roles, so guessing it would either deny a
    permitted user or, far worse, admit one who is not.

    So the values are read here, on the request thread, and carried explicitly on the run
    context. Roles come from the session the same way the classic chat route reads them,
    which keeps one source of truth for what a role claim looks like.
    """
    try:
        info = get_current_user_info() or {}
    except Exception:
        info = {}
    try:
        roles = (session.get('user') or {}).get('roles', [])
    except Exception:
        # No session to read (an unusual transport, or a torn-down context). Absent roles
        # must read as "no roles", never as "unknown, allow anyway".
        roles = []

    # The per-user agent switch. RunContext defaults this to True for the same
    # backward-compatibility reason the classic path does, but the default is only correct
    # when nobody asked -- here somebody did, so the stored preference is read rather than
    # assumed, and a user who turned agents off does not get them back via orchestration.
    enable_agents = True
    if user_id:
        try:
            enable_agents = bool(
                (get_user_settings(user_id) or {}).get('settings', {}).get('enable_agents', True)
            )
        except Exception as exc:
            log_event(
                f"[ORCHESTRATION] Could not read user agent preference: {exc}",
                level=logging.WARNING,
            )
    # Selecting an agent by hand is itself the permission: the classic path sets
    # force_enable_agents on the same reasoning, so a seeded agent is honoured even when the
    # general switch is off.
    if isinstance(seeded_agent, dict) and _text(seeded_agent.get('name')):
        enable_agents = True

    return {
        'user_email': _text(info.get('email')) or None,
        'user_roles': list(roles) if isinstance(roles, (list, tuple, set)) else [],
        'user_enable_agents': enable_agents,
    }


def _partition_citations(citations):
    """Split citations into the document, web, and tool fields chat already renders.

    ``hybrid_citations`` also feeds used-document tracking. Native calls belong in
    ``agent_citations`` so their arguments and results reach the tool renderer instead
    of becoming web-source entries without a URL.
    """
    document_citations = []
    web_citations = []
    tool_citations = []
    for citation in citations or ():
        if not isinstance(citation, dict):
            continue
        if _text(citation.get('document_id')):
            document_citations.append(citation)
        elif citation.get('tool_name') or citation.get('function_name'):
            tool_citations.append(citation)
        elif _text(citation.get('url')) or citation.get('source_type') == 'web':
            web_citations.append(citation)
        else:
            # Preserve older non-document source records without treating them as documents.
            web_citations.append(citation)
    return document_citations, web_citations, tool_citations


def _record_cited_documents(conversation_id, user_id, document_citations):
    """Fold an answer's document citations into the conversation's used-document list.

    This is what puts a document in the Documents drawer. The drawer reads
    ``used_documents`` off the conversation, not the citations off the message, so an
    answer can cite a document perfectly and still show "No documents used yet" if this
    step is skipped -- which is exactly what an orchestrated answer did before this.
    """
    if not document_citations:
        return

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id
        )
    except Exception as exc:
        log_event(f"[ORCHESTRATION] Could not read the conversation to record cited "
                  f"documents: {exc}", level=logging.WARNING)
        return

    if conversation.get('user_id') != user_id:
        return

    try:
        merge_cited_documents_into_conversation(conversation, document_citations)
        conversation['last_updated'] = _now_iso()
        cosmos_conversations_container.upsert_item(conversation)
        invalidate_conversation_cache_for_item(conversation, reason="orchestration_completed")
    except Exception as exc:
        log_event(f"[ORCHESTRATION] Could not record cited documents: {exc}",
                  level=logging.WARNING)


def _save_message(conversation_id, role, content, metadata=None, extra=None, message_id=None):
    """Write one message, returning its id.

    ``extra`` carries the citation fields an assistant message needs. They are top-level
    rather than nested in metadata because that is where every existing reader looks for
    them -- the renderer, the citation lookup and the used-document tracking alike.
    """
    message_id = message_id or f"{role}_{uuid.uuid4().hex}"
    document = {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': role,
        'content': content or '',
        'timestamp': _now_iso(),
    }
    if isinstance(extra, dict):
        document.update(extra)
    if metadata:
        document['metadata'] = metadata

    try:
        cosmos_messages_container.upsert_item(document)
    except Exception as exc:
        log_event(
            f'[ORCHESTRATION] Could not save a {role} message.',
            extra={'exception_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return None
    return message_id


def _validate_turn_memory_context(turn_context, user_id, conversation_id):
    validate_memory_context(
        _authorize_context_conversation(conversation_id, user_id), user_id,
        turn_context.get('memory_audience'), turn_context.get('memory_scope'),
    )


def _elicitation_outcome_events(outcome, turn_context, user_id, conversation_id):
    context = {
        **turn_context,
        **{key: outcome[key] for key in ('memory_audience', 'memory_scope') if key in outcome},
    }
    try:
        _validate_turn_memory_context(context, user_id, conversation_id)
    except (OrchestrationMemoryError, ConversationContextError, AzureError) as exc:
        log_event(
            '[ORCHESTRATION] Saved context could not be authorized for publication.',
            level=logging.WARNING, extra={'error_type': type(exc).__name__},
        )
        yield build_error_event(
            exc.message if isinstance(exc, OrchestrationMemoryError)
            else 'Conversation context changed or is unavailable. Create a new request.',
            conversation_id,
        )
        return
    if outcome['kind'] == 'elicitation':
        yield build_elicitation_event(outcome['document'])
    else:
        yield build_planning_thought('Plan ready.', status='completed')
        yield build_plan_event(outcome['document'])


def _persist_planned_turn(
    plan, turn_context, user_id, conversation_id, submission=None, expected_previous_run=None,
):
    _validate_turn_memory_context(turn_context, user_id, conversation_id)
    latest = get_latest_turn_run(conversation_id, user_id, turn_context['turn_id'])
    if latest and latest['run_id'] != plan['run_id']:
        expected_previous_run = expected_previous_run or read_revision_run(
            latest['run_id'], user_id, conversation_id,
        )
    message_id, fingerprint = _save_turn_message(
        conversation_id, user_id, turn_context['turn_id'], turn_context['user_message'],
        previous=turn_context, prompt_selection=turn_context.get('prompt_selection'),
    )
    turn_context['user_message_id'] = message_id
    turn_context['user_message_fingerprint'] = fingerprint
    create_orchestration_run(
        plan, user_id, conversation_id=conversation_id, idempotent=True,
        turn_context=turn_context, expected_previous_run=expected_previous_run,
    )
    if submission:
        prepare_elicitation_outcome(submission, 'plan', plan, turn_context)


def _save_turn_message(conversation_id, user_id, turn_id, message, previous=None, prompt_selection=None):
    """A stable ID makes retries and revised plans reuse their original user message."""
    _authorize_context_conversation(conversation_id, user_id)
    message_id = (previous or {}).get('user_message_id') or (
        f"user_orchestration_{uuid.uuid5(uuid.NAMESPACE_URL, f'{conversation_id}:{turn_id}').hex}"
    )
    try:
        stored = cosmos_messages_container.read_item(
            item=message_id, partition_key=conversation_id
        )
    except CosmosResourceNotFoundError:
        stored = None
    if stored is not None:
        normalized = normalize_history_message(stored)
        if (
            not normalized or normalized['role'] != 'user'
            or stored.get('conversation_id') != conversation_id
            or normalized['content'] != message
            or (
                (previous or {}).get('user_message_fingerprint')
                and normalized['fingerprint'] != previous['user_message_fingerprint']
            )
        ):
            raise ConversationContextError('This turn changed. Submit a new request.')
        return message_id, normalized['fingerprint']
    # The flat turn id is what ties a reloaded thread back to its run: the live card stamps
    # the same field on its optimistic bubble, and a message fetched from the server has
    # nothing to match against without it. It belongs on every orchestrated question, not
    # only the ones that happened to carry a saved prompt.
    metadata = {
        'orchestration': {'turn_id': turn_id},
        'orchestration_turn_id': turn_id,
    }
    if prompt_selection:
        metadata['prompt_selection'] = prompt_selection
    saved = _save_message(
        conversation_id, 'user', message,
        metadata=metadata,
        message_id=message_id,
    )
    if not saved:
        raise ConversationContextError('The user message could not be saved.')
    stored = cosmos_messages_container.read_item(item=saved, partition_key=conversation_id)
    return saved, normalize_history_message(stored)['fingerprint']


def _sum_token_usage(*usages):
    total = {}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                total[field] = total.get(field, 0) + value
    return total


def _save_pending_elicitation(
    elicitation, turn_context, user_id, conversation_id, turn_id,
    *, submission=None, expected_pending=None,
):
    _validate_turn_memory_context(turn_context, user_id, conversation_id)
    question = {
        **elicitation,
        'turn_id': turn_id,
        'conversation_id': conversation_id,
    }
    if submission:
        outcome = prepare_elicitation_outcome(submission, 'elicitation', question, turn_context)
        complete_elicitation_submission(submission)
        return outcome
    pending = create_pending_elicitation(
        question, turn_context, user_id, conversation_id, turn_id,
        expected_pending=expected_pending,
    )
    if pending.get('status') == 'completed':
        return pending['submissions'][-1]['outcome']
    return {'kind': 'elicitation', 'document': pending['question']}


def _touch_conversation(conversation_id, user_id, title=None):
    """Move a conversation to the top of the list, and name it if it has no name yet."""


    try:
        item = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id
        )
    except Exception:
        return None

    if item.get('user_id') != user_id:
        return None

    item['last_updated'] = _now_iso()
    if title and item.get('title') in (None, '', 'New Conversation'):
        item['title'] = _text(title, 80)

    try:
        cosmos_conversations_container.upsert_item(item)
    except Exception as exc:
        log_event(f"[ORCHESTRATION] Could not touch a conversation: {exc}",
                  level=logging.WARNING)
    return item


def _run_summary_row(record):
    """Project a stored run down to what the drawer's map view actually reads.

    An allowlist rather than a blocklist, and deliberately so. The stored run holds the whole
    plan -- every step, with its inputs and its document lists -- alongside the ``seeds`` that
    constrained it, and the map view needs none of it: ``plan_summary`` already carries the
    intent, the step count and the capabilities. Returning the record as stored would put
    twenty-five full plans on the wire to draw twenty-five one-line rows, and would ship the
    request's internal seeding to the browser as a side effect of a listing. Anything a future
    field adds to the record therefore stays server-side until it is named here.
    """
    record = record if isinstance(record, dict) else {}
    approval = record.get('approval') if isinstance(record.get('approval'), dict) else {}
    return {
        'run_id': record.get('run_id') or record.get('id'),
        'conversation_id': record.get('conversation_id'),
        'turn_id': record.get('turn_id'),
        'turn_index': _coerce_int(record.get('turn_index')),
        'status': record.get('status'),
        'created_at': record.get('created_at'),
        'started_at': record.get('started_at'),
        'completed_at': record.get('completed_at'),
        'error': _text(record.get('error'), 400) or None,
        'user_message': _text(record.get('user_message'), 400),
        'user_message_id': record.get('user_message_id'),
        'assistant_message_id': record.get('assistant_message_id'),
        'plan_summary': record.get('plan_summary') or {},
        'capabilities_used': list(record.get('capabilities_used') or ()),
        'artifact_count': len(record.get('artifacts') or ()),
        'revision': _coerce_int(record.get('revision')),
        # Only the two approval fields the card reads. `approved_by` is a user id and has no
        # business being echoed back to a browser that already knows whose runs these are.
        'approval': {
            'mode': approval.get('mode'),
            'state': approval.get('state'),
        },
    }


def _run_detail_row(record):
    """One run in full, for opening a stored plan rather than listing it.

    The summary plus the plan itself, which is the only heavy field the client ever wants and
    only ever for one run at a time. Built on the same allowlist so that the listing and the
    detail cannot drift into disagreeing about what a run looks like.
    """
    record = record if isinstance(record, dict) else {}
    row = _run_summary_row(record)
    row['plan'] = deepcopy(record['plan']) if isinstance(record.get('plan'), dict) else {}
    if row['plan']:
        if not isinstance(row['plan'].get('inputs'), dict):
            row['plan']['inputs'] = {}
        if isinstance(record.get('seeds'), dict):
            row['plan']['inputs']['required_capabilities'] = required_capability_ids(record['seeds'])
        else:
            row['plan']['inputs'].setdefault('required_capabilities', [])
        row['plan']['reasoning_adjustments'] = merge_reasoning_adjustments(
            row['plan'].get('reasoning_adjustments'), record.get('reasoning_adjustments'),
        )
    return row


def _plan_edit_identity(data, settings):
    if not isinstance(data, dict):
        raise PlanRevisionError('An editor request must be an object.', code='invalid_request', status_code=400)
    user_id = get_current_user_id()
    if not user_id:
        raise PlanRevisionError('User not authenticated.', code='unauthenticated', status_code=401)
    if not _orchestration_enabled(settings):
        raise PlanRevisionError('Chat orchestration is not enabled.', code='disabled', status_code=403)
    conversation_id = data.get('conversation_id')
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise PlanRevisionError('A conversation is required.', code='invalid_request', status_code=400)
    conversation_id = conversation_id.strip()
    try:
        _authorize_context_conversation(conversation_id, user_id)
    except ConversationContextError as exc:
        raise PlanRevisionError('Plan not found.', code='not_found', status_code=404) from exc
    return user_id, conversation_id


def _plan_edit_error(exc):
    if isinstance(exc, PlanRevisionError):
        payload = {'error': exc.message, 'code': exc.code}
        if exc.current_run_id:
            payload['current_run_id'] = exc.current_run_id
        status = exc.status_code
    elif isinstance(exc, OrchestrationMemoryError):
        payload = {'error': exc.message, 'code': exc.code}
        status = 409 if exc.code in ('memory_audience_changed', 'memory_scope_unavailable') else 503
    elif isinstance(exc, ElicitationContextError):
        payload = {'error': 'The answers were not valid.', 'code': 'invalid_request', 'details': [exc.message]}
        if exc.field:
            payload['field_errors'] = {exc.field: exc.message}
        status = 400
    elif isinstance(exc, ConversationContextError):
        payload = {
            'error': 'Conversation context changed or is unavailable. Create a new plan.',
            'code': 'plan_changed',
        }
        status = 409
    elif isinstance(exc, PlannerError):
        payload = {
            'error': 'The requested change could not be planned. Your previous plan is unchanged. Please retry.',
            'code': 'unavailable',
        }
        status = 503
    elif isinstance(exc, CatalogResolutionError):
        payload = {'error': exc.message, 'code': exc.code}
        status = 409 if exc.code == 'selected_agent_unavailable' else 503
    elif isinstance(exc, CapabilityResolutionError):
        payload = {
            'error': 'Available capabilities could not be loaded. Your previous plan is unchanged. Please retry.',
            'code': 'capability_context_unavailable',
        }
        status = 503
    else:
        payload = {
            'error': 'The plan change could not be confirmed. Reload the plan or retry to recover its saved state.',
            'code': 'unavailable',
        }
        status = 503
    log_event(
        '[ORCHESTRATION] Plan editor request could not be completed.',
        level=logging.WARNING, extra={'error_type': type(exc).__name__, 'code': payload['code']},
    )
    return payload, status


def _plan_editor_event(record, user_id):
    editor = plan_editor_state(record, user_id)
    question = editor['pending']
    return serialize_sse({
        'type': 'orchestration_elicitation' if question else 'orchestration_plan',
        **({'elicitation': question} if question else {'plan': editor['plan']}),
        'editor': editor, 'done': True,
    })


def register_route_backend_orchestration(bp):

    @bp.route("/api/v2/orchestration/plan", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_plan():
        """Plan one request, streaming progress and ending with a plan or a question."""
        settings = get_settings()
        if not _orchestration_enabled(settings):
            return jsonify({'error': 'Chat orchestration is not enabled.'}), 403

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'A plan request must be an object.'}), 400
        message = _text(data.get('message'))
        is_reply = 'elicitation_response' in data
        if not message and not is_reply:
            return jsonify({'error': 'A message is required.'}), 400

        conversation_id = _text(data.get('conversation_id'))
        turn_id = _text(data.get('turn_id')) or f"turn_{uuid.uuid4().hex}"
        revision = 0
        try:
            revision = max(0, int(data.get('revision') or 0))
        except (TypeError, ValueError):
            revision = 0

        approval_mode = _text(data.get('approval_mode')).lower()
        if not settings.get('chat_orchestration_allow_user_approval_override', True):
            approval_mode = ''

        seeds = resolve_seeds(data)
        replan_hint = _text(data.get('replan_hint'), 600)
        answered_record = []
        submission = None
        allow_elicitation = True
        prompt_selection = build_prompt_selection_metadata(data.get('prompt_info'), message)
        turn_context = {
            'user_message': message,
            'turn_id': turn_id,
            'seeds': seeds,
            'original_seeds': deepcopy(seeds),
            'answered_questions': [],
            'prompt_selection': prompt_selection,
            'planning_token_usage': {},
            'approval_mode': approval_mode,
            'replan_hint': replan_hint,
        }
        prior_elicitation = data.get('elicitation')
        if is_reply:
            try:
                if not conversation_id or not data.get('turn_id'):
                    raise ElicitationStateError('This question has expired. Please send the request again.')
                # Do not create a missing conversation on the answer path, and never use a
                # browser-supplied question/schema as the authority for validating a reply.
                conversation = cosmos_conversations_container.read_item(
                    item=conversation_id, partition_key=conversation_id,
                )
                if conversation.get('user_id') != user_id:
                    raise ElicitationStateError('This question has expired. Please send the request again.')
                if isinstance(prior_elicitation, dict) and (
                    prior_elicitation.get('conversation_id') not in (None, '', conversation_id)
                    or prior_elicitation.get('turn_id') not in (None, '', turn_id)
                ):
                    raise ElicitationContextError('The clarification belongs to a different turn.')
                response = data.get('elicitation_response')
                if not isinstance(response, dict):
                    raise ElicitationContextError('The question response must be an object.')
                answer_context = data.get('elicitation_context')
                if response.get('action') in ('decline', 'cancel'):
                    response = {'action': response['action'], 'content': {}}
                    answer_context = {}
                try:
                    fingerprint_data = json.dumps(
                        {'response': response, 'context': answer_context or {}},
                        sort_keys=True, ensure_ascii=False, allow_nan=False,
                    ).encode('utf-8')
                except (TypeError, ValueError) as exc:
                    raise ElicitationContextError('The answer contains an invalid value.') from exc
                if len(fingerprint_data) > ELICITATION_CONTEXT_BYTE_LIMIT:
                    raise ElicitationContextError('The answer is too large. Shorten it and try again.')
                fingerprint = hashlib.sha256(fingerprint_data).hexdigest()
                question_id = data.get('elicitation_id')
                question_revision = data.get('elicitation_revision')
                submission_id = data.get('elicitation_submission_id')
                if (
                    all(value is None for value in (question_id, question_revision, submission_id))
                    and isinstance(prior_elicitation, dict)
                    and prior_elicitation.get('elicitation_id') is not None
                ):
                    # Older upstream clients return the question envelope. Only its
                    # identity is used; its schema, labels, and message are never trusted.
                    question_id = prior_elicitation.get('elicitation_id')
                    question_revision = prior_elicitation.get('revision')
                    submission_id = 'legacy_' + hashlib.sha256(
                        f'{question_id}:{question_revision}:{fingerprint}'.encode('utf-8')
                    ).hexdigest()
                submission = claim_elicitation_submission(
                    user_id, conversation_id, turn_id,
                    fingerprint, elicitation_id=question_id,
                    revision=question_revision, submission_id=submission_id,
                )
                if submission.get('replayed'):
                    _conversation_context_for_run({
                        **submission['record']['turn_context'], 'conversation_id': conversation_id,
                    }, user_id, settings)
                    return _sse(_elicitation_outcome_events(
                        submission['outcome'], submission['record']['turn_context'],
                        user_id, conversation_id,
                    ))
                pending = submission['record']
                if submission.get('outcome'):
                    turn_context = deepcopy(pending['prepared']['turn_context'])
                else:
                    turn_context = deepcopy(pending['turn_context'])
                    question = pending['question']
                    validated, normalized_context = normalize_elicitation_answer(
                        question, response, answer_context,
                        user_id, conversation_id, settings=settings,
                    )
                    turn_context['answered_questions'] = [
                        *(turn_context.get('answered_questions') or []),
                        {
                            'elicitation_id': question['elicitation_id'],
                            'revision': question['revision'],
                            'question': question['message'],
                            'action': validated['action'],
                            'answer': validated['content'],
                            'context': normalized_context,
                        },
                    ]
                    if len(json.dumps(turn_context['answered_questions']).encode('utf-8')) > ELICITATION_CONTEXT_BYTE_LIMIT:
                        raise ElicitationContextError('This turn has too much answer context. Start a new request with a shorter summary.')
                    if validated['action'] == ELICITATION_ACTION_ACCEPT:
                        turn_context['seeds'] = merge_elicitation_context(turn_context['seeds'], normalized_context)
                    allow_elicitation = validated['action'] == ELICITATION_ACTION_ACCEPT
                # These values come from the original turn, not the answer request. In
                # particular a local answer prompt cannot replace the main prompt/model.
                message = turn_context['user_message']
                seeds = turn_context['seeds']
                answered_record = turn_context['answered_questions']
                validate_clarification_answers(answered_record)
                _conversation_context_for_run({
                    **turn_context, 'conversation_id': conversation_id,
                }, user_id, settings)
                approval_mode = turn_context.get('approval_mode', '')
                if not settings.get('chat_orchestration_allow_user_approval_override', True):
                    approval_mode = ''
                replan_hint = turn_context.get('replan_hint', '')
                revision = pending['question']['revision'] + 1
                resolve_elicitation_references(
                    seeds.get('elicitation_references') or [],
                    user_id, conversation_id, settings=settings,
                )
            except ElicitationStateError as exc:
                release_elicitation_submission(submission)
                if (
                    exc.code == 'elicitation_expired'
                    and not isinstance(prior_elicitation, dict)
                    and not any(key in data for key in (
                        'elicitation_id', 'elicitation_revision', 'elicitation_submission_id',
                    ))
                ):
                    return jsonify({'error': exc.message, 'code': exc.code}), 400
                return jsonify({'error': exc.message, 'code': exc.code}), exc.status_code
            except ElicitationContextError as exc:
                release_elicitation_submission(submission)
                payload = {'error': 'The answers were not valid.', 'details': [exc.message]}
                if exc.field:
                    payload['field_errors'] = {exc.field: exc.message}
                return jsonify(payload), 400
            except ConversationContextError:
                release_elicitation_submission(submission)
                return jsonify({
                    'error': 'Conversation context changed or is unavailable. Create a new request.',
                }), 409
            except exceptions.CosmosResourceNotFoundError:
                release_elicitation_submission(submission)
                return jsonify({
                    'error': 'This question has expired. Please send the request again.',
                    'code': 'elicitation_expired',
                }), 409
            except Exception as exc:
                release_elicitation_submission(submission)
                log_event(
                    '[ORCHESTRATION] Clarification could not be resumed.',
                    extra={'exception_type': type(exc).__name__}, level=logging.ERROR,
                )
                return jsonify({'error': 'The answer could not be checked. Please retry.'}), 503

        # Capture stable caller identity now; resolve the model only after the stream
        # restores the original turn's canonical seeds.
        identity = _request_identity(user_id)
        planner_model = None

        def close_planning_resources():
            try:
                if planner_model is not None:
                    planner_model.close()
            finally:
                release_elicitation_submission(submission)

        def generate():
            nonlocal turn_context, seeds, answered_record, approval_mode, replan_hint, planner_model
            try:
                if submission and submission.get('outcome'):
                    outcome = submission['outcome']
                    _validate_turn_memory_context(turn_context, user_id, conversation_id)
                    if outcome['kind'] == 'plan':
                        _persist_planned_turn(
                            outcome['document'], turn_context, user_id, conversation_id, submission,
                        )
                    complete_elicitation_submission(submission)
                    yield from _elicitation_outcome_events(outcome, turn_context, user_id, conversation_id)
                    return
                if submission:
                    _authorize_context_conversation(conversation_id, user_id)
                    resolved_conversation_id, created = conversation_id, False
                else:
                    resolved_conversation_id, created = _ensure_conversation(
                        conversation_id, user_id, title=message
                    )
                if not resolved_conversation_id:
                    yield build_error_event('That conversation could not be opened.')
                    return
                if created or not conversation_id:
                    # Announced with the same event the chat stream uses, so the client
                    # adopts a new conversation's id by the path it already knows.
                    yield build_conversation_metadata_event(
                        resolved_conversation_id, _text(message, 80)
                    )

                observed_pending = None
                current_revision = revision
                planning_base = None
                if submission:
                    snapshot = _conversation_context_for_run({
                        **turn_context, 'conversation_id': resolved_conversation_id,
                    }, user_id, settings)
                else:
                    previous = get_latest_turn_run(resolved_conversation_id, user_id, turn_id)
                    observed_pending = get_pending_elicitation(
                        user_id, resolved_conversation_id, turn_id,
                    )
                    if observed_pending and observed_pending.get('status') != 'completed':
                        pending_context = observed_pending['turn_context']
                        if pending_context['user_message'] != message:
                            raise ConversationContextError('This turn changed. Submit a new request.')
                        _conversation_context_for_run({
                            **pending_context, 'conversation_id': resolved_conversation_id,
                        }, user_id, settings)
                        yield from _elicitation_outcome_events(
                            {'kind': 'elicitation', 'document': observed_pending['question']},
                            pending_context, user_id, resolved_conversation_id,
                        )
                        return
                    if observed_pending:
                        completed = (observed_pending.get('submissions') or [])[-1:]
                        completed_plan = (completed[0].get('outcome') or {}).get('document') if completed else None
                        if completed_plan and (
                            not previous or int(completed_plan.get('revision') or 0) > int(previous.get('revision') or 0)
                        ):
                            previous = get_orchestration_run(
                                completed_plan['run_id'], user_id, resolved_conversation_id,
                            )
                            if not previous:
                                raise ConversationContextError('The last plan could not be opened. Submit a new request.')
                    if previous:
                        planning_base = read_revision_run(
                            previous['run_id'], user_id, resolved_conversation_id,
                        )
                        if (
                            planning_base.get('edit_version') or planning_base.get('started_at')
                            or planning_base.get('status') not in ('draft', 'awaiting_approval', 'approved')
                        ):
                            raise PlanRevisionError(
                                'Use the plan editor to revise this plan, or send a new request.',
                                current_run_id=planning_base.get('superseded_by_run_id') or planning_base['run_id'],
                            )
                        if previous.get('user_message') != message:
                            raise ConversationContextError('This turn changed. Submit a new request.')
                        snapshot = _conversation_context_for_run(previous, user_id, settings)
                        current_revision = max(revision, int(previous.get('revision') or 0) + 1)
                        for key in (
                            'user_message_id', 'user_message_fingerprint', 'seeds', 'original_seeds',
                            'answered_questions', 'prompt_selection', 'memory_audience', 'memory_scope',
                        ):
                            if key in previous:
                                turn_context[key] = deepcopy(previous[key])
                        seeds = turn_context['seeds']
                        answered_record = turn_context['answered_questions']
                    else:
                        snapshot = _load_conversation_snapshot(
                            resolved_conversation_id, user_id, settings, turn_id=turn_id,
                        )
                turn_context['conversation_context'] = snapshot
                turn_context['revision'] = current_revision
                validate_clarification_answers(answered_record)
                resolve_elicitation_references(
                    seeds.get('elicitation_references') or [],
                    user_id, resolved_conversation_id, settings=settings,
                )
                action_catalog = resolve_action_catalog(
                    user_id, seeds=seeds, settings=settings,
                    user_groups=seeds.get('active_group_ids') or None,
                )
                planning_identity = dict(identity)
                if isinstance(seeds.get('agent'), dict) and seeds['agent'].get('name'):
                    planning_identity['user_enable_agents'] = True
                try:
                    planner_model = resolve_orchestration_model(
                        settings, user_id=user_id, seeds=seeds, planner=True,
                        identity_context=planning_identity,
                    )
                    seeds['model'] = planner_model.answer_model_selection()
                    turn_context['original_seeds'] = {
                        **(turn_context.get('original_seeds') or seeds),
                        'model': dict(seeds['model']),
                    }
                except (ValueError, PermissionError, PlannerError, AzureError) as exc:
                    log_event(
                        '[ORCHESTRATION] The planner model could not be selected.',
                        level=logging.WARNING, extra={'error_type': type(exc).__name__},
                    )
                    yield build_error_event(
                        'The selected model is unavailable. Choose an enabled model you can access.',
                        resolved_conversation_id,
                    )
                    return
                resolution = resolve_conversation_request(
                    message, snapshot, settings=settings, answered_questions=answered_record,
                    planner_model=planner_model,
                )
                reasoning_adjustments = build_model_reasoning_metadata(
                    planner_model, 'planner',
                ).get('reasoning_adjustments', [])
                if reasoning_adjustments:
                    yield build_reasoning_adjustment_event(reasoning_adjustments)
                planning_usage = _sum_token_usage(
                    turn_context.get('planning_token_usage'), resolution.get('token_usage')
                )
                turn_context['planning_token_usage'] = planning_usage
                if resolution['relationship'] == 'clarification':
                    if not allow_elicitation:
                        resolution.update({
                            'relationship': 'follow_up',
                            'resolved_message': message,
                            'message_ids': [item['id'] for item in snapshot['messages']],
                            'requires_retrieval': False,
                        })
                if resolution['relationship'] == 'clarification':
                    question = resolution['clarification']
                    elicitation = normalize_elicitation({
                        'message': question,
                        'requested_schema': {
                            'type': 'object',
                            'properties': {'clarification': {'type': 'string', 'title': question}},
                            'required': ['clarification'],
                        },
                    }, run_id=None, revision=current_revision)
                    outcome = _save_pending_elicitation(
                        elicitation, turn_context, user_id, resolved_conversation_id, turn_id,
                        submission=submission, expected_pending=observed_pending,
                    )
                    yield from _elicitation_outcome_events(
                        outcome, turn_context, user_id, resolved_conversation_id,
                    )
                    return

                effective_message = resolution['resolved_message']
                turn_context['request_resolution'] = resolution
                turn_context['resolved_message'] = effective_message
                effective_request = build_elicitation_user_request(effective_message, answered_record)
                memory_context = load_orchestration_memory(
                    user_id, _authorize_context_conversation(resolved_conversation_id, user_id),
                    effective_request, settings=settings, seeds=seeds,
                    expected_audience=turn_context.get('memory_audience'),
                )
                turn_context['memory_audience'] = memory_context['audience']
                turn_context['memory_scope'] = memory_context['scope']
                for notice in memory_context['notices']:
                    yield build_planning_thought(notice)
                if (
                    resolution.get('requires_retrieval') is False
                    and not seeds.get('document_ids') and not seeds.get('elicitation_references')
                ):
                    candidates = []
                else:
                    candidates, _probed = resolve_candidate_documents(
                        effective_request, user_id, seeds=seeds,
                        conversation_id=resolved_conversation_id, settings=settings,
                    )
                ledger = _load_ledger(resolved_conversation_id, user_id, settings)
                signals = build_conversation_signals(
                    snapshot['messages'], message, truncated=snapshot['truncated'],
                    message_ids=resolution['message_ids'],
                )
                allowed_user_urls = conversation_user_urls(
                    message, snapshot, resolution['message_ids'], answered_record
                )
                signals['urls'] = allowed_user_urls

                authorized = _authorized_document_ids(candidates, seeds)
                labels = _document_labels(candidates)

                yield build_planning_thought('Deciding what this question needs.')
                agent_catalog = resolve_agent_catalog(
                    user_id, seeds=seeds, settings=settings,
                    user_groups=seeds.get('active_group_ids') or None,
                ) if planning_identity.get('user_enable_agents', True) else []

                context = build_planner_context(
                    effective_message, candidates=candidates, seeds=seeds, ledger=ledger,
                    signals=signals, agents=agent_catalog, original_message=message,
                    request_resolution=resolution, actions=action_catalog,
                    answered_questions=answered_record,
                    memory_context=memory_context,
                )
                if answered_record:
                    context['answered_now'] = answered_record

                kind, plan = plan_request(
                    effective_message, context, resolved_conversation_id, user_id,
                    settings=settings,
                    approval_mode=approval_mode,
                    authorized_document_ids=authorized,
                    replan_hint=replan_hint or None,
                    revision=current_revision,
                    allow_elicitation=allow_elicitation,
                    turn_id=turn_id, seeds=seeds, document_labels=labels,
                    request_context=_capability_request_context(
                        user_id, planning_identity, message, agent_catalog,
                        action_catalog,
                        allowed_user_urls=allowed_user_urls,
                    ),
                    planner_model=planner_model,
                )

                planning_usage = _sum_token_usage(planning_usage, plan.get('token_usage'))
                turn_context['planning_token_usage'] = planning_usage
                if kind == 'elicitation':
                    plan['revision'] = current_revision
                    outcome = _save_pending_elicitation(
                        plan, turn_context, user_id, resolved_conversation_id, turn_id,
                        submission=submission, expected_pending=observed_pending,
                    )
                    yield from _elicitation_outcome_events(
                        outcome, turn_context, user_id, resolved_conversation_id,
                    )
                    return

                plan['revision'] = current_revision
                outcome = {'kind': kind, 'document': plan}
                if submission:
                    outcome = prepare_elicitation_outcome(submission, kind, plan, turn_context)
                _persist_planned_turn(
                    plan, turn_context, user_id, resolved_conversation_id, submission,
                    expected_previous_run=planning_base,
                )
                if submission:
                    complete_elicitation_submission(submission)
                yield from _elicitation_outcome_events(
                    outcome, turn_context, user_id, resolved_conversation_id,
                )

            except PlanRevisionError as exc:
                payload, _status = _plan_edit_error(exc)
                yield serialize_sse(payload)
            except ConversationResolutionError as exc:
                log_event(
                    '[ORCHESTRATION] The conversational request could not be interpreted.',
                    level=logging.WARNING,
                    extra={
                        'stage': 'request_resolution', 'reason': exc.reason,
                        'attempt': exc.attempts, 'error_type': type(exc).__name__,
                        'resource': f"conversation:{hashlib.sha256(resolved_conversation_id.encode('utf-8')).hexdigest()}",
                    },
                )
                yield build_error_event(
                    'The conversation could not be interpreted. Please retry your request.',
                    resolved_conversation_id,
                )
            except ConversationContextError as exc:
                log_event(
                    '[ORCHESTRATION] Conversation context could not be used for planning.',
                    level=logging.WARNING, extra={'error_type': type(exc).__name__},
                )
                yield build_error_event(
                    'Conversation context could not be used. Retry or create a new plan.',
                    conversation_id,
                )
            except (PlannerError, OrchestrationMemoryError) as exc:
                yield build_error_event(exc.message, resolved_conversation_id)
            except (CatalogResolutionError, CapabilityResolutionError) as exc:
                log_event(
                    '[ORCHESTRATION] Capability context could not be loaded.',
                    level=logging.WARNING, extra={'reason': 'capability_context_failed', 'error_type': type(exc).__name__},
                )
                yield build_error_event(exc.message, resolved_conversation_id)
            except Exception as exc:
                log_event(
                    '[ORCHESTRATION] Planning failed.',
                    extra={'exception_type': type(exc).__name__}, level=logging.ERROR,
                )
                yield build_error_event('The request could not be planned or saved. Please retry.', conversation_id)
            finally:
                close_planning_resources()

        streamed = _sse(stream_with_context(generate()))
        streamed.call_on_close(close_planning_resources)
        return streamed

    @bp.route("/api/v2/orchestration/runs/<run_id>/editor", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_plan_editor(run_id):
        """Read the current revision and paged history without approving or pausing it."""
        try:
            settings = get_settings()
            user_id, conversation_id = _plan_edit_identity(request.args.to_dict(), settings)
            before = request.args.get('before_revision')
            if before is not None:
                if len(before) > 10 or not before.isdecimal():
                    raise PlanRevisionError('Invalid history cursor.', code='invalid_request', status_code=400)
                before = int(before)
            record = read_revision_run(run_id, user_id, conversation_id, follow_current=True)
            return jsonify({'editor': plan_editor_state(record, user_id, before_revision=before)})
        except (PlanRevisionError, ConversationContextError, AzureError) as exc:
            payload, status = _plan_edit_error(exc)
            return jsonify(payload), status

    @bp.route("/api/v2/orchestration/runs/<run_id>/edit", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_begin_plan_edit(run_id):
        """Acquire a durable manual approval hold before editing."""
        try:
            settings = get_settings()
            data = request.get_json(silent=True)
            user_id, conversation_id = _plan_edit_identity(data, settings)
            if set(data) - {'conversation_id', 'plan_id', 'edits', 'expected_version'}:
                raise PlanRevisionError('Invalid edit request fields.', code='invalid_request', status_code=400)
            record = read_revision_run(run_id, user_id, conversation_id)
            _conversation_context_for_run(record, user_id, settings)
            record = begin_plan_edit(
                run_id, user_id, conversation_id, plan_id=data.get('plan_id'),
                edits=data.get('edits'), expected_version=data.get('expected_version'),
            )
            return jsonify({'editor': plan_editor_state(record, user_id)})
        except (PlanRevisionError, ConversationContextError, AzureError) as exc:
            payload, status = _plan_edit_error(exc)
            return jsonify(payload), status

    @bp.route("/api/v2/orchestration/runs/<run_id>/revisions", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_revise_plan(run_id):
        """Ask, answer a planner question, restore a version, or discard a pending change."""
        claim = None
        try:
            settings = get_settings()
            data = request.get_json(silent=True)
            user_id, conversation_id = _plan_edit_identity(data, settings)
            record = read_revision_run(run_id, user_id, conversation_id)
            snapshot = _conversation_context_for_run(record, user_id, settings)
            claim = claim_plan_revision(run_id, user_id, conversation_id, data)
            identity = _request_identity(user_id, seeded_agent=(record.get('seeds') or {}).get('agent'))
        except (PlanRevisionError, ConversationContextError, ElicitationContextError, AzureError) as exc:
            release_plan_revision(claim)
            payload, status = _plan_edit_error(exc)
            return jsonify(payload), status

        def generate_revision():
            try:
                if claim.get('replayed'):
                    saved = read_revision_run(
                        claim['outcome_run_id'], user_id, conversation_id, follow_current=True,
                    )
                else:
                    yield build_planning_thought('Updating the plan without running it.')
                    outcome = build_plan_edit_outcome(
                        claim['record'], claim['request'], user_id, settings,
                        identity=identity, conversation_context=snapshot,
                        conversation=_authorize_context_conversation(conversation_id, user_id),
                        ledger=_load_ledger(conversation_id, user_id, settings),
                    )
                    _conversation_context_for_run(record, user_id, settings)
                    _validate_turn_memory_context(
                        outcome.get('turn_context') or record, user_id, conversation_id,
                    )
                    if outcome['kind'] == 'plan':
                        outcome['document'] = validate_edited_plan(
                            outcome['document'], outcome['turn_context'], user_id,
                            get_settings(), identity,
                        )
                    saved = complete_plan_revision(claim, **outcome)
                _validate_turn_memory_context(saved, user_id, conversation_id)
                yield _plan_editor_event(saved, user_id)
            except (
                PlanRevisionError, ConversationContextError, ElicitationContextError,
                PlannerError, CatalogResolutionError, CapabilityResolutionError, OrchestrationMemoryError, AzureError,
            ) as exc:
                payload, _status = _plan_edit_error(exc)
                yield serialize_sse(payload)
            finally:
                release_plan_revision(claim)

        streamed = _sse(stream_with_context(generate_revision()))
        streamed.call_on_close(lambda: release_plan_revision(claim))
        return streamed

    @bp.route("/api/v2/orchestration/run", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_run():
        """Execute an approved plan, streaming step progress and the answer."""
        settings = get_settings()
        if not _orchestration_enabled(settings):
            return jsonify({'error': 'Chat orchestration is not enabled.'}), 403

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or 'plan' in data:
            return jsonify({'error': 'Run the saved plan by its ID, not a submitted plan.'}), 400
        run_id = _text(data.get('run_id'))
        conversation_id = _text(data.get('conversation_id'))
        if not run_id:
            return jsonify({'error': 'A run id is required.'}), 400

        record = get_orchestration_run(run_id, user_id, conversation_id=conversation_id)
        if not record:
            # Ownership is enforced inside the store, so a run belonging to somebody else is
            # indistinguishable from one that does not exist. That is the intent.
            return jsonify({'error': 'Run not found.'}), 404

        plan = record.get('plan') or {}
        if record.get('status') in (PLAN_STATUS_RUNNING, PLAN_STATUS_COMPLETED):
            return jsonify({'error': 'This plan has already been run.', 'code': 'already_run'}), 409

        conversation_id = conversation_id or _text(record.get('conversation_id'))
        try:
            snapshot = _conversation_context_for_run(record, user_id, settings)
        except ConversationContextError:
            return jsonify({
                'error': 'Conversation context changed or is unavailable. Create a new plan.',
                'code': 'plan_changed',
            }), 409
        except AzureError as exc:
            log_event(
                '[ORCHESTRATION] Could not load conversation context for execution.',
                level=logging.ERROR, extra={'error_type': type(exc).__name__},
            )
            return jsonify({'error': 'Conversation history could not be loaded. Please retry.'}), 503
        # Legacy records are hydrated once. The finalization callback must validate this
        # exact snapshot rather than silently loading a different history and discarding it.
        record = {**record, 'conversation_context': snapshot}

        seeds = record.get('seeds') if isinstance(record.get('seeds'), dict) else {}
        try:
            resolve_elicitation_references(
                seeds.get('elicitation_references') or [],
                user_id, conversation_id, settings=settings,
            )
        except ElicitationContextError as exc:
            return jsonify({
                'error': 'Some accepted answer context is no longer available.',
                'code': 'plan_changed',
                'details': [exc.message],
            }), 409

        # One accumulator for the whole run, filled by every model call the closure makes.
        run_token_usage = _sum_token_usage(record.get('planning_token_usage'))
        user_message = _text(record.get('user_message')) or _text(
            (plan.get('intent') or {}).get('summary')
        )
        resolution = record.get('request_resolution') or {}
        context_message_ids = resolution.get('message_ids')
        allowed_user_urls = revision_allowed_urls({
            **record, 'user_message': user_message, 'conversation_context': snapshot,
        })

        # Captured out here, on the request thread, and closed over by the generator. A
        # streamed response's generator body runs after the view has returned, so reading
        # the session from inside it would be reading a context that is already gone.
        identity = _request_identity(user_id, seeded_agent=seeds.get('agent'))
        agent_execution_identity = capture_execution_identity(user_id, conversation_id)

        # Resolved again rather than read back off the plan. Planning and running are
        # separate requests, and an agent the user could reach when the plan was made is not
        # necessarily one they can reach now -- the same reason document authorization is
        # rechecked before the answer is composed. Still once per run, never per step.
        try:
            agent_catalog = resolve_agent_catalog(
                user_id, seeds=seeds, settings=settings,
                user_groups=seeds.get('active_group_ids') or None,
            ) if identity.get('user_enable_agents', True) else []
            action_catalog = resolve_action_catalog(
                user_id, seeds=seeds, settings=settings,
                user_groups=seeds.get('active_group_ids') or None,
            )
            effective_plan = apply_plan_edits(
                deepcopy(plan), data.get('edits', record.get('edit_narrowing')),
            )
            required_steps = {
                step['capability_id'] for step in effective_plan.get('steps') or []
                if step.get('enabled', True)
            }
            available_steps = set(resolve_available_capability_ids(
                settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
                candidate_ids=required_steps,
                request_context=_capability_request_context(
                    user_id, identity, user_message, agent_catalog, action_catalog,
                    allowed_user_urls=allowed_user_urls,
                ),
            ))
            if required_steps - available_steps:
                return jsonify({
                    'error': 'A planned operation is no longer available. Review or recreate the plan.',
                    'code': 'plan_changed',
                }), 409
        except (CatalogResolutionError, CapabilityResolutionError, AzureError) as exc:
            log_event(
                '[ORCHESTRATION] Execution capability context could not be loaded.',
                level=logging.WARNING, extra={'reason': 'capability_context_failed', 'error_type': type(exc).__name__},
            )
            return jsonify({
                'error': exc.message if isinstance(exc, (CatalogResolutionError, CapabilityResolutionError))
                else 'Available capabilities could not be loaded. Please retry.',
                'code': exc.code if isinstance(exc, CatalogResolutionError) else 'capability_context_unavailable',
            }), 409 if isinstance(exc, CatalogResolutionError) and exc.code == 'selected_agent_unavailable' else 503
        answer_model = None
        research_model = None
        try:
            _validate_turn_memory_context(record, user_id, conversation_id)
            memory_context = load_orchestration_memory(
                user_id, _authorize_context_conversation(conversation_id, user_id),
                build_elicitation_user_request(
                    record.get('resolved_message') or user_message, record.get('answered_questions'),
                ),
                settings=settings, seeds=seeds, expected_audience=record.get('memory_audience'),
            )
        except (OrchestrationMemoryError, ConversationContextError, AzureError) as exc:
            payload, status = _plan_edit_error(exc)
            return jsonify(payload), status

        def close_models():
            try:
                if research_model is not None:
                    research_model.close()
            finally:
                if answer_model is not None:
                    answer_model.close()

        try:
            answer_model = resolve_orchestration_model(
                settings, user_id=user_id, seeds=seeds, identity_context=identity,
            )
            research_model = (
                resolve_orchestration_model(
                    settings, user_id=user_id, seeds=seeds, planner=True, identity_context=identity,
                ) if has_planner_model_override(settings) else answer_model
            )
            bound_invoke_prompt = _build_invoke_prompt(
                settings, token_usage=run_token_usage, model=answer_model,
            )

            def invoke_prompt(prompt_text, stage='window_analysis', metadata=None):
                reply = bound_invoke_prompt(prompt_text, stage=stage, metadata=metadata)
                validate_memory_context(
                    _authorize_context_conversation(conversation_id, user_id), user_id,
                    memory_context['audience'], memory_context['scope'],
                )
                return reply
        except (ValueError, PermissionError, PlannerError, AzureError) as exc:
            close_models()
            log_event(
                '[ORCHESTRATION] The execution model could not be selected.',
                level=logging.WARNING, extra={'error_type': type(exc).__name__},
            )
            return jsonify({
                'error': 'The selected model is unavailable. Choose an enabled model you can access.',
            }), 403 if isinstance(exc, (PermissionError, OrchestrationModelError)) else 503

        action_model_context = {
            'model_id': answer_model.model_id,
            'endpoint_id': answer_model.endpoint_id,
            'provider': answer_model.provider,
            'model_deployment': answer_model.deployment,
            'user_id': user_id,
            'active_group_ids': seeds.get('active_group_ids') or [],
        }
        worker_started = False

        try:
            record = claim_plan_run(
                run_id, user_id, conversation_id, plan_id=data.get('plan_id'),
                expected_version=data.get('expected_version'), edits=data.get('edits'),
                conversation_context=snapshot,
            )
        except (PlanRevisionError, AzureError) as exc:
            close_models()
            payload, status = _plan_edit_error(exc)
            return jsonify(payload), status
        plan = record['plan']

        def generate():
            nonlocal worker_started
            initial_reasoning = merge_reasoning_adjustments(
                plan.get('reasoning_adjustments'),
                build_model_reasoning_metadata(answer_model).get('reasoning_adjustments'),
                build_model_reasoning_metadata(research_model, 'planner').get('reasoning_adjustments')
                if research_model is not answer_model else [],
            )
            if initial_reasoning:
                yield build_reasoning_adjustment_event(initial_reasoning)
            # Progress is streamed from a worker thread rather than collected and flushed at
            # the end. The executor is synchronous and calls `emit` from inside its own loop,
            # and a generator cannot yield from a callback -- so buffering was the obvious
            # shape and also the wrong one: every step event would arrive at once, after the
            # answer, which is exactly the "looks hung" experience the progress exists to
            # prevent. The queue is the seam that lets the executor push while the response
            # pulls.
            frames = queue.Queue()

            def emit(event):
                """Translate the executor's internal progress into stream frames."""
                if not isinstance(event, dict) or event.get('type') != 'step':
                    return
                phase = event.get('phase')
                step = {
                    'step_id': event.get('step_id'),
                    'capability_id': event.get('capability_id'),
                    'title': event.get('title'),
                }
                frames.put(build_step_event(
                    event.get('step_id'), phase, _text(event.get('summary')),
                    event.get('step_index'), event.get('capability_id'),
                ))
                if event.get('capability_id') == 'respond':
                    frames.put(build_synthesis_thought(
                        event.get('step_index') or 0,
                        status='completed' if phase != 'running' else 'running',
                    ))
                else:
                    frames.put(build_step_thought(
                        step, event.get('step_index') or 0,
                        event.get('completed') or 0, event.get('total') or 1,
                        status='running' if phase == 'running' else 'completed',
                        summary=_text(event.get('summary')) or None,
                    ))

            def persist(record_type, payload):
                try:
                    if record_type == 'step':
                        save_orchestration_step(run_id, payload)
                    elif record_type == 'run':
                        update_orchestration_run(
                            run_id, user_id,
                            {k: v for k, v in (payload or {}).items() if k != 'run_id'},
                            conversation_id=conversation_id,
                        )
                except Exception as exc:
                    log_event(f"[ORCHESTRATION] Progress not persisted: {exc}",
                              level=logging.WARNING)

            def reload_memory_context():
                nonlocal memory_context
                refreshed = load_orchestration_memory(
                    user_id, _authorize_context_conversation(conversation_id, user_id),
                    build_elicitation_user_request(
                        record.get('resolved_message') or user_message, record.get('answered_questions'),
                    ),
                    settings=get_settings(), seeds=seeds,
                    expected_audience=memory_context['audience'],
                )
                for notice in refreshed['notices']:
                    frames.put(build_planning_thought(notice))
                memory_context = refreshed
                return refreshed

            context = RunContext(
                run_id=run_id,
                plan_id=plan.get('plan_id'),
                conversation_id=conversation_id,
                user_id=user_id,
                turn_index=record.get('turn_index') or 0,
                invoke_prompt=invoke_prompt,
                planner_client=research_model.as_planner_client(),
                planner_deployment=research_model.deployment,
                user_message=user_message,
                user_message_id=record.get('user_message_id'),
                answered_questions=record.get('answered_questions') or [],
                elicitation_references=seeds.get('elicitation_references') or [],
                selected_document_ids=seeds.get('document_ids') or [],
                original_seeds=record.get('original_seeds') or {},
                resolved_message=_text(record.get('resolved_message')) or user_message,
                conversation_context=snapshot,
                context_message_ids=context_message_ids,
                allowed_user_urls=allowed_user_urls,
                revalidate_conversation_context=lambda: _conversation_context_for_run(
                    record, user_id, settings
                ),
                memory_context=memory_context,
                reload_memory_context=reload_memory_context,
                doc_scope=seeds.get('doc_scope') or 'all',
                tags=seeds.get('tags') or None,
                document_filter_mode=seeds.get('document_filter_mode') or None,
                active_group_ids=seeds.get('active_group_ids') or None,
                active_public_workspace_id=(seeds.get('active_public_workspace_ids') or [None])[0],
                active_public_workspace_ids=seeds.get('active_public_workspace_ids') or None,
                # Read on the request thread; see _request_identity.
                user_roles=identity.get('user_roles'),
                user_email=identity.get('user_email'),
                user_enable_agents=identity.get('user_enable_agents', True),
                active_group_id=(seeds.get('active_group_ids') or [None])[0],
                agent_catalog=agent_catalog,
                action_catalog=action_catalog,
                gpt_model=answer_model.deployment,
                model_context=action_model_context,
                agent_execution_identity=agent_execution_identity,
            )

            cancel_requested = _make_cancel_probe(run_id, user_id, conversation_id)
            outcome = {}

            def worker():
                try:
                    outcome['result'] = execute_plan(
                        plan, context,
                        settings=settings,
                        user_id=user_id,
                        emit=emit,
                        cancel_requested=cancel_requested,
                        persist=persist,
                    )
                except Exception as exc:
                    outcome['error'] = exc
                    log_event(
                        f"[ORCHESTRATION] Run {run_id} failed: {exc}",
                        level=logging.ERROR, exceptionTraceback=True,
                    )
                finally:
                    # The sentinel is what ends the drain loop. Sent from `finally` so a
                    # thrown worker cannot leave the response waiting on a queue nothing
                    # will ever write to again.
                    try:
                        close_models()
                    finally:
                        frames.put(None)

            thread = threading.Thread(
                target=worker, name=f'orchestration-run-{run_id}', daemon=True
            )
            thread.start()
            worker_started = True

            while True:
                try:
                    frame = frames.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    # A single analysis step can run for minutes without emitting. An SSE
                    # comment keeps proxies and load balancers from closing an idle-looking
                    # connection, and the client's frame parser ignores it.
                    yield ': keepalive\n\n'
                    continue
                if frame is None:
                    break
                yield frame

            thread.join(timeout=RUN_JOIN_TIMEOUT_SECONDS)

            failed_result = outcome.get('result') or {}
            reasoning_metadata = build_model_reasoning_metadata(answer_model)
            reasoning_metadata['reasoning_adjustments'] = merge_reasoning_adjustments(
                plan.get('reasoning_adjustments'), reasoning_metadata.get('reasoning_adjustments'),
                build_model_reasoning_metadata(research_model, 'planner').get('reasoning_adjustments')
                if research_model is not answer_model else [],
            )
            if (
                'error' in outcome or 'result' not in outcome
                or failed_result.get('status') == PLAN_STATUS_FAILED
            ):
                error_message = (
                    'Conversation context changed. Create a new plan.'
                    if isinstance(outcome.get('error'), ConversationContextError)
                    else 'The run could not be completed.'
                )
                try:
                    update_orchestration_run(run_id, user_id, {
                        'status': PLAN_STATUS_FAILED,
                        'error': error_message,
                        'completed_at': _now_iso(),
                        'reasoning_adjustments': reasoning_metadata['reasoning_adjustments'],
                        'token_usage': _combined_token_usage(
                            run_token_usage, failed_result.get('token_usage'),
                        ),
                    }, conversation_id=conversation_id)
                except AzureError as exc:
                    log_event(
                        '[ORCHESTRATION] Could not persist a failed run.',
                        level=logging.ERROR, extra={'error_type': type(exc).__name__},
                    )
                yield build_error_event(error_message, conversation_id)
                return

            result = outcome['result']
            combined_usage = _combined_token_usage(run_token_usage, result.get('token_usage'))
            answer = _text(result.get('message'))
            if (result.get('reauthorization') or {}).get('reason') == 'elicitation_context_unavailable':
                yield build_error_event(
                    'Accepted answer context is no longer available. Please update the answer or retry.',
                    conversation_id,
                )
                return
            if result.get('status') == PLAN_STATUS_CANCELLED:
                yield build_cancelled_event(conversation_id, run_id, answer)
                return

            summary = summarize_plan(plan)
            summary['status'] = result.get('status')
            summary['capabilities_used'] = list(result.get('capabilities_used') or [])

            # Everything the run gathered, split the way an assistant message carries it.
            document_citations, web_citations, tool_citations = _partition_citations(result.get('citations'))

            # The answer is an ordinary assistant message. Written before the terminal
            # frame so that a client which reloads the moment it arrives finds the answer
            # in the conversation rather than an empty turn where one just streamed.
            message_id = _save_message(
                conversation_id, 'assistant', answer,
                metadata={
                    'orchestration': {
                        'run_id': run_id,
                        'turn_id': record.get('turn_id'),
                        'plan_summary': summary,
                    },
                    'token_usage': combined_usage,
                    **reasoning_metadata,
                },
                extra={
                    **answer_model.metadata(),
                    **reasoning_metadata,
                    'hybrid_citations': document_citations,
                    'web_search_citations': web_citations,
                    'agent_citations': tool_citations,
                    'generated_artifacts': result.get('artifacts') or [],
                    'augmented': bool(document_citations or web_citations or tool_citations),
                },
            ) if answer else None

            if answer:
                _touch_conversation(conversation_id, user_id)
                # What the Documents drawer reads. The drawer works from the conversation's
                # used-document list rather than from the message's citations, so citing a
                # document is not enough on its own to make it appear there.
                _record_cited_documents(conversation_id, user_id, document_citations)
                yield build_content_event(answer)

            try:
                update_orchestration_run(run_id, user_id, {
                    'assistant_message_id': message_id,
                    'token_usage': combined_usage,
                    'reasoning_adjustments': reasoning_metadata['reasoning_adjustments'],
                }, conversation_id=conversation_id)
            except Exception:
                # The answer is already saved and streamed; failing to cross-reference it
                # is not worth failing the run over.
                pass

            answer_metadata = {**answer_model.metadata(), **reasoning_metadata}
            yield build_run_done_event(
                conversation_id,
                message_id=message_id,
                run_id=run_id,
                full_content=answer,
                citations=document_citations,
                web_citations=web_citations,
                agent_citations=tool_citations,
                artifacts=result.get('artifacts'),
                plan_summary=summary,
                status=result.get('status') or PLAN_STATUS_COMPLETED,
                **answer_metadata,
            )

        response = _sse(generate())
        response.call_on_close(lambda: close_models() if not worker_started else None)
        return response

    @bp.route("/api/v2/orchestration/cancel/<run_id>", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_cancel(run_id):
        """Ask a running plan to stop.

        Recorded on the run rather than signalled in memory, because the request almost
        never reaches the worker holding the stream.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        conversation_id = _text(data.get('conversation_id'))

        record = get_orchestration_run(run_id, user_id, conversation_id=conversation_id)
        if not record:
            return jsonify({'error': 'Run not found.'}), 404

        try:
            update_orchestration_run(run_id, user_id, {
                'cancellation_requested_at': _now_iso(),
                'cancellation_requested_by': user_id,
            }, conversation_id=conversation_id or record.get('conversation_id'))
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Could not record a cancellation: {exc}",
                      level=logging.ERROR)
            return jsonify({'error': 'The run could not be cancelled.'}), 500

        return jsonify({'success': True, 'run_id': run_id}), 200

    @bp.route("/api/v2/orchestration/runs", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_runs():
        """Every run in a conversation, oldest first, for the drawer's map view.

        Lean by default: a row is projected through ``_run_summary_row``, because the map
        draws one line per run and the stored record carries the whole plan. ``include_plan``
        adds the plan back for a caller that genuinely wants it, but still through a
        projection, so neither shape can leak a field the record happens to gain later.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_id = _text(request.args.get('conversation_id'))
        if not conversation_id:
            return jsonify({'error': 'A conversation id is required.'}), 400

        try:
            limit = max(1, min(int(request.args.get('limit') or 25), 100))
        except (TypeError, ValueError):
            limit = 25

        include_plan = _text(request.args.get('include_plan')).lower() in ('1', 'true', 'yes')

        try:
            runs = list_conversation_runs(conversation_id, user_id, limit=limit)
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Could not list runs: {exc}", level=logging.ERROR)
            return jsonify({'error': 'The run history could not be loaded.'}), 500

        # Both paths go through a projection, so no caller can reach a raw record. The
        # allowlist already excludes the conversation context, the request resolution and the
        # message fingerprint that this route used to strip by name, and it will keep
        # excluding whatever a future field adds to the record until it is named there.
        rows = _run_detail_row if include_plan else _run_summary_row
        return jsonify({'runs': [rows(run) for run in runs]}), 200

    @bp.route("/api/v2/orchestration/runs/<run_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_run_detail(run_id):
        """One stored run in full, so an earlier turn's plan can be reopened.

        This is what makes the map view's rows more than labels: the listing is deliberately
        too lean to render a plan, and the plan is fetched here for the one run the user
        actually opened. Ownership is enforced inside ``get_orchestration_run``, which
        compares ``user_id`` on both the point read and the cross-partition fallback, so a
        guessed run id belonging to somebody else is indistinguishable from a missing one.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_id = _text(request.args.get('conversation_id'))

        try:
            record = get_orchestration_run(
                run_id, user_id, conversation_id=conversation_id or None
            )
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Could not read run {run_id}: {exc}",
                      level=logging.ERROR)
            return jsonify({'error': 'The run could not be loaded.'}), 500

        if not record:
            return jsonify({'error': 'Run not found.'}), 404

        return jsonify({'run': _run_detail_row(record)}), 200

    @bp.route("/api/v2/orchestration/runs/<run_id>/steps", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def orchestration_run_steps(run_id):
        """One run's steps, for expanding a row in the map view."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_id = _text(request.args.get('conversation_id'))
        try:
            steps = list_run_steps(run_id, user_id=user_id, conversation_id=conversation_id)
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Could not list run steps: {exc}", level=logging.ERROR)
            return jsonify({'error': 'The run steps could not be loaded.'}), 500

        return jsonify({'run_id': run_id, 'steps': steps}), 200
