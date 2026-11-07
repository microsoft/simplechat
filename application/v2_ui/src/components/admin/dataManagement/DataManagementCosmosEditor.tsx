// DataManagementCosmosEditor.tsx
// The editor keeps its unlocked state and document draft in the shared store so risky
// Cosmos work survives card unmounts but is still discarded when the Admin page closes.

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { DatabaseZap, FileJson, Loader2, Lock, RotateCw, Save, Search, Unlock } from 'lucide-react';
import { ApiError } from '../../../lib/apiClient';
import {
    COSMOS_EDITOR_MAX_PAGE_SIZE,
    COSMOS_EDITOR_SAVE_PHRASE,
    acknowledgeCosmosDanger,
    errorMessage,
    listCosmosContainers,
    openCosmosDocument,
    queryCosmos,
    saveCosmosDocument,
    type CosmosContainer,
    type CosmosDocumentResult,
    type CosmosQueryItem,
} from '../../../lib/dataManagement';
import {
    checkCosmosEdit,
    formatCosmosDocument,
    formatDetailValue,
    formatNumber,
    summarizeCosmosChanges,
    validateCosmosQuery,
} from '../../../lib/dataManagementLogic';
import {
    currentEpoch,
    isCurrentEpoch,
    selectCosmosEditorDirty,
    useDataManagementStore,
    type CosmosOpenDocument,
} from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { Modal } from '../../ui/Modal';
import { GlassButton } from '../../ui/primitives';
import { inputClass } from '../fields';
import {
    DmEmpty,
    DmIntro,
    DmMetricGrid,
    DmNotice,
    DmPhraseField,
    DmWorkbench,
    isStacked,
    type DmCardProps,
} from './DmShared';

type BusyAction = 'unlock' | 'containers' | 'query' | 'next' | 'open' | 'reload' | 'save' | null;

interface PendingConfirm {
    title: string;
    description: string;
    confirmLabel: string;
    onConfirm: () => void;
}

function labelForContainer(container: CosmosContainer): string {
    const name = container.display_name || container.name || container.id;
    return `${name} (${container.partition_key_path || 'no partition key path'})${container.editable === false ? ' (read-only)' : ''}`;
}

function categoryForContainer(container: CosmosContainer): string {
    return container.category || 'Other';
}

function groupedContainers(
    containers: CosmosContainer[],
): Array<{ category: string; containers: CosmosContainer[] }> {
    const groups = new Map<string, CosmosContainer[]>();
    for (const container of [...containers].sort((left, right) => {
        const category = categoryForContainer(left).localeCompare(categoryForContainer(right));
        return category || labelForContainer(left).localeCompare(labelForContainer(right));
    })) {
        const category = categoryForContainer(container);
        groups.set(category, [...(groups.get(category) ?? []), container]);
    }
    return [...groups.entries()].map(([category, items]) => ({ category, containers: items }));
}

function resultPreview(item: CosmosQueryItem): string {
    const preview = item.preview?.trim() || 'No preview fields available.';
    return preview.length > 120 ? `${preview.slice(0, 117)}…` : preview;
}

function documentFromResult(
    result: CosmosDocumentResult,
    fallback: CosmosOpenDocument | null,
): CosmosOpenDocument {
    const document =
        result.document && typeof result.document === 'object' && !Array.isArray(result.document)
            ? result.document
            : {};
    return {
        container: result.container?.name || fallback?.container || '',
        id: result.id,
        partitionKey: result.partition_key,
        partitionKeyPath: result.container?.partition_key_path || fallback?.partitionKeyPath || '',
        etag: result.etag ?? null,
        original: document,
        text: formatCosmosDocument(document),
        editable: result.container?.editable ?? fallback?.editable ?? true,
    };
}

function queryStatus(
    result: { items: CosmosQueryItem[]; query?: { mode?: 'empty' | 'custom' }; has_more?: boolean },
    total: number,
): string {
    const source = result.query?.mode === 'empty' ? 'a browse' : 'a custom SELECT query';
    return `${formatNumber(total)} loaded from ${source}. ${result.has_more ? 'More results are available.' : 'No more results.'}`;
}

