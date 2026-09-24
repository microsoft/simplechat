// groupManageSections.ts
// The group workspace's management sections, in the group-only "Manage" group of the rail.
//
// Kept apart from the personal section registry (sections.tsx), which the personal workspace
// and its server-side registry share: a group management section has no personal counterpart,
// and the server reports it only in the group workspace context (`sections.members`). The
// group page resolves these with the rest of its sections, so a section the server does not
// report stays out of the rail. M7C adds Settings, Activity and Statistics here.

import { UserCog } from 'lucide-react';
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
];
