// azureFilesIndexAction.ts

import { EDITOR_SECRET_MASK, isRecord, type ActionConfiguration } from './workspaceAuthoring';

export const AZURE_FILES_INDEX_TYPE = 'azure_files_index';

export const AZURE_FILES_INDEX_LAYOUTS = ['document_per_file', 'chunked', 'custom'] as const;
export type AzureFilesIndexLayout = typeof AZURE_FILES_INDEX_LAYOUTS[number];

export const AZURE_FILES_INDEX_QUERY_MODES = ['keyword', 'semantic', 'hybrid'] as const;
export type AzureFilesIndexQueryMode = typeof AZURE_FILES_INDEX_QUERY_MODES[number];

export const AZURE_FILES_INDEX_PERMISSION_MODES = ['live_acl', 'none'] as const;
export type AzureFilesIndexPermissionMode = typeof AZURE_FILES_INDEX_PERMISSION_MODES[number];

export const AZURE_FILES_INDEX_SHARE_CHECKS = ['rbac', 'skip'] as const;
export type AzureFilesIndexShareCheck = typeof AZURE_FILES_INDEX_SHARE_CHECKS[number];

export interface AzureFilesStorageShareDraft {
    storage_account_resource_id: string;
    share_name: string;
}

export const AZURE_FILES_INDEX_LIMITS = {
    default_top_n: { min: 1, max: 20, defaultValue: 5 },
    max_candidates: { min: 5, max: 200, defaultValue: 50 },
    max_snippet_chars: { min: 200, max: 4000, defaultValue: 1200 },
    time_budget_seconds: { min: 5, max: 60, defaultValue: 25 },
} as const;

export const AZURE_FILES_INDEX_LAYOUT_DEFAULTS: Record<AzureFilesIndexLayout, {
    content_field: string;
    title_field: string;
    path_field: string;
    name_field: string;
    last_modified_field: string;
    vector_field: string;
    select_content: boolean;
}> = {
    document_per_file: {
        content_field: 'content',
        title_field: 'metadata_storage_name',
        path_field: 'metadata_storage_path',
        name_field: 'metadata_storage_name',
        last_modified_field: 'metadata_storage_last_modified',
        vector_field: '',
        select_content: false,
    },
    chunked: {
        content_field: 'chunk',
        title_field: 'title',
        path_field: 'metadata_storage_path',
        name_field: 'metadata_storage_name',
        last_modified_field: '',
        vector_field: 'text_vector',
        select_content: true,
    },
    custom: {
        content_field: '',
        title_field: '',
        path_field: '',
        name_field: '',
        last_modified_field: '',
        vector_field: '',
        select_content: false,
    },
};

export const AZURE_FILES_INDEX_DEFAULT_ADDITIONAL_FIELDS = {
    index_name: '',
    index_layout: 'document_per_file',
    ...AZURE_FILES_INDEX_LAYOUT_DEFAULTS.document_per_file,
    query_mode: 'keyword',
    semantic_configuration: '',
    default_top_n: AZURE_FILES_INDEX_LIMITS.default_top_n.defaultValue,
    max_candidates: AZURE_FILES_INDEX_LIMITS.max_candidates.defaultValue,
    max_snippet_chars: AZURE_FILES_INDEX_LIMITS.max_snippet_chars.defaultValue,
    time_budget_seconds: AZURE_FILES_INDEX_LIMITS.time_budget_seconds.defaultValue,
    permission_mode: 'live_acl',
    permission_mode_none_acknowledged: false,
    share_access_check: 'rbac',
    treat_builtin_users_as_member: false,
    storage_shares: [],
};

const INDEX_NAME_PATTERN = /^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){1,127}$/;
const FIELD_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,127}$/;
const RESOURCE_ID_PATTERN = /^\/subscriptions\/[0-9a-f-]{36}\/resourceGroups\/[^/]+\/providers\/Microsoft\.Storage\/storageAccounts\/[a-z0-9]{3,24}$/i;
const SHARE_NAME_PATTERN = /^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,62}$/;
const SEARCH_HOST_PATTERN = /(^|\.)search\.(windows\.net|azure\.us|azure\.cn)$/i;

