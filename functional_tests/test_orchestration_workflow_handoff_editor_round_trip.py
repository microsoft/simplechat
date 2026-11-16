#!/usr/bin/env python3
# test_orchestration_workflow_handoff_editor_round_trip.py
"""
Functional test for editing a workflow hand-off in the V2 workflow editor before accepting it.
Version: 0.261.253
Implemented in: 0.261.295

The hand-off card's Edit opens the draft route's workflow in the V2 workflow editor, and Save sends
an edited accept, ``{conversation_id, mode: 'edited', workflow}``, with the editor's payload. The
accept route records the one-time workflow as edited only when that payload changes what the
hand-off would have created. This test runs the card's real editor handling --
``normalizeWorkflowDefinition`` from ``lib/workflowEditor.ts``, then ``workflowHandoffEdit`` from
``lib/workflowHandoffs.ts``, bundled with the V2 app's own esbuild and run under node -- between
the real draft and accept routes, and pins that:

- opening a hand-off and saving it untouched is not an edit: the server creates the same manual,
  durable, disabled one-time workflow, with the same For each flow, tasks and task prompt, and
  queues its one run for this chat. The editor's save payload sets the task prompt to the first
  task's instructions, while the server set a version 3 hand-off's from its name, so the card
  leaves the task prompt for the server to set;
- a real change, such as a new name, is recorded as an edit and stored as typed;
- the payload never carries a workflow id or a task prompt, and a draft with URL Access turned on
  is never sent.

Refs #1549 and #1543. Checks use explicit raises, so they hold under ``python -O``.
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_planner import _require, _same
from test_orchestration_workflow_handoff_routes import (  # noqa: F401
    accept,
    decision,
    expect,
    handoff_draft,
    hw,
    seed_handoff_run,
    stored_runs,
    stored_workflow,
)
from test_orchestration_workflow_proposal_routes import CONVERSATION, RUN, login
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "application" / "v2_ui"
DRAFT_PROBE = Path(__file__).resolve().parent / "test_support" / "workflow_handoff_draft_probe.ts"
RENAMED = "Contract review, renamed"


def run_probe(probe, request):
    """Bundle a V2 probe with the app's own esbuild, run it under node on ``request``, and parse its output."""
    _require((V2_DIR / "node_modules").is_dir(),
             "application/v2_ui/node_modules is missing; restore the frontend dependencies first")
    esbuild = V2_DIR / "node_modules" / "esbuild" / "bin" / "esbuild"
    _require(esbuild.exists(), "application/v2_ui/node_modules/esbuild is missing")
    token = uuid.uuid4().hex
    # Under node_modules so the bundle's external imports resolve; both files are removed afterwards.
    bundle = V2_DIR / "node_modules" / f".cache-{probe.stem}-{token}.mjs"
    request_file = V2_DIR / "node_modules" / f".cache-{probe.stem}-{token}.json"
    try:
        request_file.write_text(json.dumps(request), encoding="utf-8")
        built = subprocess.run(
            [
                "node", str(esbuild), str(probe), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", "--define:import.meta.env={}", f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR), capture_output=True, text=True,
        )
        _require(built.returncode == 0, f"the {probe.name} bundle failed:\n{built.stdout}\n{built.stderr}")
        result = subprocess.run(
            ["node", str(bundle), str(request_file)], cwd=str(V2_DIR), capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        for path in (bundle, request_file):
            if path.exists():
                path.unlink()
    _require(result.returncode == 0, f"the {probe.name} probe failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def editor_saves(*drafts):
    """What the hand-off card's Save would send for each draft request."""
    saves = run_probe(DRAFT_PROBE, {"drafts": list(drafts)})["saves"]
    _same(len(saves), len(drafts), "the probe's answers")
    return saves


def sent_workflow(save):
    """The workflow an edited accept sends, after checking the card would send it at all."""
    _same(save["url_access_refused"], False, "the card's URL Access refusal")
    workflow = save["workflow"]
    _require(isinstance(workflow, dict), f"The card sends no workflow: {save!r}")
    _require("id" not in workflow, "An edited accept sends a workflow id; the server derives it from the hand-off.")
    _require("task_prompt" not in workflow,
             "An edited accept sends a task prompt; the server sets a version 3 workflow's from its name.")
    _require(workflow.get("url_access_enabled") is not True, "An edited accept turns URL Access on.")
    return workflow


def test_version_includes_the_v2_workflow_handoff_card():
    assert_app_version_at_least("0.261.253")


def test_saving_the_handoff_untouched_is_not_an_edit(hw):
    seed_handoff_run(hw)
    login(hw)
    draft = handoff_draft(hw)
    [save] = editor_saves({"workflow": draft})
    payload = sent_workflow(save)
    _same(payload.get("name"), draft.get("name"), "the payload's name")

    accepted = expect(accept(hw, mode="edited", workflow=payload), 201)

    _same((accepted["state"], accepted["created"]), ("queued", True), "the accept")
    stored = stored_workflow(hw)
    _require(stored is not None, "The edited accept created no workflow.")
    origin = stored.get("origin") or {}
    _same(
        (origin.get("source"), origin.get("one_time"), origin.get("proposal_id"), origin.get("edited")),
        ("orchestration", True, hw.handoff_id, False), "the stored origin",
    )
    _same(
        (stored["id"], stored["is_enabled"], stored.get("trigger_type"), stored.get("definition_version"),
         stored.get("durable_execution")),
        (hw.workflow_id, False, "manual", 3, True), "the stored workflow",
    )
    _same(stored.get("flow"), draft.get("flow"), "the stored For each flow")
    _same(stored.get("task_prompt"), draft.get("task_prompt"), "the stored task prompt")
    _same(
        [(task.get("id"), task.get("instructions")) for task in stored.get("tasks") or []],
        [(task.get("id"), task.get("instructions")) for task in draft.get("tasks") or []],
        "the stored tasks",
    )
    _same(decision(hw)["state"], "queued", "the decision")
    runs = stored_runs(hw)
    _same(len(runs), 1, "durable runs")
    invocation = runs[0]["chat_invocation"]
    _same(
        (accepted["run"]["id"], invocation["handoff_id"], invocation["conversation_id"],
         invocation["orchestration_run_id"]),
        (runs[0]["id"], hw.handoff_id, CONVERSATION, RUN), "the queued run",
    )


def test_a_renamed_handoff_is_recorded_as_edited_and_stored_as_typed(hw):
    seed_handoff_run(hw)
    login(hw)
    draft = handoff_draft(hw)
    [save] = editor_saves({"workflow": draft, "name": RENAMED})
    payload = sent_workflow(save)
    _same(payload.get("name"), RENAMED, "the payload's name")

    expect(accept(hw, mode="edited", workflow=payload), 201)

    stored = stored_workflow(hw)
    _require(stored is not None, "The edited accept created no workflow.")
    origin = stored.get("origin") or {}
    _same(
        (stored["name"], stored["is_enabled"], origin.get("source"), origin.get("one_time"), origin.get("edited")),
        (RENAMED, False, "orchestration", True, True), "the renamed workflow",
    )
    _same(stored.get("flow"), draft.get("flow"), "the renamed workflow's flow")
    _same(len(stored_runs(hw)), 1, "durable runs")


def test_a_draft_with_url_access_on_is_never_sent(hw):
    seed_handoff_run(hw)
    login(hw)
    draft = handoff_draft(hw)
    _require(draft.get("url_access_enabled") is not True, "The draft route turned URL Access on.")
    turned_on, arrived_on, turned_off = editor_saves(
        {"workflow": draft, "url_access": True},
        {"workflow": {**draft, "url_access_enabled": True}},
        {"workflow": draft, "url_access": False},
    )

    for label, save in (("turned on in the editor", turned_on), ("on in the draft", arrived_on)):
        _same((save["url_access_refused"], save["workflow"]), (True, None), f"a draft with URL Access {label}")
    sent_workflow(turned_off)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
