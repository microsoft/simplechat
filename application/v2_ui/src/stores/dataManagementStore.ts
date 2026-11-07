// dataManagementStore.ts
// Shared state for Admin Settings > Backup & Recovery.
//
// The page unmounts a section card whenever the category or search filter hides it, so
// anything an administrator has invested effort in -- unsaved backup settings, a migration
// half way through its six steps, an unlocked Cosmos editor with an edited document -- has
// to live outside the cards. It lives here, for the lifetime of the Admin Settings page:
// the page calls `reset()` when it unmounts, which is the same lifetime its own draft has.
//
// Two rules keep asynchronous work honest:
//
// - Every request that completes after a reset is ignored. `reset()` advances an epoch, and
//   anything that writes into the store after awaiting checks it first (`isCurrentEpoch`).
// - Aborting a write is never treated as having undone it. A queued job may already exist
//   on the server, so callers refresh job history rather than assume a request failed.
//
// The data-management settings document is saved through its own API. The page's Save bar
// counts its unsaved edits and saves them after the main settings; actions that must run
// against saved settings (queueing, reviews, retention cleanup) go through `ensureReadyFor`.

import { useMemo } from 'react';
import { create } from 'zustand';
import {
    errorMessage,
    loadDataManagementSettings,
    saveDataManagementSettings,
    type BackupFilters,
    type CosmosContainer,
    type CosmosQueryItem,
    type DmDraft,
    type DmEditableKey,
    type DmSettings,
    type JobFilters,
    type JsonRecord,
} from '../lib/dataManagement';
import {
    DM_DEPENDENT_MAIN_KEYS,
    FIRST_PAGE,
    KEY_GENERATION_DEPENDENT_MAIN_KEYS,
    buildDmSettingsPayload,
    dmDirtyKeys,
    dmSectionStatuses,
    formatCosmosDocument,
    initialMigrationState,
    migrationReviewKey,
    readDmValues,
    validateDmValues,
    type DmValues,
    type MigrationStep,
    type MigrationWizardState,
    type PagerState,
} from '../lib/dataManagementLogic';
import type { SectionStatus } from '../lib/adminSections';

type LoadStatus = 'idle' | 'loading' | 'ready' | 'error';

/** Actions that save pending backup settings first, as the classic page does. */
export type SaveFirstPurpose =
    'queue-backup' | 'retention-cleanup' | 'restore-review' | 'restore-queue' | 'migration-execute';

export type ReadinessPurpose = SaveFirstPurpose | 'generate-key';

export type ReadyResult =
    | { ok: true }
    | { ok: false; reason: 'save-all-required'; message: string; keys: string[] }
    | { ok: false; reason: 'invalid' | 'save-failed' | 'not-loaded'; message: string };

export interface SaveOutcome {
    ok: boolean;
    error?: string;
    invalid?: boolean;
}

export interface InventoryUiState {
    filters: Required<Pick<BackupFilters, 'status' | 'scheduled' | 'pageSize'>> & {
        backupType: '' | 'full' | 'partial';
        createdFrom: string;
        createdTo: string;
    };
    pager: PagerState;
    selectedId: string | null;
}

export interface JobsUiState {
    filters: Required<Pick<JobFilters, 'status' | 'scheduled' | 'pageSize'>> & {
        operation: '' | 'backup' | 'restore' | 'migration' | 'dry_run';
        createdFrom: string;
        createdTo: string;
    };
    pager: PagerState;
    selectedId: string | null;
}

export interface CosmosOpenDocument {
    container: string;
    id: string;
    partitionKey: unknown;
    partitionKeyPath: string;
    etag: string | null;
    original: JsonRecord;
    text: string;
    editable: boolean;
}

export interface CosmosEditorSession {
    unlocked: boolean;
    containers: CosmosContainer[];
    container: string;
    pageSize: number;
    query: string;
    results: CosmosQueryItem[];
    continuationToken: string | null;
    queryMode: 'empty' | 'custom' | null;
    queryStatus: string;
    document: CosmosOpenDocument | null;
}

