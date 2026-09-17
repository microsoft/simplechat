// modelConnections.ts
// Types, API wrappers and pure form logic for global model connections.
//
// A "connection" is an Azure OpenAI/Foundry resource or a Custom API: where
// it is, how SimpleChat authenticates, and which of its models may be used. The classic
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
import {
    buildCustomConnectionPayload, connectionRequestModel, CUSTOM_AUTH_TYPE_OPTIONS, validateCustomConnection,
    type CustomApiType, type CustomApiTypeDescriptor, type CustomNetworkPolicy,
} from './customModelConnections';

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

/** Providers offered in the editor. Matches `is_frontend_visible_model_endpoint_provider`. */
export type ConnectionProvider = 'aoai' | 'aifoundry' | 'new_foundry' | 'custom' | 'openai_compatible';

export type ConnectionAuthType = 'managed_identity' | 'service_principal' | 'api_key' | 'bearer' | 'oauth2_client_credentials';

export type ManagedIdentityType = 'system_assigned' | 'user_assigned';

export type ManagementCloud = 'public' | 'usgovernment' | 'custom';

export type IdentityHeaderMode = 'inherit' | 'enabled' | 'disabled';

export type ImplementedCapability = 'chat' | 'image_generation' | 'embeddings';

export const CAPABILITY_OPTIONS: Array<{ key: ImplementedCapability; label: string; supportKey: 'supportsChat' | 'supportsImageGeneration' | 'supportsEmbeddings' }> = [
    { key: 'chat', label: 'chat', supportKey: 'supportsChat' },
    { key: 'image_generation', label: 'images', supportKey: 'supportsImageGeneration' },
    { key: 'embeddings', label: 'embeddings', supportKey: 'supportsEmbeddings' },
];

export interface EmbeddingConfig {
    dimensions?: number;
    max_input_tokens?: number;
    max_batch_size?: number;
    max_batch_tokens?: number;
    model_revision?: string;
    document_prefix?: string;
    query_prefix?: string;
    openai_compatible?: boolean;
}

export interface EmbeddingPolicy {
    dimensions?: number;
    default_dimensions?: number;
    supports_dimensions?: boolean;
    request_dimensions?: number;
    min_dimensions?: number;
    max_dimensions?: number;
    allowed_dimensions?: number[];
    max_input_tokens?: number;
    max_batch_size?: number;
    max_batch_tokens?: number;
    tokenizer?: 'cl100k_base' | 'conservative';
    api?: 'openai' | 'unsupported';
    requires_input_type?: boolean;
}

export interface EmbeddingOperationSettings {
    api?: 'azure_openai' | 'openai';
    endpoint?: string;
    api_version?: string;
    is_apim?: boolean;
    auth_header?: 'api-key' | 'authorization' | 'Ocp-Apim-Subscription-Key';
}

export interface ModelCapabilityStatus {
    supported: boolean;
    available?: boolean;
    source: string;
    reason?: string;
    api?: string;
}

export interface ConnectionMigrationNotice {
    status: string;
    message: string;
    imported_connections?: number;
}

