// customModelConnections.ts
// Custom transport metadata is supplied by the server registry, not inferred from model names.

import type { ConnectionModel, ModelConnection } from './modelConnections';

export type CustomApiType = 'openai' | 'azure_openai' | 'anthropic' | 'gemini';

export interface CustomApiTypeDescriptor {
    value: CustomApiType;
    label: string;
    protocol: string;
    urlPolicy: string;
    usesModelName: boolean;
    requiresApiVersion: boolean;
    versionField: string;
    defaultVersion: string;
    authTypes: string[];
    defaultApiKeyHeader: string;
    defaultApiKeyPrefix: string;
    description: string;
}

export interface CustomNetworkPolicy {
    allow_private_custom_model_endpoints: boolean;
    allow_insecure_custom_model_endpoints: boolean;
    custom_model_endpoint_ca_bundle_path: string;
}

export const EMPTY_CUSTOM_NETWORK_POLICY: CustomNetworkPolicy = {
    allow_private_custom_model_endpoints: false,
    allow_insecure_custom_model_endpoints: false,
    custom_model_endpoint_ca_bundle_path: '',
};

export const CUSTOM_AUTH_TYPE_OPTIONS = [
    { value: 'api_key', label: 'API key', hint: 'Sent in the API type’s default header, or an explicit gateway authentication header.' },
    { value: 'bearer', label: 'Bearer token', hint: 'A stored token sent as Authorization: Bearer.' },
    { value: 'oauth2_client_credentials', label: 'OAuth2 client credentials', hint: 'Fetches short-lived bearer tokens through the same guarded transport as inference.' },
] as const;

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

export function connectionUsesModelName(connection: ModelConnection): boolean {
    return connection.provider === 'custom' && ['openai', 'anthropic', 'gemini'].includes(text(connection.api_type));
}

export function connectionRequestModel(connection: ModelConnection, model: ConnectionModel): string {
    return connectionUsesModelName(connection)
        ? text(model.modelName) || text(model.name)
        : text(model.deploymentName) || text(model.deployment);
}

export function validateCustomConnection(connection: ModelConnection): Record<string, string> {
    const errors: Record<string, string> = {};
    const auth = connection.auth ?? {};
    if (!text(connection.name)) errors.name = 'Give the connection a name.';
    if (!['openai', 'azure_openai', 'anthropic', 'gemini'].includes(text(connection.api_type))) {
        errors.api_type = 'Choose a supported Custom API type.';
    }
    try {
        const endpoint = new URL(text(connection.connection?.endpoint));
        if (!['https:', 'http:'].includes(endpoint.protocol) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
            errors.endpoint = 'Use an HTTP(S) endpoint without credentials, query parameters, or a fragment.';
        }
    } catch {
        errors.endpoint = 'Enter the full Custom endpoint URL.';
    }
    if (connection.api_type === 'azure_openai' && !text(connection.connection?.api_version)) {
        errors.api_version = 'Custom Azure OpenAI requires an explicit API version.';
    }
    if (!CUSTOM_AUTH_TYPE_OPTIONS.some((option) => option.value === auth.type)) {
        errors.auth_type = 'Choose a Custom authentication method.';
    }
    if (auth.type === 'api_key' && !text(auth.api_key) && !connection.has_api_key) {
        errors.api_key = 'An API key is required.';
    }
    if (auth.type === 'bearer' && !text(auth.bearer_token) && !connection.has_bearer_token) {
        errors.bearer_token = 'A bearer token is required.';
    }
    if (auth.type === 'oauth2_client_credentials') {
        if (!text(auth.token_url)) errors.token_url = 'A token endpoint URL is required.';
        if (!text(auth.client_id)) errors.client_id = 'An OAuth2 client ID is required.';
        if (!text(auth.client_secret) && !connection.has_client_secret) errors.client_secret = 'An OAuth2 client secret is required.';
    }
    const models = connection.models ?? [];
    const identifiers = models.map((model) => connectionRequestModel(connection, model).toLowerCase());
    if (!models.length || identifiers.some((identifier) => !identifier)) {
        errors.models = `Add at least one model with a ${connectionUsesModelName(connection) ? 'model name' : 'deployment name'}.`;
    } else if (new Set(identifiers).size !== identifiers.length) {
        errors.models = 'Request model identifiers must be unique.';
    }
    if (text(connection.connection?.client_key_path) && !text(connection.connection?.client_cert_path)) {
        errors.client_cert_path = 'A client key requires a client certificate.';
    }
    return errors;
}

export function buildCustomConnectionPayload(connection: ModelConnection): Record<string, unknown> {
    const apiType = text(connection.api_type);
    const connectionBlock: Record<string, unknown> = {
        ...connection.connection,
        endpoint: text(connection.connection?.endpoint),
        url_mode: text(connection.connection?.url_mode) || 'auto',
    };
    delete connectionBlock.openai_api_version;
    delete connectionBlock.project_api_version;
    delete connectionBlock.project_name;
    if (apiType !== 'azure_openai') delete connectionBlock.api_version;
    if (apiType !== 'anthropic') delete connectionBlock.anthropic_version;
    const sourceAuth = connection.auth ?? {};
    const auth: Record<string, unknown> = { type: sourceAuth.type || 'api_key' };
    if (auth.type === 'api_key') {
        auth.api_key_header = text(sourceAuth.api_key_header);
        if ('api_key_prefix' in sourceAuth) auth.api_key_prefix = text(sourceAuth.api_key_prefix);
        if (text(sourceAuth.api_key)) auth.api_key = text(sourceAuth.api_key);
    } else if (auth.type === 'bearer') {
        if (text(sourceAuth.bearer_token)) auth.bearer_token = text(sourceAuth.bearer_token);
    } else if (auth.type === 'oauth2_client_credentials') {
        auth.token_url = text(sourceAuth.token_url);
        auth.client_id = text(sourceAuth.client_id);
        auth.scope = text(sourceAuth.scope);
        if (text(sourceAuth.client_secret)) auth.client_secret = text(sourceAuth.client_secret);
    }
    return {
        ...(connection.id ? { id: connection.id } : {}),
        name: text(connection.name),
        provider: 'custom',
        api_type: apiType,
        enabled: connection.enabled !== false,
        connection: connectionBlock,
        auth,
        management: {},
        identity_header: { ...connection.identity_header },
        models: (connection.models ?? []).map((model) => ({
            ...model,
            displayName: text(model.displayName) || connectionRequestModel(connection, model),
            enabled: model.enabled !== false,
        })),
    };
}
