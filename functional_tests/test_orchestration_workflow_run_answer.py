#!/usr/bin/env python3
# test_orchestration_workflow_run_answer.py
"""
Functional test for the chat orchestration reply about the saved workflows a plan started.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that the reply to a plan with workflow_run steps says, in deterministic
application-owned text after the prepared answer, which saved workflows started, which were
already started for the request and which were not started and why, including the ones the
planner left out. It says where each run's progress and results appear, never promises to post
them back to the chat, never waits for or reads the run, and never shows a workflow or run id.
Saved names are shown as inline code, so a name cannot add links, formatting or lines to the
reply. A plan the user stopped still says which workflows it had already started, and a stop
between starting a run and saving its step is left to the failure explanation and recovery.
"""

import importlib
import json
import re
from datetime import datetime, timezone

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_run_adapter import (  # noqa: F401
    RUN_ID,
    _harness,
    _signed_in,
    world,
    wr,
)
from test_orchestration_workflow_run_approval_floor import CONVERSATION
from test_orchestration_workflow_run_capability import WORKFLOW_RUN, _handle, _run, planning  # noqa: F401
from test_orchestration_workflow_run_planning_context import DIGEST_ID, NOT_DURABLE_ID, OWNER, RUN_SETTINGS, wf  # noqa: F401
from test_support.orchestration_harness_execution import (
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least


HEADING = "Saved workflows:"
FOLLOW_ONE = (
    "Follow the run's progress and results in the workflow's run history in Workflows. Results also "
    "appear wherever the workflow already sends them, such as its conversation or alerts."
)
FOLLOW_MANY = (
    "Follow each run's progress and results in that workflow's run history in Workflows. Results also "
    "appear wherever each workflow already sends them, such as its conversation or alerts."
)
STOPPED = (
    "Stopping this plan doesn't stop a workflow it already started. Cancel the run in Workflows if "
    "you need to."
)
STARTED_NOTE = f"{HEADING}\n- Started `Weekly digest`.\n\n{FOLLOW_ONE}"
HOSTILE = 'Digest `x`\n# Hi <img src=x onerror="alert(1)"> [link](https://evil.example/)'
# Phrases a reply would use to promise results in this chat, which only a later phase delivers.
POST_BACK = re.compile(r"\b(post|posted|posts|posting|here|this chat|this conversation|notify|notified)\b", re.I)


def test_the_version_includes_the_workflow_run_reply():
    assert_app_version_at_least("0.261.212")


# ---------------------------------------------------------------------------
# The note, from the run's step records and the plan
# ---------------------------------------------------------------------------

def _sidecar(status, *, name="Weekly digest", reason=None, step_id="run_digest", workflow_id=DIGEST_ID):
    return {
        "version": 1, "step_id": step_id, "orchestration_run_id": "run-1", "attempt_root_run_id": "run-1",
        "conversation_id": CONVERSATION, "requested_by": OWNER, "handle": "wf-secret-handle",
        "workflow_id": workflow_id, "run_id": None if status == "unavailable" else RUN_ID,
        "name": name, "status": status, "reason": reason,
    }


def _record(step_id="run_digest", status="completed", sidecar=None, capability_id=WORKFLOW_RUN):
    record = {"step_id": step_id, "capability_id": capability_id, "status": status}
    if sidecar is not None:
        record["workflow_run"] = sidecar
    return record


def _plan(*step_ids, disabled=(), notes=None):
    plan = {"steps": [
        {"step_id": step_id, "capability_id": WORKFLOW_RUN, "enabled": step_id not in disabled}
        for step_id in step_ids
    ]}
    if notes is not None:
        plan["workflow_run_notes"] = notes
    return plan


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_started_workflow_is_named_with_where_to_follow_it(wr, status):
    note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar(status))])
    assert note == STARTED_NOTE


def test_a_run_this_request_already_started_is_not_described_as_a_new_start(wr):
    note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("already_started"))])
    assert note == (
        f"{HEADING}\n- `Weekly digest` was already started for this request, so it was not started again."
        f"\n\n{FOLLOW_ONE}"
    )


