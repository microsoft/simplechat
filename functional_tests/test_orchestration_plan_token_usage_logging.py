#!/usr/bin/env python3
# test_orchestration_plan_token_usage_logging.py
"""
Functional test for orchestration plan token usage, split by model and logged.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that what an orchestration plan spends is attributed to the models that spent
it (steps can run on different models under Auto routing), that the rows add up to the run's
total, and that a finished run writes one idempotent token usage activity row per model so the
activity logs and Control Center include plans. A run that is only waiting writes nothing, a
reused step is not counted again, and a logging failure never reaches the run.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# The application path is established above, before application imports.
import functions_orchestration_usage as plan_usage  # noqa: E402


def _binding(deployment, label, endpoint="ep-1"):
    return {
        "selection": {
            "model_deployment": deployment, "model_id": f"id-{deployment}",
            "model_endpoint_id": endpoint, "model_provider": "aoai",
        },
        "label": label, "task": "analysis",
    }


PLAN = {
    "steps": [
        {"step_id": "s1", "capability_id": "document_analyze", "model_binding": _binding("gpt-5", "GPT-5")},
        {"step_id": "s2", "capability_id": "tabular_analyze", "model_binding": _binding("gpt-5", "GPT-5")},
        {"step_id": "s3", "capability_id": "compose", "model_binding": _binding("gpt-4o", "GPT-4o")},
        {"step_id": "s4", "capability_id": "agent_invoke"},
        {"step_id": "s5", "capability_id": "document_search"},
        {"step_id": "s6", "capability_id": "document_analyze", "model_binding": _binding("gpt-5", "GPT-5")},
    ],
}
STEPS = [
    {"step_id": "s1", "token_usage": {"prompt_tokens": 100000, "completion_tokens": 2000, "total_tokens": 102000}},
    {"step_id": "s2", "token_usage": {"prompt_tokens": 60000, "completion_tokens": 3000, "total_tokens": 63000}},
    # The record's own binding wins over the plan's when both exist.
    {"step_id": "s3", "model_binding": _binding("gpt-4o-mini", "GPT-4o mini"),
     "token_usage": {"prompt_tokens": 20000, "completion_tokens": 1000, "total_tokens": 21000}},
    {"step_id": "s4", "token_usage": {"prompt_tokens": 5000, "completion_tokens": 500, "total_tokens": 5500}},
    {"step_id": "s5", "token_usage": {}},
    {"step_id": "s6", "reused": True, "token_usage": {}},
    "not a record",
]
TOTAL = {"prompt_tokens": 200000, "completion_tokens": 9000, "total_tokens": 209000}
ANSWER_MODEL = {"model_deployment_name": "gpt-4o", "model_endpoint_id": "ep-1", "model_id": "id-gpt-4o", "model_provider": "aoai"}


def test_usage_is_split_by_model_and_adds_up():
    """Each step counts under its bound model; planning and the answer under the answer model."""
    rows = plan_usage.summarize_plan_usage_by_model(PLAN, STEPS, TOTAL, ANSWER_MODEL)
    assert [row["model"] for row in rows] == ["gpt-5", "gpt-4o", "gpt-4o-mini"]
    by_model = {row["model"]: row for row in rows}
    assert by_model["gpt-5"]["total_tokens"] == 165000
    assert by_model["gpt-5"]["step_count"] == 2
    assert by_model["gpt-5"]["roles"] == ["steps"]
    assert by_model["gpt-5"]["label"] == "GPT-5"
    # The agent step has no binding, so it and the planning remainder fall to the answer model.
    assert by_model["gpt-4o"]["total_tokens"] == 5500 + (209000 - 102000 - 63000 - 21000 - 5500)
    assert by_model["gpt-4o"]["step_count"] == 1
    assert by_model["gpt-4o"]["roles"] == ["steps", "planning_and_answer"]
    assert by_model["gpt-4o-mini"]["total_tokens"] == 21000
    for field in plan_usage.USAGE_FIELDS:
        assert sum(row[field] for row in rows) == TOTAL[field]


def test_plain_plan_and_odd_inputs():
    """A plan without routing is one row; missing or malformed data never raises."""
    rows = plan_usage.summarize_plan_usage_by_model({"steps": []}, [], TOTAL, ANSWER_MODEL)
    assert len(rows) == 1 and rows[0]["model"] == "gpt-4o" and rows[0]["total_tokens"] == 209000
    assert rows[0]["roles"] == ["planning_and_answer"] and rows[0]["step_count"] == 0
    assert plan_usage.summarize_plan_usage_by_model(None, None, None, None) == []
    assert plan_usage.summarize_plan_usage_by_model({}, [], {}, {}) == []
    unknown = plan_usage.summarize_plan_usage_by_model(None, None, {"total_tokens": 10}, None)
    assert unknown[0]["model"] == "unknown"
    # Steps that report more than the run's total never produce a negative remainder.
    over = plan_usage.summarize_plan_usage_by_model(PLAN, STEPS[:1], {"total_tokens": 5}, ANSWER_MODEL)
    assert [row["model"] for row in over] == ["gpt-5"]
    negative = plan_usage.summarize_plan_usage_by_model(
        PLAN, [{"step_id": "s1", "token_usage": {"total_tokens": -5, "prompt_tokens": True}}], TOTAL, ANSWER_MODEL,
    )
    assert [row["model"] for row in negative] == ["gpt-4o"]


def test_public_rows_hide_endpoint_identity():
    """The reply's metadata names models and counts, not endpoint identifiers."""
    rows = plan_usage.summarize_plan_usage_by_model(PLAN, STEPS, TOTAL, ANSWER_MODEL)
    public = plan_usage.public_usage_by_model(rows)
    assert set(public[0]) == {
        "model", "label", "prompt_tokens", "completion_tokens", "total_tokens", "step_count", "roles",
    }
    assert plan_usage.public_usage_by_model(None) == []


