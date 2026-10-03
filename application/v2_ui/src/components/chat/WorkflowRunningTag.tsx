// WorkflowRunningTag.tsx
// A spinner in the chat list while a saved workflow run a chat started is still going, or its
// results are still on their way back to that chat (phase 6b).
//
// It reads only what the tab's workflow run tracker already knows, so the list sends no request of
// its own. It gives way to the unread dot: once a run's results are posted the chat is marked
// unread, and the dot is what says there's something new to read. The workflow's name is
// user-authored and is only ever rendered as text.

import { Loader2 } from 'lucide-react';
import { useWorkflowRunTrackerStore, workflowRunningTagLabel } from '../../stores/workflowRunTrackerStore';
import type { Conversation } from '../../lib/types';

export function WorkflowRunningTag({ conversation }: { conversation: Conversation }) {
    const label = useWorkflowRunTrackerStore((state) => workflowRunningTagLabel(state.snapshot, conversation.id));

    if (!label || conversation.has_unread_assistant_response) {
        return null;
    }

    return (
        <span role="img" title={label} aria-label={label} className="flex shrink-0 items-center text-accent">
            <Loader2 size={11} className="animate-spin" aria-hidden="true" />
        </span>
    );
}
