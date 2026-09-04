// test_v2_chat_context_request.ts
//
// Runtime test for how the V2 composer's context chips become a chat request.
// Version: 0.261.089
// Implemented in: 0.261.089
//
// These are the decisions that turn "the user picked a document" into fields the server acts
// on, and each one fails as a wrong answer rather than an error:
//
//   - `_build_document_content_filter` defaults to `intersection`, so a picked document AND a
//     picked tag must both match. A chip row holding one of each would return nothing at all
//     unless the composer asks for `union`.
//   - `hybrid_search` off while documents are named collects a selection, sends it, and has
//     the server ignore it.
//   - A group document whose group id is not in `active_group_ids` is filtered out server-side
//     by `_get_authorized_chat_scope_context`. The document is simply absent from the answer,
//     with nothing to say why.
//   - `build_tags_filter` joins tags with `and`, so sending one twice narrows the search.
//
// Run by test_v2_chat_context_picker.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping when the front-end toolchain is absent.
// Bundling rather than running directly is what resolves the extensionless imports between
// chatContext, chatContextTokens and documentExplorer.

import assert from 'node:assert/strict';
import {
    PERSONAL_SCOPE,
    addContextItem,
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
    describeContextGroup,
    documentContextItem,
    groupContextItems,
    groupScope,
    publicScope,
    removeContextItem,
    scopeContextItem,
    tagContextItem,
} from '../application/v2_ui/src/lib/chatContext';
import { resolveDocumentScope } from '../application/v2_ui/src/lib/documentScope';

const MARKETING = groupScope({ id: 'grp-1', name: 'Marketing' });
const LEGAL = groupScope({ id: 'grp-2', name: 'Legal' });
const HANDBOOK = publicScope({ id: 'pub-1', name: 'Handbook' });

const checks: Array<[string, () => void]> = [];
function check(name: string, run: () => void) {
    checks.push([name, run]);
}

function doc(id: string, title: string, scope = PERSONAL_SCOPE, existing: never[] | ReturnType<typeof documentContextItem>[] = []) {
    return documentContextItem({ id, title, file_name: `${title}.pdf` }, scope, existing);
}

/* -------------------------------------------------------------------------- */
/* Identity                                                                    */
/* -------------------------------------------------------------------------- */

check('a document is identified by its id, not its title', () => {
    // Two files can share a title. Keying on the label would silently collapse them into one.
    const first = doc('a', 'Contract');
    const second = doc('b', 'Contract', PERSONAL_SCOPE, [first]);

    assert.notEqual(first.key, second.key);
    assert.notEqual(first.token, second.token);

    const items = addContextItem(addContextItem([], first), second);
    assert.deepEqual(contextDocumentIds(items), ['a', 'b']);
});

check('the same document is not added twice', () => {
    const item = doc('a', 'Contract');
    const items = addContextItem(addContextItem([], item), item);
    assert.equal(items.length, 1);
});

check('the same tag in two workspaces is two chips but one filter', () => {
    // Each chip widens the scope to its own workspace, but `build_tags_filter` joins names
    // with `and`, so sending "urgent" twice would require a document to carry it twice.
    const personal = tagContextItem('urgent', PERSONAL_SCOPE);
    const marketing = tagContextItem('urgent', MARKETING, [personal]);
    const items = [personal, marketing];

    assert.equal(items.length, 2);
    assert.deepEqual(contextTags(items), ['urgent']);
    assert.deepEqual(contextScopes(items).groupIds, ['grp-1']);
});

check('tag de-duplication ignores case', () => {
    const items = [tagContextItem('Urgent', PERSONAL_SCOPE), tagContextItem('urgent', MARKETING)];
    assert.deepEqual(contextTags(items), ['Urgent']);
});

check('removing a chip removes only that one', () => {
    const first = doc('a', 'A');
    const second = doc('b', 'B', PERSONAL_SCOPE, [first]);
    assert.deepEqual(
        contextDocumentIds(removeContextItem([first, second], first.key)),
        ['b'],
    );
});

/* -------------------------------------------------------------------------- */
/* Filter mode                                                                 */
/* -------------------------------------------------------------------------- */

check('documents and tags together are sent as additive', () => {
    // Without this the server ANDs them and a document that does not carry the tag is
    // excluded -- so the row shows two chips and the search returns nothing.
    const items = [doc('a', 'Contract'), tagContextItem('urgent', PERSONAL_SCOPE)];
    assert.equal(contextFilterMode(items), 'union');
});