def _record(**changes):
    return {
        "id": "run-1", "turn_id": "turn-1", "user_id": "user-1", "conversation_id": "conv-1",
        "attempt_index": 2, "seeds": {"active_group_ids": ["group-9"], "active_public_workspace_ids": []},
        **changes,
    }


def test_finished_run_logs_one_row_per_model():
    """Each model gets a chat token usage row keyed by run and model."""
    rows = plan_usage.summarize_plan_usage_by_model(PLAN, STEPS, TOTAL, ANSWER_MODEL)
    calls = []
    written = plan_usage.log_plan_token_usage(
        _record(), rows, status="completed", message_id="msg-1",
        log_token_usage=lambda **kwargs: calls.append(kwargs),
    )
    assert written == 3 and len(calls) == 3
    first = calls[0]
    assert first["user_id"] == "user-1" and first["token_type"] == "chat"
    assert first["model"] == "gpt-5" and first["total_tokens"] == 165000
    assert first["prompt_tokens"] == 160000 and first["completion_tokens"] == 5000
    assert first["conversation_id"] == "conv-1" and first["message_id"] == "msg-1"
    assert first["workspace_type"] == "group" and first["group_id"] == "group-9"
    assert first["public_workspace_id"] is None
    assert first["additional_context"] == {
        "execution_path": "orchestration", "run_id": "run-1", "turn_id": "turn-1", "attempt_index": 2,
        "run_status": "completed", "model_label": "GPT-5", "model_roles": ["steps"], "step_count": 2,
    }
    keys = [call["idempotency_key"] for call in calls]
    assert keys == [
        "orchestration:run-1:gpt-5:ep-1",
        "orchestration:run-1:gpt-4o:ep-1",
        "orchestration:run-1:gpt-4o-mini:ep-1",
    ]
    assert sum(call["total_tokens"] for call in calls) == TOTAL["total_tokens"]
    # A failed or cancelled run still spent what it spent.
    assert plan_usage.log_plan_token_usage(
        _record(), rows, status="failed", message_id="msg-1", log_token_usage=lambda **kwargs: None,
    ) == 3


