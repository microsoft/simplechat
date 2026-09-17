// CapabilityModelPicker.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import {
    capabilityDescription,
    CAPABILITY_DETAILS,
    embeddingPolicyDescription,
    canGenerateImage,
    fetchCapabilityModels,
    saveCapabilityModel,
    testCapabilityModel,
    type CapabilityModelsResponse,
} from '../../lib/capabilityModels';
import {
    choiceToSelection,
    findChoiceIndex,
    groupChoicesByConnection,
    hasDefaultModel,
    type ImplementedCapability,
} from '../../lib/modelConnections';
import { useModelConnectionsStore } from '../../stores/modelConnectionsStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';

export function CapabilityModelPicker({
    capability,
    featureEnabled,
    help,
}: {
    capability: ImplementedCapability;
    featureEnabled: boolean;
    help?: string;
}) {
    const image = capability === 'image_generation';
    const embedding = capability === 'embeddings';
    const { label, id, modelKind, independence } = CAPABILITY_DETAILS[capability];
    const revision = useModelConnectionsStore((state) => state.revision);
    const [data, setData] = useState<CapabilityModelsResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [testResult, setTestResult] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [reload, setReload] = useState(0);
    const requestId = useRef(0);

    useEffect(() => {
        const controller = new AbortController();
        const request = ++requestId.current;
        setLoading(true);
        setTestResult(null);
        void fetchCapabilityModels(capability, controller.signal).then((response) => {
            if (!controller.signal.aborted && request === requestId.current) {
                setData(response);
                setError(null);
                if (image) {
                    void useBootstrapStore.getState().refresh();
                }
            }
        }).catch((loadError: unknown) => {
            if (!controller.signal.aborted && request === requestId.current) {
                setError(loadError instanceof Error ? loadError.message : 'Models could not be loaded.');
            }
        }).finally(() => {
            if (!controller.signal.aborted && request === requestId.current) {
                setLoading(false);
            }
        });
        return () => controller.abort();
    }, [capability, featureEnabled, revision, reload]);

    const groups = useMemo(() => groupChoicesByConnection(data?.choices ?? []), [data]);
    const selectedIndex = data ? findChoiceIndex(data.choices, data.selection) : -1;
    const dangling = Boolean(data && hasDefaultModel(data.selection) && selectedIndex < 0);
    const selectedChoice = data?.choices[selectedIndex];
    const selectedImageUnavailable = image && Boolean(selectedChoice) && !canGenerateImage(selectedChoice?.capability);
    const busy = loading || saving || testing;
    const enabled = data?.enabled ?? featureEnabled;
    const migrationFailed = data?.migration?.status === 'error' || data?.migration?.status === 'failed';

    const onChange = async (raw: string) => {
        if (!data || busy) {
            return;
        }
        const choice = raw === '' ? null : data.choices[Number(raw)];
        if (raw !== '' && !choice) {
            return;
        }
        if (image && choice && !canGenerateImage(choice.capability)) {
            return;
        }
        const previous = data;
        const next = choiceToSelection(choice ?? null);
        const request = ++requestId.current;
        setData({ ...data, selection: next });
        setSaving(true);
        setError(null);
        setTestResult(null);
        try {
            const response = await saveCapabilityModel(capability, next);
            if (request === requestId.current) {
                setData(response);
                if (image) {
                    void useBootstrapStore.getState().refresh();
                }
                toast.success(choice ? `${label} set to ${choice.modelLabel}.` : `${label} cleared.`);
            }
        } catch (saveError) {
            if (request === requestId.current) {
                setData(previous);
                setError(saveError instanceof Error ? saveError.message : `${label} could not be saved.`);
            }
        } finally {
            setSaving(false);
        }
    };

    const runOperationTest = async () => {
        if (!data || !selectedChoice || busy || !enabled || capability === 'chat' || selectedImageUnavailable) {
            return;
        }
        setTesting(true);
        setError(null);
        setTestResult(null);
        try {
            const response = await testCapabilityModel(capability, data.selection);
            if (response.success !== true) {
                throw new Error(response.error || `The saved ${modelKind} model did not return a valid result.`);
            }
            if (embedding) {
                if (!Number.isSafeInteger(response.dimensions) || Number(response.dimensions) <= 0) {
                    throw new Error('The saved embedding model did not return valid vector dimensions.');
                }
                setTestResult(`The saved embedding model returned ${response.dimensions?.toLocaleString()} dimensions. No vectors were stored and the default was not changed.`);
            } else {
                setTestResult('The saved image model generated an image successfully.');
            }
        } catch (testError) {
            setError(testError instanceof Error ? testError.message : `${label} could not be tested.`);
        } finally {
            setTesting(false);
        }
    };

    return (
        <div className="py-3" data-testid={`capability-picker-${capability}`}>
            <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-text-1">{label}</label>
            <select
                id={id}
                aria-describedby={`${id}-help`}
                className="w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                value={dangling ? 'unavailable' : selectedIndex < 0 ? '' : String(selectedIndex)}
                disabled={busy || !data || (capability === 'chat' && !enabled)}
                onChange={(event) => void onChange(event.target.value)}
            >
                <option value="">{loading ? 'Loading models…' : `No default ${modelKind} model`}</option>
                {dangling ? <option value="unavailable" disabled>Saved model — no longer available</option> : null}
                {groups.map((group) => (
                    <optgroup key={group.endpointId} label={group.connectionName}>
                        {group.items.map(({ choice, index }) => (
                            <option
                                key={JSON.stringify([choice.endpointId, choice.modelId])}
                                value={String(index)}
                                disabled={image && !canGenerateImage(choice.capability)}
                            >
                                {choice.modelLabel}
                                {choice.deploymentName && choice.deploymentName !== choice.modelLabel
                                    ? ` (${choice.deploymentName})` : ''}
                            </option>
                        ))}
                    </optgroup>
                ))}
            </select>
            <p id={`${id}-help`} className="mt-1.5 text-xs leading-relaxed text-text-3">
                {help || 'Choose a model from a saved AI Connection. This default saves immediately.'}
            </p>
            <p className="mt-1.5 text-xs text-text-3">{independence}</p>
            {!enabled && !embedding ? (
                <p className="mt-1.5 text-xs text-text-3">
                    {image
                        ? 'Image generation is off. You can configure its default without enabling it; save the feature switch before testing.'
                        : 'Chat is using the classic single endpoint. Enable AI Connections for chat to use this default.'}
                </p>
            ) : null}
            {!loading && data && !data.choices.length ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    No saved connection publishes a compatible {modelKind} model.
                    Add or edit a model in AI Connections and save the connection first.
                </p>
            ) : null}
            {selectedChoice ? (
                <>
                    <p className="mt-1.5 text-xs text-text-3">{capabilityDescription(selectedChoice.capability, capability)}</p>
                    {embedding ? (
                        <p className="mt-1.5 text-xs text-text-3">{embeddingPolicyDescription(selectedChoice.embedding_policy)}</p>
                    ) : null}
                </>
            ) : null}
            {embedding ? (
                <p role="note" className="mt-2 rounded-lg bg-warn-soft p-3 text-xs text-warn">
                    Matching dimensions do not make two models compatible. A model, revision, dimension or preprocessing change can require a controlled rebuild of search and fact-memory vectors. Saving never rebuilds, deletes or re-embeds existing data automatically.
                </p>
            ) : null}
            {embedding && data?.compatibility?.message ? (
                <p role="status" className="mt-2 rounded-lg bg-surface-2 p-3 text-xs text-text-2">
                    {data.compatibility.message}
                </p>
            ) : null}
            {image && selectedChoice ? (
                <div className="mt-2 space-y-1 break-words text-xs text-text-3" data-testid="image-model-capability">
                    <p>
                        {selectedChoice.capability.model_name || selectedChoice.modelLabel}
                        {' · '}{selectedChoice.capability.provider_label || 'Provider not specified'}
                        {' · '}{selectedChoice.capability.cloud_label || 'Endpoint cloud unknown'}
                    </p>
                    {selectedChoice.capability.publisher ? <p>Publisher: {selectedChoice.capability.publisher}</p> : null}
                    {selectedChoice.capability.lifecycle ? <p>Lifecycle: {selectedChoice.capability.lifecycle}</p> : null}
                    <p>
                        {selectedImageUnavailable
                            ? 'Image operations are unavailable. Choose a compatible model or refresh its capability metadata.'
                            : selectedChoice.capability.mode === 'masked'
                              ? 'Source-image editing with optional region masks, and whole-image regeneration.'
                              : selectedChoice.capability.mode === 'edit'
                                ? 'Source-image editing without region masks, and whole-image regeneration.'
                                : 'Prompt-only generation and whole-image regeneration; no source-image editing.'}
                    </p>
                    {selectedChoice.capability.reason ? <p>{selectedChoice.capability.reason}</p> : null}
                    {selectedChoice.capability.sizes?.length ? <p>Sizes: {selectedChoice.capability.sizes.join(', ')}</p> : null}
                    {selectedChoice.capability.qualities?.length ? <p>Quality: {selectedChoice.capability.qualities.join(', ')}</p> : null}
                    {selectedChoice.capability.backgrounds?.length ? <p>Background: {selectedChoice.capability.backgrounds.join(', ')}</p> : null}
                    {selectedChoice.capability.availability === 'unknown' ? (
                        <p role="status" className="text-warn">
                            Availability for this configured endpoint is not documented or is unknown.
                            This is not a confirmation of provider support.
                            {selectedChoice.capability.availability_reason ? ` ${selectedChoice.capability.availability_reason}` : ''}
                        </p>
                    ) : selectedChoice.capability.availability_reason ? (
                        <p role="status">{selectedChoice.capability.availability_reason}</p>
                    ) : null}
                </div>
            ) : null}
            {data?.reason || dangling ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    {data?.reason || 'The saved default is no longer available. Choose a replacement or clear it; another model will not be selected automatically.'}
                </p>
            ) : null}
            {capability !== 'chat' && data?.migration?.message ? (
                <p role="status" className={`mt-2 rounded-lg p-3 text-xs ${migrationFailed ? 'bg-warn-soft text-warn' : 'bg-surface-2 text-text-2'}`}>
                    {data.migration.message}
                    {migrationFailed ? ` Existing legacy settings have been retained. Review AI Connections. Classic ${embedding ? 'Embeddings' : 'Image Generation'} recovery settings are available only until a shared binding is saved.` : ''}
                </p>
            ) : null}
            {image && enabled && !loading && data && !hasDefaultModel(data.selection) && !data.reason ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    Select a default image model before generating images. Clearing this selection does not restore the legacy model.
                </p>
            ) : null}
            {embedding && !loading && data && !hasDefaultModel(data.selection) && !data.reason ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    Select a default embedding model before indexing or searching documents. Clearing a shared default does not restore legacy settings or erase vector-space compatibility history.
                </p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-2">
                <GlassButton type="button" variant="subtle" size="sm" disabled={busy} onClick={() => setReload((value) => value + 1)}>
                    <RefreshCw size={13} /> Refresh choices
                </GlassButton>
                {capability !== 'chat' ? (
                    <GlassButton type="button" variant="subtle" size="sm" disabled={busy || !selectedChoice || !enabled || selectedImageUnavailable} onClick={() => void runOperationTest()}>
                        {testing ? <Loader2 size={13} className="animate-spin" /> : null}
                        {embedding ? 'Test embeddings' : 'Test image generation'}
                    </GlassButton>
                ) : null}
                {saving ? <span role="status" className="text-xs text-text-3">Saving…</span> : null}
            </div>
            {image ? <p className="mt-1.5 text-xs text-text-3">The image test uses the saved model and may incur generation costs. A connection check alone does not test image inference.</p> : null}
            {embedding ? <p className="mt-1.5 text-xs text-text-3">The embedding test uses the saved model and may incur inference costs. It checks returned vector dimensions without storing vectors or changing this default. Success does not override vector-store compatibility checks.</p> : null}
            {testResult ? <p role="status" className="mt-1.5 text-xs text-ok">{testResult}</p> : null}
            {error ? (
                <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />{error}
                </p>
            ) : null}
        </div>
    );
}
