// test_v2_inline_image_proposal_logic.mjs
//
// Runtime test for the V2 inline image proposal logic.
// Version: 0.261.041
// Implemented in: 0.261.029
// Card identity and card state added in: 0.261.041
//
// The companion test, test_v2_inline_image_proposals.py, asserts that the V2 card agrees with
// the classic client and the server about names, caps, paths and thresholds. Those are source
// assertions: they prove the pieces are wired together, not that they behave.
//
// This file executes the parts that are pure logic and where a quiet mistake would be
// invisible until a user lost an image: reading a model-authored payload, reuniting an
// approved image with the card that proposed it, naming a card so its approval state survives
// the card being rebuilt, and running approvals one at a time. Each of those has a failure
// mode that renders perfectly and is simply wrong.
//
// Run directly with `node functional_tests/test_v2_inline_image_proposal_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real modules can be imported
// rather than a copy of them.

import assert from 'node:assert/strict';
import {
    extractProposalSpecs,
    findResultForSpec,
    groupProposalImages,
    normalizePrompt,
    parseImageProposal,
    proposalBadges,
    proposalCardKey,
    proposalSourceMessageId,
} from '../application/v2_ui/src/lib/imageProposalSpec.ts';
import {
    applyCardStatePatch,
    IDLE_CARD_STATE,
} from '../application/v2_ui/src/lib/imageProposalCardState.ts';
import {
    describeQueuePosition,
    enqueueImageApproval,
} from '../application/v2_ui/src/lib/imageProposalQueue.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/* ---------------------------------- parsing --------------------------------- */

check('parses the documented payload', () => {
    const parsed = parseImageProposal(
        JSON.stringify({
            version: 1,
            visualId: 'slide_09_timeline',
            title: 'Timeline of major events, 1700-1750',
            description: 'An illustrated timeline.',
            prompt: 'Create a horizontal illustrated timeline for 1700 to 1750.',
            visualType: 'timeline',
            slideNumber: 9,
            context: 'Major events',
        }),
    );
    assert.equal(parsed.ok, true);
    assert.equal(parsed.spec.visualId, 'slide_09_timeline');
    assert.equal(parsed.spec.slideNumber, 9);
    assert.deepEqual(proposalBadges(parsed.spec), ['timeline', 'Slide 9', 'Major events']);
});

check('accepts snake_case aliases', () => {
    const parsed = parseImageProposal(
        JSON.stringify({ visual_id: 'a-b', visual_type: 'map', slide_number: '3', prompt: 'p' }),
    );
    assert.equal(parsed.ok, true);
    assert.equal(parsed.spec.visualId, 'a-b');
    assert.equal(parsed.spec.visualType, 'map');
    assert.equal(parsed.spec.slideNumber, 3);
});

check('rejects malformed JSON without throwing', () => {
    const parsed = parseImageProposal('{not json');
    assert.equal(parsed.ok, false);
    assert.match(parsed.reason, /not recognised/);
});

check('rejects a proposal with no prompt', () => {
    assert.equal(parseImageProposal(JSON.stringify({ title: 'x' })).ok, false);
    assert.equal(parseImageProposal(JSON.stringify({ prompt: '   ' })).ok, false);
});

check('rejects a JSON array and a bare string', () => {
    assert.equal(parseImageProposal('[{"prompt":"p"}]').ok, false);
    assert.equal(parseImageProposal('"prompt"').ok, false);
});

check('caps the prompt and reduces the visual id', () => {
    const parsed = parseImageProposal(
        JSON.stringify({ visualId: '  ***weird id!!  ', prompt: 'x'.repeat(5000) }),
    );
    assert.equal(parsed.ok, true);
    assert.equal(parsed.spec.prompt.length, 4000);
    // Leading/trailing separators stripped, disallowed runs collapsed to a single underscore.
    assert.equal(parsed.spec.visualId, 'weird_id');
});

check('keeps newlines in a prompt but collapses them elsewhere', () => {
    const parsed = parseImageProposal(
        JSON.stringify({ prompt: 'line one\r\nline two', title: 'a\n\n  b' }),
    );
    assert.equal(parsed.spec.prompt, 'line one\nline two');
    assert.equal(parsed.spec.title, 'a b');
});

check('leaves a missing title empty, as the server stores it', () => {
    // The card posts the spec verbatim on approval, so a default injected here would be
    // stored and two untitled proposals in one message would share a title. The heading a
    // reader sees is supplied by the card, not by the spec.
    assert.equal(parseImageProposal(JSON.stringify({ prompt: 'p' })).spec.title, '');
});

/* --------------------------------- extraction -------------------------------- */

