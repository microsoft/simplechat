// workspaceActionConnectors.ts

import { api, ApiError, uploadFile } from './apiClient';
import {
    buildEditorWrite, EDITOR_SECRET_MASK, isRecord, pointerPart,
    type ActionConfiguration, type AuthoringResource,
} from './workspaceAuthoring';
import type { ActionIdentity } from './workspaceActionTypes';

export type ApiConnector = 'openapi' | 'mcp';
export type ConnectorResource = AuthoringResource<ActionConfiguration> | null;
export interface ConnectorOption { value: string; label: string }

// Remote specification import was removed; both modes use the upload validator.
export const OPENAPI_SOURCE_OPTIONS = [
    { value: 'file', label: 'Upload a JSON or YAML file' },
    { value: 'manual', label: 'Write or paste JSON / YAML' },
] as const;

export const STORED_CONNECTOR_SECRET = 'Stored_In_KeyVault';
export const OPENAPI_AUTH_OPTIONS: ConnectorOption[] = [
    { value: 'none', label: 'No authentication' },
    { value: 'api_key', label: 'API key' },
    { value: 'bearer', label: 'Bearer token' },
    { value: 'basic', label: 'Basic authentication' },
    { value: 'oauth2', label: 'OAuth 2 access token' },
];
export const MCP_AUTH_OPTIONS: ConnectorOption[] = [
    ...OPENAPI_AUTH_OPTIONS.filter(({ value }) => value !== 'oauth2'),
    { value: 'identity', label: 'Reusable identity' },
];
export const MCP_PERSONAL_TRANSPORTS: ConnectorOption[] = [
    { value: 'streamable_http', label: 'Streamable HTTP' },
    { value: 'sse', label: 'Server-sent events (SSE)' },
    { value: 'websocket', label: 'WebSocket' },
];
export const MCP_DEFAULT_FIELDS: Record<string, unknown> = {
    server_profile: 'generic', transport: 'streamable_http', auth_method: 'none',
    api_key_header_name: 'X-API-Key', load_tools: true, load_prompts: false,
    request_timeout: 30, connect_timeout: 10, sse_read_timeout: 300,
    retry_count: 0, retry_backoff_seconds: 1, validate_tool_arguments: false,
    tool_result_policy: 'truncate', allowed_tool_names: [],
};
export const MCP_NUMBER_FIELDS = [
    { key: 'request_timeout', label: 'Request timeout (seconds)', min: 1, max: 300, defaultValue: 30 },
    { key: 'connect_timeout', label: 'Connection timeout (seconds)', min: 1, max: 300, defaultValue: 10 },
    { key: 'sse_read_timeout', label: 'SSE read timeout (seconds)', min: 1, max: 300, defaultValue: 300 },
    { key: 'retry_count', label: 'Retry count', min: 0, max: 3, defaultValue: 0 },
    { key: 'retry_backoff_seconds', label: 'Retry backoff (seconds)', min: 1, max: 30, defaultValue: 1 },
];

