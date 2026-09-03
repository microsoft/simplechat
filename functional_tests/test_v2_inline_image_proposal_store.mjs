// test_v2_inline_image_proposal_store.mjs
//
// Runtime test for the V2 image proposal store.
// Version: 0.261.050
// Implemented in: 0.261.050
//
// The store is where two things that cost real money are decided: whether a second approval may
// be sent for a card that already has one running, and whether an approval in flight is still
// described anywhere after the view that started it has gone. Both are invisible until they are
// wrong -- a duplicate approval renders as a perfectly ordinary second image on the bill, and a
// lost record renders as a card politely inviting the user to generate something they are
// already generating.
//
// Unlike its sibling `test_v2_inline_image_proposal_resume_logic.mjs`, this imports a module
// that depends on `zustand`, so it needs `npm install` to have been run in
// `application/v2_ui`. The Python wrapper skips it when that has not happened rather than
// reporting an environment as a defect.
//
// Run directly with `node functional_tests/test_v2_inline_image_proposal_store.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module can be imported.

import assert from 'node:assert/strict';
import { register } from 'node:module';

// The application's relative imports have no file extension, because Vite and TypeScript
// resolve them. Node does not, and its TypeScript support strips types rather than resolving
// like a bundler, so importing a module that imports another module fails outright. The sibling
// test avoids this by only importing leaf modules; the store is not one, and the properties it
// owns -- refusing a duplicate approval, and remembering one across a reload -- are worth more
// than the fifteen lines of resolver needed to reach them.
register(
    'data:text/javascript,' +
        encodeURIComponent(
            [
                "const EXTENSIONS = ['.ts', '.tsx', '.js', '.mjs', '.json'];",
                'export async function resolve(specifier, context, next) {',
                '    const relative = specifier.startsWith(".");',
                '    const extensionless =',
                '        relative && !EXTENSIONS.some((ext) => specifier.endsWith(ext));',
                '    if (extensionless) {',
                '        return next(specifier + ".ts", context);',
                '    }',
                '    return next(specifier, context);',
                '}',
            ].join('\n'),
        ),
);

/** A stand-in for the browser, installed before the store's storage helper reads it. */
function installFakeWindow() {
    const data = new Map();
    globalThis.window = {
        sessionStorage: {
            getItem: (key) => (data.has(key) ? data.get(key) : null),
            setItem: (key, value) => data.set(key, String(value)),
            removeItem: (key) => data.delete(key),
        },
    };
    return data;
}

const storage = installFakeWindow();

const { APPROVAL_STORAGE_KEY, approvalRecordId } = await import(
    '../application/v2_ui/src/lib/imageProposalTracking.ts'
);
const { useImageProposalStore, selectCardStates, selectInFlightCount } = await import(
    '../application/v2_ui/src/stores/imageProposalStore.ts'
);

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

const NOW = Date.now();

function reset() {
    storage.clear();
    useImageProposalStore.setState({
        cards: {},
        inFlight: {},
        visibleConversationId: null,
        settledGenerated: 0,
        settledFailed: 0,
    });
}

function approval(overrides = {}) {
    return {
        conversationId: 'conv-1',
        assistantMessageId: 'msg-1',
        cardKey: 'block:0',
        visualId: 'slide_09',
        title: 'Timeline',
        prompt: 'Draw a timeline',
        startedAt: NOW,
        ...overrides,
    };
}

