// OverviewSection.tsx
// The workspace landing page.
//
// This section exists because of a specific complaint: the workspace is eight capabilities
// an administrator can enable independently, and a user faced with whichever subset they
// happen to have cannot tell what the pieces are for or how they relate. So the overview
// does three things a list of tabs cannot. It groups the sections by purpose, it states how
// they feed one another, and it names the sections that are switched off along with the
// reason -- because a section that silently disappears is indistinguishable from one that
// is broken or that the user simply cannot find.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Lock } from 'lucide-react';
import { GlassPanel } from '../../components/ui/primitives';
import { SectionIntro } from '../../components/workspace/primitives';
import {
    fetchPersonalDocumentFacets,
    fetchPersonalDocumentTags,
} from '../../lib/endpoints';
import {
    fetchActions,
    fetchAgents,
    fetchIdentities,
    fetchModelEndpoints,
    fetchPrompts,
    fetchSyncSources,
    fetchWorkflows,
} from '../../lib/workspaceApi';
import { groupWorkspaceSections } from '../../lib/workspaceSections';
import type { ResolvedWorkspaceSection } from '../../lib/workspaceSections';
import type { WorkspaceSectionDefinition } from './sections';

type CountMap = Record<string, number | undefined>;

/** How to count the contents of each section, for the summary on its card. */
const COUNT_LOADERS: Record<string, (signal: AbortSignal) => Promise<number>> = {
    documents: async (signal) => {
        // Counted from the facets endpoint rather than by fetching a large page and
        // measuring it: the count is the only thing wanted here, and the old approach
        // pulled up to a thousand full document records to get it.
        const facets = await fetchPersonalDocumentFacets(signal);
        return Number(facets.total ?? 0);
    },
    tags: async (signal) => (await fetchPersonalDocumentTags(signal)).tags?.length ?? 0,
    prompts: async (signal) => (await fetchPrompts({}, signal)).length,
    sync: async (signal) => (await fetchSyncSources(signal)).length,
    agents: async (signal) => (await fetchAgents(signal)).length,
    actions: async (signal) => (await fetchActions(signal)).length,
    workflows: async (signal) => (await fetchWorkflows(signal)).length,
    identities: async (signal) => (await fetchIdentities(signal)).length,
    endpoints: async (signal) => (await fetchModelEndpoints(signal)).length,
};

/**
 * Count what is in each available section.
 *
 * Counts are decoration: a section whose count fails to load still renders, without one.
 * Failing the whole overview because one collection was unreachable would be a poor trade,
 * and several of these routes can legitimately refuse depending on governance.
 */
function useSectionCounts(sectionIds: string[]): CountMap {
    const [counts, setCounts] = useState<CountMap>({});
    const key = sectionIds.join(',');

    useEffect(() => {
        const controller = new AbortController();
        const ids = key ? key.split(',') : [];

        void Promise.all(
            ids.map(async (id) => {
                const loader = COUNT_LOADERS[id];
                if (!loader) {
                    return [id, undefined] as const;
                }
                try {
                    return [id, await loader(controller.signal)] as const;
                } catch {
                    return [id, undefined] as const;
                }
            }),
        ).then((entries) => {
            if (!controller.signal.aborted) {
                setCounts(Object.fromEntries(entries));
            }
        });

        return () => controller.abort();
    }, [key]);

    return counts;
}

function SectionCard({
    entry,
    count,
}: {
    entry: ResolvedWorkspaceSection<WorkspaceSectionDefinition>;
    count?: number;
}) {
    const { section, enabled, reason } = entry;
    const Icon = section.icon;

    if (!enabled) {
        return (
            <GlassPanel
                elevation="flat"
                className="flex gap-3 p-3 opacity-60"
                aria-label={`${section.label} (unavailable)`}
            >
                <Icon size={17} className="mt-0.5 shrink-0 text-text-3" />
                <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-sm font-medium text-text-2">
                        {section.label}
                        <Lock size={11} className="text-text-3" />
                    </p>
                    <p className="mt-0.5 text-xs text-text-3">{section.blurb}</p>
                    <p className="mt-1 text-xs text-text-3 italic">{reason}</p>
                </div>
            </GlassPanel>
        );
    }

    return (
        <Link to={`/workspace/${section.id}`} className="block">
            <GlassPanel
                elevation="flat"
                className="flex h-full gap-3 p-3 transition-colors hover:bg-surface-2"
            >
                <Icon size={17} className="mt-0.5 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-sm font-medium text-text-1">
                        {section.label}
                        {typeof count === 'number' ? (
                            <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[11px] leading-none text-text-3">
                                {count}
                            </span>
                        ) : null}
                    </p>
                    <p className="mt-0.5 text-xs text-text-3">{section.blurb}</p>
                </div>
            </GlassPanel>
        </Link>
    );
}

function Relationship({ parts }: { parts: string[] }) {
    return (
        <li className="flex flex-wrap items-center gap-1.5 text-xs text-text-3">
            {parts.map((part, index) => (
                <span key={part} className="flex items-center gap-1.5">
                    {index > 0 ? <ArrowRight size={11} className="text-text-3" /> : null}
                    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-text-2">
                        {part}
                    </span>
                </span>
            ))}
        </li>
    );
}

export function OverviewSection({
    resolved,
}: {
    resolved: ResolvedWorkspaceSection<WorkspaceSectionDefinition>[];
}) {
    const enabledIds = resolved
        .filter((entry) => entry.enabled)
        .map((entry) => entry.section.id);
    const counts = useSectionCounts(enabledIds);
    const groups = groupWorkspaceSections(resolved);

    return (
        <div className="space-y-6">
            <SectionIntro
                title="Overview"
                description="Everything here is yours alone. The sections build on each other, so most people start with documents and add the rest only when they need them."
            />

            {groups.map(({ group, sections }) => (
                <section key={group.id} className="space-y-2">
                    <div>
                        <h3 className="text-sm font-semibold text-text-1">{group.label}</h3>
                        <p className="text-xs text-text-3">{group.blurb}</p>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                        {sections.map((entry) => (
                            <SectionCard
                                key={entry.section.id}
                                entry={entry}
                                count={counts[entry.section.id]}
                            />
                        ))}
                    </div>
                </section>
            ))}

            <GlassPanel elevation="flat" className="space-y-2 p-4">
                <h3 className="text-sm font-semibold text-text-1">How these fit together</h3>
                <ul className="space-y-1.5">
                    <Relationship parts={['Identities', 'File sources', 'Documents']} />
                    <Relationship parts={['Documents', 'Agents']} />
                    <Relationship parts={['Actions', 'Agents']} />
                    <Relationship parts={['Endpoints', 'Agents']} />
                    <Relationship parts={['Agents', 'Workflows']} />
                </ul>
                <p className="text-xs text-text-3">
                    Read left to right: the thing on the left is used by the thing on its
                    right. Identities and endpoints exist to be reused, so they rarely need
                    attention once set up.
                </p>
            </GlassPanel>
        </div>
    );
}
