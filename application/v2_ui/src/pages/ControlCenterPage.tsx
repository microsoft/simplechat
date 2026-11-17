// ControlCenterPage.tsx
// THESIS: Put governed administration into its own pane, not the user workspace rail.
// OWN-WORLD: Inherit SimpleChat V2's semantic glass surfaces, compact workhorse type, and blue accent.
// STORY: Administrators see only the management areas their Control Center capabilities allow.
// FIRST VIEWPORT: A labeled section rail sits beside a broad page header and one focused work area.
// FORM: Operate; extend the established Admin Settings pane without changing its visual system.

import { useState, type ComponentType } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { Activity, BarChart3, FolderOpen, PanelLeftClose, PanelLeftOpen, Users } from 'lucide-react';
import { clsx } from 'clsx';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassPanel } from '../components/ui/primitives';
import { DashboardSection } from '../components/controlCenter/DashboardSection';
import { ActivityLogsSection } from '../components/controlCenter/ActivityLogsSection';
import { RefreshDataStrip } from '../components/controlCenter/RefreshDataStrip';
import { ControlCenterDataVersion } from '../components/controlCenter/refreshContext';
import type { ControlCenterCapabilities } from '../lib/types';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import { UsersSection } from '../components/controlCenter/UsersSection';
import { GroupsSection } from '../components/controlCenter/GroupsSection';
import { PublicWorkspacesSection } from '../components/controlCenter/PublicWorkspacesSection';

type SectionId = 'dashboard' | 'users' | 'groups' | 'public-workspaces' | 'activity-logs';

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
];

// A record rather than a chain of comparisons, so a section added to the list above cannot be
// left without a view: the build fails instead of a placeholder shipping.
const SECTION_VIEWS: Record<SectionId, ComponentType> = {
    dashboard: DashboardSection,
    users: UsersSection,
    groups: GroupsSection,
    'public-workspaces': PublicWorkspacesSection,
    'activity-logs': ActivityLogsSection,
};

export function ControlCenterPage() {
    const { section: requestedSection } = useParams<{ section?: string }>();
    const capabilities = useBootstrapStore((state) => state.data?.control_center);
    const navigate = useNavigate();
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2ControlCenterRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    // Counts finished refreshes, so the section on screen reloads without losing its filters.
    const [dataVersion, setDataVersion] = useState(0);
    const sections: SectionId[] = ['dashboard', 'users', 'groups', 'public-workspaces', 'activity-logs'];
    const section = (sections.includes(requestedSection as SectionId) ? requestedSection : 'dashboard') as SectionId;
    const current = SECTIONS.find((item) => item.id === section) ?? SECTIONS[0];
    const allowed = Boolean(capabilities?.[current.capability]);
    const SectionView = SECTION_VIEWS[section];
    // The refresh routes answer only for the capability that manages users, which is the admin
    // level `control_center_required('admin')` checks; a dashboard-only reader gets no button.
    const canRefresh = Boolean(capabilities?.can_manage_users);

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader title="Control Center" description="Manage and monitor SimpleChat." />
            {canRefresh ? <RefreshDataStrip onRefreshed={() => setDataVersion((version) => version + 1)} /> : null}
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
                    ) : (
                        <ControlCenterDataVersion.Provider value={dataVersion}>
                            <SectionView />
                        </ControlCenterDataVersion.Provider>
                    )}
                </main>
            </div>
        </div>
    );
}
