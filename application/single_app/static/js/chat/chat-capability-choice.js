// chat-capability-choice.js

const CONTINUE_OPTION_ID = 'continue_without_capabilities';
const MAX_OPTIONS = 12;
const REASON_LABELS = Object.freeze({
    current_authoritative_sources: 'Current official sources could materially improve accuracy.',
    current_public_information: 'Current public information could materially improve freshness.',
    user_supplied_url_requires_review: 'The supplied links need review to answer from their contents.',
    workspace_evidence_requested: 'Authorized workspace evidence could materially improve this answer.',
    document_analysis_requested: 'Structured analysis could materially improve the findings.',
    multi_document_comparison: 'A document comparison could materially improve the result.',
    visual_output_materially_helpful: 'A visual output would materially help with this request.',
    multi_source_public_research: 'Multiple authoritative sources could materially improve confidence.',
    specialized_organizational_knowledge: 'A specialized authorized agent could materially improve this answer.',
    business_system_evidence: 'An authorized business-system agent could materially improve the evidence.',
});

function normalizeIdentifier(value) {
    return String(value || '').trim().slice(0, 200);
}

function normalizeProposal(metadata) {
    const proposal = metadata?.capability_proposal;
    if (!proposal || typeof proposal !== 'object') {
        return null;
    }
    const proposalId = normalizeIdentifier(proposal.proposal_id);
    const conversationId = normalizeIdentifier(proposal.conversation_id);
    const status = normalizeIdentifier(proposal.status).toLowerCase();
    const options = Array.isArray(proposal.options)
        ? proposal.options.slice(0, MAX_OPTIONS).map(option => ({
            id: normalizeIdentifier(option?.id),
            kind: ['agent', 'capability', 'continue'].includes(normalizeIdentifier(option?.kind).toLowerCase())
                ? normalizeIdentifier(option?.kind).toLowerCase()
                : 'capability',
            label: String(option?.label || '').trim().slice(0, 120),
            capabilityIds: Array.isArray(option?.capability_ids)
                ? option.capability_ids.map(normalizeIdentifier).filter(Boolean).slice(0, 8)
                : [],
            latencyClass: normalizeIdentifier(option?.latency_class),
            costClass: normalizeIdentifier(option?.cost_class),
            externalData: option?.external_data === true,
            scopeClass: ['personal', 'global', 'group'].includes(
                normalizeIdentifier(option?.scope_class).toLowerCase()
            ) ? normalizeIdentifier(option?.scope_class).toLowerCase() : '',
            readOnly: option?.read_only === true,
            riskClass: normalizeIdentifier(option?.risk_class),
            dataSensitivity: normalizeIdentifier(option?.data_sensitivity),
            sensitiveInputTypes: Array.isArray(option?.sensitive_input_types)
                ? option.sensitive_input_types.map(normalizeIdentifier).filter(Boolean).slice(0, 8)
                : [],
        })).filter(option => option.id && option.label)
        : [];
    if (!proposalId || !conversationId || options.length === 0) {
        return null;
    }
    const expiresAt = normalizeIdentifier(proposal.expires_at);
    const expiresAtMilliseconds = Date.parse(expiresAt);
    return {
        proposalId,
        conversationId,
        status,
        recommendedOptionId: normalizeIdentifier(proposal.recommended_option_id),
        reasonCodes: Array.isArray(proposal.reason_codes)
            ? proposal.reason_codes.map(normalizeIdentifier).filter(Boolean).slice(0, 12)
            : [],
        options,
        decision: proposal.decision && typeof proposal.decision === 'object'
            ? {
                optionId: normalizeIdentifier(proposal.decision.option_id),
                status: normalizeIdentifier(proposal.decision.status).toLowerCase(),
            }
            : null,
        resume: proposal.resume && typeof proposal.resume === 'object'
            ? {
                status: normalizeIdentifier(proposal.resume.status).toLowerCase(),
                assistantMessageId: normalizeIdentifier(proposal.resume.assistant_message_id),
            }
            : { status: 'not_requested', assistantMessageId: '' },
        expiresAt,
        expired: Number.isFinite(expiresAtMilliseconds) && expiresAtMilliseconds <= Date.now(),
    };
}

function createElement(tagName, className = '', text = '') {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    if (text) {
        element.textContent = text;
    }
    return element;
}

