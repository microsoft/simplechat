// GroupsTab.tsx
// The group workspaces this user belongs to, and which one is active.

import { GROUP_WORKSPACES } from '../../lib/workspaces';
import { WorkspaceListTab } from './WorkspaceListTab';

export function GroupsTab() {
    return <WorkspaceListTab kind={GROUP_WORKSPACES} />;
}
