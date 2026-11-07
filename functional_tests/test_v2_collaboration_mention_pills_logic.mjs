// test_v2_collaboration_mention_pills_logic.mjs
// Version: 0.261.255
// Implemented in: 0.261.255
// Executes the real V2 mention helpers behind the pills of a shared conversation: which people
// and AI target a sent message is drawn with, how their `@Name` text is taken out of what is
// shown (in the message and in a reply's quotation of it) without disturbing anything else, and
// how chips picked in the composer become the mentions the send rule, the server and the classic
// client read from the stored text.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    addComposerMention, composerMentionFromSuggestion, extractMentionedParticipants, findMentionAtCaret,
    prefixComposerMentions, removeComposerMention, removeMentionQuery, resolveSendTarget, stripMentionText,
} = await import('../application/v2_ui/src/lib/mentions.ts');
const { buildReplyPreview, readMessageMentionPills } = await import('../application/v2_ui/src/lib/sharedMessage.ts');
const { buildComposerDraftSubmission, createComposerDraft } = await import(
    '../application/v2_ui/src/lib/composerDraft.ts'
);

const AGENTS = [
    { id: 'agent-watch', name: 'watch_officer', display_name: 'Watch Officer', scope_type: 'group' },
    { id: 'agent-cell', name: 'response_cell', display_name: 'Response Cell Officer', scope_type: 'group' },
];
const PARTICIPANTS = [
    { user_id: 'u-sam', display_name: 'Sam Lee', email: 'sam@example.com', status: 'accepted' },
    { user_id: 'u-ada', display_name: 'Ada', email: 'ada@example.com', status: 'accepted' },
    { user_id: 'u-ada-l', display_name: 'Ada Lovelace', email: 'adal@example.com', status: 'accepted' },
];

function sharedMessage(metadata, overrides = {}) {
    return { id: 'm-1', conversation_id: 'c-1', role: 'user', content: '', metadata, ...overrides };
}

function testStripRemovesOnlyTheNamedMentions() {
    assert.equal(
        stripMentionText('@Watch Officer @Sam Lee can you check the plates?', ['Sam Lee', 'Watch Officer']),
        'Can you check the plates?',
        'the sentence the mentions began keeps its capital',
    );
    assert.equal(stripMentionText('Thanks @Sam Lee.', ['Sam Lee']), 'Thanks.');
    assert.equal(stripMentionText('@sam lee hi', ['Sam Lee']), 'Hi', 'matching ignores case, as the server does');
    // "@Ada Lovelace" contains "@Ada" followed by a space, so the longer name must go first.
    assert.equal(stripMentionText('@Ada Lovelace and @Ada, hi', ['Ada', 'Ada Lovelace']), 'And hi');
    assert.equal(stripMentionText('Ask @Samantha', ['Sam']), 'Ask @Samantha', 'a longer word is not a mention');
    assert.equal(stripMentionText('write to bob@Sam.org now', ['Sam']), 'write to bob@Sam.org now');
    assert.equal(stripMentionText('@Watch Officer', ['Watch Officer']), '', 'a message of mentions alone is empty');
}

function testAddressingReadsAsASentence() {
    // How people address each other: a name, a comma, then what they should do.
    assert.equal(
        stripMentionText(
            'Our gap is everything after the truck reached the depot. @Field Lead, start with the route. '
                + '@Site Lead, get the depot team on with us.',
            ['Field Lead', 'Site Lead'],
        ),
        'Our gap is everything after the truck reached the depot. Start with the route. '
            + 'Get the depot team on with us.',
    );
    assert.equal(
        stripMentionText('Is anything exposed? @Regional Lead, this is your response.', ['Regional Lead']),
        'Is anything exposed? This is your response.',
    );
    assert.equal(
        stripMentionText('While that runs: @Site Lead, how fast can the depot move?', ['Site Lead']),
        'While that runs: how fast can the depot move?',
        'mid-sentence, the next word keeps its case',
    );
    assert.equal(stripMentionText('@Sam Lee: 3 cars are ready', ['Sam Lee']), '3 cars are ready');
    assert.equal(stripMentionText('Over to @Sam Lee, then the cell.', ['Sam Lee']), 'Over to then the cell.');
}

function testStripLeavesEverythingElseAlone() {
    assert.equal(
        stripMentionText('@Sam Lee first line\n\nsecond paragraph', ['Sam Lee']),
        'First line\n\nsecond paragraph',
        'paragraph breaks survive',
    );
    assert.equal(stripMentionText('Hi team\n@Sam Lee can you check', ['Sam Lee']), 'Hi team\nCan you check');
    const untouched = 'spacing  kept   when @Other is not named';
    assert.equal(stripMentionText(untouched, ['Sam Lee']), untouched, 'nothing removed means nothing tidied');
    assert.equal(stripMentionText('no mentions here', []), 'no mentions here');
}

