// workflowDelivery.ts
// The messages a chat-started workflow run posts back to the chat that started it (phase 6b).
//
// When a plan starts one of the requester's saved workflows, the server later posts the run's
// result, or a note saying how it ended, into that chat: once per generation of the run. Each
// such message carries `metadata.workflow_delivery`, and its id starts with
// `assistant_workflow_delivery_`. Either one marks it. The server refuses to retry or edit such a
// message, so the chat hides its plain Retry. The message gets a footer instead: Follow up on a
// result, Open run, and Retry on a failed run, only while the tracker's latest read of that run
// says the server would still resume it.
//
// Everything here is pure, so it is checked in isolation by
// functional_tests/test_v2_workflow_delivery_messages.mjs.

import type { CompletedReply } from './replyEvents';
import type { ChatMessage } from './types';
import { readWorkflowResult } from './workflowResults';
import type { WorkflowResultDescriptor } from './types';
import {
    isWorkflowRunIdentifier,
    workflowRunRowControls,
    WORKFLOW_DELIVERY_MESSAGE_PREFIX,
    type WorkflowRunStatusRow,
} from './workflowRunStatus';
import type { TrackedWorkflowRun, WorkflowRunTrackerSnapshot } from './workflowRunTracker';

export const WORKFLOW_DELIVERY_VERSION = 1;

/** Said when Follow up couldn't make a delivered result the composer's source. */
export const WORKFLOW_DELIVERY_FOLLOW_UP_UNAVAILABLE_TEXT = 'This result can\'t be used as a source here right now.';

/** The kinds of message the server posts. `expired` is only ever a bell notice, never a message. */
export const WORKFLOW_DELIVERY_KINDS = [
    'result', 'analysis', 'failed', 'cancelled', 'skipped', 'status', 'content_blocked',
] as const;
export type WorkflowDeliveryKind = typeof WORKFLOW_DELIVERY_KINDS[number];

export interface WorkflowDeliveryMetadata {
    version: typeof WORKFLOW_DELIVERY_VERSION;
    /** A kind this client doesn't know reads as `unknown`, which offers Open run only. */
    kind: WorkflowDeliveryKind | 'unknown';
    workflow_id: string;
    workflow_scope: 'personal';
    run_id: string;
    /** The run's control version when this message was composed; null when the server had none. */
    generation: number | null;
    run_status: string | null;
    orchestration_run_id: string | null;
    step_id: string | null;
    requested_at: string | null;
}

/** The kinds whose message carries the run's result, so the chat can ask about it. */
const FOLLOW_UP_KINDS: readonly WorkflowDeliveryKind[] = ['result', 'analysis'];

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function idOrNull(value: unknown): string | null | undefined {
    if (value === null || value === undefined) return null;
    return isWorkflowRunIdentifier(value) ? value : undefined;
}

function textOrNull(value: unknown): string | null | undefined {
    if (value === null || value === undefined) return null;
    return typeof value === 'string' ? value : undefined;
}

/**
 * Whether a workflow run posted this message. The server's own test: the id prefix, or a
 * `workflow_delivery` object in the metadata, whatever that object holds.
 */
export function isWorkflowDeliveryMessage(message: Pick<ChatMessage, 'id' | 'metadata'> | null | undefined): boolean {
    if (!message) return false;
    return (typeof message.id === 'string' && message.id.startsWith(WORKFLOW_DELIVERY_MESSAGE_PREFIX))
        || isRecord(isRecord(message.metadata) ? message.metadata.workflow_delivery : null);
}

/**
 * The delivery metadata a message carries, checked against what the server writes. Anything
 * unexpected reads as none, so the message gets no footer; its plain Retry stays hidden anyway.
 */
export function parseWorkflowDeliveryMetadata(value: unknown): WorkflowDeliveryMetadata | null {
    if (
        !isRecord(value) || value.version !== WORKFLOW_DELIVERY_VERSION
        || typeof value.kind !== 'string' || !value.kind.trim()
        || !isWorkflowRunIdentifier(value.workflow_id) || !isWorkflowRunIdentifier(value.run_id)
        || value.workflow_scope !== 'personal'
    ) {
        return null;
    }
    const generation = value.generation;
    if (generation !== null && generation !== undefined
        && !(typeof generation === 'number' && Number.isInteger(generation) && generation >= 0)) {
        return null;
    }
    const orchestrationRunId = idOrNull(value.orchestration_run_id);
    const stepId = idOrNull(value.step_id);
    const runStatus = textOrNull(value.run_status);
    const requestedAt = textOrNull(value.requested_at);
    if (orchestrationRunId === undefined || stepId === undefined || runStatus === undefined
        || requestedAt === undefined) {
        return null;
    }
    const kind = (WORKFLOW_DELIVERY_KINDS as readonly string[]).includes(value.kind)
        ? value.kind as WorkflowDeliveryKind
        : 'unknown';
    return {
        version: WORKFLOW_DELIVERY_VERSION,
        kind,
        workflow_id: value.workflow_id,
        workflow_scope: 'personal',
        run_id: value.run_id,
        generation: typeof generation === 'number' ? generation : null,
        run_status: runStatus,
        orchestration_run_id: orchestrationRunId,
        step_id: stepId,
        requested_at: requestedAt,
    };
}

