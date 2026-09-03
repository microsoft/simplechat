// test_v2_conversation_multiselect_logic.ts
// Behavioural checks for the V2 conversation rail's multi-selection.
//
// Version: 0.261.056
// Implemented in: 0.261.056
//
// The V2 interface has no unit test runner, so this follows test_v2_conversation_export_logic.ts:
// it is bundled with the esbuild Vite already brings in and run under node by
// test_v2_conversation_multiselect.py, which skips it when the front-end toolchain is absent.
//
// What it protects, in rough order of how expensive the mistake would be:
//
//   - A shared conversation must never be posted to the personal bulk routes. Those match on
//     `user_id`, so the id comes back in `failed_ids` and nothing happens — a silent no-op on
//     a delete the user believes succeeded.
//   - Removing a shared conversation must be a leave unless the user may genuinely delete it.
//     Guessing wrong either destroys a thread other people are using, or is refused.
//   - Bulk pin must set rather than toggle, and must skip shared rows already in the target
//     state, because the collaboration route toggles and would flip them the wrong way.
//   - A range must follow the list as displayed, and a selection must not survive the rows it
//     named leaving the page.

import {
    applySelection,
    EMPTY_SELECTION,
    isEverythingSelected,
    pruneSelection,
    selectionIntentFromEvent,
    toggleSelectAll,
    type SelectionState,
} from '../application/v2_ui/src/lib/listSelection';
import {
    collaborativeIdsNeedingPin,
    collaborativeRemovals,
    partialFailureMessage,
    partitionBySpecies,
    pinActionFor,
    removalActionFor,
    removalConfirmLabel,
    removalDescription,
    removalTitle,
    selectedConversations,
    summarizeRemoval,
} from '../application/v2_ui/src/lib/conversationSelection';
import type { Conversation } from '../application/v2_ui/src/lib/types';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/** Build a rail row. Personal unless `shared` is set. */
function conversation(
    id: string,
    options: {
        title?: string;
        pinned?: boolean;
        shared?: boolean;
        canDelete?: boolean;
    } = {},
): Conversation {
    const row: Conversation = {
        id,
        title: options.title ?? `Conversation ${id}`,
        is_pinned: options.pinned ?? false,
    };
    if (options.shared) {
        // Matches COLLABORATION_KIND, which is what isCollaborative() reads.
        row.conversation_kind = 'collaborative';
        row.can_delete_conversation = options.canDelete ?? false;
    }
    return row;
}

/* ---- modifier keys ---- */

check(
    'a plain click replaces the selection',
    selectionIntentFromEvent({}) === 'replace',
);
check(
    'Ctrl+click toggles',
    selectionIntentFromEvent({ ctrlKey: true }) === 'toggle',
);
check(
    'Cmd+click toggles, so macOS behaves like Windows',
    selectionIntentFromEvent({ metaKey: true }) === 'toggle',
);
check(
    'Shift wins over Ctrl when both are held',
    selectionIntentFromEvent({ shiftKey: true, ctrlKey: true }) === 'range',
);

/* ---- selection algebra ---- */

const ordered = ['a', 'b', 'c', 'd', 'e'];

const afterFirstClick = applySelection(EMPTY_SELECTION, 'b', 'replace', ordered);
check(
    'a first click selects one row and anchors there',
    afterFirstClick.ids.join(',') === 'b' && afterFirstClick.anchorId === 'b',
    afterFirstClick,
);

const afterShift = applySelection(afterFirstClick, 'd', 'range', ordered);
check(
    'Shift+click spans the anchor to the click, in list order',
    afterShift.ids.join(',') === 'b,c,d',
    afterShift.ids,
);

const shorter = applySelection(afterShift, 'c', 'range', ordered);
check(
    'a second Shift+click corrects the range rather than adding to it',
    shorter.ids.join(',') === 'b,c' && shorter.anchorId === 'b',
    shorter,
);

const backwards = applySelection(
    { ids: ['d'], anchorId: 'd' },
    'b',
    'range',
    ordered,
);
check(
    'a range works upwards as well as downwards',
    backwards.ids.join(',') === 'b,c,d',
    backwards.ids,
);

const toggled = applySelection({ ids: ['a', 'c'], anchorId: 'c' }, 'e', 'toggle', ordered);
check(
    'Ctrl+click adds a row and keeps the result in list order',
    toggled.ids.join(',') === 'a,c,e',
    toggled.ids,
);

