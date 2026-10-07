// workflow_handoff_draft_probe.ts
//
// Runs the V2 hand-off card's real editor handling on workflow hand-off drafts from a JSON file and
// prints what an edited accept would send, so a Python test can hand it to the real accept route.
// Version: 0.261.253
// Implemented in: 0.261.279
//
// Bundled with the esbuild the V2 app already provides and executed under node by
// test_orchestration_workflow_handoff_editor_round_trip.py. The request carries `drafts`, each a
// draft route response's `workflow`, optionally a new `name`, and optionally `url_access` to turn
// URL Access on in the editor. Each is answered as the hand-off card's Edit answers Save: the draft
// opened as a new personal workflow (`normalizeWorkflowDefinition`), changed as asked, then
// prepared for an edited accept (`workflowHandoffEdit`, with no saved original). A draft the card
// refuses to send is answered with `workflow: null` and `url_access_refused: true`.

import { readFileSync } from 'node:fs';
import { normalizeWorkflowDefinition, type WorkflowScope } from '../../application/v2_ui/src/lib/workflowEditor';
import { workflowHandoffEdit } from '../../application/v2_ui/src/lib/workflowHandoffs';

interface DraftRequest {
    workflow: Record<string, unknown>;
    name?: string;
    url_access?: boolean;
}

const scope: WorkflowScope = { type: 'personal' };
const request = JSON.parse(readFileSync(process.argv[2], 'utf-8')) as { drafts: DraftRequest[] };
const saves = request.drafts.map((entry) => {
    let draft = normalizeWorkflowDefinition(entry.workflow, scope);
    if (entry.name !== undefined) draft = { ...draft, name: entry.name };
    if (entry.url_access !== undefined) draft = { ...draft, url_access_enabled: entry.url_access };
    const edit = workflowHandoffEdit(draft, null);
    return { workflow: edit ? edit.workflow : null, url_access_refused: edit === null };
});
process.stdout.write(JSON.stringify({ saves }));
