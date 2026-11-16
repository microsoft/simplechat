// WorkflowMicrosoft365RunAs.tsx

import { useEffect, useId, useState } from 'react';
import { GlassButton } from '../ui/primitives';
import { WorkflowField, workflowFieldInputClass } from './WorkflowField';
import {
    fetchWorkflowM365RunAsUsers,
    workflowScopeKey,
    type WorkflowM365RunAsUser,
    type WorkflowScope,
} from '../../lib/workflowEditor';

interface AccountChoices {
    scopeKey: string;
    status: 'loading' | 'ready' | 'failed';
    users: WorkflowM365RunAsUser[];
}

export function WorkflowMicrosoft365RunAs({
    scope,
    value,
    disabled = false,
    canListAccounts = true,
    onChange,
}: {
    scope: WorkflowScope;
    value: string;
    disabled?: boolean;
    /**
     * Whether this caller may list eligible accounts. The route refuses everyone else, so a
     * read-only viewer is shown only whether an account is stored, and nothing is requested.
     */
    canListAccounts?: boolean;
    onChange: (userId: string) => void;
}) {
    const selectId = useId();
    const helpId = `${selectId}-help`;
    const statusId = `${selectId}-status`;
    const scopeKey = workflowScopeKey(scope);
    const scopeType = scope.type;
    const groupId = scope.type === 'group' ? scope.groupId : '';
    const [attempt, setAttempt] = useState(0);
    const [choices, setChoices] = useState<AccountChoices>({
        scopeKey,
        status: 'loading',
        users: [],
    });

    useEffect(() => {
        if (!canListAccounts) {
            return undefined;
        }
        const controller = new AbortController();
        const requestScope: WorkflowScope = scopeType === 'group'
            ? { type: 'group', groupId }
            : { type: 'personal' };
        setChoices({ scopeKey, status: 'loading', users: [] });
        void fetchWorkflowM365RunAsUsers(requestScope, controller.signal).then(
            (users) => {
                if (!controller.signal.aborted) {
                    setChoices({ scopeKey, status: 'ready', users });
                }
            },
            () => {
                if (!controller.signal.aborted) {
                    setChoices({ scopeKey, status: 'failed', users: [] });
                }
            },
        );
        return () => controller.abort();
    }, [scopeKey, scopeType, groupId, attempt, canListAccounts]);

    const help = (
        <>
            Microsoft 365 actions use this account for manual and scheduled runs. The selected person
            must connect Microsoft 365. Selecting an account does not grant consent: when someone else saves
            the workflow or changes an agent or action it uses, the selected person approves that revision
            before it runs as them. A revision they saved themselves needs no separate approval.
        </>
    );

    if (!canListAccounts) {
        return (
            <WorkflowField label="Microsoft 365 Run as" htmlFor={selectId} width="standard" help={help} helpId={helpId}>
                <select
                    id={selectId}
                    className={workflowFieldInputClass}
                    value={value}
                    disabled
                    aria-describedby={`${helpId} ${statusId}`}
                >
                    <option value={value}>{value ? 'Account selected' : 'No Microsoft 365 account selected'}</option>
                </select>
                <p id={statusId} className="mt-1.5 text-xs text-text-3">
                    Only workflow managers can see which account is selected or change it.
                </p>
            </WorkflowField>
        );
    }

    const status = choices.scopeKey === scopeKey ? choices.status : 'loading';
    const users = choices.scopeKey === scopeKey ? choices.users : [];
    const loading = status === 'loading';
    const failed = status === 'failed';
    const missingSelection = Boolean(value) && !users.some((user) => user.id === value);
    const missingLabel = loading
        ? 'Selected account (loading account list)'
        : failed
            ? 'Selected account (unable to verify)'
            : 'Previously selected account (review required)';
    const statusMessage = loading
        ? 'Loading eligible Microsoft 365 accounts…'
        : failed
            ? 'Could not load eligible Microsoft 365 accounts. Your selection is kept unless you change it.'
            : missingSelection
                ? 'The selected account was not returned for this scope. It has been retained; review it before running the workflow.'
                : !users.length
                    ? 'No eligible Microsoft 365 accounts were returned for this scope.'
                    : '';

    return (
        <WorkflowField label="Microsoft 365 Run as" htmlFor={selectId} width="standard" help={help} helpId={helpId}>
            <select
                id={selectId}
                className={workflowFieldInputClass}
                value={value}
                disabled={disabled || loading}
                aria-busy={loading}
                aria-describedby={`${helpId}${statusMessage ? ` ${statusId}` : ''}`}
                onChange={(event) => onChange(event.target.value)}
            >
                <option value="">No Microsoft 365 account selected</option>
                {missingSelection ? <option value={value}>{missingLabel}</option> : null}
                {users.map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}
            </select>
            {statusMessage ? (
                <p
                    id={statusId}
                    role={failed ? 'alert' : 'status'}
                    className={failed || missingSelection
                        ? 'mt-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-sm text-warn'
                        : 'mt-1.5 text-xs text-text-3'}
                >
                    {statusMessage}
                </p>
            ) : null}
            {failed ? (
                <GlassButton type="button" size="sm" className="mt-2" disabled={disabled}
                    onClick={() => setAttempt((current) => current + 1)}>
                    Retry Microsoft 365 account list
                </GlassButton>
            ) : null}
        </WorkflowField>
    );
}
