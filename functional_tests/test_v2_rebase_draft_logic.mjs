// test_v2_rebase_draft_logic.mjs
//
// Runtime test for the shared conflict-rebase helper the group editors use.
// Version: 0.261.151
// Implemented in: 0.261.151
//
// After a save conflict every group editor reloaded only the write token and re-sent the whole
// stale draft, silently overwriting the other writer's changes to fields the user never touched --
// the lost update the token exists to prevent. `rebaseDraft` merges the reloaded record into the
// open draft field by field: an untouched field adopts the other writer's value, an edited field
// keeps the user's, and a field both sides changed to different values keeps the user's and is
// reported by its label. Secrets are never compared or copied into a notice: a typed value is kept,
// a blank input adopts the reloaded stored state.
//
// These rules are pure, so they are exercised here against the real module rather than inferred
// from the rendered editors. Run directly with `node functional_tests/test_v2_rebase_draft_logic.mjs`.
// Requires Node 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';

import './test_support/tsResolve.mjs';

const {
    rebaseDraft,
    deepEqual,
    rebaseNotice,
    REBASE_NOTICE,
    REBASE_DELETED_NOTICE,
} = await import('../application/v2_ui/src/lib/rebaseDraft.ts');

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/** A representative editable projection with a nested object, an array, and a secret pair. */
function baseRecord(overrides = {}) {
    return {
        id: 'r-1',
        name: 'Nightly sync',
        description: 'Original description',
        enabled: true,
        includePatterns: ['*.pdf'],
        connection: { directoryPath: '/data', accountUrl: 'https://a.example' },
        secretStored: true,
        credentials: { username: 'svc', secret: '' },
        ...overrides,
    };
}

const FIELDS = [
    { path: 'name', label: 'Name' },
    { path: 'description', label: 'Description' },
    { path: 'enabled', label: 'Enabled' },
    { path: 'includePatterns', label: 'Include patterns' },
    { path: 'connection.directoryPath', label: 'Path' },
    { path: 'connection.accountUrl', label: 'Account URL' },
    { path: 'secretStored', label: 'Secret stored' },
    { path: 'credentials.secret', label: 'Secret', secret: true },
];

/* --------------------------------- deepEqual --------------------------------- */

check('deepEqual compares scalars, arrays and plain objects structurally', () => {
    assert.equal(deepEqual(1, 1), true);
    assert.equal(deepEqual('a', 'a'), true);
    assert.equal(deepEqual(null, null), true);
    assert.equal(deepEqual([1, 2], [1, 2]), true);
    assert.equal(deepEqual([1, 2], [2, 1]), false);
    assert.equal(deepEqual({ a: 1, b: { c: 2 } }, { a: 1, b: { c: 2 } }), true);
    assert.equal(deepEqual({ a: 1 }, { a: 1, b: 2 }), false);
    assert.equal(deepEqual(1, '1'), false);
});

/* --------------------------- untouched fields adopt fresh -------------------- */

check('a field the user did not touch adopts the other writer\'s value', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ description: 'Changed by someone else' });
    const draft = baseRecord();
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.description, 'Changed by someone else');
    assert.deepEqual(conflicts, []);
});

check('a nested untouched field adopts the reloaded value', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ connection: { directoryPath: '/moved', accountUrl: 'https://a.example' } });
    const draft = baseRecord();
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.connection.directoryPath, '/moved');
    assert.deepEqual(conflicts, []);
});

check('an untouched array field adopts the reloaded array', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ includePatterns: ['*.docx', '*.txt'] });
    const draft = baseRecord();
    const { draft: rebased } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.deepEqual(rebased.includePatterns, ['*.docx', '*.txt']);
});

/* ------------------------------ edits are kept ------------------------------- */

check('a field the user edited keeps the user\'s value when the other writer left it alone', () => {
    const baseline = baseRecord();
    const fresh = baseRecord();
    const draft = baseRecord({ name: 'My new name' });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.name, 'My new name');
    assert.deepEqual(conflicts, []);
});

check('both writers changing a field to the same value is not a conflict', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ name: 'Agreed name' });
    const draft = baseRecord({ name: 'Agreed name' });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.name, 'Agreed name');
    assert.deepEqual(conflicts, []);
});

