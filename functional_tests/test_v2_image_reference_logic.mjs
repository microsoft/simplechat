// test_v2_image_reference_logic.mjs
// Version: 0.261.144
// Implemented in: 0.261.144
// Pure helper coverage for v2 image reference request normalization, composer merging, and gating.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

const imageReferencesUrl = new URL('../application/v2_ui/src/lib/imageReferences.ts', import.meta.url);
const composerDraftUrl = new URL('../application/v2_ui/src/lib/composerDraft.ts', import.meta.url);
const chatPreviewUrl = new URL('../application/v2_ui/src/lib/chatImagePreview.ts', import.meta.url);
const chatUploadsUrl = new URL('../application/v2_ui/src/lib/chatUploads.ts', import.meta.url);

const reactStub = `
    function unused() { throw new Error('A pure image reference helper accessed React.'); }
    export { unused as useEffect, unused as useMemo, unused as useState, unused as useSyncExternalStore };
`;
const orchestrationStoreStub = `
    export const useOrchestrationStore = {
        getState() { throw new Error('A pure image reference helper accessed orchestration state.'); },
        subscribe() { throw new Error('A pure image reference helper subscribed to orchestration state.'); },
    };
`;
const boundary = registerHooks({
    resolve(specifier, context, nextResolve) {
        if ([imageReferencesUrl.href, chatPreviewUrl.href, chatUploadsUrl.href].includes(context.parentURL)
            && specifier === 'react') {
            return { shortCircuit: true, url: `data:text/javascript,${encodeURIComponent(reactStub)}` };
        }
        if (context.parentURL === chatUploadsUrl.href && specifier === '../stores/orchestrationStore') {
            return { shortCircuit: true, url: `data:text/javascript,${encodeURIComponent(orchestrationStoreStub)}` };
        }
        return nextResolve(specifier, context);
    },
});

const {
    HEIF_REFERENCE_HINT,
    effectiveReferenceImageLimit,
    imageReferenceKey,
    imageReferencePreviewUrl,
    isHeifFileName,
    isReferenceImageFileName,
    normalizeImageReferences,
    readImageReferenceProvenance,
} = await import(imageReferencesUrl);
const {
    composerDraftImageReferences,
    createComposerDraft,
} = await import(composerDraftUrl);
const { resolveGating } = await import('../application/v2_ui/src/lib/composerGating.ts');
const { collectScopeDocuments } = await import('../application/v2_ui/src/lib/contextMentions.ts');
boundary.deregister();

const checks = [];
const check = (name, run) => checks.push([name, run]);

const editCapability = {
    enabled: true,
    mode: 'edit',
    model_name: 'gpt-image',
    reason: '',
    provider_label: 'OpenAI',
    cloud_label: 'Commercial',
    availability: 'documented',
    availability_reason: '',
    editing: true,
    masking: false,
    sizes: [],
    qualities: [],
    backgrounds: [],
    max_reference_images: 16,
    input_fidelity: true,
};

check('reference filename helpers allow only upload-compatible model formats', () => {
    for (const name of ['house.png', 'face.JPG', 'map.jpeg', 'diagram.bmp', 'scan.tif', 'scan.tiff']) {
        assert.equal(isReferenceImageFileName(name), true, name);
    }
    for (const name of ['clip.gif', 'image.webp', 'portrait.heic', 'photo.heif', 'report.pdf']) {
        assert.equal(isReferenceImageFileName(name), false, name);
    }
    assert.equal(isHeifFileName('photo.HEIC'), true);
    assert.match(HEIF_REFERENCE_HINT, /Convert/i);
});

check('capability limit is zero unless the model can edit and clamps to the app cap', () => {
    assert.equal(effectiveReferenceImageLimit(editCapability), 10);
    assert.equal(effectiveReferenceImageLimit({ ...editCapability, max_reference_images: 3 }), 3);
    assert.equal(effectiveReferenceImageLimit({ ...editCapability, editing: false }), 0);
    assert.equal(effectiveReferenceImageLimit({ ...editCapability, enabled: false }), 0);
});

check('normalizeImageReferences validates, dedupes and caps in order', () => {
    const refs = normalizeImageReferences([
        { type: 'message', message_id: ' message-1 ' },
        { type: 'message', message_id: 'message-1' },
        { type: 'document', document_id: 'doc-1', scope: 'personal', scope_id: 'ignored' },
        { type: 'document', document_id: 'doc-2', scope: 'group', scope_id: 'group-1' },
        { type: 'document', document_id: 'doc-3', scope: 'group', scope_id: '' },
        { type: 'unknown', id: 'x' },
    ], 3);
    assert.deepEqual(refs, [
        { type: 'message', message_id: 'message-1' },
        { type: 'document', document_id: 'doc-1', scope: 'personal', scope_id: null },
        { type: 'document', document_id: 'doc-2', scope: 'group', scope_id: 'group-1' },
    ]);
    assert.equal(imageReferenceKey(refs[2]), 'document:group:group-1:doc-2');
});

