// WorkspaceShell.tsx

import { useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { MobileNavigationContext } from '../layout/MobileNavigation';
import { clsx } from 'clsx';
import { LayoutGrid, PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import {
    groupWorkspaceSections, navigableSections,
    type ResolvedWorkspaceSection, type WorkspaceSectionDescriptor,
} from '../../lib/workspaceSections';
import { normalizeWorkspaceUrl } from '../../lib/workspaceContext';

export interface WorkspaceNavigationSection extends WorkspaceSectionDescriptor {
    label: string;
    icon: LucideIcon;
}

export function WorkspaceShell({
    header, basePath, sections, children, fullBleed = false,
}: {
    header: ReactNode;
    basePath: string;
    sections: ResolvedWorkspaceSection<WorkspaceNavigationSection>[];
    children: ReactNode;
    fullBleed?: boolean;
}) {
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2WorkspaceRailCollapsed === true);
    const { mobile } = useContext(MobileNavigationContext);
    const [sectionsOpen, setSectionsOpen] = useState(false);
    const location = useLocation();
    const sectionOpener = useRef<HTMLButtonElement>(null);
    useEffect(() => setSectionsOpen(false), [location.pathname, mobile]);
    const closeSections = () => {
        setSectionsOpen(false);
        sectionOpener.current?.focus();
    };
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const groups = useMemo(() => groupWorkspaceSections(navigableSections(sections)), [sections]);
    const activeSection = sections.find(({ section }) =>
        location.pathname === `${basePath}/${section.id}` || location.pathname.startsWith(`${basePath}/${section.id}/`));
    const collapsed = !mobile && railCollapsed;
    const linkClass = ({ isActive }: { isActive: boolean }) => clsx(
        'flex items-center gap-2.5 rounded-lg text-left text-sm transition-colors',
        collapsed ? 'justify-center px-2 py-2' : 'px-2.5 py-2',
        isActive ? 'bg-accent-soft font-medium text-accent' : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
    );

    return (
        <div className="flex h-full min-h-0 flex-col">
            {header}
            {mobile && <button ref={sectionOpener} type="button" aria-label="Workspace sections"
                aria-expanded={sectionsOpen} aria-controls="workspace-section-navigation"
                onClick={() => setSectionsOpen((open) => !open)}
                className="mx-2 my-1 flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-edge bg-surface-1 px-3 text-sm text-text-2">
                <LayoutGrid size={17} />
                <span>Workspace · {activeSection?.section.label || 'Overview'}</span>
                {sectionsOpen ? <PanelLeftClose size={16} className="ml-auto" /> : <PanelLeftOpen size={16} className="ml-auto" />}
            </button>}
            <div className="relative flex min-h-0 flex-1 gap-4 overflow-hidden p-2 md:p-4">
                {mobile && sectionsOpen && <button type="button" tabIndex={-1} aria-label="Close workspace sections"
                    className="absolute inset-0 z-10 bg-black/20" onClick={closeSections} />}
                <nav aria-label="Workspace sections" data-tour="workspace-sections" className={clsx(
                    'flex shrink-0 flex-col gap-3 overflow-y-auto transition-[width]',
                    mobile ? (sectionsOpen ? 'glass-modal absolute inset-x-2 top-0 z-20 max-h-full rounded-xl p-3' : 'hidden') : collapsed ? 'w-12' : 'w-52',
                )} id="workspace-section-navigation"
                    onKeyDown={(event) => { if (event.key === 'Escape') closeSections(); }}
                    onClickCapture={(event) => {
                        if (mobile && event.target instanceof Element && event.target.closest('a')) closeSections();
                    }}>
                    {!mobile && <button type="button"
                        onClick={() => updateUserSettings({ v2WorkspaceRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand workspace sections' : 'Collapse workspace sections'}
                        aria-expanded={!railCollapsed}
                        data-tour="workspace-rail-toggle"
                        title={railCollapsed ? 'Expand workspace sections' : 'Collapse workspace sections'}
                        className={clsx(
                            'flex items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-2.5',
                        )}>
                        {railCollapsed ? <PanelLeftOpen size={15} /> : (
                            <><PanelLeftClose size={15} /><span className="hidden md:inline">Collapse</span></>
                        )}
                    </button>}
                    <NavLink to={normalizeWorkspaceUrl(basePath, window.location.origin)} end className={linkClass} title={railCollapsed ? 'Overview' : undefined}
                        data-tour="workspace-overview">
                        <LayoutGrid size={15} className="shrink-0" />
                        <span className={collapsed ? 'sr-only' : 'truncate'}>Overview</span>
                    </NavLink>
                    {groups.map(({ group, sections: entries }) => (
                        <div key={group.id} className="space-y-0.5">
                            {collapsed ? <div aria-hidden="true" className="mx-2 my-1.5 border-t border-edge" /> : (
                                <p className="px-2.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">{group.label}</p>
                            )}
                            {entries.map(({ section }) => {
                                const Icon = section.icon;
                                return (
                                    <NavLink key={section.id} to={normalizeWorkspaceUrl(
                                        `${basePath}/${encodeURIComponent(section.id)}`,
                                        window.location.origin,
                                    )} className={linkClass}
                                        title={railCollapsed ? `${group.label}: ${section.label}` : undefined}>
                                        <Icon size={15} className="shrink-0" />
                                        <span className={collapsed ? 'sr-only' : 'truncate'}>{section.label}</span>
                                    </NavLink>
                                );
                            })}
                        </div>
                    ))}
                </nav>
                <div data-tour="workspace-content" className={clsx('min-w-0 flex-1', fullBleed ? 'flex min-h-0 flex-col overflow-hidden' : 'overflow-y-auto')}>
                    {fullBleed ? children : <div className="mx-auto max-w-4xl pb-8">{children}</div>}
                </div>
            </div>
        </div>
    );
}