function testPillsComeFromWhatTheServerStored() {
    const pills = readMessageMentionPills(sharedMessage({
        ai_invocation_target: { target_type: 'agent', display_name: 'Watch Officer', mention_text: '@Watch Officer' },
        mentioned_participants: [
            { user_id: 'u-sam', display_name: 'Sam Lee', email: 'sam@example.com' },
            { user_id: 'u-sam', display_name: 'Sam Lee' },
            { user_id: 'u-me', display_name: 'Pat Reader' },
            { user_id: '', display_name: 'Nobody' },
            { user_id: 'u-blank' },
            'not an object',
        ],
    }), 'u-me');

    assert.deepEqual(pills, [
        { key: 'ai', kind: 'ai', label: 'Watch Officer', target_type: 'agent' },
        { key: 'person:u-sam', kind: 'person', label: 'Sam Lee', self: false },
        { key: 'person:u-me', kind: 'person', label: 'Pat Reader', self: true },
    ]);

    const model = readMessageMentionPills(sharedMessage({ ai_invocation_target: { display_name: 'gpt-6' } }), 'u-me');
    assert.deepEqual(model, [{ key: 'ai', kind: 'ai', label: 'gpt-6', target_type: 'model' }]);

    assert.deepEqual(readMessageMentionPills(sharedMessage({ mentioned_participants: [{ user_id: 'u-sam', display_name: 'Sam' }] }, {
        role: 'assistant',
    }), 'u-me'), [], 'only a person\'s message carries pills');
    assert.deepEqual(readMessageMentionPills(sharedMessage(undefined), 'u-me'), []);
    assert.deepEqual(readMessageMentionPills(sharedMessage({ ai_invocation_target: ['x'] }), 'u-me'), []);
}

function testComposerChipsFollowTheOneAgentRule() {
    const sam = composerMentionFromSuggestion({
        kind: 'participant', user_id: 'u-sam', display_name: 'Sam Lee', mention_text: '@Sam Lee',
    });
    const invitee = composerMentionFromSuggestion({
        kind: 'invite', user_id: 'u-new', display_name: 'New Person', mention_text: '@New Person',
    });
    const watch = composerMentionFromSuggestion({
        kind: 'ai', display_name: 'Watch Officer', mention_text: '@Watch Officer',
        target: { target_type: 'agent', display_name: 'Watch Officer', mention_text: '@Watch Officer', source_mode: 'explicit_tag' },
    });
    const cell = composerMentionFromSuggestion({
        kind: 'ai', display_name: 'Response Cell Officer', mention_text: '@Response Cell Officer',
        target: { target_type: 'agent', display_name: 'Response Cell Officer', mention_text: '@Response Cell Officer', source_mode: 'explicit_tag' },
    });

    assert.deepEqual(sam, { key: 'person:u-sam', kind: 'person', display_name: 'Sam Lee', mention_text: '@Sam Lee' });
    assert.equal(invitee.key, 'person:u-new');
    assert.deepEqual(watch, {
        key: 'ai', kind: 'ai', display_name: 'Watch Officer', mention_text: '@Watch Officer', target_type: 'agent',
    });

    let chips = addComposerMention([], sam);
    chips = addComposerMention(chips, sam);
    assert.equal(chips.length, 1, 'a person is not added twice');
    chips = addComposerMention(chips, invitee);
    chips = addComposerMention(chips, watch);
    assert.deepEqual(chips.map((chip) => chip.display_name), ['Watch Officer', 'Sam Lee', 'New Person']);
    chips = addComposerMention(chips, cell);
    assert.deepEqual(
        chips.map((chip) => chip.display_name), ['Response Cell Officer', 'Sam Lee', 'New Person'],
        'a second agent replaces the first',
    );
    chips = removeComposerMention(chips, 'person:u-new');
    assert.deepEqual(chips.map((chip) => chip.key), ['ai', 'person:u-sam']);
}

function testChipsAreSentAsMentionsTheSendRuleReads() {
    const chips = [
        { key: 'ai', kind: 'ai', display_name: 'Watch Officer', mention_text: '@Watch Officer', target_type: 'agent' },
        { key: 'person:u-sam', kind: 'person', display_name: 'Sam Lee', mention_text: '@Sam Lee' },
    ];
    const sent = prefixComposerMentions('  check the plates  ', chips);
    assert.equal(sent, '@Watch Officer @Sam Lee check the plates');
    assert.equal(prefixComposerMentions('', chips), '@Watch Officer @Sam Lee', 'chips alone are a ping');
    assert.equal(prefixComposerMentions(' text ', []), 'text');
    assert.equal(prefixComposerMentions('text', undefined), 'text');

    const target = resolveSendTarget(sent, {}, { agents: AGENTS, models: [] });
    assert.equal(target?.target_type, 'agent');
    assert.equal(target?.display_name, 'Watch Officer');
    assert.equal(target?.agent_selection_key, 'agent-watch');
    assert.deepEqual(extractMentionedParticipants(sent, PARTICIPANTS).map((person) => person.user_id), ['u-sam']);

    // What the thread then shows: the sentence, with the names moved to pills.
    assert.equal(stripMentionText(sent, ['Watch Officer', 'Sam Lee']), 'Check the plates');
}

