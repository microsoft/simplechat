// test_workflow_settings_client.js
/*
Functional tests for the V2 workflow editor's settings rules and save error handling.
Version: 0.261.207
Implemented in: 0.261.149

Executes the production TypeScript in lib/workflowEditor.ts and lib/workflowSettings.ts. Only HTTP
transport is replaced. It checks what the parity test against the real server cannot reach: how
the editor words a deleted workflow's 409, reads error codes, parses the group and personal source
lists and their File Sync flag, keeps revisions out of every create, and uses the group source list
to apply the group File Sync gate and the deleted-source check. Since 0.261.207 personal workflows
author File Sync too, so their creates send the edited `file_sync`, and a personal list marks only
its own missing personal sources. test_group_workflow_file_sync_client_parity.py pins the rules
themselves against the real save functions.
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
const home = { scope_type: 'personal', scope_id: 'owner-1', source_id: 'notes-share' };
const listedHome = { ...home, name: 'Notes share', source_type: 'smb', enabled: true, label: 'Notes share (Personal)' };
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
        return respond();
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
    // A group list offers only that group's sources.
    respond = () => Response.json({ sources: [listedHome], file_sync_enabled: true });
    await assert.rejects(editor.fetchWorkflowFileSyncSources(group), /The File Sync source list returned an invalid response\./);
});

test('the personal source list spans scopes and is requested without a group', async () => {
    const otherGroup = { ...listedFinance, scope_id: 'group-beta', label: 'Finance share (Group)' };
    const handbook = {
        scope_type: 'public', scope_id: 'handbook', source_id: 'handbook-share', name: 'Handbook',
        source_type: 'sharepoint', enabled: false, label: 'Handbook (Public)',
    };
    respond = () => Response.json({ sources: [listedHome, otherGroup, handbook, listedHome], file_sync_enabled: false });
    const listing = await editor.fetchWorkflowFileSyncSources(personal);
    assert.deepEqual(listing, { fileSyncEnabled: false, sources: [listedHome, otherGroup, handbook] });
    assert.equal(requests[0].url.pathname, '/api/user/workflows/file-sync-sources');
    assert.equal(requests[0].url.search, '');

    for (const entry of [
        { ...listedHome, scope_type: 'team' },
        { ...listedHome, scope_id: '' },
        { ...listedHome, source_id: '  ' },
        { ...listedHome, enabled: 'yes' },
    ]) {
        respond = () => Response.json({ sources: [entry], file_sync_enabled: true });
        await assert.rejects(editor.fetchWorkflowFileSyncSources(personal), /The File Sync source list returned an invalid response\./);
    }
    respond = () => Response.json({ sources: [listedHome] });
    await assert.rejects(editor.fetchWorkflowFileSyncSources(personal), /The File Sync source list returned an invalid response\./);
});

test('a personal save sends the File Sync it authored, and only the source identities', () => {
    const draft = editor.newWorkflowDefinition(personal);
    draft.name = 'Review new files';
    draft.tasks[0].instructions = 'Summarize the changed files.';
    draft.trigger_type = 'file_sync';
    draft.schedule = { unit: 'hours', value: 1 };
    draft.file_sync = editor.workflowMonitorFileSyncConfig({ sources: [{ ...listedHome }, { ...listedFinance }] });
    const payload = editor.workflowForSave(draft, null, personal);
    assert.deepEqual(payload.file_sync, {
        enabled: true, wait_mode: 'complete', continue_mode: 'changed', use_changed_documents: true,
        sources: [home, finance],
    });
    assert.equal(Object.hasOwn(payload, 'group_id'), false);
    assert.deepEqual(editor.workflowSettingsDraftErrors(draft, options(personal), null, null), []);

    // An untouched stored value is sent back as loaded, and File Sync is no longer listed as preserved.
    const stored = editor.normalizeWorkflowDefinition({
        ...payload, id: 'wf-1', definition_revision: 'a'.repeat(64),
        file_sync: { source_id: 'legacy-source', delete_policy: 'preserve' },
    }, personal);
    const edited = { ...structuredClone(stored), description: 'Edited in V2.' };
    assert.deepEqual(editor.workflowForSave(edited, stored, personal).file_sync, { source_id: 'legacy-source', delete_policy: 'preserve' });
    assert.equal(editor.preservedWorkflowFieldLabels(stored).includes('file sync settings'), false);
});

test('a personal list marks only its own missing personal sources as gone', () => {
    const goneHome = { ...home, source_id: 'gone-share' };
    const unlistedGroup = { ...finance, scope_id: 'group-beta' };
    const draft = editor.newWorkflowDefinition(personal);
    draft.trigger_type = 'file_sync';
    draft.file_sync = editor.workflowMonitorFileSyncConfig({ sources: [home, goneHome, unlistedGroup] });
    const listed = [listedHome];
    assert.deepEqual(editor.workflowUnavailableFileSyncSources(draft, listed, ['personal']), [goneHome]);
    // Without the filter every unlisted source counts, which is the group rule.
    assert.deepEqual(editor.workflowUnavailableFileSyncSources(draft, listed), [goneHome, unlistedGroup]);
    // Nothing is checked while File Sync is off for the draft.
    const manual = { ...draft, trigger_type: 'manual', file_sync: { ...draft.file_sync, enabled: false } };
    assert.deepEqual(editor.workflowUnavailableFileSyncSources(manual, listed, ['personal']), []);
});

test('both scopes refuse more than ten sources instead of letting the server drop them', () => {
    const eleven = Array.from({ length: 11 }, (_, index) => ({ ...home, source_id: `share-${index}` }));
    const draft = editor.newWorkflowDefinition(personal);
    draft.name = 'Many sources';
    draft.tasks[0].instructions = 'Check the files.';
    draft.file_sync = { enabled: true, wait_mode: 'complete', continue_mode: 'always', use_changed_documents: true, sources: eleven };
    assert.deepEqual(editor.workflowSettingsDraftErrors(draft, options(personal), null, null), ['Choose at most 10 File Sync sources.']);
    const groupDraft = draftWithFileSync(eleven.map((source) => ({ ...finance, source_id: source.source_id })));
    assert.ok(editor.workflowSettingsDraftErrors(groupDraft, options(group), null, null).includes('Choose at most 10 File Sync sources.'));
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