export interface ConnectionModel {
    id?: string;
    deploymentName?: string;
    modelName?: string;
    displayName?: string;
    description?: string;
    enabled?: boolean;
    isDiscovered?: boolean;
    responseLength?: number | string;
    supportsChat?: boolean;
    supportsImageGeneration?: boolean;
    supportsEmbeddings?: boolean;
    supportsImageEditing?: boolean;
    supportsImageMasking?: boolean;
    image_generation_api?: 'images' | 'responses' | 'mai' | 'flux';
    supportsVision?: boolean;
    embedding_config?: EmbeddingConfig;
    embedding_policy?: EmbeddingPolicy;
    enabled_capabilities?: ImplementedCapability[];
    capability_status?: {
        chat?: ModelCapabilityStatus;
        image_generation?: ModelCapabilityStatus;
        embeddings?: ModelCapabilityStatus;
        vision?: { supported: boolean; source: string };
    };
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
    bearer_token?: string;
    token_url?: string;
    scope?: string;
    api_key_header?: string;
    api_key_prefix?: string;
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
    api_type?: CustomApiType;
    enabled?: boolean;
    connection?: {
        endpoint?: string;
        openai_api_version?: string;
        api_version?: string;
        anthropic_version?: string;
        url_mode?: 'auto' | 'exact';
        client_cert_path?: string;
        client_key_path?: string;
        project_api_version?: string;
        project_name?: string;
        operation_settings?: {
            embeddings?: EmbeddingOperationSettings;
            [key: string]: unknown;
        };
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
    has_bearer_token?: boolean;
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
        value: 'custom',
        label: 'Custom',
        hint: 'OpenAI, Azure OpenAI, Anthropic, or Gemini-compatible APIs with explicit authentication and manually configured models.',
    },
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
    {
        value: 'openai_compatible',
        label: 'OpenAI-compatible (embeddings only)',
        hint: 'A verified OpenAI-compatible embedding API base URL. API key authentication and manually configured text embedding models only; no Azure discovery.',
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
    return [...AUTH_TYPE_OPTIONS, ...CUSTOM_AUTH_TYPE_OPTIONS].find((option) => option.value === raw)?.label ?? (raw || 'Managed identity');
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
    return isFoundryProvider(provider) || provider === 'openai_compatible'
        ? DEFAULT_FOUNDRY_OPENAI_API_VERSION
        : DEFAULT_AOAI_OPENAI_API_VERSION;
}

export function defaultEmbeddingApi(connection: ModelConnection): 'azure_openai' | 'openai' {
    if (connection.provider === 'custom') {
        return connection.api_type === 'azure_openai' ? 'azure_openai' : 'openai';
    }
    return (connection.provider || 'aoai') === 'aoai' &&
        !/\/openai\/v1(?:\/|$)/i.test(text(connection.connection?.endpoint))
        ? 'azure_openai' : 'openai';
}

export function embeddingConnectionUnavailableReason(connection: ModelConnection): string | null {
    if (connection.provider === 'custom' && (
        !['openai', 'azure_openai'].includes(connection.api_type || '')
        || !['api_key', 'bearer'].includes(connection.auth?.type || 'api_key')
    )) {
        return 'Embeddings require a Custom OpenAI or Azure OpenAI API with API key or bearer authentication. Other Custom API types and OAuth2 embeddings are not supported.';
    }
    return null;
}

/** Update one operation override without rewriting other operations or their defaults. */
export function setEmbeddingOperation(
    connection: ModelConnection,
    key: keyof EmbeddingOperationSettings,
    value: string | boolean,
): ModelConnection {
    const operations = { ...connection.connection?.operation_settings };
    const embedding = { ...operations.embeddings };
    if (value === '') {
        delete embedding[key];
    } else {
        Object.assign(embedding, { [key]: typeof value === 'string' ? value.trim() : value });
    }
    if (Object.keys(embedding).length) {
        operations.embeddings = embedding;
    } else {
        delete operations.embeddings;
    }
    const nextConnection = { ...connection.connection };
    if (Object.keys(operations).length) {
        nextConnection.operation_settings = operations;
    } else {
        delete nextConnection.operation_settings;
    }
    return { ...connection, connection: nextConnection };
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
        connection: source.provider === 'custom'
            ? { url_mode: 'auto', ...(source.connection ?? {}) }
            : { ...blank.connection, ...(source.connection ?? {}) },
        management: { ...blank.management, ...(source.management ?? {}) },
        auth: source.provider === 'custom'
            ? { type: 'api_key', ...(source.auth ?? {}) }
            : {
                ...blank.auth,
                ...(source.auth ?? {}),
                ...(source.provider === 'openai_compatible' ? { type: 'api_key' as const } : {}),
            },
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
    openAiVersion: boolean;
    discovery: boolean;
} {
    const provider = text(connection.provider) || 'aoai';
    const embeddingOnly = provider === 'openai_compatible';
    const custom = provider === 'custom';
    const external = custom || embeddingOnly;
    const authType = embeddingOnly ? 'api_key' : (text(connection.auth?.type) || (custom ? 'api_key' : 'managed_identity')) as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);
    const cloud = text(connection.auth?.management_cloud) || 'public';

