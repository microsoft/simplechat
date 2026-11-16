// OpenApiActionConfiguration.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { GlassButton } from '../ui/primitives';
import { EditorGroup, EditorPanel, EditorRow } from '../workspace/EditorLayout';
import { ActionConnectionCheck, useConnectorRequest } from './ActionConnectionCheck';
import { ActionField, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import { EDITOR_SECRET_MASK, type ActionConfiguration } from '../../lib/workspaceAuthoring';
import {
    applyOpenApiSpecification, changeConnectorAuthMethod, changeOpenApiBasicCredential,
    connectorAuthMethod, connectorIdentityOptions, connectorObject,
    connectorSecretField, connectorStrings, connectorText, connectorUrlError, OPENAPI_AUTH_OPTIONS,
    OPENAPI_SOURCE_OPTIONS, openApiBaseUrlOverrideEnabled, openApiBasicCredentials, openApiInformation, openApiOperationKey,
    openApiSourceDraft, openApiSpecificationBaseUrl, processOpenApiText,
    selectConnectorIdentity, updateConnectorFields, updateOpenApiSourceDraft,
    uploadOpenApiSpecification, validateConnectorAuthentication,
    validateConnectorConfiguration,
    type ApiConnector, type ConnectorFeedback, type OpenApiUploadResult,
} from '../../lib/workspaceActionConnectors';

export { ConnectorFeedbackPanel, useConnectorRequest } from './ActionConnectionCheck';
export { testWorkspaceAction } from '../../lib/workspaceActionServices';

export function useConnectorValidity(props: ActionConnectorProps, key: string, message: string | null) {
    const callback = useRef(props.onValidityChange);
    callback.current = props.onValidityChange;
    const readOnly = props.readOnly || props.original?.read_only;
    useEffect(() => {
        callback.current(key, readOnly ? null : message);
        return () => callback.current(key, null);
    }, [key, message, readOnly]);
}

export function ConnectorIdentitySelect({ kind, ...props }: ActionConnectorProps & { kind: ApiConnector }) {
    const selectedId = props.draft.identity_id || '';
    const { identities, unavailable } = connectorIdentityOptions(props.identities, kind, selectedId);
    const disabled = props.readOnly || props.original?.read_only || props.identitiesLoading;
    const groupScoped = Boolean(props.groupScope);
    // A group member cannot list identities (403): the list is unresolvable, so a bound identity is
    // "kept as is" rather than flagged as replaceable. A manager whose list loaded but lacks the
    // bound id sees the actionable "unavailable" wording, even in group scope.
    const keptAsIs = groupScoped && !props.identitiesResolvable;
    const id = `${kind}-identity`;
    return (
        <div className="space-y-2">
            <ActionField id={id} label="Reusable identity"
                help="An identity is referenced by its stable ID. Its credentials are never copied into this draft."
                error={props.errors.identity_id}>
                <select id={id} className={ACTION_INPUT_CLASS} value={selectedId} disabled={disabled}
                    aria-describedby={`${id}-help ${id}-status`}
                    onChange={(event) => {
                        const next = event.target.value;
                        const identity = identities.find(({ id }) => id === next);
                        if (next && !identity) return;
                        props.onChange((current) => selectConnectorIdentity(current, kind, identity ?? null));
                    }}>
                    <option value="">Use action-specific credentials</option>
                    {unavailable ? <option value={selectedId} disabled>{keptAsIs ? 'Group identity' : 'Unavailable identity'} — {selectedId}</option> : null}
                    {identities.map((identity) => <option key={identity.id} value={identity.id}>
                        {identity.name} · {identity.auth_type.replaceAll('_', ' ')} · {identity.scope_type || 'personal'} · {identity.id}
                    </option>)}
                </select>
            </ActionField>
            <div id={`${id}-status`} className="space-y-1 text-xs text-text-3" aria-live="polite">
                {props.identitiesLoading ? <p>Loading permitted identities…</p> : null}
                {props.identitiesError ? <p role="alert" className="text-danger">{props.identitiesError} The current identity selection has not been changed.</p> : null}
                {!props.identitiesLoading && !props.identitiesError && !identities.length
                    ? <p>No compatible reusable identities are available. Action-specific credentials are still supported.</p> : null}
                {unavailable ? <p className="alert alert-warning rounded-lg bg-warn-soft p-2 text-warn">{keptAsIs
                    ? 'Uses a group identity; kept as is. Its ID is retained; enter action-specific credentials to replace it.'
                    : 'The selected identity is unavailable or incompatible. Its ID is retained; choose a replacement explicitly. A same-name identity will not be substituted.'}</p> : null}
                {selectedId && !unavailable ? <p>{identities.find(({ id }) => id === selectedId)?.description || 'The server resolves this identity when the action runs.'}</p> : null}
            </div>
        </div>
    );
}

function updateOpenApiAllowedOperations(draft: ActionConfiguration, selectedKeys: string[], allKeys: string[]): ActionConfiguration {
    const additionalFields = { ...draft.additionalFields };
    const uniqueKeys = [...new Set(selectedKeys)].filter((key) => allKeys.includes(key));
    if (uniqueKeys.length === allKeys.length) {
        delete additionalFields.allowed_operations;
        delete additionalFields.openapi_operations_disabled_all;
    } else if (!uniqueKeys.length) {
        additionalFields.allowed_operations = [];
        additionalFields.openapi_operations_disabled_all = true;
    } else {
        additionalFields.allowed_operations = uniqueKeys;
        delete additionalFields.openapi_operations_disabled_all;
    }
    return { ...draft, additionalFields };
}

function clearOpenApiSpecification(draft: ActionConfiguration): ActionConfiguration {
    const additionalFields = { ...draft.additionalFields };
    const keepOverride = openApiBaseUrlOverrideEnabled(draft);
    delete additionalFields.openapi_spec_content;
    delete additionalFields.openapi_source_type;
    delete additionalFields.allowed_operations;
    delete additionalFields.openapi_operations_disabled_all;
    if (!keepOverride) {
        additionalFields.base_url = '';
        additionalFields.base_url_override = false;
    }
    return updateOpenApiSourceDraft({
        ...draft,
        endpoint: keepOverride ? draft.endpoint : '',
        additionalFields,
    }, { filename: '', text: '{}', pending: false });
}

export function OpenApiActionConfiguration(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const specContent = draft.additionalFields.openapi_spec_content;
    const source = useMemo(() => openApiSourceDraft(draft), [draft._openApiSourceDraft, specContent]);
    const information = useMemo(() => openApiInformation(specContent), [specContent]);
    const specJson = useMemo(() => JSON.stringify(specContent, null, 2), [specContent]);
    const specBaseUrl = useMemo(() => openApiSpecificationBaseUrl(specContent), [specContent]);
    const baseUrlOverride = openApiBaseUrlOverrideEnabled(draft, specContent);
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const localErrors = validateConnectorConfiguration(draft, 'openapi');
    const { busy, run } = useConnectorRequest(props);
    const [operationSearch, setOperationSearch] = useState('');
    const [operationLimit, setOperationLimit] = useState(30);
    useConnectorValidity(props, 'openapi-configuration', Object.values(localErrors).join(' ') || null);
    const operationKeys = useMemo(() => information.operations.map(openApiOperationKey), [information.operations]);
    const storedAllowedOperations = connectorStrings(draft.additionalFields.allowed_operations);
    const operationsDisabledAll = draft.additionalFields.openapi_operations_disabled_all === true;
    const enabledOperationKeys = useMemo(() => {
        if (operationsDisabledAll) return new Set<string>();
        if (storedAllowedOperations.length) return new Set(storedAllowedOperations);
        return new Set(operationKeys);
    }, [operationKeys, operationsDisabledAll, storedAllowedOperations]);
    const enabledOperationCount = operationKeys.filter((key) => enabledOperationKeys.has(key)).length;
    const baseUrlValue = connectorText(draft.endpoint || draft.additionalFields.base_url) || specBaseUrl;

    useEffect(() => {
        if (readOnly || typeof draft.additionalFields.base_url_override === 'boolean' || !baseUrlOverride) return;
        onChange((current) => current === draft
            ? { ...current, additionalFields: { ...current.additionalFields, base_url_override: true } }
            : current);
    }, [baseUrlOverride, draft, onChange, readOnly]);

    const filteredOperations = information.operations.filter((operation) =>
        `${operation.method} ${operation.path} ${operation.id} ${operation.summary} ${operation.tags.join(' ')}`
            .toLowerCase().includes(operationSearch.toLowerCase()));
    const applyUpload = (current: ActionConfiguration, result: OpenApiUploadResult) => applyOpenApiSpecification(current, result);
    const uploadFeedback = (result: OpenApiUploadResult): ConnectorFeedback => ({
        success: true,
        message: `${result.original_filename || 'Specification'} was parsed and validated by the server.`,
        errors: [], warnings: result.warnings ?? [],
        details: { ...(result.file_id ? { file_id: result.file_id } : {}), operations: openApiInformation(result.spec_content).operations.length },
    });

    return (
        <div className="min-w-0 space-y-6" data-testid="openapi-configuration">
            <p className="text-[0.8125rem] leading-relaxed text-text-2">
                Import an OpenAPI specification to expose its operations to an agent. Importing or validating a specification does not call those operations.
            </p>
            <ActionField id="openapi-source-mode" label="Specification source" width="standard">
                <select id="openapi-source-mode" className={ACTION_INPUT_CLASS} value={source.mode} disabled={readOnly || Boolean(busy)}
                    onChange={(event) => {
                        const mode = event.target.value === 'manual' ? 'manual' : 'file';
                        onChange((current) => updateOpenApiSourceDraft(current, { mode }));
                    }}>
                    {OPENAPI_SOURCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
            </ActionField>
            {source.mode === 'file' ? (
                <ActionField id="openapi-file" label="OpenAPI specification file"
                    help="JSON, YAML, or YML, up to 5 MB. Validation uses the same server-side scanner as the classic editor. A failed import leaves the current specification unchanged."
                    error={errors['additionalFields.openapi_spec_content'] || (!draft.additionalFields.openapi_spec_content ? localErrors['additionalFields.openapi_spec_content'] : undefined)}>
                    <input ref={fileInputRef} id="openapi-file" type="file" accept=".json,.yaml,.yml" className="visually-hidden"
                        disabled={readOnly || Boolean(busy)} aria-describedby="openapi-file-help"
                        onChange={(event) => {
                            const file = event.target.files?.[0];
                            event.target.value = '';
                            if (file) void run('Validating specification…', (signal) => uploadOpenApiSpecification(file, file.name, signal), applyUpload, uploadFeedback);
                        }} />
                    <div className="flex flex-wrap items-center gap-2">
                        <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(busy)}
                            onClick={() => fileInputRef.current?.click()}>
                            {source.filename ? 'Replace file' : 'Choose OpenAPI file'}
                        </GlassButton>
                        {source.filename ? <GlassButton type="button" variant="ghost" disabled={readOnly || Boolean(busy)}
                            onClick={() => onChange((current) => clearOpenApiSpecification(current))}>
                            Remove file
                        </GlassButton> : null}
                    </div>
                    {source.filename ? <p className="mt-2 break-words text-sm text-text-2">
                        Selected specification: <span className="font-medium text-text-1">{source.filename}</span>
                    </p> : <p className="mt-2 text-sm text-text-3">No OpenAPI file selected.</p>}
                    <p className="mt-2 text-xs text-text-3">
                        For a specification hosted at a URL, download the JSON or YAML file, then upload it here.
                        SimpleChat does not fetch remote specifications.
                    </p>
                </ActionField>
            ) : (
                <div className="space-y-3">
                    <ActionField id="openapi-source-format" label="Source format" width="compact">
                        <select id="openapi-source-format" className={ACTION_INPUT_CLASS} value={source.format} disabled={readOnly || Boolean(busy)}
                            onChange={(event) => {
                                const format = event.target.value === 'yaml' ? 'yaml' : 'json';
                                onChange((current) => updateOpenApiSourceDraft(current, { format }));
                            }}>
                            <option value="json">JSON</option><option value="yaml">YAML</option>
                        </select>
                    </ActionField>
                    <ActionField id="openapi-source-text" label="Specification source" width="full"
                        help="Source text stays in this tab. Process the text to parse and validate it before saving. YAML is parsed on the server, not by a browser-loaded library."
                        error={localErrors['openapi-source'] || errors['additionalFields.openapi_spec_content']}>
                        <textarea id="openapi-source-text" rows={16} spellCheck={false} readOnly={readOnly}
                            className={`${ACTION_INPUT_CLASS} font-mono text-xs`} value={source.text}
                            aria-describedby="openapi-source-text-help" aria-invalid={source.pending}
                            onChange={(event) => {
                                const text = event.target.value;
                                onChange((current) => updateOpenApiSourceDraft(current, { text, pending: true }));
                            }} />
                    </ActionField>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(busy) || !source.text.trim()}
                            onClick={() => void run('Processing specification…', (signal) => processOpenApiText(source.text, source.format, signal), applyUpload, uploadFeedback)}>
                            Process specification
                        </GlassButton>
                        {source.pending && draft.additionalFields.openapi_spec_content ? <GlassButton type="button" disabled={readOnly || Boolean(busy)}
                            onClick={() => onChange((current) => updateOpenApiSourceDraft(current, {
                                pending: false, format: 'json', text: JSON.stringify(current.additionalFields.openapi_spec_content, null, 2),
                            }))}>Discard unprocessed source changes</GlassButton> : null}
                    </div>
                </div>
            )}
            <ActionField id="openapi-base-url" label="API base URL" required
                help="By default this comes from the imported specification's servers entry. Turn on Override base URL only when the deployed API is hosted somewhere else."
                error={errors.endpoint || localErrors.endpoint}>
                <div className="space-y-3">
                    <label className="flex items-center gap-2 text-sm text-text-2">
                        <input type="checkbox" className="form-check-input" checked={baseUrlOverride} disabled={readOnly}
                            onChange={(event) => {
                                const enabled = event.target.checked;
                                onChange((current) => {
                                    const currentSpecBaseUrl = openApiSpecificationBaseUrl(current.additionalFields.openapi_spec_content);
                                    const currentBaseUrl = connectorText(current.endpoint || current.additionalFields.base_url);
                                    const baseUrl = enabled ? currentBaseUrl : currentSpecBaseUrl;
                                    return {
                                        ...current,
                                        endpoint: baseUrl,
                                        additionalFields: { ...current.additionalFields, base_url: baseUrl, base_url_override: enabled },
                                    };
                                });
                            }} />
                        <span>Override base URL</span>
                    </label>
                    <input id="openapi-base-url" type="url" value={baseUrlValue}
                    readOnly={!baseUrlOverride} disabled={readOnly} className={ACTION_INPUT_CLASS} placeholder="https://api.example.com"
                    aria-invalid={Boolean(errors.endpoint || localErrors.endpoint)} aria-describedby="openapi-base-url-help openapi-base-url-error"
                    onChange={(event) => {
                        const endpoint = event.target.value;
                        onChange((current) => ({
                            ...current,
                            endpoint,
                            additionalFields: { ...current.additionalFields, base_url: endpoint, base_url_override: true },
                        }));
                    }} />
                    {!baseUrlOverride && specBaseUrl ? <p className="text-xs text-text-3">Using the specification server: <span className="break-all font-mono">{specBaseUrl}</span></p> : null}
                    {!baseUrlOverride && !specBaseUrl ? <p className="text-xs text-warn">The specification does not declare a usable server URL. Turn on Override base URL to enter one before saving.</p> : null}
                </div>
            </ActionField>
            {information.servers.length ? <EditorRow heading="Servers declared in the specification">
                <ul className="space-y-2">
                    {information.servers.map((server, index) => <li key={`${server.url}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-edge bg-surface-1 p-3">
                        <div className="min-w-0">
                            <p className="break-all font-mono text-xs text-text-1">{server.url}</p>
                            {server.description ? <p className="mt-1 break-words text-xs text-text-3">{server.description}</p> : null}
                        </div>
                        {!readOnly ? <GlassButton type="button" size="sm" variant="subtle" disabled={Boolean(connectorUrlError(server.url))}
                            onClick={() => onChange((current) => ({
                                ...current, endpoint: server.url, additionalFields: { ...current.additionalFields, base_url: server.url, base_url_override: false },
                            }))}>Use this base URL</GlassButton> : null}
                    </li>)}
                </ul>
            </EditorRow> : null}
            {information.title || information.operations.length ? <EditorPanel title={information.title || 'API information'}
                description={`API version ${information.version || 'not specified'} · OpenAPI ${information.specificationVersion || 'not specified'} · ${information.pathsCount} paths · ${information.operations.length} operations`}>
                {information.description ? <p className="whitespace-pre-wrap break-words text-sm text-text-2">{information.description}</p> : null}
                <ActionField id="openapi-operation-search" label="Find an operation" width="standard">
                    <input id="openapi-operation-search" type="search" className={ACTION_INPUT_CLASS} value={operationSearch}
                        placeholder="Method, path, operation ID, or tag" onChange={(event) => {
                            setOperationSearch(event.target.value); setOperationLimit(30);
                        }} />
                </ActionField>
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" size="sm" variant="subtle" disabled={readOnly || !operationKeys.length}
                        onClick={() => onChange((current) => updateOpenApiAllowedOperations(current, operationKeys, operationKeys))}>
                        Enable all
                    </GlassButton>
                    <GlassButton type="button" size="sm" variant="ghost" disabled={readOnly || !operationKeys.length}
                        onClick={() => onChange((current) => updateOpenApiAllowedOperations(current, [], operationKeys))}>
                        Disable all
                    </GlassButton>
                    <p className="text-xs text-text-3">
                        {enabledOperationCount} of {operationKeys.length} operations enabled. Empty saved allow-lists mean all operations for backward compatibility, so saving is blocked if you disable every operation.
                    </p>
                </div>
                {localErrors['additionalFields.allowed_operations'] ? <p role="alert" className="text-sm text-danger">{localErrors['additionalFields.allowed_operations']}</p> : null}
                <p className="text-xs text-text-3">{filteredOperations.length} matching operations. Enable switches control which functions agents can see and call.</p>
                <div className="space-y-2">
                    {filteredOperations.slice(0, operationLimit).map((operation) => <details key={operation.key} className="rounded-lg border border-edge bg-surface-1 p-3">
                        <summary className="cursor-pointer break-words text-sm text-text-1">
                            <span className="inline-flex min-w-0 flex-wrap items-center gap-2">
                                <span className="font-mono font-semibold">{operation.method}</span>
                                <span className="break-all font-mono text-xs">{operation.path}</span>
                                {operation.summary ? <span>{operation.summary}</span> : null}
                                {operation.deprecated ? <span className="text-xs text-warn">Deprecated</span> : null}
                            </span>
                        </summary>
                        <div className="mt-3 space-y-3 text-xs text-text-2">
                            <label className="flex items-center gap-2 text-sm text-text-1">
                                <input type="checkbox" className="form-check-input" checked={enabledOperationKeys.has(operation.key)} disabled={readOnly}
                                    onChange={(event) => {
                                        const selected = new Set(operationKeys.filter((key) => enabledOperationKeys.has(key)));
                                        if (event.target.checked) selected.add(operation.key);
                                        else selected.delete(operation.key);
                                        onChange((current) => updateOpenApiAllowedOperations(current, [...selected], operationKeys));
                                    }} />
                                <span>{enabledOperationKeys.has(operation.key) ? 'Enabled' : 'Disabled'}</span>
                            </label>
                            <p>Operation key: <span className="break-all font-mono">{operation.key}</span>{operation.id ? null : ' (generated by the connector)'}</p>
                            {operation.description ? <p className="whitespace-pre-wrap break-words">{operation.description}</p> : null}
                            {operation.tags.length ? <p>Tags: {operation.tags.join(', ')}</p> : null}
                            {operation.parameters.length ? <ul className="space-y-2">
                                {operation.parameters.map((parameter) => <li key={`${parameter.location}:${parameter.name}`}>
                                    <span className="break-all font-mono">{parameter.name}</span> ({parameter.location}, {parameter.type}{parameter.required ? ', required' : ', optional'})
                                    {parameter.description ? <p className="mt-0.5 break-words text-text-3">{parameter.description}</p> : null}
                                </li>)}
                            </ul> : <p>No declared parameters.</p>}
                            {operation.contentTypes.length ? <p>Request body ({operation.bodyRequired ? 'required' : 'optional'}): {operation.contentTypes.join(', ')}</p> : null}
                            <p>Responses: {operation.responses.join(', ') || 'Not specified'}</p>
                            <p>Security schemes: {operation.security.join(', ') || 'No declared requirement'}</p>
                        </div>
                    </details>)}
                    {!filteredOperations.length ? <p className="text-sm text-text-3">No operations match this search.</p> : null}
                    {filteredOperations.length > operationLimit ? <GlassButton type="button" variant="subtle" onClick={() => setOperationLimit((current) => current + 30)}>Show more operations</GlassButton> : null}
                </div>
                <EditorGroup summary="Validated specification JSON">
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-1 p-3 text-xs text-text-3">{specJson}</pre>
                </EditorGroup>
            </EditorPanel> : null}
        </div>
    );
}

export function OpenApiActionAuthentication(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const method = connectorAuthMethod(draft, 'openapi');
    const apiKeyIdentity = Boolean(draft.identity_id && draft.additionalFields.identity_auth_type === 'api_key');
    const credentialField = connectorSecretField(draft, 'openapi');
    const basic = openApiBasicCredentials(draft);
    const specContent = draft.additionalFields.openapi_spec_content;
    const information = useMemo(() => openApiInformation(specContent), [specContent]);
    const source = useMemo(() => openApiSourceDraft(draft), [draft._openApiSourceDraft, specContent]);
    const localErrors = validateConnectorAuthentication(draft, 'openapi', original);
    const configurationErrors = validateConnectorConfiguration(draft, 'openapi');
    useConnectorValidity(props, 'openapi-authentication', Object.values(localErrors).join(' ') || null);
    const location = connectorText(draft.additionalFields.api_key_location ?? draft.auth.location ?? 'header');
    const usernameMasked = draft.auth.username === EDITOR_SECRET_MASK || draft.auth.identity === EDITOR_SECRET_MASK;
    const setAuthField = (field: string, value: string) => onChange((current) => ({ ...current, auth: { ...current.auth, [field]: value } }));
    const authError = (field: string) => errors[field] || localErrors[field];
    return (
        <div className="space-y-5" data-testid="openapi-authentication">
            <ConnectorIdentitySelect {...props} kind="openapi" />
            <ActionField id="openapi-auth-method" label="Authentication method" width="standard" error={authError('additionalFields.auth_method')}
                help={draft.identity_id ? 'The selected reusable identity controls authentication.' : 'Changing a method does not test or run the action. Choosing no authentication clears action-specific credentials, including their legacy aliases.'}>
                <select id="openapi-auth-method" className={ACTION_INPUT_CLASS} value={method} disabled={readOnly || Boolean(draft.identity_id)}
                    onChange={(event) => {
                        const next = event.target.value;
                        onChange((current) => changeConnectorAuthMethod(current, 'openapi', next));
                    }}>
                    {method === 'identity' ? <option value="identity">Reusable identity</option> : null}
                    {!OPENAPI_AUTH_OPTIONS.some(({ value }) => value === method) && method !== 'identity' ? <option value={method} disabled>Unavailable method — {method}</option> : null}
                    {OPENAPI_AUTH_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
            </ActionField>
            {(method === 'api_key' && !draft.identity_id) || apiKeyIdentity ? <div className="min-w-0">
                <ActionField id="openapi-key-location" label="API key location" width="standard" error={authError('additionalFields.api_key_location')}>
                    <select id="openapi-key-location" value={location} disabled={readOnly} className={ACTION_INPUT_CLASS}
                        onChange={(event) => {
                            const api_key_location = event.target.value;
                            onChange((current) => updateConnectorFields(current, { api_key_location }));
                        }}>
                        {!['header', 'query'].includes(location) ? <option value={location} disabled>Unsupported location — {location}</option> : null}
                        <option value="header">HTTP header</option><option value="query">Query parameter</option>
                    </select>
                </ActionField>
                <ActionField id="openapi-key-name" label={location === 'query' ? 'Query parameter name' : 'Header name'} required width="standard" error={authError('additionalFields.api_key_name')}>
                    <input id="openapi-key-name" className={ACTION_INPUT_CLASS} disabled={readOnly}
                        value={connectorText(draft.additionalFields.api_key_name ?? draft.auth.name ?? 'X-API-Key')}
                        onChange={(event) => {
                            const api_key_name = event.target.value;
                            onChange((current) => updateConnectorFields(current, { api_key_name }));
                        }} />
                </ActionField>
            </div> : null}
            {method === 'basic' && !draft.identity_id ? <div className="min-w-0 space-y-4">
                {basic.stored && credentialField === 'key' ? <p className="rounded-xl bg-surface-2 p-3 text-sm text-text-2">
                    A stored username/password pair is configured. Its username is also hidden. Keep the stored pair unchanged, or enter both values to replace it.
                </p> : null}
                {usernameMasked && draft.auth.type === 'basic' ? <ActionSecretInput
                    id="openapi-basic-username" label="Username" value={draft.auth.username ?? draft.auth.identity}
                    storedValue={original?.record.auth.username ?? original?.record.auth.identity} disabled={readOnly}
                    error={authError('auth.basic_username')}
                    onChange={(value) => setAuthField(Object.hasOwn(draft.auth, 'username') ? 'username' : 'identity', value)} /> :
                    <ActionField id="openapi-basic-username" label="Username" required error={authError('auth.basic_username')}>
                        <input id="openapi-basic-username" value={basic.username} className={ACTION_INPUT_CLASS} disabled={readOnly}
                            autoComplete="off" placeholder={basic.stored ? 'Stored with password — enter both to replace' : 'Username'}
                            onChange={(event) => {
                                const value = event.target.value;
                                onChange((current) => changeOpenApiBasicCredential(current, 'username', value));
                            }} />
                    </ActionField>}
                <ActionSecretInput id="openapi-basic-password" label="Password" value={basic.password}
                    storedValue={original?.record.auth[credentialField]} disabled={readOnly} error={authError(`auth.${credentialField}`)}
                    help={credentialField === 'key' ? 'OpenAPI basic credentials are stored together as username:password. Clearing this field clears the pair; replacing either part requires both values.' : undefined}
                    onChange={(value) => onChange((current) => changeOpenApiBasicCredential(current, 'password', value))} />
            </div> : null}
            {['api_key', 'bearer', 'oauth2'].includes(method) && !draft.identity_id ? <ActionSecretInput
                id="openapi-credential" label={method === 'api_key' ? 'API key' : method === 'oauth2' ? 'OAuth 2 access token' : 'Bearer token'}
                value={draft.auth[credentialField]} storedValue={original?.record.auth[credentialField]}
                disabled={readOnly} error={authError(`auth.${credentialField}`)}
                help={method === 'oauth2' ? 'Supply an access token obtained from your provider. This connector does not perform an interactive OAuth sign-in or refresh-token flow.' : undefined}
                onChange={(value) => setAuthField(credentialField, value)} /> : null}
            {information.securitySchemes.length ? <EditorPanel title="Authentication declared by the API"
                description="Selecting a scheme only configures its method and key location. Credentials and reusable identity references are never imported from a specification.">
                {information.securitySchemes.map((scheme) => <div key={scheme.id} className="min-w-0 space-y-2 rounded-lg border border-edge bg-surface-1 p-3">
                    <p className="break-words text-sm font-medium text-text-1">{scheme.id} · {scheme.method || 'Unspecified scheme'}</p>
                    {scheme.description ? <p className="whitespace-pre-wrap break-words text-xs text-text-2">{scheme.description}</p> : null}
                    {scheme.method === 'api_key' ? <p className="break-words text-xs text-text-3">{scheme.location}: {scheme.name}</p> : null}
                    {scheme.scopes.length ? <p className="break-words text-xs text-text-3">Declared scopes: {scheme.scopes.join(', ')}</p> : null}
                    {scheme.supported ? <GlassButton type="button" size="sm" variant="subtle" disabled={readOnly || Boolean(draft.identity_id)}
                        onClick={() => onChange((current) => {
                            const next = changeConnectorAuthMethod(current, 'openapi', scheme.method);
                            return scheme.method === 'api_key' ? updateConnectorFields(next, { api_key_location: scheme.location, api_key_name: scheme.name }) : next;
                        })}>Use this authentication scheme</GlassButton> :
                        <p className="text-xs text-warn">This scheme or location is not supported by the current OpenAPI connector. Choose one of the supported methods above.</p>}
                </div>)}
            </EditorPanel> : null}
            {Object.keys(connectorObject(draft.additionalFields.openapi_authentication)).length ? <p className="text-xs text-text-3">Legacy authentication analysis is retained in additional fields.</p> : null}
            {Object.values(configurationErrors).length ? <p className="text-xs text-warn">{Object.values(configurationErrors).join(' ')}</p> : null}
            <ActionConnectionCheck props={props} kind="openapi" disabled={source.pending}
                configurationError={Object.values(configurationErrors).length > 0} />
        </div>
    );
}
