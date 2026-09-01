// toastStore.ts
// Transient user-facing notifications.
//
// Several actions in the chat page succeed or fail entirely server-side — exports, masking,
// attempt switching. Without somewhere to say so, a failure looks identical to a dead
// button, which is the exact complaint that motivated this work.

import { create } from 'zustand';

export type ToastTone = 'success' | 'error' | 'info';

export interface Toast {
    id: number;
    tone: ToastTone;
    message: string;
}

interface ToastState {
    toasts: Toast[];
    push: (tone: ToastTone, message: string) => void;
    dismiss: (id: number) => void;
}

/** How long a toast stays before dismissing itself. Errors linger, since they need reading. */
const TOAST_TTL: Record<ToastTone, number> = {
    success: 3200,
    info: 3800,
    error: 6500,
};

let nextId = 1;

export const useToastStore = create<ToastState>((set, get) => ({
    toasts: [],

    push: (tone, message) => {
        const id = nextId;
        nextId += 1;

        set((state) => ({ toasts: [...state.toasts, { id, tone, message }] }));

        window.setTimeout(() => {
            get().dismiss(id);
        }, TOAST_TTL[tone]);
    },

    dismiss: (id) => {
        set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
    },
}));

/** Convenience for non-component code, which cannot use the hook form. */
export const toast = {
    success: (message: string) => useToastStore.getState().push('success', message),
    error: (message: string) => useToastStore.getState().push('error', message),
    info: (message: string) => useToastStore.getState().push('info', message),
};