const untoggled = applySelection(toggled, 'c', 'toggle', ordered);
check(
    'Ctrl+click on a selected row removes it',
    untoggled.ids.join(',') === 'a,e',
    untoggled.ids,
);

// A range read from the selection rather than from the list would span the wrong rows once
// pinning has re-sorted the rail.
const resorted = ['e', 'a', 'b', 'c', 'd'];
const acrossResort = applySelection({ ids: ['e'], anchorId: 'e' }, 'b', 'range', resorted);
check(
    'a range follows the list as displayed, not the order ids were picked in',
    acrossResort.ids.join(',') === 'e,a,b',
    acrossResort.ids,
);

const all = toggleSelectAll(EMPTY_SELECTION, ordered);
check('select-all takes every loaded row', all.ids.length === 5, all.ids);
check(
    'select-all clears when everything is already selected',
    toggleSelectAll(all, ordered).ids.length === 0,
);
check(
    'an empty list does not report itself as fully selected',
    !isEverythingSelected(EMPTY_SELECTION.ids, []),
);
check(
    'a partial selection is not reported as fully selected',
    !isEverythingSelected(['a'], ordered),
);
check(
    'every row selected reports as fully selected',
    isEverythingSelected(ordered, ordered),
);

const stale: SelectionState = { ids: ['a', 'z'], anchorId: 'z' };
const pruned = pruneSelection(stale, ordered);
check(
    'ids that have left the page are dropped from the selection',
    pruned.ids.join(',') === 'a',
    pruned.ids,
);
check(
    'an anchor that has left the page is replaced rather than kept',
    pruned.anchorId === 'a',
    pruned.anchorId,
);

/* ---- resolving a selection against the list ---- */

const rows = [
    conversation('p1'),
    conversation('p2', { pinned: true }),
    conversation('s1', { shared: true, canDelete: true }),
    conversation('s2', { shared: true, canDelete: false }),
];

check(
    'a selection resolves to rows in list order, not click order',
    selectedConversations(rows, ['s1', 'p1']).map((row) => row.id).join(',') === 'p1,s1',
);
check(
    'an id with no matching row is dropped rather than acted on',
    selectedConversations(rows, ['p1', 'gone']).length === 1,
);

/* ---- the personal / shared split ---- */

const split = partitionBySpecies(rows);
check(
    'personal conversations are batched for the bulk routes',
    split.personalIds.join(',') === 'p1,p2',
    split.personalIds,
);
check(
    'shared conversations are kept out of the bulk routes',
    split.collaborativeIds.join(',') === 's1,s2',
    split.collaborativeIds,
);
check(
    'the two halves account for every selected row and overlap nowhere',
    split.personalIds.length + split.collaborativeIds.length === rows.length &&
        split.personalIds.every((id) => !split.collaborativeIds.includes(id)),
);

/* ---- delete versus leave ---- */

const removals = collaborativeRemovals(rows);
check(
    'only shared conversations need a per-row removal decision',
    removals.length === 2,
    removals,
);
check(
    'an owner deletes',
    removals.find((removal) => removal.id === 's1')?.action === 'delete',
);
check(
    'a participant leaves, so the thread survives for everybody else',
    removals.find((removal) => removal.id === 's2')?.action === 'leave',
);
check(
    'a missing permission flag is treated as leave, which is the safe direction',
    collaborativeRemovals([conversation('s3', { shared: true })])[0].action === 'leave',
);
check(
    'a personal conversation is always a deletion',
    removalActionFor(conversation('p1')) === 'delete',
);

// The confirmation and the request must be decided by the same rule, or the dialog can
// promise a leave and perform a delete — destroying a thread other people are using.
for (const row of [
    conversation('p1'),
    conversation('s1', { shared: true, canDelete: true }),
    conversation('s2', { shared: true, canDelete: false }),
    conversation('s3', { shared: true }),
]) {
    const summary = summarizeRemoval([row]);
    const promisedLeave = summary.leaveCount === 1;
    check(
        `what the dialog promises for ${row.id} is what the request performs`,
        promisedLeave === (removalActionFor(row) === 'leave') &&
            promisedLeave === (removalConfirmLabel(summary) === 'Leave'),
        { row: row.id, summary, action: removalActionFor(row) },
    );
}

/* ---- pin ---- */

