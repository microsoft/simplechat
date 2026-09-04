// ModelSelectionPicker.tsx
// Chooses the single deployment an embedding or image-generation route uses.
//
// Unlike the chat connections, these routes have no list to draw from: there is one Azure
// OpenAI resource, and the only way to learn what it has deployed is to ask it. So the
// list here is a cache of the last answer, and it is refreshed on demand rather than on
// every page load — asking Azure Resource Manager each time would make opening Admin
// Settings fail whenever discovery is slow or the credentials are mid-rotation.
//
// Two consequences the component has to make visible, because neither is an error:
//
//   - The list can be empty simply because nobody has fetched yet. That reads exactly
//     like "the resource has nothing deployed" unless it is said out loud.
//   - Discovery reads the *saved* endpoint, subscription id and resource group, so
//     fetching before saving asks the old resource. The classic page carries the same
//     caveat in fine print; here it is stated next to the button that trips over it.
//
// The choice saves on its own, like the connection list and the default chat model,
// because its stored shape is a dict that the settings PATCH refuses.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    applyDiscoveredModels,
    deploymentLabel,
    discoverCatalogModels,
    fetchModelCatalog,
    findDeploymentIndex,
    isDanglingSelection,
    saveModelCatalog,
    toModelDeployment,
    toModelDeployments,
    type ModelCatalogKind,
    type ModelDeployment,
} from '../../lib/modelSelection';
import { GlassButton } from '../ui/primitives';
import { toast } from '../../stores/toastStore';

const selectClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

const NO_SELECTION = '';

const KIND_COPY: Record<ModelCatalogKind, { noun: string; empty: string }> = {
    embedding: {
        noun: 'embedding deployment',
        empty: 'No embedding deployments have been fetched yet.',
    },
    image: {
        noun: 'image deployment',
        empty: 'No image deployments have been fetched yet.',
    },
};

function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}

export function ModelSelectionPicker({
    kind,
    label,
    help,
    unsavedConnectionEdits = false,
}: {
    kind: ModelCatalogKind;
    label: string;
    help?: string;
    /** True while an unsaved edit to the endpoint, subscription or resource group exists. */
    unsavedConnectionEdits?: boolean;
}) {
    const [models, setModels] = useState<ModelDeployment[]>([]);
    const [selected, setSelected] = useState<ModelDeployment | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [discovering, setDiscovering] = useState(false);

    const copy = KIND_COPY[kind];
    const id = `admin-model-selection-${kind}`;

    const load = useCallback(
        async (signal?: AbortSignal) => {
            try {
                const catalog = await fetchModelCatalog(kind, signal);
                setModels(toModelDeployments(catalog.models));
                setSelected(toModelDeployment(catalog.selected));
                setError(null);
            } catch (loadError) {
                setError(errorMessage(loadError, 'The deployment list could not be loaded.'));
            } finally {
                setLoading(false);
            }
        },
        [kind],
    );

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
    }, [load]);

    const persist = async (
        nextModels: ModelDeployment[],
        nextSelected: ModelDeployment | null,
    ) => {
        const previous = { models, selected };
        setModels(nextModels);
        setSelected(nextSelected);
        setSaving(true);
        setError(null);
        try {
            const saved = await saveModelCatalog(kind, {
                models: nextModels,
                selected: nextSelected,
            });
            setModels(toModelDeployments(saved.models));
            setSelected(toModelDeployment(saved.selected));
            return true;
        } catch (saveError) {
            setModels(previous.models);
            setSelected(previous.selected);
            setError(errorMessage(saveError, 'The deployment could not be saved.'));
            return false;
        } finally {
            setSaving(false);
        }
    };

    const onChange = async (raw: string) => {
        const choice = raw === NO_SELECTION ? null : (models[Number(raw)] ?? null);
        setNotice(null);
        if (await persist(models, choice)) {
            toast.success(
                choice
                    ? `${label} set to ${choice.deploymentName}.`
                    : `${label} cleared.`,
            );
        }
    };

    const onDiscover = async () => {
        setDiscovering(true);
        setError(null);
        setNotice(null);
        try {
            const response = await discoverCatalogModels(kind);
            const discovered = toModelDeployments(response.models);
            if (discovered.length === 0) {
                setNotice(
                    `The resource reported no ${copy.noun}s. Check that the endpoint, ` +
                        'subscription id and resource group name the resource the deployment ' +
                        'lives in, and that they have been saved.',
                );
                return;
            }

            const result = applyDiscoveredModels(discovered, selected);
            if (await persist(result.models, result.selected)) {
                setNotice(
                    result.droppedSelection
                        ? `${selected?.deploymentName} is no longer deployed, so the ` +
                              'selection was cleared. Choose a replacement.'
                        : `${discovered.length} ${copy.noun}${discovered.length === 1 ? '' : 's'} found.`,
                );
            }
        } catch (discoveryError) {
            setError(
                errorMessage(discoveryError, 'The deployment list could not be fetched.'),
            );
        } finally {
            setDiscovering(false);
        }
    };

    const selectedIndex = findDeploymentIndex(models, selected);
    const dangling = isDanglingSelection(models, selected);
    const busy = saving || discovering;

    return (
        <div className="py-3">
            <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-text-1">
                {label}
            </label>

            {loading ? (
                <p className="flex items-center gap-2 py-2 text-xs text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading deployments…
                </p>
            ) : (
                <>
                    <select
                        id={id}
                        className={selectClass}
                        value={selectedIndex >= 0 ? String(selectedIndex) : NO_SELECTION}
                        disabled={busy || models.length === 0}
                        onChange={(event) => void onChange(event.target.value)}
                    >
                        <option value={NO_SELECTION}>No deployment selected</option>
                        {models.map((deployment, index) => (
                            <option key={deployment.deploymentName} value={String(index)}>
                                {deploymentLabel(deployment)}
                            </option>
                        ))}
                    </select>

                    <div className="mt-2 flex items-center gap-2">
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            disabled={busy || unsavedConnectionEdits}
                            onClick={() => void onDiscover()}
                        >
                            {discovering ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <RefreshCw size={14} />
                            )}
                            Fetch deployments
                        </GlassButton>
                        {saving ? (
                            <span className="flex items-center gap-1.5 text-xs text-text-3">
                                <Loader2 size={12} className="animate-spin" />
                                Saving…
                            </span>
                        ) : null}
                    </div>
                </>
            )}

            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}

            {unsavedConnectionEdits ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    Fetching reads the saved endpoint, subscription id and resource group,
                    so it would list the previous resource. Save this section first.
                </p>
            ) : (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">
                    Fetching reads the saved endpoint, subscription id and resource group.
                </p>
            )}

            {!loading && models.length === 0 ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{copy.empty}</p>
            ) : null}

            {dangling ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    The saved deployment {selected?.deploymentName} is not in this list. Fetch
                    the deployments again, or choose a replacement.
                </p>
            ) : null}

            {notice ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-2">{notice}</p>
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
