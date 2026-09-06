// ActionEditorPage.tsx

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { errorMessage } from '../../components/workspace/useSectionResource';
import { ActionField, ACTION_INPUT_CLASS } from '../../components/workspaceActions/ActionFields';
import { ActionAuthentication } from '../../components/workspaceActions/ActionAuthentication';
import { ActionConfigurationFields } from '../../components/workspaceActions/ActionConfigurationFields';
import { ActionAdvancedFields } from '../../components/workspaceActions/ActionAdvancedFields';
import {
    ConnectorFeedbackPanel, OpenApiActionAuthentication, OpenApiActionConfiguration,
} from '../../components/workspaceActions/OpenApiActionConfiguration';
import { McpActionAuthentication, McpActionConfiguration } from '../../components/workspaceActions/McpActionConfiguration';
import { ApiError } from '../../lib/apiClient';
import {
    agentEditorReturnPath, type ActionConfiguration, type ActionTypeDefinition,
} from '../../lib/workspaceAuthoring';
import { fetchActionEditor, fetchActionTypes, saveActionConfiguration } from '../../lib/workspaceAuthoringApi';
import { queueCreatedWorkspaceAction, useWorkspaceEditorDraft } from '../../lib/workspaceEditorDrafts';
import {
    ACTION_AUTHORING_UNAVAILABLE, actionApiErrors, actionFieldError, actionForSave, actionTypeLabel, changeActionDisplayName,
    changeActionType, createActionDraft, expandActionFieldErrors, hasUsableActionRevision, validateActionDraft,
} from '../../lib/workspaceActionLogic';
import {
    fetchActionEditorHints, fetchActionIdentities, validateWorkspaceAction, type ActionEditorHints,
} from '../../lib/workspaceActionServices';
import {
    connectorFeedback, validateConnectorAuthentication, validateConnectorConfiguration, type ConnectorFeedback,
} from '../../lib/workspaceActionConnectors';
import type { ActionConnectorProps, ActionIdentity } from '../../lib/workspaceActionTypes';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function ActionEditorPage() {
    const { resourceId = 'new' } = useParams();
    const owner = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const location = useLocation();
    const query = new URLSearchParams(location.search);
    const scope = query.get('scope') === 'global' ? 'global' : 'personal';
    const returnTo = resourceId === 'new' ? agentEditorReturnPath(query.get('returnTo')) : null;
    return <ActionEditor key={JSON.stringify([owner, resourceId, scope, returnTo])} resourceId={resourceId} scope={scope} returnTo={returnTo} />;
}

