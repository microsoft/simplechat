// FeedbackTab.tsx
// Feedback this user has submitted, and what came of it.

import { TabNotBuiltYet } from './TabScaffold';

export function FeedbackTab() {
    return (
        <TabNotBuiltYet
            title="Feedback"
            description="The feedback you have submitted has not been rebuilt in this interface yet."
            classicHref="/profile?tab=feedback"
            classicLabel="Open feedback in the classic interface"
        />
    );
}
