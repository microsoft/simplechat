// WorkflowRunAskInChat.tsx
// Ask in chat on a finished personal workflow run (roadmap phase 6a).

import { MessageSquare } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { GlassButton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    canAskAboutWorkflowRun,
    formatWorkflowRunTime,
    isWorkflowResultIdentifier,
    workflowRunChatId,
    type WorkflowRunForChat,
} from '../../lib/workflowResults';
import { openWorkflowResultInChat } from '../../lib/workflowResultFollowUp';

/**
 * Opens a new chat that answers from this run's stored result without re-running the workflow.
 *
 * Drawn only where the server would accept the question: personal workflows with the
 * administrator's setting on and the reader allowed to use workflows, and finished runs. The
 * bootstrap flag only hides the button; the chat checks everything again.
 */
export function WorkflowRunAskInChat({
    scope,
    workflowId,
    run,
}: {
    scope: { type: string };
    workflowId: string;
    run: WorkflowRunForChat;
}) {
    const enabled = useBootstrapStore((state) =>
        state.data?.features?.enable_chat_workflow_results === true);
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const runId = workflowRunChatId(run);
    if (!runId || !isWorkflowResultIdentifier(workflowId) || !canAskAboutWorkflowRun(scope, run, enabled)) {
        return null;
    }
    const time = formatWorkflowRunTime(
        typeof run.completed_at === 'string' ? run.completed_at
            : typeof run.started_at === 'string' ? run.started_at : null,
    );
    return (
        <GlassButton
            type="button"
            variant="subtle"
            size="sm"
            className="h-7 shrink-0 px-2 text-xs"
            data-workflow-run-ask-in-chat=""
            aria-label={time ? `Ask in chat about the run of ${time}` : undefined}
            onClick={() => openWorkflowResultInChat(workflowId, runId, { navigate, pathname })}
        >
            <MessageSquare size={13} aria-hidden="true" />
            Ask in chat
        </GlassButton>
    );
}
