// test_v2_scope_lock_logic.ts
//
// Runtime test for the V2 scope lock rules.
// Version: 0.261.448
// Implemented in: 0.261.448
//
// The companion test, test_v2_scope_lock_edit.py, asserts that the client sends what the route
// reads and that the pieces are wired together. Those are source assertions. This file executes
// the behaviour, because each failure here is a silent one:
//
//   - A lock state of `null` is not "unlocked". Offering a Lock button for a conversation that
//     has never used a workspace document would lock it to nothing.
//   - Unlocking is refused while the administrator enforces the lock, but locking never is, so a
//     conversation unlocked before the setting was turned on can still be locked again.
//   - A shared conversation is changed by anyone who can post in it, a personal one by its owner.
//     Offering the button to anyone else ends in a refusal with no explanation.
//   - The change is optimistic. A refusal has to put back exactly what was held, and must not
//     overwrite a newer read of the conversation that landed while the request was in flight.
//   - The dialog is decided once, when it opens. If it followed the live state it would turn from
//     "Unlock" into "Lock" the moment the optimistic write landed.
//
// Run by test_v2_scope_lock_edit.py, which bundles this with the esbuild Vite already brings in and
// executes it under node, skipping it when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    changeScopeLock,
    confirmedScopeLock,
    readScopeLockWorkspaces,
    resolveScopeLockView,
    scopeLockControlLabel,
    scopeLockCopy,
    scopeLockEnforced,
    scopeLockErrorMessage,
    scopeLockRequestBody,
    withScopeLockFields,
    type ScopeLockEffects,
    type ScopeLockFields,
    type ScopeLockView,
} from '../application/v2_ui/src/lib/scopeLock';
import { scopeLockState } from '../application/v2_ui/src/lib/conversationBadges';
import type { ConversationMetadata } from '../application/v2_ui/src/lib/types';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

const GROUP = 'group-1';
const PUBLIC = 'public-1';

function conversation(extra: Record<string, unknown> = {}): ConversationMetadata {
    return {
        conversation_id: 'conv-1',
        title: 'Quarterly plan',
        user_id: 'user-1',
        scope_locked: true,
        locked_contexts: [{ scope: 'group', id: GROUP }],
        context: [{ type: 'primary', scope: 'group', id: GROUP, name: 'Marketing' }],
        ...extra,
    } as ConversationMetadata;
}

function view(metadata: ConversationMetadata | null, options: Record<string, unknown> = {}): ScopeLockView {
    return resolveScopeLockView(metadata, { enforced: false, viewerId: 'user-1', ...options });
}

// --- the administrator's setting -----------------------------------------------------------------

check('only an explicit false lifts the administrator lock', () => {
    assert.equal(scopeLockEnforced(undefined), true, 'no settings at all is enforced');
    assert.equal(scopeLockEnforced({}), true, 'a missing key is the stored default, which is on');
    assert.equal(scopeLockEnforced({ enforce_workspace_scope_lock: true }), true);
    assert.equal(scopeLockEnforced({ enforce_workspace_scope_lock: 'false' }), true, 'a string is not an off switch');
    assert.equal(scopeLockEnforced({ enforce_workspace_scope_lock: false }), false);
    assert.equal(scopeLockEnforced('settings'), true);
    assert.equal(scopeLockEnforced(null), true);
});

// --- which workspaces the lock covers ------------------------------------------------------------

check('the workspaces are named from the conversation, then the reader\'s own list, then the id', () => {
    const metadata = conversation({
        locked_contexts: [
            { scope: 'personal', id: 'user-1' },
            { scope: 'group', id: GROUP },
            { scope: 'public', id: PUBLIC },
            { scope: 'group', id: 'group-unknown' },
        ],
    });
    const workspaces = readScopeLockWorkspaces(metadata, {
        groups: [{ id: 'group-unknown', name: 'Listed group' }],
        publicWorkspaces: [{ id: PUBLIC, name: 'Public library' }],
    });
    assert.deepEqual(
        workspaces.map((item) => [item.kind, item.id, item.name]),
        [
            ['personal', '', 'Personal workspace'],
            ['group', GROUP, 'Marketing'],
            ['public', PUBLIC, 'Public library'],
            ['group', 'group-unknown', 'Listed group'],
        ],
    );
    const unnamed = readScopeLockWorkspaces(conversation({ context: [] }));
    assert.equal(unnamed[0].name, GROUP, 'an unnamed workspace falls back to its id rather than vanishing');
});

