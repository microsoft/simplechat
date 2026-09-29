// workflow_proposal_draft_probe.ts
//
// Runs the V2 workflow editor's real draft handling on workflow proposal drafts from a JSON file and
// prints what the editor would send, so a Python test can hand it to the real accept route.
// Version: 0.261.204
// Implemented in: 0.261.204
//
// Bundled with the esbuild the V2 app already provides and executed under node by
// test_orchestration_workflow_proposal_editor_round_trip.py. The request carries `drafts`, each a
// draft route response's `workflow` and optionally a new `name`. Each is answered with the payload
// the proposal card's Edit sends on Save: the draft opened as a new personal workflow
// (`normalizeWorkflowDefinition`), renamed when asked, then prepared for saving (`workflowForSave`).

import { readFileSync } from 'node:fs';
import {
    normalizeWorkflowDefinition,
    workflowForSave,
    type WorkflowScope,
} from '../../application/v2_ui/src/lib/workflowEditor';

interface DraftRequest {
    workflow: Record<string, unknown>;
    name?: string;
}

const scope: WorkflowScope = { type: 'personal' };
const request = JSON.parse(readFileSync(process.argv[2], 'utf-8')) as { drafts: DraftRequest[] };
const saves = request.drafts.map((entry) => {
    const draft = normalizeWorkflowDefinition(entry.workflow, scope);
    return workflowForSave(entry.name === undefined ? draft : { ...draft, name: entry.name }, null, scope);
});
process.stdout.write(JSON.stringify({ saves }));
