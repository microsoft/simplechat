// modelConnections.ts
// Types, API wrappers and pure form logic for global model connections.
//
// A "connection" is one Azure OpenAI or Foundry resource: where it is, how SimpleChat
// authenticates to it, and which of its deployed models may be used. The classic
// interface calls these model endpoints, and the stored shape is unchanged -- only the
// wording and the editing model differ.
//
// Why this exists as its own module rather than living in the component: the classic
// editor's rules about which fields a provider and auth type actually need are the part
// that made it confusing, and they are worth testing directly. Everything here is pure
// except the four API wrappers at the bottom.
//
// The payload shape is pinned against `buildEndpointPayload` in
// static/js/admin/admin_model_endpoints.js, which is what the server has always been
// given, and against `normalize_model_endpoints` in functions_settings.py, which is what
// it stores.

import { api } from './apiClient';

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

/** Providers offered in the editor. Matches `is_frontend_visible_model_endpoint_provider`. */
export type ConnectionProvider = 'aoai' | 'aifoundry' | 'new_foundry';

export type ConnectionAuthType = 'managed_identity' | 'service_principal' | 'api_key';

export type ManagedIdentityType = 'system_assigned' | 'user_assigned';

export type ManagementCloud = 'public' | 'usgovernment' | 'custom';

export type IdentityHeaderMode = 'inherit' | 'enabled' | 'disabled';

export interface ConnectionModel {
    id?: string;
    deploymentName?: string;
    modelName?: string;
    displayName?: string;
    description?: string;
    enabled?: boolean;
    isDiscovered?: boolean;
    responseLength?: number | string;
    [key: string]: unknown;
}

export interface ConnectionAuth {
    type?: ConnectionAuthType;
    managed_identity_type?: ManagedIdentityType;
    managed_identity_client_id?: string;
    tenant_id?: string;
    client_id?: string;
    client_secret?: string;
    api_key?: string;
    management_cloud?: ManagementCloud;
    custom_authority?: string;
    foundry_scope?: string;
    [key: string]: unknown;
}

export interface ConnectionIdentityHeader {
    mode?: IdentityHeaderMode;
    header_name?: string;
    value_type?: string;
}

export interface ModelConnection {
    id: string;
    name?: string;
    provider?: string;
    enabled?: boolean;
    connection?: {
        endpoint?: string;
        openai_api_version?: string;
        project_api_version?: string;
        project_name?: string;
        [key: string]: unknown;
    };
    management?: {
        subscription_id?: string;
        resource_group?: string;
        [key: string]: unknown;
    };
    auth?: ConnectionAuth;
    identity_header?: ConnectionIdentityHeader;
    models?: ConnectionModel[];
    /**
     * Set by `sanitize_model_endpoints_for_frontend`. The secret itself is stripped on the
     * way out, so this flag is the only way the editor can tell "a key is stored" from
     * "no key has ever been set" -- and therefore whether an empty input means "keep it".
     */
    has_api_key?: boolean;
    has_client_secret?: boolean;
    [key: string]: unknown;
}

/* -------------------------------------------------------------------------- */
/* Option lists                                                                */
/* -------------------------------------------------------------------------- */

export const DEFAULT_AOAI_OPENAI_API_VERSION = '2024-05-01-preview';
export const DEFAULT_FOUNDRY_OPENAI_API_VERSION = 'v1';
export const DEFAULT_FOUNDRY_PROJECT_API_VERSION = 'v1';

export const PROVIDER_OPTIONS: Array<{ value: ConnectionProvider; label: string; hint: string }> = [
    {
        value: 'aoai',
        label: 'Azure OpenAI',
        hint: 'An Azure OpenAI resource. Model discovery reads its deployments through Azure Resource Manager.',
    },
    {
        value: 'new_foundry',
        label: 'Azure AI Foundry',
        hint: 'A Foundry project endpoint. Model discovery reads the project’s deployments.',
    },
    {
        value: 'aifoundry',
        label: 'Azure AI Foundry (classic)',
        hint: 'The earlier Foundry project shape, kept for connections created before the move.',
    },
];

