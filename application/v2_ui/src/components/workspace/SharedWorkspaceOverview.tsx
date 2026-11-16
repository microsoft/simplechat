// SharedWorkspaceOverview.tsx

import { useEffect, useMemo, useState } from 'react';
import { WorkspaceOverview, type WorkspaceOverviewSection } from './WorkspaceOverview';
import {
    createSharedWorkspaceCountLoaders, loadWorkspaceCounts,
    type SharedWorkspaceContext, type WorkspaceCountResult,
} from '../../lib/sharedWorkspaceCounts';
import type { ResolvedWorkspaceSection } from '../../lib/workspaceSections';
import type { WorkspaceSectionGroup } from '../../lib/types';

export function SharedWorkspaceOverview({
    context, resolved, basePath, description, groupBlurbs, suspended = false,
}: {
    context: SharedWorkspaceContext;
    resolved: ResolvedWorkspaceSection<WorkspaceOverviewSection>[];
    basePath: string;
    description: string;
    groupBlurbs?: Partial<Record<WorkspaceSectionGroup, string>>;
    suspended?: boolean;
}) {
    const loaders = useMemo(() => createSharedWorkspaceCountLoaders(context), [context]);
    const sectionKey = resolved.filter((entry) => entry.enabled).map((entry) => entry.section.id).join(',');
    const identity = useMemo(() => ({ loaders, sectionKey, suspended }), [loaders, sectionKey, suspended]);
    const [state, setState] = useState<{
        identity: typeof identity;
        results: Record<string, WorkspaceCountResult>;
    }>({ identity, results: {} });
    useEffect(() => {
        const controller = new AbortController();
        setState({ identity, results: {} });
        if (!suspended) {
            void loadWorkspaceCounts(loaders, sectionKey.split(','), controller.signal, (id, result) => {
                setState((current) => ({
                    identity,
                    results: { ...(current.identity === identity ? current.results : {}), [id]: result },
                }));
            });
        }
        return () => controller.abort();
    }, [identity, loaders, sectionKey, suspended]);
    const results = state.identity === identity ? state.results : {};
    const counts: Record<string, number> = {};
    const failedCounts = new Set<string>();
    Object.entries(results).forEach(([id, result]) => {
        if (result.failed) failedCounts.add(id);
        else counts[id] = result.count;
    });
    return <WorkspaceOverview resolved={resolved} counts={counts} failedCounts={failedCounts}
        basePath={basePath} description={description} groupBlurbs={groupBlurbs} showRelationships={false} />;
}
