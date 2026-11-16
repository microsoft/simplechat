// test_v2_conversation_reference_tokens.mjs
//
// Runtime test for the `~[…]` conversation reference grammar and portable reference helpers.
// Version: 0.261.381
// Implemented in: 0.261.381
//
// Run directly with `node functional_tests/test_v2_conversation_reference_tokens.mjs`.

import assert from 'node:assert/strict';

await import(new URL('./test_support/tsResolve.mjs', import.meta.url));
const {
    CONVERSATION_REFERENCE_LIMIT,
    CONVERSATION_REFERENCE_MIME,
    addConversationReference,
    conversationReferenceRequests,
    insertConversationToken,
    isPrivateConversation,
    parseConversationTokens,
    portableConversationReference,
    readClipboardConversationReference,
    readConversationQuery,
    readPortableConversationReference,
    reconcileConversationReferences,
    removeConversationToken,
    storedConversationReferences,
} = await import('../application/v2_ui/src/lib/conversationReferences.ts');

const checks = [];
function check(name, run) {
    checks.push([name, run]);
}

/* -------------------------------------------------------------------------- */
/* Query detection                                                             */
/* -------------------------------------------------------------------------- */

check('a tilde at the start or after whitespace opens a conversation query', () => {
    assert.deepEqual(readConversationQuery('~', 1), { query: '', start: 0, end: 1 });
    assert.deepEqual(readConversationQuery('compare ~budg', 13), { query: 'budg', start: 8, end: 13 });
    assert.deepEqual(readConversationQuery('first line\n~plan', 16), { query: 'plan', start: 11, end: 16 });
});

check('a tilde mid-word does not open a query', () => {
    assert.equal(readConversationQuery('foo~bar', 7), null);
    assert.equal(readConversationQuery('approx~10', 9), null);
});

check('markdown strikethrough ~~ does not open a query', () => {
    assert.equal(readConversationQuery('~~strike', 2), null);
    assert.equal(readConversationQuery('~~strike~~', 8), null);
    assert.equal(readConversationQuery('text ~~old', 10), null);
});

check('paths such as ~/notes or ~\\notes do not open a query', () => {
    assert.equal(readConversationQuery('~/notes', 7), null);
    assert.equal(readConversationQuery('check ~/config/settings.json', 28), null);
    assert.equal(readConversationQuery('~\\AppData', 9), null);
});

check('a tilde followed by whitespace or inside a completed token is ignored', () => {
    assert.equal(readConversationQuery('~ approximately', 2), null);
    assert.equal(readConversationQuery('~[Budget review]', 1), null);
    assert.equal(readConversationQuery('~[Budget review]', 16), null);
});

check('tildes inside inline code or fenced code blocks do not open a query', () => {
    assert.equal(readConversationQuery('use `~budget` here', 12), null);
    assert.equal(readConversationQuery('```\n~budget\n```', 11), null);
    assert.equal(readConversationQuery('~~~\n~budget\n~~~', 11), null);
    assert.deepEqual(readConversationQuery('`code` ~budget', 14), { query: 'budget', start: 7, end: 14 });
});

/* -------------------------------------------------------------------------- */
/* Token parsing                                                               */
/* -------------------------------------------------------------------------- */

check('parseConversationTokens finds valid ~[Title] tokens outside code', () => {
    const text = 'Compare ~[Q3 Budget] with `~[Ignored Inline]` and ~[Architecture Notes]';
    assert.deepEqual(
        parseConversationTokens(text).map((entry) => entry.token),
        ['~[Q3 Budget]', '~[Architecture Notes]'],
    );
});

check('parseConversationTokens ignores tokens inside fenced code blocks or mid-word', () => {
    const text = 'word~[NotValid]\n```\n~[InFence]\n```\n~[Real Conversation]';
    assert.deepEqual(
        parseConversationTokens(text).map((entry) => entry.token),
        ['~[Real Conversation]'],
    );
});

/* -------------------------------------------------------------------------- */
/* Duplicate titles, insertion, removal, and reconciliation                    */
/* -------------------------------------------------------------------------- */

check('duplicate conversation titles receive disambiguated ~[Title (2)] tokens', () => {
    let refs = [];
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-1', title: 'Weekly Sync' }, 'mention');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-2', title: 'Weekly Sync' }, 'mention');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-3', title: 'Weekly Sync [Draft]' }, 'mention');

    assert.equal(refs[0].token, '~[Weekly Sync]');
    assert.equal(refs[1].token, '~[Weekly Sync (2)]');
    assert.equal(refs[2].token, '~[Weekly Sync (Draft)]');
});

check('re-adding an existing conversation upgrades attachment to both without duplicating', () => {
    let refs = [];
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-1', title: 'Roadmap' }, 'selection');
    assert.equal(refs[0].attachment, 'selection');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-1', title: 'Roadmap' }, 'mention');
    assert.equal(refs.length, 1);
    assert.equal(refs[0].attachment, 'both');
});

