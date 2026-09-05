// AgentActionBindings.tsx

import { useState } from 'react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { actionTarget, referenceKey, type AgentTargetCatalog } from '../../lib/agentDelegation';
import type { WorkspaceAction, WorkspaceAgent } from '../../lib/types';
import { DELEGATION_INPUT_CLASS } from './CallAgentEditor';

export function AgentActionBindings({
    agent, actions, catalog, saving, blocked, onSave, onCancel,
}: {
    agent: WorkspaceAgent;
    actions: WorkspaceAction[];
    catalog: AgentTargetCatalog;
    saving: boolean;
    blocked: boolean;
    onSave: (ids: string[]) => void;
    onCancel: () => void;
}) {
    const original = agent.actions_to_load ?? [];
    const [selected, setSelected] = useState(() => actions.filter((action) => original.includes(action.id)).map((action) => action.id));
    const [query, setQuery] = useState('');
    const callerKey = referenceKey({ id: agent.id, scope_type: catalog.scope_type, scope_id: catalog.scope_id });
    const availableTargets = new Set(catalog.targets.map(referenceKey));
    const visible = actions.filter((action) =>
        `${action.displayName ?? ''} ${action.name ?? ''} ${action.description ?? ''}`.toLowerCase().includes(query.trim().toLowerCase()),
    );
    const preserved = original.filter((id) => !actions.some((action) => action.id === id));

    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <h3 className="break-words font-medium text-text-1">Call agent actions for {agent.display_name || agent.name}</h3>
            <p className="text-xs text-text-3">Only local agents can call agents. Other actions, legacy references, model, knowledge and capability settings are preserved.</p>
            {preserved.length ? <p className="text-xs text-text-3">{preserved.length} other or unlisted action reference(s) will remain unchanged.</p> : null}
            <label className="block text-sm text-text-2">
                Search Call agent actions
                <input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
                    className={`${DELEGATION_INPUT_CLASS} mt-1`} />
            </label>
            <fieldset disabled={saving || blocked} className="space-y-2">
                <legend className="sr-only">Attached Call agent actions</legend>
                {visible.map((action) => {
                    const target = actionTarget(action);
                    const key = target ? referenceKey(target) : '';
                    const selfCall = key === callerKey;
                    const unavailable = !availableTargets.has(key) || action.is_enabled === false;
                    const checked = selected.includes(action.id);
                    const targetLabel = catalog.targets.find((entry) => referenceKey(entry) === key);
                    return (
                        <label key={action.id} className="flex items-start gap-3 rounded-lg border border-edge p-3 text-sm text-text-2">
                            <input type="checkbox" checked={checked} disabled={!checked && (selfCall || unavailable || !action.id)}
                                onChange={(event) => setSelected(event.target.checked
                                    ? [...selected, action.id] : selected.filter((id) => id !== action.id))} />
                            <span className="min-w-0 break-words">
                                <span className="block">{action.displayName || action.name}</span>
                                <span className="block text-xs text-text-3">
                                    {selfCall ? 'Self-call blocked — detach this action.' : unavailable
                                        ? 'Target unavailable or action disabled — existing binding can be removed.'
                                        : `Calls ${targetLabel?.display_name || targetLabel?.name} (${targetLabel?.scope_type})`}
                                </span>
                            </span>
                        </label>
                    );
                })}
            </fieldset>
            {!visible.length ? <p role="status" className="text-sm text-text-3">No Call agent actions match. Create an action in this workspace first.</p> : null}
            <p className="text-xs text-text-3">Selection is unsaved until you save bindings.</p>
            <div className="flex flex-wrap justify-end gap-2">
                <GlassButton size="sm" disabled={saving} onClick={onCancel}>Cancel</GlassButton>
                <GlassButton size="sm" variant="primary" disabled={saving || blocked} onClick={() => onSave(selected)}>
                    {saving ? 'Saving bindings…' : 'Save bindings'}
                </GlassButton>
            </div>
        </GlassPanel>
    );
}
