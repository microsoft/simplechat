# functions_orchestration_events.py

"""
The stream events an orchestration run emits.

Deliberately almost entirely *not* new. Progress rides the existing ``thought`` event,
byte-for-byte the shape ``serialize_thought_event`` produces in ``route_backend_chats.py``,
because that shape already has two consumers worth keeping: ``ThoughtTracker`` persists it
to Cosmos as it arrives, and ``activityLanes.ts`` in the V2 client renders it as staged
progress. Inventing a second progress event would mean a live run and a reloaded one drew
differently, and that divergence is exactly the bug the shared shape prevents.

``activityLanes.ts`` declares its lanes in a table and says in its own header that adding
one should be a table entry rather than a second progress card. This module supplies the
payloads that table entry matches on: every orchestration activity carries
``lane_key = "orchestration"``.

Only three genuinely new event types exist, and each is new because nothing existing means
the same thing:

``orchestration_plan``
    Terminal frame of the plan endpoint. There was no "here is what I intend to do" event
    before, because nothing previously intended anything.

``orchestration_elicitation``
    Terminal frame of the plan endpoint when a question has to be asked instead.

``orchestration_step``
    A named step changed state. Distinct from the ``thought`` it accompanies because the
    plan card ticks specific steps by id, and reverse-engineering that from prose would be
    guesswork.

Version: 0.261.085
"""

import json

# Lane key matched by the client's activity lane table.
ORCHESTRATION_LANE_KEY = 'orchestration'

# `step_type` values on the shared thought event.
STEP_TYPE_TRIAGE = 'orchestration_triage'
STEP_TYPE_PLANNING = 'orchestration_planning'
STEP_TYPE_STEP = 'orchestration_step'
STEP_TYPE_SYNTHESIS = 'orchestration_synthesis'

ORCHESTRATION_STEP_TYPES = (
    STEP_TYPE_TRIAGE,
    STEP_TYPE_PLANNING,
    STEP_TYPE_STEP,
    STEP_TYPE_SYNTHESIS,
)

# Event `type` values unique to orchestration.
EVENT_TYPE_PLAN = 'orchestration_plan'
EVENT_TYPE_ELICITATION = 'orchestration_elicitation'
EVENT_TYPE_STEP = 'orchestration_step'

# Activity `kind` values, which is how the lane tells one sort of work from another.
ACTIVITY_KIND_PLANNING = 'orchestration_planning'
ACTIVITY_KIND_STEP = 'orchestration_step_execution'
ACTIVITY_KIND_SYNTHESIS = 'orchestration_synthesis'


def serialize_sse(payload):
    """Frame one payload as an SSE ``data:`` event.

    The double newline is the frame delimiter the client's reader splits on, and
    ``sse.ts`` carries a repair for servers that emit it escaped. Producing it correctly
    here means that repair never has to fire for orchestration.
    """
    return f"data: {json.dumps(payload, default=str)}\n\n"


def build_activity(
    kind,
    title,
    status='running',
    step_id=None,
    capability_id=None,
    completed=None,
    total=None,
):
    """The ``activity`` object carried on a thought event.

    ``completed`` and ``total`` are what turn a list of sentences into "3 of 7", which for
    a run measured in minutes is the difference between looking like it is working and
    looking like it has hung.
    """
    activity = {
        'lane_key': ORCHESTRATION_LANE_KEY,
        'kind': kind,
        'title': title,
        'status': status,
    }
    if step_id:
        activity['step_id'] = step_id
    if capability_id:
        activity['capability_id'] = capability_id
        # Doubles as the activity's identity, so a lane can tell a re-emitted step from a
        # second one without the client having to track ordering itself.
        activity['activity_key'] = f"{step_id or capability_id}"
    if completed is not None:
        activity['completed'] = completed
    if total is not None:
        activity['total'] = total
    return activity


def build_thought_payload(
    step_type,
    content,
    step_index,
    message_id=None,
    detail=None,
    activity=None,
    progress=None,
):
    """A thought event payload, matching ``serialize_thought_event`` exactly.

    Optional keys are omitted rather than sent as null, because the persisted-thought
    reader treats a present key as meaningful and a null ``activity`` would be recorded as
    a step that reported staged work and then said nothing about it.
    """
    payload = {
        'type': 'thought',
        'message_id': message_id,
        'step_index': step_index,
        'step_type': step_type,
        'content': content,
    }
    if detail is not None:
        payload['detail'] = detail
    if isinstance(activity, dict) and activity:
        payload['activity'] = activity
    if isinstance(progress, dict) and progress:
        payload['progress'] = progress
    return payload


def build_thought_event(*args, **kwargs):
    """Serialized form of :func:`build_thought_payload`."""
    return serialize_sse(build_thought_payload(*args, **kwargs))


