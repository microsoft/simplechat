// test_v2_inline_image_proposal_resume_logic.mjs
//
// Runtime test for resuming a V2 image approval after the page that started it is gone.
// Version: 0.261.053
// Implemented in: 0.261.053
//
// The companion test, test_v2_inline_image_proposal_resume.py, proves the pieces are wired
// together. This one executes the rules that decide whether a user gets their image back.
//
// Every failure mode here is silent. A matcher that is too eager settles an approval against
// somebody else's image, and the card shows the wrong picture with no error anywhere. A matcher
// that is too strict never settles, so the card spins until it is written off and the user is
// told to pay for an image they already have. A storage round-trip that loses a field produces
// a record that can never match, which looks exactly like the second case.
//
// Run directly with `node functional_tests/test_v2_inline_image_proposal_resume_logic.mjs`.
// Requires Node 22.6 or newer, which strips the TypeScript types so the real modules can be
// imported rather than a copy of them.

import assert from 'node:assert/strict';
import {
    APPROVAL_STORAGE_KEY,
    GIVE_UP_AFTER_MS,
    STALE_RECORD_MS,
    approvalRecordId,
    earliestStart,
    hasExpired,
    loadApprovals,
    matchesTrackedApproval,
    saveApprovals,
} from '../application/v2_ui/src/lib/imageProposalTracking.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

const NOW = Date.parse('2026-09-03T12:00:00.000Z');

function record(overrides = {}) {
    return {
        conversationId: 'conv-1',
        assistantMessageId: 'msg-1',
        cardKey: 'block:0',
        visualId: 'slide_09_timeline',
        title: 'Timeline',
        prompt: 'Draw a timeline',
        startedAt: NOW,
        resumed: false,
        ...overrides,
    };
}

function candidate(overrides = {}) {
    return {
        message_id: 'img-1',
        created_at: new Date(NOW + 30_000).toISOString(),
        source_assistant_message_id: 'msg-1',
        visual_id: 'slide_09_timeline',
        title: 'Timeline',
        prompt: 'Draw a timeline',
        ...overrides,
    };
}

/** A stand-in for sessionStorage, so the storage rules can be run without a browser. */
function fakeStorage(initial = {}) {
    const data = { ...initial };
    return {
        data,
        getItem: (key) => (key in data ? data[key] : null),
        setItem: (key, value) => {
            data[key] = String(value);
        },
        removeItem: (key) => {
            delete data[key];
        },
    };
}

/* ---------------------------------- identity --------------------------------- */

check('a record id names one card in one message in one conversation', () => {
    const id = approvalRecordId('conv-1', 'msg-1', 'block:0');

    assert.notEqual(id, approvalRecordId('conv-2', 'msg-1', 'block:0'));
    assert.notEqual(id, approvalRecordId('conv-1', 'msg-2', 'block:0'));
    assert.notEqual(id, approvalRecordId('conv-1', 'msg-1', 'block:1'));
    assert.equal(id, approvalRecordId('conv-1', 'msg-1', 'block:0'));
});

check('ids cannot collide by running their parts together', () => {
    // A separator that can appear in an id would let two different cards share a record, and
    // the second approval would then be silently refused as a duplicate of the first.
    assert.notEqual(
        approvalRecordId('a', 'b:c', 'd'),
        approvalRecordId('a', 'b', 'c:d'),
    );
});

/* ---------------------------------- matching --------------------------------- */

check('matches the image its own approval produced', () => {
    assert.equal(matchesTrackedApproval(record(), candidate()), true);
});

check('will not take an image proposed by a different message', () => {
    // Two replies in one conversation can propose the same picture in the same words. Without
    // this the first reply's card would claim the second reply's image.
    assert.equal(
        matchesTrackedApproval(record(), candidate({ source_assistant_message_id: 'msg-2' })),
        false,
    );
});

check('will not take an image that predates the approval', () => {
    // The reachable shape: a proposal already generated once, approved again after a reload.
    // Matching the older image would settle the new approval instantly against the wrong file.
    assert.equal(
        matchesTrackedApproval(
            record(),
            candidate({ created_at: new Date(NOW - 10 * 60_000).toISOString() }),
        ),
        false,
    );
});

check('tolerates a clock that disagrees with the server by under a minute', () => {
    // Browser and server clocks drift. A strict comparison would refuse the approval's own
    // image whenever the server was a few seconds behind, which fails closed but wastes money.
    assert.equal(
        matchesTrackedApproval(
            record(),
            candidate({ created_at: new Date(NOW - 20_000).toISOString() }),
        ),
        true,
    );
});

check('an image with no timestamp is still eligible', () => {
    assert.equal(matchesTrackedApproval(record(), candidate({ created_at: undefined })), true);
});

check('the visual id decides on its own when there is one', () => {
    // It is the only field the guidance asks the model to make unique, so a mismatch is a
    // different proposal even if everything a human reads is identical.
    assert.equal(
        matchesTrackedApproval(record(), candidate({ visual_id: 'slide_10_map' })),
        false,
    );
    assert.equal(
        matchesTrackedApproval(
            record(),
            candidate({ visual_id: 'slide_09_timeline', title: 'Something else', prompt: 'other' }),
        ),
        true,
    );
});