const messageWithTwo = [
    'Here is the plan.',
    '',
    '```simpleimage',
    JSON.stringify({ visualId: 'one', title: 'First', prompt: 'draw one' }),
    '```',
    '',
    'And then:',
    '',
    '```simpleimage',
    JSON.stringify({ visualId: 'two', title: 'Second', prompt: 'draw two' }),
    '```',
].join('\n');

check('extracts every closed fence in a message', () => {
    const specs = extractProposalSpecs(messageWithTwo);
    assert.equal(specs.length, 2);
    assert.deepEqual(specs.map((spec) => spec.visualId), ['one', 'two']);
});

check('extraction is repeatable, so the shared regex carries no state', () => {
    assert.equal(extractProposalSpecs(messageWithTwo).length, 2);
    assert.equal(extractProposalSpecs(messageWithTwo).length, 2);
    assert.equal(extractProposalSpecs(messageWithTwo).length, 2);
});

check('ignores an unterminated fence and malformed payloads', () => {
    assert.equal(extractProposalSpecs('```simpleimage\n{"prompt":"p"}').length, 0);
    assert.equal(extractProposalSpecs('```simpleimage\nnot json\n```').length, 0);
    assert.equal(extractProposalSpecs('no fences here').length, 0);
});

/* ---------------------------------- matching --------------------------------- */

function imageMessage(id, proposal, sourceId = 'assistant-1') {
    return {
        id,
        conversation_id: 'c1',
        role: 'image',
        content: `/api/image/${id}`,
        metadata: {
            image_proposal: {
                ...proposal,
                approved_at: '2026-01-01T00:00:00',
                source_assistant_message_id: sourceId,
            },
        },
    };
}

check('groups approved images under their source assistant message', () => {
    const grouped = groupProposalImages([
        { id: 'a1', role: 'assistant', content: '' },
        imageMessage('img-1', { visualId: 'one', prompt: 'draw one' }),
        imageMessage('img-2', { visualId: 'two', prompt: 'draw two' }),
        // An ordinary generated image, with no proposal metadata, must not be grouped.
        { id: 'img-3', role: 'image', content: 'data:image/png;base64,AA', metadata: {} },
    ]);
    assert.equal(grouped.size, 1);
    assert.deepEqual(grouped.get('assistant-1').map((m) => m.id), ['img-1', 'img-2']);
    assert.equal(proposalSourceMessageId({ metadata: {} }), '');
});

check('matches a card to its own image by visual id', () => {
    const specs = extractProposalSpecs(messageWithTwo);
    const results = [
        imageMessage('img-2', { visualId: 'two', title: 'Second', prompt: 'draw two' }),
        imageMessage('img-1', { visualId: 'one', title: 'First', prompt: 'draw one' }),
    ];
    assert.equal(findResultForSpec(specs[0], results).id, 'img-1');
    assert.equal(findResultForSpec(specs[1], results).id, 'img-2');
});

check('still matches after the prompt was edited before approval', () => {
    const [spec] = extractProposalSpecs(messageWithTwo);
    const results = [
        imageMessage('img-1', { visualId: 'one', title: 'First', prompt: 'a completely different prompt' }),
    ];
    assert.equal(findResultForSpec(spec, results).id, 'img-1');
});

check('matches on the prompt when the server flattened its newlines', () => {
    const spec = parseImageProposal(JSON.stringify({ prompt: 'line one\nline two' })).spec;
    // The server stores prompts through _trim_text, which collapses whitespace.
    const results = [imageMessage('img-1', { prompt: 'line one line two' })];
    assert.equal(findResultForSpec(spec, results).id, 'img-1');
});

check('does not match an unrelated image', () => {
    const [spec] = extractProposalSpecs(messageWithTwo);
    assert.equal(findResultForSpec(spec, [imageMessage('img-9', { visualId: 'nine', title: 'Ninth', prompt: 'nine' })]), null);
    assert.equal(findResultForSpec(spec, []), null);
});

check('a shared title does not steal another card\'s image', () => {
    // Two proposals in one message, distinct visual ids, identical titles. Matching each
    // field across every result -- rather than every field against each result -- is what
    // keeps each card on its own image. Getting this wrong shows image one in both cards and
    // leaves image two stranded in the thread.
    const content = [
        '```simpleimage',
        JSON.stringify({ visualId: 'v_one', title: 'Timeline', prompt: 'draw one' }),
        '```',
        '```simpleimage',
        JSON.stringify({ visualId: 'v_two', title: 'Timeline', prompt: 'draw two' }),
        '```',
    ].join('\n');

    const specs = extractProposalSpecs(content);
    const results = [
        imageMessage('img-1', { visualId: 'v_one', title: 'Timeline', prompt: 'draw one' }),
        imageMessage('img-2', { visualId: 'v_two', title: 'Timeline', prompt: 'draw two' }),
    ];

    assert.equal(findResultForSpec(specs[0], results).id, 'img-1');
    assert.equal(findResultForSpec(specs[1], results).id, 'img-2');

    // Every image is claimed by exactly one card, so none is hidden while shown nowhere.
    const claimed = specs.map((spec) => findResultForSpec(spec, results).id);
    assert.deepEqual([...new Set(claimed)].sort(), ['img-1', 'img-2']);
});