check('preview URLs target chat messages or workspace image previews', () => {
    assert.equal(
        imageReferencePreviewUrl({ type: 'message', message_id: 'conv image/1' }, 'display'),
        '/api/image/conv%20image%2F1?variant=display',
    );
    assert.equal(
        imageReferencePreviewUrl({ type: 'document', document_id: 'doc 1', scope: 'personal', scope_id: null }),
        '/api/workspace_documents/image_preview?doc_id=doc+1&scope=personal&variant=thumbnail',
    );
    assert.equal(
        imageReferencePreviewUrl({ type: 'document', document_id: 'doc/2', scope: 'group', scope_id: 'g 1' }, 'display'),
        '/api/workspace_documents/image_preview?doc_id=doc%2F2&scope=group&variant=display&scope_id=g+1',
    );
});

check('provenance reader preserves safe labels and drops malformed entries', () => {
    const provenance = readImageReferenceProvenance({
        image_references: [
            { type: 'message', message_id: 'm1', file_name: '<b>face.png</b>', width: 512, height: 256 },
            { type: 'document', document_id: 'd1', scope: 'public', scope_id: 'p1', file_name: 'map.png' },
            { type: 'document', document_id: '', scope: 'personal' },
        ],
    });
    assert.deepEqual(provenance, [
        { type: 'message', message_id: 'm1', file_name: '<b>face.png</b>', width: 512, height: 256 },
        {
            type: 'document', document_id: 'd1', scope: 'public', scope_id: 'p1',
            file_name: 'map.png', width: null, height: null,
        },
    ]);
});

check('composerDraftImageReferences merges uploads, image documents and explicit refs', () => {
    const draft = {
        ...createComposerDraft(),
        uploads: [
            {
                id: 'u1', fileName: 'house.png', state: 'ready', fileMessageId: 'file-msg-1',
                reference: { kind: 'document', id: 'doc-upload', scope: { kind: 'personal', id: null } },
            },
            {
                id: 'u2', fileName: 'legacy.jpg', state: 'ready',
                reference: { kind: 'chat_attachment', id: 'legacy-msg', scope: { kind: 'chat', id: 'conv-1' } },
            },
            {
                id: 'u3', fileName: 'fallback.tiff', state: 'ready',
                reference: { kind: 'document', id: 'doc-fallback', scope: { kind: 'group', id: 'group-1' } },
            },
            {
                id: 'u4', fileName: 'portrait.heic', state: 'ready', fileMessageId: 'heic-msg',
            },
            {
                id: 'u5', fileName: 'notes.pdf', state: 'ready', fileMessageId: 'pdf-msg',
            },
        ],
        contextItems: [
            {
                key: 'document:doc-context', kind: 'document', id: 'doc-context', label: 'Map',
                token: '#[Map]', attachment: 'selection',
                scope: { kind: 'public', id: 'public-1', name: 'Public' },
                origin: 'user', meta: { fileName: 'map.bmp' },
            },
            {
                key: 'document:doc-non-image', kind: 'document', id: 'doc-non-image', label: 'Report',
                token: '#[Report]', attachment: 'selection',
                scope: { kind: 'personal', id: null, name: 'My workspace' },
                origin: 'user', meta: { fileName: 'report.pdf' },
            },
        ],
        imageReferences: [
            { type: 'message', message_id: 'file-msg-1' },
            { type: 'message', message_id: 'explicit-msg' },
        ],
    };
    assert.deepEqual(composerDraftImageReferences(draft, 4), [
        { type: 'message', message_id: 'file-msg-1' },
        { type: 'message', message_id: 'legacy-msg' },
        { type: 'document', document_id: 'doc-fallback', scope: 'group', scope_id: 'group-1' },
        { type: 'document', document_id: 'doc-context', scope: 'public', scope_id: 'public-1' },
    ]);
    assert.deepEqual(composerDraftImageReferences(draft, 10).at(-1), { type: 'message', message_id: 'explicit-msg' });
});

check('image-mode gating keeps upload and documents live only when references are supported', () => {
    const base = {
        prompt: 'make this a cartoon',
        features: {
            enable_web_search: true,
            enable_image_generation: true,
            enable_url_access: true,
            enable_source_review: true,
            enable_chat_file_uploads: true,
        },
        webSearchActive: false,
        urlAccessActive: false,
        imageGenerationActive: true,
        agentActive: false,
        orchestrating: false,
    };
    const allowed = resolveGating({ ...base, imageReferencesAvailable: true });
    assert.equal(allowed.disabledByImageGeneration, true);
    assert.equal(allowed.documentsDisabledByImageGeneration, false);
    assert.equal(allowed.uploadsDisabledByImageGeneration, false);
    const blocked = resolveGating({ ...base, imageReferencesAvailable: false });
    assert.equal(blocked.documentsDisabledByImageGeneration, true);
    assert.equal(blocked.uploadsDisabledByImageGeneration, true);
});

