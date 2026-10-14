# functions_action_credential_continuation.py
"""Durable SK tool-boundary continuation, including nested local agents.

Only paused calls are resumed. Completed tool messages remain in the real SK
history; uncertain calls are never restarted. This is not a chat-message retry.
"""

from contextlib import aclosing, contextmanager
from contextvars import ContextVar
import inspect
from copy import deepcopy

from semantic_kernel.agents import ChatHistoryAgentThread
from semantic_kernel.contents import ChatHistory, ChatMessageContent, FunctionCallContent, FunctionResultContent
from semantic_kernel.filters import FilterTypes

from action_credential_contracts import ActionCredentialError, find_credential_stop
from functions_action_manifest import get_action_origin
import functions_action_credential_state as state
from functions_action_credentials import _continuation, credential_continuation


_journal = ContextVar("action_credential_journal", default=None)
_call_id = ContextVar("action_credential_call_id", default=None)
WAIT_MARKER = "simplechat_action_credentials_waiting"


def journal_active():
    return _journal.get() is not None


async def _function_boundary(context, next):
    journal = _journal.get()
    if journal is None:
        return await next(context)
    if journal.failure:
        raise journal.failure
    if journal.pending:
        journal.deferred.add(_call_id.get())
        raise journal.pending
    try:
        await next(context)
    except Exception as error:
        pending = find_credential_stop(error)
        if pending:
            journal.pending = pending
            journal.deferred.add(_call_id.get())
        elif isinstance(error, ActionCredentialError):
            journal.failure = error
        raise


async def _auto_boundary(context, next):
    journal = _journal.get()
    token = _call_id.set(context.function_call_content.id)
    try:
        await next(context)
    finally:
        _call_id.reset(token)
    if journal and journal.failure:
        context.terminate = True
    if journal and journal.pending:
        context.terminate = True
        if context.function_call_content.id in journal.deferred:
            context.function_result.metadata = {
                **(context.function_result.metadata or {}), WAIT_MARKER: True,
            }
            context.function_result.value = {WAIT_MARKER: True, "message": "This tool call has not completed."}


def install_credential_filters(kernel):
    for kind, attribute, callback in (
        (FilterTypes.FUNCTION_INVOCATION, "function_invocation_filters", _function_boundary),
        (FilterTypes.AUTO_FUNCTION_INVOCATION, "auto_function_invocation_filters", _auto_boundary),
    ):
        if not any(existing is callback for _identity, existing in getattr(kernel, attribute)):
            kernel.add_filter(kind, callback)


class CredentialJournal:
    def __init__(self, kernel, key, signature, user_id, conversation_id):
        descriptor = _continuation.get()
        if not descriptor or not descriptor.get("checkpoint_id"):
            raise ActionCredentialError("credential_continuation_unavailable")
        self.kernel, self.key, self.signature = kernel, key, signature
        self.user_id, self.conversation_id = user_id, conversation_id
        self.checkpoint_id = descriptor["checkpoint_id"]
        self.pending, self.deferred, self.failure = None, set(), None
        self.history = None
        self.loaded = None
        self.sources = []
        install_credential_filters(kernel)

    @contextmanager
    def scope(self):
        parent = _journal.get()
        token = _journal.set(self)
        try:
            yield
        finally:
            _journal.reset(token)
            if parent is not None:
                parent.sources.extend(deepcopy(self.sources))

    def collect_sources(self):
        # Source authority is initialized by the actual invocation owner.
        from content_screening.access import current_request_source_provenance

        for source in current_request_source_provenance():
            if source not in self.sources:
                self.sources.append(source)

    def load(self):
        # New invocations have no retained work. Shared/unused actions must not
        # acquire a dependency on private storage before a credential stop.
        if not (_continuation.get() or {}).get("resume"):
            return None
        try:
            checkpoint = state.read(self.user_id, self.checkpoint_id, record_type="credential_checkpoint")
        except LookupError:
            return None
        if checkpoint["conversation_id"] != self.conversation_id:
            raise ActionCredentialError("credential_checkpoint_changed")
        entry = checkpoint["value"].get(self.key)
        if not entry:
            return None
        if entry["signature"] != self.signature:
            raise ActionCredentialError("credential_execution_changed")
        from content_screening.access import assert_document_available

        for value in checkpoint["value"].values():
            for source in value.get("sources") or []:
                assert_document_available(source, user_id=self.user_id, purpose="model")
        self.sources = deepcopy(entry.get("sources") or [])
        self.loaded = entry
        return ChatHistory.restore_chat_history(entry["history"])

    def save(self, history, *, completed=False, response=None):
        self.collect_sources()
        for _attempt in range(5):
            try:
                checkpoint = state.read(self.user_id, self.checkpoint_id, record_type="credential_checkpoint")
            except LookupError:
                checkpoint = None
            entries = dict(checkpoint["value"]) if checkpoint else {}
            entries[self.key] = {
                "signature": self.signature, "history": history.serialize(), "completed": completed,
                "response": response, "sources": deepcopy(self.sources),
            }
            try:
                state.checkpoint(
                    self.user_id, self.checkpoint_id, self.conversation_id, entries,
                    expected_etag=checkpoint["_etag"] if checkpoint else None,
                )
                return
            except ActionCredentialError as error:
                if error.code != "credential_request_changed":
                    raise
        raise ActionCredentialError("credential_checkpoint_changed")

    async def resume_calls(self, history, *, arguments=None, function_behavior=None):
        calls = {
            item.id: item for message in history.messages for item in message.items
            if isinstance(item, FunctionCallContent)
        }
        for index, message in enumerate(list(history.messages)):
            paused = [
                item for item in message.items
                if isinstance(item, FunctionResultContent) and item.metadata.get(WAIT_MARKER) is True
            ]
            if not paused:
                continue
            if len(paused) != 1 or paused[0].id not in calls:
                raise ActionCredentialError("credential_checkpoint_changed")
            working = ChatHistory(messages=list(history.messages))
            await self.kernel.invoke_function_call(
                calls[paused[0].id], working, arguments=arguments, function_behavior=function_behavior,
            )
            if self.failure:
                raise self.failure
            history.messages[index] = working.messages[-1]
            self.save(history)
            if self.pending:
                raise self.pending