function actionText(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function actionValueAt(value: unknown, pointer: string): unknown {
    if (!pointer) return value;
    return pointer.slice(1).split('/').reduce<unknown>((current, encoded) => {
        const key = encoded.replace(/~1/g, '/').replace(/~0/g, '~');
        if (Array.isArray(current)) return /^\d+$/.test(key) ? current[Number(key)] : undefined;
        return isRecord(current) && Object.hasOwn(current, key) ? current[key] : undefined;
    }, value);
}

function withActionValue<T>(value: T, pointer: string, nextValue: unknown): T {
    const parts = pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
    const update = (current: unknown, index: number): unknown => {
        if (index === parts.length) return nextValue;
        const key = parts[index];
        const record = isRecord(current) ? current : {};
        const entries = Object.entries(record).filter(([name]) => name !== key);
        const replacement = update(Object.hasOwn(record, key) ? record[key] : undefined, index + 1);
        if (replacement !== undefined) entries.push([key, replacement]);
        return Object.fromEntries(entries);
    };
    return update(value, 0) as T;
}

export function azureFilesIndexLayout(value: unknown): AzureFilesIndexLayout {
    return AZURE_FILES_INDEX_LAYOUTS.includes(value as AzureFilesIndexLayout) ? value as AzureFilesIndexLayout : 'document_per_file';
}

export function azureFilesIndexQueryMode(value: unknown): AzureFilesIndexQueryMode {
    return AZURE_FILES_INDEX_QUERY_MODES.includes(value as AzureFilesIndexQueryMode) ? value as AzureFilesIndexQueryMode : 'keyword';
}

export function azureFilesIndexPermissionMode(value: unknown): AzureFilesIndexPermissionMode {
    return AZURE_FILES_INDEX_PERMISSION_MODES.includes(value as AzureFilesIndexPermissionMode) ? value as AzureFilesIndexPermissionMode : 'live_acl';
}

export function azureFilesStorageShares(value: unknown): AzureFilesStorageShareDraft[] {
    if (!Array.isArray(value)) return [];
    return value.map((item) => isRecord(item) ? {
        storage_account_resource_id: actionText(item.storage_account_resource_id),
        share_name: actionText(item.share_name),
    } : { storage_account_resource_id: '', share_name: '' });
}

export function azureFilesIndexEffectiveField(draft: ActionConfiguration, key: keyof typeof AZURE_FILES_INDEX_LAYOUT_DEFAULTS.document_per_file): string | boolean {
    const value = actionValueAt(draft, `/additionalFields/${key}`);
    if (typeof value === 'boolean') return value;
    const text = actionText(value).trim();
    if (text || azureFilesIndexLayout(draft.additionalFields.index_layout) === 'custom') return text;
    return AZURE_FILES_INDEX_LAYOUT_DEFAULTS[azureFilesIndexLayout(draft.additionalFields.index_layout)][key];
}

export function applyAzureFilesIndexLayoutPreset(draft: ActionConfiguration, layout: AzureFilesIndexLayout): ActionConfiguration {
    let next = withActionValue(draft, '/additionalFields/index_layout', layout);
    if (layout !== 'custom') {
        for (const [key, value] of Object.entries(AZURE_FILES_INDEX_LAYOUT_DEFAULTS[layout])) {
            next = withActionValue(next, `/additionalFields/${key}`, value);
        }
    }
    return next;
}

export function updateAzureFilesStorageShare(
    draft: ActionConfiguration,
    index: number,
    field: keyof AzureFilesStorageShareDraft,
    value: string,
): ActionConfiguration {
    const shares = azureFilesStorageShares(draft.additionalFields.storage_shares);
    shares[index] = { ...(shares[index] ?? { storage_account_resource_id: '', share_name: '' }), [field]: value };
    return withActionValue(draft, '/additionalFields/storage_shares', shares);
}

export function addAzureFilesStorageShare(draft: ActionConfiguration): ActionConfiguration {
    return withActionValue(draft, '/additionalFields/storage_shares', [
        ...azureFilesStorageShares(draft.additionalFields.storage_shares),
        { storage_account_resource_id: '', share_name: '' },
    ]);
}

export function removeAzureFilesStorageShare(draft: ActionConfiguration, index: number): ActionConfiguration {
    return withActionValue(draft, '/additionalFields/storage_shares',
        azureFilesStorageShares(draft.additionalFields.storage_shares).filter((_, itemIndex) => itemIndex !== index));
}

function validSearchEndpoint(value: string): boolean {
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && SEARCH_HOST_PATTERN.test(url.hostname);
    } catch {
        return false;
    }
}

