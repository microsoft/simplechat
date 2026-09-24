// WorkflowFileSyncFields.tsx
// Group workflow File Sync authoring: the Monitor File Sync changes trigger and File Sync before run.

import { useEffect, useId, useState } from 'react';
import { GlassButton, Toggle } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import {
    fetchWorkflowFileSyncSources,
    workflowFileSyncConfig,
    workflowFileSyncSourceKey,
    workflowScopeKey,
    workflowUnavailableFileSyncSources,
    WORKFLOW_FILE_SYNC_MAX_SOURCES,
    type WorkflowDefinition,
    type WorkflowFileSyncConfig,
    type WorkflowFileSyncContinueMode,
    type WorkflowFileSyncSource,
    type WorkflowFileSyncSourceRef,
    type WorkflowFileSyncWaitMode,
    type WorkflowScope,
} from '../../lib/workflowEditor';

const selectClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

export interface WorkflowFileSyncSourceList {
    status: 'idle' | 'loading' | 'ready' | 'failed';
    sources: WorkflowFileSyncSource[];
    retry: () => void;
}

/**
 * The sources this group offers to its workflows, requested with the page's explicit group.
 * Only managers request them: the route refuses members, and members cannot author triggers.
 */
export function useWorkflowFileSyncSources(scope: WorkflowScope, enabled: boolean): WorkflowFileSyncSourceList {
    const scopeKey = workflowScopeKey(scope);
    const groupId = scope.type === 'group' ? scope.groupId : '';
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<{ key: string; status: WorkflowFileSyncSourceList['status']; sources: WorkflowFileSyncSource[] }>({
        key: '', status: 'idle', sources: [],
    });
    const active = enabled && Boolean(groupId);
    useEffect(() => {
        if (!active) {
            return undefined;
        }
        const controller = new AbortController();
        setState({ key: scopeKey, status: 'loading', sources: [] });
        void fetchWorkflowFileSyncSources({ type: 'group', groupId }, controller.signal).then(
            (sources) => {
                if (!controller.signal.aborted) setState({ key: scopeKey, status: 'ready', sources });
            },
            () => {
                if (!controller.signal.aborted) setState({ key: scopeKey, status: 'failed', sources: [] });
            },
        );
        return () => controller.abort();
    }, [active, scopeKey, groupId, attempt]);
    const current = active && state.key === scopeKey;
    return {
        status: current ? state.status : active ? 'loading' : 'idle',
        sources: current ? state.sources : [],
        retry: () => setAttempt((value) => value + 1),
    };
}

function sourceName(source: WorkflowFileSyncSourceRef): string {
    return source.name || source.source_id;
}

