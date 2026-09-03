// GeneratedArtifactCard.tsx
// The files an assistant turn produced, shown under the reply that produced them.
//
// The server writes these to storage and advertises them on the message; without a card the
// file exists but nothing in the interface leads to it. Rendered per capability rather than
// per file type, so a tabular export, an Analyze summary, a comparison workbook and a Deep
// Research ledger all arrive through the same path.
//
// Two layouts. A finished row-level export is compact — its file name and row count already
// say what it is, so the preview moves behind a "View" control. Everything else shows where
// the file went, what it came from and an inline preview, because for those the preview is
// the only way to judge whether the file is the one that was asked for.

import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { Download, Eye, FileLock2, Loader2, X } from 'lucide-react';
import { generatedArtifactDownloadUrl } from '../../lib/endpoints';
import { resolveGeneratedFileApproval } from '../../lib/collaboration';
import { toast } from '../../stores/toastStore';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { AssistantMarkdown } from './AssistantMarkdown';
import { TabularRunStatus } from './TabularRunStatus';
import {
    approvalBlocksDownload,
    artifactFileName,
    artifactOutputFormat,
    artifactPreviewItemList,
    artifactPreviewLines,
    artifactPreviewRowList,
    artifactPreviewRows,
    artifactPreviewText,
    artifactStorageNote,
    artifactTitle,
    describeArtifactApproval,
    formatArtifactRowCount,
    formatPreviewValue,
    hasArtifactPreview,
    isCompletedTabularArtifact,
    isMarkdownArtifact,
    previewTableModel,
    readArtifactApproval,
    readGeneratedArtifacts,
    shouldCollapsePreview,
    shouldRenderPreviewItemsAsRows,
    type GeneratedArtifact,
    type GeneratedRunStatus,
} from '../../lib/generatedArtifacts';

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
}

