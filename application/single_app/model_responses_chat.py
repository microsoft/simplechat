# model_responses_chat.py
"""Stateless Responses translation for the existing authorized tool loop.

Reasoning items stay private to SDK message objects. They are carried to the
next tool round, never added to public message metadata or provider storage.
"""

from copy import deepcopy
import json

from openai.types.chat import ChatCompletion
from pydantic import PrivateAttr

from functions_model_capabilities import ModelTokenBudgetError
from functions_model_endpoint_validation import ModelEndpointValidationError


class ResponsesChatCompletion(ChatCompletion):
    _responses_items: list[dict] = PrivateAttr(default_factory=list)
    _responses_owner: object = PrivateAttr(default=None)


class ResponsesInputItems(list):
    """Request-owned continuation; a caller's JSON list cannot impersonate it."""


def _message_content(content, role):
    if isinstance(content, str) or content is None:
        return content or ""
    if not isinstance(content, list):
        raise ModelEndpointValidationError("The Responses message content is invalid.")
    converted = []
    for item in content:
        if not isinstance(item, dict):
            raise ModelEndpointValidationError("The Responses message content is invalid.")
        if item.get("type") == "text":
            converted.append({
                "type": "output_text" if role == "assistant" else "input_text",
                "text": item["text"],
            })
        elif item.get("type") == "image_url" and role == "user":
            image = item["image_url"]
            converted.append({
                "type": "input_image",
                "image_url": image["url"] if isinstance(image, dict) else image,
            })
        else:
            raise ModelEndpointValidationError("This message content is not supported by the selected Responses endpoint.")
    return converted


def responses_request(parameters):
    """Translate only supported options; never silently change requested reasoning."""
    values = dict(parameters)
    extra = values.pop("extra_body", None) or {}
    if not isinstance(extra, dict):
        raise ModelEndpointValidationError("Responses request options are invalid.")
    values.update(extra)
    allowed = {
        "model", "messages", "tools", "tool_choice", "parallel_tool_calls",
        "reasoning_effort", "max_tokens", "max_completion_tokens", "max_output_tokens",
        "temperature", "top_p", "response_format", "stream", "stream_options", "user",
    }
    if any(key not in allowed and value is not None for key, value in values.items()):
        raise ModelEndpointValidationError("A configured Chat Completions option is not supported by the selected Responses endpoint.")
    inputs = []
    for message in values.get("messages") or []:
        private_items = message.get("_simplechat_responses_items")
        if private_items is not None:
            if not isinstance(private_items, ResponsesInputItems):
                raise ModelEndpointValidationError("Responses continuation must come from this execution's model output.")
            inputs.extend(deepcopy(private_items))
            continue
        role = message.get("role")
        if role == "tool":
            output = message.get("content", "")
            inputs.append({
                "type": "function_call_output", "call_id": message["tool_call_id"],
                "output": output if isinstance(output, str) else json.dumps(output, allow_nan=False),
            })
            continue
        if role not in {"system", "developer", "user", "assistant"}:
            raise ModelEndpointValidationError("The Responses message role is invalid.")
        content = _message_content(message.get("content"), role)
        if message.get("name"):
            if not isinstance(content, str):
                raise ModelEndpointValidationError("Named multimodal Responses messages are not supported.")
            content = f"{message['name']}:\n{content}"
        if content:
            inputs.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            inputs.append({
                "type": "function_call", "call_id": call["id"],
                "name": call["function"]["name"], "arguments": call["function"]["arguments"],
            })
    request = {
        "model": values["model"], "input": inputs, "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    tools = []
    for tool in values.get("tools") or []:
        if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
            raise ModelEndpointValidationError("This Responses integration supports authorized function tools only.")
        tools.append({"type": "function", **tool["function"]})
    if tools:
        request["tools"] = tools
    choice = values.get("tool_choice")
    if choice is not None:
        request["tool_choice"] = (
            {"type": "function", "name": choice["function"]["name"]}
            if isinstance(choice, dict) and choice.get("type") == "function" else choice
        )
    for field in ("parallel_tool_calls", "temperature", "top_p", "user"):
        if values.get(field) is not None:
            request[field] = values[field]
    if values.get("reasoning_effort") is not None:
        request["reasoning"] = {"effort": values["reasoning_effort"]}
    limit = next((values[field] for field in ("max_output_tokens", "max_completion_tokens", "max_tokens")
                  if values.get(field) is not None), None)
    if limit is not None:
        request["max_output_tokens"] = limit
    response_format = values.get("response_format")
    if response_format:
        if not isinstance(response_format, dict):
            raise ModelEndpointValidationError("The Responses structured-output format is invalid.")
        request["text"] = {"format": (
            {"type": "json_schema", **response_format["json_schema"]}
            if response_format.get("type") == "json_schema" else response_format
        )}
    return request


def responses_completion(response):
    if response.status != "completed":
        raise ModelTokenBudgetError(
            "model_response_incomplete",
            "The model did not complete its response. Review Response Length and the request before retrying.",
        )
    output = [item.model_dump(exclude_none=True) for item in response.output]
    texts, calls = [], []
    for item in output:
        if item["type"] == "function_call":
            calls.append({
                "id": item["call_id"], "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            })
        elif item["type"] == "message":
            texts.extend(
                block.get("text") or block.get("refusal", "")
                for block in item.get("content") or []
                if block.get("type") in {"output_text", "refusal"}
            )
    if not texts and not calls:
        raise ModelEndpointValidationError("The Responses endpoint returned no answer or function calls.")
    usage = None
    if response.usage is not None:
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    completion = ResponsesChatCompletion(
        id=response.id, created=int(response.created_at), model=response.model, object="chat.completion",
        choices=[{
            "index": 0, "finish_reason": "tool_calls" if calls else "stop",
            "message": {"role": "assistant", "content": "".join(texts) or None, "tool_calls": calls or None},
        }],
        usage=usage,
    )
    completion._responses_items = output
    return completion