export const AUTH_TYPE_OPTIONS: Array<{
    value: ConnectionAuthType;
    label: string;
    hint: string;
}> = [
    {
        value: 'managed_identity',
        label: 'Managed identity',
        hint: 'Uses the App Service identity. No secret is stored.',
    },
    {
        value: 'service_principal',
        label: 'Service principal',
        hint: 'An app registration. The client secret is stored in Key Vault when it is configured.',
    },
    {
        value: 'api_key',
        label: 'API key',
        hint: 'Inference only. Model discovery needs Azure credentials, so the model list must be entered by hand.',
    },
];

export const MANAGEMENT_CLOUD_OPTIONS: Array<{ value: ManagementCloud; label: string }> = [
    { value: 'public', label: 'Azure public cloud' },
    { value: 'usgovernment', label: 'Azure US Government' },
    { value: 'custom', label: 'Custom authority' },
];

export const IDENTITY_HEADER_MODE_OPTIONS: Array<{
    value: IdentityHeaderMode;
    label: string;
}> = [
    { value: 'inherit', label: 'Use the global setting' },
    { value: 'enabled', label: 'Always send' },
    { value: 'disabled', label: 'Never send' },
];

export const IDENTITY_VALUE_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
    { value: '', label: 'Use the global setting' },
    { value: 'user_oid_tenant_id', label: 'Object id and tenant id' },
    { value: 'user_oid', label: 'Object id' },
    { value: 'user_upn_tenant_id', label: 'User principal name and tenant id' },
    { value: 'user_upn', label: 'User principal name' },
];

/* -------------------------------------------------------------------------- */
/* Pure helpers                                                                */
/* -------------------------------------------------------------------------- */

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

export function providerLabel(provider: unknown): string {
    const raw = text(provider);
    return PROVIDER_OPTIONS.find((option) => option.value === raw)?.label ?? (raw || 'Connection');
}

export function authTypeLabel(authType: unknown): string {
    const raw = text(authType);
    return AUTH_TYPE_OPTIONS.find((option) => option.value === raw)?.label ?? (raw || 'Managed identity');
}

export function isFoundryProvider(provider: unknown): boolean {
    const raw = text(provider);
    return raw === 'aifoundry' || raw === 'new_foundry';
}

/** Whether a Foundry endpoint URL already names its project. */
export function endpointIncludesProject(endpoint: unknown): boolean {
    return text(endpoint).toLowerCase().includes('/api/projects/');
}

/**
 * Pull the project name out of a Foundry endpoint URL.
 *
 * Mirrors `getProjectNameFromEndpoint` in the classic editor, including its fallback for
 * a value that is not a parseable URL, because an administrator pasting a half-typed
 * endpoint should still get the hint.
 */