function appendOptionMeta(container, option) {
    const parts = [];
    if (option.kind === 'agent') {
        parts.push('Agent');
        if (option.scopeClass) {
            parts.push(`Scope: ${option.scopeClass}`);
        }
        if (option.readOnly) {
            parts.push('Read only');
        }
        if (option.riskClass) {
            parts.push(`Risk: ${option.riskClass.replaceAll('_', ' ')}`);
        }
        if (option.dataSensitivity) {
            parts.push(`Data: ${option.dataSensitivity.replaceAll('_', ' ')}`);
        }
    }
    if (option.latencyClass) {
        parts.push(`Time: ${option.latencyClass}`);
    }
    if (option.costClass) {
        parts.push(`Cost: ${option.costClass}`);
    }
    if (parts.length === 0) {
        return;
    }
    const metadata = createElement('span', 'sc-capability-choice-option-meta', parts.join(' | '));
    if (option.kind === 'agent') {
        metadata.dataset.testid = 'agent-option-meta';
    }
    container.appendChild(metadata);
}

function getReasonText(proposal) {
    const reasonCode = proposal.reasonCodes.find(code => REASON_LABELS[code]);
    return REASON_LABELS[reasonCode] || 'An additional capability could materially improve this answer.';
}

function setCardBusy(card, busy) {
    card.dataset.submitting = busy ? 'true' : 'false';
    card.querySelectorAll('button').forEach(button => {
        button.disabled = busy;
    });
}

function updateStatus(statusElement, message, tone = 'muted') {
    statusElement.className = `sc-capability-choice-status text-${tone}`;
    statusElement.textContent = message;
}

async function submitDecision(card, proposal, option, statusElement, onResume) {
    if (card.dataset.submitting === 'true') {
        return;
    }
    setCardBusy(card, true);
    updateStatus(statusElement, 'Saving your choice...', 'primary');
    try {
        const response = await fetch(
            `/api/chat/capability-proposals/${encodeURIComponent(proposal.proposalId)}/decision`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    conversation_id: proposal.conversationId,
                    option_id: option.id,
                }),
            },
        );
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.error || 'Your capability choice could not be saved.');
        }
        updateStatus(
            statusElement,
            option.id === CONTINUE_OPTION_ID
                ? 'Continuing without additional capabilities...'
                : `Approved ${option.label}. Resuming...`,
            'primary',
        );
        if (typeof onResume !== 'function') {
            throw new Error('Chat resume is not available. Refresh this conversation to continue.');
        }
        await onResume({
            conversationId: proposal.conversationId,
            proposalId: proposal.proposalId,
            endpoint: result.resume_endpoint || '/api/chat/stream',
        });
        updateStatus(
            statusElement,
            option.id === CONTINUE_OPTION_ID
                ? 'Completed without additional capabilities.'
                : `Completed with ${option.label}.`,
            'success',
        );
    } catch (error) {
        setCardBusy(card, false);
        updateStatus(
            statusElement,
            error?.message || 'Your capability choice could not be saved.',
            'danger',
        );
    }
}

function renderPendingOptions(card, proposal, actions, statusElement, onResume) {
    proposal.options.forEach(option => {
        const isRecommended = option.id === proposal.recommendedOptionId;
        const isContinue = option.id === CONTINUE_OPTION_ID;
        const button = createElement(
            'button',
            isContinue
                ? 'btn btn-outline-secondary sc-capability-choice-button'
                : isRecommended
                ? 'btn btn-primary sc-capability-choice-button'
                : 'btn btn-outline-primary sc-capability-choice-button',
        );
        button.type = 'button';
        button.dataset.optionId = option.id;
        button.setAttribute('aria-describedby', statusElement.id);

        const label = createElement('span', 'sc-capability-choice-option-label', option.label);
        button.appendChild(label);
        if (isRecommended) {
            button.appendChild(createElement('span', 'badge text-bg-light ms-2', 'Recommended'));
        }
        appendOptionMeta(button, option);
        button.addEventListener('click', () => {
            void submitDecision(card, proposal, option, statusElement, onResume);
        });
        actions.appendChild(button);
    });
}

