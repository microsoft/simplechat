// OverviewSection.tsx
// Personal counts stay here; the shared overview never fetches personal data.

import { useEffect, useState } from 'react';
import { WorkspaceOverview } from '../../components/workspace/WorkspaceOverview';
import { fetchPersonalDocumentFacets, fetchPersonalDocumentTags } from '../../lib/endpoints';
import {
    fetchActions, fetchAgents, fetchIdentities, fetchModelEndpoints,
    fetchPrompts, fetchSyncSources, fetchWorkflows,
} from '../../lib/workspaceApi';
import type { ResolvedWorkspaceSection } from '../../lib/workspaceSections';
import type { WorkspaceSectionDefinition } from './sections';

type CountMap = Record<string, number | undefined>;

const COUNT_LOADERS: Record<string, (signal: AbortSignal) => Promise<number>> = {
    documents: async (signal) => Number((await fetchPersonalDocumentFacets(signal)).total ?? 0),
    tags: async (signal) => (await fetchPersonalDocumentTags(signal)).tags?.length ?? 0,
    prompts: async (signal) => (await fetchPrompts({}, signal)).length,
    sync: async (signal) => (await fetchSyncSources(signal)).length,
    agents: async (signal) => (await fetchAgents(signal)).length,
    actions: async (signal) => (await fetchActions(signal)).length,
    workflows: async (signal) => (await fetchWorkflows(signal)).length,
    identities: async (signal) => (await fetchIdentities(signal)).length,
    endpoints: async (signal) => (await fetchModelEndpoints(signal)).length,
};

function useSectionCounts(sectionIds: string[]): CountMap {
    const [counts, setCounts] = useState<CountMap>({});
    const key = sectionIds.join(',');
    useEffect(() => {
        const controller = new AbortController();
        const ids = key ? key.split(',') : [];
        void Promise.all(ids.map(async (id) => {
            const loader = COUNT_LOADERS[id];
            if (!loader) return [id, undefined] as const;
            try {
                return [id, await loader(controller.signal)] as const;
            } catch {
                // Preserve the personal overview's advisory counters: unavailable is not zero.
                return [id, undefined] as const;
            }
        })).then((entries) => {
            if (!controller.signal.aborted) setCounts(Object.fromEntries(entries));
        });
        return () => controller.abort();
    }, [key]);
    return counts;
}

export function OverviewSection({ resolved }: {
    resolved: ResolvedWorkspaceSection<WorkspaceSectionDefinition>[];
}) {
    const counts = useSectionCounts(resolved.filter((entry) => entry.enabled).map((entry) => entry.section.id));
    return <WorkspaceOverview resolved={resolved} counts={counts} basePath="/workspace"
        description="Everything here is yours alone. The sections build on each other, so most people start with documents and add the rest only when they need them." />;
}
