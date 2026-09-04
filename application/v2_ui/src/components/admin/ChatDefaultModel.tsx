// ChatDefaultModel.tsx
// Picks the model chat falls back to when nothing else has chosen one.
//
// The stored value is a reference -- a connection id plus a model id -- so it is only
// meaningful next to the connections that currently exist. Two consequences shape this
// component:
//
//   - The list is built from /api/v2/admin/model-endpoints rather than the settings
//     document the surrounding page already holds, because that document carries raw
//     credentials and the sanitized route does not.
//   - Only models that are enabled on an enabled connection are offered. Anything else
//     is cleared by the server the next time connections are written, so offering it
//     would let an administrator pick a value that silently reverts.
//
// The choice saves on its own rather than joining the page's draft, for the same reason
// the connection list does: it is written through its own validating endpoint, not the
// settings PATCH, which refuses this key outright.
//
// Connections are edited in the section directly above this one, so what may be offered
// changes while this component is mounted. Whether chat uses connections at all is passed
// in from the page rather than fetched here, and the connection list is re-read whenever
// it is written -- otherwise the picker would keep describing the state the page was
// opened in, and contradict the notice sitting next to it.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2 } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    buildDefaultModelChoices,
    choiceToSelection,
    fetchDefaultModel,
    fetchModelConnections,
    findChoiceIndex,
    groupChoicesByConnection,
    hasDefaultModel,
    saveDefaultModel,
    toDefaultModelSelection,
    type DefaultModelChoice,
    type DefaultModelSelection,
} from '../../lib/modelConnections';
import { useModelConnectionsStore } from '../../stores/modelConnectionsStore';
import { toast } from '../../stores/toastStore';

const selectClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

const NO_DEFAULT = '';

function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}

/** How a choice reads in the list: the model, then the deployment when they differ. */
function choiceLabel(choice: DefaultModelChoice): string {
    if (choice.deploymentName && choice.deploymentName !== choice.modelLabel) {
        return `${choice.modelLabel} (${choice.deploymentName})`;
    }
    return choice.modelLabel;
}

interface ChatDefaultModelProps {
    /**
     * Whether chat is stored as using connections. Taken from the page's saved settings
     * rather than this component's own fetch: the switch that controls it lives in the
     * section above, so a value read once at mount would still say "off" after it had
     * been turned on and the notice beside it had already said so.
     */
    multiEndpointEnabled: boolean;
    help?: string;
}

export function ChatDefaultModel({ multiEndpointEnabled, help }: ChatDefaultModelProps) {
    const [choices, setChoices] = useState<DefaultModelChoice[]>([]);
    const [selection, setSelection] = useState<DefaultModelSelection | null>(null);
    const [clearedReason, setClearedReason] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    // Bumped by every write to the connection list. Adding a connection or enabling a
    // model changes what may be offered here, and deleting one makes the server clear a
    // default that named it.
    const connectionsRevision = useModelConnectionsStore((state) => state.revision);

    const load = useCallback(async (signal?: AbortSignal) => {
        try {
            const [connections, current] = await Promise.all([
                fetchModelConnections(signal),
                fetchDefaultModel(signal),
            ]);
            setChoices(buildDefaultModelChoices(connections.endpoints ?? []));
            setSelection(toDefaultModelSelection(current.selection));
            setClearedReason(current.reason ?? null);
            setError(null);
        } catch (loadError) {
            // An abort is this component going away, not a failure worth reporting.
            if (signal?.aborted) {
                return;
            }
            setError(errorMessage(loadError, 'The default model could not be loaded.'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
        // Enabling connections seeds the list server-side, so the reload is what surfaces
        // the connection an administrator did not add by hand.
    }, [load, connectionsRevision, multiEndpointEnabled]);

    const groups = useMemo(() => groupChoicesByConnection(choices), [choices]);
    const selectedIndex = useMemo(
        () => (selection ? findChoiceIndex(choices, selection) : -1),
        [choices, selection],
    );

    // A stored default whose model is no longer offered would otherwise show as "None",
    // which reads as "never set" rather than "the thing it named went away".
    const danglingSelection = Boolean(
        selection && hasDefaultModel(selection) && selectedIndex < 0,
    );

    const onChange = async (raw: string) => {
        const previous = selection;
        const choice = raw === NO_DEFAULT ? null : (choices[Number(raw)] ?? null);
        const next = choiceToSelection(choice);

        setSelection(next);
        setSaving(true);
        setError(null);
        try {
            const response = await saveDefaultModel(next);
            setSelection(toDefaultModelSelection(response.selection));
            setClearedReason(null);
            toast.success(choice ? `Default model set to ${choice.modelLabel}.` : 'Default model cleared.');
        } catch (saveError) {
            setSelection(previous);
            setError(errorMessage(saveError, 'The default model could not be saved.'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="py-3">
            <label
                htmlFor="chat-default-model"
                className="mb-1.5 block text-sm font-medium text-text-1"
            >
                Default model
            </label>

            {loading ? (
                <p className="flex items-center gap-2 py-2 text-xs text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading models…
                </p>
            ) : (
                <>
                    <select
                        id="chat-default-model"
                        className={selectClass}
                        value={selectedIndex >= 0 ? String(selectedIndex) : NO_DEFAULT}
                        disabled={saving || !multiEndpointEnabled || choices.length === 0}
                        onChange={(event) => void onChange(event.target.value)}
                    >
                        <option value={NO_DEFAULT}>No default model</option>
                        {groups.map((group) => (
                            <optgroup key={group.connectionName} label={group.connectionName}>
                                {group.items.map(({ choice, index }) => (
                                    <option
                                        key={`${choice.endpointId}\u0000${choice.modelId}`}
                                        value={String(index)}
                                    >
                                        {choiceLabel(choice)}
                                    </option>
                                ))}
                            </optgroup>
                        ))}
                    </select>

                    {saving ? (
                        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-text-3">
                            <Loader2 size={12} className="animate-spin" />
                            Saving…
                        </p>
                    ) : null}
                </>
            )}

            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}

            {!loading && !multiEndpointEnabled ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">
                    Chat is on the classic single endpoint, so this has nothing to choose from.
                    The default model applies to connections only.
                </p>
            ) : null}

            {!loading && multiEndpointEnabled && choices.length === 0 ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">
                    No connection currently publishes an enabled model. Add a connection, or
                    enable one of the models on an existing one.
                </p>
            ) : null}

            {clearedReason ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {clearedReason}
                </p>
            ) : null}

            {danglingSelection && !clearedReason ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    The saved default is not in this list any more. Pick a replacement, or it
                    will be cleared the next time a connection is saved.
                </p>
            ) : null}

            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}
