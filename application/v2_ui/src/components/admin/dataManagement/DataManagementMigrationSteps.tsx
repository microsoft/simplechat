// DataManagementMigrationSteps.tsx
// The migration step panels keep local request state near the controls while committing every durable wizard decision to the shared migration store.

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { AlertCircle, Ban, CheckCircle2, Loader2, Play, RotateCcw, Search, Square, X } from 'lucide-react';
import { clsx } from 'clsx';
import { ApiError } from '../../../lib/apiClient';
import {
    JOB_POLL_INTERVAL_MS,
    MIGRATION_MAX_SELECTED_IDS,
    MIRROR_CONFIRMATION_PHRASE,
    TARGET_COSMOS_DATABASE_NAME,
    cancelJob,
    errorMessage,
    getJobProgress,
    listMigrationCatalog,
    migrationManifestUrl,
    queueJob,
    readWorkflowStep,
    retryJob,
    reviewMigration,
    testTargetCosmos,
    testTargetCosmosRuBoost,
    testTargetEnhancedCitationStorage,
    testTargetSearch,
    type CatalogItem,
    type DataManagementJob,
    type JsonRecord,
    type MigrationMode,
    type MigrationTargetType,
} from '../../../lib/dataManagement';
import {
    DM_SECTION_IDS,
    FIRST_PAGE,
    MIGRATION_MODE_LABELS,
    MIGRATION_TARGET_LABELS,
    asFlag,
    asText,
    buildDmSettingsPayload,
    buildMigrationPlan,
    canExecuteMigration,
    formatDateTime,
    formatNumber,
    humanizeToken,
    isActiveJob,
    isMigrationReviewCurrent,
    isTerminalJob,
    isValidGuid,
    migrationLiveMetrics,
    migrationReviewKey,
    migrationStepIssue,
    normalizeReviewChecks,
    pagerAfterLoad,
    pagerBack,
    pagerForward,
    pagerPageNumber,
    progressPercent,
    readDmValues,
    retryLabel,
    reviewHeadline,
    secondsUntil,
    selectedScopeCount,
    type DmValues,
    type MigrationScopeState,
    type MigrationStep,
    type MigrationWizardState,
    type PagerState,
} from '../../../lib/dataManagementLogic';
import {
    currentEpoch,
    isCurrentEpoch,
    useDataManagementStore,
    useDmDirtyCount,
} from '../../../stores/dataManagementStore';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { GlassButton, Toggle } from '../../ui/primitives';
import { inputClass } from '../fields';
import { DmField } from './DmField';
import {
    DmChip,
    DmEvidenceChecks,
    DmMetricGrid,
    DmNotice,
    DmPager,
    DmPhraseField,
    DmStatusPill,
    useInterval,
    useNow,
} from './DmShared';
import { useSaveFirst } from './useSaveFirst';
import type { GuideId } from './DataManagementGuides';

type OutcomeTone = 'info' | 'success' | 'danger';
type Outcome = { tone: OutcomeTone; message: string };

type PanelProps = {
    step: MigrationStep;
    state: MigrationWizardState;
    values: DmValues;
    disabled?: boolean;
    onNavigate: (sectionId: string) => void;
    onStep: (step: MigrationStep) => void;
    onGuide: (guide: GuideId) => void;
    onReattach: () => void;
};

const TARGET_TYPES: readonly MigrationTargetType[] = ['users', 'groups', 'public_workspaces'];

function currentSettingsPayload() {
    const store = useDataManagementStore.getState();
    const values = readDmValues(store.settings, store.draft);
    return { state: store.migration, values, payload: buildDmSettingsPayload(values) };
}

function serviceOutcome(outcome?: Outcome | null) {
    if (!outcome) return null;
    return (
        <p
            role={outcome.tone === 'danger' ? 'alert' : 'status'}
            aria-live="polite"
            className={clsx(
                'mt-2 text-xs',
                outcome.tone === 'danger' && 'text-danger',
                outcome.tone === 'success' && 'text-ok',
                outcome.tone === 'info' && 'text-text-3',
            )}
        >
            {outcome.message}
        </p>
    );
}

function sectionHeading(title: string, description: string, aside?: ReactNode) {
    return (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 basis-64">
                <h3 id="dm-migration-step-heading" className="text-base font-semibold text-text-1">
                    {title}
                </h3>
                <p className="mt-1 max-w-[72ch] text-sm leading-relaxed text-text-3">{description}</p>
            </div>
            {aside ? <div className="shrink-0">{aside}</div> : null}
        </header>
    );
}

function ServicePanel({
    title,
    purpose,
    action,
    children,
}: {
    title: string;
    purpose: string;
    action: ReactNode;
    children: ReactNode;
}) {
    return (
        <section className="min-w-0 rounded-xl border border-edge-strong bg-surface-1 p-3 @2xl:p-4">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <h4 className="text-sm font-semibold text-text-1">{title}</h4>
                    <p className="mt-0.5 text-xs text-text-3">{purpose}</p>
                </div>
                {action}
            </div>
            <div className="min-w-0">{children}</div>
        </section>
    );
}

function TestButton({
    busy,
    disabled,
    onClick,
    children,
}: {
    busy: boolean;
    disabled?: boolean;
    onClick: () => void;
    children: ReactNode;
}) {
    return (
        <GlassButton type="button" variant="subtle" size="sm" disabled={busy || disabled} onClick={onClick}>
            {busy ? (
                <Loader2 size={14} aria-hidden="true" className="animate-spin" />
            ) : (
                <CheckCircle2 size={14} aria-hidden="true" />
            )}
            {children}
        </GlassButton>
    );
}

