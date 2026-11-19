// test_v2_artifact_actions_logic.ts
//
// Runtime test for the V2 generated-artifact actions: "Add to workspace" and "Create PowerPoint".
// Version: 0.261.448
// Implemented in: 0.261.448
//
// The companion test, test_v2_artifact_actions.py, asserts that the client sends what the two
// routes read and that the card is wired to the actions. Those are source assertions. This file
// executes the rules, because each failure here puts a file somewhere the reader did not choose
// or offers a button that can only be refused:
//
//   - The destination is the conversation's own workspace. Defaulting to "personal" for a
//     conversation whose metadata has not loaded would offer to put a group's file in the
//     reader's private workspace.
//   - A destination the deployment has switched off is not offered: the server would accept the
//     file and nobody could open it.
//   - The request names its destination explicitly, with only the id that destination uses.
//   - 409 from the promote route is not an error body. The publication may exist; telling the
//     reader nothing happened would invite the second click the server went to lengths to absorb.
//   - A PowerPoint is built from Markdown only, beside the reply that carries the file, and never
//     in a shared conversation, where the export route cannot find the reply.
//
// Run by test_v2_artifact_actions.py, which bundles this with the esbuild Vite already brings in
// and executes it under node, skipping it when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    PERSONAL_TARGET,
    artifactConversationId,
    canAddToWorkspace,
    canCreatePowerPoint,
    isActionableArtifact,
    powerPointArtifactBody,
    promotionConflict,
    promotionErrorMessage,
    promotionOutcome,
    promotionRequestBody,
    resolvePromotionTargets,
    type PromotionContext,
    type PromotionTarget,
} from '../application/v2_ui/src/lib/generatedArtifactActions';
import {
    normalizeGeneratedArtifact,
    type GeneratedArtifact,
} from '../application/v2_ui/src/lib/generatedArtifacts';
import type { ConversationMetadata } from '../application/v2_ui/src/lib/types';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

function artifact(raw: Record<string, unknown> = {}): GeneratedArtifact {
    const normalized = normalizeGeneratedArtifact({
        capability: 'analyze',
        artifact_message_id: 'artifact-1',
        conversation_id: 'conv-1',
        file_name: 'analysis-summary.md',
        output_format: 'md',
        ...raw,
    });
    assert.ok(normalized, 'the fixture should normalise');
    return normalized;
}

const GROUPS = [{ id: 'group-1', name: 'Marketing' }, { id: 'group-2', name: 'Finance' }];
const PUBLICS = [{ id: 'public-1', name: 'Public library' }];
const ALL_ON = { personal: true, group: true, public: true };

function metadata(extra: Record<string, unknown> = {}): ConversationMetadata {
    return { conversation_id: 'conv-1', title: 'Plan', ...extra } as ConversationMetadata;
}

function targets(meta: ConversationMetadata | null, available = ALL_ON): PromotionTarget[] {
    const context: PromotionContext = { metadata: meta, groups: GROUPS, publicWorkspaces: PUBLICS, available };
    return resolvePromotionTargets(context);
}

// --- which file, which conversation --------------------------------------------------------------

check('the file is addressed by the conversation that stores it', () => {
    assert.equal(artifactConversationId(artifact({ conversation_id: 'stored', source_conversation_id: 'source' }), 'open'), 'stored');
    assert.equal(artifactConversationId(artifact({ conversation_id: '', source_conversation_id: 'source' }), 'open'), 'source');
    assert.equal(artifactConversationId(artifact({ conversation_id: '' }), '  open  '), 'open');
    assert.equal(artifactConversationId(artifact({ conversation_id: '' })), '');
});

check('a file is actionable only when it is finished, on its own message and not withheld', () => {
    assert.equal(isActionableArtifact(artifact(), 'conv-1'), true);
    assert.equal(isActionableArtifact(artifact(), ''), false, 'no conversation to address it by');
    assert.equal(isActionableArtifact(artifact({ artifact_message_id: '' , document_id: 'doc-1' }), 'conv-1'), false,
        'a workspace document has no chat artifact message to promote');
    assert.equal(isActionableArtifact(artifact({ background_export: true, export_run_id: 'run-1' }), 'conv-1'), false,
        'a running export has no file yet');
    for (const state of ['pending_approval', 'denied', 'auto_denied']) {
        assert.equal(isActionableArtifact(artifact({ approval: { state } }), 'conv-1'), false, `${state} is withheld from everyone`);
    }
    assert.equal(isActionableArtifact(artifact({ approval: { state: 'approved' } }), 'conv-1'), true, 'a released file is actionable');
});

// --- where a file can go -------------------------------------------------------------------------

check('a personal conversation offers the personal workspace and nothing else', () => {
    for (const chat_type of ['personal', 'personal_single_user', undefined, 'workflow', 'something-new']) {
        const found = targets(metadata(chat_type ? { chat_type } : {}));
        assert.deepEqual(found.map((item) => item.id), ['personal'], `chat_type ${String(chat_type)}`);
    }
    const personal = targets(metadata())[0];
    assert.equal(personal.name, 'Personal workspace');
    assert.equal(personal.detail, 'Private to you');
    assert.equal(personal.confirmLabel, 'Add to Personal');
    assert.equal(personal, PERSONAL_TARGET);
});