function ActionEditor({ resourceId, scope, returnTo }: { resourceId: string; scope: string; returnTo: string | null }) {
    const navigate = useNavigate();
    const location = useLocation();
    const id = useId();
    const isNew = resourceId === 'new';
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const {
        draft, setDraft, original, load, clear, dirty, restored,
    } = useWorkspaceEditorDraft<ActionConfiguration>('actions', JSON.stringify([scope, resourceId, returnTo]), createActionDraft);
    const loadRef = useRef(load);
    loadRef.current = load;
    const draftRef = useRef(draft);
    draftRef.current = draft;
    const mounted = useRef(true);
    const hasLoadedDraft = useRef(restored);
    const [loading, setLoading] = useState(!isNew && !restored);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [catalogue, setCatalogue] = useState<ActionTypeDefinition[]>([]);
    const [catalogueLoading, setCatalogueLoading] = useState(true);
    const [catalogueError, setCatalogueError] = useState<string | null>(null);
    const [identities, setIdentities] = useState<ActionIdentity[]>([]);
    const [identitiesLoading, setIdentitiesLoading] = useState(true);
    const [identitiesError, setIdentitiesError] = useState<string | null>(null);
    const [hints, setHints] = useState<ActionEditorHints | null>(null);
    const [hintsError, setHintsError] = useState<string | null>(null);
    const [hintsLoading, setHintsLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
    const [validity, setValidity] = useState<Record<string, string>>({});
    const [typeSearch, setTypeSearch] = useState('');
    const [pendingType, setPendingType] = useState<ActionTypeDefinition | null>(null);
    const [version, setVersion] = useState(0);
    const [editorGeneration, setEditorGeneration] = useState(0);
    const [latestReadOnly, setLatestReadOnly] = useState(false);
    const [reloadConfirmation, setReloadConfirmation] = useState(false);
    const replaceDraft = useRef(false);
    const [validationFeedback, setValidationFeedback] = useState<ConnectorFeedback | null>(null);
    const [validating, setValidating] = useState(false);
    const validationController = useRef<AbortController | null>(null);
    const [validatedDraft, setValidatedDraft] = useState<ActionConfiguration | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setCatalogueLoading(true); setCatalogueError(null);
        void fetchActionTypes(controller.signal).then((types) => {
            if (!controller.signal.aborted) setCatalogue(types);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setCatalogueError(errorMessage(cause, 'Could not load the governed action catalogue.'));
        }).finally(() => { if (!controller.signal.aborted) setCatalogueLoading(false); });
        setIdentitiesLoading(true); setIdentitiesError(null);
        void fetchActionIdentities(controller.signal).then((items) => {
            if (!controller.signal.aborted) setIdentities(items);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setIdentitiesError(errorMessage(cause, 'Could not load reusable identities.'));
        }).finally(() => { if (!controller.signal.aborted) setIdentitiesLoading(false); });
        setHintsLoading(true); setHintsError(null);
        void fetchActionEditorHints(controller.signal).then((options) => {
            if (!controller.signal.aborted) { setHints(options); setHintsError(null); }
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setHintsError(errorMessage(cause, 'Action authoring permissions and reminder defaults are unavailable.'));
        }).finally(() => { if (!controller.signal.aborted) setHintsLoading(false); });
        return () => controller.abort();
    }, [version]);
    useEffect(() => {
        if (isNew) return;
        const controller = new AbortController();
        setLoading(!hasLoadedDraft.current); setLoadError(null);
        void fetchActionEditor(resourceId, scope, controller.signal).then((resource) => {
            if (controller.signal.aborted) return;
            if (!resource?.record || !hasUsableActionRevision(resource, scope)) throw new Error('The action editor returned an invalid resource.');
            setLatestReadOnly(resource.read_only || Boolean(resource.record.is_global));
            // A return from New action must not overwrite a draft or silently rebase its revision.
            if ((!restored && !hasLoadedDraft.current) || replaceDraft.current) {
                loadRef.current(resource);
                setEditorGeneration((current) => current + 1);
                replaceDraft.current = false;
                hasLoadedDraft.current = true;
            }
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setLoadError(errorMessage(cause, 'Could not load this action.'));
        }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [isNew, resourceId, scope, restored, version]);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            validationController.current?.abort();
        };
    }, []);

    const readOnly = scope === 'global' || latestReadOnly || original?.read_only === true || draft.is_global === true;
    const canAuthor = !hintsLoading && !hintsError && hints?.canAuthor === true;
    const definition = catalogue.find((type) => type.type === draft.type);
    const visibleTypes = useMemo(() => catalogue.filter((type) => type.type === draft.type ||
        `${type.display} ${type.type} ${type.description}`.toLowerCase().includes(typeSearch.trim().toLowerCase()))
        .sort((left, right) => left.display.localeCompare(right.display)), [catalogue, draft.type, typeSearch]);
    const fallbackDefinition: ActionTypeDefinition = {
        type: draft.type, display: actionTypeLabel(draft.type), description: '',
        allowed_auth_types: draft.auth.type ? [draft.auth.type] : [],
        additional_fields_schema: {}, metadata_schema: {},
    };
    const displayDefinition = definition ?? fallbackDefinition;
    const onValidityChange = useCallback((key: string, message: string | null) => {
        setValidity((current) => {
            if (message === null && !(key in current) || message !== null && current[key] === message) return current;
            const next = { ...current };
            if (message) next[key] = message;
            else delete next[key];
            return next;
        });
    }, []);
    const connectorProps: ActionConnectorProps = {
        draft, original, onChange: setDraft,
        readOnly: readOnly || !canAuthor || saving || catalogueLoading || Boolean(catalogueError) || Boolean(loadError) || !definition,
        errors: expandActionFieldErrors(fieldErrors), onValidityChange, identities, identitiesLoading, identitiesError,
    };

    const validateLocally = () => {
        const errors = validateActionDraft(actionForSave(draft), definition, original);
        if (draft.type === 'openapi' || draft.type === 'mcp') {
            Object.assign(errors,
                validateConnectorConfiguration(draft, draft.type),
                validateConnectorAuthentication(draft, draft.type, original));
        }
        setFieldErrors(errors);
        const messages = [...Object.values(errors), ...Object.values(validity)];
        if (messages.length) {
            setError([...new Set(messages)].join(' '));
            return false;
        }
        setError(null);
        return true;
    };
    const save = async () => {
        if (saving || readOnly || !canAuthor || loadError || catalogueLoading || catalogueError || !validateLocally()) return;
        validationController.current?.abort();
        setSaving(true); setError(null); setValidationFeedback(null);
        try {
            const saved = await saveActionConfiguration(actionForSave(draft), original);
            if (!mounted.current) return;
            if (!saved?.record?.id) throw new Error('The server did not return a saved action ID. Reload before retrying.');
            if (returnTo) queueCreatedWorkspaceAction(returnTo, saved.record);
            load(saved);
            clear();
            void refreshBootstrap();
            navigate(returnTo || '/workspace/actions', {
                state: { workspaceEditorSaved: true, workspaceEditorFrom: location.key, ...(returnTo ? { preserveWorkspaceDraft: true } : {}) },
            });
        } catch (cause) {
            if (!mounted.current) return;
            const conflict = cause instanceof ApiError && cause.status === 409;
            setFieldErrors(cause instanceof ApiError ? actionApiErrors(cause.payload) : {});
            setError(conflict
                ? 'This action changed in another session. Your draft is still here. Review it, or load the saved version before trying again.'
                : errorMessage(cause, 'Could not save the action. Your draft is retained.'));
        } finally {
            if (mounted.current) setSaving(false);
        }
    };
    const validate = async () => {
        if (readOnly || !canAuthor || saving || validating || !validateLocally()) return;
        validationController.current?.abort();
        const controller = new AbortController();
        validationController.current = controller;
        const snapshot = draft;
        setValidating(true);
        try {
            const result = await validateWorkspaceAction(snapshot, original, controller.signal);
            if (controller.signal.aborted) return;
            setValidationFeedback(connectorFeedback(result));
            setValidatedDraft(snapshot);
            if (draftRef.current === snapshot) setFieldErrors(actionApiErrors(result));
        } catch (cause) {
            if (controller.signal.aborted) return;
            setValidationFeedback(connectorFeedback(cause));
            setValidatedDraft(snapshot);
            if (draftRef.current === snapshot && cause instanceof ApiError) setFieldErrors(actionApiErrors(cause.payload));
        } finally {
            if (validationController.current === controller) setValidating(false);
        }
    };
    const reloadSaved = async () => {
        setReloadConfirmation(false);
        replaceDraft.current = true;
        setError(null); setFieldErrors({}); setValidationFeedback(null);
        setVersion((current) => current + 1);
    };
    const applyType = (type: ActionTypeDefinition) => {
        if (readOnly || !canAuthor) {
            setPendingType(null);
            return;
        }
        validationController.current?.abort();
        setDraft((current) => changeActionType(current, type));
        setPendingType(null); setFieldErrors({}); setValidity({}); setError(null); setValidationFeedback(null);
    };
    const identitySection = (
        <div className="space-y-5">
            {returnTo ? <p className="rounded-xl bg-accent-soft p-3 text-sm text-accent">Save this action to return to your agent draft with it selected. The agent itself will not be saved.</p> : null}
            {restored ? <p role="status" className="text-xs text-text-3">Your unsaved action draft has been restored in this tab.</p> : null}
            {!readOnly && hintsLoading ? <p role="status" className="text-sm text-text-3">Checking action authoring permissions…</p> : null}
            {!readOnly && !hintsLoading && !canAuthor ? <div role={hintsError ? 'alert' : 'status'}
                className="space-y-2 rounded-xl bg-warn-soft p-3 text-sm text-warn">
                <p>{hintsError || ACTION_AUTHORING_UNAVAILABLE}</p>
                {dirty ? <p>Your unsaved draft has been retained. Reading it does not require creation permission.</p> : null}
                {hintsError ? <GlassButton type="button" size="sm" onClick={() => setVersion((current) => current + 1)}>Retry authoring permissions</GlassButton> : null}
            </div> : null}
            {catalogueError ? <div role="alert" className="space-y-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
                <p>{catalogueError} Existing configuration has not been changed.</p>
                <GlassButton type="button" size="sm" onClick={() => setVersion((current) => current + 1)}>Retry action catalogue</GlassButton>
            </div> : null}
            {draft.type && !definition && !catalogueLoading && !catalogueError ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                This action’s type is no longer offered to this workspace. Its configuration is preserved for review. Choose a permitted type before saving.
            </p> : null}
            {!readOnly && canAuthor ? <ActionField id={`${id}-type-search`} label="Search action types">
                <input id={`${id}-type-search`} type="search" className={ACTION_INPUT_CLASS} value={typeSearch}
                    onChange={(event) => setTypeSearch(event.target.value)} />
            </ActionField> : null}
            <ActionField id={`${id}-type`} label="Action type" required help={displayDefinition.description}
                error={actionFieldError(fieldErrors, '/type')}>
                <select id={`${id}-type`} className={ACTION_INPUT_CLASS} value={draft.type} required disabled={readOnly || !canAuthor || catalogueLoading}
                    onChange={(event) => {
                        const next = catalogue.find((type) => type.type === event.target.value);
                        if (!next || next.type === draft.type) return;
                        if (draft.type) setPendingType(next);
                        else applyType(next);
                    }}>
                    <option value="">{catalogueLoading ? 'Loading action types…' : 'Select an action type'}</option>
                    {draft.type && !definition ? <option value={draft.type}>{actionTypeLabel(draft.type)} (existing)</option> : null}
                    {visibleTypes.map((type) => <option key={type.type} value={type.type}>{type.display}</option>)}
                </select>
            </ActionField>
            {!catalogueLoading && !catalogueError && !catalogue.length ? <p role="status" className="text-sm text-text-3">No action types are permitted in this workspace. Contact your administrator.</p> : null}
            <ActionField id={`${id}-name`} label="Action name" required error={actionFieldError(fieldErrors, '/displayName')}>
                <input id={`${id}-name`} autoFocus={!readOnly && canAuthor} disabled={!canAuthor} className={ACTION_INPUT_CLASS} value={draft.displayName ?? draft.name ?? ''} required
                    onChange={(event) => setDraft((current) => changeActionDisplayName(current, event.target.value, isNew))} />
            </ActionField>
            <ActionField id={`${id}-description`} label="Description" help="Explain what this action does and when an agent should use it.">
                <textarea id={`${id}-description`} rows={3} disabled={!canAuthor} className={ACTION_INPUT_CLASS} value={draft.description}
                    onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
            </ActionField>
            <ConnectorFeedbackPanel feedback={validationFeedback} stale={Boolean(validatedDraft && validatedDraft !== draft)} />
        </div>
    );
    const configuration = draft.type === 'openapi' ? <OpenApiActionConfiguration {...connectorProps} /> :
        draft.type === 'mcp' ? <McpActionConfiguration {...connectorProps} /> :
            <ActionConfigurationFields {...connectorProps} definition={displayDefinition} />;
    const authentication = draft.type === 'openapi' ? <OpenApiActionAuthentication {...connectorProps} /> :
        draft.type === 'mcp' ? <McpActionAuthentication {...connectorProps} /> :
            <ActionAuthentication {...connectorProps} definition={displayDefinition} />;
    const sections = [
        { id: 'identity', label: 'Identity and type', content: identitySection },
        ...(draft.type ? [
            { id: 'configuration', label: 'Configuration', content: configuration },
            { id: 'authentication', label: 'Authentication', content: authentication },
            { id: 'advanced', label: 'Advanced', content: <ActionAdvancedFields {...connectorProps} definition={displayDefinition} hints={hints} hintsError={hintsError} /> },
        ] : []),
    ];
    if (loading) return <div role="status" className="space-y-4"><p className="text-sm text-text-3">Loading action…</p><Skeleton className="h-44 w-full" /></div>;
    if (loadError && !original) return <GlassPanel elevation="flat" className="space-y-3 p-5">
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <div className="flex flex-wrap gap-2">
            <GlassButton type="button" onClick={() => setVersion((current) => current + 1)}>Retry action</GlassButton>
            <GlassButton type="button" onClick={() => navigate(returnTo || '/workspace/actions')}>Back to actions</GlassButton>
        </div>
        {restored ? <p className="text-xs text-text-3">The unsaved draft remains in this tab; it has not been overwritten by this failed read.</p> : null}
    </GlassPanel>;

    return (
        <>
            <WorkspaceEditorFrame title={readOnly ? 'Action details' : isNew ? 'New action' : canAuthor ? 'Edit action' : 'Action details'}
                description={readOnly ? 'This provided action is managed by an administrator.' :
                    isNew ? 'Configure an action, then explicitly save it. Connectors run only when you choose a discovery or test command.' : draft.displayName || draft.name}
                backTo={returnTo || '/workspace/actions'} sections={sections.map((section) => ({
                    ...section, content: <div key={editorGeneration} className="min-w-0">{section.content}</div>,
                }))} dirty={dirty || Object.keys(validity).some((key) => key.startsWith('json:'))} saving={saving} readOnly={readOnly}
                error={loadError || error} saveLabel="Save action" onSave={() => void save()} onDiscard={clear}
                saveDisabled={!canAuthor || catalogueLoading || Boolean(catalogueError) || Boolean(loadError) || !definition}
                actions={!readOnly ? <>
                    {!isNew ? <GlassButton type="button" size="sm" disabled={saving} onClick={() => setReloadConfirmation(true)}><RefreshCw size={14} />Load saved version</GlassButton> : null}
                    <GlassButton type="button" size="sm" disabled={!canAuthor || saving || validating || !definition}
                        onClick={() => void validate()}><CheckCircle2 size={14} />{validating ? 'Validating…' : 'Validate configuration'}</GlassButton>
                </> : undefined} />
            {pendingType ? <ConfirmDialog title="Change action type?" tone="primary" confirmLabel="Change type"
                description="Configuration and authentication will switch to the selected connector. The previous type’s draft stays in this tab if you switch back; it is not sent as configuration for the new type."
                onClose={() => setPendingType(null)} onConfirm={() => applyType(pendingType)}>
                <p className="text-sm text-text-2">The name, description, ID, and metadata are kept. Review configuration before saving.</p>
            </ConfirmDialog> : null}
            {reloadConfirmation ? <ConfirmDialog title="Load the saved action?" tone="primary" confirmLabel="Load saved version"
                description="This replaces your unsaved action draft with the server’s latest version. It does not change any agent draft."
                onClose={() => setReloadConfirmation(false)} onConfirm={() => void reloadSaved()}>
                <p className="text-sm text-text-2">Keep editing to retain your current changes.</p>
            </ConfirmDialog> : null}
        </>
    );
}
