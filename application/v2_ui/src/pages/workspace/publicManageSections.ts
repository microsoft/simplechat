// publicManageSections.ts
// The public workspace's management sections, in the public "Manage" group of the rail.
//
// Kept apart from the shared content registry (sections.tsx) and from the group's manage list
// (groupManageSections.ts): a public management section has no personal counterpart and its
// wording is the public workspace's own. The server reports them only in the public workspace
// context (`sections.members`, `sections.settings`, ...), so a section the server does not report
// stays out of the rail. M10A adds Members; M10C adds Settings, Activity and Statistics.

import { Activity, BarChart3, Settings, UserCog } from 'lucide-react';
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
    {
        id: 'settings',
        label: 'Settings',
        group: 'manage',
        icon: Settings,
        blurb: "The workspace's name, description, colour, logo, downloads and retention.",
    },
    {
        id: 'activity',
        label: 'Activity',
        group: 'manage',
        icon: Activity,
        blurb: 'A recent record of what changed in this workspace and who changed it.',
    },
    {
        id: 'statistics',
        label: 'Statistics',
        group: 'manage',
        icon: BarChart3,
        blurb: "The workspace's documents, storage, tokens and members over time.",
    },
];