function renderResolvedAction(card, proposal, actions, statusElement, onResume) {
    const selectedOption = proposal.options.find(option => option.id === proposal.decision?.optionId);
    const selectedLabel = selectedOption?.label || 'saved choice';
    if (proposal.resume.status === 'completed') {
        updateStatus(statusElement, `Completed with ${selectedLabel}.`, 'success');
        return;
    }
    if (proposal.resume.status === 'running') {
        updateStatus(statusElement, `Resuming with ${selectedLabel}...`, 'primary');
        return;
    }
    if (!selectedOption) {
        updateStatus(statusElement, 'This capability choice is no longer available.', 'danger');
        return;
    }
    const resumeButton = createElement(
        'button',
        'btn btn-primary sc-capability-choice-button',
        proposal.resume.status === 'failed' ? 'Retry resume' : 'Resume',
    );
    resumeButton.type = 'button';
    resumeButton.setAttribute('aria-describedby', statusElement.id);
    resumeButton.addEventListener('click', () => {
        void submitDecision(card, proposal, selectedOption, statusElement, onResume);
    });
    actions.appendChild(resumeButton);
    updateStatus(
        statusElement,
        proposal.resume.status === 'failed'
            ? `The previous resume attempt failed. ${selectedLabel} remains approved for this turn.`
            : `${selectedLabel} is saved and ready to resume.`,
        proposal.resume.status === 'failed' ? 'warning' : 'muted',
    );
}

export function hydrateCapabilityChoice(messageElement, metadata, { onResume } = {}) {
    if (!messageElement) {
        return;
    }
    messageElement.querySelector('.sc-capability-choice-card')?.remove();
    const proposal = normalizeProposal(metadata);
    if (!proposal) {
        return;
    }

    const messageText = messageElement.querySelector('.message-text');
    if (!messageText) {
        return;
    }
    const safeId = proposal.proposalId.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80) || 'proposal';
    const titleId = `capability-choice-title-${safeId}`;
    const statusId = `capability-choice-status-${safeId}`;
    const card = createElement('section', 'sc-capability-choice-card');
    card.dataset.testid = 'capability-choice-card';
    card.setAttribute('aria-labelledby', titleId);

    const header = createElement('div', 'sc-capability-choice-header');
    const icon = createElement('i', 'bi bi-signpost-split');
    icon.setAttribute('aria-hidden', 'true');
    header.appendChild(icon);
    const title = createElement('h3', 'sc-capability-choice-title', 'Choose how to continue');
    title.id = titleId;
    header.appendChild(title);
    card.appendChild(header);
    card.appendChild(createElement('p', 'sc-capability-choice-reason', getReasonText(proposal)));

    const hasExternalCapabilityOption = proposal.options.some(
        option => option.externalData && option.kind !== 'agent'
    );
    if (hasExternalCapabilityOption) {
        const notice = createElement(
            'p',
            'sc-capability-choice-notice',
            'External options send only the current message query. Conversation history and workspace content are not included.',
        );
        notice.dataset.testid = 'capability-external-data-notice';
        card.appendChild(notice);
    }
    if (proposal.options.some(option => option.externalData && option.kind === 'agent')) {
        const agentExternalNotice = createElement(
            'p',
            'sc-capability-choice-notice',
            'A recommended agent may access external data under its saved governance policy.',
        );
        agentExternalNotice.dataset.testid = 'agent-external-data-notice';
        card.appendChild(agentExternalNotice);
    }
    if (proposal.options.some(option => option.sensitiveInputTypes.length > 0)) {
        const sensitiveNotice = createElement(
            'p',
            'sc-capability-choice-sensitive-notice',
            'Options labeled with the supplied address explicitly approve using that address for this turn.',
        );
        sensitiveNotice.dataset.testid = 'capability-sensitive-data-notice';
        card.appendChild(sensitiveNotice);
    }

    const actions = createElement('div', 'sc-capability-choice-actions');
    const statusElement = createElement('div', 'sc-capability-choice-status text-muted');
    statusElement.id = statusId;
    statusElement.setAttribute('role', 'status');
    statusElement.setAttribute('aria-live', 'polite');
    statusElement.textContent = 'Waiting for your choice.';
    if (proposal.status === 'pending' && proposal.expired) {
        updateStatus(statusElement, 'This capability choice has expired.', 'muted');
    } else if (proposal.status === 'pending') {
        renderPendingOptions(card, proposal, actions, statusElement, onResume);
    } else if (proposal.status === 'approved' || proposal.status === 'declined') {
        renderResolvedAction(card, proposal, actions, statusElement, onResume);
    } else {
        updateStatus(statusElement, 'This capability choice is no longer available.', 'muted');
    }
    card.appendChild(actions);
    card.appendChild(statusElement);
    messageText.insertAdjacentElement('afterend', card);
}