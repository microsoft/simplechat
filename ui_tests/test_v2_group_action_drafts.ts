// test_v2_group_action_drafts.ts
//
// Runtime test for the scope isolation of the workspace editor draft cache and the
// created-action handoff.
// Version: 0.261.137
// Implemented in: 0.261.137
//
// The group actions browser suite proves the editor CRUD, gating, conflict and secret
// behaviour against a mocked backend. It cannot prove the one property the contract calls the
// key risk: that a draft opened in group A can never be restored into group B or into personal
// scope. That isolation lives entirely in the cache key, and a mocked browser navigation between
// two group workspaces is a full document load that clears the in-memory Map, so a leak could
// never manifest there to be caught.
//
// The draft cache and the created-action handoff both derive their partition from the same
// `editorScopeSegments(scope)` prefix in workspaceEditorDrafts.ts. The handoff functions are pure
// module functions over that Map, so exercising them under node pins the shared partitioning
// decisively, with a positive control beside every negative one: a value stored under group A is
// returned only when read back under group A, and never under group B or personal scope.
//
// Run by test_v2_group_actions.py, bundled with the esbuild Vite already provides and executed
// under node, requiring only the existing front-end toolchain.

import assert from 'node:assert/strict';
import { useBootstrapStore } from '../application/v2_ui/src/stores/bootstrapStore';
import {
    clearWorkspaceEditorDrafts,
    queueCreatedWorkspaceAction,
    takeCreatedWorkspaceAction,
    type EditorWorkspaceScope,
} from '../application/v2_ui/src/lib/workspaceEditorDrafts';

const RETURN_PATH = '/workspace/agents/agent-under-edit';
const PERSONAL: EditorWorkspaceScope = { kind: 'personal' };
const GROUP_A: EditorWorkspaceScope = { kind: 'group', id: 'group-a' };
const GROUP_B: EditorWorkspaceScope = { kind: 'group', id: 'group-b' };

function action(id: string): any {
    return { id, name: id, displayName: id, type: 'fixture_custom', auth: { type: 'NoAuth' } };
}

function seedOwner(id: string): void {
    // ownerKey() clears the cache whenever the signed-in owner changes, so the value must be set
    // before anything is queued and kept stable across the reads under test.
    useBootstrapStore.setState({ data: { user: { id } } } as any);
}

function testGroupDraftNeverLeaksToAnotherGroupOrPersonal(): void {
    seedOwner('owner-1');
    clearWorkspaceEditorDrafts();
    const stored = action('group-a-created');
    queueCreatedWorkspaceAction(RETURN_PATH, stored, GROUP_A);

    // Negative: the same return path in another group, or in personal scope, must not find it.
    assert.equal(takeCreatedWorkspaceAction(RETURN_PATH, GROUP_B), null,
        'A group A handoff must never be taken from group B.');
    assert.equal(takeCreatedWorkspaceAction(RETURN_PATH, PERSONAL), null,
        'A group A handoff must never be taken from personal scope.');
    assert.equal(takeCreatedWorkspaceAction(RETURN_PATH), null,
        'A group A handoff must never be taken from the default (personal) scope.');

    // Positive control: the group A reader still finds it, so the negatives cannot pass trivially.
    const taken = takeCreatedWorkspaceAction(RETURN_PATH, GROUP_A);
    assert.equal(taken?.id, 'group-a-created', 'The group A handoff must be taken from group A.');
    // And it is consumed once, not left to be replayed.
    assert.equal(takeCreatedWorkspaceAction(RETURN_PATH, GROUP_A), null,
        'A handoff must be taken exactly once.');
}

function testPersonalHandoffIsUnchangedByTheScopeArgument(): void {
    seedOwner('owner-2');
    clearWorkspaceEditorDrafts();
    const stored = action('personal-created');
    // Personal is the default, and a personal draft must be byte-identical whether the scope is
    // passed explicitly or omitted -- personal contributes nothing to the key.
    queueCreatedWorkspaceAction(RETURN_PATH, stored);
    assert.equal(takeCreatedWorkspaceAction(RETURN_PATH, GROUP_A), null,
        'A personal handoff must never be taken from a group.');
    const taken = takeCreatedWorkspaceAction(RETURN_PATH, PERSONAL);
    assert.equal(taken?.id, 'personal-created', 'A personal handoff is retrievable with the explicit personal scope.');
}

function testAnInvalidReturnPathIsRejected(): void {
    seedOwner('owner-3');
    clearWorkspaceEditorDrafts();
    assert.throws(() => queueCreatedWorkspaceAction('/groups/group-a/documents', action('x'), GROUP_A),
        'Only an agent editor return path may seed a handoff.');
}

for (const check of [
    testGroupDraftNeverLeaksToAnotherGroupOrPersonal,
    testPersonalHandoffIsUnchangedByTheScopeArgument,
    testAnInvalidReturnPathIsRejected,
]) {
    check();
}

console.log('group action draft scope isolation checks passed');
