// AdminYamcsActions.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { Pencil, Plus, RefreshCw } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { ActionAuthentication } from '../workspaceActions/ActionAuthentication';
import { ActionDescriptorField } from '../workspaceActions/ActionConfigurationFields';
import { ActionField, ACTION_INPUT_CLASS } from '../workspaceActions/ActionFields';
import { ActionCredentialCard } from '../chat/ActionCredentialCard';
import { useSectionResource } from '../workspace/useSectionResource';
import {
    ADMIN_YAMCS_SCOPE, SavedYamcsReloadError, fetchAdminActionIdentities, fetchAdminYamcsActions,
    fetchAdminYamcsType, globalYamcsActionReference, saveAdminYamcsAction, setAdminYamcsEnabled, testAdminYamcsAction,
} from '../../lib/adminYamcsActions';
import {
    actionForSave, changeActionDisplayName, changeActionType, createActionDraft, validateActionDraft,
} from '../../lib/workspaceActionLogic';
import { nativeActionDefinition } from '../../lib/workspaceActionRegistry';
import { sameEditorValue, type ActionConfiguration, type ActionTypeDefinition, type AuthoringResource } from '../../lib/workspaceAuthoring';
import type { ActionConnectorProps, ActionIdentity } from '../../lib/workspaceActionTypes';
import { ACTION_AUTH_PROFILES, actionAuthErrorMessage, isActionCredentialsRequired } from '../../lib/actionAuth';
import { actionAuthController } from '../../lib/actionAuthController';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function AdminYamcsActions({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
    const { items, setItems, loading, error, refresh, setError } = useSectionResource(fetchAdminYamcsActions, 'Could not load global Yamcs actions.');
    const [definition, setDefinition] = useState<ActionTypeDefinition | null>(null);
    const [typeError, setTypeError] = useState<string | null>(null);
    const [editing, setEditing] = useState<AuthoringResource<ActionConfiguration> | null | undefined>(undefined);
    const [busy, setBusy] = useState<string | null>(null);
    const [testResult, setTestResult] = useState<string | null>(null);
    const testController = useRef<AbortController | null>(null);
    const actor = useBootstrapStore((state) => state.data?.user?.id);
    const actorRef = useRef(actor);
    actorRef.current = actor;
    useEffect(() => {
        const controller = new AbortController();
        void fetchAdminYamcsType(controller.signal).then(setDefinition).catch(() => {
            if (!controller.signal.aborted) setTypeError('The installed Yamcs action type could not be loaded. Reload this page before creating or editing.');
        });
        return () => {
            controller.abort();
            testController.current?.abort();
            actionAuthController.cancel('admin-yamcs');
        };
    }, []);
    useEffect(() => {
        onDirtyChange?.(editing !== undefined);
        return () => onDirtyChange?.(false);
    }, [editing, onDirtyChange]);
    const test = async (resource: AuthoringResource<ActionConfiguration>) => {
        if (busy) return;
        const controller = new AbortController();
        testController.current?.abort();
        testController.current = controller;
        const isCurrent = () => testController.current === controller && !controller.signal.aborted &&
            !useBootstrapStore.getState().authExpired && actorRef.current === actor;
        setBusy(resource.record.id); setError(null); setTestResult(null);
        const input = {
            action_ref: globalYamcsActionReference(resource.record),
            conversation_id: null, conversation_kind: 'personal' as const,
        };
        try {
            const receipt = resource.record.credential_requirement
                ? await actionAuthController.request(input, { surface: 'admin-yamcs', isCurrent })
                : { requestId: null };
            if (!receipt || !isCurrent()) return;
            await testAdminYamcsAction(resource, controller.signal);
            if (isCurrent()) setTestResult(resource.record.credential_requirement
                ? 'Connected to the saved Yamcs destination using your private personal identity.'
                : 'The saved Yamcs connection was verified.');
        } catch (cause) {
            if (!isCurrent()) return;
            if (isActionCredentialsRequired(cause)) {
                actionAuthController.repair(cause, input, { surface: 'admin-yamcs', isCurrent });
            } else setError(actionAuthErrorMessage(cause));
        } finally {
            if (isCurrent()) setBusy(null);
        }
    };
    const toggle = async (resource: AuthoringResource<ActionConfiguration>) => {
        if (busy) return;
        setBusy(resource.record.id); setError(null);
        try {
            await setAdminYamcsEnabled(resource.record, resource.record.is_enabled === false);
            await refresh();
        } catch {
            setError('The action’s enabled state could not be changed. Reload and try again.');
        } finally { setBusy(null); }
    };
    return (
        <GlassPanel elevation="flat" className="space-y-4 p-4" data-testid="admin-yamcs-actions">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-text-1">Global Yamcs actions</h2>
                {editing === undefined ? <div className="flex gap-2">
                    <GlassButton type="button" size="sm" disabled={loading || Boolean(busy)} onClick={() => void refresh()}>
                        <RefreshCw size={14} aria-hidden="true" /> Reload
                    </GlassButton>
                    <GlassButton type="button" size="sm" variant="primary" disabled={!definition || Boolean(busy)}
                        onClick={() => { setTestResult(null); setEditing(null); }}>
                        <Plus size={14} aria-hidden="true" /> Add Yamcs action
                    </GlassButton>
                </div> : null}
            </div>
            <p className="text-sm text-text-2">Publish one read-only telemetry action and let each person connect their own Yamcs account. These resources save independently of the Admin Settings save bar.</p>
            {error || typeError ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error || typeError}</p> : null}
            {testResult ? <p role="status" className="rounded-xl bg-accent-soft p-3 text-sm text-text-1">{testResult}</p> : null}
            {editing !== undefined && definition ? <AdminYamcsEditor key={editing?.record.id || 'new'}
                original={editing} definition={definition} testing={Boolean(busy)}
                onClose={() => { actionAuthController.cancel('admin-yamcs'); setEditing(undefined); }}
                onTest={test} onSaved={(saved) => {
                    setItems([...items.filter((item) => item.record.id !== saved.record.id), saved]);
                    setEditing(undefined); setError(null); setTestResult('Global Yamcs action saved.');
                }} /> : loading ? <p role="status" className="text-sm text-text-3">Loading Yamcs actions…</p> : (
                <div className="space-y-2">
                    {!items.length ? <p className="text-sm text-text-3">No global Yamcs actions yet.</p> : null}
                    {items.map((resource) => <div key={resource.record.id || resource.record.name}
                        data-testid="admin-yamcs-action-row"
                        className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge p-3">
                        <div className="min-w-0">
                            <h3 className="break-words text-sm font-medium text-text-1">{resource.record.displayName}</h3>
                            <p className="text-xs text-text-3">{resource.record.credential_requirement
                                ? `Each user’s personal identity · ${resource.record.credential_requirement.identity_name}`
                                : 'Configured action credentials or global identity'} · {resource.record.is_enabled === false ? 'Disabled' : 'Enabled'}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <GlassButton type="button" size="sm" disabled={Boolean(busy) || !definition} onClick={() => setEditing(resource)}
                                aria-label={`Edit Yamcs action ${resource.record.displayName}`}><Pencil size={14} aria-hidden="true" />Edit</GlassButton>
                            <GlassButton type="button" size="sm" disabled={Boolean(busy)} onClick={() => void toggle(resource)}
                                aria-label={`${resource.record.is_enabled === false ? 'Enable' : 'Disable'} ${resource.record.displayName}`}>
                                {resource.record.is_enabled === false ? 'Enable' : 'Disable'}
                            </GlassButton>
                            <GlassButton type="button" size="sm" disabled={Boolean(busy) || resource.record.is_enabled === false}
                                onClick={() => void test(resource)}>
                                {busy === resource.record.id ? 'Working…' : resource.record.credential_requirement ? 'Test as me' : 'Test saved connection'}
                            </GlassButton>
                        </div>
                    </div>)}
                </div>
            )}
            <ActionCredentialCard surface="admin-yamcs" />
            <p className="text-xs text-text-3">Other global connectors remain available on the <a href="/admin/settings" className="text-accent underline">classic admin page</a>.</p>
        </GlassPanel>
    );
}