export function WorkflowFileSyncFields({
    scope,
    workflow,
    sourceList,
    disabled,
    onChange,
}: {
    scope: Extract<WorkflowScope, { type: 'group' }>;
    workflow: WorkflowDefinition;
    sourceList: WorkflowFileSyncSourceList;
    disabled: boolean;
    /** Receives an updater so consecutive edits apply to the latest draft, not this render's copy. */
    onChange: (update: (config: WorkflowFileSyncConfig) => WorkflowFileSyncConfig) => void;
}) {
    const baseId = useId();
    const config = workflowFileSyncConfig(workflow.file_sync);
    const monitored = workflow.trigger_type === 'file_sync';
    const active = monitored || config.enabled;
    const selected = new Set(config.sources.map(workflowFileSyncSourceKey));
    const unavailable = sourceList.status === 'ready' ? workflowUnavailableFileSyncSources(workflow, sourceList.sources) : [];
    const listed = sourceList.status === 'ready' ? sourceList.sources : [];
    // Without a verified list, the saved selection is still shown so it is never silently dropped.
    const unverified = sourceList.status === 'ready' ? [] : config.sources;
    const atLimit = config.sources.length >= WORKFLOW_FILE_SYNC_MAX_SOURCES;

    const update = (changes: Partial<WorkflowFileSyncConfig>) => onChange((current) => ({ ...current, ...changes }));
    const toggleSource = (source: WorkflowFileSyncSourceRef, checked: boolean) => {
        const key = workflowFileSyncSourceKey(source);
        onChange((current) => {
            const others = current.sources.filter((item) => workflowFileSyncSourceKey(item) !== key);
            return {
                ...current,
                sources: checked
                    ? [...others, {
                        scope_type: 'group', scope_id: scope.groupId, source_id: source.source_id,
                        ...(source.name ? { name: source.name } : {}),
                        ...(source.source_type ? { source_type: source.source_type } : {}),
                    }]
                    : others,
            };
        });
    };

    return (
        <section aria-labelledby={`${baseId}-title`} className="space-y-3 rounded-2xl border border-edge p-4">
            <div>
                <h3 id={`${baseId}-title`} className="text-base font-semibold text-text-1">File Sync</h3>
                <p className="mt-0.5 text-xs text-text-3">
                    {monitored
                        ? 'Monitor workflows check the selected sources on the interval above and run only when files changed.'
                        : 'Optionally sync the selected group sources before each run.'}
                </p>
            </div>
            <Toggle
                label="Run File Sync before each run"
                checked={active}
                disabled={disabled || monitored}
                onChange={(checked) => update({ enabled: checked })}
                description={monitored ? 'Required by the Monitor File Sync changes trigger.' : undefined}
            />
            <fieldset disabled={disabled || !active} className="min-w-0 space-y-2">
                <legend className="text-sm text-text-2">File Sync sources</legend>
                {sourceList.status === 'loading' ? (
                    <p role="status" className="text-xs text-text-3">Loading this group&apos;s File Sync sources…</p>
                ) : null}
                {sourceList.status === 'failed' ? (
                    <div role="alert" className="space-y-2 rounded-xl bg-warn-soft p-3 text-sm text-warn">
                        <p>Could not load this group&apos;s File Sync sources. Your selection is kept, but it cannot be checked.</p>
                        <GlassButton type="button" size="sm" onClick={sourceList.retry}>Retry File Sync sources</GlassButton>
                    </div>
                ) : null}
                {sourceList.status === 'ready' && !listed.length ? (
                    <p role="status" className="text-xs text-text-3">No File Sync sources are available to this group.</p>
                ) : null}
                <ul className="space-y-1" aria-label="File Sync sources">
                    {listed.map((source) => {
                        const key = workflowFileSyncSourceKey(source);
                        const checked = selected.has(key);
                        return (
                            <li key={key}>
                                <label className="flex items-center gap-2 text-sm text-text-1">
                                    <input
                                        type="checkbox"
                                        className="accent-[var(--accent)]"
                                        aria-label={`Use File Sync source ${source.label}`}
                                        checked={checked}
                                        disabled={!checked && atLimit}
                                        onChange={(event) => toggleSource(source, event.target.checked)}
                                    />
                                    <span className="min-w-0 break-words">{source.label}</span>
                                    {source.source_type ? <Pill>{source.source_type}</Pill> : null}
                                    {!source.enabled ? <Pill tone="warn">Disabled</Pill> : null}
                                </label>
                            </li>
                        );
                    })}
                    {[...unavailable, ...unverified].map((source) => (
                        <li key={workflowFileSyncSourceKey(source)}>
                            <label className="flex items-center gap-2 text-sm text-text-1">
                                <input
                                    type="checkbox"
                                    className="accent-[var(--accent)]"
                                    aria-label={`Use File Sync source ${sourceName(source)}`}
                                    checked
                                    onChange={(event) => toggleSource(source, event.target.checked)}
                                />
                                <span className="min-w-0 break-words">{sourceName(source)}</span>
                                {sourceList.status === 'ready' ? <Pill tone="warn">No longer available</Pill> : null}
                            </label>
                        </li>
                    ))}
                </ul>
                {atLimit ? (
                    <p className="text-xs text-text-3">A workflow can use up to {WORKFLOW_FILE_SYNC_MAX_SOURCES} File Sync sources.</p>
                ) : null}
            </fieldset>
            <div className="grid gap-3 md:grid-cols-2">
                <label className="text-sm text-text-2">
                    Wait for File Sync
                    <select
                        className={`${selectClass} mt-1`}
                        aria-label="Wait for File Sync"
                        value={monitored ? 'complete' : config.wait_mode}
                        disabled={disabled || !active || monitored}
                        onChange={(event) => update({ wait_mode: event.target.value as WorkflowFileSyncWaitMode })}
                    >
                        <option value="complete">Until sync completes</option>
                        <option value="queued">Queue only</option>
                    </select>
                </label>
                <label className="text-sm text-text-2">
                    Continue the workflow
                    <select
                        className={`${selectClass} mt-1`}
                        aria-label="Continue the workflow"
                        value={monitored ? 'changed' : config.continue_mode}
                        disabled={disabled || !active || monitored}
                        onChange={(event) => update({ continue_mode: event.target.value as WorkflowFileSyncContinueMode })}
                    >
                        <option value="always">Always continue</option>
                        <option value="changed">Only when files changed</option>
                    </select>
                </label>
            </div>
            <Toggle
                label="Use changed files as Analyze targets"
                checked={config.use_changed_documents}
                disabled={disabled || !active}
                onChange={(checked) => update({ use_changed_documents: checked })}
                description="Analyze tasks without selected documents run on the files this sync changed."
            />
        </section>
    );
}