/* ------------------------------ true conflicts ------------------------------- */

check('a field both sides changed to different values keeps the user\'s and is reported by label', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ name: 'Their name' });
    const draft = baseRecord({ name: 'My name' });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.name, 'My name');
    assert.deepEqual(conflicts, ['Name']);
});

check('several independent edits merge, with only the doubly-changed field reported', () => {
    const baseline = baseRecord();
    // The other writer moved the path and the description; the user renamed and changed the path.
    const fresh = baseRecord({
        description: 'Their description',
        connection: { directoryPath: '/their-path', accountUrl: 'https://a.example' },
    });
    const draft = baseRecord({
        name: 'User name',
        connection: { directoryPath: '/my-path', accountUrl: 'https://a.example' },
    });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.name, 'User name'); // user-only edit kept
    assert.equal(rebased.description, 'Their description'); // untouched by user, adopts theirs
    assert.equal(rebased.connection.directoryPath, '/my-path'); // both changed -> user's kept
    assert.deepEqual(conflicts, ['Path']);
});

/* --------------------------------- secrets ----------------------------------- */

check('a typed secret is kept and never reported, even when the stored state changed', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ secretStored: false, credentials: { username: 'svc', secret: '' } });
    const draft = baseRecord({ credentials: { username: 'svc', secret: 'freshly-typed' } });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.credentials.secret, 'freshly-typed');
    assert.deepEqual(conflicts, []);
});

check('a blank secret input adopts the reloaded stored state without a value', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ credentials: { username: 'svc', secret: '' } });
    const draft = baseRecord({ credentials: { username: 'svc', secret: '   ' } });
    const { draft: rebased } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.credentials.secret, '');
});

check('the stored-secret flag rebases as an ordinary field', () => {
    // The other writer rotated the secret, so the stored flag flips; the user never touched it.
    const baseline = baseRecord({ secretStored: true });
    const fresh = baseRecord({ secretStored: false });
    const draft = baseRecord({ secretStored: true });
    const { draft: rebased, conflicts } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.secretStored, false);
    assert.deepEqual(conflicts, []);
});

/* --------------------------------- purity ------------------------------------ */

check('rebaseDraft does not mutate the inputs and deep-clones the result', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ connection: { directoryPath: '/moved', accountUrl: 'https://a.example' } });
    const draft = baseRecord({ name: 'Edited' });
    const { draft: rebased } = rebaseDraft(baseline, fresh, draft, FIELDS);
    // Mutating the result must not reach the fresh record it was cloned from.
    rebased.connection.directoryPath = '/mutated';
    rebased.includePatterns.push('*.zip');
    assert.equal(fresh.connection.directoryPath, '/moved');
    assert.deepEqual(fresh.includePatterns, ['*.pdf']);
    assert.equal(draft.name, 'Edited');
});

check('a field absent from the spec is left as the draft holds it', () => {
    const baseline = baseRecord();
    const fresh = baseRecord({ id: 'r-2' });
    const draft = baseRecord();
    // `id` is not in FIELDS, so the reloaded id is not adopted.
    const { draft: rebased } = rebaseDraft(baseline, fresh, draft, FIELDS);
    assert.equal(rebased.id, 'r-1');
});

/* --------------------------------- notices ----------------------------------- */

check('the no-conflict notice is the plain reload message', () => {
    assert.equal(rebaseNotice([]), REBASE_NOTICE);
    assert.match(REBASE_NOTICE, /their changes are loaded; your edits are kept/i);
});

check('the conflict notice names the fields both sides changed', () => {
    const notice = rebaseNotice(['Name', 'Path']);
    assert.ok(notice.startsWith(REBASE_NOTICE));
    assert.match(notice, /You and someone else both changed: Name, Path\. Your values are shown\./);
});

check('the deleted notice tells the user to copy and close', () => {
    assert.match(REBASE_DELETED_NOTICE, /deleted/i);
    assert.match(REBASE_DELETED_NOTICE, /close/i);
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`ok   ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL ${name}`);
        console.log(`     ${error.message}`);
        failed += 1;
    }
}

console.log(`\n${passed}/${passed + failed} runtime checks passed`);
process.exit(failed > 0 ? 1 : 0);