check(
    'a selection with anything unpinned pins',
    pinActionFor([conversation('a', { pinned: true }), conversation('b')]) === 'pin',
);
check(
    'a selection that is entirely pinned unpins',
    pinActionFor([conversation('a', { pinned: true }), conversation('b', { pinned: true })]) ===
        'unpin',
);
check(
    'an empty selection reports a stable label rather than throwing',
    pinActionFor([]) === 'pin',
);

const mixedShared = [
    conversation('s1', { shared: true, pinned: true }),
    conversation('s2', { shared: true, pinned: false }),
    conversation('p1', { pinned: false }),
];
check(
    'only shared rows not already pinned are toggled towards pinned',
    collaborativeIdsNeedingPin(mixedShared, 'pin').join(',') === 's2',
    collaborativeIdsNeedingPin(mixedShared, 'pin'),
);
check(
    'only shared rows not already unpinned are toggled towards unpinned',
    collaborativeIdsNeedingPin(mixedShared, 'unpin').join(',') === 's1',
    collaborativeIdsNeedingPin(mixedShared, 'unpin'),
);
check(
    'personal rows never go through the collaboration toggle',
    !collaborativeIdsNeedingPin(mixedShared, 'pin').includes('p1'),
);

/* ---- what the confirmation promises ---- */

const deletingOnly = summarizeRemoval([conversation('p1'), conversation('p2')]);
check(
    'a personal selection is entirely a deletion',
    deletingOnly.deleteCount === 2 && deletingOnly.leaveCount === 0,
    deletingOnly,
);
check('two conversations get a plural title', removalTitle(deletingOnly) === 'Delete conversations');

const leavingOnly = summarizeRemoval([conversation('s2', { shared: true, canDelete: false })]);
check(
    'a shared conversation the user cannot delete counts as a leave',
    leavingOnly.leaveCount === 1 && leavingOnly.deleteCount === 0,
    leavingOnly,
);
check(
    'the user is never told they are deleting something they can only leave',
    removalTitle(leavingOnly) === 'Leave conversation' &&
        removalConfirmLabel(leavingOnly) === 'Leave' &&
        !removalDescription(leavingOnly).toLowerCase().includes('delet'),
    removalDescription(leavingOnly),
);

const mixedRemoval = summarizeRemoval(rows);
check(
    'a mixed selection counts deletes and leaves apart',
    mixedRemoval.deleteCount === 3 && mixedRemoval.leaveCount === 1,
    mixedRemoval,
);
check(
    'a mixed selection says so rather than claiming one or the other',
    removalTitle(mixedRemoval) === 'Delete and leave conversations' &&
        removalDescription(mixedRemoval).includes('3') &&
        removalDescription(mixedRemoval).includes('1'),
    removalDescription(mixedRemoval),
);

const single = summarizeRemoval([conversation('p1', { title: 'Quarterly numbers' })]);
check(
    'a single deletion names the conversation, so the wrong row is obvious',
    single.onlyTitle === 'Quarterly numbers' &&
        removalDescription(single).includes('Quarterly numbers'),
    removalDescription(single),
);
check(
    'an untitled conversation still gets a name to show',
    summarizeRemoval([conversation('p1', { title: '' })]).onlyTitle === 'Untitled conversation',
);

/* ---- partial failure ---- */

check(
    'nothing is reported when the whole batch lands',
    partialFailureMessage(5, 0, 'delete', 'deleted') === null,
);
const partial = partialFailureMessage(5, 2, 'delete', 'deleted');
check(
    'a partial failure reports what did and did not happen',
    partial !== null && partial.includes('3 of 5') && partial.includes('2'),
    partial,
);
check(
    'a total failure says so plainly rather than counting',
    partialFailureMessage(3, 3, 'delete', 'deleted') === 'Could not delete those conversations.',
    partialFailureMessage(3, 3, 'delete', 'deleted'),
);
check(
    'a single total failure is phrased in the singular',
    partialFailureMessage(1, 1, 'hide', 'hidden') === 'Could not hide that conversation.',
);
check(
    'the past tense is supplied rather than guessed, so "hide" never becomes "hided"',
    (partialFailureMessage(4, 1, 'hide', 'hidden') ?? '').includes('hidden'),
    partialFailureMessage(4, 1, 'hide', 'hidden'),
);

if (failures > 0) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
}