check('one kind alone sends no mode at all', () => {
    // With a single kind the mode has no effect, and an unnecessary field is one more thing
    // to account for later.
    assert.equal(contextFilterMode([doc('a', 'A')]), undefined);
    assert.equal(contextFilterMode([tagContextItem('urgent', PERSONAL_SCOPE)]), undefined);
    assert.equal(contextFilterMode([]), undefined);
});

/* -------------------------------------------------------------------------- */
/* Scope                                                                       */
/* -------------------------------------------------------------------------- */

check('no chips leaves the deployment scope untouched', () => {
    assert.deepEqual(resolveDocumentScope(undefined), {
        doc_scope: 'personal',
        active_group_ids: [],
        active_group_id: null,
        active_public_workspace_ids: [],
        active_public_workspace_id: null,
    });
});

check('a group chip makes its group reachable', () => {
    // The whole point: without the id in active_group_ids the server filters the document out
    // and the answer is missing it with no explanation.
    const items = [doc('a', 'Brief', MARKETING)];
    const scope = resolveDocumentScope({
        contextGroupIds: contextScopes(items).groupIds,
    });

    assert.equal(scope.doc_scope, 'all');
    assert.deepEqual(scope.active_group_ids, ['grp-1']);
    assert.equal(scope.active_group_id, 'grp-1');
});

check('chips from several workspaces all travel', () => {
    const items = [
        doc('a', 'Brief', MARKETING),
        doc('b', 'Policy', LEGAL),
        doc('c', 'Handbook', HANDBOOK),
        doc('d', 'Notes'),
    ];
    const workspaces = contextScopes(items);
    const scope = resolveDocumentScope({
        contextGroupIds: workspaces.groupIds,
        contextPublicWorkspaceIds: workspaces.publicWorkspaceIds,
    });

    assert.equal(workspaces.includesPersonal, true);
    assert.deepEqual(scope.active_group_ids, ['grp-1', 'grp-2']);
    assert.deepEqual(scope.active_public_workspace_ids, ['pub-1']);
    assert.equal(scope.doc_scope, 'all');
});

check('the active workspace is kept alongside the chips', () => {
    // Someone working inside a group who pins a personal document must not lose the group.
    const scope = resolveDocumentScope({
        activeGroupId: 'grp-active',
        contextGroupIds: ['grp-1'],
    });
    assert.deepEqual(scope.active_group_ids, ['grp-active', 'grp-1']);
});

check('a workspace named twice is sent once', () => {
    const scope = resolveDocumentScope({
        activeGroupId: 'grp-1',
        contextGroupIds: ['grp-1', 'grp-1'],
    });
    assert.deepEqual(scope.active_group_ids, ['grp-1']);
});

check('a whole-workspace chip widens the scope without pinning documents', () => {
    // Enumerating the workspace here would freeze it as it was when the chip was added.
    const items = [scopeContextItem(MARKETING)];
    assert.deepEqual(contextDocumentIds(items), []);
    assert.deepEqual(contextScopes(items).groupIds, ['grp-1']);
});

/* -------------------------------------------------------------------------- */
/* Presentation                                                                */
/* -------------------------------------------------------------------------- */

check('chips group by workspace, personal first', () => {
    const items = [
        doc('a', 'Brief', HANDBOOK),
        doc('b', 'Policy', MARKETING),
        doc('c', 'Notes'),
    ];
    assert.deepEqual(
        groupContextItems(items).map((group) => group.scope.name),
        ['My workspace', 'Marketing', 'Handbook'],
    );
});

check('a collapsed group counts each kind', () => {
    const items = [
        doc('a', 'A', MARKETING),
        doc('b', 'B', MARKETING),
        tagContextItem('urgent', MARKETING),
    ];
    assert.equal(describeContextGroup(items), '2 documents and 1 tag');
    assert.equal(describeContextGroup([items[2]]), '1 tag');
});

check('a document with no extracted title falls back to its file name', () => {
    const item = documentContextItem(
        { id: 'a', file_name: 'MSA_v2_FINAL(3).docx' },
        PERSONAL_SCOPE,
    );
    assert.equal(item.label, 'MSA_v2_FINAL(3).docx');
    assert.equal(item.token, '#[MSA_v2_FINAL(3).docx]');
});

/* -------------------------------------------------------------------------- */

let failed = 0;
for (const [name, run] of checks) {
    try {
        run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`);
        console.error(`        ${(error as Error).message}`);
    }
}

console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed === 0 ? 0 : 1);
