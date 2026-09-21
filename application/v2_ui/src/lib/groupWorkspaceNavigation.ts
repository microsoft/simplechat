// groupWorkspaceNavigation.ts

import type { WorkspaceAvailability } from './types';
import {
    GROUP_WORKSPACE_SECTION_IDS, workspaceBasePath,
    type GroupWorkspaceContext, type GroupWorkspaceSectionId,
} from './workspaceContext';

export const GROUP_SECTION_BLURBS: Record<GroupWorkspaceSectionId, string> = {
    documents: 'Shared files the team can search and use in chat.',
    tags: 'The shared labels that keep this group\'s documents organized.',
    sync: 'Bring approved files into this group from other systems.',
    prompts: 'Reusable wording the team can use in chat.',
    agents: 'Assistants configured with this group\'s knowledge, models and tools.',
    actions: 'Tools for group agents, including calls to another agent.',
    workflows: 'Repeatable tasks using this group\'s agents and documents.',
    identities: 'Saved sign-ins for this group\'s file sources and actions.',
    endpoints: 'Model connections available to this group\'s agents and workflows.',
};

export function classicGroupSectionLabel(section: string, label: string): string {
    if (section === 'tags') return 'Documents, then Manage Tags';
    if (section === 'sync') return 'Sync';
    return label;
}

export function isGroupWorkspaceSection(value: string | undefined): value is GroupWorkspaceSectionId {
    return GROUP_WORKSPACE_SECTION_IDS.some((id) => id === value);
}

export function groupWorkspacePath(groupId: string, section?: string): string {
    const base = workspaceBasePath({ kind: 'group', id: groupId });
    return isGroupWorkspaceSection(section) ? `${base}/${section}` : base;
}

export function groupWorkspaceNavigationAvailability(context: GroupWorkspaceContext): WorkspaceAvailability {
    return {
        ...context,
        sections: {
            ...context.sections,
            // The existing Call agent tools remain reachable even when full legacy
            // agent/action tabs are unavailable under the personal-kernel setting.
            actions: context.native_delegation?.enabled ? context.native_delegation : context.sections.actions,
        },
    };
}

export const GROUP_STATUS_LABELS: Record<GroupWorkspaceContext['status'], string> = {
    active: 'Active',
    locked: 'Locked - read only',
    upload_disabled: 'Uploads disabled',
    inactive: 'Inactive',
    unknown: 'Status unavailable',
};
