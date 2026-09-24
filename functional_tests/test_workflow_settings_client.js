// test_workflow_settings_client.js
/*
Functional tests for the V2 workflow editor's settings rules and save error handling.
Version: 0.261.149
Implemented in: 0.261.149

Executes the production TypeScript in lib/workflowEditor.ts and lib/workflowSettings.ts. Only HTTP
transport is replaced. It checks what the parity test against the real server cannot reach: how
the editor words a deleted workflow's 409, reads error codes, parses the group source list and its
File Sync flag, keeps revisions out of every create, and uses the source list to apply the group
File Sync gate and the deleted-source check. test_group_workflow_file_sync_client_parity.py pins
the rules themselves against the real save functions.
*/

const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { afterEach, before, beforeEach, test } = require('node:test');

const root = path.resolve(__dirname, '..');
const nativeFetch = globalThis.fetch;
const personal = { type: 'personal' };
const group = { type: 'group', groupId: 'group-alpha' };
const finance = { scope_type: 'group', scope_id: 'group-alpha', source_id: 'finance-share' };
const listedFinance = { ...finance, name: 'Finance share', source_type: 'smb', enabled: true, label: 'Finance share (Group)' };
const sourceUnavailable = 'A selected File Sync source is no longer available. Remove it and save again.';
const groupFileSyncOff = 'Group File Sync must be enabled before a group workflow can use File Sync sources.';
const requests = [];
let editor;
let apiClient;
let respond;

before(async () => {
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const sourceUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
    editor = await import(sourceUrl('workflowEditor'));
    apiClient = await import(sourceUrl('apiClient'));
});

beforeEach(() => {
    requests.length = 0;
    respond = () => { throw new Error('Unexpected API request.'); };
    globalThis.fetch = async (url, init) => {
        const request = {
            url: new URL(url, 'https://simplechat.test'),
            ...init,
            body: init.body === undefined ? undefined : JSON.parse(init.body),
        };
        requests.push(request);
        return respond(request);
    };
});

afterEach(() => {
    globalThis.fetch = nativeFetch;
});

function options(scope) {
    return {
        definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
        agents: [], models: [], default_model: { label: 'Default model', valid: true },
        scope: scope.type === 'group' ? { type: 'group', id: scope.groupId } : { type: 'personal', id: 'owner-1' },
    };
}

function draftWithFileSync(sources = [finance]) {
    const draft = editor.newWorkflowDefinition(group);
    draft.name = 'Sync before run';
    draft.tasks[0].instructions = 'Summarize the changed files.';
    draft.file_sync = { enabled: true, wait_mode: 'complete', continue_mode: 'always', use_changed_documents: true, sources };
    return draft;
}

test('a deleted workflow keeps the draft and never advises a reload', () => {
    const cause = new apiClient.ApiError(editor.WORKFLOW_DELETED_MESSAGE, 409, {
        error: editor.WORKFLOW_DELETED_MESSAGE, code: 'workflow_deleted',
    });
    const message = editor.workflowErrorMessage(cause, 'fallback');
    assert.equal(message, 'This workflow was deleted after it was opened, so your changes were not saved. '
        + 'Your draft has been retained. Copy anything you need, then close this editor.');
    assert.doesNotMatch(message, /reload/i);
    const unworded = new apiClient.ApiError('', 409, { code: 'workflow_deleted' });
    assert.match(editor.workflowErrorMessage(unworded, 'fallback'), /^This workflow was deleted after it was opened/);
});

test('other conflicts and errors keep their existing messages', () => {
    const stale = new apiClient.ApiError('This workflow changed since it was opened. Reload it before saving.', 409, {
        code: 'workflow_definition_conflict',
    });
    assert.match(editor.workflowErrorMessage(stale, 'fallback'), /reload the saved workflow before retrying\.$/);
    const settings = new apiClient.ApiError(sourceUnavailable, 400, { error: sourceUnavailable, code: 'file_sync_source_unavailable' });
    assert.equal(editor.workflowErrorMessage(settings, 'fallback'), sourceUnavailable);
    assert.equal(editor.workflowErrorMessage('not an error', 'fallback'), 'fallback');
});

