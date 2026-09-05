// AgentDelegationManager.tsx

import { useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    actionTarget, delegationError, deleteCallAgentAction, fetchAgentTargets, fetchDelegationActions,
    fetchDelegationAgents, isOwnedResource, referenceKey, saveCallAgentAction,
    saveAgentActionBindings, type AgentTargetCatalog, type CallAgentWrite, type DelegationScope,
} from '../../lib/agentDelegation';
import type { WorkspaceAction, WorkspaceAgent } from '../../lib/types';
import { GlassButton } from '../ui/primitives';
import { ConfirmAction } from '../workspace/primitives';
import { AgentActionBindings } from './AgentActionBindings';
import { CallAgentEditor, DELEGATION_INPUT_CLASS } from './CallAgentEditor';

export function AgentDelegationManager({
    scope,
    allowManage = true,
    mode = 'both',
    revision = 0,
    onDirtyChange,
}: {
    scope: DelegationScope;
    allowManage?: boolean;
    mode?: 'actions' | 'bindings' | 'both';
    revision?: number;
    onDirtyChange?: (dirty: boolean) => void;
}) {
    const [catalog, setCatalog] = useState<AgentTargetCatalog | null>(null);
    const [actions, setActions] = useState<WorkspaceAction[]>([]);
    const [agents, setAgents] = useState<WorkspaceAgent[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [reload, setReload] = useState(0);
    const [editor, setEditor] = useState<{ action?: WorkspaceAction } | null>(null);
    const [caller, setCaller] = useState<WorkspaceAgent | null>(null);
    const [saving, setSaving] = useState(false);
    const [blocked, setBlocked] = useState(false);
    const [query, setQuery] = useState('');
    const [confirmReload, setConfirmReload] = useState(false);
    const scopeType = scope.type;
    const groupId = scope.type === 'group' ? scope.groupId : '';
    const loadVersion = useRef(0);
    const dirty = Boolean(editor || caller);
    const canManage = allowManage && catalog?.can_manage === true;

    useEffect(() => {
        onDirtyChange?.(dirty);
        return () => onDirtyChange?.(false);
    }, [dirty, onDirtyChange]);

    useEffect(() => {
        if (!dirty) {
            return;
        }
        const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty]);

    useEffect(() => {
        const abort = new AbortController();
        const version = ++loadVersion.current;
        const requestScope: DelegationScope = scopeType === 'group'
            ? { type: 'group', groupId } : { type: scopeType };
        setLoading(true);
        setCatalog(null);
        setError('');
        setBlocked(false);
        setEditor(null);
        setCaller(null);
        setActions([]);
        setAgents([]);
        void Promise.all([
            fetchAgentTargets(requestScope, abort.signal),
            fetchDelegationActions(requestScope, abort.signal),
            mode === 'actions' ? Promise.resolve([]) : fetchDelegationAgents(requestScope, abort.signal),
        ]).then(([nextCatalog, nextActions, nextAgents]) => {
            if (!abort.signal.aborted && version === loadVersion.current) {
                setCatalog(nextCatalog);
                setActions(nextActions);
                setAgents(nextAgents.filter((agent) => isOwnedResource(agent, requestScope)));
            }
        }).catch((failure: unknown) => {
            if (!abort.signal.aborted) {
                setError(delegationError(failure));
            }
        }).finally(() => {
            if (!abort.signal.aborted) {
                setLoading(false);
            }
        });
        return () => { abort.abort(); loadVersion.current += 1; };
    }, [scopeType, groupId, reload, revision, mode]);

    const save = async (operation: () => Promise<unknown>, message: string) => {
        const version = loadVersion.current;
        setSaving(true);
        setError('');
        try {
            await operation();
            if (version === loadVersion.current) {
                setNotice(message);
                setReload((value) => value + 1);
            }
        } catch (failure) {
            if (version === loadVersion.current) {
                setError(delegationError(failure));
                setBlocked(failure instanceof ApiError && [401, 403, 409].includes(failure.status));
            }
        } finally {
            if (version === loadVersion.current) {
                setSaving(false);
            }
        }
    };

    const reloadResources = () => {
        setConfirmReload(false);
        setNotice('');
        setReload((value) => value + 1);
    };
    const matches = (name: string) => name.toLowerCase().includes(query.trim().toLowerCase());
    const visibleActions = actions.filter((action) => matches(`${action.displayName ?? ''} ${action.name ?? ''} ${action.description ?? ''}`));
    const visibleAgents = agents.filter((agent) => matches(`${agent.display_name ?? ''} ${agent.name ?? ''}`));

    return (
        <section aria-label="Call agent configuration" className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold text-text-1">Call agent</h2>
                <div className="flex flex-wrap gap-2">
                    <GlassButton size="sm" disabled={loading || saving}
                        onClick={() => dirty ? setConfirmReload(true) : reloadResources()}>Reload Call agent resources</GlassButton>
                    {mode !== 'bindings' && canManage ? (
                        <GlassButton size="sm" variant="primary" disabled={loading || dirty || saving}
                            onClick={() => { setNotice(''); setEditor({}); }}>New Call agent action</GlassButton>
                    ) : null}
                </div>
            </div>
            <p className="text-sm text-text-3">Delegate to one configured agent in the same workspace or a permitted global agent. Foundry-backed agents can be targets; only local agents can have these actions attached.</p>
            {loading ? <p role="status" className="text-sm text-text-3">Loading Call agent resources…</p> : null}
            {error ? <p role="alert" className="break-words text-sm text-danger">{error}</p> : null}
            {notice ? <p role="status" className="text-sm text-text-2">{notice}</p> : null}
            {confirmReload ? (
                <div role="alert" className="space-y-2 rounded-xl border border-edge p-3 text-sm text-text-2">
                    <p>Reloading will discard your unsaved Call agent changes.</p>
                    <GlassButton size="sm" onClick={() => setConfirmReload(false)}>Keep editing</GlassButton>
                    <GlassButton size="sm" onClick={reloadResources}>Discard changes and reload</GlassButton>
                </div>
            ) : null}
            {!loading && catalog && !canManage ? <p role="status" className="text-sm text-warn">Read-only access. You do not have permission to manage Call agent configuration in this scope.</p> : null}
            {editor && canManage ? (
                <CallAgentEditor action={editor.action} targets={catalog?.targets ?? []} saving={saving} blocked={blocked}
                    onCancel={() => setEditor(null)}
                    onSave={(payload: CallAgentWrite) => void save(
                        () => saveCallAgentAction(scope, payload, editor.action), 'Call agent action saved.',
                    )} />
            ) : null}
            {caller && catalog && canManage ? (
                <AgentActionBindings key={caller.id} agent={caller} actions={actions} catalog={catalog}
                    saving={saving} blocked={blocked} onCancel={() => setCaller(null)}
                    onSave={(ids) => void save(() => saveAgentActionBindings(scope, caller, ids), 'Call agent bindings saved.')} />
            ) : null}
            {!loading && catalog ? (
                <>
                    <label className="block text-sm text-text-2">
                        Search delegation resources
                        <input className={`${DELEGATION_INPUT_CLASS} mt-1`} type="search" value={query}
                            onChange={(event) => setQuery(event.target.value)} />
                    </label>
                    {mode !== 'bindings' ? (
                        <div className="space-y-2">
                            <h3 className="text-sm font-medium text-text-2">Call agent actions</h3>
                            {!visibleActions.length ? <p className="text-sm text-text-3">No Call agent actions found.</p> : null}
                            {visibleActions.map((action) => {
                                const target = actionTarget(action);
                                const resolved = catalog.targets.find((entry) => target && referenceKey(entry) === referenceKey(target));
                                return (
                                    <div key={action.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge p-3">
                                        <div className="min-w-0 flex-1 break-words">
                                            <p className="text-sm font-medium text-text-1">{action.displayName || action.name}</p>
                                            <p className="text-xs text-text-3">{resolved
                                                ? `Calls ${resolved.display_name || resolved.name} · ${resolved.scope_type} · ${resolved.agent_type}`
                                                : 'Target unavailable — deleted, disabled or no longer permitted.'}</p>
                                            {action.is_enabled === false ? <p className="text-xs text-warn">Action disabled</p> : null}
                                        </div>
                                        {canManage && isOwnedResource(action, scope) ? (
                                            <div className="flex items-center gap-2">
                                                <GlassButton size="sm" disabled={dirty || saving || !action.id}
                                                    aria-label={`Edit Call agent action ${action.displayName || action.name}`}
                                                    onClick={() => { setNotice(''); setEditor({ action }); }}>Edit</GlassButton>
                                                {!dirty ? (
                                                    <ConfirmAction icon={<Trash2 size={15} />}
                                                        label={`Delete Call agent action ${action.displayName || action.name}`}
                                                        confirmLabel="Confirm delete" busy={saving} disabled={!action.id}
                                                        onConfirm={() => void save(
                                                            () => deleteCallAgentAction(scope, action),
                                                            'Call agent action deleted. Existing references are no longer callable.',
                                                        )} />
                                                ) : null}
                                            </div>
                                        ) : <span className="text-xs text-text-3">Provided · read only</span>}
                                    </div>
                                );
                            })}
                        </div>
                    ) : null}
                    {mode !== 'actions' ? (
                        <div className="space-y-2">
                            <h3 className="text-sm font-medium text-text-2">Calling agents</h3>
                            {!visibleAgents.length ? <p className="text-sm text-text-3">No calling agents found. Create a local agent first, then attach a Call agent action here.</p> : null}
                            {visibleAgents.map((agent) => (
                                <div key={agent.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge p-3">
                                    <span className="min-w-0 flex-1 break-words text-sm text-text-1">{agent.display_name || agent.name}</span>
                                    {(agent.agent_type || 'local') === 'local' ? (
                                        canManage ? <GlassButton size="sm" disabled={dirty || saving}
                                            aria-label={`Attach Call agent actions to ${agent.display_name || agent.name}`}
                                            onClick={() => { setNotice(''); setCaller(agent); }}>Attach Call agent actions</GlassButton> : null
                                    ) : <span className="text-xs text-text-3">Target only — configure tools in Foundry</span>}
                                </div>
                            ))}
                        </div>
                    ) : null}
                </>
            ) : null}
        </section>
    );
}
