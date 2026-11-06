// composerAttachmentDrafts.ts
// Attachment selections live in this tab, separately from the composer's text/preferences.

import { useCallback, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { createComposerDraft, type ComposerDraft } from './composerDraft';

type AttachmentFields = Pick<
    ComposerDraft, 'contextItems' | 'uploads' | 'imageReferences' | 'conversationReferences'
>;

export interface ComposerAttachmentOwner {
    accountId: string;
    conversationId: string | null;
    kind: 'personal' | 'collaborative';
    epoch: number;
    key: string;
}

export interface ComposerAttachmentSnapshot extends AttachmentFields {
    documentSearch: boolean;
    uploadConversationId: string | null;
    initialized: boolean;
    revision: number;
}

interface RetainedAttachments {
    epoch: number;
    snapshot: ComposerAttachmentSnapshot;
}

function emptyAttachments(): ComposerAttachmentSnapshot {
    return {
        contextItems: [], uploads: [], imageReferences: [], conversationReferences: [],
        documentSearch: false, uploadConversationId: null, initialized: false, revision: 0,
    };
}

const EMPTY_ATTACHMENTS = emptyAttachments();

export function composerAttachmentOwner(
    accountId: string,
    conversationId: string | null,
    kind: 'personal' | 'collaborative',
    epoch: number,
): ComposerAttachmentOwner {
    return {
        accountId, conversationId, kind, epoch,
        key: JSON.stringify([accountId, kind, conversationId, conversationId ? null : epoch]),
    };
}

function attachmentFields(draft: ComposerDraft): AttachmentFields {
    return {
        contextItems: draft.contextItems,
        uploads: draft.uploads,
        imageReferences: draft.imageReferences,
        conversationReferences: draft.conversationReferences,
    };
}

function withAttachments(draft: ComposerDraft, attachments: AttachmentFields): ComposerDraft {
    return {
        ...draft, contextItems: attachments.contextItems, uploads: attachments.uploads,
        imageReferences: attachments.imageReferences, conversationReferences: attachments.conversationReferences,
    };
}

export class ComposerAttachmentDrafts {
    private accountId: string | null = null;
    private drafts = new Map<string, RetainedAttachments>();
    private listeners = new Set<() => void>();

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    };

    private publish(): void {
        for (const listener of this.listeners) listener();
    }

    activate(owner: ComposerAttachmentOwner): void {
        const accountChanged = Boolean(this.accountId) && this.accountId !== owner.accountId;
        if (this.accountId !== owner.accountId) {
            this.drafts.clear();
            this.accountId = owner.accountId;
        }
        const retained = this.drafts.get(owner.key);
        if (retained) retained.epoch = owner.epoch;
        else this.drafts.set(owner.key, {
            epoch: owner.epoch, snapshot: { ...emptyAttachments(), initialized: accountChanged },
        });
    }

    read(owner: ComposerAttachmentOwner): ComposerAttachmentSnapshot {
        return this.accountId === owner.accountId
            ? this.drafts.get(owner.key)?.snapshot ?? EMPTY_ATTACHMENTS
            : EMPTY_ATTACHMENTS;
    }

    update(
        owner: ComposerAttachmentOwner,
        change: (current: ComposerAttachmentSnapshot) => ComposerAttachmentSnapshot,
    ): boolean {
        const retained = this.drafts.get(owner.key);
        if (this.accountId !== owner.accountId || !retained || retained.epoch !== owner.epoch) return false;
        const next = change(retained.snapshot);
        if (next === retained.snapshot) return false;
        retained.snapshot = { ...next, revision: retained.snapshot.revision + 1 };
        this.publish();
        return true;
    }

    initialize(owner: ComposerAttachmentOwner, contextItems: ComposerDraft['contextItems'], documentSearch: boolean): void {
        this.update(owner, (current) => current.initialized ? current : {
            ...current, contextItems, documentSearch, initialized: true,
        });
    }

    adoptConversation(owner: ComposerAttachmentOwner, conversationId: string): void {
        const retained = this.drafts.get(owner.key);
        if (!retained || !conversationId || this.accountId !== owner.accountId || retained.epoch !== owner.epoch) return;
        if (owner.conversationId && owner.conversationId !== conversationId) return;
        if (!owner.conversationId) {
            const adopted = composerAttachmentOwner(owner.accountId, conversationId, 'personal', owner.epoch);
            this.drafts.set(adopted.key, retained);
        }
    }

    bindUploadConversation(owner: ComposerAttachmentOwner, conversationId: string): void {
        if (owner.conversationId && owner.conversationId !== conversationId) return;
        this.adoptConversation(owner, conversationId);
        this.update(owner, (current) => current.uploadConversationId === conversationId
            ? current : { ...current, uploadConversationId: conversationId });
    }

    sameDraft(left: ComposerAttachmentOwner, right: ComposerAttachmentOwner): boolean {
        return this.accountId === left.accountId && left.accountId === right.accountId
            && this.drafts.has(left.key) && this.drafts.get(left.key) === this.drafts.get(right.key);
    }

    canSubmit(owner: ComposerAttachmentOwner, current: ComposerAttachmentOwner, revision: number): boolean {
        return owner.epoch === current.epoch && this.sameDraft(owner, current)
            && this.read(owner).revision === revision;
    }

    /** Recovery may follow a return to the same chat, but never a subsequent draft edit. */
    recover(owner: ComposerAttachmentOwner, revision: number, draft: ComposerDraft): boolean {
        const retained = this.drafts.get(owner.key);
        if (this.accountId !== owner.accountId || !retained || retained.snapshot.revision !== revision) return false;
        retained.snapshot = {
            ...retained.snapshot, ...attachmentFields(draft),
            initialized: true, revision: revision + 1,
        };
        this.publish();
        return true;
    }

    forget(accountId: string, conversationId: string): void {
        if (this.accountId !== accountId) return;
        const removed = new Set<RetainedAttachments>();
        for (const kind of ['personal', 'collaborative'] as const) {
            const retained = this.drafts.get(composerAttachmentOwner(accountId, conversationId, kind, 0).key);
            if (retained) removed.add(retained);
        }
        for (const [key, retained] of this.drafts) {
            if (removed.has(retained)) this.drafts.delete(key);
        }
        if (removed.size) this.publish();
    }

    reset(): void {
        this.drafts.clear();
        this.accountId = null;
        this.publish();
    }
}

