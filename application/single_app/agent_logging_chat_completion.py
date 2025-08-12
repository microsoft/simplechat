
from pydantic import Field
from semantic_kernel.agents import ChatCompletionAgent
from functions_appinsights import log_event


class LoggingChatCompletionAgent(ChatCompletionAgent):
    display_name: str | None = Field(default=None)
    default_agent: bool = Field(default=False)

    def __init__(self, *args, display_name=None, default_agent=False, **kwargs):
        # Remove these from kwargs so the base class doesn't see them
        kwargs.pop('display_name', None)
        kwargs.pop('default_agent', None)
        super().__init__(*args, **kwargs)
        self.display_name = display_name
        self.default_agent = default_agent

    async def invoke(self, *args, **kwargs):
        # Log the prompt/messages before sending to LLM
        log_event(
            "[Logging Agent Request] Agent LLM prompt",
            extra={
                "agent": self.name,
                "prompt": [m.content[:30] for m in args[0]] if args else None
            }
        )
        response = None
        try:
            result = super().invoke(*args, **kwargs)
            if hasattr(result, "__aiter__"):
                # Streaming/async generator response
                response_chunks = []
                async for chunk in result:
                    response_chunks.append(chunk)
                response = response_chunks[-1] if response_chunks else None
            else:
                # Regular coroutine response
                response = await result
            return response
        finally:
            usage = getattr(response, "usage", None)
            log_event(
                "[Logging Agent Response][Usage] Agent LLM response",
                extra={
                    "agent": self.name,
                    "response": str(response)[:100] if response else None,
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                    "usage": str(usage) if usage else None,
                }
            )
        