/** A preview table, or null when the rows are not uniform enough to make one. */
function PreviewTable({
    rows,
    columns,
    maxColumns,
    maxCellLength,
}: {
    rows: unknown;
    columns?: unknown;
    maxColumns?: number;
    maxCellLength?: number;
}) {
    const model = useMemo(
        () => previewTableModel(rows, { columns, maxColumns }),
        [rows, columns, maxColumns],
    );

    if (!model) {
        return null;
    }

    return (
        <div>
            <div className="overflow-auto rounded-lg border border-edge">
                <table className="w-full border-collapse text-xs">
                    <thead>
                        <tr className="border-b border-edge bg-surface-sunken">
                            {model.columns.map((column) => (
                                <th
                                    key={column}
                                    scope="col"
                                    className="px-2 py-1.5 text-left font-medium text-text-2 whitespace-nowrap"
                                >
                                    {column}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {model.rows.map((row, rowIndex) => (
                            <tr key={rowIndex} className="border-b border-edge last:border-0">
                                {model.columns.map((column) => (
                                    <td key={column} className="px-2 py-1.5 text-text-2">
                                        {formatPreviewValue(row[column], maxCellLength)}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {model.hiddenColumnCount > 0 && (
                <p className="mt-2 text-xs text-text-3">
                    Preview limited to {model.columns.length} of{' '}
                    {model.columns.length + model.hiddenColumnCount} fields.
                </p>
            )}
        </div>
    );
}

function PreviewJson({ value }: { value: unknown }) {
    let serialized: string;
    try {
        serialized = JSON.stringify(value ?? [], null, 2);
    } catch {
        serialized = String(value ?? '[]');
    }

    return (
        <pre className="max-h-64 overflow-auto rounded-lg border border-edge bg-surface-sunken p-2 text-xs break-words whitespace-pre-wrap text-text-2">
            {serialized}
        </pre>
    );
}

/** Preview prose. Markdown artifacts render as markdown; everything else stays literal. */
function PreviewText({ value, markdown }: { value: string; markdown: boolean }) {
    if (!value) {
        return null;
    }
    if (markdown) {
        return (
            <div className="max-h-64 overflow-auto rounded-lg border border-edge bg-surface-sunken p-2">
                <AssistantMarkdown content={value} />
            </div>
        );
    }
    return (
        <pre className="max-h-64 overflow-auto rounded-lg border border-edge bg-surface-sunken p-2 text-xs break-words whitespace-pre-wrap text-text-2">
            {value}
        </pre>
    );
}

/** The preview ladder: rows, then items, then lines, then free text. */
function ArtifactPreview({ artifact }: { artifact: GeneratedArtifact }) {
    const rows = artifactPreviewRowList(artifact);
    const items = artifactPreviewItemList(artifact);
    const lines = artifactPreviewLines(artifact);
    const body = artifactPreviewText(artifact);
    const markdown = isMarkdownArtifact(artifact);
    const columns = artifact.preview_columns;

    // Rows are meant to be a table, but a set of non-uniform rows has no honest column
    // layout, so those fall back to JSON rather than being forced into one.
    if (rows.length) {
        return previewTableModel(rows, { columns }) ? (
            <PreviewTable rows={rows} columns={columns} />
        ) : (
            <PreviewJson value={rows} />
        );
    }

    if (items.length) {
        const asTable =
            shouldRenderPreviewItemsAsRows(artifact) && previewTableModel(items, { columns });
        return asTable ? (
            <PreviewTable rows={items} columns={columns} />
        ) : (
            <PreviewJson value={items} />
        );
    }

    if (lines.length) {
        return <PreviewText value={lines.join('\n')} markdown={markdown} />;
    }

    return <PreviewText value={body} markdown={markdown} />;
}

/**
 * The full-size preview for a compact card.
 *
 * Wider limits than the inline preview — fifty columns rather than four — because this is
 * opened specifically to inspect the contents before downloading.
 */
function ArtifactPreviewDialog({
    artifact,
    onClose,
}: {
    artifact: GeneratedArtifact;
    onClose: () => void;
}) {
    const rows = artifactPreviewRows(artifact);
    const lines = artifactPreviewLines(artifact);
    const body = artifactPreviewText(artifact);
    const fileName = artifactFileName(artifact);
    const totalRows = formatArtifactRowCount(artifact.row_count);

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={`Preview ${fileName}`}
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={onClose} />
            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[85vh] w-full max-w-4xl flex-col"
            >
                <div className="flex h-14 shrink-0 items-center gap-3 border-b border-edge px-5">
                    <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text-1">
                        Preview: {fileName}
                    </h2>
                    <GlassButton size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
                        <X size={16} />
                    </GlassButton>
                </div>

                <div className="min-h-0 flex-1 overflow-auto p-4">
                    {rows.length ? (
                        <PreviewTable
                            rows={rows}
                            columns={artifact.preview_columns}
                            maxColumns={50}
                            maxCellLength={240}
                        />
                    ) : (
                        <PreviewText
                            value={lines.length ? lines.join('\n') : body}
                            markdown={isMarkdownArtifact(artifact)}
                        />
                    )}
                </div>

                <div className="shrink-0 border-t border-edge px-5 py-3 text-xs text-text-3">
                    {rows.length
                        ? `Showing ${rows.length.toLocaleString()}${
                              totalRows ? ` of ${totalRows}` : ''
                          } rows. Preview values may be shortened; download for complete content.`
                        : 'Generated artifact preview'}
                </div>
            </GlassPanel>
        </div>,
        // Portalled for the same reason as the export wizard: the message list is a
        // transformed, scrolling container, so `fixed` would resolve against it.
        document.body,
    );
}

export function GeneratedArtifactCard({
    artifact: initialArtifact,
    conversationId,
}: {
    artifact: GeneratedArtifact;
    conversationId?: string;
}) {
    const [artifact, setArtifact] = useState(initialArtifact);
    const [finished, setFinished] = useState<GeneratedArtifact[] | null>(null);
    const [previewOpen, setPreviewOpen] = useState(false);
    const [deciding, setDeciding] = useState<'approve' | 'deny' | null>(null);

    // A completed run replaces its own progress card with the files it produced.
    if (finished) {
        return (
            <>
                {finished.map((member, index) => (
                    <GeneratedArtifactCard
                        key={
                            member.artifact_message_id ||
                            member.document_id ||
                            `${artifactFileName(member)}-${index}`
                        }
                        artifact={member}
                        conversationId={conversationId}
                    />
                ))}
            </>
        );
    }

    const outputFormat = artifactOutputFormat(artifact);
    const fileName = artifactFileName(artifact);
    const rowCount = formatArtifactRowCount(artifact.row_count);
    const sourceFileName = text(artifact.source_file_name);
    const selectedSheet = text(artifact.selected_sheet);
    const summary = text(artifact.summary);
    const running = Boolean(artifact.background_export);
    const compact = isCompletedTabularArtifact(artifact);
    const downloadUrl = generatedArtifactDownloadUrl(artifact, conversationId);

    const sourceNote = [
        sourceFileName ? `Source: ${sourceFileName}` : '',
        selectedSheet ? `Sheet: ${selectedSheet}` : '',
    ]
        .filter(Boolean)
        .join(' | ');

    // A staged file is withheld from everyone, including whoever asked for it, so the
    // download and preview controls are replaced by the banner rather than left to 403.
    const approval = readArtifactApproval(artifact);
    const withheld = approvalBlocksDownload(artifact);

    const decide = async (decision: 'approve' | 'deny') => {
        const sourceConversationId =
            String(artifact.source_conversation_id ?? '').trim() ||
            String(artifact.conversation_id ?? '').trim() ||
            String(conversationId ?? '').trim();
        const artifactMessageId = String(artifact.artifact_message_id ?? '').trim();

        if (!sourceConversationId || !artifactMessageId) {
            toast.error('This file approval is missing its conversation reference.');
            return;
        }

        setDeciding(decision);
        try {
            const result = await resolveGeneratedFileApproval(
                sourceConversationId,
                artifactMessageId,
                decision,
            );
            setArtifact(
                (current) =>
                    ({
                        ...current,
                        approval: {
                            ...(current.approval as Record<string, unknown> | undefined),
                            state:
                                result.approval_state ||
                                (decision === 'approve' ? 'approved' : 'denied'),
                            viewer_can_approve: false,
                            resolved_by_name: result.resolved_by_name ?? '',
                        },
                    }) as GeneratedArtifact,
            );
            toast.success(
                decision === 'approve'
                    ? 'File released to the conversation.'
                    : 'File withheld.',
            );
        } catch (cause) {
            toast.error(
                cause instanceof Error ? cause.message : 'Could not resolve the file approval.',
            );
        } finally {
            setDeciding(null);
        }
    };

    const download = () => {
        if (!downloadUrl) {
            toast.error('Generated export is missing download metadata.');
            return;
        }
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
    };

    // While a run is in flight the supporting notes move inside its collapsed details, so the
    // progress bar is the first thing read rather than the fourth.
    const supporting = (
        <>
            <p>File: {fileName}</p>
            {rowCount && <p>Rows: {rowCount}</p>}
            <p>{artifactStorageNote(artifact)}</p>
            {sourceNote && <p>{sourceNote}</p>}
            {summary && <p>{summary}</p>}
            {hasArtifactPreview(artifact) && (
                <div className="mt-2">
                    <p className="mb-1 font-medium text-text-2">Preview</p>
                    <ArtifactPreview artifact={artifact} />
                </div>
            )}
        </>
    );

    return (
        <section className="glass-flat mt-3 rounded-xl p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <h4 className="text-sm font-semibold text-text-1">{artifactTitle(artifact)}</h4>
                    {!running && (
                        <p className="mt-0.5 text-xs break-all text-text-3">{fileName}</p>
                    )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    {rowCount && !running && (
                        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] tabular-nums text-text-2">
                            {rowCount} rows
                        </span>
                    )}
                    {Boolean(artifact.rows_truncated) && (
                        <span
                            className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn"
                            title="The source action reported truncated results, so this file covers only the rows it returned."
                        >
                            Partial
                        </span>
                    )}
                </div>
            </div>

            {!compact && !running && (
                <>
                    <p className="mt-2 text-xs text-text-3">{artifactStorageNote(artifact)}</p>
                    {sourceNote && <p className="text-xs text-text-3">{sourceNote}</p>}
                    {summary && <p className="mt-2 text-xs text-text-2">{summary}</p>}
                </>
            )}

            {running && (
                <TabularRunStatus
                    artifact={artifact}
                    onRunUpdate={(run: GeneratedRunStatus) =>
                        setArtifact((current) => ({ ...current, ...run }) as GeneratedArtifact)
                    }
                    onComplete={setFinished}
                >
                    {supporting}
                </TabularRunStatus>
            )}

            {!compact && !running && hasArtifactPreview(artifact) && !withheld && (
                <div className="mt-3">
                    {shouldCollapsePreview(artifact) ? (
                        <details>
                            <summary className="cursor-pointer text-xs font-medium text-text-2">
                                Show preview
                            </summary>
                            <div className="mt-2">
                                <ArtifactPreview artifact={artifact} />
                            </div>
                        </details>
                    ) : (
                        <>
                            <p className="mb-2 text-xs font-medium text-text-2">Preview</p>
                            <ArtifactPreview artifact={artifact} />
                        </>
                    )}
                </div>
            )}

            {approval && (
                <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-surface-sunken px-3 py-2">
                    <FileLock2
                        size={14}
                        className={clsx('shrink-0', withheld ? 'text-warn' : 'text-ok')}
                    />
                    <p className="min-w-0 flex-1 text-xs text-text-2">
                        {describeArtifactApproval(approval)}
                    </p>
                    {approval.viewerCanApprove && (
                        <div className="flex shrink-0 gap-2">
                            <GlassButton
                                size="sm"
                                variant="primary"
                                disabled={deciding !== null}
                                onClick={() => void decide('approve')}
                            >
                                {deciding === 'approve' ? (
                                    <Loader2 size={13} className="animate-spin" />
                                ) : null}
                                Approve
                            </GlassButton>
                            <GlassButton
                                size="sm"
                                variant="danger"
                                disabled={deciding !== null}
                                onClick={() => void decide('deny')}
                            >
                                {deciding === 'deny' ? (
                                    <Loader2 size={13} className="animate-spin" />
                                ) : null}
                                Deny
                            </GlassButton>
                        </div>
                    )}
                </div>
            )}

            {!running && !withheld && downloadUrl && (
                <div className="mt-3 flex flex-wrap gap-2">
                    <GlassButton size="sm" variant="subtle" onClick={download}>
                        <Download size={13} />
                        Download {outputFormat.toUpperCase()}
                    </GlassButton>

                    {compact && hasArtifactPreview(artifact) && (
                        <GlassButton
                            size="sm"
                            variant="subtle"
                            onClick={() => setPreviewOpen(true)}
                        >
                            <Eye size={13} />
                            View {outputFormat.toUpperCase()}
                        </GlassButton>
                    )}

                    {!compact && isMarkdownArtifact(artifact) && hasArtifactPreview(artifact) && (
                        <GlassButton
                            size="sm"
                            variant="subtle"
                            onClick={() => setPreviewOpen(true)}
                        >
                            <Eye size={13} />
                            View MD
                        </GlassButton>
                    )}
                </div>
            )}

            {previewOpen && (
                <ArtifactPreviewDialog
                    artifact={artifact}
                    onClose={() => setPreviewOpen(false)}
                />
            )}
        </section>
    );
}

/**
 * Every generated file advertised on one assistant message.
 *
 * `MessageList` maps the artifacts itself, because it also needs to know whether they
 * suppress the reply text. This wrapper exists for any other surface that just wants the
 * cards.
 */
export function GeneratedArtifacts({
    metadata,
    conversationId,
}: {
    metadata: unknown;
    conversationId?: string;
}) {
    const artifacts = useMemo(() => readGeneratedArtifacts(metadata), [metadata]);

    if (!artifacts.length) {
        return null;
    }

    return (
        <>
            {artifacts.map((artifact, index) => (
                <GeneratedArtifactCard
                    key={
                        artifact.artifact_message_id ||
                        artifact.document_id ||
                        artifact.export_run_id ||
                        `${artifactFileName(artifact)}-${index}`
                    }
                    artifact={artifact}
                    conversationId={conversationId}
                />
            ))}
        </>
    );
}
