// ModelCatalogManager.tsx
// The Model Catalog in V2 Admin Settings, and the profile picker AI Connections uses.
//
// The classic page renders the catalog with the shared vanilla module in
// `static/js/admin/model_catalog_ui.js`. V2 used to mount that same module inside a
// 768px column, where its list and detail wrapped into one long, narrow strip. This is a
// native replacement laid out as a workbench: filters across the top, then a compact
// profile list beside a tabbed detail pane, each scrolling on its own so the AI
// Connections section below stays one scroll away. Saving, conflicts, and preferences
// follow the classic module's behaviour, against the same API.

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { Link2, Plus, RotateCw, Search, Star, TriangleAlert } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    CATALOG_CAPABILITIES,
    CATALOG_CHANGED_EVENT,
    DEFAULT_CATALOG_FILTERS,
    activeFilterCount,
    catalogChanged,
    duplicateProfileForm,
    emptyProfileForm,
    filterCatalogProfiles,
    formToPayload,
    linkedModelCount,
    loadAdminCatalog,
    loadCatalogChoices,
    profileToForm,
    profileToPayload,
    publisherLabel,
    publisherOptions,
    saveCatalogChange,
    type CatalogConnectionTarget,
    type CatalogFilters,
    type CatalogPreferences,
    type CatalogPriority,
    type CatalogProfile,
    type CatalogProfileForm,
    type CatalogProfilePayload,
    type CatalogResponse,
} from '../../lib/modelCatalog';
import { modelConnectionsChanged } from '../../stores/modelConnectionsStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';
import { ModelCatalogDetail, type CatalogDetailTab } from './ModelCatalogDetail';
import { ModelCatalogEditor } from './ModelCatalogEditor';

interface Notice {
    kind: 'info' | 'success' | 'error';
    text: string;
    /** Offer a retry, for a list that could not be read. */
    retry?: boolean;
}

interface EditorState {
    form: CatalogProfileForm;
    /** The custom profile being edited, or null for a new one. */
    profileId: string | null;
}

function errorText(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}

/** Whether the detail pane currently sits below the list rather than beside it. */
function isStacked(list: HTMLElement | null, detail: HTMLElement | null): boolean {
    if (!list || !detail) {
        return false;
    }
    return detail.getBoundingClientRect().top >= list.getBoundingClientRect().bottom - 1;
}

function FilterSelect({
    label,
    value,
    options,
    onChange,
}: {
    label: string;
    value: string;
    options: ReadonlyArray<readonly [string, string]>;
    onChange: (value: string) => void;
}) {
    const id = useId();
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-xs font-medium text-text-2">
                {label}
            </label>
            <select
                id={id}
                className={clsx(inputClass, 'min-w-0')}
                value={value}
                onChange={(event) => onChange(event.target.value)}
            >
                {options.map(([optionValue, text]) => (
                    <option key={optionValue} value={optionValue}>
                        {text}
                    </option>
                ))}
            </select>
        </div>
    );
}

