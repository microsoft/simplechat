# functions_workflow_chat_delivery_worker.py
"""Deliver a chat-started workflow run's outcome back into the chat that asked (6b-1).

A chat-orchestration plan that starts one of the user's saved workflows ends right away, and the
run may finish hours later. This worker posts the run's outcome into the requesting chat once per
delivery generation:

* a reply the model composes from a bounded, fenced excerpt of the run's result, under a dated
  label;
* a fixed note when the run failed or was cancelled, or its result can't be shown here;
* nothing, and one bell notice instead, when the chat can't take it any more.

The record that drives delivery is the run document's ``chat_delivery`` field. Only ETag-guarded
writes that fence on the claim's lease advance it. The message ID, the unread mark and every
notification are idempotent, so a crash at any point resumes without a second post or notice.

This module imports only the standard library, azure-core's match conditions, the unread outcome
constants and the pure delivery contract, so importing it never initializes application storage.
``default_workflow_chat_delivery_services`` binds the production dependencies on first use.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Optional

from azure.core import MatchConditions

from functions_workflow_chat_delivery import (
    CHAT_DELIVERY_KEY,
    COMPOSE_MAX_TOKENS,
    COMPOSE_TEMPERATURE,
    DEFER_MAX_SECONDS,
    DEFER_RETRY_SECONDS,
    DELIVERY_METADATA_KEY,
    EXCERPT_BUDGET_BYTES,
    EXPIRED_NOTICE_MESSAGE,
    FALLBACK_QUESTION,
    KIND_ANALYSIS,
    KIND_CANCELLED,
    KIND_CONTENT_BLOCKED,
    KIND_EXPIRED,
    KIND_FAILED,
    KIND_RESULT,
    KIND_SKIPPED,
    KIND_STATUS,
    LEASE_SECONDS,
    MAX_ATTEMPTS,
    NOTICE_CHAT_RESPONSE,
    NOTICE_EXPIRED,
    NOTICE_NONE,
    NOTICE_UNDELIVERABLE,
    NOTIFICATION_TYPE,
    PHASE_CLAIMED,
    PHASE_MESSAGE_CREATED,
    PHASE_NOTIFIED,
    PHASE_PUBLISHING,
    PHASE_UNREAD_MARKED,
    REASON_ACCESS_LOST,
    REASON_CHAT_UNAVAILABLE,
    REASON_CONTENT_BLOCKED,
    REASON_DELIVERY_FAILED,
    REASON_EXPIRED_BEFORE_DELIVERY,
    REASON_RESULT_UNAVAILABLE,
    REASON_RESULTS_OFF,
    REASON_WORKFLOW_DELETED,
    RECENT_USER_MESSAGE_SECONDS,
    REPLY_MAX_CHARS,
    RESULT_CONTEXT_KINDS,
    RUN_DOCUMENT_TERMINAL_STATUSES,
    SILENT_REASONS,
    STATUS_DELIVERED,
    STATUS_DELIVERING,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_UNDELIVERABLE,
    STREAM_META_FRESH_SECONDS,
    SWEEP_LOCK_NAME,
    SWEEP_LOCK_SECONDS,
    SWEEP_MAX_RUNS,
    SWEEP_MAX_SECONDS,
    SWEEP_TOP,
    SWEEP_TS_GRACE_SECONDS,
    TRIMMED_FALLBACK_CHARS,
    TRIMMED_FALLBACK_INTRO,
    UNDELIVERABLE_NOTICE_MESSAGE,
    assemble_delivery_content,
    build_delivery_metadata,
    control_summary,
    delivered_notice_preview,
    delivery_label,
    delivery_log,
    delivery_note_text,
    delivery_notification_key,
    delivery_thread_id,
    expired_notification_key,
    format_delivery_timestamp,
    next_backoff_seconds,
    notice_metadata,
    notice_title,
    parse_delivery_timestamp,
    phase_at_least,
    reconcile_chat_delivery,
    token_usage_idempotency_key,
    undeliverable_notification_key,
    utc_now,
    workflow_delivery_message_id,
    workflow_run_notice_link,
)
from functions_workflow_chat_delivery import _close_for_runtime
from functions_conversation_unread import (
    UNREAD_ALREADY_MARKED,
    UNREAD_MARKED,
    UNREAD_NOT_FOUND,
    UNREAD_READ_SINCE,
    UNREAD_UNAVAILABLE,
)


QUESTION_MAX_CHARS = 4000
RECORD_WRITE_RETRIES = 5
HINT_BATCH = 32
NEWEST_MESSAGE_QUERY = (
    'SELECT TOP 1 c.id, c.role, c.timestamp, c.metadata.thread_info AS thread_info '
    'FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp DESC'
)

OUTCOME_DELIVERED = 'delivered'
OUTCOME_UNDELIVERABLE = 'undeliverable'
OUTCOME_CLOSED_SILENTLY = 'closed_silently'
OUTCOME_EXPIRED = 'expired'
OUTCOME_DEFERRED = 'deferred'
OUTCOME_RETRY_SCHEDULED = 'retry_scheduled'
OUTCOME_PENDING = 'pending'
OUTCOME_NOT_DUE = 'not_due'
OUTCOME_BUSY = 'busy'
OUTCOME_LOST_LEASE = 'lost_lease'
OUTCOME_NOT_APPLICABLE = 'not_applicable'
OUTCOME_UNAVAILABLE = 'unavailable'


class _Transient(Exception):
    """A retryable failure. It consumes the claim's attempt and backs off."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _LostLease(Exception):
    """Another worker owns the record now, or the run document is gone. Stop without writing."""


class _Defer(Exception):
    """The chat may be mid-reply. ``counted`` is True when the deferral consumes the attempt."""

    def __init__(self, counted):
        super().__init__('deferred')
        self.counted = counted


@dataclass
class WorkflowChatDeliveryServices:
    """Every dependency the worker touches, so tests can drive it without Azure."""

    runs: Any
    workflows: Any
    conversations: Any
    messages: Any
    get_settings: Callable
    runtime_store_factory: Callable
    runtime_conflict_error: type
    runtime_unavailable_error: type
    read_workflow_result: Callable
    result_unavailable_error: type
    workflow_result_context: Callable
    format_run_time: Callable
    format_disclosure: Callable
    build_result_messages: Callable
    new_fence_nonce: Callable
    excerpt_budget_steps: tuple
    calculate_budget: Callable
    resolve_model: Callable
    model_error: type
    capture_identity: Callable
    extract_text: Callable
    check_content: Callable
    attach_chat_check: Callable
    record_incident: Callable
    is_message_retracted: Callable
    create_chat_response_notification: Callable
    create_notification: Callable
    log_token_usage: Callable
    bump_cache_version: Callable
    mark_unread_guarded: Callable
    is_conversation_private: Callable
    is_user_workflows_enabled: Callable
    is_chat_workflow_results_enabled: Callable
    stream_activity_probe: Callable
    acquire_lock: Callable
    release_lock: Callable
    drain_hints: Callable
    signal_delivery: Callable
    clock: Callable
    compose_output_tokens: Callable = None
    monotonic: Callable = time.monotonic


def _no_lock(_task_name, _lease_seconds):
    return None


def _ignore_release(_lock_document):
    return None


def _personal_runtime_store(user_id, workflow_id, run_id):
    # A personal store's identity is the workflow ID and owner only, so a tombstoned control stays
    # readable after the workflow document itself is gone.
    from functions_workflow_runtime_store import workflow_runtime_store

    return workflow_runtime_store({'id': workflow_id, 'user_id': user_id}, run_id)