function AdminYamcsEditor({
    original, definition, testing, onClose, onSaved, onTest,
}: {
    original: AuthoringResource<ActionConfiguration> | null;
    definition: ActionTypeDefinition;
    testing: boolean;
    onClose: () => void;
    onSaved: (resource: AuthoringResource<ActionConfiguration>) => void;
    onTest: (resource: AuthoringResource<ActionConfiguration>) => Promise<void>;
}) {
    const id = useId();
    const [draft, setDraft] = useState<ActionConfiguration>(() => original
        ? structuredClone(original.record) : changeActionType(createActionDraft(), definition));
    const [review, setReview] = useState(false);
    const [saving, setSaving] = useState(false);
    const [reloadRequired, setReloadRequired] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [identities, setIdentities] = useState<ActionIdentity[]>([]);
    const [identitiesLoading, setIdentitiesLoading] = useState(true);
    const [identitiesError, setIdentitiesError] = useState<string | null>(null);
    const controller = useRef<AbortController | null>(null);
    useEffect(() => {
        const request = new AbortController();
        void fetchAdminActionIdentities(request.signal).then((items) => {
            if (!request.signal.aborted) setIdentities(items);
        }).catch(() => {
            if (!request.signal.aborted) setIdentitiesError('Global identities could not be loaded. The saved reference is unchanged.');
        }).finally(() => { if (!request.signal.aborted) setIdentitiesLoading(false); });
        return () => { request.abort(); controller.current?.abort(); actionAuthController.cancel('admin-yamcs'); };
    }, []);
    useEffect(() => { actionAuthController.cancel('admin-yamcs'); }, [draft]);
    const dirty = !original || !sameEditorValue(actionForSave(draft), actionForSave(original.record));
    const connectorProps: ActionConnectorProps = {
        authoringScope: ADMIN_YAMCS_SCOPE, draft, original, onChange: setDraft,
        readOnly: saving || testing || reloadRequired, errors, onValidityChange: () => {},
        identities, identitiesLoading, identitiesError,
    };
    const submit = async () => {
        if (saving || testing || reloadRequired) return;
        const fieldErrors = validateActionDraft(actionForSave(draft), definition, original, ADMIN_YAMCS_SCOPE);
        setErrors(fieldErrors);
        if (Object.keys(fieldErrors).length) {
            setError('Review the highlighted configuration fields.');
            setReview(false);
            return;
        }
        if (!review) { setError(null); setReview(true); return; }
        const request = new AbortController();
        controller.current = request;
        setSaving(true); setError(null);
        try {
            const saved = await saveAdminYamcsAction(actionForSave(draft), original, definition, request.signal);
            if (!request.signal.aborted) onSaved(saved);
        } catch (cause) {
            if (!request.signal.aborted) {
                setReloadRequired(cause instanceof SavedYamcsReloadError);
                setError(cause instanceof SavedYamcsReloadError ? cause.message :
                    'The global action could not be saved. It may have changed or failed validation. Your draft is still here; reload the saved list before trying again.');
            }
        } finally { if (!request.signal.aborted) setSaving(false); }
    };
    return (
        <form className="space-y-5 rounded-xl border border-edge p-4" aria-label={original ? 'Edit global Yamcs action' : 'Create global Yamcs action'}
            aria-busy={saving} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            <h3 className="text-sm font-semibold text-text-1">{review ? 'Review global Yamcs action' : original ? 'Edit global Yamcs action' : 'Create global Yamcs action'}</h3>
            {review ? <div className="space-y-2 text-sm text-text-2">
                <p><strong>{draft.displayName}</strong> · {draft.name}</p>
                <p className="break-all">Destination: {draft.endpoint} · Instance: {String(draft.additionalFields.instance || '')}</p>
                <p>{draft.is_enabled === false ? 'Disabled' : 'Enabled'} · Read-only</p>
                <p>{draft.credential_requirement
                    ? `Each user’s personal identity: ${draft.credential_requirement.identity_name} · ${ACTION_AUTH_PROFILES[draft.credential_requirement.profile].label}`
                    : draft.identity_id ? 'Use the selected global workspace identity.' : `Use configured ${draft.auth.type} authentication.`}</p>
                <p className="text-xs text-text-3">Unchanged hidden fields and stored secrets are kept. This saves only the action configuration; Test as me connects your private identity separately.</p>
            </div> : <>
                <ActionField id={`${id}-name`} label="Action name" required error={errors['/displayName']}>
                    <input id={`${id}-name`} className={ACTION_INPUT_CLASS} required value={draft.displayName} disabled={connectorProps.readOnly}
                        onChange={(event) => setDraft((current) => changeActionDisplayName(current, event.target.value, !original))} />
                </ActionField>
                <ActionField id={`${id}-machine`} label="Machine name" required error={errors['/name']}>
                    <input id={`${id}-machine`} className={ACTION_INPUT_CLASS} required pattern="[A-Za-z0-9_\-]+" value={draft.name}
                        disabled={connectorProps.readOnly} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
                </ActionField>
                <ActionField id={`${id}-description`} label="Description">
                    <textarea id={`${id}-description`} className={ACTION_INPUT_CLASS} rows={2} value={draft.description} disabled={connectorProps.readOnly}
                        onChange={(event) => {
                            const description = event.target.value;
                            setDraft((current) => ({ ...current, description, metadata: { ...current.metadata, description } }));
                        }} />
                </ActionField>
                <ActionAuthentication {...connectorProps} definition={definition} />
                <div className="grid gap-4 sm:grid-cols-2">
                    {nativeActionDefinition('yamcs').fields.map((descriptor) => <ActionDescriptorField key={descriptor.path}
                        props={connectorProps} descriptor={{
                            ...descriptor,
                            readOnly: descriptor.readOnly || Boolean(draft.credential_requirement && descriptor.path === '/additionalFields/tls_verify'),
                            help: draft.credential_requirement && descriptor.path === '/additionalFields/tls_verify'
                                ? 'Certificate verification is required when sending personal credentials.' : descriptor.help,
                        }} />)}
                </div>
                <label className="flex items-center gap-2 text-sm text-text-2">
                    <input type="checkbox" checked={draft.is_enabled !== false} disabled={connectorProps.readOnly}
                        onChange={(event) => setDraft((current) => ({ ...current, is_enabled: event.target.checked }))} />
                    Enable this global action
                </label>
            </>}
            {error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
            <div className="flex flex-wrap justify-between gap-2">
                <GlassButton type="button" size="sm" disabled={saving} onClick={onClose}>{reloadRequired ? 'Close and reload list' : 'Cancel'}</GlassButton>
                <div className="flex flex-wrap gap-2">
                    {original ? <GlassButton type="button" size="sm" disabled={dirty || saving || testing || reloadRequired || original.record.is_enabled === false}
                        onClick={() => void onTest(original)}>{original.record.credential_requirement ? 'Test as me' : 'Test saved connection'}</GlassButton> : null}
                    {review ? <GlassButton type="button" size="sm" disabled={saving} onClick={() => setReview(false)}>Back to configuration</GlassButton> : null}
                    <GlassButton type="submit" size="sm" variant="primary" disabled={saving || testing || reloadRequired}>
                        {saving ? 'Saving…' : review ? 'Save global Yamcs action' : 'Review action'}
                    </GlassButton>
                </div>
            </div>
            {dirty ? <p className="text-xs text-text-3">Save configuration changes before testing the saved destination.</p> : null}
        </form>
    );
}