def test_workspace_type_follows_the_run():
    rows = plan_usage.summarize_plan_usage_by_model({}, [], TOTAL, ANSWER_MODEL)
    calls = []
    plan_usage.log_plan_token_usage(
        _record(seeds={"active_public_workspace_ids": ["pub-1"], "active_group_ids": ["group-9"]}),
        rows, status="completed", message_id="m", log_token_usage=lambda **kwargs: calls.append(kwargs),
    )
    plan_usage.log_plan_token_usage(
        _record(seeds=None), rows, status="partial", message_id="m",
        log_token_usage=lambda **kwargs: calls.append(kwargs),
    )
    assert calls[0]["workspace_type"] == "public" and calls[0]["public_workspace_id"] == "pub-1"
    assert calls[1]["workspace_type"] == "personal" and calls[1]["group_id"] is None


def test_waiting_runs_and_failures_write_nothing_harmful():
    """A waiting run finalizes again later; a logging failure never reaches the run."""
    rows = plan_usage.summarize_plan_usage_by_model(PLAN, STEPS, TOTAL, ANSWER_MODEL)
    calls = []
    waiting_rows = plan_usage.log_plan_token_usage(
        _record(), rows, status="waiting", message_id="m", log_token_usage=lambda **kwargs: calls.append(kwargs),
    )
    empty_rows = plan_usage.log_plan_token_usage(
        _record(), [], status="completed", message_id="m", log_token_usage=lambda **kwargs: calls.append(kwargs),
    )
    assert waiting_rows == 0 and empty_rows == 0
    assert calls == []

    def broken(**kwargs):
        raise RuntimeError("activity log store unavailable")

    assert plan_usage.log_plan_token_usage(
        _record(), rows, status="completed", message_id="m", log_token_usage=broken,
    ) == 0
    assert plan_usage.log_plan_token_usage(
        {}, rows, status="completed", message_id="m", log_token_usage=lambda **kwargs: None,
    ) == 0


def test_finalize_records_and_logs_usage():
    """The run's finalize step keeps the per-model rows on the reply and logs them once saved."""
    source = (APP / "functions_orchestration_execution.py").read_text(encoding="utf-8")
    assert "summarize_plan_usage_by_model(" in source
    assert 'metadata["usage_by_model"] = public_usage_by_model(usage_rows)' in source
    saved = source.index('"assistant_message_id": message_id, "message_saved": True, "finalization_status": "saved",')
    logged = source.index("log_plan_token_usage(self.record, usage_rows, status=status, message_id=message_id)")
    # Logged only after the reply is durably saved, so a failed publication is never counted.
    assert logged > saved


def test_requests_are_observed_per_model_with_a_peak():
    """Each request notes its model, what it spent and its size; a summed usage sets no peak."""
    observed = {}
    plan_usage.observe_model_request(observed, "gpt-5", {"prompt_tokens": 9000, "completion_tokens": 100, "total_tokens": 9100}, limit=20000)
    plan_usage.observe_model_request(observed, "gpt-5", {"prompt_tokens": 15000, "completion_tokens": 200, "total_tokens": 15200})

    class Usage:
        prompt_tokens, completion_tokens, total_tokens = 4000, 50, 4050

    plan_usage.observe_model_request(observed, "agent-model", Usage(), single_request=False)
    assert observed["gpt-5"]["request_count"] == 2
    assert observed["gpt-5"]["peak_request"] == 15000
    assert observed["gpt-5"]["limit"] == 20000
    assert observed["gpt-5"]["total_tokens"] == 24300
    assert observed["agent-model"]["peak_request"] == 0 and observed["agent-model"]["total_tokens"] == 4050
    # Nothing to note, and nothing raised, for unusable input.
    plan_usage.observe_model_request(observed, "", {"total_tokens": 5})
    plan_usage.observe_model_request(observed, "x", {})
    plan_usage.observe_model_request(None, "x", {"total_tokens": 5})
    plan_usage.observe_model_request(observed, "x", object())
    assert set(observed) == {"gpt-5", "agent-model"}


