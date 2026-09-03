// ConversationDetails.tsx
// Conversation metadata view, opened from the chat header.
//
// Renders only fields GET /api/conversations/<id>/metadata actually returns. The route keys
// on conversation_id (not id) and carries no created_at, participants or permission flags,
// so none of those are displayed.
//
// The route's `tags` array is heterogeneous — every entry carries a `category`, and the
// useful fields differ per category. Flattening them into one list is what made documents
// appear mixed in with everything else, so each category gets its own section.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import {
    Check,
    ChevronLeft,
    ChevronRight,
    Cpu,
    Download,
    ExternalLink,
    Eye,
    EyeOff,
    FileText,
    Loader2,
    Lock,
    Pencil,
    Pin,
    Sparkles,
    Tags,
    TriangleAlert,
    Users,
    X,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { generateConversationSummary } from '../../lib/endpoints';
import { ConversationExportDialog } from './ConversationExportDialog';
import {
    formatChatType,
    labelsOfCategory,
    readContexts,
    readLinkedDocuments,
    readLockedContexts,
    readSourceDocuments,
    webSources,
    type DocumentSummary,
} from '../../lib/conversationDetails';
import { GlassButton, GlassPanel, Skeleton } from '../ui/primitives';
import type { ConversationMetadata } from '../../lib/types';

/** Source documents shown per page before paging. */
const DOCUMENTS_PER_PAGE = 6;

function formatTimestamp(value?: string | null): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }
    return parsed.toLocaleString();
}

function classificationList(value: ConversationMetadata['classification']): string[] {
    if (Array.isArray(value)) {
        return value.map(String).filter(Boolean);
    }
    if (typeof value === 'string' && value.trim()) {
        return [value.trim()];
    }
    return [];
}

function Section({
    title,
    icon,
    count,
    children,
}: {
    title: string;
    icon?: React.ReactNode;
    count?: number;
    children: React.ReactNode;
}) {
    return (
        <section className="border-t border-edge py-3 first:border-t-0 first:pt-0">
            <h3 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                {icon}
                {title}
                {typeof count === 'number' && count > 0 && (
                    <span className="opacity-70">({count})</span>
                )}
            </h3>
            {children}
        </section>
    );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="flex gap-3 py-1">
            <dt className="w-36 shrink-0 text-xs text-text-3">{label}</dt>
            <dd className="min-w-0 flex-1 text-sm break-words text-text-1">{children}</dd>
        </div>
    );
}

function Chips({ labels }: { labels: string[] }) {
    return (
        <div className="flex flex-wrap gap-1.5">
            {labels.map((label) => (
                <span
                    key={label}
                    className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-xs text-text-1"
                >
                    {label}
                </span>
            ))}
        </div>
    );
}

function TitleEditor({ metadata }: { metadata: ConversationMetadata }) {
    const { renameConversation, loadMetadata } = useChatStore();
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(metadata.title);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setDraft(metadata.title);
    }, [metadata.title]);

    const commit = async () => {
        const trimmed = draft.trim();
        if (!trimmed || trimmed === metadata.title) {
            setDraft(metadata.title);
            setEditing(false);
            return;
        }
        setSaving(true);
        await renameConversation(metadata.conversation_id, trimmed);
        // Re-read so the panel reflects what was actually stored rather than the draft.
        await loadMetadata(metadata.conversation_id);
        setSaving(false);
        setEditing(false);
    };

    if (!editing) {
        return (
            <div className="flex items-start gap-2">
                <span className="min-w-0 flex-1 break-words">{metadata.title}</span>
                <button
                    type="button"
                    onClick={() => setEditing(true)}
                    aria-label="Rename conversation"
                    className="shrink-0 rounded-md p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <Pencil size={13} />
                </button>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-1.5">
            <input
                autoFocus
                value={draft}
                disabled={saving}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        void commit();
                    }
                    if (event.key === 'Escape') {
                        setDraft(metadata.title);
                        setEditing(false);
                    }
                }}
                aria-label="Conversation title"
                className="min-w-0 flex-1 rounded-lg border border-accent bg-surface-solid px-2 py-1 text-sm text-text-1 outline-none"
            />
            <button
                type="button"
                onClick={() => void commit()}
                disabled={saving}
                aria-label="Save title"
                className="shrink-0 rounded-md p-1 text-accent transition-colors hover:bg-surface-2"
            >
                <Check size={15} />
            </button>
        </div>
    );
}