check('the list is what the server enforces with: locked_contexts, else the recorded contexts', () => {
    const fromContext = readScopeLockWorkspaces(conversation({
        locked_contexts: [],
        context: [
            { type: 'primary', scope: 'group', id: GROUP, name: 'Marketing' },
            { type: 'secondary', scope: 'personal', id: 'user-1' },
            { type: 'secondary', scope: 'model_knowledge', id: 'x' },
        ],
    }));
    assert.deepEqual(fromContext.map((item) => item.name), ['Marketing', 'Personal workspace']);

    const filtered = readScopeLockWorkspaces(conversation({
        locked_contexts: [
            { scope: 'group', id: GROUP },
            { scope: 'group', id: GROUP },
            { scope: 'group', id: '' },
            { scope: 'model_knowledge', id: 'x' },
            'not an object',
            null,
        ],
    }));
    assert.deepEqual(filtered.map((item) => item.id), [GROUP], 'duplicates, blanks and other scopes are dropped');
});

// --- what the reader may do ----------------------------------------------------------------------

check('a conversation that has never used a workspace has no lock to show', () => {
    for (const scope_locked of [null, undefined]) {
        const hidden = view(conversation({ scope_locked }));
        assert.equal(hidden.state, 'hidden');
        assert.equal(hidden.action, null);
        assert.equal(hidden.workspaces.length, 0);
        assert.equal(scopeLockControlLabel(hidden), '');
    }
    assert.equal(view(null).state, 'hidden');
    assert.equal(scopeLockState(conversation({ scope_locked: null })), 'hidden', 'the badge reads the same three states');
});

check('a locked conversation can be unlocked unless the administrator enforces the lock', () => {
    const free = view(conversation());
    assert.equal(free.state, 'locked');
    assert.equal(free.action, 'unlock');
    assert.equal(free.limit, null);

    const enforced = view(conversation(), { enforced: true });
    assert.equal(enforced.state, 'locked');
    assert.equal(enforced.action, null, 'an enforced lock offers no unlock');
    assert.equal(enforced.limit, 'enforced');
    assert.match(scopeLockControlLabel(enforced), /locked\. View details\./i);
});

check('locking is allowed even while the administrator enforces the lock', () => {
    const relock = view(conversation({ scope_locked: false }), { enforced: true });
    assert.equal(relock.state, 'unlocked');
    assert.equal(relock.action, 'lock');
    assert.equal(relock.limit, null);
});

check('an unlocked conversation with nothing recorded cannot be locked to nothing', () => {
    const empty = view(conversation({ scope_locked: false, locked_contexts: [], context: [] }));
    assert.equal(empty.state, 'unlocked');
    assert.equal(empty.action, null);
    assert.equal(empty.limit, 'nothing_recorded');
});

check('a personal conversation is changed by its owner, a shared one by anyone who can post', () => {
    const stranger = view(conversation({ user_id: 'someone-else' }));
    assert.equal(stranger.action, null);
    assert.equal(stranger.limit, 'owner_only');
    assert.equal(view(conversation({ user_id: '' })).action, 'unlock', 'an absent owner is left to the server');
    assert.equal(view(conversation(), { viewerId: null }).action, 'unlock', 'so is an absent viewer');

    const shared = { conversation_kind: 'collaborative', user_id: 'creator' };
    assert.equal(view(conversation({ ...shared, can_post_messages: true })).action, 'unlock');
    // A participant who did not create it may still change it.
    assert.equal(view(conversation({ ...shared, can_post_messages: true }), { viewerId: 'participant' }).action, 'unlock');
    for (const can_post_messages of [false, undefined, 'true']) {
        const blocked = view(conversation({ ...shared, can_post_messages }));
        assert.equal(blocked.action, null, `can_post_messages ${String(can_post_messages)} is not permission`);
        assert.equal(blocked.limit, 'shared_participant');
    }
});

// --- wording -------------------------------------------------------------------------------------

