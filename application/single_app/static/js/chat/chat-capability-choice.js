// chat-capability-choice.js

const CONTINUE_OPTION_ID = 'continue_without_capabilities';
const MAX_OPTIONS = 12;
const CAPABILITY_LABELS = Object.freeze({
    analyze: 'Analyze',
    compare: 'Compare',
    deep_research: 'Deep Research',
    image: 'Image',
    url_access: 'URL Access',
    web_search: 'Web Search',
    workspace_search: 'Workspace Search',
});
const CAPABILITY_ICONS = Object.freeze({
    analyze: 'bi-bar-chart-line',
    compare: 'bi-layout-split',
    deep_research: 'bi-database',
    image: 'bi-image',
    url_access: 'bi-link-45deg',
    web_search: 'bi-search',
    workspace_search: 'bi-collection',
});
const CAPABILITY_DESCRIPTIONS = Object.freeze({
    analyze: 'Analyze authorized documents and return structured findings.',
    compare: 'Compare authorized documents for differences and consistency.',
    deep_research: 'Exhaustive public-source research for broad coverage.',
    image: 'Create a visual output for this request.',
    url_access: 'Review the supplied links and use their contents.',
    web_search: 'Focused current web results for a faster answer.',
    workspace_search: 'Search authorized workspace knowledge and documents.',
});
const LATENCY_LABELS = Object.freeze({
    immediate: 'Immediate',
    seconds: 'Seconds',
    minutes: 'Minutes',
});
const COST_LABELS = Object.freeze({
    none: 'None',
    low: 'Low',
    standard: 'Standard',
    extended: 'Extended',
});
const REASON_LABELS = Object.freeze({
    fresh_public_information: 'Fresh public information could materially improve this answer.',
    public_source_retrieval: 'Public source retrieval could materially improve this answer.',
    public_source_archive_research: 'Broader public archive research could materially improve coverage.',
    multi_source_research: 'Multiple public sources could materially improve confidence.',
    authorized_workspace_evidence: 'Authorized workspace evidence could materially improve this answer.',
    cross_source_evidence: 'Workspace and public evidence could materially improve completeness.',
    document_analysis: 'Structured document analysis could materially improve the findings.',
    document_comparison: 'A document comparison could materially improve the result.',
    visual_output: 'A visual output would materially help with this request.',
    specialized_authorized_agent: 'A specialized authorized agent could materially improve this answer.',
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
            effectiveCapabilityIds: Array.isArray(option?.effective_capability_ids)
                ? option.effective_capability_ids.map(normalizeIdentifier).filter(Boolean).slice(0, 8)
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
        selectedContextLabels: Array.isArray(proposal.selected_context_labels)
            ? proposal.selected_context_labels
                .map(label => String(label || '').trim().slice(0, 120))
                .filter(Boolean)
                .slice(0, 8)
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

function normalizeClassLabel(value, labels) {
    const normalizedValue = normalizeIdentifier(value).toLowerCase();
    if (!normalizedValue) {
        return '';
    }
    return labels[normalizedValue]
        || normalizedValue.replaceAll('_', ' ').replace(/\b\w/g, character => character.toUpperCase());
}

function getOptionCapabilityLabels(option) {
    return option.effectiveCapabilityIds
        .map(capabilityId => CAPABILITY_LABELS[capabilityId])
        .filter(Boolean);
}

function getOptionDescription(option) {
    if (option.kind === 'agent') {
        const scope = option.scopeClass
            ? `${normalizeClassLabel(option.scopeClass, {})} governed agent`
            : 'Governed specialized agent';
        return `${scope} for the requested evidence.`;
    }
    const effectiveIds = new Set(option.effectiveCapabilityIds);
    if (effectiveIds.has('deep_research') && effectiveIds.has('web_search')) {
        return 'Exhaustive archive research with supporting current web search.';
    }
    if (effectiveIds.has('workspace_search') && effectiveIds.has('web_search')) {
        return 'Search authorized workspace knowledge and current public sources together.';
    }
    if (option.effectiveCapabilityIds.length > 1) {
        return 'Run the included governed capabilities together for broader evidence coverage.';
    }
    const primaryCapabilityId = option.capabilityIds[0] || option.effectiveCapabilityIds[0];
    return CAPABILITY_DESCRIPTIONS[primaryCapabilityId]
        || 'Use this governed capability to improve the response.';
}

function getOptionIconClass(option) {
    if (option.kind === 'agent') {
        return 'bi-robot';
    }
    const primaryCapabilityId = option.capabilityIds[0] || option.effectiveCapabilityIds[0];
    return CAPABILITY_ICONS[primaryCapabilityId] || 'bi-stars';
}

function appendOptionSummary(container, option) {
    const summary = createElement('span', 'sc-capability-choice-option-summary');
    summary.dataset.testid = 'capability-option-summary';
    const latencyLabel = normalizeClassLabel(option.latencyClass, LATENCY_LABELS);
    const costLabel = normalizeClassLabel(option.costClass, COST_LABELS);

    if (latencyLabel) {
        const latency = createElement('span', 'sc-capability-choice-option-summary-item');
        const icon = createElement('i', 'bi bi-clock');
        icon.setAttribute('aria-hidden', 'true');
        latency.appendChild(icon);
        latency.appendChild(createElement('span', '', latencyLabel));
        summary.appendChild(latency);
    }
    if (costLabel) {
        const cost = createElement('span', 'sc-capability-choice-option-summary-item');
        const icon = createElement('i', 'bi bi-box-seam');
        icon.setAttribute('aria-hidden', 'true');
        cost.appendChild(icon);
        cost.appendChild(createElement('span', '', costLabel));
        summary.appendChild(cost);
    }
    if (summary.childElementCount > 0) {
        container.appendChild(summary);
    }
}

function appendCapabilityChecklist(container, option) {
    if (option.kind !== 'capability') {
        return;
    }
    const labels = getOptionCapabilityLabels(option);
    if (labels.length < 2) {
        return;
    }
    const includes = createElement('div', 'sc-capability-choice-includes');
    includes.dataset.testid = 'capability-option-includes';
    includes.appendChild(createElement('span', 'sc-capability-choice-includes-label', 'Includes'));
    const list = createElement('ul', 'sc-capability-choice-includes-list');
    labels.forEach(label => {
        const item = createElement('li', 'sc-capability-choice-includes-item');
        const check = createElement('i', 'bi bi-check2');
        check.setAttribute('aria-hidden', 'true');
        item.appendChild(check);
        item.appendChild(createElement('span', '', label));
        list.appendChild(item);
    });
    includes.appendChild(list);
    container.appendChild(includes);
}

function appendSelectedContext(card, proposal) {
    if (proposal.selectedContextLabels.length === 0) {
        return;
    }
    const context = createElement(
        'div',
        'sc-capability-choice-selected-context',
        `Already included: ${proposal.selectedContextLabels.join(', ')}`,
    );
    context.dataset.testid = 'capability-selected-context';
    card.appendChild(context);
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

function getCompactOptionDetail(option) {
    if (option.id === CONTINUE_OPTION_ID) {
        return '';
    }
    const capabilityLabels = getOptionCapabilityLabels(option);
    if (capabilityLabels.length > 1) {
        return `Includes ${capabilityLabels.join(' + ')}`;
    }
    if (option.kind === 'agent') {
        return getOptionDescription(option);
    }
    return '';
}

function renderCompactSelection(
    card,
    option,
    statusElement,
    {
        state = 'completed',
        statusMessage = '',
        actionLabel = '',
        onAction = null,
    } = {},
) {
    const stateConfig = {
        completed: { label: 'Completed', tone: 'success', icon: 'bi-check-circle-fill' },
        failed: { label: 'Needs attention', tone: 'warning', icon: 'bi-exclamation-circle' },
        running: { label: 'Running...', tone: 'primary', icon: 'bi-arrow-repeat' },
        saved: { label: 'Saved', tone: 'muted', icon: 'bi-check-circle' },
    }[state] || { label: 'Saved', tone: 'muted', icon: 'bi-check-circle' };

    card.replaceChildren();
    card.classList.add('is-compact');

    const summary = createElement('div', 'sc-capability-choice-compact-summary');
    summary.dataset.testid = 'capability-choice-compact-summary';
    const icon = createElement('i', `bi ${getOptionIconClass(option)} sc-capability-choice-compact-icon`);
    icon.setAttribute('aria-hidden', 'true');
    summary.appendChild(icon);

    const copy = createElement('div', 'sc-capability-choice-compact-copy');
    const label = createElement('span', 'sc-capability-choice-compact-label', option.label);
    label.id = `${statusElement.id}-selection`;
    copy.appendChild(label);
    const detailText = getCompactOptionDetail(option);
    if (detailText) {
        copy.appendChild(createElement('span', 'sc-capability-choice-compact-detail', detailText));
    }
    summary.appendChild(copy);
    card.setAttribute('aria-labelledby', label.id);

    const trailing = createElement('div', 'sc-capability-choice-compact-trailing');
    const stateIndicator = createElement(
        'span',
        `sc-capability-choice-compact-state text-${stateConfig.tone}`,
    );
    stateIndicator.dataset.testid = 'capability-choice-compact-state';
    const stateIcon = createElement('i', `bi ${stateConfig.icon}`);
    stateIcon.setAttribute('aria-hidden', 'true');
    stateIndicator.appendChild(stateIcon);
    stateIndicator.appendChild(createElement('span', '', stateConfig.label));
    trailing.appendChild(stateIndicator);

    if (actionLabel && typeof onAction === 'function') {
        summary.classList.add('has-action');
        const actionButton = createElement(
            'button',
            'btn btn-sm btn-outline-primary sc-capability-choice-compact-action',
            actionLabel,
        );
        actionButton.type = 'button';
        actionButton.setAttribute('aria-describedby', statusElement.id);
        actionButton.addEventListener('click', onAction);
        trailing.appendChild(actionButton);
    }
    summary.appendChild(trailing);
    card.appendChild(summary);

    updateStatus(statusElement, statusMessage || stateConfig.label, stateConfig.tone);
    statusElement.classList.add('visually-hidden');
    card.appendChild(statusElement);
}

async function submitDecision(card, proposal, option, statusElement, onResume) {
    if (card.dataset.submitting === 'true') {
        return;
    }
    let decisionSaved = false;
    card.querySelectorAll('.sc-capability-choice-option-card').forEach(optionCard => {
        const isSelected = optionCard.dataset.optionId === option.id;
        optionCard.classList.toggle('is-selected', isSelected);
    });
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
        decisionSaved = true;
        renderCompactSelection(card, option, statusElement, {
            state: 'running',
            statusMessage: option.id === CONTINUE_OPTION_ID
                ? 'Continuing without additional capabilities...'
                : `Approved ${option.label}. Resuming...`,
        });
        if (typeof onResume !== 'function') {
            throw new Error('Chat resume is not available. Refresh this conversation to continue.');
        }
        await onResume({
            conversationId: proposal.conversationId,
            proposalId: proposal.proposalId,
            endpoint: result.resume_endpoint || '/api/chat/stream',
        });
        setCardBusy(card, false);
        renderCompactSelection(card, option, statusElement, {
            state: 'completed',
            statusMessage: option.id === CONTINUE_OPTION_ID
                ? 'Completed without additional capabilities.'
                : `Completed with ${option.label}.`,
        });
    } catch (error) {
        setCardBusy(card, false);
        if (decisionSaved) {
            renderCompactSelection(card, option, statusElement, {
                state: 'failed',
                statusMessage: error?.message || 'The resume attempt failed.',
                actionLabel: 'Retry resume',
                onAction: () => {
                    void submitDecision(card, proposal, option, statusElement, onResume);
                },
            });
            return;
        }
        updateStatus(
            statusElement,
            error?.message || 'Your capability choice could not be saved.',
            'danger',
        );
    }
}

function renderPendingOptions(card, proposal, actions, statusElement, onResume) {
    const optionGrid = createElement('div', 'sc-capability-choice-option-grid');
    const selectableOptions = proposal.options.filter(option => option.id !== CONTINUE_OPTION_ID);
    const continueOption = proposal.options.find(option => option.id === CONTINUE_OPTION_ID);

    selectableOptions.forEach(option => {
        const isRecommended = option.id === proposal.recommendedOptionId;
        const button = createElement(
            'button',
            `sc-capability-choice-option-card${isRecommended ? ' is-recommended' : ''}`,
        );
        button.type = 'button';
        button.dataset.optionId = option.id;
        button.dataset.testid = 'capability-option-card';
        button.setAttribute('aria-describedby', statusElement.id);
        button.setAttribute(
            'aria-label',
            `${isRecommended ? 'Recommended: ' : ''}${option.label}`,
        );

        if (isRecommended) {
            const ribbon = createElement('span', 'sc-capability-choice-recommended-ribbon', 'Recommended');
            ribbon.dataset.testid = 'capability-recommended-ribbon';
            button.appendChild(ribbon);
        }

        const heading = createElement('span', 'sc-capability-choice-option-heading');
        const selectionMarker = createElement(
            'span',
            `sc-capability-choice-selection-marker${option.effectiveCapabilityIds.length > 1 ? ' is-combined' : ''}`,
        );
        selectionMarker.setAttribute('aria-hidden', 'true');
        selectionMarker.appendChild(createElement('i', 'bi bi-check2'));
        heading.appendChild(selectionMarker);
        const optionIcon = createElement('i', `bi ${getOptionIconClass(option)} sc-capability-choice-option-icon`);
        optionIcon.setAttribute('aria-hidden', 'true');
        heading.appendChild(optionIcon);
        heading.appendChild(createElement('span', 'sc-capability-choice-option-label', option.label));
        button.appendChild(heading);

        const description = createElement(
            'span',
            'sc-capability-choice-option-description',
            getOptionDescription(option),
        );
        description.dataset.testid = 'capability-option-description';
        button.appendChild(description);
        appendCapabilityChecklist(button, option);
        appendOptionSummary(button, option);
        button.addEventListener('click', () => {
            void submitDecision(card, proposal, option, statusElement, onResume);
        });
        optionGrid.appendChild(button);
    });
    actions.appendChild(optionGrid);

    if (continueOption) {
        const continueButton = createElement(
            'button',
            'btn btn-link sc-capability-choice-continue',
        );
        continueButton.type = 'button';
        continueButton.dataset.optionId = continueOption.id;
        continueButton.setAttribute('aria-describedby', statusElement.id);
        continueButton.appendChild(createElement('span', '', continueOption.label));
        const arrow = createElement('i', 'bi bi-arrow-right ms-2');
        arrow.setAttribute('aria-hidden', 'true');
        continueButton.appendChild(arrow);
        continueButton.addEventListener('click', () => {
            void submitDecision(card, proposal, continueOption, statusElement, onResume);
        });
        actions.appendChild(continueButton);
    }
}

function renderResolvedAction(card, proposal, statusElement, onResume) {
    const selectedOption = proposal.options.find(option => option.id === proposal.decision?.optionId);
    const selectedLabel = selectedOption?.label || 'saved choice';
    if (!selectedOption) {
        updateStatus(statusElement, 'This capability choice is no longer available.', 'danger');
        return false;
    }
    if (proposal.resume.status === 'completed') {
        renderCompactSelection(card, selectedOption, statusElement, {
            state: 'completed',
            statusMessage: selectedOption.id === CONTINUE_OPTION_ID
                ? 'Completed without additional capabilities.'
                : `Completed with ${selectedLabel}.`,
        });
        return true;
    }
    if (proposal.resume.status === 'running') {
        renderCompactSelection(card, selectedOption, statusElement, {
            state: 'running',
            statusMessage: `Resuming with ${selectedLabel}...`,
        });
        return true;
    }
    const resumeFailed = proposal.resume.status === 'failed';
    renderCompactSelection(card, selectedOption, statusElement, {
        state: resumeFailed ? 'failed' : 'saved',
        statusMessage: resumeFailed
            ? `The previous resume attempt failed. ${selectedLabel} remains approved for this turn.`
            : `${selectedLabel} is saved and ready to resume.`,
        actionLabel: resumeFailed ? 'Retry resume' : 'Resume',
        onAction: () => {
            void submitDecision(card, proposal, selectedOption, statusElement, onResume);
        },
    });
    return true;
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
    const title = createElement('h3', 'sc-capability-choice-title', 'How would you like to continue?');
    title.id = titleId;
    header.appendChild(title);
    card.appendChild(header);
    card.appendChild(createElement('p', 'sc-capability-choice-reason', getReasonText(proposal)));
    appendSelectedContext(card, proposal);

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
    let compactSelectionRendered = false;
    if (proposal.status === 'pending' && proposal.expired) {
        updateStatus(statusElement, 'This capability choice has expired.', 'muted');
    } else if (proposal.status === 'pending') {
        renderPendingOptions(card, proposal, actions, statusElement, onResume);
    } else if (proposal.status === 'approved' || proposal.status === 'declined') {
        compactSelectionRendered = renderResolvedAction(card, proposal, statusElement, onResume);
    } else {
        updateStatus(statusElement, 'This capability choice is no longer available.', 'muted');
    }
    if (!compactSelectionRendered) {
        card.appendChild(actions);
        card.appendChild(statusElement);
    }
    messageText.insertAdjacentElement('afterend', card);
}