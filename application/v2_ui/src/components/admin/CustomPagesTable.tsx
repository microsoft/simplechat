// CustomPagesTable.tsx
// Lists static custom page metadata and hosts the designer and developer guide.
//
// This talks to `/api/admin/custom-pages` directly rather than going through the settings
// PATCH, because page metadata lives in its own Cosmos container, not in the settings
// document. Changes here therefore save immediately and are not part of the page's draft.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import {
    AlertCircle,
    BookOpen,
    Loader2,
    Pencil,
    Plus,
    Trash2,
    UserPlus,
} from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import {
    emptyCustomPage,
    isReadOnly,
    toCustomPage,
    type CustomPage,
} from '../../lib/customPages';
import { AdminMarkdown } from './AdminMarkdown';
import { AdminModal } from './AdminModal';
import { CustomPageDesigner } from './CustomPageDesigner';
import { GlassButton } from '../ui/primitives';

interface ListResponse {
    pages: unknown[];
}

function Pill({ tone, children }: { tone: 'ok' | 'muted'; children: React.ReactNode }) {
    return (
        <span
            className={clsx(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase',
                tone === 'ok' ? 'bg-ok-soft text-ok' : 'bg-surface-2 text-text-3',
            )}
        >
            {children}
        </span>
    );
}

function DeveloperGuideModal({ onClose }: { onClose: () => void }) {
    const [markdown, setMarkdown] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const response = await api.get<{ markdown: string }>(
                    '/api/admin/custom-pages/developer-guide',
                );
                if (!cancelled) {
                    setMarkdown(response.markdown);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'The developer guide could not be loaded.',
                    );
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <AdminModal title="Custom Pages developer guide" size="lg" onClose={onClose}>
            {error ? (
                <p role="alert" className="text-sm text-danger">
                    {error}
                </p>
            ) : markdown === null ? (
                <p className="flex items-center gap-2 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading…
                </p>
            ) : (
                <AdminMarkdown content={markdown} />
            )}
        </AdminModal>
    );
}

