// WorkspaceShell.tsx

import { useMemo, type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { clsx } from 'clsx';
import { LayoutGrid, PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import {
    groupWorkspaceSections, navigableSections,
    type ResolvedWorkspaceSection, type WorkspaceSectionDescriptor,
} from '../../lib/workspaceSections';

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
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const groups = useMemo(() => groupWorkspaceSections(navigableSections(sections)), [sections]);
    const linkClass = ({ isActive }: { isActive: boolean }) => clsx(
        'flex items-center gap-2.5 rounded-lg text-left text-sm transition-colors',
        railCollapsed ? 'justify-center px-2 py-2' : 'px-2.5 py-2',
        isActive ? 'bg-accent-soft font-medium text-accent' : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
    );

    return (
        <div className="flex h-full min-h-0 flex-col">
            {header}
            <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
                <nav aria-label="Workspace sections" className={clsx(
                    'flex shrink-0 flex-col gap-3 overflow-y-auto transition-[width]',
                    railCollapsed ? 'w-12' : 'w-12 md:w-52',
                )}>
                    <button type="button"
                        onClick={() => updateUserSettings({ v2WorkspaceRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand workspace sections' : 'Collapse workspace sections'}
                        aria-expanded={!railCollapsed}
                        title={railCollapsed ? 'Expand workspace sections' : 'Collapse workspace sections'}
                        className={clsx(
                            'flex items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-2.5',
                        )}>
                        {railCollapsed ? <PanelLeftOpen size={15} /> : (
                            <><PanelLeftClose size={15} /><span className="hidden md:inline">Collapse</span></>
                        )}
                    </button>
                    <NavLink to={basePath} end className={linkClass} title={railCollapsed ? 'Overview' : undefined}>
                        <LayoutGrid size={15} className="shrink-0" />
                        <span className={railCollapsed ? 'sr-only' : 'sr-only md:not-sr-only md:truncate'}>Overview</span>
                    </NavLink>
                    {groups.map(({ group, sections: entries }) => (
                        <div key={group.id} className="space-y-0.5">
                            {railCollapsed ? <div aria-hidden="true" className="mx-2 my-1.5 border-t border-edge" /> : (
                                <p className="hidden px-2.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase md:block">{group.label}</p>
                            )}
                            {entries.map(({ section }) => {
                                const Icon = section.icon;
                                return (
                                    <NavLink key={section.id} to={`${basePath}/${section.id}`} className={linkClass}
                                        title={railCollapsed ? `${group.label}: ${section.label}` : undefined}>
                                        <Icon size={15} className="shrink-0" />
                                        <span className={railCollapsed ? 'sr-only' : 'sr-only md:not-sr-only md:truncate'}>{section.label}</span>
                                    </NavLink>
                                );
                            })}
                        </div>
                    ))}
                </nav>
                <div className={clsx('min-w-0 flex-1', fullBleed ? 'flex min-h-0 flex-col overflow-hidden' : 'overflow-y-auto')}>
                    {fullBleed ? children : <div className="mx-auto max-w-4xl pb-8">{children}</div>}
                </div>
            </div>
        </div>
    );
}
