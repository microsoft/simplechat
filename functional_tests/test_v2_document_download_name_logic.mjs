// test_v2_document_download_name_logic.mjs
// Version: 0.261.163
// Implemented in: 0.261.163
// Executes the real V2 document download path (lib/documentOperations.ts) against controlled HTTP.
// A single document is saved under its own file name, whatever the server's lossy single-file name.
// Several are saved under the archive name the server gives, read from Content-Disposition
// (`filename*` first, then `filename`) and reduced to a bare file name, or documents.zip without
// one. A personal download never reads the personal routes' names, so it is saved exactly as it
// always was.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    DOCUMENT_OPERATIONS, PERSONAL_DOCUMENT_OPERATIONS, attachmentFileName, createGroupDocumentOperations,
    createPublicDocumentOperations, documentDownloadName,
} = await import('../application/v2_ui/src/lib/documentOperations.ts');

const support = { schema_version: 1, operations: [...DOCUMENT_OPERATIONS] };
const group = createGroupDocumentOperations({ kind: 'group', id: 'group-a', name: 'Research group' }, support);
const publicWorkspace = createPublicDocumentOperations({ kind: 'public', id: 'pub-a', name: 'Public research' }, support);
const originalFetch = globalThis.fetch;
let calls = [];
let respond = () => assert.fail('No response was scripted.');
let checks = 0;

globalThis.fetch = async (path, options = {}) => {
    const url = new URL(String(path), 'http://fixture.test');
    calls.push({ path: url.pathname, method: options.method ?? 'GET' });
    return respond(url.pathname);
};

function attachment(disposition, body = 'file bytes') {
    return new Response(body, { headers: { 'Content-Type': 'application/octet-stream', 'Content-Disposition': disposition } });
}

function groupDocument(id, fileName) {
    return {
        id, group_id: 'group-a', shared_approval_status: 'owner', file_name: fileName,
        is_current_version: true, document_actions: ['download'],
    };
}

function publicDocument(id, fileName) {
    return { id, public_workspace_id: 'pub-a', file_name: fileName, is_current_version: true, document_actions: ['download'] };
}

async function check(name, run) {
    calls = [];
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

async function saved(adapter, documents, disposition) {
    respond = () => attachment(disposition);
    const download = await adapter.download(documents);
    return { download, name: documentDownloadName(download, documents) };
}

try {
    await check('the attachment name is read from filename* first, then filename', async () => {
        assert.equal(attachmentFileName('attachment; filename="group-documents.zip"'), 'group-documents.zip');
        assert.equal(attachmentFileName('attachment; filename=plain.zip'), 'plain.zip');
        assert.equal(attachmentFileName(`attachment; filename*=UTF-8''r%C3%A9sum%C3%A9%20set.zip; filename="resume_set.zip"`), 'résumé set.zip');
        assert.equal(attachmentFileName(`attachment; filename="resume_set.zip"; filename*=UTF-8''r%C3%A9sum%C3%A9%20set.zip`), 'résumé set.zip');
        assert.equal(attachmentFileName(`attachment; filename*=utf-8''%E6%8A%A5%E5%91%8A.pdf`), '报告.pdf');
    });

    await check('any path and control character is dropped from the name', async () => {
        assert.equal(attachmentFileName('attachment; filename="../../reports/evil.zip"'), 'evil.zip');
        assert.equal(attachmentFileName('attachment; filename="C:\\Users\\me\\evil.zip"'), 'evil.zip');
        assert.equal(attachmentFileName(`attachment; filename*=UTF-8''..%2F..%2Fevil.zip`), 'evil.zip');
        assert.equal(attachmentFileName('attachment; filename="safe\u0007name.zip"'), 'safename.zip');
    });

    await check('an empty, blank, dots-only or trailing-slash name is no name', async () => {
        for (const header of [
            null, '', 'attachment', 'attachment; filename=""', 'attachment; filename="   "',
            'attachment; filename=".."', 'attachment; filename="."', 'attachment; filename="reports/"',
        ]) {
            assert.equal(attachmentFileName(header), null, JSON.stringify(header));
        }
    });

    await check('a single download keeps its own name, whatever lossy name the server gives it', async () => {
        const report = groupDocument('report', 'Published report (final).pdf');
        const lossy = await saved(group, [report], 'attachment; filename="Published_report_final.pdf"');
        assert.deepEqual([lossy.download.fileName, lossy.name], ['Published_report_final.pdf', 'Published report (final).pdf']);
        assert.equal(calls.at(-1).path, '/api/groups/group-a/documents/report/download');
        const cjk = await saved(group, [groupDocument('cjk', '报告.pdf')], 'attachment; filename="pdf"');
        assert.equal(cjk.name, '报告.pdf');
        const bare = await saved(group, [report], 'attachment');
        assert.deepEqual([bare.download.fileName, bare.name], [null, 'Published report (final).pdf']);
    });

    await check('a group archive is saved under the name the server gives it, or documents.zip', async () => {
        const report = groupDocument('report', 'Published report.txt');
        const notes = groupDocument('notes', 'Field notes.pdf');
        const named = await saved(group, [report, notes], 'attachment; filename="group-documents.zip"');
        assert.deepEqual([named.download.fileName, named.name], ['group-documents.zip', 'group-documents.zip']);
        assert.deepEqual(calls.at(-1), { path: '/api/groups/group-a/documents/download', method: 'POST' });
        assert.equal((await saved(group, [report, notes], 'attachment; filename="../../reports/evil.zip"')).name, 'evil.zip');
        for (const header of ['attachment', 'attachment; filename=""', 'attachment; filename="reports/"', 'attachment; filename=".."']) {
            assert.equal((await saved(group, [report, notes], header)).name, 'documents.zip', header);
        }
    });

    await check('a public download is saved under the public archive name the server gives it', async () => {
        const brief = publicDocument('brief', 'brief.txt');
        const notes = publicDocument('notes', 'notes.pdf');
        const batch = await saved(publicWorkspace, [brief, notes], 'attachment; filename="public-documents.zip"');
        assert.deepEqual([batch.download.fileName, batch.name], ['public-documents.zip', 'public-documents.zip']);
        assert.deepEqual(calls.at(-1), { path: '/api/public-workspaces/pub-a/documents/download', method: 'POST' });
    });

    await check('a personal download keeps its name whatever the personal route sends', async () => {
        const alpha = { id: 'personal-alpha', file_name: 'Alpha notes.txt' };
        const beta = { id: 'personal-beta', file_name: 'personal-beta.txt' };
        // What the personal routes send: the secure_filename of the name, and personal_documents.zip.
        const single = await saved(PERSONAL_DOCUMENT_OPERATIONS, [alpha], 'attachment; filename="Alpha_notes.txt"');
        assert.deepEqual([single.download.fileName, single.name], [null, 'Alpha notes.txt']);
        assert.equal(calls.at(-1).path, '/api/documents/personal-alpha/download');
        const batch = await saved(PERSONAL_DOCUMENT_OPERATIONS, [alpha, beta], 'attachment; filename="personal_documents.zip"');
        assert.deepEqual([batch.download.fileName, batch.name], [null, 'documents.zip']);
        assert.deepEqual(calls.at(-1), { path: '/api/documents/download', method: 'POST' });
    });

    console.log(`${checks} document download name checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