function TargetStep({ values, disabled }: Pick<PanelProps, 'values' | 'disabled'>) {
    const [busy, setBusy] = useState<string | null>(null);
    const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
    const trackRequest = useDataManagementStore((state) => state.trackRequest);
    const cosmosAuth = asText(values.target_cosmos_authentication_type, 'managed_identity');
    const searchAuth = asText(values.target_ai_search_authentication_type, 'managed_identity');
    const storageAuth = asText(
        values.target_enhanced_citations_storage_authentication_type,
        'managed_identity',
    );

    const run = async (key: string, action: () => Promise<Outcome>) => {
        setBusy(key);
        try {
            const outcome = await action();
            setOutcomes((current) => ({ ...current, [key]: outcome }));
        } catch (error) {
            setOutcomes((current) => ({
                ...current,
                [key]: { tone: 'danger', message: errorMessage(error, 'Connection test failed.') },
            }));
        } finally {
            setBusy(null);
        }
    };

    const testCosmos = () =>
        void run('cosmos', async () => {
            const current = currentSettingsPayload();
            const result = await testTargetCosmos(current.payload, buildMigrationPlan(current.state));
            const containers = Number(result.migration_access?.container_count ?? 0) || 0;
            return {
                tone: 'success',
                message: `Connected to database ${result.database_name || TARGET_COSMOS_DATABASE_NAME}. ${formatNumber(containers)} planned containers verified.`,
            };
        });

    const testSearch = () =>
        void run('search', async () => {
            const current = currentSettingsPayload();
            const result = await testTargetSearch(current.payload);
            const missing = Array.isArray(result.missing_indexes) ? result.missing_indexes.length : 0;
            const existing = Array.isArray(result.existing_indexes) ? result.existing_indexes.length : 0;
            return {
                tone: 'success',
                message: missing
                    ? `${formatNumber(existing)} indexes exist. ${formatNumber(missing)} missing indexes will be created during migration.`
                    : `${formatNumber(existing)} expected indexes exist.`,
            };
        });

    const testStorage = () =>
        void run('storage', async () => {
            const current = currentSettingsPayload();
            const result = await trackRequest(testTargetEnhancedCitationStorage(current.payload));
            return {
                tone: 'success',
                message: `${formatNumber(result.containers?.length ?? 0)} containers ready.`,
            };
        });

    return (
        <div>
            {sectionHeading(
                'Connect the destination',
                'Configure the destination services this migration will write to. Tests send the current values inline and do not save settings.',
                <DmChip>Database: {TARGET_COSMOS_DATABASE_NAME}</DmChip>,
            )}
            <div className="grid min-w-0 gap-3 @4xl:grid-cols-3">
                <ServicePanel
                    title="Cosmos DB"
                    purpose="Required for every migration."
                    action={
                        <TestButton busy={busy === 'cosmos'} disabled={disabled} onClick={testCosmos}>
                            Test Cosmos DB
                        </TestButton>
                    }
                >
                    <DmField dmKey="target_cosmos_authentication_type" disabled={disabled} />
                    <DmField dmKey="target_cosmos_endpoint" disabled={disabled} />
                    <div className="rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm text-text-2">
                        <span className="font-semibold text-text-1">Database:</span>{' '}
                        {TARGET_COSMOS_DATABASE_NAME}
                        <span className="ml-2 text-xs text-text-3">Fixed app contract</span>
                    </div>
                    {cosmosAuth === 'key' ? <DmField dmKey="target_cosmos_key" disabled={disabled} /> : null}
                    {serviceOutcome(outcomes.cosmos)}
                </ServicePanel>
                <ServicePanel
                    title="AI Search"
                    purpose="Needed when AI Search documents are included."
                    action={
                        <TestButton busy={busy === 'search'} disabled={disabled} onClick={testSearch}>
                            Test AI Search
                        </TestButton>
                    }
                >
                    <DmField dmKey="target_ai_search_authentication_type" disabled={disabled} />
                    <DmField dmKey="target_ai_search_endpoint" disabled={disabled} />
                    {searchAuth === 'key' ? (
                        <DmField dmKey="target_ai_search_key" disabled={disabled} />
                    ) : null}
                    {serviceOutcome(outcomes.search)}
                </ServicePanel>
                <ServicePanel
                    title="Enhanced Citation storage"
                    purpose="Needed when selected source document files are included."
                    action={
                        <TestButton busy={busy === 'storage'} disabled={disabled} onClick={testStorage}>
                            Test storage
                        </TestButton>
                    }
                >
                    <DmField
                        dmKey="target_enhanced_citations_storage_authentication_type"
                        disabled={disabled}
                    />
                    {storageAuth === 'connection_string' ? (
                        <DmField
                            dmKey="target_enhanced_citations_storage_connection_string"
                            disabled={disabled}
                        />
                    ) : (
                        <DmField
                            dmKey="target_enhanced_citations_storage_blob_endpoint"
                            disabled={disabled}
                        />
                    )}
                    {serviceOutcome(outcomes.storage)}
                </ServicePanel>
            </div>
        </div>
    );
}

interface CatalogState {
    search: string;
    appliedSearch: string;
    items: CatalogItem[];
    total: number;
    pager: PagerState;
    loading: boolean;
    error: string | null;
    limitMessage: string | null;
}

const initialCatalog = (): CatalogState => ({
    search: '',
    appliedSearch: '',
    items: [],
    total: 0,
    pager: FIRST_PAGE,
    loading: false,
    error: null,
    limitMessage: null,
});

function updateScope(type: MigrationTargetType, patch: Partial<MigrationScopeState>) {
    useDataManagementStore.getState().updateMigration((state) => ({
        ...state,
        reviewKey: null,
        acknowledged: false,
        mirrorPhrase: '',
        scopes: { ...state.scopes, [type]: { ...state.scopes[type], ...patch } },
    }));
}