def _default_stream_activity_probe(user_id, conversation_id, now):
    """Whether a reply may be streaming into this chat right now (D7 signals 1 and 2)."""
    import sys

    chats = sys.modules.get('route_backend_chats')
    registry = getattr(chats, 'CHAT_STREAM_REGISTRY', None) if chats is not None else None
    if registry is not None:
        try:
            if registry.get_session(user_id, conversation_id, active_only=True):
                return True
        except Exception as exc:
            delivery_log('Stream registry probe failed.', level=logging.WARNING, error_type=type(exc).__name__)
    try:
        import app_settings_cache

        getter = getattr(app_settings_cache, 'get_stream_session_meta', None)
        meta = getter(f'{user_id}:{conversation_id}') if callable(getter) else None
    except Exception as exc:
        delivery_log('Stream metadata probe failed.', level=logging.WARNING, error_type=type(exc).__name__)
        meta = None
    if isinstance(meta, dict) and meta.get('active'):
        updated = parse_delivery_timestamp(meta.get('updated_at'))
        if updated is not None and (now - updated).total_seconds() < STREAM_META_FRESH_SECONDS:
            return True
    return False


def default_workflow_chat_delivery_services(*, acquire_lock=None, release_lock=None):
    """Bind the production dependencies.

    Every import is deferred to this call because each one initializes application storage. The
    sweep's distributed lock helpers come from background_tasks, which passes them in. Without them
    the sweep never runs; hint-driven deliveries still do, because a claim is an ETag write.
    """
    import config
    import functions_orchestration_models as orchestration_models
    from agent_execution_context import capture_execution_identity
    from functions_activity_logging import log_token_usage
    from functions_chat_content_checks import attach_chat_check, check_chat_content
    from functions_chat_content_review import record_chat_content_incident, reply_is_retracted
    from functions_conversation_cache import bump_conversation_cache_version
    from functions_conversation_unread import mark_conversation_unread_guarded
    from functions_notifications import create_chat_response_notification, create_notification
    from functions_orchestration_memory import conversation_is_private
    from functions_settings import (
        get_settings,
        is_chat_workflow_results_enabled_for_user,
        is_user_workflows_enabled_for_user,
    )
    from functions_workflow_chat_delivery import (
        drain_workflow_chat_delivery_hints,
        signal_workflow_chat_delivery,
    )
    from functions_workflow_context import calculate_workflow_context_budget
    from functions_workflow_result_followup import (
        EXCERPT_BUDGET_STEPS,
        build_workflow_result_messages,
        new_fence_nonce,
    )
    from functions_workflow_result_reader import (
        WorkflowResultUnavailable,
        format_workflow_result_disclosure,
        format_workflow_run_time,
        read_workflow_result,
        workflow_result_context,
    )
    from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict
    from model_endpoint_clients import ModelEndpointBehavior, extract_chat_completion_response_text

    def compose_output_tokens(model):
        # Mirrors OrchestrationModel.create_completion: reasoning tokens share the completion budget.
        behavior = ModelEndpointBehavior(model.provider, getattr(model, 'behavior_name', None) or model.deployment)
        if behavior.is_openai_reasoning_model:
            return max(COMPOSE_MAX_TOKENS, orchestration_models.REASONING_COMPLETION_BUDGET)
        return COMPOSE_MAX_TOKENS

    return WorkflowChatDeliveryServices(
        runs=config.cosmos_personal_workflow_runs_container,
        workflows=config.cosmos_personal_workflows_container,
        conversations=config.cosmos_conversations_container,
        messages=config.cosmos_messages_container,
        get_settings=get_settings,
        runtime_store_factory=_personal_runtime_store,
        runtime_conflict_error=WorkflowRuntimeConflict,
        runtime_unavailable_error=RuntimeUnavailable,
        read_workflow_result=read_workflow_result,
        result_unavailable_error=WorkflowResultUnavailable,
        workflow_result_context=workflow_result_context,
        format_run_time=format_workflow_run_time,
        format_disclosure=format_workflow_result_disclosure,
        build_result_messages=build_workflow_result_messages,
        new_fence_nonce=new_fence_nonce,
        excerpt_budget_steps=tuple(EXCERPT_BUDGET_STEPS),
        calculate_budget=calculate_workflow_context_budget,
        resolve_model=orchestration_models.resolve_orchestration_model,
        model_error=orchestration_models.OrchestrationModelError,
        capture_identity=capture_execution_identity,
        extract_text=extract_chat_completion_response_text,
        check_content=check_chat_content,
        attach_chat_check=attach_chat_check,
        record_incident=record_chat_content_incident,
        is_message_retracted=reply_is_retracted,
        create_chat_response_notification=create_chat_response_notification,
        create_notification=create_notification,
        log_token_usage=log_token_usage,
        bump_cache_version=bump_conversation_cache_version,
        mark_unread_guarded=mark_conversation_unread_guarded,
        is_conversation_private=conversation_is_private,
        is_user_workflows_enabled=is_user_workflows_enabled_for_user,
        is_chat_workflow_results_enabled=is_chat_workflow_results_enabled_for_user,
        stream_activity_probe=_default_stream_activity_probe,
        acquire_lock=acquire_lock or _no_lock,
        release_lock=release_lock or _ignore_release,
        drain_hints=drain_workflow_chat_delivery_hints,
        signal_delivery=signal_workflow_chat_delivery,
        clock=utc_now,
        compose_output_tokens=compose_output_tokens,
    )


def _status_code(exc):
    code = getattr(exc, 'status_code', None)
    return code if type(code) is int else None


def _message_timestamp(moment):
    # Naive ISO UTC with microseconds: the format both conversation loaders already sort.
    return format_delivery_timestamp(moment)[:-1]


def _now(services):
    return parse_delivery_timestamp(services.clock()) or utc_now()


def _later(moment, seconds):
    return format_delivery_timestamp(moment + timedelta(seconds=seconds))


def _count(value):
    return value if type(value) is int and value >= 0 else 0


class _Delivery:
    """One claimed generation: the run document as last written and the lease that fences it."""

    def __init__(self, services, user_id, run, lease_id, *, exhausted=False):
        self.services = services
        self.user_id = user_id
        self.run = run
        self.lease_id = lease_id
        self.exhausted = exhausted
        self.workflow = None
        self.settings = None
        self.conversation = None

    @property
    def run_id(self):
        return self.run.get('id')

    @property
    def workflow_id(self):
        return self.run.get('workflow_id')

    @property
    def record(self):
        value = self.run.get(CHAT_DELIVERY_KEY)
        return dict(value) if isinstance(value, dict) else {}

    @property
    def invocation(self):
        value = self.run.get('chat_invocation')
        return value if isinstance(value, dict) else {}

    @property
    def conversation_id(self):
        return self.invocation.get('conversation_id')

    @property
    def generation(self):
        return self.record.get('generation')

    def workflow_name(self):
        if isinstance(self.workflow, dict) and isinstance(self.workflow.get('name'), str):
            return self.workflow.get('name')
        return self.run.get('workflow_name')

    def message_id(self):
        return workflow_delivery_message_id(self.run_id, self.conversation_id, self.generation)

    def now(self):
        return _now(self.services)


def _read_run(services, user_id, run_id):
    """The run document, or None when it's gone. Other storage errors propagate."""
    try:
        run = services.runs.read_item(item=run_id, partition_key=user_id)
    except Exception as exc:
        if _status_code(exc) == 404:
            return None
        raise
    if not isinstance(run, dict) or run.get('user_id') != user_id:
        return None
    return run


def _read_control_summary(services, user_id, run):
    """Summarize the run's runtime control. A control that was never written reads as missing."""
    try:
        store = services.runtime_store_factory(user_id, run.get('workflow_id'), run.get('id'))
        control = store.read(allow_deleted=True)
    except services.runtime_conflict_error as exc:
        if getattr(exc, 'code', None) == 'not_found':
            return control_summary(None)
        raise _Transient('runtime_conflict') from None
    except services.runtime_unavailable_error:
        raise _Transient('runtime_unavailable') from None
    except Exception as exc:
        delivery_log('Runtime control read failed.', level=logging.WARNING, run_id=run.get('id'), error_type=type(exc).__name__)
        raise _Transient('runtime_unavailable') from None
    return control_summary(control)


