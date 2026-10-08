// DrawerAssets.tsx
// The Generated and Media sections of the conversation drawer's Documents tab.
//
// Generated lists every file the conversation produced, in conversation order, for both personal
// and shared conversations: the files a plan rendered and the exports and analysis files replies
// wrote, read off the thread itself, and the documents agents created with the SimpleChat upload
// actions, which the server lists along with whether the workspace's download rules let this
// reader have them. A file that is still being written, failed or waits for approval is listed
// with its status, and Download appears once it is ready; Markdown and files with an inline
// preview open in a preview, and every row can scroll to the reply that produced it.
//
// Media gathers every image, video and audio clip the thread shows, including signed links an
// action fetched from a remote service, which are otherwise hard to find again in a long thread.
// Images and clips are tiles, three to a row, that open one viewer stepping through them all;
// recordings are players, each with Download and a button that scrolls to its message.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import {
    Download,
    Eye,
    File as GenericFileIcon,
    FileCode,
    FileJson,
    FileSpreadsheet,
    FileText,
    Loader2,
    LocateFixed,
    Presentation,
    type LucideIcon,
} from 'lucide-react';
import type { ConversationMediaItem } from '../../lib/conversationMedia';
import {
    generatedFileDetails,
    type ConversationGeneratedFile,
    type GeneratedEntry,
    type GeneratedFileStatus,
} from '../../lib/conversationGeneratedFiles';
import { downloadGeneratedArtifact, saveBlob, type ConversationKind } from '../../lib/endpoints';
import { hasArtifactPreview, type GeneratedArtifact } from '../../lib/generatedArtifacts';
import { fetchGeneratedDocument, type GeneratedDocument } from '../../lib/generatedDocuments';
import { toast } from '../../stores/toastStore';
import { Modal } from '../ui/Modal';
import { PlainMarkdown } from '../ui/PlainMarkdown';
import { GlassButton } from '../ui/primitives';
import { ArtifactPreviewDialog } from './GeneratedArtifactCard';
import { InlineAudioPlayer } from './InlineAudioPlayer';
import { MediaViewer, type MediaViewerItem } from './MediaViewer';
import { ImageTile, VideoTile } from './MediaTiles';

/** Largest Markdown file previewed in the app; anything bigger is better read downloaded. */
const PREVIEW_MAX_BYTES = 2 * 1024 * 1024;

const ROW_BUTTON =
    'shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:opacity-50';

/** Spreadsheets, documents, decks and structured data each get an icon a person recognises. */
const FORMAT_ICONS: Readonly<Record<string, LucideIcon>> = {
    csv: FileSpreadsheet,
    tsv: FileSpreadsheet,
    xls: FileSpreadsheet,
    xlsx: FileSpreadsheet,
    docx: FileText,
    pdf: FileText,
    md: FileText,
    txt: FileText,
    pptx: Presentation,
    json: FileJson,
    xml: FileCode,
    yaml: FileCode,
};

/** Status pills share the tones of the plan's own file cards. */
const STATUS_TONES: Readonly<Record<Exclude<GeneratedFileStatus, 'ready'>, string>> = {
    pending: 'bg-surface-3 text-text-2',
    cancelled: 'bg-surface-3 text-text-2',
    failed: 'bg-danger-soft text-danger',
    withheld: 'bg-warn-soft text-warn',
    unavailable: 'bg-warn-soft text-warn',
};

function FormatIcon({ format }: { format: string }) {
    const Icon = FORMAT_ICONS[format] ?? GenericFileIcon;
    return <Icon size={16} className="mt-0.5 shrink-0 text-text-3" aria-hidden="true" />;
}

function extensionOf(fileName: string): string {
    return (/\.([a-z0-9]{1,8})$/i.exec(fileName)?.[1] ?? '').toLowerCase();
}

export function SectionHeading({ children }: { children: React.ReactNode }) {
    return (
        <h3 className="px-1 pb-1.5 text-[11px] font-medium tracking-wide text-text-3 uppercase">
            {children}
        </h3>
    );
}

function scopeLabel(document: GeneratedDocument): string {
    return document.workspace_scope === 'group' ? 'Group workspace' : 'Personal workspace';
}

function GeneratedDocumentPreview({
    conversationId,
    kind,
    document,
    onDownload,
    onClose,
}: {
    conversationId: string;
    kind: ConversationKind;
    document: GeneratedDocument;
    onDownload: () => void;
    onClose: () => void;
}) {
    const [content, setContent] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        fetchGeneratedDocument(conversationId, kind, document.document_id, controller.signal)
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
    }, [conversationId, kind, document.document_id]);

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

function LocateButton({ name, onLocate }: { name: string; onLocate: () => void }) {
    return (
        <button type="button" onClick={onLocate} aria-label={`Show ${name} in the conversation`}
            title="Show in conversation" className={ROW_BUTTON}>
            <LocateFixed size={15} />
        </button>
    );
}

