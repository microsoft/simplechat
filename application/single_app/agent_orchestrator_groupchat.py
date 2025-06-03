# Copyright (c) Microsoft. All rights reserved.

from typing import Any, Callable, Awaitable, Optional
import logging
import asyncio
from functions_appinsights import log_event, get_appinsights_logger
from semantic_kernel.agents.orchestration.group_chat import GroupChatOrchestration, GroupChatManager, RoundRobinGroupChatManager
from semantic_kernel.agents.agent import Agent
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent
from semantic_kernel.agents.orchestration.orchestration_base import DefaultTypeAlias, TIn, TOut

class OrchestratorAgent(GroupChatOrchestration):
    """
    Custom OrchestratorAgent for advanced multi-agent group chat orchestration.
    - Supports custom agent routing, scratchpad, reflection, DRY fallback, and detailed logging.
    """
    def __init__(
        self,
        members: list[Agent],
        manager: GroupChatManager,
        name: str | None = None,
        description: str | None = None,
        input_transform: Callable[[TIn], Awaitable[DefaultTypeAlias] | DefaultTypeAlias] | None = None,
        output_transform: Callable[[DefaultTypeAlias], Awaitable[TOut] | TOut] | None = None,
        agent_response_callback: Callable[[DefaultTypeAlias], Awaitable[None] | None] | None = None,
        streaming_agent_response_callback: Callable[[StreamingChatMessageContent, bool], Awaitable[None] | None] | None = None,
        agent_router: Optional[Callable[[Any], str]] = None,
        scratchpad: Optional[dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.agent_router = agent_router
        self.scratchpad = scratchpad if scratchpad is not None else {}
        if logger is not None:
            self._logger = logger
        else:
            ai_logger = get_appinsights_logger()
            if ai_logger is not None:
                self._logger = ai_logger
            else:
                self._logger = logging.getLogger()
        # Set agent_response_callback to self.agent_response_callback if not provided
        if agent_response_callback is None:
            agent_response_callback = self.agent_response_callback
        # Only use a user-provided streaming callback; do not assign self.streaming_agent_response_callback to avoid recursion
        self._user_streaming_agent_response_callback = streaming_agent_response_callback
        super().__init__(
            members=members,
            manager=manager,
            name=name,
            description=description,
            input_transform=input_transform,
            output_transform=output_transform,
            agent_response_callback=agent_response_callback,
            streaming_agent_response_callback=self._internal_streaming_agent_response_callback,
        )

    async def _internal_streaming_agent_response_callback(self, message: StreamingChatMessageContent, is_final: bool) -> None:
        await self.streaming_agent_response_callback(message, is_final)


    def log_message_to_agent(self, agent, message):
        """Log every message queued to an agent."""
        log_event(
            "Queueing message for agent",
            extra={
                "agent_name": getattr(agent, "name", None),
                "message": str(message),
            },
            level=logging.INFO,
        )

    async def get_available_agents(self) -> list[dict]:
        return [
            {
                "name": getattr(agent, "name", None),
                "display_name": getattr(agent, "display_name", None),
                "description": getattr(agent, "description", None),
            }
            for agent in self.members
        ]

    def get_scratchpad(self) -> dict[str, Any]:
        return self.scratchpad

    def log_agent_event(self, event: str, **kwargs):
        self._logger.info(f"[OrchestratorEvent] {event} | {kwargs}")

    def agent_response_callback(self, message: ChatMessageContent) -> None:
        # Robust error/type checking and logging for debugging orchestration failures
        try:
            if not isinstance(message, ChatMessageContent):
                log_event(
                    f"[AgentResponseCallback][ERROR] Received non-ChatMessageContent: {type(message)} | {message}",
                    extra={"raw_message": repr(message)},
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )
                self._logger.error(f"[AgentResponseCallback][ERROR] Non-ChatMessageContent received: {type(message)} | {message}")
                return
            # Log every message received from an agent (response)
            log_event(
                f"[AgentResponseCallback] Agent response received {message}",
                extra={
                    "agent_name": getattr(message, "name", None),
                    "content": getattr(message, "content", None),
                    "role": getattr(message, "role", None),
                    "metadata": getattr(message, "metadata", None),
                },
                level=logging.INFO,
            )
            # Optionally, also log to the orchestrator logger
            self._logger.info(f"[AgentResponseCallback] {getattr(message, 'name', None)}: {getattr(message, 'content', None)}")
        except Exception as e:
            log_event(
                f"[AgentResponseCallback][EXCEPTION] Exception in agent_response_callback: {e}",
                extra={"raw_message": repr(message)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            self._logger.exception(f"[AgentResponseCallback][EXCEPTION] Exception in agent_response_callback: {e}")
            return
        # Only call the user-provided callback if it exists and is not this method
        callback = getattr(self, "_user_agent_response_callback", None)
        if callback and callback is not self.agent_response_callback:
            if asyncio.iscoroutinefunction(callback):
                import asyncio
                asyncio.create_task(callback(message))
            else:
                callback(message)

    async def streaming_agent_response_callback(self, message: StreamingChatMessageContent, is_final: bool) -> None:
        """
        Observer function to handle streaming responses from agents.
        Only log to App Insights when the full message is received (is_final is True).
        """
        if is_final:
            log_event(
                f"[StreamingAgentResponseCallback] **{message.name}**\n{message.content}",
                extra={"agent_name": message.name, "content": message.content},
                level=logging.INFO,
            )
        # Only call the user-provided callback if it exists and is not this method
        callback = getattr(self, "_user_streaming_agent_response_callback", None)
        if callback and callback is not self.streaming_agent_response_callback:
            import asyncio
            if asyncio.iscoroutinefunction(callback):
                await callback(message, is_final)
            else:
                callback(message, is_final)

# You can define a custom GroupChatManager or use RoundRobinGroupChatManager
class SCGroupChatManager(RoundRobinGroupChatManager):
    pass