def test_every_reason_a_workflow_was_not_started_is_explained_in_application_text(wr):
    for reason, text in wr.WORKFLOW_RUN_REASON_TEXT.items():
        note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("unavailable", reason=reason))])
        assert note == f"{HEADING}\n- `Weekly digest` was not started. {text}", reason
    # A damaged stored record can hold any JSON value as its reason, including one that cannot be a key.
    for reason in (None, "a_reason_added_later", 7, ["workflow_deleted"], {"code": "workflow_deleted"}):
        note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("unavailable", reason=reason))])
        assert note == f"{HEADING}\n- `Weekly digest` was not started. {wr.WORKFLOW_RUN_REASON_TEXT['workflow_run_not_started']}"


def test_a_workflow_the_planner_left_out_is_explained_after_the_ones_that_ran(wr):
    notes = [
        {"reason": "workflow_not_durable", "name": "Contract watcher"},
        {"reason": "workflow_run_limit", "name": None},
        {"reason": "a_reason_added_later", "name": "Filler workflow 03"},
        {"reason": "workflow_run_duplicate", "name": "Weekly digest"},
        {"reason": "workflow_not_durable", "name": "Contract watcher"},
        "not a note",
        {"reason": "workflow_run_limit", "name": "   "},
    ]
    note = wr.workflow_run_note(_plan("run_digest", notes=notes), [_record(sidecar=_sidecar("queued"))])
    skip = wr.WORKFLOW_RUN_SKIP_REASONS
    assert note == "\n".join([
        HEADING,
        "- Started `Weekly digest`.",
        f"- `Contract watcher` was not started. {skip['workflow_not_durable']}",
        f"- A workflow you asked for was not started. {skip['workflow_run_limit']}",
        f"- `Filler workflow 03` was not started. {skip['workflow_run_invalid']}",
    ]) + f"\n\n{FOLLOW_ONE}"

    # A plan whose only workflow was left out still says so, without pointing to a run.
    left_out = wr.workflow_run_note({"steps": [], "workflow_run_notes": notes[:1]}, [])
    assert left_out == f"{HEADING}\n- `Contract watcher` was not started. {skip['workflow_not_durable']}"


def test_each_started_run_is_listed_in_plan_order(wr):
    plan = _plan("run_digest", "run_filler", "run_watcher")
    records = [
        _record("run_watcher", sidecar=_sidecar(
            "unavailable", name="Contract watcher", reason="workflow_not_durable", step_id="run_watcher",
        )),
        _record("run_filler", sidecar=_sidecar("already_started", name="Filler workflow 03", step_id="run_filler")),
        _record("run_digest", sidecar=_sidecar("running")),
    ]
    note = wr.workflow_run_note(plan, records)
    assert note == "\n".join([
        HEADING,
        "- Started `Weekly digest`.",
        "- `Filler workflow 03` was already started for this request, so it was not started again.",
        f"- `Contract watcher` was not started. {wr.WORKFLOW_RUN_REASON_TEXT['workflow_not_durable']}",
    ]) + f"\n\n{FOLLOW_MANY}"


def test_steps_that_did_not_finish_are_left_to_the_failure_explanation(wr):
    started = _sidecar("queued")
    cases = [
        (_plan("run_digest"), []),
        (_plan("run_digest"), [_record(status="failed")]),
        (_plan("run_digest"), [_record(status="cancelled")]),
        (_plan("run_digest"), [_record(status="failed", sidecar=started)]),
        (_plan("run_digest", disabled={"run_digest"}), [_record(sidecar=started)]),
        (_plan("run_digest"), [_record(sidecar={**started, "status": "finished"})]),
        (_plan("run_digest"), [_record(sidecar="queued")]),
        (_plan("run_digest"), [_record(capability_id="compose", sidecar=started)]),
        ({"steps": [{"step_id": "run_digest", "capability_id": "compose"}]}, [_record(sidecar=started)]),
        (None, None),
        ({"steps": "not steps", "workflow_run_notes": "not notes"}, "not records"),
    ]
    for plan, records in cases:
        assert wr.workflow_run_note(plan, records) == "", (plan, records)


