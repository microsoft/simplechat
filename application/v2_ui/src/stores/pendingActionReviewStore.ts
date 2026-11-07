// pendingActionReviewStore.ts

import { createStore } from 'zustand';
import { editorAssistKey } from '../lib/editorAssist';
import type { PendingReviewDraft, PendingReviewHistory, PendingReviewResponse } from '../lib/pendingActionReview';
import type { PendingAction } from '../lib/approvalsApi';

interface PendingReviewState {
    review: PendingReviewResponse | null;
    draft: PendingReviewDraft | null;
    history: readonly PendingReviewHistory[];
    continuationToken: string;
    attribution: 'direct' | 'ai';
    assistTurnId: string;
    load(review: PendingReviewResponse): void;
    edit(draft: PendingReviewDraft, attribution?: 'direct' | 'ai'): void;
    appendHistory(history: readonly PendingReviewHistory[], token: string, older?: boolean): void;
    acceptAssist(action: PendingAction, version: string, turnId: string): void;
    clear(): void;
}

/** One editor visit's working copy. Durable material is always reread from the owner API. */
export function createPendingReviewStore() {
    return createStore<PendingReviewState>()((set) => ({
        review: null, draft: null, history: [], continuationToken: '', attribution: 'direct', assistTurnId: '',
        load: (review) => set({
            review, draft: review.draft, history: review.history ?? [],
            continuationToken: review.continuation_token ?? '', attribution: 'direct', assistTurnId: '',
        }),
        edit: (draft, attribution = 'direct') => set({ draft, attribution }),
        appendHistory: (history, continuationToken, older = false) => set((state) => ({
            history: [...new Map((older ? [...history, ...state.history] : [...state.history, ...history])
                .map((item) => [item.id, item])).values()].slice(-100),
            continuationToken,
        })),
        acceptAssist: (action, version, assistTurnId) => set((state) => ({
            review: state.review ? { ...state.review, pending_action: action, version } : null, assistTurnId,
        })),
        clear: () => set({ review: null, draft: null, history: [], continuationToken: '', attribution: 'direct', assistTurnId: '' }),
    }));
}

export function pendingReviewDirty(saved: PendingReviewDraft | null, draft: PendingReviewDraft | null): boolean {
    return Boolean(saved && draft && editorAssistKey(saved) !== editorAssistKey(draft));
}