def _signature(agent):
    from agent_execution_context import current_agent_execution

    frame = current_agent_execution()
    configuration = None
    if frame and frame.caller.get("scope_type") and frame.caller.get("id"):
        # Fresh canonical configuration includes knowledge, model and attached
        # action selections; a slim catalogue reference is not a change guard.
        from functions_agent_delegation import resolve_delegation_agent
        from functions_settings import get_settings

        configuration = resolve_delegation_agent(
            frame.caller, user_id=frame.identity.user_id, settings=get_settings(),
        )
    manifests = []
    for plugin in agent.kernel.plugins.values():
        for function in plugin.functions.values():
            instance = getattr(getattr(function, "method", None), "__self__", None)
            manifest = getattr(instance, "manifest", None)
            if manifest:
                origin = get_action_origin(manifest)
                manifests.append({
                    "manifest": manifest,
                    "origin": (origin.scope_type, origin.scope_id, origin.action_id) if origin else None,
                })
    services = []
    for service_id, service in sorted(getattr(agent.kernel, "services", {}).items()):
        client = getattr(service, "client", None)
        services.append({
            "id": service_id, "model": getattr(service, "ai_model_id", None),
            "endpoint": str(getattr(client, "base_url", "")),
            "api_version": getattr(client, "_api_version", None),
        })
    return state.key_for(
        agent.name, agent.instructions, getattr(agent, "deployment_name", None),
        getattr(agent, "azure_endpoint", None), getattr(agent, "api_version", None),
        configuration, manifests, services,
        sorted(item.fully_qualified_name for item in agent.kernel.get_full_list_of_function_metadata()),
    )


def _journal_for(agent, messages):
    from agent_execution_context import current_agent_execution

    frame = current_agent_execution()
    descriptor = _continuation.get()
    if (
        not frame or not descriptor or not state.is_configured()
        or not all(hasattr(agent, field) for field in ("kernel", "name", "instructions", "arguments", "function_choice_behavior"))
    ):
        return None
    key = "root" if frame.depth == 0 and descriptor.get("mode") == "chat" else state.key_for(
        agent.name, [
            message.to_dict() if hasattr(message, "to_dict") else str(message)
            for message in (messages if isinstance(messages, list) else [messages])
        ],
    )
    return CredentialJournal(
        agent.kernel, key, _signature(agent), frame.identity.user_id, frame.identity.conversation_id,
    )


async def _prepare_agent(journal, agent, messages, kwargs):
    history = journal.load()
    if history:
        await journal.resume_calls(
            history, arguments=agent.arguments, function_behavior=agent.function_choice_behavior,
        )
        thread = ChatHistoryAgentThread(history)
        return thread, {"messages": None, "thread": thread, **kwargs}
    thread = kwargs.pop("thread", None) or ChatHistoryAgentThread()
    return thread, {"messages": messages, "thread": thread, **kwargs}


async def invoke_credential_agent(agent, messages, **kwargs):
    journal = _journal_for(agent, messages)
    if journal is None:
        return await _invoke_agent(agent, messages=messages, **kwargs)
    with journal.scope():
        loaded = journal.load()
        if loaded is not None and journal.loaded.get("completed"):
            return ChatMessageContent(role="assistant", content=journal.loaded["response"] or "")
        thread, kwargs = await _prepare_agent(journal, agent, messages, kwargs)
        result = await _invoke_agent(agent, **kwargs)
        if journal.failure:
            raise journal.failure
        journal.collect_sources()
        history = ChatHistory(messages=[message async for message in thread.get_messages()])
        if journal.pending or journal.loaded:
            journal.save(history, completed=journal.pending is None, response=str(result) if result is not None else "")
        if journal.pending:
            raise journal.pending
        return result


async def _invoke_agent(agent, **kwargs):
    result = agent.invoke(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    if hasattr(result, "__aiter__"):
        last = None
        async with aclosing(result) as stream:
            async for item in stream:
                last = item
        result = last
    return result


async def stream_credential_agent(agent, messages, **kwargs):
    journal = _journal_for(agent, messages)
    if journal is None:
        async with aclosing(agent.invoke_stream(messages=messages, **kwargs)) as stream:
            async for result in stream:
                yield result
        return
    with journal.scope():
        loaded = journal.load()
        if loaded is not None and journal.loaded.get("completed"):
            yield ChatMessageContent(role="assistant", content=journal.loaded["response"] or "")
            return
        thread, kwargs = await _prepare_agent(journal, agent, messages, kwargs)
        async with aclosing(agent.invoke_stream(**kwargs)) as stream:
            async for result in stream:
                if journal.pending is None and journal.failure is None:
                    yield result
        if journal.failure:
            raise journal.failure
        journal.collect_sources()
        history = ChatHistory(messages=[message async for message in thread.get_messages()])
        if journal.pending or journal.loaded:
            journal.save(
                history, completed=journal.pending is None,
                response=history.messages[-1].content if journal.pending is None and history.messages else None,
            )
        if journal.pending:
            raise journal.pending