check('a group conversation offers its own group, named from the conversation, then the reader\'s list', () => {
    const named = targets(metadata({
        chat_type: 'group-single-user',
        context: [{ type: 'primary', scope: 'group', id: 'group-1', name: 'Conversation name' }],
    }));
    assert.deepEqual(named.map((item) => [item.id, item.name, item.groupId]), [['group:group-1', 'Conversation name', 'group-1']]);
    assert.equal(named[0].detail, 'Group workspace approval request');
    assert.equal(named[0].confirmLabel, 'Submit to Group');

    const listed = targets(metadata({
        chat_type: 'group-single-user',
        context: [{ type: 'primary', scope: 'group', id: 'group-2' }],
    }));
    assert.equal(listed[0].name, 'Finance', 'an unnamed context takes the name from the reader\'s groups');

    const shared = targets(metadata({ chat_type: 'group_multi_user', group_id: 'group-1', group_name: 'Marketing', context: [] }));
    assert.deepEqual(shared.map((item) => [item.id, item.name]), [['group:group-1', 'Marketing']],
        'a shared group conversation names its group on the conversation itself');
});

check('a public conversation offers its public workspace', () => {
    const found = targets(metadata({
        chat_type: 'public',
        context: [{ type: 'primary', scope: 'public', id: 'public-1', name: 'Library' }],
    }));
    assert.deepEqual(found.map((item) => [item.id, item.name, item.publicWorkspaceId]), [['public:public-1', 'Library', 'public-1']]);
    assert.equal(found[0].confirmLabel, 'Submit to Public');
    assert.equal(found[0].detail, 'Public workspace approval request');
});

check('a conversation that does not name its workspace lets the reader choose among their own', () => {
    const found = targets(metadata({ chat_type: 'group-single-user', context: [] }));
    assert.deepEqual(found.map((item) => item.id), ['personal', 'group:group-1', 'group:group-2', 'public:public-1']);
    const noGroups = targets(metadata({ chat_type: 'group-single-user', context: [] }), { personal: true, group: false, public: true });
    assert.deepEqual(noGroups.map((item) => item.id), ['personal', 'public:public-1']);
});

check('nothing is offered before the conversation has loaded', () => {
    assert.deepEqual(targets(null), []);
    assert.deepEqual(resolvePromotionTargets({ metadata: undefined, groups: GROUPS, publicWorkspaces: PUBLICS, available: ALL_ON }), []);
});

check('a workspace kind the deployment has switched off is not offered', () => {
    assert.deepEqual(targets(metadata(), { personal: false, group: true, public: true }), [],
        'a personal conversation with the personal workspace off has nowhere to go');
    assert.deepEqual(targets(metadata({
        chat_type: 'group-single-user',
        context: [{ type: 'primary', scope: 'group', id: 'group-1', name: 'Marketing' }],
    }), { personal: true, group: false, public: false }), []);
    assert.equal(canAddToWorkspace(artifact(), 'conv-1', []), false, 'no destination, no button');
    assert.equal(canAddToWorkspace(artifact(), 'conv-1', [PERSONAL_TARGET]), true);
    assert.equal(canAddToWorkspace(artifact({ approval: { state: 'pending_approval' } }), 'conv-1', [PERSONAL_TARGET]), false);
});

// --- the promote request and its answers ---------------------------------------------------------

check('the request names its destination explicitly, with only the id that destination uses', () => {
    assert.deepEqual(promotionRequestBody('conv-1', 'artifact-1', PERSONAL_TARGET), {
        conversation_id: 'conv-1', message_id: 'artifact-1', workspace_scope: 'personal',
    });
    const group = targets(metadata({ chat_type: 'group-single-user', group_id: 'group-1' }))[0];
    assert.deepEqual(promotionRequestBody('conv-1', 'artifact-1', group), {
        conversation_id: 'conv-1', message_id: 'artifact-1', workspace_scope: 'group', group_id: 'group-1',
    });
    const publicTarget = targets(metadata({ chat_type: 'public', context: [{ type: 'primary', scope: 'public', id: 'public-1' }] }))[0];
    assert.deepEqual(promotionRequestBody('conv-1', 'artifact-1', publicTarget), {
        conversation_id: 'conv-1', message_id: 'artifact-1', workspace_scope: 'public', public_workspace_id: 'public-1',
    });
    for (const body of [promotionRequestBody('c', 'm', PERSONAL_TARGET), promotionRequestBody('c', 'm', group)]) {
        assert.equal('request_id' in body, false, 'no request_id: the route then uses one fixed id, so a retry is not a second copy');
    }
});

