// test_v2_prompt_composer_card_logic.ts
//
// Runtime test for the attached-prompt card's composition and recovery rules.
// Version: 0.261.096
// Implemented in: 0.261.096
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
// Run by test_v2_prompt_composer_card.py, which also supplies executed backend persistence
// fixtures. Missing frontend dependencies fail validation rather than silently skipping it.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
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
import { applyPromptVariables } from '../application/v2_ui/src/lib/promptVariables';
import { startOrchestrationPlan } from '../application/v2_ui/src/lib/orchestrationController';
import { useChatStore } from '../application/v2_ui/src/stores/chatStore';
import { useCollaborationStore } from '../application/v2_ui/src/stores/collaborationStore';
import { usePromptVariableValues, type PromptVariableValues } from '../application/v2_ui/src/lib/usePromptVariableValues';
import { PromptVariableField } from '../application/v2_ui/src/components/prompts/PromptVariableField';
import type { ChatMessage, Json } from '../application/v2_ui/src/lib/types';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
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
    // The legacy tail is empty; the separate composer_text snapshot still keeps it visible.
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
    assert.equal(info.template_content, 'Report on {{topic}}.');
    assert.equal(info.user_text, 'Keep it short.');
    assert.equal(info.composer_text, 'Keep it short.');
    assert.equal(info.composer_embedded, false);
    assert.deepEqual(info.variables, { topic: 'latency' });
    assert.equal(info.edited, false);
});

check('an unfilled variable is not reported as an answered one', () => {
    const info = buildPromptInfo({
        attached: attached({ originalContent: '{{topic}} {{owner}} {{team}}' }),
        promptText: 'x',
        userText: '',
        values: { topic: '', owner: '   ', team: 'Platform' },
    }) as Record<string, unknown>;

    assert.deepEqual(info.variables, { team: 'Platform' });
});

check('a turn-local edit records only the active template and its declared variables', () => {
    const template = 'For {{customer-name|Guest}} and {{constructor}}. `{{inline}}` \\{{escaped}}';
    const info = buildPromptInfo({
        attached: attached({
            originalContent: '{{removed}}',
            editedContent: template,
            scopeType: 'group',
            scopeName: 'Operations',
        }),
        promptText: 'For Ada and an ordinary variable. `{{inline}}` {{escaped}}',
        userText: 'Next week.',
        values: {
            customer_name: 'Ada', constructor: 'an ordinary variable', removed: 'private old value',
            inline: 'not a field', escaped: 'not a field',
        },
    });
    assert.equal(info.template_content, template);
    assert.equal(info.edited, true);
    assert.equal(info.scope_type, 'group');
    assert.equal(info.scope_name, 'Operations');
    assert.deepEqual(info.variables, { customer_name: 'Ada', constructor: 'an ordinary variable' });
});

check('composer words remain visible without being appended twice', () => {
    const template = 'Summarise: {{composer}}';
    const info = buildPromptInfo({
        attached: attached({ originalContent: template }),
        promptText: 'Summarise: the quarterly numbers',
        userText: '',
        composerText: 'the quarterly numbers',
        values: { composer: 'the quarterly numbers' },
    });
    assert.equal(info.composer_embedded, true);
    assert.equal(info.composer_text, 'the quarterly numbers');
    assert.equal(info.user_text, '');
    const message = {
        content: buildOutgoingMessage(template, String(info.content), String(info.composer_text)).message,
        metadata: { prompt_selection: promptSelectionMetadata(info) },
    };
    assert.equal(message.content, 'Summarise: the quarterly numbers');
    assert.equal(readMessagePrompt(message)?.userText, 'the quarterly numbers');
    assert.equal(readMessagePrompt(message)?.variableCount, 1);
});

check('an unavailable composer default does not invent separately typed words', () => {
    const template = 'Summarise {{composer|the current report}}';
    const promptText = applyPromptVariables(template, {});
    const info = buildPromptInfo({
        attached: attached({ originalContent: template }), promptText,
        userText: '', composerText: '', values: {},
    });
    assert.equal(promptText, 'Summarise the current report');
    const found = readMessagePrompt({
        content: promptText,
        metadata: { prompt_selection: promptSelectionMetadata(info) },
    });
    assert.equal(found?.userText, '');
    assert.equal(found?.variableCount, 1);
});

