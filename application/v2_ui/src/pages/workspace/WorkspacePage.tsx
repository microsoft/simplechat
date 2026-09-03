// WorkspacePage.tsx
// The personal workspace shell: header, grouped navigation rail, and the active section.
//
// The classic workspace presents these as eight sibling tabs, which reads as eight
// unrelated things and hides the fact that most of them exist to serve one another. Here
// they are grouped by purpose, with an overview in front, and the rail carries only what is
// actually available -- everything else is accounted for on the overview, where there is
// room to say why.

import { useMemo } from 'react';
import { NavLink, useParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { LayoutGrid, Lock } from 'lucide-react';
import { PageHeader } from '../../components/layout/PageHeader';
import { EmptyState } from '../../components/ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    groupWorkspaceSections,
    navigableSections,
    resolveWorkspaceSections,
} from '../../lib/workspaceSections';
import { OverviewSection } from './OverviewSection';
import { WORKSPACE_SECTIONS, WORKSPACE_SECTIONS_BY_ID } from './sections';
import type { WorkspaceSectionContext } from './sections';

export function WorkspacePage() {
    const workspace = useBootstrapStore((state) => state.data?.workspace);
    const { section: requestedSection } = useParams<{ section?: string }>();

    const resolved = useMemo(
        () => resolveWorkspaceSections(WORKSPACE_SECTIONS, workspace),
        [workspace],
    );

    const available = useMemo(() => navigableSections(resolved), [resolved]);
    const groups = useMemo(() => groupWorkspaceSections(available), [available]);

    const context: WorkspaceSectionContext = useMemo(
        () => ({
            isEnabled: (sectionId: string) =>
                resolved.some((entry) => entry.section.id === sectionId && entry.enabled),
        }),
        [resolved],
    );

    // The whole page is gated on enable_user_workspace upstream, but the flag is reported
    // here too so a disabled workspace explains itself rather than rendering an empty rail.
    if (workspace && !workspace.enabled) {
        return (
            <div className="flex h-full min-h-0 flex-col">
                <PageHeader title="My workspace" description="Your private documents and tools" />
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                    <EmptyState
                        icon={<Lock size={28} />}
                        title="Your workspace is not enabled"
                        description="Your administrator has not enabled personal workspaces for this deployment."
                    />
                </div>
            </div>
        );
    }

    const activeEntry = requestedSection
        ? resolved.find((entry) => entry.section.id === requestedSection)
        : null;
    const showOverview = !requestedSection;

    const renderBody = () => {
        if (showOverview) {
            return <OverviewSection resolved={resolved} />;
        }
        if (!activeEntry) {
            return (
                <EmptyState
                    icon={<LayoutGrid size={28} />}
                    title="Section not found"
                    description="That part of the workspace does not exist."
                />
            );
        }
        if (!activeEntry.enabled) {
            // Reached by a bookmark or a shared link to a section that has since been turned
            // off. The reason is the same one the overview shows.
            return (
                <EmptyState
                    icon={<Lock size={28} />}
                    title={`${activeEntry.section.label} is not available`}
                    description={activeEntry.reason ?? undefined}
                />
            );
        }
        return activeEntry.section.render(context);
    };

    const linkClass = ({ isActive }: { isActive: boolean }) =>
        clsx(
            'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
            isActive
                ? 'bg-accent-soft font-medium text-accent'
                : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
        );

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                title="My workspace"
                description="Documents, prompts and automation that belong to you alone"
            />

            <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
                <nav
                    aria-label="Workspace sections"
                    className="flex w-52 shrink-0 flex-col gap-3 overflow-y-auto"
                >
                    <NavLink to="/workspace" end className={linkClass}>
                        <LayoutGrid size={15} className="shrink-0" />
                        <span className="truncate">Overview</span>
                    </NavLink>

                    {groups.map(({ group, sections }) => (
                        <div key={group.id} className="space-y-0.5">
                            <p className="px-2.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                                {group.label}
                            </p>
                            {sections.map(({ section }) => {
                                const Icon = section.icon;
                                return (
                                    <NavLink
                                        key={section.id}
                                        to={`/workspace/${section.id}`}
                                        className={linkClass}
                                    >
                                        <Icon size={15} className="shrink-0" />
                                        <span className="truncate">{section.label}</span>
                                    </NavLink>
                                );
                            })}
                        </div>
                    ))}
                </nav>

                <div className="min-w-0 flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-4xl pb-8">{renderBody()}</div>
                </div>
            </div>
        </div>
    );
}

export { WORKSPACE_SECTIONS, WORKSPACE_SECTIONS_BY_ID };
