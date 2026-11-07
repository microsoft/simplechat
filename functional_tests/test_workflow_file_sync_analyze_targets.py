# test_workflow_file_sync_analyze_targets.py
#!/usr/bin/env python3
"""
Functional test for Analyze tasks whose targets come from File Sync, in personal and group workflows.
Version: 0.261.144
Implemented in: 0.261.144

Both saves let an Analyze task have no selected documents when the workflow's File Sync is
enabled and uses the changed documents. In both ``save_personal_workflow`` and
``save_group_workflow`` that gate is ``allow_empty_file_sync_targets``, which is
``file_sync.enabled and file_sync.use_changed_documents``. The runner then analyzes the files each
sync changed.

Before 0.261.144 the V2 editor honoured this only for group workflows. A personal workflow
created in classic with File Sync and Analyze on changed files could therefore be opened in V2,
but never saved there.

This test ensures that the editor allows such a save exactly when the server accepts it, in both
scopes:

* The client half is the production TypeScript (``lib/workflowEditor.ts``) under Node. It
  normalizes the record the server stored, applies the editor's own edit (the description, or the
  evidence removed with ``documentActionFromSelection``, as the task fields do), validates with
  ``workflowValidationErrors``, and builds the payload with ``workflowForSave``.
* The server half creates and reloads each record through the REAL ``save_personal_workflow`` and
  ``save_group_workflow``, then saves the editor's exact payload through the same function. The
  harness is ``test_group_workflow_round_trip_preservation.py``; only I/O is doubled, plus a
  personal File Sync source for the personal scope.
* Personal File Sync authoring stays out of scope, so a personal draft carries its loaded
  ``file_sync`` unchanged.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

import test_group_workflow_round_trip_preservation as harness  # noqa: E402  (shared real-module harness)


REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = harness.OWNER_ID
GROUP_ID = harness.GROUP_ID
PERSONAL_SOURCE = {"scope_type": "personal", "scope_id": OWNER_ID, "source_id": "home-share"}
GROUP_SOURCE = {"scope_type": "group", "scope_id": GROUP_ID, "source_id": harness.SOURCE_ID}
SCOPES = ("personal", "group")


def _file_sync(scope, *, enabled, changed, sources=True):
    source = PERSONAL_SOURCE if scope == "personal" else GROUP_SOURCE
    return {
        "enabled": enabled, "wait_mode": "complete", "continue_mode": "always",
        "use_changed_documents": changed, "sources": [dict(source)] if sources else [],
    }


def _record(scope, file_sync, document_ids):
    """A V2 workflow whose only task analyzes the given documents."""
    record = {
        "name": "Changed-file analysis", "description": "Analyze what File Sync changed.",
        "definition_version": 2, "runner_type": "model", "model_endpoint_id": "", "model_id": "",
        "trigger_type": "manual", "is_enabled": True, "chat_capabilities_enabled": False,
        "error_handling": {"strategy": "halt", "retry_count": 0}, "reference_inputs": [],
        "tasks": [{
            "id": "analyze", "type": "instructions", "name": "Analyze changes",
            "instructions": "Summarize each changed file.", "runner": {"type": "inherit"},
            "document_action": {
                "type": "analyze", "document_ids": list(document_ids), "analysis_mode": "per_document",
                "target_mode": "selected",
            },
        }],
        "file_sync": file_sync,
    }
    if scope == "group":
        record["group_id"] = GROUP_ID
    return record


# name: (stored file_sync factory or None for a new workflow, stored document ids, editor edit, accepted)
CASES = {
    "changed_files_analyze_without_evidence": (
        lambda scope: _file_sync(scope, enabled=True, changed=True), [], "describe", True,
    ),
    "changed_files_evidence_removed": (
        lambda scope: _file_sync(scope, enabled=True, changed=True), ["policy-doc"], "remove_evidence", True,
    ),
    "sync_without_changed_files_evidence_removed": (
        lambda scope: _file_sync(scope, enabled=True, changed=False), ["policy-doc"], "remove_evidence", False,
    ),
    "file_sync_off_evidence_removed": (
        lambda scope: _file_sync(scope, enabled=False, changed=True, sources=False), ["policy-doc"], "remove_evidence", False,
    ),
    "new_workflow_without_evidence": (None, None, "new_without_evidence", False),
}

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const editor = await import(pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowEditor.ts')));
const scopes = { personal: { type: 'personal' }, group: { type: 'group', groupId: input.group_id } };
const options = (scope) => ({
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
    scope: scope.type === 'group' ? { type: 'group', id: scope.groupId } : { type: 'personal', id: input.owner_id },
});
// The task fields write a document action exactly this way when the evidence selection changes.
const noEvidence = () => editor.documentActionFromSelection('analyze', [], { mode: 'selected', analysisMode: 'per_document' });
const edits = {
    describe: (draft) => ({ ...draft, description: 'Edited in V2.' }),
    remove_evidence: (draft) => ({
        ...draft,
        tasks: draft.tasks.map((task, index) => index === 0 ? { ...task, document_action: noEvidence() } : task),
    }),
    new_without_evidence: (draft) => ({
        ...draft,
        name: 'New analysis',
        tasks: draft.tasks.map((task, index) => index === 0
            ? { ...task, name: 'Analyze changes', instructions: 'Summarize each changed file.', document_action: noEvidence() }
            : task),
    }),
};
const output = {};
for (const [name, testCase] of Object.entries(input.cases)) {
    const scope = scopes[testCase.scope];
    const original = testCase.record ? editor.normalizeWorkflowDefinition(testCase.record, scope) : null;
    const draft = edits[testCase.edit](original ? structuredClone(original) : editor.newWorkflowDefinition(scope));
    output[name] = {
        errors: editor.workflowValidationErrors(draft, options(scope), original),
        providesTargets: editor.workflowFileSyncProvidesAnalyzeTargets(draft),
        payload: editor.workflowForSave(draft, original, scope),
    };
}
console.log(JSON.stringify(output));
"""


