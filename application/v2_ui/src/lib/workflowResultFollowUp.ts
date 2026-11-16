// workflowResultFollowUp.ts
// The one way to open a chat about a finished workflow run's stored result (phase 6a).
//
// Ask in chat on a run row and Ask about this on a workflow alert come through here, and so
// will phase 6b's delivered message, run card and recurring-workflow card, so every entry
// point opens the same kind of chat the same way.

import { chatHrefForWorkflowResult } from './conversationUrl';
import type { WorkflowResultContext } from './types';
import { useChatStore } from '../stores/chatStore';

export interface WorkflowResultNavigation {
    navigate: (path: string) => void;
    /** The current route, relative to the router's `/v2` base. */
    pathname: string;
}

/**
 * Open a new chat asking about one finished personal workflow run.
 *
 * The run's current descriptor is always read again rather than trusted from the caller, so
 * the chip names the result as it is now and a run that can no longer be asked about is
 * reported instead of selected. On the chat page the store starts the chat directly: the page
 * reads its query string only on its first render, so a link that only changed it would leave
 * the old chat on screen. Anywhere else the link is followed.
 */
export function openWorkflowResultInChat(
    workflowId: string,
    runId: string,
    navigation: WorkflowResultNavigation,
): void {
    if (navigation.pathname === '/chat') {
        void useChatStore.getState().launchWorkflowResult(workflowId, runId);
        return;
    }
    navigation.navigate(chatHrefForWorkflowResult(workflowId, runId));
}

/**
 * Follow up on a run a card or message already describes (phase 6b's seam).
 *
 * Only the run's identity is used; the descriptor it carries may be stale by now.
 */
export function followUpWorkflowResult(
    descriptor: Pick<WorkflowResultContext, 'workflow_id' | 'run_id'>,
    navigation: WorkflowResultNavigation,
): void {
    openWorkflowResultInChat(descriptor.workflow_id, descriptor.run_id, navigation);
}
