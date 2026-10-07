// DrawerAssets.tsx
// The Generated and Media sections of the conversation drawer's Documents tab.
//
// Generated lists the documents agents created in a shared conversation, with Download where the
// workspace's own download rules allow it and a preview for Markdown. Media gathers every image,
// video and audio clip the thread shows, including signed links an action fetched from a remote
// service, which are otherwise hard to find again in a long thread. Images and clips are tiles,
// three to a row, that open one viewer stepping through them all; recordings are players, each
// with Download and a button that scrolls to its message.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, Eye, FileText, Loader2 } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchCollaborationGeneratedDocument,
    fetchCollaborationGeneratedDocuments,
    type GeneratedDocument,
} from '../../lib/collaboration';
import { saveBlob } from '../../lib/endpoints';
import type { ConversationMediaItem } from '../../lib/conversationMedia';
import { useChatStore } from '../../stores/chatStore';
import { toast } from '../../stores/toastStore';
import { Modal } from '../ui/Modal';
import { PlainMarkdown } from '../ui/PlainMarkdown';
import { GlassButton } from '../ui/primitives';
import { InlineAudioPlayer } from './InlineAudioPlayer';
import { MediaViewer, type MediaViewerItem } from './MediaViewer';
import { ImageTile, VideoTile } from './MediaTiles';

/** Largest Markdown file previewed in the app; anything bigger is better read downloaded. */
const PREVIEW_MAX_BYTES = 2 * 1024 * 1024;

export function SectionHeading({ children }: { children: React.ReactNode }) {
    return (
        <h3 className="px-1 pb-1.5 text-[11px] font-medium tracking-wide text-text-3 uppercase">
            {children}
        </h3>
    );
}

/**
 * The generated documents of a shared conversation, refreshed as answers arrive.
 *
 * Refetched when the number of non-person messages changes, which is when an agent can have
 * created another document.
 */
export function useGeneratedDocuments(conversationId: string | null, enabled: boolean) {
    const answerCount = useChatStore(
        (state) => state.messages.filter((message) => message.role !== 'user').length,
    );
    // Keyed by conversation, so another conversation's list is never shown while this one loads.
    const [loaded, setLoaded] = useState<{
        conversationId: string | null;
        documents: GeneratedDocument[];
        error: string | null;
    }>({ conversationId: null, documents: [], error: null });

    useEffect(() => {
        if (!enabled || !conversationId) {
            return;
        }
        const controller = new AbortController();
        fetchCollaborationGeneratedDocuments(conversationId, controller.signal)
            .then((result) => {
                setLoaded({
                    conversationId,
                    documents: Array.isArray(result?.documents) ? result.documents : [],
                    error: null,
                });
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                // Refused or gone, as for an invitation not yet accepted: there is nothing to list.
                const refused = cause instanceof ApiError && (cause.status === 403 || cause.status === 404);
                setLoaded((current) => ({
                    conversationId,
                    documents: current.conversationId === conversationId && !refused ? current.documents : [],
                    error: refused
                        ? null
                        : cause instanceof Error ? cause.message : 'Could not list generated documents.',
                }));
            });
        return () => controller.abort();
    }, [conversationId, enabled, answerCount]);

    const current = enabled && loaded.conversationId === conversationId;
    return {
        documents: current ? loaded.documents : [],
        error: current ? loaded.error : null,
    };
}

function scopeLabel(document: GeneratedDocument): string {
    return document.workspace_scope === 'group' ? 'Group workspace' : 'Personal workspace';
}

function GeneratedDocumentPreview({
    conversationId,
    document,
    onDownload,
    onClose,
}: {
    conversationId: string;
    document: GeneratedDocument;
    onDownload: () => void;
    onClose: () => void;
}) {
    const [content, setContent] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        fetchCollaborationGeneratedDocument(conversationId, document.document_id, controller.signal)
            .then(async (blob) => {
                if (blob.size > PREVIEW_MAX_BYTES) {
                    setError('This document is too large to preview. Download it instead.');
                    return;
                }
                setContent(await blob.text());
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    setError(cause instanceof Error ? cause.message : 'Could not open the document.');
                }
            });
        return () => controller.abort();
    }, [conversationId, document.document_id]);

    return (
        <Modal
            title={document.file_name}
            description={scopeLabel(document)}
            onClose={onClose}
            size="lg"
            footer={(
                <>
                    <GlassButton size="sm" onClick={onClose}>Close</GlassButton>
                    <GlassButton size="sm" variant="primary" onClick={onDownload}>
                        <Download size={14} aria-hidden="true" /> Download
                    </GlassButton>
                </>
            )}
        >
            {error ? (
                <p role="alert" className="text-sm text-danger">{error}</p>
            ) : content === null ? (
                <p className="flex items-center gap-2 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Loading preview…
                </p>
            ) : (
                <PlainMarkdown content={content} size="md" emptyLabel="This document is empty." />
            )}
        </Modal>
    );
}