function testMentionQueryIsRemovedCleanly() {
    const middle = 'Hi @Sa there';
    assert.deepEqual(removeMentionQuery(middle, findMentionAtCaret(middle, 6)), { value: 'Hi there', caretIndex: 3 });
    const start = '@Wat hello';
    assert.deepEqual(removeMentionQuery(start, findMentionAtCaret(start, 4)), { value: 'hello', caretIndex: 0 });
    const end = 'ping @Sa';
    assert.deepEqual(removeMentionQuery(end, findMentionAtCaret(end, 8)), { value: 'ping ', caretIndex: 5 });
}

function testSubmissionCarriesChipsThroughPrompts() {
    const chips = [
        { key: 'ai', kind: 'ai', display_name: 'Watch Officer', mention_text: '@Watch Officer', target_type: 'agent' },
    ];
    const plain = buildComposerDraftSubmission({ ...createComposerDraft(), text: 'status?', mentions: chips }, {});
    assert.equal(plain.message, '@Watch Officer status?');
    assert.equal(plain.promptInfo, null);
    assert.deepEqual(createComposerDraft().mentions, []);

    const attached = (content) => ({
        id: 'p-1', name: 'Brief', originalContent: content, editedContent: null,
    });
    const tail = buildComposerDraftSubmission({
        ...createComposerDraft(), text: 'for today', mentions: chips, attachedPrompt: attached('Write the brief.'),
    }, {});
    // The server keeps prompt metadata only when the message is exactly prompt + blank line +
    // the recorded user text (functions_prompt_metadata.build_prompt_selection_metadata).
    assert.equal(tail.promptInfo.user_text, '@Watch Officer for today');
    assert.equal(tail.promptInfo.composer_text, '@Watch Officer for today');
    assert.equal(tail.message, `${tail.promptInfo.content}\n\n${tail.promptInfo.user_text}`);

    const embedded = buildComposerDraftSubmission({
        ...createComposerDraft(), text: 'the harbor', mentions: chips, attachedPrompt: attached('Summarise {{composer}} now.'),
    }, {});
    assert.equal(embedded.promptInfo.composer_embedded, true);
    assert.equal(embedded.promptInfo.user_text, '');
    assert.ok(embedded.promptInfo.content.includes(embedded.promptInfo.composer_text), 'composer text sits inside the prompt');
    assert.equal(embedded.message, 'Summarise @Watch Officer the harbor now.');
}

function testReplyQuotesReadLikeTheMessage() {
    // An agent's answer quotes its request, whose agent is already a pill on the request.
    const request = sharedMessage(
        { ai_invocation_target: { target_type: 'agent', display_name: 'Logistics Analyst' } },
        { content: '@Logistics Analyst Truck TR-4471 reached the depot this morning.' },
    );
    assert.equal(buildReplyPreview(request), 'Truck TR-4471 reached the depot this morning.');

    const addressed = sharedMessage(
        { mentioned_participants: [{ user_id: 'u-dir', display_name: 'Operations Director' }] },
        { content: "Signed. That's our green light. @Operations Director, requesting approval to ship." },
    );
    assert.equal(buildReplyPreview(addressed), "Signed. That's our green light. Requesting approval to ship.");

    const ping = sharedMessage({ mentioned_participants: [{ user_id: 'u-sam', display_name: 'Sam Lee' }] }, {
        content: '@Sam Lee',
    });
    assert.equal(buildReplyPreview(ping), '@Sam Lee', 'a message of mentions alone is not quoted as nothing');

    const answer = sharedMessage({}, {
        role: 'assistant',
        content: '## Answer\n\nLast scanned at **08:47 EDT**, [dock D-11](https://example.com/dock), *blue* container.'
            + '\n\n- Truck: `TR-4471`\n- order_id: ORD-77',
    });
    assert.equal(
        buildReplyPreview(answer),
        'Answer Last scanned at 08:47 EDT, dock D-11, blue container. Truck: TR-4471 order_id: ORD-77',
    );

    const table = sharedMessage({}, { role: 'assistant', content: '| Dock | Status |\n| --- | --- |\n| A | Loading |' });
    assert.equal(buildReplyPreview(table), 'Dock Status A Loading');

    const typed = sharedMessage({}, { content: 'Use 5 * 3 * 2 and **not** more' });
    assert.equal(buildReplyPreview(typed), 'Use 5 * 3 * 2 and **not** more', "a person's text is not read as markdown");

    const long = buildReplyPreview(sharedMessage({}, { role: 'assistant', content: `## Answer\n\n${'word '.repeat(60)}` }));
    assert.equal(long.length, 140);
    assert.ok(long.startsWith('Answer word') && long.endsWith('\u2026'));
}

const tests = [
    testStripRemovesOnlyTheNamedMentions,
    testAddressingReadsAsASentence,
    testStripLeavesEverythingElseAlone,
    testPillsComeFromWhatTheServerStored,
    testReplyQuotesReadLikeTheMessage,
    testComposerChipsFollowTheOneAgentRule,
    testChipsAreSentAsMentionsTheSendRuleReads,
    testMentionQueryIsRemovedCleanly,
    testSubmissionCarriesChipsThroughPrompts,
];

for (const test of tests) {
    test();
    console.log(`passed: ${test.name}`);
}
console.log(`${tests.length} mention pill checks passed`);
