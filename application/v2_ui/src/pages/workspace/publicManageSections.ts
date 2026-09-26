// publicManageSections.ts
// The public workspace's management sections, in the public "Manage" group of the rail.
//
// Kept apart from the shared content registry (sections.tsx) and from the group's manage list
// (groupManageSections.ts): a public management section has no personal counterpart and its
// wording is the public workspace's own. The server reports it only in the public workspace
// context (`sections.members`), so a section the server does not report stays out of the rail.
// M10A adds Members; settings, activity and statistics arrive with M10C.

import { UserCog } from 'lucide-react';
import type { WorkspaceOverviewSection } from '../../components/workspace/WorkspaceOverview';
import type { PublicManageSectionId } from '../../lib/workspaceContext';

export interface PublicManageSection extends WorkspaceOverviewSection {
    id: PublicManageSectionId;
}

export const PUBLIC_MANAGE_SECTIONS: PublicManageSection[] = [
    {
        id: 'members',
        label: 'Members',
        group: 'manage',
        icon: UserCog,
        blurb: 'Who manages this workspace, their roles, and who is asking to help.',
    },
];