class Stores:
    """The real personal and group workflow stores, over the harness's doubled I/O."""

    def __init__(self):
        self.group = harness.GroupWorkflowStore()
        self.group.module._utc_now_iso = lambda: "2026-09-22T12:00:00+00:00"
        self.personal = self.group.modules["functions_personal_workflows"]
        self.personal.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
        authorize_group_source = self.personal.get_authorized_sync_source
        self.personal_source_reads = []

        def get_authorized_sync_source(scope_type, source_id, user_id, scope_id=None, **kwargs):
            if scope_type != "personal":
                return authorize_group_source(scope_type, source_id, user_id, scope_id=scope_id, **kwargs)
            self.personal_source_reads.append((scope_id, source_id))
            if scope_id != OWNER_ID or source_id != PERSONAL_SOURCE["source_id"]:
                raise LookupError("File sync source not found")
            return {
                "id": source_id, "scope_type": "personal", "user_id": user_id, "name": "Home share",
                "source_type": "onedrive", "auth": {"token": "never-store"},
            }

        self.personal.get_authorized_sync_source = get_authorized_sync_source

    def save(self, scope, payload):
        payload = copy.deepcopy(payload)
        if scope == "personal":
            return self.personal.save_personal_workflow(OWNER_ID, payload, actor_user_id=OWNER_ID)
        return self.group.save(payload)

    def load(self, scope, workflow_id):
        record = (self.personal.get_personal_workflow(OWNER_ID, workflow_id) if scope == "personal"
                  else self.group.load(workflow_id))
        # What the list route returns: the stored record without Cosmos metadata.
        return {key: value for key, value in record.items() if not key.startswith("_")}


@pytest.fixture(scope="module")
def outcome():
    stores = Stores()
    loaded = {}
    for scope in SCOPES:
        for name, (file_sync, document_ids, _edit, _accepted) in CASES.items():
            if file_sync is None:
                loaded[(scope, name)] = None
                continue
            saved = stores.save(scope, _record(scope, file_sync(scope), document_ids))
            loaded[(scope, name)] = stores.load(scope, saved["id"])
    payload = {
        "group_id": GROUP_ID, "owner_id": OWNER_ID,
        "cases": {
            f"{scope}:{name}": {"scope": scope, "record": loaded[(scope, name)], "edit": CASES[name][2]}
            for scope in SCOPES for name in CASES
        },
    }
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=90, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return stores, loaded, json.loads(result.stdout)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", sorted(CASES))
def test_the_editor_allows_an_analyze_save_exactly_when_the_server_accepts_it(outcome, scope, name):
    stores, loaded, client = outcome
    _file_sync_factory, _document_ids, _edit, accepted = CASES[name]
    result = client[f"{scope}:{name}"]
    evidence_error = "Analyze changes needs selected evidence for Analyze."

    try:
        saved = stores.save(scope, result["payload"])
        server_error = None
    except ValueError as exc:
        saved, server_error = None, exc

    if accepted:
        assert result["errors"] == [], result["errors"]
        assert result["providesTargets"] is True
        assert server_error is None, f"The server refused a save the editor allows: {server_error}"
        # The loaded File Sync is sent back unchanged and stored unchanged; Analyze keeps no documents.
        assert result["payload"]["file_sync"] == loaded[(scope, name)]["file_sync"]
        assert saved["file_sync"] == loaded[(scope, name)]["file_sync"]
        assert saved["tasks"][0]["document_action"]["type"] == "analyze"
        assert saved["tasks"][0]["document_action"]["document_ids"] == []
    else:
        assert evidence_error in result["errors"], result["errors"]
        assert result["providesTargets"] is False
        assert server_error is not None, "The server accepted a save the editor refuses."
        # The refusal is the document-action rule, which stays on the generic 400, not a reviewed alert message.
        assert not isinstance(server_error, stores.group.modules["functions_workflow_definitions"].WorkflowPublicValidationError)


def test_personal_file_sync_is_carried_unchanged_and_reauthorized(outcome):
    """V2 does not author personal File Sync: the stored configuration goes back as loaded."""
    stores, loaded, client = outcome
    stored = loaded[("personal", "changed_files_analyze_without_evidence")]["file_sync"]
    assert stored["enabled"] is True and stored["use_changed_documents"] is True
    assert stored["sources"] == [{**PERSONAL_SOURCE, "name": "Home share", "source_type": "onedrive"}]
    assert client["personal:changed_files_analyze_without_evidence"]["payload"]["file_sync"] == stored
    assert (OWNER_ID, "home-share") in stores.personal_source_reads