check('the dialog says what the lock does, in the classic modal\'s words', () => {
    const unlock = scopeLockCopy(view(conversation()), 'unlock');
    assert.equal(unlock.title, 'Unlock workspace scope');
    assert.match(unlock.description, /prevent accidental cross-contamination/);
    assert.equal(unlock.listLabel, 'Currently locked to:');
    assert.equal(unlock.confirmLabel, 'Unlock scope');
    assert.equal(unlock.noticeTone, 'warn');
    assert.match(unlock.notice, /lock it again later/);

    const lock = scopeLockCopy(view(conversation({ scope_locked: false })), 'lock');
    assert.equal(lock.title, 'Lock workspace scope');
    assert.equal(lock.listLabel, 'Will lock to:');
    assert.equal(lock.confirmLabel, 'Lock scope');
    assert.match(lock.notice, /Sources you already added from other workspaces must be removed/);
});

check('a dialog that cannot change anything explains why, with no confirm button', () => {
    const enforced = scopeLockCopy(view(conversation(), { enforced: true }), null);
    assert.equal(enforced.title, 'Workspace scope is locked');
    assert.equal(enforced.confirmLabel, '');
    assert.equal(enforced.notice, 'Workspace scope lock is enforced by your administrator. The scope cannot be unlocked.');

    const shared = scopeLockCopy(view(conversation({ conversation_kind: 'collaborative' })), null);
    assert.match(shared.notice, /Only people who can post in this conversation/);
    const owner = scopeLockCopy(view(conversation({ user_id: 'someone-else' })), null);
    assert.match(owner.notice, /Only the owner/);
    const empty = scopeLockCopy(view(conversation({ scope_locked: false, locked_contexts: [], context: [] })), null);
    assert.equal(empty.title, 'Workspace scope is unlocked');
    assert.match(empty.notice, /nothing to lock it to/);
});

check('the dialog keeps the intent it opened with while the state changes under it', () => {
    const opened = view(conversation());
    assert.equal(opened.action, 'unlock');
    // What the view becomes the instant the optimistic write lands.
    const flipped = view(conversation({ scope_locked: false }));
    assert.equal(flipped.action, 'lock');
    const copy = scopeLockCopy(flipped, opened.action);
    assert.equal(copy.title, 'Unlock workspace scope', 'the title must not flip to "Lock" mid-request');
    assert.equal(copy.confirmLabel, 'Unlock scope');
});

// --- the request and its answer ------------------------------------------------------------------

check('the request body holds a real boolean, which is all the route accepts', () => {
    assert.deepEqual(scopeLockRequestBody(true), { scope_locked: true });
    assert.deepEqual(scopeLockRequestBody(false), { scope_locked: false });
    assert.equal(JSON.stringify(scopeLockRequestBody(false)), '{"scope_locked":false}');
});

check('the answer is reduced to the two fields a change writes', () => {
    const held = [{ scope: 'group', id: GROUP }];
    assert.deepEqual(
        confirmedScopeLock({ success: true, scope_locked: false, locked_contexts: [{ scope: 'public', id: PUBLIC }] }, false, held),
        { scope_locked: false, locked_contexts: [{ scope: 'public', id: PUBLIC }] },
    );
    assert.deepEqual(confirmedScopeLock({ success: true }, true, held), { scope_locked: true, locked_contexts: held },
        'a body missing both fields falls back to what was asked for and what was held');
    assert.deepEqual(confirmedScopeLock(null, false, held), { scope_locked: false, locked_contexts: held });
    assert.deepEqual(confirmedScopeLock({ scope_locked: 'yes', locked_contexts: 'all' }, true, undefined),
        { scope_locked: true, locked_contexts: undefined }, 'wrong types are ignored rather than trusted');
});

check('error text comes from the server when it sent any', () => {
    assert.equal(scopeLockErrorMessage(new Error('Scope unlock is disabled by administrator'), false), 'Scope unlock is disabled by administrator');
    assert.match(scopeLockErrorMessage(new Error('  '), true), /could not be locked/);
    assert.match(scopeLockErrorMessage('nope', false), /could not be unlocked/);
});

check('lock fields are written onto metadata without touching the rest of it', () => {
    const metadata = conversation({ summary: { content: 'kept' } });
    const written = withScopeLockFields(metadata, { scope_locked: false, locked_contexts: [{ scope: 'public', id: PUBLIC }] });
    assert.equal(written.scope_locked, false);
    assert.deepEqual(written.locked_contexts, [{ scope: 'public', id: PUBLIC }]);
    assert.deepEqual(written.summary, { content: 'kept' });
    assert.equal(written.title, 'Quarterly plan');
    assert.equal(metadata.scope_locked, true, 'the original is not mutated');
});

