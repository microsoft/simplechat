// chatUploads.ts

import { ApiError } from './apiClient';
import {
    fetchGroupDocument,
    fetchPersonalDocument,
    type ChatUploadResponse,
    type ChatUploadTarget,
} from './endpoints';
import { documentStatus } from './documentExplorer';
import type { ComposerDraft, ComposerReference, ComposerUpload } from './composerDraft';
import type { ChatMessage, WorkspaceDocument } from './types';
import type { Dispatch, SetStateAction } from 'react';
import { useOrchestrationStore } from '../stores/orchestrationStore';

// The /upload route supports these formats, not the workspace-only audio/video processors.
export const CHAT_UPLOAD_ACCEPT = [
    'txt', 'doc', 'docm', 'html', 'md', 'json', 'xml', 'yaml', 'yml', 'log',
    'pdf', 'docx', 'pptx', 'ppt', 'csv', 'xlsx', 'xls', 'xlsm', 'msg',
    'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif', 'heic',
].map((extension) => `.${extension}`).join(',');

export function chatUploadValidationError(
    file: File,
    enabled: boolean,
    maxSizeMb: unknown,
): string | null {
    if (!enabled) {
        return 'File uploads are not available for your account.';
    }
    const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
    if (!CHAT_UPLOAD_ACCEPT.split(',').includes(extension)) {
        return 'This file type is not supported for chat uploads.';
    }
    const limit = Number(maxSizeMb);
    if (Number.isFinite(limit) && limit > 0 && file.size > limit * 1024 * 1024) {
        return `This file exceeds the ${limit} MB upload limit.`;
    }
    return null;
}

type UploadStatus = Pick<ComposerUpload, 'state' | 'progress' | 'error'>;

export function chatUploadDocumentStatus(document: WorkspaceDocument): UploadStatus {
    const status = documentStatus(document);
    if (status.state === 'error') {
        return { state: 'failed', error: 'File processing failed. Retry the status check or remove this file.' };
    }
    if (status.state === 'pending_approval') {
        return { state: 'failed', error: 'This file is waiting for access approval.' };
    }
    const text = String(document.status ?? '').trim().toLowerCase();
    const rawProgress = document.percentage_complete;
    const progress = rawProgress === undefined || rawProgress === null
        ? NaN
        : Number(rawProgress);
    // The explorer treats old records with no progress as ready. A new upload cannot make
    // that assumption: a queued response without a percentage is still not usable.
    if ((Number.isFinite(progress) && progress >= 100)
        || /^(ready|completed?|processed|finished|processing complete[.!]?)$/.test(text)) {
        return { state: 'ready', progress: 100 };
    }
    return {
        state: 'processing',
        progress: Number.isFinite(progress) ? Math.max(0, Math.min(99, progress)) : 0,
    };
}

export function normalizeChatUpload(
    response: ChatUploadResponse,
    fileName: string,
): Pick<ComposerUpload, 'reference' | 'conversationId' | 'state' | 'progress' | 'error'> {
    if (response.error || response.success === false) {
        throw new Error(response.error || 'The upload did not succeed.');
    }
    const document = response.workspace_document;
    const id = String(response.workspace_document_id || document?.document_id || '').trim();
    const conversationId = String(response.conversation_id ?? '').trim();
    if (id) {
        const kind = String(response.workspace_scope || document?.scope || '');
        if (kind !== 'personal' && kind !== 'group') {
            throw new Error('The upload did not return a supported workspace destination.');
        }
        const groupId = String(document?.group_id || response.group_upload_target?.id || '').trim();
        if (kind === 'group' && !groupId) {
            throw new Error('The upload did not identify its group workspace.');
        }
        return {
            reference: {
                kind: 'document',
                id,
                label: String(document?.file_name || fileName),
                scope: {
                    kind,
                    id: kind === 'group' ? groupId : null,
                    name: kind === 'group'
                        ? String(document?.group_name || response.group_upload_target?.name || 'Group workspace')
                        : 'My workspace',
                },
            },
            conversationId: conversationId || undefined,
            ...chatUploadDocumentStatus(document ?? {}),
        };
    }
    const messageId = String(response.file_message_id ?? '').trim();
    if (!messageId || !conversationId) {
        throw new Error('The upload did not return an attachment identity. Reload the conversation before choosing it.');
    }
    return {
        reference: {
            kind: 'chat_attachment',
            id: messageId,
            label: fileName,
            scope: { kind: 'chat', id: conversationId, name: 'This conversation' },
        },
        conversationId,
        state: 'ready',
        progress: 100,
    };
}

export function chatUploadTargets(error: unknown): ChatUploadTarget[] | null {
    const payload = error instanceof ApiError ? error.payload as ChatUploadResponse | null : null;
    if (!payload?.requires_group_upload_target) {
        return null;
    }
    return (payload.group_upload_targets ?? []).filter((target) =>
        typeof target.id === 'string' && typeof target.name === 'string',
    );
}

function waitForPoll(signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const abort = () => {
            clearTimeout(timer);
            reject(new DOMException('Upload tracking cancelled.', 'AbortError'));
        };
        const timer = setTimeout(() => {
            signal.removeEventListener('abort', abort);
            resolve();
        }, 1500);
        signal.addEventListener('abort', abort, { once: true });
        if (signal.aborted) {
            abort();
        }
    });
}

