// groupManageSections.ts
// The group workspace's management sections, in the group-only "Manage" group of the rail.
//
// Kept apart from the personal section registry (sections.tsx), which the personal workspace
// and its server-side registry share: a group management section has no personal counterpart,
// and the server reports it only in the group workspace context (`sections.members`). The
// group page resolves these with the rest of its sections, so a section the server does not
// report stays out of the rail. M7C adds Settings, Activity and Statistics here.

import { Activity, BarChart3, Settings, UserCog } from 'lucide-react';
import type { WorkspaceOverviewSection } from '../../components/workspace/WorkspaceOverview';
import type { GroupManageSectionId } from '../../lib/workspaceContext';

export interface GroupManageSection extends WorkspaceOverviewSection {
    id: GroupManageSectionId;
}

export const GROUP_MANAGE_SECTIONS: GroupManageSection[] = [
    {
        id: 'members',
        label: 'Members',
        group: 'manage',
        icon: UserCog,
        blurb: 'Who belongs to this group, their roles, and who is asking to join.',
    },
    {
        id: 'settings',
        label: 'Settings',
        group: 'manage',
        icon: Settings,
        blurb: "The group's name, description, colour, logo, downloads and retention.",
    },
    {
        id: 'activity',
        label: 'Activity',
        group: 'manage',
        icon: Activity,
        blurb: 'A recent record of what changed in this group and who changed it.',
    },
    {
        id: 'statistics',
        label: 'Statistics',
        group: 'manage',
        icon: BarChart3,
        blurb: "The group's documents, storage, tokens and members over time.",
    },
];
