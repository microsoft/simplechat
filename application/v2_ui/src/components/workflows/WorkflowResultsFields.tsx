// WorkflowResultsFields.tsx

import { useEffect, useId, useState } from 'react';
import { fetchCollaboratorSuggestions, fetchGroupMembers } from '../../lib/collaboration';
import type { WorkflowDefinition, WorkflowEditorOptions, WorkflowResultsDelivery, WorkflowScope } from '../../lib/workflowEditor';
import { workflowResultsSummary } from '../../lib/workflowChatExecution';
import { WorkflowField, WorkflowFieldList, WorkflowReadout, WorkflowSwitch, workflowFieldInputClass } from './WorkflowField';
import { GlassButton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';

interface RecipientChoice { id: string; label: string }

export function WorkflowResultsFields({
    workflow, options, scope, onChange,
}: {
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    scope: WorkflowScope;
    onChange: (value: WorkflowResultsDelivery) => void;
}) {
    const id = useId();
    const value = workflow.results_delivery;
    const [query, setQuery] = useState('');
    const [candidates, setCandidates] = useState<RecipientChoice[]>([]);
    const [known, setKnown] = useState<Record<string, string>>({});
    const [searching, setSearching] = useState(false);
    const [error, setError] = useState('');
    const catalog = options.results_delivery;
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);
    const shared = value?.mode === 'conversation' && ['shared', 'group_shared'].includes(value.conversation_type);
    const groupId = scope.type === 'group' ? scope.groupId : undefined;
    const searchActive = shared && !value?.all_group_members;

    useEffect(() => {
        if (!searchActive) { setSearching(false); return; }
        const controller = new AbortController();
        setCandidates([]);
        setSearching(true);
        setError('');
        const timer = window.setTimeout(async () => {
            try {
                const choices = groupId
                    ? (await fetchGroupMembers(groupId, query, controller.signal)).map((member) => ({
                        id: String(member.userId ?? member.user_id ?? member.id ?? ''),
                        label: String(member.displayName ?? member.display_name ?? member.name ?? member.email ?? ''),
                    }))
                    : (await fetchCollaboratorSuggestions(query, { limit: 8 }, controller.signal)).results.map((person) => ({
                        id: String(person.user_id ?? ''), label: String(person.display_name || person.email || person.user_id || ''),
                    }));
                if (controller.signal.aborted) return;
                const valid = choices.filter((choice) => choice.id && choice.id !== currentUserId);
                setCandidates(valid);
                setKnown((current) => ({ ...current, ...Object.fromEntries(valid.map((choice) => [choice.id, choice.label])) }));
            } catch {
                if (!controller.signal.aborted) setError('Could not load recipients. Try another search or try again later.');
            } finally {
                if (!controller.signal.aborted) setSearching(false);
            }
        }, 250);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [groupId, query, searchActive, currentUserId]);

    const privateType = scope.type === 'group' ? 'group' : 'personal';
    const base: WorkflowResultsDelivery = value ?? catalog?.default ?? {
        version: 1, mode: 'conversation', conversation_type: privateType, recipient_ids: [], all_group_members: false,
    };
    const choices = catalog?.recipient_choices ?? [];
    const recipientLabel = (key: string) => known[key] || choices.find((choice) => choice.id === key)?.label || key;
    return (
        <WorkflowFieldList>
            <WorkflowField label="Results delivery" htmlFor={`${id}-mode`} width="wide"
                help="Every run keeps its own audit history. A results conversation shares the outcome and deliverables, not that private audit.">
                <select id={`${id}-mode`} aria-label="Results delivery" className={workflowFieldInputClass} value={value?.mode ?? 'legacy'}
                    onChange={(event) => onChange({
                        ...base, mode: event.target.value as WorkflowResultsDelivery['mode'],
                        conversation_type: privateType, recipient_ids: [], all_group_members: false,
                    })}>
                    {!value ? <option value="legacy">Existing delivery behavior (unchanged)</option> : null}
                    <option value="history">Run history only</option>
                    <option value="conversation">Create a results conversation</option>
                    <option value="task">Delivered by a task/agent</option>
                </select>
            </WorkflowField>
            {value?.mode === 'conversation' ? <>
                <WorkflowField label="Results audience" htmlFor={`${id}-audience`} width="wide"
                    help={scope.type === 'group' ? 'Results stay bound to this workflow’s group. Sharing can include only its current members.'
                        : 'Keep results private or share a new conversation with named people.'}>
                    <select id={`${id}-audience`} aria-label="Results audience" className={workflowFieldInputClass} value={value.conversation_type}
                        onChange={(event) => onChange({
                            ...value, conversation_type: event.target.value as WorkflowResultsDelivery['conversation_type'],
                            recipient_ids: [], all_group_members: false,
                        })}>
                        <option value={privateType}>{scope.type === 'group' ? 'Private in this group' : 'Personal (private)'}</option>
                        <option value={scope.type === 'group' ? 'group_shared' : 'shared'}
                            disabled={!catalog?.conversation_types.some((choice) =>
                                choice.id === (scope.type === 'group' ? 'group_shared' : 'shared') && choice.available !== false)}>
                            {scope.type === 'group' ? 'Shared in this group' : 'Shared personal'}
                        </option>
                    </select>
                </WorkflowField>
                {shared ? <WorkflowField label="Recipients" width="full" help="Recipients are checked against current membership and sharing permissions whenever results are delivered.">
                    {scope.type === 'group' && catalog?.allow_all_group_members ? (
                        <WorkflowSwitch label="All current group members" checked={value.all_group_members}
                            description="Resolve current membership for each run, including later membership changes."
                            onChange={(checked) => onChange({ ...value, all_group_members: checked, recipient_ids: [] })} />
                    ) : null}
                    {!value.all_group_members ? <>
                        <label htmlFor={`${id}-search`} className="mb-1 block text-sm text-text-2">{groupId ? 'Search group members' : 'Search people'}</label>
                        <input id={`${id}-search`} type="search" aria-label="Search results recipients" className={workflowFieldInputClass}
                            value={query} onChange={(event) => setQuery(event.target.value)} />
                        <div className="mt-2 space-y-1">
                            {value.recipient_ids.map((key) => <div key={key} className="flex min-w-0 items-center justify-between gap-2 py-1">
                                <span className="min-w-0 break-words text-sm text-text-2">{recipientLabel(key)}</span>
                                <GlassButton size="sm" className="shrink-0 whitespace-nowrap" aria-label={`Remove recipient ${recipientLabel(key)}`}
                                    onClick={() => onChange({ ...value, recipient_ids: value.recipient_ids.filter((item) => item !== key) })}>Remove</GlassButton>
                            </div>)}
                        </div>
                        <ul aria-label="Available results recipients" className="mt-2 space-y-1">
                            {candidates.filter((choice) => !value.recipient_ids.includes(choice.id)).map((choice) => (
                                <li key={choice.id} className="flex min-w-0 items-center justify-between gap-2 py-1">
                                    <span className="min-w-0 break-words text-sm text-text-2">{choice.label || choice.id}</span>
                                    <GlassButton size="sm" className="shrink-0 whitespace-nowrap" aria-label={`Add recipient ${choice.label || choice.id}`}
                                        onClick={() => onChange({ ...value, recipient_ids: [...value.recipient_ids, choice.id] })}>Add</GlassButton>
                                </li>
                            ))}
                        </ul>
                        <p role="status" className="mt-2 text-xs text-text-3">{searching ? 'Searching recipients…'
                            : !error && !candidates.length ? 'No matching recipients. Search by name or email.' : ''}</p>
                        {error ? <p role="alert" className="mt-2 text-xs text-danger">{error}</p> : null}
                        {!value.recipient_ids.length ? <p className="mt-2 text-xs text-warn">Select at least one recipient before saving shared results.</p> : null}
                    </> : null}
                </WorkflowField> : null}
            </> : null}
            <WorkflowReadout label="Effective audience">{workflowResultsSummary(workflow)}</WorkflowReadout>
        </WorkflowFieldList>
    );
}