def test_a_saved_name_is_inline_code_that_cannot_format_the_reply(wr):
    note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("queued", name=HOSTILE))])
    line = note.split("\n")[1]
    assert line == "- Started `Digest 'x' # Hi <img src=x onerror=\"alert(1)\"> [link](https://evil.example/)`."
    assert line.count("`") == 2 and note.count("\n") == STARTED_NOTE.count("\n")

    long_name = "Quarterly " * 20
    note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("queued", name=long_name))])
    shown = note.split("\n")[1][len("- Started `"):-len("`.")]
    assert len(shown) == 80 and shown.endswith("\u2026")

    for blank in ("``` ```", "", None, 7):
        note = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("queued", name=blank))])
        assert note.split("\n")[1] == "- Started `Workflow`.", blank


def test_the_note_never_shows_an_id_or_a_handle(wr):
    records = [
        _record(sidecar=_sidecar("queued")),
        _record("run_watcher", sidecar=_sidecar(
            "unavailable", name="Contract watcher", reason="workflow_not_durable", step_id="run_watcher",
            workflow_id=NOT_DURABLE_ID,
        )),
    ]
    note = wr.workflow_run_note(_plan("run_digest", "run_watcher"), records, stopped=True)
    for secret in (DIGEST_ID, NOT_DURABLE_ID, RUN_ID, "run-1", "wf-secret-handle", OWNER, CONVERSATION, "run_digest"):
        assert secret not in note, secret


def test_a_stopped_plan_says_the_workflow_it_started_keeps_running(wr):
    started = wr.workflow_run_note(_plan("run_digest"), [_record(sidecar=_sidecar("queued"))], stopped=True)
    assert started == f"{STARTED_NOTE}\n\n{STOPPED}"
    unavailable = [_record(sidecar=_sidecar("unavailable", reason="workflow_already_running"))]
    not_started = wr.workflow_run_note(_plan("run_digest"), unavailable, stopped=True)
    assert STOPPED not in not_started and FOLLOW_ONE not in not_started


def test_the_reply_never_promises_results_in_this_chat(wr):
    texts = [
        wr.WORKFLOW_RUN_NOTE_HEADING, wr.WORKFLOW_RUN_FOLLOW_UP, wr.WORKFLOW_RUN_FOLLOW_UP_MANY,
        wr.WORKFLOW_RUN_STOPPED, *wr.WORKFLOW_RUN_REASON_TEXT.values(), *wr.WORKFLOW_RUN_SKIP_REASONS.values(),
    ]
    assert (wr.WORKFLOW_RUN_NOTE_HEADING, wr.WORKFLOW_RUN_FOLLOW_UP, wr.WORKFLOW_RUN_FOLLOW_UP_MANY,
            wr.WORKFLOW_RUN_STOPPED) == (HEADING, FOLLOW_ONE, FOLLOW_MANY, STOPPED)
    for text in texts:
        assert not POST_BACK.search(text), text


# ---------------------------------------------------------------------------
# The reply a run of the plan saves
# ---------------------------------------------------------------------------

def _plan_harness(monkeypatch, planning, steps, *, replies=(), final_response=None, notes=None):
    """A run of the plan ``steps`` planned with ``planning``, and with ``notes`` when the planner left workflows out."""
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(RUN_SETTINGS)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and WORKFLOW_RUN not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, WORKFLOW_RUN]
        kwargs.setdefault("workflow_planning", planning)
        plan = real_normalize(raw, *args, **kwargs)
        if notes is not None:
            # As the planner records the run steps it left out.
            plan["workflow_run_notes"] = notes
        return plan

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(steps, replies=replies, final_response=final_response, workflow_planning=planning)
    return env


def _reply(env):
    execution = _signed_in(env.prepare())
    frames = decoded_frames(execution.execute(emit=lambda frame: None))
    messages = env.assistant_messages()
    assert len(messages) == 1, messages
    return frames, messages[0]


def _assert_no_ids(*surfaces):
    for surface in surfaces:
        text = json.dumps(surface, default=str)
        for secret in (RUN_ID, DIGEST_ID, "chat_invocation"):
            assert secret not in text, secret


def test_the_reply_follows_the_answer_with_the_workflow_it_started(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [compose_step("answer"), _run(_handle(planning, "Weekly digest"))],
                   ["Your priorities."])
    frames, message = _reply(env)
    assert env.read()["status"] == "completed" and len(world.queued) == 1
    assert message["content"] == f"Your priorities.\n\n{STARTED_NOTE}"
    _assert_no_ids(frames, message)


