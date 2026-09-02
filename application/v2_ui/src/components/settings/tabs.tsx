// tabs.tsx
// The registry of settings tabs.
//
// Each tab is a self-contained component listed here once. Keeping the list in its own
// module means a tab can be built without touching the page shell, the router or the
// sidebar, which is what lets the remaining tabs be built independently of each other.
//
// Tab order differs from the classic profile page, which leads with Stats. Preferences comes
// first here because it is the reason a V2 user opens this page; the rest keep their
// familiar order.

import type { ComponentType } from 'react';
import {
    BarChart3,
    Globe2,
    MessageSquareHeart,
    ShieldAlert,
    SlidersHorizontal,
    Users,
} from 'lucide-react';
import { PreferencesTab } from './PreferencesTab';
import { StatsTab } from './StatsTab';
import { GroupsTab } from './GroupsTab';
import { PublicWorkspacesTab } from './PublicWorkspacesTab';
import { FeedbackTab } from './FeedbackTab';
import { ViolationsTab } from './ViolationsTab';

export interface SettingsTab {
    id: string;
    label: string;
    icon: ComponentType<{ size?: number | string; className?: string }>;
    /**
     * Admin capability that must be on for the tab to appear at all.
     *
     * A tab whose feature is disabled is hidden rather than shown empty: its endpoints
     * return errors in that state, so it could only ever display a failure.
     */
    feature?: string;
    Component: ComponentType;
}

export const SETTINGS_TABS: SettingsTab[] = [
    { id: 'preferences', label: 'Preferences', icon: SlidersHorizontal, Component: PreferencesTab },
    { id: 'stats', label: 'Stats', icon: BarChart3, Component: StatsTab },
    {
        id: 'groups',
        label: 'Groups',
        icon: Users,
        feature: 'enable_group_workspaces',
        Component: GroupsTab,
    },
    {
        id: 'public',
        label: 'Public',
        icon: Globe2,
        feature: 'enable_public_workspaces',
        Component: PublicWorkspacesTab,
    },
    {
        id: 'feedback',
        label: 'Feedback',
        icon: MessageSquareHeart,
        feature: 'enable_user_feedback',
        Component: FeedbackTab,
    },
    {
        id: 'violations',
        label: 'Violations',
        icon: ShieldAlert,
        feature: 'enable_content_safety',
        Component: ViolationsTab,
    },
];