function ScopeStep({ state, disabled }: Pick<PanelProps, 'state' | 'disabled'>) {
    const [active, setActive] = useState<MigrationTargetType>('users');
    const [catalog, setCatalog] = useState<Record<MigrationTargetType, CatalogState>>({
        users: initialCatalog(),
        groups: initialCatalog(),
        public_workspaces: initialCatalog(),
    });
    const tabRefs = useRef<Record<MigrationTargetType, HTMLButtonElement | null>>({
        users: null,
        groups: null,
        public_workspaces: null,
    });
    const catalogRequests = useRef<Record<MigrationTargetType, number>>({
        users: 0,
        groups: 0,
        public_workspaces: 0,
    });
    const selectedTotal = selectedScopeCount(state);
    const scope = state.scopes[active];
    const currentCatalog = catalog[active];
    const selectedIds = useMemo(() => new Set(scope.selected.map((item) => item.id)), [scope.selected]);

    const loadCatalog = async (type: MigrationTargetType, search: string, pager: PagerState) => {
        const token = currentEpoch();
        // Only the newest search for a type may land; an older, slower one is dropped.
        const request = catalogRequests.current[type] + 1;
        catalogRequests.current[type] = request;
        const latest = () => isCurrentEpoch(token) && catalogRequests.current[type] === request;
        setCatalog((current) => ({
            ...current,
            [type]: { ...current[type], loading: true, error: null, appliedSearch: search, pager },
        }));
        try {
            const page = await listMigrationCatalog(type, search, pager.current ?? '');
            if (!latest()) return;
            setCatalog((current) => ({
                ...current,
                [type]: {
                    ...current[type],
                    loading: false,
                    items: page.items,
                    total: page.total_count,
                    pager: pagerAfterLoad(pager, page.continuation_token),
                    error: null,
                },
            }));
        } catch (error) {
            if (!latest()) return;
            setCatalog((current) => ({
                ...current,
                [type]: {
                    ...current[type],
                    loading: false,
                    items: [],
                    error: errorMessage(error, 'Catalog could not be loaded.'),
                },
            }));
        }
    };

    const onTabKey = (event: KeyboardEvent<HTMLButtonElement>, type: MigrationTargetType) => {
        const index = TARGET_TYPES.indexOf(type);
        const nextIndex = event.key === 'ArrowRight' ? index + 1 : event.key === 'ArrowLeft' ? index - 1 : -1;
        if (nextIndex < 0) return;
        event.preventDefault();
        const next = TARGET_TYPES[(nextIndex + TARGET_TYPES.length) % TARGET_TYPES.length];
        setActive(next);
        tabRefs.current[next]?.focus();
    };

    const setSearch = (value: string) =>
        setCatalog((current) => ({ ...current, [active]: { ...current[active], search: value } }));
    const search = () => void loadCatalog(active, currentCatalog.search.trim(), FIRST_PAGE);
    const next = () =>
        void loadCatalog(active, currentCatalog.appliedSearch, pagerForward(currentCatalog.pager));
    const previous = () =>
        void loadCatalog(active, currentCatalog.appliedSearch, pagerBack(currentCatalog.pager));

    const toggleItem = (item: CatalogItem, checked: boolean) => {
        const current = state.scopes[active];
        if (checked && current.selected.length >= MIGRATION_MAX_SELECTED_IDS && !selectedIds.has(item.id)) {
            setCatalog((catalogState) => ({
                ...catalogState,
                [active]: {
                    ...catalogState[active],
                    limitMessage: `Choose at most ${formatNumber(MIGRATION_MAX_SELECTED_IDS)} ${MIGRATION_TARGET_LABELS[active].plural.toLowerCase()}, or choose All.`,
                },
            }));
            return;
        }
        const selected = checked
            ? [...current.selected.filter((existing) => existing.id !== item.id), item]
            : current.selected.filter((existing) => existing.id !== item.id);
        setCatalog((catalogState) => ({
            ...catalogState,
            [active]: { ...catalogState[active], limitMessage: null },
        }));
        updateScope(active, { selected });
    };

    return (
        <div>
            {sectionHeading(
                'Choose who and what moves',
                'Select users, groups, and public workspaces. All uses the server count when the job starts; the browser never loads every record.',
                <div
                    className="rounded-full border border-edge bg-surface-2 px-3 py-1 text-xs text-text-2"
                    aria-live="polite"
                >
                    {formatNumber(selectedTotal)} principal scopes selected
                </div>,
            )}
            <div
                role="tablist"
                aria-label="Migration scope type"
                className="mb-4 flex min-w-0 flex-wrap gap-2"
            >
                {TARGET_TYPES.map((type) => (
                    <button
                        key={type}
                        ref={(node) => {
                            tabRefs.current[type] = node;
                        }}
                        type="button"
                        role="tab"
                        aria-selected={active === type}
                        className={clsx(
                            'rounded-xl border px-3 py-2 text-sm font-medium',
                            active === type
                                ? 'border-accent bg-accent-soft text-accent'
                                : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2',
                        )}
                        onClick={() => setActive(type)}
                        onKeyDown={(event) => onTabKey(event, type)}
                    >
                        {MIGRATION_TARGET_LABELS[type].plural}
                        <span className="ml-2 rounded-full border border-edge bg-surface-solid px-1.5 py-0.5 text-xs">
                            {formatNumber(state.scopes[type].selected.length)}
                        </span>
                    </button>
                ))}
            </div>
            <section
                role="tabpanel"
                className="min-w-0 rounded-xl border border-edge-strong bg-surface-1 p-3"
            >
                <fieldset disabled={disabled}>
                    <legend className="text-sm font-semibold text-text-1">
                        {MIGRATION_TARGET_LABELS[active].plural}
                    </legend>
                    <div className="mt-2 grid gap-2 @2xl:grid-cols-3">
                        {(['none', 'selected', 'all'] as const).map((mode) => (
                            <label
                                key={mode}
                                className={clsx(
                                    'flex cursor-pointer gap-2 rounded-xl border p-3 text-sm',
                                    scope.mode === mode
                                        ? 'border-accent bg-accent-soft text-accent'
                                        : 'border-edge bg-surface-solid text-text-2',
                                )}
                            >
                                <input
                                    type="radio"
                                    name={`migration-${active}-mode`}
                                    value={mode}
                                    checked={scope.mode === mode}
                                    onChange={() =>
                                        updateScope(active, {
                                            mode,
                                            includeDocuments:
                                                mode === 'none' ? false : scope.includeDocuments,
                                        })
                                    }
                                />
                                <span>
                                    <span className="block font-semibold">{humanizeToken(mode)}</span>
                                    <span className="block text-xs opacity-80">
                                        {mode === 'all'
                                            ? 'Server counts everything at job start.'
                                            : mode === 'selected'
                                              ? 'Choose records across pages.'
                                              : `Skip ${MIGRATION_TARGET_LABELS[active].plural.toLowerCase()}.`}
                                    </span>
                                </span>
                            </label>
                        ))}
                    </div>
                    <Toggle
                        checked={scope.includeDocuments}
                        disabled={scope.mode === 'none' || disabled}
                        onChange={(checked) => updateScope(active, { includeDocuments: checked })}
                        label="Include their documents"
                        description="When off, only the selected principal records move."
                    />
                </fieldset>
                {scope.mode === 'selected' ? (
                    <div className="mt-4 grid min-w-0 gap-4 @4xl:grid-cols-[minmax(0,1fr)_minmax(15rem,22rem)]">
                        <div className="min-w-0">
                            <div className="flex flex-wrap items-end gap-2">
                                <label className="min-w-0 flex-1 text-xs font-medium text-text-2">
                                    Search {MIGRATION_TARGET_LABELS[active].plural.toLowerCase()}
                                    <input
                                        type="search"
                                        className={clsx(inputClass, 'mt-1')}
                                        value={currentCatalog.search}
                                        disabled={disabled}
                                        onChange={(event) => setSearch(event.target.value)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter') search();
                                        }}
                                    />
                                </label>
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    disabled={currentCatalog.loading || disabled}
                                    onClick={search}
                                >
                                    {currentCatalog.loading ? (
                                        <Loader2 size={14} className="animate-spin" />
                                    ) : (
                                        <Search size={14} />
                                    )}
                                    Search
                                </GlassButton>
                            </div>
                            <p
                                role={currentCatalog.error ? 'alert' : 'status'}
                                aria-live="polite"
                                className={clsx(
                                    'mt-2 text-xs',
                                    currentCatalog.error ? 'text-danger' : 'text-text-3',
                                )}
                            >
                                {currentCatalog.error ?? `${formatNumber(currentCatalog.total)} matches`}
                            </p>
                            <div className="mt-2 divide-y divide-edge overflow-hidden rounded-xl border border-edge bg-surface-solid">
                                {currentCatalog.loading ? (
                                    <div className="p-3 text-sm text-text-3">Loading catalog…</div>
                                ) : null}
                                {!currentCatalog.loading && !currentCatalog.items.length ? (
                                    <div className="p-3 text-sm text-text-3">Search the server catalog.</div>
                                ) : null}
                                {currentCatalog.items.map((item) => (
                                    <label
                                        key={item.id}
                                        className="flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-surface-2"
                                    >
                                        <input
                                            type="checkbox"
                                            className="mt-1"
                                            checked={selectedIds.has(item.id)}
                                            disabled={disabled}
                                            onChange={(event) => toggleItem(item, event.target.checked)}
                                        />
                                        <span className="min-w-0 text-sm">
                                            <span className="block break-words font-semibold text-text-1">
                                                {item.label || item.id}
                                            </span>
                                            <span className="block break-words text-xs text-text-3">
                                                {item.description || item.id}
                                                {item.document_count
                                                    ? ` · ${formatNumber(item.document_count)} documents`
                                                    : ''}
                                            </span>
                                        </span>
                                    </label>
                                ))}
                            </div>
                            <DmPager
                                label={`${MIGRATION_TARGET_LABELS[active].plural} catalog pages`}
                                page={pagerPageNumber(currentCatalog.pager)}
                                hasPrevious={currentCatalog.pager.previous.length > 0}
                                hasNext={Boolean(currentCatalog.pager.next)}
                                loading={currentCatalog.loading}
                                onPrevious={previous}
                                onNext={next}
                            />
                        </div>
                        <div className="min-w-0 rounded-xl border border-edge bg-surface-solid p-3">
                            <div className="flex items-center justify-between gap-2">
                                <h4 className="text-sm font-semibold text-text-1">
                                    Selected ({formatNumber(scope.selected.length)})
                                </h4>
                                <GlassButton
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    disabled={!scope.selected.length || disabled}
                                    onClick={() => updateScope(active, { selected: [] })}
                                >
                                    Clear
                                </GlassButton>
                            </div>
                            {currentCatalog.limitMessage ? (
                                <p role="alert" className="mt-2 text-xs text-warn">
                                    {currentCatalog.limitMessage}
                                </p>
                            ) : null}
                            <ul className="mt-2 max-h-72 divide-y divide-edge overflow-y-auto rounded-lg border border-edge">
                                {scope.selected.length ? (
                                    scope.selected.map((item) => (
                                        <li
                                            key={item.id}
                                            className="flex items-start gap-2 px-2 py-2 text-sm"
                                        >
                                            <span className="min-w-0 flex-1 break-words">
                                                {item.label || item.id}
                                            </span>
                                            <button
                                                type="button"
                                                className="text-text-3 hover:text-danger"
                                                disabled={disabled}
                                                onClick={() => toggleItem(item, false)}
                                                aria-label={`Remove ${item.label || item.id}`}
                                            >
                                                <X size={14} />
                                            </button>
                                        </li>
                                    ))
                                ) : (
                                    <li className="px-2 py-3 text-sm text-text-3">No selected items.</li>
                                )}
                            </ul>
                        </div>
                    </div>
                ) : null}
            </section>
        </div>
    );
}

