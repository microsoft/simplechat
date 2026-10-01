// WorkflowEditorDialog.tsx
// Native V2 workflow create/edit dialog.

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { AlertTriangle, Plus, Redo2, Undo2 } from 'lucide-react';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Modal } from '../ui/Modal';
import { GlassButton, Toggle } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import { WorkflowDocumentPicker } from './WorkflowDocumentPicker';
import { WorkflowAgentPicker, WorkflowModelPicker, WorkflowTaskFields } from './WorkflowTaskFields';
import { WorkflowFieldDraftsProvider, workflowDraftOwners } from './WorkflowFieldDrafts';
import { WorkflowHistoryBoundary, useWorkflowAuthoringHistory } from './WorkflowAuthoringHistory';
import { WorkflowStructuredList } from './WorkflowStructuredList';
import { WorkflowMicrosoft365RunAs } from './WorkflowMicrosoft365RunAs';
import { WorkflowFlowAuthoring } from './WorkflowFlowAuthoring';
import { WorkflowFlowLimitFields } from './WorkflowStructuredFields';
import { WorkflowFileSyncFields, useWorkflowFileSyncSources } from './WorkflowFileSyncFields';
import { WorkflowScheduleFields } from './WorkflowScheduleFields';
import { WorkflowAlertEditor } from './WorkflowAlertEditor';
import { WorkflowAlertSummary } from './WorkflowAlertSummary';
import { useWorkflowAuthoring } from './useWorkflowAuthoring';
import { useWorkflowAssist } from './useWorkflowAssist';
import { WorkflowAskAiTab, WorkflowAskAiToggle, WorkflowAssistLockBanner } from './WorkflowAskAiTab';
import {
    WorkflowChangedField, WorkflowChangeNotice, WorkflowChangesTab, WorkflowChangesToggle, WorkflowChangeTrackingScope,
    WorkflowEditorSidePanel, WorkflowReferenceChanges, WorkflowRemovedItemRows, focusWorkflowChangeTarget,
    workflowSessionSaveNeedsConfirmation,
} from './WorkflowChangeTracking';
import { ApiError } from '../../lib/apiClient';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    WORKFLOW_TASK_ORDER_KEY, parseWorkflowChangeKey, workflowChangeItemKey, workflowTasksInOrder, type WorkflowChange,
} from '../../lib/workflowChangeTracking';
import {
    convertToStructuredWorkflow,
    enclosingFlowLoopControls,
    flowTaskNodeId,
    flowUnsupportedReason,
    isFlowRegion,
    type WorkflowTaskNode,
} from '../../lib/workflowFlow';
import {
    createWorkflowTask,
    newWorkflowDefinition,
    normalizeWorkflowDefinition,
    preservedWorkflowFieldLabels,
    sameWorkflowDefinition,
    saveWorkflowDefinition,
    workflowErrorCode,
    workflowErrorMessage,
    workflowFileSyncConfig,
    workflowForFlowPreview,
    workflowForSave,
    workflowMonitorFileSyncConfig,
    workflowScopeKey,
    workflowValidationErrors,
    workflowAgentKey,
    WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_CODE,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowFileSyncSourceListing,
    type WorkflowScope,
    type WorkflowTask,
} from '../../lib/workflowEditor';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';
const textareaClass = `${inputClass} min-h-24`;

function fieldId(prefix: string, name: string): string {
    return `${prefix}-${name}`;
}

function fieldLabel(name: string, required = false) {
    return `${name}${required ? ' *' : ''}`;
}

function setTaskAt(
    tasks: WorkflowTask[],
    taskId: string,
    update: (task: WorkflowTask) => WorkflowTask,
): WorkflowTask[] {
    return workflowTasksInOrder(tasks.map((task) => (task.id === taskId ? update(task) : task)));
}

/** The side panel sits beside the editor from Tailwind's xl breakpoint; below it, it replaces the editor. */
function sidePanelBesideEditor(): boolean {
    return typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 80rem)').matches;
}

/** Where Jump goes when a change has no element of its own on screen: the section it belongs to. */
function changeSection(root: HTMLElement, key: string): HTMLElement | null {
    const info = parseWorkflowChangeKey(key);
    if (info.scope === 'workflow' && info.field === 'file_sync') {
        const fileSync = root.querySelector('[aria-label="File Sync sources"]')?.closest<HTMLElement>('section');
        if (fileSync) return fileSync;
    }
    const label = info.scope === 'reference' || info.scope === 'order' && info.list === 'references' ? 'Workflow shared references'
        : info.scope !== 'workflow' || info.field === 'definition_version' ? 'Workflow tasks' : 'Workflow basics';
    return root.querySelector<HTMLElement>(`section[aria-label="${label}"]`);
}

/** Where Jump goes: a change from the Changes tab, or one Ask AI made. */
type WorkflowJumpChange = Pick<WorkflowChange, 'key' | 'target'>;

function workflowRunnerSummary(workflow: WorkflowDefinition, options: WorkflowEditorOptions): string {
    if (workflow.runner_type === 'agent') {
        const agent = options.agents.find((item) => workflowAgentKey(item) === workflowAgentKey(workflow.selected_agent));
        return agent?.display_name || agent?.name || 'Agent not selected';
    }
    const model = options.models.find((item) =>
        item.endpoint_id === workflow.model_endpoint_id && item.model_id === workflow.model_id);
    return model?.label || 'App default model';
}

