// GroupsTab.tsx
// The group workspaces this user belongs to, and which one is active.

import { GROUP_WORKSPACES } from '../../lib/workspaces';
import { WorkspaceListTab } from './WorkspaceListTab';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function GroupsTab() {
    const viewerId = useBootstrapStore((state) => state.data?.user.id);
    return <WorkspaceListTab key={viewerId} kind={GROUP_WORKSPACES} />;
}
