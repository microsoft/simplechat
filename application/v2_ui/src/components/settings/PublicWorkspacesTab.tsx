// PublicWorkspacesTab.tsx
// The public workspaces available to this user, and which one is active.

import { TabNotBuiltYet } from './TabScaffold';

export function PublicWorkspacesTab() {
    return (
        <TabNotBuiltYet
            title="Public workspaces"
            description="Browsing public workspaces and choosing an active one has not been rebuilt in this interface yet."
            classicHref="/profile?tab=public-workspaces"
            classicLabel="Open public workspaces in the classic interface"
        />
    );
}
