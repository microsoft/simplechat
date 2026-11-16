// conversationMode.ts
// Only explicit choices are saved; a missing entry continues to use the deployment default.

import { toast } from '../stores/toastStore';

export const CONVERSATION_MODE_PREFIX = 'simplechat:v2:conversation-mode:';

interface ModeChoice {
    choice: boolean | undefined;
    storageFailed: boolean;
}

export interface DraftModeChoice {
    accountId: string;
    draftId: number;
    session: number;
    choice: boolean | undefined;
}

export class ConversationModeMemory {
    private choices = new Map<string, ModeChoice>();
    private draftChoices = new Map<string, boolean>();
    private draftId = 0;
    private session = 0;
    private revision = 0;
    private listeners = new Set<() => void>();
    private storage: () => Storage;

    constructor(storage: () => Storage) {
        this.storage = storage;
    }

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    };

    getRevision = (): number => this.revision;

    private changed(): void {
        this.revision += 1;
        this.listeners.forEach((listener) => listener());
    }

    private key(accountId: string, conversationId: string): string {
        return `${CONVERSATION_MODE_PREFIX}${encodeURIComponent(accountId)}:${encodeURIComponent(conversationId)}`;
    }

    read(accountId: string, conversationId: string | null): ModeChoice {
        if (!conversationId) {
            return { choice: this.draftChoices.get(accountId), storageFailed: false };
        }
        const key = this.key(accountId, conversationId);
        let result = this.choices.get(key);
        // Choices made before identity resolves can be local, but cannot read browser persistence.
        if (!accountId) return result ?? { choice: undefined, storageFailed: false };
        if (!result) {
            try {
                const value = this.storage().getItem(key);
                result = { choice: value === 'on' ? true : value === 'off' ? false : undefined, storageFailed: false };
            } catch {
                result = { choice: undefined, storageFailed: true };
            }
            this.choices.set(key, result);
        }
        return result;
    }

    choose(accountId: string, conversationId: string | null, choice: boolean): boolean {
        let saved = true;
        if (!conversationId) {
            this.draftChoices.set(accountId, choice);
        } else {
            const key = this.key(accountId, conversationId);
            // Keep the chosen mode usable for this page even if browser storage is unavailable.
            this.choices.set(key, { choice, storageFailed: false });
            if (accountId) {
                try {
                    this.storage().setItem(key, choice ? 'on' : 'off');
                } catch {
                    saved = false;
                }
            }
        }
        this.changed();
        return saved;
    }

    captureDraft(accountId: string): DraftModeChoice {
        return { accountId, draftId: this.draftId, session: this.session, choice: this.draftChoices.get(accountId) };
    }

    adoptDraft(draft: DraftModeChoice, conversationId: string): boolean {
        // Logout/account reset invalidates late creation responses, not just the visible draft.
        if (draft.session !== this.session) return true;
        const saved = draft.choice === undefined || !draft.accountId
            ? true : this.choose(draft.accountId, conversationId, draft.choice);
        // A response for a draft already left must not consume the next new chat's choice.
        if (draft.draftId === this.draftId) this.resetDraft();
        return saved;
    }

    resetDraft(): void {
        this.draftChoices.clear();
        this.draftId += 1;
        this.changed();
    }

    reset(): void {
        this.choices.clear();
        this.session += 1;
        this.resetDraft();
    }

    forget(accountId: string, conversationId: string): boolean {
        if (!accountId) return true;
        const key = this.key(accountId, conversationId);
        this.choices.set(key, { choice: undefined, storageFailed: false });
        let removed = true;
        try {
            this.storage().removeItem(key);
        } catch {
            removed = false;
        }
        this.changed();
        return removed;
    }

    forgetAccount(accountId: string): boolean {
        let removed = true;
        try {
            const storage = this.storage();
            const prefix = `${CONVERSATION_MODE_PREFIX}${encodeURIComponent(accountId)}:`;
            const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index));
            for (const key of keys) {
                if (key?.startsWith(prefix)) storage.removeItem(key);
            }
        } catch {
            removed = false;
        }
        this.reset();
        return removed;
    }
}

export const conversationModes = new ConversationModeMemory(() => window.localStorage);

export function rememberConversationMode(accountId: string, conversationId: string | null, choice: boolean): void {
    if (!conversationModes.choose(accountId, conversationId, choice)) {
        toast.error('Your mode choice could not be saved in this browser. It applies until this page is reloaded.');
    }
}

export function adoptConversationModeDraft(draft: DraftModeChoice, conversationId: string): void {
    if (!conversationModes.adoptDraft(draft, conversationId)) {
        toast.error('Your mode choice could not be saved in this browser. It applies until this page is reloaded.');
    }
}

export function forgetConversationMode(accountId: string, conversationId: string): void {
    if (!conversationModes.forget(accountId, conversationId)) {
        toast.error('The conversation was removed, but its mode choice could not be cleared from this browser.');
    }
}

export function clearConversationModes(accountId: string): void {
    if (!conversationModes.forgetAccount(accountId)) {
        toast.error('Saved mode choices could not be cleared from this browser. Clear site data on a shared device.');
    }
}