def build_triage_thought(complexity, step_index=0, message_id=None):
    """Reported even when triage decides there is nothing to plan.

    A user who sees no planning activity at all cannot tell a fast decision from a broken
    feature, so the decision itself is the event.
    """
    wording = {
        'trivial': 'Answering directly; this needs no research.',
        'simple': 'Working out what this needs.',
        'complex': 'Working out what this needs.',
    }.get(complexity, 'Working out what this needs.')

    return build_thought_event(
        STEP_TYPE_TRIAGE,
        wording,
        step_index,
        message_id=message_id,
        detail=f"complexity: {complexity}",
        activity=build_activity(ACTIVITY_KIND_PLANNING, 'Understanding the request',
                                status='completed'),
    )


def build_planning_thought(content, step_index=1, message_id=None, status='running'):
    return build_thought_event(
        STEP_TYPE_PLANNING,
        content,
        step_index,
        message_id=message_id,
        activity=build_activity(ACTIVITY_KIND_PLANNING, 'Building a plan', status=status),
    )


def build_step_thought(
    step,
    step_index,
    completed,
    total,
    message_id=None,
    status='running',
    summary=None,
):
    """Progress for one plan step, carrying its position in the run."""
    step = step or {}
    title = step.get('title') or step.get('capability_id') or 'Step'
    return build_thought_event(
        STEP_TYPE_STEP,
        summary or title,
        step_index,
        message_id=message_id,
        detail=step.get('rationale') or None,
        activity=build_activity(
            ACTIVITY_KIND_STEP,
            title,
            status=status,
            step_id=step.get('step_id'),
            capability_id=step.get('capability_id'),
            completed=completed,
            total=total,
        ),
    )


def build_synthesis_thought(step_index, message_id=None, status='running'):
    return build_thought_event(
        STEP_TYPE_SYNTHESIS,
        'Writing the answer.',
        step_index,
        message_id=message_id,
        activity=build_activity(ACTIVITY_KIND_SYNTHESIS, 'Writing the answer', status=status),
    )


def build_conversation_metadata_event(conversation_id, title=''):
    """Tell the client which conversation this turn belongs to.

    Named and shaped exactly like the chat stream's own event, because the V2 client
    already adopts a new conversation's id by listening for it -- a differently named
    event would need a second code path in the client for no reason.
    """
    return serialize_sse({
        'type': 'conversation_metadata',
        'conversation_id': conversation_id,
        'conversation_title': title or 'New Conversation',
        'title': title or 'New Conversation',
    })


def build_plan_event(plan):
    """Terminal frame of the plan endpoint: here is what I intend to do."""
    return serialize_sse({'type': EVENT_TYPE_PLAN, 'plan': plan, 'done': True})


def build_elicitation_event(elicitation):
    """Terminal frame of the plan endpoint when a question has to be asked first."""
    return serialize_sse({
        'type': EVENT_TYPE_ELICITATION,
        'elicitation': elicitation,
        'done': True,
    })


def build_step_event(step_id, status, summary='', step_index=None, capability_id=None):
    """A named step changed state, so the plan card can tick exactly that row."""
    payload = {
        'type': EVENT_TYPE_STEP,
        'step_id': step_id,
        'status': status,
        'summary': summary or '',
    }
    if step_index is not None:
        payload['step_index'] = step_index
    if capability_id:
        payload['capability_id'] = capability_id
    return serialize_sse(payload)


def build_content_event(content):
    """A content delta, matching what the chat stream already sends."""
    return serialize_sse({'content': content})


def build_error_event(message, conversation_id=None):
    payload = {'error': str(message or 'The request could not be completed.')}
    if conversation_id:
        payload['conversation_id'] = conversation_id
    return serialize_sse(payload)


def build_run_done_event(
    conversation_id,
    message_id=None,
    run_id=None,
    full_content='',
    citations=None,
    artifacts=None,
    plan_summary=None,
    status='completed',
):
    """Terminal frame of the run endpoint.

    Shaped like the chat stream's own terminal payload so the V2 message renderer needs no
    special case: an orchestrated answer is still just an assistant message, and the parts
    that are new to orchestration are additive keys rather than a different envelope.
    """
    return serialize_sse({
        'done': True,
        'type': 'orchestration_done',
        'conversation_id': conversation_id,
        'message_id': message_id,
        'run_id': run_id,
        'full_content': full_content,
        'hybrid_citations': list(citations or ()),
        'generated_artifacts': list(artifacts or ()),
        'orchestration': plan_summary or {},
        'status': status,
    })


def build_cancelled_event(conversation_id, run_id=None, partial_content=''):
    return serialize_sse({
        'done': True,
        'type': 'cancelled',
        'cancelled': True,
        'conversation_id': conversation_id,
        'run_id': run_id,
        'partial_content': partial_content,
    })
