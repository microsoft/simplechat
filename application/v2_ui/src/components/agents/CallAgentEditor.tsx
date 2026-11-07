// CallAgentEditor.tsx

import { useId, useState } from 'react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import {
    actionTarget,
    referenceKey,
    type AgentTarget,
    type CallAgentWrite,
} from '../../lib/agentDelegation';
import type { WorkspaceAction } from '../../lib/types';

export const DELEGATION_INPUT_CLASS =
    'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

export function CallAgentEditor({
    action,
    targets,
    saving,
    blocked,
    onSave,
    onCancel,
}: {
    action?: WorkspaceAction;
    targets: AgentTarget[];
    saving: boolean;
    blocked: boolean;
    onSave: (payload: CallAgentWrite) => void;
    onCancel: () => void;
}) {
    const fieldId = useId();
    const previousTarget = action ? actionTarget(action) : null;
    const [displayName, setDisplayName] = useState(action?.displayName || action?.name || '');
    const [description, setDescription] = useState(action?.description || '');
    const [targetKey, setTargetKey] = useState(previousTarget ? referenceKey(previousTarget) : '');
    const [query, setQuery] = useState('');
    const selected = targets.find((target) => referenceKey(target) === targetKey);
    const visibleTargets = targets.filter((target) =>
        referenceKey(target) === targetKey ||
        `${target.display_name ?? ''} ${target.name} ${target.description ?? ''} ${target.agent_type} ${target.scope_type}`
            .toLowerCase().includes(query.trim().toLowerCase()),
    );
    const canSave = Boolean(displayName.trim() && selected && !blocked && !saving);

    const submit = () => {
        if (!canSave || !selected) {
            return;
        }
        const metadata = action?.metadata;
        onSave({
            ...(action ? { id: action.id } : {}),
            name: action?.name || displayName.trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'call-agent',
            displayName: displayName.trim(),
            description,
            type: 'agent',
            endpoint: 'internal://agent',
            auth: { type: 'user' },
            metadata: metadata && typeof metadata === 'object' && !Array.isArray(metadata)
                ? metadata as Record<string, unknown> : {},
            is_enabled: action?.is_enabled !== false,
            additionalFields: {
                target_agent: {
                    id: selected.id,
                    scope_type: selected.scope_type,
                    scope_id: selected.scope_id,
                },
            },
        });
    };

    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <h3 className="font-medium text-text-1">{action ? 'Edit Call agent action' : 'New Call agent action'}</h3>
            <p className="text-xs text-text-3">Unsaved changes stay here until you save or cancel.</p>
            <form onSubmit={(event) => { event.preventDefault(); submit(); }} className="space-y-3">
                <fieldset disabled={saving || blocked} className="space-y-3">
                    <div>
                        <label htmlFor={`${fieldId}-name`} className="mb-1 block text-sm text-text-2">Action name</label>
                        <input id={`${fieldId}-name`} autoFocus required value={displayName}
                            onChange={(event) => setDisplayName(event.target.value)} className={DELEGATION_INPUT_CLASS} />
                    </div>
                    <div>
                        <label htmlFor={`${fieldId}-description`} className="mb-1 block text-sm text-text-2">Action description</label>
                        <textarea id={`${fieldId}-description`} rows={2} value={description}
                            onChange={(event) => setDescription(event.target.value)} className={DELEGATION_INPUT_CLASS} />
                    </div>
                    <div>
                        <label htmlFor={`${fieldId}-search`} className="mb-1 block text-sm text-text-2">Search target agents</label>
                        <input id={`${fieldId}-search`} type="search" value={query}
                            onChange={(event) => setQuery(event.target.value)} className={DELEGATION_INPUT_CLASS} />
                    </div>
                    <div>
                        <label htmlFor={`${fieldId}-target`} className="mb-1 block text-sm text-text-2">Target agent</label>
                        <select id={`${fieldId}-target`} value={targetKey}
                            onChange={(event) => setTargetKey(event.target.value)} className={DELEGATION_INPUT_CLASS}>
                            <option value="">Select a target agent</option>
                            {targetKey && !selected ? <option value={targetKey} disabled>Unavailable target — select another agent</option> : null}
                            {visibleTargets.map((target) => (
                                <option key={referenceKey(target)} value={referenceKey(target)}>
                                    {target.display_name || target.name} · {target.scope_type} · {target.agent_type}
                                </option>
                            ))}
                        </select>
                    </div>
                </fieldset>
                {targetKey && !selected ? <p role="alert" className="text-sm text-warn">The saved target is unavailable or access was revoked. It will never be replaced by a same-name agent automatically.</p> : null}
                {!targets.length ? <p role="status" className="text-sm text-text-3">No permitted target agents are available in this scope.</p> : null}
                {selected ? <p className="break-words text-sm text-text-2">{selected.description || 'This action calls only the selected agent.'}</p> : null}
                <p className="text-xs text-text-3">Uses the current user’s permissions. Only the task and explicit context are passed, not the full conversation. Limits: 3 levels, 10 calls per turn, 120 seconds per call. Self-calls and loops are blocked by the server.</p>
                <div className="flex flex-wrap justify-end gap-2">
                    <GlassButton type="button" size="sm" disabled={saving} onClick={onCancel}>Cancel</GlassButton>
                    <GlassButton type="submit" size="sm" variant="primary" disabled={!canSave}>
                        {saving ? 'Saving action…' : 'Save Call agent action'}
                    </GlassButton>
                </div>
            </form>
        </GlassPanel>
    );
}
