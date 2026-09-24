// OrchestrationPlannerModelPicker.tsx
// Pick the orchestration planner model from the models already configured.
//
// The planner used to be named with four typed values -- deployment, model id, endpoint id and
// provider -- that had to agree with each other and with a saved connection. The list here is
// the same one the default chat model picker offers, so an administrator picks a model and the
// four values are written for them. The choice joins the page's other unsaved edits and is
// stored by the normal Save button.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { fetchCapabilityModels } from '../../lib/capabilityModels';
import type { AdminField } from '../../lib/adminFields';
import type { DefaultModelChoice } from '../../lib/modelConnections';
import {
    ANSWER_MODEL_VALUE,
    SAVED_VALUE,
    classicPlannerChoices,
    connectionPlannerChoices,
    describePlannerSelection,
    plannerSelectionUpdates,
    plannerSelectionValue,
    readPlannerSelection,
    type PlannerModelChoice,
} from '../../lib/orchestrationPlannerModel';
import { useModelConnectionsStore } from '../../stores/modelConnectionsStore';
import { GlassButton } from '../ui/primitives';
import { FieldShell } from './fields';

export function OrchestrationPlannerModelPicker({
    field,
    connectionsEnabled,
    read,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    /** Whether chat uses saved AI Connections rather than the classic single endpoint. */
    connectionsEnabled: boolean;
    /** Reads a setting, preferring the page's unsaved edit. */
    read: (key: string) => unknown;
    error?: string;
    disabled?: boolean;
    onChange: (updates: Record<string, string>) => void;
}) {
    const id = 'admin-field-orchestration-planner-model';
    const revision = useModelConnectionsStore((state) => state.revision);
    const [connectionModels, setConnectionModels] = useState<DefaultModelChoice[]>([]);
    const [loading, setLoading] = useState(connectionsEnabled);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [reload, setReload] = useState(0);

    // Refetched whenever the connection list is written, like the default chat model picker,
    // so a model added or removed beside this control is offered or withdrawn at once.
    useEffect(() => {
        if (!connectionsEnabled) {
            setLoading(false);
            return;
        }
        const controller = new AbortController();
        setLoading(true);
        void fetchCapabilityModels('chat', controller.signal).then((response) => {
            if (!controller.signal.aborted) {
                setConnectionModels(response.choices);
                setLoadError(null);
            }
        }).catch((fetchError: unknown) => {
            if (!controller.signal.aborted) {
                setLoadError(fetchError instanceof Error ? fetchError.message : 'Models could not be loaded.');
            }
        }).finally(() => {
            if (!controller.signal.aborted) {
                setLoading(false);
            }
        });
        return () => controller.abort();
    }, [connectionsEnabled, revision, reload]);

    const choices: PlannerModelChoice[] = connectionsEnabled
        ? connectionPlannerChoices(connectionModels)
        : classicPlannerChoices(read);
    // Until the connection list has loaded, a saved model cannot be matched against it, so it
    // is shown as saved rather than reported as missing from a list that is not there yet.
    const listReady = !connectionsEnabled || (!loading && !loadError);
    const selection = readPlannerSelection(read);
    const value = plannerSelectionValue(selection, choices);
    const groups = new Map<string, PlannerModelChoice[]>();
    for (const choice of choices) {
        const group = choice.group ?? '';
        groups.set(group, [...(groups.get(group) ?? []), choice]);
    }

    return (
        <FieldShell field={field} error={error} htmlFor={id}>
            <select
                id={id}
                className={clsx(
                    'w-full appearance-none rounded-lg border border-edge bg-surface-1 px-3 py-2 pr-8',
                    'text-sm text-text-1 focus:border-accent focus:outline-none',
                    'disabled:cursor-not-allowed disabled:opacity-60',
                )}
                value={value}
                disabled={disabled || loading}
                onChange={(event) => {
                    const updates = plannerSelectionUpdates(event.target.value, choices);
                    if (updates) {
                        onChange(updates);
                    }
                }}
            >
                <option value={ANSWER_MODEL_VALUE}>Use the answer model (default)</option>
                {value === SAVED_VALUE ? (
                    <option value={SAVED_VALUE}>
                        {describePlannerSelection(selection)}
                        {listReady ? ' — not in the current model list' : ''}
                    </option>
                ) : null}
                {[...groups].map(([group, items]) => (group ? (
                    <optgroup key={group} label={group}>
                        {items.map((choice) => (
                            <option key={choice.value} value={choice.value}>{choice.label}</option>
                        ))}
                    </optgroup>
                ) : (
                    items.map((choice) => (
                        <option key={choice.value} value={choice.value}>{choice.label}</option>
                    ))
                )))}
            </select>

            {loading ? (
                <p role="status" className="mt-1.5 text-xs text-text-3">Loading models…</p>
            ) : null}
            {listReady && !choices.length ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    {connectionsEnabled
                        ? 'No saved AI Connection publishes a chat model yet. Add one under AI Models.'
                        : 'No classic chat deployment is configured yet. Add one under AI Models.'}
                </p>
            ) : null}
            {listReady && value === SAVED_VALUE ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    The saved planner model is not one of the models listed here. It is kept until
                    you choose another; planning fails rather than switching models if it cannot
                    be used.
                </p>
            ) : null}
            {loadError ? (
                <div role="alert" className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-danger">
                    <AlertCircle size={13} className="shrink-0" />
                    <span>{loadError}</span>
                    <GlassButton type="button" variant="subtle" size="sm" onClick={() => setReload((count) => count + 1)}>
                        <RefreshCw size={13} /> Retry
                    </GlassButton>
                </div>
            ) : null}
        </FieldShell>
    );
}