export function WorkflowEditorDialog({
    scope,
    workflow,
    options,
    onClose,
    onSaved,
    onDirtyChange,
    onBusyChange,
    interactionDisabled = false,
    initialDraft = null,
    onSaveOverride,
    onReload,
}: {
    scope: WorkflowScope;
    workflow: WorkflowDefinition | null;
    options: WorkflowEditorOptions;
    onClose: () => void;
    onSaved: (workflow: WorkflowDefinition) => void;
    onDirtyChange?: (dirty: boolean) => void;
    onBusyChange?: (busy: boolean) => void;
    interactionDisabled?: boolean;
    /** A new workflow's starting point, such as a proposal from chat; ignored when editing a saved workflow. */
    initialDraft?: WorkflowDefinition | null;
    /** Saves in place of the workflow save route, such as accepting a proposal with this draft. */
    onSaveOverride?: (
        draft: WorkflowDefinition,
        original: WorkflowDefinition | null,
    ) => Promise<{ success?: boolean; workflow?: WorkflowDefinition }>;
    /**
     * Reopen the saved workflow, discarding the draft. Ask AI offers it when the saved workflow
     * changed after the editor opened; without it, the reader closes and reopens the editor.
     */
    onReload?: () => Promise<void>;
}) {
    const [original] = useState<WorkflowDefinition | null>(() =>
        workflow ? structuredClone(workflow) : null,
    );
    const [baseline, setBaseline] = useState<WorkflowDefinition>(() =>
        workflow ? structuredClone(workflow) : initialDraft ? structuredClone(initialDraft) : newWorkflowDefinition(scope),
    );
    const history = useWorkflowAuthoringHistory(baseline);
    const draft = history.draft;
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [confirmClose, setConfirmClose] = useState(false);
    const [confirmStructured, setConfirmStructured] = useState(false);
    const [accessLost, setAccessLost] = useState(false);
    const [surface, setSurface] = useState<'list' | 'flow'>('list');
    const authoringRef = useRef<HTMLDivElement>(null);
    const [changesOpen, setChangesOpen] = useState(false);
    const [sideTab, setSideTab] = useState<'changes' | 'askai'>('changes');
    const [confirmingSave, setConfirmingSave] = useState(false);
    const [panelFocus, setPanelFocus] = useState<{ target: 'tab' | 'confirm' | 'list' | 'ask'; sequence: number } | null>(null);
    const [jump, setJump] = useState<{ change: WorkflowJumpChange; retry: boolean; sequence: number } | null>(null);
    const focusSequence = useRef(0);
    const confirmHeadingRef = useRef<HTMLHeadingElement>(null);
    const changesHeadingRef = useRef<HTMLHeadingElement>(null);
    const errorRef = useRef<HTMLParagraphElement>(null);
    const sidePanelBaseId = useId();
    const changesToggleId = `${sidePanelBaseId}-changes-toggle`;
    const askAiToggleId = `${sidePanelBaseId}-ask-ai-toggle`;
    const askAiInputId = `${sidePanelBaseId}-ask-ai-input`;
    const sidePanelId = `${sidePanelBaseId}-side-panel`;
    const scopeKey = workflowScopeKey(scope);
    const fieldDrafts = useMemo(() => ({
        store: history.session.fields,
        ...history.session.fields.summary(workflowDraftOwners(draft)),
    }), [history.session, history.revision, draft]);
    const schemaFieldErrors = fieldDrafts.taskSchemaErrors;
    const unsupportedFlow = flowUnsupportedReason(draft, options);
    const unsupported = !(options.supported_definition_versions ?? [1, 2]).includes(draft.definition_version) || Boolean(unsupportedFlow);
    const readOnly = unsupported || !options.can_manage || Boolean(draft.active_run_id) || accessLost;
    const localRunner = draft.definition_version === 3 && draft.tasks.some((task) =>
        task.runner.type === 'inherit' && !task.publication &&
        (task.input_processing === 'saved_record_report' || enclosingFlowLoopControls(draft, flowTaskNodeId(draft, task.id)).length > 0));
    const dirty = !sameWorkflowDefinition(baseline, draft) || fieldDrafts.pending;
    const preserved = preservedWorkflowFieldLabels(original);
    const groupScope = scope.type === 'group';
    const fileSyncSources = useWorkflowFileSyncSources(scope, !readOnly);
    const fileSyncTriggerOffered = draft.trigger_type === 'file_sync' ||
        fileSyncSources.status === 'ready' && fileSyncSources.sources.length > 0;
    const scheduled = draft.trigger_type === 'interval' || draft.trigger_type === 'file_sync';
    // Once loaded, the group's source list lets validation apply the save's File Sync gate and source checks.
    const fileSyncListing = useMemo<WorkflowFileSyncSourceListing | null>(() => (
        groupScope && fileSyncSources.status === 'ready' && fileSyncSources.fileSyncEnabled !== null
            ? { fileSyncEnabled: fileSyncSources.fileSyncEnabled, sources: fileSyncSources.sources } : null
    ), [groupScope, fileSyncSources.status, fileSyncSources.fileSyncEnabled, fileSyncSources.sources]);
    const validationErrors = useMemo(() => workflowValidationErrors(draft, options, original, fileSyncListing),
        [draft, options, original, fileSyncListing]);
    const schemaErrors = useMemo(() => draft.tasks.flatMap((task, index) => {
        if (!task.output_contract?.schema) {
            return [];
        }
        try {
            JSON.stringify(task.output_contract.schema);
            return [];
        } catch {
            return [`Task ${index + 1} output schema cannot be saved.`];
        }
    }), [draft.tasks]);
    const visibleSchemaErrors = useMemo(() => draft.tasks.map((task) => schemaFieldErrors.get(task.id))
        .filter((message): message is string => Boolean(message)), [draft.tasks, schemaFieldErrors]);
    const allErrors = useMemo(() => [...validationErrors, ...schemaErrors, ...visibleSchemaErrors],
        [validationErrors, schemaErrors, visibleSchemaErrors]);
    const flowPreview = useMemo(() => {
        if (surface !== 'flow' || readOnly || allErrors.length) return { definition: null, error: '' };
        try {
            return { definition: workflowForFlowPreview(workflowForSave(draft, original, scope)), error: '' };
        } catch (cause: unknown) {
            return { definition: null, error: workflowErrorMessage(cause, 'This draft cannot be previewed safely. Your edits are retained.') };
        }
    }, [surface, readOnly, allErrors, draft, original, scopeKey]);
    const setWorkflow: Dispatch<SetStateAction<WorkflowDefinition>> = (update) => {
        setError('');
        history.session.changeDraft(update);
    };
    const authoring = useWorkflowAuthoring({
        draft, options, readOnly, saving, onError: setError,
        getDraft: () => history.session.draft,
        onRejected: () => history.session.reject(),
        onChange: (next, command, selectedId) => {
            const structural = command.type === 'add' || command.type === 'move' || command.type === 'remove';
            const affectedId = command.type === 'move' || command.type === 'remove' ? command.nodeId : selectedId;
            const accepted = history.session.changeDraft(next, structural ? {
                label: command.type === 'add' ? `Add ${command.kind.replaceAll('_', ' ')}`
                    : command.type === 'move' ? 'Move block' : 'Remove block',
                targetId: affectedId,
            } : undefined);
            history.session.target(affectedId);
            return accepted;
        },
    });
    const recoverAuthoring = (before: WorkflowDefinition, after: WorkflowDefinition, targetId: string | undefined, focus: boolean) => {
        // Only structured drafts carry block selection and layout; a classic draft has none to recover.
        if (isFlowRegion(before.flow) && isFlowRegion(after.flow)) authoring.recover(before, after, targetId, focus);
        else if (isFlowRegion(before.flow) || isFlowRegion(after.flow)) authoring.reset();
    };
    history.session.configure({
        options, readOnly, saving, commandPending: Boolean(authoring.pending), selectionId: authoring.selectedId, onError: setError,
        onRestore: (before, after, targetId) => recoverAuthoring(before, after, targetId,
            !document.activeElement?.closest('[data-workflow-history-controls]')),
        onRollback: (before, after, targetId) => recoverAuthoring(before, after, targetId, false),
    });
    const panelOpen = changesOpen && !readOnly;
    // The bootstrap sends this per user: on only where the setting, personal workflows and the role allow it.
    const askAiEnabled = useBootstrapStore((state) => state.data?.features?.enable_workflow_ai_assistant === true);
    const askAiAvailable = askAiEnabled && scope.type === 'personal' && !readOnly;
    const panelTab = askAiAvailable ? sideTab : 'changes';
    const onAccessLost = useCallback((status: number) => {
        setAccessLost(true);
        history.session.invalidate();
        authoring.reset();
        setError(status === 404
            ? 'This workflow is no longer available. Cached authoring details were removed. Close this editor before reopening a workflow.'
            : 'Current authoring access could not be confirmed. Cached authoring details were removed. Close and reopen after access is restored.');
    }, [history.session, authoring.reset]);
    const hadManagementAccess = useRef(options.can_manage);
    useEffect(() => {
        if (hadManagementAccess.current && !options.can_manage) onAccessLost(403);
        hadManagementAccess.current = options.can_manage;
    }, [options.can_manage, onAccessLost]);

    useEffect(() => {
        if (surface !== 'list' || !authoring.focusRequest || accessLost) return;
        const id = authoring.focusRequest.id;
        const block = [...(authoringRef.current?.querySelectorAll<HTMLElement>('[data-workflow-authoring-id]') ?? [])]
            .find((element) => element.dataset.workflowAuthoringId === id);
        const field = authoring.focusRequest.fields
            ? block?.querySelector<HTMLElement>('input:not(:disabled), textarea:not(:disabled), select:not(:disabled)') : null;
        (field ?? block)?.focus({ preventScroll: true });
        block?.scrollIntoView({ block: 'nearest' });
    }, [surface, authoring.focusRequest, accessLost]);

    const openChanges = (target: 'tab' | 'confirm') => {
        setSideTab('changes');
        setChangesOpen(true);
        setPanelFocus({ target, sequence: ++focusSequence.current });
    };
    const openAskAi = () => {
        setSideTab('askai');
        setConfirmingSave(false);
        setChangesOpen(true);
        setPanelFocus({ target: 'ask', sequence: ++focusSequence.current });
    };
    const selectSideTab = (tab: string) => {
        // Leaving Changes ends a save review; Save starts it again.
        if (tab === 'askai') setConfirmingSave(false);
        setSideTab(tab === 'askai' ? 'askai' : 'changes');
    };
    const closeChanges = (focusToggle: boolean) => {
        setChangesOpen(false);
        setConfirmingSave(false);
        const toggleId = panelTab === 'askai' ? askAiToggleId : changesToggleId;
        if (focusToggle) requestAnimationFrame(() => document.getElementById(toggleId)?.focus());
    };
    const jumpToChange = (change: WorkflowJumpChange) => {
        if (!sidePanelBesideEditor()) closeChanges(false);
        if (surface === 'flow' && draft.definition_version === 3) {
            const info = parseWorkflowChangeKey(change.key);
            const nodeId = change.target.nodeId ?? (info.scope === 'region' ? info.id : undefined);
            if (nodeId) {
                history.session.closeGroup();
                authoring.setSelectedId(nodeId);
            }
        }
        setJump({ change, retry: true, sequence: ++focusSequence.current });
    };
    const assist = useWorkflowAssist({
        available: askAiAvailable,
        history,
        options,
        workflowId: original?.id || null,
        blocked: saving || Boolean(history.pending) || Boolean(authoring.pending) || interactionDisabled,
        onJump: jumpToChange,
    });
    // While Ask AI works, the editor is locked so its answer applies to the draft it was sent with.
    const assistPending = Boolean(assist.pending);
    const historyBlockedReason = saving ? 'Workflow history is unavailable while saving.'
        : authoring.pending || history.pending ? 'Finish or cancel the current confirmation first.'
            : assistPending ? 'Wait for Ask AI to finish, or cancel it.' : '';

    useEffect(() => {
        if (!panelFocus) return;
        const frame = requestAnimationFrame(() => {
            const selectedTab = () => document.getElementById(sidePanelId)?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
            const askInput = () => {
                const input = document.getElementById(askAiInputId);
                return input instanceof HTMLTextAreaElement && !input.disabled ? input : null;
            };
            const target = panelFocus.target === 'confirm' ? confirmHeadingRef.current
                : panelFocus.target === 'list' ? changesHeadingRef.current
                    : panelFocus.target === 'ask' ? askInput() ?? selectedTab() : selectedTab();
            target?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [panelFocus, sidePanelId, askAiInputId]);

    useEffect(() => {
        if (!jump) return;
        const frame = requestAnimationFrame(() => {
            const root = authoringRef.current;
            if (!root) return;
            const { change } = jump;
            const itemKey = workflowChangeItemKey(change.key);
            const exact = root.querySelector<HTMLElement>(`[data-workflow-change-key="${CSS.escape(change.target.focusKey)}"]`)
                ?? (itemKey ? root.querySelector<HTMLElement>(`[data-workflow-change-item="${CSS.escape(itemKey)}"]`) : null);
            if (!exact && jump.retry && surface === 'flow') {
                // The Flow surface shows one block's fields at a time; the List shows every field.
                history.session.closeGroup();
                setSurface('list');
                setJump({ change, retry: false, sequence: ++focusSequence.current });
                return;
            }
            const target = exact ?? changeSection(root, change.key);
            if (!target) return;
            for (let details = target.closest('details'); details; details = details.parentElement?.closest('details') ?? null) {
                details.open = true;
            }
            focusWorkflowChangeTarget(target);
        });
        return () => cancelAnimationFrame(frame);
    }, [jump]);

    useEffect(() => {
        if (!panelOpen) return;
        // Escape inside the side panel closes the panel, not the editor.
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape' || event.defaultPrevented) return;
            const active = document.activeElement;
            const panel = document.getElementById(sidePanelId);
            if (!active || !(panel?.contains(active) || active.id === changesToggleId || active.id === askAiToggleId)) return;
            // An open # menu or document picker closes itself on this Escape, and the panel stays open.
            const picker = panel?.querySelector('[data-context-picker]');
            if (picker || active.closest('[data-composer-menu-open]')) {
                if (picker?.contains(active)) {
                    // The picker's search box goes with it, so carry on in the Ask AI input.
                    window.setTimeout(() => {
                        if (!document.getElementById(sidePanelId)?.contains(document.activeElement)) {
                            document.getElementById(askAiInputId)?.focus();
                        }
                    }, 0);
                }
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            closeChanges(true);
        };
        window.addEventListener('keydown', onKeyDown, true);
        return () => window.removeEventListener('keydown', onKeyDown, true);
    }, [panelOpen, panelTab, sidePanelId, changesToggleId, askAiToggleId, askAiInputId]);

    // When the lock ends and took focus with it (its Cancel button is gone), carry on in Ask AI.
    const wasAssistPending = useRef(false);
    useEffect(() => {
        const was = wasAssistPending.current;
        wasAssistPending.current = assistPending;
        if (!was || assistPending) return undefined;
        const frame = requestAnimationFrame(() => {
            const active = document.activeElement;
            if (active && active !== document.body) return;
            const input = document.getElementById(askAiInputId);
            const target = input instanceof HTMLTextAreaElement && !input.disabled ? input : document.getElementById(askAiToggleId);
            target?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [assistPending, askAiInputId, askAiToggleId]);

    const shownError = useRef(error);
    useEffect(() => {
        const appeared = Boolean(error) && error !== shownError.current;
        shownError.current = error;
        if (!appeared || !panelOpen || sidePanelBesideEditor()) return;
        // Narrow screens show the panel instead of the editor, so a new error brings the editor back.
        closeChanges(false);
        requestAnimationFrame(() => errorRef.current?.focus());
    }, [error, panelOpen]);

    const switchSurface = (next: 'list' | 'flow') => {
        history.session.closeGroup();
        setSurface(next);
        const id = authoring.selectedId ?? (isFlowRegion(draft.flow) ? draft.flow.id : null);
        if (id) authoring.requestFocus(id);
    };

    useEffect(() => {
        onDirtyChange?.(dirty);
        return () => onDirtyChange?.(false);
    }, [dirty, onDirtyChange]);

    useEffect(() => {
        onBusyChange?.(saving);
        return () => onBusyChange?.(false);
    }, [saving, onBusyChange]);

    useEffect(() => {
        if (!dirty || readOnly) {
            return;
        }
        const beforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty, readOnly]);

    const close = () => {
        if (saving || history.session.saving) return;
        history.session.closeGroup();
        const current = history.session.getSnapshot();
        if (current.pending) {
            history.session.cancel();
            return;
        }
        if (authoring.pending) {
            authoring.cancel();
            return;
        }
        const pendingChanges = !sameWorkflowDefinition(baseline, current.draft) ||
            history.session.fields.summary(workflowDraftOwners(current.draft)).pending;
        if (pendingChanges && !readOnly) {
            setConfirmClose(true);
        } else {
            history.session.invalidate();
            onClose();
        }
    };

    const save = async (confirmed = false) => {
        if (interactionDisabled) {
            setError('Refresh workspace access before saving. Your draft has been retained.');
            return;
        }
        history.session.closeGroup();
        if (saving || history.session.saving || readOnly || authoring.pending || history.session.getSnapshot().pending || assistPending) {
            return;
        }
        const savingDraft = history.session.draft;
        const currentErrors = [
            ...workflowValidationErrors(savingDraft, options, original, fileSyncListing),
            ...history.session.fields.summary(workflowDraftOwners(savingDraft)).taskSchemaErrors.values(),
        ];
        if (currentErrors.length) {
            setError(currentErrors.join(' '));
            return;
        }
        if (!confirmed && workflowSessionSaveNeedsConfirmation(history.session)) {
            // Unsaved AI assist changes are reviewed in the Changes tab before they are saved.
            setConfirmingSave(true);
            openChanges('confirm');
            return;
        }
        history.session.setSaving(true);
        setSaving(true);
        setError('');
        try {
            const response = onSaveOverride
                ? await onSaveOverride(savingDraft, original)
                : await saveWorkflowDefinition(scope, savingDraft, original);
            if (!history.session.active) return;
            const saved = response.workflow ? normalizeWorkflowDefinition(response.workflow, scope) : workflowForSave(savingDraft, original, scope);
            setBaseline(saved);
            history.session.saved(saved);
            onSaved(saved);
        } catch (cause: unknown) {
            if (!history.session.active) return;
            if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
                onAccessLost(cause.status);
                return;
            }
            // A source deleted since the list loaded: reload it so the editor marks that source.
            if (workflowErrorCode(cause) === WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_CODE) fileSyncSources.retry();
            setError(workflowErrorMessage(cause, 'Could not save the workflow. Your draft has been retained.'));
        } finally {
            history.session.setSaving(false);
            setSaving(false);
        }
    };

    const updateTask = (taskId: string, update: (task: WorkflowTask) => WorkflowTask) => {
        setWorkflow((current) => ({
            ...current,
            tasks: setTaskAt(current.tasks, taskId, update),
        }));
    };
    const moveTask = (taskId: string, direction: -1 | 1) => {
        setWorkflow((current) => {
            const index = current.tasks.findIndex((task) => task.id === taskId);
            const nextIndex = index + direction;
            if (index < 0 || nextIndex < 0 || nextIndex >= current.tasks.length) {
                return current;
            }
            const tasks = [...current.tasks];
            [tasks[index], tasks[nextIndex]] = [tasks[nextIndex], tasks[index]];
            return { ...current, tasks: workflowTasksInOrder(tasks) };
        });
    };
    const removeTask = (taskId: string) => {
        setWorkflow((current) => ({
            ...current,
            tasks: workflowTasksInOrder(current.tasks.filter((task) => task.id !== taskId)),
        }));
        fieldDrafts.store.clear(['task', taskId]);
    };
    const renderStructuredTask = (task: WorkflowTask, node: WorkflowTaskNode, onNodeChange: (node: WorkflowTaskNode) => void) => (
        <WorkflowTaskFields key={task.id} scope={scope} task={task}
            index={draft.tasks.findIndex((item) => item.id === task.id)} workflow={draft} options={options}
            onChange={(value) => authoring.execute({ type: 'task', taskId: task.id, value, expected: task })}
            durableExecution={draft.durable_execution === true}
            onNeedsDurable={() => setWorkflow((current) => ({ ...current, durable_execution: true }))}
            structuredNode={node} onStructuredNodeChange={onNodeChange}
            onAskAi={askAiAvailable ? () => askAiAboutTask(task.id) : undefined}
            draftWithAi={askAiAvailable ? assist.draftWithAi(task.id) : undefined} />
    );
    const askAiAboutTask = (taskId: string) => {
        assist.setFocusTask(taskId);
        openAskAi();
    };

    return (
        <WorkflowFieldDraftsProvider value={fieldDrafts.store}>
            <WorkflowChangeTrackingScope session={history.session} enabled={!readOnly}>
            <Modal
                title={workflow ? 'Edit workflow' : 'Create workflow'}
                description={`Scope: ${workflowScopeKey(scope)}. ${readOnly ? 'This workflow is read-only.' : 'Changes are saved only when you choose Save workflow.'}`}
                onClose={close}
                size={panelOpen ? '2xl' : 'xl'}
                tall
                bodyClassName="flex min-h-0"
                footer={
                    // A narrow screen can't fit the toggles, Cancel and Save on one line once Ask AI is
                    // offered, so Cancel and Save move together to a second line instead of wrapping a label.
                    <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
                        {askAiAvailable ? <WorkflowAskAiToggle id={askAiToggleId} open={panelOpen && panelTab === 'askai'}
                            controls={sidePanelId}
                            onToggle={() => (panelOpen && panelTab === 'askai' ? closeChanges(false) : openAskAi())} /> : null}
                        {!readOnly ? <WorkflowChangesToggle id={changesToggleId} open={panelOpen && panelTab === 'changes'}
                            controls={sidePanelId}
                            onToggle={() => (panelOpen && panelTab === 'changes' ? closeChanges(false) : openChanges('tab'))} /> : null}
                        <div className="flex shrink-0 items-center gap-2">
                            <GlassButton type="button" onClick={close} disabled={saving}>
                                {readOnly ? 'Close' : 'Cancel'}
                            </GlassButton>
                            {!readOnly ? (
                                <GlassButton type="button" variant="primary" disabled={interactionDisabled || saving || Boolean(authoring.pending) || Boolean(history.pending) || assistPending} onClick={() => void save()}>
                                    {saving ? 'Saving…' : 'Save workflow'}
                                </GlassButton>
                            ) : null}
                        </div>
                    </div>
                }
            >
                <div className={`min-w-0 flex-1 overflow-y-auto px-4 py-3${panelOpen ? ' hidden xl:block' : ''}`}
                    onKeyDownCapture={(event) => {
                        // Workflow undo and redo wait for Ask AI too.
                        const key = event.key.toLowerCase();
                        if (assistPending && (event.ctrlKey || event.metaKey) && (key === 'z' || key === 'y')) event.preventDefault();
                    }}>
                {assist.pending ? <WorkflowAssistLockBanner pending={assist.pending} onCancel={assist.cancel} /> : null}
                <WorkflowHistoryBoundary session={history.session}>
                <div className="space-y-5 p-1">
                    {unsupported ? (
                        <div role="alert" className="flex gap-2 rounded-xl bg-warn-soft p-3 text-sm text-warn">
                            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                            <p>
                                This workflow uses definition version {draft.definition_version}. V2 can read
                                it but cannot safely save it without downgrading fields from a newer editor.
                                {unsupportedFlow ? ` ${unsupportedFlow}` : ''}
                            </p>
                        </div>
                    ) : null}
                    {!options.can_manage ? (
                        <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                            You have read-only access to workflows in this scope.
                        </p>
                    ) : null}
                    {error ? <p ref={errorRef} role="alert" tabIndex={-1} className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
                    {!error && allErrors.length ? (
                        <div role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                            <p className="font-medium">Resolve these validation issues before saving:</p>
                            <ul className="mt-1 list-disc pl-5">
                                {allErrors.map((message) => <li key={message}>{message}</li>)}
                            </ul>
                        </div>
                    ) : null}
                    {!accessLost && preserved.length ? (
                        <div className="rounded-xl border border-edge p-3 text-sm text-text-2">
                            <p className="font-medium text-text-1">Preserved settings</p>
                            <p className="mt-1 text-xs text-text-3">
                                V2 does not edit these legacy settings, but saves keep them intact:
                                {' '}{preserved.join(', ')}.
                            </p>
                        </div>
                    ) : null}
                    {draft.definition_version === 3 && !readOnly ? <div className="space-y-2">
                        <div className="flex flex-wrap gap-2" role="group" aria-label="Workflow edit history" data-workflow-history-controls>
                            <GlassButton size="sm" disabled={Boolean(historyBlockedReason)} aria-disabled={!history.undoLabel}
                                className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                                aria-label="Undo workflow edit" title={historyBlockedReason || (history.undoLabel ? `Undo: ${history.undoLabel}` : 'No workflow edits to undo')}
                                onClick={() => { if (history.undoLabel) history.session.request('undo'); }}><Undo2 size={14} /> Undo</GlassButton>
                            <GlassButton size="sm" disabled={Boolean(historyBlockedReason)} aria-disabled={!history.redoLabel}
                                className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                                aria-label="Redo workflow edit" title={historyBlockedReason || (history.redoLabel ? `Redo: ${history.redoLabel}` : 'No workflow edits to redo')}
                                onClick={() => { if (history.redoLabel) history.session.request('redo'); }}><Redo2 size={14} /> Redo</GlassButton>
                            <span className="self-center text-xs text-text-3">
                                {history.undoLabel ? `Undo: ${history.undoLabel}. ` : 'No earlier retained edits. '}
                                Text fields keep native undo.
                            </span>
                        </div>
                        {history.notice ? <p role="status" className="rounded-lg bg-warn-soft p-3 text-xs text-warn">{history.notice}</p> : null}
                        <div className="flex flex-wrap gap-2" role="group" aria-label="Workflow authoring surface">
                            <GlassButton size="sm" aria-pressed={surface === 'list'} disabled={saving || Boolean(authoring.pending) || Boolean(history.pending)}
                                onClick={() => switchSurface('list')}>List authoring</GlassButton>
                            <GlassButton size="sm" aria-pressed={surface === 'flow'} disabled={saving || Boolean(authoring.pending) || Boolean(history.pending)}
                                onClick={() => switchSurface('flow')}>Flow authoring</GlassButton>
                        </div>
                        <p className="text-xs text-text-3">
                            Both surfaces edit one unsaved draft. Buttons change execution order and bindings; dragging changes temporary layout only.
                        </p>
                    </div> : null}
                    {!accessLost ? <div ref={authoringRef} className="min-w-0">
                    <fieldset disabled={readOnly || saving || Boolean(history.pending) || Boolean(authoring.pending) || assistPending}
                        aria-busy={assistPending || undefined} className="min-w-0 space-y-5">
                        <section className="space-y-4 rounded-2xl border border-edge p-4" aria-label="Workflow basics">
                            <div className="grid gap-3 md:grid-cols-2">
                                <WorkflowChangedField changeKey="name">
                                <label className="text-sm text-text-2">
                                    {fieldLabel('Workflow name', true)}
                                    <input
                                        id={fieldId('workflow', 'name')}
                                        className={`${inputClass} mt-1`}
                                        aria-label="Workflow name"
                                        value={draft.name}
                                        required
                                        onChange={(event) => setWorkflow((current) => ({ ...current, name: event.target.value }))}
                                    />
                                </label>
                                </WorkflowChangedField>
                                <WorkflowChangedField changeKey="runner_type">
                                <label className="text-sm text-text-2">
                                    Runner type
                                    <select
                                        className={`${inputClass} mt-1`}
                                        aria-label="Runner type"
                                        value={draft.runner_type}
                                        onChange={(event) => setWorkflow((current) => ({
                                            ...current,
                                            runner_type: event.target.value as WorkflowDefinition['runner_type'],
                                        }))}
                                    >
                                        <option value="model">Model</option>
                                        <option value="agent">Agent</option>
                                    </select>
                                </label>
                                </WorkflowChangedField>
                            </div>
                            <WorkflowChangedField changeKey="description">
                            <label className="block text-sm text-text-2">
                                Description
                                <textarea
                                    className={`${textareaClass} mt-1`}
                                    aria-label="Description"
                                    value={draft.description}
                                    onChange={(event) => setWorkflow((current) => ({ ...current, description: event.target.value }))}
                                />
                            </label>
                            </WorkflowChangedField>
                            {draft.runner_type === 'agent' ? (
                                <WorkflowChangedField changeKey="selected_agent">
                                <WorkflowAgentPicker
                                    value={draft.selected_agent}
                                    options={options}
                                    localOnly={localRunner}
                                    onChange={(selectedAgent) => setWorkflow((current) => ({ ...current, selected_agent: selectedAgent }))}
                                />
                                </WorkflowChangedField>
                            ) : (
                                <WorkflowChangedField changeKey="model">
                                <WorkflowModelPicker
                                    endpointId={draft.model_endpoint_id}
                                    modelId={draft.model_id}
                                    options={options}
                                    localOnly={localRunner}
                                    onChange={(endpointId, modelId) => setWorkflow((current) => ({
                                        ...current,
                                        model_endpoint_id: endpointId,
                                        model_id: modelId,
                                    }))}
                                />
                                </WorkflowChangedField>
                            )}
                            <WorkflowChangedField changeKey="m365_run_as_user_id">
                            <WorkflowMicrosoft365RunAs
                                scope={scope}
                                value={draft.m365_run_as_user_id ?? ''}
                                disabled={readOnly || saving}
                                canListAccounts={options.can_manage}
                                onChange={(userId) => setWorkflow((current) => ({ ...current, m365_run_as_user_id: userId }))}
                            />
                            </WorkflowChangedField>
                            <WorkflowScheduleFields
                                triggerField={(
                                    <label className="text-sm text-text-2">
                                        Trigger
                                        <select
                                            className={`${inputClass} mt-1`}
                                            aria-label="Trigger"
                                            value={draft.trigger_type}
                                            onChange={(event) => {
                                                const trigger = event.target.value as WorkflowDefinition['trigger_type'];
                                                setWorkflow((current) => trigger === 'file_sync' ? {
                                                    ...current,
                                                    trigger_type: trigger,
                                                    file_sync: workflowMonitorFileSyncConfig(current.file_sync),
                                                } : { ...current, trigger_type: trigger });
                                            }}
                                        >
                                            <option value="manual">Manual</option>
                                            <option value="interval">Schedule</option>
                                            {fileSyncTriggerOffered ? <option value="file_sync">Monitor File Sync changes</option> : null}
                                        </select>
                                    </label>
                                )}
                                schedule={draft.schedule}
                                options={options}
                                scheduled={scheduled}
                                onChange={(update) => setWorkflow((current) => ({ ...current, schedule: update(current.schedule) }))}
                            />
                            <WorkflowChangedField changeKey="error_handling">
                            <div className="grid gap-3 md:grid-cols-2">
                                <label className="text-sm text-text-2">
                                    Error handling
                                    <select
                                        className={`${inputClass} mt-1`}
                                        aria-label="Error handling"
                                        value={draft.error_handling.strategy}
                                        onChange={(event) => setWorkflow((current) => ({
                                            ...current,
                                            error_handling: {
                                                ...current.error_handling,
                                                strategy: event.target.value as WorkflowDefinition['error_handling']['strategy'],
                                            },
                                        }))}
                                    >
                                        <option value="halt">Halt on failure</option>
                                        <option value="continue">Continue after failure</option>
                                    </select>
                                </label>
                                <label className="text-sm text-text-2">
                                    Retry count
                                    <input
                                        className={`${inputClass} mt-1`}
                                        type="number"
                                        min={0}
                                        max={5}
                                        aria-label="Retry count"
                                        value={draft.error_handling.retry_count}
                                        onChange={(event) => setWorkflow((current) => ({
                                            ...current,
                                            error_handling: {
                                                ...current.error_handling,
                                                retry_count: Math.min(5, Math.max(0, Math.trunc(Number(event.target.value) || 0))),
                                            },
                                        }))}
                                    />
                                </label>
                            </div>
                            </WorkflowChangedField>
                            <div className="grid gap-2 md:grid-cols-2">
                                <WorkflowChangedField changeKey="is_enabled">
                                <Toggle
                                    label="Workflow enabled"
                                    checked={draft.is_enabled}
                                    onChange={(checked) => setWorkflow((current) => ({ ...current, is_enabled: checked }))}
                                    description="Disabled workflows can be edited but will not run automatically."
                                />
                                </WorkflowChangedField>
                                <WorkflowChangedField changeKey="durable_execution">
                                <Toggle
                                    label="Durable execution"
                                    checked={draft.durable_execution === true}
                                    disabled={draft.definition_version === 3}
                                    onChange={(checked) => setWorkflow((current) => ({ ...current, durable_execution: checked }))}
                                    description={draft.definition_version === 3
                                        ? 'Required for structured control flow. Saved decisions and exact execution checkpoints survive waits and restarts.'
                                        : 'Save checkpoints so queued and interrupted runs can resume instead of depending on this browser tab.'}
                                />
                                </WorkflowChangedField>
                                <WorkflowChangedField changeKey="chat_capabilities_enabled">
                                <Toggle
                                    label="Chat capabilities enabled"
                                    checked={draft.chat_capabilities_enabled}
                                    onChange={(checked) => setWorkflow((current) => ({ ...current, chat_capabilities_enabled: checked }))}
                                    description="Allow tasks to use configured chat capabilities when the runner supports them."
                                />
                                </WorkflowChangedField>
                            </div>
                            <p className="rounded-xl bg-surface-sunken p-3 text-xs text-text-3">
                                Effective runner: {workflowRunnerSummary(draft, options)}
                            </p>
                        </section>
                        <WorkflowFileSyncFields
                            scope={scope}
                            workflow={draft}
                            sourceList={fileSyncSources}
                            disabled={readOnly || saving}
                            onChange={(update) => setWorkflow((current) => ({
                                ...current,
                                file_sync: update(workflowFileSyncConfig(current.file_sync)),
                            }))}
                        />
                        <section className="rounded-2xl border border-edge p-4" aria-label="Workflow shared references">
                            <WorkflowDocumentPicker
                                scope={scope}
                                references={draft.reference_inputs}
                                readOnly={readOnly || saving}
                                onChange={(referenceInputs) => setWorkflow((current) => ({ ...current, reference_inputs: referenceInputs }))}
                            />
                            <WorkflowReferenceChanges className="mt-3" />
                        </section>
                        {draft.definition_version === 3 && !unsupported ? <WorkflowChangedField changeKey="limits">
                            <WorkflowFlowLimitFields workflow={draft} onEdit={authoring.execute} />
                        </WorkflowChangedField> : null}
                        <section className="space-y-3 rounded-2xl border border-edge p-4" aria-label="Workflow tasks">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                    <h3 className="text-base font-semibold text-text-1">{draft.definition_version === 3
                                        ? surface === 'flow' ? 'Structured Flow' : 'Structured List' : 'Tasks'}</h3>
                                    <p className="text-xs text-text-3">
                                        Task IDs stay stable while you edit, so explicit input bindings do not change meaning.
                                    </p>
                                </div>
                                {draft.definition_version !== 3 ? <div className="flex flex-wrap gap-2">
                                {options.supported_definition_versions?.includes(3) && !unsupported ? (
                                    <GlassButton type="button" size="sm" onClick={() => setConfirmStructured(true)}>
                                        Enable structured control flow
                                    </GlassButton>
                                ) : null}
                                <GlassButton
                                    type="button"
                                    size="sm"
                                    variant="primary"
                                    disabled={draft.tasks.length >= options.max_tasks}
                                    onClick={() => setWorkflow((current) => ({
                                        ...current,
                                        tasks: [...current.tasks, createWorkflowTask(current.tasks.length)],
                                    }))}
                                >
                                    <Plus size={14} /> Add task
                                </GlassButton>
                                </div> : <Pill tone="accent">Definition v3</Pill>}
                            </div>
                            {draft.tasks.length >= options.max_tasks ? (
                                <p role="status" className="text-xs text-warn">Maximum task count reached for this scope.</p>
                            ) : null}
                            {draft.definition_version === 3 ? (
                                surface === 'flow' && !unsupported ? <>
                                    {flowPreview.error ? <p role="alert" className="text-sm text-danger">{flowPreview.error}</p> : null}
                                    <WorkflowFlowAuthoring workflow={draft} options={options} scope={scope}
                                        previewDefinition={flowPreview.definition} selectedId={authoring.selectedId}
                                        onSelect={(id) => {
                                            if (id !== authoring.selectedId) history.session.closeGroup();
                                            authoring.setSelectedId(id);
                                        }} onEdit={authoring.execute} renderTask={renderStructuredTask}
                                        positions={authoring.positions} setPositions={authoring.setPositions}
                                        collapsed={authoring.collapsed} setCollapsed={authoring.setCollapsed}
                                        focusRequest={authoring.focusRequest} disabled={readOnly || saving || Boolean(history.pending) || Boolean(authoring.pending) || assistPending} onAccessLost={onAccessLost} />
                                </> : <WorkflowStructuredList workflow={draft} options={options} scope={scope}
                                    onEdit={authoring.execute} selectedId={authoring.selectedId}
                                    onSelect={(id) => {
                                        if (id !== authoring.selectedId) history.session.closeGroup();
                                        authoring.setSelectedId(id);
                                    }} renderTask={renderStructuredTask} />
                            ) : <>
                            <WorkflowChangeNotice changeKey={WORKFLOW_TASK_ORDER_KEY} />
                            <WorkflowRemovedItemRows list="task" placement={{ at: 'start' }} />
                            {draft.tasks.map((task, index) => (
                                <Fragment key={task.id}>
                                <WorkflowTaskFields
                                    key={task.id}
                                    scope={scope}
                                    task={task}
                                    index={index}
                                    workflow={draft}
                                    options={options}
                                    onChange={(nextTask) => updateTask(task.id, () => nextTask)}
                                    onMove={(direction) => moveTask(task.id, direction)}
                                    onRemove={() => removeTask(task.id)}
                                    durableExecution={draft.durable_execution === true}
                                    onNeedsDurable={() => setWorkflow((current) => ({ ...current, durable_execution: true }))}
                                    onAskAi={askAiAvailable ? () => askAiAboutTask(task.id) : undefined}
                                    draftWithAi={askAiAvailable ? assist.draftWithAi(task.id) : undefined}
                                />
                                <WorkflowRemovedItemRows list="task" placement={{ at: 'after', id: task.id }} />
                                </Fragment>
                            ))}
                            <WorkflowRemovedItemRows list="task"
                                placement={{ at: 'end', siblings: draft.tasks.map((task) => task.id), root: true }} />
                            </>}
                        </section>
                        {/* Rules watch tasks by ID, so alerts follow the tasks they can refer to. */}
                        {options.can_manage && !readOnly ? (
                            <WorkflowChangedField changeKey="alerts">
                            <WorkflowAlertEditor workflow={draft} onChange={(update) => setWorkflow((current) => update(current))} />
                            </WorkflowChangedField>
                        ) : (
                            <WorkflowAlertSummary workflow={draft} />
                        )}
                    </fieldset>
                    </div> : null}
                </div>
                </WorkflowHistoryBoundary>
                </div>
                {panelOpen ? (
                    <WorkflowEditorSidePanel id={sidePanelId} className="w-full xl:w-96 xl:shrink-0 xl:border-l xl:border-edge"
                        selected={panelTab} onSelect={selectSideTab}
                        tabs={[{
                            id: 'changes', label: 'Changes',
                            content: <WorkflowChangesTab confirming={confirmingSave}
                                disabled={saving || Boolean(authoring.pending) || Boolean(history.pending) || assistPending}
                                onConfirmSave={() => void save(true)}
                                onKeepReviewing={() => {
                                    setConfirmingSave(false);
                                    setPanelFocus({ target: 'list', sequence: ++focusSequence.current });
                                }}
                                onJump={jumpToChange} confirmHeadingRef={confirmHeadingRef} listHeadingRef={changesHeadingRef} />,
                        }, ...(askAiAvailable ? [{
                            id: 'askai', label: 'Ask AI', panelClassName: 'flex flex-col overflow-hidden',
                            content: <WorkflowAskAiTab assist={assist} inputId={askAiInputId} onReload={original ? onReload : undefined} />,
                        }] : [])]} />
                ) : null}
                {/* Outside the editor pane, which narrow screens hide while the side panel is open. */}
                {!accessLost && authoring.announcement ? <p role="status" className="sr-only">{authoring.announcement}</p> : null}
                {!accessLost && history.announcement ? <p role="status" className="sr-only">{history.announcement}</p> : null}
            </Modal>
            {!accessLost && authoring.pending ? <ConfirmDialog
                title={authoring.pending.command.type === 'remove' ? 'Remove this flow block?' : 'Move this flow block?'}
                description={authoring.pending.message}
                confirmLabel={authoring.pending.command.type === 'remove' ? 'Remove block' : 'Move block'}
                cancelLabel="Keep draft unchanged" onClose={authoring.cancel} onConfirm={authoring.confirm}>
                {authoring.pending.impact.length ? <ul className="space-y-2 text-xs text-text-2" aria-label="Affected draft references">
                    {authoring.pending.impact.map((impact, index) => <li key={index} className="break-words">
                        {impact.nodeId ? <strong>{impact.nodeId}: </strong> : null}{impact.message}
                    </li>)}
                </ul> : <p className="text-xs text-text-2">No outside references are affected. This changes only the unsaved draft; retained edits can be undone before saving or closing.</p>}
            </ConfirmDialog> : null}
            {!accessLost && history.pending ? <ConfirmDialog
                title={history.pending.kind === 'overflow' ? 'Apply edit and clear history?' : history.pending.kind === 'change' ? history.pending.title
                    : `${history.pending.direction === 'undo' ? 'Undo' : 'Redo'} workflow edit?`}
                description={history.pending.message}
                confirmLabel={history.pending.kind === 'overflow' ? 'Apply and clear history' : history.pending.kind === 'change' ? history.pending.confirmLabel
                    : history.pending.direction === 'undo' ? 'Undo change' : 'Redo change'}
                cancelLabel="Keep draft unchanged" onClose={() => history.session.cancel()} onConfirm={() => history.session.confirm()}>
                <p className="mb-2 text-sm text-text-2">{history.pending.label}</p>
                {history.pending.impact.length ? <ul className="space-y-2 text-xs text-text-2" aria-label="Affected history references">
                    {history.pending.impact.map((impact, index) => <li key={index} className="break-words">
                        {impact.nodeId ? <strong>{impact.nodeId}: </strong> : null}{impact.message}
                    </li>)}
                </ul> : <p className="text-xs text-text-2">
                    {history.pending.kind === 'overflow' ? 'The complete edit will be kept, but cleared history cannot be recovered.'
                        : 'No outside references are affected. This changes only the unsaved draft.'}
                </p>}
            </ConfirmDialog> : null}
            {confirmStructured ? (
                <ConfirmDialog title="Enable structured control flow?"
                    description="This explicitly converts the draft to definition version 3 and requires durable execution. Existing task inputs are made explicit. Classic can still run or cancel it, but advanced editing requires V2. Nothing changes until Save workflow."
                    confirmLabel="Convert draft" cancelLabel="Keep ordered tasks"
                    onClose={() => setConfirmStructured(false)}
                    onConfirm={() => {
                        try {
                            setWorkflow(convertToStructuredWorkflow(draft, `root-${createWorkflowTask(0).id}`));
                            setConfirmStructured(false);
                        } catch (cause: unknown) {
                            setConfirmStructured(false);
                            setError(workflowErrorMessage(cause, 'This workflow cannot be converted safely. Choose explicit inputs first.'));
                        }
                    }} />
            ) : null}
            {confirmClose ? (
                <ConfirmDialog
                    title="Discard unsaved workflow changes?"
                    description="Your workflow draft has not been saved."
                    confirmLabel="Discard changes"
                    cancelLabel="Keep editing"
                    onClose={() => setConfirmClose(false)}
                    onConfirm={() => {
                        setConfirmClose(false);
                        history.session.invalidate();
                        onClose();
                    }}
                />
            ) : null}
            </WorkflowChangeTrackingScope>
        </WorkflowFieldDraftsProvider>
    );
}
