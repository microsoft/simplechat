// AgentActionPicker.tsx

import { useState, type Dispatch, type SetStateAction } from 'react';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { actionTarget, referenceKey, type AgentTargetCatalog } from '../../lib/agentDelegation';
import type { ActionConfiguration, AgentConfiguration, AgentEditorOptions } from '../../lib/workspaceAuthoring';
import {
    AGENT_ACTION_CAPABILITIES, agentActionCapabilities, agentActionLabel, agentActionUnavailableReason,
    agentHasAction, resolveAgentAction, toggleAgentAction, updateAgentCapability,
} from '../../lib/workspaceAgentActions';
import { AGENT_INPUT_CLASS } from '../../lib/workspaceAgentAuthoring';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill, SectionSearch } from '../workspace/primitives';
import { AgentField, AgentNotice } from './AgentFields';

export function AgentActionPicker({
    draft, setDraft, actions, targets, loading, error, targetError, ownerId, builtinActions,
    canCreateActions, onRefresh, onNewAction, readOnly,
}: {
    draft: AgentConfiguration;
    setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    actions: ActionConfiguration[];
    targets: AgentTargetCatalog | null;
    loading: boolean;
    error: string | null;
    targetError: string | null;
    ownerId: string;
    builtinActions: AgentEditorOptions['builtin_actions'];
    canCreateActions: boolean;
    onRefresh: () => void;
    onNewAction: () => void;
    readOnly: boolean;
}) {
    const [query, setQuery] = useState('');
    const [typeFilter, setTypeFilter] = useState('');
    const [selectedOnly, setSelectedOnly] = useState(false);
    const [confirmDetach, setConfirmDetach] = useState(false);
    const unresolved = draft.actions_to_load.filter((reference) => !resolveAgentAction(reference, actions));
    const types = [...new Set(actions.map((action) => action.type))].sort();
    const visible = actions.filter((action) =>
        `${agentActionLabel(action)} ${action.name} ${action.description} ${action.type} ${action.type === 'agent' ? 'Call agent' : ''}`.toLowerCase().includes(query.trim().toLowerCase()) &&
        (!typeFilter || action.type === typeFilter) && (!selectedOnly || agentHasAction(draft, action, actions)));

    if (draft.agent_type !== 'local') {
        return (
            <div className="space-y-3">
                <AgentNotice>Foundry manages this agent’s tools. Local action assignment and capability controls are not editable for this type.</AgentNotice>
                {error ? <AgentNotice error>{error} Existing references remain in the draft.</AgentNotice> : null}
                {targetError ? <AgentNotice error>{targetError}</AgentNotice> : null}
                {draft.actions_to_load.length ? (
                    <div className="space-y-3 rounded-xl border border-warn/40 p-3">
                        <p className="text-sm text-text-2">These local actions are still in the draft. Detach them explicitly to save a Foundry agent, or switch back to Local.</p>
                        <ul className="list-inside list-disc text-sm text-text-3">
                            {draft.actions_to_load.map((reference) => {
                                const action = resolveAgentAction(reference, actions);
                                return <li key={reference}>{action ? agentActionLabel(action) : reference}</li>;
                            })}
                        </ul>
                        {!readOnly ? confirmDetach ? (
                            <div className="space-y-2">
                                <p className="text-sm text-warn">Detach all {draft.actions_to_load.length} local action references? Their capability settings will be retained.</p>
                                <div className="flex flex-wrap gap-2">
                                    <GlassButton type="button" size="sm" onClick={() => setConfirmDetach(false)}>Keep actions</GlassButton>
                                    <GlassButton type="button" size="sm" variant="danger" onClick={() => {
                                        setDraft((current) => ({ ...current, actions_to_load: [] }));
                                        setConfirmDetach(false);
                                    }}>Confirm detach</GlassButton>
                                </div>
                            </div>
                        ) : <GlassButton type="button" size="sm" onClick={() => setConfirmDetach(true)}>Detach local actions</GlassButton> : null}
                    </div>
                ) : null}
            </div>
        );
    }
    return (
        <div className="space-y-4">
            <p className="text-sm text-text-3">Select actions for this agent. Capability choices apply only to this assignment. Call agent appears here like any other action; its target remains configured on the action.</p>
            <div className="flex flex-wrap gap-2">
                {!readOnly && canCreateActions ? <GlassButton type="button" size="sm" onClick={onNewAction}><Plus size={14} />New action</GlassButton> : null}
                <GlassButton type="button" size="sm" disabled={loading} onClick={onRefresh}><RefreshCw size={14} />Refresh actions</GlassButton>
                <label className="flex items-center gap-2 text-xs text-text-2">
                    <input type="checkbox" checked={selectedOnly} onChange={(event) => setSelectedOnly(event.target.checked)} className="accent-accent" />
                    Selected only
                </label>
            </div>
            {!canCreateActions && !readOnly ? <AgentNotice>Creating actions is unavailable in this workspace. You can still assign permitted existing actions from the authorized catalogue.</AgentNotice> : null}
            {error ? <AgentNotice error>{error} Existing references have not been removed.</AgentNotice> : null}
            {targetError ? <AgentNotice error>{targetError} Call agent targets could not be checked; existing assignments are preserved.</AgentNotice> : null}
            {loading ? <p role="status" className="text-sm text-text-3">Loading available actions…</p> : null}
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]">
                <SectionSearch value={query} onChange={setQuery} placeholder="Search actions by name, description or type" />
                <AgentField id="agent-action-type-filter" label="Action type">
                    <select id="agent-action-type-filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className={AGENT_INPUT_CLASS}>
                        <option value="">All action types</option>
                        {types.map((type) => <option key={type} value={type}>{type === 'agent' ? 'Call agent' : type}</option>)}
                    </select>
                </AgentField>
            </div>
            <div className="space-y-2">
                {visible.map((action) => {
                    const checked = agentHasAction(draft, action, actions);
                    const reason = agentActionUnavailableReason(draft, action, targets, ownerId);
                    const target = actionTarget(action);
                    const targetDetails = target ? targets?.targets.find((item) => referenceKey(item) === referenceKey(target)) : null;
                    const capabilities = agentActionCapabilities(draft, action);
                    const definitions = AGENT_ACTION_CAPABILITIES[action.type] ?? [];
                    const label = agentActionLabel(action);
                    return (
                        <GlassPanel key={`${action.is_global ? 'global' : 'personal'}:${action.id}`} elevation="flat" className="space-y-3 border border-edge p-3">
                            <label className="flex items-start gap-3">
                                <input type="checkbox" className="mt-1 accent-accent" checked={checked} aria-label={`Assign ${label}`}
                                    disabled={readOnly || (!checked && (loading || Boolean(error) || Boolean(reason)))}
                                    onChange={(event) => setDraft((current) => toggleAgentAction(current, action, event.target.checked, actions))} />
                                <span className="min-w-0 flex-1">
                                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-text-1">
                                        {label}<Pill>{action.type === 'agent' ? 'Call agent' : action.type}</Pill>
                                        {action.is_global ? <Pill tone="accent">Provided</Pill> : <Pill>Personal</Pill>}
                                    </span>
                                    <span className="mt-1 block break-words text-xs text-text-3">{action.description}</span>
                                    <span className="mt-1 block break-all text-[11px] text-text-3">ID: {action.id}</span>
                                    {action.type === 'agent' && target ? (
                                        <span className="mt-1 block break-words text-xs text-text-2">Calls {targetDetails?.display_name || targetDetails?.name || target.id} · {target.scope_type}</span>
                                    ) : null}
                                    {reason ? <span className="mt-1 block text-xs text-warn">{reason}{checked ? ' This saved reference remains until you remove it.' : ''}</span> : null}
                                </span>
                            </label>
                            {checked && definitions.length ? (
                                <details className="rounded-lg border border-edge p-3" open>
                                    <summary className="cursor-pointer text-xs font-medium text-text-2">Capabilities for {label}</summary>
                                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                                        {definitions.map((capability) => (
                                            <label key={capability.key} className="flex items-start gap-2 text-xs text-text-2">
                                                <input type="checkbox" className="mt-0.5 accent-accent" checked={Boolean(capabilities[capability.key])}
                                                    disabled={readOnly || loading || Boolean(error)}
                                                    onChange={(event) => setDraft((current) => updateAgentCapability(current, action, capability.key, event.target.checked))} />
                                                <span>{capability.label}<code className="mt-0.5 block break-all text-[10px] text-text-3">{capability.key}</code></span>
                                            </label>
                                        ))}
                                    </div>
                                </details>
                            ) : null}
                        </GlassPanel>
                    );
                })}
            </div>
            {!visible.length && !loading && !error ? <p role="status" className="text-sm text-text-3">No actions match. Adjust the filters or refresh the authorized catalogue.</p> : null}
            {unresolved.length ? (
                <div className="space-y-2 rounded-xl border border-warn/30 p-3">
                    <h4 className="text-sm font-medium text-text-1">Saved references to review</h4>
                    <p className="text-xs text-text-3">Unlisted, ambiguous, and legacy references are kept during unrelated edits. Remove one only when you no longer want it assigned.</p>
                    {unresolved.map((reference) => (
                        <div key={reference} className="flex flex-wrap items-center justify-between gap-2 text-sm text-text-2">
                            <code className="min-w-0 break-all">{reference}</code>
                            {!readOnly ? <GlassButton type="button" size="sm" aria-label={`Remove action reference ${reference}`}
                                onClick={() => setDraft((current) => ({ ...current, actions_to_load: current.actions_to_load.filter((item) => item !== reference) }))}>
                                <Trash2 size={13} />Remove reference
                            </GlassButton> : null}
                        </div>
                    ))}
                </div>
            ) : null}
            {builtinActions.length ? (
                <div className="rounded-xl border border-edge p-3">
                    <h4 className="text-sm font-medium text-text-2">Enabled built-in tools</h4>
                    <p className="mt-1 text-xs text-text-3">Provided by your administrator; these are not personal settings.</p>
                    <ul className="mt-2 space-y-1 text-xs text-text-2">
                        {builtinActions.map((action) => <li key={action.id}>{action.label}{action.description ? ` — ${action.description}` : ''}</li>)}
                    </ul>
                </div>
            ) : null}
        </div>
    );
}