function serverSummary(result: CosmosDocumentResult): string | null {
    if (!result.change_summary) return null;
    const count = formatNumber(
        result.change_summary.changed_count ?? result.change_summary.changed_paths?.length ?? 0,
    );
    return `Server recorded ${count} changed path${count === '1' ? '' : 's'} (${formatNumber(result.change_summary.added_count ?? 0)} added, ${formatNumber(result.change_summary.removed_count ?? 0)} removed, ${formatNumber(result.change_summary.updated_count ?? 0)} updated).`;
}

export function DataManagementCosmosEditor({ help, disabled }: DmCardProps) {
    const baseId = useId();
    const cosmos = useDataManagementStore((state) => state.cosmos);
    const dirty = useDataManagementStore(selectCosmosEditorDirty);
    const [dangerOpen, setDangerOpen] = useState(false);
    const [dangerAccepted, setDangerAccepted] = useState(false);
    const [busy, setBusy] = useState<BusyAction>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
    const [saveOpen, setSaveOpen] = useState(false);
    const [savePhrase, setSavePhrase] = useState('');
    const [saveError, setSaveError] = useState<string | null>(null);
    const [lastSaveSummary, setLastSaveSummary] = useState<string | null>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const detailRef = useRef<HTMLDivElement>(null);

    const selectedContainer = useMemo(
        () =>
            cosmos.containers.find(
                (container) => container.name === cosmos.container || container.id === cosmos.container,
            ) ?? null,
        [cosmos.container, cosmos.containers],
    );
    const containerGroups = useMemo(() => groupedContainers(cosmos.containers), [cosmos.containers]);
    const queryError = validateCosmosQuery(cosmos.query);
    const editCheck = cosmos.document
        ? checkCosmosEdit(cosmos.document.text, {
              id: cosmos.document.id,
              partitionKey: cosmos.document.partitionKey,
              partitionKeyPath: cosmos.document.partitionKeyPath,
          })
        : null;
    const parsedDocument = editCheck?.ok ? editCheck.document : null;
    const localSummary =
        parsedDocument && cosmos.document
            ? summarizeCosmosChanges(cosmos.document.original, parsedDocument)
            : null;
    const controlsDisabled = Boolean(disabled || busy);
    const canRunQuery = cosmos.unlocked && Boolean(cosmos.container) && !queryError && !controlsDisabled;
    const canSave = Boolean(cosmos.document?.editable && editCheck?.ok && !controlsDisabled);

    useEffect(() => {
        if (!dirty) return;
        const onBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    }, [dirty]);

    const askBeforeDiscard = useCallback(
        (action: () => void, title: string, description: string, confirmLabel: string) => {
            if (!dirty) {
                action();
                return;
            }
            setPendingConfirm({ title, description, confirmLabel, onConfirm: action });
        },
        [dirty],
    );

    const loadContainers = useCallback(async () => {
        const token = currentEpoch();
        setBusy('containers');
        setError(null);
        try {
            const containers = await listCosmosContainers();
            if (!isCurrentEpoch(token)) return;
            useDataManagementStore.getState().updateCosmos((current) => ({
                ...current,
                containers,
                container: current.container || containers[0]?.name || '',
            }));
            if (!containers.length) setNotice('No Cosmos DB containers were returned.');
        } catch (failure) {
            if (!isCurrentEpoch(token)) return;
            setError(errorMessage(failure, 'Cosmos DB containers could not be loaded.'));
            useDataManagementStore.getState().updateCosmos({ containers: [], container: '' });
        } finally {
            if (isCurrentEpoch(token)) setBusy(null);
        }
    }, []);

    // The list loads once when the editor is unlocked. A failed or empty load waits for
    // Retry rather than reloading on its own, so an outage is not hammered with requests.

    const unlock = async () => {
        if (!dangerAccepted) return;
        const token = currentEpoch();
        setBusy('unlock');
        setError(null);
        try {
            await useDataManagementStore.getState().trackRequest(acknowledgeCosmosDanger());
            if (!isCurrentEpoch(token)) return;
            useDataManagementStore.getState().updateCosmos({ unlocked: true });
            setDangerOpen(false);
            setDangerAccepted(false);
            setNotice(
                'Cosmos DB editor unlocked for this page session. The acknowledgement was recorded in activity logs.',
            );
            await loadContainers();
        } catch (failure) {
            if (!isCurrentEpoch(token)) return;
            setError(errorMessage(failure, 'Cosmos DB editor could not be unlocked.'));
        } finally {
            if (isCurrentEpoch(token)) setBusy(null);
        }
    };

    const lockEditor = () => {
        askBeforeDiscard(
            () => {
                useDataManagementStore.getState().lockCosmos();
                setNotice('Cosmos DB editor locked.');
                setError(null);
                setLastSaveSummary(null);
            },
            'Discard the open JSON draft?',
            'Locking the editor clears the open document and any unsaved JSON changes in this page session.',
            'Discard and lock',
        );
    };

    const selectContainer = (container: string) => {
        askBeforeDiscard(
            () => {
                useDataManagementStore.getState().updateCosmos({
                    container,
                    results: [],
                    continuationToken: null,
                    queryMode: null,
                    queryStatus: 'No query has run yet.',
                    document: null,
                });
                setLastSaveSummary(null);
            },
            'Discard the open JSON draft?',
            'Changing containers closes the current document and clears unsaved JSON changes.',
            'Discard and change container',
        );
    };

    const runQuery = async (useContinuation: boolean) => {
        if (
            !cosmos.unlocked ||
            !cosmos.container ||
            (useContinuation && !cosmos.continuationToken) ||
            queryError
        )
            return;
        const execute = async () => {
            const token = currentEpoch();
            setBusy(useContinuation ? 'next' : 'query');
            setError(null);
            setLastSaveSummary(null);
            useDataManagementStore.getState().updateCosmos({
                queryStatus: useContinuation ? 'Loading next page…' : 'Running query…',
                ...(useContinuation ? {} : { document: null, results: [], continuationToken: null }),
            });
            try {
                const result = await queryCosmos(
                    cosmos.container,
                    cosmos.query,
                    cosmos.pageSize,
                    useContinuation ? cosmos.continuationToken : null,
                );
                if (!isCurrentEpoch(token)) return;
                const previous = useContinuation ? useDataManagementStore.getState().cosmos.results : [];
                const results = [...previous, ...(result.items ?? [])];
                useDataManagementStore.getState().updateCosmos({
                    results,
                    continuationToken: result.continuation_token ?? null,
                    queryMode: result.query?.mode ?? (cosmos.query.trim() ? 'custom' : 'empty'),
                    queryStatus: queryStatus(result, results.length),
                });
                if (!result.items.length && !useContinuation) setNotice('No documents matched this query.');
            } catch (failure) {
                if (!isCurrentEpoch(token)) return;
                const message = errorMessage(failure, 'Cosmos DB query failed.');
                setError(message);
                useDataManagementStore.getState().updateCosmos({ queryStatus: message });
            } finally {
                if (isCurrentEpoch(token)) setBusy(null);
            }
        };
        if (useContinuation) {
            await execute();
        } else {
            askBeforeDiscard(
                () => {
                    void execute();
                },
                'Discard the open JSON draft?',
                'Running a new query closes the current document and clears unsaved JSON changes.',
                'Discard and run query',
            );
        }
    };

    const openDocument = async (item: CosmosQueryItem) => {
        if (!item.id || item.selectable !== true) return;
        const execute = async () => {
            const token = currentEpoch();
            setBusy('open');
            setError(null);
            setLastSaveSummary(null);
            try {
                const result = await openCosmosDocument(
                    cosmos.container,
                    item.id as string,
                    item.partition_key,
                );
                if (!isCurrentEpoch(token)) return;
                useDataManagementStore
                    .getState()
                    .updateCosmos({ document: documentFromResult(result, null) });
                window.setTimeout(() => {
                    if (isStacked(listRef.current, detailRef.current)) {
                        detailRef.current?.scrollIntoView({ block: 'start' });
                    } else {
                        detailRef.current?.focus({ preventScroll: true });
                    }
                }, 0);
            } catch (failure) {
                if (!isCurrentEpoch(token)) return;
                setError(errorMessage(failure, 'Cosmos DB document could not be opened.'));
                useDataManagementStore.getState().updateCosmos({ document: null });
            } finally {
                if (isCurrentEpoch(token)) setBusy(null);
            }
        };
        askBeforeDiscard(
            () => {
                void execute();
            },
            'Discard the open JSON draft?',
            'Opening another document clears the unsaved JSON changes in the current document.',
            'Discard and open document',
        );
    };

    const reloadDocumentNow = async () => {
        const document = cosmos.document;
        if (!document) return;
        const token = currentEpoch();
        setBusy('reload');
        setError(null);
        setSaveError(null);
        setLastSaveSummary(null);
        try {
            const result = await openCosmosDocument(document.container, document.id, document.partitionKey);
            if (!isCurrentEpoch(token)) return;
            useDataManagementStore
                .getState()
                .updateCosmos({ document: documentFromResult(result, document) });
            setNotice('Document reloaded from Cosmos DB.');
        } catch (failure) {
            if (!isCurrentEpoch(token)) return;
            setError(errorMessage(failure, 'Cosmos DB document could not be reloaded.'));
        } finally {
            if (isCurrentEpoch(token)) setBusy(null);
        }
    };

    const reloadDocument = async () => {
        askBeforeDiscard(
            () => {
                void reloadDocumentNow();
            },
            'Discard unsaved JSON changes?',
            'Reloading reads the current document from Cosmos DB and replaces the JSON in the editor.',
            'Discard and reload',
        );
    };

    const resetChanges = () => {
        const document = cosmos.document;
        if (!document) return;
        useDataManagementStore.getState().updateCosmos({
            document: { ...document, text: formatCosmosDocument(document.original) },
        });
        setSaveError(null);
        setLastSaveSummary(null);
    };

    const saveDocument = async () => {
        const document = cosmos.document;
        if (!document || !parsedDocument || !document.etag) return;
        const token = currentEpoch();
        setBusy('save');
        setSaveError(null);
        try {
            const result = await useDataManagementStore.getState().trackRequest(
                saveCosmosDocument({
                    container: document.container,
                    id: document.id,
                    partitionKey: document.partitionKey,
                    etag: document.etag,
                    document: parsedDocument,
                    confirmationPhrase: savePhrase,
                }),
            );
            if (!isCurrentEpoch(token)) return;
            useDataManagementStore
                .getState()
                .updateCosmos({ document: documentFromResult(result, document) });
            setLastSaveSummary(serverSummary(result));
            setSaveOpen(false);
            toast.success('Cosmos DB document saved. The edit was recorded in activity logs.');
        } catch (failure) {
            if (!isCurrentEpoch(token)) return;
            if (failure instanceof ApiError && failure.status === 409) {
                setSaveError(
                    'This document changed after it was opened. Reload it, reapply the edit, then save again.',
                );
            } else {
                setSaveError(errorMessage(failure, 'Cosmos DB document could not be saved.'));
            }
        } finally {
            setSavePhrase('');
            if (isCurrentEpoch(token)) setBusy(null);
        }
    };

    const handleListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        const buttons = [
            ...(listRef.current?.querySelectorAll<HTMLButtonElement>('button[data-result-row="true"]') ?? []),
        ].filter((button) => !button.disabled);
        if (!buttons.length) return;
        const current =
            document.activeElement instanceof HTMLButtonElement
                ? buttons.indexOf(document.activeElement)
                : -1;
        const next =
            event.key === 'ArrowDown'
                ? (current + 1) % buttons.length
                : current <= 0
                  ? buttons.length - 1
                  : current - 1;
        event.preventDefault();
        buttons[next]?.focus();
    };

    return (
        <div data-testid="dm-cosmos-editor" className="@container min-w-0 py-1">
            <DmIntro>
                {help ||
                    'Query a known SimpleChat Cosmos DB container, inspect one document, and save guarded JSON repairs with ETag protection.'}
            </DmIntro>
            <div className="space-y-3">
                <DmNotice tone="danger" title="Production data editor">
                    This tool changes production Cosmos DB documents directly. Use it only for targeted repair
                    or investigation after the impact is understood.
                </DmNotice>
                {notice ? (
                    <DmNotice tone="info" role="status">
                        {notice}
                    </DmNotice>
                ) : null}
                {error ? (
                    <DmNotice tone="danger" role="alert">
                        {error}
                    </DmNotice>
                ) : null}
                {!cosmos.unlocked ? (
                    <section className="rounded-xl border border-edge-strong bg-surface-solid p-4">
                        <div className="max-w-[72ch] space-y-2 text-sm leading-relaxed text-text-2">
                            <p className="font-semibold text-text-1">The Cosmos DB JSON editor is locked.</p>
                            <p>
                                Unlock it only after you know which container and document you need. Unlocking
                                records an acknowledgement in activity logs and enables live queries for this
                                page session.
                            </p>
                        </div>
                        <GlassButton
                            type="button"
                            variant="danger"
                            className="mt-4"
                            disabled={controlsDisabled}
                            onClick={() => {
                                setDangerAccepted(false);
                                setDangerOpen(true);
                            }}
                        >
                            <Unlock size={16} aria-hidden="true" />
                            Unlock editor
                        </GlassButton>
                    </section>
                ) : (
                    <section className="space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm text-text-2">
                                Editor unlocked for this page session. Queries and saves are recorded by the
                                server.
                            </p>
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                disabled={controlsDisabled}
                                onClick={lockEditor}
                            >
                                <Lock size={14} aria-hidden="true" />
                                Lock editor
                            </GlassButton>
                        </div>
                        {!cosmos.containers.length && busy !== 'containers' ? (
                            <DmNotice
                                tone="warning"
                                action={
                                    <GlassButton
                                        type="button"
                                        variant="subtle"
                                        size="sm"
                                        disabled={controlsDisabled}
                                        onClick={() => void loadContainers()}
                                    >
                                        <RotateCw size={14} aria-hidden="true" />
                                        Load containers
                                    </GlassButton>
                                }
                            >
                                The container list is not loaded.
                            </DmNotice>
                        ) : null}
                        <fieldset
                            disabled={controlsDisabled}
                            className="grid min-w-0 gap-3 rounded-xl border border-edge-strong bg-surface-solid p-3 @2xl:grid-cols-[minmax(14rem,1.1fr)_8rem_minmax(18rem,2fr)]"
                        >
                            <div className="min-w-0">
                                <label
                                    htmlFor={`${baseId}-container`}
                                    className="text-xs font-medium text-text-2"
                                >
                                    Container
                                </label>
                                <select
                                    id={`${baseId}-container`}
                                    className={clsx(inputClass, 'mt-1 min-w-0')}
                                    value={cosmos.container}
                                    onChange={(event) => selectContainer(event.target.value)}
                                >
                                    <option value="">Choose a container</option>
                                    {containerGroups.map((group) => (
                                        <optgroup key={group.category} label={group.category}>
                                            {group.containers.map((container) => (
                                                <option key={container.name} value={container.name}>
                                                    {labelForContainer(container)}
                                                </option>
                                            ))}
                                        </optgroup>
                                    ))}
                                </select>
                                <p className="mt-1 text-xs text-text-3">
                                    {selectedContainer
                                        ? `${categoryForContainer(selectedContainer)} · ${selectedContainer.partition_key_path || 'No partition key path'}`
                                        : 'Category · partition key'}
                                </p>
                            </div>
                            <div className="min-w-0">
                                <label
                                    htmlFor={`${baseId}-page-size`}
                                    className="text-xs font-medium text-text-2"
                                >
                                    Page size
                                </label>
                                <input
                                    id={`${baseId}-page-size`}
                                    type="number"
                                    min={1}
                                    max={COSMOS_EDITOR_MAX_PAGE_SIZE}
                                    className={clsx(inputClass, 'mt-1 min-w-0')}
                                    value={cosmos.pageSize}
                                    onChange={(event) => {
                                        const next = Math.max(
                                            1,
                                            Math.min(
                                                COSMOS_EDITOR_MAX_PAGE_SIZE,
                                                Number.parseInt(event.target.value, 10) ||
                                                    COSMOS_EDITOR_MAX_PAGE_SIZE,
                                            ),
                                        );
                                        // A continuation token belongs to the query and page size that produced it.
                                        useDataManagementStore
                                            .getState()
                                            .updateCosmos({ pageSize: next, continuationToken: null });
                                    }}
                                />
                                <p className="mt-1 text-xs text-text-3">
                                    1 to {COSMOS_EDITOR_MAX_PAGE_SIZE}.
                                </p>
                            </div>
                            <div className="min-w-0">
                                <label
                                    htmlFor={`${baseId}-query`}
                                    className="text-xs font-medium text-text-2"
                                >
                                    SELECT query
                                </label>
                                <textarea
                                    id={`${baseId}-query`}
                                    rows={4}
                                    spellCheck={false}
                                    className={clsx(
                                        inputClass,
                                        'mt-1 min-h-24 resize-y font-mono text-xs leading-relaxed',
                                    )}
                                    placeholder="Leave empty to browse the first 100 documents. Custom queries must start with SELECT."
                                    value={cosmos.query}
                                    onChange={(event) =>
                                        useDataManagementStore.getState().updateCosmos({
                                            query: event.target.value,
                                            continuationToken: null,
                                        })
                                    }
                                />
                                <p
                                    className={clsx(
                                        'mt-1 text-xs',
                                        queryError ? 'text-danger' : 'text-text-3',
                                    )}
                                    role={queryError ? 'alert' : undefined}
                                >
                                    {queryError ||
                                        'Browsing returns at most the first 100 documents. Only custom SELECT queries can page further.'}
                                </p>
                            </div>
                        </fieldset>
                        <div className="flex flex-wrap items-center gap-2">
                            <GlassButton
                                type="button"
                                variant="primary"
                                disabled={!canRunQuery}
                                onClick={() => void runQuery(false)}
                            >
                                {busy === 'query' ? (
                                    <Loader2 size={16} aria-hidden="true" className="animate-spin" />
                                ) : (
                                    <Search size={16} aria-hidden="true" />
                                )}
                                Run query
                            </GlassButton>
                            {cosmos.continuationToken ? (
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    disabled={controlsDisabled}
                                    onClick={() => void runQuery(true)}
                                >
                                    {busy === 'next' ? (
                                        <Loader2 size={16} aria-hidden="true" className="animate-spin" />
                                    ) : null}
                                    Next page
                                </GlassButton>
                            ) : null}
                            <span className="text-xs text-text-3" role="status" aria-live="polite">
                                {cosmos.queryStatus || 'No query has run yet.'}
                            </span>
                        </div>
                        <DmWorkbench
                            listLabel="Query results"
                            detailRef={detailRef}
                            list={
                                <div ref={listRef} className="min-w-0" onKeyDown={handleListKeyDown}>
                                    {cosmos.results.length ? (
                                        <ul
                                            className="divide-y divide-edge"
                                            data-testid="dm-cosmos-editor-results"
                                        >
                                            {cosmos.results.map((item, index) => (
                                                <li key={`${item.id ?? 'projection'}-${index}`}>
                                                    <button
                                                        type="button"
                                                        data-result-row="true"
                                                        disabled={
                                                            item.selectable !== true || controlsDisabled
                                                        }
                                                        className={clsx(
                                                            'flex w-full min-w-0 gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface-2 focus:bg-surface-2 focus:outline-none',
                                                            item.selectable !== true &&
                                                                'cursor-not-allowed opacity-60',
                                                        )}
                                                        onClick={() => void openDocument(item)}
                                                    >
                                                        <span className="mt-0.5 inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full border border-edge bg-surface-2 px-1 text-xs font-semibold text-text-2">
                                                            {formatNumber(index + 1)}
                                                        </span>
                                                        <span className="min-w-0 flex-1">
                                                            <span className="block break-all text-sm font-semibold text-text-1">
                                                                {item.id || 'Projection without an id'}
                                                            </span>
                                                            <span className="mt-0.5 block break-all text-xs text-text-3">
                                                                {item.partition_key !== null &&
                                                                item.partition_key !== undefined
                                                                    ? `Partition key: ${formatDetailValue(item.partition_key)}`
                                                                    : 'No partition key in this projection'}
                                                            </span>
                                                            <span className="mt-1 block text-xs leading-relaxed text-text-3">
                                                                {resultPreview(item)}
                                                            </span>
                                                        </span>
                                                    </button>
                                                </li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <DmEmpty title="Run a query to list documents.">
                                            Empty browse lists the first 100 summaries; SELECT queries can
                                            continue when Cosmos returns a token.
                                        </DmEmpty>
                                    )}
                                </div>
                            }
                            detail={
                                <div
                                    tabIndex={-1}
                                    className="min-h-full min-w-0 p-3 outline-none"
                                    data-testid="dm-cosmos-editor-document"
                                >
                                    {cosmos.document ? (
                                        <div className="space-y-3">
                                            <div className="flex flex-wrap items-start justify-between gap-2">
                                                <div className="min-w-0">
                                                    <h3 className="flex items-center gap-2 text-sm font-semibold text-text-1">
                                                        <FileJson size={16} aria-hidden="true" />
                                                        Document JSON
                                                    </h3>
                                                    <dl className="mt-2 grid gap-1 text-xs text-text-3">
                                                        <div className="min-w-0">
                                                            <dt className="inline font-semibold text-text-2">
                                                                Id:{' '}
                                                            </dt>
                                                            <dd className="inline break-all">
                                                                {cosmos.document.id}
                                                            </dd>
                                                        </div>
                                                        <div className="min-w-0">
                                                            <dt className="inline font-semibold text-text-2">
                                                                Partition key:{' '}
                                                            </dt>
                                                            <dd className="inline break-all">
                                                                {formatDetailValue(
                                                                    cosmos.document.partitionKey,
                                                                )}
                                                            </dd>
                                                        </div>
                                                        <div className="min-w-0">
                                                            <dt className="inline font-semibold text-text-2">
                                                                ETag:{' '}
                                                            </dt>
                                                            <dd className="inline break-all">
                                                                {cosmos.document.etag || 'Not returned'}
                                                            </dd>
                                                        </div>
                                                    </dl>
                                                </div>
                                                <div className="flex flex-wrap gap-2">
                                                    {dirty ? (
                                                        <GlassButton
                                                            type="button"
                                                            variant="subtle"
                                                            size="sm"
                                                            disabled={controlsDisabled}
                                                            onClick={resetChanges}
                                                        >
                                                            Reset changes
                                                        </GlassButton>
                                                    ) : null}
                                                    <GlassButton
                                                        type="button"
                                                        variant="subtle"
                                                        size="sm"
                                                        disabled={controlsDisabled}
                                                        onClick={() => void reloadDocument()}
                                                    >
                                                        {busy === 'reload' ? (
                                                            <Loader2
                                                                size={14}
                                                                aria-hidden="true"
                                                                className="animate-spin"
                                                            />
                                                        ) : (
                                                            <RotateCw size={14} aria-hidden="true" />
                                                        )}
                                                        Reload from database
                                                    </GlassButton>
                                                    {cosmos.document.editable ? (
                                                        <GlassButton
                                                            type="button"
                                                            variant="danger"
                                                            size="sm"
                                                            disabled={!canSave}
                                                            onClick={() => {
                                                                setSaveError(null);
                                                                setSavePhrase('');
                                                                setSaveOpen(true);
                                                            }}
                                                        >
                                                            <Save size={14} aria-hidden="true" />
                                                            Save…
                                                        </GlassButton>
                                                    ) : null}
                                                </div>
                                            </div>
                                            {cosmos.document.editable ? null : (
                                                <DmNotice tone="warning">
                                                    This container is read-only in the Data Management editor.
                                                    You can inspect the JSON but cannot save changes here.
                                                </DmNotice>
                                            )}
                                            {lastSaveSummary ? (
                                                <DmNotice tone="success" role="status">
                                                    {lastSaveSummary}
                                                </DmNotice>
                                            ) : null}
                                            <textarea
                                                aria-label="Cosmos DB document JSON"
                                                spellCheck={false}
                                                readOnly={!cosmos.document.editable}
                                                className={clsx(
                                                    inputClass,
                                                    'min-h-[26rem] resize-y font-mono text-xs leading-relaxed',
                                                )}
                                                value={cosmos.document.text}
                                                onChange={(event) => {
                                                    const document =
                                                        useDataManagementStore.getState().cosmos.document;
                                                    if (!document) return;
                                                    useDataManagementStore.getState().updateCosmos({
                                                        document: {
                                                            ...document,
                                                            text: event.target.value,
                                                        },
                                                    });
                                                    setSaveError(null);
                                                    setLastSaveSummary(null);
                                                }}
                                            />
                                            <p
                                                aria-live="polite"
                                                className={clsx(
                                                    'text-xs',
                                                    editCheck?.ok ? 'text-ok' : 'text-danger',
                                                )}
                                            >
                                                {editCheck?.ok
                                                    ? 'JSON is valid. Id and partition key still match the opened document.'
                                                    : editCheck?.error}
                                            </p>
                                        </div>
                                    ) : (
                                        <DmEmpty title="Select a result to load JSON.">
                                            Open one selectable document at a time. Saves use the ETag
                                            returned when the document was loaded.
                                        </DmEmpty>
                                    )}
                                </div>
                            }
                        />
                    </section>
                )}
            </div>
            {dangerOpen ? (
                <Modal
                    title="Unlock Cosmos DB editor"
                    description="This interface can change live application data."
                    size="md"
                    onClose={() => setDangerOpen(false)}
                    footer={
                        <>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={busy === 'unlock'}
                                onClick={() => setDangerOpen(false)}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                disabled={!dangerAccepted || busy === 'unlock'}
                                onClick={() => void unlock()}
                            >
                                {busy === 'unlock' ? (
                                    <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                                ) : (
                                    <Unlock size={14} aria-hidden="true" />
                                )}
                                Unlock
                            </GlassButton>
                        </>
                    }
                >
                    <div className="space-y-3 text-sm leading-relaxed text-text-2">
                        <DmNotice tone="danger">
                            Incorrect edits can break authentication, workspaces, chat history, documents,
                            automations, or activity log integrity. Each unlock is recorded in activity logs.
                        </DmNotice>
                        <ul className="list-disc space-y-1 pl-5 text-xs text-text-3">
                            <li>Run targeted SELECT queries instead of broad container scans.</li>
                            <li>Do not change a document id or partition key value.</li>
                            <li>Review JSON carefully before saving; saves are audited in Activity Logs.</li>
                        </ul>
                        <label className="flex items-start gap-2 text-sm font-semibold text-text-1">
                            <input
                                type="checkbox"
                                className="mt-1 h-4 w-4 rounded border-edge text-accent focus:ring-accent"
                                checked={dangerAccepted}
                                onChange={(event) => setDangerAccepted(event.target.checked)}
                            />
                            <span>I understand this editor can damage overall system health.</span>
                        </label>
                    </div>
                </Modal>
            ) : null}
            {saveOpen && cosmos.document && localSummary && parsedDocument ? (
                <Modal
                    title="Confirm Cosmos DB document save"
                    description={`Container: ${cosmos.document.container}; id: ${cosmos.document.id}`}
                    size="lg"
                    onClose={() => {
                        if (busy !== 'save') setSaveOpen(false);
                    }}
                    footer={
                        <>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={busy === 'save'}
                                onClick={() => setSaveOpen(false)}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                disabled={busy === 'save' || savePhrase !== COSMOS_EDITOR_SAVE_PHRASE}
                                onClick={() => void saveDocument()}
                            >
                                {busy === 'save' ? (
                                    <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                                ) : (
                                    <DatabaseZap size={14} aria-hidden="true" />
                                )}
                                Save document
                            </GlassButton>
                        </>
                    }
                >
                    <div className="@container space-y-3">
                        <DmNotice tone="danger">
                            Saving replaces the selected Cosmos DB document with the JSON currently in the
                            editor. This action is audited and cannot be undone from this screen.
                        </DmNotice>
                        <DmMetricGrid
                            label="Change summary"
                            items={[
                                {
                                    label: 'Changed paths',
                                    value: formatNumber(localSummary.changedPaths.length),
                                },
                                { label: 'Added', value: formatNumber(localSummary.addedCount) },
                                { label: 'Removed', value: formatNumber(localSummary.removedCount) },
                                { label: 'Updated', value: formatNumber(localSummary.updatedCount) },
                            ]}
                        />
                        <div className="rounded-lg border border-edge bg-surface-1 p-3 text-xs leading-relaxed text-text-2">
                            <p className="font-semibold text-text-1">First changed paths</p>
                            <p className="mt-1 break-words">
                                {localSummary.changedPaths.length
                                    ? localSummary.changedPaths.slice(0, 20).join(', ')
                                    : 'No value changes detected. Saving still replaces the document, which gives it a new ETag.'}
                            </p>
                        </div>
                        {saveError ? (
                            <DmNotice
                                tone="danger"
                                role="alert"
                                action={
                                    saveError.startsWith('This document changed') ? (
                                        <GlassButton
                                            type="button"
                                            variant="subtle"
                                            size="sm"
                                            disabled={busy === 'reload'}
                                            onClick={() => void reloadDocumentNow()}
                                        >
                                            Reload
                                        </GlassButton>
                                    ) : undefined
                                }
                            >
                                {saveError}
                            </DmNotice>
                        ) : null}
                        <DmPhraseField
                            phrase={COSMOS_EDITOR_SAVE_PHRASE}
                            value={savePhrase}
                            onChange={setSavePhrase}
                            disabled={busy === 'save'}
                            label="Type the save confirmation phrase"
                        />
                    </div>
                </Modal>
            ) : null}
            {pendingConfirm ? (
                <ConfirmDialog
                    title={pendingConfirm.title}
                    description={pendingConfirm.description}
                    confirmLabel={pendingConfirm.confirmLabel}
                    onClose={() => setPendingConfirm(null)}
                    onConfirm={() => {
                        const action = pendingConfirm.onConfirm;
                        setPendingConfirm(null);
                        action();
                    }}
                />
            ) : null}
        </div>
    );
}
