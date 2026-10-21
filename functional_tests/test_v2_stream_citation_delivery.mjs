// test_v2_stream_citation_delivery.mjs
// Version: 0.261.367
// Implemented in: 0.261.365
// Real chat-store/SSE regressions with mocked HTTP only; no live model or connector calls.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const { mergeCollaborationMessage, useChatStore } = await import('../application/v2_ui/src/stores/chatStore.ts');
const { readSources } = await import('../application/v2_ui/src/lib/messageDetails.ts');

const tool = {
    tool_name: 'Example.lookupRecord',
    function_name: 'lookupRecord',
    plugin_name: 'Example',
    function_arguments: { record_id: 'record-42' },
    function_result: { amount: 125000, status: 'Awarded' },
    success: true,
    artifact_id: 'reply_artifact_1',
};
const web = { title: 'Reference', url: 'https://example.test/reference' };
const document = { file_name: 'brief.pdf', page_number: 2 };
const m365 = {
    citation_id: 'm365-1234567890abcdef', kind: 'file', source: 'spo',
    title: 'Notes', web_url: 'https://example.test/notes',
};

async function sendReply(event, check, { mode = 'send', beforeFinal, disconnect = false } = {}) {
    const originalFetch = globalThis.fetch;
    const originalDocument = globalThis.document;
    globalThis.document = Object.assign(new EventTarget(), { visibilityState: 'hidden' });
    const requests = [];
    const conversationId = 'citation-conversation';
    const final = {
        done: true, message_id: 'reply', conversation_id: conversationId,
        full_content: 'Model prose is not tool evidence.', metadata: {}, ...event,
    };
    const question = {
        id: 'question', role: 'user', conversation_id: conversationId, content: 'Look up the record.',
        metadata: { thread_info: { thread_id: 'thread', thread_attempt: 1 } },
    };
    let liveReply;
    useChatStore.setState({
        ...useChatStore.getInitialState(),
        activeConversationId: mode === 'resume' ? null : conversationId,
        activeConversationKind: 'personal',
        messages: mode === 'retry' || mode === 'edit' ? [question] : [],
        streaming: false,
        loadingMessages: false,
    }, true);
    globalThis.fetch = async (input, init = {}) => {
        const path = new URL(String(input), 'http://localhost').pathname;
        requests.push({ path, method: init.method ?? 'GET' });
        if (path === '/api/message/question/retry' || path === '/api/message/question/edit') {
            return Response.json({
                success: true, thread_id: 'thread', new_attempt: 2,
                user_message_id: question.id,
                user_message: { ...question, metadata: { thread_info: { thread_id: 'thread', thread_attempt: 2 } } },
                chat_request: { conversation_id: conversationId, message: question.content, retry_user_message_id: question.id },
            });
        }
        if (path === '/api/get_messages') {
            liveReply = useChatStore.getState().messages.find((message) => message.id === 'reply');
            return Response.json({ messages: mode === 'resume' ? [] : [
                { ...final, id: 'reply', role: 'assistant', content: final.full_content },
            ] });
        }
        if (path === `/api/chat/stream/status/${conversationId}`) {
            return Response.json({ pending: true });
        }
        if (path === '/api/chat/stream') {
            if (disconnect) {
                return new Response('data: {"content":"Discard this partial replay."}\n\n', {
                    headers: { 'Content-Type': 'text/event-stream' },
                });
            }
            beforeFinal?.(final);
            return new Response(`data: ${JSON.stringify(final)}\n\n`, {
                headers: { 'Content-Type': 'text/event-stream' },
            });
        }
        if (path === `/api/chat/stream/reattach/${conversationId}`) {
            return new Response(`data: ${JSON.stringify(final)}\n\n`, {
                headers: { 'Content-Type': 'text/event-stream' },
            });
        }
        return new Response(JSON.stringify({ success: true, messages: [], pending_actions: [] }), {
            headers: { 'Content-Type': 'application/json' },
        });
    };
    try {
        if (mode === 'retry') await useChatStore.getState().retryMessage('question');
        else if (mode === 'edit') await useChatStore.getState().editMessage('question', 'Look up another record.');
        else if (mode === 'resume') {
            await useChatStore.getState().selectConversation(conversationId, { kind: 'personal' });
            for (let tick = 0; tick < 100 && !useChatStore.getState().messages.some((message) => message.id === 'reply'); tick++) {
                await new Promise((resolve) => setTimeout(resolve, 0));
            }
        } else await useChatStore.getState().sendMessage('Look up the record.', {});
        const reply = useChatStore.getState().messages.find((message) => message.id === 'reply');
        assert.ok(reply, `the real send/stream path must produce the saved reply: ${JSON.stringify({
            error: useChatStore.getState().streamError, requests,
        })}`);
        if (mode === 'retry' || mode === 'edit') {
            assert.ok(liveReply, 'retry/edit must publish the completed reply before reloading history');
        }
        await check(liveReply ?? reply, requests);
        assert.equal(requests.filter(({ path }) => path === '/api/chat/stream').length, mode === 'resume' ? 0 : 1);
        assert.equal(requests.filter(({ path }) => path.includes('get_messages')).length, mode === 'send' ? 0 : 1);
        assert.equal(requests.filter(({ path }) => path.includes('/reattach/')).length,
            mode === 'resume' || disconnect ? 1 : 0, 'reconnect must not replay the action request');
    } finally {
        globalThis.fetch = originalFetch;
        if (originalDocument === undefined) delete globalThis.document;
        else globalThis.document = originalDocument;
        useChatStore.setState({ ...useChatStore.getInitialState() }, true);
    }
}

