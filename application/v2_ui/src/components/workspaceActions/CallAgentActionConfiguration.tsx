// CallAgentActionConfiguration.tsx

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ActionField, ACTION_INPUT_CLASS } from './ActionFields';
import {
    actionTarget, fetchAgentTargets, PERSONAL_DELEGATION_SCOPE, referenceKey, type AgentTargetCatalog,
} from '../../lib/agentDelegation';
import { actionFieldError, withActionValue } from '../../lib/workspaceActionLogic';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import { errorMessage } from '../workspace/useSectionResource';

export function CallAgentActionConfiguration(props: ActionConnectorProps) {
    const id = useId();
    const [catalogue, setCatalogue] = useState<AgentTargetCatalog | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [version, setVersion] = useState(0);
    const callback = useRef(props.onValidityChange);
    callback.current = props.onValidityChange;
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true); setError(null);
        void fetchAgentTargets(PERSONAL_DELEGATION_SCOPE, controller.signal).then((result) => {
            if (controller.signal.aborted) return;
            if (!result || !Array.isArray(result.targets)) throw new Error('The target catalogue returned an invalid response.');
            setCatalogue(result);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setError(errorMessage(cause, 'Could not load permitted target agents.'));
        }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [version]);
    const target = actionTarget(props.draft);
    const selectedKey = target ? referenceKey(target) : '';
    const targets = catalogue?.targets ?? [];
    const selected = targets.find((candidate) => referenceKey(candidate) === selectedKey);
    const visible = useMemo(() => targets.filter((candidate) =>
        referenceKey(candidate) === selectedKey ||
        `${candidate.display_name} ${candidate.name} ${candidate.description} ${candidate.agent_type} ${candidate.scope_type} ${candidate.id}`
            .toLowerCase().includes(query.trim().toLowerCase())), [targets, selectedKey, query]);
    const validation = loading ? 'Wait for the permitted target agents to load.' : error ||
        (catalogue?.can_manage === false ? 'You no longer have permission to configure Call agent actions.' :
            !selected ? 'Select an available, authorized target agent.' : null);
    useEffect(() => {
        callback.current('call-agent-target', props.readOnly ? null : validation);
        return () => callback.current('call-agent-target', null);
    }, [props.readOnly, validation]);
    return (
        <div className="space-y-4" data-testid="call-agent-configuration">
            <p className="text-sm text-text-2">This action calls one explicitly selected agent using your current permissions.</p>
            <ActionField id={`${id}-search`} label="Search target agents">
                <input id={`${id}-search`} type="search" className={ACTION_INPUT_CLASS} value={query}
                    onChange={(event) => setQuery(event.target.value)} />
            </ActionField>
            <ActionField id={`${id}-target`} label="Target agent" required
                error={actionFieldError(props.errors, '/additionalFields/target_agent')}>
                <select id={`${id}-target`} className={ACTION_INPUT_CLASS} value={selectedKey} required
                    disabled={props.readOnly || loading || Boolean(error) || catalogue?.can_manage === false}
                    onChange={(event) => {
                        const chosen = targets.find((candidate) => referenceKey(candidate) === event.target.value);
                        if (!chosen) return;
                        props.onChange((draft) => withActionValue(draft, '/additionalFields/target_agent', {
                            id: chosen.id, scope_type: chosen.scope_type, scope_id: chosen.scope_id,
                        }));
                    }}>
                    <option value="">Select a target agent</option>
                    {target && !selected ? <option value={selectedKey} disabled>Unavailable target · {target.scope_type} · {target.id}</option> : null}
                    {visible.map((candidate) => <option key={referenceKey(candidate)} value={referenceKey(candidate)}>
                        {candidate.display_name || candidate.name} · {candidate.scope_type} · {candidate.agent_type} · {candidate.id}
                    </option>)}
                </select>
            </ActionField>
            {loading ? <p role="status" className="text-sm text-text-3">Loading permitted target agents…</p> : null}
            {error ? <div role="alert" className="space-y-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
                <p>{error}</p>
                <GlassButton type="button" size="sm" onClick={() => setVersion((value) => value + 1)}><RefreshCw size={14} />Retry target agents</GlassButton>
            </div> : null}
            {!loading && !error && !targets.length ? <p role="status" className="text-sm text-text-3">No permitted target agents are available.</p> : null}
            {!loading && target && !selected ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                The saved target is unavailable or access was revoked. Its scope and ID are retained; no same-name agent will be selected automatically.
            </p> : null}
            {selected ? <p className="break-words text-sm text-text-2">{selected.description || 'Only this selected agent can be called by the action.'}</p> : null}
            {target ? <dl className="grid gap-1 break-all text-xs text-text-3">
                <div><dt className="inline font-medium">Scope: </dt><dd className="inline">{target.scope_type} · {target.scope_id}</dd></div>
                <div><dt className="inline font-medium">Agent ID: </dt><dd className="inline">{target.id}</dd></div>
            </dl> : null}
            <p className="text-xs leading-relaxed text-text-3">
                Only the task and explicit context are passed, not the full conversation. Self-calls and cycles are blocked by the server.
                Limits are 3 levels, 10 calls per turn, and 120 seconds per call. No endpoint, credential, or connection test is needed.
            </p>
        </div>
    );
}
