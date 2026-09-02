// ViolationsTab.tsx
// Content-safety violations recorded against this user. Read-only except the user's own
// notes.

import { TabNotBuiltYet } from './TabScaffold';

export function ViolationsTab() {
    return (
        <TabNotBuiltYet
            title="Safety violations"
            description="Reviewing flagged messages and adding your own notes has not been rebuilt in this interface yet."
            classicHref="/profile?tab=violations"
            classicLabel="Open violations in the classic interface"
        />
    );
}
