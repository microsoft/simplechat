// test_v2_document_access_copy_logic.mjs
// Version: 0.261.167
// Implemented in: 0.261.167
// Executes the real V2 access copy (lib/documentAccessCopy.ts) and the operation adapter's hint
// recognition (lib/documentOperations.ts). An empty shared explorer tells a viewer who can't upload
// who can add documents, or why no one can in the workspace's status, in the group's or the public
// workspace's own words; a viewer the server grants no document operation is told the same when
// they try one. A missing or unknown management hint is never read as a role: it asks for a refresh.
// Nothing points at the classic workspace, which applies the same policy.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { documentManagementRefusal, emptyDocumentsDescription } = await import('../application/v2_ui/src/lib/documentAccessCopy.ts');
const {
    PERSONAL_DOCUMENT_OPERATIONS, createGroupDocumentOperations, createPublicDocumentOperations,
} = await import('../application/v2_ui/src/lib/documentOperations.ts');

let checks = 0;

function check(name, run) {
    run();
    checks += 1;
    console.log(`ok ${name}`);
}

const NOUN = { group: 'group', public: 'public workspace' };
const STATUSES = ['active', 'upload_disabled', 'locked', 'inactive', 'unknown', undefined];

function expectedEmpty(scope, status) {
    const noun = NOUN[scope];
    if (status === 'upload_disabled') return `Document uploads are disabled for this ${noun}.`;
    if (status === 'locked') return `This ${noun} is locked (read-only), so documents can't be added.`;
    if (status === 'inactive' || status === 'unknown') return `Documents can't be added to this ${noun} in its current status.`;
    return `This ${noun}'s owner, admins and document managers can add documents.`;
}

function expectedRefusal(scope, status) {
    const noun = NOUN[scope];
    if (status === 'locked') return `This ${noun} is locked (read-only), so its documents can't be changed.`;
    if (status === 'inactive' || status === 'unknown') return `This ${noun}'s documents can't be changed in its current status.`;
    return `Only this ${noun}'s owner, admins and document managers can manage its documents.`;
}

check('an empty explorer says who can add documents, or why no one can, in each status', () => {
    for (const scope of ['group', 'public']) {
        for (const status of STATUSES) {
            assert.equal(emptyDocumentsDescription(scope, { status, advertised: true }), expectedEmpty(scope, status), `${scope} ${status}`);
        }
    }
});

check('a refused change names the roles that manage documents, or the status that stops everyone', () => {
    for (const scope of ['group', 'public']) {
        for (const status of STATUSES) {
            assert.equal(documentManagementRefusal(scope, { status, advertised: true }), expectedRefusal(scope, status), `${scope} ${status}`);
        }
    }
});

check('an unrecognized management hint asks for a refresh instead of naming a role, in any status', () => {
    for (const scope of ['group', 'public']) {
        const noun = NOUN[scope];
        for (const status of STATUSES) {
            assert.equal(
                emptyDocumentsDescription(scope, { status, advertised: false }),
                `This ${noun}'s document permissions couldn't be confirmed. Refresh this workspace to check whether you can add documents.`,
            );
            assert.equal(
                documentManagementRefusal(scope, { status, advertised: false }),
                `This ${noun}'s document permissions couldn't be confirmed. Refresh this workspace before managing documents.`,
            );
        }
    }
});

check('the copy is scope-honest, never points at classic, and never repeats the empty heading', () => {
    for (const scope of ['group', 'public']) {
        for (const status of STATUSES) {
            for (const advertised of [true, false]) {
                for (const text of [
                    emptyDocumentsDescription(scope, { status, advertised }),
                    documentManagementRefusal(scope, { status, advertised }),
                ]) {
                    assert.doesNotMatch(text, /classic/i);
                    assert.doesNotMatch(text, /no documents yet/i);
                    assert.match(text, /\.$/);
                    if (scope === 'group') assert.doesNotMatch(text, /public workspace/);
                    else assert.doesNotMatch(text, /\bgroup\b/);
                }
            }
        }
    }
});

check('the adapter records whether the server management hint was recognized', () => {
    const group = { kind: 'group', id: 'group-a', name: 'Research group' };
    const workspace = { kind: 'public', id: 'pub-a', name: 'Research library' };
    for (const create of [
        (hint) => createGroupDocumentOperations(group, hint),
        (hint) => createPublicDocumentOperations(workspace, hint),
    ]) {
        const reader = create({ schema_version: 1, operations: [] });
        assert.equal(reader.advertised, true);
        assert.equal(reader.supported.size, 0);
        assert.equal(create({ schema_version: 1, operations: ['download', 'future'] }).advertised, true);
        for (const unrecognized of [undefined, null, {}, { schema_version: 99, operations: ['upload'] },
            { schema_version: 1 }, { schema_version: 1, operations: 'upload' }, { schema_version: 1, operations: [1] }]) {
            const adapter = create(unrecognized);
            assert.equal(adapter.advertised, false, JSON.stringify(unrecognized));
            assert.equal(adapter.supported.size, 0);
        }
    }
    assert.equal(PERSONAL_DOCUMENT_OPERATIONS.advertised, true);
    assert.equal(PERSONAL_DOCUMENT_OPERATIONS.supported.has('upload'), true);
});

console.log(`${checks} document access copy checks passed.`);
