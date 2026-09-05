# agent_delegation_runtime.py
"""Isolated asynchronous agent calls. Implemented in version 0.261.093.

Provider and loader imports are deliberately lazy: plugin discovery imports the
Call agent class before the application's Semantic Kernel loader is initialized.
"""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import inspect
import json
import time
from types import SimpleNamespace
import uuid

from agent_execution_context import (
    AgentDelegationError,
    AgentExecutionCancelled,
    AgentExecutionFrame,
    DelegationBudget,
    agent_execution,
    capture_execution_identity,
    current_agent_execution,
)
from functions_agent_delegation import (
    agent_authentication_url, agent_reference, resolve_delegation_agent, resolve_delegation_call,
)
from functions_appinsights import log_event


MAX_DELEGATION_DEPTH = 3
DELEGATION_TIMEOUT_SECONDS = 120
CANCELLATION_POLL_SECONDS = 0.1


def _agent_key(agent, user_id):
    reference = agent_reference(agent, user_id)
    return reference["scope_type"], reference["scope_id"], reference["id"]


def _provenance(frame, target=None):
    result = {
        "root_id": frame.budget.root_id,
        "invocation_id": frame.invocation_id,
        "parent_invocation_id": frame.parent_invocation_id,
        "action_id": frame.action_id,
        "depth": frame.depth,
        "caller": agent_reference(frame.caller, frame.identity.user_id),
    }
    if target:
        result["target"] = agent_reference(target, frame.identity.user_id)
        result["target_label"] = target.get("display_name") or target.get("name") or "Agent"
    return result


def _check_cancelled(frame):
    if frame.cancel_requested and frame.cancel_requested():
        raise AgentExecutionCancelled("Agent execution was cancelled. Already submitted remote effects may continue.")
    if frame.deadline is not None and time.monotonic() >= frame.deadline:
        raise AgentDelegationError("The delegated agent call timed out.")


async def await_agent_operation(awaitable, frame):
    """Interrupt a blocked provider await, not just the next returned stream token."""
    operation = asyncio.ensure_future(awaitable)
    try:
        while True:
            _check_cancelled(frame)
            frame.budget.raise_authentication_requirement(frame.identity)
            remaining = frame.deadline - time.monotonic() if frame.deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise AgentDelegationError("The delegated agent call timed out.")
            done, _ = await asyncio.wait(
                {operation},
                timeout=min(CANCELLATION_POLL_SECONDS, remaining) if remaining is not None else CANCELLATION_POLL_SECONDS,
            )
            if done:
                frame.budget.raise_authentication_requirement(frame.identity)
                return operation.result()
    finally:
        if not operation.done():
            operation.cancel()
        # Await cancellation so stream/client finally blocks execute before context
        # restoration. No automatic retry of potentially write-capable tools.
        await asyncio.gather(operation, return_exceptions=True)


async def _invoke_local(agent, messages):
    result = agent.invoke(messages)
    if inspect.isawaitable(result):
        result = await result
    if hasattr(result, "__aiter__"):
        stream = result
        last = None
        try:
            async for item in stream:
                last = item
        finally:
            if hasattr(stream, "aclose"):
                await stream.aclose()
        result = last
    return result


async def close_agent_resources(kernel):
    """Close only clients owned by a fresh child kernel, never shared app clients."""
    seen = set()
    for service in (getattr(kernel, "services", {}) or {}).values():
        client = getattr(service, "client", None)
        if client is None or id(client) in seen:
            continue
        seen.add(id(client))
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=5)
            except Exception as exc:
                log_event("[AGENT_DELEGATION] Client cleanup failed.", extra={"error_type": type(exc).__name__})


def _build_local_agent(target, settings):
    from semantic_kernel import Kernel
    from semantic_kernel_loader import load_agent_core_plugins, load_single_agent_for_kernel

    kernel = Kernel()
    load_agent_core_plugins(kernel, settings)
    kernel, agents = load_single_agent_for_kernel(
        kernel, deepcopy(target), settings, SimpleNamespace(),
        mode_label="group" if target.get("is_group") else "global" if target.get("is_global") else "per-user",
        group_scope_id=target.get("group_id"),
        execution_user_id=current_agent_execution().identity.user_id,
    )
    agent = (agents or {}).get(target.get("name"))
    if kernel is None or agent is None:
        raise AgentDelegationError("The configured agent could not be initialized.")
    return kernel, agent