export function projectNameFromEndpoint(endpoint: unknown): string {
    const value = text(endpoint);
    if (!value) {
        return '';
    }

    try {
        const parsed = new URL(value);
        const segments = parsed.pathname.split('/').filter(Boolean);
        const index = segments.findIndex((segment) => segment.toLowerCase() === 'projects');
        if (index >= 0 && segments[index + 1]) {
            return decodeURIComponent(segments[index + 1]);
        }
    } catch {
        const marker = '/api/projects/';
        const markerIndex = value.toLowerCase().indexOf(marker);
        if (markerIndex >= 0) {
            return value.slice(markerIndex + marker.length).split(/[/?#]/)[0];
        }
    }
    return '';
}

export function defaultOpenAiApiVersion(provider: unknown): string {
    return isFoundryProvider(provider)
        ? DEFAULT_FOUNDRY_OPENAI_API_VERSION
        : DEFAULT_AOAI_OPENAI_API_VERSION;
}

/** A blank connection, shaped so every control is controlled from the first render. */
export function emptyConnection(): ModelConnection {
    return {
        id: '',
        name: '',
        provider: 'aoai',
        enabled: true,
        connection: {
            endpoint: '',
            openai_api_version: DEFAULT_AOAI_OPENAI_API_VERSION,
            project_api_version: DEFAULT_FOUNDRY_PROJECT_API_VERSION,
            project_name: '',
        },
        management: { subscription_id: '', resource_group: '' },
        auth: {
            type: 'managed_identity',
            managed_identity_type: 'system_assigned',
            managed_identity_client_id: '',
            tenant_id: '',
            client_id: '',
            client_secret: '',
            api_key: '',
            management_cloud: 'public',
            custom_authority: '',
            foundry_scope: '',
        },
        identity_header: { mode: 'inherit', header_name: '', value_type: '' },
        models: [],
        has_api_key: false,
        has_client_secret: false,
    };
}

/** Fill a stored connection out to the full editor shape without losing unknown keys. */
export function toEditableConnection(source: ModelConnection): ModelConnection {
    const blank = emptyConnection();
    return {
        ...blank,
        ...source,
        connection: { ...blank.connection, ...(source.connection ?? {}) },
        management: { ...blank.management, ...(source.management ?? {}) },
        auth: { ...blank.auth, ...(source.auth ?? {}) },
        identity_header: { ...blank.identity_header, ...(source.identity_header ?? {}) },
        models: Array.isArray(source.models) ? source.models.map((model) => ({ ...model })) : [],
    };
}

/**
 * Which editor fields a given provider and auth type actually use.
 *
 * The classic editor decided this by toggling `d-none` across two dozen elements from
 * three separate listeners, which is why fields appeared and disappeared unpredictably
 * while typing. Deriving it in one place makes the rule inspectable and testable.
 */
export function visibleFields(connection: ModelConnection): {
    project: boolean;
    management: boolean;
    managedIdentity: boolean;
    servicePrincipal: boolean;
    apiKey: boolean;
    managementCloud: boolean;
    customAuthority: boolean;
    foundryScope: boolean;
    userAssignedClientId: boolean;
} {
    const provider = text(connection.provider) || 'aoai';
    const authType = (text(connection.auth?.type) || 'managed_identity') as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);
    const cloud = text(connection.auth?.management_cloud) || 'public';

    return {
        project: foundry,
        // Discovery for Azure OpenAI goes through Azure Resource Manager, which needs the
        // resource coordinates. An API key cannot reach ARM, so they serve no purpose there.
        management: provider === 'aoai' && authType !== 'api_key',
        managedIdentity: authType === 'managed_identity',
        servicePrincipal: authType === 'service_principal',
        apiKey: authType === 'api_key',
        managementCloud: authType !== 'api_key',
        customAuthority: authType !== 'api_key' && cloud === 'custom',
        foundryScope: foundry && authType !== 'api_key',
        userAssignedClientId:
            authType === 'managed_identity' &&
            text(connection.auth?.managed_identity_type) === 'user_assigned',
    };
}

/**
 * Validate a connection, returning one message per offending field.
 *
 * Keyed by field so the editor can mark the control that caused it, rather than the
 * classic editor's behaviour of raising a toast that named the problem but not the place.
 */
export function validateConnection(connection: ModelConnection): Record<string, string> {
    const errors: Record<string, string> = {};
    const provider = text(connection.provider) || 'aoai';
    const authType = (text(connection.auth?.type) || 'managed_identity') as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);
    const shown = visibleFields(connection);

    if (!text(connection.name)) {
        errors.name = 'Give the connection a name.';
    }

    const endpoint = text(connection.connection?.endpoint);
    if (!endpoint) {
        errors.endpoint = 'An endpoint URL is required.';
    } else if (!/^https?:\/\//i.test(endpoint)) {
        errors.endpoint = 'Enter the full URL, including https://.';
    }

    if (!text(connection.connection?.openai_api_version)) {
        errors.openai_api_version = 'An OpenAI API version is required.';
    }

    if (foundry) {
        if (!text(connection.connection?.project_api_version)) {
            errors.project_api_version =
                'A project API version is required for Foundry model discovery.';
        }
        if (!endpointIncludesProject(endpoint) && !text(connection.connection?.project_name)) {
            errors.project_name =
                'Name the project, or use an endpoint URL that includes /api/projects/.';
        }
    }

    if (shown.management) {
        if (!text(connection.management?.subscription_id)) {
            errors.subscription_id = 'Required so Azure OpenAI deployments can be discovered.';
        }
        if (!text(connection.management?.resource_group)) {
            errors.resource_group = 'Required so Azure OpenAI deployments can be discovered.';
        }
    }

    if (authType === 'service_principal') {
        if (!text(connection.auth?.tenant_id)) {
            errors.tenant_id = 'Required for service principal authentication.';
        }
        if (!text(connection.auth?.client_id)) {
            errors.client_id = 'Required for service principal authentication.';
        }
        // An empty box means "keep the stored secret" only when one is actually stored.
        if (!text(connection.auth?.client_secret) && !connection.has_client_secret) {
            errors.client_secret = 'Required for service principal authentication.';
        }
    }

    if (authType === 'api_key' && !text(connection.auth?.api_key) && !connection.has_api_key) {
        errors.api_key = 'Required for API key authentication.';
    }

    if (shown.customAuthority && !text(connection.auth?.custom_authority)) {
        errors.custom_authority = 'Required when the management cloud is Custom.';
    }

    if (foundry && authType === 'service_principal' && text(connection.auth?.management_cloud) === 'custom') {
        if (!text(connection.auth?.foundry_scope)) {
            errors.foundry_scope = 'Required when the management cloud is Custom.';
        }
    }

    return errors;
}

