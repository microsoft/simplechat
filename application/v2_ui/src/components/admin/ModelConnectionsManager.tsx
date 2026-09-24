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

import { useCallback, useEffect, useId, useMemo, useState } from 'react';
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
import { capabilityDescription, embeddingPolicyDescription, testCapabilityModel, type ImageModelCapabilityStatus } from '../../lib/capabilityModels';
import {
    connectionRequestModel, connectionUsesModelName, CUSTOM_AUTH_TYPE_OPTIONS,
    EMPTY_CUSTOM_NETWORK_POLICY, type CustomApiTypeDescriptor, type CustomNetworkPolicy,
} from '../../lib/customModelConnections';
import {
    AUTH_TYPE_OPTIONS,
    CAPABILITY_OPTIONS,
    IDENTITY_HEADER_MODE_OPTIONS,
    IDENTITY_VALUE_TYPE_OPTIONS,
    MANAGEMENT_CLOUD_OPTIONS,
    PROVIDER_OPTIONS,
    authTypeLabel,
    buildConnectionPayload,
    createAdminModelConnectionsAdapter,
    defaultOpenAiApiVersion,
    defaultEmbeddingApi,
    emptyConnection,
    embeddingConnectionUnavailableReason,
    enabledModelCount,
    EndpointConflictError,
    EndpointInUseError,
    GroupWriteConflictError,
    isFoundryProvider,
    isKnownEmbeddingModel,
    mergeDiscoveredModels,
    modelPublishesCapability,
    modelNeedsEmbeddingGateway,
    modelSupportsCapability,
    projectNameFromEndpoint,
    providerLabel,
    setModelCapabilityEnabled,
    setEmbeddingOperation,
    toEditableConnection,
    validateConnection,
    visibleFields,
    type ConnectionModel,
    type ConnectionMigrationNotice,
    type EmbeddingConfig,
    type EmbeddingOperationSettings,
    type EndpointReference,
    type ImplementedCapability,
    type ModelConnection,
    type ModelConnectionsAdapter,
} from '../../lib/modelConnections';
import { AdminModal } from './AdminModal';
import { CatalogProfilePicker } from './ModelCatalogManager';
import { CustomAuthenticationFields, CustomConnectionFields } from './CustomConnectionFields';
import { CustomNetworkPolicyEditor } from './CustomNetworkPolicyEditor';
import { GlassButton } from '../ui/primitives';
import { useModelConnectionsStore, modelConnectionsChanged } from '../../stores/modelConnectionsStore';
import { toast } from '../../stores/toastStore';

// The admin surface's adapter, built once. It routes every call straight to the global
// /api/v2/admin/model-endpoints and shared /api/models/* routes and fires the shared revision store,
// so the admin experience stays byte-identical to the pre-adapter direct calls.
const ADMIN_MODEL_CONNECTIONS_ADAPTER: ModelConnectionsAdapter = createAdminModelConnectionsAdapter(modelConnectionsChanged);

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

