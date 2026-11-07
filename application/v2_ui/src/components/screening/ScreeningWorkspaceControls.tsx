// ScreeningWorkspaceControls.tsx

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    changeScreeningScan,
    fetchScreeningConfiguration,
    fetchScreeningPolicy,
    fetchScreeningScan,
    fetchScreeningScans,
    isStaleScreeningError,
    screeningErrorMessage,
    startAllWorkspaceScreeningScan,
    startScreeningScan,
    type ScreeningConfiguration,
    type ScreeningJob,
    type ScreeningJobAction,
    type ScreeningPolicyResponse,
    type ScreeningScope,
} from '../../lib/contentScreeningApi';
import { AdminModal } from '../admin/AdminModal';
import { GlassButton, Skeleton } from '../ui/primitives';
import { ScreeningScanControls, type ScreeningScanScope } from './ScreeningScanControls';
import { ScreeningField, screeningInputClass } from './ScreeningFields';
import { ScreeningPolicyEditor } from './ScreeningPolicyEditor';

function ScopeControls({ scope, documentIds }: { scope: ScreeningScope; documentIds?: string[] }) {
    const [configuration, setConfiguration] = useState<ScreeningConfiguration | null>(null);
    const [policy, setPolicy] = useState<ScreeningPolicyResponse | null>(null);
    const [jobs, setJobs] = useState<ScreeningJob[]>([]);
    const [continuation, setContinuation] = useState<string | null>(null);
    const [job, setJob] = useState<ScreeningJob | null>(null);
    const [selectedId, setSelectedId] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [stale, setStale] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [refresh, setRefresh] = useState(0);
    const inFlight = useRef(false);
    const selectedIdRef = useRef(selectedId);
    selectedIdRef.current = selectedId;
    const scopeIdentity = useRef('');
    scopeIdentity.current = `${scope.scope_type}:${scope.scope_id}`;
    const active = useRef(true);
    useEffect(() => {
        active.current = true;
        return () => { active.current = false; };
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setConfiguration(null);
        setPolicy(null);
        setJobs([]);
        setJob(null);
        setSelectedId('');
        setContinuation(null);
        setError(null);
        setStale(false);
        void (async () => {
            try {
                // A successful policy read is the server's scope-management authorization.
                const authorized = await fetchScreeningPolicy(scope, controller.signal);
                const [config, page] = await Promise.all([
                    fetchScreeningConfiguration(controller.signal),
                    fetchScreeningScans(scope, null, controller.signal),
                ]);
                if (controller.signal.aborted) return;
                setPolicy(authorized);
                setConfiguration(config);
                setJobs(page.items);
                setContinuation(page.continuation);
                setSelectedId(page.items[0]?.id ?? '');
            } catch (failure) {
                if (!controller.signal.aborted) setError(screeningErrorMessage(failure));
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        })();
        return () => controller.abort();
    }, [scope.scope_type, scope.scope_id, refresh]);

    useEffect(() => {
        const controller = new AbortController();
        setJob(null);
        if (selectedId) {
            void fetchScreeningScan(selectedId, controller.signal).then((next) => {
                if (!controller.signal.aborted && selectedIdRef.current === selectedId) setJob(next);
            }).catch((failure) => {
                if (!controller.signal.aborted) {
                    setError(screeningErrorMessage(failure));
                    if (failure instanceof ApiError && failure.isAuthError) {
                        setPolicy(null);
                        setConfiguration(null);
                        setJobs([]);
                    }
                }
            });
        }
        return () => controller.abort();
    }, [selectedId]);

    const pollingId = !busy && job?.allowed_actions?.includes('cancel') && !job.cancel_requested ? job.id : '';
    useEffect(() => {
        if (!pollingId) return;
        const controller = new AbortController();
        let polling = false;
        const timer = window.setInterval(async () => {
            if (polling) return;
            polling = true;
            try {
                const next = await fetchScreeningScan(pollingId, controller.signal);
                if (!controller.signal.aborted && selectedIdRef.current === pollingId) setJob(next);
            } catch (failure) {
                if (!controller.signal.aborted) {
                    setError(screeningErrorMessage(failure));
                    setJob(null);
                    if (failure instanceof ApiError && failure.isAuthError) {
                        setPolicy(null);
                        setConfiguration(null);
                        setJobs([]);
                    }
                }
            } finally {
                polling = false;
            }
        }, 5000);
        return () => {
            window.clearInterval(timer);
            controller.abort();
        };
    }, [pollingId]);

    const startScopes: ScreeningScanScope[] = [];
    const baselineEnabled = scope.scope_type === 'global' ? policy?.policy.enabled : policy?.inherited_summary?.enabled;
    if (configuration?.enabled && configuration.enhanced_citations_enabled && policy && baselineEnabled) {
        if (scope.scope_type !== 'global') {
            startScopes.push({
                key: 'workspace',
                label: documentIds?.length ? 'This document' : 'This workspace',
            });
        }
        if (configuration.can_scan_all) {
            startScopes.push({ key: 'all', label: 'All workspaces (administrator)', allWorkspaces: true });
        }
    }

    async function run<T>(operation: () => Promise<T>, apply: (result: T) => void) {
        if (inFlight.current || stale) return;
        const requestedScope = scopeIdentity.current;
        inFlight.current = true;
        setBusy(true);
        setError(null);
        try {
            const result = await operation();
            if (active.current && requestedScope === scopeIdentity.current) apply(result);
        } catch (failure) {
            if (active.current && requestedScope === scopeIdentity.current) {
                setError(screeningErrorMessage(failure));
                if (isStaleScreeningError(failure)) {
                    setStale(true);
                    setJob(null);
                }
                if (failure instanceof ApiError && failure.isAuthError) {
                    setPolicy(null);
                    setConfiguration(null);
                    setJob(null);
                    setJobs([]);
                }
            }
        } finally {
            inFlight.current = false;
            if (active.current) setBusy(false);
        }
    }

    const updateJob = (next: ScreeningJob) => {
        setJob(next);
        setSelectedId(next.id);
        setJobs((current) => [next, ...current.filter((item) => item.id !== next.id)]);
    };
    const action = (name: ScreeningJobAction) => {
        if (job?.allowed_actions?.includes(name)) {
            void run(() => changeScreeningScan(job.id, name), updateJob);
        }
    };

    return (
        <div className="space-y-4">
            <p className="text-xs text-text-3">
                Screening requires Enhanced Citations and its configured storage. Existing holds and
                reviews remain active when new scanning is disabled.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Link to="/content-review" className="text-sm text-accent hover:underline">Open Content review</Link>
                <GlassButton type="button" variant="subtle" size="sm" disabled={busy || loading}
                    onClick={() => setRefresh((value) => value + 1)}>Refresh screening controls</GlassButton>
            </div>
            {loading ? <Skeleton className="h-24" /> : null}
            {configuration ? (
                <p className="rounded-lg border border-edge bg-surface-2 p-3 text-xs text-text-2">
                    New scanning: {configuration.enabled ? 'enabled' : 'disabled'}.
                    {' '}Enhanced Citations: {configuration.enhanced_citations_enabled ? 'enabled' : 'required before activation'}.
                    Storage readiness is validated by the server, not inferred from these flags.
                </p>
            ) : null}
            {policy ? (
                <p className="text-xs text-text-3">
                    {scope.scope_type === 'global'
                        ? 'Administrative policies govern required checks across enrolled workspaces.'
                        : 'Workspace additions never replace or disable the administrative baseline.'}
                </p>
            ) : null}
            {scope.scope_type !== 'global' && policy ? (
                <ScreeningPolicyEditor scope={scope} onSaved={setPolicy} />
            ) : null}
            {jobs.length ? (
                <ScreeningField label="Recent screening scans">
                    {(id) => (
                        <select id={id} className={screeningInputClass} value={selectedId} disabled={busy}
                            onChange={(event) => {
                                setJob(null);
                                setSelectedId(event.target.value);
                            }}>
                            {jobs.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.state}</option>)}
                        </select>
                    )}
                </ScreeningField>
            ) : null}
            {continuation ? <GlassButton type="button" size="sm" variant="subtle" disabled={busy}
                onClick={() => void run(() => fetchScreeningScans(scope, continuation), (page) => {
                    setJobs((current) => [...current, ...page.items.filter((item) => !current.some((existing) => existing.id === item.id))]);
                    setContinuation(page.continuation);
                })}>Load more scans</GlassButton> : null}
            <ScreeningScanControls scopes={startScopes} job={job} busy={busy || loading || stale} error={error}
                onStart={(key) => {
                    if (!startScopes.some((item) => item.key === key)) return;
                    void run(
                        () => key === 'all' ? startAllWorkspaceScreeningScan() : startScreeningScan(scope, documentIds),
                        updateJob,
                    );
                }}
                onRefresh={() => {
                    if (job) void run(() => fetchScreeningScan(job.id), updateJob);
                }}
                onCancel={() => action('cancel')}
                onResume={() => action('resume')}
                onRetry={() => action('retry')} />
        </div>
    );
}

export function ScreeningWorkspaceControls({
    scope,
    documentIds,
    label = 'Screening scans',
    disabled = false,
    compact = false,
}: {
    scope: ScreeningScope;
    documentIds?: string[];
    label?: string;
    /** Holds the controls closed while the host cannot confirm the viewer's access. */
    disabled?: boolean;
    /** Below the sm breakpoint, show the icon alone; the label stays the button's name and tooltip. */
    compact?: boolean;
}) {
    const [open, setOpen] = useState(false);
    return (
        <>
            <GlassButton type="button" size="sm" variant="subtle" onClick={() => setOpen(true)}
                disabled={disabled || !scope.scope_id}
                aria-label={compact ? label : undefined} title={compact ? label : undefined}>
                <ShieldCheck size={14} />{compact ? <span className="hidden sm:inline">{label}</span> : label}
            </GlassButton>
            {open ? (
                <AdminModal title="Content screening controls" size="lg"
                    description="Scope management and scan actions are authorized by the server."
                    onClose={() => setOpen(false)}>
                    <ScopeControls scope={scope} documentIds={documentIds} />
                </AdminModal>
            ) : null}
        </>
    );
}
