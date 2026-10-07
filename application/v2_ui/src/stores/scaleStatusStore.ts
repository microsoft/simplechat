// scaleStatusStore.ts
// Live status shared between the Admin Settings Scale cards.
//
// Several Scale cards read the same thing. DAI Metrics, Conversation Cache and Cosmos
// Maintenance are all drawn from one app maintenance status, and the server-rendered page
// refreshes the three together; here they share one fetch, so a refresh in any of them
// updates all three and opening the page never asks for it three times. Cosmos DB
// Throughput and Cosmos Metrics share the throughput status the same way, along with the
// confirmation in front of a capacity change, which either card can ask for.
//
// The cards are siblings rendered from a declarative schema, so a store is how they talk.
// Cosmos DB Throughput, for instance, asks Cosmos Metrics to select a container through
// `requestContainerFocus`, and either card can ask for the capacity confirmation the page
// draws once.

import { create } from 'zustand';
import { ApiError, api } from '../lib/apiClient';
import {
    describeCosmosThroughputStatus,
    type CosmosAccessValidation,
    type CosmosScaleResult,
    type CosmosThroughputStatus,
} from '../lib/cosmosThroughput';
import { formatRu, type ToneText } from '../lib/scaleFormat';
import type { AppMaintenanceStatus } from '../lib/scaleMaintenance';

const MAINTENANCE_STATUS_PATH = '/api/admin/settings/app-maintenance/status';
const THROUGHPUT_PATH = '/api/admin/settings/cosmos-throughput';

/** A capacity change waiting for the administrator to confirm it. */
export interface PendingCapacityAction {
    kind: 'scale' | 'convert';
    direction?: 'up' | 'down';
    /** Empty for the database; a container name otherwise. */
    containerName: string;
}

interface MaintenanceState {
    data: AppMaintenanceStatus | null;
    loading: boolean;
    error: string | null;
    loadedAt: number | null;
}

interface ThroughputState {
    status: CosmosThroughputStatus | null;
    /** `saved` while showing the snapshot automation last stored; `live` after a refresh. */
    source: 'saved' | 'live' | null;
    loading: boolean;
    validating: boolean;
    acting: boolean;
    message: ToneText | null;
    validation: CosmosAccessValidation | null;
    loadedAt: number | null;
}

interface ScaleStatusState {
    maintenance: MaintenanceState;
    /** Read the app maintenance status. Concurrent callers share one request. */
    loadMaintenance: (options?: { force?: boolean }) => Promise<AppMaintenanceStatus | null>;
    /** Merge part of a status a manual run returned, so cards update before the next refresh. */
    mergeMaintenance: (partial: Partial<AppMaintenanceStatus>) => void;

    /** Bumped to ask the Redis Metrics card to refresh, after a successful connection test. */
    redisRefreshRevision: number;
    requestRedisRefresh: () => void;

    throughput: ThroughputState;
    seedThroughput: (status: CosmosThroughputStatus) => void;
    refreshThroughput: () => Promise<void>;
    validateThroughputAccess: (payload: Record<string, unknown>) => Promise<void>;
    performCapacityAction: (action: PendingCapacityAction) => Promise<boolean>;

    pendingCapacityAction: PendingCapacityAction | null;
    requestCapacityAction: (action: PendingCapacityAction) => void;
    clearCapacityAction: () => void;

    /**
     * A container the Cosmos Metrics workbench should select, asked for from elsewhere --
     * the throughput card's "Container policies" link, for one. Cleared once acted on.
     */
    containerFocus: { name: string | null; revision: number };
    requestContainerFocus: (name?: string | null) => void;
}

let maintenanceRequest: Promise<AppMaintenanceStatus | null> | null = null;

function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}

