// test_v2_azure_files_index_action_logic.mjs
// Version: 0.261.293
// Implemented in: 0.261.293
// Executes the real V2 Azure Files Search native registry, validation, preset, and test-payload logic.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import './test_support/tsResolve.mjs';

const {
    actionTypeLabel, changeActionAuth, changeActionField, changeActionType, createActionDraft, validateActionDraft,
} = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const { nativeActionDefinition } = await import('../application/v2_ui/src/lib/workspaceActionRegistry.ts');
const { buildActionConnectionPayload } = await import('../application/v2_ui/src/lib/workspaceActionServices.ts');
const {
    AZURE_FILES_INDEX_LAYOUT_DEFAULTS, addAzureFilesStorageShare, applyAzureFilesIndexLayoutPreset,
} = await import('../application/v2_ui/src/lib/azureFilesIndexAction.ts');
const { EDITOR_SECRET_MASK } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const schemas = path.join(root, 'application', 'single_app', 'static', 'json', 'schemas');
const definition = {
    type: 'azure_files_index',
    display: 'Azure Files Search',
    description: 'Search an existing Azure Files indexer index and return permitted files.',
    allowed_auth_types: JSON.parse(fs.readFileSync(path.join(schemas, 'azure_files_index.definition.json'), 'utf8')).allowedAuthTypes,
    additional_fields_schema: JSON.parse(fs.readFileSync(path.join(schemas, 'azure_files_index_plugin.additional_settings.schema.json'), 'utf8')),
    metadata_schema: { type: 'object', properties: {}, additionalProperties: true },
};
const share = {
    storage_account_resource_id: '/subscriptions/00000000-0000-4000-8000-000000000000/resourceGroups/rg-search/providers/Microsoft.Storage/storageAccounts/filesacct',
    share_name: 'documents',
};

let checks = 0;
function check(label, run) {
    run();
    checks += 1;
    console.log(`ok ${label}`);
}

function configuredDraft() {
    let draft = changeActionType(createActionDraft(), definition);
    draft = {
        ...draft,
        id: 'owned-azure-files',
        name: 'azure_files_search',
        displayName: 'Azure Files Search',
        description: 'Search Azure Files with ACL trimming.',
        endpoint: 'https://contoso.search.windows.net',
    };
    draft = changeActionField(draft, '/additionalFields/index_name', 'files-index');
    draft = changeActionField(draft, '/additionalFields/storage_shares', [share]);
    return draft;
}

check('registry exposes Azure Files Search with managed identity defaults and connection test route', () => {
    const native = nativeActionDefinition('azure_files_index');
    const draft = changeActionType(createActionDraft(), definition);
    assert.equal(actionTypeLabel('azure_files_index'), 'Azure Files Search');
    assert.equal(native.testPath, '/api/plugins/test-azure-files-index-connection');
    assert.deepEqual(definition.allowed_auth_types, ['identity', 'key']);
    assert.equal(draft.auth.type, 'identity');
    assert.equal(draft.auth.identity, 'managed_identity');
    assert.equal(draft.additionalFields.permission_mode, 'live_acl');
    assert.equal(draft.additionalFields.default_top_n, 5);
    assert.equal(draft.additionalFields.max_candidates, 50);
    assert.deepEqual(draft.additionalFields.storage_shares, []);
});

check('draft validation mirrors Azure Files Search endpoint, index, permission, and share rules', () => {
    const invalid = configuredDraft();
    invalid.endpoint = 'https://example.test';
    invalid.additionalFields.index_name = 'Bad--Index';
    invalid.additionalFields.query_mode = 'hybrid';
    invalid.additionalFields.index_layout = 'document_per_file';
    invalid.additionalFields.vector_field = '';
    invalid.additionalFields.storage_shares = [{
        storage_account_resource_id: '/subscriptions/not-a-guid/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct',
        share_name: 'Bad_Share',
    }];
    const errors = validateActionDraft(invalid, definition);
    assert.match(errors['/endpoint'], /Azure AI Search HTTPS endpoint/);
    assert.match(errors['/additionalFields/index_name'], /2-128 lowercase/);
    assert.match(errors['/additionalFields/vector_field'], /Vector field/);
    assert.match(errors['/additionalFields/storage_shares/0/storage_account_resource_id'], /storage account resource ID/);
    assert.match(errors['/additionalFields/storage_shares/0/share_name'], /Share name/);

    const noAcl = configuredDraft();
    noAcl.additionalFields.storage_shares = [];
    assert.match(validateActionDraft(noAcl, definition)['/additionalFields/storage_shares'], /at least one/);

    const noPermission = configuredDraft();
    noPermission.additionalFields.permission_mode = 'none';
    noPermission.additionalFields.permission_mode_none_acknowledged = false;
    assert.match(validateActionDraft(noPermission, definition)['/additionalFields/permission_mode_none_acknowledged'], /Acknowledge/);
    noPermission.additionalFields.permission_mode_none_acknowledged = true;
    assert.deepEqual(validateActionDraft(noPermission, definition), {});

    const keyed = changeActionAuth(configuredDraft(), { value: 'key', label: 'API key', authType: 'key' });
    keyed.auth.key = '';
    assert.ok(validateActionDraft(keyed, definition)['/auth/key']);
    keyed.auth.key = EDITOR_SECRET_MASK;
    assert.deepEqual(validateActionDraft(keyed, definition, { record: keyed, revision: 'r1', read_only: false, secret_paths: ['/auth/key'] }), {});
});

check('layout presets apply the field defaults used by the backend normalizer', () => {
    let draft = configuredDraft();
    draft = applyAzureFilesIndexLayoutPreset(draft, 'chunked');
    for (const [key, value] of Object.entries(AZURE_FILES_INDEX_LAYOUT_DEFAULTS.chunked)) {
        assert.equal(draft.additionalFields[key], value, key);
    }
    assert.equal(validateActionDraft(draft, definition)['/additionalFields/vector_field'], undefined);
    draft = applyAzureFilesIndexLayoutPreset(draft, 'custom');
    draft.additionalFields.content_field = '';
    draft.additionalFields.path_field = '';
    draft.additionalFields.name_field = '';
    const errors = validateActionDraft(draft, definition);
    assert.match(errors['/additionalFields/content_field'], /required/);
    assert.match(errors['/additionalFields/path_field'], /required/);
    assert.match(errors['/additionalFields/name_field'], /required/);
});

check('connection test payload uses the admin global scope and transient manifest contract', () => {
    const draft = addAzureFilesStorageShare(configuredDraft());
    draft.additionalFields.storage_shares[1] = {
        storage_account_resource_id: '/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg2/providers/Microsoft.Storage/storageAccounts/filesacct2',
        share_name: 'records',
    };
    const payload = buildActionConnectionPayload(draft, null, { global: true });
    assert.equal(payload.action_scope, 'global');
    assert.equal(payload.type, 'azure_files_index');
    assert.equal(payload.endpoint, 'https://contoso.search.windows.net');
    assert.deepEqual(payload.auth, { type: 'identity', identity: 'managed_identity' });
    assert.equal(payload.additionalFields.index_name, 'files-index');
    assert.deepEqual(payload.additionalFields.storage_shares, draft.additionalFields.storage_shares);
    assert.ok(!('existing_plugin' in payload));
});

console.log(`passed ${checks} Azure Files Search V2 action logic checks`);