function RadioCard({
    checked,
    title,
    text,
    danger,
    onChange,
    disabled,
}: {
    checked: boolean;
    title: string;
    text: string;
    danger?: boolean;
    onChange: () => void;
    disabled?: boolean;
}) {
    return (
        <label
            className={clsx(
                'flex cursor-pointer gap-3 rounded-xl border p-3 text-sm',
                checked && !danger && 'border-accent bg-accent-soft text-accent',
                checked && danger && 'border-danger/50 bg-danger-soft text-danger',
                !checked && 'border-edge bg-surface-1 text-text-2',
            )}
        >
            <input
                type="radio"
                name="migration-mode"
                checked={checked}
                disabled={disabled}
                onChange={onChange}
                className="mt-1"
            />
            <span>
                <span className="block font-semibold">{title}</span>
                <span className="mt-1 block text-xs leading-relaxed opacity-85">{text}</span>
            </span>
        </label>
    );
}

function OptionsStep({
    state,
    values,
    disabled,
    onGuide,
}: Pick<PanelProps, 'state' | 'values' | 'disabled' | 'onGuide'>) {
    const updateMigration = useDataManagementStore((store) => store.updateMigration);
    const trackRequest = useDataManagementStore((store) => store.trackRequest);
    const [ruOutcome, setRuOutcome] = useState<Outcome | null>(null);
    const [ruBusy, setRuBusy] = useState(false);
    const ruEnabled = asFlag(values.migration_temporary_destination_ru_enabled);
    const baselineInvalid =
        state.mode !== 'new_only' && state.baselineJobId.trim() && !isValidGuid(state.baselineJobId);
    const setMode = (mode: MigrationMode) =>
        updateMigration({ mode, reviewKey: null, acknowledged: false, mirrorPhrase: '' });
    const patch = (update: Partial<MigrationWizardState>) =>
        updateMigration({ ...update, reviewKey: null, acknowledged: false, mirrorPhrase: '' });
    const testRu = async () => {
        setRuBusy(true);
        try {
            const current = currentSettingsPayload();
            const result = await trackRequest(
                testTargetCosmosRuBoost(current.payload, buildMigrationPlan(current.state)),
            );
            setRuOutcome({
                tone: 'success',
                message: `${formatNumber(result.targets?.length ?? 0)} targets can be set to ${formatNumber(result.target_ru)} RU.`,
            });
        } catch (error) {
            setRuOutcome({
                tone: 'danger',
                message: errorMessage(error, 'RU Boost permissions could not be verified.'),
            });
        } finally {
            setRuBusy(false);
        }
    };
    return (
        <div>
            {sectionHeading(
                'Choose what moves',
                'Set destination behavior, optional surfaces, performance limits, and resumability before the server review.',
            )}
            <div className="grid gap-3">
                <RadioCard
                    checked={state.mode === 'new_only'}
                    disabled={disabled}
                    title={MIGRATION_MODE_LABELS.new_only}
                    text="Copy missing items only: copies source items missing from the destination; existing destination data is never updated or deleted."
                    onChange={() => setMode('new_only')}
                />
                <RadioCard
                    checked={state.mode === 'delta_upsert'}
                    disabled={disabled}
                    title={MIGRATION_MODE_LABELS.delta_upsert}
                    text="Catch up changed items: copies new items and updates changed items this migration created, from a previous completed migration; destination-only data is kept."
                    onChange={() => setMode('delta_upsert')}
                />
                <RadioCard
                    checked={state.mode === 'mirror_with_deletions'}
                    disabled={disabled}
                    danger
                    title={MIGRATION_MODE_LABELS.mirror_with_deletions}
                    text="Make destination match source: catches up, then deletes destination items that earlier SimpleChat migrations created and the source no longer has; data not created by a migration is kept and reported as a conflict."
                    onChange={() => setMode('mirror_with_deletions')}
                />
            </div>
            {state.mode !== 'new_only' ? (
                <label className="mt-4 block text-sm font-semibold text-text-1">
                    Previous migration job ID
                    <input
                        className={clsx(inputClass, 'mt-1 font-mono', baselineInvalid && 'border-danger')}
                        value={state.baselineJobId}
                        disabled={disabled}
                        placeholder="Optional completed migration GUID"
                        onChange={(event) => patch({ baselineJobId: event.target.value })}
                    />
                    <span
                        className={clsx(
                            'mt-1 block text-xs',
                            baselineInvalid ? 'text-danger' : 'text-text-3',
                        )}
                    >
                        Blank lets the server pick the latest compatible completed migration. If entered, it
                        must be a GUID.
                    </span>
                </label>
            ) : null}
            <div className="mt-4 grid gap-3 @3xl:grid-cols-2">
                <div className="rounded-xl border border-edge bg-surface-1 p-3">
                    <h4 className="text-sm font-semibold text-text-1">Data surfaces</h4>
                    <Toggle
                        checked={state.includeAiSearch}
                        disabled={disabled}
                        onChange={(checked) =>
                            patch({
                                includeAiSearch: checked,
                                searchWritesFrozen: checked ? state.searchWritesFrozen : false,
                            })
                        }
                        label="Migrate matching AI Search documents"
                        description="Search records that match selected scopes are copied or reconciled."
                    />
                    {state.includeAiSearch ? (
                        <label className="mt-1 flex items-start gap-2 text-sm text-text-2">
                            <input
                                type="checkbox"
                                className="mt-1"
                                checked={state.searchWritesFrozen}
                                disabled={disabled}
                                onChange={(event) => patch({ searchWritesFrozen: event.target.checked })}
                            />
                            <span>
                                Other writers to the destination AI Search are frozen. SimpleChat pauses its
                                own indexing; external writers must be frozen before review.
                            </span>
                        </label>
                    ) : null}
                    <Toggle
                        checked={state.includeSourceBlobs}
                        disabled={disabled}
                        onChange={(checked) => patch({ includeSourceBlobs: checked })}
                        label="Migrate the selected source document files"
                        description="Requires Enhanced Citation storage at both source and destination."
                    />
                </div>
                <div className="rounded-xl border border-edge bg-surface-1 p-3">
                    <h4 className="text-sm font-semibold text-text-1">Performance and resume</h4>
                    <DmField dmKey="migration_max_parallel_operations" disabled={disabled} />
                    <DmField dmKey="migration_retry_count" disabled={disabled} />
                    <DmField dmKey="migration_skip_recent_within_hours" disabled={disabled} />
                    <p className="mt-2 text-xs text-text-3">
                        Retry and Resume keep durable checkpoints and the same migration ID.
                    </p>
                </div>
            </div>
            <div className="mt-3 rounded-xl border border-edge-strong bg-surface-1 p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-semibold text-text-1">Destination capacity</h4>
                    <GlassButton type="button" variant="ghost" size="sm" onClick={() => onGuide('ru-boost')}>
                        About RU Boost
                    </GlassButton>
                </div>
                <DmField
                    dmKey="migration_temporary_destination_ru_enabled"
                    emphasis="primary"
                    disabled={disabled}
                />
                {ruEnabled ? (
                    <div className="grid gap-2 @3xl:grid-cols-2">
                        <DmField
                            dmKey="migration_temporary_destination_ru"
                            emphasis="dependent"
                            disabled={disabled}
                        />
                        <DmField
                            dmKey="target_cosmos_subscription_id"
                            emphasis="dependent"
                            disabled={disabled}
                        />
                        <DmField
                            dmKey="target_cosmos_resource_group"
                            emphasis="dependent"
                            disabled={disabled}
                        />
                        <div className="flex items-center gap-2 ps-3">
                            <TestButton busy={ruBusy} disabled={disabled} onClick={() => void testRu()}>
                                Test RU Boost permissions
                            </TestButton>
                        </div>
                    </div>
                ) : null}
                {serviceOutcome(ruOutcome)}
            </div>
        </div>
    );
}

