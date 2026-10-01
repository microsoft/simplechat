#!/usr/bin/env python3
# test_workflow_chat_delivery_off_golden.py
"""
Functional test for the workflow results to chat setting-off golden.
Version: 0.261.218
Implemented in: 0.261.218

This test ensures that, with ``enable_chat_workflow_results`` off (the default) and chat
orchestration workflow runs on, starting a saved workflow from chat is byte-identical to the
release before results were posted back to chat. It compares, against a committed golden
fixture captured on the unmodified base (0.261.216, b6172962777f, before any delivery change):

- the step sidecar ``result['workflow_run']`` and the step summary;
- the options the step passes to the durable queue;
- the body of the run document's first write and the stored run document;
- the reply's note, from the real sidecar, for one run, two runs and a stopped plan;
- the answer message's content and metadata.

Never regenerate the fixture to make this test pass. After merging an upstream change to how a
plan starts workflows, regenerate it from the upstream commit itself (without this feature):

    python functional_tests/test_workflow_chat_delivery_off_golden.py --write-golden
"""

import json
import os
import sys
from copy import deepcopy
from difflib import unified_diff
from pathlib import Path

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_run_adapter import (  # noqa: F401
    RUN_ID,
    _signed_in,
    world,
    wr,
)
from test_orchestration_workflow_run_answer import _plan_harness
from test_orchestration_workflow_run_capability import _handle, _run, planning  # noqa: F401
from test_orchestration_workflow_run_planning_context import OWNER, wf  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "workflow_chat_delivery_off_golden.json"
WRITE_ENV = "SIMPLECHAT_WRITE_WORKFLOW_CHAT_DELIVERY_OFF_GOLDEN"
RESULTS_SETTING = "enable_chat_workflow_results"
# The 6a setting is off by default, so it is compared both absent and explicitly off.
SETTING_VARIANTS = {"absent": None, "off": False}
FLOWS = ("answer_and_run", "run_only")
# Values that change on every run. Each is replaced by a placeholder that names it, so the rest of
# the document is compared byte for byte.
VOLATILE_KEYS = frozenset({
    "requested_at", "timestamp", "created_at", "updated_at", "last_updated", "_ts", "_etag",
    "thread_id", "previous_thread_id", "expected_version",
})


def test_version_includes_the_workflow_chat_delivery_off_golden():
    assert_app_version_at_least("0.261.218")


def _pretty(value):
    return json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True)


def _diff(expected, actual, label):
    return "\n".join(unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile=f"golden {label}", tofile=f"actual {label}",
        lineterm="",
    ))


def _normalized(value):
    if isinstance(value, dict):
        return {
            key: (f"<{key}>" if key in VOLATILE_KEYS and item not in (None, "") else _normalized(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _environment(monkeypatch, planning, flow):
    run_step = _run(_handle(planning, "Weekly digest"))
    if flow == "answer_and_run":
        return _plan_harness(
            monkeypatch, planning, [compose_step("answer"), run_step], replies=["Your priorities."],
            final_response=input_binding("answer"),
        )
    return _plan_harness(monkeypatch, planning, [run_step])


def _capture(world, wr, planning, monkeypatch, flow, results_setting):
    created = []
    real_create = world.runs.create_item

    def create_item(body, **kwargs):
        # The body of the run document's first write, before storage adds anything.
        created.append(deepcopy(body))
        return real_create(body, **kwargs)

    monkeypatch.setattr(world.runs, "create_item", create_item)
    env = _environment(monkeypatch, planning, flow)
    if results_setting is not None:
        env.settings[RESULTS_SETTING] = results_setting
    else:
        env.settings.pop(RESULTS_SETTING, None)
    execution = _signed_in(env.prepare())
    decoded_frames(execution.execute(emit=lambda frame: None))
    messages = env.assistant_messages()
    assert len(messages) == 1, messages
    step = env.steps.read_item("run-1:run_digest", "run-1")
    sidecar = step["workflow_run"]
    stored = world.runs.get(OWNER, RUN_ID)
    plan_one = {"steps": [{"step_id": "run_digest", "capability_id": step["capability_id"], "enabled": True}]}
    plan_two = {"steps": [
        *plan_one["steps"], {"step_id": "run_other", "capability_id": step["capability_id"], "enabled": True},
    ]}
    record = {"step_id": "run_digest", "capability_id": step["capability_id"], "status": step["status"],
              "workflow_run": deepcopy(sidecar)}
    other = {**deepcopy(record), "step_id": "run_other",
             "workflow_run": {**deepcopy(sidecar), "step_id": "run_other", "name": "Other digest"}}
    return _normalized({
        "sidecar": sidecar,
        "step_summary": step.get("summary"),
        "queued": world.queued,
        "first_write": created,
        "stored_run": {key: value for key, value in (stored or {}).items() if not key.startswith("_")},
        "notes": {
            "one": wr.workflow_run_note(plan_one, [record]),
            "two": wr.workflow_run_note(plan_two, [record, other]),
            "stopped": wr.workflow_run_note(plan_one, [record], stopped=True),
        },
        "message": messages[0],
    })


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _write_section(flow, captured):
    golden = _load_golden() if GOLDEN.exists() else {}
    golden[flow] = captured
    GOLDEN.write_text(_pretty(golden) + "\n", encoding="utf-8")


@pytest.mark.parametrize("variant", sorted(SETTING_VARIANTS))
@pytest.mark.parametrize("flow", FLOWS)
def test_starting_a_workflow_with_results_in_chat_off_is_byte_identical_to_the_base(
    world, wr, planning, monkeypatch, flow, variant,
):
    captured = _capture(world, wr, planning, monkeypatch, flow, SETTING_VARIANTS[variant])
    if os.environ.get(WRITE_ENV) == "1":
        if variant == "absent":
            _write_section(flow, captured)
        return
    expected = _load_golden()[flow]
    for part in sorted(expected):
        expected_text, actual_text = _pretty(expected[part]), _pretty(captured.get(part))
        assert actual_text == expected_text, _diff(expected_text, actual_text, f"{flow} {part}")
    assert sorted(captured) == sorted(expected)


def test_the_fixture_covers_the_cases_that_matter():
    golden = _load_golden()
    assert sorted(golden) == sorted(FLOWS)
    for flow in FLOWS:
        case = golden[flow]
        assert case["sidecar"]["status"] == "queued" and case["sidecar"]["run_id"] == RUN_ID
        assert "chat_delivery" not in case["sidecar"]
        assert len(case["queued"]) == 1 and "chat_delivery" not in case["queued"][0]
        assert len(case["first_write"]) == 1 and "chat_delivery" not in case["first_write"][0]
        assert "chat_invocation" in case["first_write"][0]
        assert "chat_delivery" not in case["stored_run"]
        assert "post" not in case["notes"]["one"].lower()
        assert case["message"]["content"].endswith(case["notes"]["one"])
        assert "workflow_delivery" not in json.dumps(case["message"])
    assert golden["answer_and_run"]["message"]["content"].startswith("Your priorities.\n\n")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        os.environ[WRITE_ENV] = "1"
        exit_code = pytest.main([__file__, "-q", "-k", "byte_identical_to_the_base and absent"])
        print(f"Wrote {GOLDEN}" if exit_code == 0 else "The golden was not written.")
        sys.exit(exit_code)
    sys.exit(pytest.main([__file__, "-q"]))
