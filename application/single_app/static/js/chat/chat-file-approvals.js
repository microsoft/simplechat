// chat-file-approvals.js

import { showToast } from "./chat-toast.js";

const APPROVAL_STATE_PENDING = 'pending_approval';
const APPROVAL_STATE_APPROVED = 'approved';
const APPROVAL_STATE_DENIED = 'denied';
const APPROVAL_STATE_AUTO_DENIED = 'auto_denied';

/**
 * Read the approval descriptor attached to a generated artifact, when one exists.
 * Artifacts produced by a conversation owner carry no descriptor and stay ungated.
 */
export function getGeneratedFileApproval(outputMetadata) {
    const approval = outputMetadata && typeof outputMetadata.approval === 'object'
        ? outputMetadata.approval
        : null;
    if (!approval) {
        return null;
    }

    const state = String(approval.state || '').trim().toLowerCase();
    if (!state) {
        return null;
    }

    return {
        state,
        isPending: state === APPROVAL_STATE_PENDING,
        isApproved: state === APPROVAL_STATE_APPROVED,
        isDenied: state === APPROVAL_STATE_DENIED || state === APPROVAL_STATE_AUTO_DENIED,
        isAutoDenied: state === APPROVAL_STATE_AUTO_DENIED,
        viewerCanApprove: approval.viewer_can_approve === true,
        viewerIsRequester: approval.viewer_is_requester === true,
        requestedByName: String(approval.requested_by_name || '').trim(),
        resolvedByName: String(approval.resolved_by_name || '').trim(),
    };
}

/**
 * Return whether the artifact content is currently unavailable to everyone.
 * A staged file is withheld from the requester too, so the download control is suppressed.
 */
export function generatedFileApprovalBlocksDownload(outputMetadata) {
    const approval = getGeneratedFileApproval(outputMetadata);
    if (!approval) {
        return false;
    }
    return approval.isPending || approval.isDenied;
}

function buildApprovalMessage(approval) {
    if (approval.isApproved) {
        return approval.resolvedByName
            ? `Approved by ${approval.resolvedByName}.`
            : 'Approved.';
    }

    if (approval.isAutoDenied) {
        return 'This file expired before it was approved and is no longer available.';
    }

    if (approval.isDenied) {
        return approval.resolvedByName
            ? `${approval.resolvedByName} declined this file, so it is not available.`
            : 'This file was declined and is not available.';
    }

    if (approval.viewerCanApprove) {
        return approval.requestedByName
            ? `${approval.requestedByName} generated this file in a shared conversation. Approve it to make it available.`
            : 'A participant generated this file in a shared conversation. Approve it to make it available.';
    }

    if (approval.viewerIsRequester) {
        return 'This file is waiting for the conversation owner to approve it before it can be downloaded.';
    }

    return 'This file is waiting for approval before it can be downloaded.';
}

async function submitApprovalDecision(outputMetadata, decision) {
    const sourceConversationId = String(outputMetadata?.conversation_id || '').trim();
    const artifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
    if (!sourceConversationId || !artifactMessageId) {
        throw new Error('This file approval is missing its conversation reference.');
    }

    const response = await fetch(
        `/api/collaboration/file-approvals/${encodeURIComponent(sourceConversationId)}`
        + `/${encodeURIComponent(artifactMessageId)}/${encodeURIComponent(decision)}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
        },
    );

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || `Failed to ${decision} this file.`);
    }
    return payload;
}

/**
 * Build the approval banner rendered on a gated artifact card.
 * Returns null when the artifact is approved or was never gated, so ordinary
 * downloads render unchanged.
 */
export function buildGeneratedFileApprovalBlock(outputMetadata, onResolved = null) {
    const approval = getGeneratedFileApproval(outputMetadata);
    if (!approval || approval.isApproved) {
        return null;
    }

    const wrapper = document.createElement('div');
    wrapper.className = approval.isDenied
        ? 'alert alert-secondary d-flex flex-column gap-2 mt-3 mb-0'
        : 'alert alert-warning d-flex flex-column gap-2 mt-3 mb-0';
    wrapper.setAttribute('role', 'status');

    const headline = document.createElement('div');
    headline.className = 'd-flex align-items-start gap-2';

    const icon = document.createElement('i');
    icon.className = approval.isDenied ? 'bi bi-file-earmark-x' : 'bi bi-file-earmark-lock';
    icon.setAttribute('aria-hidden', 'true');
    headline.appendChild(icon);

    const messageText = document.createElement('span');
    messageText.className = 'small';
    messageText.textContent = buildApprovalMessage(approval);
    headline.appendChild(messageText);
    wrapper.appendChild(headline);

    if (!approval.isPending || !approval.viewerCanApprove) {
        return wrapper;
    }

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2';

    const approveButton = document.createElement('button');
    approveButton.type = 'button';
    approveButton.className = 'btn btn-sm btn-success generated-file-approve-btn';
    approveButton.textContent = 'Approve';

    const denyButton = document.createElement('button');
    denyButton.type = 'button';
    denyButton.className = 'btn btn-sm btn-outline-danger generated-file-deny-btn';
    denyButton.textContent = 'Deny';

    const setBusy = isBusy => {
        approveButton.disabled = isBusy;
        denyButton.disabled = isBusy;
    };

    const handleDecision = async decision => {
        setBusy(true);
        try {
            const payload = await submitApprovalDecision(outputMetadata, decision);
            showToast(
                decision === 'approve' ? 'File approved.' : 'File declined.',
                decision === 'approve' ? 'success' : 'secondary',
            );
            if (typeof onResolved === 'function') {
                onResolved(decision, payload);
            }
        } catch (error) {
            showToast(error.message || 'Failed to update this file approval.', 'danger');
            setBusy(false);
        }
    };

    approveButton.addEventListener('click', () => handleDecision('approve'));
    denyButton.addEventListener('click', () => handleDecision('deny'));

    actions.appendChild(approveButton);
    actions.appendChild(denyButton);
    wrapper.appendChild(actions);

    return wrapper;
}
