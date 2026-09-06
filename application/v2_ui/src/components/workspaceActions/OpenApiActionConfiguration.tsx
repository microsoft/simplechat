// OpenApiActionConfiguration.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { ActionField, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import { EDITOR_SECRET_MASK, type ActionConfiguration } from '../../lib/workspaceAuthoring';
import {
    applyOpenApiSpecification, changeConnectorAuthMethod, changeOpenApiBasicCredential,
    connectorAuthMethod, connectorFeedback, connectorIdentityOptions, connectorObject,
    connectorSecretField, connectorText, connectorUrlError, OPENAPI_AUTH_OPTIONS,
    OPENAPI_SOURCE_OPTIONS, openApiBasicCredentials, openApiInformation, openApiSourceDraft, processOpenApiText,
    selectConnectorIdentity, testApiConnector, updateConnectorFields, updateOpenApiSourceDraft,
    uploadOpenApiSpecification, validateApiConnector, validateConnectorAuthentication,
    validateConnectorConfiguration,
    type ApiConnector, type ConnectorFeedback, type OpenApiUploadResult,
} from '../../lib/workspaceActionConnectors';

export function useConnectorValidity(props: ActionConnectorProps, key: string, message: string | null) {
    const callback = useRef(props.onValidityChange);
    callback.current = props.onValidityChange;
    const readOnly = props.readOnly || props.original?.read_only;
    useEffect(() => {
        callback.current(key, readOnly ? null : message);
        return () => callback.current(key, null);
    }, [key, message, readOnly]);
}

export function useConnectorRequest(props: ActionConnectorProps) {
    const latest = useRef(props);
    latest.current = props;
    const activeRequest = useRef<{
        controller: AbortController;
        draft: ActionConfiguration;
        original: ActionConnectorProps['original'];
    } | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [feedback, setFeedback] = useState<{ value: ConnectorFeedback; draft: ActionConfiguration } | null>(null);

    useEffect(() => {
        const active = activeRequest.current;
        if (active && (active.draft !== props.draft || active.original !== props.original || props.readOnly || props.original?.read_only)) {
            active.controller.abort();
            activeRequest.current = null;
            setBusy(null);
        }
    }, [props.draft, props.original, props.readOnly]);
    useEffect(() => () => {
        activeRequest.current?.controller.abort();
        activeRequest.current = null;
    }, []);

    async function run<T>(
        label: string,
        operation: (signal: AbortSignal) => Promise<T>,
        apply?: (draft: ActionConfiguration, result: T) => ActionConfiguration,
        describe?: (result: T) => ConnectorFeedback,
    ): Promise<T | undefined> {
        const snapshot = latest.current;
        if (snapshot.readOnly || snapshot.original?.read_only) return;
        activeRequest.current?.controller.abort();
        const request = new AbortController();
        activeRequest.current = { controller: request, draft: snapshot.draft, original: snapshot.original };
        setBusy(label);
        try {
            const response = await operation(request.signal);
            if (request.signal.aborted || latest.current.draft !== snapshot.draft ||
                latest.current.original !== snapshot.original || latest.current.readOnly) return;
            const value = describe ? describe(response) : connectorFeedback(response);
            let resultDraft = snapshot.draft;
            if (value.success && apply) {
                resultDraft = apply(snapshot.draft, response);
                snapshot.onChange((current) => current === snapshot.draft ? resultDraft : current);
            }
            setFeedback({ value, draft: resultDraft });
            return value.success ? response : undefined;
        } catch (error) {
            if (!request.signal.aborted && latest.current.draft === snapshot.draft &&
                latest.current.original === snapshot.original) {
                setFeedback({ value: connectorFeedback(error), draft: snapshot.draft });
            }
            return undefined;
        } finally {
            if (activeRequest.current?.controller === request) {
                activeRequest.current = null;
                setBusy(null);
            }
        }
    }
    return { busy, feedback: feedback?.value ?? null, stale: Boolean(feedback && feedback.draft !== props.draft), run };
}

