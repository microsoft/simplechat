// test_v2_shared_orchestration_routing.mjs
//
// Runtime test for Orchestrate in V2 shared conversations.
// Version: 0.261.269
// Implemented in: 0.261.269 (Refs #1659)
//
// With Orchestrate on, every message in a shared conversation used to start a plan, so a remark
// addressed only to another person was sent to the model. The composer now applies the shared
// conversation send rule first, the same rule manual sends use: a message that addresses only
// people is posted to them. Only the person who started the conversation plans in it.
//
// This file executes the real send rule and the real chat store merge for the shared copies of
// an orchestrated question and answer, and checks the composer wiring that a runtime test cannot
// reach without a browser.
//
// Run directly with `node functional_tests/test_v2_shared_orchestration_routing.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real modules can be imported.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Registers the resolver for the real V2 modules; it must load before the dynamic imports below.
import './test_support/tsResolve.mjs';

const { resolveSendTarget, sharedConversationTarget } = await import('../application/v2_ui/src/lib/mentions.ts');
const { mergeCollaborationMessage } = await import('../application/v2_ui/src/stores/chatStore.ts');

const AGENTS = [
    { id: 'agent-1', name: 'researcher', display_name: 'Research Assistant', scope_type: 'personal' },
];
const MODELS = [
    { selection_key: 'user::ep1::gpt-4o', display_name: 'GPT-4o', deployment_name: 'gpt-4o', endpoint_id: 'ep1' },
];
const CATALOGS = { agents: AGENTS, models: MODELS };
const OPTIONS = {
    agentSelection: undefined,
    promptId: undefined,
    documentSearch: false,
    webSearch: false,
    imageGeneration: false,
    deepResearch: false,
    urlAccess: false,
    modelDeployment: 'user::ep1::gpt-4o',
};

const source = (path) => readFileSync(new URL(`../application/v2_ui/src/${path}`, import.meta.url), 'utf8');

test('a message that addresses only people never reaches a model or a plan', () => {
    assert.equal(sharedConversationTarget('@Ada Lovelace can you check this?', OPTIONS, CATALOGS), null);
    assert.equal(sharedConversationTarget('Thanks, everyone.', OPTIONS, CATALOGS), null);
});

test('an agent or model tag addresses the assistant exactly as the manual send rule does', () => {
    const message = '@Research Assistant summarize the thread';
    const target = sharedConversationTarget(message, OPTIONS, CATALOGS);

    assert.equal(target?.target_type, 'agent');
    assert.equal(target?.source_mode, 'explicit_tag');
    assert.deepEqual(target, resolveSendTarget(message, OPTIONS, CATALOGS));
    assert.equal(sharedConversationTarget('@GPT-4o summarize the thread', OPTIONS, CATALOGS)?.target_type, 'model');
});

test('a source toggle addresses the assistant unless a saved analysis is being asked about', () => {
    const searching = { ...OPTIONS, webSearch: true };

    assert.equal(sharedConversationTarget('What changed this week?', searching, CATALOGS)?.source_mode, 'web_search');
    assert.equal(
        sharedConversationTarget('What changed this week?', searching, CATALOGS, { savedContext: true }),
        null,
    );
    // A selected agent still addresses the assistant while a saved analysis is open.
    assert.equal(
        sharedConversationTarget('Explain it', { ...OPTIONS, agentSelection: 'agent-key' }, CATALOGS, {
            savedContext: true,
        })?.target_type,
        'agent',
    );
});

test("the shared copy of an orchestrated question replaces the run's own bubble", () => {
    const thread = [{ id: 'user_1', role: 'user', content: 'Draft the note', metadata: {} }];
    const copy = {
        id: 'collab-1', role: 'user', content: 'Draft the note',
        metadata: { source_message_id: 'user_1' }, sender: { user_id: 'owner' },
    };
    const merged = mergeCollaborationMessage(thread, copy, { currentUserId: 'owner' });

    assert.equal(merged.length, 1);
    assert.equal(merged[0].id, 'collab-1');
});

test("a run's answer that lands after its shared copy updates the copy instead of doubling it", () => {
    const thread = [{
        id: 'collab-2', role: 'assistant', content: 'Here is the note.',
        metadata: { source_message_id: 'assistant_1' },
    }];
    const answer = {
        id: 'assistant_1', role: 'assistant', content: 'Here is the note.',
        metadata: { orchestration: { run_id: 'run-1' } },
    };
    const merged = mergeCollaborationMessage(thread, answer);

    assert.equal(merged.length, 1);
    assert.equal(merged[0].metadata.orchestration.run_id, 'run-1');
    // The copy arriving again, as an event replay would deliver it, still leaves one message.
    assert.equal(mergeCollaborationMessage(merged, thread[0]).length, 1);
});

test('unrelated messages are still appended', () => {
    const thread = [{ id: 'a', role: 'user', content: 'one', metadata: {} }];
    const merged = mergeCollaborationMessage(thread, { id: 'b', role: 'user', content: 'two', metadata: {} });

    assert.deepEqual(merged.map((message) => message.id), ['a', 'b']);
});

test('the composer applies the shared send rule before planning and plans only for the owner', () => {
    const composer = source('components/chat/Composer.tsx');
    const helper = composer.slice(
        composer.indexOf('const sharedOrchestrationRequest = '),
        composer.indexOf('const dispatchOrchestration = ('),
    );

    assert.match(
        composer,
        /const sharedRequest = orchestrating && shared \? sharedOrchestrationRequest\(outgoing\.message\) : null;\s*if \(orchestrating && shared && !sharedRequest\) \{\s*dispatch\(outgoing\);\s*return;/,
    );
    assert.match(composer, /dispatchOrchestration\(outgoing\.message, outgoing\.promptInfo, sharedRequest\);/);
    assert.match(helper, /sharedConversationTarget\(message, options,/);
    assert.match(helper, /if \(!target \|\| !sharedOrchestrationAllowed\) \{\s*return null;/);
    assert.match(helper, /invocation_target: target/);
    assert.match(helper, /mentioned_participants: extractMentionedParticipants\(/);
    assert.match(composer, /collaboration\.user_id === bootstrap\.user\.id/);
    // An explicit tag seeds the plan's agent or model in personal and shared conversations alike.
    assert.match(composer, /const tagged = resolveInvocationTarget\(/);
    assert.match(composer, /agentSelection: taggedAgent \?\? \(taggedModel \? undefined : options\.agentSelection\)/);
});

test('manual sends and Orchestrate share one rule', () => {
    const store = source('stores/chatStore.ts');

    assert.match(store, /\? sharedConversationTarget\(\s*trimmed,\s*options,/);
    assert.doesNotMatch(store, /resolveSendTarget\(/);
});