def test_step_observations_are_deltas_with_a_per_step_peak():
    """A step reports only what happened during it, and its own largest request."""
    prompts, steps = {}, {}
    plan_usage.observe_model_request(prompts, "gpt-5", {"prompt_tokens": 50000, "total_tokens": 50500}, limit=100000)
    before = plan_usage.begin_step_observations(steps, prompts, None)
    # The earlier step's peak does not carry into this one.
    assert prompts["gpt-5"]["peak_request"] == 0
    plan_usage.observe_model_request(prompts, "gpt-5", {"prompt_tokens": 8000, "completion_tokens": 10, "total_tokens": 8010})
    plan_usage.observe_model_request(prompts, "gpt-5", {"prompt_tokens": 30000, "completion_tokens": 20, "total_tokens": 30020})
    plan_usage.observe_model_request(steps, "agent-model", {"prompt_tokens": 700, "total_tokens": 900}, single_request=False)
    rows = plan_usage.end_step_observations(before, steps, prompts, None)
    assert [row["model"] for row in rows] == ["gpt-5", "agent-model"]
    assert rows[0]["total_tokens"] == 38030 and rows[0]["request_count"] == 2
    assert rows[0]["peak_request"] == 30000 and rows[0]["limit"] == 100000
    assert rows[1]["total_tokens"] == 900 and rows[1]["peak_request"] == 0
    # A step that made no request reports nothing.
    idle = plan_usage.begin_step_observations(steps, prompts)
    assert plan_usage.end_step_observations(idle, steps, prompts) == []


def test_step_context_fill_picks_the_fullest_request():
    """The fill is the request that came closest to its own model's limit."""
    fill = plan_usage.step_context_fill([
        {"model": "big", "label": "Big", "peak_request": 90000, "limit": 400000},
        {"model": "small", "label": "Small", "peak_request": 30000, "limit": 32000},
        {"model": "agent", "peak_request": 0},
    ])
    assert fill == {"model": "Small", "peak_request": 30000, "limit": 32000, "percent": 94}
    unknown = plan_usage.step_context_fill([{"model": "custom", "peak_request": 5000, "limit": None}])
    assert unknown == {"model": "custom", "peak_request": 5000, "limit": None, "percent": None}
    over = plan_usage.step_context_fill([{"model": "m", "peak_request": 50000, "limit": 1000}])
    assert over["percent"] == 100
    assert plan_usage.step_context_fill([]) is None
    assert plan_usage.step_context_fill([{"model": "agent", "peak_request": 0}]) is None
    assert plan_usage.step_context_fill(None) is None


