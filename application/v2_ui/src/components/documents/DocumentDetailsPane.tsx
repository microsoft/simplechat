// DocumentDetailsPane.tsx
// The right-hand pane: what is selected, and what can be done with it.
//
// Three states, matching a file manager's details pane. Nothing selected, one document, or
// several. The multi-selection state is the one that earns the pane: it is where a bulk
// operation can state what it is about to touch -- how many documents, how large, which tags
// they already share -- instead of a toolbar button acting on an invisible set.
//
// Metadata is presented, not previewed. There is no general document-preview endpoint, so
// promising a preview here would mean promising something the server cannot supply.

import {
    Check,
    Download,
    FileStack,
    MessageSquare,
    PanelRightClose,
    Pencil,
    RefreshCw,
    Share2,
    Sparkles,
    Tag as TagIcon,
    Trash2,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import type { WorkspaceDocument } from '../../lib/types';
import { isScreeningAvailable } from '../../lib/contentScreening';
import {
    documentSelectionReason, groupDocumentOrigin, type DocumentReadAdapter,
} from '../../lib/documentReadAdapter';
import type { DocumentOperation } from '../../lib/documentOperations';
import { ScreeningStatusBadge } from '../screening/ScreeningStatusBadge';
import {
    commonTags,
    documentDate,
    documentDisplayName,
    documentId,
    extractionMode as documentExtractionMode,
    extractionModeLabel,
    formatAbsoluteDate,
    formatFileSize,
    normalizeStringList,
    normalizeTags,
    summarizeExtraction,
    totalFileSize,
    type ExtractionMode,
} from '../../lib/documentExplorer';
import { GlassButton } from '../ui/primitives';
import { errorMessage } from '../workspace/useSectionResource';
import {
    ClassificationBadge,
    DocumentIcon,
    DocumentStatusBadge,
    TagChip,
} from './documentPresentation';

function Field({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="grid grid-cols-[7rem_1fr] gap-2 py-1 text-xs">
            <dt className="text-text-3">{label}</dt>
            <dd className="min-w-0 break-words text-text-2">{children}</dd>
        </div>
    );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className="border-t border-edge px-3 py-2.5">
            <h4 className="mb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                {title}
            </h4>
            {children}
        </section>
    );
}

export interface DocumentActionAvailability {
    upload: boolean;
    tagDocuments: boolean;
    manageTags: boolean;
    editMetadata: boolean;
    deleteDocuments: boolean;
    reprocess: boolean;
    allows: (operation: DocumentOperation, documents?: readonly WorkspaceDocument[]) => boolean;
    chat: boolean;
    downloads: boolean;
    extractMetadata: boolean;
    sharing: boolean;
    classification: boolean;
    /**
     * Whether Enhanced extraction is switched on for the deployment.
     *
     * The reprocess route rejects a request for `layout` outright when it is not, so the
     * option is disabled with a reason rather than offered and refused.
     */
    enhancedExtraction: boolean;
    canReview?: (document: WorkspaceDocument) => boolean;
}

export interface DocumentPaneActions {
    onChat: (documents: WorkspaceDocument[]) => void;
    onDownload: (documents: WorkspaceDocument[]) => void;
    onEditMetadata: (document: WorkspaceDocument) => void;
    onExtractMetadata: (documents: WorkspaceDocument[]) => void;
    onReextract: (documents: WorkspaceDocument[], mode: 'read' | 'layout') => void;
    onShare: (document: WorkspaceDocument) => void;
    onManageTags: (documents: WorkspaceDocument[]) => void;
    onDelete: (documents: WorkspaceDocument[]) => void;
    onSelectTag: (tag: string) => void;
    onRemoveTag: (documents: WorkspaceDocument[], tag: string) => void;
    onReview?: (document: WorkspaceDocument) => void;
}