/**
 * The conversation summary, generated on demand.
 *
 * The summary is produced by a model, so it is not created automatically; it is requested,
 * persisted, and afterwards returned by the metadata endpoint like any other field.
 */
function SummarySection({ metadata }: { metadata: ConversationMetadata }) {
    const { loadMetadata } = useChatStore();
    const [busy, setBusy] = useState(false);
    const summary = metadata.summary;

    const generate = async () => {
        setBusy(true);
        try {
            await generateConversationSummary(metadata.conversation_id);
            // Re-read rather than trusting the response, so the panel shows what was stored.
            await loadMetadata(metadata.conversation_id);
            toast.success('Summary generated.');
        } catch (error) {
            toast.error(
                error instanceof Error ? error.message : 'The summary could not be generated.',
            );
        } finally {
            setBusy(false);
        }
    };

    return (
        <Section title="Summary" icon={<Sparkles size={12} />}>
            {summary?.content ? (
                <>
                    <p className="text-sm whitespace-pre-wrap text-text-1">{summary.content}</p>
                    <p className="mt-1.5 text-xs text-text-3">
                        {[summary.model_deployment, formatTimestamp(summary.generated_at)]
                            .filter(Boolean)
                            .join(' · ')}
                    </p>
                </>
            ) : (
                <p className="text-sm text-text-3">
                    No summary has been generated for this conversation.
                </p>
            )}
            <GlassButton
                size="sm"
                onClick={() => void generate()}
                disabled={busy}
                className="mt-2"
            >
                {busy && <Loader2 size={13} className="animate-spin" />}
                {summary?.content ? 'Regenerate summary' : 'Generate summary'}
            </GlassButton>
        </Section>
    );
}

function DocumentRow({ document }: { document: DocumentSummary }) {
    return (
        <li className="flex items-start gap-2 rounded-lg bg-surface-sunken px-2.5 py-2 text-xs">
            <FileText size={13} className="mt-0.5 shrink-0 text-text-3" />
            <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5">
                    <span className="min-w-0 truncate text-text-1">{document.title}</span>
                    {document.cited && (
                        <span className="shrink-0 rounded-full bg-accent-soft px-1.5 text-[10px] text-accent">
                            cited
                        </span>
                    )}
                </p>
                <p className="mt-0.5 flex flex-wrap gap-x-2 text-text-3">
                    {document.locations.length > 0 && (
                        <span>{document.locations.join(', ')}</span>
                    )}
                    {document.chunkCount > 0 && (
                        <span>
                            {document.chunkCount} excerpt
                            {document.chunkCount === 1 ? '' : 's'}
                        </span>
                    )}
                    {document.scopeName && <span>{document.scopeName}</span>}
                    {document.classification && <span>{document.classification}</span>}
                </p>
            </div>
        </li>
    );
}

/**
 * Source documents, paged.
 *
 * A long conversation can draw on dozens of documents, and an unbounded list pushes
 * everything else out of reach.
 */
function SourceDocumentsSection({ metadata }: { metadata: ConversationMetadata }) {
    const { documents, citationTracked } = useMemo(
        () => readSourceDocuments(metadata),
        [metadata],
    );
    const [page, setPage] = useState(0);

    useEffect(() => {
        setPage(0);
    }, [metadata.conversation_id]);

    if (documents.length === 0) {
        return null;
    }

    const pageCount = Math.ceil(documents.length / DOCUMENTS_PER_PAGE);
    const current = Math.min(page, pageCount - 1);
    const visible = documents.slice(
        current * DOCUMENTS_PER_PAGE,
        current * DOCUMENTS_PER_PAGE + DOCUMENTS_PER_PAGE,
    );

    return (
        <Section
            title="Source documents"
            icon={<FileText size={12} />}
            count={documents.length}
        >
            <ul className="space-y-1">
                {visible.map((document) => (
                    <DocumentRow
                        key={document.documentId || document.title}
                        document={document}
                    />
                ))}
            </ul>

            {pageCount > 1 && (
                <div className="mt-2 flex items-center justify-end gap-1">
                    <button
                        type="button"
                        onClick={() => setPage(Math.max(0, current - 1))}
                        disabled={current === 0}
                        aria-label="Previous page of documents"
                        className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
                    >
                        <ChevronLeft size={14} />
                    </button>
                    <span className="font-mono text-[11px] text-text-3">
                        {current + 1}/{pageCount}
                    </span>
                    <button
                        type="button"
                        onClick={() => setPage(Math.min(pageCount - 1, current + 1))}
                        disabled={current >= pageCount - 1}
                        aria-label="Next page of documents"
                        className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
                    >
                        <ChevronRight size={14} />
                    </button>
                </div>
            )}

            <p className="mt-2 text-[11px] text-text-3">
                {citationTracked
                    ? 'All documents returned for this conversation are listed. "Cited" marks those a response actually referenced.'
                    : 'All associated documents are listed. This conversation predates citation tracking, so which were actually referenced was not recorded.'}
            </p>
        </Section>
    );
}

