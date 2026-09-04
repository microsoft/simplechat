// ModelConnectionsManager.tsx
// Lists global model connections and edits one at a time.
//
// This talks to /api/v2/admin/model-endpoints directly rather than going through the
// settings PATCH, for the same reason CustomPagesTable does: a connection is its own
// resource with its own Key Vault handling, not a value in the settings blob.
//
// The behaviour that motivated the rewrite: in the classic interface, adding or editing a
// connection changed an in-memory array that was serialized into a hidden form field, so
// nothing was stored until the whole admin page was submitted -- and a half-filled
// connection looked identical to a saved one. Here each connection saves on its own, and
// the editor says which state it is in.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import {
    AlertCircle,
    Check,
    Loader2,
    Pencil,
    Plus,
    Power,
    RefreshCw,
    Search,
    Server,
    Trash2,
    Zap,
} from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    AUTH_TYPE_OPTIONS,
    IDENTITY_HEADER_MODE_OPTIONS,
    IDENTITY_VALUE_TYPE_OPTIONS,
    MANAGEMENT_CLOUD_OPTIONS,
    PROVIDER_OPTIONS,
    authTypeLabel,
    buildConnectionPayload,
    createModelConnection,
    deleteModelConnection,
    defaultOpenAiApiVersion,
    discoverModels,
    emptyConnection,
    enabledModelCount,
    fetchModelConnections,
    isFoundryProvider,
    mergeDiscoveredModels,
    projectNameFromEndpoint,
    providerLabel,
    testConnection,
    testConnectionModel,
    toEditableConnection,
    updateModelConnection,
    validateConnection,
    visibleFields,
    type ConnectionModel,
    type ModelConnection,
} from '../../lib/modelConnections';
import { AdminModal } from './AdminModal';
import { GlassButton } from '../ui/primitives';
import { useModelConnectionsStore, modelConnectionsChanged } from '../../stores/modelConnectionsStore';
import { toast } from '../../stores/toastStore';

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}

/** One labelled control in the editor, with its own validation message. */
function Field({
    label,
    help,
    error,
    htmlFor,
    children,
}: {
    label: string;
    help?: string;
    error?: string;
    htmlFor?: string;
    children: React.ReactNode;
}) {
    return (
        <div className="py-2">
            <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-text-1">
                {label}
            </label>
            {children}
            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}
            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}

function SectionHeading({ children, hint }: { children: React.ReactNode; hint?: string }) {
    return (
        <div className="mt-5 mb-1 border-t border-edge pt-4 first:mt-0 first:border-t-0 first:pt-0">
            <h3 className="text-xs font-semibold tracking-wide text-text-2 uppercase">{children}</h3>
            {hint ? <p className="mt-1 text-xs text-text-3">{hint}</p> : null}
        </div>
    );
}

function Pill({ tone, children }: { tone: 'ok' | 'muted' | 'warn'; children: React.ReactNode }) {
    return (
        <span
            className={clsx(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase',
                tone === 'ok' && 'bg-ok-soft text-ok',
                tone === 'warn' && 'bg-warn-soft text-warn',
                tone === 'muted' && 'bg-surface-2 text-text-3',
            )}
        >
            {children}
        </span>
    );
}

/* -------------------------------------------------------------------------- */
/* Editor                                                                      */
/* -------------------------------------------------------------------------- */

