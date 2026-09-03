// DocumentsSection.tsx
// Personal documents: list, search, tag filter, upload and delete.
//
// Carried over from the single-purpose workspace page this section replaced. The behaviour
// is unchanged; only its surroundings are.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { FileText, FolderSync, Loader2, Trash2, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
    deletePersonalDocument,
    fetchPersonalDocumentTags,
    fetchPersonalDocuments,
    uploadDocument,
} from '../../lib/endpoints';
import { GlassButton } from '../../components/ui/primitives';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import { errorMessage } from '../../components/workspace/useSectionResource';
import type { WorkspaceDocument, WorkspaceTag } from '../../lib/types';

/**
 * Reduce a tag of any shape to its name.
 *
 * Tags arrive in more than one form: /api/documents/tags returns `{name, count, color}`
 * objects, while a document's own `tags` field may be an array of strings or a
 * comma-separated string. Rendering an object directly is what caused React error #31 on
 * this page, so every tag is funnelled through here.
 */
function tagName(tag: unknown): string {
    if (typeof tag === 'string') {
        return tag.trim();
    }
    if (tag && typeof tag === 'object' && 'name' in tag) {
        return String((tag as { name: unknown }).name ?? '').trim();
    }
    return '';
}

function normalizeTags(tags: unknown): string[] {
    if (Array.isArray(tags)) {
        return tags.map(tagName).filter(Boolean);
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
        return <Pill tone="ok">Ready</Pill>;
    }

    return (
        <span className="flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
            <Loader2 size={10} className="animate-spin" />
            {Math.round(percent)}%
        </span>
    );
}

export function DocumentsSection({ syncEnabled }: { syncEnabled: boolean }) {
    const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
    const [tags, setTags] = useState<WorkspaceTag[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [activeTag, setActiveTag] = useState<string | null>(null);
    const [uploading, setUploading] = useState(false);
    const [deletingId, setDeletingId] = useState<string | null>(null);

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
            setError(errorMessage(loadError, 'Failed to load documents.'));
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
            setError(errorMessage(uploadError, `Could not upload ${file.name}.`));
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
        setDeletingId(id);
        setDocuments(documents.filter((item) => (item.id ?? item.document_id) !== id));
        try {
            await deletePersonalDocument(id);
        } catch (deleteError) {
            setDocuments(previous);
            setError(errorMessage(deleteError, 'Could not delete document.'));
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Documents"
                description="Files you upload here are indexed and can be cited in chat. Everything in this section is private to you."
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

            {syncEnabled ? (
                <p className="text-xs text-text-3">
                    Documents can also arrive automatically from a{' '}
                    <Link to="/workspace/sync" className="text-accent hover:underline">
                        file source
                    </Link>
                    .
                </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-[16rem] flex-1">
                    <SectionSearch
                        value={query}
                        onChange={setQuery}
                        placeholder="Search documents"
                    />
                </div>

                {tags.slice(0, 8).map((tag) => {
                    const name = tagName(tag);
                    if (!name) {
                        return null;
                    }
                    return (
                        <button
                            key={name}
                            type="button"
                            onClick={() => setActiveTag(activeTag === name ? null : name)}
                            className={clsx(
                                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                                activeTag === name
                                    ? 'border-transparent bg-accent-soft text-accent'
                                    : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2',
                            )}
                        >
                            {name}
                            {typeof tag === 'object' && tag.count ? (
                                <span className="ml-1 opacity-60">{tag.count}</span>
                            ) : null}
                        </button>
                    );
                })}
            </div>

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<FileText size={28} />}
                emptyTitle={
                    documents.length === 0
                        ? 'No documents yet'
                        : 'No documents match your filters'
                }
                emptyDescription={
                    documents.length === 0
                        ? 'Upload a file to make it available for grounded chat.'
                        : undefined
                }
                getKey={(document, index) =>
                    String(document.id ?? document.document_id ?? index)
                }
                renderItem={(document) => {
                    const id = String(document.id ?? document.document_id ?? '');
                    const documentTags = normalizeTags(document.tags);
                    return (
                        <ResourceRow
                            icon={<FileText size={17} />}
                            title={String(document.file_name ?? document.title ?? 'Untitled')}
                            subtitle={
                                documentTags.length > 0 ? documentTags.join(' · ') : undefined
                            }
                            meta={<ProcessingBadge document={document} />}
                            actions={
                                <ConfirmAction
                                    icon={<Trash2 size={15} />}
                                    label={`Delete ${document.file_name ?? 'document'}`}
                                    confirmLabel="Delete"
                                    busy={deletingId === id}
                                    onConfirm={() => void onDelete(document)}
                                />
                            }
                        />
                    );
                }}
            />

            {syncEnabled ? null : (
                <p className="flex items-center gap-1.5 text-xs text-text-3">
                    <FolderSync size={13} />
                    File sync is not enabled for your account, so documents can only be added
                    by uploading them.
                </p>
            )}
        </div>
    );
}
