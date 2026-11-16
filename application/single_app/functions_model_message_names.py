# functions_model_message_names.py
"""Transport-only author names; saved agent identities are never renamed."""

import hashlib
import re

from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.contents import ChatHistory


def model_message_author_name(name: str) -> str:
    """Keep compatible names, otherwise derive a stable 64-character alias."""
    if len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return name
    digest = hashlib.sha256(name.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"sc_author_{digest[:54]}"


def _request_history(history: ChatHistory) -> ChatHistory:
    messages = []
    for message in history.messages:
        if message.role in {"system", "developer", "user", "assistant"} and message.name is not None:
            name = model_message_author_name(message.name)
            if name != message.name:
                message = message.model_copy(update={"name": name})
        messages.append(message)
    return history.model_copy(update={"messages": messages})


class _MessageNameChatCompletion(ChatCompletionClientBase):
    """Copy author metadata before each provider request, including tool rounds."""

    delegate: ChatCompletionClientBase

    def __getattr__(self, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            delegate = self.__dict__.get("delegate")
            if delegate is None:
                raise
            return getattr(delegate, name)

    def get_prompt_execution_settings_class(self):
        return self.delegate.get_prompt_execution_settings_class()

    def _verify_function_choice_settings(self, settings):
        return self.delegate._verify_function_choice_settings(settings)

    def _update_function_choice_settings_callback(self):
        return self.delegate._update_function_choice_settings_callback()

    def _reset_function_choice_settings(self, settings):
        return self.delegate._reset_function_choice_settings(settings)

    def _prepare_chat_history_for_request(self, chat_history, role_key="role", content_key="content"):
        return self.delegate._prepare_chat_history_for_request(
            _request_history(chat_history), role_key=role_key, content_key=content_key,
        )

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        return await self.delegate._inner_get_chat_message_contents(_request_history(chat_history), settings)

    async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
        async for messages in self.delegate._inner_get_streaming_chat_message_contents(
            _request_history(chat_history), settings, function_invoke_attempt,
        ):
            yield messages


class _FunctionCallingMessageNameChatCompletion(_MessageNameChatCompletion):
    SUPPORTS_FUNCTION_CALLING = True


def wrap_agent_message_names(service: ChatCompletionClientBase) -> ChatCompletionClientBase:
    """Keep the original service/agent identity while guarding its request copies."""
    if isinstance(service, _MessageNameChatCompletion):
        return service
    wrapper = _FunctionCallingMessageNameChatCompletion if service.SUPPORTS_FUNCTION_CALLING else _MessageNameChatCompletion
    return wrapper(
        ai_model_id=service.ai_model_id, service_id=service.service_id,
        instruction_role=service.instruction_role, delegate=service,
    )