def test_agent_steps_count_under_the_agents_own_model():
    """A step that observed its models is split by them; the rest stays with the bound model."""
    steps = [
        {"step_id": "s4", "token_usage": {"prompt_tokens": 5000, "completion_tokens": 500, "total_tokens": 5500},
         "model_usage": [
             {"model": "agent-model", "label": "agent-model", "prompt_tokens": 3000, "completion_tokens": 300, "total_tokens": 3300},
             {"model": "delegate-model", "prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
             {"model": "", "total_tokens": 99},
         ]},
        {"step_id": "s1", "token_usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
         "model_usage": [{"model": "gpt-5", "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}]},
    ]
    total = {"prompt_tokens": 6000, "completion_tokens": 600, "total_tokens": 6600}
    rows = plan_usage.summarize_plan_usage_by_model(PLAN, steps, total, ANSWER_MODEL)
    by_model = {row["model"]: row for row in rows}
    assert by_model["agent-model"]["total_tokens"] == 3300 and by_model["agent-model"]["step_count"] == 1
    assert by_model["delegate-model"]["total_tokens"] == 1100 and by_model["delegate-model"]["step_count"] == 0
    # The step's unobserved remainder (1,100) and the run's planning remainder fall to the answer model.
    assert by_model["gpt-4o"]["total_tokens"] == (5500 - 3300 - 1100) + (6600 - 5500 - 110)
    # The observed model equal to the step's binding keeps the binding's label.
    assert by_model["gpt-5"]["label"] == "GPT-5" and by_model["gpt-5"]["total_tokens"] == 110
    for field in plan_usage.USAGE_FIELDS:
        assert sum(row[field] for row in rows) == total[field]
    # Observations larger than the step's own total are capped, so rows still add up.
    capped = plan_usage.summarize_plan_usage_by_model(
        PLAN, [{"step_id": "s4", "token_usage": {"total_tokens": 10}, "model_usage": [{"model": "agent-model", "total_tokens": 500}]}],
        {"total_tokens": 10}, ANSWER_MODEL,
    )
    assert [(row["model"], row["total_tokens"]) for row in capped] == [("agent-model", 10)]


def test_step_fill_is_recorded_and_shown_without_private_detail():
    """The executor keeps per-model detail on the step; readers get only the fill figures."""
    # The runs module opens the database on import, so the projection is run from its source.
    import ast
    from copy import deepcopy

    runs_source = (APP / "functions_orchestration_runs.py").read_text(encoding="utf-8")
    function = next(
        node for node in ast.parse(runs_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "public_step_record"
    )
    namespace = {"deepcopy": deepcopy, "safe_failure": lambda failure: failure}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "public_step_record", "exec"), namespace)
    public_step_record = namespace["public_step_record"]

    public = public_step_record({
        "step_id": "s1", "status": "completed", "summary": "done", "token_usage": {"total_tokens": 9},
        "model_usage": [{"model": "gpt-5", "total_tokens": 9}],
        "context_fill": {"model": "GPT-5", "peak_request": 9000, "limit": 20000, "percent": 45, "secret": "x"},
    })
    assert public["context_fill"] == {"model": "GPT-5", "peak_request": 9000, "limit": 20000, "percent": 45}
    assert "model_usage" not in public and "token_usage" not in public
    for odd in (None, {}, {"peak_request": 0}, {"peak_request": "9"}, "text"):
        assert "context_fill" not in public_step_record({"step_id": "s", "status": "completed", "context_fill": odd})
    unknown = public_step_record({"step_id": "s", "status": "completed", "context_fill": {"peak_request": 5}})
    assert unknown["context_fill"] == {"model": "", "peak_request": 5, "limit": None, "percent": None}

    executor = (APP / "functions_orchestration_executor.py").read_text(encoding="utf-8")
    assert "observations_before = begin_step_observations(" in executor
    assert "context.step_model_usage = end_step_observations(" in executor
    assert "'model_usage': [] if reused else" in executor
    assert "'context_fill': None if reused else step_context_fill(" in executor
    execution = (APP / "functions_orchestration_execution.py").read_text(encoding="utf-8")
    assert "observations, model.deployment, usage, limit=_request_limit(invoke_prompt)," in execution
    # The notes live on the run context, never inside the usage totals, which hold counts only.
    assert "self.context.model_observations = self.model_observations" in execution
    assert execution.count("observations=self.model_observations,") == 2
    adapters = (APP / "functions_orchestration_adapters.py").read_text(encoding="utf-8")
    assert "observe_model_request(observations, result.get('model'), result.get('usage'), single_request=False)" in adapters
    assert "observe_model_request(observations, record.get('model'), record.get('usage'), single_request=False)" in adapters


def run_all():
    tests = [
        test_requests_are_observed_per_model_with_a_peak,
        test_step_observations_are_deltas_with_a_per_step_peak,
        test_step_context_fill_picks_the_fullest_request,
        test_agent_steps_count_under_the_agents_own_model,
        test_step_fill_is_recorded_and_shown_without_private_detail,
        test_usage_is_split_by_model_and_adds_up,
        test_plain_plan_and_odd_inputs,
        test_public_rows_hide_endpoint_identity,
        test_finished_run_logs_one_row_per_model,
        test_workspace_type_follows_the_run,
        test_waiting_runs_and_failures_write_nothing_harmful,
        test_finalize_records_and_logs_usage,
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
