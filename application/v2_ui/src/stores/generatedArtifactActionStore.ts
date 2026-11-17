// generatedArtifactActionStore.ts
// How far each generated file got on its way into a workspace, kept for the life of the page.
//
// The card that offers "Add to workspace" can be unmounted and drawn again while the reader is
// still in the conversation -- another attempt is shown, the thread is reloaded after a reply --
// and its own state would go with it, putting the button back for a file that was already added.
// Classic loses this on a reload too, and relies on the server to answer a repeated request with
// the publication that already exists; that still holds here, but the card should not need the
// round trip to remember what it just did.

import { create } from 'zustand';
import type { PromotionStatus } from '../lib/generatedArtifactActions';

export interface ArtifactPromotionRecord {
    status: PromotionStatus;
    /** The workspace it went to, for the status the card shows. */
    targetName: string;
    /** The sentence the reader was told, which an unconfirmed file keeps showing. */
    message: string;
}

interface GeneratedArtifactActionState {
    /** Keyed by conversation and file, see `promotionKey`. */
    promotions: Record<string, ArtifactPromotionRecord>;
    recordPromotion: (key: string, record: ArtifactPromotionRecord) => void;
}

export function promotionKey(conversationId: string, artifactMessageId: string): string {
    return `${conversationId}:${artifactMessageId}`;
}

export const useGeneratedArtifactActionStore = create<GeneratedArtifactActionState>((set) => ({
    promotions: {},
    recordPromotion: (key, record) =>
        set((state) => ({ promotions: { ...state.promotions, [key]: record } })),
}));