export function ConversationDetails({ onClose }: { onClose: () => void }) {
    const { metadata, metadataLoading, metadataError, activeConversationId, loadMetadata } =
        useChatStore();
    const classificationEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_document_classification),
    );

    const [exporting, setExporting] = useState(false);

    useEffect(() => {
        if (activeConversationId && !metadata && !metadataLoading && !metadataError) {
            void loadMetadata(activeConversationId);
        }
    }, [activeConversationId, metadata, metadataLoading, metadataError, loadMetadata]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            // The export wizard is rendered inside this dialog and closes itself on Escape.
            // Without this guard one keypress would dismiss both, losing the details view
            // the user was reading as a side effect of cancelling an export.
            if (event.key === 'Escape' && !exporting) {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose, exporting]);

    const classifications = metadata ? classificationList(metadata.classification) : [];
    const models = labelsOfCategory(metadata, 'model');
    const agents = labelsOfCategory(metadata, 'agent');
    const participants = labelsOfCategory(metadata, 'participant');
    const semantic = labelsOfCategory(metadata, 'semantic');
    const web = webSources(metadata);
    const contexts = readContexts(metadata);
    const lockedContexts = readLockedContexts(metadata);
    const linked = readLinkedDocuments(metadata);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation details"
        >
            <div
                className="absolute inset-0 bg-black/40"
                aria-hidden="true"
                onClick={onClose}
            />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[85vh] w-full max-w-2xl flex-col"
            >
                <div className="flex h-14 shrink-0 items-center border-b border-edge px-5">
                    <h2 className="text-[15px] font-semibold text-text-1">
                        Conversation details
                    </h2>
                    {activeConversationId && (
                        <button
                            type="button"
                            onClick={() => setExporting(true)}
                            title="Export this conversation"
                            className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <Download size={14} /> Export
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close details"
                        className={clsx(
                            'rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            activeConversationId ? 'ml-1' : 'ml-auto',
                        )}
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {metadataLoading && !metadata && (
                        <div className="space-y-2">
                            {Array.from({ length: 6 }).map((_, index) => (
                                <Skeleton key={index} className="h-6 w-full" />
                            ))}
                        </div>
                    )}

                    {metadataError && (
                        <p className="flex items-start gap-2 text-sm text-danger">
                            <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                            {metadataError}
                        </p>
                    )}

                    {metadata && (
                        <>
                            <SummarySection metadata={metadata} />

                            <Section title="About">
                                <dl>
                                    <Row label="Title">
                                        <TitleEditor metadata={metadata} />
                                    </Row>
                                    <Row label="Identifier">
                                        <code className="font-mono text-xs break-all text-text-2">
                                            {metadata.conversation_id}
                                        </code>
                                    </Row>
                                    {metadata.last_updated && (
                                        <Row label="Last updated">
                                            {formatTimestamp(metadata.last_updated)}
                                        </Row>
                                    )}
                                    {metadata.chat_type && (
                                        <Row label="Type">
                                            {formatChatType(metadata.chat_type)}
                                        </Row>
                                    )}
                                    {metadata.workflow_id && (
                                        <Row label="Workflow">
                                            <code className="font-mono text-xs break-all text-text-2">
                                                {metadata.workflow_id}
                                            </code>
                                        </Row>
                                    )}
                                    <Row label="State">
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            <span
                                                className={clsx(
                                                    'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                                                    metadata.is_pinned
                                                        ? 'bg-accent-soft text-accent'
                                                        : 'bg-surface-sunken text-text-3',
                                                )}
                                            >
                                                <Pin size={11} />
                                                {metadata.is_pinned ? 'Pinned' : 'Not pinned'}
                                            </span>
                                            <span
                                                className={clsx(
                                                    'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                                                    metadata.is_hidden
                                                        ? 'bg-warn-soft text-warn'
                                                        : 'bg-surface-sunken text-text-3',
                                                )}
                                            >
                                                {metadata.is_hidden ? (
                                                    <EyeOff size={11} />
                                                ) : (
                                                    <Eye size={11} />
                                                )}
                                                {metadata.is_hidden ? 'Hidden' : 'Visible'}
                                            </span>
                                            {metadata.scope_locked && (
                                                <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-xs text-warn">
                                                    <Lock size={11} />
                                                    Scope locked
                                                </span>
                                            )}
                                            {metadata.strict && (
                                                <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-text-3">
                                                    Strict
                                                </span>
                                            )}
                                        </div>
                                    </Row>
                                    {classificationEnabled && classifications.length > 0 && (
                                        <Row label="Classification">
                                            <Chips labels={classifications} />
                                        </Row>
                                    )}
                                </dl>
                            </Section>

                            {contexts.length > 0 && (
                                <Section title="Workspaces" icon={<Lock size={12} />}>
                                    <ul className="space-y-1">
                                        {contexts.map((context) => (
                                            <li
                                                key={`${context.scope}-${context.id}-${context.type}`}
                                                className="flex items-center gap-2 rounded-lg bg-surface-sunken px-2.5 py-1.5 text-xs"
                                            >
                                                <span className="rounded-full bg-surface-2 px-1.5 text-[10px] text-text-3">
                                                    {context.type}
                                                </span>
                                                <span className="min-w-0 flex-1 truncate text-text-1">
                                                    {context.name || context.id}
                                                </span>
                                                <span className="text-text-3">
                                                    {context.scope}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                    {lockedContexts.length > 0 && (
                                        <p className="mt-1.5 text-[11px] text-text-3">
                                            {lockedContexts.length} of these{' '}
                                            {lockedContexts.length === 1 ? 'is' : 'are'} locked
                                            to this conversation:{' '}
                                            {lockedContexts.join(', ')}.
                                        </p>
                                    )}
                                </Section>
                            )}

                            <SourceDocumentsSection metadata={metadata} />

                            {linked.length > 0 && (
                                <Section
                                    title="Linked documents"
                                    icon={<FileText size={12} />}
                                    count={linked.length}
                                >
                                    <ul className="space-y-1">
                                        {linked.map((document) => (
                                            <DocumentRow
                                                key={document.documentId || document.title}
                                                document={document}
                                            />
                                        ))}
                                    </ul>
                                </Section>
                            )}

                            {(models.length > 0 || agents.length > 0) && (
                                <Section title="Models and agents" icon={<Cpu size={12} />}>
                                    <dl>
                                        {models.length > 0 && (
                                            <Row label="Models">
                                                <Chips labels={models} />
                                            </Row>
                                        )}
                                        {agents.length > 0 && (
                                            <Row label="Agents">
                                                <Chips labels={agents} />
                                            </Row>
                                        )}
                                    </dl>
                                </Section>
                            )}

                            {participants.length > 0 && (
                                <Section
                                    title="Participants"
                                    icon={<Users size={12} />}
                                    count={participants.length}
                                >
                                    <Chips labels={participants} />
                                </Section>
                            )}

                            {semantic.length > 0 && (
                                <Section
                                    title="Topics"
                                    icon={<Tags size={12} />}
                                    count={semantic.length}
                                >
                                    <Chips labels={semantic} />
                                </Section>
                            )}

                            {web.length > 0 && (
                                <Section
                                    title="Web sources"
                                    icon={<ExternalLink size={12} />}
                                    count={web.length}
                                >
                                    <ul className="space-y-1">
                                        {web.map((source) => (
                                            <li key={source.label} className="text-xs">
                                                {source.href ? (
                                                    <a
                                                        href={source.href}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="flex items-start gap-2 rounded-lg bg-surface-sunken px-2.5 py-1.5 text-accent hover:bg-surface-2"
                                                    >
                                                        <ExternalLink
                                                            size={12}
                                                            className="mt-0.5 shrink-0"
                                                        />
                                                        <span className="min-w-0 flex-1 break-all">
                                                            {source.label}
                                                        </span>
                                                    </a>
                                                ) : (
                                                    <span className="block rounded-lg bg-surface-sunken px-2.5 py-1.5 text-text-2">
                                                        {source.label}
                                                    </span>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                </Section>
                            )}
                        </>
                    )}
                </div>
            </GlassPanel>

            {exporting && activeConversationId && (
                <ConversationExportDialog
                    conversationIds={[activeConversationId]}
                    skipSelection
                    onClose={() => setExporting(false)}
                />
            )}
        </div>
    );
}