check('a shared title with no visual id still resolves on the prompt', () => {
    const content = [
        '```simpleimage',
        JSON.stringify({ title: 'Diagram', prompt: 'draw the first' }),
        '```',
        '```simpleimage',
        JSON.stringify({ title: 'Diagram', prompt: 'draw the second' }),
        '```',
    ].join('\n');

    const specs = extractProposalSpecs(content);
    const results = [
        imageMessage('img-1', { title: 'Diagram', prompt: 'draw the first' }),
        imageMessage('img-2', { title: 'Diagram', prompt: 'draw the second' }),
    ];

    assert.equal(findResultForSpec(specs[0], results).id, 'img-1');
    assert.equal(findResultForSpec(specs[1], results).id, 'img-2');
});

check('a visual id match beats an earlier image that only shares a title', () => {
    const spec = parseImageProposal(
        JSON.stringify({ visualId: 'mine', title: 'Shared', prompt: 'mine' }),
    ).spec;
    const results = [
        imageMessage('img-other', { visualId: 'theirs', title: 'Shared', prompt: 'theirs' }),
        imageMessage('img-mine', { visualId: 'mine', title: 'Shared', prompt: 'mine' }),
    ];
    assert.equal(findResultForSpec(spec, results).id, 'img-mine');
});

check('an untitled proposal never matches on the title the card displays', () => {
    // Reachable shape: the model gave no title, so the spec and the stored proposal both
    // carry '' and the title pass has nothing to compare. Approving with a default injected
    // into the spec would store that default and break this.
    const spec = parseImageProposal(JSON.stringify({ prompt: 'mine' })).spec;
    assert.equal(spec.title, '');
    assert.equal(findResultForSpec(spec, [imageMessage('img-1', { title: '', prompt: 'theirs' })]), null);
});

check('two untitled proposals cannot claim each other\'s image after an edit', () => {
    // The narrow leak: no visual id, no title, and prompts edited before approval, so
    // neither the visual id nor the prompt pass can match. Nothing must be claimed on a
    // shared placeholder title; both images then stay visible in the thread instead of one
    // being shown twice and the other attributed to the wrong card.
    const content = [
        '```simpleimage',
        JSON.stringify({ prompt: 'a red bridge' }),
        '```',
        '```simpleimage',
        JSON.stringify({ prompt: 'a blue harbour' }),
        '```',
    ].join('\n');

    const specs = extractProposalSpecs(content);
    const results = [
        imageMessage('img-red', { title: '', prompt: 'a red bridge at sunset, watercolour' }),
        imageMessage('img-blue', { title: '', prompt: 'a blue harbour at dawn, watercolour' }),
    ];

    assert.equal(findResultForSpec(specs[0], results), null);
    assert.equal(findResultForSpec(specs[1], results), null);
});

/* ----------------------------------- queue ----------------------------------- */

check('runs approvals one at a time, in order', async () => {
    const events = [];
    let inFlight = 0;

    const task = (name) => async () => {
        inFlight += 1;
        assert.equal(inFlight, 1, `${name} ran concurrently with another approval`);
        events.push(`start:${name}`);
        await new Promise((resolve) => setTimeout(resolve, 5));
        events.push(`end:${name}`);
        inFlight -= 1;
        return name;
    };

    const positions = { a: [], b: [], c: [] };
    const results = await Promise.all([
        enqueueImageApproval(task('a'), (ahead) => positions.a.push(ahead)),
        enqueueImageApproval(task('b'), (ahead) => positions.b.push(ahead)),
        enqueueImageApproval(task('c'), (ahead) => positions.c.push(ahead)),
    ]);

    assert.deepEqual(results, ['a', 'b', 'c']);
    assert.deepEqual(events, ['start:a', 'end:a', 'start:b', 'end:b', 'start:c', 'end:c']);
    // The last one queued is told it is behind two others, and counts down as they finish.
    assert.ok(positions.c.includes(2), `expected c to report 2 ahead, saw ${positions.c}`);
    assert.ok(positions.c.includes(1), `expected c to count down to 1, saw ${positions.c}`);
});

check('a failed approval rejects only its own caller and does not wedge the queue', async () => {
    const failure = enqueueImageApproval(async () => {
        throw new Error('image generation failed');
    }, () => {});
    await assert.rejects(failure, /image generation failed/);

    // The queue must still accept and run work afterwards.
    assert.equal(await enqueueImageApproval(async () => 'ok', () => {}), 'ok');
});

