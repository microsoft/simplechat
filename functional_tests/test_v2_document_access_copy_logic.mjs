// test_v2_document_access_copy_logic.mjs
// Version: 0.261.168
// Implemented in: 0.261.167
// A refused upload from a viewer who holds other operations says why no upload can happen: 0.261.168
// Executes the real V2 access copy (lib/documentAccessCopy.ts) and the operation adapter's hint
// recognition (lib/documentOperations.ts). An empty shared explorer tells a viewer who can't upload
// who can add documents, or why no one can in the workspace's status, in the group's or the public
// workspace's own words; a viewer the server grants no document operation is told the same when
// they try one, and one who holds other operations is told why no upload can happen, in the empty
// explorer's words. Any other refused operation is a per-document decision and keeps the explorer's
// generic answer. A missing or unknown management hint is never read as a role: it asks for a
// refresh. Nothing points at the classic workspace, which applies the same policy.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    documentManagementRefusal, documentUploadUnavailable, sharedOperationRefusal,
} = await import('../application/v2_ui/src/lib/documentAccessCopy.ts');
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
            assert.equal(documentUploadUnavailable(scope, { status, advertised: true }), expectedEmpty(scope, status), `${scope} ${status}`);
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
                documentUploadUnavailable(scope, { status, advertised: false }),
                `This ${noun}'s document permissions couldn't be confirmed. Refresh this workspace to check whether you can add documents.`,
            );
            assert.equal(
                documentManagementRefusal(scope, { status, advertised: false }),
                `This ${noun}'s document permissions couldn't be confirmed. Refresh this workspace before managing documents.`,
            );
        }
    }
});

check('a refused operation is answered for the viewer the server grants no operation, in every operation', () => {
    for (const scope of ['group', 'public']) {
        for (const status of STATUSES) {
            for (const advertised of [true, false]) {
                const access = { status, advertised };
                for (const operation of ['upload', 'edit_metadata', 'tag_documents', 'delete', 'download']) {
                    assert.equal(
                        sharedOperationRefusal(scope, operation, new Set(), access), documentManagementRefusal(scope, access),
                        `${scope} ${status} ${advertised} ${operation}`,
                    );
                }
            }
        }
    }
});

check('a refused upload from a viewer who holds other operations says why no upload can happen', () => {
    // A locked manager keeps downloads, and an uploads-disabled manager keeps deletion and reprocessing.
    for (const supported of [new Set(['download']), new Set(['delete', 'download', 'reprocess'])]) {
        for (const scope of ['group', 'public']) {
            for (const status of STATUSES) {
                const access = { status, advertised: true };
                const answer = sharedOperationRefusal(scope, 'upload', supported, access);
                assert.equal(answer, documentUploadUnavailable(scope, access), `${scope} ${status}`);
                assert.equal(answer, expectedEmpty(scope, status), `${scope} ${status}`);
            }
        }
    }
});

check('any other refusal is a per-document decision and keeps the generic answer', () => {
    const access = { status: 'upload_disabled', advertised: true };
    for (const scope of ['group', 'public']) {
        assert.equal(sharedOperationRefusal(scope, 'delete', new Set(['download']), access), null);
        assert.equal(sharedOperationRefusal(scope, 'edit_metadata', new Set(['delete', 'download', 'reprocess']), access), null);
        assert.equal(sharedOperationRefusal(scope, 'delete', new Set(['delete', 'download', 'reprocess']), access), null);
        // Upload is granted, so a refusal comes from elsewhere (a busy or refreshing explorer).
        assert.equal(sharedOperationRefusal(scope, 'upload', new Set(['upload', 'download']), access), null);
    }
});

check('the copy is scope-honest, never points at classic, and never repeats the empty heading', () => {
    for (const scope of ['group', 'public']) {
        for (const status of STATUSES) {
            for (const advertised of [true, false]) {
                for (const text of [
                    documentUploadUnavailable(scope, { status, advertised }),
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
