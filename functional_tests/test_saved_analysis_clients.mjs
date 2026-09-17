// test_saved_analysis_clients.mjs
/**
 * Saved Analyze client contract regressions.
 * Version: 0.261.109
 * Implemented in: 0.261.109
 *
 * Executes the shipped classic helper and bundled V2 helper. Browser rendering,
 * real reader authorization, streaming and composer interactions are covered in
 * ui_tests/test_chat_saved_analysis.py.
 *
 * Run: node functional_tests/test_saved_analysis_clients.mjs
 */

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { build } = await import(pathToFileURL(resolve(root, 'application', 'v2_ui', 'node_modules', 'esbuild', 'lib', 'main.js')));
const compiled = await build({
    entryPoints: [resolve(root, 'application', 'v2_ui', 'src', 'lib', 'savedAnalysis.ts')],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
    define: { 'import.meta.env': '{}' },
    logLevel: 'silent',
});
const loadSource = source => import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const react = await loadSource(compiled.outputFiles[0].text);
const classic = await loadSource(await readFile(
    resolve(root, 'application', 'single_app', 'static', 'js', 'chat', 'chat-analysis-results.js'), 'utf8',
));

globalThis.window = { currentConversationId: 'conversation-1', dispatchEvent() {} };
globalThis.document = { getElementById: () => null, querySelector: () => null };
globalThis.CustomEvent ??= class CustomEvent { constructor(type) { this.type = type; } };

const descriptor = {
    version: 'analyze-final-v1', conversation_id: 'conversation-1', message_id: 'assistant-1',
    result_sha256: 'a'.repeat(64), record_count: 60, source_count: 4, validation_status: 'partial',
    binding: { private: 'backend-only' },
};
const context = {
    conversation_id: descriptor.conversation_id,
    message_id: descriptor.message_id,
    result_sha256: descriptor.result_sha256,
};
const message = { id: 'assistant-1', conversation_id: 'conversation-1', role: 'assistant', content: 'Readable answer', metadata: { saved_analysis: descriptor } };
const sourceRequest = {
    conversation_id: 'conversation-1', message: 'Explain this', model_id: 'chosen-model',
    agent_info: { id: 'chosen-agent' }, hybrid_search: true, image_generation: true,
    web_search_enabled: true, url_access_enabled: true, source_review_enabled: true,
    deep_research_enabled: true, selected_document_ids: ['source-1'], tags: ['source-tag'],
    document_action: { type: 'analyze' }, analyze: { enabled: true },
    conversation_task_document_ids: ['uploaded-source'], active_group_ids: ['source-group'],
    orchestration: { required_capabilities: ['document_search'] },
};

for (const client of [react, classic]) {
    assert.equal(client.readSavedAnalysis(message.metadata).record_count, 60);
    assert.equal(client.readSavedAnalysis({ saved_analysis: { ...descriptor, available: false } }).available, false);
    assert.equal(client.readSavedAnalysis({ saved_analysis: { ...descriptor, result_sha256: 'not-a-digest' } }), null);
    assert.equal(client.readSavedAnalysis({ saved_analysis: { ...descriptor, record_count: -1 } }), null);
    assert.equal(client.readSavedAnalysis(message.metadata).binding, undefined);
}

assert.equal(classic.selectSavedAnalysis(descriptor), true);
for (const request of [
    react.applySavedAnalysisContext(sourceRequest, context),
    classic.applySavedAnalysisContext(sourceRequest),
]) {
    assert.deepEqual(request.analysis_result_context, context);
    assert.equal(request.model_id, 'chosen-model');
    assert.deepEqual(request.agent_info, { id: 'chosen-agent' });
    for (const key of ['hybrid_search', 'web_search_enabled', 'url_access_enabled', 'source_review_enabled', 'deep_research_enabled', 'image_generation']) {
        assert.equal(request[key], false, key);
    }
    for (const key of ['selected_document_ids', 'conversation_task_document_ids', 'tags', 'active_group_ids', 'active_public_workspace_ids']) {
        assert.deepEqual(request[key], [], key);
    }
    assert.equal(request.document_action, undefined);
    assert.equal(request.analyze, undefined);
    assert.equal(request.orchestration, undefined);
}
assert.equal(sourceRequest.hybrid_search, true, 'Request normalization must not mutate the original selection.');
assert.equal(react.applySavedAnalysisContext({ ...sourceRequest, conversation_id: 'other' }, context).analysis_result_context, undefined);

const revision = classic.getAnalysisContextRevision();
classic.clearSavedAnalysisContext();
assert.equal(classic.offerSavedAnalysis(message, revision), false, 'A late completion must not override a new source action.');
classic.hydrateSavedAnalysisContext([message], 'conversation-1', classic.getAnalysisContextRevision());
assert.equal(classic.getSavedAnalysisContext(), null, 'Reload must preserve explicit context removal.');
window.currentConversationId = 'other';
assert.equal(classic.getSavedAnalysisContext(), null);
assert.equal(classic.selectSavedAnalysis(descriptor), false);
window.currentConversationId = 'conversation-1';
classic.syncSavedAnalysisConversation();
classic.hydrateSavedAnalysisContext([message], 'conversation-1', classic.getAnalysisContextRevision());
assert.deepEqual(classic.getSavedAnalysisContext(), context);
classic.hydrateSavedAnalysisContext([{ ...message, metadata: { ...message.metadata, masked: true } }],
    'conversation-1', classic.getAnalysisContextRevision());
assert.equal(classic.getSavedAnalysisContext(), null);

assert.equal(react.latestSavedAnalysis([message]).message_id, 'assistant-1');
assert.equal(react.latestSavedAnalysis([message, { ...message, role: 'user', metadata: {}, content: 'New source pass' }]), null);
assert.equal(react.latestSavedAnalysis([{ ...message, metadata: { ...message.metadata, masked: true } }]), null);
assert.equal(react.latestSavedAnalysis([{ ...message, metadata: { saved_analysis: { ...descriptor, available: false } } }]), null);
const records = Array.from({ length: 25 }, (_, index) => ({
    record_id: `record-${index + 25}`, document_id: `source-${index % 4}`,
    source: { file_name: '<img src=x onerror=bad()>.txt' },
    values: { finding: `Complete finding ${index + 25}` }, evidence_refs: [`evidence-${index + 25}`],
}));
const page = {
    records, offset: 25, next_offset: 50, total_records: 60, source_count: 4,
    result_sha256: descriptor.result_sha256, validation: { status: 'partial' },
};
assert.equal(react.validateAnalysisPage(page, descriptor, 25).records.at(-1).record_id, 'record-49');
for (const invalid of [
    { ...page, records: [] },
    { ...page, offset: 0 },
    { ...page, next_offset: null },
    { ...page, result_sha256: 'b'.repeat(64) },
    { ...page, records: [...records, records[0]] },
    { ...page, records: [{ record_id: 'clipped' }] },
]) {
    assert.throws(() => react.validateAnalysisPage(invalid, descriptor, 25), error => error.status === 409);
}
assert.match(react.analysisValidationNotice('pending'), /Validation pending/);
assert.match(react.analysisValidationNotice('partial'), /subset/);
assert.match(react.analysisValidationNotice('invalid'), /Validation failed/);
assert.match(react.analysisValidationNotice('not_validated'), /Not validated/);
assert.deepEqual(react.analysisNotices(['A public limitation', { message: 'Unresolved issue' }, { diagnostics: 'INTERNAL' }]),
    ['A public limitation', 'Unresolved issue']);

console.log('Saved Analyze client contracts passed for classic and V2.');
