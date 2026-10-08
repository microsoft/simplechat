// test_v2_drawer_generated_files_logic.mjs
// Version: 0.261.302
// Implemented in: 0.261.302
// Executes the real V2 helpers behind the Generated section of the conversation drawer: every
// file a reply produced is listed for any conversation, not only shared ones. That covers each
// format an orchestration plan can render, the screenshot case of a finished CSV, legacy
// tabular, Analyze and background exports, and approval-withheld files. Each file carries its
// status, and the live run state takes precedence. The section hides what the thread hides,
// lists each file once in conversation order, gates the agent-document request and re-reads it
// whenever the replies the thread shows change, lists only agent documents whose reply is shown,
// and counts the header badge without double counting.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const hadWindow = 'window' in globalThis;
const previousWindow = globalThis.window;
const originalFetch = globalThis.fetch;
globalThis.window = { location: { href: 'https://chat.example.gov/v2/chat' } };
globalThis.fetch = () => {
    throw new Error('The generated-files helpers must not make network requests.');
};

try {
    const {
        collectConversationGeneratedFiles,
        countConversationDocuments,
        generatedDocumentsThreadKey,
        generatedFileDetails,
        mayHaveGeneratedDocuments,
        mergeGeneratedEntries,
        messageGeneratedFiles,
        visibleGeneratedDocuments,
    } = await import('../application/v2_ui/src/lib/conversationGeneratedFiles.ts');
    const { artifactDownloadPath, normalizeGeneratedArtifact } = await import(
        '../application/v2_ui/src/lib/generatedArtifacts.ts'
    );

    const CONVERSATION = 'conv-1';

    function reply(id, metadata = {}, extra = {}) {
        return { id, conversation_id: CONVERSATION, role: 'assistant', content: 'Done.', metadata, ...extra };
    }

    function output(id, format, state, extra = {}) {
        return {
            output_id: id, step_id: `step-${id}`, file_name: `${id}.${format}`, output_format: format,
            profile: 'prepared_text_v1', state, attempt_count: 1, automatic_attempts: 1, max_automatic_attempts: 3,
            next_retry_at: null, can_retry: false, available: true, error_code: null, message: '',
            artifact_message_id: state === 'completed' ? `art-${id}` : null,
            row_count: null, character_count: null, size_bytes: null, ...extra,
        };
    }

    function receipt(out, extra = {}) {
        return {
            capability: 'render_file', source_kind: 'orchestration_retained_output', output_id: out.output_id,
            artifact_message_id: out.artifact_message_id, conversation_id: CONVERSATION, storage_scope: 'chat',
            file_name: out.file_name, output_format: out.output_format, profile: out.profile, ...extra,
        };
    }

    function planReply(id, runId, outputs, receipts = outputs.filter((o) => o.state === 'completed').map((o) => receipt(o))) {
        return reply(id, { orchestration: { run_id: runId, outputs } }, { generated_artifacts: receipts });
    }

    // The screenshot: a plan wrote a CSV, its card says Completed, and the drawer listed nothing.
    const csv = output('us_states_and_capitals', 'csv', 'completed', {
        file_name: 'us_states_and_capitals.csv', profile: 'tabular_records_v1', row_count: 50, size_bytes: 1006,
    });
    const [screenshot] = messageGeneratedFiles(planReply('a-csv', 'run-csv', [csv]));
    assert.equal(screenshot.fileName, 'us_states_and_capitals.csv');
    assert.equal(screenshot.status, 'ready');
    assert.equal(screenshot.typeLabel, 'CSV file');
    assert.equal(generatedFileDetails(screenshot), 'CSV file · 50 rows · 1006 B');
    assert.equal(screenshot.messageId, 'a-csv', 'Show in conversation goes to the reply that made it');
    assert.equal(
        artifactDownloadPath(screenshot.artifact, CONVERSATION),
        '/api/chat_artifacts/download?conversation_id=conv-1&message_id=art-us_states_and_capitals',
        'downloads go through the authorized chat artifact route',
    );

    // Every format a plan can render is listed, with the label a person uses for it.
    const labels = {
        csv: 'CSV file', json: 'JSON file', xml: 'XML file', yaml: 'YAML file', md: 'Markdown file',
        txt: 'Text file', xlsx: 'Excel workbook', docx: 'Word document', pdf: 'PDF document', pptx: 'PowerPoint deck',
    };
    const everyFormat = Object.keys(labels).map((format) => output(`file-${format}`, format, 'completed'));
    const rendered = messageGeneratedFiles(planReply('a-formats', 'run-formats', everyFormat));
    assert.deepEqual(rendered.map((file) => [file.format, file.typeLabel, file.status]),
        Object.entries(labels).map(([format, label]) => [format, label, 'ready']));
    assert.ok(rendered.every((file) => file.artifact), 'every ready file can be downloaded');

    // Files that are not ready are listed with their status and nothing to download.
    const states = messageGeneratedFiles(planReply('a-states', 'run-states', [
        output('waiting', 'pdf', 'waiting'),
        output('rendering', 'docx', 'rendering'),
        output('retrying', 'pptx', 'retry_scheduled'),
        output('failed', 'xlsx', 'failed'),
        output('stopped', 'md', 'cancelled'),
        output('no-receipt', 'csv', 'completed'),
        output('revoked', 'csv', 'completed', { available: false }),
        output('unknown', 'txt', 'mystery'),
    ], []));
    assert.deepEqual(states.map((file) => [file.fileName, file.status, file.statusLabel]), [
        ['waiting.pdf', 'pending', 'Waiting'],
        ['rendering.docx', 'pending', 'Rendering'],
        ['retrying.pptx', 'pending', 'Automatic retry scheduled'],
        ['failed.xlsx', 'failed', 'Failed'],
        ['stopped.md', 'cancelled', 'Cancelled'],
        ['no-receipt.csv', 'unavailable', 'Download details unavailable'],
        ['revoked.csv', 'unavailable', 'Unavailable'],
        ['unknown.txt', 'unavailable', 'Status unavailable'],
    ]);
    assert.ok(states.every((file) => file.artifact === null), 'only a ready file offers a download');

    // The live run state the file cards poll takes precedence over the snapshot saved on the reply.
    const pending = output('report', 'pdf', 'rendering');
    const finished = output('report', 'pdf', 'completed', { size_bytes: 2048 });
    const liveReply = planReply('a-live', 'run-live', [pending], []);
    assert.equal(messageGeneratedFiles(liveReply)[0].status, 'pending');
    const live = messageGeneratedFiles(liveReply, {
        runs: { 'run-live': { outputs: [finished], generated_artifacts: [normalizeGeneratedArtifact(receipt(finished))] } },
    });
    assert.deepEqual([live[0].status, generatedFileDetails(live[0])], ['ready', 'PDF document · 2 KB']);
    const denied = messageGeneratedFiles(liveReply, { runs: { 'run-live': { outputs: [finished], outputAccessDenied: true } } });
    assert.deepEqual([denied[0].status, denied[0].artifact], ['unavailable', null], 'withheld when access cannot be confirmed');

    // Exports and analysis files written by ordinary replies are listed too.
    const exports = messageGeneratedFiles(reply('a-exports', {
        generated_tabular_outputs: [{
            capability: 'tabular', artifact_message_id: 'tab-1', conversation_id: CONVERSATION,
            file_name: 'orders.csv', output_format: 'csv', row_count: 1200,
        }],
        generated_analysis_artifacts: [{
            capability: 'analyze', artifact_message_id: 'an-1', conversation_id: CONVERSATION,
            file_name: 'summary.md', output_format: 'markdown', preview_text: '# Summary',
        }],
    }));
    assert.deepEqual(exports.map((file) => [file.fileName, file.typeLabel, file.status]), [
        ['summary.md', 'Markdown file', 'ready'],
        ['orders.csv', 'CSV file', 'ready'],
    ]);
    assert.equal(generatedFileDetails(exports[1]), `CSV file · ${(1200).toLocaleString()} rows`);

    // A workspace copy keeps its document id, so the badge does not count it twice.
    const [workspaceCopy] = messageGeneratedFiles(reply('a-ws', {
        generated_tabular_outputs: [{ capability: 'tabular', document_id: 'doc-9', file_name: 'saved.xlsx', output_format: 'xlsx' }],
    }));
    assert.deepEqual([workspaceCopy.documentId, workspaceCopy.status, workspaceCopy.key], ['doc-9', 'ready', 'document:doc-9']);

    // A background export is generating until its card reports the files it produced.
    const background = reply('a-bg', {
        generated_tabular_outputs: [{
            capability: 'tabular', export_run_id: 'exp-1', background_export: true, output_format: 'xlsx', status: 'running',
        }],
    });
    const [generating] = messageGeneratedFiles(background);
    assert.deepEqual([generating.fileName, generating.status, generating.statusLabel], ['Generated XLSX export', 'pending', 'Generating']);
    const member = normalizeGeneratedArtifact({
        capability: 'tabular', artifact_message_id: 'tab-done', conversation_id: CONVERSATION,
        file_name: 'large-export.xlsx', output_format: 'xlsx', row_count: 90000,
    });
    const done = messageGeneratedFiles(background, { exportRuns: { 'exp-1': { status: 'completed', members: [member] } } });
    assert.deepEqual(done.map((file) => [file.fileName, file.status]), [['large-export.xlsx', 'ready']]);
    assert.equal(messageGeneratedFiles(background, { exportRuns: { 'exp-1': { status: 'failed' } } })[0].status, 'failed');
    assert.equal(
        messageGeneratedFiles(background, { exportRuns: { 'exp-1': { status: 'failed', retryableFailure: true } } })[0].status,
        'pending', 'a failure the worker will retry is still in progress',
    );
    const [stopped] = messageGeneratedFiles(reply('a-stopped', {
        generated_tabular_outputs: [{
            capability: 'tabular', export_run_id: 'exp-2', status: 'canceled', suppress_assistant_table_export: true,
        }],
    }));
    assert.equal(stopped.status, 'cancelled');

    // A file staged for the conversation owner's approval is listed but not downloadable.
    const staged = (state) => messageGeneratedFiles(reply(`a-${state}`, {
        generated_tabular_outputs: [{
            capability: 'tabular', artifact_message_id: `staged-${state}`, conversation_id: CONVERSATION,
            file_name: 'shared.csv', output_format: 'csv', approval: { state },
        }],
    }))[0];
    assert.deepEqual(['pending_approval', 'denied', 'auto_denied', 'approved'].map((state) => [staged(state).status, staged(state).statusLabel]), [
        ['withheld', 'Awaiting approval'], ['withheld', 'Declined'], ['withheld', 'Expired'], ['ready', ''],
    ]);

    // What the thread hides stays hidden.
    const exportsMetadata = {
        generated_tabular_outputs: [{
            capability: 'tabular', artifact_message_id: 'tab-hidden', conversation_id: CONVERSATION,
            file_name: 'hidden.csv', output_format: 'csv',
        }],
    };
    assert.deepEqual(messageGeneratedFiles(reply('a-masked', { ...exportsMetadata, masked: true })), []);
    assert.deepEqual(messageGeneratedFiles(reply('a-superseded', { ...exportsMetadata, superseded_by_workflow_reply: true })), []);
    assert.deepEqual(messageGeneratedFiles({ ...reply('u-1', exportsMetadata), role: 'user' }), []);
    const partlyMasked = planReply('a-partial', 'run-partial', [csv]);
    partlyMasked.metadata = { ...partlyMasked.metadata, ...exportsMetadata, masked_ranges: [{ start: 0, end: 2 }] };
    assert.deepEqual(messageGeneratedFiles(partlyMasked).map((file) => file.fileName), ['hidden.csv'],
        'a partly masked reply hides its plan files, as the thread does, and keeps its other files');

    // Saved Analyze findings gate their downloads exactly as the thread gates them.
    const savedAnalysis = {
        version: 'analyze-final-v1', conversation_id: CONVERSATION, message_id: 'a-analysis',
        result_sha256: 'a'.repeat(64), record_count: 3, source_count: 1, validation_status: 'valid',
    };
    assert.equal(messageGeneratedFiles(reply('a-analysis', { ...exportsMetadata, saved_analysis: savedAnalysis })).length, 1);
    assert.equal(messageGeneratedFiles(reply('a-analysis', { ...exportsMetadata, saved_analysis: { ...savedAnalysis, available: false } })).length, 0);
    assert.equal(messageGeneratedFiles(reply('a-analysis', { ...exportsMetadata, saved_analysis: { broken: true } })).length, 0);

    // A plan's committed file is listed once, under its file card, not again as a loose receipt.
    assert.equal(messageGeneratedFiles(planReply('a-once', 'run-once', [csv])).length, 1);
    const receiptOnly = reply('a-receipt', { orchestration: { run_id: 'run-receipt' } }, { generated_artifacts: [receipt(csv)] });
    assert.deepEqual(messageGeneratedFiles(receiptOnly).map((file) => [file.fileName, file.status]),
        [['us_states_and_capitals.csv', 'ready']], 'without file cards the receipt itself is listed');

    // Each file once, oldest first, attributed to the first reply that showed it.
    const retry = planReply('a-retry', 'run-retry', [csv]);
    const conversation = [
        { id: 'u-0', conversation_id: CONVERSATION, role: 'user', content: 'Make a CSV' },
        planReply('a-csv', 'run-csv', [csv]),
        reply('a-exports', {
            generated_tabular_outputs: [{
                capability: 'tabular', artifact_message_id: 'tab-1', conversation_id: CONVERSATION,
                file_name: 'orders.csv', output_format: 'csv',
            }],
        }),
        retry,
    ];
    const all = collectConversationGeneratedFiles(conversation);
    assert.deepEqual(all.map((file) => [file.fileName, file.messageId]), [
        ['us_states_and_capitals.csv', 'a-csv'],
        ['orders.csv', 'a-exports'],
    ]);

    // The agent-document request is made only when the thread can hold such a document.
    const upload = { function_name: 'upload_word_document', function_result: '{}' };
    assert.equal(mayHaveGeneratedDocuments([reply('a-1', {}, { agent_citations: [upload] })]), true);
    assert.equal(mayHaveGeneratedDocuments([reply('a-1', {}, { agent_citations: [{ function_name: 'search_documents' }] })]), false);
    assert.equal(mayHaveGeneratedDocuments([reply('a-1', {}, { agent_display_name: 'Analyst' })]), true,
        "an agent's reply that finished in this tab has not had its tool calls read back yet");
    assert.equal(mayHaveGeneratedDocuments([reply('a-1', {}, { agent_display_name: 'Analyst', agent_citations: [] })]), false);
    assert.equal(mayHaveGeneratedDocuments([reply('a-1')]), false);
    assert.equal(mayHaveGeneratedDocuments([{ id: 'u-1', role: 'user', content: '', agent_citations: [upload] }]), false);

    // The agent-document list is read again whenever the replies the thread shows change, which a
    // reply count misses: showing another attempt of an answer, or masking a reply, keeps the count.
    const asked = { id: 'u-1', conversation_id: CONVERSATION, role: 'user', content: 'Write the brief' };
    const shown = [asked, reply('a-1'), reply('a-2')];
    const threadKey = generatedDocumentsThreadKey(shown);
    assert.notEqual(generatedDocumentsThreadKey([asked, reply('a-1'), reply('a-2b')]), threadKey, 'another attempt shown');
    assert.notEqual(generatedDocumentsThreadKey([asked, reply('a-1'), reply('a-2', { masked: true })]), threadKey,
        'a reply fully masked');
    assert.notEqual(generatedDocumentsThreadKey([...shown, reply('a-3')]), threadKey, 'a new reply');
    assert.notEqual(generatedDocumentsThreadKey([asked, reply('a-2')]), threadKey, 'a reply deleted');
    assert.equal(generatedDocumentsThreadKey([...shown, { ...asked, id: 'u-2' }]), threadKey,
        "a person's own message cannot hold an agent document, so it costs no request");
    assert.equal(generatedDocumentsThreadKey([asked, reply('a-1'), { ...reply('a-2'), content: 'Edited.' }]), threadKey);

    // Only documents whose reply the thread still shows are listed and counted.
    const agentDocument = (documentId, messageId) => ({
        document_id: documentId, file_name: `${documentId}.docx`, workspace_scope: 'personal', preview: null,
        message_id: messageId, created_at: '', can_download: true,
    });
    const listed = [
        agentDocument('doc-shown', 'a-1'),
        agentDocument('doc-other-attempt', 'a-2'),
        agentDocument('doc-masked', 'a-masked'),
        agentDocument('doc-replaced', 'a-replaced'),
        agentDocument('doc-unattributed', ''),
    ];
    assert.deepEqual(visibleGeneratedDocuments(listed, [
        asked,
        reply('a-1'),
        reply('a-masked', { masked: true }),
        reply('a-replaced', { superseded_by_workflow_reply: true }),
        reply('a-partly-masked', { masked_ranges: [{ start: 0, end: 2 }] }),
    ]).map((document) => document.document_id), ['doc-shown']);
    assert.deepEqual(
        visibleGeneratedDocuments([agentDocument('doc-partial', 'a-partly-masked')], [
            reply('a-partly-masked', { masked_ranges: [{ start: 0, end: 2 }] }),
        ]).map((document) => document.document_id),
        ['doc-partial'], 'masking part of a reply keeps its documents, as the server does',
    );

    // Files and agent documents share one list in conversation order; a shared document id is listed once.
    const brief = {
        document_id: 'doc-brief', file_name: 'Brief.docx', workspace_scope: 'personal', preview: null,
        message_id: 'a-csv', created_at: '', can_download: true,
    };
    const duplicate = { ...brief, document_id: 'doc-9', message_id: 'a-ws' };
    const entries = mergeGeneratedEntries(
        [...collectConversationGeneratedFiles([conversation[2], reply('a-ws', {
            generated_tabular_outputs: [{ capability: 'tabular', document_id: 'doc-9', file_name: 'saved.xlsx', output_format: 'xlsx' }],
        })])],
        [duplicate, brief],
        [conversation[1], conversation[2], reply('a-ws')],
    );
    assert.deepEqual(entries.map((entry) => [entry.kind, entry.messageId]), [
        ['document', 'a-csv'],
        ['file', 'a-exports'],
        ['file', 'a-ws'],
    ]);

    // The badge counts documents answers used and documents the conversation produced, each once.
    const badge = countConversationDocuments(
        {
            used_documents: [{ document_id: 'doc-9' }, { document_id: 'doc-used' }],
            linked_workspace_documents: [{ document_id: 'doc-used' }],
        },
        [screenshot, workspaceCopy],
        [brief, { ...brief, document_id: 'doc-used' }],
    );
    assert.equal(badge, 4, 'doc-9, doc-used, the CSV and the brief');
    assert.equal(countConversationDocuments(null, [], []), 0);

    console.log('Drawer generated-files checks passed');
} finally {
    globalThis.fetch = originalFetch;
    if (hadWindow) {
        globalThis.window = previousWindow;
    } else {
        delete globalThis.window;
    }
}