check('constructor and __proto__ are ordinary attachment values, not object properties', () => {
    const template = 'Compare {{constructor}} with {{__proto__}}.';
    const values = Object.fromEntries([['constructor', 'Alpha'], ['__proto__', 'Beta']]);
    const promptText = applyPromptVariables(template, values);
    const info = buildPromptInfo({
        attached: attached({ originalContent: template }), promptText,
        userText: 'Keep it brief.', values,
    });
    const metadata = promptSelectionMetadata(info);
    assert.equal(promptText, 'Compare Alpha with Beta.');
    assert.deepEqual(metadata.prompt_variables, values);
    assert.equal(Object.getPrototypeOf(metadata.prompt_variables), Object.prototype);
    assert.equal(Object.prototype.hasOwnProperty.call(metadata.prompt_variables, '__proto__'), true);
    assert.equal(readMessagePrompt({
        content: 'Compare Alpha with Beta.\n\nKeep it brief.',
        metadata: { prompt_selection: metadata },
    })?.variableCount, 2);
});

check('the real variable hook and fields render unanswered prototype-like names safely', () => {
    const template = 'Compare {{constructor}} with {{__proto__}}.';
    let captured: PromptVariableValues | undefined;
    function PrototypeFields() {
        const state = usePromptVariableValues({
            promptId: 'prototype-regression', content: template, context: {}, shared: true,
        });
        captured = state;
        return createElement('div', {}, ...state.variables.map((variable) => createElement(
            PromptVariableField,
            {
                key: variable.key, variable, value: state.values[variable.key] ?? '',
                prefilled: state.prefilled.has(variable.key), history: state.history[variable.key] ?? [],
                aiValue: state.aiValues[variable.key], idPrefix: 'prototype-regression',
                onChange: (value: string) => state.setValue(variable.key, value),
            },
        )));
    }
    const html = renderToStaticMarkup(createElement(PrototypeFields));
    assert.ok(captured);
    assert.deepEqual(captured.unfilled.map((variable) => variable.key), ['constructor', '__proto__']);
    assert.equal(captured.resolve(), template);
    assert.equal(captured.getRevision('constructor'), 0);
    assert.equal(captured.getRevision('__proto__'), 0);
    for (const key of ['constructor', '__proto__']) {
        assert.equal(Object.prototype.hasOwnProperty.call(captured.values, key), true);
        assert.equal(captured.values[key], '');
        assert.equal(captured.aiValues[key], undefined);
    }
    assert.ok(html.includes('prototype-regression-constructor'));
    assert.ok(html.includes('prototype-regression-__proto__'));
    assert.equal(html.includes('[object Object]'), false);
    assert.equal(html.includes('[native code]'), false);
    assert.equal(html.includes('AI-filled'), false);
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

check('a stale recorded user_text leaves the complete edited message alone', () => {
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
    assert.equal(readMessagePrompt(message), null);
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

check('a legacy split requires the exact delimiter, never a partial prefix', () => {
    const metadata = { prompt_selection: { selected_prompt_text: 'Prompt' } };
    assert.equal(readMessagePrompt({ content: 'Prompt\n\nQuestion.', metadata })?.userText, 'Question.');
    for (const content of ['Promptly do this.', 'Prompt changed.\n\nQuestion.', 'Prompt\nQuestion.']) {
        assert.equal(readMessagePrompt({ content, metadata }), null);
    }
    assert.equal(readMessagePrompt({
        content: 'Prompt\n\nQuestion.',
        metadata: { prompt_selection: { selected_prompt_text: 'Prompt', user_text: null } },
    })?.userText, 'Question.');
});

check('malformed and stale snapshots never fall through to legacy prefix stripping', () => {
    const info = buildPromptInfo({
        attached: attached(), promptText: 'Summarise the week.', userText: 'For Q3.', values: {},
    });
    const selection = promptSelectionMetadata(info);
    for (const change of [
        { composer_text: ['bad'] }, { composer_embedded: 'false' }, { template_content: null },
        { user_text: 'Other question.' }, { composer_text: 'Other question.' }, { composer_embedded: true },
    ]) {
        assert.equal(readMessagePrompt({
            content: 'Summarise the week.\n\nFor Q3.',
            metadata: { prompt_selection: { ...selection, ...change } },
        }), null);
    }
    for (const content of ['Summarise the week.\n\nFor Q4.', '[hidden]\n\nFor Q3.']) {
        assert.equal(readMessagePrompt({ content, metadata: { prompt_selection: selection } }), null);
    }
});

check('metadata cannot disclose composer words missing from an embedded stored message', () => {
    const info = buildPromptInfo({
        attached: attached({ originalContent: 'Summarise {{composer}}.' }),
        promptText: 'Summarise quarterly numbers.', userText: '',
        composerText: 'private other text', values: {},
    });
    assert.equal(readMessagePrompt({
        content: 'Summarise quarterly numbers.',
        metadata: { prompt_selection: promptSelectionMetadata(info) },
    }), null);
});

check('malformed scalar metadata and non-string values stay inert', () => {
    for (const promptSelection of [null, false, [], 'prompt', 1]) {
        assert.equal(readMessagePrompt({
            content: 'A message.', metadata: { prompt_selection: promptSelection },
        }), null);
    }
    const metadata = promptSelectionMetadata({
        name: ['bad'], id: { bad: true }, index: true, edited: 'false',
        variables: { valid: 'value', invalid: ['no'], empty: ' ' },
    });
    assert.equal(metadata.prompt_name, null);
    assert.equal(metadata.prompt_id, null);
    assert.equal(metadata.selected_prompt_index, null);
    assert.equal(metadata.prompt_edited, false);
    assert.deepEqual(metadata.prompt_variables, { valid: 'value' });
});

/* -------------------------- shipping store/controller --------------------------- */

function resetChat(conversationId = 'store-conversation') {
    useChatStore.setState({
        ...useChatStore.getInitialState(),
        activeConversationId: conversationId,
        activeConversationKind: 'personal',
    }, true);
    useCollaborationStore.setState(useCollaborationStore.getInitialState(), true);
}

check('orchestration optimistic messages retain snapshots when ids are reconciled', () => {
    resetChat();
    const info = buildPromptInfo({
        attached: attached(), promptText: 'Summarise the week.', userText: 'For Q3.', values: {},
    });
    const content = 'Summarise the week.\n\nFor Q3.';
    const pendingId = useChatStore.getState().beginOrchestrationTurn(
        'store-conversation', content, true, 'client-turn', info,
    );
    const before = useChatStore.getState().messages[0];
    assert.equal(before.metadata?.orchestration_turn_id, 'client-turn');
    assert.deepEqual(before.metadata?.prompt_selection, promptSelectionMetadata(info));
    useChatStore.getState().reassignOrchestrationTurn({
        fromConversationId: 'store-conversation', toConversationId: 'store-conversation',
        fromTurnId: 'client-turn', toTurnId: 'server-turn',
    });
    useChatStore.getState().settleOrchestrationTurn('store-conversation', {
        status: 'completed', accumulated: 'Answer.', pendingUserMessageId: pendingId,
        event: { message_id: 'answer-1', user_message_id: 'stored-user-1' },
    });
    const after = useChatStore.getState().messages.find((message) => message.id === 'stored-user-1');
    assert.ok(after);
    assert.equal(after.metadata?.orchestration_turn_id, 'server-turn');
    assert.deepEqual(after.metadata?.prompt_selection, before.metadata?.prompt_selection);
    assert.deepEqual(readMessagePrompt(after), readMessagePrompt(before));
});

check('old orchestration callers and re-plans do not acquire phantom prompt messages', () => {
    resetChat();
    useChatStore.getState().beginOrchestrationTurn('store-conversation', 'Ordinary question.');
    assert.equal(useChatStore.getState().messages[0].metadata, undefined);
    useChatStore.getState().beginOrchestrationTurn('store-conversation', '', false);
    assert.equal(useChatStore.getState().messages.length, 1);
    useChatStore.getState().beginOrchestrationTurn('somewhere-else', 'Do not show here.', true, 't1');
    assert.equal(useChatStore.getState().messages.length, 1);
});

check('dispatchPlan carries the prompt into both the optimistic message and request', async () => {
    resetChat();
    const info = buildPromptInfo({
        attached: attached(), promptText: 'Summarise the week.', userText: 'For Q3.', values: {},
    });
    const originalFetch = globalThis.fetch;
    let observed = false;
    globalThis.fetch = async (url, init) => {
        assert.equal(String(url), '/api/v2/orchestration/plan');
        const body = JSON.parse(String(init?.body));
        assert.deepEqual(body.prompt_info, info);
        assert.equal(body.message, 'Summarise the week.\n\nFor Q3.');
        const optimistic = useChatStore.getState().messages[0];
        assert.equal(optimistic.metadata?.orchestration_turn_id, body.turn_id);
        assert.deepEqual(optimistic.metadata?.prompt_selection, promptSelectionMetadata(info));
        observed = true;
        return new Response(`data: ${JSON.stringify({
            type: 'orchestration_plan', done: true,
            plan: {
                plan_id: 'plan-1', run_id: 'run-1', turn_id: body.turn_id,
                conversation_id: body.conversation_id, user_id: 'author-1', revision: 0,
                intent: { summary: body.message, complexity: 'simple' },
                steps: [], assumptions: [], status: 'awaiting_approval',
                approval: { mode: 'manual', state: 'pending' },
                validation: { valid: true, errors: [], warnings: [], repairs: [] },
            },
        })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } });
    };
    try {
        await startOrchestrationPlan({
            conversationId: 'store-conversation', message: 'Summarise the week.\n\nFor Q3.',
            approvalMode: 'manual', seeds: { prompt_info: info },
        });
        assert.equal(observed, true);
        assert.equal(useChatStore.getState().streaming, false);
        assert.equal(useChatStore.getState().streamError, null);
        assert.equal(readMessagePrompt(useChatStore.getState().messages[0])?.userText, 'For Q3.');
    } finally {
        globalThis.fetch = originalFetch;
    }
});

/* -------------------------- executed server snapshots --------------------------- */

interface LifecycleFixture {
    path: string;
    case: string;
    promptInfo: Json;
    stored: ChatMessage;
    echo: ChatMessage;
}

const fixtures: LifecycleFixture[] = process.argv.includes('--lifecycle-fixtures')
    ? JSON.parse(readFileSync(0, 'utf8'))
    : [];
if (process.argv.includes('--lifecycle-fixtures')) {
    assert.ok(fixtures.length > 0, 'backend lifecycle fixtures must execute, not silently skip');
}
for (const fixture of fixtures) {
    check(`${fixture.path}/${fixture.case}: optimistic, stored, echo and reload snapshots agree`, () => {
        const info = fixture.promptInfo;
        const metadata = promptSelectionMetadata(info);
        const rebuiltInfo = buildPromptInfo({
            attached: attached({
                id: String(info.id), name: String(info.name),
                originalContent: String(info.original_content),
                editedContent: info.edited ? String(info.template_content) : null,
                scopeType: String(info.scope_type), scopeName: String(info.scope_name),
            }),
            promptText: String(info.content), userText: String(info.user_text),
            composerText: String(info.composer_text), values: info.variables as Record<string, string>,
        });
        assert.deepEqual(promptSelectionMetadata(rebuiltInfo), metadata);
        assert.deepEqual(fixture.stored.metadata?.prompt_selection, metadata);
        assert.equal(fixture.stored.content, buildOutgoingMessage(
            String(info.template_content), String(info.content), String(info.composer_text),
        ).message);
        for (const message of [
            fixture.stored, fixture.echo, JSON.parse(JSON.stringify(fixture.stored)),
        ]) {
            assert.deepEqual(readMessagePrompt(message), {
                name: info.name, promptText: info.content, userText: info.composer_text,
                scopeLabel: 'Operations', edited: info.edited,
                variableCount: fixture.case === 'prompt-only'
                    ? 0
                    : fixture.case.startsWith('prototype-') ? 2 : 1,
            });
        }
    });
}

const plainSendOptions = {
    documentSearch: false, webSearch: false, imageGeneration: false,
    deepResearch: false, urlAccess: false,
};
for (const fixture of fixtures.filter((item) => item.case === 'appended'
    && (item.path === 'chat-stream' || item.path === 'shared-post'))) {
    check(`${fixture.path}: the real chat store sends and reconciles the attachment`, async () => {
        const conversationId = fixture.stored.conversation_id;
        resetChat(conversationId);
        if (fixture.path === 'shared-post') {
            useChatStore.setState({
                activeConversationKind: 'collaborative',
                conversations: [{
                    id: conversationId, title: 'Shared', conversation_kind: 'collaborative',
                }],
            });
        }
        const originalFetch = globalThis.fetch;
        let sent = false;
        globalThis.fetch = async (url, init) => {
            const path = String(url);
            const body = JSON.parse(String(init?.body ?? '{}'));
            assert.deepEqual(body.prompt_info, fixture.promptInfo);
            assert.equal(body.message ?? body.content, fixture.stored.content);
            assert.equal(readMessagePrompt(useChatStore.getState().messages[0])?.userText, 'Keep it brief.');
            sent = true;
            if (fixture.path === 'shared-post') {
                assert.equal(path, `/api/collaboration/conversations/${conversationId}/messages`);
                return new Response(JSON.stringify({
                    message: fixture.echo,
                    conversation: { id: conversationId, conversation_kind: 'collaborative', participants: [] },
                }), { headers: { 'Content-Type': 'application/json' } });
            }
            assert.equal(path, '/api/chat/stream');
            return new Response([
                `data: ${JSON.stringify({
                    type: 'user_message_persisted', conversation_id: conversationId,
                    user_message_id: fixture.stored.id, message_persisted: true,
                })}\n\n`,
                `data: ${JSON.stringify({ done: true, message_id: 'answer-1', user_message_id: fixture.stored.id })}\n\n`,
            ].join(''), { headers: { 'Content-Type': 'text/event-stream' } });
        };
        try {
            await useChatStore.getState().sendMessage(
                fixture.stored.content, { ...plainSendOptions, promptInfo: fixture.promptInfo },
            );
            assert.equal(sent, true);
            assert.equal(useChatStore.getState().streamError, null);
            const saved = useChatStore.getState().messages.find((message) => message.id === fixture.stored.id);
            assert.ok(saved);
            assert.deepEqual(readMessagePrompt(saved), readMessagePrompt(fixture.stored));
        } finally {
            globalThis.fetch = originalFetch;
        }
    });
}

/* ----------------------------------- runner ------------------------------------- */

let failed = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
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
