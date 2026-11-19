# model_tool_chat_completion.py
"""Apply the selected model's tool policy at the Semantic Kernel SDK boundary."""

from copy import deepcopy
from contextvars import ContextVar
from typing import Literal

from pydantic import Field
from openai import APIError
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.function_call_content import FunctionCallContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent
from semantic_kernel.contents.streaming_text_content import StreamingTextContent
from semantic_kernel.contents.utils.author_role import AuthorRole
from semantic_kernel.contents.utils.finish_reason import FinishReason

from functions_model_budget_runtime import prepare_model_execution_settings
from functions_model_capabilities import ModelTokenBudget, ModelTokenBudgetError, resolve_model_token_budget
from functions_model_endpoint_diagnostics import build_sanitized_model_endpoint_error
from functions_model_endpoint_validation import ModelEndpointValidationError
from model_responses_chat import (
    ResponsesChatCompletion,
    ResponsesInputItems,
    responses_completion,
    responses_request,
    responses_stream_final_response,
    responses_stream_text_delta,
)
from model_endpoint_clients import configure_mai_async_openai_client


_RESPONSE_OWNER = ContextVar("simplechat_responses_owner", default=None)


def _response_history_owner(chat_history):
    return next(
        (message for message in reversed(chat_history.messages) if message.role == AuthorRole.USER),
        chat_history,
    )


