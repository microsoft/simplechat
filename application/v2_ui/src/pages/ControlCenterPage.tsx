// ControlCenterPage.tsx
// THESIS: Put governed administration into its own pane, not the user workspace rail.
// OWN-WORLD: Inherit SimpleChat V2's semantic glass surfaces, compact workhorse type, and blue accent.
// STORY: Administrators see which areas are available; Data health is explicitly on-demand.
// FIRST VIEWPORT: A labeled section rail sits beside a broad page header and one focused work area.
// FORM: Operate; extend the established Admin Settings pane without changing its visual system.

import { useState } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { Activity, BarChart3, Database, FolderOpen, PanelLeftClose, PanelLeftOpen, Users } from 'lucide-react';
import { clsx } from 'clsx';
import { api } from '../lib/apiClient';
import { PageHeader } from '../components/layout/PageHeader';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { GlassButton, GlassPanel } from '../components/ui/primitives';
import { DashboardSection } from '../components/controlCenter/DashboardSection';
import { ActivityLogsSection } from '../components/controlCenter/ActivityLogsSection';
import type { ControlCenterCapabilities } from '../lib/types';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import { UsersSection } from '../components/controlCenter/UsersSection';
import { GroupsSection } from '../components/controlCenter/GroupsSection';
import { PublicWorkspacesSection } from '../components/controlCenter/PublicWorkspacesSection';

type SectionId = 'dashboard' | 'users' | 'groups' | 'public-workspaces' | 'activity-logs' | 'data-health';

interface MigrationStatus {
    conversations_without_logs: number;
    personal_documents_without_logs: number;
    group_documents_without_logs: number;
    public_documents_without_logs: number;
    total_documents_without_logs: number;
    migration_needed: boolean;
    estimated_total_records: number;
}

interface MigrationResult {
    conversations_migrated: number;
    conversations_skipped_existing: number;
    personal_documents_migrated: number;
    personal_documents_skipped_existing: number;
    group_documents_migrated: number;
    group_documents_skipped_existing: number;
    public_documents_migrated: number;
    public_documents_skipped_existing: number;
    total_migrated: number;
    total_skipped_existing: number;
    total_failed: number;
}

const SECTIONS: {
    id: SectionId;
    label: string;
    Icon: typeof BarChart3;
    capability: keyof ControlCenterCapabilities;
}[] = [
    { id: 'dashboard', label: 'Dashboard', Icon: BarChart3, capability: 'can_view_dashboard' },
    { id: 'users', label: 'Users', Icon: Users, capability: 'can_manage_users' },
    { id: 'groups', label: 'Groups', Icon: Users, capability: 'can_manage_groups' },
    { id: 'public-workspaces', label: 'Public Workspaces', Icon: FolderOpen, capability: 'can_manage_workspaces' },
    { id: 'activity-logs', label: 'Activity Logs', Icon: Activity, capability: 'can_view_activity_logs' },
    { id: 'data-health', label: 'Data health', Icon: Database, capability: 'can_run_maintenance' },
];