export function GeneratedDocumentsSection({
    conversationId,
    documents,
    error,
}: {
    conversationId: string;
    documents: GeneratedDocument[];
    error: string | null;
}) {
    const [previewing, setPreviewing] = useState<GeneratedDocument | null>(null);
    const [downloading, setDownloading] = useState<string | null>(null);

    const download = useCallback(async (document: GeneratedDocument) => {
        setDownloading(document.document_id);
        try {
            const blob = await fetchCollaborationGeneratedDocument(conversationId, document.document_id);
            saveBlob(blob, document.file_name);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : 'Could not download the document.');
        } finally {
            setDownloading(null);
        }
    }, [conversationId]);

    if (documents.length === 0 && !error) {
        return null;
    }

    return (
        <section aria-label="Generated documents" data-drawer-generated="">
            <SectionHeading>Generated</SectionHeading>
            {error && <p role="alert" className="px-1 text-xs text-danger">{error}</p>}
            <ul className="space-y-2">
                {documents.map((document) => {
                    const canPreview = document.can_download && document.preview === 'markdown';
                    const busy = downloading === document.document_id;
                    const open = () => (canPreview ? setPreviewing(document) : void download(document));
                    return (
                        <li key={document.document_id} className="glass-flat rounded-xl p-3"
                            data-generated-document={document.document_id}>
                            <div className="flex items-start gap-2.5">
                                <FileText size={16} className="mt-0.5 shrink-0 text-text-3" aria-hidden="true" />
                                <div className="min-w-0 flex-1">
                                    {document.can_download ? (
                                        <button type="button" onClick={open} title={document.file_name}
                                            className="block max-w-full truncate text-left text-sm text-text-1 hover:text-accent hover:underline">
                                            {document.file_name}
                                        </button>
                                    ) : (
                                        <p className="truncate text-sm text-text-1" title={document.file_name}>
                                            {document.file_name}
                                        </p>
                                    )}
                                    <p className="mt-1 text-xs text-text-3">
                                        {scopeLabel(document)}
                                        {!document.can_download && ' · Download not permitted'}
                                    </p>
                                </div>
                                {canPreview && (
                                    <button type="button" onClick={() => setPreviewing(document)}
                                        aria-label={`Preview ${document.file_name}`} title="Preview"
                                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1">
                                        <Eye size={15} />
                                    </button>
                                )}
                                {document.can_download && (
                                    <button type="button" disabled={busy} onClick={() => void download(document)}
                                        aria-label={`Download ${document.file_name}`} title="Download"
                                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:opacity-50">
                                        {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
                                    </button>
                                )}
                            </div>
                        </li>
                    );
                })}
            </ul>
            {previewing && (
                <GeneratedDocumentPreview
                    conversationId={conversationId}
                    document={previewing}
                    onDownload={() => void download(previewing)}
                    onClose={() => setPreviewing(null)}
                />
            )}
        </section>
    );
}

function MediaGroup({ label, count, children }: { label: string; count: number; children: React.ReactNode }) {
    return (
        <div role="group" aria-label={label} data-drawer-media-group={label.toLowerCase()}>
            <h4 className="flex items-baseline gap-1.5 px-1 pb-1.5 text-xs text-text-2">
                {label}
                <span className="text-[11px] text-text-3 tabular-nums">{count}</span>
            </h4>
            {children}
        </div>
    );
}

export function MediaSection({
    items,
    onLocate,
}: {
    items: ConversationMediaItem[];
    /** Scrolls the thread to the message an item appears in. */
    onLocate?: (messageId: string) => void;
}) {
    const [viewing, setViewing] = useState<number | null>(null);
    const images = useMemo(() => items.filter((item) => item.kind === 'image'), [items]);
    const videos = useMemo(() => items.filter((item) => item.kind === 'video'), [items]);
    const recordings = useMemo(() => items.filter((item) => item.kind === 'audio'), [items]);
    // One viewer steps through the images and then the clips, in the order the tiles show them.
    const visual = useMemo<MediaViewerItem[]>(
        () => [...images, ...videos].map(({ kind, src, title, messageId }) => ({
            kind: kind === 'video' ? 'video' : 'image',
            src,
            title,
            messageId,
        })),
        [images, videos],
    );

    if (items.length === 0) {
        return null;
    }

    return (
        <section aria-label="Media" data-drawer-media="">
            <SectionHeading>Media</SectionHeading>
            <div className="space-y-3">
                {images.length > 0 && (
                    <MediaGroup label="Images" count={images.length}>
                        <ul className="grid grid-cols-3 gap-1.5">
                            {images.map((item, index) => (
                                <li key={item.key}>
                                    <ImageTile
                                        src={item.src}
                                        title={item.title}
                                        label={`View image: ${item.title}`}
                                        onOpen={() => setViewing(index)}
                                        className="aspect-square"
                                    />
                                </li>
                            ))}
                        </ul>
                    </MediaGroup>
                )}
                {videos.length > 0 && (
                    <MediaGroup label="Videos" count={videos.length}>
                        <ul className="grid grid-cols-3 gap-1.5">
                            {videos.map((item, index) => (
                                <li key={item.key}>
                                    <VideoTile
                                        src={item.src}
                                        title={item.title}
                                        label={`Play video: ${item.title}`}
                                        onOpen={() => setViewing(images.length + index)}
                                        className="aspect-square"
                                    />
                                </li>
                            ))}
                        </ul>
                    </MediaGroup>
                )}
                {recordings.length > 0 && (
                    <MediaGroup label="Audio" count={recordings.length}>
                        <ul>
                            {recordings.map((item) => (
                                <li key={item.key}>
                                    <InlineAudioPlayer
                                        src={item.src}
                                        title={item.title}
                                        onLocate={onLocate ? () => onLocate(item.messageId) : undefined}
                                    />
                                </li>
                            ))}
                        </ul>
                    </MediaGroup>
                )}
            </div>
            {viewing !== null && visual[viewing] && (
                <MediaViewer
                    items={visual}
                    index={viewing}
                    onIndexChange={setViewing}
                    onClose={() => setViewing(null)}
                    onLocate={onLocate ? (item) => item.messageId && onLocate(item.messageId) : undefined}
                />
            )}
        </section>
    );
}