export function CustomPagesTable({ help }: { help?: string }) {
    const [pages, setPages] = useState<CustomPage[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [editing, setEditing] = useState<{ page: CustomPage; isNew: boolean } | null>(null);
    const [designerError, setDesignerError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [showGuide, setShowGuide] = useState(false);

    const load = useCallback(async () => {
        try {
            const response = await api.get<ListResponse>('/api/admin/custom-pages');
            setPages((response.pages ?? []).map(toCustomPage));
            setError(null);
        } catch (fetchError) {
            setError(
                fetchError instanceof Error
                    ? fetchError.message
                    : 'Custom pages could not be loaded.',
            );
            setPages([]);
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    const save = async (page: CustomPage) => {
        setBusy(true);
        setDesignerError(null);
        try {
            if (editing?.isNew) {
                await api.post('/api/admin/custom-pages', page);
            } else {
                await api.put(`/api/admin/custom-pages/${encodeURIComponent(page.slug)}`, page);
            }
            setEditing(null);
            await load();
        } catch (saveError) {
            setDesignerError(
                saveError instanceof ApiError || saveError instanceof Error
                    ? saveError.message
                    : 'The page could not be saved.',
            );
        } finally {
            setBusy(false);
        }
    };

    const remove = async (page: CustomPage) => {
        if (!window.confirm(`Delete the custom page "${page.slug}"?`)) {
            return;
        }
        setBusy(true);
        try {
            await api.delete(`/api/admin/custom-pages/${encodeURIComponent(page.slug)}`);
            await load();
        } catch (deleteError) {
            setError(
                deleteError instanceof Error
                    ? deleteError.message
                    : 'The page could not be deleted.',
            );
        } finally {
            setBusy(false);
        }
    };

    const addRequestAccessPage = async () => {
        setBusy(true);
        try {
            await api.post('/api/admin/custom-pages/request-access-example');
            await load();
        } catch (createError) {
            setError(
                createError instanceof Error
                    ? createError.message
                    : 'The Request Access page could not be created.',
            );
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="py-3">
            <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <span className="block text-sm font-medium text-text-1">
                        Static page metadata
                    </span>
                    {help ? <p className="mt-0.5 text-xs text-text-3">{help}</p> : null}
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5">
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        onClick={() => setShowGuide(true)}
                    >
                        <BookOpen size={14} />
                        Guide
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        disabled={busy}
                        onClick={() => void addRequestAccessPage()}
                    >
                        <UserPlus size={14} />
                        Request Access page
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        onClick={() => {
                            setDesignerError(null);
                            setEditing({ page: emptyCustomPage(), isNew: true });
                        }}
                    >
                        <Plus size={14} />
                        New page
                    </GlassButton>
                </div>
            </div>

            {error ? (
                <p role="alert" className="mb-2 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}

            {pages === null ? (
                <p className="flex items-center gap-2 py-4 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading custom pages…
                </p>
            ) : pages.length === 0 ? (
                <p className="rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    No custom pages defined yet.
                </p>
            ) : (
                <div className="overflow-x-auto rounded-lg border border-edge">
                    <table className="w-full text-left text-sm">
                        <thead className="bg-surface-2 text-xs text-text-3">
                            <tr>
                                <th className="px-3 py-2 font-medium">Slug</th>
                                <th className="px-3 py-2 font-medium">Title</th>
                                <th className="px-3 py-2 font-medium">Access</th>
                                <th className="px-3 py-2 font-medium">Status</th>
                                <th className="px-3 py-2 font-medium">Nav</th>
                                <th className="px-3 py-2 font-medium sr-only">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-edge">
                            {pages.map((page) => {
                                const readOnly = isReadOnly(page);
                                return (
                                    <tr key={page.slug} className="text-text-2">
                                        <td className="px-3 py-2 font-mono text-xs text-text-1">
                                            {page.slug}
                                            {readOnly ? (
                                                <span className="ml-1.5">
                                                    <Pill tone="muted">Python</Pill>
                                                </span>
                                            ) : null}
                                        </td>
                                        <td className="px-3 py-2">{page.title}</td>
                                        <td className="px-3 py-2 text-xs">{page.access_level}</td>
                                        <td className="px-3 py-2">
                                            <Pill tone={page.enabled ? 'ok' : 'muted'}>
                                                {page.enabled ? 'Enabled' : 'Disabled'}
                                            </Pill>
                                        </td>
                                        <td className="px-3 py-2 text-xs">
                                            {page.show_in_nav ? page.nav_label || page.title : '—'}
                                        </td>
                                        <td className="px-3 py-2">
                                            <div className="flex justify-end gap-1">
                                                <button
                                                    type="button"
                                                    title={
                                                        readOnly
                                                            ? 'Python-backed pages are managed in code'
                                                            : 'Edit'
                                                    }
                                                    aria-label={`Edit ${page.slug}`}
                                                    disabled={readOnly || busy}
                                                    onClick={() => {
                                                        setDesignerError(null);
                                                        setEditing({ page, isNew: false });
                                                    }}
                                                    className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                                                >
                                                    <Pencil size={14} />
                                                </button>
                                                <button
                                                    type="button"
                                                    title={
                                                        readOnly
                                                            ? 'Python-backed pages are managed in code'
                                                            : 'Delete'
                                                    }
                                                    aria-label={`Delete ${page.slug}`}
                                                    disabled={readOnly || busy}
                                                    onClick={() => void remove(page)}
                                                    className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}

            {editing ? (
                <CustomPageDesigner
                    key={editing.page.slug || '__new'}
                    page={editing.page}
                    isNew={editing.isNew}
                    existingSlugs={(pages ?? []).map((page) => page.slug)}
                    saving={busy}
                    serverError={designerError}
                    onCancel={() => setEditing(null)}
                    onSave={(page) => void save(page)}
                />
            ) : null}

            {showGuide ? <DeveloperGuideModal onClose={() => setShowGuide(false)} /> : null}
        </div>
    );
}
