// chatImagePreview.ts

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { apiUrl, CREDENTIALS_MODE } from './apiClient';
import { fetchGroupDocument, fetchPersonalDocument } from './endpoints';
import {
    chatUploadDocumentStatus,
    getChatUploadLocalPreview,
    subscribeChatUploadLocalPreviews,
} from './chatUploads';
import { isScreeningAvailable, isScreeningBusy } from './contentScreening';
import type { WorkspaceDocument } from './types';

export type ChatImagePreviewVariant = 'thumbnail' | 'display';
export type ChatImagePreviewStatus = 'loading' | 'ready' | 'processing' | 'held' | 'unavailable';

export interface WorkspaceAttachmentPreviewRef {
    document_id?: unknown;
    file_name?: unknown;
    scope?: unknown;
    group_id?: unknown;
    scope_id?: unknown;
    status?: unknown;
    percentage_complete?: unknown;
}

export interface ChatImagePreviewState {
    status: ChatImagePreviewStatus;
    url: string | null;
    localUrl: string | null;
    reason: string | null;
}

export interface ChatImagePreviewOptions {
    enabled: boolean;
    variant?: ChatImagePreviewVariant;
    fileName?: string;
    localPreviewKeys?: readonly unknown[];
    workspaceAttachment?: WorkspaceAttachmentPreviewRef | null;
}

export const HEIC_BROWSER_PREVIEW_HINT =
    "Preview isn't available in this browser. Convert to JPG or PNG to preview it.";

const PROCESSING_STATUSES = new Set([409, 503]);
const UNAVAILABLE_STATUSES = new Set([403, 404, 413, 415]);
const POLL_INTERVAL_MS = 2000;
const POLL_DEADLINE_MS = 3 * 60 * 1000;
// A document record can read as ready while the preview is still refused, for example when
// its stored bytes cannot be read. The record will not change, so re-polling it would spin.
const MAX_READY_PREVIEW_RETRIES = 2;
const UNAVAILABLE_REASON = 'Preview is unavailable.';
const HELD_REASON = 'Unavailable pending review.';

export type WorkspaceAttachmentPollOutcome = 'ready' | 'held' | 'unavailable' | 'pending';
export type ChatImagePreviewUpdate = Omit<ChatImagePreviewState, 'localUrl'>;

/** The side effects one preview run needs, injected so the retry rules can be tested directly. */
export interface ChatImagePreviewRunDeps {
    fetchPreview: (signal: AbortSignal) => Promise<Response>;
    /** Null when the message names no workspace document whose progress can be polled. */
    fetchDocument: ((signal: AbortSignal) => Promise<WorkspaceDocument>) | null;
    wait: (signal: AbortSignal) => Promise<void>;
    now: () => number;
    createObjectUrl: (blob: Blob) => string;
}

export interface ChatImagePreviewRunOptions {
    fileName?: string;
    deadlineMs?: number;
    maxReadyRetries?: number;
}

export function buildChatImagePreviewUrl(
    messageId: string,
    variant: ChatImagePreviewVariant = 'thumbnail',
): string {
    return apiUrl(`/api/image/${encodeURIComponent(messageId)}?variant=${encodeURIComponent(variant)}`);
}

export function chatImagePreviewStatusForResponse(
    status: number,
    payload: unknown = null,
): Exclude<ChatImagePreviewStatus, 'loading'> {
    if (status >= 200 && status < 300) {
        return 'ready';
    }
    const errorCode = typeof payload === 'object' && payload !== null && 'error_code' in payload
        ? String((payload as { error_code?: unknown }).error_code ?? '')
        : '';
    if (status === 409 && errorCode && errorCode !== 'document_under_review') {
        return 'unavailable';
    }
    if (PROCESSING_STATUSES.has(status)) {
        return 'processing';
    }
    if (UNAVAILABLE_STATUSES.has(status)) {
        return 'unavailable';
    }
    return 'unavailable';
}

export function imagePreviewHintForFileName(fileName: string): string | null {
    return /\.(hei[cf])$/i.test(fileName.trim()) ? HEIC_BROWSER_PREVIEW_HINT : null;
}

export function workspaceAttachmentDocumentId(
    attachment: WorkspaceAttachmentPreviewRef | null | undefined,
): string {
    return String(attachment?.document_id ?? '').trim();
}

export function workspaceAttachmentScope(
    attachment: WorkspaceAttachmentPreviewRef | null | undefined,
): { kind: 'personal' | 'group'; groupId: string | null } | null {
    const scope = String(attachment?.scope ?? '').trim().toLowerCase();
    if (scope === 'personal') {
        return { kind: 'personal', groupId: null };
    }
    if (scope === 'group') {
        return {
            kind: 'group',
            groupId: String(attachment?.group_id ?? attachment?.scope_id ?? '').trim() || null,
        };
    }
    return null;
}