check('a visual id normalised differently by the server still matches', () => {
    // The server reduces a visual id to a known character set; the record keeps what the model
    // wrote. Comparing them verbatim would strand every proposal whose id needed cleaning.
    assert.equal(
        matchesTrackedApproval(
            record({ visualId: 'Slide 09 Timeline' }),
            candidate({ visual_id: 'Slide_09_Timeline' }),
        ),
        true,
    );
});

check('falls back to the prompt when the model gave no visual id', () => {
    const withoutId = record({ visualId: '' });
    assert.equal(matchesTrackedApproval(withoutId, candidate({ visual_id: '' })), true);
    assert.equal(
        matchesTrackedApproval(withoutId, candidate({ visual_id: '', prompt: 'Draw a map' })),
        false,
    );
});

check('the prompt is compared with its line breaks flattened', () => {
    // The record holds the prompt as approved, which may be multi-line; the server stores it
    // through a trim that collapses whitespace. A verbatim comparison would never match an
    // edited multi-line prompt.
    assert.equal(
        matchesTrackedApproval(
            record({ visualId: '', prompt: 'Draw a timeline\n  of the period' }),
            candidate({ visual_id: '', prompt: 'Draw a timeline of the period' }),
        ),
        true,
    );
});

check('falls back to the title only when there is nothing better', () => {
    const titleOnly = record({ visualId: '', prompt: '' });
    assert.equal(
        matchesTrackedApproval(titleOnly, candidate({ visual_id: '', prompt: 'anything' })),
        true,
    );
    assert.equal(
        matchesTrackedApproval(titleOnly, candidate({ visual_id: '', title: 'Other' })),
        false,
    );
});

check('a record with nothing to match on never matches', () => {
    // Better to write the approval off than to attach the card to an arbitrary image.
    const empty = record({ visualId: '', prompt: '', title: '' });
    assert.equal(matchesTrackedApproval(empty, candidate({ visual_id: '', title: '' })), false);
});

/* ----------------------------------- window ---------------------------------- */

check('the poll window starts before the earliest approval', () => {
    const since = earliestStart([
        record({ startedAt: NOW }),
        record({ startedAt: NOW - 60_000 }),
    ]);
    assert.equal(Date.parse(since) <= NOW - 60_000, true);
});

check('no records means no window', () => {
    assert.equal(earliestStart([]), undefined);
});

check('an approval is written off once, and only after the deadline', () => {
    assert.equal(hasExpired(record(), NOW + GIVE_UP_AFTER_MS - 1_000), false);
    assert.equal(hasExpired(record(), NOW + GIVE_UP_AFTER_MS + 1_000), true);
});

/* ---------------------------------- storage ---------------------------------- */

check('a saved record comes back with every field it needs to match', () => {
    const storage = fakeStorage();
    saveApprovals([record()], storage);

    const [restored] = loadApprovals(storage, NOW + 1_000);
    assert.equal(restored.conversationId, 'conv-1');
    assert.equal(restored.assistantMessageId, 'msg-1');
    assert.equal(restored.cardKey, 'block:0');
    assert.equal(restored.visualId, 'slide_09_timeline');
    assert.equal(restored.prompt, 'Draw a timeline');
    assert.equal(restored.startedAt, NOW);
    assert.equal(matchesTrackedApproval(restored, candidate()), true);
});

check('a restored record knows it has no request behind it', () => {
    // The card says something different for a resumed approval, and only polling can settle
    // one, so a record that came back from storage must never claim to be live.
    const storage = fakeStorage();
    saveApprovals([record({ resumed: false })], storage);
    assert.equal(loadApprovals(storage, NOW)[0].resumed, true);
});

check('an empty set removes the entry rather than storing an empty list', () => {
    const storage = fakeStorage();
    saveApprovals([record()], storage);
    saveApprovals([], storage);
    assert.equal(storage.getItem(APPROVAL_STORAGE_KEY), null);
});

check('a record older than the stale bound is not resumed', () => {
    // A tab reopened much later must not claim to be waiting for work that finished long ago.
    const storage = fakeStorage();
    saveApprovals([record()], storage);
    assert.equal(loadApprovals(storage, NOW + STALE_RECORD_MS - 1_000).length, 1);
    assert.equal(loadApprovals(storage, NOW + STALE_RECORD_MS + 1_000).length, 0);
});

check('unreadable storage yields no records rather than throwing', () => {
    // Storage is shared with whatever else wrote to it, and it is read during startup, so a
    // bad value has to cost the recovery and nothing else.
    assert.deepEqual(loadApprovals(fakeStorage({ [APPROVAL_STORAGE_KEY]: 'not json' }), NOW), []);
    assert.deepEqual(loadApprovals(fakeStorage({ [APPROVAL_STORAGE_KEY]: '{}' }), NOW), []);
    assert.deepEqual(
        loadApprovals(fakeStorage({ [APPROVAL_STORAGE_KEY]: '[{"conversationId":"c"}]' }), NOW),
        [],
    );
    assert.deepEqual(loadApprovals(null, NOW), []);
});

check('saving into storage that refuses writes does not throw', () => {
    const hostile = {
        getItem: () => null,
        setItem: () => {
            throw new Error('QuotaExceededError');
        },
        removeItem: () => {
            throw new Error('QuotaExceededError');
        },
    };
    saveApprovals([record()], hostile);
    saveApprovals([], hostile);
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
