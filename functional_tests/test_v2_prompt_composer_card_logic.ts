// test_v2_prompt_composer_card_logic.ts
//
// Runtime test for the attached-prompt card's composition and recovery rules.
// Version: 0.261.092
// Implemented in: 0.261.092
//
// The companion test, test_v2_prompt_composer_card.py, asserts that the pieces are wired
// together. This file executes the behaviour, because these failure modes are all quiet ones
// -- a message that still sends, and reads wrong:
//
//   - Composing in the wrong order buries the question under the standing instructions it was
//     asked with, which is the arrangement the card exists to undo.
//   - A prompt that positions the typed text itself with `{{composer}}` and then has it
//     appended underneath as well sends it twice.
//   - `readMessagePrompt` splitting a message it cannot account for would rewrite messages
//     sent before any of this existed, and would mis-split one that has since been edited.
//   - `prompt_selection` metadata whose keys do not match what the server writes leaves the
//     optimistic bubble drawn one way and the echoed one drawn another.
//
// Run by test_v2_prompt_composer_card.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping it when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    attachedPromptContent,
    attachedPromptIsEdited,
    buildOutgoingMessage,
    buildPromptInfo,
    composePromptMessage,
    promptConsumesComposer,
    promptSelectionMetadata,
    type AttachedPrompt,
} from '../application/v2_ui/src/lib/promptRequest';
import { readMessagePrompt } from '../application/v2_ui/src/lib/messagePrompt';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

function attached(overrides: Partial<AttachedPrompt> = {}): AttachedPrompt {
    return {
        id: 'p1',
        name: 'Weekly status',
        originalContent: 'Summarise the week.',
        editedContent: null,
        ...overrides,
    };
}

/* --------------------------------- composition --------------------------------- */

check('the prompt leads and the typed message follows', () => {
    assert.equal(composePromptMessage('Do the thing.', 'For Q3.'), 'Do the thing.\n\nFor Q3.');
});

check('either side alone is the whole message', () => {
    assert.equal(composePromptMessage('Only the prompt.', ''), 'Only the prompt.');
    assert.equal(composePromptMessage('', 'Only what I typed.'), 'Only what I typed.');
    assert.equal(composePromptMessage('   ', '  '), '');
});

check('surrounding whitespace never becomes a blank line of its own', () => {
    assert.equal(composePromptMessage('  Prompt.  ', '\n Typed. \n'), 'Prompt.\n\nTyped.');
});

/* ------------------------------ the composer built-in ---------------------------- */

check('a prompt that names {{composer}} is detected', () => {
    assert.equal(promptConsumesComposer('Summarise: {{composer}}'), true);
    assert.equal(promptConsumesComposer('Summarise the week.'), false);
});

check('{{composer}} inside a code fence does not count as consuming the message', () => {
    const content = ['Explain this template:', '```', '{{composer}}', '```'].join('\n');
    assert.equal(promptConsumesComposer(content), false);
});

check('a prompt that positions the typed text is not also sent it a second time', () => {
    const outgoing = buildOutgoingMessage(
        'Summarise: {{composer}}',
        'Summarise: the quarterly numbers',
        'the quarterly numbers',
    );
    assert.equal(outgoing.message, 'Summarise: the quarterly numbers');
    // Reported as consumed, so the sent bubble does not show it a second time either.
    assert.equal(outgoing.userText, '');
});

check('an ordinary prompt still carries the typed text after it', () => {
    const outgoing = buildOutgoingMessage('Summarise the week.', 'Summarise the week.', 'For Q3.');
    assert.equal(outgoing.message, 'Summarise the week.\n\nFor Q3.');
    assert.equal(outgoing.userText, 'For Q3.');
});

/* ----------------------------------- editing ------------------------------------ */

check('an unedited prompt uses its saved wording and is not flagged', () => {
    const prompt = attached();
    assert.equal(attachedPromptContent(prompt), 'Summarise the week.');
    assert.equal(attachedPromptIsEdited(prompt), false);
});

check('an edit for this turn takes precedence and is flagged', () => {
    const prompt = attached({ editedContent: 'Summarise the fortnight.' });
    assert.equal(attachedPromptContent(prompt), 'Summarise the fortnight.');
    assert.equal(attachedPromptIsEdited(prompt), true);
});

check('editing back to the original wording is not an edit', () => {
    const prompt = attached({ editedContent: 'Summarise the week.' });
    assert.equal(attachedPromptIsEdited(prompt), false);
});

/* --------------------------------- prompt_info ---------------------------------- */