// --- the change itself ---------------------------------------------------------------------------

interface Harness {
    effects: ScopeLockEffects;
    state: { fields: ScopeLockFields | null };
    log: string[];
}

function harness(
    send: (locked: boolean) => Promise<unknown>,
    initial: ScopeLockFields | null = { scope_locked: true, locked_contexts: [{ scope: 'group', id: GROUP }] },
): Harness {
    const state = { fields: initial };
    const log: string[] = [];
    return {
        state,
        log,
        effects: {
            read: () => (state.fields ? { ...state.fields } : null),
            write: (fields) => {
                log.push(`write:${String(fields.scope_locked)}`);
                if (state.fields) state.fields = { ...fields };
            },
            send: (locked) => {
                log.push(`send:${String(locked)}`);
                return send(locked);
            },
            refresh: () => {
                log.push('refresh');
            },
        },
    };
}

check('a change shows its result before the server answers, then confirms and refreshes', async () => {
    let release: (value: unknown) => void = () => undefined;
    const run = harness(() => new Promise((resolve) => { release = resolve; }));
    const pending = changeScopeLock(false, run.effects);

    // The press is answered at once: the optimistic write precedes the request and outlives it.
    await Promise.resolve();
    assert.deepEqual(run.log, ['write:false', 'send:false']);
    assert.equal(run.state.fields?.scope_locked, false);

    release({ success: true, scope_locked: false, locked_contexts: [{ scope: 'group', id: GROUP }] });
    const result = await pending;
    assert.deepEqual(result, { ok: true });
    assert.deepEqual(run.log, ['write:false', 'send:false', 'write:false', 'refresh']);
    assert.deepEqual(run.state.fields?.locked_contexts, [{ scope: 'group', id: GROUP }], 'unlocking keeps the workspaces');
});

check('a refusal puts back exactly what was held and says why', async () => {
    const run = harness(() => Promise.reject(new Error('Scope unlock is disabled by administrator')));
    const result = await changeScopeLock(false, run.effects);
    assert.deepEqual(result, { ok: false, message: 'Scope unlock is disabled by administrator' });
    assert.equal(run.state.fields?.scope_locked, true, 'rolled back');
    assert.deepEqual(run.state.fields?.locked_contexts, [{ scope: 'group', id: GROUP }]);
    assert.deepEqual(run.log, ['write:false', 'send:false', 'write:true'], 'and no refresh for a change that did not happen');
});

check('a rollback never overwrites a newer read of the conversation', async () => {
    // While the request was in flight a metadata read landed with the server's own answer.
    let landed = false;
    const run = harness(async () => {
        run.state.fields = { scope_locked: true, locked_contexts: [{ scope: 'public', id: PUBLIC }] };
        landed = true;
        throw new Error('Failed to update scope lock');
    });
    const result = await changeScopeLock(false, run.effects);
    assert.equal(result.ok, false);
    assert.ok(landed);
    // The state already reads `true`, so there is no optimistic value left to undo; the newer read stands.
    assert.deepEqual(run.state.fields?.locked_contexts, [{ scope: 'public', id: PUBLIC }]);
    assert.equal(run.log.filter((entry) => entry.startsWith('write:')).length, 1, 'only the optimistic write happened');
});

check('a change for a conversation that is not loaded sends nothing', async () => {
    const run = harness(() => Promise.resolve({}), null);
    const result = await changeScopeLock(true, run.effects);
    assert.equal(result.ok, false);
    assert.deepEqual(run.log, [], 'no write, no request');
});

check('locking writes the workspaces the server returned', async () => {
    const run = harness(
        async () => ({ success: true, scope_locked: true, locked_contexts: [{ scope: 'group', id: GROUP }, { scope: 'personal', id: 'user-1' }] }),
        { scope_locked: false, locked_contexts: [{ scope: 'group', id: GROUP }] },
    );
    assert.deepEqual(await changeScopeLock(true, run.effects), { ok: true });
    assert.equal(run.state.fields?.scope_locked, true);
    assert.equal(run.state.fields?.locked_contexts?.length, 2);
});

let failed = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
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
console.log(`${checks.length} scope lock logic checks passed`);