export const INITIAL_INVENTORY: InventoryUiState = {
    filters: {
        status: 'available',
        scheduled: 'all',
        pageSize: 25,
        backupType: '',
        createdFrom: '',
        createdTo: '',
    },
    pager: FIRST_PAGE,
    selectedId: null,
};

export const INITIAL_JOBS: JobsUiState = {
    filters: {
        status: '',
        scheduled: 'all',
        pageSize: 25,
        operation: '',
        createdFrom: '',
        createdTo: '',
    },
    pager: FIRST_PAGE,
    selectedId: null,
};

export const INITIAL_COSMOS: CosmosEditorSession = {
    unlocked: false,
    containers: [],
    container: '',
    pageSize: 100,
    query: '',
    results: [],
    continuationToken: null,
    queryMode: null,
    queryStatus: '',
    document: null,
};

interface DataManagementState {
    status: LoadStatus;
    loadError: string | null;
    /** The saved document as the server last returned it (sanitized, secrets redacted). */
    settings: DmSettings | null;
    /** Unsaved edits, keyed by settings key. */
    draft: DmDraft;
    saving: boolean;
    saveError: string | null;
    fieldErrors: Partial<Record<DmEditableKey, string>>;

    /** Main-settings keys with unsaved edits, published by the page for the save guard. */
    mainDirtyKeys: string[];
    /** The page's save coordinator, which saves main settings and then these. */
    saveAllHandler: (() => Promise<boolean>) | null;
    /** State-changing requests in flight, which the page's navigation guard respects. */
    pendingRequests: number;

    jobsRevision: number;
    backupsRevision: number;
    /** A job another card asked the Jobs workbench to open. */
    focusJobId: string | null;

    migration: MigrationWizardState;
    /** A step another card asked the migration workbench to show. */
    migrationFocusStep: MigrationStep | null;
    cosmos: CosmosEditorSession;
    inventory: InventoryUiState;
    jobs: JobsUiState;

    ensureLoaded: () => Promise<void>;
    reload: () => Promise<void>;
    setValue: (key: DmEditableKey, value: unknown) => void;
    discard: () => void;
    save: () => Promise<SaveOutcome>;
    ensureReadyFor: (purpose: ReadinessPurpose) => Promise<ReadyResult>;
    rebase: (settings: DmSettings) => void;
    trackRequest: <T>(promise: Promise<T>) => Promise<T>;
    notifyJobsChanged: () => void;
    notifyBackupsChanged: () => void;
    focusJob: (jobId: string | null) => void;
    updateMigration: (
        update: Partial<MigrationWizardState> | ((state: MigrationWizardState) => MigrationWizardState),
    ) => void;
    resetMigration: () => void;
    requestMigrationStep: (step: MigrationStep | null) => void;
    updateCosmos: (
        update: Partial<CosmosEditorSession> | ((state: CosmosEditorSession) => CosmosEditorSession),
    ) => void;
    lockCosmos: () => void;
    updateInventory: (
        update: Partial<InventoryUiState> | ((state: InventoryUiState) => InventoryUiState),
    ) => void;
    updateJobs: (update: Partial<JobsUiState> | ((state: JobsUiState) => JobsUiState)) => void;
    setMainDirtyKeys: (keys: string[]) => void;
    registerSaveAll: (handler: (() => Promise<boolean>) | null) => void;
    reset: () => void;
}

function initialState() {
    return {
        status: 'idle' as LoadStatus,
        loadError: null,
        settings: null,
        draft: {},
        saving: false,
        saveError: null,
        fieldErrors: {},
        mainDirtyKeys: [],
        saveAllHandler: null,
        pendingRequests: 0,
        jobsRevision: 0,
        backupsRevision: 0,
        focusJobId: null,
        migration: initialMigrationState(),
        migrationFocusStep: null,
        cosmos: { ...INITIAL_COSMOS },
        inventory: { ...INITIAL_INVENTORY },
        jobs: { ...INITIAL_JOBS },
    };
}

let epoch = 0;
let loadController: AbortController | null = null;
let loadPromise: Promise<void> | null = null;

/** The current store lifetime. Capture it before awaiting; compare it before writing back. */
export function currentEpoch(): number {
    return epoch;
}

