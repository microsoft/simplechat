// PublicWorkspacesTab.tsx
// The public workspaces available to this user, and which one is active.

import { PUBLIC_WORKSPACES } from '../../lib/workspaces';
import { WorkspaceListTab } from './WorkspaceListTab';

export function PublicWorkspacesTab() {
    return <WorkspaceListTab kind={PUBLIC_WORKSPACES} />;
}