test('completed live replies preserve every citation family and full tool metadata', async () => {
    await sendReply({
        agent_citations: [tool], web_search_citations: [web],
        hybrid_citations: [document], m365_citations: [m365],
    }, (reply) => {
        const sources = readSources(reply);
        assert.deepEqual(sources.tools, [tool]);
        assert.deepEqual(sources.web, [web]);
        assert.deepEqual(sources.documents, [document]);
        assert.equal(sources.m365.length, 1);
        assert.equal(sources.total, 4);
    });
});

test('web-only replies expose sources before a reload', async () => {
    await sendReply({ web_search_citations: [web] }, (reply) => {
        assert.deepEqual(readSources(reply).web, [web]);
    });
});

test('large tool results and artifact references survive live completion unchanged', async () => {
    const evidence = { ...tool, function_result: { rows: Array.from({ length: 300 }, (_, id) => ({
        id, description: `Record ${id}: ${'detail '.repeat(20)}`,
    })) }, result_is_truncated: true, result_truncation_limit: 50 };
    await sendReply({ agent_citations: [evidence] }, (reply) => {
        assert.deepEqual(readSources(reply).tools, [evidence]);
    });
});

for (const result of [{ error: 'HTTP 502', status_code: 502 }, null]) {
    test(`failed tool evidence is retained with ${result ? 'a returned error' : 'no result'}`, async () => {
        const failure = { ...tool, success: false, error_message: 'Upstream unavailable.', function_result: result };
        await sendReply({ agent_citations: [failure] }, (reply) => {
            assert.deepEqual(readSources(reply).tools, [failure]);
        });
    });
}

for (const event of [{ blocked: true }, { role: 'safety' }]) {
    test(`moderated replies suppress all evidence (${JSON.stringify(event)})`, async () => {
        await sendReply({
            ...event, agent_citations: [tool], web_search_citations: [web],
            hybrid_citations: [document], m365_citations: [m365],
        }, (reply) => {
            assert.equal(reply.role, 'safety');
            assert.equal(readSources(reply).total, 0);
        });
    });
}

test('missing and empty citation arrays do not invent sources', async () => {
    for (const event of [{}, { agent_citations: [], web_search_citations: [] }]) {
        await sendReply(event, (reply) => assert.equal(readSources(reply).total, 0));
    }
});

for (const mode of ['retry', 'edit', 'resume']) {
    test(`${mode} completion retains live evidence before any history refresh`, async () => {
        await sendReply({ agent_citations: [tool], web_search_citations: [web] }, (reply) => {
            assert.deepEqual(readSources(reply).tools, [tool]);
            assert.deepEqual(readSources(reply).web, [web]);
        }, { mode });
    });
}

test('a recovered transport delivers evidence without sending a second action request', async () => {
    await sendReply({ agent_citations: [tool], web_search_citations: [web] }, (reply) => {
        assert.deepEqual(readSources(reply).tools, [tool]);
        assert.deepEqual(readSources(reply).web, [web]);
        assert.equal(reply.content, 'Model prose is not tool evidence.');
    }, { disconnect: true });
});

for (const order of ['echo-first', 'stream-first']) {
    test(`collaboration ${order} merges one reply without losing evidence`, async () => {
        const echo = (final) => ({
            ...final, id: 'reply', role: 'assistant', content: final.full_content,
        });
        await sendReply({ agent_citations: [tool], web_search_citations: [web] }, (reply) => {
            if (order === 'stream-first') {
                useChatStore.setState((state) => ({
                    messages: mergeCollaborationMessage(state.messages, echo(reply)),
                }));
            }
            const replies = useChatStore.getState().messages.filter((message) => message.id === 'reply');
            assert.equal(replies.length, 1);
            assert.deepEqual(readSources(replies[0]).tools, [tool]);
            assert.deepEqual(readSources(replies[0]).web, [web]);
        }, { beforeFinal: order === 'echo-first' ? (final) => {
            useChatStore.setState((state) => ({
                messages: mergeCollaborationMessage(state.messages, echo(final)),
            }));
        } : undefined });
    });
}

for (const guard of [{}, { blocked: true }, { role: 'safety' }]) {
    test(`orchestration uses identical evidence projection (${JSON.stringify(guard)})`, async () => {
        const event = {
            ...guard, agent_citations: [tool], web_search_citations: [web],
            hybrid_citations: [document], m365_citations: [m365],
        };
        await sendReply(event, (reply) => {
            const expected = readSources(reply);
            useChatStore.setState({ messages: [] });
            useChatStore.getState().settleOrchestrationTurn('citation-conversation', {
                status: 'completed', accumulated: '',
                event: { ...event, message_id: 'orchestrated-reply', full_content: 'Model prose.' },
            });
            const final = useChatStore.getState().messages.find((message) => message.id === 'orchestrated-reply');
            assert.ok(final);
            assert.deepEqual(readSources(final), expected);
        });
    });
}