export function ConnectorFeedbackPanel({ feedback, stale }: { feedback: ConnectorFeedback | null; stale?: boolean }) {
    if (!feedback) return null;
    const details = Object.entries(feedback.details).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value));
    return (
        <div role={feedback.success ? 'status' : 'alert'} aria-live="polite"
            className={`alert rounded-xl border p-3 text-sm ${feedback.success
                ? 'alert-success border-edge bg-surface-2 text-text-1'
                : 'alert-danger border-danger/30 bg-danger-soft text-danger'}`}>
            <p className="break-words">{feedback.message}</p>
            {stale ? <p className="mt-1 text-xs text-text-3">This result describes an earlier draft. Run the command again to check your current configuration.</p> : null}
            {feedback.errors.length ? <ul className="mt-2 list-disc space-y-1 pl-5">
                {feedback.errors.map((message, index) => <li key={index} className="break-words">{message}</li>)}
            </ul> : null}
            {feedback.warnings.length ? <div className="alert alert-warning mt-2 rounded-lg bg-warn-soft p-2 text-warn">
                <p className="font-medium">Warnings</p>
                <ul className="list-disc space-y-1 pl-5">
                    {feedback.warnings.map((message, index) => <li key={index} className="break-words">{message}</li>)}
                </ul>
            </div> : null}
            {details.length ? <dl className="mt-2 grid gap-1 text-xs text-text-2">
                {details.map(([name, value]) => <div key={name} className="flex flex-wrap gap-x-2">
                    <dt className="font-medium">{name.replaceAll('_', ' ')}:</dt><dd className="break-all">{String(value)}</dd>
                </div>)}
            </dl> : null}
        </div>
    );
}

export function ConnectorIdentitySelect({ kind, ...props }: ActionConnectorProps & { kind: ApiConnector }) {
    const selectedId = props.draft.identity_id || '';
    const { identities, unavailable } = connectorIdentityOptions(props.identities, kind, selectedId);
    const disabled = props.readOnly || props.original?.read_only || props.identitiesLoading;
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
                    {unavailable ? <option value={selectedId} disabled>Unavailable identity — {selectedId}</option> : null}
                    {identities.map((identity) => <option key={identity.id} value={identity.id}>
                        {identity.name} · {identity.auth_type.replaceAll('_', ' ')} · {identity.scope_type || 'personal'} · {identity.id}
                    </option>)}
                </select>
            </ActionField>
            <div id={`${id}-status`} className="space-y-1 text-xs text-text-3" aria-live="polite">
                {props.identitiesLoading ? <p>Loading permitted identities…</p> : null}
                {props.identitiesError ? <p role="alert" className="text-danger">{props.identitiesError} The current identity selection has not been changed.</p> : null}
                {!props.identitiesLoading && !props.identitiesError && !identities.length ? <p>No compatible reusable identities are available. Action-specific credentials are still supported.</p> : null}
                {unavailable ? <p className="alert alert-warning rounded-lg bg-warn-soft p-2 text-warn">
                    The selected identity is unavailable or incompatible. Its ID is retained; choose a replacement explicitly. A same-name identity will not be substituted.
                </p> : null}
                {selectedId && !unavailable ? <p>{identities.find(({ id }) => id === selectedId)?.description || 'The server resolves this identity when the action runs.'}</p> : null}
            </div>
        </div>
    );
}