function ActionButtons({
    documents,
    availability,
    actions,
    selectionReason,
}: {
    documents: WorkspaceDocument[];
    availability: DocumentActionAvailability;
    actions: DocumentPaneActions;
    selectionReason: (document: WorkspaceDocument) => string | null;
}) {
    const single = documents.length === 1 ? documents[0] : null;
    const blockedReason = documents.map(selectionReason).find(Boolean);
    return (
        <>
        {blockedReason ? <p className="px-3 py-2.5 text-xs text-text-3">{blockedReason}</p> : null}
        <div className="flex flex-wrap gap-1.5 px-3 py-2.5">
            {single && actions.onReview && availability.canReview?.(single) ? (
                <GlassButton variant="subtle" size="sm" onClick={() => actions.onReview?.(single)}>
                    <Share2 size={14} />Sharing and review
                </GlassButton>
            ) : null}
            <GlassButton variant="primary" size="sm" disabled={!availability.chat || Boolean(blockedReason)} onClick={() => actions.onChat(documents)}>
                <MessageSquare size={14} />
                Chat
            </GlassButton>

            {availability.downloads ? (
                <GlassButton variant="subtle" size="sm" disabled={!availability.allows('download', documents)} onClick={() => actions.onDownload(documents)}>
                    <Download size={14} />
                    Download
                </GlassButton>
            ) : null}

            {availability.tagDocuments ? <GlassButton variant="subtle" size="sm" disabled={!availability.allows('tag_documents', documents)} onClick={() => actions.onManageTags(documents)}>
                <TagIcon size={14} />
                Tag
            </GlassButton> : null}

            {single && availability.editMetadata ? (
                <GlassButton
                    variant="subtle"
                    size="sm"
                    disabled={!availability.allows('edit_metadata', documents)}
                    onClick={() => actions.onEditMetadata(single)}
                >
                    <Pencil size={14} />
                    Edit
                </GlassButton>
            ) : null}

            {availability.extractMetadata ? (
                <GlassButton
                    variant="subtle"
                    size="sm"
                    onClick={() => actions.onExtractMetadata(documents)}
                    disabled={!availability.allows('extract_metadata', documents)}
                    title="Ask the model to re-read the file and fill in title, authors, keywords and abstract"
                >
                    <Sparkles size={14} />
                    Extract
                </GlassButton>
            ) : null}

            {single && availability.sharing ? (
                <GlassButton variant="subtle" size="sm" onClick={() => actions.onShare(single)}>
                    <Share2 size={14} />
                    Share
                </GlassButton>
            ) : null}

            {availability.deleteDocuments ? <GlassButton variant="danger" size="sm" disabled={!availability.allows('delete', documents)} onClick={() => actions.onDelete(documents)}>
                <Trash2 size={14} />
                Delete
            </GlassButton> : null}
        </div>
        </>
    );
}

/**
 * The re-extraction control.
 *
 * Previously two equal buttons labelled Standard and Enhanced, with nothing saying which one
 * the document was already on -- so changing it meant guessing and then checking. The current
 * mode is now stated, the button for it is inert and marked as current, and the other one is
 * the actionable choice. Documents that are neither PDFs nor images do not go through
 * Document Intelligence at all, so the control is not offered for them.
 */
function ReextractSection({
    documents,
    enhancedEnabled,
    onReextract,
    disabled = false,
    requireAll = false,
}: {
    documents: WorkspaceDocument[];
    enhancedEnabled: boolean;
    onReextract: (documents: WorkspaceDocument[], mode: ExtractionMode) => void;
    disabled?: boolean;
    requireAll?: boolean;
}) {
    const { supported, unsupported, current } = summarizeExtraction(documents.filter(isScreeningAvailable));

    if (supported.length === 0) {
        return null;
    }

    const currentLabel =
        current === 'mixed'
            ? 'Mixed'
            : current
              ? extractionModeLabel(current)
              : 'Not recorded';

    const options: { mode: ExtractionMode; label: string; hint: string }[] = [
        {
            mode: 'read',
            label: 'Standard',
            hint: 'Faster and cheaper. Best for plain text PDFs and images.',
        },
        {
            mode: 'layout',
            label: 'Enhanced',
            hint: 'Preserves tables, page structure and checkboxes. Slower and costlier.',
        },
    ];

    return (
        <Section title="Extraction">
            <p className="mb-2 text-xs text-text-2">
                Currently:{' '}
                <span className="font-medium text-text-1">{currentLabel}</span>
                {supported.length > 1 ? (
                    <span className="text-text-3">
                        {' '}
                        across {supported.length} documents
                    </span>
                ) : null}
            </p>

            <div className="flex flex-wrap gap-1.5">
                {options.map((option) => {
                    const isCurrent = current === option.mode;
                    const blocked = option.mode === 'layout' && !enhancedEnabled;

                    if (isCurrent) {
                        return (
                            <span
                                key={option.mode}
                                className="inline-flex items-center gap-1 rounded-xl border border-edge bg-surface-2 px-3 py-1.5 text-sm text-text-3"
                                title={`These documents were already extracted with ${option.label}.`}
                            >
                                <Check size={13} />
                                {option.label}
                                <span className="text-[11px]">(current)</span>
                            </span>
                        );
                    }

                    return (
                        <GlassButton
                            key={option.mode}
                            variant="subtle"
                            size="sm"
                            disabled={blocked || disabled}
                            onClick={() => onReextract(requireAll ? documents : supported, option.mode)}
                            title={
                                disabled ? 'Every selected document must permit reprocessing.' : blocked
                                    ? 'Enhanced extraction is switched off for this deployment.'
                                    : `${option.hint} Re-reads ${supported.length === 1 ? 'this document' : `these ${supported.length} documents`}.`
                            }
                        >
                            <RefreshCw size={13} />
                            {current ? `Switch to ${option.label}` : `Extract as ${option.label}`}
                        </GlassButton>
                    );
                })}
            </div>

            {unsupported.length > 0 && requireAll ? <p className="mt-1.5 text-xs text-text-3">
                Choose only documents that support reprocessing; this selection will not be silently reduced.
            </p> : unsupported.length > 0 ? (
                <p className="mt-1.5 text-[11px] text-text-3">
                    {unsupported.length} of the selected{' '}
                    {unsupported.length === 1 ? 'document is' : 'documents are'} not a PDF or
                    image, so the extraction mode does not apply and{' '}
                    {unsupported.length === 1 ? 'it will' : 'they will'} be left alone.
                </p>
            ) : null}
        </Section>
    );
}