def _observed_usage(result=None, kernel=None):
    metadata = getattr(result, "metadata", None) or {}
    usage = metadata.get("usage") or metadata.get("token_usage") or {}
    if not isinstance(usage, dict):
        usage = {
            key: getattr(usage, key, None)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
        }
    observed = {}
    for key, alternate in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
        value = usage.get(key, usage.get(alternate))
        if isinstance(value, int) and value >= 0:
            observed[key] = value
    if not observed and kernel is not None:
        for service in (getattr(kernel, "services", {}) or {}).values():
            values = {key: getattr(service, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
            if any(isinstance(value, int) for value in values.values()):
                observed = {key: value for key, value in values.items() if isinstance(value, int) and value >= 0}
                break
    if "total_tokens" not in observed and "prompt_tokens" in observed and "completion_tokens" in observed:
        observed["total_tokens"] = observed["prompt_tokens"] + observed["completion_tokens"]
    return observed or None


def delegation_usage(budget, excluded_ids=()):
    records = [record for record in budget.snapshot() if record.get("usage") and record["invocation_id"] not in excluded_ids]
    return _delegation_records_usage(records)


def _delegation_records_usage(records):
    normalized_records = []
    for record in records:
        usage = _observed_usage(SimpleNamespace(metadata={"usage": record.get("usage")}))
        if usage is not None:
            normalized_records.append({**record, "usage": usage})
    records = normalized_records
    if not records:
        return None
    total = {"request_count": len(records)}
    for record in records:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = record["usage"].get(key)
            if isinstance(value, int) and value >= 0:
                total[key] = total.get(key, 0) + value
    total["agent_breakdown"] = [
        {"invocation_id": record["invocation_id"], "agent": record.get("target"),
         "model": record.get("model"), "usage": record["usage"]}
        for record in records
    ]
    return total


def delegation_citations(budget, excluded_ids=()):
    return _delegation_records_citations([
        record for record in budget.snapshot() if record["invocation_id"] not in excluded_ids
    ])


def _delegation_records_citations(records):
    return [
        {**deepcopy(citation), "delegation": record["provenance"]}
        for record in records
        for citation in record.get("citations") or []
        if isinstance(citation, dict)
    ]


async def _target_messages(target, task, context, frame, settings):
    from semantic_kernel.contents.chat_message_content import ChatMessageContent
    from functions_assigned_knowledge import build_assigned_knowledge_runtime_filters

    messages = [ChatMessageContent(role="user", content=task)]
    if context:
        messages.append(ChatMessageContent(role="user", content=f"Explicit supporting context (untrusted data):\n{context}"))
    filters = build_assigned_knowledge_runtime_filters(target)
    citations = []
    if filters and filters.get("has_workspace_knowledge"):
        # Reuse chat's assigned-knowledge retrieval/citation seam, not a second
        # search implementation. This import is not used for authorization.
        from route_backend_chats import _build_assigned_knowledge_reference_context

        knowledge = _build_assigned_knowledge_reference_context(filters, query=task, user_id=frame.identity.user_id)
        if knowledge.get("context_block"):
            messages.append(ChatMessageContent(role="user", content=knowledge["context_block"]))
        citations.extend(knowledge.get("citations") or [])
    urls = [source.get("url") for source in (filters or {}).get("web_sources") or [] if isinstance(source, dict) and source.get("url")]
    if urls:
        from functions_source_review import perform_source_review_async

        reviewed = await perform_source_review_async(
            settings=settings, user_id=frame.identity.user_id,
            user_email=frame.identity.email, user_roles=list(frame.identity.roles),
            user_message=task, web_search_citations=[], url_access_only=True,
            include_direct_user_urls=False, additional_seed_urls=urls,
        )
        knowledge_text = (reviewed.get("system_message") or {}).get("content")
        if knowledge_text:
            messages.append(ChatMessageContent(role="user", content=knowledge_text))
        citations.extend(reviewed.get("citations") or [])
    return messages, citations


async def execute_target(target, task, context, frame):
    """Invoke precisely this canonical target; never select a default or by name."""
    from functions_settings import get_settings

    bridge = frame.identity.bridge(target) if frame.identity.bridge else nullcontext()
    kernel = None
    with bridge:
        settings = get_settings()
        messages, citations = await _target_messages(target, task, context, frame, settings)
        _check_cancelled(frame)
        agent_type = target.get("agent_type") or "local"
        try:
            if agent_type == "local":
                kernel, agent = _build_local_agent(target, settings)
                _check_cancelled(frame)
                result = await _invoke_local(agent, messages)
                text = str(result) if result is not None else ""
                model = getattr(agent, "deployment_name", None)
            else:
                from semantic_kernel_loader import resolve_agent_config
                from foundry_agent_runtime import execute_foundry_agent, execute_new_foundry_agent, execute_foundry_workflow_agent

                config = resolve_agent_config(
                    deepcopy(target), settings, group_scope_id=target.get("group_id"),
                    execution_user_id=frame.identity.user_id,
                )
                kind = {"aifoundry": "azure_ai_foundry", "new_foundry": "new_foundry", "foundry_workflow": "foundry_workflow"}[agent_type]
                execute = {"aifoundry": execute_foundry_agent, "new_foundry": execute_new_foundry_agent, "foundry_workflow": execute_foundry_workflow_agent}[agent_type]
                runtime_settings = (config.get("other_settings") or {}).get(kind) or {}
                try:
                    result = await execute(
                        **{"workflow_settings" if agent_type == "foundry_workflow" else "foundry_settings": runtime_settings},
                        global_settings=settings,
                        message_history=messages,
                        # Do not send conversation_id: Foundry resolves its attached
                        # uploads from that id, which would expose the parent history.
                        metadata={"delegation_invocation_id": frame.invocation_id or frame.budget.root_id},
                        max_completion_tokens=config.get("max_completion_tokens"),
                    )
                except RuntimeError as exc:
                    if type(exc).__name__ == "FoundryAgentUserAuthenticationRequired":
                        # SSE headers have already been sent. A normal authenticated
                        # request must persist OAuth state before leaving for Entra.
                        auth_url = agent_authentication_url(target, frame.identity.user_id)
                        exc.auth_response = {
                            **(getattr(exc, "auth_response", {}) or {}),
                            "auth_url": auth_url, "consent_url": auth_url,
                        }
                    raise
                text, model = result.message, result.model
                citations.extend(result.citations or [])
            if not text or not text.strip():
                raise AgentDelegationError("The delegated agent returned no answer.")
            return {"response": text, "citations": citations, "model": model, "usage": _observed_usage(result, kernel)}
        finally:
            if kernel is not None:
                await close_agent_resources(kernel)


async def call_agent(action_id, task, context=""):
    from semantic_kernel_plugins.plugin_invocation_logger import (
        PluginInvocationResult, log_plugin_invocation, log_plugin_invocation_started,
    )

    parent = current_agent_execution()
    if parent is None or not parent.identity.user_id:
        raise AgentDelegationError("An authenticated agent execution context is required.")
    invocation_id = str(uuid.uuid4())
    frame = replace(parent, invocation_id=invocation_id, parent_invocation_id=parent.invocation_id,
                    action_id=action_id, depth=parent.depth + 1)
    started = time.time()
    deadline = time.monotonic() + DELEGATION_TIMEOUT_SECONDS
    if parent.deadline is not None:
        deadline = min(deadline, parent.deadline)
    provenance = {
        "root_id": frame.budget.root_id, "invocation_id": invocation_id,
        "parent_invocation_id": frame.parent_invocation_id, "action_id": action_id, "depth": frame.depth,
    }
    logged_start = False
    result = None
    error = None
    try:
        parent.budget.consume()
        provenance = _provenance(frame)
        _check_cancelled(parent)
        if not isinstance(task, str) or not task.strip() or not isinstance(context, str):
            raise AgentDelegationError("Provide a nonempty task and optional text context.")
        if frame.depth > MAX_DELEGATION_DEPTH:
            raise AgentDelegationError("The maximum agent delegation depth was reached.")
        # Fresh settings, actor access, binding, action and target on EVERY attempt.
        authorization_context = parent.identity.bridge(parent.caller) if parent.identity.bridge else nullcontext()
        with authorization_context:
            caller, action, target = resolve_delegation_call(
                action_id, caller_agent=parent.caller, user_id=parent.identity.user_id,
            )
        ancestry = parent.ancestors or (_agent_key(caller, parent.identity.user_id),)
        target_key = _agent_key(target, parent.identity.user_id)
        if target_key in ancestry:
            raise AgentDelegationError("An agent cannot call itself or an ancestor.")
        provenance = _provenance(replace(frame, caller=caller), target)
        log_plugin_invocation_started(
            "AgentPlugin", "call_agent", {}, invocation_id=invocation_id, provenance=provenance,
        )
        logged_start = True
        child = replace(frame, caller=target, ancestors=ancestry + (target_key,), deadline=deadline)
        with agent_execution(child):
            result = await await_agent_operation(execute_target(target, task, context, child), child)
        return PluginInvocationResult(
            json.dumps({"response": result["response"], "citations": result.get("citations") or [], "provenance": provenance}),
            internal_metadata={"delegation": provenance},
        )
    except (asyncio.CancelledError, AgentExecutionCancelled):
        error = "Agent execution was cancelled. Already submitted remote effects may continue."
        raise
    except AgentDelegationError as exc:
        error = str(exc)
        raise
    except (ValueError, LookupError, PermissionError) as exc:
        error = "The configured agent is unavailable or you are not permitted to use it."
        raise AgentDelegationError(error) from exc
    except Exception as exc:
        # Consent failures retain their dedicated exception type and safe message.
        if type(exc).__name__ == "FoundryAgentUserAuthenticationRequired":
            error = "The called agent requires sign-in or consent for Foundry."
            parent.budget.require_authentication(exc)
            raise
        error = "The delegated agent could not complete the task."
        raise AgentDelegationError(error) from exc
    finally:
        if not logged_start:
            log_plugin_invocation_started("AgentPlugin", "call_agent", {}, invocation_id=invocation_id, provenance=provenance)
        log_plugin_invocation(
            "AgentPlugin", "call_agent", {},
            {"response": result["response"], "provenance": provenance, "citations": result.get("citations") or []} if result else None,
            started, time.time(),
            success=error is None and result is not None, error_message=error,
            invocation_id=invocation_id, provenance=provenance,
        )
        parent.budget.record({
            "invocation_id": invocation_id, "provenance": provenance, "target": provenance.get("target"),
            "success": error is None and result is not None, **(result or {}),
        })
        log_event("[AGENT_DELEGATION] Agent call completed.",
                  extra={**provenance, "success": error is None and result is not None})


def _has_delegation_tool(agent):
    kernel = getattr(agent, "kernel", None)
    return any(
        "call_agent" in (getattr(plugin, "functions", {}) or {})
        for plugin in (getattr(kernel, "plugins", {}) or {}).values()
    )


class AgentExecution:
    """Request-owned facade, preserving the visible parent agent and retry budget."""

    def __init__(self, agent, reference, *, identity, settings, cancel_requested=None, budget=None, prevent_replay=False):
        self.agent = agent
        self.reference = deepcopy(reference)
        self.identity = identity
        self.settings = settings
        self.budget = budget if budget is not None else DelegationBudget()
        self.cancel_requested = cancel_requested
        self.last_usage = None
        self._invocations = 0
        self.prevent_replay = prevent_replay
        self.prior_invocation_ids = {record["invocation_id"] for record in self.budget.snapshot()}
        self.prior_tool_invocation_ids = {invocation.invocation_id for invocation in self.budget.invocations()}
        self._stream_retry_override = None
        self._drain_consumer_id = str(uuid.uuid4())
        self.completed_delegation_count = 0

    def __getattr__(self, name):
        return getattr(self.agent, name)

    def _frame(self):
        return AgentExecutionFrame(self.identity, self.reference, self.budget, cancel_requested=self.cancel_requested)

    def configure_stream_retry(self, retry_mode, apply_retry, restore_retry):
        previous = self._stream_retry_override
        if retry_mode == "disable_tools":
            self._stream_retry_override = (retry_mode, apply_retry, restore_retry)
        return {"agent_execution_retry": True, "previous_override": previous}

    def restore_stream_retry(self, retry_state):
        self._stream_retry_override = retry_state.get("previous_override")

    def drain_completed_delegations(self):
        records = self.budget.drain_completed_records(self._drain_consumer_id, self.prior_invocation_ids)
        self.completed_delegation_count += len(records)
        return {"citations": _delegation_records_citations(records), "usage": _delegation_records_usage(records)}

    async def _run(self, messages, *, streaming=False, **kwargs):
        if self.prevent_replay and self._invocations and self.budget.attempts:
            raise AgentDelegationError("This agent turn cannot be replayed after a delegated action.")
        self._invocations += 1
        self.last_usage = None
        frame = self._frame()
        kernel = None
        stream = None
        invocation_retry_state = None
        retry_override = self._stream_retry_override
        selected = self.agent
        try:
            with agent_execution(frame):
                frame.budget.raise_authentication_requirement(frame.identity)
                if _has_delegation_tool(selected):
                    from functions_settings import get_settings

                    authorization_context = self.identity.bridge(self.reference) if self.identity.bridge else nullcontext()
                    with authorization_context:
                        current_settings = get_settings()
                        canonical = resolve_delegation_agent(self.reference, user_id=self.identity.user_id, settings=current_settings)
                    frame = replace(frame, caller=canonical, ancestors=(_agent_key(canonical, self.identity.user_id),))
                    invocation_settings = dict(current_settings)
                    # Workflow entrypoints override iteration count, not access
                    # policy. Keep that per-run tuning without retaining old gates.
                    if "max_auto_invoke_attempts" in self.settings:
                        invocation_settings["max_auto_invoke_attempts"] = self.settings["max_auto_invoke_attempts"]
                    with agent_execution(frame):
                        kernel, selected = _build_local_agent(canonical, invocation_settings)
                if retry_override:
                    invocation_retry_state = retry_override[1](selected, retry_override[0])
            if streaming:
                with agent_execution(frame):
                    stream = selected.invoke_stream(messages=messages, **kwargs)
                while True:
                    with agent_execution(frame):
                        try:
                            result = await await_agent_operation(stream.__anext__(), frame)
                        except StopAsyncIteration:
                            break
                    observed_usage = _observed_usage(result)
                    if observed_usage is not None:
                        self.last_usage = observed_usage
                    # A synchronous streaming route resumes this generator in a
                    # new asyncio Task for each token. Never retain a ContextVar
                    # token across the yield.
                    yield result
            else:
                with agent_execution(frame):
                    result = await await_agent_operation(_invoke_local(selected, messages), frame)
                    self.last_usage = _observed_usage(result, kernel or getattr(selected, "kernel", None))
                yield result
        finally:
            with agent_execution(frame):
                try:
                    if stream is not None and hasattr(stream, "aclose"):
                        await stream.aclose()
                finally:
                    if retry_override and invocation_retry_state is not None:
                        retry_override[2](selected, invocation_retry_state)
                    if kernel is not None:
                        self.last_usage = self.last_usage or _observed_usage(kernel=kernel)
                        await close_agent_resources(kernel)

    async def invoke(self, messages, **kwargs):
        stream = self._run(messages, **kwargs)
        try:
            async for result in stream:
                return result
        finally:
            await stream.aclose()

    def invoke_stream(self, messages, **kwargs):
        return self._run(messages, streaming=True, **kwargs)


def prepare_agent_execution(agent, reference, *, user_id, settings, conversation_id=None,
                            cancel_requested=None, budget=None, identity=None, prevent_replay=False):
    if str(getattr(agent, "agent_type", "local") or "local").lower() != "local":
        return agent
    identity = identity or capture_execution_identity(user_id, conversation_id)
    return AgentExecution(agent, reference, identity=identity, settings=settings,
                          cancel_requested=cancel_requested, budget=budget, prevent_replay=prevent_replay)


async def invoke_scoped_agent(reference, task, *, identity, budget, cancel_requested=None):
    """Worker-safe root execution; Flask compatibility belongs to the captured bridge."""
    bridge = identity.bridge(reference) if identity.bridge else nullcontext()
    with bridge:
        canonical = resolve_delegation_agent(reference, user_id=identity.user_id)
    frame = AgentExecutionFrame(
        identity, canonical, budget, ancestors=(_agent_key(canonical, identity.user_id),),
        cancel_requested=cancel_requested,
    )
    with agent_execution(frame):
        return await await_agent_operation(execute_target(canonical, task, "", frame), frame)