export function OpenApiActionConfiguration(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const specContent = draft.additionalFields.openapi_spec_content;
    const source = useMemo(() => openApiSourceDraft(draft), [draft._openApiSourceDraft, specContent]);
    const information = useMemo(() => openApiInformation(specContent), [specContent]);
    const specJson = useMemo(() => JSON.stringify(specContent, null, 2), [specContent]);
    const localErrors = validateConnectorConfiguration(draft, 'openapi');
    const { busy, feedback, stale, run } = useConnectorRequest(props);
    const [operationSearch, setOperationSearch] = useState('');
    const [operationLimit, setOperationLimit] = useState(30);
    useConnectorValidity(props, 'openapi-configuration', Object.values(localErrors).join(' ') || null);

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
            <p className="text-sm leading-relaxed text-text-2">
                Import an OpenAPI specification to expose its operations to an agent. Importing or validating a specification does not call those operations.
            </p>
            <ActionField id="openapi-source-mode" label="Specification source">
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
                    <input id="openapi-file" type="file" accept=".json,.yaml,.yml" className={ACTION_INPUT_CLASS}
                        disabled={readOnly || Boolean(busy)} aria-describedby="openapi-file-help"
                        onChange={(event) => {
                            const file = event.target.files?.[0];
                            event.target.value = '';
                            if (file) void run('Validating specification…', (signal) => uploadOpenApiSpecification(file, file.name, signal), applyUpload, uploadFeedback);
                        }} />
                    {source.filename ? <p className="mt-2 break-words text-xs text-text-3">Last imported: {source.filename}</p> : null}
                    <p className="mt-2 text-xs text-text-3">
                        For a specification hosted at a URL, download the JSON or YAML file, then upload it here.
                        SimpleChat does not fetch remote specifications.
                    </p>
                </ActionField>
            ) : (
                <div className="space-y-3">
                    <ActionField id="openapi-source-format" label="Source format">
                        <select id="openapi-source-format" className={ACTION_INPUT_CLASS} value={source.format} disabled={readOnly || Boolean(busy)}
                            onChange={(event) => {
                                const format = event.target.value === 'yaml' ? 'yaml' : 'json';
                                onChange((current) => updateOpenApiSourceDraft(current, { format }));
                            }}>
                            <option value="json">JSON</option><option value="yaml">YAML</option>
                        </select>
                    </ActionField>
                    <ActionField id="openapi-source-text" label="Specification source"
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
                help="The URL against which the imported operations run. Changing it does not fetch or replace the specification."
                error={errors.endpoint || localErrors.endpoint}>
                <input id="openapi-base-url" type="url" value={draft.endpoint || connectorText(draft.additionalFields.base_url)}
                    disabled={readOnly} className={ACTION_INPUT_CLASS} placeholder="https://api.example.com"
                    aria-invalid={Boolean(errors.endpoint || localErrors.endpoint)} aria-describedby="openapi-base-url-help openapi-base-url-error"
                    onChange={(event) => {
                        const endpoint = event.target.value;
                        onChange((current) => ({ ...current, endpoint, additionalFields: { ...current.additionalFields, base_url: endpoint } }));
                    }} />
            </ActionField>
            {information.servers.length ? <div className="space-y-2">
                <p className="text-sm font-medium text-text-1">Servers declared in the specification</p>
                <ul className="space-y-2">
                    {information.servers.map((server, index) => <li key={`${server.url}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-edge p-3">
                        <div className="min-w-0">
                            <p className="break-all font-mono text-xs text-text-1">{server.url}</p>
                            {server.description ? <p className="mt-1 break-words text-xs text-text-3">{server.description}</p> : null}
                        </div>
                        {!readOnly ? <GlassButton type="button" size="sm" variant="subtle" disabled={Boolean(connectorUrlError(server.url))}
                            onClick={() => onChange((current) => ({
                                ...current, endpoint: server.url, additionalFields: { ...current.additionalFields, base_url: server.url },
                            }))}>Use this base URL</GlassButton> : null}
                    </li>)}
                </ul>
            </div> : null}
            {information.title || information.operations.length ? <GlassPanel elevation="flat" className="space-y-4 p-4">
                <div>
                    <h3 className="break-words font-semibold text-text-1">{information.title || 'API information'}</h3>
                    <p className="mt-1 text-xs text-text-3">
                        API version {information.version || 'not specified'} · OpenAPI {information.specificationVersion || 'not specified'} · {information.pathsCount} paths · {information.operations.length} operations
                    </p>
                    {information.description ? <p className="mt-2 whitespace-pre-wrap break-words text-sm text-text-2">{information.description}</p> : null}
                </div>
                <ActionField id="openapi-operation-search" label="Find an operation">
                    <input id="openapi-operation-search" type="search" className={ACTION_INPUT_CLASS} value={operationSearch}
                        placeholder="Method, path, operation ID, or tag" onChange={(event) => {
                            setOperationSearch(event.target.value); setOperationLimit(30);
                        }} />
                </ActionField>
                <p className="text-xs text-text-3">{filteredOperations.length} matching operations. This is a read-only description, not an operation runner.</p>
                <div className="space-y-2">
                    {filteredOperations.slice(0, operationLimit).map((operation) => <details key={`${operation.method}:${operation.path}`} className="rounded-xl border border-edge p-3">
                        <summary className="cursor-pointer break-words text-sm text-text-1">
                            <span className="mr-2 font-mono font-semibold">{operation.method}</span>
                            <span className="break-all font-mono text-xs">{operation.path}</span>
                            {operation.summary ? <span className="ml-2">{operation.summary}</span> : null}
                            {operation.deprecated ? <span className="ml-2 text-xs text-warn">Deprecated</span> : null}
                        </summary>
                        <div className="mt-3 space-y-3 text-xs text-text-2">
                            <p>Operation ID: <span className="break-all font-mono">{operation.id || 'Generated by the connector'}</span></p>
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
                <details className="text-xs text-text-3">
                    <summary className="cursor-pointer">Validated specification JSON</summary>
                    <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-1 p-3">{specJson}</pre>
                </details>
            </GlassPanel> : null}
            <div className="space-y-3 border-t border-edge pt-4">
                <p className="text-xs leading-relaxed text-text-3">Validation checks the manifest without running it. Connection testing parses the specification and probes the authenticated base URL; it does not invoke an individual API operation.</p>
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(busy) || source.pending}
                        onClick={() => void run('Validating configuration…', (signal) => validateApiConnector(draft, original, 'openapi', signal))}>
                        Validate OpenAPI configuration
                    </GlassButton>
                    <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(busy) || source.pending}
                        onClick={() => void run('Testing OpenAPI connection…', (signal) => testApiConnector(draft, original, 'openapi', signal))}>
                        Test OpenAPI connection
                    </GlassButton>
                    {busy ? <p role="status" className="text-sm text-text-3">{busy}</p> : null}
                </div>
                {readOnly ? <p className="text-xs text-text-3">Provided actions are read-only. Import, validation, and connection testing are disabled.</p> : null}
                <ConnectorFeedbackPanel feedback={feedback} stale={stale} />
            </div>
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
    const localErrors = validateConnectorAuthentication(draft, 'openapi', original);
    useConnectorValidity(props, 'openapi-authentication', Object.values(localErrors).join(' ') || null);
    const location = connectorText(draft.additionalFields.api_key_location ?? draft.auth.location ?? 'header');
    const usernameMasked = draft.auth.username === EDITOR_SECRET_MASK || draft.auth.identity === EDITOR_SECRET_MASK;
    const setAuthField = (field: string, value: string) => onChange((current) => ({ ...current, auth: { ...current.auth, [field]: value } }));
    const authError = (field: string) => errors[field] || localErrors[field];
    return (
        <div className="space-y-5" data-testid="openapi-authentication">
            <ConnectorIdentitySelect {...props} kind="openapi" />
            <ActionField id="openapi-auth-method" label="Authentication method" error={authError('additionalFields.auth_method')}
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
            {(method === 'api_key' && !draft.identity_id) || apiKeyIdentity ? <div className="grid gap-4 sm:grid-cols-2">
                <ActionField id="openapi-key-location" label="API key location" error={authError('additionalFields.api_key_location')}>
                    <select id="openapi-key-location" value={location} disabled={readOnly} className={ACTION_INPUT_CLASS}
                        onChange={(event) => {
                            const api_key_location = event.target.value;
                            onChange((current) => updateConnectorFields(current, { api_key_location }));
                        }}>
                        {!['header', 'query'].includes(location) ? <option value={location} disabled>Unsupported location — {location}</option> : null}
                        <option value="header">HTTP header</option><option value="query">Query parameter</option>
                    </select>
                </ActionField>
                <ActionField id="openapi-key-name" label={location === 'query' ? 'Query parameter name' : 'Header name'} required error={authError('additionalFields.api_key_name')}>
                    <input id="openapi-key-name" className={ACTION_INPUT_CLASS} disabled={readOnly}
                        value={connectorText(draft.additionalFields.api_key_name ?? draft.auth.name ?? 'X-API-Key')}
                        onChange={(event) => {
                            const api_key_name = event.target.value;
                            onChange((current) => updateConnectorFields(current, { api_key_name }));
                        }} />
                </ActionField>
            </div> : null}
            {method === 'basic' && !draft.identity_id ? <div className="space-y-4">
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
            {information.securitySchemes.length ? <div className="space-y-3">
                <h3 className="text-sm font-semibold text-text-1">Authentication declared by the API</h3>
                <p className="text-xs text-text-3">Selecting a scheme only configures its method and key location. Credentials and reusable identity references are never imported from a specification.</p>
                {information.securitySchemes.map((scheme) => <GlassPanel key={scheme.id} elevation="flat" className="space-y-2 p-3">
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
                </GlassPanel>)}
            </div> : null}
            {Object.keys(connectorObject(draft.additionalFields.openapi_authentication)).length ? <p className="text-xs text-text-3">Legacy authentication analysis is retained in additional fields.</p> : null}
        </div>
    );
}
