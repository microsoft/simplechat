// workspaceSections.ts
// Grouping and availability rules for the personal workspace.
//
// Deliberately free of React and of the section registry, which carries icons and
// components: everything here is a plain function over plain data so the rules can be
// exercised directly in a test without a renderer.
//
// The workspace is assembled from eight capabilities that an administrator can enable
// independently, which is why a flat list of tabs reads as arbitrary. Grouping them by what
// they are *for* gives the page a shape that survives any particular tenant's
// configuration: knowledge is what the assistant can draw on, automation is what it can do,
// and connections is the shared setup the other two reuse.

import type { WorkspaceAvailability, WorkspaceSectionGroup } from './types';

export interface WorkspaceGroupMeta {
    id: WorkspaceSectionGroup;
    label: string;
    /** One line saying what the group is for. Shown on the overview and above the rail. */
    blurb: string;
}

export const WORKSPACE_GROUPS: WorkspaceGroupMeta[] = [
    {
        id: 'knowledge',
        label: 'Knowledge',
        blurb: 'What your assistant can draw on.',
    },
    {
        id: 'automation',
        label: 'Automation',
        blurb: 'What your assistant can do.',
    },
    {
        id: 'connections',
        label: 'Connections',
        blurb: 'Shared setup the other sections reuse.',
    },
];

export interface WorkspaceSectionDescriptor {
    id: string;
    group: WorkspaceSectionGroup;
}

export interface ResolvedWorkspaceSection<T extends WorkspaceSectionDescriptor> {
    section: T;
    enabled: boolean;
    /** Why the section is unavailable, straight from the server. Null when enabled. */
    reason: string | null;
}

export interface WorkspaceSectionGroupView<T extends WorkspaceSectionDescriptor> {
    group: WorkspaceGroupMeta;
    sections: ResolvedWorkspaceSection<T>[];
}

const MISSING_SECTION_REASON = 'This section is not available in this deployment.';

/**
 * Pair each known section with the server's verdict on it.
 *
 * A section the server does not mention is treated as unavailable rather than as available.
 * The alternative fails open: a capability the server has stopped reporting would render a
 * section whose endpoints refuse every request.
 */
export function resolveWorkspaceSections<T extends WorkspaceSectionDescriptor>(
    descriptors: readonly T[],
    availability: WorkspaceAvailability | null | undefined,
): ResolvedWorkspaceSection<T>[] {
    const sections = availability?.sections ?? {};
    return descriptors.map((section) => {
        const state = sections[section.id];
        if (!state) {
            return { section, enabled: false, reason: MISSING_SECTION_REASON };
        }
        return {
            section,
            enabled: Boolean(state.enabled),
            reason: state.enabled ? null : (state.reason ?? MISSING_SECTION_REASON),
        };
    });
}

/**
 * The sections that belong in the navigation rail.
 *
 * Only enabled ones. A disabled section is still described on the overview, where there is
 * room to say *why* it is unavailable -- which is the part that stops people wondering
 * whether a capability is missing, broken, or simply not switched on for them. A dead entry
 * in the rail would carry no such explanation.
 */
export function navigableSections<T extends WorkspaceSectionDescriptor>(
    resolved: readonly ResolvedWorkspaceSection<T>[],
): ResolvedWorkspaceSection<T>[] {
    return resolved.filter((entry) => entry.enabled);
}

/** Group sections for display, dropping groups that ended up with nothing in them. */
export function groupWorkspaceSections<T extends WorkspaceSectionDescriptor>(
    resolved: readonly ResolvedWorkspaceSection<T>[],
): WorkspaceSectionGroupView<T>[] {
    return WORKSPACE_GROUPS.map((group) => ({
        group,
        sections: resolved.filter((entry) => entry.section.group === group.id),
    })).filter((view) => view.sections.length > 0);
}

/**
 * Which section to show when none was asked for, or when the one asked for is unavailable.
 *
 * Returns null when nothing is enabled, which the page renders as an empty state rather
 * than redirecting somewhere the user did not ask to go.
 */
export function defaultSectionId<T extends WorkspaceSectionDescriptor>(
    resolved: readonly ResolvedWorkspaceSection<T>[],
    requested?: string | null,
): string | null {
    if (requested) {
        const match = resolved.find((entry) => entry.section.id === requested);
        if (match?.enabled) {
            return match.section.id;
        }
    }
    return navigableSections(resolved)[0]?.section.id ?? null;
}

/** True when the user has at least one section available. */
export function hasAnyWorkspaceSection<T extends WorkspaceSectionDescriptor>(
    resolved: readonly ResolvedWorkspaceSection<T>[],
): boolean {
    return resolved.some((entry) => entry.enabled);
}
