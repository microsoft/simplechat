# Magentic Orchestrator Agent custom implementation. At the time of writing, it only accepts a single ChatMessageContent which can result in a loss of context to the LLM.
# Copyright (c) Microsoft. All rights reserved.

from typing import Any, Callable, Awaitable, Optional
import logging
from functions_appinsights import log_event, get_appinsights_logger
from semantic_kernel.agents.orchestration.magentic import MagenticOrchestration, MagenticManagerBase, MagenticContext
from semantic_kernel.agents.agent import Agent
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent
from semantic_kernel.agents.orchestration.orchestration_base import DefaultTypeAlias, TIn, TOut

class OrchestratorAgent(MagenticOrchestration):
    """
    Custom OrchestratorAgent for advanced multi-agent orchestration.
    - Supports custom agent routing, scratchpad, reflection, DRY fallback, and detailed logging.
    """
    def __init__(
        self,
        members: list[Agent],
        manager: MagenticManagerBase,
        name: str | None = None,
        description: str | None = None,
        input_transform: Callable[[TIn], Awaitable[DefaultTypeAlias] | DefaultTypeAlias] | None = None,
        output_transform: Callable[[DefaultTypeAlias], Awaitable[TOut] | TOut] | None = None,
        agent_response_callback: Callable[[DefaultTypeAlias], Awaitable[None] | None] | None = None,
        streaming_agent_response_callback: Callable[[StreamingChatMessageContent, bool], Awaitable[None] | None] | None = None,
        agent_router: Optional[Callable[[MagenticContext], str]] = None,
        scratchpad: Optional[dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Args:
            agent_router: Optional custom agent routing function (context -> agent_name)
            scratchpad: Optional shared dict for agent/manager state
            logger: Optional logger for detailed orchestration/LLM events
            fallback_chain: Optional list of async callables for DRY fallback
        """
        self.agent_router = agent_router
        self.scratchpad = scratchpad if scratchpad is not None else {}
        # Prefer Application Insights logger if available, else fallback to provided or default logger
        if logger is not None:
            self._logger = logger
        else:
            ai_logger = get_appinsights_logger()
            if ai_logger is not None:
                self._logger = ai_logger
            else:
                self._logger = logging.getLogger("OrchestratorAgent")
        super().__init__(
            members=members,
            manager=manager,
            name=name,
            description=description,
            input_transform=input_transform,
            output_transform=output_transform,
            agent_response_callback=self.agent_response_callback,
            streaming_agent_response_callback=self.streaming_agent_response_callback,
        )

    async def get_available_agents(self) -> list[dict]:
        """
        Return a list of available agent info (name, display_name, description).
        """
        return [
            {
                "name": getattr(agent, "name", None),
                "display_name": getattr(agent, "display_name", None),
                "description": getattr(agent, "description", None),
            }
            for agent in self.members
        ] 

    async def select_next_agent(self, context: MagenticContext) -> str:
        """
        Select the next agent to speak. Uses custom router if provided, else falls back to default.
        """
        if self.agent_router:
            agent_name = self.agent_router(context)
            self._logger.debug(f"[OrchestratorAgentEvent] Custom agent_router selected: {agent_name}")
            return agent_name
        # Default: round-robin or manager logic
        return list(context.participant_descriptions.keys())[context.round_count % len(context.participant_descriptions)]

    def get_scratchpad(self) -> dict[str, Any]:
        """Access the shared scratchpad."""
        return self.scratchpad

    async def reflect(self, context: MagenticContext) -> None:
        """
        Perform a basic reflection: summarize the conversation so far and store in the scratchpad.
        """
        # Try to get the conversation history from context
        history = getattr(context, 'history', None)
        summary = None
        if history and isinstance(history, list):
            # Simple summary: concatenate the last 5 messages (or all if fewer)
            last_msgs = history[-5:] if len(history) > 5 else history
            summary = '\n'.join(str(m) for m in last_msgs)
        else:
            # Fallback: try to get a string representation of context
            summary = str(context)
        self.scratchpad['reflection_summary'] = summary
        self._logger.info(f"[OrchestratorAgentEvent] Reflection summary updated: {summary}")

    def log_agent_event(self, event: str, **kwargs):
        """Log orchestration-level events."""
        self._logger.info(f"[OrchestratorEvent] {event} | {kwargs}")

    def agent_response_callback(self, message: ChatMessageContent) -> None:
        """Observer function to print the messages from the agents."""
        log_event(
            f"**{message.name}**\n{message.content}",
            extra={"agent_name": message.name, "content": message.content},
            level=logging.INFO,
        )
        super().agent_response_callback(message)

    async def streaming_agent_response_callback(self, message: StreamingChatMessageContent, is_final: bool) -> None:
        """
        Observer function to handle streaming responses from agents.
        """
        log_event(
            f"**{message.name}** (streaming)\n{message.content}",
            extra={"agent_name": message.name, "content": message.content},
            level=logging.INFO,
        )
        # If a callback was provided at construction, call it (await if coroutine)
        callback = getattr(self, "_streaming_agent_response_callback", None)
        if callback is not None:
            import asyncio
            if asyncio.iscoroutinefunction(callback):
                await callback(message, is_final)
            else:
                callback(message, is_final)

    # Optionally override SK orchestration hooks to inject logging, scratchpad, etc.
    # For example, override _start, _prepare, or agent/manager actor registration as needed.
    # This allows you to customize the orchestration flow and logging behavior as needed.
    # You can also add more methods for specific orchestration tasks, such as managing agent states,
