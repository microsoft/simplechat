// test_v2_delete_guard_conversation_logic.mjs
// Version: 0.261.164
// Implemented in: 0.261.164
// Executes the real V2 delete-guard helpers (lib/documentOperations.ts, lib/conversationUrl.ts). A
// conversation-linked delete guard names its conversation by title, as text, and the confirmation
// opens it natively at /chat?conversationId=<id>: the id is the guard's own conversation id or, without
// one, the conversation its url names, read only from a same-origin relative url. The server's url,
// which points at the classic chat page, is never followed, and an absolute, protocol-relative,
// backslash or scripted url never yields a conversation.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { deleteGuardConversation, sameOriginRelativePath } = await import('../application/v2_ui/src/lib/documentOperations.ts');
const { chatHrefForConversation } = await import('../application/v2_ui/src/lib/conversationUrl.ts');

const ORIGIN = 'https://simplechat.example';
const originalWindow = globalThis.window;
globalThis.window = { location: { origin: ORIGIN } };
let checks = 0;

function check(name, run) {
    run();
    checks += 1;
    console.log(`ok ${name}`);
}

function guard(conversation) {
    return {
        document_id: 'notes-document', error: 'conversation_linked_document_delete_requires_confirmation',
        message: 'This document is part of a conversation. Confirm its deletion.', needs_confirmation: true,
        conversation,
    };
}

const UNSAFE_URLS = [
    'https://evil.example/chats?conversation_id=stolen', `${ORIGIN}/chats?conversation_id=stolen`,
    '//evil.example/chats?conversation_id=stolen', '/\\evil.example/chats?conversation_id=stolen',
    'javascript:alert(1)//?conversation_id=stolen', 'JaVaScRiPt:alert(1)//?conversation_id=stolen',
    ' /chats?conversation_id=stolen', '/chats?conversation_id=stolen\n', 'chats?conversation_id=stolen',
];

try {
    check('only a same-origin relative path is one, normalized', () => {
        assert.equal(sameOriginRelativePath('/chats?conversation_id=existing-workspace-chat'), '/chats?conversation_id=existing-workspace-chat');
        assert.equal(sameOriginRelativePath('/chats/../chats?conversation_id=x'), '/chats?conversation_id=x');
        for (const url of [...UNSAFE_URLS, '///evil.example', '/chats\tx', '/chats x', '/chats\u0000', '', null, undefined, 42, {}, ['/chats']]) {
            assert.equal(sameOriginRelativePath(url), null, JSON.stringify(url));
        }
    });

    check('the guard\'s own conversation id opens the conversation, whatever its url', () => {
        for (const url of ['/chats?conversation_id=existing-workspace-chat', 'https://evil.example/chats', 'javascript:alert(1)', undefined]) {
            assert.deepEqual(
                deleteGuardConversation(guard({ id: ' existing-workspace-chat ', title: '  Planning review ', url })),
                { title: 'Planning review', conversationId: 'existing-workspace-chat' }, String(url),
            );
        }
    });

    check('without an id, a same-origin url names the conversation, canonical spelling first', () => {
        assert.deepEqual(
            deleteGuardConversation(guard({ title: 'Planning review', url: '/chats?conversation_id=from%20the%20url' })),
            { title: 'Planning review', conversationId: 'from the url' },
        );
        assert.deepEqual(
            deleteGuardConversation(guard({ id: '   ', title: 'Planning review', url: '/v2/chat?conversationId=canonical&conversation_id=legacy' })),
            { title: 'Planning review', conversationId: 'canonical' },
        );
    });

    check('an absolute, protocol-relative, backslash or scripted url never names a conversation', () => {
        for (const url of UNSAFE_URLS) {
            assert.deepEqual(
                deleteGuardConversation(guard({ title: 'Planning review', url })),
                { title: 'Planning review', conversationId: null }, JSON.stringify(url),
            );
        }
    });

    check('a url that names no conversation leaves the title alone', () => {
        for (const url of ['/chats', '/chats?conversation_id=', '/chats?conversation_id=%20%20', undefined, null]) {
            assert.deepEqual(
                deleteGuardConversation(guard({ title: 'Planning review', url })),
                { title: 'Planning review', conversationId: null }, JSON.stringify(url),
            );
        }
    });

    check('a title is the text it is, markup included, and a guard without one names none', () => {
        const markup = '<img src=x onerror=alert(1)>';
        assert.deepEqual(deleteGuardConversation(guard({ id: 'c', title: markup })), { title: markup, conversationId: 'c' });
        for (const conversation of [undefined, null, 'Planning review', ['Planning review'], { id: 'c', title: '' }, { title: '   ' }, { title: 7 }, { id: 'c', url: '/chats' }]) {
            assert.equal(deleteGuardConversation(guard(conversation)), null, JSON.stringify(conversation));
        }
        assert.equal(deleteGuardConversation({ document_id: 'x', error: 'synced_document_delete_requires_action' }), null);
    });

    check('the native link is the chat page with the conversation id encoded', () => {
        assert.equal(chatHrefForConversation('existing-workspace-chat'), '/chat?conversationId=existing-workspace-chat');
        assert.equal(chatHrefForConversation('a b/c?d&e'), '/chat?conversationId=a%20b%2Fc%3Fd%26e');
    });

    console.log(`${checks} delete guard conversation checks passed.`);
} finally {
    globalThis.window = originalWindow;
}