function DocumentVersions({
    document, reader, enabled,
}: {
    document: WorkspaceDocument;
    reader: DocumentReadAdapter;
    enabled: boolean;
}) {
    const [open, setOpen] = useState(false);
    const [versions, setVersions] = useState<WorkspaceDocument[] | null>(null);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);
    const id = documentId(document);

    useEffect(() => {
        if (!open || !enabled) return;
        const controller = new AbortController();
        setVersions(null);
        setError('');
        void reader.versions(id, controller.signal).then((response) => {
            if (!controller.signal.aborted) setVersions(response.versions ?? []);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setError(errorMessage(cause, 'Could not load version history.'));
        });
        return () => controller.abort();
    }, [id, reader, open, enabled, retry]);

    return (
        <Section title="Versions">
            <GlassButton size="sm" variant="subtle" disabled={!enabled} aria-expanded={open}
                onClick={() => setOpen((value) => !value)}>
                <FileStack size={14} />{open ? 'Hide version history' : 'Version history'}
            </GlassButton>
            {open ? (
                error ? <div role="alert" className="mt-2 space-y-2 text-xs text-danger">
                    <p>{error}</p>
                    <GlassButton size="sm" disabled={!enabled} onClick={() => setRetry((value) => value + 1)}>Retry version history</GlassButton>
                </div> : versions === null ? <p role="status" className="mt-2 text-xs text-text-3">Loading version history...</p>
                    : versions.length === 0 ? <p className="mt-2 text-xs text-text-3">No accessible versions were returned.</p>
                        : <ul className="mt-2 divide-y divide-edge">
                            {versions.map((version) => (
                                <li key={documentId(version)} className="space-y-1 py-2 text-xs">
                                    <p className="break-words font-medium text-text-1">
                                        Version {version.version ?? 'not recorded'}{version.is_current_version ? ' (current)' : ''}
                                    </p>
                                    <p className="break-words text-text-2">{documentDisplayName(version).primary}</p>
                                    <p className="text-text-3">{formatAbsoluteDate(documentDate(version))}</p>
                                    {reader.scope.kind === 'group' ? <p className="text-text-3">{groupDocumentOrigin(version, reader.scope.id)}</p> : null}
                                    <DocumentStatusBadge document={version} />
                                </li>
                            ))}
                        </ul>
            ) : null}
        </Section>
    );
}

