#!/usr/bin/env python3
# test_token_usage_source_filter.py
"""
Functional test for the token usage source filter and older-message summary usage logging.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that Control Center can tell token usage from ordinary chat, orchestration
plans and workflows apart on both the dashboard and the activity logs, and that the request
which summarizes older messages, which used to discard its usage, is added to usage reporting
as its own record without changing the reply's own count.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# The application path is established above, before application imports.
import functions_control_center_activity as activity  # noqa: E402
import functions_control_center_dashboard as dashboard  # noqa: E402


def test_source_clauses_are_fixed_and_exclusive():
    """Each source has one predicate; unknown input never becomes a filter."""
    plan = dashboard.token_source_clause("plan")
    workflow = dashboard.token_source_clause("workflow")
    chat = dashboard.token_source_clause("chat")
    assert "c.additional_context.execution_path = 'orchestration'" in plan
    assert "c.additional_context.workflow_id" in workflow
    assert "c.additional_context.workflow_result_delivery = true" in workflow
    # Chat is chat-type usage that is neither of the others.
    assert chat == f"(c.token_type = 'chat' AND NOT {plan} AND NOT {workflow})"
    assert dashboard.token_source_clause(" PLAN ") == plan
    for unknown in (None, "", "all", "embedding", "plan' OR 1=1 --", 5, {}):
        assert dashboard.token_source_clause(unknown) == ""
        assert dashboard.normalize_token_source(unknown) is None
    assert [option["value"] for option in dashboard.TOKEN_SOURCE_OPTIONS] == ["chat", "plan", "workflow"]


def test_dashboard_filters_accept_and_apply_a_source():
    """The dashboard reads the source from a query string or a JSON payload and applies it."""
    assert dashboard.extract_token_filters({"token_source": "plan"})["token_source"] == "plan"
    assert dashboard.extract_token_filters({"token_filters": {"token_source": "workflow"}})["token_source"] == "workflow"
    assert dashboard.extract_token_filters({"token_source": "nonsense"})["token_source"] is None
    assert dashboard.extract_token_filters({"model": "gpt-4o"})["token_source"] is None

    conditions, parameters = [], []
    dashboard.append_token_usage_filters(conditions, parameters, {"token_source": "plan", "model": "gpt-4o"})
    assert dashboard.token_source_clause("plan") in conditions
    # The predicate carries no caller-supplied value.
    assert [item["name"] for item in parameters] == ["@token_model"]

    conditions, parameters = [], []
    dashboard.append_token_usage_filters(conditions, parameters, {"token_source": None})
    assert conditions == [] and parameters == []
    # Different sources never share a cached dashboard result.
    assert dashboard._filters_cache_key({"token_source": "plan"}) != dashboard._filters_cache_key({"token_source": "chat"})


def test_activity_logs_accept_and_apply_a_source():
    """The activity logs take the same filter, limited to token usage records."""
    filters = activity.parse_activity_filters({"token_source": "Plan", "date": "2026-11-01"})
    assert filters["token_source"] == "plan"
    where, parameters = activity.activity_query_context(filters)
    assert f"(c.activity_type = 'token_usage' AND {dashboard.token_source_clause('plan')})" in where
    assert all("source" not in item["name"] for item in parameters)

    plain = activity.parse_activity_filters({"date": "2026-11-01"})
    assert plain["token_source"] == ""
    assert "additional_context.execution_path" not in activity.activity_query_context(plain)[0]

    try:
        activity.parse_activity_filters({"token_source": "plan' OR 1=1", "date": "2026-11-01"})
    except ValueError as error:
        assert "token source" in str(error)
    else:
        raise AssertionError("An unknown token source must be refused, not ignored.")


def _load_summary_helpers(calls):
    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    wanted = {"_history_summary_usage", "log_history_summary_usage"}
    functions = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {node.name for node in functions} == wanted
    namespace = {
        "log_token_usage": lambda **kwargs: calls.append(kwargs),
        "debug_print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "summary_helpers", "exec"), namespace)
    return namespace


def test_summary_request_usage_is_read_and_logged():
    """The summary's usage is logged as its own chat record, marked with its purpose."""
    calls = []
    helpers = _load_summary_helpers(calls)
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=900, completion_tokens=80, total_tokens=980))
    usage = helpers["_history_summary_usage"](response, "gpt-4o")
    assert usage == {"prompt_tokens": 900, "completion_tokens": 80, "total_tokens": 980, "model": "gpt-4o"}
    # A provider that omits the total still yields one; no usage at all yields nothing.
    partial = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=None))
    assert helpers["_history_summary_usage"](partial, "m")["total_tokens"] == 15
    assert helpers["_history_summary_usage"](SimpleNamespace(usage=None), "m") is None
    assert helpers["_history_summary_usage"](SimpleNamespace(), "m") is None

    logged = helpers["log_history_summary_usage"](
        {"summary_usage": usage}, user_id="u1", conversation_id="c1", message_id="m1", group_id="g1",
    )
    assert logged is True and len(calls) == 1
    call = calls[0]
    assert call["token_type"] == "chat" and call["model"] == "gpt-4o" and call["total_tokens"] == 980
    assert call["prompt_tokens"] == 900 and call["completion_tokens"] == 80
    assert call["workspace_type"] == "group" and call["group_id"] == "g1"
    assert call["conversation_id"] == "c1" and call["message_id"] == "m1"
    assert call["additional_context"] == {"execution_path": "chat", "purpose": "history_summary"}

    # No summary was made, or nothing was reported: nothing is logged.
    for segments in (None, {}, {"summary_usage": None}, {"summary_usage": {"total_tokens": 0}}, "text"):
        assert helpers["log_history_summary_usage"](segments, user_id="u", conversation_id="c") is False
    assert len(calls) == 1


def test_summary_logging_failure_never_reaches_the_chat():
    def broken(**kwargs):
        raise RuntimeError("activity log store unavailable")

    helpers = _load_summary_helpers([])
    helpers["log_token_usage"] = broken
    assert helpers["log_history_summary_usage"](
        {"summary_usage": {"total_tokens": 5}}, user_id="u", conversation_id="c",
    ) is False


def test_every_summarizing_caller_logs_the_usage():
    """Each chat path that can summarize older messages logs what the summary spent."""
    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    assert "summary_usage = _history_summary_usage(summary_response_older, gpt_model)" in source
    assert "'summary_usage': summary_usage," in source
    summarizing_calls = source.count("enable_summarize_older_messages=enable_summarize_content_history_beyond_conversation_history_limit,")
    assert summarizing_calls == 4
    assert source.count("log_history_summary_usage(\n") + source.count("log_history_summary_usage(\r\n") == summarizing_calls + 1


def run_all():
    tests = [
        test_source_clauses_are_fixed_and_exclusive,
        test_dashboard_filters_accept_and_apply_a_source,
        test_activity_logs_accept_and_apply_a_source,
        test_summary_request_usage_is_read_and_logged,
        test_summary_logging_failure_never_reaches_the_chat,
        test_every_summarizing_caller_logs_the_usage,
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