check('describes its queue position in words', () => {
    assert.equal(describeQueuePosition(0), 'Queued. Starting soon…');
    assert.equal(describeQueuePosition(1), 'Queued. 1 image ahead.');
    assert.equal(describeQueuePosition(4), 'Queued. 4 images ahead.');
});

check('normalizePrompt is defensive about non-strings', () => {
    assert.equal(normalizePrompt(undefined), '');
    assert.equal(normalizePrompt(null), '');
    assert.equal(normalizePrompt('  padded  '), 'padded');
});

/* ------------------------------- card identity ------------------------------- */

/** A closed proposal fence carrying the given payload. */
function proposalFence(payload) {
    return ['```simpleimage', JSON.stringify(payload), '```'].join('\n');
}

check('a card is identified by its position among the fences', () => {
    const message = [
        proposalFence({ visualId: 'a', prompt: 'first' }),
        proposalFence({ visualId: 'b', prompt: 'second' }),
    ].join('\n\n');
    const [first, second] = extractProposalSpecs(message);

    // Two cards in one message must never share a key: the scope files their approval state
    // under it, so a collision would show one card the other's progress.
    assert.notEqual(proposalCardKey(first, 0), proposalCardKey(second, 1));
    assert.equal(proposalCardKey(first, 0), 'block:0');
    assert.equal(proposalCardKey(second, 1), 'block:1');
});

check('the key survives the card being rebuilt from the same message', () => {
    const message = proposalFence({ visualId: 'a', prompt: 'first' });
    const before = proposalCardKey(extractProposalSpecs(message)[0], 0);
    const after = proposalCardKey(extractProposalSpecs(message)[0], 0);

    // This is the whole point: re-parsing the same message has to name the same card, or an
    // approval in flight loses the state it is reporting into.
    assert.equal(before, after);
});

check('the key falls back to the spec when there is no block index', () => {
    const withId = parseImageProposal(JSON.stringify({ visualId: 'slide_1', prompt: 'p' })).spec;
    assert.equal(proposalCardKey(withId), 'visual:slide_1');

    const withoutId = parseImageProposal(JSON.stringify({ prompt: 'a  multi\nline' })).spec;
    assert.equal(proposalCardKey(withoutId), 'prompt:a multi line');

    // A malformed proposal has no spec, and cannot be approved either, so one shared key is
    // enough for all of them.
    assert.equal(proposalCardKey(null), 'invalid');

    // A negative or fractional index is not an index; it must not be trusted as a key.
    assert.equal(proposalCardKey(withId, -1), 'visual:slide_1');
    assert.equal(proposalCardKey(withId, 1.5), 'visual:slide_1');
});

/* -------------------------------- card state --------------------------------- */

check('an unknown card starts from the idle state', () => {
    const states = applyCardStatePatch({}, 'block:0', { status: 'queued' });
    assert.equal(states['block:0'].status, 'queued');
    assert.equal(states['block:0'].queuePosition, 0);
    assert.equal(states['block:0'].failure, '');
    assert.equal(states['block:0'].editing, false);
    assert.equal(IDLE_CARD_STATE.status, 'idle');
});

check('a patch leaves the fields it does not mention alone', () => {
    let states = applyCardStatePatch({}, 'block:0', { prompt: 'edited', editing: true });
    states = applyCardStatePatch(states, 'block:0', { status: 'generating' });

    assert.equal(states['block:0'].prompt, 'edited');
    assert.equal(states['block:0'].editing, true);
    assert.equal(states['block:0'].status, 'generating');
});

check('one card cannot disturb another', () => {
    let states = applyCardStatePatch({}, 'block:0', { status: 'generating' });
    states = applyCardStatePatch(states, 'block:1', { status: 'queued', queuePosition: 1 });

    // The reported bug in one sentence: the first image arriving must not reset the others.
    assert.equal(states['block:0'].status, 'generating');
    assert.equal(states['block:1'].status, 'queued');
    assert.equal(states['block:1'].queuePosition, 1);
});

check('a patch that changes nothing returns the same record', () => {
    const states = applyCardStatePatch({}, 'block:0', { status: 'queued', queuePosition: 2 });

    // The queue reports its position to every waiting card each time it moves, and most of
    // those reports say what the card already knows. A new record for each would re-render
    // every card in the message repeatedly for no visible change.
    assert.equal(applyCardStatePatch(states, 'block:0', { queuePosition: 2 }), states);
    assert.equal(applyCardStatePatch(states, 'block:0', {}), states);
    assert.notEqual(applyCardStatePatch(states, 'block:0', { queuePosition: 1 }), states);
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