def _replace_run(services, run, record):
    """One ETag-guarded replace of the delivery record: the stored run, or None after a 412."""
    body = dict(run)
    body[CHAT_DELIVERY_KEY] = record
    try:
        stored = services.runs.replace_item(
            item=run['id'], body=body, etag=run.get('_etag'), match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        code = _status_code(exc)
        if code == 412:
            return None
        if code == 404:
            raise _LostLease() from None
        delivery_log(
            'Delivery record write failed.', level=logging.WARNING, run_id=run.get('id'),
            error_type=type(exc).__name__, code=code,
        )
        raise _Transient('record_unavailable') from None
    return stored if isinstance(stored, dict) else body


def _write_claimed(delivery, mutate, *, release=False, summary=None):
    """Apply ``mutate(record, now)`` under the lease and the run's ETag; returns the record written.

    Every write renews the lease unless it releases it. A releasing write is reconciled with
    ``summary`` (a fresh control summary) so a resume that landed mid-delivery reopens the record.
    """
    services = delivery.services
    for _attempt in range(RECORD_WRITE_RETRIES + 1):
        current = delivery.run.get(CHAT_DELIVERY_KEY)
        if (
            not isinstance(current, dict) or current.get('status') != STATUS_DELIVERING
            or current.get('lease_id') != delivery.lease_id
        ):
            raise _LostLease()
        now = delivery.now()
        record = mutate(dict(current), now)
        record['updated_at'] = format_delivery_timestamp(now)
        if release:
            record.update({'lease_id': None, 'lease_expires_at': None})
            if summary is not None:
                record, _changed, _ready = reconcile_chat_delivery(record, summary, now)
        else:
            record['lease_expires_at'] = _later(now, LEASE_SECONDS)
        stored = _replace_run(services, delivery.run, record)
        if stored is not None:
            delivery.run = stored
            return record
        fresh = _read_run(services, delivery.user_id, delivery.run_id)
        if fresh is None:
            raise _LostLease()
        delivery.run = fresh
    raise _Transient('record_conflict')


def _settled_outcome(record, changed):
    status = record.get('status')
    if status == STATUS_PENDING:
        return OUTCOME_PENDING
    if status == STATUS_READY:
        return OUTCOME_NOT_DUE
    if changed and status in {STATUS_DELIVERED, STATUS_UNDELIVERABLE}:
        return OUTCOME_CLOSED_SILENTLY
    return OUTCOME_NOT_APPLICABLE


def _postpone_unclaimed(services, user_id, run, reason):
    """An open record whose control can't be read waits out a backoff, so it never holds a sweep slot.

    The cap closes it without a notice: no outcome was ever read, so there's nothing to tell.
    """
    for _attempt in range(RECORD_WRITE_RETRIES + 1):
        record = run.get(CHAT_DELIVERY_KEY) if isinstance(run, dict) else None
        if not isinstance(record, dict) or record.get('status') not in {STATUS_PENDING, STATUS_READY, STATUS_DELIVERING}:
            return OUTCOME_UNAVAILABLE
        now = _now(services)
        stamp = format_delivery_timestamp(now)
        attempts = _count(record.get('attempts')) + 1
        if attempts >= MAX_ATTEMPTS:
            updated = _close_for_runtime(record, REASON_DELIVERY_FAILED, stamp)
            updated['attempts'] = attempts
        else:
            updated = dict(record)
            updated.update({
                'status': STATUS_READY if record.get('status') == STATUS_DELIVERING else record.get('status'),
                'lease_id': None,
                'lease_expires_at': None,
                'attempts': attempts,
                'next_attempt_at': _later(now, next_backoff_seconds(attempts)),
                'updated_at': stamp,
            })
        stored = _replace_run(services, run, updated)
        if stored is not None:
            delivery_log(
                'Delivery postponed: the runtime control could not be read.', level=logging.WARNING,
                run_id=run.get('id'), reason=reason, attempt=attempts,
            )
            if updated.get('status') in {STATUS_DELIVERED, STATUS_UNDELIVERABLE}:
                return OUTCOME_CLOSED_SILENTLY
            return OUTCOME_RETRY_SCHEDULED
        run = _read_run(services, user_id, run.get('id'))
    return OUTCOME_BUSY


def _claim(services, user_id, run_id):
    """Reconcile the record with the runtime, then claim it when a delivery is due.

    Returns a ``_Delivery`` for a claim, otherwise an outcome string.
    """
    run = _read_run(services, user_id, run_id)
    for _attempt in range(RECORD_WRITE_RETRIES + 1):
        record = run.get(CHAT_DELIVERY_KEY) if isinstance(run, dict) else None
        if not isinstance(record, dict):
            return OUTCOME_NOT_APPLICABLE
        now = _now(services)
        released = False
        if record.get('status') == STATUS_DELIVERING:
            lease_end = parse_delivery_timestamp(record.get('lease_expires_at'))
            if lease_end is not None and lease_end > now:
                return OUTCOME_BUSY
            # An abandoned claim is released, then reconciled like any ready record.
            record = {**record, 'status': STATUS_READY, 'lease_id': None, 'lease_expires_at': None}
            released = True
        try:
            summary = _read_control_summary(services, user_id, run)
        except _Transient as exc:
            waiting_until = parse_delivery_timestamp(record.get('next_attempt_at'))
            if waiting_until is not None and waiting_until > now:
                # An early hint never spends an attempt; the due sweep reads the control again.
                return OUTCOME_NOT_DUE
            return _postpone_unclaimed(services, user_id, run, exc.reason)
        updated, changed, ready = reconcile_chat_delivery(record, summary, now)
        due = parse_delivery_timestamp(updated.get('next_attempt_at'))
        if ready and (due is None or due <= now):
            attempts = _count(updated.get('attempts'))
            lease_id = uuid.uuid4().hex
            claimed = dict(updated)
            claimed.update({
                'status': STATUS_DELIVERING,
                'lease_id': lease_id,
                'lease_expires_at': _later(now, LEASE_SECONDS),
                'phase': updated.get('phase') or PHASE_CLAIMED,
                'attempts': attempts + 1,
                'next_attempt_at': None,
                'updated_at': format_delivery_timestamp(now),
            })
            stored = _replace_run(services, run, claimed)
            if stored is not None:
                return _Delivery(services, user_id, stored, lease_id, exhausted=attempts >= MAX_ATTEMPTS)
        elif changed or released:
            stored = _replace_run(services, run, updated)
            if stored is not None:
                if updated.get('status') == STATUS_READY and due is not None:
                    return OUTCOME_NOT_DUE
                return _settled_outcome(updated, changed)
        else:
            return _settled_outcome(updated, False)
        run = _read_run(services, user_id, run_id)
    return OUTCOME_BUSY


def _read_workflow(delivery):
    """The owner's workflow document, or None once it's gone or being deleted."""
    services = delivery.services
    try:
        workflow = services.workflows.read_item(item=delivery.workflow_id, partition_key=delivery.user_id)
    except Exception as exc:
        if _status_code(exc) == 404:
            return None
        delivery_log(
            'Workflow read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('workflow_unavailable') from None
    if not isinstance(workflow, dict) or workflow.get('user_id') != delivery.user_id:
        return None
    if workflow.get('deleting') or workflow.get('status') == 'deleting':
        return None
    return workflow


def _conversation_ok(services, conversation, user_id):
    """Whether the chat can still take a delivery: the owner's, not deleted, and private."""
    if not isinstance(conversation, dict) or conversation.get('user_id') != user_id:
        return False
    # The same markers the guarded unread mark checks, so both decide alike.
    if conversation.get('orchestration_deleted') or conversation.get('deleted'):
        return False
    try:
        return services.is_conversation_private(conversation, user_id) is True
    except Exception as exc:
        delivery_log('Chat privacy check failed.', level=logging.WARNING, error_type=type(exc).__name__)
        raise _Transient('privacy_unavailable') from None


def _read_conversation(delivery):
    """The requesting chat when it can still take the delivery, otherwise None."""
    services = delivery.services
    conversation_id = delivery.conversation_id
    if not isinstance(conversation_id, str) or not conversation_id:
        return None
    try:
        conversation = services.conversations.read_item(item=conversation_id, partition_key=conversation_id)
    except Exception as exc:
        if _status_code(exc) == 404:
            return None
        delivery_log(
            'Chat read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('conversation_unavailable') from None
    if not _conversation_ok(services, conversation, delivery.user_id):
        return None
    delivery.conversation = conversation
    return conversation


def _newest_message(delivery):
    """The chat's newest message row, or None for an empty chat.

    A failed read is never treated as an empty chat: it defers, and the deferral counts (D7).
    """
    services = delivery.services
    try:
        rows = list(services.messages.query_items(
            query=NEWEST_MESSAGE_QUERY,
            parameters=[{'name': '@conversation_id', 'value': delivery.conversation_id}],
            partition_key=delivery.conversation_id,
        ))
    except Exception as exc:
        delivery_log(
            'Newest-message read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Defer(True) from None
    newest = rows[0] if rows else None
    return newest if isinstance(newest, dict) else None


def _message_exists(delivery, message_id):
    """Whether the delivery message was already created by an earlier attempt."""
    services = delivery.services
    try:
        message = services.messages.read_item(item=message_id, partition_key=delivery.conversation_id)
    except Exception as exc:
        if _status_code(exc) == 404:
            return False
        delivery_log(
            'Delivery message read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('message_unavailable') from None
    return isinstance(message, dict)


def _defer_probe(delivery, record, now):
    """Raise ``_Defer`` while a reply may be streaming into the chat (D7).

    Fifteen minutes after the first deferral the activity signals are ignored. A failed
    newest-message read still defers, and that deferral consumes the attempt.
    """
    newest = _newest_message(delivery)
    first = parse_delivery_timestamp(record.get('first_deferred_at'))
    if first is not None and (now - first).total_seconds() >= DEFER_MAX_SECONDS:
        return newest
    if delivery.services.stream_activity_probe(delivery.user_id, delivery.conversation_id, now):
        raise _Defer(False)
    if isinstance(newest, dict) and newest.get('role') == 'user':
        sent = parse_delivery_timestamp(newest.get('timestamp'))
        if sent is None or (now - sent).total_seconds() < RECENT_USER_MESSAGE_SECONDS:
            raise _Defer(False)
    return newest


class _Undeliverable(Exception):
    """Post nothing for this generation. One notice says why, unless the reason is silent."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _mark_unread(delivery):
    """Mark the chat unread for M before M exists (D9 step 6); the mark and T are one write.

    A retry after ``publishing`` passes the earlier planned time, so a chat that already reached
    it (marked then read, or moved on) is left alone.
    """
    services = delivery.services
    record = delivery.record
    message_id = delivery.message_id()
    previous = record.get('planned_at') if record.get('phase') == PHASE_PUBLISHING else None
    planned_at = _message_timestamp(delivery.now())

    def publishing(current, _now):
        current.update({'phase': PHASE_PUBLISHING, 'message_id': message_id, 'planned_at': planned_at})
        return current

    _write_claimed(delivery, publishing)
    try:
        outcome, _conversation = services.mark_unread_guarded(
            services.conversations, delivery.conversation_id, delivery.user_id, message_id, planned_at,
            require_private=True, skip_if_read_since=previous if isinstance(previous, str) and previous else None,
        )
    except Exception as exc:
        delivery_log(
            'Unread mark failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('unread_unavailable') from None
    if outcome in {UNREAD_NOT_FOUND, UNREAD_UNAVAILABLE}:
        # The chat stopped taking deliveries between the re-check and the mark.
        raise _Undeliverable(REASON_CHAT_UNAVAILABLE)
    if outcome not in {UNREAD_MARKED, UNREAD_ALREADY_MARKED, UNREAD_READ_SINCE}:
        raise _Transient('unread_conflict')
    if outcome == UNREAD_MARKED:
        try:
            services.bump_cache_version(delivery.user_id, reason='workflow_chat_delivery')
        except Exception as exc:
            # A stale chat list only delays the unread dot; it never fails the delivery.
            delivery_log(
                'Chat cache bump failed.', level=logging.WARNING, run_id=delivery.run_id,
                error_type=type(exc).__name__,
            )

    def marked(current, _now):
        current['phase'] = PHASE_UNREAD_MARKED
        return current

    _write_claimed(delivery, marked)


def _create_message(delivery, build_message, *, reason=None):
    """Place M after the chat's newest message and create it (D9 step 7). A 409 means it exists.

    ``reason`` is the closed code a note stands in for, kept on the record with the phase.
    """
    services = delivery.services
    message_id = delivery.message_id()
    newest = _newest_message(delivery)
    now = delivery.now()
    newest_at = parse_delivery_timestamp(newest.get('timestamp')) if newest else None
    moment = newest_at + timedelta(microseconds=1) if newest_at is not None and newest_at >= now else now
    previous_thread = (newest.get('thread_info') or {}) if newest else {}
    thread_info = {
        'thread_id': delivery_thread_id(message_id),
        'previous_thread_id': previous_thread.get('thread_id') if isinstance(previous_thread, dict) else None,
        'active_thread': True,
        'thread_attempt': 1,
    }
    document = build_message(_message_timestamp(moment), thread_info)
    try:
        services.messages.create_item(body=document)
    except Exception as exc:
        if _status_code(exc) != 409:
            delivery_log(
                'Delivery message create failed.', level=logging.WARNING, run_id=delivery.run_id,
                error_type=type(exc).__name__,
            )
            raise _Transient('message_create_failed') from None

    def created(current, _now):
        current.update({'phase': PHASE_MESSAGE_CREATED, 'message_id': message_id, 'outcome_reason': reason})
        return current

    _write_claimed(delivery, created)


class _TooLarge(Exception):
    """Not even the smallest excerpt fits the model's context window."""


class _ResultClosed(Exception):
    """The reader closed the result for a reason a retry won't change."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


_RESULT_CODE_PREFIX = 'workflow_result_'
_RESULT_RETRY_CODES = frozenset({
    'workflow_result_storage_unavailable',
    'workflow_result_in_progress',
    'workflow_result_not_finished',
})
_RESULT_MISSING_CODE = 'workflow_result_not_found'


@dataclass
class _Content:
    """What this generation posts: the final text, already checked, and its metadata."""

    kind: str
    text: str
    reason: Optional[str] = None
    descriptor: Optional[dict] = None
    contexts: Optional[list] = None
    model_deployment_name: Optional[str] = None
    token_usage: Optional[dict] = None
    check: Any = None
    blocked_check: Any = None


def _note(delivery, label, kind, *, reason=None, reason_code=None, descriptor=None, contexts=None):
    body = delivery_note_text(kind, delivery.workflow_name(), reason_code=reason_code)
    return _Content(kind, assemble_delivery_content(label, body), reason=reason, descriptor=descriptor, contexts=contexts)


def _read_result(delivery, budget, *, expected_sha256=None):
    """Read the run's result at one excerpt budget, mapping the reader's closed reasons (D10)."""
    services = delivery.services
    try:
        return services.read_workflow_result(
            delivery.user_id, delivery.workflow_id, delivery.run_id,
            expected_sha256=expected_sha256, include_excerpts=True, excerpt_budget_bytes=budget,
        )
    except services.result_unavailable_error as exc:
        code = getattr(exc, 'code', None)
        code = code if isinstance(code, str) and code else 'workflow_result_invalid'
        if code in _RESULT_RETRY_CODES:
            # Storage was unavailable, or the run document hasn't caught up with the runtime yet.
            raise _Transient(code[len(_RESULT_CODE_PREFIX):]) from None
        raise _ResultClosed(code) from None
    except Exception as exc:
        delivery_log(
            'Workflow result read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('result_unavailable') from None


def _first_excerpt_text(result):
    for item in result.get('excerpts') or []:
        if isinstance(item, dict) and isinstance(item.get('text'), str) and item['text'].strip():
            return item['text']
    return ''


class _Excerpt:
    """The result as last read, and the smaller excerpt budgets left to try (D10)."""

    def __init__(self, delivery, result):
        self.delivery = delivery
        self.result = result
        steps = [step for step in delivery.services.excerpt_budget_steps if type(step) is int]
        self.steps = [step for step in steps if 0 < step < EXCERPT_BUDGET_BYTES]

    def step_down(self):
        if not self.steps:
            raise _TooLarge()
        descriptor = self.result.get('descriptor') if isinstance(self.result, dict) else None
        expected = descriptor.get('result_sha256') if isinstance(descriptor, dict) else None
        # Bound to the digest first read, so a smaller excerpt is always of the same result.
        self.result = _read_result(self.delivery, self.steps.pop(0), expected_sha256=expected)


def _question(delivery):
    """The request's own text, clipped; the fixed question when it's gone or was retracted."""
    services = delivery.services
    message_id = delivery.invocation.get('user_message_id')
    if not isinstance(message_id, str) or not message_id:
        return FALLBACK_QUESTION
    try:
        message = services.messages.read_item(item=message_id, partition_key=delivery.conversation_id)
    except Exception as exc:
        if _status_code(exc) == 404:
            return FALLBACK_QUESTION
        delivery_log(
            'Request message read failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('message_unavailable') from None
    if (
        not isinstance(message, dict) or message.get('role') != 'user'
        or message.get('conversation_id') != delivery.conversation_id
        or services.is_message_retracted(message)
    ):
        return FALLBACK_QUESTION
    text = message.get('content')
    text = text.strip() if isinstance(text, str) else ''
    return text[:QUESTION_MAX_CHARS] if text else FALLBACK_QUESTION


def _model_metadata(model):
    try:
        metadata = model.metadata()
    except Exception:
        metadata = None
    return metadata if isinstance(metadata, dict) else {}


def _close_model(delivery, model):
    close = getattr(model, 'close', None)
    if not callable(close):
        return
    try:
        close()
    except Exception as exc:
        delivery_log(
            'Delivery model client close failed.', level=logging.INFO, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )


def _resolve_model(delivery, seeds):
    """The model for ``seeds``, re-authorized for the requester now; None when it's unavailable."""
    services = delivery.services
    try:
        identity = services.capture_identity(delivery.user_id, conversation_id=delivery.conversation_id)
        return services.resolve_model(
            delivery.settings, user_id=delivery.user_id, seeds=seeds, identity_context=identity,
        )
    except Exception as exc:
        level = logging.INFO if isinstance(exc, services.model_error) else logging.WARNING
        delivery_log(
            'Delivery model unavailable.', level=level, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        return None


def _usage_from(response):
    usage = getattr(response, 'usage', None)
    values = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = getattr(usage, field, None) if usage is not None else None
        if type(value) is int and value >= 0:
            values[field] = value
    return values


def _reply_text(services, response):
    """The reply, clipped; None for an empty, filtered or refused completion."""
    choices = getattr(response, 'choices', None) or []
    if not choices:
        return None
    choice = choices[0]
    if getattr(choice, 'finish_reason', None) == 'content_filter':
        return None
    if getattr(getattr(choice, 'message', None), 'refusal', None):
        return None
    text = services.extract_text(response)
    text = text.strip() if isinstance(text, str) else ''
    return text[:REPLY_MAX_CHARS] if text else None


def _fits(services, model, messages):
    """Whether the messages fit the model's window with room for the reply."""
    name = getattr(model, 'model_metadata', None) or getattr(model, 'behavior_name', None) or model.deployment
    output_tokens = COMPOSE_MAX_TOKENS
    if callable(services.compose_output_tokens):
        output_tokens = services.compose_output_tokens(model)
    budget = services.calculate_budget(
        messages, name, provider=getattr(model, 'provider', None), output_tokens=output_tokens,
    )
    return isinstance(budget, dict) and budget.get('decision') == 'full_input'


def _compose_with(delivery, model, excerpt, question, time_zone):
    """One model's reply, stepping the excerpt down until it fits; None when it can't answer.

    Raises ``_TooLarge`` once the smallest excerpt still doesn't fit.
    """
    services = delivery.services
    while True:
        try:
            # A fresh nonce for every request, named by the system prompt that fences the excerpt.
            messages = services.build_result_messages(
                delivery.settings, excerpt.result, [], question, time_zone, nonce=services.new_fence_nonce(),
            )
            fits = _fits(services, model, messages)
        except Exception as exc:
            delivery_log(
                'Delivery prompt could not be prepared for this model.', level=logging.WARNING,
                run_id=delivery.run_id, error_type=type(exc).__name__,
            )
            return None
        if fits:
            break
        excerpt.step_down()
    try:
        response = model.create_completion(
            messages=messages, temperature=COMPOSE_TEMPERATURE, max_tokens=COMPOSE_MAX_TOKENS,
        )
        reply = _reply_text(services, response)
    except Exception as exc:
        delivery_log(
            'Delivery compose failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        return None
    if reply is None:
        delivery_log('Delivery compose returned no usable reply.', level=logging.INFO, run_id=delivery.run_id)
        return None
    return reply, _usage_from(response)


def _compose(delivery, excerpt, question, time_zone):
    """The reply from the request's model, then the default model (D10).

    Returns ``(reply, deployment, usage)``, or None when neither model answered.
    """
    selection = delivery.record.get('model_selection')
    chain = []
    if (
        isinstance(selection, dict) and isinstance(selection.get('model'), dict)
        and any(selection['model'].values())
    ):
        chain.append(selection)
    chain.append({})
    tried = set()
    for seeds in chain:
        model = _resolve_model(delivery, seeds)
        if model is None:
            continue
        try:
            metadata = _model_metadata(model)
            binding = (
                metadata.get('model_deployment_name'), metadata.get('model_provider'),
                metadata.get('model_endpoint_id'), metadata.get('model_id'),
            )
            if binding in tried:
                continue
            tried.add(binding)
            composed = _compose_with(delivery, model, excerpt, question, time_zone)
            if composed is not None:
                reply, usage = composed
                return reply, metadata.get('model_deployment_name') or getattr(model, 'deployment', None), usage
        finally:
            _close_model(delivery, model)
    return None


def _log_compose_usage(delivery, deployment, usage):
    """Count the compose the way 6a counts a Follow up answer (A4). Logging never fails delivery."""
    total = usage.get('total_tokens') if isinstance(usage, dict) else None
    if not total:
        return
    message_id = delivery.message_id()
    try:
        delivery.services.log_token_usage(
            user_id=delivery.user_id, token_type='chat', conversation_id=delivery.conversation_id,
            message_id=message_id, model=deployment, workspace_type='personal', total_tokens=total,
            prompt_tokens=usage.get('prompt_tokens'), completion_tokens=usage.get('completion_tokens'),
            additional_context={'workflow_result_delivery': True},
            idempotency_key=token_usage_idempotency_key(message_id, delivery.record.get('attempts')),
        )
    except Exception as exc:
        delivery_log(
            'Delivery token usage logging failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )


def _fenced(text):
    """A code block whose fence is longer than any run of backticks in the text."""
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}\n{text}\n{fence}'


def _disclosure(delivery, result, time_zone, *, truncated=False):
    return delivery.services.format_disclosure(
        result.get('descriptor') or {}, time_zone,
        truncated=truncated or bool(result.get('truncated')), partial=bool(result.get('partial')),
        analysis_only=bool(result.get('analysis_only')), skipped_reports=bool(result.get('skipped_reports')),
    )


def _checked(delivery, label, content):
    """Check the final text as chat output; a blocked reply posts the fixed note instead (D10)."""
    services = delivery.services
    try:
        check = services.check_content(
            content.text, 'chat_output', user_id=delivery.user_id, settings=delivery.settings,
        )
    except Exception as exc:
        delivery_log(
            'Delivery content check failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('content_check_unavailable') from None
    if getattr(check, 'blocked', False):
        blocked = _note(delivery, label, KIND_CONTENT_BLOCKED, reason=REASON_CONTENT_BLOCKED)
        blocked.blocked_check = check
        return blocked
    content.check = check
    return content


def _closed_result(delivery, label, code):
    """A result the reader closed: the status note, or no post at all when the run is gone."""
    if code == _RESULT_MISSING_CODE:
        if _read_workflow(delivery) is None:
            raise _Undeliverable(REASON_WORKFLOW_DELETED)
        raise _Undeliverable(REASON_ACCESS_LOST)
    delivery_log('Workflow result closed; posting the status note.', level=logging.INFO, run_id=delivery.run_id, code=code)
    return _note(delivery, label, KIND_STATUS, reason=REASON_RESULT_UNAVAILABLE)


def _result_content(delivery, label, time_zone):
    """The composed reply for a completed run, or the note that stands in for it (D10)."""
    services = delivery.services
    if not services.is_chat_workflow_results_enabled(delivery.settings, user_roles=delivery.record.get('requester_roles')):
        # Without Use Workflow Results In Chat, nothing of the result reaches a model or the chat.
        return _note(delivery, label, KIND_STATUS, reason=REASON_RESULTS_OFF)
    try:
        result = _read_result(delivery, EXCERPT_BUDGET_BYTES)
        descriptor = dict(result.get('descriptor') or {})
        contexts = [services.workflow_result_context(descriptor)]
        if result.get('saved_inputs'):
            return _note(delivery, label, KIND_ANALYSIS, descriptor=descriptor, contexts=contexts)
        if not _first_excerpt_text(result):
            return _note(delivery, label, KIND_STATUS, reason=REASON_RESULT_UNAVAILABLE)
        excerpt = _Excerpt(delivery, result)
        composed = _compose(delivery, excerpt, _question(delivery), time_zone)
    except _ResultClosed as exc:
        return _closed_result(delivery, label, exc.code)
    except _TooLarge:
        return _note(delivery, label, KIND_STATUS, reason=REASON_RESULT_UNAVAILABLE)
    except services.result_unavailable_error:
        # The descriptor didn't name a valid result context, so Follow up couldn't use it.
        return _note(delivery, label, KIND_STATUS, reason=REASON_RESULT_UNAVAILABLE)
    result = excerpt.result
    if composed is None:
        # Neither model answered: the start of the result, fenced, under a fixed sentence.
        body = f'{TRIMMED_FALLBACK_INTRO}\n\n{_fenced(_first_excerpt_text(result)[:TRIMMED_FALLBACK_CHARS])}'
        text = assemble_delivery_content(label, body, _disclosure(delivery, result, time_zone, truncated=True))
        content = _Content(KIND_RESULT, text, descriptor=descriptor, contexts=contexts)
    else:
        reply, deployment, usage = composed
        _log_compose_usage(delivery, deployment, usage)
        text = assemble_delivery_content(label, reply, _disclosure(delivery, result, time_zone))
        content = _Content(
            KIND_RESULT, text, descriptor=descriptor, contexts=contexts,
            model_deployment_name=deployment, token_usage=usage,
        )
    return _checked(delivery, label, content)


def _failure_code(delivery):
    """The closed reason code for a failed run: the runtime's gate reason, else its state."""
    try:
        summary = _read_control_summary(delivery.services, delivery.user_id, delivery.run)
    except _Transient:
        summary = {}
    return summary.get('gate_reason_code') or delivery.record.get('run_status')


def _content(delivery, label, time_zone):
    kind = delivery.record.get('kind')
    if kind == KIND_RESULT:
        return _result_content(delivery, label, time_zone)
    if kind == KIND_FAILED:
        return _note(delivery, label, KIND_FAILED, reason_code=_failure_code(delivery))
    if kind in {KIND_CANCELLED, KIND_SKIPPED}:
        return _note(delivery, label, kind)
    raise _Transient('unsupported_kind')


def _message_builder(delivery, content):
    """Build the delivery message for the timestamp and thread placement chosen at create time."""
    services = delivery.services
    record = delivery.record
    invocation = delivery.invocation
    message_id = delivery.message_id()

    def build(timestamp, thread_info):
        metadata = {
            DELIVERY_METADATA_KEY: build_delivery_metadata(
                kind=content.kind, workflow_id=delivery.workflow_id, run_id=delivery.run_id,
                generation=record.get('generation'), run_status=record.get('run_status'),
                orchestration_run_id=invocation.get('orchestration_run_id'), step_id=invocation.get('step_id'),
                requested_at=invocation.get('requested_at'),
            ),
            'token_usage': dict(content.token_usage or {}),
            'user_info': {'user_id': delivery.user_id},
            'thread_info': thread_info,
        }
        if content.kind in RESULT_CONTEXT_KINDS and content.descriptor and content.contexts:
            # The same lineage keys a 6a answer carries, so Follow up and masking treat it alike.
            metadata['workflow_result'] = dict(content.descriptor)
            metadata['workflow_result_contexts'] = [dict(item) for item in content.contexts]
        document = {
            'id': message_id,
            'conversation_id': delivery.conversation_id,
            'role': 'assistant',
            'content': content.text,
            'timestamp': timestamp,
            'model_deployment_name': content.model_deployment_name,
            'augmented': False,
            'hybrid_citations': [],
            'hybridsearch_query': None,
            'agent_citations': [],
            'web_search_citations': [],
            'user_message': None,
            'metadata': metadata,
        }
        if content.check is not None:
            services.attach_chat_check(document, content.check)
        return document

    return build


def _record_incident(delivery, check):
    """Best-effort incident for a blocked reply. The record holds categories, never text."""
    services = delivery.services
    try:
        stub = services.attach_chat_check(
            {'id': delivery.message_id(), 'conversation_id': delivery.conversation_id}, check,
        )
        services.record_incident(stub, delivery.user_id)
    except Exception as exc:
        delivery_log(
            'Delivery content incident failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )


SWEEP_QUERY = (
    'SELECT TOP @top c.id, c.user_id FROM c '
    'WHERE IS_DEFINED(c.chat_delivery) '
    'AND (NOT IS_DEFINED(c.chat_delivery.next_attempt_at) OR IS_NULL(c.chat_delivery.next_attempt_at) '
    'OR c.chat_delivery.next_attempt_at <= @now) '
    'AND (c.chat_delivery.status = @ready '
    'OR (c.chat_delivery.status = @delivering AND c.chat_delivery.lease_expires_at <= @now) '
    'OR (c.chat_delivery.status = @pending AND (c.chat_delivery.expires_at <= @now '
    'OR (ARRAY_CONTAINS(@terminal, c.status) AND c._ts <= @grace_ts))))'
)

_OUTCOME_BY_STATUS = {
    STATUS_DELIVERED: OUTCOME_DELIVERED,
    STATUS_UNDELIVERABLE: OUTCOME_UNDELIVERABLE,
    STATUS_EXPIRED: OUTCOME_EXPIRED,
}


def _write_phase(delivery, phase):
    def advance(current, _now):
        current['phase'] = phase
        return current

    _write_claimed(delivery, advance)


def _signal(delivery):
    try:
        delivery.services.signal_delivery(delivery.user_id, delivery.run_id)
    except Exception as exc:
        delivery_log('Delivery hint failed.', level=logging.INFO, run_id=delivery.run_id, error_type=type(exc).__name__)


def _finish(delivery, status, notice_kind, *, reason=None):
    """Close the generation and release the lease.

    The write is reconciled with a fresh control read, so a resume that landed while this
    generation was being delivered reopens the record for the next one.
    """
    try:
        summary = _read_control_summary(delivery.services, delivery.user_id, delivery.run)
    except _Transient:
        # The projection of the resume's own terminal write reconciles the record instead.
        summary = None

    def close(current, now):
        current.update({
            'status': status,
            'notice_kind': notice_kind,
            'next_attempt_at': None,
            'first_deferred_at': None,
        })
        if status == STATUS_DELIVERED:
            current['delivered_at'] = current.get('delivered_at') or format_delivery_timestamp(now)
        if reason is not None:
            current['outcome_reason'] = reason
        return current

    record = _write_claimed(delivery, close, release=True, summary=summary)
    if record.get('status') == STATUS_READY:
        _signal(delivery)
    delivery_log(
        'Delivery closed.', run_id=delivery.run_id, conversation_id=delivery.conversation_id,
        status=status, reason=reason,
    )
    return _OUTCOME_BY_STATUS.get(status, OUTCOME_NOT_APPLICABLE)


def _close_silently(delivery, reason):
    """Close without a post or a notice: the run itself is gone (A1)."""

    def close(current, now):
        return _close_for_runtime(current, reason, format_delivery_timestamp(now))

    _write_claimed(delivery, close, release=True)
    delivery_log('Delivery closed silently.', run_id=delivery.run_id, reason=reason)
    return OUTCOME_CLOSED_SILENTLY


def _conversation_title(delivery):
    conversation = delivery.conversation
    if conversation is None and isinstance(delivery.conversation_id, str) and delivery.conversation_id:
        try:
            conversation = delivery.services.conversations.read_item(
                item=delivery.conversation_id, partition_key=delivery.conversation_id,
            )
        except Exception as exc:
            delivery_log(
                'Chat title read failed.', level=logging.INFO, run_id=delivery.run_id,
                error_type=type(exc).__name__,
            )
            conversation = None
    if not isinstance(conversation, dict) or conversation.get('user_id') != delivery.user_id:
        return ''
    title = conversation.get('title')
    return title if isinstance(title, str) else ''


def _send_chat_notice(delivery):
    """The bell notice for a posted message. It opens the chat; its key makes it one per generation."""
    try:
        delivery.services.create_chat_response_notification(
            delivery.user_id, delivery.conversation_id, delivery.message_id(),
            conversation_title=_conversation_title(delivery),
            response_preview=delivered_notice_preview(delivery.workflow_name()),
            idempotency_key=delivery_notification_key(delivery.run_id, delivery.generation),
            strict=True,
        )
    except Exception as exc:
        delivery_log(
            'Delivery notice failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('notification_failed') from None


def _send_notice(delivery, kind, key, message, delivery_status):
    """One fixed workflow notice that links to the run. Nothing in it comes from the result."""
    name = delivery.workflow_name()
    try:
        title = notice_title(kind, name)
    except ValueError:
        title = notice_title(KIND_STATUS, name)
    try:
        delivery.services.create_notification(
            user_id=delivery.user_id,
            notification_type=NOTIFICATION_TYPE,
            title=title,
            message=message,
            link_url=workflow_run_notice_link(delivery.workflow_id, delivery.run_id),
            metadata=notice_metadata(delivery.workflow_id, delivery.run_id, delivery_status),
            idempotency_key=key,
            strict=True,
        )
    except Exception as exc:
        delivery_log(
            'Delivery notice failed.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        raise _Transient('notification_failed') from None


def _notify_delivered(delivery):
    if not phase_at_least(delivery.record.get('phase'), PHASE_NOTIFIED):
        _send_chat_notice(delivery)
        _write_phase(delivery, PHASE_NOTIFIED)
    return _finish(delivery, STATUS_DELIVERED, NOTICE_CHAT_RESPONSE)


def _undeliverable(delivery, reason):
    """Post nothing; send one notice that says the chat can't show the run, unless it's silent.

    The notice's key makes it one per generation, so this path never records ``notified``: that
    phase means a message exists.
    """
    if reason in SILENT_REASONS:
        return _close_silently(delivery, reason)
    if phase_at_least(delivery.record.get('phase'), PHASE_MESSAGE_CREATED):
        return _notify_delivered(delivery)
    _send_notice(
        delivery, delivery.record.get('kind'),
        undeliverable_notification_key(delivery.run_id, delivery.generation),
        UNDELIVERABLE_NOTICE_MESSAGE, STATUS_UNDELIVERABLE,
    )
    return _finish(delivery, STATUS_UNDELIVERABLE, NOTICE_UNDELIVERABLE, reason=reason)


def _expire(delivery):
    """The run didn't finish before the delivery window closed: one notice, nothing in the chat."""
    _send_notice(
        delivery, KIND_EXPIRED, expired_notification_key(delivery.run_id),
        EXPIRED_NOTICE_MESSAGE, STATUS_EXPIRED,
    )
    return _finish(delivery, STATUS_EXPIRED, NOTICE_EXPIRED)


def _exhausted(delivery, reason):
    """Attempts ran out. Close with a best-effort notice; never post a second message."""
    phase = delivery.record.get('phase')
    created = phase_at_least(phase, PHASE_MESSAGE_CREATED)
    if not created:
        try:
            created = _message_exists(delivery, delivery.message_id())
        except _Transient:
            # Unknown: an undeliverable notice beats a silent loss.
            created = False
    if created:
        try:
            _send_chat_notice(delivery)
            notice = NOTICE_CHAT_RESPONSE
        except _Transient:
            notice = NOTICE_NONE
        return _finish(delivery, STATUS_DELIVERED, notice)
    if delivery.record.get('kind') == KIND_EXPIRED:
        # An expiry whose notice kept failing still closes as an expiry.
        try:
            _send_notice(
                delivery, KIND_EXPIRED, expired_notification_key(delivery.run_id),
                EXPIRED_NOTICE_MESSAGE, STATUS_EXPIRED,
            )
            notice = NOTICE_EXPIRED
        except _Transient:
            notice = NOTICE_NONE
        return _finish(delivery, STATUS_EXPIRED, notice)
    try:
        _send_notice(
            delivery, delivery.record.get('kind'),
            undeliverable_notification_key(delivery.run_id, delivery.generation),
            UNDELIVERABLE_NOTICE_MESSAGE, STATUS_UNDELIVERABLE,
        )
        notice = NOTICE_UNDELIVERABLE
    except _Transient:
        notice = NOTICE_NONE
    return _finish(delivery, STATUS_UNDELIVERABLE, notice, reason=reason)


def _retry_later(delivery, reason):
    attempts = _count(delivery.record.get('attempts'))
    if attempts >= MAX_ATTEMPTS:
        return _exhausted(delivery, REASON_DELIVERY_FAILED)
    delay = next_backoff_seconds(attempts)

    def later(current, now):
        current.update({'status': STATUS_READY, 'next_attempt_at': _later(now, delay)})
        return current

    _write_claimed(delivery, later, release=True)
    delivery_log(
        'Delivery attempt failed; it will be retried.', level=logging.WARNING, run_id=delivery.run_id,
        reason=reason, attempt=attempts,
    )
    return OUTCOME_RETRY_SCHEDULED


def _defer(delivery, counted):
    """Wait for the chat to settle (D7). An uncounted deferral gives the claim's attempt back.

    A counted deferral (the chat's activity couldn't be read) backs off like any failed attempt.
    """
    attempts = _count(delivery.record.get('attempts'))
    if counted and attempts >= MAX_ATTEMPTS:
        return _exhausted(delivery, REASON_DELIVERY_FAILED)
    delay = next_backoff_seconds(attempts) if counted else DEFER_RETRY_SECONDS

    def deferred(current, now):
        current.update({'status': STATUS_READY, 'next_attempt_at': _later(now, delay)})
        if not counted:
            current['attempts'] = max(0, _count(current.get('attempts')) - 1)
            if not current.get('first_deferred_at'):
                current['first_deferred_at'] = format_delivery_timestamp(now)
        return current

    _write_claimed(delivery, deferred, release=True)
    delivery_log('Delivery deferred while the chat is busy.', run_id=delivery.run_id, step='counted' if counted else 'activity')
    return OUTCOME_DEFERRED


def _asked_when(delivery, time_zone):
    try:
        asked = delivery.services.format_run_time(delivery.invocation.get('requested_at'), time_zone)
    except Exception as exc:
        delivery_log('Request time could not be formatted.', level=logging.INFO, run_id=delivery.run_id, error_type=type(exc).__name__)
        return ''
    return asked if isinstance(asked, str) else ''


def _deliver(delivery):
    """One claimed attempt at the generation, resuming from the phase the last attempt reached (D9)."""
    services = delivery.services
    if delivery.exhausted:
        return _exhausted(delivery, REASON_DELIVERY_FAILED)
    try:
        delivery.settings = services.get_settings() or {}
    except Exception as exc:
        delivery_log('Settings read failed.', level=logging.WARNING, run_id=delivery.run_id, error_type=type(exc).__name__)
        raise _Transient('settings_unavailable') from None
    delivery.workflow = _read_workflow(delivery)
    if delivery.workflow is None:
        return _close_silently(delivery, REASON_WORKFLOW_DELETED)

    phase = delivery.record.get('phase')
    if not phase_at_least(phase, PHASE_MESSAGE_CREATED) and _message_exists(delivery, delivery.message_id()):
        # Check before compose (D9 step 4): an earlier attempt at this generation already posted M,
        # whether its phase write was lost or the record itself was reverted. Skip compose and the
        # unread mark; the notice below is idempotent by its key.
        _write_phase(delivery, PHASE_MESSAGE_CREATED)
    if phase_at_least(delivery.record.get('phase'), PHASE_MESSAGE_CREATED):
        return _notify_delivered(delivery)
    record = delivery.record
    if record.get('kind') == KIND_EXPIRED:
        return _expire(delivery)

    if _read_conversation(delivery) is None:
        raise _Undeliverable(REASON_CHAT_UNAVAILABLE)
    if not services.is_user_workflows_enabled(delivery.settings, user_roles=record.get('requester_roles')):
        raise _Undeliverable(REASON_ACCESS_LOST)
    now = delivery.now()
    if not phase_at_least(record.get('phase'), PHASE_PUBLISHING):
        expires_at = parse_delivery_timestamp(record.get('expires_at'))
        if expires_at is not None and now > expires_at:
            raise _Undeliverable(REASON_EXPIRED_BEFORE_DELIVERY)
        _defer_probe(delivery, record, now)

    time_zone = record.get('time_zone')
    label = delivery_label(delivery.workflow_name(), _asked_when(delivery, time_zone))
    content = _content(delivery, label, time_zone)
    if not phase_at_least(delivery.record.get('phase'), PHASE_UNREAD_MARKED):
        _mark_unread(delivery)
    _create_message(delivery, _message_builder(delivery, content), reason=content.reason)
    if content.blocked_check is not None:
        _record_incident(delivery, content.blocked_check)
    return _notify_delivered(delivery)


def _handle(delivery, handler, *args):
    """Record the attempt's outcome. If even that fails, the lease lapses and a later claim retries."""
    try:
        try:
            return handler(delivery, *args)
        except _Transient as exc:
            if handler is not _undeliverable:
                raise
            return _retry_later(delivery, exc.reason)
    except _LostLease:
        return OUTCOME_LOST_LEASE
    except Exception as exc:
        delivery_log(
            'Delivery outcome could not be recorded.', level=logging.WARNING, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        return OUTCOME_UNAVAILABLE


def _run_claimed(delivery):
    try:
        return _deliver(delivery)
    except _LostLease:
        return OUTCOME_LOST_LEASE
    except _Undeliverable as exc:
        return _handle(delivery, _undeliverable, exc.reason)
    except _Defer as exc:
        return _handle(delivery, _defer, exc.counted)
    except _Transient as exc:
        return _handle(delivery, _retry_later, exc.reason)
    except Exception as exc:
        delivery_log(
            'Delivery attempt failed unexpectedly.', level=logging.ERROR, run_id=delivery.run_id,
            error_type=type(exc).__name__,
        )
        return _handle(delivery, _retry_later, 'unexpected_error')


def _services_or_default(services):
    if services is not None:
        return services
    try:
        return default_workflow_chat_delivery_services()
    except Exception as exc:
        delivery_log('Delivery services unavailable.', level=logging.ERROR, error_type=type(exc).__name__)
        return None


def process_workflow_chat_delivery(user_id, run_id, *, services=None):
    """Deliver one run's outcome when it's due. Returns an ``OUTCOME_*`` string and never raises."""
    if not isinstance(user_id, str) or not user_id or not isinstance(run_id, str) or not run_id:
        return OUTCOME_NOT_APPLICABLE
    services = _services_or_default(services)
    if services is None:
        return OUTCOME_UNAVAILABLE
    try:
        claimed = _claim(services, user_id, run_id)
    except _LostLease:
        return OUTCOME_LOST_LEASE
    except Exception as exc:
        delivery_log('Delivery claim failed.', level=logging.WARNING, run_id=run_id, error_type=type(exc).__name__)
        return OUTCOME_UNAVAILABLE
    if not isinstance(claimed, _Delivery):
        return claimed
    return _run_claimed(claimed)


def process_workflow_chat_delivery_hints(services=None, limit=HINT_BATCH):
    """Process this process's queued hints. They need no lock: every claim is an ETag write."""
    services = _services_or_default(services)
    if services is None:
        return []
    try:
        hints = list(services.drain_hints(limit))
    except Exception as exc:
        delivery_log('Delivery hints could not be read.', level=logging.WARNING, error_type=type(exc).__name__)
        return []
    outcomes = []
    for user_id, run_id in hints:
        outcomes.append((run_id, process_workflow_chat_delivery(user_id, run_id, services=services)))
    return outcomes


def run_workflow_chat_delivery_sweep(services=None):
    """Find due deliveries across all users and process a bounded batch under the sweep lock (D8).

    Returns ``{'locked', 'processed', 'outcomes'}``. Without the lock nothing is queried.
    """
    summary = {'locked': False, 'processed': 0, 'outcomes': {}}
    services = _services_or_default(services)
    if services is None:
        return summary
    try:
        lock = services.acquire_lock(SWEEP_LOCK_NAME, SWEEP_LOCK_SECONDS)
    except Exception as exc:
        delivery_log('Delivery sweep lock failed.', level=logging.WARNING, error_type=type(exc).__name__)
        return summary
    if not lock:
        return summary
    summary['locked'] = True
    started = services.monotonic()
    try:
        now = _now(services)
        rows = services.runs.query_items(
            query=SWEEP_QUERY,
            parameters=[
                {'name': '@top', 'value': SWEEP_TOP},
                {'name': '@now', 'value': format_delivery_timestamp(now)},
                {'name': '@ready', 'value': STATUS_READY},
                {'name': '@delivering', 'value': STATUS_DELIVERING},
                {'name': '@pending', 'value': STATUS_PENDING},
                {'name': '@terminal', 'value': sorted(RUN_DOCUMENT_TERMINAL_STATUSES)},
                {'name': '@grace_ts', 'value': int(now.timestamp()) - SWEEP_TS_GRACE_SECONDS},
            ],
            enable_cross_partition_query=True,
        )
        for row in rows:
            if summary['processed'] >= SWEEP_MAX_RUNS or services.monotonic() - started >= SWEEP_MAX_SECONDS:
                break
            if not isinstance(row, dict):
                continue
            outcome = process_workflow_chat_delivery(row.get('user_id'), row.get('id'), services=services)
            summary['processed'] += 1
            summary['outcomes'][outcome] = summary['outcomes'].get(outcome, 0) + 1
    except Exception as exc:
        delivery_log('Delivery sweep failed.', level=logging.WARNING, error_type=type(exc).__name__)
    finally:
        try:
            services.release_lock(lock)
        except Exception as exc:
            delivery_log('Delivery sweep lock release failed.', level=logging.WARNING, error_type=type(exc).__name__)
    return summary


__all__ = (
    'HINT_BATCH',
    'OUTCOME_BUSY',
    'OUTCOME_CLOSED_SILENTLY',
    'OUTCOME_DEFERRED',
    'OUTCOME_DELIVERED',
    'OUTCOME_EXPIRED',
    'OUTCOME_LOST_LEASE',
    'OUTCOME_NOT_APPLICABLE',
    'OUTCOME_NOT_DUE',
    'OUTCOME_PENDING',
    'OUTCOME_RETRY_SCHEDULED',
    'OUTCOME_UNAVAILABLE',
    'OUTCOME_UNDELIVERABLE',
    'QUESTION_MAX_CHARS',
    'SWEEP_QUERY',
    'WorkflowChatDeliveryServices',
    'default_workflow_chat_delivery_services',
    'process_workflow_chat_delivery',
    'process_workflow_chat_delivery_hints',
    'run_workflow_chat_delivery_sweep',
)
