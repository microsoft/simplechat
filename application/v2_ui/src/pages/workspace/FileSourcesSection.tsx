// FileSourcesSection.tsx
// External file sources that feed the documents section.
//
// Called "Sync" in the classic interface, which describes the mechanism rather than the
// purpose. What a user is doing here is pointing the workspace at somewhere their files
// already live, so the section is named for that and says where the files end up.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, FolderSync, Play, Trash2 } from 'lucide-react';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import {
    errorMessage,
    useSectionResource,
} from '../../components/workspace/useSectionResource';
import {
    deleteSyncSource,
    fetchSyncRuns,
    fetchSyncSources,
    startSyncRun,
} from '../../lib/workspaceApi';
import { statusTone } from './WorkflowsSection';
import type { WorkspaceSyncRun, WorkspaceSyncSource } from '../../lib/types';

const SOURCE_TYPE_LABELS: Record<string, string> = {
    smb: 'Network share',
    azure_files: 'Azure Files',
    azure_blob: 'Azure Blob Storage',
    onedrive: 'OneDrive',
    google_drive: 'Google Drive',
    google_shared_drive: 'Google shared drive',
};

export function sourceTypeLabel(sourceType: unknown): string {
    const raw = String(sourceType ?? '').trim();
    return SOURCE_TYPE_LABELS[raw] ?? (raw ? raw.replace(/[_-]+/g, ' ') : 'Unknown');
}

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function SourceRuns({ sourceId }: { sourceId: string }) {
    const { items, loading, error } = useSectionResource<WorkspaceSyncRun>(
        (signal) => fetchSyncRuns(sourceId, signal),
        'Failed to load sync history.',
    );

    if (loading) {
        return <p className="px-3 pb-3 text-xs text-text-3">Loading history…</p>;
    }
    if (error) {
        return <p className="px-3 pb-3 text-xs text-danger">{error}</p>;
    }
    if (items.length === 0) {
        return <p className="px-3 pb-3 text-xs text-text-3">This source has not run yet.</p>;
    }

    return (
        <ul className="space-y-1 px-3 pb-3">
            {items.slice(0, 10).map((run) => (
                <li key={run.id} className="flex items-center gap-2 text-xs text-text-3">
                    <Pill tone={statusTone(run.status)}>{String(run.status ?? 'unknown')}</Pill>
                    <span className="truncate">
                        {formatTimestamp(run.started_at) || 'Not started'}
                        {run.completed_at ? ` → ${formatTimestamp(run.completed_at)}` : ''}
                    </span>
                </li>
            ))}
        </ul>
    );
}

export function FileSourcesSection() {
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspaceSyncSource>(
            fetchSyncSources,
            'Failed to load file sources.',
        );

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((source) =>
            `${source.name ?? ''} ${source.remote_path ?? ''}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const onRun = async (source: WorkspaceSyncSource) => {
        setBusyId(source.id);
        setError(null);
        try {
            await startSyncRun(source.id);
            await refresh();
        } catch (runError) {
            setError(errorMessage(runError, 'Could not start the sync.'));
        } finally {
            setBusyId(null);
        }
    };

    const onDelete = async (source: WorkspaceSyncSource) => {
        const previous = items;
        setBusyId(source.id);
        setItems(items.filter((item) => item.id !== source.id));
        try {
            // The documents this source produced are deliberately kept. Removing a
            // connection and discarding everything it ever brought in are different
            // intentions, and only the first one was expressed here.
            await deleteSyncSource(source.id, false);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the file source.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="File sources"
                description="Places your files already live. Approved files are brought in and processed the same way an upload is, then appear in your documents."
            />

            <p className="text-xs text-text-3">
                Files land in{' '}
                <Link to="/workspace/documents" className="text-accent hover:underline">
                    Documents
                </Link>
                . Adding and configuring a source is still done in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .
            </p>

            <SectionSearch value={query} onChange={setQuery} placeholder="Search file sources" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<FolderSync size={28} />}
                emptyTitle={
                    items.length === 0 ? 'No file sources yet' : 'No sources match your search'
                }
                emptyDescription={
                    items.length === 0
                        ? 'Connect a source to bring documents in without uploading them one by one.'
                        : undefined
                }
                getKey={(source, index) => String(source.id ?? index)}
                renderItem={(source) => {
                    const expanded = expandedId === source.id;
                    return (
                        <div>
                            <ResourceRow
                                icon={<FolderSync size={17} />}
                                title={String(source.name ?? 'Untitled source')}
                                subtitle={String(source.remote_path ?? '')}
                                meta={
                                    <>
                                        <Pill>{sourceTypeLabel(source.source_type)}</Pill>
                                        <Pill tone={source.enabled ? 'ok' : 'neutral'}>
                                            {source.enabled ? 'Enabled' : 'Paused'}
                                        </Pill>
                                    </>
                                }
                                actions={
                                    <>
                                        <RowAction
                                            icon={
                                                expanded ? (
                                                    <ChevronDown size={15} />
                                                ) : (
                                                    <ChevronRight size={15} />
                                                )
                                            }
                                            label={
                                                expanded
                                                    ? 'Hide sync history'
                                                    : 'Show sync history'
                                            }
                                            onClick={() =>
                                                setExpandedId(expanded ? null : source.id)
                                            }
                                        />
                                        <RowAction
                                            icon={<Play size={15} />}
                                            label={`Sync ${source.name ?? 'source'} now`}
                                            busy={busyId === source.id}
                                            onClick={() => void onRun(source)}
                                        />
                                        <ConfirmAction
                                            icon={<Trash2 size={15} />}
                                            label={`Delete ${source.name ?? 'source'}`}
                                            confirmLabel="Delete"
                                            busy={busyId === source.id}
                                            onConfirm={() => void onDelete(source)}
                                        />
                                    </>
                                }
                            />
                            {expanded ? <SourceRuns sourceId={source.id} /> : null}
                        </div>
                    );
                }}
            />
        </div>
    );
}