/** The delivery metadata of a message, or null when it carries none the client can read. */
export function readWorkflowDelivery(message: Pick<ChatMessage, 'metadata'> | null | undefined): WorkflowDeliveryMetadata | null {
    return parseWorkflowDeliveryMetadata(isRecord(message?.metadata) ? message.metadata.workflow_delivery : null);
}

/**
 * The result a delivered message lets the chat ask about: its own descriptor, only for a result
 * or analysis, only while the server says it can still be read, and only for the same run.
 */
export function workflowDeliveryFollowUp(
    delivery: WorkflowDeliveryMetadata,
    metadata: unknown,
): WorkflowResultDescriptor | null {
    if (!FOLLOW_UP_KINDS.includes(delivery.kind as WorkflowDeliveryKind)) {
        return null;
    }
    const descriptor = readWorkflowResult(metadata);
    if (!descriptor || descriptor.available === false
        || descriptor.workflow_id !== delivery.workflow_id || descriptor.run_id !== delivery.run_id) {
        return null;
    }
    return descriptor;
}

/**
 * The tracker's row for the run that posted a message: the same run, started by the same plan
 * step, in the same chat. Undefined when the tracker hasn't read it, or it doesn't match.
 */
export function workflowDeliveryRun(
    snapshot: WorkflowRunTrackerSnapshot,
    delivery: WorkflowDeliveryMetadata,
    conversationId: string,
): TrackedWorkflowRun | undefined {
    const tracked = snapshot.runs[delivery.run_id];
    if (
        !tracked || tracked.row.conversation_id !== conversationId
        || tracked.row.workflow_id !== delivery.workflow_id
        || tracked.row.orchestration_run_id !== delivery.orchestration_run_id
        || tracked.row.step_id !== delivery.step_id
    ) {
        return undefined;
    }
    return tracked;
}

/**
 * Whether a failed run's note may offer Retry: the tracker is reading, chats can start workflows,
 * and its newest read of the same run says the server would resume it, for the generation this
 * note reported. A note from an earlier generation never retries a run that has since moved on.
 */
export function workflowDeliveryCanRetry(
    snapshot: WorkflowRunTrackerSnapshot,
    delivery: WorkflowDeliveryMetadata,
    conversationId: string,
): boolean {
    if (delivery.kind !== 'failed' || delivery.generation === null || !snapshot.running || snapshot.halted
        || snapshot.available !== true) {
        return false;
    }
    const tracked = workflowDeliveryRun(snapshot, delivery, conversationId);
    if (!tracked || tracked.retired || tracked.row.kind !== 'status') {
        return false;
    }
    return workflowRunRowControls(tracked.row, true).retry
        && tracked.row.delivery.generation === delivery.generation;
}

/** The DOM id of a delivered message's footer, so the run card can move focus to it. */
export function workflowDeliveryFooterId(messageId: string): string {
    return `workflow-delivery-${messageId}`;
}

/**
 * The reply a posted result settles as: a workflow's, so the desktop notice and the unread rules
 * treat it as one, and keyed by the posted message, so one result is never announced twice.
 */
export function workflowDeliveryReply(row: WorkflowRunStatusRow, conversationTitle: string | null): CompletedReply {
    return {
        conversationId: row.conversation_id,
        messageId: row.delivery.message_id,
        runId: row.run_id,
        conversationTitle,
        blocked: false,
        source: 'workflow',
    };
}

/** What the open chat is doing, as far as re-reading its messages is concerned. */
export interface OpenChatActivity {
    /** A reply is streaming into it. */
    streaming: boolean;
    /** Its messages are being read. */
    messagesLoading: boolean;
    /** A plan is still running in it, whose stream the chat store doesn't report. */
    orchestrationActive: boolean;
}

/** Whether a result posted to the open chat must wait before its messages are re-read. */
export function workflowDeliveryMustWait(activity: OpenChatActivity): boolean {
    return activity.streaming || activity.messagesLoading || activity.orchestrationActive;
}

export interface WorkflowDeliveryLanding<T> {
    /** Results for any other chat, settled straight away. */
    elsewhere: T[];
    /** Results for the open chat, settled after one re-read of its messages. */
    reloadNow: T[];
    /** Results for the open chat that wait until it is quiet. */
    waiting: T[];
}

/**
 * Where each posted result lands: another chat's straight away; the open chat's after one re-read,
 * or later when the open chat is busy. `openConversationId` is null when no chat is open.
 */
export function planWorkflowDeliveryLanding<T extends { conversation_id: string }>(
    rows: readonly T[],
    openConversationId: string | null,
    openChatBusy: boolean,
): WorkflowDeliveryLanding<T> {
    const elsewhere = rows.filter((row) => row.conversation_id !== openConversationId);
    const here = rows.filter((row) => row.conversation_id === openConversationId);
    const now = here.length > 0 && openConversationId !== null && !openChatBusy;
    return { elsewhere, reloadNow: now ? here : [], waiting: now ? [] : here };
}
