// GroupsTab.tsx
// The group workspaces this user belongs to, and which one is active.

import { TabNotBuiltYet } from './TabScaffold';

export function GroupsTab() {
    return (
        <TabNotBuiltYet
            title="Group workspaces"
            description="Browsing your groups and choosing an active one has not been rebuilt in this interface yet."
            classicHref="/profile?tab=groups"
            classicLabel="Open groups in the classic interface"
        />
    );
}
