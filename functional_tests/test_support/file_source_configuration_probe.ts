// file_source_configuration_probe.ts
// Version: 0.261.310
// Implemented in: 0.261.310
// Executes the real personal transport and shared credential/field serializers.

import assert from 'node:assert/strict';
import {
    PERSONAL_FILE_SOURCE_WORKBENCH as adapter,
    FileSourceConflictError,
    FileSourceWriteConflictError,
    FileSourceBusyError,
    FileSourceDeleteIncompleteError,
    FileSourcePartialDeleteError,
} from '../../application/v2_ui/src/lib/fileSourceWorkbench';
import {
    buildFileSourceWrite,
    connectionDescriptor,
    draftFromSource,
    emptyFileSourceDraft,
    visibleSourceTypes,
} from '../../application/v2_ui/src/lib/fileSourceFields';
import type { FileSourceOptions, WorkspaceSyncSource } from '../../application/v2_ui/src/lib/types';

interface Call { method: string; path: string; body?: unknown; }
const calls: Call[] = [];
let payload: unknown;
let status = 200;
const options: FileSourceOptions = {
    source_types: ['smb', 'azure_files', 'azure_blob'].map((value) => ({ value, label: value, visible: true })),
    eligible_identity_ids: { smb: ['identity'], azure_files: [], azure_blob: [] },
    schedule: { min_interval_minutes: 5, max_interval_minutes: 10080 },
    limits: { max_sources: 25 },
    recursive_allowed: false,
    default_remote_delete_policy: 'hard_delete',
};
const source: WorkspaceSyncSource = {
    id: 'source-id', config_revision: 'revision-1', name: 'Reports', source_type: 'smb',
    credentials: { auth_type: 'username_password', username: 'svc', password_stored: true },
};