export function connectorText(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

export function connectorObject(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : {};
}

export function connectorStrings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

export function connectorLines(value: string): string[] {
    return [...new Set(value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
}

export function updateConnectorFields(
    draft: ActionConfiguration, fields: Record<string, unknown>,
): ActionConfiguration {
    return { ...draft, additionalFields: { ...draft.additionalFields, ...fields } };
}

export function connectorAuthMethod(draft: ActionConfiguration, kind: ApiConnector): string {
    if (draft.identity_id || draft.auth.type === 'identity') return 'identity';
    const explicit = connectorText(draft.additionalFields.auth_method);
    if (explicit) return explicit;
    if (kind === 'mcp') return draft.auth.type === 'key' ? 'bearer' : 'none';
    if (['api_key', 'bearer', 'basic', 'oauth2'].includes(draft.auth.type)) return draft.auth.type;
    return draft.auth.type === 'key' && draft.auth.key ? 'api_key' : 'none';
}

export function connectorSecretField(draft: ActionConfiguration, kind: ApiConnector): string {
    if (kind === 'openapi') {
        if (draft.auth.type === 'api_key') return 'value';
        if (['bearer', 'oauth2'].includes(draft.auth.type)) return 'token';
        if (draft.auth.type === 'basic' && Object.hasOwn(draft.auth, 'password')) return 'password';
    }
    return 'key';
}

export function changeConnectorAuthMethod(
    draft: ActionConfiguration, kind: ApiConnector, method: string,
): ActionConfiguration {
    const choices = kind === 'openapi' ? OPENAPI_AUTH_OPTIONS : MCP_AUTH_OPTIONS;
    if (!choices.some(({ value }) => value === method)) throw new Error('Unsupported authentication method.');
    const auth: ActionConfiguration['auth'] = {
        ...draft.auth,
        type: method === 'identity' ? 'identity' : kind === 'mcp' && method === 'none' ? 'NoAuth' : 'key',
    };
    // OpenAPI's V1 "none" manifest still uses type=key; legacy aliases must not supply a fallback.
    if (kind === 'openapi' && method === 'none') {
        auth.key = '';
        for (const field of ['value', 'token', 'password']) {
            if (Object.hasOwn(auth, field)) auth[field] = '';
        }
    }
    if (method !== 'none' && method !== 'identity' && !Object.hasOwn(auth, 'key')) auth.key = '';
    return {
        ...draft,
        auth,
        additionalFields: {
            ...draft.additionalFields,
            auth_method: method,
            ...(method === 'api_key' && kind === 'openapi' ? {
                api_key_location: draft.additionalFields.api_key_location ?? draft.auth.location ?? 'header',
                api_key_name: draft.additionalFields.api_key_name ?? draft.auth.name ?? 'X-API-Key',
            } : {}),
            ...(method === 'api_key' && kind === 'mcp' ? {
                api_key_header_name: draft.additionalFields.api_key_header_name ?? 'X-API-Key',
            } : {}),
        },
    };
}

export function availableConnectorIdentities(identities: ActionIdentity[], kind: ApiConnector): ActionIdentity[] {
    const allowed = kind === 'mcp'
        ? ['api_key', 'bearer_token', 'username_password', 'managed_identity']
        : ['api_key', 'bearer_token', 'username_password'];
    return identities.filter((identity) => identity.id && allowed.includes(identity.auth_type.toLowerCase()));
}

export function connectorIdentityOptions(
    identities: ActionIdentity[], kind: ApiConnector, selectedId: string,
): { identities: ActionIdentity[]; unavailable: boolean } {
    const available = availableConnectorIdentities(identities, kind);
    return { identities: available, unavailable: Boolean(selectedId && !available.some(({ id }) => id === selectedId)) };
}

export function selectConnectorIdentity(
    draft: ActionConfiguration, kind: ApiConnector, identity: ActionIdentity | null,
): ActionConfiguration {
    if (identity) {
        if (!availableConnectorIdentities([identity], kind).length) throw new Error('This identity cannot authenticate this connector.');
        return {
            ...draft,
            identity_id: identity.id,
            auth: { ...draft.auth, type: 'identity', identity: identity.id },
            additionalFields: {
                ...draft.additionalFields, auth_method: 'identity',
                identity_auth_type: identity.auth_type.toLowerCase(),
                ...(kind === 'openapi' && identity.auth_type.toLowerCase() === 'api_key' ? {
                    api_key_location: draft.additionalFields.api_key_location ?? draft.auth.location ?? 'header',
                    api_key_name: draft.additionalFields.api_key_name ?? draft.auth.name ?? 'X-API-Key',
                } : {}),
            },
        };
    }
    const next = changeConnectorAuthMethod(draft, kind, 'none');
    const additionalFields = { ...next.additionalFields };
    delete additionalFields.identity_auth_type;
    return { ...next, identity_id: '', additionalFields };
}

export function openApiBasicCredentials(draft: ActionConfiguration): { username: string; password: string; stored: boolean } {
    if (draft.auth.type === 'basic' && Object.hasOwn(draft.auth, 'password')) {
        return {
            username: connectorText(draft.auth.username ?? draft.auth.identity),
            password: connectorText(draft.auth.password),
            stored: draft.auth.password === EDITOR_SECRET_MASK,
        };
    }
    const key = connectorText(draft.auth.key);
    if ([EDITOR_SECRET_MASK, STORED_CONNECTOR_SECRET].includes(key)) {
        return { username: '', password: key, stored: true };
    }
    const separator = key.indexOf(':');
    return {
        username: separator < 0 ? '' : key.slice(0, separator),
        password: separator < 0 ? '' : key.slice(separator + 1),
        stored: false,
    };
}

export function changeOpenApiBasicCredential(
    draft: ActionConfiguration, part: 'username' | 'password', value: string,
): ActionConfiguration {
    if (draft.auth.type === 'basic' && Object.hasOwn(draft.auth, 'password')) {
        return { ...draft, auth: { ...draft.auth, [part]: value } };
    }
    if (part === 'password' && (value === EDITOR_SECRET_MASK || value === '')) {
        return { ...draft, auth: { ...draft.auth, key: value } };
    }
    const current = openApiBasicCredentials(draft);
    const username = part === 'username' ? value : current.username;
    const password = part === 'password' ? value : current.stored ? '' : current.password;
    return { ...draft, auth: { ...draft.auth, key: `${username}:${password}` } };
}

export function connectorUrlError(value: unknown, websocket = false): string | null {
    const text = connectorText(value);
    if (!text.trim()) return 'Enter an endpoint URL.';
    try {
        const url = new URL(text);
        const protocols = websocket ? ['ws:', 'wss:'] : ['http:', 'https:'];
        if (!protocols.includes(url.protocol) || !url.hostname || url.username || url.password || url.hash || /\s/.test(text)) {
            return `Use an absolute ${websocket ? 'ws:// or wss://' : 'http:// or https://'} URL without credentials, spaces, or a fragment.`;
        }
        return null;
    } catch {
        return 'Enter a valid absolute URL.';
    }
}

export interface OpenApiOperation {
    id: string;
    method: string;
    path: string;
    summary: string;
    description: string;
    deprecated: boolean;
    tags: string[];
    parameters: { name: string; location: string; required: boolean; type: string; description: string }[];
    bodyRequired: boolean;
    contentTypes: string[];
    responses: string[];
    security: string[];
}

export interface OpenApiSecurityScheme {
    id: string;
    method: string;
    description: string;
    location: string;
    name: string;
    scopes: string[];
    supported: boolean;
}

export interface OpenApiInformation {
    title: string;
    description: string;
    version: string;
    specificationVersion: string;
    servers: { url: string; description: string }[];
    pathsCount: number;
    operations: OpenApiOperation[];
    securitySchemes: OpenApiSecurityScheme[];
}

function resolveSpecObject(spec: Record<string, unknown>, value: unknown): Record<string, unknown> {
    let current = connectorObject(value);
    const visited = new Set<string>();
    while (typeof current.$ref === 'string' && current.$ref.startsWith('#/')) {
        if (visited.has(current.$ref)) break;
        visited.add(current.$ref);
        let target: unknown = spec;
        for (const encoded of current.$ref.slice(2).split('/')) {
            const key = encoded.replace(/~1/g, '/').replace(/~0/g, '~');
            if (!isRecord(target) || !Object.hasOwn(target, key)) { target = undefined; break; }
            target = target[key];
        }
        if (!isRecord(target)) break;
        current = target;
    }
    return current;
}

export function openApiInformation(value: unknown): OpenApiInformation {
    const spec = connectorObject(value);
    const info = connectorObject(spec.info);
    const paths = connectorObject(spec.paths);
    const operations: OpenApiOperation[] = [];
    const methods = new Set(['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace']);
    for (const [path, rawPath] of Object.entries(paths)) {
        const pathItem = resolveSpecObject(spec, rawPath);
        for (const [method, rawOperation] of Object.entries(pathItem)) {
            if (!methods.has(method) || !isRecord(rawOperation)) continue;
            const operation = resolveSpecObject(spec, rawOperation);
            const parameterMap = new Map<string, OpenApiOperation['parameters'][number]>();
            for (const rawParameter of [
                ...(Array.isArray(pathItem.parameters) ? pathItem.parameters : []),
                ...(Array.isArray(operation.parameters) ? operation.parameters : []),
            ]) {
                const parameter = resolveSpecObject(spec, rawParameter);
                const name = connectorText(parameter.name);
                if (!name) continue;
                const location = connectorText(parameter.in);
                const schema = resolveSpecObject(spec, parameter.schema);
                parameterMap.set(`${location}:${name}`, {
                    name, location, required: parameter.required === true,
                    type: connectorText(schema.type ?? parameter.type) || 'value',
                    description: connectorText(parameter.description),
                });
            }
            const body = resolveSpecObject(spec, operation.requestBody);
            const security = operation.security ?? spec.security;
            operations.push({
                id: connectorText(operation.operationId), method: method.toUpperCase(), path,
                summary: connectorText(operation.summary), description: connectorText(operation.description),
                deprecated: operation.deprecated === true, tags: connectorStrings(operation.tags),
                parameters: [...parameterMap.values()], bodyRequired: body.required === true,
                contentTypes: Object.keys(connectorObject(body.content)),
                responses: Object.keys(connectorObject(operation.responses)),
                security: Array.isArray(security) ? security.flatMap((entry) => Object.keys(connectorObject(entry))) : [],
            });
        }
    }
    const securitySchemes = Object.entries(
        connectorObject(connectorObject(spec.components).securitySchemes ?? spec.securityDefinitions),
    ).map(([id, value]): OpenApiSecurityScheme => {
        const scheme = resolveSpecObject(spec, value);
        const type = connectorText(scheme.type).toLowerCase();
        const method = type === 'apikey' ? 'api_key' : type === 'http' ? connectorText(scheme.scheme).toLowerCase() : type;
        const location = connectorText(scheme.in) || 'header';
        const scopes = Object.values(connectorObject(scheme.flows))
            .flatMap((flow) => Object.keys(connectorObject(connectorObject(flow).scopes)));
        return {
            id, method, location, name: connectorText(scheme.name),
            description: connectorText(scheme.description), scopes: [...new Set(scopes)],
            supported: OPENAPI_AUTH_OPTIONS.some(({ value }) => value === method) &&
                (method !== 'api_key' || ['header', 'query'].includes(location)),
        };
    });
    const servers = (Array.isArray(spec.servers) ? spec.servers : []).filter(isRecord).map((server) => ({
        url: connectorText(server.url).replace(/\{([^}]+)\}/g, (match, name: string) => {
            const replacement = connectorObject(connectorObject(server.variables)[name]).default;
            return typeof replacement === 'string' ? replacement : match;
        }),
        description: connectorText(server.description),
    }));
    if (!servers.length && typeof spec.host === 'string') {
        servers.push({ url: `${connectorStrings(spec.schemes)[0] ?? 'https'}://${spec.host}${connectorText(spec.basePath)}`, description: '' });
    }
    return {
        title: connectorText(info.title), version: connectorText(info.version),
        description: connectorText(info.description),
        specificationVersion: connectorText(spec.openapi ?? spec.swagger),
        servers, pathsCount: Object.keys(paths).length, operations, securitySchemes,
    };
}

export interface OpenApiUploadResult {
    success: boolean;
    file_id?: string;
    original_filename?: string;
    spec_content: Record<string, unknown>;
    spec_info?: Record<string, unknown>;
    authentication?: Record<string, unknown>;
    warnings?: string[];
    error?: string;
}

export interface OpenApiSourceDraft {
    mode: (typeof OPENAPI_SOURCE_OPTIONS)[number]['value'];
    format: 'json' | 'yaml';
    text: string;
    pending: boolean;
    filename?: string;
}

export function openApiSourceDraft(draft: ActionConfiguration): OpenApiSourceDraft {
    const source = connectorObject(draft._openApiSourceDraft);
    return {
        mode: source.mode === 'manual' ? 'manual' : 'file',
        format: source.format === 'yaml' ? 'yaml' : 'json',
        text: typeof source.text === 'string' ? source.text : JSON.stringify(draft.additionalFields.openapi_spec_content ?? {}, null, 2),
        pending: source.pending === true,
        filename: connectorText(source.filename),
    };
}

export function updateOpenApiSourceDraft(
    draft: ActionConfiguration, updates: Partial<OpenApiSourceDraft>,
): ActionConfiguration {
    // Draft-only source text survives section changes; shared editor writes omit root _ fields.
    return { ...draft, _openApiSourceDraft: { ...openApiSourceDraft(draft), ...updates } };
}

export async function uploadOpenApiSpecification(file: File | Blob, filename?: string, signal?: AbortSignal): Promise<OpenApiUploadResult> {
    const name = filename || (file instanceof File ? file.name : 'openapi.json');
    if (!/\.(json|ya?ml)$/i.test(name)) throw new Error('Choose a .json, .yaml, or .yml specification.');
    if (file.size > 5 * 1024 * 1024) throw new Error('OpenAPI specifications must be 5 MB or smaller.');
    if (!file.size) throw new Error('The specification is empty.');
    const formData = new FormData();
    formData.append('file', file, name);
    const result = await uploadFile<OpenApiUploadResult>('/api/openapi/upload', formData, signal);
    if (!result || result.success !== true || !isRecord(result.spec_content)) {
        throw new Error(result?.error || 'The server did not return a validated OpenAPI specification.');
    }
    return { ...result, warnings: connectorStrings(result.warnings) };
}

export function processOpenApiText(text: string, format: 'json' | 'yaml', signal?: AbortSignal): Promise<OpenApiUploadResult> {
    return uploadOpenApiSpecification(
        new Blob([text], { type: format === 'json' ? 'application/json' : 'application/yaml' }),
        `openapi.${format}`, signal,
    );
}

export function applyOpenApiSpecification(draft: ActionConfiguration, result: OpenApiUploadResult): ActionConfiguration {
    if (!result.success || !isRecord(result.spec_content)) throw new Error('A validated specification is required.');
    const information = openApiInformation(result.spec_content);
    const source = openApiSourceDraft(draft);
    const endpoint = draft.endpoint || connectorText(draft.additionalFields.base_url) ||
        information.servers.find(({ url }) => !connectorUrlError(url))?.url || '';
    return {
        ...draft, endpoint,
        additionalFields: {
            ...draft.additionalFields,
            openapi_spec_content: result.spec_content, openapi_source_type: 'content', base_url: endpoint,
        },
        _openApiSourceDraft: {
            ...source, pending: false,
            text: JSON.stringify(result.spec_content, null, 2), format: 'json',
            filename: result.original_filename || '',
        },
    };
}

export interface McpCatalogEntry {
    id: string;
    displayName: string;
    description: string;
    defaults: Record<string, unknown>;
    constraints: Record<string, unknown>;
    ui: Record<string, unknown>;
    warnings: string[];
    implementation: Record<string, unknown>;
    additionalSettings: Record<string, unknown>;
    endpoint?: string;
    transport?: string;
    presetId?: string;
    scopeEligibility?: string[];
    requiredGovernanceGates?: string[];
    operatorNotes?: string[];
    authRequirement?: string;
    riskLabel?: string;
    catalogTier?: string;
    documentationUrl?: string;
}

export const MCP_GENERIC_PRESET: McpCatalogEntry = {
    id: 'generic', displayName: 'Generic MCP server',
    description: 'Standards-compliant MCP server.',
    defaults: MCP_DEFAULT_FIELDS, constraints: {}, ui: {}, warnings: [],
    implementation: { id: 'generic', schemaVersion: '1.0.0' },
    additionalSettings: { compatibilityProfile: 'standards_compliant' },
};

export function parseMcpCatalogue(payload: unknown, key: 'presets' | 'preconfigurations'): McpCatalogEntry[] {
    let records: unknown = payload;
    if (isRecord(records)) records = records[key] ?? connectorObject(records.data)[key] ?? records.data;
    if (!Array.isArray(records)) throw new Error(`The server returned an invalid MCP ${key} catalogue.`);
    const entries: McpCatalogEntry[] = records.map((value) => {
        if (!isRecord(value) || !connectorText(value.id)) throw new Error(`The MCP ${key} catalogue contains an invalid entry.`);
        return {
            ...value, id: connectorText(value.id), displayName: connectorText(value.displayName) || connectorText(value.id),
            description: connectorText(value.description), defaults: connectorObject(value.defaults),
            constraints: connectorObject(value.constraints), ui: connectorObject(value.ui),
            implementation: connectorObject(value.implementation), additionalSettings: connectorObject(value.additionalSettings),
            warnings: connectorStrings(value.warnings), endpoint: typeof value.endpoint === 'string' ? value.endpoint : undefined,
            transport: typeof value.transport === 'string' ? value.transport : undefined,
            presetId: typeof value.presetId === 'string' ? value.presetId : undefined,
            scopeEligibility: Array.isArray(value.scopeEligibility) ? connectorStrings(value.scopeEligibility) : undefined,
            requiredGovernanceGates: connectorStrings(value.requiredGovernanceGates),
            operatorNotes: connectorStrings(value.operatorNotes),
            authRequirement: connectorText(value.authRequirement), riskLabel: connectorText(value.riskLabel),
            catalogTier: connectorText(value.catalogTier), documentationUrl: connectorText(value.documentationUrl),
        };
    });
    if (new Set(entries.map(({ id }) => id)).size !== entries.length) throw new Error(`The MCP ${key} catalogue contains duplicate identifiers.`);
    return entries;
}

export async function fetchMcpPresets(signal?: AbortSignal): Promise<McpCatalogEntry[]> {
    return parseMcpCatalogue(await api.get<unknown>('/api/plugins/mcp/presets', signal), 'presets');
}

export async function fetchMcpPreconfigurations(signal?: AbortSignal): Promise<McpCatalogEntry[]> {
    return parseMcpCatalogue(await api.get<unknown>('/api/plugins/mcp/preconfigurations?scope=personal', signal), 'preconfigurations');
}

export function allowedMcpTransports(preset?: McpCatalogEntry): ConnectorOption[] {
    const allowed = connectorStrings(preset?.constraints.allowedTransports);
    return MCP_PERSONAL_TRANSPORTS.filter(({ value }) => !allowed.length || allowed.includes(value));
}

export function allowedMcpAuthMethods(transport: string, preset?: McpCatalogEntry): ConnectorOption[] {
    const allowed = connectorStrings(preset?.constraints.allowedAuthMethods);
    return MCP_AUTH_OPTIONS.filter(({ value }) =>
        (transport !== 'websocket' || value === 'none') && (!allowed.length || allowed.includes(value)));
}

export interface McpImplementationField {
    key: string;
    label: string;
    kind: 'fixed' | 'select' | 'multi' | 'lines';
    options?: ConnectorOption[];
    expected?: string | boolean;
    help?: string;
    optional?: boolean;
}

const options = (...values: string[]): ConnectorOption[] => values.map((value) => ({
    value, label: value.replaceAll('_', ' '),
}));
const fixed = (key: string, label: string, expected: string | boolean, help?: string): McpImplementationField =>
    ({ key, label, expected, help, kind: 'fixed' });
const implementationFields: Record<string, McpImplementationField[]> = {
    generic: [fixed('compatibilityProfile', 'Compatibility profile', 'standards_compliant')],
    splunk: [
        fixed('compatibilityProfile', 'Compatibility profile', 'splunk_mcp'),
        fixed('credentialMode', 'Credential handling', 'scoped_test_or_workspace_identity'),
        fixed('customHeaderValueHandling', 'Custom header values', 'secret'),
        fixed('preferredTransport', 'Preferred transport', 'streamable_http'),
    ],
    microsoft_learn: [
        { key: 'contentFocus', label: 'Documentation focus', kind: 'select', options: options('all_microsoft', 'azure') },
        fixed('publicDocumentationOnly', 'Public documentation only', true),
        { key: 'preferredTools', label: 'Preferred documentation tools', kind: 'multi', options: options('microsoft_docs_search', 'microsoft_docs_fetch', 'microsoft_code_sample_search') },
    ],
    github: [
        fixed('hostedServer', 'Hosted GitHub server', true),
        fixed('permissionModel', 'Permission model', 'supplied_identity_permissions'),
        fixed('recommendedCredentialHandling', 'Credential guidance', 'least_privilege_pat_or_identity'),
        { ...fixed('defaultRepositoryScope', 'Repository scope', 'user_selected'), optional: true },
    ],
    microsoft_sentinel: [
        fixed('dataSensitivity', 'Data sensitivity', 'high'),
        fixed('defaultAccessMode', 'Access mode', 'read_only'),
        { key: 'requiredProducts', label: 'Required products', kind: 'multi', options: options('microsoft_sentinel_data_lake', 'microsoft_defender', 'microsoft_security_copilot_optional') },
        { key: 'toolCollections', label: 'Tool collections', kind: 'multi', options: options('incidents_read', 'alerts_read', 'entities_read', 'hunting_read') },
    ],
    azure_mcp_server: [
        fixed('defaultAccessMode', 'Access mode', 'read_only'),
        fixed('localCommandExecution', 'Local command execution', false),
        fixed('organizationHostedRemoteRequired', 'Organization-hosted remote endpoint required', true),
        { key: 'serviceNamespaces', label: 'Azure service namespaces', kind: 'lines', help: 'One namespace per line, for example Azure.ResourceGroups. Keep this list limited to the services the agent needs.' },
    ],
    simplechat_local_dev: [
        fixed('fixtureType', 'Fixture type', 'simplechat_local_mcp'),
        fixed('intendedEnvironment', 'Intended environment', 'development'),
        fixed('loopbackOnly', 'Loopback only', true),
    ],
};

export function mcpImplementationFields(id: string): McpImplementationField[] {
    return Object.hasOwn(implementationFields, id) ? implementationFields[id] : [];
}

function mergeConnectorObjects(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries([...new Set([...Object.keys(before), ...Object.keys(after)])].map((key) => {
        if (!Object.hasOwn(after, key) || before[key] === EDITOR_SECRET_MASK || before[key] === STORED_CONNECTOR_SECRET) return [key, before[key]];
        if (isRecord(before[key]) && isRecord(after[key])) return [key, mergeConnectorObjects(before[key], after[key])];
        return [key, after[key]];
    }));
}

function applyMcpImplementation(fields: Record<string, unknown>, entry: McpCatalogEntry): Record<string, unknown> {
    if (!Object.keys(entry.implementation).length) return fields;
    const previousImplementation = connectorObject(fields.implementation);
    const changingImplementation = previousImplementation.id !== entry.implementation.id;
    const oldKnownKeys = new Set(mcpImplementationFields(connectorText(previousImplementation.id)).map(({ key }) => key));
    const previousSettings = Object.fromEntries(Object.entries(connectorObject(fields.additionalSettings))
        .filter(([key]) => !changingImplementation || !oldKnownKeys.has(key) || Object.hasOwn(entry.additionalSettings, key)));
    return {
        ...fields,
        implementation: { ...previousImplementation, ...entry.implementation },
        additionalSettings: mergeConnectorObjects(previousSettings, entry.additionalSettings),
    };
}

export function applyMcpPreset(draft: ActionConfiguration, preset: McpCatalogEntry): ActionConfiguration {
    const transports = allowedMcpTransports(preset);
    if (!transports.length) throw new Error('This preset has no transport permitted in a personal workspace.');
    const defaults = { ...MCP_DEFAULT_FIELDS, ...preset.defaults };
    const preferredTransport = connectorText(defaults.transport);
    const transport = transports.some(({ value }) => value === preferredTransport) ? preferredTransport : transports[0].value;
    let fields = mergeConnectorObjects(draft.additionalFields, {
        ...defaults, server_profile: preset.id, transport,
        allowed_tool_names: [...new Set([
            ...connectorStrings(draft.additionalFields.allowed_tool_names),
            ...connectorStrings(defaults.allowed_tool_names),
        ])],
    });
    fields = applyMcpImplementation(fields, preset);
    const next = { ...draft, additionalFields: fields };
    return draft.identity_id ? {
        ...next, additionalFields: { ...fields, auth_method: 'identity' },
    } : changeConnectorAuthMethod(next, 'mcp', connectorText(defaults.auth_method) || 'none');
}

export function applyMcpPreconfiguration(
    draft: ActionConfiguration, entry: McpCatalogEntry, preset = MCP_GENERIC_PRESET,
): ActionConfiguration {
    if (entry.scopeEligibility?.length && !entry.scopeEligibility.includes('personal')) {
        throw new Error('This preconfiguration is not available in a personal workspace.');
    }
    if (entry.transport === 'stdio') throw new Error('Personal actions cannot use stdio.');
    let next = applyMcpPreset(draft, preset);
    let fields = mergeConnectorObjects(next.additionalFields, {
        ...entry.defaults, preconfiguration_id: entry.id, server_profile: entry.presetId ?? preset.id,
        ...(entry.transport !== undefined ? { transport: entry.transport } : {}),
        allowed_tool_names: [...new Set([
            ...connectorStrings(draft.additionalFields.allowed_tool_names),
            ...connectorStrings(entry.defaults.allowed_tool_names),
        ])],
    });
    fields = applyMcpImplementation(fields, entry);
    next = {
        ...next, additionalFields: fields, endpoint: entry.endpoint ?? next.endpoint,
        displayName: draft.displayName || entry.displayName, description: draft.description || entry.description,
    };
    return draft.identity_id ? {
        ...next, additionalFields: { ...fields, auth_method: 'identity' },
    } : changeConnectorAuthMethod(next, 'mcp', connectorText(fields.auth_method) || 'none');
}

const headerNamePattern = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const reservedHeaders = new Set([
    'connection', 'content-length', 'cookie', 'host', 'keep-alive', 'proxy-authenticate',
    'proxy-authorization', 'set-cookie', 'te', 'trailer', 'transfer-encoding', 'upgrade',
]);

export function mcpHeaderNameError(name: string, headers: Record<string, unknown> = {}, previousName?: string): string | null {
    if (!headerNamePattern.test(name) || reservedHeaders.has(name.toLowerCase())) return 'Use a valid, non-reserved HTTP header name.';
    if (Object.keys(headers).some((key) => key !== previousName && key.toLowerCase() === name.toLowerCase())) return 'A header with this name already exists.';
    return null;
}

export function renameMcpHeader(draft: ActionConfiguration, before: string, after: string): ActionConfiguration {
    const headers = connectorObject(draft.additionalFields.custom_headers);
    const error = mcpHeaderNameError(after, headers, before);
    if (error) throw new Error(error);
    if (before !== after && [EDITOR_SECRET_MASK, STORED_CONNECTOR_SECRET].includes(connectorText(headers[before]))) {
        throw new Error('Replace the stored header value before renaming its header.');
    }
    return updateConnectorFields(draft, {
        custom_headers: Object.fromEntries(Object.entries(headers).map(([name, value]) => [name === before ? after : name, value])),
    });
}

export interface McpTool extends Record<string, unknown> {
    original_name: string;
    function_name: string;
    description?: string;
    input_schema?: Record<string, unknown>;
    output_schema?: Record<string, unknown>;
    annotations?: Record<string, unknown>;
}

export function parseMcpTools(value: unknown): McpTool[] {
    if (!Array.isArray(value)) return [];
    return value.filter(isRecord).flatMap((tool) => {
        const name = connectorText(tool.original_name ?? tool.name);
        return name ? [{
            ...tool, original_name: name, function_name: connectorText(tool.function_name) || name,
            description: connectorText(tool.description),
            input_schema: connectorObject(tool.input_schema ?? tool.inputSchema),
            output_schema: connectorObject(tool.output_schema ?? tool.outputSchema),
            annotations: connectorObject(tool.annotations),
        }] : [];
    });
}

export function mergeMcpTools(previous: unknown, discovered: unknown, selected: string[]): McpTool[] {
    const old = new Map(parseMcpTools(previous).map((tool) => [tool.original_name, tool]));
    const next = new Map(parseMcpTools(discovered).map((tool) => [
        tool.original_name,
        { ...old.get(tool.original_name), ...tool } as McpTool,
    ]));
    for (const name of selected) {
        const prior = old.get(name);
        if (!next.has(name) && prior) next.set(name, prior);
    }
    return [...next.values()];
}

export function mcpToolChoices(tools: unknown, selected: unknown, discoveredNames?: string[]): {
    name: string; tool?: McpTool; selected: boolean; unavailable: boolean;
}[] {
    const catalogue = new Map(parseMcpTools(tools).map((tool) => [tool.original_name, tool]));
    const names = connectorStrings(selected);
    const available = discoveredNames ? new Set(discoveredNames) : null;
    return [...new Set([...names, ...catalogue.keys()])].map((name) => ({
        name, tool: catalogue.get(name), selected: names.includes(name),
        unavailable: available ? !available.has(name) : !catalogue.has(name),
    }));
}

export function setMcpToolSelection(draft: ActionConfiguration, name: string, selected: boolean): ActionConfiguration {
    const current = connectorStrings(draft.additionalFields.allowed_tool_names);
    return updateConnectorFields(draft, {
        allowed_tool_names: selected ? [...new Set([...current, name])] : current.filter((item) => item !== name),
    });
}

function pointerValue(value: unknown, pointer: string): unknown {
    let current = value;
    for (const part of pointer.slice(1).split('/')) {
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        if (Array.isArray(current) && /^(0|[1-9][0-9]*)$/.test(key)) {
            current = current[Number(key)];
            continue;
        }
        if (!isRecord(current) || !Object.hasOwn(current, key)) return undefined;
        current = current[key];
    }
    return current;
}

function supportedSecret(value: unknown, path: string, original: ConnectorResource): boolean {
    if (value === EDITOR_SECRET_MASK || value === STORED_CONNECTOR_SECRET) {
        return Boolean(original && !original.read_only && original.secret_paths.includes(path) &&
            [EDITOR_SECRET_MASK, STORED_CONNECTOR_SECRET].includes(connectorText(pointerValue(original.record, path))));
    }
    return typeof value === 'string' && Boolean(value.trim());
}

export function validateConnectorAuthentication(
    draft: ActionConfiguration, kind: ApiConnector, original: ConnectorResource,
): Record<string, string> {
    const errors: Record<string, string> = {};
    const method = connectorAuthMethod(draft, kind);
    if (kind === 'openapi' && (method === 'api_key' ||
        method === 'identity' && draft.additionalFields.identity_auth_type === 'api_key')) {
        const location = connectorText(draft.additionalFields.api_key_location ?? draft.auth.location ?? 'header');
        const name = connectorText(draft.additionalFields.api_key_name ?? draft.auth.name ?? 'X-API-Key');
        if (!['header', 'query'].includes(location)) errors['additionalFields.api_key_location'] = 'API keys support a header or query parameter.';
        if (!name.trim() || (location === 'header' && !headerNamePattern.test(name))) errors['additionalFields.api_key_name'] = 'Enter a valid API key header or query parameter name.';
    }
    if (method === 'identity') {
        if (!draft.identity_id) errors.identity_id = 'Choose a reusable identity.';
        if (kind === 'mcp' && draft.additionalFields.identity_auth_type === 'api_key') {
            const error = mcpHeaderNameError(connectorText(draft.additionalFields.api_key_header_name ?? 'X-API-Key'));
            if (error) errors['additionalFields.api_key_header_name'] = error;
        }
        return errors;
    }
    const supported = kind === 'openapi' ? OPENAPI_AUTH_OPTIONS : MCP_AUTH_OPTIONS;
    if (!supported.some(({ value }) => value === method)) errors['additionalFields.auth_method'] = 'Choose a supported authentication method.';
    if (method === 'none') return errors;
    const field = connectorSecretField(draft, kind);
    if (!supportedSecret(draft.auth[field], `/auth/${field}`, original)) {
        errors[`auth.${field}`] = 'Enter a credential, or explicitly keep the stored credential. Cleared credentials cannot be used for a test.';
    }
    if (kind === 'openapi' && method === 'basic') {
        const pair = openApiBasicCredentials(draft);
        if (draft.auth.type === 'basic' && !supportedSecret(draft.auth.username ?? draft.auth.identity,
            Object.hasOwn(draft.auth, 'username') ? '/auth/username' : '/auth/identity', original)) {
            errors['auth.basic_username'] = 'Enter a username, or keep its stored value.';
        }
        if (!pair.stored) {
            if (!pair.username) errors['auth.basic_username'] = 'Enter a username. Replacing stored basic credentials requires both values.';
            if (!pair.password) errors[`auth.${field}`] = 'Enter a password. Replacing stored basic credentials requires both values.';
            if (pair.username.includes(':')) errors['auth.basic_username'] = 'Basic authentication usernames cannot contain a colon.';
        }
    }
    if (kind === 'mcp' && method === 'basic' && !supportedSecret(draft.auth.identity, '/auth/identity', original)) {
        errors['auth.identity'] = 'Enter the username, or keep its stored value.';
    }
    if (method === 'api_key' && kind === 'mcp') {
        const name = connectorText(draft.additionalFields.api_key_header_name ?? 'X-API-Key');
        const error = mcpHeaderNameError(name);
        if (error) errors['additionalFields.api_key_header_name'] = error;
    }
    return errors;
}

export function validateConnectorConfiguration(
    draft: ActionConfiguration, kind: ApiConnector, preset?: McpCatalogEntry,
): Record<string, string> {
    const errors: Record<string, string> = {};
    const fields = draft.additionalFields;
    const transport = connectorText(fields.transport) || 'streamable_http';
    const endpointError = connectorUrlError(draft.endpoint || (kind === 'openapi' ? fields.base_url : ''), kind === 'mcp' && transport === 'websocket');
    if (endpointError) errors.endpoint = endpointError;
    if (kind === 'openapi') {
        if (!isRecord(fields.openapi_spec_content) || !Object.keys(fields.openapi_spec_content).length) {
            errors['additionalFields.openapi_spec_content'] = 'Upload or process an OpenAPI JSON/YAML specification.';
        }
        if (connectorObject(draft._openApiSourceDraft).pending === true) errors['openapi-source'] = 'Process the edited specification before saving or testing.';
        return errors;
    }
    if (!allowedMcpTransports(preset).some(({ value }) => value === transport)) {
        errors['additionalFields.transport'] = transport === 'stdio'
            ? 'Stdio is only available for admin-managed global actions. Select a remote transport.'
            : 'Select a personal-workspace transport supported by this preset.';
    }
    for (const field of MCP_NUMBER_FIELDS) {
        const value = fields[field.key] ?? field.defaultValue;
        if (typeof value !== 'number' || !Number.isInteger(value) || value < field.min || value > field.max) {
            errors[`additionalFields.${field.key}`] = `Enter a whole number from ${field.min} to ${field.max}.`;
        }
    }
    for (const key of ['load_tools', 'load_prompts', 'validate_tool_arguments']) {
        if (fields[key] !== undefined && typeof fields[key] !== 'boolean') {
            errors[`additionalFields.${key}`] = 'Choose an enabled or disabled value.';
        }
    }
    if (fields.allowed_tool_names !== undefined &&
        (!Array.isArray(fields.allowed_tool_names) || connectorStrings(fields.allowed_tool_names).length !== fields.allowed_tool_names.length)) {
        errors['additionalFields.allowed_tool_names'] = 'Allowed tool names must be an array of strings.';
    }
    if (fields.mcp_tools !== undefined && (!Array.isArray(fields.mcp_tools) || fields.mcp_tools.some((tool) =>
        !isRecord(tool) || !connectorText(tool.original_name) || !connectorText(tool.function_name)))) {
        errors['additionalFields.mcp_tools'] = 'Tool metadata must be an array containing original_name and function_name for every tool.';
    }
    const headers = connectorObject(fields.custom_headers);
    if (fields.custom_headers !== undefined && !isRecord(fields.custom_headers)) errors['additionalFields.custom_headers'] = 'Custom headers must be an object.';
    if (Object.keys(headers).length > 20) errors['additionalFields.custom_headers'] = 'Use at most 20 custom headers.';
    for (const [name, value] of Object.entries(headers)) {
        const error = mcpHeaderNameError(name, headers, name);
        if (error) errors[`additionalFields.custom_headers.${name}`] = error;
        if (typeof value !== 'string' || /[\r\n]/.test(value) || value.length > 4096) {
            errors[`additionalFields.custom_headers.${name}`] = 'Header values must be strings without line breaks, at most 4096 characters.';
        }
    }
    const hasHeaders = Object.values(headers).some((value) => value !== '' && value != null);
    if (hasHeaders && (transport === 'websocket' || preset?.constraints.customHeadersAllowed === false)) {
        errors['additionalFields.custom_headers'] = 'This transport or preset does not support custom headers. Remove them explicitly, or change the transport/preset.';
    }
    const method = connectorAuthMethod(draft, 'mcp');
    if (transport === 'websocket' && method !== 'none') errors['additionalFields.auth_method'] = 'The WebSocket connector does not support authentication headers.';
    if (method !== 'identity' && !allowedMcpAuthMethods(transport, preset).some(({ value }) => value === method)) {
        errors['additionalFields.auth_method'] = 'The selected authentication method is not supported by this preset.';
    }
    if (!['truncate', 'error_on_limit'].includes(connectorText(fields.tool_result_policy ?? 'truncate'))) {
        errors['additionalFields.tool_result_policy'] = 'Choose a supported large-result policy.';
    }
    const implementationId = connectorText(connectorObject(fields.implementation).id);
    const settings = connectorObject(fields.additionalSettings);
    for (const field of mcpImplementationFields(implementationId)) {
        const value = settings[field.key];
        if (field.optional && value === undefined) continue;
        if (field.kind === 'fixed' && value !== field.expected) errors[`additionalFields.additionalSettings.${field.key}`] = `This implementation requires ${String(field.expected)}.`;
        if (field.kind === 'select' && !field.options?.some((option) => option.value === value)) {
            errors[`additionalFields.additionalSettings.${field.key}`] = 'Choose a supported implementation setting.';
        }
        if (field.kind === 'multi' || field.kind === 'lines') {
            const values = connectorStrings(value);
            if (!Array.isArray(value) || values.length !== value.length || !values.length || values.length > (field.kind === 'lines' ? 50 : 20)) {
                errors[`additionalFields.additionalSettings.${field.key}`] = 'Provide at least one valid entry within the implementation limit.';
            } else if (field.options && values.some((item) => !field.options?.some(({ value }) => value === item))) {
                errors[`additionalFields.additionalSettings.${field.key}`] = 'Review unavailable implementation selections.';
            } else if (field.kind === 'lines' && values.some((item) => !/^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/.test(item))) {
                errors[`additionalFields.additionalSettings.${field.key}`] = 'Namespaces must contain letters, numbers, dots, underscores, or hyphens (maximum 81 characters).';
            }
        }
    }
    return errors;
}

export interface ConnectorFeedback {
    success: boolean;
    message: string;
    errors: string[];
    warnings: string[];
    details: Record<string, unknown>;
}

export function connectorFeedback(value: unknown): ConnectorFeedback {
    const response = value instanceof ApiError ? connectorObject(value.payload) : connectorObject(value);
    const success = !(value instanceof Error) && (response.success === true || response.valid === true);
    const messages = Array.isArray(response.errors)
        ? response.errors.map((item) => typeof item === 'string' ? item : connectorText(connectorObject(item).message)).filter(Boolean)
        : [];
    return {
        success,
        message: connectorText(response.error ?? response.message) ||
            (value instanceof Error ? value.message : success ? 'Validation passed.' : 'The request did not succeed.'),
        errors: messages, warnings: connectorStrings(response.warnings), details: connectorObject(response.details),
    };
}

export function buildConnectorSupportPayload(
    draft: ActionConfiguration, original: ConnectorResource, kind: ApiConnector,
    purpose: 'test' | 'discover' | 'validate' = 'test',
): Record<string, unknown> {
    if (original?.read_only || draft.is_global || draft.is_group) throw new Error('Provided actions are read-only and cannot be tested.');
    if (original && !connectorText(original.record.id).trim()) throw new Error('Reload this action before testing: its stable owned ID is missing.');
    const errors = {
        ...validateConnectorConfiguration(draft, kind),
        ...validateConnectorAuthentication(draft, kind, original),
    };
    if (Object.keys(errors).length) throw new Error(Object.values(errors).join(' '));
    const clearPaths = new Set(buildEditorWrite(draft, original).clear_secret_paths);
    const translate = (value: unknown, path = ''): unknown => {
        if (value === EDITOR_SECRET_MASK || value === STORED_CONNECTOR_SECRET) {
            if (!original?.secret_paths.includes(path)) {
                // Literal masks in descriptions are ordinary text, not credential references.
                if (/^\/auth\/|^\/additionalFields\/custom_headers\//.test(path) ||
                    /key|secret|password|token|credential|connection/i.test(path.split('/').at(-1) ?? '')) {
                    throw new Error('A stored credential has no owned record to resolve it from.');
                }
                return value;
            }
            if (!supportedSecret(value, path, original)) throw new Error('The stored credential cannot be resolved from this action.');
            return STORED_CONNECTOR_SECRET;
        }
        if (Array.isArray(value)) return value.map((item, index) => translate(item, `${path}/${index}`));
        if (isRecord(value)) return Object.fromEntries(Object.entries(value)
            .filter(([key, item]) => {
                const childPath = `${path}/${pointerPart(key)}`;
                if (clearPaths.has(childPath) || (/^\/additionalFields\/custom_headers$/.test(path) && (item === '' || item == null))) return false;
                return item !== undefined;
            })
            .map(([key, item]) => [key, translate(item, `${path}/${pointerPart(key)}`)]));
        return value;
    };
    const manifest = translate({
        name: draft.name || `${kind}_${purpose}`, displayName: draft.displayName || `${kind.toUpperCase()} ${purpose}`,
        type: draft.type, description: draft.description, endpoint: draft.endpoint || draft.additionalFields.base_url,
        auth: draft.auth, additionalFields: draft.additionalFields, metadata: draft.metadata,
        ...(draft.identity_id ? { identity_id: draft.identity_id } : {}),
    }) as Record<string, unknown>;
    if (connectorAuthMethod(draft, kind) === 'none') {
        // Do not let V1's edit-time empty-value fallback resurrect an inactive credential.
        manifest.auth = { type: kind === 'mcp' ? 'NoAuth' : 'key', ...(kind === 'openapi' ? { key: '' } : {}) };
        for (const key of ['key', 'identity', 'tenantId', 'token', 'value', 'password']) clearPaths.add(`/auth/${key}`);
    } else if (draft.identity_id) {
        manifest.auth = { type: 'identity', identity: draft.identity_id };
    }
    if (kind === 'mcp') {
        manifest.additionalFields = { ...MCP_DEFAULT_FIELDS, ...connectorObject(manifest.additionalFields) };
    }
    return {
        ...manifest,
        ...(purpose !== 'validate' ? {
            action_scope: 'personal',
            ...(original ? { plugin_context: { scope: 'personal', id: original.record.id, name: original.record.name } } : {}),
            clear_secret_paths: [...clearPaths],
        } : {}),
    };
}

export function testApiConnector(draft: ActionConfiguration, original: ConnectorResource, kind: ApiConnector, signal?: AbortSignal): Promise<unknown> {
    const payload = buildConnectorSupportPayload(draft, original, kind);
    return api.post(`/api/plugins/test-${kind}-connection`, payload, signal);
}

export function validateApiConnector(draft: ActionConfiguration, original: ConnectorResource, kind: ApiConnector, signal?: AbortSignal): Promise<unknown> {
    return api.post('/api/plugins/validate', buildConnectorSupportPayload(draft, original, kind, 'validate'), signal);
}

export interface McpDiscoveryResult {
    success?: boolean;
    tools?: unknown[];
    capabilities?: Record<string, unknown>;
    warnings?: string[];
    error?: string;
    errors?: string[];
    transport?: string;
    auth_method?: string;
    mcp_operation_id?: string;
}

export async function discoverMcpAction(draft: ActionConfiguration, original: ConnectorResource, signal?: AbortSignal): Promise<McpDiscoveryResult> {
    const result = await api.post<McpDiscoveryResult>('/api/plugins/mcp/discover', buildConnectorSupportPayload(draft, original, 'mcp', 'discover'), signal);
    if (!result || (result.success === true && (!Array.isArray(result.tools) ||
        parseMcpTools(result.tools).length !== result.tools.length))) {
        throw new Error('The server returned an invalid MCP tool catalogue.');
    }
    return {
        ...result, warnings: connectorStrings(result.warnings), capabilities: connectorObject(result.capabilities),
        ...(Array.isArray(result.tools) ? { tools: parseMcpTools(result.tools) } : {}),
    };
}