check('prompt_info reports the resolved text and the saved text separately', () => {
    const info = buildPromptInfo({
        attached: attached({ originalContent: 'Report on {{topic}}.' }),
        promptText: 'Report on latency.',
        userText: 'Keep it short.',
        values: { topic: 'latency' },
    }) as Record<string, unknown>;

    assert.equal(info.content, 'Report on latency.');
    assert.equal(info.original_content, 'Report on {{topic}}.');
    assert.equal(info.user_text, 'Keep it short.');
    assert.deepEqual(info.variables, { topic: 'latency' });
    assert.equal(info.edited, false);
});

check('an unfilled variable is not reported as an answered one', () => {
    const info = buildPromptInfo({
        attached: attached(),
        promptText: 'x',
        userText: '',
        values: { topic: '', owner: '   ', team: 'Platform' },
    }) as Record<string, unknown>;

    assert.deepEqual(info.variables, { team: 'Platform' });
});

check('the optimistic metadata uses the keys the server writes', () => {
    const info = buildPromptInfo({
        attached: attached(),
        promptText: 'Summarise the week.',
        userText: 'For Q3.',
        values: {},
    });
    const metadata = promptSelectionMetadata(info) as Record<string, unknown>;

    assert.equal(metadata.prompt_id, 'p1');
    assert.equal(metadata.prompt_name, 'Weekly status');
    assert.equal(metadata.selected_prompt_text, 'Summarise the week.');
    assert.equal(metadata.user_text, 'For Q3.');
    assert.equal(metadata.prompt_edited, false);
});

/* ------------------------------ reading it back out ------------------------------ */

function sentMessage(promptText: string, userText: string, contentOverride?: string) {
    return {
        content: contentOverride ?? composePromptMessage(promptText, userText),
        metadata: {
            prompt_selection: {
                prompt_name: 'Weekly status',
                selected_prompt_text: promptText,
                user_text: userText,
            },
        },
    };
}

check('a sent message is split back into its prompt and its own words', () => {
    const found = readMessagePrompt(sentMessage('Summarise the week.', 'For Q3.'));
    assert.ok(found);
    assert.equal(found!.name, 'Weekly status');
    assert.equal(found!.promptText, 'Summarise the week.');
    assert.equal(found!.userText, 'For Q3.');
});

check('a prompt-only message has no typed text under it', () => {
    const found = readMessagePrompt(sentMessage('Summarise the week.', ''));
    assert.ok(found);
    assert.equal(found!.userText, '');
});

check('a message with no prompt metadata is left exactly as it is', () => {
    assert.equal(readMessagePrompt({ content: 'Just a question.' }), null);
    assert.equal(readMessagePrompt({ content: 'Just a question.', metadata: {} }), null);
});

check('metadata naming a prompt with no text is not enough to split on', () => {
    const message = {
        content: 'Just a question.',
        metadata: { prompt_selection: { prompt_name: 'Weekly status' } },
    };
    assert.equal(readMessagePrompt(message), null);
});

check('a message that does not begin with its prompt is left alone', () => {
    // What an edited message, or one assembled the old way, looks like.
    const message = sentMessage('Summarise the week.', 'For Q3.', 'For Q3.\n\nSummarise the week.');
    assert.equal(readMessagePrompt(message), null);
});

check('a stale user_text falls back to stripping the prompt from the front', () => {
    const message = {
        content: 'Summarise the week.\n\nActually, for Q4.',
        metadata: {
            prompt_selection: {
                prompt_name: 'Weekly status',
                selected_prompt_text: 'Summarise the week.',
                user_text: 'For Q3.',
            },
        },
    };
    const found = readMessagePrompt(message);
    assert.ok(found);
    assert.equal(found!.userText, 'Actually, for Q4.');
});

check('a message sent before user_text existed still splits', () => {
    const message = {
        content: 'Summarise the week.\n\nFor Q3.',
        metadata: {
            prompt_selection: {
                prompt_name: 'Weekly status',
                selected_prompt_text: 'Summarise the week.',
            },
        },
    };
    const found = readMessagePrompt(message);
    assert.ok(found);
    assert.equal(found!.userText, 'For Q3.');
});

check('an unnamed prompt still gets a label rather than an empty one', () => {
    const message = {
        content: 'Summarise the week.',
        metadata: { prompt_selection: { selected_prompt_text: 'Summarise the week.' } },
    };
    const found = readMessagePrompt(message);
    assert.ok(found);
    assert.equal(found!.name, 'Prompt');
});

/* ----------------------------------- runner ------------------------------------- */

let failed = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`);
        console.error(error instanceof Error ? error.message : String(error));
    }
}

if (failed > 0) {
    console.error(`\n${failed} of ${checks.length} checks failed`);
    process.exit(1);
}
console.log(`\n${checks.length} checks passed`);
