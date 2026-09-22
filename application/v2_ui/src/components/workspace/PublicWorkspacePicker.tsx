// PublicWorkspacePicker.tsx
//
// Mirrors GroupWorkspacePicker for the read-only public workspace surface, differing only in
// wording and the workspace kind it lists. Selecting one navigates to /public/<id>; the page
// fires setActive separately, so this control never blocks on a write.

import { useEffect, useState } from 'react';
import { PUBLIC_WORKSPACES, type WorkspacePage } from '../../lib/workspaces';
import { GlassButton } from '../ui/primitives';

const PAGE_SIZE = 25;
const INPUT_CLASS = 'w-full min-w-0 rounded-xl border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

export function PublicWorkspacePicker({
    value, selectedName, disabled, onSelect,
}: {
    value?: string;
    selectedName?: string;
    disabled: boolean;
    onSelect: (id: string) => void;
}) {
    const [search, setSearch] = useState('');
    const [term, setTerm] = useState('');
    const [page, setPage] = useState(1);
    const [result, setResult] = useState<WorkspacePage | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);

    useEffect(() => {
        const timeout = window.setTimeout(() => { setTerm(search.trim()); setPage(1); }, 300);
        return () => window.clearTimeout(timeout);
    }, [search]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        void PUBLIC_WORKSPACES.list(page, PAGE_SIZE, term, controller.signal).then((next) => {
            if (!controller.signal.aborted) setResult(next);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) {
                setResult(null);
                setError(cause instanceof Error ? cause.message : 'Could not load public workspaces. Please retry.');
            }
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [page, term, retry]);

    const items = result?.items ?? [];
    return (
        <div className="min-w-0 space-y-2">
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <label className="min-w-0 space-y-1 text-xs text-text-2">
                    <span>Public workspace</span>
                    <select aria-label="Public workspace" className={INPUT_CLASS} value={value ?? ''}
                        disabled={disabled || loading || Boolean(error)}
                        onChange={(event) => { if (event.target.value) onSelect(event.target.value); }}>
                        <option value="">{loading ? 'Loading public workspaces...' : 'Select a public workspace'}</option>
                        {value && !items.some((item) => item.id === value) ? (
                            <option value={value}>{selectedName || value}</option>
                        ) : null}
                        {items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                </label>
                <label className="min-w-0 space-y-1 text-xs text-text-2">
                    <span>Search public workspaces</span>
                    <input type="search" className={INPUT_CLASS} value={search} disabled={disabled}
                        placeholder="Search all public workspaces" onChange={(event) => setSearch(event.target.value)} />
                </label>
            </div>
            {error ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-danger">
                    <span>{error}</span><GlassButton size="sm" disabled={disabled} onClick={() => setRetry((count) => count + 1)}>Retry public workspace list</GlassButton>
                </div>
            ) : null}
            {!loading && !error && items.length === 0 ? (
                <p role="status" className="text-xs text-text-3">{term ? 'No public workspaces match your search.' : 'You cannot access any public workspace yet.'}</p>
            ) : null}
            {result && (page > 1 || result.totalCount > PAGE_SIZE) ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                    <span>Page {page} of {Math.max(1, Math.ceil(result.totalCount / PAGE_SIZE))} · {result.totalCount} public workspaces</span>
                    <div className="flex gap-2">
                        <GlassButton size="sm" disabled={disabled || loading || page <= 1} onClick={() => setPage((current) => current - 1)}>Previous public workspaces</GlassButton>
                        <GlassButton size="sm" disabled={disabled || loading || page * PAGE_SIZE >= result.totalCount} onClick={() => setPage((current) => current + 1)}>Next public workspaces</GlassButton>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
