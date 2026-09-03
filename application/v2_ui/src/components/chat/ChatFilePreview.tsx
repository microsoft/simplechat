// ChatFilePreview.tsx
// What a file uploaded into a conversation actually contains.
//
// The name alone is not enough to work with. A spreadsheet attached mid-conversation is the
// subject of everything said afterwards, and being unable to look at it means checking the
// assistant's answers against a file you cannot see. Opened on demand rather than inline,
// because the extracted content of a document can be the entire document.
//
// The original file is offered as a download only when the server still has it. Enhanced
// citations keep the upload in blob storage; without them only the extracted text survives,
// and offering a download that produces a text approximation of a spreadsheet would be worse
// than offering nothing.

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Download, Loader2, X } from 'lucide-react';
import {
    chatUploadTabularDownloadUrl,
    fetchChatFileContent,
    type ChatFileContent,
} from '../../lib/endpoints';
import { parseCsvPreview } from '../../lib/csvPreview';
import { GlassButton, GlassPanel } from '../ui/primitives';

function CsvTable({ content }: { content: string }) {
    const preview = parseCsvPreview(content);

    if (!preview) {
        return <p className="text-sm text-text-3">No data available.</p>;
    }

    return (
        <div>
            <div className="overflow-auto rounded-lg border border-edge">
                <table className="w-full border-collapse text-xs">
                    <thead>
                        <tr className="border-b border-edge bg-surface-sunken">
                            {preview.columns.map((column, index) => (
                                <th
                                    key={`${column}-${index}`}
                                    scope="col"
                                    className="px-2 py-1.5 text-left font-medium whitespace-nowrap text-text-2"
                                >
                                    {column}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {preview.rows.map((row, rowIndex) => (
                            <tr key={rowIndex} className="border-b border-edge last:border-0">
                                {row.map((cell, cellIndex) => (
                                    <td key={cellIndex} className="px-2 py-1.5 text-text-2">
                                        {cell}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {preview.hiddenRowCount > 0 && (
                <p className="mt-2 text-xs text-text-3">
                    Showing the first {preview.rows.length.toLocaleString()} rows.{' '}
                    {preview.hiddenRowCount.toLocaleString()} more are in the file.
                </p>
            )}
        </div>
    );
}

export function ChatFilePreview({
    conversationId,
    fileId,
    fileName,
    onClose,
}: {
    conversationId: string;
    fileId: string;
    fileName: string;
    onClose: () => void;
}) {
    const [data, setData] = useState<ChatFileContent | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setData(null);
        setError(null);

        fetchChatFileContent(conversationId, fileId)
            .then((result) => {
                if (cancelled) {
                    return;
                }
                if (result.error) {
                    setError(result.error);
                    return;
                }
                setData(result);
            })
            .catch((cause: unknown) => {
                if (!cancelled) {
                    setError(
                        cause instanceof Error ? cause.message : 'Could not load the file.',
                    );
                }
            });

        return () => {
            cancelled = true;
        };
    }, [conversationId, fileId]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    const title = String(data?.filename ?? fileName).trim() || 'Uploaded file';
    const downloadable = data?.file_content_source === 'blob';

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={`Uploaded file: ${title}`}
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[85vh] w-full max-w-4xl flex-col"
            >
                <div className="flex h-14 shrink-0 items-center gap-3 border-b border-edge px-5">
                    <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text-1">
                        Uploaded file: {title}
                    </h2>
                    {downloadable && (
                        <a
                            href={chatUploadTabularDownloadUrl(conversationId, fileId)}
                            download
                            rel="noopener"
                            className="inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium glass-flat text-text-1 transition-colors hover:bg-surface-2"
                        >
                            <Download size={13} />
                            Download original
                        </a>
                    )}
                    <GlassButton size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
                        <X size={16} />
                    </GlassButton>
                </div>

                <div className="min-h-0 flex-1 overflow-auto p-4">
                    {error ? (
                        <p className="text-sm text-danger">{error}</p>
                    ) : !data ? (
                        <p className="flex items-center gap-2 text-sm text-text-3">
                            <Loader2 size={14} className="animate-spin" />
                            Loading the file…
                        </p>
                    ) : data.is_table ? (
                        <CsvTable content={String(data.file_content ?? '')} />
                    ) : (
                        <pre className="text-xs break-words whitespace-pre-wrap text-text-2">
                            {String(data.file_content ?? '')}
                        </pre>
                    )}
                </div>
            </GlassPanel>
        </div>,
        document.body,
    );
}