function scopeSummary(state: MigrationWizardState) {
    return TARGET_TYPES.map((type) => {
        const scope = state.scopes[type];
        const count = scope.mode === 'all' ? 'All' : formatNumber(scope.selected.length);
        return `${MIGRATION_TARGET_LABELS[type].plural}: ${humanizeToken(scope.mode)} (${count}, ${scope.includeDocuments ? 'documents included' : 'documents skipped'})`;
    });
}

function ReviewStep({
    state,
    values,
    disabled,
    onStep,
}: Pick<PanelProps, 'state' | 'values' | 'disabled' | 'onStep'>) {
    const updateMigration = useDataManagementStore((store) => store.updateMigration);
    const now = useNow(1000, Boolean(state.review));
    const [busy, setBusy] = useState<string | null>(null);
    const [cosmosOutcome, setCosmosOutcome] = useState<Outcome | null>(null);
    const reviewGeneration = useRef(0);
    const stale = Boolean(state.review && !isMigrationReviewCurrent(state, values));
    const headline = reviewHeadline(state.review, stale);
    const expires = secondsUntil(state.review?.authorization_expires_at, now);

    const validateCosmos = async () => {
        setBusy('cosmos');
        try {
            const current = currentSettingsPayload();
            const result = await testTargetCosmos(current.payload, buildMigrationPlan(current.state));
            setCosmosOutcome({
                tone: 'success',
                message: `Connected to database ${result.database_name || TARGET_COSMOS_DATABASE_NAME}. ${formatNumber(result.migration_access?.container_count ?? 0)} planned containers verified.`,
            });
        } catch (error) {
            setCosmosOutcome({
                tone: 'danger',
                message: errorMessage(error, 'Destination Cosmos access could not be validated.'),
            });
        } finally {
            setBusy(null);
        }
    };

    const runReview = async () => {
        const generation = reviewGeneration.current + 1;
        reviewGeneration.current = generation;
        const epoch = currentEpoch();
        setBusy('review');
        const store = useDataManagementStore.getState();
        const sentState = store.migration;
        const sentValues = readDmValues(store.settings, store.draft);
        const payload = buildDmSettingsPayload(sentValues);
        const plan = buildMigrationPlan(sentState);
        const current = () => isCurrentEpoch(epoch) && reviewGeneration.current === generation;
        try {
            const review = await reviewMigration(payload, plan);
            if (!current()) return;
            updateMigration({
                review,
                reviewKey: migrationReviewKey(sentState, sentValues),
                reviewError: null,
                acknowledged: false,
            });
        } catch (error) {
            if (!current()) return;
            updateMigration({ reviewError: errorMessage(error, 'Preflight review failed.') });
        } finally {
            if (current()) setBusy(null);
        }
    };

    const review = state.review;
    const outcomes = review?.preview?.estimated_outcomes ?? {};
    return (
        <div>
            {sectionHeading(
                'Review migration evidence',
                'Run the server preflight review against the current plan and settings. The checkpoint must be ready and current before Confirm opens.',
                <DmChip
                    tone={
                        headline.tone === 'ready'
                            ? 'ok'
                            : headline.tone === 'warning'
                              ? 'warn'
                              : headline.tone === 'blocked' || headline.tone === 'stale'
                                ? 'danger'
                                : 'neutral'
                    }
                >
                    {headline.text}
                </DmChip>,
            )}
            <div className="flex flex-wrap gap-2">
                <TestButton
                    busy={busy === 'cosmos'}
                    disabled={disabled}
                    onClick={() => void validateCosmos()}
                >
                    Validate Cosmos access
                </TestButton>
                <GlassButton
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={busy === 'review' || disabled}
                    onClick={() => void runReview()}
                >
                    {busy === 'review' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    {review ? 'Run again' : 'Run preflight review'}
                </GlassButton>
            </div>
            {serviceOutcome(cosmosOutcome)}
            {state.reviewError ? (
                <DmNotice tone="danger" role="alert" className="mt-3">
                    {state.reviewError}
                </DmNotice>
            ) : null}
            {stale && !state.reviewError ? (
                <DmNotice tone="warning" className="mt-3">
                    Inputs changed after this review. Run it again before confirming.
                </DmNotice>
            ) : null}
            {review ? (
                <div className="mt-4 grid gap-4">
                    <div
                        className={clsx(
                            'rounded-2xl border p-4',
                            headline.tone === 'ready' && 'border-ok/40 bg-ok-soft',
                            headline.tone === 'warning' && 'border-warn/40 bg-warn-soft',
                            (headline.tone === 'blocked' || headline.tone === 'stale') &&
                                'border-danger/40 bg-danger-soft',
                        )}
                    >
                        <p className="text-lg font-semibold text-text-1">{headline.text}</p>
                        <p className="mt-1 text-sm text-text-2">
                            {expires === null
                                ? 'No authorization expiry was returned.'
                                : `Authorization expires in ${formatNumber(expires)} seconds.`}
                        </p>
                    </div>
                    <div className="grid gap-3 @3xl:grid-cols-2">
                        <div className="rounded-xl border border-edge bg-surface-1 p-3">
                            <h4 className="text-sm font-semibold text-text-1">Scope summary</h4>
                            <ul className="mt-2 space-y-1 text-sm text-text-2">
                                {scopeSummary(state).map((line) => (
                                    <li key={line}>{line}</li>
                                ))}
                            </ul>
                            <div className="mt-3 flex flex-wrap gap-1.5">
                                <DmChip>
                                    {state.includeAiSearch ? 'AI Search included' : 'AI Search skipped'}
                                </DmChip>
                                <DmChip>
                                    {state.includeSourceBlobs
                                        ? 'Source files included'
                                        : 'Source files skipped'}
                                </DmChip>
                                <DmChip>{MIGRATION_MODE_LABELS[state.mode]}</DmChip>
                            </div>
                        </div>
                        <div className="rounded-xl border border-edge bg-surface-1 p-3">
                            <h4 className="text-sm font-semibold text-text-1">
                                Estimated destination changes
                            </h4>
                            <DmMetricGrid
                                className="mt-2"
                                items={[
                                    { label: 'Create', value: formatNumber(outcomes.create_count) },
                                    { label: 'Update', value: formatNumber(outcomes.update_count) },
                                    { label: 'Unchanged', value: formatNumber(outcomes.unchanged_count) },
                                    { label: 'Delete', value: formatNumber(outcomes.delete_count) },
                                    {
                                        label: 'Not applicable',
                                        value: formatNumber(outcomes.not_applicable_count),
                                    },
                                    { label: 'Missing', value: formatNumber(outcomes.missing_count) },
                                    { label: 'Conflicts', value: formatNumber(outcomes.conflict_count) },
                                ]}
                            />
                            <p className="mt-2 text-xs text-text-3">
                                Captured{' '}
                                {formatDateTime(review.preview?.captured_at || review.reviewed_at) ||
                                    'during review'}
                                {review.preview?.baseline_job_id
                                    ? ` from baseline ${review.preview.baseline_job_id}`
                                    : ''}
                            </p>
                        </div>
                    </div>
                    <DmEvidenceChecks
                        checks={normalizeReviewChecks(review.checks)}
                        onFixStep={(step) => onStep(step as MigrationStep)}
                    />
                </div>
            ) : null}
        </div>
    );
}

function ConfirmStep({
    state,
    values,
    disabled,
    onNavigate,
    onReattach,
}: Pick<PanelProps, 'state' | 'values' | 'disabled' | 'onNavigate' | 'onReattach'>) {
    const updateMigration = useDataManagementStore((store) => store.updateMigration);
    const dirty = useDmDirtyCount();
    const { ensure, dialog } = useSaveFirst();
    const now = useNow(1000, Boolean(state.review));
    const executable = canExecuteMigration(state, values, now) && !disabled;
    const review = state.review;
    const outcomes = review?.preview?.estimated_outcomes ?? {};
    const [message, setMessage] = useState<string | null>(null);

    const execute = async () => {
        setMessage(null);
        const epoch = currentEpoch();
        updateMigration({ submission: 'submitting' });
        if (!(await ensure('migration-execute'))) {
            if (isCurrentEpoch(epoch)) updateMigration({ submission: 'idle' });
            return;
        }
        if (!isCurrentEpoch(epoch)) return;
        const fresh = useDataManagementStore.getState();
        const freshValues = readDmValues(fresh.settings, fresh.draft);
        if (!canExecuteMigration({ ...fresh.migration, submission: 'idle' }, freshValues, Date.now())) {
            // Sent back to Review, which shows the reason: this step is gone once it changes.
            updateMigration({
                submission: 'idle',
                reviewKey: null,
                acknowledged: false,
                mirrorPhrase: '',
                step: 'review',
                reviewError: 'The saved settings changed the migration review. Run the review again.',
            });
            return;
        }
        try {
            const job = await fresh.trackRequest(
                queueJob('migration', null, {
                    review_fingerprint: fresh.migration.review?.review_fingerprint,
                    review_authorization_token: fresh.migration.review?.authorization_token,
                    migration_plan: buildMigrationPlan(fresh.migration),
                }),
            );
            if (!isCurrentEpoch(epoch)) return;
            updateMigration({ jobId: job.id, submission: 'accepted', step: 'progress', reached: 5 });
            useDataManagementStore.getState().notifyJobsChanged();
        } catch (error) {
            if (!isCurrentEpoch(epoch)) return;
            const workflowStep = readWorkflowStep(error);
            if ((error instanceof ApiError && error.status === 409) || workflowStep === 'review') {
                updateMigration({
                    submission: 'idle',
                    reviewKey: null,
                    acknowledged: false,
                    mirrorPhrase: '',
                    step: 'review',
                    reviewError: errorMessage(error, 'The review is no longer current. Run it again.'),
                });
                return;
            }
            if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                updateMigration({ submission: 'idle' });
                setMessage(errorMessage(error, 'Migration could not be queued.'));
                return;
            }
            updateMigration({ submission: 'uncertain' });
            useDataManagementStore.getState().notifyJobsChanged();
            setMessage(
                'The request failed after submission may have started. Check Job history before retrying.',
            );
        }
    };

    return (
        <div>
            {sectionHeading(
                'Confirm and start migration',
                'Review the normalized plan summary, acknowledge the operational impact, then submit the durable migration job once.',
            )}
            <div className="grid gap-3 @3xl:grid-cols-2">
                <div className="rounded-xl border border-edge bg-surface-1 p-3">
                    <h4 className="text-sm font-semibold text-text-1">Server-normalized plan</h4>
                    <DmMetricGrid
                        className="mt-2"
                        items={[
                            { label: 'Principal scopes', value: formatNumber(selectedScopeCount(state)) },
                            {
                                label: 'Document handling',
                                value: TARGET_TYPES.some((type) => state.scopes[type].includeDocuments)
                                    ? 'Included'
                                    : 'Skipped',
                            },
                            { label: 'Mode', value: MIGRATION_MODE_LABELS[state.mode] },
                            {
                                label: 'Creates / updates',
                                value: `${formatNumber(outcomes.create_count)} / ${formatNumber(outcomes.update_count)}`,
                            },
                            { label: 'Deletes', value: formatNumber(outcomes.delete_count) },
                            { label: 'Conflicts', value: formatNumber(outcomes.conflict_count) },
                        ]}
                    />
                </div>
                <div className="rounded-xl border border-edge bg-surface-1 p-3">
                    <h4 className="text-sm font-semibold text-text-1">Authorization</h4>
                    <p className="mt-1 text-sm text-text-3">
                        Review fingerprint:{' '}
                        <span className="break-all font-mono text-xs">
                            {review?.review_fingerprint || 'Not available'}
                        </span>
                    </p>
                    <p className="mt-1 text-sm text-text-3">
                        Authorization expires in{' '}
                        {formatNumber(secondsUntil(review?.authorization_expires_at, now))} seconds.
                    </p>
                </div>
            </div>
            {state.mode === 'mirror_with_deletions' ? (
                <DmNotice tone="danger" className="mt-3">
                    Only migration-created destination items may be deleted. Unowned destination data is kept
                    and reported as a conflict.
                </DmNotice>
            ) : null}
            {state.mode === 'mirror_with_deletions' ? (
                <div className="mt-3">
                    <DmPhraseField
                        phrase={MIRROR_CONFIRMATION_PHRASE}
                        value={state.mirrorPhrase}
                        disabled={disabled}
                        onChange={(mirrorPhrase) => updateMigration({ mirrorPhrase })}
                    />
                </div>
            ) : null}
            <label className="mt-4 flex items-start gap-2 text-sm text-text-2">
                <input
                    type="checkbox"
                    className="mt-1"
                    checked={state.acknowledged}
                    disabled={disabled}
                    onChange={(event) => updateMigration({ acknowledged: event.target.checked })}
                />
                <span>
                    I reviewed the plan, the destination checks, the warnings and the operational impact.
                </span>
            </label>
            {message ? (
                <DmNotice
                    tone={state.submission === 'uncertain' ? 'warning' : 'danger'}
                    role="alert"
                    className="mt-3"
                    action={
                        state.submission === 'uncertain' ? (
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                onClick={() => onNavigate(DM_SECTION_IDS.jobs)}
                            >
                                Check Job history
                            </GlassButton>
                        ) : null
                    }
                >
                    {message}
                </DmNotice>
            ) : null}
            {state.submission === 'uncertain' ? (
                <GlassButton type="button" variant="subtle" size="sm" className="mt-2" onClick={onReattach}>
                    Look for the migration
                </GlassButton>
            ) : null}
            <div className="mt-4 flex flex-wrap items-center gap-2">
                <GlassButton
                    type="button"
                    variant={state.mode === 'mirror_with_deletions' ? 'danger' : 'primary'}
                    size="md"
                    disabled={!executable}
                    onClick={() => void execute()}
                >
                    {state.submission === 'submitting' ? (
                        <Loader2 size={14} className="animate-spin" />
                    ) : (
                        <Play size={14} />
                    )}
                    {dirty > 0 ? 'Save and start migration' : 'Start migration'}
                </GlassButton>
                <span className="text-xs text-text-3">
                    {migrationStepIssue('review', state, values) ??
                        (executable
                            ? 'Ready to submit.'
                            : 'Complete acknowledgement and confirmation to start.')}
                </span>
            </div>
            {dialog}
        </div>
    );
}

