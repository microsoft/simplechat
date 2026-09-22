// publicWorkspaceStore.ts
//
// A read-only public workspace is loaded by explicit URL id. Reads never target a workspace
// by the account's saved active selection, so the store only needs load / revalidate / clear.
// There is deliberately no activate/reconcile machinery: nothing here is load-bearing for a
// document read, and the page fires PUBLIC_WORKSPACES.setActive separately and non-blocking.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import { fetchPublicWorkspaceContext, requireWorkspaceId, type PublicWorkspaceContext } from '../lib/workspaceContext';
import { useBootstrapStore } from './bootstrapStore';

export class PublicWorkspaceRequestSuperseded extends Error {
    constructor() {
        super('Workspace selection or sign-in changed while loading.');
        this.name = 'PublicWorkspaceRequestSuperseded';
    }
}

interface PublicWorkspaceState {
    context: PublicWorkspaceContext | null;
    pendingWorkspaceId: string | null;
    loading: boolean;
    refreshing: boolean;
    error: string | null;
    load: (workspaceId: string) => Promise<PublicWorkspaceContext>;
    revalidate: (workspaceId: string) => Promise<PublicWorkspaceContext>;
    clear: () => void;
}

const EMPTY_STATE = {
    context: null,
    pendingWorkspaceId: null,
    loading: false,
    refreshing: false,
    error: null,
};

let sequence = 0;
let readController: AbortController | null = null;

function currentViewer(): string {
    const bootstrap = useBootstrapStore.getState();
    if (bootstrap.authExpired || !bootstrap.data?.user?.id) {
        throw new Error('Sign in again before opening a workspace.');
    }
    return requireWorkspaceId(bootstrap.data.user.id);
}

function assertCurrent(token: number, viewerId: string): void {
    const bootstrap = useBootstrapStore.getState();
    if (token !== sequence || bootstrap.authExpired || bootstrap.data?.user?.id !== viewerId) {
        throw new PublicWorkspaceRequestSuperseded();
    }
}

function beginRead(): { token: number; signal: AbortSignal } {
    readController?.abort();
    readController = new AbortController();
    return { token: ++sequence, signal: readController.signal };
}

function failureMessage(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError) {
        if (cause.status === 401) return 'Your session has expired. Sign in again.';
        if (cause.status === 403) return 'You do not have access to that public workspace.';
        if (cause.status === 404) return 'That public workspace no longer exists.';
    }
    return fallback;
}

export const usePublicWorkspaceStore = create<PublicWorkspaceState>((set, get) => ({
    ...EMPTY_STATE,

    clear: () => {
        ++sequence;
        readController?.abort();
        readController = null;
        set({ ...EMPTY_STATE });
    },

    load: async (workspaceId) => {
        const viewerId = currentViewer();
        requireWorkspaceId(workspaceId);
        const { token, signal } = beginRead();
        set({ ...EMPTY_STATE, loading: true, pendingWorkspaceId: workspaceId });
        try {
            const context = await fetchPublicWorkspaceContext(workspaceId, viewerId, signal);
            assertCurrent(token, viewerId);
            set({ context, loading: false, pendingWorkspaceId: null });
            return context;
        } catch (cause) {
            assertCurrent(token, viewerId);
            const message = failureMessage(cause, 'Could not load this workspace. Please retry.');
            set({ loading: false, pendingWorkspaceId: null, error: message });
            throw new Error(message, { cause });
        }
    },

    revalidate: async (workspaceId) => {
        const viewerId = currentViewer();
        const previous = get().context;
        if (previous?.scope.id !== workspaceId || previous.viewer_id !== viewerId) {
            throw new Error('Load the selected workspace before refreshing its details.');
        }
        const { token, signal } = beginRead();
        set({ refreshing: true, error: null });
        try {
            const context = await fetchPublicWorkspaceContext(workspaceId, viewerId, signal);
            assertCurrent(token, viewerId);
            set({ context, refreshing: false });
            return context;
        } catch (cause) {
            assertCurrent(token, viewerId);
            const denied = cause instanceof ApiError && [401, 403, 404].includes(cause.status);
            const message = failureMessage(cause, 'Workspace access could not be refreshed. Please retry.');
            set({ context: denied ? null : previous, refreshing: false, error: message });
            throw new Error(message, { cause });
        }
    },
}));

useBootstrapStore.subscribe((state, previous) => {
    if (state.data?.user?.id !== previous.data?.user?.id || (state.authExpired && !previous.authExpired)) {
        usePublicWorkspaceStore.getState().clear();
    }
});
