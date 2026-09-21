// PublicWorkspacesTab.tsx
// The public workspaces available to this user, and which one is active.

import { PUBLIC_WORKSPACES } from '../../lib/workspaces';
import { WorkspaceListTab } from './WorkspaceListTab';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function PublicWorkspacesTab() {
    const viewerId = useBootstrapStore((state) => state.data?.user.id);
    return <WorkspaceListTab key={viewerId} kind={PUBLIC_WORKSPACES} />;
}
