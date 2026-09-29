#!/usr/bin/env python3
# test_orchestration_workflow_proposal_editor_round_trip.py
"""
Functional test for editing a workflow proposal in the V2 workflow editor before accepting it.
Version: 0.261.206
Implemented in: 0.261.206

The proposal card's Edit opens the draft route's workflow in the V2 workflow editor, and Save
accepts the proposal with the editor's payload. The accept route records the workflow as edited
only when that payload changes what the proposal would have created. This test runs the editor's
real draft handling -- `normalizeWorkflowDefinition` then `workflowForSave` from
`lib/workflowEditor.ts`, bundled with the V2 app's own esbuild and run under node -- between the
real draft and accept routes, and pins that:
- opening a proposal and saving it untouched is not an edit, for calendar, interval and manual
  triggers, and creates the same workflow Create would;
- a real change, such as a new name, is recorded as an edit and stored as typed;
- the editor's payload carries no workflow id and never turns URL Access on.
"""

import json
import subprocess
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_proposal_routes import (  # noqa: F401
    BLUEPRINT,
    ZONE,
    accept,
    draft,
    h,
    login,
    seed_run,
    stored_workflow,
)
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "application" / "v2_ui"
PROBE_TS = Path(__file__).resolve().parent / "test_support" / "workflow_proposal_draft_probe.ts"

TRIGGERS = {
    "calendar": BLUEPRINT["trigger"],
    "interval": {"type": "interval", "unit": "hours", "value": 2},
    "manual": {"type": "manual"},
}


def run_probe(drafts):
    """Run the editor's real draft handling under node and return the payload each Save sends."""
    assert (V2_DIR / "node_modules").is_dir(), (
        "application/v2_ui/node_modules is missing; restore the frontend dependencies first"
    )
    esbuild = V2_DIR / "node_modules" / "esbuild" / "bin" / "esbuild"
    assert esbuild.exists(), "application/v2_ui/node_modules/esbuild is missing"
    token = uuid.uuid4().hex
    # Under node_modules so the bundle's external imports resolve; both files are removed afterwards.
    bundle = V2_DIR / "node_modules" / f".cache-workflow-proposal-draft-{token}.mjs"
    request_file = V2_DIR / "node_modules" / f".cache-workflow-proposal-draft-{token}.json"
    try:
        request_file.write_text(json.dumps({"drafts": drafts}), encoding="utf-8")
        subprocess.run(
            [
                "node", str(esbuild), str(PROBE_TS), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", "--define:import.meta.env={}", f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["node", str(bundle), str(request_file)], cwd=str(V2_DIR), capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        for path in (bundle, request_file):
            if path.exists():
                path.unlink()
    assert result.returncode == 0, f"the workflow draft probe failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)["saves"]


def blueprint_with(trigger):
    blueprint = deepcopy(BLUEPRINT)
    blueprint["trigger"] = deepcopy(trigger)
    return blueprint


def draft_workflow(h):
    response = draft(h)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["workflow"]


def schedule_fields(workflow):
    return {key: deepcopy(workflow.get(key)) for key in ("trigger_type", "schedule", "tasks", "alert_rules")}


def test_version_includes_editing_a_proposal_before_accepting_it():
    assert_app_version_at_least("0.261.206")


@pytest.mark.parametrize("trigger", sorted(TRIGGERS))
def test_saving_the_proposal_untouched_is_not_an_edit(h, trigger):
    seed_run(h, blueprint=blueprint_with(TRIGGERS[trigger]))
    login(h)
    workflow = draft_workflow(h)
    [payload] = run_probe([{"workflow": workflow}])
    assert "id" not in payload
    assert payload.get("url_access_enabled") is not True
    assert payload["name"] == BLUEPRINT["name"]

    response = accept(h, workflow=payload)
    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    assert body["state"] == "created_paused"
    stored = stored_workflow(h)
    assert stored["origin"]["edited"] is False
    assert stored["is_enabled"] is False
    assert stored["trigger_type"] == workflow["trigger_type"]
    assert schedule_fields(stored) == schedule_fields(workflow)
    if trigger == "calendar":
        assert stored["schedule"]["timezone"] == ZONE


def test_a_renamed_proposal_is_recorded_as_edited_and_stored_as_typed(h):
    seed_run(h)
    login(h)
    workflow = draft_workflow(h)
    [payload] = run_probe([{"workflow": workflow, "name": "Weekly inbox triage"}])
    assert payload["name"] == "Weekly inbox triage"

    response = accept(h, workflow=payload)
    assert response.status_code == 201, response.get_data(as_text=True)
    stored = stored_workflow(h)
    assert stored["name"] == "Weekly inbox triage"
    assert stored["origin"]["edited"] is True
    assert stored["origin"]["source"] == "orchestration"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
