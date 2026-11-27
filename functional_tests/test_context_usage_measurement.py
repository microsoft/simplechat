#!/usr/bin/env python3
# test_context_usage_measurement.py
"""
Functional test for chat context usage measurement.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that the request a chat sends to the model is sized by where its text came
from (messages, summary, attached files, workspace results, memory, instructions), that the
selected model's limits are resolved into the ceiling the display measures against, and that
the chat route records the measurement on every path that calls the model.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# The application path is established above, before application imports.
import functions_context_usage as context_usage  # noqa: E402
from functions_conversation_context import CONVERSATION_CONTEXT_START_MARKER  # noqa: E402


def _request():
    return [
        {"role": "system", "content": "<Summary of previous conversation context>\nEarlier talk.\n</Summary of previous conversation context>"},
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "system", "content": "Use these excerpts.", "documents": [{"id": "d1"}]},
        {"role": "system", "content": "Retrieved saved facts.\n<Fact Memory>\n- Likes tables\n</Fact Memory>"},
        {"role": "system", "content": "[User uploaded a file named 'Q3-forecast.xlsx'. Content preview:\n" + "row,value\n" * 200 + "]\nUse this file context if relevant."},
        {"role": "system", "content": "[User uploaded an image named 'chart.png'.]"},
        {"role": "system", "content": "Web search results (news):\nRates held steady.\n\nSources (cite by number as markdown links):\n[1] Example - https://example.com"},
        {"role": "system", "content": "[SOURCE_REVIEW_EVIDENCE]\n{}\n[/Source Review Evidence]"},
        {"role": "system", "content": "[Assistant generated an image based on the prompt: 'a chart']"},
        {"role": "user", "content": "Compare the forecast with last quarter."},
        {"role": "assistant", "content": "Revenue is tracking above last quarter."},
        {"role": "user", "content": f"{CONVERSATION_CONTEXT_START_MARKER}{{}}</conversation_context_reference>"},
        {"role": "user", "content": "Which renewals?"},
    ]


def test_messages_are_classified_by_source():
    """Each message of the request lands in the category the display names."""
    categories = [context_usage.classify_context_message(message) for message in _request()]
    assert categories == [
        ("summary", ""),
        ("instructions", ""),
        ("search", ""),
        ("memory", ""),
        ("files", "Q3-forecast.xlsx"),
        ("files", "chart.png"),
        ("web", ""),
        ("web", ""),
        ("messages", ""),
        ("messages", ""),
        ("messages", ""),
        ("instructions", ""),
        ("messages", ""),
    ]
    assert context_usage.classify_context_message(None) == ("instructions", "")
    assert context_usage.classify_context_message({"role": "tool", "content": "x"}) == ("instructions", "")


def test_measurement_totals_and_items():
    """Category sizes add up to the total and files are itemized, largest first."""
    result = context_usage.measure_context_usage(_request(), model_name="gpt-4o")
    assert result["version"] == context_usage.CONTEXT_USAGE_VERSION
    assert result["message_count"] == 13
    assert sum(result["categories"].values()) == result["estimated_total"]
    assert set(result["categories"]) == {"messages", "summary", "files", "search", "web", "memory", "instructions"}
    assert result["counts"]["messages"] == 4
    assert result["counts"]["web"] == 2
    assert result["counts"]["files"] == 2
    assert [item["label"] for item in result["items"]] == ["Q3-forecast.xlsx", "chart.png"]
    assert result["items"][0]["size"] > result["items"][1]["size"]
    assert result["categories"]["files"] > result["categories"]["messages"]
    # Serializers treat field names containing these words as credentials.
    flattened = repr(sorted(result)) + repr(sorted(result["limits"])) + repr(result["items"][0].keys())
    assert "token" not in flattened and "key" not in flattened.replace("dict_keys", "")


def test_measurement_survives_odd_shapes():
    """Multimodal parts, missing content and non-dict entries never raise."""
    result = context_usage.measure_context_usage(
        [
            None,
            "text",
            {"role": "user", "content": [{"type": "text", "text": "Describe this"}, {"type": "image_url", "image_url": {"url": "data:..."}}]},
            {"role": "assistant", "content": None},
            {"role": "assistant"},
        ],
        model_name="unknown-deployment",
    )
    assert result["message_count"] == 3
    assert result["categories"] == {"messages": result["estimated_total"]}
    assert context_usage.measure_context_usage(None)["estimated_total"] == 0


def test_character_fallback_when_no_vocabulary():
    """Without a tokenizer vocabulary the size is an explicit character estimate, cached."""
    original = context_usage.tiktoken.get_encoding
    calls = []

    def unavailable(name):
        calls.append(name)
        raise OSError("vocabulary host unreachable")

    context_usage.reset_context_usage_encoding_cache()
    context_usage.tiktoken.get_encoding = unavailable
    try:
        first = context_usage.measure_context_usage([{"role": "user", "content": "abcdefgh"}], model_name="gpt-4o")
        context_usage.measure_context_usage([{"role": "user", "content": "abcdefgh"}], model_name="gpt-4o")
    finally:
        context_usage.tiktoken.get_encoding = original
        context_usage.reset_context_usage_encoding_cache()
    assert first["estimator"] == context_usage.ESTIMATOR_CHARACTERS
    assert first["estimated_total"] == 2 + context_usage.PER_MESSAGE_OVERHEAD
    # The failure is remembered: an unreachable host is not retried on every request.
    assert len(calls) == 1


def test_limits_resolve_to_an_input_ceiling():
    """The ceiling is the window less the reply allowance, capped by the input limit."""
    record = {"deploymentName": "custom-name", "contextWindow": 10000, "outputTokenLimit": 2000}
    assert context_usage.resolve_context_limits(record) == {
        "window": 10000, "input_limit": None, "reply_reserve": 2000, "input_ceiling": 8000,
    }
    assert context_usage.resolve_context_limits(record, response_length=500)["input_ceiling"] == 9500
    capped = context_usage.resolve_context_limits({**record, "inputTokenLimit": 6000})
    assert capped["input_ceiling"] == 6000
    # A reply allowance as large as the window cannot be subtracted from it.
    whole = context_usage.resolve_context_limits({"deploymentName": "x", "contextWindow": 4000, "outputTokenLimit": 4000})
    assert whole["input_ceiling"] == 4000 and whole["reply_reserve"] is None
    # Unknown models and invalid configuration yield no limits rather than a guess or an error.
    assert context_usage.resolve_context_limits("no-such-deployment-name") == {}
    assert context_usage.resolve_context_limits({"deploymentName": "x", "contextWindow": -5}) == {}
    assert context_usage.resolve_context_limits(record, response_length="abc")["reply_reserve"] == 2000


def test_model_catalog_carries_each_models_limits():
    """Every selectable model sends its limits, so the ring can re-base the moment one is picked."""
    source = (APP / "functions_chat_model_catalog.py").read_text(encoding="utf-8")
    assert "from functions_context_usage import resolve_context_limits" in source
    # Both the single-endpoint and the multi-endpoint catalogs carry them.
    assert source.count("'context_limits': resolve_context_limits(") == 2
    assert "model, endpoint, provider=provider, response_length=model.get('responseLength')," in source
    # The limits hold sizes only: nothing a settings sanitizer would need to strip.
    limits = context_usage.resolve_context_limits({"deploymentName": "x", "contextWindow": 10000, "outputTokenLimit": 2000})
    assert set(limits) == {"window", "input_limit", "reply_reserve", "input_ceiling"}
    assert all(value is None or type(value) is int for value in limits.values())


def test_limits_are_reused_from_model_resolution_not_looked_up_again():
    """The request resolves its model once; the display reuses those limits and reads nothing."""
    import ast

    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_chat_context_limits"
    )
    helper_source = ast.get_source_segment(source, helper)
    # No endpoint, user settings, governance or group lookup happens for the display.
    for lookup in ("get_streaming_model_endpoint_candidates", "get_user_settings", "ensure_governance_access", "cosmos"):
        assert lookup not in helper_source

    calls = []

    def fake_resolve(model, endpoint=None, *, provider=None, response_length=None):
        calls.append((model, endpoint, provider, response_length))
        return {"input_ceiling": 1}

    namespace = {"resolve_context_limits": fake_resolve, "debug_print": lambda *args, **kwargs: None}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "limits_helper", "exec"), namespace)
    resolve = namespace["_resolve_chat_context_limits"]

    # Limits worked out during model resolution are returned as they are, including "unknown".
    resolved = {"window": 128000, "input_ceiling": 112000}
    assert resolve({}, "gpt-4o", "aoai", None, resolved) is resolved
    assert resolve({}, "custom", "custom", None, {}) == {}
    assert calls == []
    # Without them the model is one of the application's own deployments, found in loaded settings.
    record = {"deploymentName": "gpt-4o", "contextWindow": 5000}
    settings = {"gpt_model": {"selected": [{"deploymentName": "other"}, record]}}
    assert resolve(settings, "gpt-4o", None, 800) == {"input_ceiling": 1}
    assert calls == [(record, None, "aoai", 800)]
    resolve({}, "apim-deployment", "aoai", None)
    assert calls[-1] == ("apim-deployment", None, "aoai", None)
    # Malformed settings never stop a chat request.
    resolve({"gpt_model": {"selected": [None]}}, "gpt-4o", "aoai", None)
    assert calls[-1][0] == "gpt-4o"

    # Model resolution leaves the limits for its caller, which takes them straight back out.
    assert "data[CONTEXT_LIMITS_REQUEST_FIELD] = resolve_context_limits(" in source
    assert "model_cfg, resolved_endpoint_cfg, provider=provider, response_length=model_response_length," in source
    assert source.count("chat_context_limits = data.pop(CONTEXT_LIMITS_REQUEST_FIELD, None)") == 2
    assert source.count("settings, gpt_model, gpt_provider, gpt_response_length, chat_context_limits,") == 4


def test_chat_route_records_usage_on_every_model_path():
    """Every call that prepares a request passes the reply's history details to be filled in."""
    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    assert "from functions_context_usage import measure_context_usage, resolve_context_limits" in source
    calls = source.count("= _prepare_conversation_context_for_invocation(")
    assert calls >= 4
    assert source.count("history_debug_info=history_debug_info,") == calls
    assert source.count("context_limits=lambda: _resolve_chat_context_limits(") == calls
    assert "history_debug_info['context_usage'] = measure_context_usage(" in source
    # The measurement rides on the history details every saved reply already stores.
    assert source.count("'history_context': history_debug_info") >= 4


def run_all():
    tests = [
        test_messages_are_classified_by_source,
        test_measurement_totals_and_items,
        test_measurement_survives_odd_shapes,
        test_character_fallback_when_no_vocabulary,
        test_limits_resolve_to_an_input_ceiling,
        test_model_catalog_carries_each_models_limits,
        test_limits_are_reused_from_model_resolution_not_looked_up_again,
        test_chat_route_records_usage_on_every_model_path,
    ]
    for test in tests:
        print(f"Testing {test.__name__}...")
        try:
            test()
            print("Test passed!")
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback
            traceback.print_exc()
            return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
