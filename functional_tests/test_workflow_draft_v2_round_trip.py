# test_workflow_draft_v2_round_trip.py
#!/usr/bin/env python3
"""
Functional test for opening and re-saving workflows created from chat in the V2 editor.
Version: 0.261.202
Implemented in: 0.261.202

This test ensures that each workflow the draft service creates from a blueprint (a weekly
calendar digest on an agent with bell-only alerts, an interval check and a manual task on the
default model, and a personal File Sync review with a document input) opens in the production
V2 editor without a read-only reason, and that saving it unchanged, through ``workflowForSave``
and the real personal save, changes no field of the stored workflow except its update time, and
leaves it unedited.

The TypeScript runs unmodified in Node through ``test_support/tsResolve.mjs``. The workflows are
created and saved by the real workflow modules over the doubles of the draft service test.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import REPO_ROOT  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import OWNER_ID  # noqa: E402
from test_workflow_draft_service import (  # noqa: E402  (the draft service harness and examples)
    DOCUMENT_REVIEW,
    EMAIL_DIGEST,
    EMAIL_HANDLES,
    ORIGIN,
    REVIEW_HANDLES,
    DraftHarness,
)


MINIMUM_VERSION = "0.261.202"

INTERVAL_CHECK = {
    "name": "Queue check",
    "trigger": {"type": "interval", "unit": "hours", "value": 2},
    "tasks": [{
        "title": "Check the queue",
        "instructions": "List the requests that have waited longer than a day.",
        "runner": {"type": "model"},
    }],
    "alerts": {"mode": "every_run", "severity": "low"},
    "run_as": "none",
}
MANUAL_SUMMARY = {
    "name": "Meeting notes",
    "trigger": {"type": "manual"},
    "tasks": [
        {"title": "Summarize", "instructions": "Summarize the meeting notes I paste into the run."},
        {"title": "List actions", "instructions": "List each action item with its owner."},
    ],
    "alerts": {"mode": "failures_only"},
}

CASES = {
    "weekly_agent_digest": (EMAIL_DIGEST, EMAIL_HANDLES),
    "interval_model_check": (INTERVAL_CHECK, {}),
    "manual_model_tasks": (MANUAL_SUMMARY, {}),
    "personal_file_sync_review": (DOCUMENT_REVIEW, REVIEW_HANDLES),
}
# A save always records when it happened (both timestamps) and gets a new container etag; nothing
# else may change when nothing was edited.
SAVE_TIME_FIELDS = frozenset({"updated_at", "modified_at", "_etag"})

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const lib = path.join(root, 'application', 'v2_ui', 'src', 'lib');
const editor = await import(pathToFileURL(path.join(lib, 'workflowEditor.ts')));
const flow = await import(pathToFileURL(path.join(lib, 'workflowFlow.ts')));
const scope = { type: 'personal' };
const output = {};
for (const [name, record] of Object.entries(input.records)) {
    // What the editor does with a loaded workflow the user saves without changing anything.
    const original = editor.normalizeWorkflowDefinition(record, scope);
    output[name] = {
        readonly: flow.flowUnsupportedReason(original) || '',
        payload: editor.workflowForSave(structuredClone(original), original, scope),
    };
}
console.log(JSON.stringify(output));
"""


@pytest.fixture(scope="module")
def round_trip():
    harness = DraftHarness()
    records = {}
    for name, (blueprint, handles) in CASES.items():
        created = harness.create(blueprint, handles, origin={**ORIGIN, "proposal_id": f"proposal-{name}"})
        assert (created["ok"], created["created"]) == (True, True), created["errors"]
        records[name] = created["workflow"]

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps({"records": records}, allow_nan=False), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    client = json.loads(result.stdout)

    saves = {}
    stored = harness.containers["personal_workflows"].items
    for name, record in records.items():
        key = (OWNER_ID, record["id"])
        before = copy.deepcopy(stored[key])
        harness.save_personal(f"resave:{name}", client[name]["payload"], actor_user_id=OWNER_ID)
        saves[name] = (before, copy.deepcopy(stored[key]), harness.steps[-1]["error"])
    return client, saves


def test_the_application_version_includes_the_draft_service():
    assert_app_version_at_least(MINIMUM_VERSION)


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_workflow_created_from_chat_opens_editable_in_v2(round_trip, name):
    client, _saves = round_trip
    assert client[name]["readonly"] == ""


@pytest.mark.parametrize("name", sorted(CASES))
def test_an_unchanged_v2_save_changes_nothing_but_the_save_time(round_trip, name):
    _client, saves = round_trip
    before, after, error = saves[name]
    assert error is None, error
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    assert set(changed) <= SAVE_TIME_FIELDS, {key: (before.get(key), after.get(key)) for key in changed}
    assert "updated_at" in changed, "The save did not reach the store."


@pytest.mark.parametrize("name", sorted(CASES))
def test_an_unchanged_v2_save_leaves_the_workflow_unedited(round_trip, name):
    _client, saves = round_trip
    before, after, _error = saves[name]
    assert after["origin"] == before["origin"]
    assert after["origin"]["edited"] is False
