// AgentEditorPage.tsx

import { useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { GlassButton } from '../../components/ui/primitives';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { SectionSkeleton } from '../../components/workspace/primitives';
import { AgentIdentityFields } from '../../components/workspaceAgents/AgentIdentityFields';
import { AgentModelFields } from '../../components/workspaceAgents/AgentModelFields';
import { AgentActionPicker } from '../../components/workspaceAgents/AgentActionPicker';
import { AgentKnowledgeFields } from '../../components/workspaceAgents/AgentKnowledgeFields';
import { AgentInstructionsFields } from '../../components/workspaceAgents/AgentInstructionsFields';
import { AgentAdvancedFields, agentAdvancedError } from '../../components/workspaceAgents/AgentAdvancedFields';
import { AgentTemplatesPanel } from '../../components/workspaceAgents/AgentTemplatesPanel';
import { AgentNotice } from '../../components/workspaceAgents/AgentFields';
import { ApiError } from '../../lib/apiClient';
import { fetchAgentTargets, PERSONAL_DELEGATION_SCOPE, type AgentTargetCatalog } from '../../lib/agentDelegation';
import {
    fetchAuthoringActions, fetchAgentEditor, fetchAgentEditorOptions, saveAgentConfiguration,
} from '../../lib/workspaceAuthoringApi';
import {
    isRecord, type ActionConfiguration, type AgentConfiguration, type AgentEditorOptions,
} from '../../lib/workspaceAuthoring';
import { takeCreatedWorkspaceAction, useWorkspaceEditorDraft } from '../../lib/workspaceEditorDrafts';
import { agentForSave, agentText, agentValidationErrors, applySafeAgentDraft, isAgentEditorEnvelope, newAgentDraft } from '../../lib/workspaceAgentAuthoring';
import { newAgentActionErrors } from '../../lib/workspaceAgentActions';
import { agentKnowledgeErrors, fetchAgentKnowledgeCatalog, type AgentKnowledgeCatalog } from '../../lib/workspaceAgentKnowledge';
import { useBootstrapStore } from '../../stores/bootstrapStore';

function message(cause: unknown): string {
    return cause instanceof Error ? cause.message : 'The operation could not be completed.';
}

function AgentEditorSession({ resourceId, scope }: { resourceId: string; scope: string }) {
    const navigate = useNavigate();
    const location = useLocation();
    const ownerId = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const canCreateActions = useBootstrapStore((state) => state.data?.workspace?.sections.actions?.enabled === true);
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const isNew = resourceId === 'new';
    const { draft, setDraft: setStoredDraft, original, load, clear, dirty, restored } =
        useWorkspaceEditorDraft<AgentConfiguration>('agents', `${scope}:${resourceId}`, newAgentDraft);
    const setDraft: Dispatch<SetStateAction<AgentConfiguration>> = (update) => setStoredDraft((current) =>
        applySafeAgentDraft(current, typeof update === 'function' ? update(current) : update, original));
    const [options, setOptions] = useState<AgentEditorOptions | null>(null);
    const [bootLoading, setBootLoading] = useState(true);
    const [bootError, setBootError] = useState<string | null>(null);
    const [bootRevision, setBootRevision] = useState(0);
    const [accessReadOnly, setAccessReadOnly] = useState(scope === 'global');
    const [saving, setSaving] = useState(false);
    const [iconBusy, setIconBusy] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [hasSaveConflict, setHasSaveConflict] = useState(false);
    const [actions, setActions] = useState<ActionConfiguration[]>([]);
    const [actionsLoading, setActionsLoading] = useState(false);
    const [actionsError, setActionsError] = useState<string | null>(null);
    const [targets, setTargets] = useState<AgentTargetCatalog | null>(null);
    const [targetError, setTargetError] = useState<string | null>(null);
    const [actionsRevision, setActionsRevision] = useState(0);
    const [knowledge, setKnowledge] = useState<AgentKnowledgeCatalog | null>(null);
    const [knowledgeLoading, setKnowledgeLoading] = useState(false);
    const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
    const [knowledgeRevision, setKnowledgeRevision] = useState(0);
    const returnedAction = useRef<ActionConfiguration | null>(null);
    const handoffChecked = useRef(false);
    const templatesAnchor = useRef<HTMLDivElement>(null);
    const readOnly = accessReadOnly || original?.read_only === true;
    const advancedError = agentAdvancedError(draft, original);
    const arraySecretError = agentText(draft._editor_array_secret_error) || null;

    useEffect(() => {
        if (bootLoading || new URLSearchParams(location.search).get('templates') !== '1') return;
        templatesAnchor.current?.scrollIntoView({ block: 'start' });
        templatesAnchor.current?.focus({ preventScroll: true });
    }, [bootLoading, location.search]);

    useEffect(() => {
        const controller = new AbortController();
        setBootLoading(true);
        setBootError(null);
        void Promise.all([
            fetchAgentEditorOptions(controller.signal),
            isNew ? Promise.resolve(null) : fetchAgentEditor(resourceId, scope, controller.signal),
        ]).then(([editorOptions, resource]) => {
            if (controller.signal.aborted) return;
            if (!editorOptions || !Array.isArray(editorOptions.agent_types) || !Array.isArray(editorOptions.model_endpoints) ||
                !Array.isArray(editorOptions.builtin_actions) || !isRecord(editorOptions.settings)) {
                throw new Error('The agent editor options returned an invalid response.');
            }
            if (resource && !isAgentEditorEnvelope(resource)) {
                throw new Error('The agent editor returned an invalid resource.');
            }
            setOptions(editorOptions);
            setAccessReadOnly(scope === 'global' || resource?.read_only === true);
            // A restored draft keeps its original revision so another save cannot hide a conflict.
            if (resource && !restored) load(resource);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setBootError(message(cause));
        }).finally(() => { if (!controller.signal.aborted) setBootLoading(false); });
        return () => controller.abort();
        // The outer keyed component scopes these callbacks and the draft to one resource.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [resourceId, scope, isNew, bootRevision]);

    useEffect(() => {
        if (bootLoading || bootError || readOnly || handoffChecked.current) return;
        handoffChecked.current = true;
        const action = takeCreatedWorkspaceAction(location.pathname);
        if (!action) return;
        returnedAction.current = action;
        setActions((current) => [...current.filter((item) => item.id !== action.id || item.is_global !== action.is_global), action]);
        setDraft((current) => ({
            ...current,
            actions_to_load: current.actions_to_load.includes(action.id) ? current.actions_to_load : [...current.actions_to_load, action.id],
        }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bootLoading, bootError, readOnly, location.pathname]);

    useEffect(() => {
        if (bootLoading || bootError) return;
        const controller = new AbortController();
        setActionsLoading(true);
        setActionsError(null);
        setTargetError(null);
        setTargets(null);
        void fetchAuthoringActions(controller.signal).then((items) => {
            if (controller.signal.aborted) return;
            const created = returnedAction.current;
            const available = created && !items.some((item) => item.id === created.id && item.is_global === created.is_global)
                ? [...items, created] : items;
            setActions(available);
            if (available.some((item) => item.type === 'agent')) {
                void fetchAgentTargets(PERSONAL_DELEGATION_SCOPE, controller.signal).then((catalog) => {
                    if (!Array.isArray(catalog.targets)) throw new Error('The authorized agent catalogue returned an invalid response.');
                    if (!controller.signal.aborted) setTargets(catalog);
                }).catch((cause: unknown) => { if (!controller.signal.aborted) setTargetError(message(cause)); });
            }
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setActionsError(message(cause));
        }).finally(() => { if (!controller.signal.aborted) setActionsLoading(false); });
        return () => controller.abort();
    }, [bootLoading, bootError, actionsRevision]);

    useEffect(() => {
        if (bootLoading || bootError || draft.agent_type !== 'local') return;
        const controller = new AbortController();
        setKnowledgeLoading(true);
        setKnowledgeError(null);
        void fetchAgentKnowledgeCatalog(controller.signal).then((catalog) => {
            if (!controller.signal.aborted) setKnowledge(catalog);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setKnowledgeError(message(cause));
        }).finally(() => { if (!controller.signal.aborted) setKnowledgeLoading(false); });
        return () => controller.abort();
    }, [bootLoading, bootError, draft.agent_type, knowledgeRevision]);

    const save = async () => {
        if (!options || readOnly || saving || iconBusy) return;
        const errors = [
            ...agentValidationErrors(draft, options),
            ...agentKnowledgeErrors(draft),
            ...newAgentActionErrors(draft, original?.record ?? null, actions, targets, ownerId),
            ...(advancedError ? [advancedError] : []),
        ];
        if (errors.length) {
            setHasSaveConflict(false);
            setSaveError(errors.join(' '));
            return;
        }
        setSaving(true);
        setSaveError(null);
        setHasSaveConflict(false);
        try {
            const resource = await saveAgentConfiguration(agentForSave(draft), original);
            if (!resource.record?.id) throw new Error('The save response did not include an agent identifier. Reload before trying again.');
            load(resource);
            clear();
            await refreshBootstrap();
            navigate('/workspace/agents', { replace: true, state: { workspaceEditorSaved: true, workspaceEditorFrom: location.key } });
        } catch (cause) {
            const conflict = cause instanceof ApiError && cause.status === 409;
            setHasSaveConflict(conflict && !isNew);
            setSaveError(conflict && !isNew
                ? 'This agent changed in another session. Your draft has been retained. Open the latest agent in a new tab to compare before discarding or reapplying your changes.'
                : conflict ? `${message(cause)} Your draft has been retained.` : message(cause));
        } finally {
            setSaving(false);
        }
    };

    if (bootLoading) return <div className="p-4"><p role="status" className="mb-3 text-sm text-text-3">Loading agent editor…</p><SectionSkeleton /></div>;
    if (bootError || !options) return (
        <div className="space-y-3 p-4">
            <AgentNotice error>{bootError || 'Editor options are unavailable.'} Any restored draft remains in memory.</AgentNotice>
            <div className="flex flex-wrap gap-2">
                <GlassButton type="button" onClick={() => setBootRevision((value) => value + 1)}>Retry editor</GlassButton>
                <Link to="/workspace/agents" className="rounded-lg px-3 py-2 text-sm text-accent">Back to agents</Link>
            </div>
        </div>
    );

    const structured = (content: ReactNode) => <fieldset disabled={Boolean(advancedError) || iconBusy} className="min-w-0">{content}</fieldset>;
    return (
        <WorkspaceEditorFrame
            title={isNew ? 'New agent' : draft.display_name || draft.name || 'Agent details'}
            description={isNew ? 'Configure a reusable assistant. Changes are saved only when you choose Save agent.' : `Stable ID: ${draft.id}`}
            backTo="/workspace/agents" dirty={dirty || iconBusy} saving={saving} readOnly={readOnly} error={arraySecretError || saveError}
            onSave={() => void save()} onDiscard={clear} saveLabel="Save agent" saveDisabled={Boolean(advancedError) || iconBusy}
            actions={<>
                {advancedError ? <span role="status" className="max-w-xs text-xs text-danger">
                    {arraySecretError ? 'Review stored array credentials before saving.' : 'Fix Additional settings JSON to enable saving.'}
                </span> : null}
                {hasSaveConflict ? (
                    <Link to={`${location.pathname}${location.search}`} target="_blank" rel="noopener noreferrer"
                        className="rounded-lg px-3 py-2 text-sm text-accent hover:bg-accent-soft">Open latest in a new tab</Link>
                ) : null}
                {!isNew && !dirty && draft.is_enabled !== false ? (
                <Link to={`/chat?agent_id=${encodeURIComponent(draft.id)}&agent_scope=${draft.is_global ? 'global' : 'personal'}&new=1`}
                    className="rounded-lg px-3 py-2 text-sm text-accent hover:bg-accent-soft">Use in chat</Link>
                ) : null}
            </>}
            sections={[
                {
                    id: 'identity', label: 'Identity',
                    content: <><AgentIdentityFields draft={draft} setDraft={setDraft} options={options} isNew={isNew} onIconBusyChange={setIconBusy} />
                        {restored ? <p role="status" className="mt-3 text-xs text-text-3">Your unsaved draft was restored from this tab’s memory.</p> : null}</>,
                },
                { id: 'model', label: 'Model & connection', content: structured(<AgentModelFields draft={draft} setDraft={setDraft} options={options} original={original} />) },
                { id: 'actions', label: 'Actions', content: structured(<AgentActionPicker draft={draft} setDraft={setDraft}
                    actions={actions} targets={targets} loading={actionsLoading} error={actionsError} targetError={targetError}
                    builtinActions={options.builtin_actions} ownerId={ownerId} canCreateActions={canCreateActions} readOnly={readOnly}
                    onRefresh={() => setActionsRevision((value) => value + 1)}
                    onNewAction={() => navigate(`/workspace/actions/new?returnTo=${encodeURIComponent(location.pathname)}`, { state: { preserveWorkspaceDraft: true, workspaceEditorFrom: location.key } })} />) },
                { id: 'knowledge', label: 'Assigned knowledge', content: structured(<AgentKnowledgeFields draft={draft} setDraft={setDraft}
                    catalog={knowledge} loading={knowledgeLoading} error={knowledgeError} readOnly={readOnly}
                    onRefresh={() => setKnowledgeRevision((value) => value + 1)} />) },
                { id: 'instructions', label: 'Instructions', content: <AgentInstructionsFields key={draft.agent_type}
                    draft={draft} setDraft={setDraft} actions={actions} catalog={knowledge} readOnly={readOnly}
                    contextError={actionsError || (readAgentKnowledgeEnabled(draft) ? knowledgeError : null)} /> },
                { id: 'advanced', label: 'Advanced', content: <AgentAdvancedFields draft={draft} setDraft={setDraft} options={options} original={original} /> },
                { id: 'templates', label: 'Examples & templates', content: structured(<div ref={templatesAnchor} tabIndex={-1}>
                    <AgentTemplatesPanel draft={draft} setDraft={setDraft} options={options} actions={actions} isNew={isNew} dirty={dirty} readOnly={readOnly} />
                </div>) },
            ]}
        />
    );
}

function readAgentKnowledgeEnabled(draft: AgentConfiguration): boolean {
    return isRecord(draft.other_settings.assigned_knowledge) && draft.other_settings.assigned_knowledge.enabled === true;
}

export function AgentEditorPage() {
    const { resourceId = 'new' } = useParams<{ resourceId?: string }>();
    const location = useLocation();
    const scope = new URLSearchParams(location.search).get('scope') === 'global' ? 'global' : 'personal';
    return <AgentEditorSession key={`${scope}:${resourceId}`} resourceId={resourceId} scope={scope} />;
}