export function isCurrentEpoch(token: number): boolean {
    return token === epoch;
}

function applyUpdate<T>(current: T, update: Partial<T> | ((state: T) => T)): T {
    return typeof update === 'function' ? (update as (state: T) => T)(current) : { ...current, ...update };
}

export const useDataManagementStore = create<DataManagementState>((set, get) => ({
    ...initialState(),

    ensureLoaded: () => {
        const { status } = get();
        if (status === 'ready') return Promise.resolve();
        if (status === 'loading' && loadPromise) return loadPromise;
        return get().reload();
    },

    reload: () => {
        loadController?.abort();
        const controller = new AbortController();
        loadController = controller;
        const token = epoch;
        set({ status: 'loading', loadError: null });
        loadPromise = loadDataManagementSettings(controller.signal)
            .then((settings) => {
                if (!isCurrentEpoch(token) || controller.signal.aborted) return;
                set({ settings, status: 'ready', loadError: null });
            })
            .catch((error: unknown) => {
                if (!isCurrentEpoch(token) || controller.signal.aborted) return;
                set({
                    status: 'error',
                    loadError: errorMessage(error, 'Backup settings could not be loaded.'),
                });
            })
            .finally(() => {
                if (loadController === controller) {
                    loadController = null;
                    loadPromise = null;
                }
            });
        return loadPromise;
    },

    setValue: (key, value) =>
        set((state) => {
            const fieldErrors = { ...state.fieldErrors };
            delete fieldErrors[key];
            return { draft: { ...state.draft, [key]: value }, fieldErrors, saveError: null };
        }),

    discard: () => set({ draft: {}, fieldErrors: {}, saveError: null }),

    save: async () => {
        const state = get();
        if (!state.settings) {
            return { ok: false, error: 'Backup settings have not loaded yet.' };
        }
        const values = readDmValues(state.settings, state.draft);
        const errors = validateDmValues(values);
        if (Object.keys(errors).length) {
            const message = 'Fix the highlighted Backup & Recovery settings, then save again.';
            set({ fieldErrors: errors, saveError: message });
            return { ok: false, error: message, invalid: true };
        }
        const submitted = { ...state.draft };
        const token = epoch;
        set({ saving: true, saveError: null, fieldErrors: {} });
        try {
            const saved = await saveDataManagementSettings(buildDmSettingsPayload(values));
            if (!isCurrentEpoch(token))
                return { ok: false, error: 'The page was closed before the save finished.' };
            // An edit made while the save was in flight was not part of it, so it stays.
            const remaining: DmDraft = {};
            for (const [key, value] of Object.entries(get().draft) as [DmEditableKey, unknown][]) {
                if (!Object.prototype.hasOwnProperty.call(submitted, key) || submitted[key] !== value) {
                    remaining[key] = value;
                }
            }
            // A migration review run against exactly what was just saved is still current,
            // but the response masks any secret that was typed and the draft entry is gone,
            // so its key is restated in the saved form. The server still compares its own
            // fingerprint of the saved settings when the job is queued.
            const migration = get().migration;
            const reviewedWhatWasSaved = Boolean(
                migration.review &&
                migration.reviewKey &&
                migration.reviewKey === migrationReviewKey(migration, values),
            );
            set({
                settings: saved,
                draft: remaining,
                saving: false,
                saveError: null,
                ...(reviewedWhatWasSaved
                    ? {
                          migration: {
                              ...migration,
                              reviewKey: migrationReviewKey(migration, readDmValues(saved, {})),
                          },
                      }
                    : {}),
            });
            return { ok: true };
        } catch (error) {
            if (!isCurrentEpoch(token))
                return { ok: false, error: 'The page was closed before the save finished.' };
            const message = errorMessage(error, 'Backup & Recovery settings could not be saved.');
            set({ saving: false, saveError: message });
            return { ok: false, error: message };
        }
    },

    ensureReadyFor: async (purpose) => {
        if (!get().settings) {
            await get().ensureLoaded();
        }
        const state = get();
        if (!state.settings) {
            return { ok: false, reason: 'not-loaded', message: 'Backup settings could not be loaded.' };
        }
        const savesFirst = purpose !== 'generate-key';
        const dmDirty = dmDirtyKeys(state.settings, state.draft).length > 0;
        const watched =
            purpose === 'generate-key'
                ? [...DM_DEPENDENT_MAIN_KEYS, ...KEY_GENERATION_DEPENDENT_MAIN_KEYS]
                : DM_DEPENDENT_MAIN_KEYS;
        const pendingMain = state.mainDirtyKeys.filter((key) => watched.includes(key));
        // Backup settings are validated against the saved main settings, so saving them
        // while a key they are checked against has an unsaved edit would check the wrong
        // value. Saving everything first resolves it.
        if (pendingMain.length && (purpose === 'generate-key' || (savesFirst && dmDirty))) {
            return {
                ok: false,
                reason: 'save-all-required',
                keys: pendingMain,
                message:
                    purpose === 'generate-key'
                        ? 'Key Vault or Enhanced Citations settings have unsaved changes. Save all changes first so the key is stored where those settings say.'
                        : 'Enhanced Citations storage settings have unsaved changes, and backup storage is checked against them. Save all changes first.',
            };
        }
        if (savesFirst && dmDirty) {
            const outcome = await get().save();
            if (!outcome.ok) {
                return {
                    ok: false,
                    reason: outcome.invalid ? 'invalid' : 'save-failed',
                    message: outcome.error ?? 'Backup & Recovery settings could not be saved.',
                };
            }
        }
        return { ok: true };
    },

    rebase: (settings) => set({ settings }),

    trackRequest: async <T>(promise: Promise<T>) => {
        const token = epoch;
        set((state) => ({ pendingRequests: state.pendingRequests + 1 }));
        try {
            return await promise;
        } finally {
            if (isCurrentEpoch(token)) {
                set((state) => ({ pendingRequests: Math.max(0, state.pendingRequests - 1) }));
            }
        }
    },

    notifyJobsChanged: () => set((state) => ({ jobsRevision: state.jobsRevision + 1 })),
    notifyBackupsChanged: () => set((state) => ({ backupsRevision: state.backupsRevision + 1 })),
    focusJob: (jobId) => set({ focusJobId: jobId }),

    updateMigration: (update) => set((state) => ({ migration: applyUpdate(state.migration, update) })),
    resetMigration: () => set({ migration: initialMigrationState() }),
    requestMigrationStep: (step) => set({ migrationFocusStep: step }),

    updateCosmos: (update) => set((state) => ({ cosmos: applyUpdate(state.cosmos, update) })),
    lockCosmos: () => set({ cosmos: { ...INITIAL_COSMOS } }),

    updateInventory: (update) => set((state) => ({ inventory: applyUpdate(state.inventory, update) })),
    updateJobs: (update) => set((state) => ({ jobs: applyUpdate(state.jobs, update) })),

    setMainDirtyKeys: (keys) => set({ mainDirtyKeys: keys }),
    registerSaveAll: (handler) => set({ saveAllHandler: handler }),

    reset: () => {
        epoch += 1;
        loadController?.abort();
        loadController = null;
        loadPromise = null;
        // Registrations are cleared too. The page resets on unmount and registers again
        // when it mounts.
        set({ ...initialState() });
    },
}));

/** Every editable value, unsaved edits first. */
export function useDmValues(): DmValues {
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    return useMemo(() => readDmValues(settings, draft), [settings, draft]);
}

/** How many backup settings have unsaved edits, for the page's Save bar. */
export function useDmDirtyCount(): number {
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    return useMemo(() => dmDirtyKeys(settings, draft).length, [settings, draft]);
}

/** Status chips for the Backup & Recovery cards that have a configured state. */
export function useDmSectionStatuses(): Partial<Record<string, SectionStatus>> {
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    return useMemo(() => dmSectionStatuses(settings, draft), [settings, draft]);
}

/** Whether the Cosmos editor holds JSON edits that have not been saved to the database. */
export function selectCosmosEditorDirty(state: { cosmos: CosmosEditorSession }): boolean {
    const document = state.cosmos.document;
    return Boolean(document && document.text !== formatCosmosDocument(document.original));
}
