# functions_m365_agent_continuation.py
"""Checkpoint real agent tool history so an approval does not repeat completed calls."""

from contextvars import ContextVar
from functools import wraps
import hashlib
import json

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from flask import g, has_request_context
from semantic_kernel.agents import ChatHistoryAgentThread
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent, FunctionCallContent, FunctionResultContent
from semantic_kernel.filters import FilterTypes

from functions_conversation_memory import EvidenceChunk, EvidenceSource
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_execution import get_m365_execution_context
from m365_interaction import M365_AUTH_INTERACTION_CODES, M365SignInRequired


_current_journal = ContextVar("m365_agent_journal", default=None)
_current_call_id = ContextVar("m365_agent_call_id", default=None)
_dependencies = {}
PAUSED_TOOL_MARKER = "simplechat_m365_tool_waiting"


def configure_m365_agent_continuation(*, memory_resolver, jobs_factory, model_context_setter):
    _dependencies.update(
        memory_resolver=memory_resolver, jobs_factory=jobs_factory,
        model_context_setter=model_context_setter,
    )


def get_m365_analysis_agent(context):
    journal = _current_journal.get()
    if journal is None or (
        journal.context.request_id != context.request_id
        or journal.context.data_user_id != context.data_user_id
        or journal.context.conversation_id != context.conversation_id
    ):
        raise M365PolicyError("m365_analysis_unavailable", "A selected conversation agent is required for deeper analysis.")
    return journal.agent


def _approval_error(error):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, (M365ApprovalRequired, M365SignInRequired)):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


async def _capture_function_wait(context, next):
    journal = _current_journal.get()
    if journal is None:
        return await next(context)
    if journal.pending is not None:
        journal.deferred_calls.add(_current_call_id.get())
        raise journal.pending
    try:
        return await next(context)
    except Exception as error:
        pending = _approval_error(error)
        if pending is not None:
            journal.pending = pending
            journal.deferred_calls.add(_current_call_id.get())
        raise


async def _terminate_for_approval(context, next):
    call_id = context.function_call_content.id
    token = _current_call_id.set(call_id)
    try:
        await next(context)
    finally:
        _current_call_id.reset(token)
    journal = _current_journal.get()
    if journal is not None and journal.pending is None:
        value = context.function_result.value
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = None
        if isinstance(value, dict) and (
            value.get("source") in {"calendar", "email", "onedrive", "spo"}
            or journal.context.workflow_id
        ):
            error = value.get("error")
            if isinstance(error, str):
                error = {**value, "code": error}
            if isinstance(error, dict) and error.get("code") in M365_AUTH_INTERACTION_CODES:
                journal.pending = M365SignInRequired(error["code"], error)
                journal.deferred_calls.add(call_id)
    if journal is not None and journal.pending is not None:
        context.terminate = True
        if call_id in journal.deferred_calls:
            context.function_result.metadata = {
                **context.function_result.metadata,
                PAUSED_TOOL_MARKER: True,
                "m365_approval_id": journal.pending.approval_id,
            }
            context.function_result.value = {
                PAUSED_TOOL_MARKER: True,
                "approval_id": journal.pending.approval_id,
                "message": "This call has not executed. Resume only after the user's decision.",
            }


def install_m365_agent_filters(kernel):
    filters = (
        (FilterTypes.FUNCTION_INVOCATION, "function_invocation_filters", _capture_function_wait),
        (FilterTypes.AUTO_FUNCTION_INVOCATION, "auto_function_invocation_filters", _terminate_for_approval),
    )
    for filter_type, attribute, callback in filters:
        if not any(existing is callback for _identity, existing in getattr(kernel, attribute)):
            kernel.add_filter(filter_type, callback)


def _is_paused_result(item):
    return (
        isinstance(item, FunctionResultContent)
        and item.metadata.get(PAUSED_TOOL_MARKER) is True
    )


