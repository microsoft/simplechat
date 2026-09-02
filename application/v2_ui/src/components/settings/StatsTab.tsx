// StatsTab.tsx
// The user's own usage statistics.

import { TabNotBuiltYet } from './TabScaffold';

export function StatsTab() {
    return (
        <TabNotBuiltYet
            title="Stats"
            description="Your activity trends have not been rebuilt in this interface yet. The classic profile page still shows them."
            classicHref="/profile?tab=stats"
            classicLabel="Open stats in the classic interface"
        />
    );
}