function ModelCapabilities({ model, connection, disabled, errors, onChange }: {
    model: ConnectionModel;
    connection: ModelConnection;
    disabled: boolean;
    errors: Record<string, string>;
    onChange: (next: ConnectionModel) => void;
}) {
    const metadataId = useId();
    const embeddingOnly = connection.provider === 'openai_compatible';
    const embeddingUnavailableReason = embeddingConnectionUnavailableReason(connection);
    const capabilities = CAPABILITY_OPTIONS.filter(({ key }) => !embeddingOnly || key === 'embeddings');
    const embedding = embeddingOnly || modelSupportsCapability(model, 'embeddings') || isKnownEmbeddingModel(model) || Boolean(model.embedding_config);
    const imageStatus: ImageModelCapabilityStatus | undefined = model.capability_status?.image_generation;
    const setEmbeddingConfig = (key: keyof EmbeddingConfig, value: string | boolean) => {
        const config = { ...model.embedding_config };
        if (value === '') {
            delete config[key];
        } else {
            Object.assign(config, {
                [key]: key === 'dimensions' || key === 'max_input_tokens' ? Number(value) : value,
            });
        }
        const next: ConnectionModel = { ...model, embedding_config: config };
        delete next.capability_status;
        if (!Object.keys(config).length) delete next.embedding_config;
        onChange(next);
    };
    return (
        <div className="mt-3 space-y-2">
            {capabilities.map(({ key, label }) => (
                <div key={key}>
                    <label className="flex items-center gap-2 text-xs text-text-2">
                        <input
                            type="checkbox"
                            className="accent-[var(--accent)]"
                            checked={!(key === 'embeddings' && embeddingUnavailableReason) && modelSupportsCapability(model, key) && (!model.enabled_capabilities || model.enabled_capabilities.includes(key))}
                            disabled={disabled || !modelSupportsCapability(model, key) || (key === 'embeddings' && Boolean(embeddingUnavailableReason))}
                            onChange={(event) => onChange(setModelCapabilityEnabled(model, key, event.target.checked))}
                        />
                        Use for {label}
                    </label>
                    <p className="mt-1 text-xs text-text-3">{key === 'embeddings' && embeddingUnavailableReason || capabilityDescription(model.capability_status?.[key], key)}</p>
                </div>
            ))}
            {!embeddingOnly && model.capability_status?.vision ? (
                <p className="text-xs text-text-3">
                    Image input (vision): {model.capability_status.vision.supported ? 'supported' : 'not supported'}
                    {' · '}{model.capability_status.vision.source}. This is separate from image output.
                </p>
            ) : null}
            {embedding ? <p className="text-xs text-text-3">{embeddingPolicyDescription(model.embedding_policy)}</p> : null}
            {!embeddingOnly && imageStatus?.supported ? (
                <p className="text-xs text-text-3">
                    {[imageStatus.provider_label, imageStatus.cloud_label, imageStatus.lifecycle].filter(Boolean).join(' · ')}
                    {' · '}{imageStatus.masking ? 'Masked and whole-image edits'
                        : imageStatus.editing ? 'Reference-image edits; no uploaded masks' : 'Generation only'}
                </p>
            ) : null}
            {imageStatus?.availability_reason ? (
                <p className="text-xs text-warn">{imageStatus.availability_reason}</p>
            ) : null}
            {model.enabled === false ? <p className="text-xs text-warn">Model is disabled. Enable it and save to publish the selected uses.</p> : null}
            <details className="text-xs text-text-3" open={embeddingOnly ? true : undefined}>
                <summary className="cursor-pointer py-1 text-text-2">Capability metadata</summary>
                <p className="mb-2">Use automatic metadata unless you have verified the deployment’s capabilities. Saving rechecks provider compatibility; this is not an inference test.</p>
                {([
                    ['supportsChat', 'Text output support'],
                    ['supportsImageGeneration', 'Image generation support'],
                    ['supportsImageEditing', 'Source-image editing support'],
                    ['supportsImageMasking', 'Uploaded-mask support'],
                    ['supportsVision', 'Image input support'],
                    ['supportsEmbeddings', 'Text embedding support'],
                ] as const).filter(([key]) => !embeddingOnly || key === 'supportsEmbeddings').map(([key, label]) => (
                    <div key={key} className="mt-2">
                        <label htmlFor={`${metadataId}-${key}`} className="mb-1 block">{label}</label>
                        <select
                            id={`${metadataId}-${key}`}
                            className={inputClass}
                            value={typeof model[key] === 'boolean' ? String(model[key]) : ''}
                            disabled={disabled || (isKnownEmbeddingModel(model) && key !== 'supportsEmbeddings') || (key === 'supportsEmbeddings' && Boolean(embeddingUnavailableReason))}
                            onChange={(event) => {
                                const next = { ...model };
                                delete next.capability_status;
                                if (event.target.value === '') {
                                    delete next[key];
                                } else {
                                    next[key] = event.target.value === 'true';
                                }
                                onChange(next);
                            }}
                        >
                            <option value="">Automatic</option>
                            <option value="true">Supported (verified by administrator)</option>
                            <option value="false">Not supported</option>
                        </select>
                        {errors[key] ? <p role="alert" className="mt-1 text-danger">{errors[key]}</p> : null}
                    </div>
                ))}
                {embedding ? (
                    <div className="mt-3 border-t border-edge pt-2">
                        <p className="mb-2">Leave overrides blank to retain catalog defaults. Unknown models require declared embedding support, dimensions and an input token limit. Setting dimensions is an explicit model change, not an automatic resize.</p>
                        {([
                            ['dimensions', 'Embedding dimensions'],
                            ['max_input_tokens', 'Embedding input token limit'],
                        ] as const).map(([key, label]) => (
                            <Field key={key} label={label} htmlFor={`${metadataId}-${key}`} error={errors[key]}>
                                <input
                                    id={`${metadataId}-${key}`}
                                    className={inputClass}
                                    type="number"
                                    min="1"
                                    step="1"
                                    placeholder={model.embedding_policy?.[key] ? `Catalog: ${model.embedding_policy[key]}` : isKnownEmbeddingModel(model) ? 'Use catalog default' : 'Required for an unknown model'}
                                    value={model.embedding_config?.[key] ?? ''}
                                    disabled={disabled || Boolean(embeddingUnavailableReason)}
                                    onChange={(event) => setEmbeddingConfig(key, event.target.value)}
                                />
                            </Field>
                        ))}
                        <Field label="Embedding model revision" htmlFor={`${metadataId}-revision`} help="Optional for known models; identify a custom deployment revision so vector-space changes are detectable.">
                            <input
                                id={`${metadataId}-revision`}
                                className={inputClass}
                                type="text"
                                value={model.embedding_config?.model_revision ?? ''}
                                disabled={disabled || Boolean(embeddingUnavailableReason)}
                                onChange={(event) => setEmbeddingConfig('model_revision', event.target.value)}
                            />
                        </Field>
                        {embeddingOnly || modelNeedsEmbeddingGateway(model) || model.embedding_policy?.api === 'unsupported' || model.embedding_config?.openai_compatible !== undefined ? (
                            <Field label="Verified OpenAI-compatible gateway" htmlFor={`${metadataId}-compatible`} help="Declare only a verified gateway exposing the supported text embedding contract. Vendor-native and deprecated inference APIs are not supported.">
                                <select
                                    id={`${metadataId}-compatible`}
                                    className={inputClass}
                                    value={model.embedding_config?.openai_compatible === undefined ? '' : String(model.embedding_config.openai_compatible)}
                                    disabled={disabled || Boolean(embeddingUnavailableReason)}
                                    onChange={(event) => setEmbeddingConfig('openai_compatible', event.target.value === '' ? '' : event.target.value === 'true')}
                                >
                                    <option value="">Use catalog compatibility</option>
                                    <option value="true">Verified compatible gateway</option>
                                    <option value="false">Not compatible</option>
                                </select>
                            </Field>
                        ) : null}
                    </div>
                ) : null}
                {!embeddingOnly ? <div className="mt-2">
                    <label htmlFor={`${metadataId}-image-api`} className="mb-1 block">Image API for explicit metadata</label>
                    <select
                        id={`${metadataId}-image-api`}
                        className={inputClass}
                        value={model.image_generation_api ?? ''}
                        disabled={disabled || isKnownEmbeddingModel(model)}
                        onChange={(event) => {
                            const next = { ...model };
                            const value = event.target.value;
                            delete next.capability_status;
                            if (value === '') {
                                delete next.image_generation_api;
                            } else if (value === 'images' || value === 'responses' || value === 'mai' || value === 'flux') {
                                next.image_generation_api = value;
                            } else {
                                toast.error('The image API is not supported.');
                                return;
                            }
                            onChange(next);
                        }}
                    >
                        <option value="">Automatic (catalog)</option>
                        <option value="images">Images API</option>
                        <option value="responses">OpenAI Responses image tool</option>
                        <option value="mai">Foundry MAI Image</option>
                        <option value="flux">Foundry FLUX</option>
                    </select>
                    <p className="mt-1">
                        Unknown Custom image models need an explicit compatible API. Editing and masks
                        are separate capabilities; declarations cannot override provider restrictions.
                    </p>
                </div> : null}
            </details>
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Editor                                                                      */
/* -------------------------------------------------------------------------- */

function ConnectionEditor({
    initial,
    customApiTypes,
    adapter,
    onClose,
    onSaved,
    onReloadEndpoint,
}: {
    initial: ModelConnection;
    customApiTypes: CustomApiTypeDescriptor[];
    adapter: ModelConnectionsAdapter;
    onClose: () => void;
    onSaved: (saved: ModelConnection, created: boolean) => void;
    /**
     * Reload the latest stored copy of this endpoint after a stale-revision conflict, returning the
     * fresh row so a re-save carries its new revision. Provided only in group scope; admin never
     * conflicts, so it stays undefined and the reload affordance never appears.
     */
    onReloadEndpoint?: (id: string) => Promise<ModelConnection | null>;
}) {
    // The baseline the editor saves against. It starts as the row that opened the editor and is
    // replaced only when a conflict reload pulls the latest revision, so the user's field edits in
    // `draft` are preserved across a reload while the conditional-write token refreshes.
    const [current, setCurrent] = useState<ModelConnection>(initial);
    const [draft, setDraft] = useState<ModelConnection>(() => toEditableConnection(initial));
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [saving, setSaving] = useState(false);
    const [discovering, setDiscovering] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testingModelId, setTestingModelId] = useState<string | null>(null);
    const [formError, setFormError] = useState<string | null>(null);
    // A stale-revision conflict keeps the draft and offers a reload rather than losing the edit.
    const [needsReload, setNeedsReload] = useState(false);
    const [reloading, setReloading] = useState(false);

    const isNew = !initial.id;
    const foundry = isFoundryProvider(draft.provider);
    const embeddingOnly = draft.provider === 'openai_compatible';
    const embeddingOperation = draft.connection?.operation_settings?.embeddings;
    const embeddingApi = embeddingOperation?.api || defaultEmbeddingApi(draft);
    const embeddingUnavailableReason = embeddingConnectionUnavailableReason(draft);
    const custom = draft.provider === 'custom';
    const usesModelName = connectionUsesModelName(draft);
    const authType = String(draft.auth?.type ?? (custom || embeddingOnly ? 'api_key' : 'managed_identity'));
    const authOptions = custom ? CUSTOM_AUTH_TYPE_OPTIONS : AUTH_TYPE_OPTIONS.filter((option) => !embeddingOnly || option.value === 'api_key');
    // A saved endpoint may run a chat model test when the scope allows testing: admin always, a
    // group manager when the row carries the `test` action. The image and embedding capability tests
    // use an admin-settings route with no group equivalent, so they render only for the admin scope.
    const canTestChat = adapter.canTestConnection || adapter.allows('test', initial);
    const canTestCapabilities = adapter.canTestCapabilities;
    // Whether this scope may persist the editor: a new row needs create, an existing one needs edit.
    // Admin allows both, so its editor is unchanged; a group member viewing a row cannot save.
    const canSave = isNew ? adapter.canCreate : adapter.allows('edit', initial);

    const shown = useMemo(() => visibleFields(draft), [draft]);
    const savedBinding = !isNew && JSON.stringify(buildConnectionPayload(draft)) ===
        JSON.stringify(buildConnectionPayload(toEditableConnection(current)));

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
            if (path === 'name' || path === 'provider' || path === 'enabled' || path === 'api_type') {
                (next as Record<string, unknown>)[path] = value;
                // Switching provider changes which API version default applies, and the
                // previous provider's default would otherwise be silently carried over.
                if (path === 'provider') {
                    next.connection = {
                        ...next.connection,
                        openai_api_version: defaultOpenAiApiVersion(value),
                    };
                    if (value === 'custom') {
                        next.api_type = next.api_type || 'openai';
                        next.connection.openai_api_version = '';
                        next.auth = { ...next.auth, type: 'api_key' };
                    } else if (value === 'openai_compatible') {
                        next.auth = { ...next.auth, type: 'api_key' };
                    } else if (current.provider === 'custom') {
                        next.auth = { ...next.auth, type: 'managed_identity' };
                    }
                    next.models = next.models?.map(({ capability_status: _status, ...model }) => model);
                }
                if (path === 'api_type') {
                    const descriptor = customApiTypes.find((option) => option.value === value);
                    next.connection = { ...next.connection, api_version: '', anthropic_version: descriptor?.defaultVersion || '' };
                    next.auth = { ...next.auth, api_key_header: '', api_key_prefix: descriptor?.defaultApiKeyPrefix || '' };
                    next.models = next.models?.map(({ capability_status: _status, ...model }) => model);
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
    }, [customApiTypes]);

    const setModels = useCallback((models: ConnectionModel[]) => {
        setDraft((current) => ({ ...current, models }));
    }, []);

    const setOperation = (key: keyof EmbeddingOperationSettings, value: string | boolean) => {
        setDraft((current) => setEmbeddingOperation(current, key, value));
        setErrors((current) => {
            const next = { ...current };
            delete next[`embedding_${key}`];
            return next;
        });
    };

    const runDiscovery = async () => {
        const validation = validateConnection(draft, { requireDiscovery: true });
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
            const response = await adapter.discover(buildConnectionPayload(draft));
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
        if (custom) return;
        const validation = validateConnection(draft, { requireDiscovery: !embeddingOnly });
        delete validation.name;
        if (Object.keys(validation).length) {
            setErrors(validation);
            setFormError('Fill in the connection and authentication details first.');
            return;
        }

        setTesting(true);
        setFormError(null);
        try {
            const response = await adapter.testConnection(buildConnectionPayload(draft));
            toast.success(
                response.validation_only
                    ? response.message || 'Configuration validated. Inference was not tested.'
                    : typeof response.count === 'number'
                    ? `Connected. ${response.count} deployment${response.count === 1 ? '' : 's'} visible. Image inference was not tested.`
                    : 'Connected. Image inference was not tested.',
            );
        } catch (error) {
            setFormError(errorMessage(error, 'The connection could not be reached.'));
        } finally {
            setTesting(false);
        }
    };

    const runModelTest = async (model: ConnectionModel, capability: ImplementedCapability) => {
        if (embeddingOnly && capability !== 'embeddings') return;
        if (capability !== 'chat' && !savedBinding) {
            setFormError(`Save the connection first. ${capability === 'embeddings' ? 'Embedding' : 'Image'} tests use only the saved model and credentials.`);
            return;
        }
        if (capability === 'embeddings' && embeddingUnavailableReason) {
            setFormError(embeddingUnavailableReason);
            return;
        }
        const deploymentName = connectionRequestModel(draft, model);
        if (!deploymentName) {
            setFormError(`Give the model a ${usesModelName ? 'model name' : 'deployment name'} before testing it.`);
            return;
        }
        setTestingModelId(String(model.id ?? deploymentName));
        setFormError(null);
        try {
            if (capability !== 'chat') {
                const response = await testCapabilityModel(capability, {
                    endpoint_id: current.id,
                    model_id: String(model.id || connectionRequestModel(current, model)),
                    provider: String(current.provider || ''),
                });
                if (response.success !== true) {
                    throw new Error(response.error || 'The saved model did not return a valid result.');
                }
                if (capability === 'embeddings') {
                    if (!Number.isSafeInteger(response.dimensions) || Number(response.dimensions) <= 0) {
                        throw new Error('The saved embedding model did not return valid vector dimensions.');
                    }
                    toast.success(`${deploymentName} returned ${response.dimensions?.toLocaleString()} dimensions. No vectors were stored and the default was not changed.`);
                } else {
                    toast.success(`${deploymentName} generated an image.`);
                }
            } else {
                await adapter.testConnectionModel(buildConnectionPayload(draft), model);
                toast.success(`${deploymentName} answered a chat request. Image inference was not tested.`);
            }
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
        setNeedsReload(false);
        try {
            const payload = buildConnectionPayload(draft);
            const response = initial.id
                ? await adapter.update(current, payload)
                : await adapter.create(payload);
            onSaved(response.endpoint ?? {}, !initial.id);
        } catch (error) {
            // A stale-revision conflict keeps the draft and offers a reload; a concurrent unrelated
            // group write keeps the draft for a plain retry; anything else, including the server's
            // reviewed 400 text, is shown verbatim with the draft preserved.
            if (error instanceof EndpointConflictError) {
                setFormError(error.message);
                setNeedsReload(Boolean(onReloadEndpoint));
            } else if (error instanceof GroupWriteConflictError) {
                setFormError(error.message);
            } else {
                setFormError(errorMessage(error, 'The connection could not be saved.'));
            }
        } finally {
            setSaving(false);
        }
    };

    const reloadLatest = async () => {
        if (!onReloadEndpoint || !current.id) {
            return;
        }
        setReloading(true);
        try {
            const fresh = await onReloadEndpoint(current.id);
            if (fresh) {
                setCurrent(fresh);
                setNeedsReload(false);
                setFormError('Reloaded the latest saved version. Review your changes, then save again.');
            } else {
                setFormError('This connection is no longer available. Close the editor and refresh the list.');
            }
        } catch (error) {
            setFormError(errorMessage(error, 'Could not reload the latest version.'));
        } finally {
            setReloading(false);
        }
    };

    const busy = saving || discovering || testing || reloading || testingModelId !== null;
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
                        {canSave ? 'Cancel' : 'Close'}
                    </GlassButton>
                    {canSave ? (
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
                    ) : null}
                </>
            }
        >
            {formError ? (
                <p
                    role="alert"
                    className="mb-3 flex items-start gap-2 rounded-lg border border-edge bg-danger-soft p-3 text-sm text-danger"
                >
                    <AlertCircle size={15} className="mt-0.5 shrink-0" />
                    <span className="flex-1">{formError}</span>
                    {needsReload ? (
                        <GlassButton type="button" variant="subtle" size="sm" disabled={busy} onClick={() => void reloadLatest()}>
                            {reloading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                            Reload latest
                        </GlassButton>
                    ) : null}
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

            {custom ? <CustomConnectionFields draft={draft} descriptors={customApiTypes} errors={errors} busy={busy} inputClass={inputClass} onChange={setField} /> : null}

            <SectionHeading>Connection</SectionHeading>

            <Field
                label={embeddingOnly ? 'Embedding API base URL' : foundry ? 'Project endpoint' : 'Endpoint URL'}
                error={errors.endpoint}
                htmlFor="connection-endpoint"
                help={
                    embeddingOnly
                        ? 'Use the explicit OpenAI-compatible API base, for example https://gateway.example/api/v1. Its path is preserved; no Azure route is added.'
                        : custom
                        ? 'The Custom API URL. HTTPS is required unless both private-host and plaintext HTTP permissions are explicitly enabled.'
                        : foundry
                        ? 'A Foundry project URL. Including /api/projects/<name> names the project for you.'
                        : 'The resource endpoint, for example https://my-resource.openai.azure.com.'
                }
            >
                <input
                    id="connection-endpoint"
                    type="url"
                    className={inputClass}
                    placeholder={embeddingOnly ? 'https://gateway.example/api/v1' : custom ? 'https://api.example.com' : foundry ? 'https://…/api/projects/my-project' : 'https://my-resource.openai.azure.com'}
                    value={String(draft.connection?.endpoint ?? '')}
                    disabled={busy}
                    spellCheck={false}
                    onChange={(event) => setField('connection.endpoint', event.target.value)}
                />
            </Field>

            {shown.openAiVersion ? <Field
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
            </Field> : null}

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
                hint={authOptions.find((option) => option.value === authType)?.hint}
            >
                Authentication
            </SectionHeading>

            <Field label="Method" htmlFor="connection-auth-type" error={errors.auth_type}>
                <select
                    id="connection-auth-type"
                    className={inputClass}
                    value={authType}
                    disabled={busy}
                    onChange={(event) => setField('auth.type', event.target.value)}
                >
                    {authOptions.map((option) => (
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
            {custom ? <CustomAuthenticationFields draft={draft} descriptors={customApiTypes} errors={errors} busy={busy} inputClass={inputClass} onChange={setField} /> : null}

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
                        help="Required for discovery, optional when entering models manually."
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

            {!embeddingUnavailableReason ? (
                <>
                    <SectionHeading hint="These operation-specific settings reuse this connection’s credentials without changing chat or image routing.">
                        Embedding inference
                    </SectionHeading>
                    <Field label="Embedding API" htmlFor="connection-embedding-api" error={errors.embedding_api}>
                        <select
                            id="connection-embedding-api"
                            className={inputClass}
                            value={embeddingOperation?.api ?? ''}
                            disabled={busy}
                            onChange={(event) => setOperation('api', event.target.value)}
                        >
                            <option value="">Provider default ({defaultEmbeddingApi(draft) === 'azure_openai' ? 'Azure OpenAI versioned' : 'OpenAI-compatible'})</option>
                            {draft.provider === 'aoai' || custom && draft.api_type === 'azure_openai' ? <option value="azure_openai">Azure OpenAI versioned</option> : null}
                            {!custom || draft.api_type === 'openai' ? <option value="openai">Current OpenAI-compatible API</option> : null}
                        </select>
                    </Field>
                    <Field
                        label="Embedding inference base URL"
                        htmlFor="connection-embedding-endpoint"
                        error={errors.embedding_endpoint}
                        help={foundry
                            ? 'Foundry project endpoints do not route embeddings. Supply the explicit resource inference base ending /openai/v1/; the project URL is never rewritten.'
                            : custom
                            ? 'Optional override using this Custom connection’s API type, URL mode and guarded transport. Its model name or deployment name remains the request identifier.'
                            : 'Optional when the connection URL already serves embeddings. Preserve a custom gateway’s API base path exactly.'}
                    >
                        <input
                            id="connection-embedding-endpoint"
                            className={inputClass}
                            type="url"
                            placeholder={foundry ? 'https://resource.services.ai.azure.com/openai/v1/' : 'Use the connection endpoint'}
                            value={embeddingOperation?.endpoint ?? ''}
                            disabled={busy}
                            onChange={(event) => setOperation('endpoint', event.target.value)}
                        />
                    </Field>
                    {embeddingApi === 'azure_openai' || embeddingOperation?.api_version ? (
                        <Field label="Embedding API version" htmlFor="connection-embedding-version" error={errors.embedding_api_version} help="Only Azure OpenAI versioned operations accept an api-version. Leave blank for the connection’s version; OpenAI-compatible operations must leave this blank.">
                            <input
                                id="connection-embedding-version"
                                className={inputClass}
                                type="text"
                                value={embeddingOperation?.api_version ?? ''}
                                disabled={busy}
                                onChange={(event) => setOperation('api_version', event.target.value)}
                            />
                        </Field>
                    ) : null}
                    <Field label="Embedding authentication header" htmlFor="connection-embedding-auth-header" error={errors.embedding_auth_header} help="Reuses the connection’s stored credential. Only these supported gateway headers can be overridden.">
                        <select
                            id="connection-embedding-auth-header"
                            className={inputClass}
                            value={embeddingOperation?.auth_header ?? ''}
                            disabled={busy}
                            onChange={(event) => setOperation('auth_header', event.target.value)}
                        >
                            <option value="">Protocol default</option>
                            <option value="api-key">api-key</option>
                            <option value="authorization">Authorization</option>
                            <option value="Ocp-Apim-Subscription-Key">Ocp-Apim-Subscription-Key</option>
                        </select>
                    </Field>
                    <Field label="Embedding API Management routing" htmlFor="connection-embedding-apim" help="Keep imported gateway behavior unless intentionally changing the embedding route.">
                        <select
                            id="connection-embedding-apim"
                            className={inputClass}
                            value={embeddingOperation?.is_apim === undefined ? '' : String(embeddingOperation.is_apim)}
                            disabled={busy}
                            onChange={(event) => setOperation('is_apim', event.target.value === '' ? '' : event.target.value === 'true')}
                        >
                            <option value="">Protocol default</option>
                            <option value="true">API Management gateway</option>
                            <option value="false">Direct inference</option>
                        </select>
                    </Field>
                    <p className="mt-2 text-xs text-warn">Embedding model and dimension changes, including same-dimension model switches, are checked against existing vectors when saved. No automatic rebuild is performed.</p>
                </>
            ) : (
                <p role="status" className="mt-3 text-xs text-warn">{embeddingUnavailableReason}</p>
            )}

            <SectionHeading
                hint={
                    embeddingOnly
                        ? 'This OpenAI-compatible provider supports text embeddings only. Add a model manually and declare its verified dimensions and input limit when it is not in the catalog.'
                        : custom
                        ? 'Enter the exact request model identifier. Custom connections do not use Azure management discovery.'
                        : shown.apiKey
                          ? 'Discovery needs Azure credentials, so with an API key the models have to be listed by hand.'
                          : 'Discovered models arrive switched off. Turn on the ones people may use.'
                }
            >
                Models
            </SectionHeading>

            <div className="mb-3 flex flex-wrap gap-2">
                {!custom && !embeddingOnly ? <>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => void runDiscovery()}
                    disabled={busy || !shown.discovery}
                >
                    {discovering ? (
                        <Loader2 size={14} className="animate-spin" />
                    ) : (
                        <RefreshCw size={14} />
                    )}
                    Discover models
                </GlassButton>
                {adapter.canTestConnection ? (
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        onClick={() => void runConnectionTest()}
                        disabled={busy}
                    >
                        {testing ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                        {embeddingOnly ? 'Validate configuration' : 'Test connection'}
                    </GlassButton>
                ) : null}
                </> : null}
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
                                ...(custom || embeddingOnly ? { supportsChat: false, supportsImageGeneration: false, supportsVision: false } : {}),
                            },
                        ])
                    }
                >
                    <Plus size={14} />
                    Add manually
                </GlassButton>
            </div>
            <p className="mb-3 text-xs text-text-3">
                Connection checks do not test image or embedding inference. Operation tests use saved bindings and may incur inference costs.
                {!savedBinding ? ' Save the connection first before testing images or embeddings, or choosing a default.' : ''}
            </p>
            {errors.models ? <p role="alert" className="mb-2 text-xs text-danger">{errors.models}</p> : null}

            {models.length === 0 ? (
                <p className="rounded-lg border border-edge bg-surface-1 p-3 text-xs text-text-3">
                    {custom || embeddingOnly ? 'No models yet. Add one manually using its request identifier.' : 'No models yet. Discover them from the connection, or add one by deployment name.'}
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
                                            aria-label={`Enable ${connectionRequestModel(draft, model) || 'model'}`}
                                            onChange={(event) => {
                                                const next = [...models];
                                                next[index] = {
                                                    ...model,
                                                    enabled: event.target.checked,
                                                };
                                                setModels(next);
                                            }}
                                        />
                                        <span className="text-xs text-text-3">Model enabled</span>
                                    </label>
                                    {model.isDiscovered ? <Pill tone="muted">Discovered</Pill> : null}
                                    <button
                                        type="button"
                                        title={`Remove ${connectionRequestModel(draft, model) || 'model'}`}
                                        aria-label={`Remove ${connectionRequestModel(draft, model) || 'model'}`}
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
                                        placeholder={usesModelName ? 'Model name' : 'Deployment name'}
                                        aria-label={usesModelName ? 'Model name' : 'Deployment name'}
                                        value={String((usesModelName ? model.modelName : model.deploymentName) ?? '')}
                                        disabled={busy}
                                        spellCheck={false}
                                        onChange={(event) => {
                                            const next = [...models];
                                            next[index] = {
                                                ...model,
                                                [usesModelName ? 'modelName' : 'deploymentName']: event.target.value,
                                            };
                                            delete next[index].capability_status;
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
                                {!usesModelName ? <label className="mt-2 block text-xs text-text-3">
                                    Underlying model name (optional)
                                    <input
                                        type="text"
                                        className={inputClass}
                                        value={model.modelName ?? ''}
                                        disabled={busy}
                                        onChange={(event) => {
                                            const nextModel = { ...model, modelName: event.target.value };
                                            delete nextModel.capability_status;
                                            setModels(models.map((item, at) => at === index ? nextModel : item));
                                        }}
                                    />
                                </label> : null}
                                <CatalogProfilePicker
                                    value={model.catalogProfileId}
                                    onChange={(catalogProfileId) => setModels(models.map((item, at) => {
                                        if (at !== index) return item;
                                        const next = { ...item, catalogProfileId };
                                        delete next.capability_status;
                                        return next;
                                    }))}
                                />
                                <ModelCapabilities
                                    model={model}
                                    connection={draft}
                                    disabled={busy}
                                    errors={Object.fromEntries(Object.entries(errors)
                                        .filter(([name]) => name.startsWith(`model_${index}_`))
                                        .map(([name, message]) => [name.slice(`model_${index}_`.length), message]))}
                                    onChange={(nextModel) => setModels(models.map((item, at) => at === index ? nextModel : item))}
                                />
                                <div className="mt-3 flex flex-wrap gap-2">
                                    {canTestChat && !embeddingOnly && modelPublishesCapability(model, 'chat') ? (
                                        <GlassButton type="button" variant="subtle" size="sm" disabled={busy} onClick={() => void runModelTest(model, 'chat')}>
                                            Test chat
                                        </GlassButton>
                                    ) : null}
                                    {canTestCapabilities && !embeddingOnly && modelSupportsCapability(model, 'image_generation') ? (
                                        <GlassButton type="button" variant="subtle" size="sm" disabled={busy} onClick={() => void runModelTest(model, 'image_generation')}>
                                            Test image generation
                                        </GlassButton>
                                    ) : null}
                                    {canTestCapabilities && !embeddingUnavailableReason && modelSupportsCapability(model, 'embeddings') ? (
                                        <GlassButton type="button" variant="subtle" size="sm" disabled={busy} onClick={() => void runModelTest(model, 'embeddings')}>
                                            Test embeddings
                                        </GlassButton>
                                    ) : null}
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

export function ModelConnectionsManager({ help, adapter = ADMIN_MODEL_CONNECTIONS_ADAPTER }: { help?: string; adapter?: ModelConnectionsAdapter }) {
    const [connections, setConnections] = useState<ModelConnection[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [editing, setEditing] = useState<ModelConnection | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [inUse, setInUse] = useState<{ name: string; references: EndpointReference[] } | null>(null);
    const [migration, setMigration] = useState<ConnectionMigrationNotice | null>(null);
    const [embeddingMigration, setEmbeddingMigration] = useState<ConnectionMigrationNotice | null>(null);
    const [defaultNotices, setDefaultNotices] = useState<string[]>([]);
    const [customApiTypes, setCustomApiTypes] = useState<CustomApiTypeDescriptor[]>([]);
    const [customNetworkPolicy, setCustomNetworkPolicy] = useState<CustomNetworkPolicy>(EMPTY_CUSTOM_NETWORK_POLICY);

    // Turning connections on seeds this list server-side with the classic chat endpoint,
    // and that save happens in the section above rather than here. Without a reload the
    // list would keep reading as empty at the exact moment it stopped being so.
    const connectionsRevision = useModelConnectionsStore((state) => state.revision);

    const load = useCallback(async (signal?: AbortSignal) => {
        try {
            const response = await adapter.list(signal);
            setConnections(Array.isArray(response.endpoints) ? response.endpoints : []);
            setCustomApiTypes(response.custom_api_types ?? []);
            setCustomNetworkPolicy(response.custom_network_policy ?? EMPTY_CUSTOM_NETWORK_POLICY);
            setMigration(response.migration ?? null);
            setEmbeddingMigration(response.embedding_migration ?? null);
            setDefaultNotices(Object.values(response.default_notices ?? {}).filter((notice): notice is string => typeof notice === 'string' && Boolean(notice)));
            setError(null);
        } catch (loadError) {
            if (signal?.aborted) {
                return;
            }
            setError(errorMessage(loadError, 'AI Connections could not be loaded.'));
        } finally {
            setLoading(false);
        }
    }, [adapter]);

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
            const result = await adapter.update(connection, { enabled: next });
            // Group rows carry a revision that advances on every write; refresh it so a follow-up
            // toggle is not rejected as stale. Admin responses omit it, so the row is unchanged.
            const savedRevision = result.endpoint?.revision;
            if (savedRevision) {
                setConnections((current) =>
                    current.map((item) =>
                        item.id === connection.id ? { ...item, enabled: next, revision: savedRevision } : item,
                    ),
                );
            }
            adapter.onChanged();
        } catch (toggleError) {
            setConnections(previous);
            if (toggleError instanceof EndpointConflictError) {
                // The stored copy moved on, so reload the list to pick up its current state
                // rather than leaving a stale row on screen.
                setError(toggleError.message);
                void load();
            } else {
                setError(errorMessage(toggleError, 'The connection could not be updated.'));
            }
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
            await adapter.remove(connection);
            adapter.onChanged();
            toast.success(`Deleted ${connection.name || 'connection'}.`);
        } catch (deleteError) {
            setConnections(previous);
            if (deleteError instanceof EndpointInUseError) {
                // Something still binds this connection, so name what and let the manager clear it
                // before deleting rather than reporting a bare failure.
                setInUse({ name: connection.name || 'This connection', references: deleteError.references });
            } else if (deleteError instanceof EndpointConflictError) {
                setError(deleteError.message);
                void load();
            } else {
                setError(errorMessage(deleteError, 'The connection could not be deleted.'));
            }
        } finally {
            setBusyId(null);
        }
    };

    const onSaved = (saved: ModelConnection, created: boolean) => {
        setEditing(null);
        setError(null);
        adapter.onChanged();
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
        <div className="py-3" role="region" aria-label="AI Connections">
            <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-text-1">AI Connections</span>
                {adapter.canCreate ? (
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        onClick={() => setEditing(emptyConnection())}
                    >
                        <Plus size={14} />
                        Add connection
                    </GlassButton>
                ) : null}
            </div>

            {help ? <p className="mb-3 text-xs leading-relaxed text-text-3">{help}</p> : null}
            <p className="mb-3 text-xs text-text-3">Configure credentials once, then choose independent chat, image and embedding defaults. Images and embeddings remain available when chat uses its classic endpoint.</p>
            {adapter.canEditNetworkPolicy && !loading ? <CustomNetworkPolicyEditor policy={customNetworkPolicy} onSaved={setCustomNetworkPolicy} /> : null}
            {adapter.showMigrationNotices ? [migration, embeddingMigration].map((notice, index) => notice?.message ? (
                <p key={index} role="status" className={`mb-3 rounded-lg p-3 text-xs ${notice.status === 'complete' ? 'bg-surface-2 text-text-2' : 'bg-warn-soft text-warn'}`}>
                    {notice.message}
                </p>
            ) : null) : null}
            {adapter.showMigrationNotices ? defaultNotices.map((notice, index) => (
                <p key={index} role="status" className="mb-2 text-xs text-warn">{notice}</p>
            )) : null}

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
                        ? 'No connections yet. Add an Azure OpenAI, Foundry, Custom, or embedding-only OpenAI-compatible connection to publish models.'
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
                                        {connection.provider === 'custom' ? `${customApiTypes.find((option) => option.value === connection.api_type)?.label || connection.api_type || 'API type missing'} · ` : ''}
                                        {authTypeLabel(connection.auth?.type)} ·{' '}
                                        {total === 0
                                            ? 'no models'
                                            : `${available} of ${total} model${total === 1 ? '' : 's'} available`}
                                    </p>
                                    <p className="mt-1 text-xs text-text-3">
                                        {connection.enabled === false ? 'Connection disabled' : (
                                            <>
                                                {connection.provider === 'openai_compatible' ? 0 : (connection.models ?? []).filter((model) => modelPublishesCapability(model, 'chat')).length} chat
                                                {' · '}
                                                {connection.provider === 'openai_compatible' ? 0 : (connection.models ?? []).filter((model) => modelPublishesCapability(model, 'image_generation')).length} image generation
                                                {' · '}
                                                {embeddingConnectionUnavailableReason(connection) ? 0 : (connection.models ?? []).filter((model) => modelPublishesCapability(model, 'embeddings')).length} embeddings
                                            </>
                                        )}
                                    </p>
                                    {connection.connection?.endpoint ? (
                                        <p className="truncate font-mono text-[11px] text-text-3">
                                            {String(connection.connection.endpoint)}
                                        </p>
                                    ) : null}
                                </div>

                                <div className="flex shrink-0 items-center gap-1">
                                    {adapter.allows('enable', connection) ? (
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
                                    ) : null}
                                    <button
                                        type="button"
                                        title={adapter.allows('edit', connection) ? 'Edit' : 'View'}
                                        aria-label={`${adapter.allows('edit', connection) ? 'Edit' : 'View'} ${connection.name ?? 'connection'}`}
                                        onClick={() => setEditing(connection)}
                                        className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                                    >
                                        <Pencil size={15} />
                                    </button>
                                    {adapter.allows('delete', connection) ? (
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
                                    ) : null}
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}

            {editing ? (
                <ConnectionEditor
                    initial={editing}
                    customApiTypes={customApiTypes}
                    adapter={adapter}
                    onReloadEndpoint={adapter.reload}
                    onClose={() => setEditing(null)}
                    onSaved={onSaved}
                />
            ) : null}

            {inUse ? (
                <AdminModal
                    title="This connection is still in use"
                    description="Remove it from the items below, then delete it."
                    onClose={() => setInUse(null)}
                    footer={
                        <GlassButton type="button" variant="ghost" size="sm" onClick={() => setInUse(null)}>
                            Close
                        </GlassButton>
                    }
                >
                    <p className="mb-2 text-sm text-text-2">
                        {inUse.name} is referenced by {inUse.references.length} item{inUse.references.length === 1 ? '' : 's'}.
                    </p>
                    <ul className="space-y-1">
                        {inUse.references.map((reference) => (
                            <li key={`${reference.kind}-${reference.id}`} className="rounded-lg border border-edge bg-surface-1 p-2 text-xs text-text-2">
                                <span className="text-text-3">{reference.kind === 'workflow' ? 'Workflow' : reference.kind === 'agent' ? 'Agent' : reference.kind}: </span>
                                {reference.name || reference.id}
                            </li>
                        ))}
                    </ul>
                </AdminModal>
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
                        will be removed. Any chat, image or embedding defaults that use it
                        will need a replacement.
                    </p>
                </AdminModal>
            ) : null}
        </div>
    );
}