globalThis.fetch = async (input, init) => {
    calls.push({
        method: init?.method ?? 'GET', path: String(input),
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    return new Response(JSON.stringify(payload), {
        status, headers: { 'content-type': 'application/json' },
    });
};

function respond(value: unknown, responseStatus = 200): void {
    calls.length = 0;
    payload = value;
    status = responseStatus;
}

function last(method: string, path: string, body?: unknown): void {
    assert.deepEqual(calls, [{ method, path, body }]);
}

async function transport(): Promise<void> {
    const base = '/api/file-sync/personal/sources';
    const saved = `${base}/source-id`;
    const write = { name: 'Draft', source_type: 'smb', connection: { unc_path: '\\\\files\\reports' } };
    respond({ sources: [source] });
    const listed = await adapter.list();
    assert.deepEqual(listed, [source]);
    last('GET', base);
    respond({ source });
    await adapter.read(source);
    last('GET', saved);
    await adapter.create(write);
    assert.equal(calls.at(-1)?.method, 'POST');
    assert.deepEqual(calls.at(-1)?.body, write);
    respond({ source });
    await adapter.update(source, write);
    last('PATCH', saved, { ...write, expected_config_revision: 'revision-1' });
    respond(options);
    const loaded = await adapter.options();
    assert.deepEqual(loaded, options);
    last('GET', '/api/file-sync/personal/source-options');
    respond({ identities: [{ id: 'identity' }] });
    await adapter.identities();
    last('GET', '/api/workspace-identities/personal/identities');
    respond({ tags: [{ name: 'legal', count: 2 }, { name: 'finance', count: 4 }] });
    const tags = await adapter.tags();
    assert.deepEqual(tags, ['finance', 'legal']);
    last('GET', '/api/documents/tags');
    for (const target of [null, source]) {
        const root = target ? saved : base;
        respond({ connection: { success: true } });
        await adapter.testConnection(target, write);
        last('POST', `${root}/test-connection`, write);
        respond({ browse: { path: 'Reports', entries: [] } });
        await adapter.browse(target, write, 'Reports');
        last('POST', `${root}/browse`, { ...write, browse_path: 'Reports' });
    }
    respond({ item: { ignored: true } });
    await adapter.ignorePath(source.id, '\\\\files\\reports\\report.pdf', true);
    last('POST', `${saved}/ignore-path`, { remote_path: '\\\\files\\reports\\report.pdf', ignored: true });
    const result = { associated_files_requested: true, documents_deleted: 3, documents_failed: 0, documents_skipped: 1 };
    respond({ delete_result: result });
    const removed = await adapter.remove(source, true);
    assert.deepEqual(removed, result);
    last('DELETE', saved, { expected_config_revision: 'revision-1', delete_associated_files: true });

    for (const [code, errorType] of [
        ['config_conflict', FileSourceConflictError], ['write_conflict', FileSourceWriteConflictError],
    ] as const) {
        respond({ error: 'Refused', error_code: code }, 409);
        await assert.rejects(() => adapter.update(source, write), errorType);
    }
    for (const [errorPayload, errorType] of [
        [{ error_code: 'source_busy' }, FileSourceBusyError],
        [{ error_code: 'config_conflict' }, FileSourceConflictError],
        [{ error_code: 'delete_incomplete', delete_result: result }, FileSourceDeleteIncompleteError],
        [{ partial: true, delete_result: result }, FileSourcePartialDeleteError],
    ] as const) {
        respond({ error: 'Refused', ...errorPayload }, 409);
        await assert.rejects(() => adapter.remove(source, true), errorType);
    }
    respond({});
    await assert.rejects(() => adapter.read(source), /malformed/);
    await assert.rejects(() => adapter.list(), /malformed/);
    await assert.rejects(() => adapter.options(), /malformed/);
    await assert.rejects(() => adapter.identities(), /malformed/);
    await assert.rejects(() => adapter.remove(source, true), /could not be verified/);
    respond({ connection: { success: false } });
    await assert.rejects(() => adapter.testConnection(null, {}), /malformed/);
    respond({ item: {} });
    await assert.rejects(() => adapter.ignorePath(source.id, 'remote-path', true), /malformed/);
    respond({ sources: [{ id: 'missing-revision' }] });
    await assert.rejects(() => adapter.list(), /malformed/);
    respond({ ...options, recursive_allowed: 'false' });
    await assert.rejects(() => adapter.options(), /malformed/);
    respond({ ...options, limits: { max_sources: 1.5 } });
    await assert.rejects(() => adapter.options(), /malformed/);
    respond({});
    await assert.rejects(() => adapter.update({ id: 'no-revision' }, write), /version marker/);
    assert.equal(calls.length, 0, 'No write may occur without the revision.');
}

function fields(): void {
    for (const sourceType of ['smb', 'azure_files', 'azure_blob']) {
        for (const authType of connectionDescriptor(sourceType).authTypes) {
            const draft = emptyFileSourceDraft(sourceType, 5);
            draft.credentialMode = 'inline';
            Object.assign(draft, {
                name: 'Reports', selectedPaths: ['Q1/report.pdf'], fixedTags: ['finance'],
                folderTagMode: 'full_path', remoteDeletePolicy: 'hard_delete',
                includePatterns: '*.pdf, *.docx', excludePatterns: 'drafts/*',
                allowedExtensions: 'pdf', scheduleEnabled: true, intervalMinutes: 30,
            });
            Object.assign(draft.credentials, {
                authType, username: 'svc', domain: 'CORP', clientId: 'client-id', tenantId: 'tenant-id',
                secret: 'fixture-new-secret',
            });
            const write = buildFileSourceWrite(draft);
            assert.deepEqual(write.connection?.selected_paths, ['Q1/report.pdf']);
            assert.deepEqual(write.filters?.fixed_tags, ['finance']);
            assert.equal(write.filters?.folder_tag_mode, 'full_path');
            assert.equal(write.remote_delete_policy, 'hard_delete');
            assert.deepEqual(write.schedule, { enabled: true, interval_minutes: 30 });
            assert.equal(write.credentials?.auth_type, authType);
            if (authType === 'managed_identity') assert.equal(write.credentials?.managed_identity_client_id, 'client-id');
            if (authType === 'client_secret') {
                assert.equal(write.credentials?.identity, 'client-id');
                assert.equal(write.credentials?.tenant_id, 'tenant-id');
                assert.equal(write.credentials?.secret, 'fixture-new-secret');
            }
            if (authType === 'connection_string') assert.equal(write.credentials?.connection_string, 'fixture-new-secret');
            if (authType === 'username_password') assert.equal(write.credentials?.password, 'fixture-new-secret');
            draft.credentialMode = 'identity';
            draft.identityId = 'identity';
            const bound = buildFileSourceWrite(draft);
            assert.equal(bound.identity_id, 'identity');
            assert.equal(bound.credentials, undefined);
        }
    }
    const masked = draftFromSource({
        ...source, credentials: { auth_type: 'username_password', password: '********', password_stored: true },
    }, 5);
    assert.equal(masked.credentials.secret, '');
    assert.equal(buildFileSourceWrite(masked).credentials?.password, '');
    const existing = draftFromSource({
        id: 'onedrive-existing', source_type: 'onedrive', identity_id: 'old-global',
        connection: { selected_paths: ['Reports'] }, credentials: { auth_type: 'global_identity' },
    }, 5);
    const oneDriveWrite = buildFileSourceWrite(existing);
    assert.deepEqual(oneDriveWrite.connection, { selected_paths: ['Reports'] });
    assert.deepEqual(oneDriveWrite.credentials, { auth_type: 'global_identity' });
    assert.equal(oneDriveWrite.identity_id, '');
    assert.ok(!visibleSourceTypes(options).some((item) => item.value === 'onedrive'));
    assert.throws(() => connectionDescriptor('google_workspace'), /cannot be configured/);
}

async function main(): Promise<void> {
    await transport();
    fields();
    console.log('native personal configuration transport and field checks passed');
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
