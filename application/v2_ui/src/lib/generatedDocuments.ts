// generatedDocuments.ts
// The documents agents created in a conversation with the SimpleChat upload actions.
//
// A shared conversation and a personal one list these behind different routes, because each is
// authorized against its own kind of conversation: participation for a shared one, ownership for
// a personal one. Callers name the conversation and its kind and this module picks the route, so
// a list read from one family is never downloaded through the other.

import { api, apiUrl, CREDENTIALS_MODE } from './apiClient';
import {
    collaborationGeneratedDocumentUrl,
    fetchCollaborationGeneratedDocuments,
    type GeneratedDocument,
} from './collaboration';
import type { ConversationKind } from './endpoints';

export type { GeneratedDocument };

const personalGeneratedDocumentsPath = (conversationId: string) =>
    `/api/conversations/${encodeURIComponent(conversationId)}/generated-documents`;

export function fetchGeneratedDocuments(
    conversationId: string,
    kind: ConversationKind,
    signal?: AbortSignal,
): Promise<{ documents: GeneratedDocument[] }> {
    return kind === 'collaborative'
        ? fetchCollaborationGeneratedDocuments(conversationId, signal)
        : api.get<{ documents: GeneratedDocument[] }>(personalGeneratedDocumentsPath(conversationId), signal);
}

/** Where one generated document downloads from; the same request also feeds the preview. */
export function generatedDocumentDownloadUrl(
    conversationId: string,
    kind: ConversationKind,
    documentId: string,
): string {
    return kind === 'collaborative'
        ? collaborationGeneratedDocumentUrl(conversationId, documentId)
        : apiUrl(`${personalGeneratedDocumentsPath(conversationId)}/${encodeURIComponent(documentId)}/download`);
}

/**
 * Fetch a generated document's file, for saving or previewing.
 *
 * Rejects with the server's error message, such as the reader not being allowed to download it,
 * so the reader learns why rather than receiving a broken file.
 */
export async function fetchGeneratedDocument(
    conversationId: string,
    kind: ConversationKind,
    documentId: string,
    signal?: AbortSignal,
): Promise<Blob> {
    const response = await fetch(generatedDocumentDownloadUrl(conversationId, kind, documentId), {
        credentials: CREDENTIALS_MODE,
        signal,
    });
    if (!response.ok) {
        let message = `Download failed (${response.status})`;
        try {
            const payload = (await response.json()) as { error?: string } | null;
            if (payload?.error) {
                message = payload.error;
            }
        } catch {
            // Not JSON: the status line is all there is to report.
        }
        throw new Error(message);
    }
    return response.blob();
}
