#!/usr/bin/env python3
"""
Functional test for synthetic streaming of completed model responses.
Version: 0.261.018
Implemented in: 0.261.018

SimpleChat only supports streaming responses; the non-streaming path is legacy.
Some providers and code paths can only return a completed answer -- notably tool
calling, where a tool call has to arrive whole -- so that answer still has to be
delivered through the stream.

The previous implementation did deliver it through the streaming interface, but
as a single chunk, so the user saw nothing and then everything at once. Because
SimpleChat leans on agents and plugins, that path is common rather than exotic.

These tests ensure that:
  * chunking is lossless, since the frontend accumulates chunks,
  * a completed answer is delivered as several chunks rather than one blob,
  * non-text items such as function calls still arrive whole,
  * the finish reason and usage metadata appear exactly once, on the final chunk,
    so token usage is not multiplied by the number of chunks.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "application",
        "single_app",
    )
)

from test_support.versioning import assert_app_version_at_least

from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.function_call_content import FunctionCallContent
from semantic_kernel.contents.text_content import TextContent
from semantic_kernel.contents.utils.author_role import AuthorRole
from semantic_kernel.contents.utils.finish_reason import FinishReason

from model_endpoint_clients import (
    AnthropicSemanticKernelChatCompletion,
    iter_synthetic_stream_text_chunks,
)


SAMPLE_TEXTS = [
    "Hello world, this is a synthetic stream that should arrive in several pieces.",
    "short",
    "",
    "   leading and trailing   ",
    "line one\nline two\n\nline four",
    "a" * 200,
    "word " * 40,
    "Unicode: caf\u00e9 na\u00efve \u4e2d\u6587 \U0001F600 done",
]


def _build_service():
    return AnthropicSemanticKernelChatCompletion(
        service_id="test",
        deployment_name="claude-opus-5",
        endpoint="https://api.anthropic.com",
        api_key="test-key",
    )


def test_chunking_is_lossless():
    """Concatenating every chunk must reproduce the original text exactly."""
    print("Testing lossless chunking...")
    try:
        for text in SAMPLE_TEXTS:
            chunks = list(iter_synthetic_stream_text_chunks(text))
            rejoined = "".join(chunks)
            assert rejoined == text, (
                f"Chunking lost or altered content.\n  in : {text!r}\n  out: {rejoined!r}"
            )

        # Empty input yields nothing rather than an empty chunk.
        assert list(iter_synthetic_stream_text_chunks("")) == []
        assert list(iter_synthetic_stream_text_chunks(None)) == []

        # A non-positive chunk size must not loop or lose content.
        assert list(iter_synthetic_stream_text_chunks("abc", 0)) == ["abc"]

        print(f"Chunking lossless across {len(SAMPLE_TEXTS)} samples")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_long_answer_is_split_into_several_chunks():
    """A completed answer must not arrive as a single blob."""
    print("Testing multi-chunk delivery...")
    try:
        text = (
            "The answer arrives in several pieces so that it reads like a real "
            "stream rather than appearing all at once after a long pause."
        )
        chunks = list(iter_synthetic_stream_text_chunks(text))
        assert len(chunks) > 1, "A long answer must be split into multiple chunks."
        assert "".join(chunks) == text

        # A short answer stays a single chunk; there is nothing to animate.
        assert len(list(iter_synthetic_stream_text_chunks("ok"))) == 1

        print(f"Long answer split into {len(chunks)} chunks")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_function_calls_survive_synthetic_streaming():
    """Tool calls must arrive whole, on the final chunk."""
    print("Testing function call preservation...")
    try:
        service = _build_service()
        text = "Calling a tool now, after a reasonably long preamble to force chunking."
        message = ChatMessageContent(
            role=AuthorRole.ASSISTANT,
            items=[
                TextContent(text=text),
                FunctionCallContent(id="call-1", name="do_thing", arguments="{}"),
            ],
            finish_reason=FinishReason.TOOL_CALLS,
        )

        streamed = list(service._iter_synthetic_stream_messages(message, 0))
        assert len(streamed) > 1, "Expected the preamble to be chunked."

        function_calls = [
            item
            for streamed_message in streamed
            for item in streamed_message.items
            if isinstance(item, FunctionCallContent)
        ]
        assert len(function_calls) == 1, (
            f"Expected exactly one function call, got {len(function_calls)}"
        )
        assert function_calls[0].name == "do_thing"

        # The function call must ride on the final message, not an earlier one.
        final_items = streamed[-1].items
        assert any(isinstance(item, FunctionCallContent) for item in final_items)

        # The text must still reconstruct exactly.
        assert "".join(str(m) for m in streamed) == text

        print("Function calls preserved on the final chunk")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_finish_reason_and_metadata_appear_once():
    """Usage metadata must not be multiplied by the number of chunks."""
    print("Testing terminal metadata placement...")
    try:
        service = _build_service()
        message = ChatMessageContent(
            role=AuthorRole.ASSISTANT,
            items=[TextContent(text="A long enough answer to be split into chunks here.")],
            finish_reason=FinishReason.STOP,
            metadata={"usage": {"prompt_tokens": 10, "completion_tokens": 20}},
        )

        streamed = list(service._iter_synthetic_stream_messages(message, 0))
        assert len(streamed) > 1, "Expected multiple chunks for this answer."

        finish_reasons = [m.finish_reason for m in streamed]
        assert finish_reasons[-1] == FinishReason.STOP
        assert all(reason is None for reason in finish_reasons[:-1]), (
            f"Finish reason leaked onto non-final chunks: {finish_reasons}"
        )

        carries_usage = [bool(m.metadata) for m in streamed]
        assert carries_usage[-1] is True
        assert not any(carries_usage[:-1]), (
            f"Usage metadata repeated across chunks: {carries_usage}"
        )

        print("Finish reason and usage metadata appear once, on the final chunk")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_stream_options_are_kept_where_supported():
    """stream_options must be dropped only for surfaces that reject it."""
    print("Testing stream_options handling...")
    try:
        from functions_model_endpoint_providers import (
            MODEL_ENDPOINT_API_TYPE_OPENAI,
            get_model_endpoint_provider,
        )

        openai_provider = get_model_endpoint_provider(MODEL_ENDPOINT_API_TYPE_OPENAI)
        assert openai_provider.supports_stream_options is True, (
            "OpenAI accepts stream_options.include_usage, which reports token usage."
        )

        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "application",
            "single_app",
            "model_endpoint_clients.py",
        )
        with open(source_path, encoding="utf-8") as source_file:
            source = source_file.read()
        assert (
            'request_kwargs = dict(kwargs)\n        request_kwargs.pop("stream_options", None)'
            not in source
        ), "stream_options must no longer be dropped unconditionally."
        assert "if not self._supports_stream_options:" in source

        print("stream_options retained where the provider supports it")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """Synthetic streaming ships at or after its implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.018")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_chunking_is_lossless,
        test_long_answer_is_split_into_several_chunks,
        test_function_calls_survive_synthetic_streaming,
        test_finish_reason_and_metadata_appear_once,
        test_stream_options_are_kept_where_supported,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