def test_a_plan_that_only_starts_a_workflow_replies_with_the_note_alone(world, wr, planning, monkeypatch):
    env = _plan_harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest"))])
    assert "final_response" not in env.read()["plan"]
    frames, message = _reply(env)
    assert env.read()["status"] == "completed" and len(world.queued) == 1
    assert message["content"] == STARTED_NOTE
    _assert_no_ids(frames, message)


def test_the_reply_explains_a_workflow_that_could_not_start(world, wr, planning, monkeypatch):
    world.definitions.patch(OWNER, DIGEST_ID, status="awaiting_sign_in")
    env = _plan_harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest"))])
    frames, message = _reply(env)
    assert env.read()["status"] == "completed" and world.queued == []
    assert message["content"] == (
        f"{HEADING}\n- `Weekly digest` was not started. "
        f"{wr.WORKFLOW_RUN_REASON_TEXT['workflow_waiting_for_microsoft_365']}"
    )
    _assert_no_ids(frames, message)


def test_the_reply_explains_a_workflow_the_planner_left_out(world, wr, planning, monkeypatch):
    notes = [{"reason": "workflow_not_durable", "name": "Contract watcher"}]
    env = _plan_harness(
        monkeypatch, planning, [compose_step("answer"), _run(_handle(planning, "Weekly digest"))],
        replies=["Your priorities."], final_response=input_binding("answer"), notes=notes,
    )
    assert env.read()["plan"]["workflow_run_notes"] == notes
    _frames, message = _reply(env)
    assert message["content"] == (
        "Your priorities.\n\n"
        f"{HEADING}\n- Started `Weekly digest`.\n"
        f"- `Contract watcher` was not started. {wr.WORKFLOW_RUN_SKIP_REASONS['workflow_not_durable']}"
        f"\n\n{FOLLOW_ONE}"
    )

    # With every run step left out, the note still says why, and points to no run.
    left_out = _plan_harness(
        monkeypatch, planning, [compose_step("answer")], replies=["Your priorities."],
        final_response=input_binding("answer"), notes=notes,
    )
    _frames, message = _reply(left_out)
    assert message["content"] == (
        "Your priorities.\n\n"
        f"{HEADING}\n- `Contract watcher` was not started. {wr.WORKFLOW_RUN_SKIP_REASONS['workflow_not_durable']}"
    )


def test_a_plan_stopped_after_its_workflow_started_still_says_so(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")], [])
    execution = _signed_in(env.prepare())

    def stop_while_answering():
        # The user stops the plan after its workflow started, while the answer is being written.
        execution.lease.update({"cancellation_requested_at": datetime.now(timezone.utc).isoformat()})
        return "Your priorities."

    env.replies.append(stop_while_answering)
    decoded_frames(execution.execute(emit=lambda frame: None))
    saved = env.read()
    messages = env.assistant_messages()
    assert saved["status"] == "cancelled" and len(world.queued) == 1 and len(messages) == 1
    assert env.steps.read_item("run-1:run_digest", "run-1")["status"] == "completed"
    content = messages[0]["content"]
    assert content.startswith(f"{STARTED_NOTE}\n\n{STOPPED}\n\nThe run was stopped."), content
    assert "Your priorities." not in content


def test_a_stop_before_the_started_run_is_saved_is_left_to_recovery(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])
    execution = _signed_in(env.prepare())

    def stop():
        execution.lease.update({"cancellation_requested_at": datetime.now(timezone.utc).isoformat()})

    # Stopped between starting the run and saving the step: the step cannot keep a result, so it
    # is stopped with its effects uncertain, and a retry links the run instead of starting another.
    world.after_queue = stop
    decoded_frames(execution.execute(emit=lambda frame: None))
    step = env.steps.read_item("run-1:run_digest", "run-1")
    messages = env.assistant_messages()
    assert env.read()["status"] == "cancelled" and len(world.queued) == 1 and len(messages) == 1
    assert step["status"] == "cancelled" and step["effects_uncertain"] is True and "workflow_run" not in step
    content = messages[0]["content"]
    assert HEADING not in content and "Already submitted external actions may still finish." in content


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