/**
 * Shape a connection for the server, dropping fields the chosen provider does not use.
 *
 * Blank secrets are omitted rather than sent empty: the server treats an absent secret as
 * "keep what is stored", so sending "" would clear a key the editor was never shown.
 */
export function buildConnectionPayload(connection: ModelConnection): Record<string, unknown> {
    const provider = (text(connection.provider) || 'aoai') as ConnectionProvider;
    const authType = (text(connection.auth?.type) || 'managed_identity') as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);

    const endpoint = text(connection.connection?.endpoint);
    const connectionBlock: Record<string, unknown> = {
        endpoint,
        openai_api_version: text(connection.connection?.openai_api_version) || defaultOpenAiApiVersion(provider),
    };

    if (foundry) {
        connectionBlock.project_api_version =
            text(connection.connection?.project_api_version) || DEFAULT_FOUNDRY_PROJECT_API_VERSION;
        const projectName =
            projectNameFromEndpoint(endpoint) || text(connection.connection?.project_name);
        if (projectName) {
            connectionBlock.project_name = projectName;
        }
    }

    const auth: Record<string, unknown> = {
        type: authType,
        management_cloud: text(connection.auth?.management_cloud) || 'public',
        custom_authority: text(connection.auth?.custom_authority),
        foundry_scope: text(connection.auth?.foundry_scope),
    };

    if (authType === 'managed_identity') {
        auth.managed_identity_type = text(connection.auth?.managed_identity_type) || 'system_assigned';
        auth.managed_identity_client_id = text(connection.auth?.managed_identity_client_id);
    }

    if (authType === 'service_principal') {
        auth.tenant_id = text(connection.auth?.tenant_id);
        auth.client_id = text(connection.auth?.client_id);
        const clientSecret = text(connection.auth?.client_secret);
        if (clientSecret) {
            auth.client_secret = clientSecret;
        }
    }

    if (authType === 'api_key') {
        const apiKey = text(connection.auth?.api_key);
        if (apiKey) {
            auth.api_key = apiKey;
        }
    }

    const payload: Record<string, unknown> = {
        name: text(connection.name),
        provider,
        enabled: connection.enabled !== false,
        connection: connectionBlock,
        management: provider === 'aoai'
            ? {
                  subscription_id: text(connection.management?.subscription_id),
                  resource_group: text(connection.management?.resource_group),
              }
            : {},
        auth,
        identity_header: {
            mode: (text(connection.identity_header?.mode) || 'inherit') as IdentityHeaderMode,
            header_name: text(connection.identity_header?.header_name),
            value_type: text(connection.identity_header?.value_type),
        },
        models: (connection.models ?? []).map((model) => ({
            ...model,
            deploymentName: text(model.deploymentName),
            displayName: text(model.displayName) || text(model.deploymentName),
            enabled: model.enabled !== false,
        })),
    };

    if (text(connection.id)) {
        payload.id = text(connection.id);
    }

    return payload;
}