function MigrationDataHealth() {
    const [checking, setChecking] = useState(false);
    const [running, setRunning] = useState(false);
    const [status, setStatus] = useState<MigrationStatus | null>(null);
    const [result, setResult] = useState<MigrationResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [confirmOpen, setConfirmOpen] = useState(false);

    const check = async () => {
        setChecking(true);
        setError(null);
        setResult(null);
        try {
            setStatus(await api.get<MigrationStatus>('/api/admin/control-center/migrate/status'));
        } catch (requestError) {
            setError(requestError instanceof Error ? requestError.message : 'Unable to check activity-log status.');
        } finally {
            setChecking(false);
        }
    };

    const runBackfill = async () => {
        setConfirmOpen(false);
        setRunning(true);
        setError(null);
        setResult(null);
        try {
            setResult(await api.post<MigrationResult>('/api/admin/control-center/migrate/all'));
        } catch (requestError) {
            setError(requestError instanceof Error ? requestError.message : 'Unable to run the activity-log backfill.');
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="max-w-4xl space-y-5 p-5 md:p-8">
            <div>
                <h2 className="text-xl font-semibold text-text-1">Activity-log data health</h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-text-2">
                    The legacy backfill adds conversation and document creation records to activity logs when those
                    records are missing. Normal application workflows already write activity logs, so this maintenance
                    operation is usually unnecessary. Check the counts before deciding to run it.
                </p>
            </div>
            <div className="flex flex-wrap gap-2">
                <GlassButton variant="primary" disabled={checking || running} onClick={() => void check()}>
                    {checking ? 'Checking…' : 'Check activity-log status'}
                </GlassButton>
                <GlassButton variant="subtle" disabled={checking || running} onClick={() => setConfirmOpen(true)}>
                    {running ? 'Running backfill…' : 'Run backfill'}
                </GlassButton>
            </div>
            {error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
            {status ? (
                <GlassPanel className="space-y-3 p-4" aria-live="polite">
                    <h3 className="font-medium text-text-1">Check results</h3>
                    <dl className="grid gap-3 sm:grid-cols-2">
                        {[
                            ['Conversations without the legacy flag', status.conversations_without_logs],
                            ['Personal documents without the legacy flag', status.personal_documents_without_logs],
                            ['Group documents without the legacy flag', status.group_documents_without_logs],
                            ['Public documents without the legacy flag', status.public_documents_without_logs],
                            ['Estimated records', status.estimated_total_records],
                        ].map(([label, value]) => (
                            <div key={label} className="rounded-xl bg-surface-2 px-3 py-2">
                                <dt className="text-xs text-text-3">{label}</dt>
                                <dd className="mt-1 font-semibold text-text-1">{Number(value).toLocaleString()}</dd>
                            </div>
                        ))}
                    </dl>
                    <p className="text-sm text-text-2">
                        {status.migration_needed
                            ? 'These counts identify records missing the legacy flag, not necessarily missing activity logs.'
                            : 'No records are missing the legacy flag.'}
                    </p>
                </GlassPanel>
            ) : null}
            {result ? (
                <GlassPanel className="space-y-2 p-4" role="status" aria-live="polite">
                    <h3 className="font-medium text-text-1">Backfill complete</h3>
                    <p className="text-sm text-text-2">
                        {result.total_migrated.toLocaleString()} records added;
                        {' '}{result.total_skipped_existing.toLocaleString()} existing activity records skipped;
                        {' '}{result.total_failed.toLocaleString()} failures.
                    </p>
                </GlassPanel>
            ) : null}
            {confirmOpen ? (
                <ConfirmDialog title="Run activity-log backfill?"
                    description="This scans conversations and all three document workspaces. Existing creation activity records are skipped."
                    confirmLabel="Run backfill" tone="primary" onClose={() => setConfirmOpen(false)}
                    onConfirm={() => void runBackfill()}>
                    <p className="text-sm text-text-2">The operation can take time on large datasets. It is safe to run again; records already present will be skipped.</p>
                </ConfirmDialog>
            ) : null}
        </div>
    );
}

function SectionPlaceholder({ label }: { label: string }) {
    return (
        <GlassPanel className="m-5 max-w-3xl p-6 md:m-8">
            <h2 className="text-lg font-semibold text-text-1">{label}</h2>
            <p className="mt-2 text-sm leading-relaxed text-text-2">
                This V2 management section is being built. Until it is available here, use the classic Control Center.
            </p>
            <a href="/admin/control-center" className="mt-4 inline-flex rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover">
                Open classic Control Center
            </a>
        </GlassPanel>
    );
}

export function ControlCenterPage() {
    const { section: requestedSection } = useParams<{ section?: string }>();
    const capabilities = useBootstrapStore((state) => state.data?.control_center);
    const navigate = useNavigate();
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2ControlCenterRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const sections: SectionId[] = ['dashboard', 'users', 'groups', 'public-workspaces', 'activity-logs', 'data-health'];
    const section = (sections.includes(requestedSection as SectionId) ? requestedSection : 'dashboard') as SectionId;
    const current = SECTIONS.find((item) => item.id === section) ?? SECTIONS[0];
    const allowed = Boolean(capabilities?.[current.capability]);

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader title="Control Center" description="Manage and monitor SimpleChat." />
            <div className="flex min-h-0 flex-1">
                <aside aria-label="Control Center sections"
                    className={clsx('hidden shrink-0 overflow-y-auto border-r border-edge transition-[width] motion-reduce:transition-none lg:block',
                        railCollapsed ? 'w-16 px-2 py-3' : 'w-56 p-3')}>
                    <button type="button" onClick={() => updateUserSettings({ v2ControlCenterRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand Control Center sections' : 'Collapse Control Center sections'}
                        aria-expanded={!railCollapsed} aria-controls="control-center-section-list"
                        title={railCollapsed ? 'Expand Control Center sections' : 'Collapse Control Center sections'}
                        className={clsx('mb-2 flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-3')}>
                        {railCollapsed ? <PanelLeftOpen size={15} aria-hidden="true" /> : <><PanelLeftClose size={15} aria-hidden="true" /><span>Collapse</span></>}
                    </button>
                    <nav id="control-center-section-list" className="space-y-0.5">
                        {SECTIONS.filter((item) => capabilities?.[item.capability]).map(({ id, label, Icon }) => (
                            <NavLink key={id} to={`/control-center/${id}`} aria-current={section === id ? 'page' : undefined}
                                title={railCollapsed ? label : undefined}
                                className={({ isActive }) => clsx('flex items-center gap-2.5 rounded-lg py-2.5 text-sm transition-colors',
                                    railCollapsed ? 'justify-center px-2' : 'px-3',
                                    isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-text-2 hover:bg-surface-2 hover:text-text-1')}>
                                <Icon size={16} aria-hidden="true" />
                                <span className={railCollapsed ? 'sr-only' : undefined}>{label}</span>
                            </NavLink>
                        ))}
                    </nav>
                </aside>
                <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
                    <div className="p-4 lg:hidden">
                        <label className="sr-only" htmlFor="control-center-section">Control Center section</label>
                        <select id="control-center-section" className="w-full rounded-xl border border-edge bg-surface-1 p-2 text-sm text-text-1"
                            value={section} onChange={(event) => navigate(`/control-center/${event.target.value}`)}>
                            {SECTIONS.filter((item) => capabilities?.[item.capability]).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                        </select>
                    </div>
                    {!allowed ? (
                        <GlassPanel role="alert" className="m-5 max-w-2xl p-5 md:m-8">
                            <h2 className="font-semibold text-text-1">Access unavailable</h2>
                            <p className="mt-2 text-sm text-text-2">Your Control Center permissions do not include this section.</p>
                        </GlassPanel>
                    ) : section === 'dashboard' ? <DashboardSection />
                        : section === 'users' ? <UsersSection />
                        : section === 'groups' ? <GroupsSection />
                        : section === 'activity-logs' ? <ActivityLogsSection />
                        : section === 'public-workspaces' ? <PublicWorkspacesSection />
                        : section === 'data-health' ? <MigrationDataHealth />
                            : <SectionPlaceholder label={current.label} />}
                </main>
            </div>
        </div>
    );
}
