// WorkspacePage.tsx
// The personal workspace shell: header, grouped navigation rail, and the active section.
//
// The classic workspace presents these as eight sibling tabs, which reads as eight
// unrelated things and hides the fact that most of them exist to serve one another. Here
// they are grouped by purpose, with an overview in front, and the rail carries only what is
// actually available -- everything else is accounted for on the overview, where there is
// room to say why.

import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { LayoutGrid, Lock } from 'lucide-react';
import { PageHeader } from '../../components/layout/PageHeader';
import { EmptyState } from '../../components/ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { WorkspaceShell } from '../../components/workspace/WorkspaceShell';
import { resolveWorkspaceSections } from '../../lib/workspaceSections';
import { OverviewSection } from './OverviewSection';
import { WORKSPACE_SECTIONS, WORKSPACE_SECTIONS_BY_ID } from './sections';
import type { WorkspaceSectionContext } from './sections';

export function WorkspacePage() {
    const workspace = useBootstrapStore((state) => state.data?.workspace);
    const ownerId = useBootstrapStore((state) => state.data?.user?.id);
    const { section: requestedSection, resourceId } = useParams<{ section?: string; resourceId?: string }>();

    const resolved = useMemo(
        () => resolveWorkspaceSections(WORKSPACE_SECTIONS, workspace),
        [workspace],
    );

    const context: WorkspaceSectionContext = useMemo(
        () => ({
            resourceId,
            ownerId,
            isEnabled: (sectionId: string) =>
                resolved.some((entry) => entry.section.id === sectionId && entry.enabled),
        }),
        [resolved, resourceId, ownerId],
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

    // A full-bleed section manages its own width, height and scrolling. Wrapping one in the
    // page's centred, page-scrolling container would give it a second scrollbar and squeeze
    // a three-pane layout into a reading measure.
    const fullBleed = !showOverview && activeEntry?.enabled && activeEntry.section.layout === 'full';

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
        if (resourceId && !['agents', 'actions'].includes(activeEntry.section.id)) {
            return <EmptyState title="Editor not found" description="That editor does not exist in this workspace section." />;
        }
        return activeEntry.section.render(context);
    };

    return (
        <WorkspaceShell basePath="/workspace" sections={resolved} fullBleed={Boolean(fullBleed)}
            header={<PageHeader
                title="My workspace"
                description="Documents, prompts and automation that belong to you alone"
            />}>
            {renderBody()}
        </WorkspaceShell>
    );
}

export { WORKSPACE_SECTIONS, WORKSPACE_SECTIONS_BY_ID };