function fieldNameError(value: unknown, label: string, required: boolean): string | null {
    const text = actionText(value).trim();
    if (!text) return required ? `${label} is required.` : null;
    return FIELD_NAME_PATTERN.test(text) ? null : `${label}: use letters, numbers, and underscores, starting with a letter.`;
}

export function validateAzureFilesIndexDraft(draft: ActionConfiguration, original?: { secret_paths?: string[] } | null): Record<string, string> {
    if (draft.type !== AZURE_FILES_INDEX_TYPE) return {};
    const errors: Record<string, string> = {};
    const endpoint = actionText(draft.endpoint).trim();
    if (!validSearchEndpoint(endpoint)) {
        errors['/endpoint'] = 'Endpoint must be an Azure AI Search HTTPS endpoint ending in .search.windows.net, .search.azure.us, or .search.azure.cn.';
    }
    const indexName = actionText(draft.additionalFields.index_name).trim();
    if (!INDEX_NAME_PATTERN.test(indexName)) {
        errors['/additionalFields/index_name'] = 'Index name must be 2-128 lowercase letters, numbers, or single dashes.';
    }
    const layout = azureFilesIndexLayout(draft.additionalFields.index_layout);
    const custom = layout === 'custom';
    for (const [key, label, required] of [
        ['content_field', 'Content field', custom],
        ['title_field', 'Title field', false],
        ['path_field', 'Path field', custom],
        ['name_field', 'Name field', custom],
        ['last_modified_field', 'Last modified field', false],
        ['vector_field', 'Vector field', azureFilesIndexQueryMode(draft.additionalFields.query_mode) === 'hybrid'],
    ] as const) {
        const value = custom ? draft.additionalFields[key] : azureFilesIndexEffectiveField(draft, key);
        const message = fieldNameError(value, label, required);
        if (message) errors[`/additionalFields/${key}`] = message;
    }
    if (azureFilesIndexPermissionMode(draft.additionalFields.permission_mode) === 'none' &&
        draft.additionalFields.permission_mode_none_acknowledged !== true) {
        errors['/additionalFields/permission_mode_none_acknowledged'] = 'Acknowledge that everyone who can use this action can search every file in the index.';
    }
    const shares = azureFilesStorageShares(draft.additionalFields.storage_shares);
    if (azureFilesIndexPermissionMode(draft.additionalFields.permission_mode) === 'live_acl' && !shares.length) {
        errors['/additionalFields/storage_shares'] = 'Add at least one Azure Files share for live ACL permission checks.';
    }
    shares.forEach((share, index) => {
        if (!RESOURCE_ID_PATTERN.test(share.storage_account_resource_id.trim())) {
            errors[`/additionalFields/storage_shares/${index}/storage_account_resource_id`] =
                'Enter a storage account resource ID like /subscriptions/<guid>/resourceGroups/<name>/providers/Microsoft.Storage/storageAccounts/<name>.';
        }
        if (!SHARE_NAME_PATTERN.test(share.share_name.trim())) {
            errors[`/additionalFields/storage_shares/${index}/share_name`] =
                'Share name must be 3-63 lowercase letters, numbers, or single dashes.';
        }
    });
    if (draft.auth.type === 'key') {
        const key = actionText(draft.auth.key);
        if (!key || key === EDITOR_SECRET_MASK && !original?.secret_paths?.includes('/auth/key')) {
            errors['/auth/key'] = 'Query key is required.';
        }
    }
    return errors;
}
