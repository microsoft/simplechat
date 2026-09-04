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

Request data is read out of the Flask request *before* any generator starts. A streamed
response outlives the request context, so touching ``request`` from inside the generator
raises rather than returning the value it would have had -- a failure that only appears
once streaming is actually exercised.

Version: 0.261.085
"""

import logging
import queue
import threading
import uuid
from datetime import datetime, timezone

from flask import Response, jsonify, request, session

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
    build_conversation_signals,
    build_planner_context,
    build_run_ledger,
    collect_answered_questions,
    resolve_agent_catalog,
    resolve_candidate_documents,
    resolve_seeds,
)
from functions_orchestration_events import (
    build_cancelled_event,
    build_content_event,
    build_conversation_metadata_event,
    build_elicitation_event,
    build_error_event,
    build_plan_event,
    build_planning_thought,
    build_run_done_event,
    build_step_event,
    build_step_thought,
    build_synthesis_thought,
    build_triage_thought,
)
from functions_orchestration_executor import RunContext, execute_plan
from functions_orchestration_planner import (
    build_trivial_plan,
    plan_request,
    resolve_planner_client,
    triage_request,
)
from functions_orchestration_runs import (
    create_orchestration_run,
    get_orchestration_run,
    list_conversation_runs,
    list_run_steps,
    save_orchestration_step,
    update_orchestration_run,
)
from functions_orchestration_schema import (
    APPROVAL_STATE_APPROVED,
    COMPLEXITY_TRIVIAL,
    ELICITATION_ACTION_ACCEPT,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_RUNNING,
    apply_plan_edits,
    normalize_plan,
    summarize_plan,
    validate_elicitation_response,
)
from functions_settings import get_settings, get_user_settings
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


def _sse(generator):
    return Response(generator, mimetype='text/event-stream', headers=dict(SSE_HEADERS))


def _orchestration_enabled(settings):
    return bool((settings or {}).get('enable_chat_orchestration'))


def _build_invoke_prompt(settings, token_usage=None):
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

    Shares the planner's client resolution, which already handles APIM, managed identity
    and key auth, but deliberately not its deployment: planning may be pointed at a small
    model, while the answer should come from the deployment the administrator chose for
    chat.
    """
    client, planner_deployment = resolve_planner_client(settings)

    deployment = None
    gpt_model = (settings or {}).get('gpt_model') or {}
    if gpt_model.get('selected'):
        deployment = (gpt_model['selected'][0] or {}).get('deploymentName')
    deployment = deployment or planner_deployment

    def invoke_prompt(prompt_text, stage='window_analysis', metadata=None):
        messages = (
            prompt_text
            if isinstance(prompt_text, list)
            else [{'role': 'user', 'content': str(prompt_text or '')}]
        )
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=ANSWER_TEMPERATURE,
            max_tokens=ANSWER_MAX_TOKENS,
        )

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
            return ''
        return response.choices[0].message.content or ''

    return invoke_prompt


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
        limit = int(settings.get('chat_orchestration_ledger_max_runs') or 10)
    except (TypeError, ValueError):
        limit = 10
    try:
        runs = list_conversation_runs(conversation_id, user_id, limit=max(limit, 1))
    except Exception as exc:
        log_event(
            f"[ORCHESTRATION] Could not read the run ledger; planning without it: {exc}",
            level=logging.WARNING,
        )
        return build_run_ledger([], settings=settings)
    return build_run_ledger(
        runs, settings=settings, answered_questions=collect_answered_questions(runs)
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
    except Exception:
        pass

    try:
        cosmos_conversations_container.upsert_item({
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
    """Split a run's citations into the document and web buckets chat already uses.

    An assistant message carries these in two separate fields, and the difference is not
    cosmetic: ``hybrid_citations`` is what the conversation's used-document tracking reads
    to work out which documents an answer actually drew on, and a web citation has no
    document to track. Folding both into one field would either lose the web sources or
    put entries with no ``document_id`` in front of ``build_used_documents``, which skips
    them silently -- a bug that looks like nothing happening.
    """
    document_citations = []
    web_citations = []
    for citation in citations or ():
        if not isinstance(citation, dict):
            continue
        if _text(citation.get('document_id')):
            document_citations.append(citation)
        elif _text(citation.get('url')) or citation.get('source_type') == 'web':
            web_citations.append(citation)
        else:
            # Neither a document nor a page: an agent tool call, for instance. Carried as
            # a web-style citation so it is still visible on the message rather than
            # discarded, but kept out of document tracking where it has no place.
            web_citations.append(citation)
    return document_citations, web_citations


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


def _save_message(conversation_id, role, content, metadata=None, extra=None):
    """Write one message, returning its id.

    ``extra`` carries the citation fields an assistant message needs. They are top-level
    rather than nested in metadata because that is where every existing reader looks for
    them -- the renderer, the citation lookup and the used-document tracking alike.
    """
    message_id = f"{role}_{uuid.uuid4().hex}"
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
            f"[ORCHESTRATION] Could not save a {role} message: {exc}",
            level=logging.ERROR, exceptionTraceback=True,
        )
        return None
    return message_id


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
        message = _text(data.get('message'))
        if not message:
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
        recent_messages = data.get('recent_messages')
        replan_hint = _text(data.get('replan_hint'), 600)

        # An answered question is folded into the message the planner sees, so the next plan
        # is built with the answer in hand rather than being told a question was asked.
        answered = None
        answered_record = []
        elicitation_response = data.get('elicitation_response')
        prior_elicitation = data.get('elicitation')
        if isinstance(elicitation_response, dict) and isinstance(prior_elicitation, dict):
            validated, errors = validate_elicitation_response(
                prior_elicitation, elicitation_response
            )
            if errors:
                return jsonify({'error': 'The answers were not valid.', 'details': errors}), 400
            if validated['action'] == ELICITATION_ACTION_ACCEPT:
                answered = validated['content']
                answered_record = [{
                    'elicitation_id': prior_elicitation.get('elicitation_id'),
                    'question': _text(prior_elicitation.get('message'), 240),
                    'answer': answered,
                }]
            # Declining is a decision rather than a failure: plan without the answer instead
            # of asking again. Either way this is a new attempt at the same turn.
            revision += 1

        def generate():
            try:
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

                candidates, _probed = resolve_candidate_documents(
                    message, user_id, seeds=seeds,
                    conversation_id=resolved_conversation_id, settings=settings,
                )
                ledger = _load_ledger(resolved_conversation_id, user_id, settings)
                signals = build_conversation_signals(recent_messages, message)

                context = build_planner_context(
                    message, candidates=candidates, seeds=seeds, ledger=ledger, signals=signals,
                )
                if answered:
                    context['answered_now'] = answered

                complexity = triage_request(message, context)
                yield build_triage_thought(complexity)

                authorized = _authorized_document_ids(candidates, seeds)
                labels = _document_labels(candidates)

                if complexity == COMPLEXITY_TRIVIAL and not replan_hint:
                    # No planning round trip. The point of triage is to make a
                    # conversational reply feel instant rather than sent away to think.
                    plan = normalize_plan(
                        build_trivial_plan(message, context),
                        resolved_conversation_id, user_id, settings=settings,
                        approval_mode=approval_mode,
                        authorized_document_ids=authorized,
                        turn_id=turn_id, seeds=seeds, document_labels=labels,
                    )
                    kind = 'plan'
                else:
                    yield build_planning_thought('Deciding what this question needs.')
                    # The agent catalog is resolved here rather than above so a
                    # conversational message never pays for it: it is a multi-query Cosmos
                    # traversal with no cache, and a trivial reply has no plan for an agent
                    # to appear in. Once per plan, never per step.
                    #
                    # The context is rebuilt rather than having 'agents' assigned into it,
                    # because build_planner_context is the single place the catalog is
                    # projected down to its naming fields. Writing the key directly would
                    # put an agent's full instructions in front of the planner.
                    context = build_planner_context(
                        message, candidates=candidates, seeds=seeds, ledger=ledger,
                        signals=signals,
                        agents=resolve_agent_catalog(
                            user_id, seeds=seeds, settings=settings,
                            user_groups=seeds.get('active_group_ids') or None,
                        ),
                    )
                    if answered:
                        context['answered_now'] = answered

                    kind, plan = plan_request(
                        message, context, resolved_conversation_id, user_id,
                        settings=settings,
                        approval_mode=approval_mode,
                        authorized_document_ids=authorized,
                        replan_hint=replan_hint or None,
                        revision=revision,
                        turn_id=turn_id, seeds=seeds, document_labels=labels,
                    )

                if kind == 'elicitation':
                    # `plan` holds an elicitation here. Nothing is persisted: a question is
                    # not a run, and creating a record for one would put a run in the map
                    # view that never did anything.
                    plan['turn_id'] = turn_id
                    plan['conversation_id'] = resolved_conversation_id
                    yield build_elicitation_event(plan)
                    return

                # The question is recorded once a plan exists for it, so a conversation
                # never shows a user message whose work was never planned.
                user_message_id = _save_message(resolved_conversation_id, 'user', message)

                plan['revision'] = revision
                try:
                    create_orchestration_run(
                        plan, user_id, conversation_id=resolved_conversation_id,
                    )
                    # Written straight after creation rather than through the create call,
                    # because the run endpoint is a separate request that has none of this:
                    # it needs the question that was asked and the selections that
                    # constrained the plan in order to execute it faithfully.
                    update_orchestration_run(run_id=plan['run_id'], user_id=user_id, updates={
                        'user_message': message,
                        'user_message_id': user_message_id,
                        'turn_id': turn_id,
                        'seeds': seeds,
                        'answered_questions': answered_record,
                    }, conversation_id=resolved_conversation_id)
                except Exception as exc:
                    # A plan that cannot be stored cannot be run, because the run endpoint
                    # loads it by id. Better to say so now than to show a plan whose
                    # Approve button would fail.
                    log_event(
                        f"[ORCHESTRATION] Could not persist a plan: {exc}",
                        level=logging.ERROR, exceptionTraceback=True,
                    )
                    yield build_error_event('The plan could not be saved.',
                                            resolved_conversation_id)
                    return

                yield build_planning_thought('Plan ready.', status='completed')
                yield build_plan_event(plan)

            except Exception as exc:
                log_event(
                    f"[ORCHESTRATION] Planning failed: {exc}",
                    level=logging.ERROR, exceptionTraceback=True,
                )
                yield build_error_event('The request could not be planned.', conversation_id)

        return _sse(generate())

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
            return jsonify({'error': 'This plan has already been run.'}), 409

        try:
            plan = apply_plan_edits(plan, data.get('edits'))
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Rejected plan edits: {exc}", level=logging.WARNING)
            return jsonify({'error': 'The plan edits were not valid.'}), 400

        conversation_id = conversation_id or _text(record.get('conversation_id'))

        # One accumulator for the whole run, filled by every model call the closure makes.
        run_token_usage = {}
        try:
            invoke_prompt = _build_invoke_prompt(settings, token_usage=run_token_usage)
        except Exception as exc:
            log_event(f"[ORCHESTRATION] No usable chat model: {exc}", level=logging.ERROR)
            return jsonify({'error': 'No chat model is configured.'}), 503

        seeds = record.get('seeds') if isinstance(record.get('seeds'), dict) else {}
        user_message = _text(record.get('user_message')) or _text(
            (plan.get('intent') or {}).get('summary')
        )

        # Captured out here, on the request thread, and closed over by the generator. A
        # streamed response's generator body runs after the view has returned, so reading
        # the session from inside it would be reading a context that is already gone.
        identity = _request_identity(user_id, seeded_agent=seeds.get('agent'))

        # Resolved again rather than read back off the plan. Planning and running are
        # separate requests, and an agent the user could reach when the plan was made is not
        # necessarily one they can reach now -- the same reason document authorization is
        # rechecked before the answer is composed. Still once per run, never per step.
        agent_catalog = resolve_agent_catalog(
            user_id, seeds=seeds, settings=settings,
            user_groups=seeds.get('active_group_ids') or None,
        )

        def generate():
            approved_at = _now_iso()
            try:
                update_orchestration_run(run_id, user_id, {
                    'status': PLAN_STATUS_RUNNING,
                    'started_at': approved_at,
                    'plan': plan,
                    'plan_summary': summarize_plan(plan),
                    'approval': {**(plan.get('approval') or {}),
                                 'state': APPROVAL_STATE_APPROVED,
                                 'approved_at': approved_at,
                                 'approved_by': user_id},
                }, conversation_id=conversation_id)
            except Exception as exc:
                log_event(f"[ORCHESTRATION] Could not mark a run started: {exc}",
                          level=logging.ERROR)

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

            context = RunContext(
                run_id=run_id,
                plan_id=plan.get('plan_id'),
                conversation_id=conversation_id,
                user_id=user_id,
                turn_index=record.get('turn_index') or 0,
                invoke_prompt=invoke_prompt,
                user_message=user_message,
                doc_scope=seeds.get('doc_scope') or 'all',
                active_group_ids=seeds.get('active_group_ids') or None,
                active_public_workspace_id=(
                    (seeds.get('active_public_workspace_ids') or [None])[0]
                ),
                # Read on the request thread; see _request_identity.
                user_roles=identity.get('user_roles'),
                user_email=identity.get('user_email'),
                user_enable_agents=identity.get('user_enable_agents', True),
                active_group_id=(seeds.get('active_group_ids') or [None])[0],
                agent_catalog=agent_catalog,
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
                    frames.put(None)

            thread = threading.Thread(
                target=worker, name=f'orchestration-run-{run_id}', daemon=True
            )
            thread.start()

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

            if 'error' in outcome or 'result' not in outcome:
                yield build_error_event('The run could not be completed.', conversation_id)
                return

            result = outcome['result']
            answer = _text(result.get('message'))
            if result.get('status') == PLAN_STATUS_CANCELLED:
                yield build_cancelled_event(conversation_id, run_id, answer)
                return

            summary = summarize_plan(plan)
            summary['status'] = result.get('status')

            # Everything the run gathered, split the way an assistant message carries it.
            document_citations, web_citations = _partition_citations(result.get('citations'))

            # The answer is an ordinary assistant message. Written before the terminal
            # frame so that a client which reloads the moment it arrives finds the answer
            # in the conversation rather than an empty turn where one just streamed.
            message_id = _save_message(
                conversation_id, 'assistant', answer,
                metadata={
                    'orchestration': {
                        'run_id': run_id,
                        'plan_summary': summary,
                    },
                    'token_usage': run_token_usage or result.get('token_usage') or {},
                },
                extra={
                    'hybrid_citations': document_citations,
                    'web_search_citations': web_citations,
                    'augmented': bool(document_citations or web_citations),
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
                    'token_usage': run_token_usage,
                }, conversation_id=conversation_id)
            except Exception:
                # The answer is already saved and streamed; failing to cross-reference it
                # is not worth failing the run over.
                pass

            yield build_run_done_event(
                conversation_id,
                message_id=message_id,
                run_id=run_id,
                full_content=answer,
                citations=document_citations,
                web_citations=web_citations,
                artifacts=result.get('artifacts'),
                plan_summary=summary,
                status=result.get('status') or PLAN_STATUS_COMPLETED,
            )

        return _sse(generate())

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
        """Every run in a conversation, oldest first, for the drawer's map view."""
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

        try:
            runs = list_conversation_runs(conversation_id, user_id, limit=limit)
        except Exception as exc:
            log_event(f"[ORCHESTRATION] Could not list runs: {exc}", level=logging.ERROR)
            return jsonify({'error': 'The run history could not be loaded.'}), 500

        return jsonify({'runs': runs}), 200

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
