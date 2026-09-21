// WorkspaceOverview.tsx

import { Link } from 'react-router-dom';
import { ArrowRight, Lock } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import { SectionIntro } from './primitives';
import type { WorkspaceNavigationSection } from './WorkspaceShell';
import { groupWorkspaceSections, type ResolvedWorkspaceSection } from '../../lib/workspaceSections';

export interface WorkspaceOverviewSection extends WorkspaceNavigationSection {
    blurb: string;
    availabilityLabel?: string;
}

export function WorkspaceOverview({
    resolved, basePath, description, counts = {}, showRelationships = true,
}: {
    resolved: ResolvedWorkspaceSection<WorkspaceOverviewSection>[];
    basePath: string;
    description: string;
    counts?: Record<string, number | undefined>;
    showRelationships?: boolean;
}) {
    return (
        <div className="space-y-6">
            <SectionIntro title="Overview" description={description} />
            {groupWorkspaceSections(resolved).map(({ group, sections }) => (
                <section key={group.id} className="space-y-2">
                    <div>
                        <h3 className="text-sm font-semibold text-text-1">{group.label}</h3>
                        <p className="text-xs text-text-3">{group.blurb}</p>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                        {sections.map(({ section, enabled, reason }) => {
                            const Icon = section.icon;
                            if (!enabled) return (
                                <GlassPanel key={section.id} elevation="flat" className="flex gap-3 p-3 opacity-60"
                                    aria-label={`${section.label} (unavailable)`}>
                                    <Icon size={17} className="mt-0.5 shrink-0 text-text-3" />
                                    <div className="min-w-0">
                                        <p className="flex items-center gap-1.5 text-sm font-medium text-text-2">
                                            {section.label}<Lock size={11} className="text-text-3" />
                                        </p>
                                        <p className="mt-0.5 text-xs text-text-3">{section.blurb}</p>
                                        <p className="mt-1 text-xs text-text-3 italic">{reason}</p>
                                    </div>
                                </GlassPanel>
                            );
                            const count = counts[section.id];
                            return (
                                <Link key={section.id} to={`${basePath}/${section.id}`} className="block">
                                    <GlassPanel elevation="flat" className="flex h-full gap-3 p-3 transition-colors hover:bg-surface-2">
                                        <Icon size={17} className="mt-0.5 shrink-0 text-accent" />
                                        <div className="min-w-0 flex-1">
                                            <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-text-1">
                                                {section.label}
                                                {typeof count === 'number' ? <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[11px] leading-none text-text-3">{count}</span> : null}
                                                {section.availabilityLabel ? <span className="text-xs font-normal text-text-3">{section.availabilityLabel}</span> : null}
                                            </p>
                                            <p className="mt-0.5 text-xs text-text-3">{section.blurb}</p>
                                        </div>
                                    </GlassPanel>
                                </Link>
                            );
                        })}
                    </div>
                </section>
            ))}
            {showRelationships ? (
                <GlassPanel elevation="flat" className="space-y-2 p-4">
                    <h3 className="text-sm font-semibold text-text-1">How these fit together</h3>
                    <ul className="space-y-1.5">
                        {[
                            ['Identities', 'File sources', 'Documents'], ['Documents', 'Agents'],
                            ['Actions', 'Agents'], ['Endpoints', 'Agents'], ['Agents', 'Workflows'],
                        ].map((parts) => (
                            <li key={parts.join(':')} className="flex flex-wrap items-center gap-1.5 text-xs text-text-3">
                                {parts.map((part, index) => (
                                    <span key={part} className="flex items-center gap-1.5">
                                        {index > 0 ? <ArrowRight size={11} className="text-text-3" /> : null}
                                        <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-text-2">{part}</span>
                                    </span>
                                ))}
                            </li>
                        ))}
                    </ul>
                    <p className="text-xs text-text-3">
                        Read left to right: the thing on the left is used by the thing on its
                        right. Identities and endpoints exist to be reused, so they rarely need
                        attention once set up.
                    </p>
                </GlassPanel>
            ) : null}
        </div>
    );
}