export async function pollChatUpload(
    reference: ComposerReference,
    signal: AbortSignal,
    onStatus: (status: UploadStatus) => void,
): Promise<void> {
    if (reference.kind !== 'document'
        || (reference.scope.kind !== 'personal' && reference.scope.kind !== 'group')) {
        throw new Error('This upload has no supported processing destination.');
    }
    const deadline = Date.now() + 10 * 60 * 1000;
    while (!signal.aborted) {
        const document = reference.scope.kind === 'group'
            ? await fetchGroupDocument(reference.id, signal)
            : await fetchPersonalDocument(reference.id, signal);
        if (signal.aborted) {
            return;
        }
        const status = chatUploadDocumentStatus(document);
        onStatus(status);
        if (status.state !== 'processing') {
            return;
        }
        if (Date.now() >= deadline) {
            throw new Error('Processing is taking longer than expected. Retry to check its status.');
        }
        await waitForPoll(signal);
    }
}

interface RetainedProcessing {
    current: () => boolean;
    stop: () => void;
}

const retainedProcessing = new Map<string, RetainedProcessing>();

function retainedKey(uploadId: string, conversationId: string): string {
    return JSON.stringify([conversationId, uploadId]);
}

function sameReference(left: ComposerReference | undefined, right: ComposerReference): boolean {
    return left?.kind === right.kind && left.id === right.id
        && left.scope.kind === right.scope.kind && left.scope.id === right.scope.id;
}

export function hasRetainedComposerUpload(uploadId: string, conversationId: string | null): boolean {
    return Boolean(conversationId
        && retainedProcessing.get(retainedKey(uploadId, conversationId))?.current());
}

export function cancelRetainedComposerUpload(uploadId: string, conversationId: string | null): void {
    if (conversationId) {
        retainedProcessing.get(retainedKey(uploadId, conversationId))?.stop();
    }
}

/**
 * A pending question owns its processing checks beyond an individual page's editor mount.
 * Discover the exact persisted field by its local upload identity, and subscribe to that
 * question's lifetime. No active-conversation lookup or DOM-id parsing can redirect a result.
 *
 * Other controlled hosts keep their mounted lifecycle and actionable interruption behavior.
 */
export function retainComposerUploadProcessing(
    upload: ComposerUpload,
    conversationId: string | null,
    changeDraft: Dispatch<SetStateAction<ComposerDraft>>,
): boolean {
    if (!conversationId || upload.state !== 'processing' || upload.reference?.kind !== 'document') {
        return false;
    }
    const key = retainedKey(upload.id, conversationId);
    const existing = retainedProcessing.get(key);
    if (existing?.current()) {
        return true;
    }
    existing?.stop();
    const reference: ComposerReference = { ...upload.reference, scope: { ...upload.reference.scope } };
    const state = useOrchestrationStore.getState();
    for (const [questionKey, questionDraft] of Object.entries(state.elicitationDrafts)) {
        if (questionKey.split('\u0000')[0] !== conversationId) {
            continue;
        }
        const field = Object.entries(questionDraft.editors).find(([, editor]) =>
            editor.uploads.some((item) => item.id === upload.id && sameReference(item.reference, reference)),
        )?.[0];
        if (field === undefined) {
            continue;
        }
        const elicitationId = questionDraft.elicitationId;
        const revision = questionDraft.revision;
        const current = () => {
            const live = useOrchestrationStore.getState();
            const question = live.elicitations[questionKey];
            const draft = live.elicitationDrafts[questionKey];
            if (question?.elicitation_id !== elicitationId || (question.revision ?? 0) !== revision
                || draft?.elicitationId !== elicitationId || draft.revision !== revision) {
                return false;
            }
            return Boolean(draft.editors[field]?.uploads.some((item) =>
                item.id === upload.id && item.state === 'processing'
                && sameReference(item.reference, reference),
            ));
        };
        if (!current()) {
            continue;
        }
        const controller = new AbortController();
        let unsubscribe: (() => void) | undefined;
        const entry: RetainedProcessing = {
            current,
            stop: () => {
                controller.abort();
                unsubscribe?.();
                if (retainedProcessing.get(key) === entry) {
                    retainedProcessing.delete(key);
                }
            },
        };
        const publish = (status: UploadStatus) => {
            if (controller.signal.aborted || !current()) {
                return;
            }
            changeDraft((draft) => ({
                ...draft,
                uploads: draft.uploads.map((item) =>
                    item.id === upload.id && item.state === 'processing'
                        && sameReference(item.reference, reference)
                        ? { ...item, ...status, interrupted: undefined, error: status.error }
                        : item,
                ),
            }));
        };
        retainedProcessing.set(key, entry);
        unsubscribe = useOrchestrationStore.subscribe(() => {
            if (!current()) {
                entry.stop();
            }
        });
        void pollChatUpload(reference, controller.signal, publish)
            .catch((error: unknown) => {
                if (!controller.signal.aborted) {
                    publish({
                        state: 'failed',
                        error: error instanceof Error ? error.message : 'Could not check file processing. Retry or remove it.',
                    });
                }
            })
            .finally(entry.stop);
        return true;
    }
    return false;
}

/** Only real, already-loaded file messages from the editor's conversation are candidates. */
export function conversationAttachmentReferences(
    messages: readonly ChatMessage[],
    conversationId: string | null,
): ComposerReference[] {
    if (!conversationId) {
        return [];
    }
    return messages.flatMap((message) => {
        if (message.conversation_id !== conversationId || !message.id
            || message.workspace_document_id || !message.filename
            || (message.role !== 'file' && !message.id.includes('_file_'))) {
            return [];
        }
        return [{
            kind: 'chat_attachment' as const,
            id: message.id,
            label: String(message.filename),
            scope: { kind: 'chat' as const, id: conversationId, name: 'This conversation' },
        }];
    });
}