export function DocumentDetailsPane({
    documents,
    availability,
    actions,
    tagColors,
    classificationColors,
    onClose,
    reader,
    selectionReason,
    onRefresh,
    loading,
    error,
    interactionDisabled,
    compact = false,
}: {
    /** The current selection, resolved to documents. */
    documents: WorkspaceDocument[];
    availability: DocumentActionAvailability;
    actions: DocumentPaneActions;
    tagColors: Record<string, string | undefined>;
    classificationColors: Record<string, string | undefined>;
    onClose: () => void;
    reader: DocumentReadAdapter;
    selectionReason: (document: WorkspaceDocument) => string | null;
    onRefresh: () => void;
    loading: boolean;
    error: string | null;
    interactionDisabled: boolean;
    compact?: boolean;
}) {
    const paneClassName = clsx('flex h-full shrink-0 flex-col overflow-hidden rounded-xl border border-edge bg-surface-1', compact ? 'w-full' : 'w-80');
    const header = (
        <div className="flex items-center justify-between gap-2 px-3 py-2">
            <h3 className="truncate text-xs font-semibold tracking-wide text-text-3 uppercase">
                Details
            </h3>
            {documents.length === 1 ? <button type="button" onClick={onRefresh}
                disabled={loading || interactionDisabled} aria-label="Refresh document details"
                className="ml-auto rounded-lg p-1 text-text-3 hover:bg-surface-2 hover:text-text-1 disabled:opacity-50">
                <RefreshCw size={15} className={loading ? 'animate-spin' : undefined} />
            </button> : null}
            <button
                type="button"
                onClick={onClose}
                aria-label="Hide details pane"
                className="rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
            >
                <PanelRightClose size={15} />
            </button>
        </div>
    );

    if (error) return (
        <aside className={paneClassName}>
            {header}
            <div role="alert" className="space-y-2 px-3 py-2 text-xs text-danger">
                <p>{error}</p>
                <GlassButton size="sm" disabled={interactionDisabled || loading} onClick={onRefresh}>Retry document details</GlassButton>
            </div>
        </aside>
    );

    if (documents.length === 0) {
        return (
            <aside className={paneClassName}>
                {header}
                <p className="px-3 py-6 text-center text-xs text-text-3">
                    Select a document to see its details.
                </p>
            </aside>
        );
    }

    if (documents.length > 1) {
        const shared = commonTags(documents);
        return (
            <aside className={paneClassName}>
                {header}
                <div className="min-h-0 flex-1 overflow-y-auto">
                    <div className="flex items-center gap-2.5 px-3 pb-3">
                        <FileStack size={22} className="shrink-0 text-text-3" />
                        <div className="min-w-0">
                            <p className="text-sm font-medium text-text-1">
                                {documents.length} documents selected
                            </p>
                            <p className="text-xs text-text-3">
                                {formatFileSize(totalFileSize(documents))} total
                            </p>
                        </div>
                    </div>

                    <Section title="Tags on all selected">
                        {shared.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                                {shared.map((tag) => (
                                    <TagChip
                                        key={tag}
                                        name={tag}
                                        color={tagColors[tag]}
                                        onRemove={availability.allows('tag_documents', documents) ? () => actions.onRemoveTag(documents, tag) : undefined}
                                    />
                                ))}
                            </div>
                        ) : (
                            <p className="text-xs text-text-3">
                                These documents have no tag in common.
                            </p>
                        )}
                    </Section>

                    {availability.reprocess ? <ReextractSection
                        documents={documents}
                        enhancedEnabled={availability.enhancedExtraction}
                        onReextract={actions.onReextract}
                        disabled={!availability.allows('reprocess', documents)}
                        requireAll={reader.scope.kind === 'group'}
                    /> : null}
                </div>

                <div className="border-t border-edge">
                    <ActionButtons
                        documents={documents}
                        availability={availability}
                        actions={actions}
                        selectionReason={selectionReason}
                    />
                </div>
            </aside>
        );
    }

    const document = documents[0];
    const available = !documentSelectionReason(document, reader.scope);
    const { primary, secondary } = documentDisplayName(document);
    const tags = normalizeTags(document.tags);
    const authors = available ? normalizeStringList(document.authors) : [];
    const keywords = available ? normalizeStringList(document.keywords) : [];
    const classification = String(document.document_classification ?? '').trim();
    const abstract = available ? String(document.abstract ?? '').trim() : '';
    const currentExtraction = documentExtractionMode(document);
    const sharedCount = Array.isArray(document.shared_user_ids)
        ? document.shared_user_ids.length
        : 0;

    return (
        <aside className={paneClassName}>
            {header}
            <div className="min-h-0 flex-1 overflow-y-auto">
                {loading ? <p role="status" className="px-3 pb-2 text-xs text-text-3">Refreshing document details...</p> : null}
                <div className="flex items-start gap-2.5 px-3 pb-3">
                    <DocumentIcon document={document} size={22} className="mt-0.5" />
                    <div className="min-w-0">
                        <p className="text-sm font-medium break-words text-text-1">{primary}</p>
                        {secondary ? (
                            <p className="text-xs break-all text-text-3">{secondary}</p>
                        ) : null}
                        <div className="mt-1.5">
                            <DocumentStatusBadge document={document} showProgressBar />
                        </div>
                    </div>
                </div>

                {reader.scope.kind === 'group' ? <Section title="Group access">
                    <p className="text-xs text-text-2">{groupDocumentOrigin(document, reader.scope.id)}</p>
                    <p className="mt-1 text-xs text-text-3">Browsing {reader.scope.name}. Actions follow this group's current permissions.</p>
                </Section> : null}

                {Object.prototype.hasOwnProperty.call(document, 'content_screening') ? (
                    <Section title="Content screening">
                        <ScreeningStatusBadge summary={document.content_screening ?? null} detail />
                    </Section>
                ) : null}

                <Section title="Tags">
                    {tags.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                            {tags.map((tag) => (
                                <TagChip
                                    key={tag}
                                    name={tag}
                                    color={tagColors[tag]}
                                    onClick={() => actions.onSelectTag(tag)}
                                    onRemove={available && availability.allows('tag_documents', [document]) ? () => actions.onRemoveTag([document], tag) : undefined}
                                />
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-text-3">Not tagged.</p>
                    )}
                </Section>

                <Section title="File">
                    <dl>
                        {availability.classification && classification ? (
                            <Field label="Classification">
                                <ClassificationBadge
                                    classification={classification}
                                    color={classificationColors[classification]}
                                />
                            </Field>
                        ) : null}
                        <Field label="Size">{formatFileSize(document.file_size)}</Field>
                        <Field label="Pages">{document.number_of_pages ?? '—'}</Field>
                        <Field label="Version">{document.version ?? '—'}</Field>
                        <Field label="Chunks">{document.num_chunks ?? '—'}</Field>
                        <Field label="Uploaded">
                            {formatAbsoluteDate(documentDate(document))}
                        </Field>
                        {currentExtraction ? (
                            <Field label="Extraction">
                                {extractionModeLabel(currentExtraction)}
                            </Field>
                        ) : null}
                    </dl>
                </Section>

                {available && (authors.length > 0 || keywords.length > 0 || document.publication_date) ? (
                    <Section title="Metadata">
                        <dl>
                            {authors.length > 0 ? (
                                <Field label="Authors">{authors.join(', ')}</Field>
                            ) : null}
                            {keywords.length > 0 ? (
                                <Field label="Keywords">{keywords.join(', ')}</Field>
                            ) : null}
                            {document.publication_date ? (
                                <Field label="Published">
                                    {String(document.publication_date)}
                                </Field>
                            ) : null}
                        </dl>
                    </Section>
                ) : null}

                {abstract ? (
                    <Section title="Abstract">
                        <p className="text-xs leading-relaxed text-text-2">{abstract}</p>
                    </Section>
                ) : null}

                {availability.sharing && sharedCount > 0 ? (
                    <Section title="Sharing">
                        <p className="text-xs text-text-2">
                            Shared with {sharedCount} {sharedCount === 1 ? 'person' : 'people'}.
                        </p>
                    </Section>
                ) : null}

                {document.created_from_chat_upload && document.conversation_id ? (
                    <Section title="Source">
                        <p className="text-xs text-text-2">
                            Uploaded through chat
                            {document.conversation_title_at_upload
                                ? ` in "${document.conversation_title_at_upload}"`
                                : ''}
                            .
                        </p>
                    </Section>
                ) : null}

                <DocumentVersions key={documentId(document)} document={document} reader={reader} enabled={!interactionDisabled} />

                {availability.reprocess ? <ReextractSection
                    documents={[document]}
                    enhancedEnabled={availability.enhancedExtraction}
                    onReextract={actions.onReextract}
                    disabled={!availability.allows('reprocess', [document])}
                    requireAll={reader.scope.kind === 'group'}
                /> : null}
            </div>

            <div className="border-t border-edge">
                <ActionButtons
                    documents={documents}
                    availability={availability}
                    actions={actions}
                    selectionReason={selectionReason}
                />
            </div>
        </aside>
    );
}