    return {
        project: foundry,
        // Discovery for Azure OpenAI goes through Azure Resource Manager, which needs the
        // resource coordinates. An API key cannot reach ARM, so they serve no purpose there.
        management: provider === 'aoai' && authType !== 'api_key',
        managedIdentity: !external && authType === 'managed_identity',
        servicePrincipal: !external && authType === 'service_principal',
        apiKey: authType === 'api_key',
        managementCloud: !external && authType !== 'api_key',
        customAuthority: !external && authType !== 'api_key' && cloud === 'custom',
        foundryScope: foundry && authType !== 'api_key',
        userAssignedClientId:
            !external && authType === 'managed_identity' &&
            text(connection.auth?.managed_identity_type) === 'user_assigned',
        openAiVersion: !external,
        discovery: !external && authType !== 'api_key',
    };
}

/**
 * Validate a connection, returning one message per offending field.
 *
 * Keyed by field so the editor can mark the control that caused it, rather than the
 * classic editor's behaviour of raising a toast that named the problem but not the place.
 */
export function validateConnection(
    connection: ModelConnection,
    { requireDiscovery = false }: { requireDiscovery?: boolean } = {},
): Record<string, string> {
    if (connection.provider === 'custom') {
        return { ...validateCustomConnection(connection), ...validateEmbeddingConfiguration(connection) };
    }
    const errors: Record<string, string> = {};
    const provider = text(connection.provider) || 'aoai';
    const authType = (text(connection.auth?.type) || 'managed_identity') as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);
    const custom = provider === 'openai_compatible';
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

    if (!custom && !text(connection.connection?.openai_api_version)) {
        errors.openai_api_version = 'An OpenAI API version is required.';
    }
    if (custom && authType !== 'api_key') {
        errors.auth_type = 'OpenAI-compatible connections support API key authentication only.';
    }
    if (custom && requireDiscovery) {
        errors.discovery = 'Custom embedding connections use manually entered models, not Azure discovery.';
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

    if (shown.management && requireDiscovery) {
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

    return { ...errors, ...validateEmbeddingConfiguration(connection) };
}

function validateEmbeddingConfiguration(connection: ModelConnection): Record<string, string> {
    const errors: Record<string, string> = {};
    const provider = text(connection.provider) || 'aoai';
    const embeddingOnly = provider === 'openai_compatible';
    const custom = provider === 'custom';
    const foundry = isFoundryProvider(provider);
    const endpoint = text(connection.connection?.endpoint);
    const embedding = connection.connection?.operation_settings?.embeddings;
    const embeddingApi = embedding?.api || defaultEmbeddingApi(connection);
    if (embedding?.api && (!['azure_openai', 'openai'].includes(embedding.api) || (embeddingOnly && embedding.api !== 'openai'))) {
        errors.embedding_api = 'Choose a supported embedding API. Embedding-only OpenAI-compatible connections require the OpenAI-compatible API.';
    } else if (custom && embedding?.api && embedding.api !== connection.api_type) {
        errors.embedding_api = 'The embedding operation must match the Custom connection API type.';
    }
    if (embedding?.auth_header && !['api-key', 'authorization', 'Ocp-Apim-Subscription-Key'].includes(embedding.auth_header)) {
        errors.embedding_auth_header = 'Choose one of the supported embedding authentication headers.';
    }
    const publishedEmbeddings = (connection.models ?? []).filter((model) =>
        model.enabled !== false &&
        (!model.enabled_capabilities || model.enabled_capabilities.includes('embeddings')) &&
        (embeddingOnly || modelSupportsCapability(model, 'embeddings')),
    );
    if (embedding?.endpoint || publishedEmbeddings.length) {
        const inferenceEndpoint = text(embedding?.endpoint) || endpoint;
        try {
            const parsed = new URL(inferenceEndpoint);
            if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
                throw new Error('Invalid base URL');
            }
            if (endpointIncludesProject(inferenceEndpoint)) {
                errors.embedding_endpoint = 'Foundry project endpoints do not route embeddings. Enter the explicit embedding inference base URL ending /openai/v1/.';
            } else if (foundry && !/\/openai\/v1\/?$/i.test(parsed.pathname)) {
                errors.embedding_endpoint = 'Enter the explicit Foundry embedding inference base URL ending /openai/v1/. The project URL is not rewritten.';
            }
        } catch {
            errors.embedding_endpoint = 'Enter a full embedding API base URL without credentials, a query, or a fragment.';
        }
    }
    if (embeddingApi === 'openai' && embedding?.api_version) {
        errors.embedding_api_version = 'The OpenAI-compatible embedding API does not use an Azure api-version query. Clear the embedding API version override.';
    }
    (connection.models ?? []).forEach((model, index) => {
        const config = model.embedding_config;
        for (const key of ['dimensions', 'max_input_tokens', 'max_batch_size', 'max_batch_tokens'] as const) {
            if (config?.[key] !== undefined && (!Number.isSafeInteger(config[key]) || Number(config[key]) <= 0)) {
                errors[`model_${index}_${key}`] = `${key.replaceAll('_', ' ')} must be a positive whole number.`;
            }
        }
        if (!publishedEmbeddings.includes(model)) return;
        const unavailableReason = embeddingConnectionUnavailableReason(connection);
        if (unavailableReason) {
            errors[`model_${index}_supportsEmbeddings`] = unavailableReason;
        } else if (embeddingOnly && !isKnownEmbeddingModel(model) && !modelSupportsCapability(model, 'embeddings')) {
            errors[`model_${index}_supportsEmbeddings`] = 'Declare embedding support for this custom model before publishing it.';
        }
        if (!isKnownEmbeddingModel(model) && model.capability_status?.embeddings?.source !== 'catalog') {
            if (model.supportsEmbeddings !== true) {
                errors[`model_${index}_supportsEmbeddings`] = 'Unknown embedding models require an explicit administrator declaration of embedding support.';
            }
            for (const key of ['dimensions', 'max_input_tokens'] as const) {
                if (!config?.[key]) {
                    errors[`model_${index}_${key}`] = `Unknown embedding models require explicit ${key.replaceAll('_', ' ')}; no catalog default is assumed.`;
                }
            }
        }
    });
    return errors;
}