export const composerAttachmentDrafts = new ComposerAttachmentDrafts();

export function useComposerAttachmentDraft(
    accountId: string,
    conversationId: string | null,
    collaborative: boolean,
    epoch: number,
    readOwner: () => ComposerAttachmentOwner,
) {
    const owner = useMemo(
        () => composerAttachmentOwner(accountId, conversationId, collaborative ? 'collaborative' : 'personal', epoch),
        [accountId, conversationId, collaborative, epoch],
    );
    const previousOwner = useRef(owner);
    if (!previousOwner.current.conversationId && conversationId
        && previousOwner.current.accountId === accountId && previousOwner.current.epoch === epoch) {
        composerAttachmentDrafts.adoptConversation(previousOwner.current, conversationId);
    }
    previousOwner.current = owner;
    composerAttachmentDrafts.activate(owner);
    const attachments = useSyncExternalStore(
        composerAttachmentDrafts.subscribe,
        useCallback(() => composerAttachmentDrafts.read(owner), [owner]),
    );
    const [localDraft, setLocalDraft] = useState(createComposerDraft);
    const live = useRef({ owner, draft: localDraft });
    live.current = { owner, draft: localDraft };
    const setDraft = useCallback<React.Dispatch<React.SetStateAction<ComposerDraft>>>((change) => {
        const activeOwner = readOwner();
        if (activeOwner.accountId !== owner.accountId) return;
        const current = composerAttachmentDrafts.read(owner);
        const previous = withAttachments(live.current.draft, current);
        const next = typeof change === 'function' ? change(previous) : change;
        if (next === previous) return;
        const fields = attachmentFields(next);
        const attachmentsChanged = fields.contextItems !== current.contextItems || fields.uploads !== current.uploads
            || fields.imageReferences !== current.imageReferences || fields.conversationReferences !== current.conversationReferences;
        const changed = composerAttachmentDrafts.update(owner, (snapshot) => ({
            ...snapshot, ...fields, initialized: snapshot.initialized || attachmentsChanged,
        }));
        if (changed && activeOwner.epoch === owner.epoch
            && composerAttachmentDrafts.sameDraft(owner, activeOwner)) {
            live.current.draft = next;
            setLocalDraft(next);
        }
    }, [owner, readOwner]);
    const setDocumentSearch = useCallback((documentSearch: boolean) => {
        composerAttachmentDrafts.update(owner, (current) => ({
            ...current, documentSearch, initialized: true,
        }));
    }, [owner]);
    const recoverDraft = useCallback((sentDraft: ComposerDraft, revision: number) => {
        const activeOwner = readOwner();
        if (activeOwner.accountId !== owner.accountId) return;
        if (!composerAttachmentDrafts.recover(owner, revision, sentDraft)) return;
        if (composerAttachmentDrafts.sameDraft(activeOwner, live.current.owner)
            && composerAttachmentDrafts.sameDraft(owner, activeOwner)) {
            live.current.draft = sentDraft;
            setLocalDraft(sentDraft);
        }
    }, [owner, readOwner]);
    return {
        owner, attachments, draft: withAttachments(localDraft, attachments),
        setDraft, setDocumentSearch, recoverDraft,
    };
}
