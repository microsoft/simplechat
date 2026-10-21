// test_v2_public_source_policy.mjs
// Version: 0.261.372
// Implemented in: 0.261.372
// Real V2 transport, scope, discovery, URL builders and SSE recovery; synthetic HTTP only.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const { safeV2SourceUrl, v2ApiFetch } = await import('../application/v2_ui/src/lib/v2SourcePolicy.ts');
const { isChattableStatus } = await import('../application/v2_ui/src/lib/publicAvailability.ts');
const { readPublicWorkspaceSelection, publicChatScopeFromMessages } = await import('../application/v2_ui/src/lib/publicChatScope.ts');
const { resolveDocumentScope } = await import('../application/v2_ui/src/lib/documentScope.ts');
const { WRITABLE_USER_SETTING_KEYS } = await import('../application/v2_ui/src/lib/userSettings.ts');
const { api, uploadFile } = await import('../application/v2_ui/src/lib/apiClient.ts');
const endpoints = await import('../application/v2_ui/src/lib/endpoints.ts');
const { streamChat } = await import('../application/v2_ui/src/lib/sse.ts');
const { searchContextCandidates } = await import('../application/v2_ui/src/lib/contextMentions.ts');
const { useChatStore } = await import('../application/v2_ui/src/stores/chatStore.ts');
const { openImageInNewTab } = await import('../application/v2_ui/src/lib/images.ts');
const { generatedDocumentDownloadUrl, fetchGeneratedDocument } = await import('../application/v2_ui/src/lib/generatedDocuments.ts');

test('availability is status-based, not classic public curation', () => {
    for (const status of ['active', 'locked', 'upload_disabled']) {
        assert.equal(isChattableStatus(status), true);
    }
    for (const status of ['inactive', 'unknown', 'archived', '', 'deleting']) {
        assert.equal(isChattableStatus(status), false);
    }
    for (const key of ['publicDirectorySettings', 'publicDirectorySavedLists', 'visiblePublicWorkspaceIds']) {
        assert.equal(WRITABLE_USER_SETTING_KEYS.includes(key), false);
    }
});

test('legacy visible input normalizes to canonical all without changing ordinary mixed scope', () => {
    assert.equal(readPublicWorkspaceSelection('visible'), 'all');
    assert.equal(readPublicWorkspaceSelection('all'), 'all');
    assert.equal(readPublicWorkspaceSelection('anything-else'), null);
    assert.equal(publicChatScopeFromMessages([
        { role: 'user', metadata: { workspace_search: { public_workspace_selection: 'visible' } } },
    ]), 'all');
    assert.equal(publicChatScopeFromMessages([
        { role: 'user', metadata: { public_workspace_selection: 'visible' } },
        { role: 'user', metadata: {} },
    ]), null);
    assert.deepEqual(resolveDocumentScope({
        publicWorkspaceSelection: 'visible', contextGroupIds: ['group-1'],
    }), {
        public_workspace_selection: 'all', doc_scope: 'public',
        active_group_ids: [], active_group_id: null,
        active_public_workspace_ids: [], active_public_workspace_id: null,
    });
    const mixed = resolveDocumentScope({
        contextGroupIds: ['group-1'], contextPublicWorkspaceIds: ['public-1'],
    });
    assert.equal(mixed.doc_scope, 'all');
    assert.deepEqual(mixed.active_group_ids, ['group-1']);
    assert.deepEqual(mixed.active_public_workspace_ids, ['public-1']);
    assert.equal('public_workspace_selection' in mixed, false);
    const originalSelection = useChatStore.getState().publicWorkspaceSelection;
    try {
        useChatStore.getState().setPublicWorkspaceSelection('visible');
        assert.equal(useChatStore.getState().publicWorkspaceSelection, 'all');
    } finally {
        useChatStore.setState({ publicWorkspaceSelection: originalSelection });
    }
});

test('navigation marker is restricted, idempotent and leaves signed URLs byte-for-byte intact', () => {
    for (const path of ['/api/workspace_documents/download?doc_id=a',
        'http://localhost/api/enhanced_citations/image?doc_id=a',
        '/api/enhanced_citations/visio?doc_id=a#page=2',
        '/api/image/message?variant=display']) {
        const marked = safeV2SourceUrl(path);
        const url = new URL(marked, 'http://localhost');
        assert.equal(url.searchParams.get('ui_version'), 'v2');
        assert.equal(safeV2SourceUrl(marked), marked);
    }
    assert.equal(safeV2SourceUrl('/api/enhanced_citations/image?ui_version=v1'),
        '/api/enhanced_citations/image?ui_version=v2');
    for (const url of [
        'https://storage.example.test/api/document?sig=a%2Bb%2Fc&se=123',
        'https://other.test/api/get_citation', '//other.test/api/a', '//localhost/api/a',
        '/apiary', '/v2/chat', '/static/document.pdf', 'blob:http://localhost/id',
        'data:text/plain,example', 'javascript:void(0)', '/\\other.test/api/a',
        'http://user:password@localhost/api/a', '/api/a\n',
        '/api', '/api/get_citation', '/api/enhanced_citations/pdf?doc_id=a',
        '/api/public_workspaces/directory?view=all',
        '/api/public-workspaces/public-1/documents/document-1',
        '/api/public-workspaces/public-1/documents/document-1/download',
        '/api/public-workspaces/public-1/documents/document-1/versions/revision-1',
        '/api/chat_artifacts/download?conversation_id=c&message_id=m',
        '/api/conversations/c/generated-documents/d/download',
        '/api/collaboration/conversations/c/generated-documents/d/download',
    ]) {
        assert.equal(safeV2SourceUrl(url), url);
    }
});