function stored() {
    const raw = storage.get(APPROVAL_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
}

/* ------------------------------- duplicate guard ------------------------------ */

check('a second approval for the same card is refused', () => {
    reset();
    assert.equal(useImageProposalStore.getState().beginApproval(approval()), true);
    assert.equal(useImageProposalStore.getState().beginApproval(approval()), false);
    assert.equal(Object.keys(useImageProposalStore.getState().inFlight).length, 1);
});

check('two cards in one message are tracked separately', () => {
    // "Approve all" starts one approval per card, and they must not collapse into one record
    // or the second image would never be tracked at all.
    reset();
    useImageProposalStore.getState().beginApproval(approval({ cardKey: 'block:0' }));
    useImageProposalStore.getState().beginApproval(approval({ cardKey: 'block:1' }));
    assert.equal(Object.keys(useImageProposalStore.getState().inFlight).length, 2);
});

check('the same card in two conversations is tracked separately', () => {
    reset();
    useImageProposalStore.getState().beginApproval(approval({ conversationId: 'conv-1' }));
    useImageProposalStore.getState().beginApproval(approval({ conversationId: 'conv-2' }));
    assert.equal(selectInFlightCount(useImageProposalStore.getState(), 'conv-1'), 1);
    assert.equal(selectInFlightCount(useImageProposalStore.getState(), 'conv-2'), 1);
});

check('a card may be approved again once its first approval has ended', () => {
    // A failed approval has to be retryable, so the guard is on the record, not on the card.
    reset();
    const id = approvalRecordId('conv-1', 'msg-1', 'block:0');
    useImageProposalStore.getState().beginApproval(approval());
    useImageProposalStore.getState().endApproval(id, 'failed');
    assert.equal(useImageProposalStore.getState().beginApproval(approval()), true);
});

/* -------------------------------- persistence -------------------------------- */

check('an approval is written to storage as it starts', () => {
    reset();
    useImageProposalStore.getState().beginApproval(approval());

    const records = stored();
    assert.equal(records.length, 1);
    assert.equal(records[0].conversationId, 'conv-1');
    assert.equal(records[0].cardKey, 'block:0');
    assert.equal(records[0].prompt, 'Draw a timeline');
});

check('ending an approval takes it out of storage', () => {
    reset();
    useImageProposalStore.getState().beginApproval(approval());
    useImageProposalStore
        .getState()
        .endApproval(approvalRecordId('conv-1', 'msg-1', 'block:0'), 'generated');
    assert.equal(stored(), null);
});

check('ending an approval that is not tracked changes nothing', () => {
    // Reachable: the card clears its record when the image appears, and the image can appear
    // after the approval's own response has already cleared it.
    reset();
    useImageProposalStore.getState().beginApproval(approval());
    useImageProposalStore.getState().endApproval('no-such-record', 'generated');
    assert.equal(Object.keys(useImageProposalStore.getState().inFlight).length, 1);
    assert.equal(useImageProposalStore.getState().settledGenerated, 0);
});

/* ---------------------------------- restore ---------------------------------- */

check('a restored record puts its card back into the generating state', () => {
    reset();
    useImageProposalStore
        .getState()
        .restoreApprovals([{ ...approval(), resumed: true }]);

    const states = selectCardStates(useImageProposalStore.getState(), 'conv-1', 'msg-1');
    assert.equal(states['block:0'].status, 'generating');
    assert.equal(states['block:0'].resumed, true);
});

check('a restore does not overwrite an approval this page started', () => {
    // The live record has a request behind it and can settle itself; the restored one cannot.
    // Taking the restored one would turn a live approval into a polled one for no reason.
    reset();
    useImageProposalStore.getState().beginApproval(approval());
    useImageProposalStore.getState().restoreApprovals([{ ...approval(), resumed: true }]);

    const record =
        useImageProposalStore.getState().inFlight[approvalRecordId('conv-1', 'msg-1', 'block:0')];
    assert.equal(record.resumed, false);
});

check('restoring nothing leaves the store alone', () => {
    reset();
    const before = useImageProposalStore.getState();
    useImageProposalStore.getState().restoreApprovals([]);
    assert.equal(useImageProposalStore.getState().cards, before.cards);
});

/* --------------------------------- card state -------------------------------- */

check('card state is addressed by conversation and message', () => {
    reset();
    const store = useImageProposalStore.getState();
    store.updateCardState('conv-1', 'msg-1', 'block:0', { status: 'queued' });
    store.updateCardState('conv-2', 'msg-1', 'block:0', { status: 'error', failure: 'no' });

    assert.equal(
        selectCardStates(useImageProposalStore.getState(), 'conv-1', 'msg-1')['block:0'].status,
        'queued',
    );
    assert.equal(
        selectCardStates(useImageProposalStore.getState(), 'conv-2', 'msg-1')['block:0'].status,
        'error',
    );
});

check('one card cannot disturb another in the same message', () => {
    reset();
    const store = useImageProposalStore.getState();
    store.updateCardState('conv-1', 'msg-1', 'block:0', { status: 'generating' });
    store.updateCardState('conv-1', 'msg-1', 'block:1', { status: 'error', failure: 'nope' });

    const states = selectCardStates(useImageProposalStore.getState(), 'conv-1', 'msg-1');
    assert.equal(states['block:0'].status, 'generating');
    assert.equal(states['block:0'].failure, '');
});

check('a patch that changes nothing does not replace the map', () => {
    // The approval queue reports its position to every waiting card each time it moves, and
    // most of those reports say what the card already knows. A new object each time would
    // re-render every card in the message for no visible change.
    reset();
    useImageProposalStore.getState().updateCardState('conv-1', 'msg-1', 'block:0', {
        status: 'queued',
        queuePosition: 2,
    });
    const before = useImageProposalStore.getState().cards;
    useImageProposalStore.getState().updateCardState('conv-1', 'msg-1', 'block:0', {
        queuePosition: 2,
    });
    assert.equal(useImageProposalStore.getState().cards, before);
});

check('card state without an address is not filed anywhere', () => {
    // The assistant message id is empty until a reply has finished streaming.
    reset();
    useImageProposalStore.getState().updateCardState('conv-1', '', 'block:0', { status: 'queued' });
    assert.deepEqual(useImageProposalStore.getState().cards, {});
});

/* ---------------------------------- outcomes --------------------------------- */

check('outcomes are counted so a batch can be reported', () => {
    reset();
    const store = useImageProposalStore.getState();
    store.beginApproval(approval({ cardKey: 'block:0' }));
    store.beginApproval(approval({ cardKey: 'block:1' }));
    store.endApproval(approvalRecordId('conv-1', 'msg-1', 'block:0'), 'generated');
    store.endApproval(approvalRecordId('conv-1', 'msg-1', 'block:1'), 'failed');

    assert.equal(useImageProposalStore.getState().settledGenerated, 1);
    assert.equal(useImageProposalStore.getState().settledFailed, 1);

    useImageProposalStore.getState().clearSettled();
    assert.equal(useImageProposalStore.getState().settledGenerated, 0);
    assert.equal(useImageProposalStore.getState().settledFailed, 0);
});

/* --------------------------------- visibility -------------------------------- */

check('the visible conversation is remembered and can be cleared', () => {
    // What the away notice counts. Leaving the chat page clears it, which is the difference
    // between "another conversation is open" and "these cards are not on screen at all".
    reset();
    useImageProposalStore.getState().setVisibleConversation('conv-1');
    assert.equal(useImageProposalStore.getState().visibleConversationId, 'conv-1');

    const unchanged = useImageProposalStore.getState();
    useImageProposalStore.getState().setVisibleConversation('conv-1');
    assert.equal(useImageProposalStore.getState(), unchanged);

    useImageProposalStore.getState().setVisibleConversation(null);
    assert.equal(useImageProposalStore.getState().visibleConversationId, null);
});

/* ---------------------------------- pruning ---------------------------------- */

check('pruning keeps the open conversation and anything still generating', () => {
    reset();
    const store = useImageProposalStore.getState();
    store.updateCardState('conv-open', 'msg-1', 'block:0', { status: 'cancelled' });
    store.updateCardState('conv-busy', 'msg-1', 'block:0', { status: 'generating' });
    store.updateCardState('conv-gone', 'msg-1', 'block:0', { status: 'generated' });
    store.beginApproval(approval({ conversationId: 'conv-busy' }));

    useImageProposalStore.getState().pruneSettled('conv-open');
    const cards = useImageProposalStore.getState().cards;

    assert.equal(Object.keys(cards).some((key) => key.startsWith('conv-open')), true);
    assert.equal(Object.keys(cards).some((key) => key.startsWith('conv-busy')), true);
    assert.equal(Object.keys(cards).some((key) => key.startsWith('conv-gone')), false);
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