async function readErrorPayload(response: Response): Promise<unknown> {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        return null;
    }
    try {
        return await response.json();
    } catch {
        return null;
    }
}

function waitForPreviewPoll(signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const abort = () => {
            window.clearTimeout(timer);
            reject(new DOMException('Image preview polling cancelled.', 'AbortError'));
        };
        const timer = window.setTimeout(() => {
            signal.removeEventListener('abort', abort);
            resolve();
        }, POLL_INTERVAL_MS);
        signal.addEventListener('abort', abort, { once: true });
        if (signal.aborted) {
            abort();
        }
    });
}

async function pollWorkspaceAttachment(
    deps: ChatImagePreviewRunDeps,
    fetchDocument: (signal: AbortSignal) => Promise<WorkspaceDocument>,
    signal: AbortSignal,
    deadline: number,
): Promise<'ready' | 'held' | 'unavailable'> {
    while (!signal.aborted) {
        if (deps.now() >= deadline) {
            return 'held';
        }
        let document: WorkspaceDocument;
        try {
            document = await fetchDocument(signal);
        } catch {
            return 'unavailable';
        }
        const outcome = workspaceAttachmentPollOutcome(document);
        if (outcome !== 'pending') {
            return outcome;
        }
        try {
            await deps.wait(signal);
        } catch {
            return 'unavailable';
        }
    }
    return 'unavailable';
}

/**
 * What a polled workspace document says about whether its preview can be retried.
 *
 * A screened document is only servable once screening clears it, so its screening state
 * decides before its processing progress: a held record can sit at 100% indefinitely.
 */
export function workspaceAttachmentPollOutcome(
    document: WorkspaceDocument,
): WorkspaceAttachmentPollOutcome {
    if (Object.prototype.hasOwnProperty.call(document, 'content_screening')
        && !isScreeningAvailable(document)) {
        return isScreeningBusy(document) ? 'pending' : 'held';
    }
    const status = chatUploadDocumentStatus(document);
    if (status.state === 'ready') {
        return 'ready';
    }
    if (status.state === 'failed') {
        return /approval|review|screen|hold/i.test(status.error ?? '') ? 'held' : 'unavailable';
    }
    return 'pending';
}

/**
 * Load one preview, waiting out processing, within a single deadline and retry budget.
 *
 * Every exit publishes a settled state, so a card never stays on its skeleton, and nothing
 * is published once the signal aborts.
 */
export async function runChatImagePreview(
    deps: ChatImagePreviewRunDeps,
    signal: AbortSignal,
    publish: (update: ChatImagePreviewUpdate) => void,
    options: ChatImagePreviewRunOptions = {},
): Promise<void> {
    const deadline = deps.now() + (options.deadlineMs ?? POLL_DEADLINE_MS);
    const maxReadyRetries = Math.max(0, options.maxReadyRetries ?? MAX_READY_PREVIEW_RETRIES);
    const settle = (update: ChatImagePreviewUpdate) => {
        if (!signal.aborted) {
            publish(update);
        }
    };
    const unavailable = (reason = UNAVAILABLE_REASON) => settle({ status: 'unavailable', url: null, reason });
    let readyRetries = 0;

    settle({ status: 'loading', url: null, reason: null });
    while (!signal.aborted) {
        let response: Response;
        try {
            response = await deps.fetchPreview(signal);
        } catch {
            unavailable();
            return;
        }
        if (response.ok) {
            let blob: Blob;
            try {
                blob = await response.blob();
            } catch {
                unavailable();
                return;
            }
            if (!signal.aborted) {
                settle({ status: 'ready', url: deps.createObjectUrl(blob), reason: null });
            }
            return;
        }
        const payload = await readErrorPayload(response);
        if (signal.aborted) {
            return;
        }
        const status = chatImagePreviewStatusForResponse(response.status, payload);
        if (status !== 'processing') {
            settle({
                status,
                url: null,
                reason: imagePreviewHintForFileName(options.fileName ?? '') ?? UNAVAILABLE_REASON,
            });
            return;
        }
        if (!deps.fetchDocument) {
            unavailable();
            return;
        }
        settle({ status: 'processing', url: null, reason: null });
        const outcome = await pollWorkspaceAttachment(deps, deps.fetchDocument, signal, deadline);
        if (signal.aborted) {
            return;
        }
        if (outcome === 'held') {
            settle({ status: 'held', url: null, reason: HELD_REASON });
            return;
        }
        if (outcome === 'unavailable' || readyRetries >= maxReadyRetries) {
            unavailable();
            return;
        }
        // The first retry covers the record turning ready a moment before the preview does;
        // later ones wait a poll interval rather than hammering a preview that keeps refusing.
        if (readyRetries > 0) {
            try {
                await deps.wait(signal);
            } catch {
                return;
            }
        }
        readyRetries += 1;
    }
}