check('enforces the five-conversation reference limit', () => {
    let refs = [];
    for (let i = 1; i <= CONVERSATION_REFERENCE_LIMIT; i += 1) {
        refs = addConversationReference(refs, { kind: 'conversation', id: `conv-${i}`, title: `Chat ${i}` }, 'selection');
    }
    assert.throws(
        () => addConversationReference(refs, { kind: 'conversation', id: 'conv-6', title: 'Chat 6' }, 'selection'),
        /at most five conversation sources/i,
    );
});

check('insertConversationToken and removeConversationToken preserve clean spacing', () => {
    const startText = 'Summarize ~bud';
    const query = readConversationQuery(startText, startText.length);
    const inserted = insertConversationToken(startText, query.start, query.end, '~[Budget Thread]');
    assert.equal(inserted.text, 'Summarize ~[Budget Thread] ');

    const removed = removeConversationToken(`${inserted.text}for leadership`, '~[Budget Thread]');
    assert.equal(removed, 'Summarize for leadership');
});

check('reconcileConversationReferences drops removed mentions while keeping selections and downgrading both', () => {
    let refs = [];
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-mention', title: 'Mentioned' }, 'mention');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-select', title: 'Selected' }, 'selection');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-both', title: 'Combined' }, 'selection');
    refs = addConversationReference(refs, { kind: 'conversation', id: 'conv-both', title: 'Combined' }, 'mention');

    const withAll = reconcileConversationReferences('See ~[Mentioned] and ~[Combined]', refs);
    assert.equal(withAll.length, 3);
    assert.equal(withAll.find((item) => item.id === 'conv-both')?.attachment, 'both');

    const afterTextDelete = reconcileConversationReferences('No inline tokens left', withAll);
    assert.deepEqual(
        afterTextDelete.map((item) => [item.id, item.attachment]),
        [
            ['conv-select', 'selection'],
            ['conv-both', 'selection'],
        ],
    );
});

/* -------------------------------------------------------------------------- */
/* Portable reference parsing and origin validation                            */
/* -------------------------------------------------------------------------- */

check('portableConversationReference round-trips only for matching origin and /v2/chat path', () => {
    const origin = 'https://simplechat.example.org';
    const token = portableConversationReference({ kind: 'conversation', id: 'conv_123' }, origin);
    assert.equal(token, 'simplechat-conversation:v1:https://simplechat.example.org/v2/chat?conversationId=conv_123');
    assert.deepEqual(readPortableConversationReference(token, origin), { kind: 'conversation', id: 'conv_123' });

    // Cross-origin or wrong path or invalid id is rejected.
    assert.equal(readPortableConversationReference(token, 'https://other.example.org'), null);
    assert.equal(
        readPortableConversationReference('simplechat-conversation:v1:https://simplechat.example.org/chats?conversationId=conv_123', origin),
        null,
    );
    assert.equal(
        readPortableConversationReference('simplechat-conversation:v1:https://simplechat.example.org/v2/chat?conversationId=../bad', origin),
        null,
    );
});

check('readClipboardConversationReference supports both plain text and custom MIME', () => {
    const origin = 'http://simplechat.test';
    const portable = portableConversationReference({ kind: 'conversation', id: 'alpha-1' }, origin);
    const plainClipboard = {
        getData: (type) => (type === 'text/plain' ? portable : ''),
    };
    assert.deepEqual(readClipboardConversationReference(plainClipboard, origin), {
        kind: 'conversation',
        id: 'alpha-1',
    });

    const mimeClipboard = {
        getData: (type) => (type === CONVERSATION_REFERENCE_MIME
            ? JSON.stringify({ kind: 'conversation', id: 'beta-2', origin })
            : ''),
    };
    assert.deepEqual(readClipboardConversationReference(mimeClipboard, origin), {
        kind: 'conversation',
        id: 'beta-2',
    });
});

check('conversationReferenceRequests deduplicates and filters invalid ids, and isPrivateConversation excludes shared/group/public', () => {
    assert.deepEqual(
        conversationReferenceRequests([
            { kind: 'conversation', id: 'valid-1' },
            { kind: 'conversation', id: 'valid-1' },
            { kind: 'conversation', id: '../invalid' },
        ]),
        [{ kind: 'conversation', id: 'valid-1' }],
    );
    assert.equal(storedConversationReferences([{ kind: 'conversation', id: 'valid-1', title: 'Alpha' }])[0].title, 'Alpha');
    assert.equal(isPrivateConversation({ id: 'c1', chat_type: 'personal_single_user' }), true);
    assert.equal(isPrivateConversation({ id: 'c2', conversation_kind: 'collaborative' }), false);
    assert.equal(isPrivateConversation({ id: 'c3', chat_type: 'group-single-user' }), false);
    assert.equal(isPrivateConversation({ id: 'c4', chat_type: 'public' }), false);
});

/* -------------------------------------------------------------------------- */

let failed = 0;
for (const [name, run] of checks) {
    try {
        run();
        console.log(`  PASS  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`);
        console.error(`        ${error.message}`);
    }
}

console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed === 0 ? 0 : 1);