function ProgressStep({ state, onNavigate }: Pick<PanelProps, 'state' | 'onNavigate'>) {
    const updateMigration = useDataManagementStore((store) => store.updateMigration);
    const resetMigration = useDataManagementStore((store) => store.resetMigration);
    const focusJob = useDataManagementStore((store) => store.focusJob);
    const trackRequest = useDataManagementStore((store) => store.trackRequest);
    const now = useNow();
    const [job, setJob] = useState<DataManagementJob | null>(null);
    const [pollError, setPollError] = useState<string | null>(null);
    const [paused, setPaused] = useState(false);
    const [cancelOpen, setCancelOpen] = useState(false);
    const [cancelReason, setCancelReason] = useState('Canceled by administrator.');
    const previousActive = useRef(false);
    const loadInFlight = useRef(false);
    const jobId = state.jobId;
    const jobIdRef = useRef(jobId);
    jobIdRef.current = jobId;
    const active = Boolean(job && isActiveJob(job.status) && !paused);

    const load = async () => {
        if (!jobId || loadInFlight.current) return;
        const requestedId = jobId;
        const epoch = currentEpoch();
        loadInFlight.current = true;
        try {
            const next = await getJobProgress(requestedId);
            if (!isCurrentEpoch(epoch) || jobIdRef.current !== requestedId) return;
            setJob(next);
            setPollError(null);
            setPaused(false);
            const nextActive = isActiveJob(next.status);
            if (previousActive.current && !nextActive) {
                useDataManagementStore.getState().notifyJobsChanged();
                useDataManagementStore.getState().notifyBackupsChanged();
            }
            previousActive.current = nextActive;
        } catch (error) {
            if (!isCurrentEpoch(epoch) || jobIdRef.current !== requestedId) return;
            setPollError(errorMessage(error, 'Progress could not be refreshed.'));
            setPaused(true);
        } finally {
            loadInFlight.current = false;
        }
    };

    useEffect(() => {
        void load();
    }, [jobId]);
    useInterval(
        () => {
            void load();
        },
        active ? JOB_POLL_INTERVAL_MS : null,
    );

    const retry = async () => {
        if (!jobId) return;
        const epoch = currentEpoch();
        try {
            const next = await trackRequest(retryJob(jobId));
            if (!isCurrentEpoch(epoch)) return;
            setJob(next);
            updateMigration({ submission: 'accepted' });
            useDataManagementStore.getState().notifyJobsChanged();
        } catch (error) {
            if (!isCurrentEpoch(epoch)) return;
            setPollError(errorMessage(error, 'Retry could not be queued.'));
        }
    };

    const cancel = async () => {
        if (!jobId) return;
        const epoch = currentEpoch();
        try {
            const next = await trackRequest(cancelJob(jobId, cancelReason));
            if (!isCurrentEpoch(epoch)) return;
            setJob(next);
            setCancelOpen(false);
            useDataManagementStore.getState().notifyJobsChanged();
        } catch (error) {
            if (!isCurrentEpoch(epoch)) return;
            setPollError(errorMessage(error, 'Cancel request failed.'));
        }
    };

    const percent = progressPercent(job?.progress as JsonRecord | undefined);
    const terminal = Boolean(job && isTerminalJob(job.status));
    return (
        <div>
            {sectionHeading(
                'Monitor migration progress',
                'Follow the durable job, recover with retry or resume, and download manifests when available.',
                job ? <DmStatusPill status={job.status} /> : null,
            )}
            {!jobId ? <DmNotice tone="warning">No migration job is attached yet.</DmNotice> : null}
            {pollError ? (
                <DmNotice
                    tone="warning"
                    role="alert"
                    className="mb-3"
                    action={
                        <GlassButton type="button" variant="subtle" size="sm" onClick={() => void load()}>
                            Resume updates
                        </GlassButton>
                    }
                >
                    {pollError}
                </DmNotice>
            ) : null}
            {job ? (
                <div className="grid gap-4">
                    <div className="rounded-xl border border-edge bg-surface-1 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="min-w-0 break-all text-sm font-semibold text-text-1">{job.id}</p>
                            <p className="text-sm text-text-2">
                                Current step: {humanizeToken(job.progress?.current_step) || 'Waiting'}
                            </p>
                        </div>
                        <div
                            className="mt-3 h-3 overflow-hidden rounded-full bg-surface-sunken"
                            role="progressbar"
                            aria-valuenow={isActiveJob(job.status) ? undefined : percent}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuetext={
                                isActiveJob(job.status) ? 'Migration is running' : `${percent}% complete`
                            }
                        >
                            <div
                                className={clsx(
                                    'h-full rounded-full bg-accent transition-all',
                                    isActiveJob(job.status) && 'w-1/2 animate-pulse',
                                )}
                                style={isActiveJob(job.status) ? undefined : { width: `${percent}%` }}
                            />
                        </div>
                        <p className={clsx('mt-2 text-sm', job.last_error ? 'text-danger' : 'text-text-3')}>
                            {job.last_error || job.last_message || 'Waiting for job messages.'}
                        </p>
                    </div>
                    <DmMetricGrid items={migrationLiveMetrics(job, now)} label="Migration live metrics" />
                    <div className="flex flex-wrap gap-2">
                        {job.can_retry ? (
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                onClick={() => void retry()}
                            >
                                <RotateCcw size={14} />
                                {retryLabel(job)}
                            </GlassButton>
                        ) : null}
                        {job.can_cancel ? (
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                onClick={() => setCancelOpen(true)}
                            >
                                <Ban size={14} />
                                Cancel
                            </GlassButton>
                        ) : null}
                        <GlassButton
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                                focusJob(job.id);
                                onNavigate(DM_SECTION_IDS.jobs);
                            }}
                        >
                            Open in Job history
                        </GlassButton>
                        <a
                            className="inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-text-2 hover:bg-surface-2"
                            href={migrationManifestUrl(job.id)}
                            download
                        >
                            Download manifest
                        </a>
                        <a
                            className="inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-text-2 hover:bg-surface-2"
                            href={migrationManifestUrl(job.id, true)}
                            download
                        >
                            Download failures
                        </a>
                        {terminal ? (
                            <GlassButton type="button" variant="primary" size="sm" onClick={resetMigration}>
                                <Square size={14} />
                                Start a new migration
                            </GlassButton>
                        ) : null}
                    </div>
                </div>
            ) : null}
            {cancelOpen ? (
                <ConfirmDialog
                    title="Cancel migration?"
                    description="The server records the cancel request and stops at the next safe checkpoint."
                    confirmLabel="Cancel migration"
                    cancelLabel="Keep running"
                    confirmIcon={<AlertCircle size={14} />}
                    onConfirm={() => void cancel()}
                    onClose={() => setCancelOpen(false)}
                >
                    <label className="block text-sm text-text-2">
                        Reason
                        <input
                            className={clsx(inputClass, 'mt-1')}
                            value={cancelReason}
                            onChange={(event) => setCancelReason(event.target.value)}
                        />
                    </label>
                </ConfirmDialog>
            ) : null}
        </div>
    );
}

export function MigrationStepPanel(props: PanelProps) {
    if (props.step === 'target') return <TargetStep values={props.values} disabled={props.disabled} />;
    if (props.step === 'scope') return <ScopeStep state={props.state} disabled={props.disabled} />;
    if (props.step === 'options')
        return (
            <OptionsStep
                state={props.state}
                values={props.values}
                disabled={props.disabled}
                onGuide={props.onGuide}
            />
        );
    if (props.step === 'review')
        return (
            <ReviewStep
                state={props.state}
                values={props.values}
                disabled={props.disabled}
                onStep={props.onStep}
            />
        );
    if (props.step === 'confirm')
        return (
            <ConfirmStep
                state={props.state}
                values={props.values}
                disabled={props.disabled}
                onNavigate={props.onNavigate}
                onReattach={props.onReattach}
            />
        );
    return <ProgressStep state={props.state} onNavigate={props.onNavigate} />;
}
