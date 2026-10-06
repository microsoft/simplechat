// WorkflowDeliveryFooter.tsx
// The actions under a message a chat-started workflow run posted back to its chat (phase 6b).
//
// The message itself, a label line naming the workflow and when it was asked for and then the
// result or a note on how the run ended, is the server's text and renders like any other answer.
// This footer adds what the chat can do next with it:
//
// - Follow up, on a result, makes that result the composer's source in this chat.
// - Open run opens the run in Workflows.
// - Retry workflow run, on a failed run's note, resumes that same run. It shows only while the
//   tab's run tracker has just read the run and the server says it would still resume it, for the
//   generation this note reported. It never starts a new run.
//
// The chat's own Retry and Edit are hidden on these messages: the server refuses both.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { useFeature } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { useWorkflowRunTrackerStore } from '../../stores/workflowRunTrackerStore';
import { useFocusFallback } from '../../lib/useFocusFallback';
import { useWorkflowRunAction } from '../../lib/useWorkflowRunAction';
import { requestWorkflowConversationRuns } from '../../lib/useWorkflowRunTracker';
import {
    workflowDeliveryCanRetry,
    workflowDeliveryFollowUp,
    workflowDeliveryFooterId,
    workflowDeliveryRun,
    WORKFLOW_DELIVERY_FOLLOW_UP_UNAVAILABLE_TEXT,
    type WorkflowDeliveryMetadata,
} from '../../lib/workflowDelivery';
import { workflowRunHref } from '../../lib/workflowRunLink';

const LINK_CLASS = 'inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

export function WorkflowDeliveryFooter({
    messageId,
    conversationId,
    delivery,
    metadata,
}: {
    messageId: string;
    conversationId: string;
    delivery: WorkflowDeliveryMetadata;
    /** The message's whole metadata, which carries the result's descriptor. */
    metadata: unknown;
}) {
    const resultsInChat = useFeature('enable_chat_workflow_results');
    const workflowsOn = useFeature('allow_user_workflows');
    const descriptor = useMemo(
        () => (resultsInChat ? workflowDeliveryFollowUp(delivery, metadata) : null),
        [resultsInChat, delivery, metadata],
    );
    const canRetry = useWorkflowRunTrackerStore((state) =>
        workflowDeliveryCanRetry(state.snapshot, delivery, conversationId));
    // The tracker's name for the run, when it has read it; the message's label names it either way.
    const name = useWorkflowRunTrackerStore((state) =>
        workflowDeliveryRun(state.snapshot, delivery, conversationId)?.row.workflow_name ?? '');
    const { pending, outcome, run } = useWorkflowRunAction(conversationId, delivery.workflow_id, delivery.run_id);
    const [followUpNote, setFollowUpNote] = useState('');
    const section = useRef<HTMLElement>(null);
    const armFocus = useFocusFallback(section, canRetry, pending !== null);
    const failed = delivery.kind === 'failed';

    // A failed run's note offers Retry only after a fresh read says the run can still be resumed.
    useEffect(() => {
        if (failed) {
            void requestWorkflowConversationRuns(conversationId);
        }
    }, [failed, conversationId]);

    if (!descriptor && !workflowsOn) {
        return null;
    }

    const followUp = () => {
        if (!descriptor) return;
        if (useChatStore.getState().selectWorkflowResult(descriptor, conversationId)) {
            setFollowUpNote('');
            document.getElementById('composer-input')?.focus();
        } else {
            setFollowUpNote(WORKFLOW_DELIVERY_FOLLOW_UP_UNAVAILABLE_TEXT);
        }
    };
    const note = outcome || followUpNote;

    return (
        <section
            ref={section}
            id={workflowDeliveryFooterId(messageId)}
            tabIndex={-1}
            aria-label={name ? `Workflow run: ${name}` : 'Workflow run'}
            className="mt-3 min-w-0 rounded-xl border border-edge p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
            <div className="flex flex-wrap items-center gap-2">
                {descriptor ? (
                    <GlassButton type="button" size="sm" variant="subtle"
                        aria-label={name ? `Follow up on ${name}` : 'Follow up on this result'}
                        onClick={followUp}>
                        Follow up
                    </GlassButton>
                ) : null}
                {canRetry ? (
                    <GlassButton type="button" size="sm" variant="ghost"
                        className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                        aria-label={name ? `Retry workflow run of ${name}` : 'Retry workflow run'}
                        aria-disabled={pending !== null || undefined}
                        onClick={() => {
                            if (pending !== null) return;
                            armFocus();
                            void run('retry');
                        }}>
                        {pending === 'retry' ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                        Retry workflow run
                    </GlassButton>
                ) : null}
                {workflowsOn ? (
                    <Link to={workflowRunHref(delivery.workflow_id, delivery.run_id)}
                        aria-label={name ? `Open run of ${name}` : 'Open run that posted this message'}
                        className={LINK_CLASS}>
                        Open run
                    </Link>
                ) : null}
            </div>
            <p role="status" className={note ? 'mt-2 break-words text-xs text-text-2' : 'sr-only'}>{note}</p>
        </section>
    );
}