/** A file a reply produced: a plan's rendered file, an export, or an analysis or research file. */
function GeneratedFileRow({
    file,
    busy,
    onDownload,
    onPreview,
    onLocate,
}: {
    file: ConversationGeneratedFile;
    busy: boolean;
    onDownload: () => void;
    onPreview: () => void;
    onLocate?: () => void;
}) {
    const ready = file.status === 'ready' && file.artifact !== null;
    const canPreview = ready && file.artifact !== null && hasArtifactPreview(file.artifact);

    return (
        <li className="glass-flat rounded-xl p-3" data-generated-file={file.key} data-generated-file-status={file.status}>
            <div className="flex items-start gap-2.5">
                <FormatIcon format={file.format} />
                <div className="min-w-0 flex-1">
                    {ready ? (
                        <button type="button" onClick={canPreview ? onPreview : onDownload} title={file.fileName}
                            className="block max-w-full truncate text-left text-sm text-text-1 hover:text-accent hover:underline">
                            {file.fileName}
                        </button>
                    ) : (
                        <p className="truncate text-sm text-text-1" title={file.fileName}>
                            {file.fileName}
                        </p>
                    )}
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-3">
                        <span>{generatedFileDetails(file)}</span>
                        {file.status !== 'ready' && file.statusLabel && (
                            <span className={clsx('rounded px-1.5 py-0.5 font-medium', STATUS_TONES[file.status])}>
                                {file.statusLabel}
                            </span>
                        )}
                    </p>
                </div>
                {canPreview && (
                    <button type="button" onClick={onPreview} aria-label={`Preview ${file.fileName}`} title="Preview"
                        className={ROW_BUTTON}>
                        <Eye size={15} />
                    </button>
                )}
                {ready && (
                    <button type="button" disabled={busy} onClick={onDownload}
                        aria-label={`Download ${file.fileName}`} title="Download" className={ROW_BUTTON}>
                        {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
                    </button>
                )}
                {onLocate && <LocateButton name={file.fileName} onLocate={onLocate} />}
            </div>
        </li>
    );
}

/** A document an agent created with a SimpleChat upload action, under its workspace's download rules. */
function GeneratedDocumentRow({
    document,
    busy,
    onDownload,
    onPreview,
    onLocate,
}: {
    document: GeneratedDocument;
    busy: boolean;
    onDownload: () => void;
    onPreview: () => void;
    onLocate?: () => void;
}) {
    const canPreview = document.can_download && document.preview === 'markdown';

    return (
        <li className="glass-flat rounded-xl p-3" data-generated-document={document.document_id}>
            <div className="flex items-start gap-2.5">
                <FormatIcon format={extensionOf(document.file_name)} />
                <div className="min-w-0 flex-1">
                    {document.can_download ? (
                        <button type="button" onClick={canPreview ? onPreview : onDownload} title={document.file_name}
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
                    <button type="button" onClick={onPreview}
                        aria-label={`Preview ${document.file_name}`} title="Preview" className={ROW_BUTTON}>
                        <Eye size={15} />
                    </button>
                )}
                {document.can_download && (
                    <button type="button" disabled={busy} onClick={onDownload}
                        aria-label={`Download ${document.file_name}`} title="Download" className={ROW_BUTTON}>
                        {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
                    </button>
                )}
                {onLocate && <LocateButton name={document.file_name} onLocate={onLocate} />}
            </div>
        </li>
    );
}

export function GeneratedSection({
    conversationId,
    kind,
    entries,
    error,
    onLocate,
}: {
    conversationId: string;
    kind: ConversationKind;
    entries: readonly GeneratedEntry[];
    /** Why the server's list of agent-created documents could not be read, if it could not. */
    error: string | null;
    /** Scrolls the thread to the reply that produced an entry. */
    onLocate?: (messageId: string) => void;
}) {
    const [previewingDocument, setPreviewingDocument] = useState<GeneratedDocument | null>(null);
    const [previewingFile, setPreviewingFile] = useState<GeneratedArtifact | null>(null);
    const [downloading, setDownloading] = useState<string | null>(null);

    const downloadDocument = useCallback(async (document: GeneratedDocument) => {
        setDownloading(`document:${document.document_id}`);
        try {
            const blob = await fetchGeneratedDocument(conversationId, kind, document.document_id);
            saveBlob(blob, document.file_name);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : 'Could not download the document.');
        } finally {
            setDownloading(null);
        }
    }, [conversationId, kind]);

    const downloadFile = useCallback(async (file: ConversationGeneratedFile) => {
        if (!file.artifact) {
            return;
        }
        setDownloading(file.key);
        try {
            await downloadGeneratedArtifact(file.artifact, conversationId);
        } catch {
            toast.error('The file could not be downloaded. Refresh the conversation and try again.');
        } finally {
            setDownloading(null);
        }
    }, [conversationId]);

    if (entries.length === 0 && !error) {
        return null;
    }

    return (
        <section aria-label="Generated documents" data-drawer-generated="">
            <SectionHeading>Generated</SectionHeading>
            {error && <p role="alert" className="px-1 text-xs text-danger">{error}</p>}
            <ul className="space-y-2">
                {entries.map((entry) => {
                    const locate = onLocate && entry.messageId ? () => onLocate(entry.messageId) : undefined;
                    return entry.kind === 'file' ? (
                        <GeneratedFileRow
                            key={entry.key}
                            file={entry.file}
                            busy={downloading === entry.file.key}
                            onDownload={() => void downloadFile(entry.file)}
                            onPreview={() => setPreviewingFile(entry.file.artifact)}
                            onLocate={locate}
                        />
                    ) : (
                        <GeneratedDocumentRow
                            key={entry.key}
                            document={entry.document}
                            busy={downloading === `document:${entry.document.document_id}`}
                            onDownload={() => void downloadDocument(entry.document)}
                            onPreview={() => setPreviewingDocument(entry.document)}
                            onLocate={locate}
                        />
                    );
                })}
            </ul>
            {previewingDocument && (
                <GeneratedDocumentPreview
                    conversationId={conversationId}
                    kind={kind}
                    document={previewingDocument}
                    onDownload={() => void downloadDocument(previewingDocument)}
                    onClose={() => setPreviewingDocument(null)}
                />
            )}
            {previewingFile && (
                <ArtifactPreviewDialog artifact={previewingFile} onClose={() => setPreviewingFile(null)} />
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
