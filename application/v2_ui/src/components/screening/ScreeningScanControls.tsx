// ScreeningScanControls.tsx
// The controller supplies only server-authorized scopes and actions.

import { useState } from 'react';
import { Loader2, RefreshCw, ScanLine } from 'lucide-react';
import type { ScreeningJob } from '../../lib/contentScreeningApi';
import { AdminModal } from '../admin/AdminModal';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { ScreeningField, screeningInputClass } from './ScreeningFields';

export interface ScreeningScanScope {
    key: string;
    label: string;
    allWorkspaces?: boolean;
}

export function ScreeningScanControls({
    scopes,
    job,
    busy,
    error,
    onStart,
    onCancel,
    onResume,
    onRetry,
    onRefresh,
}: {
    scopes: ScreeningScanScope[];
    job: ScreeningJob | null;
    busy: boolean;
    error?: string | null;
    onStart: (scopeKey: string) => void;
    onCancel: () => void;
    onResume: () => void;
    onRetry: () => void;
    onRefresh: () => void;
}) {
    const [scopeKey, setScopeKey] = useState('');
    const [confirmAll, setConfirmAll] = useState(false);
    const selected = scopes.find((scope) => scope.key === scopeKey) ?? (scopes.length === 1 ? scopes[0] : undefined);

    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-text-1"><ScanLine size={16} />Screen existing knowledge</h3>
            <p className="text-xs leading-relaxed text-text-3">
                Queued existing documents stay available until their individual scan starts.
                Findings, incomplete coverage, and errors then keep that document held.
                Canceling a job or disabling future scanning never releases an existing hold.
            </p>
            {scopes.length ? (
                <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-0 flex-1">
                        <ScreeningField label="Scan scope">
                            {(id) => (
                                <select id={id} className={screeningInputClass}
                                    value={selected?.key ?? ''} disabled={busy}
                                    onChange={(event) => setScopeKey(event.target.value)}>
                                    <option value="">Choose an authorized workspace</option>
                                    {scopes.map((scope) => <option key={scope.key} value={scope.key}>{scope.label}</option>)}
                                </select>
                            )}
                        </ScreeningField>
                    </div>
                    <GlassButton type="button" size="sm" variant="primary" disabled={busy || !selected}
                        onClick={() => {
                            if (selected?.allWorkspaces) {
                                setConfirmAll(true);
                            } else if (selected) {
                                onStart(selected.key);
                            }
                        }}>
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />}
                        Start scan
                    </GlassButton>
                </div>
            ) : <p className="text-xs text-text-3">No scan action is authorized for this scope, or new scanning is disabled.</p>}
            {error ? <p role="alert" className="rounded-lg bg-danger-soft p-2 text-xs text-danger">{error}</p> : null}
            {job ? (
                <div className="space-y-2 border-t border-edge pt-3" aria-live="polite">
                    <p className="break-words text-sm text-text-2">Job {job.id} · {job.state}</p>
                    {!job.enumeration_complete && !job.cancel_requested ? (
                        <progress className="h-2 w-full accent-[var(--accent)]" aria-label="Discovering documents for screening" />
                    ) : null}
                    <p className="text-xs text-text-3">
                        {job.enumeration_complete ? 'Document enumeration complete.' : 'Document enumeration is not complete.'}
                        {job.cancel_requested ? ' Cancellation requested; existing holds remain enforced.' : ''}
                    </p>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                        {Object.entries(job.counters ?? {}).filter(([, value]) => Number.isFinite(value)).map(([key, value]) => (
                            <div key={key} className="flex items-baseline justify-between gap-2">
                                <dt className="text-text-3">{key.replaceAll('_', ' ')}</dt>
                                <dd className="font-medium tabular-nums text-text-2">{value}</dd>
                            </div>
                        ))}
                    </dl>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="subtle" disabled={busy} onClick={onRefresh}>
                            <RefreshCw size={13} />Refresh scan
                        </GlassButton>
                        {job.allowed_actions?.includes('cancel') ? <GlassButton type="button" size="sm" variant="subtle" disabled={busy || job.cancel_requested} onClick={onCancel}>Cancel scan</GlassButton> : null}
                        {job.allowed_actions?.includes('resume') ? <GlassButton type="button" size="sm" variant="subtle" disabled={busy} onClick={onResume}>Resume scan</GlassButton> : null}
                        {job.allowed_actions?.includes('retry') ? <GlassButton type="button" size="sm" variant="subtle" disabled={busy} onClick={onRetry}>Retry failed items</GlassButton> : null}
                    </div>
                </div>
            ) : null}
            {confirmAll && selected?.allWorkspaces ? (
                <AdminModal title="Scan all workspaces?"
                    description="Administrator-only operation. This permission does not grant access to private review evidence."
                    onClose={() => !busy && setConfirmAll(false)}
                    footer={<>
                        <GlassButton type="button" disabled={busy} onClick={() => setConfirmAll(false)}>Keep current scans</GlassButton>
                        <GlassButton type="button" variant="primary" disabled={busy} onClick={() => {
                            setConfirmAll(false);
                            onStart(selected.key);
                        }}>Confirm all-workspace scan</GlassButton>
                    </>}>
                    <p className="text-sm text-text-2">
                        Existing knowledge across personal, group, and public workspaces will be queued.
                        Each document becomes unavailable when its scan starts and may need a scoped human decision.
                    </p>
                </AdminModal>
            ) : null}
        </GlassPanel>
    );
}