class AgentContinuationJournal:
    def __init__(self, agent, context):
        if not _dependencies:
            raise M365PolicyError("m365_continuation_unavailable", "Durable agent continuation is not configured.")
        self.agent = agent
        self.context = context
        self.store, self.memory_context = _dependencies["memory_resolver"](context)
        self.jobs = _dependencies["jobs_factory"]()
        self.key = hashlib.sha256(
            f"{agent.name}:{context.step_id or ''}".encode("utf-8")
        ).hexdigest()
        self.fingerprint = hashlib.sha256(json.dumps({
            "name": agent.name,
            "instructions": agent.instructions,
            "model": getattr(agent, "deployment_name", None),
            "functions": sorted(
                metadata.fully_qualified_name
                for metadata in agent.kernel.get_full_list_of_function_metadata()
            ),
        }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        self.pending = None
        self.deferred_calls = set()
        self.run_id = None
        self.thread = None
        self.history = None
        install_m365_agent_filters(agent.kernel)

    def _job(self):
        try:
            return self.jobs.read_item(self.context.request_id, partition_key=self.context.data_user_id)
        except CosmosResourceNotFoundError:
            body = {
                "id": self.context.request_id, "user_id": self.context.data_user_id,
                "actor_user_id": self.context.actor_user_id,
                "conversation_id": self.context.conversation_id,
                "workflow_id": self.context.workflow_id, "run_id": self.context.run_id,
                "type": "m365_execution_request", "status": "running",
            }
            try:
                return self.jobs.create_item(body=body)
            except CosmosResourceExistsError:
                return self.jobs.read_item(self.context.request_id, partition_key=self.context.data_user_id)

    def _save_reference(self, run_id):
        job = self._job()
        updated = dict(job)
        updated["agent_checkpoints"] = {
            **job.get("agent_checkpoints", {}),
            self.key: {"run_id": run_id, "fingerprint": self.fingerprint},
        }
        self.jobs.replace_item(
            job["id"], body=updated, partition_key=self.context.data_user_id,
            etag=job["_etag"], match_condition=MatchConditions.IfNotModified,
        )

    def _read_history(self, checkpoint):
        pieces = []
        start = 0
        while start is not None:
            page = self.store.read_evidence_range(
                self.memory_context, self.run_id, checkpoint["history_evidence_id"], start=start,
            )
            pieces.extend(chunk["text"] for chunk in page["chunks"])
            start = page["next_start"]
        return ChatHistory.restore_chat_history("".join(pieces))

    def _save_history(self, history):
        if self.run_id is None:
            run = self.store.create_run(
                self.memory_context,
                request_id=self.context.request_id, purpose="m365_agent_continuation",
            )
            self.run_id = run["run_id"]
            self._save_reference(self.run_id)
        serialized = history.serialize()
        source = self.store.add_evidence(
            self.memory_context, self.run_id,
            source=EvidenceSource(
                source_type="agent_continuation", source_id=self.key,
                version=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                coverage_complete=True,
            ),
            chunks=(
                EvidenceChunk(serialized[offset:offset + 24000])
                for offset in range(0, len(serialized), 24000)
            ),
        )
        self.store.append_checkpoint(
            self.memory_context, self.run_id,
            checkpoint={
                "history_evidence_id": source["evidence_id"],
                "agent_fingerprint": self.fingerprint,
            },
        )

    async def prepare(self, args, kwargs):
        entry = self._job().get("agent_checkpoints", {}).get(self.key)
        if entry:
            if entry["fingerprint"] != self.fingerprint:
                raise M365PolicyError(
                    "m365_agent_changed", "The agent changed while this request was paused. Start a new request.",
                )
            self.run_id = entry["run_id"]
            checkpoint = self.store.read_checkpoint(self.memory_context, self.run_id)
            if not checkpoint:
                raise M365PolicyError("m365_recovery_required", "The agent checkpoint needs recovery.")
            self.history = self._read_history(checkpoint["checkpoint"])
            _dependencies["model_context_setter"](
                getattr(self.agent, "deployment_name", None), self.history.messages,
                instructions=self.agent.instructions,
            )
            await self._resume_paused_calls()
            self.thread = ChatHistoryAgentThread(self.history)
            args = ()
            kwargs = {**kwargs, "messages": None, "thread": self.thread}
        else:
            self.thread = kwargs.get("thread") or ChatHistoryAgentThread()
            kwargs = {**kwargs, "thread": self.thread}
        messages = args[0] if args else kwargs.get("messages")
        history_messages = self.history.messages if self.history is not None else (
            messages if isinstance(messages, list) else [messages] if messages else []
        )
        _dependencies["model_context_setter"](
            getattr(self.agent, "deployment_name", None),
            history_messages,
            instructions=self.agent.instructions,
        )
        return args, kwargs

    async def _resume_paused_calls(self):
        calls = {
            item.id: item for message in self.history.messages for item in message.items
            if isinstance(item, FunctionCallContent)
        }
        for index, message in enumerate(list(self.history.messages)):
            pending_items = [item for item in message.items if _is_paused_result(item)]
            if not pending_items:
                continue
            if len(pending_items) != 1 or pending_items[0].id not in calls:
                raise M365PolicyError("m365_checkpoint_invalid", "A paused tool call cannot be resolved.")
            call = calls[pending_items[0].id]
            working = ChatHistory(messages=list(self.history.messages))
            await self.agent.kernel.invoke_function_call(
                call, working, arguments=self.agent.arguments,
                function_behavior=self.agent.function_choice_behavior,
            )
            self.history.messages[index] = working.messages[-1]
            self._save_history(self.history)
            if self.pending is not None:
                raise self.pending

    async def finish(self):
        pending = self.pending
        if pending is None:
            return
        history = ChatHistory()
        async for message in self.thread.get_messages():
            history.add_message(message)
        self._save_history(history)
        raise pending


def _needs_journal(context):
    return context is not None and (
        bool(context.workflow_id)
        or any(config.get("source") in {"onedrive", "spo"} for config in context.action_configs.values())
    )


def _add_declined_source_notice(args, kwargs):
    declined = getattr(g, "m365_declined_sources", ()) if has_request_context() else ()
    labels = {"calendar": "Calendar", "email": "Email", "onedrive": "OneDrive", "spo": "SharePoint Online"}
    sources = sorted({labels[source] for source in declined if source in labels})
    if not sources:
        return args, kwargs
    incoming = kwargs.get("messages") if "messages" in kwargs else args[0] if args else None
    if isinstance(incoming, str):
        messages = [ChatMessageContent(role=AuthorRole.USER, content=incoming)]
    elif isinstance(incoming, ChatMessageContent):
        messages = [incoming]
    elif incoming is None:
        messages = []
    elif isinstance(incoming, list):
        messages = list(incoming)
    else:
        raise ValueError("Microsoft 365 conversation messages must use the agent's supported message types.")
    notice = ChatMessageContent(
        role=AuthorRole.SYSTEM,
        content=(
            "The user declined fresh access to these Microsoft 365 sources for this request: "
            + ", ".join(sources)
            + ". Continue with the other permitted sources and explicitly explain this coverage limitation. "
            "Previously published conversation evidence may still be used, but do not describe it as a fresh source read."
        ),
    )
    if args and "messages" not in kwargs:
        return ([notice, *messages], *args[1:]), kwargs
    return args, {**kwargs, "messages": [notice, *messages]}


def m365_agent_continuation(function):
    @wraps(function)
    async def wrapped(agent, *args, **kwargs):
        context = get_m365_execution_context()
        args, kwargs = _add_declined_source_notice(args, kwargs)
        if not _needs_journal(context):
            return await function(agent, *args, **kwargs)
        journal = AgentContinuationJournal(agent, context)
        token = _current_journal.set(journal)
        try:
            args, kwargs = await journal.prepare(args, kwargs)
            result = await function(agent, *args, **kwargs)
            await journal.finish()
            return result
        finally:
            _current_journal.reset(token)
    return wrapped


def m365_agent_stream_continuation(function):
    @wraps(function)
    async def wrapped(agent, *args, **kwargs):
        context = get_m365_execution_context()
        args, kwargs = _add_declined_source_notice(args, kwargs)
        if not _needs_journal(context):
            async for response in function(agent, *args, **kwargs):
                yield response
            return
        journal = AgentContinuationJournal(agent, context)
        token = _current_journal.set(journal)
        try:
            args, kwargs = await journal.prepare(args, kwargs)
            async for response in function(agent, *args, **kwargs):
                if journal.pending is None:
                    yield response
            await journal.finish()
        finally:
            _current_journal.reset(token)
    return wrapped