export function ModelCatalogManager({
    help,
    onOpenConnection,
}: {
    help?: string;
    /**
     * Take the administrator to AI Connections, optionally to one connection's model.
     * Supplied by the settings page; without it the catalog lists links as plain text.
     */
    onOpenConnection?: (target?: CatalogConnectionTarget) => void;
}) {
    const baseId = useId();
    const [catalog, setCatalog] = useState<CatalogResponse>({ profiles: [], tasks: {} });
    const [loaded, setLoaded] = useState(false);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState<Notice | null>({ kind: 'info', text: 'Loading model catalog…' });
    const [filters, setFilters] = useState<CatalogFilters>({ ...DEFAULT_CATALOG_FILTERS });
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
    const [tab, setTab] = useState<CatalogDetailTab>('overview');
    const [editor, setEditor] = useState<EditorState | null>(null);
    const [dirty, setDirty] = useState(false);
    const [pendingDiscard, setPendingDiscard] = useState<(() => void) | null>(null);

    const listRef = useRef<HTMLDivElement>(null);
    const detailRef = useRef<HTMLDivElement>(null);
    const headingRef = useRef<HTMLHeadingElement>(null);
    const controllerRef = useRef<AbortController | null>(null);
    const mountedRef = useRef(true);
    // Saving disables every control, which drops focus. These say where it goes back.
    const restoreFocusRef = useRef<{ id?: string; heading?: boolean } | null>(null);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            controllerRef.current?.abort();
        };
    }, []);

    const load = useCallback(async () => {
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        setLoading(true);
        setNotice({ kind: 'info', text: 'Loading model catalog…' });
        try {
            const result = await loadAdminCatalog(controller.signal);
            if (controller.signal.aborted) {
                return;
            }
            setCatalog(result);
            setLoaded(true);
            setNotice(null);
        } catch (error) {
            if (controller.signal.aborted) {
                return;
            }
            setNotice({
                kind: 'error',
                text: errorText(error, 'The model catalog could not be loaded.'),
                retry: true,
            });
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false);
            }
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    // Edits that exist only in this form have to survive an accidental tab close.
    useEffect(() => {
        if (!dirty) {
            return;
        }
        const onBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    }, [dirty]);

    useEffect(() => {
        if (busy || !restoreFocusRef.current) {
            return;
        }
        const target = restoreFocusRef.current;
        restoreFocusRef.current = null;
        if (document.activeElement && document.activeElement !== document.body) {
            return;
        }
        const element = target.heading
            ? headingRef.current
            : target.id
                ? document.getElementById(target.id)
                : null;
        element?.focus();
    }, [busy]);

    const rows = useMemo(
        () => filterCatalogProfiles(catalog.profiles, filters),
        [catalog.profiles, filters],
    );
    const publishers = useMemo(() => publisherOptions(catalog.profiles), [catalog.profiles]);
    const selected = catalog.profiles.find((profile) => profile.id === selectedId) ?? null;
    const filtersApplied = activeFilterCount(filters);
    const locked = busy || loading;

    const setFilter = <K extends keyof CatalogFilters>(key: K, value: CatalogFilters[K]) =>
        setFilters((current) => ({ ...current, [key]: value }));

    /** Run an action, first asking whether to drop unsaved profile edits. */
    const confirmDiscard = (action: () => void) => {
        if (locked) {
            return;
        }
        if (!dirty) {
            action();
            return;
        }
        setNotice(null);
        setPendingDiscard(() => action);
    };

    const onSaved = () => {
        catalogChanged();
        modelConnectionsChanged();
        void useBootstrapStore.getState().refreshRequired().catch(() => {
            toast.error('Catalog saved, but model availability could not refresh. Reload before selecting a model.');
        });
    };

    const save = async (
        change: { profile?: CatalogProfilePayload; preferences?: CatalogPreferences },
        profileId?: string,
    ) => {
        if (locked) {
            return;
        }
        const closesEditor = Boolean(change.profile && editor);
        restoreFocusRef.current = closesEditor
            ? { heading: true }
            : { id: (document.activeElement as HTMLElement | null)?.id || undefined };
        const before = new Set(catalog.profiles.map((profile) => profile.id));
        setBusy(true);
        setPendingDiscard(null);
        setNotice({ kind: 'info', text: 'Saving…' });
        try {
            const result = await saveCatalogChange(change, catalog.etag, profileId);
            if (!mountedRef.current) {
                return;
            }
            const created = profileId ? undefined : result.profiles.find((profile) => !before.has(profile.id));
            setCatalog(result);
            setDirty(false);
            setEditor(null);
            if (created) {
                setSelectedId(created.id);
                setTab('overview');
            } else if (profileId) {
                setSelectedId(profileId);
            }
            setNotice({ kind: 'success', text: 'Catalog saved.' });
            onSaved();
        } catch (error) {
            if (!mountedRef.current) {
                return;
            }
            // The form stays as typed, so a conflict or validation error loses nothing.
            setNotice({ kind: 'error', text: errorText(error, 'The catalog could not be saved.') });
        } finally {
            if (mountedRef.current) {
                setBusy(false);
            }
        }
    };

    const selectProfile = (profileId: string, nextTab: CatalogDetailTab) =>
        confirmDiscard(() => {
            setEditor(null);
            setDirty(false);
            setSelectedId(profileId);
            setTab(nextTab);
            // Stacked on a narrow screen, the detail is below the list and out of view.
            requestAnimationFrame(() => {
                if (isStacked(listRef.current, detailRef.current)) {
                    detailRef.current?.scrollIntoView({ block: 'start' });
                }
            });
        });

    const openEditor = (state: EditorState, startsDirty: boolean) => {
        setEditor(state);
        setDirty(startsDirty);
        setNotice(null);
        requestAnimationFrame(() => {
            if (isStacked(listRef.current, detailRef.current)) {
                detailRef.current?.scrollIntoView({ block: 'start' });
            }
        });
    };

    const updatePreferences = (profile: CatalogProfile, change: Partial<CatalogPreferences>) =>
        void save({ preferences: { ...profile.preferences, ...change } }, profile.id);

    // Arrow keys move through the list; Tab leaves it in one step.
    const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            return;
        }
        const buttons = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-catalog-row]'),
        );
        if (!buttons.length) {
            return;
        }
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next =
            event.key === 'Home' ? 0
                : event.key === 'End' ? buttons.length - 1
                    : event.key === 'ArrowDown' ? Math.min(buttons.length - 1, index + 1)
                        : Math.max(0, index - 1);
        buttons[next]?.focus();
    };

    const tabStopId =
        (focusedRowId && rows.some((row) => row.id === focusedRowId) && focusedRowId) ||
        (selectedId && rows.some((row) => row.id === selectedId) && selectedId) ||
        rows[0]?.id;

    const noticeElement = pendingDiscard ? (
        <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn"
        >
            <TriangleAlert size={15} aria-hidden="true" className="shrink-0" />
            <span className="min-w-0 flex-1">This profile has unsaved changes.</span>
            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                onClick={() => {
                    const action = pendingDiscard;
                    setPendingDiscard(null);
                    setDirty(false);
                    action();
                }}
            >
                Discard changes
            </GlassButton>
            <GlassButton type="button" variant="ghost" size="sm" onClick={() => setPendingDiscard(null)}>
                Keep editing
            </GlassButton>
        </div>
    ) : notice?.kind === 'error' ? (
        <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger"
        >
            <TriangleAlert size={15} aria-hidden="true" className="shrink-0" />
            <span className="min-w-0 flex-1">{notice.text}</span>
            {notice.retry ? (
                <GlassButton type="button" variant="subtle" size="sm" disabled={loading} onClick={() => void load()}>
                    Retry
                </GlassButton>
            ) : null}
        </div>
    ) : notice ? (
        <p className={clsx('text-sm', notice.kind === 'success' ? 'text-ok' : 'text-text-3')}>{notice.text}</p>
    ) : null;

    return (
        <div
            data-testid="model-catalog-manager"
            aria-busy={locked}
            className="@container min-w-0 py-3"
        >
            {help ? (
                <p className="mb-4 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{help}</p>
            ) : null}

            <fieldset disabled={locked} className="m-0 min-w-0 border-0 p-0">
                <legend className="sr-only">Model Catalog</legend>

                <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-[min(100%,16rem)] flex-1">
                        <Search
                            size={16}
                            aria-hidden="true"
                            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                        />
                        <input
                            type="search"
                            aria-label="Search profiles"
                            placeholder="Search by name, publisher, alias, or summary"
                            className={clsx(inputClass, 'pl-9')}
                            value={filters.query}
                            onChange={(event) => setFilter('query', event.target.value)}
                        />
                    </div>
                    <GlassButton
                        type="button"
                        variant="subtle"
                        aria-pressed={filters.favorites}
                        className={clsx(filters.favorites && 'bg-accent-soft text-accent')}
                        onClick={() => setFilter('favorites', !filters.favorites)}
                    >
                        <Star
                            size={15}
                            aria-hidden="true"
                            className={clsx(filters.favorites && 'fill-current')}
                        />
                        Favorites only
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="primary"
                        onClick={() =>
                            confirmDiscard(() => {
                                setSelectedId(null);
                                openEditor({ form: emptyProfileForm(), profileId: null }, false);
                            })
                        }
                    >
                        <Plus size={15} aria-hidden="true" />
                        Add custom profile
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="ghost"
                        onClick={() =>
                            confirmDiscard(() => {
                                setEditor(null);
                                setDirty(false);
                                void load();
                            })
                        }
                    >
                        <RotateCw size={15} aria-hidden="true" />
                        Reload catalog
                    </GlassButton>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 @2xl:grid-cols-3 @5xl:grid-cols-6">
                    <FilterSelect
                        label="Origin"
                        value={filters.origin}
                        options={[['', 'All profiles'], ['built_in', 'Built-in'], ['custom', 'Custom']]}
                        onChange={(value) => setFilter('origin', value as CatalogFilters['origin'])}
                    />
                    <FilterSelect
                        label="Task strength"
                        value={filters.task}
                        options={[['', 'All tasks'], ...Object.entries(catalog.tasks)]}
                        onChange={(value) => setFilter('task', value)}
                    />
                    <FilterSelect
                        label="Publisher"
                        value={filters.publisher}
                        options={[
                            ['', 'All publishers'],
                            ...publishers.map((value) => [value, publisherLabel(value)] as const),
                        ]}
                        onChange={(value) => setFilter('publisher', value)}
                    />
                    <FilterSelect
                        label="Capability"
                        value={filters.capability}
                        options={[
                            ['', 'All capabilities'],
                            ...CATALOG_CAPABILITIES.map((item) => [item.key, item.label] as const),
                        ]}
                        onChange={(value) => setFilter('capability', value)}
                    />
                    <FilterSelect
                        label="Connections"
                        value={filters.availability}
                        options={[['', 'All profiles'], ['linked', 'Linked globally'], ['unlinked', 'Not linked globally']]}
                        onChange={(value) => setFilter('availability', value as CatalogFilters['availability'])}
                    />
                    <FilterSelect
                        label="Status"
                        value={filters.lifecycle}
                        options={[['active', 'Active'], ['archived', 'Archived'], ['', 'All statuses']]}
                        onChange={(value) => setFilter('lifecycle', value as CatalogFilters['lifecycle'])}
                    />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-3">
                    <span>
                        <span className="font-semibold text-text-1 tabular-nums">{rows.length}</span>
                        {' of '}
                        <span className="tabular-nums">{catalog.profiles.length}</span> profiles · Profiles
                        describe models; they are not deployments.
                    </span>
                    {filtersApplied ? (
                        <button
                            type="button"
                            className="text-accent underline underline-offset-2"
                            onClick={() => setFilters((current) => ({ ...DEFAULT_CATALOG_FILTERS, query: current.query }))}
                        >
                            Clear filters ({filtersApplied})
                        </button>
                    ) : null}
                </div>

                <div aria-live="polite" className="mt-3 empty:mt-0">
                    {noticeElement}
                </div>

                <div className="mt-3 grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-[clamp(30rem,72vh,52rem)] @3xl:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)]">
                    <div
                        ref={listRef}
                        className="max-h-[24rem] min-h-0 overflow-y-auto border-b border-edge-strong @3xl:max-h-none @3xl:border-r @3xl:border-b-0"
                    >
                        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-edge-strong bg-surface-solid px-3 py-2 text-xs font-semibold text-text-2">
                            <span>Profile</span>
                            <span>Connected</span>
                        </div>
                        {rows.length ? (
                            <ul aria-label="Catalog profiles" onKeyDown={onListKeyDown}>
                                {rows.map((profile) => {
                                    const isSelected = profile.id === selectedId;
                                    const count = linkedModelCount(profile);
                                    const favorite = Boolean(profile.preferences?.favorite);
                                    const metaId = `${baseId}-row-${profile.id}`;
                                    return (
                                        <li key={profile.id}>
                                            <button
                                                type="button"
                                                data-catalog-row
                                                aria-pressed={isSelected}
                                                aria-label={`${favorite ? 'Favorite - ' : ''}${profile.displayName}`}
                                                aria-describedby={metaId}
                                                tabIndex={profile.id === tabStopId ? 0 : -1}
                                                onFocus={() => setFocusedRowId(profile.id)}
                                                onClick={(event) =>
                                                    selectProfile(
                                                        profile.id,
                                                        (event.target as HTMLElement).closest('[data-catalog-connections]')
                                                            ? 'connections'
                                                            : 'overview',
                                                    )
                                                }
                                                className={clsx(
                                                    'flex w-full items-center gap-2.5 border-b border-edge px-3 py-2.5 text-left transition-colors',
                                                    isSelected
                                                        ? 'bg-accent-soft ring-1 ring-accent/40 ring-inset'
                                                        : 'hover:bg-surface-sunken',
                                                )}
                                            >
                                                <Star
                                                    size={13}
                                                    aria-hidden="true"
                                                    className={clsx(
                                                        'shrink-0',
                                                        favorite ? 'fill-current text-warn' : 'text-transparent',
                                                    )}
                                                />
                                                <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
                                                    <span
                                                        className={clsx(
                                                            'min-w-0 truncate text-sm font-semibold',
                                                            isSelected ? 'text-accent' : 'text-text-1',
                                                        )}
                                                    >
                                                        {profile.displayName}
                                                    </span>
                                                    <span id={metaId} className="text-xs text-text-3">
                                                        {publisherLabel(profile.publisher)}
                                                        {profile.origin === 'custom' ? ' · Custom' : ''}
                                                        {profile.archived ? ' · Archived' : ''}
                                                        <span className="sr-only">
                                                            {`. ${count} globally connected ${count === 1 ? 'model' : 'models'}`}
                                                        </span>
                                                    </span>
                                                </span>
                                                <span
                                                    data-catalog-connections
                                                    title={
                                                        count
                                                            ? `Show the ${count} connected ${count === 1 ? 'model' : 'models'}`
                                                            : 'No global connections use this profile'
                                                    }
                                                    className={clsx(
                                                        'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums',
                                                        count ? 'bg-accent-soft text-accent' : 'text-text-3',
                                                    )}
                                                >
                                                    <Link2 size={12} aria-hidden="true" />
                                                    {count}
                                                </span>
                                            </button>
                                        </li>
                                    );
                                })}
                            </ul>
                        ) : (
                            <p className="px-3 py-6 text-sm text-text-3">
                                {loaded
                                    ? 'No matching profiles. Try a different search or add a custom profile.'
                                    : 'Profiles appear here once the catalog loads.'}
                            </p>
                        )}
                    </div>

                    <div ref={detailRef} className="@container min-h-0 min-w-0 @3xl:overflow-y-auto">
                        {editor ? (
                            <ModelCatalogEditor
                                form={editor.form}
                                tasks={catalog.tasks}
                                isNew={editor.profileId === null}
                                onChange={(form) => {
                                    setEditor((current) => (current ? { ...current, form } : current));
                                    setDirty(true);
                                }}
                                onSave={() => void save({ profile: formToPayload(editor.form) }, editor.profileId ?? undefined)}
                                onCancel={() =>
                                    confirmDiscard(() => {
                                        setEditor(null);
                                        setDirty(false);
                                    })
                                }
                            />
                        ) : selected ? (
                            <ModelCatalogDetail
                                profile={selected}
                                tasks={catalog.tasks}
                                tab={tab}
                                onTabChange={setTab}
                                headingRef={headingRef}
                                onToggleFavorite={() =>
                                    updatePreferences(selected, { favorite: !selected.preferences?.favorite })
                                }
                                onPriorityChange={(priority: CatalogPriority) =>
                                    updatePreferences(selected, { priority })
                                }
                                onDuplicate={() =>
                                    openEditor({ form: duplicateProfileForm(selected), profileId: null }, true)
                                }
                                onEdit={() =>
                                    openEditor({ form: profileToForm(selected), profileId: selected.id }, false)
                                }
                                onToggleArchive={() =>
                                    void save(
                                        { profile: { ...profileToPayload(selected), archived: !selected.archived } },
                                        selected.id,
                                    )
                                }
                                onOpenConnection={onOpenConnection}
                            />
                        ) : (
                            <div className="flex h-full min-h-[12rem] flex-col items-center justify-center px-6 py-10 text-center">
                                <p className="text-sm font-medium text-text-1">No profile selected</p>
                                <p className="mt-1 max-w-sm text-[0.8125rem] leading-relaxed text-text-3">
                                    Select a profile to inspect its strengths, evidence, and routing
                                    preferences, and the global models connected to it.
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </fieldset>
        </div>
    );
}

/**
 * Choose the catalog profile an AI Connection model is described by.
 *
 * Used inside the connection editor, one per model. The profile list is shared between
 * them (see `loadCatalogChoices`) and re-read after any catalog save.
 */
export function CatalogProfilePicker({
    value,
    onChange,
}: {
    value?: string;
    onChange: (value: string) => void;
}) {
    const id = useId();
    const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        const refresh = () => setRevision((current) => current + 1);
        window.addEventListener(CATALOG_CHANGED_EVENT, refresh);
        return () => window.removeEventListener(CATALOG_CHANGED_EVENT, refresh);
    }, []);

    useEffect(() => {
        let cancelled = false;
        loadCatalogChoices()
            .then((result) => {
                if (!cancelled) {
                    setCatalog(result);
                    setError(null);
                }
            })
            .catch((loadError: unknown) => {
                if (!cancelled) {
                    setError(errorText(loadError, 'Catalog profiles could not be loaded.'));
                }
            });
        return () => {
            cancelled = true;
        };
    }, [revision]);

    if (error) {
        return (
            <p role="alert" className="mt-2 text-xs text-danger">
                {error}
            </p>
        );
    }
    if (!catalog) {
        return <p className="mt-2 text-xs text-text-3">Loading catalog profiles…</p>;
    }

    const current = value ?? '';
    const choices: [string, string][] = [
        ['', 'Automatic exact match (built-in only)'],
        ...catalog.profiles.map((profile): [string, string] => [profile.id, profile.displayName]),
    ];
    if (current && !choices.some(([key]) => key === current)) {
        choices.push([current, `${current} (unavailable or archived)`]);
    }
    const profile = catalog.profiles.find((item) => item.id === current);

    return (
        <div className="mt-2">
            <label htmlFor={id} className="mb-1 block text-xs font-medium text-text-2">
                Catalog profile
            </label>
            <select
                id={id}
                className={inputClass}
                value={current}
                onChange={(event) => onChange(event.target.value)}
            >
                {choices.map(([key, text]) => (
                    <option key={key} value={key}>
                        {text}
                    </option>
                ))}
            </select>
            <p className="mt-1 text-xs text-text-3">
                {profile
                    ? `${profile.summary} Connection overrides still apply.`
                    : 'Profile association does not change the deployment name or credentials.'}
            </p>
        </div>
    );
}