test('the browser origin, not a hostname substring, determines first-party URLs', async () => {
    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.window = { location: { origin: 'https://simplechat.test' } };
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        return Response.json({});
    };
    try {
        const local = 'https://simplechat.test/api/enhanced_citations/image?doc_id=a';
        const marked = safeV2SourceUrl(local);
        assert.equal(new URL(marked).searchParams.get('ui_version'), 'v2');
        await v2ApiFetch(local);
        assert.equal(new Headers(calls.at(-1).init.headers).get('X-SimpleChat-UI'), 'v2');
        for (const external of [
            'https://simplechat.test.evil.test/api/a', 'https://evil.test/api/simplechat.test/a',
            'http://simplechat.test/api/a', 'https://simplechat.test:444/api/a',
        ]) {
            assert.equal(safeV2SourceUrl(external), external);
            await v2ApiFetch(external);
            assert.equal(new Headers(calls.at(-1).init.headers).has('X-SimpleChat-UI'), false);
        }
    } finally {
        globalThis.fetch = originalFetch;
        if (originalWindow === undefined) delete globalThis.window;
        else globalThis.window = originalWindow;
    }
});

test('generated downloads use raw-fetch headers without adding query parameters', async () => {
    const artifactUrl = endpoints.generatedArtifactDownloadUrl({
        artifact_message_id: 'message', conversation_id: 'conversation',
    });
    assert.equal(artifactUrl, '/api/chat_artifacts/download?conversation_id=conversation&message_id=message');
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        return new Response('synthetic file');
    };
    try {
        for (const [kind, expected] of [
            ['personal', '/api/conversations/conversation/generated-documents/document/download'],
            ['collaborative', '/api/collaboration/conversations/conversation/generated-documents/document/download'],
        ]) {
            const url = generatedDocumentDownloadUrl('conversation', kind, 'document');
            assert.equal(url, expected);
            const file = await fetchGeneratedDocument('conversation', kind, 'document');
            assert.equal(await file.text(), 'synthetic file');
            assert.equal(calls.at(-1).url, expected);
            assert.equal(new Headers(calls.at(-1).init.headers).get('X-SimpleChat-UI'), 'v2');
        }
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('image navigation validates the source and never marks an external signed image', () => {
    const originalWindow = globalThis.window;
    const opened = [];
    globalThis.window = {
        location: { origin: 'http://localhost' },
        open(url) {
            opened.push(url);
            return { opener: null };
        },
    };
    try {
        const refused = openImageInNewTab({ kind: 'external', src: 'javascript:doNotRun()' });
        assert.equal(refused, false);
        assert.deepEqual(opened, []);
        const local = openImageInNewTab({ kind: 'endpoint', src: '/api/image/message?variant=display' });
        assert.equal(local, true);
        assert.equal(opened.at(-1), '/api/image/message?variant=display&ui_version=v2');
        const signed = 'https://blob.example.test/image.png?sig=opaque%2Bsignature';
        const external = openImageInNewTab({ kind: 'external', src: signed });
        assert.equal(external, true);
        assert.equal(opened.at(-1), signed);
    } finally {
        if (originalWindow === undefined) delete globalThis.window;
        else globalThis.window = originalWindow;
    }
});

test('central JSON, multipart, raw reads and external calls keep the marker boundary', async () => {
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        return Response.json({ success: true });
    };
    try {
        await api.get('/api/public_workspace_documents');
        await api.post('/api/get_citation', { citation_id: 'guide_1' });
        const form = new FormData();
        form.set('file', 'synthetic');
        await uploadFile('/api/upload', form);
        for (const call of calls) {
            assert.equal(new Headers(call.init.headers).get('X-SimpleChat-UI'), 'v2');
            assert.equal(call.init.redirect, 'error', 'marked fetches cannot redirect the custom header externally');
        }
        assert.equal(new Headers(calls[2].init.headers).has('Content-Type'), false);
        const custom = new Headers({ Accept: 'text/plain', 'X-CSRFToken': 'test-csrf' });
        await v2ApiFetch('/api/source', { headers: custom });
        assert.equal(new Headers(calls.at(-1).init.headers).get('X-CSRFToken'), 'test-csrf');
        assert.equal(custom.has('X-SimpleChat-UI'), false, 'do not mutate caller headers');
        const signed = 'https://blob.example.test/file?sig=opaque%2Bsignature';
        await v2ApiFetch(signed, { headers: { 'X-SimpleChat-UI': 'v2' } });
        assert.equal(calls.at(-1).url, signed);
        assert.equal(new Headers(calls.at(-1).init.headers).has('X-SimpleChat-UI'), false);
        assert.equal(calls.at(-1).init.redirect, undefined);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('citation media, download and tabular navigation carry the V2 marker', () => {
    for (const url of [
        endpoints.enhancedCitationMediaUrl('audio', 'public-guide'),
        endpoints.enhancedCitationMediaUrl('video', 'public-guide'),
        endpoints.enhancedCitationImageUrl('public-guide'),
        endpoints.enhancedCitationVisioUrl('public-guide', 2, true),
        endpoints.workspaceDocumentDownloadUrl('public-guide'),
        endpoints.tabularWorkspaceDownloadUrl('public-guide'),
        endpoints.chatUploadTabularDownloadUrl('conversation', 'file'),
    ]) {
        const parsed = new URL(url, 'http://localhost');
        assert.equal(parsed.searchParams.get('ui_version'), 'v2');
        assert.ok(parsed.pathname.startsWith('/api/'));
    }
});

test('current-context search retains personal, group, public documents and tags without aggregate mode', async () => {
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init) => {
        const parsed = new URL(url, 'http://localhost');
        calls.push({ parsed, init });
        if (parsed.pathname.endsWith('/tags')) return Response.json({ tags: [{ name: 'ready' }] });
        const scope = parsed.pathname.includes('public_workspace') ? 'public'
            : parsed.pathname.includes('group') ? 'group' : 'personal';
        return Response.json({
            documents: [{
                id: `${scope}-document`, file_name: `${scope}-guide.md`, status: 'completed',
                ...(scope === 'group' ? { group_id: 'group-1' } : {}),
                ...(scope === 'public' ? { public_workspace_id: 'public-1' } : {}),
            }],
            total_count: 1,
        });
    };
    try {
        const results = await searchContextCandidates({
            query: '', groups: [{ id: 'group-1', name: 'Group' }],
            publicWorkspaces: [{ id: 'public-1', name: 'Public' }],
            groupsEnabled: true, publicEnabled: true,
        });
        assert.deepEqual(results.filter((item) => item.kind === 'document')
            .map((item) => item.document.id).sort(), ['group-document', 'personal-document', 'public-document']);
        assert.ok(results.some((item) => item.kind === 'tag' && item.scope.kind === 'public'));
        for (const { parsed, init } of calls) {
            assert.equal(new Headers(init.headers).get('X-SimpleChat-UI'), 'v2');
            assert.equal(parsed.searchParams.has('public_workspace_selection'), false);
        }
        await endpoints.fetchPublicWorkspaceDocuments({}, undefined, 'visible');
        assert.equal(calls.at(-1).parsed.searchParams.get('public_workspace_selection'), 'all');
        await endpoints.fetchPublicWorkspaceDocumentTags(undefined, 'visible');
        assert.equal(calls.at(-1).parsed.searchParams.get('public_workspace_selection'), 'all');
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('stream submission, dropped-stream status and reattach all carry the V2 marker', async () => {
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, init });
        if (url.includes('/status/')) return Response.json({ pending: true });
        return new Response(url.includes('/reattach/')
            ? 'data: {"done":true,"full_content":"Recovered answer"}\n\n'
            : 'data: {"content":"Partial answer"}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } });
    };
    try {
        const result = await streamChat({
            conversation_id: 'public-source-conversation', message: 'Compare selected sources',
            doc_scope: 'all', active_group_ids: ['group-1'], active_public_workspace_ids: ['public-1'],
            selected_document_ids: ['personal-document', 'group-document', 'public-document'],
        }, {});
        assert.equal(result.completed, true);
        assert.equal(result.reconnected, true);
        const sourceCalls = calls.filter(({ url }) => url.includes('/api/chat/stream'));
        assert.equal(sourceCalls.length, 3);
        for (const { init } of sourceCalls) {
            assert.equal(new Headers(init.headers).get('X-SimpleChat-UI'), 'v2');
        }
        const body = JSON.parse(sourceCalls[0].init.body);
        assert.equal(body.doc_scope, 'all');
        assert.deepEqual(body.selected_document_ids, ['personal-document', 'group-document', 'public-document']);
        assert.equal('public_workspace_selection' in body, false);
    } finally {
        globalThis.fetch = originalFetch;
    }
});
