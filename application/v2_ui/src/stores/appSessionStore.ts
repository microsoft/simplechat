// appSessionStore.ts
// Runtime sign-in state stays separate from bootstrap so expiry never discards an open draft.

import { create } from 'zustand';

export const SESSION_REQUIRED_MESSAGE = 'Your SimpleChat session needs to be renewed. Sign in again to continue.';

interface AppSessionState {
    status: 'ready' | 'required' | 'changed';
    viewerId: string;
    revision: number;
    requireSignIn(revision: number): void;
    confirmUser(viewerId: string, revision: number): boolean;
}

export const useAppSessionStore = create<AppSessionState>((set, get) => ({
    status: 'ready',
    viewerId: '',
    revision: 0,
    requireSignIn: (revision) => {
        const current = get();
        if (current.revision !== revision || current.status === 'changed') return;
        set({ status: 'required', revision: revision + 1 });
    },
    confirmUser: (viewerId, revision) => {
        const current = get();
        if (!viewerId || current.revision !== revision || current.status === 'changed') return false;
        if (current.viewerId && current.viewerId !== viewerId) {
            set({ status: 'changed', revision: revision + 1 });
            return false;
        }
        if (current.status !== 'ready' || current.viewerId !== viewerId) {
            set({ status: 'ready', viewerId, revision: revision + 1 });
        }
        return true;
    },
}));