const isImageDocument = (document) => isReferenceImageFileName(String(document.file_name ?? ''));

function pagedWorkspace(documents, { reportsTotal = true } = {}) {
    const requests = [];
    const fetchPage = async (query) => {
        requests.push({ ...query });
        const start = (query.page - 1) * query.pageSize;
        return {
            documents: documents.slice(start, start + query.pageSize),
            ...(reportsTotal ? { total_count: documents.length } : {}),
        };
    };
    return { fetchPage, requests };
}

const namedDocuments = (count, name) =>
    Array.from({ length: count }, (_, index) => ({ id: `${name}-${index}`, file_name: `${name}-${index}` }));

check('unfiltered scope search keeps the single short page', async () => {
    const workspace = pagedWorkspace(namedDocuments(40, 'report.pdf'));
    const found = await collectScopeDocuments(workspace.fetchPage, 'q');
    assert.equal(found.length, 6);
    assert.deepEqual(workspace.requests, [{ search: 'q', page: 1, pageSize: 6 }]);
});

check('images-only scope search pages past recent non-images', async () => {
    const documents = [
        ...namedDocuments(120, 'notes').map((document) => ({ ...document, file_name: `${document.file_name}.pdf` })),
        { id: 'house', file_name: 'house.jpg' },
        { id: 'map', file_name: 'map.tiff' },
        { id: 'portrait', file_name: 'portrait.heic' },
    ];
    const workspace = pagedWorkspace(documents);
    const found = await collectScopeDocuments(workspace.fetchPage, '', isImageDocument);
    assert.deepEqual(found.map((document) => document.id), ['house', 'map']);
    assert.deepEqual(workspace.requests.map((request) => request.page), [1, 2, 3]);
    assert.ok(workspace.requests.every((request) => request.pageSize === 50));
});

check('images-only scope search stops once it has enough matches', async () => {
    const images = namedDocuments(80, 'photo').map((document) => ({ ...document, file_name: `${document.file_name}.png` }));
    const workspace = pagedWorkspace(images);
    const found = await collectScopeDocuments(workspace.fetchPage, '', isImageDocument);
    assert.equal(found.length, 12);
    assert.equal(workspace.requests.length, 1);
});

check('images-only scope search is capped and does not re-read unpaged routes', async () => {
    const pdfs = namedDocuments(1000, 'deck').map((document) => ({ ...document, file_name: `${document.file_name}.pdf` }));
    const capped = pagedWorkspace(pdfs);
    assert.deepEqual(await collectScopeDocuments(capped.fetchPage, '', isImageDocument), []);
    assert.equal(capped.requests.length, 4);

    const unpaged = pagedWorkspace(pdfs, { reportsTotal: false });
    assert.deepEqual(await collectScopeDocuments(unpaged.fetchPage, '', isImageDocument), []);
    assert.equal(unpaged.requests.length, 1);
});

check('images-only scope search keeps earlier matches when a later page fails', async () => {
    const requests = [];
    const fetchPage = async (query) => {
        requests.push(query.page);
        if (query.page === 2) {
            throw new Error('Search index unavailable.');
        }
        return {
            documents: [
                { id: 'first', file_name: 'first.png' },
                ...namedDocuments(49, 'sheet').map((document) => ({ ...document, file_name: `${document.file_name}.xlsx` })),
            ],
            total_count: 500,
        };
    };
    const found = await collectScopeDocuments(fetchPage, '', isImageDocument);
    assert.deepEqual(found.map((document) => document.id), ['first']);
    assert.deepEqual(requests, [1, 2]);
});

check('images-only scope search stops paging once the search is cancelled', async () => {
    const controller = new AbortController();
    const requests = [];
    const fetchPage = async (query) => {
        requests.push(query.page);
        controller.abort();
        return { documents: namedDocuments(50, 'memo.docx'), total_count: 500 };
    };
    assert.deepEqual(await collectScopeDocuments(fetchPage, '', isImageDocument, controller.signal), []);
    assert.deepEqual(requests, [1]);
});

let failures = 0;
for (const [name, run] of checks) {
    try {
        await run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`  FAIL  ${name}`, error);
    }
}
console.log(`${checks.length - failures}/${checks.length} image reference checks passed.`);
process.exitCode = failures ? 1 : 0;