test('the error code comes only from a route payload', () => {
    assert.equal(editor.workflowErrorCode(new apiClient.ApiError('x', 400, { code: 'file_sync_source_unavailable' })),
        editor.WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_CODE);
    assert.equal(editor.workflowErrorCode(new apiClient.ApiError('x', 400, { code: 7 })), '');
    assert.equal(editor.workflowErrorCode(new apiClient.ApiError('x', 400, 'text body')), '');
    assert.equal(editor.workflowErrorCode(new Error('plain')), '');
});

test('the source list carries the File Sync gate and refuses a response without it', async () => {
    respond = () => Response.json({ sources: [listedFinance], file_sync_enabled: true });
    const listing = await editor.fetchWorkflowFileSyncSources(group);
    assert.deepEqual(listing, { fileSyncEnabled: true, sources: [listedFinance] });
    assert.equal(requests[0].url.pathname, '/api/group/workflows/file-sync-sources');
    assert.equal(requests[0].url.searchParams.get('group_id'), 'group-alpha');

    respond = () => Response.json({ sources: [], file_sync_enabled: false });
    assert.deepEqual(await editor.fetchWorkflowFileSyncSources(group), { fileSyncEnabled: false, sources: [] });

    respond = () => Response.json({ sources: [listedFinance] });
    await assert.rejects(editor.fetchWorkflowFileSyncSources(group), /The File Sync source list returned an invalid response\./);
    await assert.rejects(editor.fetchWorkflowFileSyncSources(personal), /listed only for group workflows/);
});

test('a create never sends a revision, even from a draft that carries one', async () => {
    for (const scope of [personal, group]) {
        const draft = { ...editor.newWorkflowDefinition(scope), definition_revision: 'f'.repeat(64) };
        draft.name = 'New workflow';
        draft.tasks[0].instructions = 'Do the work.';
        // In memory the key is present as undefined; JSON drops it, and the request body is what counts.
        assert.equal(editor.workflowForSave(draft, null, scope).definition_revision, undefined);
        respond = () => Response.json({ success: true, workflow: { ...draft, id: 'created' } }, { status: 201 });
        requests.length = 0;
        await editor.saveWorkflowDefinition(scope, draft, null);
        assert.equal(Object.hasOwn(requests[0].body, 'definition_revision'), false);
        assert.equal(Object.hasOwn(requests[0].body, 'id'), false);
    }
});

test('the group source list gates the File Sync check and the deleted-source check', () => {
    const draft = draftWithFileSync();
    const on = { fileSyncEnabled: true, sources: [listedFinance] };
    assert.deepEqual(editor.workflowSettingsDraftErrors(draft, options(group), null, on), []);
    // Unknown until the list loads: both checks are left to the server.
    assert.deepEqual(editor.workflowSettingsDraftErrors(draftWithFileSync([{ ...finance, source_id: 'gone' }]),
        options(group), null, null), []);
    assert.deepEqual(editor.workflowSettingsDraftErrors(draftWithFileSync([{ ...finance, source_id: 'gone' }]),
        options(group), null, on), [sourceUnavailable]);
    // A group with File Sync off lists nothing, which says nothing about the selected source.
    const off = { fileSyncEnabled: false, sources: [] };
    assert.deepEqual(editor.workflowSettingsDraftErrors(draft, options(group), null, off), [groupFileSyncOff]);
    const unused = { ...draft, file_sync: { ...draft.file_sync, enabled: false, sources: [] } };
    assert.deepEqual(editor.workflowSettingsDraftErrors(unused, options(group), null, off), []);
});

test('personal validation applies the personal rules and ignores any source list', () => {
    const draft = editor.newWorkflowDefinition(personal);
    draft.name = 'Personal schedule';
    draft.tasks[0].instructions = 'Check in.';
    draft.trigger_type = 'interval';
    draft.schedule = { unit: 'minutes', value: 90 };
    const errors = editor.workflowValidationErrors(draft, options(personal), null, { fileSyncEnabled: false, sources: [] });
    assert.ok(errors.includes('Schedule value for minutes must be between 1 and 59.'), errors);
    assert.ok(!errors.includes('Interval workflows need a positive schedule value.'), errors);
    draft.schedule = { unit: 'minutes', value: 59 };
    assert.deepEqual(editor.workflowSettingsDraftErrors(draft, options(personal), null, { fileSyncEnabled: false, sources: [] }), []);
});