/**
 * Shape a connection for the server, dropping fields the chosen provider does not use.
 *
 * Blank secrets are omitted rather than sent empty: the server treats an absent secret as
 * "keep what is stored", so sending "" would clear a key the editor was never shown.
 */
export function buildConnectionPayload(connection: ModelConnection): Record<string, unknown> {
    if (connection.provider === 'custom') return buildCustomConnectionPayload(connection);
    const provider = (text(connection.provider) || 'aoai') as ConnectionProvider;
    const custom = provider === 'openai_compatible';
    const authType = custom ? 'api_key' : (text(connection.auth?.type) || 'managed_identity') as ConnectionAuthType;
    const foundry = isFoundryProvider(provider);

    const endpoint = text(connection.connection?.endpoint);
    const connectionBlock: Record<string, unknown> = {
        ...connection.connection,
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
    } else {
        delete connectionBlock.project_api_version;
        delete connectionBlock.project_name;
    }
    if (custom) {
        delete connectionBlock.openai_api_version;
        delete connectionBlock.api_version;
    }

    const auth: Record<string, unknown> = {
        type: authType,
        ...(!custom ? {
            management_cloud: text(connection.auth?.management_cloud) || 'public',
            custom_authority: text(connection.auth?.custom_authority),
            foundry_scope: text(connection.auth?.foundry_scope),
        } : {}),
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
            ...candidate,
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

/** Server metadata is authoritative; older chat records keep their existing behavior. */
export function isKnownEmbeddingModel(model: ConnectionModel): boolean {
    const name = text(model.modelName || model.deploymentName).toLowerCase();
    return [
        'text-embedding-ada-002', 'text-embedding-3-small', 'text-embedding-3-large',
        'embed-v-4-0', 'embed-v4.0', 'embed-english-v3.0', 'embed-multilingual-v3.0',
        'cohere-embed-v3-english', 'cohere-embed-v3-multilingual',
    ].includes(name);
}

export function modelNeedsEmbeddingGateway(model: ConnectionModel): boolean {
    return isKnownEmbeddingModel(model) &&
        !/^text-embedding-(ada-002|3-small|3-large)$/i.test(text(model.modelName || model.deploymentName));
}

export function modelSupportsCapability(model: ConnectionModel, capability: ImplementedCapability): boolean {
    if (isKnownEmbeddingModel(model) && capability !== 'embeddings') {
        return false;
    }
    const resolved = model.capability_status?.[capability];
    if (resolved) {
        return resolved.supported === true;
    }
    if (capability === 'embeddings') {
        return model.supportsEmbeddings ?? (
            isKnownEmbeddingModel(model) && (!modelNeedsEmbeddingGateway(model) || model.embedding_config?.openai_compatible === true)
        );
    }
    if (capability === 'image_generation') {
        return model.supportsImageGeneration === true;
    }
    return model.supportsChat ?? (
        model.supportsEmbeddings !== true && !model.embedding_policy && !model.embedding_config
    );
}

export function modelPublishesCapability(model: ConnectionModel, capability: ImplementedCapability): boolean {
    return model.enabled !== false &&
        modelSupportsCapability(model, capability) &&
        (!Array.isArray(model.enabled_capabilities) || model.enabled_capabilities.includes(capability));
}

/** Restrict publication without changing what the model technically supports. */
export function setModelCapabilityEnabled(
    model: ConnectionModel,
    capability: ImplementedCapability,
    enabled: boolean,
): ConnectionModel {
    const published = new Set<ImplementedCapability>(
        model.enabled_capabilities ?? CAPABILITY_OPTIONS.map(({ key }) => key),
    );
    if (enabled) {
        published.add(capability);
    } else {
        published.delete(capability);
    }
    return { ...model, enabled_capabilities: [...published] };
}

/* -------------------------------------------------------------------------- */
/* Default chat model                                                          */
/* -------------------------------------------------------------------------- */

/**
 * The stored reference to the model chat falls back to.
 *
 * It names an endpoint and a model by id rather than holding the model itself, which is
 * why it outlives what it points at and has to be re-checked against the connections that
 * currently exist.
 */
export interface DefaultModelSelection {
    endpoint_id: string;
    model_id: string;
    provider: string;
}

/** One offerable model, already resolved to the labels a picker needs. */
export interface DefaultModelChoice {
    endpointId: string;
    modelId: string;
    provider: string;
    connectionName: string;
    modelLabel: string;
    deploymentName: string;
    capability?: ModelCapabilityStatus;
}

export const EMPTY_DEFAULT_MODEL_SELECTION: DefaultModelSelection = {
    endpoint_id: '',
    model_id: '',
    provider: '',
};

export function toDefaultModelSelection(value: unknown): DefaultModelSelection {
    const source = value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
    return {
        endpoint_id: text(source.endpoint_id),
        model_id: text(source.model_id),
        provider: text(source.provider).toLowerCase(),
    };
}

export function hasDefaultModel(selection: DefaultModelSelection): boolean {
    return Boolean(selection.endpoint_id && selection.model_id);
}

export function isSameSelection(a: DefaultModelSelection, b: DefaultModelSelection): boolean {
    return a.endpoint_id === b.endpoint_id && a.model_id === b.model_id;
}

/**
 * The models an administrator may actually pick as the default.
 *
 * A disabled connection or a disabled model is excluded rather than shown greyed out,
 * because `resolve_default_model_selection` clears anything in that state on the next
 * write -- offering it would let someone choose a value that silently reverts.
 *
 * Ordered by connection then model so the list is stable between renders; the stored
 * order of connections is whatever the administrator added them in.
 */
export function buildDefaultModelChoices(connections: ModelConnection[]): DefaultModelChoice[] {
    const choices: DefaultModelChoice[] = [];

    for (const connection of connections ?? []) {
        if (!connection || connection.enabled === false || !text(connection.id) || connection.provider === 'openai_compatible') {
            continue;
        }
        const connectionName =
            text(connection.name) || text(connection.connection?.endpoint) || 'Connection';

        for (const model of connection.models ?? []) {
            if (!model || !modelPublishesCapability(model, 'chat')) {
                continue;
            }
            // `normalize_model_endpoints` fills a missing id from the deployment name, so
            // a model with neither is not addressable and cannot be referenced.
            const modelId = text(model.id) || connectionRequestModel(connection, model);
            if (!modelId) {
                continue;
            }
            choices.push({
                endpointId: text(connection.id),
                modelId,
                provider: text(connection.provider).toLowerCase(),
                connectionName,
                modelLabel:
                    text(model.displayName) ||
                    text(model.deploymentName) ||
                    text(model.modelName) ||
                    modelId,
                deploymentName: connectionRequestModel(connection, model),
                ...(model.capability_status?.chat ? { capability: model.capability_status.chat } : {}),
            });
        }
    }

    return choices.sort(
        (a, b) =>
            a.connectionName.localeCompare(b.connectionName) ||
            a.endpointId.localeCompare(b.endpointId) ||
            a.modelLabel.localeCompare(b.modelLabel),
    );
}

/**
 * Group choices by connection for `optgroup` rendering, carrying each one's index.
 *
 * The index is what the `select` uses as an option value, so it has to survive the
 * grouping; recovering it afterwards would mean searching the flat list per option.
 */
export function groupChoicesByConnection(
    choices: DefaultModelChoice[],
): Array<{ endpointId: string; connectionName: string; items: Array<{ choice: DefaultModelChoice; index: number }> }> {
    const groups: Array<{
        endpointId: string;
        connectionName: string;
        items: Array<{ choice: DefaultModelChoice; index: number }>;
    }> = [];

    choices.forEach((choice, index) => {
        const group = groups.find((item) => item.endpointId === choice.endpointId);
        if (group) {
            group.items.push({ choice, index });
        } else {
            groups.push({ endpointId: choice.endpointId, connectionName: choice.connectionName, items: [{ choice, index }] });
        }
    });

    return groups;
}

/**
 * Where a stored selection sits in the offerable list, or -1.
 *
 * The index is what the `select` carries as its option value. Endpoint and model ids are
 * administrator-supplied strings, so composing them into one value would need an escape
 * rule that a deployment name could still break.
 */
export function findChoiceIndex(
    choices: DefaultModelChoice[],
    selection: DefaultModelSelection,
): number {
    if (!hasDefaultModel(selection)) {
        return -1;
    }
    return choices.findIndex(
        (choice) =>
            choice.endpointId === selection.endpoint_id && choice.modelId === selection.model_id,
    );
}

/** Turn a picked choice back into the shape the API stores. */
export function choiceToSelection(choice: DefaultModelChoice | null): DefaultModelSelection {
    if (!choice) {
        return { ...EMPTY_DEFAULT_MODEL_SELECTION };
    }
    return {
        endpoint_id: choice.endpointId,
        model_id: choice.modelId,
        provider: choice.provider,
    };
}

/* -------------------------------------------------------------------------- */
/* API                                                                         */
/* -------------------------------------------------------------------------- */

const BASE = '/api/v2/admin/model-endpoints';

export interface ConnectionListResponse {
    endpoints: ModelConnection[];
    multi_endpoint_enabled?: boolean;
    migration?: ConnectionMigrationNotice | null;
    embedding_migration?: ConnectionMigrationNotice | null;
    default_notices?: Record<string, string | null>;
    custom_api_types?: CustomApiTypeDescriptor[];
    custom_network_policy?: CustomNetworkPolicy;
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
    api.post<{ success?: boolean; count?: number; validation_only?: boolean; message?: string }>('/api/models/test-connection', payload);

/** Check that one specific deployment answers. */
export const testConnectionModel = (payload: Record<string, unknown>, model: ConnectionModel | string) =>
    api.post<{ success?: boolean }>('/api/models/test-model', {
        ...payload,
        model: typeof model === 'string' ? { deploymentName: model } : model,
    });

export const saveCustomNetworkPolicy = (settings: CustomNetworkPolicy) =>
    api.patch<{ settings: CustomNetworkPolicy }>('/api/v2/admin/settings', { settings });

const DEFAULT_MODEL_BASE = '/api/v2/admin/default-model';

export interface DefaultModelResponse {
    selection: DefaultModelSelection;
    multi_endpoint_enabled: boolean;
    /** Why the stored selection no longer resolves, when it does not. */
    reason: string | null;
}

export const fetchDefaultModel = (signal?: AbortSignal) =>
    api.get<DefaultModelResponse>(DEFAULT_MODEL_BASE, signal);

export const saveDefaultModel = (selection: DefaultModelSelection) =>
    api.put<{ selection: DefaultModelSelection }>(DEFAULT_MODEL_BASE, { selection });