/**
 * Merge discovered deployments into the model list already on the connection.
 *
 * Matching is by deployment name, case-insensitively, so re-running discovery does not
 * duplicate a model or overwrite a display name that was edited by hand. New models
 * arrive disabled, because discovery finding a deployment is not the same as an
 * administrator choosing to publish it.
 */
export function mergeDiscoveredModels(
    existing: ConnectionModel[],
    discovered: Array<Record<string, unknown>>,
): { models: ConnectionModel[]; added: number } {
    const models = existing.map((model) => ({ ...model }));
    const seen = new Set(
        models
            .map((model) => text(model.deploymentName).toLowerCase())
            .filter((name) => name.length > 0),
    );

    let added = 0;
    for (const candidate of discovered) {
        const deploymentName = text(candidate.deploymentName) || text(candidate.deployment);
        if (!deploymentName) {
            continue;
        }
        const key = deploymentName.toLowerCase();
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        models.push({
            id: deploymentName,
            deploymentName,
            modelName: text(candidate.modelName) || text(candidate.name),
            displayName: deploymentName,
            description: '',
            enabled: false,
            isDiscovered: true,
        });
        added += 1;
    }

    return { models, added };
}

export function enabledModelCount(connection: ModelConnection): number {
    return (connection.models ?? []).filter((model) => model.enabled !== false).length;
}

/* -------------------------------------------------------------------------- */
/* API                                                                         */
/* -------------------------------------------------------------------------- */

const BASE = '/api/v2/admin/model-endpoints';

export interface ConnectionListResponse {
    endpoints: ModelConnection[];
    multi_endpoint_enabled?: boolean;
}

export const fetchModelConnections = (signal?: AbortSignal) =>
    api.get<ConnectionListResponse>(BASE, signal);

export const createModelConnection = (payload: Record<string, unknown>) =>
    api.post<{ endpoint: ModelConnection }>(BASE, payload);

export const updateModelConnection = (id: string, payload: Record<string, unknown>) =>
    api.patch<{ endpoint: ModelConnection }>(`${BASE}/${encodeURIComponent(id)}`, payload);

export const deleteModelConnection = (id: string) =>
    api.delete<{ success: boolean }>(`${BASE}/${encodeURIComponent(id)}`);

/** Discover the deployments a connection exposes. Admin-gated, shared with the classic UI. */
export const discoverModels = (payload: Record<string, unknown>) =>
    api.post<{ models?: Array<Record<string, unknown>> }>('/api/models/fetch', payload);

/** Check that the connection's credentials and endpoint resolve. */
export const testConnection = (payload: Record<string, unknown>) =>
    api.post<{ success?: boolean; count?: number }>('/api/models/test-connection', payload);

/** Check that one specific deployment answers. */
export const testConnectionModel = (payload: Record<string, unknown>, deploymentName: string) =>
    api.post<{ success?: boolean }>('/api/models/test-model', {
        ...payload,
        model: { deploymentName },
    });