check('an answer is read as added, waiting for approval, or unconfirmed', () => {
    const group = targets(metadata({ chat_type: 'group-single-user', group_id: 'group-1', group_name: 'Marketing' }))[0];

    assert.deepEqual(
        promotionOutcome({ approval_required: false, publication: { state: 'queued' }, message: 'Generated artifact added to your personal workspace.' }, PERSONAL_TARGET),
        { status: 'added', message: 'Added to your personal workspace.' },
    );
    assert.deepEqual(
        promotionOutcome({ approval_required: true, publication: { state: 'pending_approval' } }, group),
        { status: 'pending_approval', message: 'Submitted to Marketing for approval.' },
    );
    assert.equal(promotionOutcome({}, group).status, 'pending_approval',
        'a group or public destination is never reported as added on an answer that does not say so');
    const approved = promotionOutcome({ approval_required: true, publication: { state: 'approved' }, message: 'This artifact publication has already been approved.' }, group);
    assert.deepEqual(approved, { status: 'added', message: 'This artifact publication has already been approved.' });
    for (const state of ['uncertain', 'approval_failed']) {
        assert.equal(promotionOutcome({ publication: { state } }, group).status, 'unconfirmed', state);
    }
    assert.equal(promotionOutcome(null, PERSONAL_TARGET).status, 'added', 'an empty 200 for a personal destination is an add');
});

check('409 is a publication that could not be confirmed, not a failure', () => {
    const conflict = {
        status: 409,
        payload: {
            message: 'Publication could not be fully confirmed. Check the existing destination; no second copy was created.',
            publication: { state: 'uncertain' },
        },
    };
    assert.deepEqual(promotionConflict(conflict), {
        status: 'unconfirmed',
        message: 'Publication could not be fully confirmed. Check the existing destination; no second copy was created.',
    });
    assert.match(promotionConflict({ status: 409, payload: { publication: { state: 'uncertain' } } })?.message ?? '', /no second copy/);
    assert.equal(promotionConflict({ status: 409, payload: { error: 'something else' } }), null, '409 without a publication is a plain error');
    assert.equal(promotionConflict({ status: 403, payload: { publication: {} } }), null);
    assert.equal(promotionConflict({ status: 500, payload: null }), null);
    assert.equal(promotionConflict(new Error('boom')), null);
    assert.equal(promotionConflict(null), null);
});

check('a refusal reads as the server worded it', () => {
    assert.equal(promotionErrorMessage(new Error('Artifact publication is not permitted.')), 'Artifact publication is not permitted.');
    assert.match(promotionErrorMessage(new Error('')), /Failed to add the generated artifact/);
    assert.match(promotionErrorMessage('nope'), /Failed to add the generated artifact/);
});

// --- create PowerPoint ---------------------------------------------------------------------------

check('a PowerPoint is offered for a finished Markdown file beside its reply, in the reader\'s own conversation', () => {
    const base = { shared: false, messageId: 'reply-1' };
    assert.equal(canCreatePowerPoint(artifact(), 'conv-1', base), true);
    assert.equal(canCreatePowerPoint(artifact({ output_format: '', file_name: 'Notes.markdown' }), 'conv-1', base), true, 'recognised by file name too');
    assert.equal(canCreatePowerPoint(artifact({ output_format: 'csv', file_name: 'rows.csv', capability: 'tabular' }), 'conv-1', base), false, 'a spreadsheet is not a deck');
    assert.equal(canCreatePowerPoint(artifact({ output_format: 'json', file_name: 'rows.json' }), 'conv-1', base), false);
    assert.equal(canCreatePowerPoint(artifact({ capability: 'tabular', output_format: 'md' }), 'conv-1', base), true,
        'a Markdown file stays eligible whatever produced it');
    assert.equal(canCreatePowerPoint(artifact(), 'conv-1', { shared: true, messageId: 'reply-1' }), false, 'the export route cannot find a shared conversation\'s reply');
    assert.equal(canCreatePowerPoint(artifact(), 'conv-1', { shared: false, messageId: '' }), false, 'the deck is built beside the reply that carries the file');
    assert.equal(canCreatePowerPoint(artifact({ approval: { state: 'pending_approval' } }), 'conv-1', base), false);
    assert.equal(canCreatePowerPoint(artifact({ background_export: true, export_run_id: 'run-1' }), 'conv-1', base), false);
    assert.equal(canCreatePowerPoint(artifact(), '', base), false);
});

check('the PowerPoint request names the file and the reply, and never the reply\'s own text', () => {
    const body = powerPointArtifactBody(artifact(), 'conv-1', 'reply-1');
    assert.deepEqual(body, { message_id: 'reply-1', conversation_id: 'conv-1', artifact_message_id: 'artifact-1' });
    assert.equal('message_content_override' in body, false, 'the route ignores an override for a file export, so none is sent');
    assert.equal('visual_assets' in body, false, 'no diagrams on screen means no key at all');

    const assets = [{ kind: 'diagram', source: 'graph TD;A-->B', data_uri: 'data:image/png;base64,AAAA' }];
    assert.deepEqual(powerPointArtifactBody(artifact(), 'conv-1', 'reply-1', assets).visual_assets, assets);
});

let failed = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failed += 1;
        console.log(`  FAIL  ${name}`);
        console.log(error);
    }
}
if (failed) {
    process.exit(1);
}
console.log(`${checks.length} artifact action logic checks passed`);
