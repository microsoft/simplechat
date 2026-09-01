// WorkspacePage.tsx
// Personal workspace documents: list, search, tag filter, upload and delete.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { FileText, Loader2, Search, Trash2, Upload } from 'lucide-react';
import {
    deletePersonalDocument,
    fetchPersonalDocumentTags,
    fetchPersonalDocuments,
    uploadDocument,
} from '../lib/endpoints';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import type { WorkspaceDocument } from '../lib/types';

function normalizeTags(tags: WorkspaceDocument['tags']): string[] {
    if (Array.isArray(tags)) {
        return tags.map(String);
    }
    if (typeof tags === 'string' && tags.trim()) {
        return tags.split(',').map((tag) => tag.trim()).filter(Boolean);
    }
    return [];
}

function ProcessingBadge({ document }: { document: WorkspaceDocument }) {
    const percent = Number(document.percentage_complete ?? 100);
    const complete = Number.isFinite(percent) ? percent >= 100 : true;

    if (complete) {
        return (
            <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">
                Ready
            </span>
        );
    }

    return (
        <span className="flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
            <Loader2 size={10} className="animate-spin" />
            {Math.round(percent)}%
        </span>
    );
}

export function WorkspacePage() {
    const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
    const [tags, setTags] = useState<string[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [activeTag, setActiveTag] = useState<string | null>(null);
    const [uploading, setUploading] = useState(false);

    const fileInputRef = useRef<HTMLInputElement>(null);

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            const [documentsResponse, tagsResponse] = await Promise.all([
                fetchPersonalDocuments(),
                fetchPersonalDocumentTags().catch(() => ({ tags: [] })),
            ]);
            // The endpoint has used both `documents` and `items` as its collection key.
            setDocuments(documentsResponse.documents ?? documentsResponse.items ?? []);
            setTags(tagsResponse.tags ?? []);
        } catch (loadError) {
            setError(
                loadError instanceof Error ? loadError.message : 'Failed to load documents.',
            );
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void load();
    }, []);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return documents.filter((document) => {
            const name = String(document.file_name ?? document.title ?? '').toLowerCase();
            if (needle && !name.includes(needle)) {
                return false;
            }
            if (activeTag && !normalizeTags(document.tags).includes(activeTag)) {
                return false;
            }
            return true;
        });
    }, [documents, query, activeTag]);

    const onSelectFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }
        setUploading(true);
        try {
            await uploadDocument(file, null);
            await load();
        } catch (uploadError) {
            setError(
                uploadError instanceof Error
                    ? uploadError.message
                    : `Could not upload ${file.name}.`,
            );
        } finally {
            setUploading(false);
            event.target.value = '';
        }
    };

    const onDelete = async (document: WorkspaceDocument) => {
        const id = String(document.id ?? document.document_id ?? '');
        if (!id) {
            return;
        }
        const previous = documents;
        setDocuments(documents.filter((item) => (item.id ?? item.document_id) !== id));
        try {
            await deletePersonalDocument(id);
        } catch (deleteError) {
            setDocuments(previous);
            setError(
                deleteError instanceof Error ? deleteError.message : 'Could not delete document.',
            );
        }
    };

    return (
        <>
            <PageHeader
                title="My workspace"
                description="Private documents available for grounded chat"
                actions={
                    <>
                        <input
                            ref={fileInputRef}
                            type="file"
                            className="hidden"
                            onChange={onSelectFile}
                        />
                        <GlassButton
                            variant="primary"
                            size="sm"
                            disabled={uploading}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            {uploading ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <Upload size={14} />
                            )}
                            Upload
                        </GlassButton>
                    </>
                }
            />

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <div className="mx-auto max-w-4xl space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                        <div className="relative min-w-[16rem] flex-1">
                            <Search
                                size={15}
                                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                            />
                            <input
                                type="search"
                                value={query}
                                onChange={(event) => setQuery(event.target.value)}
                                placeholder="Search documents"
                                aria-label="Search documents"
                                className="w-full rounded-xl border border-edge bg-surface-1 py-2 pr-3 pl-9 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                            />
                        </div>

                        {tags.slice(0, 8).map((tag) => (
                            <button
                                key={tag}
                                type="button"
                                onClick={() => setActiveTag(activeTag === tag ? null : tag)}
                                className={clsx(
                                    'rounded-full border px-2.5 py-1 text-xs transition-colors',
                                    activeTag === tag
                                        ? 'border-transparent bg-accent-soft text-accent'
                                        : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2',
                                )}
                            >
                                {tag}
                            </button>
                        ))}
                    </div>

                    {error && (
                        <GlassPanel elevation="flat" className="p-3 text-sm text-danger">
                            {error}
                        </GlassPanel>
                    )}

                    {loading && (
                        <div className="space-y-2">
                            {Array.from({ length: 5 }).map((_, index) => (
                                <Skeleton key={index} className="h-14 w-full" />
                            ))}
                        </div>
                    )}

                    {!loading && visible.length === 0 && !error && (
                        <EmptyState
                            icon={<FileText size={28} />}
                            title={
                                documents.length === 0
                                    ? 'No documents yet'
                                    : 'No documents match your filters'
                            }
                            description={
                                documents.length === 0
                                    ? 'Upload a file to make it available for grounded chat.'
                                    : undefined
                            }
                        />
                    )}

                    <ul className="space-y-2">
                        {visible.map((document) => {
                            const id = String(document.id ?? document.document_id ?? '');
                            const documentTags = normalizeTags(document.tags);
                            return (
                                <li key={id}>
                                    <GlassPanel
                                        elevation="flat"
                                        className="flex items-center gap-3 p-3"
                                    >
                                        <FileText size={17} className="shrink-0 text-text-3" />
                                        <div className="min-w-0 flex-1">
                                            <p className="truncate text-sm text-text-1">
                                                {String(
                                                    document.file_name ??
                                                        document.title ??
                                                        'Untitled',
                                                )}
                                            </p>
                                            {documentTags.length > 0 && (
                                                <p className="mt-0.5 truncate text-xs text-text-3">
                                                    {documentTags.join(' · ')}
                                                </p>
                                            )}
                                        </div>
                                        <ProcessingBadge document={document} />
                                        <button
                                            type="button"
                                            onClick={() => void onDelete(document)}
                                            aria-label={`Delete ${document.file_name ?? 'document'}`}
                                            className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger"
                                        >
                                            <Trash2 size={15} />
                                        </button>
                                    </GlassPanel>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            </div>
        </>
    );
}
