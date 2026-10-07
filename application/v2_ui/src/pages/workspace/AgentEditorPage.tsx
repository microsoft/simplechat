// AgentEditorPage.tsx

import { useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { BookOpen, Cpu, IdCard, LayoutTemplate, Plug, ScrollText, SlidersHorizontal, Sparkles } from 'lucide-react';
import { GlassButton } from '../../components/ui/primitives';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { SectionSkeleton } from '../../components/workspace/primitives';
import { AgentIcon, AgentIdentityFields } from '../../components/workspaceAgents/AgentIdentityFields';
import { AgentModelFields } from '../../components/workspaceAgents/AgentModelFields';
import { AgentActionPicker } from '../../components/workspaceAgents/AgentActionPicker';
import { AgentKnowledgeFields } from '../../components/workspaceAgents/AgentKnowledgeFields';
import { AgentInstructionsFields } from '../../components/workspaceAgents/AgentInstructionsFields';
import { AgentAdvancedFields, agentAdvancedError } from '../../components/workspaceAgents/AgentAdvancedFields';
import { AgentTemplatesPanel } from '../../components/workspaceAgents/AgentTemplatesPanel';
import { AgentNotice } from '../../components/workspaceAgents/AgentFields';
import { ApiError } from '../../lib/apiClient';
import { chatHrefForAgent } from '../../lib/conversationUrl';
import { type AgentTargetCatalog } from '../../lib/agentDelegation';
import { PERSONAL_AGENT_WORKBENCH, type AgentWorkbenchAdapter } from '../../lib/agentWorkbench';
import {
    isRecord, type ActionConfiguration, type ActionTypeDefinition, type AgentConfiguration, type AgentEditorOptions,
} from '../../lib/workspaceAuthoring';
import {
    clearWorkspaceActionHandoff, seedNewWorkspaceActionDraft, takeCreatedWorkspaceAction, takeWorkspaceActionHandoff, useWorkspaceEditorDraft,
} from '../../lib/workspaceEditorDrafts';
import { agentForSave, agentReasoningLevels, agentText, agentValidationErrors, applySafeAgentDraft, isAgentEditorEnvelope, newAgentDraft } from '../../lib/workspaceAgentAuthoring';
import { newAgentActionErrors } from '../../lib/workspaceAgentActions';
import { agentKnowledgeErrors, type AgentKnowledgeCatalog } from '../../lib/workspaceAgentKnowledge';
import {
    agentAssistValues, applyAgentAssistPatch, buildAgentAssistView, newPendingActionReference, pendingAgentActions,
    prunePendingAgentActions, resolvePendingAgentAction, type AgentAssistContext,
} from '../../lib/agentEditorAssist';
import { actionForSave, createActionDraft, validateActionDraft } from '../../lib/workspaceActionLogic';
import type { ModelCatalogEntry } from '../../lib/models';
import { useEditorAssist } from '../../components/editorAssist/useEditorAssist';
import { EditorAskAiPanel, EditorAskAiToggle, EditorAssistLockBanner } from '../../components/editorAssist/EditorAskAiPanel';
import { useBootstrapStore } from '../../stores/bootstrapStore';

function message(cause: unknown): string {
    return cause instanceof Error ? cause.message : 'The operation could not be completed.';
}

function AgentEditorSession({ resourceId, scope, adapter }: { resourceId: string; scope: string; adapter: AgentWorkbenchAdapter }) {
    const navigate = useNavigate();
    const location = useLocation();
    const ownerId = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const personalCanCreateActions = useBootstrapStore((state) => state.data?.workspace?.sections.actions?.enabled === true);
    const canCreateActions = adapter.scope.kind === 'personal' ? personalCanCreateActions : adapter.canCreateActions;
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const isNew = resourceId === 'new';
    const { draft, setDraft: setStoredDraft, original, load, clear, dirty, restored } =
        useWorkspaceEditorDraft<AgentConfiguration>('agents', `${scope}:${resourceId}`, newAgentDraft, adapter.draftScope);
    const setDraft: Dispatch<SetStateAction<AgentConfiguration>> = (update) => setStoredDraft((current) =>
        applySafeAgentDraft(current, prunePendingAgentActions(typeof update === 'function' ? update(current) : update), original));
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
    const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[] | null>(null);
    // Drafted actions an undo may bring back after a later turn or Remove dropped them.
    const pendingStash = useRef(new Map<string, ActionConfiguration>());
    const returnedAction = useRef<ActionConfiguration | null>(null);
    const handoffChecked = useRef(false);
    // A member without the edit hint sees the group editor read-only; personal scope always authors.
    const canAuthor = adapter.allows(isNew ? 'create' : 'edit', original?.record ?? draft);
    const readOnly = accessReadOnly || original?.read_only === true || !canAuthor;
    const advancedError = agentAdvancedError(draft, original);
    const arraySecretError = agentText(draft._editor_array_secret_error) || null;
    const assistEnabled = useBootstrapStore((state) => state.data?.features?.enable_agent_ai_assistant === true);
    const models = useBootstrapStore((state) => state.data?.catalogs?.models) as ModelCatalogEntry[] | undefined;
    const [assistOpen, setAssistOpen] = useState(false);
    const [jumpTo, setJumpTo] = useState<{ section: string; sequence: number } | null>(null);
    // Ask AI reads and changes the latest draft between renders, so it works from a ref.
    const draftRef = useRef(draft);
    draftRef.current = draft;
    const actionWorkbench = adapter.actionWorkbench;
    const assistContext = (current: AgentConfiguration): AgentAssistContext | null => options ? {
        options, actions, targets, knowledge, knowledgeScopes: adapter.knowledgeScopes,
        reasoningLevels: agentReasoningLevels(current, options, models), ownerId, isNew,
        ...(actionTypes && canCreateActions && actionWorkbench ? {
            actionTypes,
            newPendingReference: newPendingActionReference,
            recallPendingAction: (reference: string) => pendingStash.current.get(reference),
        } : {}),
    } : null;
    const assist = useEditorAssist({
        kind: 'agent',
        available: assistEnabled && !readOnly && !bootLoading && !bootError && Boolean(options),
        scope: adapter.scope.kind === 'group' ? { kind: 'group', id: adapter.scope.id } : { kind: adapter.scope.kind },
        recordKey: `${scope}:${resourceId}`,
        blocked: saving || iconBusy || Boolean(advancedError),
        buildView: () => {
            const context = assistContext(draftRef.current);
            if (!context) throw new Error('The agent editor is still loading.');
            return buildAgentAssistView(draftRef.current, context);
        },
        apply: (patch, newItems) => {
            const current = draftRef.current;
            const context = assistContext(current);
            const next = context ? applyAgentAssistPatch(current, patch, context, newItems) : null;
            if (!next || !context) return null;
            for (const { reference, action } of pendingAgentActions(next)) pendingStash.current.set(reference, action);
            draftRef.current = next;
            setDraft(next);
            return agentAssistValues(next, { ...context, reasoningLevels: agentReasoningLevels(next, context.options, models) });
        },
        onJump: (section) => setJumpTo((current) => ({ section, sequence: (current?.sequence ?? 0) + 1 })),
    });
    const assistShown = assist.available && assistOpen;

    useEffect(() => {
        const controller = new AbortController();
        setBootLoading(true);
        setBootError(null);
        void Promise.all([
            adapter.fetchOptions(controller.signal),
            isNew ? Promise.resolve(null) : adapter.fetchEditor(resourceId, scope, controller.signal),
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
        const action = takeCreatedWorkspaceAction(location.pathname, adapter.draftScope);
        if (!action) return;
        const handoff = takeWorkspaceActionHandoff(location.pathname, adapter.draftScope);
        returnedAction.current = action;
        setActions((current) => [...current.filter((item) => item.id !== action.id || item.is_global !== action.is_global), action]);
        setDraft((current) => {
            // An action Ask AI drafted and the person finished in the action editor replaces its placeholder.
            if (handoff && current.actions_to_load.includes(handoff)) return resolvePendingAgentAction(current, handoff, action.id);
            return {
                ...current,
                actions_to_load: current.actions_to_load.includes(action.id) ? current.actions_to_load : [...current.actions_to_load, action.id],
            };
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bootLoading, bootError, readOnly, location.pathname]);

    useEffect(() => {
        if (bootLoading || bootError) return;
        const controller = new AbortController();
        setActionsLoading(true);
        setActionsError(null);
        setTargetError(null);
        setTargets(null);
        void adapter.fetchActions(controller.signal).then((items) => {
            if (controller.signal.aborted) return;
            const created = returnedAction.current;
            const available = created && !items.some((item) => item.id === created.id && item.is_global === created.is_global)
                ? [...items, created] : items;
            setActions(available);
            if (available.some((item) => item.type === 'agent')) {
                void adapter.fetchTargets(controller.signal).then((catalog) => {
                    if (!Array.isArray(catalog.targets)) throw new Error('The authorized agent catalogue returned an invalid response.');
                    if (!controller.signal.aborted) setTargets(catalog);
                }).catch((cause: unknown) => { if (!controller.signal.aborted) setTargetError(message(cause)); });
            }
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setActionsError(message(cause));
        }).finally(() => { if (!controller.signal.aborted) setActionsLoading(false); });
        return () => controller.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bootLoading, bootError, actionsRevision]);

    useEffect(() => {
        if (!assistEnabled || readOnly || bootLoading || bootError || !canCreateActions || !actionWorkbench) return;
        const controller = new AbortController();
        // Without the catalogue Ask AI only assigns existing actions, so a failure stays quiet.
        void actionWorkbench.fetchTypes(controller.signal).then((types) => {
            if (!controller.signal.aborted && Array.isArray(types)) setActionTypes(types);
        }).catch(() => { if (!controller.signal.aborted) setActionTypes(null); });
        return () => controller.abort();
    }, [assistEnabled, readOnly, bootLoading, bootError, canCreateActions, actionWorkbench]);

    useEffect(() => {
        if (bootLoading || bootError || draft.agent_type !== 'local') return;
        const controller = new AbortController();
        setKnowledgeLoading(true);
        setKnowledgeError(null);
        void adapter.fetchKnowledge(controller.signal).then((catalog) => {
            if (!controller.signal.aborted) setKnowledge(catalog);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setKnowledgeError(message(cause));
        }).finally(() => { if (!controller.signal.aborted) setKnowledgeLoading(false); });
        return () => controller.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bootLoading, bootError, draft.agent_type, knowledgeRevision]);

    const pendingActions = pendingAgentActions(draft);
    const actionTypeFor = (action: ActionConfiguration) => actionTypes?.find((type) => type.type === action.type);
    const pendingIssues = Object.fromEntries(pendingActions.map(({ reference, action }) => [
        reference, [...new Set(Object.values(validateActionDraft(actionForSave(action), actionTypeFor(action))))],
    ]));

    const finishPendingAction = (reference: string) => {
        const pending = pendingActions.find((item) => item.reference === reference);
        if (!pending || !actionWorkbench) return;
        seedNewWorkspaceActionDraft(location.pathname, pending.action, createActionDraft(), actionWorkbench.draftScope, reference);
        navigate(`${adapter.actionsBasePath}/new?returnTo=${encodeURIComponent(location.pathname)}`,
            { state: { preserveWorkspaceDraft: true, workspaceEditorFrom: location.key } });
    };

    const save = async () => {
        if (!options || readOnly || saving || iconBusy) return;
        const pendingErrors = pendingActions.flatMap(({ reference, action }) => (pendingIssues[reference] ?? []).length
            ? [`New action ${agentText(action.displayName) || action.name} needs attention: ${pendingIssues[reference].join(' ')} Finish it in the action editor or remove it.`]
            : []);
        if (pendingActions.length && (!actionWorkbench || !canCreateActions)) pendingErrors.push('New actions from Ask AI can’t be created here. Remove them before saving.');
        const errors = [
            ...agentValidationErrors(draft, options),
            ...agentKnowledgeErrors(draft),
            ...newAgentActionErrors(draft, original?.record ?? null, actions, targets, ownerId),
            ...(advancedError ? [advancedError] : []),
            ...pendingErrors,
        ];
        if (errors.length) {
            setHasSaveConflict(false);
            setSaveError(errors.join(' '));
            return;
        }
        setSaving(true);
        setSaveError(null);
        setHasSaveConflict(false);
        let working = draft;
        try {
            // Create the actions Ask AI drafted first, so the agent saves with their real IDs.
            for (const { reference, action } of pendingActions) {
                if (!actionWorkbench) break;
                let created: ActionConfiguration | undefined;
                try {
                    created = (await actionWorkbench.save(actionForSave(action), null)).record;
                } catch (cause) {
                    throw new Error(`New action ${agentText(action.displayName) || action.name} could not be created: ${message(cause)} The agent was not saved.`);
                }
                if (!created?.id) throw new Error('An action save response did not include an identifier. The agent was not saved.');
                const saved = created;
                working = resolvePendingAgentAction(working, reference, saved.id);
                pendingStash.current.delete(reference);
                setActions((current) => [...current.filter((item) => item.id !== saved.id), saved]);
                setDraft(working);
            }
            const { _pendingActions: _drafts, ...agent } = working;
            const resource = await adapter.save(agentForSave(agent as AgentConfiguration), original);
            if (!resource.record?.id) throw new Error('The save response did not include an agent identifier. Reload before trying again.');
            load(resource);
            clear();
            await refreshBootstrap();
            navigate(adapter.basePath, { replace: true, state: { workspaceEditorSaved: true, workspaceEditorFrom: location.key } });
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
                <Link to={adapter.basePath} className="rounded-lg px-3 py-2 text-sm text-accent">Back to agents</Link>
            </div>
        </div>
    );

    const structured = (content: ReactNode) => <fieldset disabled={Boolean(advancedError) || iconBusy} className="min-w-0">{content}</fieldset>;
    return (
        <WorkspaceEditorFrame
            title={isNew ? 'New agent' : draft.display_name || draft.name || 'Agent details'} icon={Sparkles}
            iconNode={draft.icon ? <AgentIcon icon={draft.icon} /> : undefined}
            description={isNew ? 'Configure a reusable assistant. Changes are saved only when you choose Save agent.' : draft.description || undefined}
            backTo={adapter.basePath} dirty={dirty || iconBusy} saving={saving} readOnly={readOnly} error={arraySecretError || saveError}
            onSave={() => void save()} onDiscard={clear} saveLabel="Save agent" saveDisabled={Boolean(advancedError) || iconBusy}
            initialSection={new URLSearchParams(location.search).get('templates') === '1' ? 'templates' : undefined}
            sidePanel={assist.available ? <EditorAskAiPanel assist={assist} id="agent-ask-ai-panel" inputId="agent-ask-ai-input"
                onClose={() => setAssistOpen(false)} /> : undefined}
            sidePanelOpen={assistShown} aiChangedSections={assist.changedSections}
            locked={Boolean(assist.pending)} jumpTo={jumpTo}
            lockBanner={assist.pending ? <EditorAssistLockBanner pending={assist.pending} onCancel={assist.cancel} /> : undefined}
            actions={<>
                {assist.available ? <EditorAskAiToggle id="agent-ask-ai-toggle" open={assistShown} controls="agent-ask-ai-panel"
                    onToggle={() => setAssistOpen((value) => !value)} /> : null}
                {advancedError ? <span role="status" className="max-w-xs text-xs text-danger">
                    {arraySecretError ? 'Review stored array credentials before saving.' : 'Fix Additional settings JSON to enable saving.'}
                </span> : null}
                {hasSaveConflict ? (
                    <Link to={`${location.pathname}${location.search}`} target="_blank" rel="noopener noreferrer"
                        className="rounded-lg px-3 py-2 text-sm text-accent hover:bg-accent-soft">Open latest in a new tab</Link>
                ) : null}
                {!isNew && !dirty && adapter.canUseInChat(draft) ? (
                <Link to={chatHrefForAgent(draft.id, adapter.chatScope(draft))}
                    className="rounded-lg px-3 py-2 text-sm text-accent hover:bg-accent-soft">Use in chat</Link>
                ) : null}
            </>}
            sections={[
                {
                    id: 'identity', label: 'Identity', icon: IdCard,
                    description: 'The name people see, what the agent is for, its type and its icon.',
                    content: <><AgentIdentityFields draft={draft} setDraft={setDraft} options={options} isNew={isNew} onIconBusyChange={setIconBusy} />
                        {restored ? <p role="status" className="mt-3 text-xs text-text-3">Your unsaved draft was restored from this tab’s memory.</p> : null}</>,
                },
                { id: 'model', label: 'Model & connection', icon: Cpu,
                    description: 'The model that answers, or the Foundry resource that runs the agent.', content: structured(<AgentModelFields draft={draft} setDraft={setDraft} options={options} original={original}
                    allowCustomEndpoints={adapter.allowsCustomEndpoints(options.settings)} discoverFoundryResources={adapter.discoverFoundryResources}
                    neutralReadOnlyCopy={adapter.scope.kind === 'group' && readOnly} />) },
                { id: 'actions', label: 'Actions', icon: Plug,
                    description: 'The actions the agent can call, and what each one may do.', content: structured(<AgentActionPicker draft={draft} setDraft={setDraft}
                    actions={actions} targets={targets} loading={actionsLoading} error={actionsError} targetError={targetError}
                    builtinActions={options.builtin_actions} ownerId={ownerId} canCreateActions={canCreateActions} readOnly={readOnly}
                    scopeKind={adapter.scope.kind}
                    pendingActions={pendingActions} pendingIssues={pendingIssues}
                    onFinishPendingAction={actionWorkbench ? finishPendingAction : undefined}
                    onRefresh={() => setActionsRevision((value) => value + 1)}
                    onNewAction={() => {
                        clearWorkspaceActionHandoff(location.pathname, adapter.draftScope);
                        navigate(`${adapter.actionsBasePath}/new?returnTo=${encodeURIComponent(location.pathname)}`, { state: { preserveWorkspaceDraft: true, workspaceEditorFrom: location.key } });
                    }} />) },
                { id: 'knowledge', label: 'Assigned knowledge', icon: BookOpen,
                    description: 'The documents, tags and web pages the agent answers from.', content: structured(<AgentKnowledgeFields draft={draft} setDraft={setDraft}
                    catalog={knowledge} loading={knowledgeLoading} error={knowledgeError} readOnly={readOnly} knowledgeScopes={adapter.knowledgeScopes}
                    onRefresh={() => setKnowledgeRevision((value) => value + 1)} />) },
                { id: 'instructions', label: 'Instructions', icon: ScrollText,
                    description: 'How the agent behaves and responds.', content: <AgentInstructionsFields key={draft.agent_type}
                    draft={draft} setDraft={setDraft} actions={actions} catalog={knowledge} readOnly={readOnly} draftInstructions={adapter.draftInstructions}
                    contextError={actionsError || (readAgentKnowledgeEnabled(draft) ? knowledgeError : null)} /> },
                { id: 'advanced', label: 'Advanced', icon: SlidersHorizontal,
                    description: 'Token and reasoning limits, and every setting as JSON.', content: <AgentAdvancedFields draft={draft} setDraft={setDraft} options={options} original={original} /> },
                { id: 'templates', label: 'Examples & templates', icon: LayoutTemplate,
                    description: 'Approved examples and templates to start a new agent from.', content: structured(
                    <AgentTemplatesPanel draft={draft} setDraft={setDraft} options={options} actions={actions} isNew={isNew} dirty={dirty} readOnly={readOnly}
                        submissionAllowed={adapter.allowsTemplateSubmission(options.settings)} scope={adapter.scope.kind} />) },
            ]}
        />
    );
}

function readAgentKnowledgeEnabled(draft: AgentConfiguration): boolean {
    return isRecord(draft.other_settings.assigned_knowledge) && draft.other_settings.assigned_knowledge.enabled === true;
}

export function AgentEditorPage({ adapter = PERSONAL_AGENT_WORKBENCH }: { adapter?: AgentWorkbenchAdapter }) {
    const { resourceId = 'new' } = useParams<{ resourceId?: string }>();
    const location = useLocation();
    const scope = new URLSearchParams(location.search).get('scope') === 'global' ? 'global' : 'personal';
    return <AgentEditorSession key={JSON.stringify([adapter.basePath, scope, resourceId])} resourceId={resourceId} scope={scope} adapter={adapter} />;
}