class _ModelToolPolicy:
    def __init__(self, *, model_token_budget=None, tool_provider=None, inference_api="chat_completions", **kwargs):
        super().__init__(**kwargs)
        self.model_token_budget = model_token_budget
        self.inference_api = inference_api
        if tool_provider is not None:
            self.tool_provider = tool_provider
        configure_mai_async_openai_client(
            self.client,
            model_name=model_token_budget.model_id if model_token_budget else self.ai_model_id,
        )

    def _prepare_chat_history_for_request(self, chat_history, **kwargs):
        if self.inference_api != "responses":
            return super()._prepare_chat_history_for_request(chat_history, **kwargs)
        messages = []
        owner = _response_history_owner(chat_history)
        for message in chat_history.messages:
            prepared = super()._prepare_chat_history_for_request(ChatHistory(messages=[message]), **kwargs)
            inner = message.inner_content
            if isinstance(inner, list):
                inner = next((value for value in reversed(inner) if isinstance(value, ResponsesChatCompletion)), None)
            if isinstance(inner, ResponsesChatCompletion) and inner._responses_owner is owner and prepared:
                prepared[0]["_simplechat_responses_items"] = ResponsesInputItems(deepcopy(inner._responses_items))
            messages.extend(prepared)
        return messages

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        if self.inference_api != "responses":
            return await super()._inner_get_chat_message_contents(chat_history, settings)
        token = _RESPONSE_OWNER.set(_response_history_owner(chat_history))
        try:
            return await super()._inner_get_chat_message_contents(chat_history, settings)
        finally:
            _RESPONSE_OWNER.reset(token)

    async def _send_request(self, settings):
        requested_model = getattr(settings, "ai_model_id", None)
        if requested_model and requested_model != self.ai_model_id:
            raise ModelTokenBudgetError("model_context_invalid", "Select the requested model instead of overriding this service's bound deployment.")
        budget = self.model_token_budget or resolve_model_token_budget(
            self.ai_model_id, provider=self.tool_provider, protocol=self.inference_api,
        )
        if budget.protocol != self.inference_api:
            raise ModelTokenBudgetError("model_context_invalid", "The model policy does not match the selected inference API.")
        prepared, _ = prepare_model_execution_settings(
            settings, budget, tools_enabled=bool(getattr(settings, "tools", None)),
        )
        if self.inference_api == "responses":
            parameters = prepared.prepare_settings_dict()
            parameters["model"] = self.ai_model_id
            parameters["messages"] = prepared.messages
            safe_error = None
            try:
                response = await self.client.responses.create(**responses_request(parameters))
            except APIError as error:
                safe_error = build_sanitized_model_endpoint_error(
                    "The selected Responses endpoint could not complete the request.",
                    error, api_type="openai", protocol="responses", request_url=str(self.client.base_url),
                    status_code=getattr(error, "status_code", None),
                )
                safe_error.status_code = getattr(error, "status_code", None)
            if safe_error is not None:
                raise safe_error from None
            completion = responses_completion(response)
            completion._responses_owner = _RESPONSE_OWNER.get()
            return completion
        return await super()._send_request(prepared)

    async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
        if self.inference_api != "responses":
            async for result in super()._inner_get_streaming_chat_message_contents(
                chat_history, settings, function_invoke_attempt,
            ):
                yield result
            return
        if not isinstance(settings, OpenAIChatPromptExecutionSettings):
            settings = self.get_prompt_execution_settings_from_settings(settings)
        settings.stream = True
        settings.messages = self._prepare_chat_history_for_request(chat_history)
        settings.ai_model_id = settings.ai_model_id or self.ai_model_id

        budget = self.model_token_budget or resolve_model_token_budget(
            self.ai_model_id, provider=self.tool_provider, protocol=self.inference_api
        )
        if budget.protocol != self.inference_api:
            raise ModelTokenBudgetError(
                "model_context_invalid",
                "The model policy does not match the selected inference API.",
            )
        prepared, _ = prepare_model_execution_settings(
            settings,
            budget,
            tools_enabled=bool(getattr(settings, "tools", None)),
        )
        parameters = prepared.prepare_settings_dict()
        parameters["model"] = self.ai_model_id
        parameters["messages"] = prepared.messages
        request = responses_request(parameters)
        request["stream"] = True
        owner = _response_history_owner(chat_history)
        stream = None
        completed = False
        try:
            stream = await self.client.responses.create(**request)
            if not hasattr(stream, "__aiter__"):
                completion = responses_completion(stream)
                completion._responses_owner = owner
                choice = completion.choices[0]
                message_items = []
                if choice.message.content:
                    message_items.append(StreamingTextContent(
                        choice_index=0,
                        text=choice.message.content,
                        ai_model_id=self.ai_model_id,
                        inner_content=completion,
                    ))
                for index, call in enumerate(choice.message.tool_calls or []):
                    message_items.append(FunctionCallContent(
                        id=call.id,
                        call_id=call.id,
                        index=index,
                        name=call.function.name,
                        arguments=call.function.arguments,
                    ))
                usage = (
                    completion.usage.model_dump(exclude_none=True)
                    if completion.usage is not None
                    else None
                )
                yield [StreamingChatMessageContent(
                    role=AuthorRole.ASSISTANT,
                    choice_index=0,
                    items=message_items,
                    inner_content=completion,
                    ai_model_id=self.ai_model_id,
                    metadata={"usage": usage} if usage is not None else {},
                    finish_reason=(
                        FinishReason.TOOL_CALLS
                        if choice.finish_reason == "tool_calls"
                        else FinishReason.STOP
                    ),
                    function_invoke_attempt=function_invoke_attempt,
                )]
                completed = True
            else:
                async for event in stream:
                    delta = responses_stream_text_delta(event)
                    if delta:
                        yield [StreamingChatMessageContent(
                            role=AuthorRole.ASSISTANT,
                            choice_index=0,
                            items=[StreamingTextContent(
                                choice_index=0,
                                text=delta,
                                ai_model_id=self.ai_model_id,
                                inner_content=event,
                            )],
                            inner_content=event,
                            ai_model_id=self.ai_model_id,
                            function_invoke_attempt=function_invoke_attempt,
                        )]
                        continue

                    response = responses_stream_final_response(event)
                    if response is None:
                        continue
                    completion = responses_completion(response)
                    completion._responses_owner = owner
                    choice = completion.choices[0]
                    function_calls = []
                    for index, call in enumerate(choice.message.tool_calls or []):
                        function_calls.append(FunctionCallContent(
                            id=call.id,
                            call_id=call.id,
                            index=index,
                            name=call.function.name,
                            arguments=call.function.arguments,
                        ))
                    usage = (
                        completion.usage.model_dump(exclude_none=True)
                        if completion.usage is not None
                        else None
                    )
                    finish_reason = (
                        FinishReason.TOOL_CALLS
                        if choice.finish_reason == "tool_calls"
                        else FinishReason.STOP
                    )
                    yield [StreamingChatMessageContent(
                        role=AuthorRole.ASSISTANT,
                        choice_index=0,
                        items=function_calls,
                        inner_content=completion,
                        metadata={"usage": usage} if usage is not None else {},
                        finish_reason=finish_reason,
                        ai_model_id=self.ai_model_id,
                        function_invoke_attempt=function_invoke_attempt,
                    )]
                    completed = True
                    break
            if not completed:
                raise ModelEndpointValidationError(
                    "The Responses stream ended before a terminal event."
                )
        except APIError as error:
            safe_error = build_sanitized_model_endpoint_error(
                "The selected Responses endpoint could not complete the request.",
                error,
                api_type="openai",
                protocol="responses",
                request_url=str(self.client.base_url),
                status_code=getattr(error, "status_code", None),
            )
            safe_error.status_code = getattr(error, "status_code", None)
            raise safe_error from None
        finally:
            close = getattr(stream, "close", None)
            if hasattr(stream, "__aiter__") and callable(close):
                await close()


class AzureToolChatCompletion(_ModelToolPolicy, AzureChatCompletion):
    model_token_budget: ModelTokenBudget | None = Field(default=None, exclude=True)
    tool_provider: str = "azure"
    inference_api: Literal["chat_completions", "responses"] = "chat_completions"


class OpenAIToolChatCompletion(_ModelToolPolicy, OpenAIChatCompletion):
    model_token_budget: ModelTokenBudget | None = Field(default=None, exclude=True)
    tool_provider: str = "openai"
    inference_api: Literal["chat_completions", "responses"] = "chat_completions"