function workspaceAttachmentFetcher(
    attachment: WorkspaceAttachmentPreviewRef | null | undefined,
): ((signal: AbortSignal) => Promise<WorkspaceDocument>) | null {
    const documentId = workspaceAttachmentDocumentId(attachment);
    const scope = workspaceAttachmentScope(attachment);
    if (!documentId || !scope) {
        return null;
    }
    return (signal) => (scope.kind === 'group'
        ? fetchGroupDocument(documentId, signal)
        : fetchPersonalDocument(documentId, signal));
}

function localPreviewSnapshot(keys: readonly unknown[] | undefined): string | null {
    return getChatUploadLocalPreview(...(keys ?? []));
}

export function useChatImagePreview(
    messageId: string,
    options: ChatImagePreviewOptions,
): ChatImagePreviewState {
    const {
        enabled,
        variant = 'thumbnail',
        fileName = '',
        localPreviewKeys = [],
        workspaceAttachment = null,
    } = options;
    const previewUrl = useMemo(
        () => (messageId ? buildChatImagePreviewUrl(messageId, variant) : ''),
        [messageId, variant],
    );
    const localPreviewKeySignature = useMemo(
        () => JSON.stringify(localPreviewKeys.map((key) => String(key ?? ''))),
        [localPreviewKeys],
    );
    const localUrl = useSyncExternalStore(
        subscribeChatUploadLocalPreviews,
        () => localPreviewSnapshot(localPreviewKeys),
        () => localPreviewSnapshot(localPreviewKeys),
    );
    // Message objects are replaced whenever the conversation reloads. Keying the fetch on the
    // attachment's primitive fields, not the object, keeps a reload from re-fetching every
    // thumbnail and flashing the skeleton.
    const attachmentDocumentId = workspaceAttachmentDocumentId(workspaceAttachment);
    const attachmentScope = workspaceAttachmentScope(workspaceAttachment);
    const attachmentScopeKind = attachmentScope?.kind ?? '';
    const attachmentGroupId = attachmentScope?.groupId ?? '';
    const pollTarget = useMemo<WorkspaceAttachmentPreviewRef | null>(
        () => (attachmentDocumentId && attachmentScopeKind
            ? { document_id: attachmentDocumentId, scope: attachmentScopeKind, group_id: attachmentGroupId || null }
            : null),
        [attachmentDocumentId, attachmentScopeKind, attachmentGroupId],
    );
    const [state, setState] = useState<ChatImagePreviewState>({
        status: enabled ? 'loading' : 'unavailable',
        url: null,
        localUrl,
        reason: null,
    });

    useEffect(() => {
        setState((current) => ({ ...current, localUrl }));
    }, [localUrl]);

    useEffect(() => {
        if (!enabled || !previewUrl) {
            setState({ status: 'unavailable', url: null, localUrl, reason: UNAVAILABLE_REASON });
            return undefined;
        }
        const controller = new AbortController();
        let currentObjectUrl: string | null = null;

        const publish = (next: ChatImagePreviewUpdate) => {
            if (!controller.signal.aborted) {
                setState({ ...next, localUrl: localPreviewSnapshot(localPreviewKeys) });
            }
        };

        const deps: ChatImagePreviewRunDeps = {
            fetchPreview: (signal) => fetch(previewUrl, { credentials: CREDENTIALS_MODE, signal }),
            fetchDocument: workspaceAttachmentFetcher(pollTarget),
            wait: waitForPreviewPoll,
            now: Date.now,
            createObjectUrl: (blob) => {
                currentObjectUrl = URL.createObjectURL(blob);
                return currentObjectUrl;
            },
        };

        runChatImagePreview(deps, controller.signal, publish, { fileName }).catch(() => {
            publish({ status: 'unavailable', url: null, reason: UNAVAILABLE_REASON });
        });
        return () => {
            controller.abort();
            if (currentObjectUrl) {
                URL.revokeObjectURL(currentObjectUrl);
            }
        };
        // The local preview is merged by the effect above, so a local URL appearing or being
        // evicted does not need a server round trip.
    }, [enabled, fileName, localPreviewKeySignature, previewUrl, pollTarget]);

    return state;
}