export const useScaleStatusStore = create<ScaleStatusState>((set, get) => ({
    maintenance: { data: null, loading: false, error: null, loadedAt: null },

    loadMaintenance: async (options = {}) => {
        const current = get().maintenance;
        if (!options.force && current.data) {
            return current.data;
        }
        if (maintenanceRequest) {
            return maintenanceRequest;
        }
        set((state) => ({ maintenance: { ...state.maintenance, loading: true, error: null } }));
        maintenanceRequest = (async () => {
            try {
                const data = await api.get<AppMaintenanceStatus>(MAINTENANCE_STATUS_PATH);
                set({ maintenance: { data, loading: false, error: null, loadedAt: Date.now() } });
                return data;
            } catch (error) {
                set((state) => ({
                    maintenance: {
                        ...state.maintenance,
                        loading: false,
                        error: errorMessage(error, 'Failed to load app maintenance status.'),
                    },
                }));
                return null;
            } finally {
                maintenanceRequest = null;
            }
        })();
        return maintenanceRequest;
    },

    mergeMaintenance: (partial) =>
        set((state) => ({
            maintenance: {
                ...state.maintenance,
                data: { ...(state.maintenance.data ?? {}), ...partial },
            },
        })),

    redisRefreshRevision: 0,
    requestRedisRefresh: () => set((state) => ({ redisRefreshRevision: state.redisRefreshRevision + 1 })),

    throughput: {
        status: null,
        source: null,
        loading: false,
        validating: false,
        acting: false,
        message: null,
        validation: null,
        loadedAt: null,
    },

    seedThroughput: (status) =>
        set((state) =>
            state.throughput.status
                ? state
                : { throughput: { ...state.throughput, status, source: 'saved' } },
        ),

    refreshThroughput: async () => {
        set((state) => ({
            throughput: {
                ...state.throughput,
                loading: true,
                validation: null,
                message: { text: 'Loading Cosmos throughput status…', tone: 'info' },
            },
        }));
        try {
            const status = await api.get<CosmosThroughputStatus>(`${THROUGHPUT_PATH}/status`);
            set((state) => ({
                throughput: {
                    ...state.throughput,
                    status,
                    source: 'live',
                    loading: false,
                    loadedAt: Date.now(),
                    message: describeCosmosThroughputStatus(status),
                },
            }));
        } catch (error) {
            set((state) => ({
                throughput: {
                    ...state.throughput,
                    loading: false,
                    message: { text: errorMessage(error, 'Failed to load Cosmos throughput status.'), tone: 'danger' },
                },
            }));
        }
    },

    validateThroughputAccess: async (payload) => {
        set((state) => ({
            throughput: {
                ...state.throughput,
                validating: true,
                validation: null,
                message: { text: 'Validating Cosmos throughput configuration and access…', tone: 'info' },
            },
        }));
        try {
            const validation = await api.post<CosmosAccessValidation>(`${THROUGHPUT_PATH}/validate-access`, payload);
            // A validation reads Azure with the values on screen, which may name another
            // target or carry draft policies. Its status stays with the result, so manual
            // changes keep estimating from the last status read for the saved settings.
            set((state) => ({
                throughput: {
                    ...state.throughput,
                    validating: false,
                    validation,
                    message: null,
                },
            }));
        } catch (error) {
            set((state) => ({
                throughput: {
                    ...state.throughput,
                    validating: false,
                    message: { text: errorMessage(error, 'Failed to validate Cosmos throughput access.'), tone: 'danger' },
                },
            }));
        }
    },

    performCapacityAction: async (action) => {
        const target = action.containerName ? ` for ${action.containerName}` : '';
        set((state) => ({
            throughput: {
                ...state.throughput,
                acting: true,
                message: {
                    text:
                        action.kind === 'convert'
                            ? `Converting manual Cosmos throughput${target} to native autoscale…`
                            : `Submitting the scale-${action.direction} request${target}…`,
                    tone: 'info',
                },
            },
        }));
        try {
            const result =
                action.kind === 'convert'
                    ? await api.post<CosmosScaleResult>(`${THROUGHPUT_PATH}/convert-autoscale`, {
                          container_name: action.containerName,
                      })
                    : await api.post<CosmosScaleResult>(`${THROUGHPUT_PATH}/scale`, {
                          direction: action.direction,
                          container_name: action.containerName,
                      });
            const scope = result.container_name ? ` for ${result.container_name}` : '';
            const done: ToneText =
                action.kind === 'convert'
                    ? {
                          text: `Cosmos throughput${scope} converted from manual ${formatRu(result.from_ru)} to autoscale with a maximum of ${formatRu(result.to_ru)}.`,
                          tone: 'ok',
                      }
                    : {
                          text: `Cosmos throughput${scope} changed from ${formatRu(result.from_ru)} to ${formatRu(result.to_ru)}.`,
                          tone: 'ok',
                      };
            // Still acting until the new status is read, so neither the dialog nor the cards
            // offer another change based on the capacity this one just replaced.
            await get().refreshThroughput();
            // The refresh reports the new status; the outcome of the change is the news.
            set((state) => ({ throughput: { ...state.throughput, acting: false, message: done } }));
            return true;
        } catch (error) {
            set((state) => ({
                throughput: {
                    ...state.throughput,
                    acting: false,
                    message: {
                        text: errorMessage(
                            error,
                            action.kind === 'convert'
                                ? 'Cosmos throughput mode conversion failed.'
                                : 'Cosmos throughput scale request failed.',
                        ),
                        tone: 'danger',
                    },
                },
            }));
            return false;
        }
    },

    pendingCapacityAction: null,
    requestCapacityAction: (action) => set({ pendingCapacityAction: action }),
    clearCapacityAction: () => set({ pendingCapacityAction: null }),

    containerFocus: { name: null, revision: 0 },
    requestContainerFocus: (name = null) =>
        set((state) => ({ containerFocus: { name, revision: state.containerFocus.revision + 1 } })),
}));