function ConnectionEditor({
    initial,
    onClose,
    onSaved,
}: {
    initial: ModelConnection;
    onClose: () => void;
    onSaved: (saved: ModelConnection, created: boolean) => void;
}) {
    const [draft, setDraft] = useState<ModelConnection>(() => toEditableConnection(initial));
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [saving, setSaving] = useState(false);
    const [discovering, setDiscovering] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testingModelId, setTestingModelId] = useState<string | null>(null);
    const [formError, setFormError] = useState<string | null>(null);

    const isNew = !initial.id;
    const foundry = isFoundryProvider(draft.provider);
    const authType = String(draft.auth?.type ?? 'managed_identity');

    const shown = useMemo(() => visibleFields(draft), [draft]);

    const setField = useCallback((path: string, value: unknown) => {
        setErrors((current) => {
            if (!(path in current)) {
                return current;
            }
            const next = { ...current };
            delete next[path];
            return next;
        });
        setDraft((current) => {
            const next = { ...current };
            if (path === 'name' || path === 'provider' || path === 'enabled') {
                (next as Record<string, unknown>)[path] = value;
                // Switching provider changes which API version default applies, and the
                // previous provider's default would otherwise be silently carried over.
                if (path === 'provider') {
                    next.connection = {
                        ...next.connection,
                        openai_api_version: defaultOpenAiApiVersion(value),
                    };
                }
                return next;
            }
            const [group, key] = path.split('.');
            (next as Record<string, Record<string, unknown>>)[group] = {
                ...((current as Record<string, Record<string, unknown>>)[group] ?? {}),
                [key]: value,
            };
            return next;
        });
    }, []);

    const setModels = useCallback((models: ConnectionModel[]) => {
        setDraft((current) => ({ ...current, models }));
    }, []);

    const runDiscovery = async () => {
        const validation = validateConnection(draft);
        // Discovery needs the connection and credentials, but not the model list, so a
        // missing name should not stop it.
        delete validation.name;
        if (Object.keys(validation).length) {
            setErrors(validation);
            setFormError('Fill in the connection and authentication details first.');
            return;
        }

        setDiscovering(true);
        setFormError(null);
        try {
            const response = await discoverModels(buildConnectionPayload(draft));
            const discovered = Array.isArray(response.models) ? response.models : [];
            const { models, added } = mergeDiscoveredModels(draft.models ?? [], discovered);
            setModels(models);
            toast.success(
                added
                    ? `Found ${discovered.length} deployment${discovered.length === 1 ? '' : 's'}, added ${added} new.`
                    : `Found ${discovered.length} deployment${discovered.length === 1 ? '' : 's'}; none were new.`,
            );
        } catch (error) {
            setFormError(errorMessage(error, 'Could not read the deployments for this connection.'));
        } finally {
            setDiscovering(false);
        }
    };

    const runConnectionTest = async () => {
        const validation = validateConnection(draft);
        delete validation.name;
        if (Object.keys(validation).length) {
            setErrors(validation);
            setFormError('Fill in the connection and authentication details first.');
            return;
        }

        setTesting(true);
        setFormError(null);
        try {
            const response = await testConnection(buildConnectionPayload(draft));
            toast.success(
                typeof response.count === 'number'
                    ? `Connected. ${response.count} chat deployment${response.count === 1 ? '' : 's'} visible.`
                    : 'Connected.',
            );
        } catch (error) {
            setFormError(errorMessage(error, 'The connection could not be reached.'));
        } finally {
            setTesting(false);
        }
    };

    const runModelTest = async (model: ConnectionModel) => {
        const deploymentName = String(model.deploymentName ?? '').trim();
        if (!deploymentName) {
            setFormError('Give the model a deployment name before testing it.');
            return;
        }
        setTestingModelId(String(model.id ?? deploymentName));
        setFormError(null);
        try {
            await testConnectionModel(buildConnectionPayload(draft), deploymentName);
            toast.success(`${deploymentName} answered.`);
        } catch (error) {
            setFormError(errorMessage(error, `${deploymentName} did not answer.`));
        } finally {
            setTestingModelId(null);
        }
    };

    const save = async () => {
        const validation = validateConnection(draft);
        if (Object.keys(validation).length) {
            setErrors(validation);
            setFormError('Some details still need attention.');
            return;
        }

        setSaving(true);
        setFormError(null);
        try {
            const payload = buildConnectionPayload(draft);
            const response = initial.id
                ? await updateModelConnection(initial.id, payload)
                : await createModelConnection(payload);
            onSaved(response.endpoint ?? {}, !initial.id);
        } catch (error) {
            setFormError(errorMessage(error, 'The connection could not be saved.'));
        } finally {
            setSaving(false);
        }
    };

    const busy = saving || discovering || testing || testingModelId !== null;
    const models = draft.models ?? [];
    const projectHint = foundry ? projectNameFromEndpoint(draft.connection?.endpoint) : '';

    return (
        <AdminModal
            title={isNew ? 'Add a connection' : `Edit ${initial.name || 'connection'}`}
            description={
                isNew
                    ? 'Nothing is stored until you choose Save.'
                    : 'Changes are stored when you choose Save.'
            }
            size="lg"
            onClose={onClose}
            footer={
                <>
                    <GlassButton type="button" variant="ghost" size="sm" onClick={onClose} disabled={saving}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        onClick={() => void save()}
                        disabled={busy}
                    >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                        {isNew ? 'Create connection' : 'Save changes'}
                    </GlassButton>
                </>
            }
        >
            {formError ? (
                <p
                    role="alert"
                    className="mb-3 flex items-start gap-2 rounded-lg border border-edge bg-danger-soft p-3 text-sm text-danger"
                >
                    <AlertCircle size={15} className="mt-0.5 shrink-0" />
                    {formError}
                </p>
            ) : null}

            <SectionHeading>Identity</SectionHeading>

            <Field label="Name" error={errors.name} htmlFor="connection-name" help="Shown wherever a model from this connection is offered.">
                <input
                    id="connection-name"
                    type="text"
                    className={inputClass}
                    value={String(draft.name ?? '')}
                    disabled={busy}
                    onChange={(event) => setField('name', event.target.value)}
                />
            </Field>

            <Field
                label="Provider"
                htmlFor="connection-provider"
                help={PROVIDER_OPTIONS.find((option) => option.value === draft.provider)?.hint}
            >
                <select
                    id="connection-provider"
                    className={inputClass}
                    value={String(draft.provider ?? 'aoai')}
                    disabled={busy}
                    onChange={(event) => setField('provider', event.target.value)}
                >
                    {PROVIDER_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </Field>

            <SectionHeading>Connection</SectionHeading>

            <Field
                label={foundry ? 'Project endpoint' : 'Endpoint URL'}
                error={errors.endpoint}
                htmlFor="connection-endpoint"
                help={
                    foundry
                        ? 'A Foundry project URL. Including /api/projects/<name> names the project for you.'
                        : 'The resource endpoint, for example https://my-resource.openai.azure.com.'
                }
            >
                <input
                    id="connection-endpoint"
                    type="url"
                    className={inputClass}
                    placeholder={foundry ? 'https://…/api/projects/my-project' : 'https://my-resource.openai.azure.com'}
                    value={String(draft.connection?.endpoint ?? '')}
                    disabled={busy}
                    spellCheck={false}
                    onChange={(event) => setField('connection.endpoint', event.target.value)}
                />
            </Field>

            <Field
                label="OpenAI API version"
                error={errors.openai_api_version}
                htmlFor="connection-openai-version"
            >
                <input
                    id="connection-openai-version"
                    type="text"
                    className={inputClass}
                    value={String(draft.connection?.openai_api_version ?? '')}
                    disabled={busy}
                    spellCheck={false}
                    onChange={(event) => setField('connection.openai_api_version', event.target.value)}
                />
            </Field>

            {shown.project ? (
                <>
                    <Field
                        label="Project API version"
                        error={errors.project_api_version}
                        htmlFor="connection-project-version"
                    >
                        <input
                            id="connection-project-version"
                            type="text"
                            className={inputClass}
                            value={String(draft.connection?.project_api_version ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) =>
                                setField('connection.project_api_version', event.target.value)
                            }
                        />
                    </Field>

                    <Field
                        label="Project name"
                        error={errors.project_name}
                        htmlFor="connection-project-name"
                        help={
                            projectHint
                                ? `Taken from the endpoint URL: ${projectHint}`
                                : 'Only needed when the endpoint URL does not include /api/projects/.'
                        }
                    >
                        <input
                            id="connection-project-name"
                            type="text"
                            className={inputClass}
                            value={String(draft.connection?.project_name ?? '')}
                            placeholder={projectHint}
                            disabled={busy}
                            onChange={(event) => setField('connection.project_name', event.target.value)}
                        />
                    </Field>
                </>
            ) : null}

            <SectionHeading
                hint={AUTH_TYPE_OPTIONS.find((option) => option.value === authType)?.hint}
            >
                Authentication
            </SectionHeading>

            <Field label="Method" htmlFor="connection-auth-type">
                <select
                    id="connection-auth-type"
                    className={inputClass}
                    value={authType}
                    disabled={busy}
                    onChange={(event) => setField('auth.type', event.target.value)}
                >
                    {AUTH_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </Field>

            {shown.managedIdentity ? (
                <>
                    <Field label="Identity" htmlFor="connection-mi-type">
                        <select
                            id="connection-mi-type"
                            className={inputClass}
                            value={String(draft.auth?.managed_identity_type ?? 'system_assigned')}
                            disabled={busy}
                            onChange={(event) => setField('auth.managed_identity_type', event.target.value)}
                        >
                            <option value="system_assigned">System assigned</option>
                            <option value="user_assigned">User assigned</option>
                        </select>
                    </Field>

                    {shown.userAssignedClientId ? (
                        <Field label="Managed identity client id" htmlFor="connection-mi-client-id">
                            <input
                                id="connection-mi-client-id"
                                type="text"
                                className={inputClass}
                                value={String(draft.auth?.managed_identity_client_id ?? '')}
                                disabled={busy}
                                spellCheck={false}
                                onChange={(event) =>
                                    setField('auth.managed_identity_client_id', event.target.value)
                                }
                            />
                        </Field>
                    ) : null}
                </>
            ) : null}

            {shown.servicePrincipal ? (
                <>
                    <Field label="Tenant id" error={errors.tenant_id} htmlFor="connection-tenant-id">
                        <input
                            id="connection-tenant-id"
                            type="text"
                            className={inputClass}
                            value={String(draft.auth?.tenant_id ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) => setField('auth.tenant_id', event.target.value)}
                        />
                    </Field>
                    <Field label="Client id" error={errors.client_id} htmlFor="connection-client-id">
                        <input
                            id="connection-client-id"
                            type="text"
                            className={inputClass}
                            value={String(draft.auth?.client_id ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) => setField('auth.client_id', event.target.value)}
                        />
                    </Field>
                    <Field
                        label="Client secret"
                        error={errors.client_secret}
                        htmlFor="connection-client-secret"
                        help={
                            draft.has_client_secret
                                ? 'A secret is stored. Leave this blank to keep it, or type a new one to replace it.'
                                : 'Stored in Key Vault when Key Vault is configured.'
                        }
                    >
                        <input
                            id="connection-client-secret"
                            type="password"
                            autoComplete="new-password"
                            className={inputClass}
                            placeholder={draft.has_client_secret ? '••••••••  (stored)' : ''}
                            value={String(draft.auth?.client_secret ?? '')}
                            disabled={busy}
                            onChange={(event) => setField('auth.client_secret', event.target.value)}
                        />
                    </Field>
                </>
            ) : null}

            {shown.apiKey ? (
                <Field
                    label="API key"
                    error={errors.api_key}
                    htmlFor="connection-api-key"
                    help={
                        draft.has_api_key
                            ? 'A key is stored. Leave this blank to keep it, or type a new one to replace it.'
                            : 'Stored in Key Vault when Key Vault is configured.'
                    }
                >
                    <input
                        id="connection-api-key"
                        type="password"
                        autoComplete="new-password"
                        className={inputClass}
                        placeholder={draft.has_api_key ? '••••••••  (stored)' : ''}
                        value={String(draft.auth?.api_key ?? '')}
                        disabled={busy}
                        onChange={(event) => setField('auth.api_key', event.target.value)}
                    />
                </Field>
            ) : null}

            {shown.managementCloud ? (
                <Field label="Management cloud" htmlFor="connection-cloud">
                    <select
                        id="connection-cloud"
                        className={inputClass}
                        value={String(draft.auth?.management_cloud ?? 'public')}
                        disabled={busy}
                        onChange={(event) => setField('auth.management_cloud', event.target.value)}
                    >
                        {MANAGEMENT_CLOUD_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </Field>
            ) : null}

            {shown.customAuthority ? (
                <Field
                    label="Custom authority"
                    error={errors.custom_authority}
                    htmlFor="connection-authority"
                >
                    <input
                        id="connection-authority"
                        type="text"
                        className={inputClass}
                        value={String(draft.auth?.custom_authority ?? '')}
                        disabled={busy}
                        spellCheck={false}
                        onChange={(event) => setField('auth.custom_authority', event.target.value)}
                    />
                </Field>
            ) : null}

            {shown.foundryScope ? (
                <Field
                    label="Foundry scope"
                    error={errors.foundry_scope}
                    htmlFor="connection-foundry-scope"
                    help="The token audience used when calling the project. Required only for a custom cloud."
                >
                    <input
                        id="connection-foundry-scope"
                        type="text"
                        className={inputClass}
                        value={String(draft.auth?.foundry_scope ?? '')}
                        disabled={busy}
                        spellCheck={false}
                        onChange={(event) => setField('auth.foundry_scope', event.target.value)}
                    />
                </Field>
            ) : null}

            {shown.management ? (
                <>
                    <SectionHeading hint="Model discovery reads deployments through Azure Resource Manager, which needs the resource coordinates.">
                        Discovery
                    </SectionHeading>
                    <Field
                        label="Subscription id"
                        error={errors.subscription_id}
                        htmlFor="connection-subscription"
                    >
                        <input
                            id="connection-subscription"
                            type="text"
                            className={inputClass}
                            value={String(draft.management?.subscription_id ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) => setField('management.subscription_id', event.target.value)}
                        />
                    </Field>
                    <Field
                        label="Resource group"
                        error={errors.resource_group}
                        htmlFor="connection-resource-group"
                    >
                        <input
                            id="connection-resource-group"
                            type="text"
                            className={inputClass}
                            value={String(draft.management?.resource_group ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) => setField('management.resource_group', event.target.value)}
                        />
                    </Field>
                </>
            ) : null}

            <SectionHeading
                hint={
                    shown.apiKey
                        ? 'Discovery needs Azure credentials, so with an API key the models have to be listed by hand.'
                        : 'Discovered models arrive switched off. Turn on the ones people may use.'
                }
            >
                Models
            </SectionHeading>

            <div className="mb-3 flex flex-wrap gap-2">
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => void runDiscovery()}
                    disabled={busy || shown.apiKey}
                >
                    {discovering ? (
                        <Loader2 size={14} className="animate-spin" />
                    ) : (
                        <RefreshCw size={14} />
                    )}
                    Discover models
                </GlassButton>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => void runConnectionTest()}
                    disabled={busy}
                >
                    {testing ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                    Test connection
                </GlassButton>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                        setModels([
                            ...models,
                            {
                                id: `model-${models.length + 1}-${Date.now()}`,
                                deploymentName: '',
                                displayName: '',
                                enabled: false,
                            },
                        ])
                    }
                >
                    <Plus size={14} />
                    Add manually
                </GlassButton>
            </div>

            {models.length === 0 ? (
                <p className="rounded-lg border border-edge bg-surface-1 p-3 text-xs text-text-3">
                    No models yet. Discover them from the connection, or add one by deployment name.
                </p>
            ) : (
                <ul className="space-y-2">
                    {models.map((model, index) => {
                        const key = String(model.id ?? index);
                        return (
                            <li
                                key={key}
                                className="rounded-lg border border-edge bg-surface-1 p-3"
                            >
                                <div className="flex items-start gap-2">
                                    <label className="flex flex-1 items-center gap-2">
                                        <input
                                            type="checkbox"
                                            className="accent-[var(--accent)]"
                                            checked={model.enabled !== false}
                                            disabled={busy}
                                            aria-label={`Enable ${model.deploymentName || 'model'}`}
                                            onChange={(event) => {
                                                const next = [...models];
                                                next[index] = {
                                                    ...model,
                                                    enabled: event.target.checked,
                                                };
                                                setModels(next);
                                            }}
                                        />
                                        <span className="text-xs text-text-3">Available</span>
                                    </label>
                                    {model.isDiscovered ? <Pill tone="muted">Discovered</Pill> : null}
                                    <button
                                        type="button"
                                        title={`Test ${model.deploymentName || 'model'}`}
                                        aria-label={`Test ${model.deploymentName || 'model'}`}
                                        disabled={busy}
                                        onClick={() => void runModelTest(model)}
                                        className="rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:opacity-50"
                                    >
                                        {testingModelId === String(model.id ?? model.deploymentName) ? (
                                            <Loader2 size={14} className="animate-spin" />
                                        ) : (
                                            <Zap size={14} />
                                        )}
                                    </button>
                                    <button
                                        type="button"
                                        title={`Remove ${model.deploymentName || 'model'}`}
                                        aria-label={`Remove ${model.deploymentName || 'model'}`}
                                        disabled={busy}
                                        onClick={() =>
                                            setModels(models.filter((_, at) => at !== index))
                                        }
                                        className="rounded-lg p-1 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>

                                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                    <input
                                        type="text"
                                        className={inputClass}
                                        placeholder="Deployment name"
                                        aria-label="Deployment name"
                                        value={String(model.deploymentName ?? '')}
                                        disabled={busy}
                                        spellCheck={false}
                                        onChange={(event) => {
                                            const next = [...models];
                                            next[index] = {
                                                ...model,
                                                deploymentName: event.target.value,
                                            };
                                            setModels(next);
                                        }}
                                    />
                                    <input
                                        type="text"
                                        className={inputClass}
                                        placeholder="Display name"
                                        aria-label="Display name"
                                        value={String(model.displayName ?? '')}
                                        disabled={busy}
                                        onChange={(event) => {
                                            const next = [...models];
                                            next[index] = {
                                                ...model,
                                                displayName: event.target.value,
                                            };
                                            setModels(next);
                                        }}
                                    />
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}

            <SectionHeading hint="Overrides the identity header setting for this connection only.">
                Identity header
            </SectionHeading>

            <Field label="Mode" htmlFor="connection-identity-mode">
                <select
                    id="connection-identity-mode"
                    className={inputClass}
                    value={String(draft.identity_header?.mode ?? 'inherit')}
                    disabled={busy}
                    onChange={(event) => setField('identity_header.mode', event.target.value)}
                >
                    {IDENTITY_HEADER_MODE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </Field>

            {String(draft.identity_header?.mode ?? 'inherit') !== 'disabled' ? (
                <>
                    <Field
                        label="Header name override"
                        htmlFor="connection-identity-name"
                        help="Leave blank to use the name configured for all connections."
                    >
                        <input
                            id="connection-identity-name"
                            type="text"
                            className={inputClass}
                            value={String(draft.identity_header?.header_name ?? '')}
                            disabled={busy}
                            spellCheck={false}
                            onChange={(event) =>
                                setField('identity_header.header_name', event.target.value)
                            }
                        />
                    </Field>
                    <Field label="Identity override" htmlFor="connection-identity-value">
                        <select
                            id="connection-identity-value"
                            className={inputClass}
                            value={String(draft.identity_header?.value_type ?? '')}
                            disabled={busy}
                            onChange={(event) =>
                                setField('identity_header.value_type', event.target.value)
                            }
                        >
                            {IDENTITY_VALUE_TYPE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </Field>
                </>
            ) : null}
        </AdminModal>
    );
}

/* -------------------------------------------------------------------------- */
/* Manager                                                                     */
/* -------------------------------------------------------------------------- */

export function ModelConnectionsManager({ help }: { help?: string }) {
    const [connections, setConnections] = useState<ModelConnection[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [editing, setEditing] = useState<ModelConnection | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

    // Turning connections on seeds this list server-side with the classic chat endpoint,
    // and that save happens in the section above rather than here. Without a reload the
    // list would keep reading as empty at the exact moment it stopped being so.
    const connectionsRevision = useModelConnectionsStore((state) => state.revision);

    const load = useCallback(async (signal?: AbortSignal) => {
        try {
            const response = await fetchModelConnections(signal);
            setConnections(Array.isArray(response.endpoints) ? response.endpoints : []);
            setError(null);
        } catch (loadError) {
            if (signal?.aborted) {
                return;
            }
            setError(errorMessage(loadError, 'Model connections could not be loaded.'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
    }, [load, connectionsRevision]);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return connections;
        }
        return connections.filter((connection) =>
            `${connection.name ?? ''} ${connection.provider ?? ''} ${connection.connection?.endpoint ?? ''}`
                .toLowerCase()
                .includes(needle),
        );
    }, [connections, query]);

    const onToggle = async (connection: ModelConnection) => {
        const previous = connections;
        const next = connection.enabled === false;
        setBusyId(connection.id);
        setConnections(
            connections.map((item) =>
                item.id === connection.id ? { ...item, enabled: next } : item,
            ),
        );
        try {
            // A partial update, so the stripped secrets in the copy held here are never
            // sent back and cannot overwrite what is stored.
            await updateModelConnection(connection.id, { enabled: next });
            modelConnectionsChanged();
        } catch (toggleError) {
            setConnections(previous);
            setError(errorMessage(toggleError, 'The connection could not be updated.'));
        } finally {
            setBusyId(null);
        }
    };

    const onDelete = async (connection: ModelConnection) => {
        const previous = connections;
        setBusyId(connection.id);
        setConfirmDeleteId(null);
        setConnections(connections.filter((item) => item.id !== connection.id));
        try {
            await deleteModelConnection(connection.id);
            modelConnectionsChanged();
            toast.success(`Deleted ${connection.name || 'connection'}.`);
        } catch (deleteError) {
            setConnections(previous);
            setError(errorMessage(deleteError, 'The connection could not be deleted.'));
        } finally {
            setBusyId(null);
        }
    };

    const onSaved = (saved: ModelConnection, created: boolean) => {
        setEditing(null);
        setError(null);
        modelConnectionsChanged();
        if (created) {
            setConnections((current) => [...current, saved]);
            toast.success(`Created ${saved.name || 'connection'}.`);
        } else {
            setConnections((current) =>
                current.map((item) => (item.id === saved.id ? saved : item)),
            );
            toast.success(`Saved ${saved.name || 'connection'}.`);
        }
    };

    return (
        <div className="py-3">
            <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-text-1">Connections</span>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => setEditing(emptyConnection())}
                >
                    <Plus size={14} />
                    Add connection
                </GlassButton>
            </div>

            {help ? <p className="mb-3 text-xs leading-relaxed text-text-3">{help}</p> : null}

            {error ? (
                <p
                    role="alert"
                    className="mb-3 flex items-start gap-2 rounded-lg border border-edge bg-danger-soft p-3 text-xs text-danger"
                >
                    <AlertCircle size={14} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}

            {connections.length > 3 ? (
                <div className="relative mb-3">
                    <Search
                        size={14}
                        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search connections"
                        aria-label="Search connections"
                        className={clsx(inputClass, 'pl-8')}
                    />
                </div>
            ) : null}

            {loading ? (
                <p className="flex items-center gap-2 py-4 text-xs text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading connections…
                </p>
            ) : visible.length === 0 ? (
                <p className="rounded-lg border border-edge bg-surface-1 p-4 text-xs text-text-3">
                    {connections.length === 0
                        ? 'No connections yet. Add one to publish models from an Azure OpenAI or Foundry resource.'
                        : 'No connections match your search.'}
                </p>
            ) : (
                <ul className="space-y-2">
                    {visible.map((connection) => {
                        const total = connection.models?.length ?? 0;
                        const available = enabledModelCount(connection);
                        return (
                            <li
                                key={connection.id}
                                className="flex items-start gap-3 rounded-lg border border-edge bg-surface-1 p-3"
                            >
                                <span className="mt-0.5 shrink-0 text-text-3">
                                    <Server size={17} />
                                </span>

                                <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="truncate text-sm font-medium text-text-1">
                                            {connection.name || 'Untitled connection'}
                                        </span>
                                        <Pill tone={connection.enabled === false ? 'muted' : 'ok'}>
                                            {connection.enabled === false ? 'Disabled' : 'Enabled'}
                                        </Pill>
                                        {total > 0 && available === 0 ? (
                                            <Pill tone="warn">No models available</Pill>
                                        ) : null}
                                    </div>
                                    <p className="mt-0.5 truncate text-xs text-text-3">
                                        {providerLabel(connection.provider)} ·{' '}
                                        {authTypeLabel(connection.auth?.type)} ·{' '}
                                        {total === 0
                                            ? 'no models'
                                            : `${available} of ${total} model${total === 1 ? '' : 's'} available`}
                                    </p>
                                    {connection.connection?.endpoint ? (
                                        <p className="truncate font-mono text-[11px] text-text-3">
                                            {String(connection.connection.endpoint)}
                                        </p>
                                    ) : null}
                                </div>

                                <div className="flex shrink-0 items-center gap-1">
                                    <button
                                        type="button"
                                        title={connection.enabled === false ? 'Enable' : 'Disable'}
                                        aria-label={`${connection.enabled === false ? 'Enable' : 'Disable'} ${connection.name ?? 'connection'}`}
                                        disabled={busyId === connection.id}
                                        onClick={() => void onToggle(connection)}
                                        className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:opacity-50"
                                    >
                                        {busyId === connection.id ? (
                                            <Loader2 size={15} className="animate-spin" />
                                        ) : (
                                            <Power size={15} />
                                        )}
                                    </button>
                                    <button
                                        type="button"
                                        title="Edit"
                                        aria-label={`Edit ${connection.name ?? 'connection'}`}
                                        onClick={() => setEditing(connection)}
                                        className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                                    >
                                        <Pencil size={15} />
                                    </button>
                                    <button
                                        type="button"
                                        title="Delete"
                                        aria-label={`Delete ${connection.name ?? 'connection'}`}
                                        disabled={busyId === connection.id}
                                        onClick={() => setConfirmDeleteId(connection.id)}
                                        className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                                    >
                                        <Trash2 size={15} />
                                    </button>
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}

            {editing ? (
                <ConnectionEditor
                    initial={editing}
                    onClose={() => setEditing(null)}
                    onSaved={onSaved}
                />
            ) : null}

            {confirmDeleteId ? (
                <AdminModal
                    title="Delete this connection?"
                    description="Models published from it stop being offered, and any stored key or secret is removed."
                    onClose={() => setConfirmDeleteId(null)}
                    footer={
                        <>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setConfirmDeleteId(null)}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                onClick={() => {
                                    const target = connections.find(
                                        (item) => item.id === confirmDeleteId,
                                    );
                                    if (target) {
                                        void onDelete(target);
                                    }
                                }}
                            >
                                <Trash2 size={14} />
                                Delete
                            </GlassButton>
                        </>
                    }
                >
                    <p className="text-sm text-text-2">
                        {connections.find((item) => item.id === confirmDeleteId)?.name ||
                            'This connection'}{' '}
                        will be removed. If it is the default model for chat, that default is
                        cleared too.
                    </p>
                </AdminModal>
            ) : null}
        </div>
    );
}
