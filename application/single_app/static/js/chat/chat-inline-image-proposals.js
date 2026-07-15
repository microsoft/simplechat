// chat-inline-image-proposals.js

const INLINE_IMAGE_PROPOSAL_LANGUAGE = 'simpleimage';
const INLINE_IMAGE_PROPOSAL_REGEX = new RegExp(`\`\`\`${INLINE_IMAGE_PROPOSAL_LANGUAGE}\\s*([\\s\\S]*?)\`\`\``, 'gi');
const INLINE_IMAGE_PROPOSAL_PENDING_REGEX = new RegExp(`\`\`\`${INLINE_IMAGE_PROPOSAL_LANGUAGE}\\b[\\s\\S]*$`, 'i');
const IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000;
const IMAGE_PROPOSAL_TEXT_MAX_LENGTH = 600;
const IMAGE_PROPOSAL_METADATA_ID_MAX_LENGTH = 160;
const IMAGE_PROPOSAL_METADATA_MAX_ITEMS = 24;
const IMAGE_PROPOSAL_TOKEN_PREFIX = '@@SC_INLINE_IMAGE_PROPOSAL_';
const IMAGE_PROPOSAL_SOURCE_LABELS = Object.freeze({
    assigned_knowledge: 'Assigned Knowledge',
    conversation_documents: 'Conversation Documents',
    conversation_history: 'Conversation History',
    deep_research: 'Deep Research',
    document_action: 'Selected Action',
    prior_citations: 'Prior Citations',
    selected_action: 'Selected Action',
    selected_agent: 'Selected Agent',
    selected_documents: 'Selected Documents',
    selected_image: 'Selected Image',
    selected_images: 'Selected Image',
    source_review: 'Source Review',
    user_message: 'User Provided',
    web_search: 'Web Search',
    workspace_search: 'Workspace Search',
});
const imageProposalQueue = [];
const imageProposalQueuePromises = new WeakMap();
let imageProposalQueueActive = false;

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]
    ));
}

function replaceAllOccurrences(value, searchValue, replacementValue) {
    return String(value ?? '').split(searchValue).join(replacementValue);
}

function sanitizeText(value, maxLength = IMAGE_PROPOSAL_TEXT_MAX_LENGTH) {
    return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function sanitizePrompt(value) {
    return String(value ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim().slice(0, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH);
}

function sanitizeVisualId(value) {
    return sanitizeText(value, 120).replace(/[^a-zA-Z0-9_.-]+/g, '_').replace(/^[_\-.]+|[_\-.]+$/g, '');
}

function sanitizeMetadataId(value) {
    return sanitizeText(value, IMAGE_PROPOSAL_METADATA_ID_MAX_LENGTH)
        .replace(/[^a-zA-Z0-9_.:-]+/g, '_')
        .replace(/^[_.:-]+|[_.:-]+$/g, '');
}

function sanitizeMetadataList(values, sanitizer) {
    if (!Array.isArray(values)) {
        return [];
    }

    const normalizedValues = [];
    values.forEach(value => {
        const normalizedValue = sanitizer(value);
        if (normalizedValue && !normalizedValues.includes(normalizedValue)) {
            normalizedValues.push(normalizedValue);
        }
    });
    return normalizedValues.slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS);
}

function sanitizeImageSource(value) {
    const imageSource = String(value ?? '').trim();
    if (!imageSource || imageSource === 'null') {
        return '';
    }

    const lowerSource = imageSource.toLowerCase();
    if (
        lowerSource.startsWith('/api/image/')
        || lowerSource.startsWith('data:image/')
        || lowerSource.startsWith('https://')
        || lowerSource.startsWith('http://')
    ) {
        return imageSource;
    }

    return '';
}

function createElement(tagName, className = '', textContent = '') {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    if (textContent !== '') {
        element.textContent = textContent;
    }
    return element;
}

function getObjectEntries(value) {
    return Array.isArray(value) ? value.filter(entry => entry && typeof entry === 'object') : [];
}

function getEvidenceSourceLabel(sourceType) {
    const normalizedType = sanitizeMetadataId(sourceType).toLowerCase();
    if (IMAGE_PROPOSAL_SOURCE_LABELS[normalizedType]) {
        return IMAGE_PROPOSAL_SOURCE_LABELS[normalizedType];
    }
    return sanitizeText(normalizedType.replaceAll('_', ' ').replace(/\b\w/g, character => character.toUpperCase()), 80)
        || 'Evidence Source';
}

function getEvidenceEntrySourceIds(entry) {
    const sourceIds = sanitizeMetadataList(entry?.source_ids, sanitizeMetadataId);
    const sourceId = sanitizeMetadataId(entry?.source_id);
    if (sourceId && !sourceIds.includes(sourceId)) {
        sourceIds.push(sourceId);
    }
    return sourceIds;
}

function normalizeApprovalReview(rawReview) {
    if (!rawReview || typeof rawReview !== 'object' || Array.isArray(rawReview)) {
        return null;
    }

    const state = ['ready', 'confirmation_required', 'blocked'].includes(rawReview.state)
        ? rawReview.state
        : 'blocked';
    const sources = getObjectEntries(rawReview.sources).slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS).map(source => ({
        id: sanitizeMetadataId(source.id),
        type: sanitizeMetadataId(source.type).toLowerCase() || 'evidence_source',
        label: getEvidenceSourceLabel(source.type),
        status: sanitizeMetadataId(source.status).toLowerCase() || 'unknown',
        required: Boolean(source.required),
        used: Boolean(source.used),
    }));
    const referenceImages = getObjectEntries(rawReview.reference_images || rawReview.referenceImages)
        .slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS)
        .map(reference => ({
            id: sanitizeMetadataId(reference.id),
            name: sanitizeText(reference.name, 160) || 'Selected image',
            referenceId: sanitizeMetadataId(reference.reference_id || reference.referenceId),
            documentId: sanitizeMetadataId(reference.document_id || reference.documentId),
            messageId: sanitizeMetadataId(reference.message_id || reference.messageId),
        }));

    return {
        version: 1,
        state,
        canApprove: state !== 'blocked',
        requiresConfirmation: state === 'confirmation_required',
        ledgerStatus: sanitizeMetadataId(rawReview.ledger_status || rawReview.ledgerStatus).toLowerCase() || 'unavailable',
        runtimeStatus: sanitizeMetadataId(rawReview.runtime_status || rawReview.runtimeStatus).toLowerCase() || 'unavailable',
        message: sanitizeText(rawReview.message) || 'Review the image proposal before generation.',
        sources,
        missingEvidence: sanitizeMetadataList(
            rawReview.missing_evidence || rawReview.missingEvidence,
            value => sanitizeText(value),
        ),
        referenceImages,
    };
}

function buildImageProposalApprovalReview(messageElement, spec) {
    const metadata = messageElement?.__simpleChatImageProposalReviewMetadata;
    const explicitReview = normalizeApprovalReview(metadata?.image_proposal_approval_review);
    if (explicitReview) {
        return explicitReview;
    }

    const ledger = metadata?.evidence_ledger;
    const runtime = metadata?.orchestration_runtime;
    if (!ledger || typeof ledger !== 'object' || Array.isArray(ledger)) {
        const isStreaming = messageElement?.dataset?.messageComplete === 'false';
        return {
            version: 1,
            state: isStreaming ? 'blocked' : 'ready',
            canApprove: !isStreaming,
            requiresConfirmation: false,
            ledgerStatus: 'unavailable',
            runtimeStatus: 'unavailable',
            message: isStreaming
                ? 'Evidence review is still in progress.'
                : 'Review the image proposal before generation.',
            sources: [],
            missingEvidence: [],
            referenceImages: [],
        };
    }

    const ledgerStatus = sanitizeMetadataId(ledger.status).toLowerCase() || 'unknown';
    const runtimeStatus = sanitizeMetadataId(runtime?.status).toLowerCase() || 'unavailable';
    const requirements = getObjectEntries(ledger.requirements);
    const sources = getObjectEntries(ledger.sources);
    const retainedEvidenceIds = new Set(sanitizeMetadataList(spec.evidenceIds, sanitizeMetadataId));
    const retainedReferenceIds = new Set(sanitizeMetadataList(spec.referenceImageIds, sanitizeMetadataId));
    const selectedEntryIds = new Set([...retainedEvidenceIds, ...retainedReferenceIds]);
    const supportedEntries = [
        ...getObjectEntries(ledger.facts),
        ...getObjectEntries(ledger.citations),
        ...getObjectEntries(ledger.artifacts),
        ...getObjectEntries(ledger.results).filter(entry => ['succeeded', 'partial'].includes(entry.status)),
    ];
    const usedSourceIds = new Set();
    supportedEntries.forEach(entry => {
        const entryId = sanitizeMetadataId(entry.id);
        if (selectedEntryIds.size === 0 || !selectedEntryIds.has(entryId)) {
            return;
        }
        getEvidenceEntrySourceIds(entry).forEach(sourceId => usedSourceIds.add(sourceId));
    });

    const sourceSummaries = sources.slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS).map(source => {
        const sourceId = sanitizeMetadataId(source.id);
        const sourceType = sanitizeMetadataId(source.type).toLowerCase() || 'evidence_source';
        return {
            id: sourceId,
            type: sourceType,
            label: getEvidenceSourceLabel(sourceType),
            status: sanitizeMetadataId(source.status).toLowerCase() || 'unknown',
            required: Boolean(source.required),
            used: usedSourceIds.has(sourceId),
        };
    });

    const missingEvidence = [];
    getObjectEntries(ledger.missing_or_failed).forEach(gap => {
        const message = sanitizeText(gap.message);
        if (message && !missingEvidence.includes(message)) {
            missingEvidence.push(message);
        }
    });
    requirements.forEach(requirement => {
        const requirementStatus = sanitizeMetadataId(requirement.status).toLowerCase();
        const description = sanitizeText(requirement.description);
        if (
            ['pending', 'partial', 'unsatisfied'].includes(requirementStatus)
            && description
            && !missingEvidence.includes(description)
        ) {
            missingEvidence.push(description);
        }
    });

    const referenceImages = getObjectEntries(ledger.artifacts)
        .filter(artifact => artifact.type === 'image_reference')
        .filter(artifact => retainedReferenceIds.has(sanitizeMetadataId(artifact.id)))
        .slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS)
        .map(artifact => ({
            id: sanitizeMetadataId(artifact.id),
            name: sanitizeText(artifact.name, 160) || 'Selected image',
            referenceId: sanitizeMetadataId(artifact.reference),
            documentId: sanitizeMetadataId(artifact.document_id),
            messageId: sanitizeMetadataId(artifact.message_id),
        }));

    const blockingReasons = [];
    const confirmationReasons = [];
    if (['collecting', 'pending', 'running'].includes(ledgerStatus)) {
        blockingReasons.push('Evidence collection is still in progress.');
    } else if (ledgerStatus === 'cancelled') {
        blockingReasons.push('The evidence review was cancelled.');
    } else if (!['ready', 'partial', 'completed'].includes(ledgerStatus)) {
        blockingReasons.push('The evidence review did not complete successfully.');
    }

    if (['pending', 'running'].includes(runtimeStatus)) {
        blockingReasons.push('The orchestration workflow is still running.');
    } else if (runtimeStatus === 'cancelled') {
        blockingReasons.push('The orchestration workflow was cancelled.');
    } else if (runtimeStatus === 'failed') {
        blockingReasons.push('The orchestration workflow failed.');
    } else if (!['unavailable', 'succeeded', 'partial'].includes(runtimeStatus)) {
        blockingReasons.push('The orchestration workflow is not ready for approval.');
    }

    const requiredPending = requirements.some(requirement => (
        Boolean(requirement.required) && sanitizeMetadataId(requirement.status).toLowerCase() === 'pending'
    ));
    if (requiredPending) {
        blockingReasons.push('Required evidence is still pending.');
    }

    const requiredCancelled = sources.some(source => (
        Boolean(source.required) && sanitizeMetadataId(source.status).toLowerCase() === 'cancelled'
    ));
    if (requiredCancelled) {
        blockingReasons.push('A required evidence source was cancelled.');
    }

    const requiredIncomplete = requirements.some(requirement => (
        Boolean(requirement.required)
        && ['partial', 'unsatisfied'].includes(sanitizeMetadataId(requirement.status).toLowerCase())
    ));
    if (ledgerStatus === 'partial' || runtimeStatus === 'partial' || requiredIncomplete) {
        if (
            supportedEntries.length > 0
            && ['ready', 'partial', 'completed'].includes(ledgerStatus)
            && blockingReasons.length === 0
        ) {
            confirmationReasons.push('Some requested evidence was not available. Review the missing evidence before continuing.');
        } else if (blockingReasons.length === 0) {
            blockingReasons.push('Required evidence is incomplete and cannot be approved.');
        }
    }

    const state = blockingReasons.length > 0
        ? 'blocked'
        : confirmationReasons.length > 0
            ? 'confirmation_required'
            : 'ready';
    return {
        version: 1,
        state,
        canApprove: state !== 'blocked',
        requiresConfirmation: state === 'confirmation_required',
        ledgerStatus,
        runtimeStatus,
        message: blockingReasons[0]
            || confirmationReasons[0]
            || 'Evidence review complete. Review the image proposal before generation.',
        sources: sourceSummaries,
        missingEvidence: missingEvidence.slice(0, IMAGE_PROPOSAL_METADATA_MAX_ITEMS),
        referenceImages,
    };
}

function getImageProposalApprovalReview(container, spec) {
    if (container.__simpleChatImageProposalApprovalReview) {
        return container.__simpleChatImageProposalApprovalReview;
    }
    return buildImageProposalApprovalReview(container.closest('.message'), spec);
}

function parseImageProposalPayload(payloadText) {
    const trimmed = String(payloadText ?? '').trim();
    if (!trimmed) {
        return null;
    }

    try {
        return JSON.parse(trimmed);
    } catch (error) {
        console.warn('Failed to parse inline image proposal JSON:', error);
        return null;
    }
}

function normalizeImageProposalSpec(rawSpec) {
    if (!rawSpec || typeof rawSpec !== 'object' || Array.isArray(rawSpec)) {
        return null;
    }

    const prompt = sanitizePrompt(rawSpec.prompt);
    if (!prompt) {
        return null;
    }

    const spec = {
        version: 1,
        visualId: sanitizeVisualId(rawSpec.visualId || rawSpec.visual_id),
        title: sanitizeText(rawSpec.title, 160) || 'Generate image',
        description: sanitizeText(rawSpec.description),
        prompt,
        visualType: sanitizeText(rawSpec.visualType || rawSpec.visual_type, 80),
        context: sanitizeText(rawSpec.context),
    };

    const slideNumber = rawSpec.slideNumber ?? rawSpec.slide_number;
    if (slideNumber !== undefined && slideNumber !== null && String(slideNumber).trim() !== '') {
        const numericSlide = Number(slideNumber);
        spec.slideNumber = Number.isFinite(numericSlide)
            ? numericSlide
            : sanitizeText(slideNumber, 40);
    }

    const evidenceIds = sanitizeMetadataList(
        rawSpec.evidenceIds || rawSpec.evidence_ids,
        sanitizeMetadataId,
    );
    if (evidenceIds.length > 0) {
        spec.evidenceIds = evidenceIds;
    }

    const sourceSummary = sanitizeText(rawSpec.sourceSummary || rawSpec.source_summary);
    if (sourceSummary) {
        spec.sourceSummary = sourceSummary;
    }

    const missingEvidence = sanitizeMetadataList(
        rawSpec.missingEvidence || rawSpec.missing_evidence,
        value => sanitizeText(value),
    );
    if (missingEvidence.length > 0) {
        spec.missingEvidence = missingEvidence;
    }

    const referenceImageIds = sanitizeMetadataList(
        rawSpec.referenceImageIds || rawSpec.reference_image_ids,
        sanitizeMetadataId,
    );
    if (referenceImageIds.length > 0) {
        spec.referenceImageIds = referenceImageIds;
    }

    return spec;
}

function createImageProposalToken(blocks, block) {
    const token = `${IMAGE_PROPOSAL_TOKEN_PREFIX}${blocks.length}@@`;
    blocks.push({ ...block, token });
    return token;
}

function buildPlaceholderHtml(block, index) {
    const encodedSpec = encodeURIComponent(JSON.stringify(block.spec));
    return `<section class="sc-inline-image-proposal my-3" data-image-proposal-index="${index}" data-image-proposal-spec="${escapeHtml(encodedSpec)}" data-image-proposal-state="pending" data-image-proposal-hydrated="false"></section>`;
}

function buildStatusPlaceholderHtml(block, index) {
    const title = block.pending ? 'Preparing image...' : 'Image proposal unavailable';
    const detail = block.pending
        ? 'Image proposal is still streaming.'
        : sanitizeText(block.error || 'The image proposal could not be rendered.', 180);

    return `
        <section class="sc-inline-image-proposal sc-inline-image-proposal-status card border-0 shadow-sm my-3" data-image-proposal-index="${index}" data-image-proposal-state="status" data-image-proposal-hydrated="status" aria-label="Inline image proposal ${index + 1}">
            <div class="card-body p-3">
                <div class="d-flex align-items-start gap-2">
                    <i class="bi bi-image text-primary mt-1" aria-hidden="true"></i>
                    <div class="min-w-0">
                        <div class="fw-semibold sc-inline-image-proposal-status-title">${escapeHtml(title)}</div>
                        <div class="small text-muted mt-1 sc-inline-image-proposal-status-text">${escapeHtml(detail)}</div>
                    </div>
                </div>
            </div>
        </section>
    `;
}

function decodeContainerSpec(container) {
    const encodedSpec = container.getAttribute('data-image-proposal-spec');
    if (!encodedSpec) {
        return null;
    }

    try {
        return normalizeImageProposalSpec(JSON.parse(decodeURIComponent(encodedSpec)));
    } catch (error) {
        console.warn('Failed to decode inline image proposal spec:', error);
        return null;
    }
}

function getConversationId(container) {
    const messageElement = container.closest('.message');
    const messageConversationId = messageElement?.dataset?.conversationId;
    if (messageConversationId) {
        return messageConversationId;
    }

    if (window.chatConversations && typeof window.chatConversations.getCurrentConversationId === 'function') {
        return window.chatConversations.getCurrentConversationId();
    }

    return window.currentConversationId || '';
}

function getAssistantMessageId(container) {
    return container.closest('.message')?.getAttribute('data-message-id') || '';
}

function getImageProposalMetadata(imageMessage) {
    if (!imageMessage || typeof imageMessage !== 'object') {
        return null;
    }

    const metadata = imageMessage.metadata && typeof imageMessage.metadata === 'object'
        ? imageMessage.metadata
        : {};
    const proposalMetadata = metadata.image_proposal && typeof metadata.image_proposal === 'object'
        ? metadata.image_proposal
        : imageMessage.image_proposal;

    return proposalMetadata && typeof proposalMetadata === 'object' ? proposalMetadata : null;
}

function normalizeGeneratedImageResult(imageResult) {
    if (!imageResult || typeof imageResult !== 'object') {
        return null;
    }

    const imageMessage = imageResult.image_message && typeof imageResult.image_message === 'object'
        ? imageResult.image_message
        : imageResult;
    const imageUrl = sanitizeImageSource(imageResult.image_url || imageMessage.content);
    if (!imageUrl) {
        return null;
    }

    return {
        image_url: imageUrl,
        message_id: imageResult.message_id || imageMessage.id || '',
        model_deployment_name: imageResult.model_deployment_name || imageMessage.model_deployment_name || '',
        image_message: {
            ...imageMessage,
            content: imageUrl,
        },
        image_proposal: getImageProposalMetadata(imageMessage) || getImageProposalMetadata(imageResult),
    };
}

function normalizeGeneratedImageResults(imageResults) {
    return (Array.isArray(imageResults) ? imageResults : [])
        .map(normalizeGeneratedImageResult)
        .filter(Boolean);
}

function getMessageGeneratedImageResults(container) {
    const messageElement = container.closest('.message');
    if (!messageElement) {
        return [];
    }

    return Array.isArray(messageElement.__simpleChatGeneratedImageProposals)
        ? messageElement.__simpleChatGeneratedImageProposals
        : [];
}

function findGeneratedImageResultForSpec(container, spec) {
    const normalizedVisualId = sanitizeVisualId(spec?.visualId || '');
    const title = sanitizeText(spec?.title || '', 160).toLowerCase();
    const prompt = sanitizePrompt(spec?.prompt || '');

    return getMessageGeneratedImageResults(container).find(imageResult => {
        const proposal = imageResult.image_proposal || {};
        const proposalVisualId = sanitizeVisualId(proposal.visualId || proposal.visual_id || '');
        if (normalizedVisualId && proposalVisualId && normalizedVisualId === proposalVisualId) {
            return true;
        }

        const proposalTitle = sanitizeText(proposal.title || '', 160).toLowerCase();
        if (title && proposalTitle && title === proposalTitle) {
            return true;
        }

        const proposalPrompt = sanitizePrompt(proposal.prompt || '');
        return Boolean(prompt && proposalPrompt && prompt === proposalPrompt);
    });
}

function setButtonLoading(button, isLoading, loadingText = 'Generating') {
    if (!button) {
        return;
    }

    button.disabled = isLoading;
    if (isLoading) {
        button.dataset.originalText = button.textContent;
        button.replaceChildren();
        const spinner = createElement('span', 'spinner-border spinner-border-sm me-2');
        spinner.setAttribute('aria-hidden', 'true');
        button.appendChild(spinner);
        button.appendChild(document.createTextNode(loadingText));
        return;
    }

    button.textContent = button.dataset.originalText || 'Approve';
}

function setCardState(container, state, message = '') {
    container.setAttribute('data-image-proposal-state', state);
    const statusElement = container.querySelector('.sc-inline-image-proposal-status-text');
    if (statusElement) {
        statusElement.textContent = message;
        statusElement.classList.toggle('d-none', !message);
    }
}

function reenableProposalControls(container) {
    container.querySelectorAll('button, textarea, input').forEach(control => {
        control.disabled = false;
    });
    setButtonLoading(container.querySelector('.sc-inline-image-proposal-approve'), false);
    syncApprovalControls(container);
}

function renderGeneratedImageResult(container, spec, imageResult) {
    const normalizedResult = normalizeGeneratedImageResult(imageResult);
    if (!normalizedResult) {
        return false;
    }

    container.replaceChildren();
    container.setAttribute('data-image-proposal-state', 'approved');
    container.setAttribute('data-image-proposal-hydrated', 'true');
    container.classList.add('sc-inline-image-proposal-approved');

    const card = createElement('div', 'sc-inline-image-proposal-card card border-0 shadow-sm');
    const cardBody = createElement('div', 'card-body p-3');
    const header = createElement('div', 'd-flex align-items-start gap-2 mb-2');
    const icon = createElement('i', 'bi bi-image text-success mt-1');
    icon.setAttribute('aria-hidden', 'true');
    const titleGroup = createElement('div', 'flex-grow-1 min-w-0');
    const title = createElement('h6', 'mb-1 sc-inline-image-proposal-title', spec.title || 'Generated image');
    const status = createElement('div', 'small text-muted sc-inline-image-proposal-status-text', 'Image generated.');
    titleGroup.appendChild(title);
    titleGroup.appendChild(status);
    header.appendChild(icon);
    header.appendChild(titleGroup);
    cardBody.appendChild(header);

    const metaList = createProposalMetaList(spec);
    if (metaList.childElementCount > 0) {
        cardBody.appendChild(metaList);
    }

    const approvalReview = getImageProposalApprovalReview(container, spec);
    const evidenceReview = createEvidenceReviewSection(spec, approvalReview);
    if (evidenceReview) {
        cardBody.appendChild(evidenceReview);
    }

    const resultWrapper = createElement('div', 'sc-inline-image-proposal-result mt-2');
    const image = document.createElement('img');
    image.src = normalizedResult.image_url;
    image.alt = `${spec.title || 'Generated'} image`;
    image.className = 'generated-image sc-inline-image-proposal-result-image';
    image.dataset.imageSrc = normalizedResult.image_url;
    image.loading = 'lazy';
    image.addEventListener('load', () => {
        if (typeof window.scrollChatToBottom === 'function') {
            window.scrollChatToBottom();
        }
    });
    image.addEventListener('error', () => {
        image.src = '/static/images/image-error.png';
        image.alt = 'Failed to load generated image';
    }, { once: true });
    resultWrapper.appendChild(image);
    cardBody.appendChild(resultWrapper);

    if (normalizedResult.model_deployment_name) {
        const modelLabel = createElement('div', 'small text-muted mt-2 sc-inline-image-proposal-model', normalizedResult.model_deployment_name);
        cardBody.appendChild(modelLabel);
    }

    card.appendChild(cardBody);
    container.appendChild(card);
    refreshImageProposalBulkActions(container.closest('.message') || document);
    return true;
}

function rememberGeneratedImageResult(container, imageResult) {
    const messageElement = container.closest('.message');
    const normalizedResult = normalizeGeneratedImageResult(imageResult);
    if (!messageElement || !normalizedResult) {
        return normalizedResult;
    }

    const generatedResults = Array.isArray(messageElement.__simpleChatGeneratedImageProposals)
        ? messageElement.__simpleChatGeneratedImageProposals
        : [];
    if (!generatedResults.some(result => result.message_id && result.message_id === normalizedResult.message_id)) {
        generatedResults.push(normalizedResult);
    }
    messageElement.__simpleChatGeneratedImageProposals = generatedResults;
    return normalizedResult;
}

async function runImageProposalGeneration(container) {
    const spec = decodeContainerSpec(container);
    if (!spec) {
        reenableProposalControls(container);
        setCardState(container, 'error', 'The image proposal is not valid.');
        return false;
    }

    const textarea = container.querySelector('.sc-inline-image-proposal-prompt-editor');
    const prompt = sanitizePrompt(textarea?.value || spec.prompt);
    if (!prompt) {
        reenableProposalControls(container);
        setCardState(container, 'error', 'Add a prompt before generating the image.');
        textarea?.focus();
        return false;
    }

    const conversationId = getConversationId(container);
    if (!conversationId) {
        reenableProposalControls(container);
        setCardState(container, 'error', 'Open a conversation before generating the image.');
        return false;
    }

    const approvalReview = getImageProposalApprovalReview(container, spec);
    const confirmationControl = container.querySelector('.sc-inline-image-proposal-confirm-partial');
    if (approvalReview.state === 'blocked') {
        reenableProposalControls(container);
        setCardState(container, 'blocked', approvalReview.message);
        return false;
    }
    if (approvalReview.requiresConfirmation && !confirmationControl?.checked) {
        reenableProposalControls(container);
        setCardState(container, 'pending', 'Confirm that you want to continue with the available evidence.');
        confirmationControl?.focus();
        return false;
    }

    const approveButton = container.querySelector('.sc-inline-image-proposal-approve');
    const actionButtons = container.querySelectorAll('button, textarea, input');
    actionButtons.forEach(control => {
        control.disabled = true;
    });
    setButtonLoading(approveButton, true);
    setCardState(container, 'generating', 'Generating image...');

    try {
        const response = await fetch('/api/chat/image-proposals/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                conversation_id: conversationId,
                assistant_message_id: getAssistantMessageId(container),
                confirm_partial: approvalReview.requiresConfirmation && confirmationControl?.checked === true,
                proposal: {
                    ...spec,
                    prompt,
                },
            }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            const refreshedReview = normalizeApprovalReview(result.approval_review);
            if (refreshedReview) {
                container.__simpleChatImageProposalApprovalReview = refreshedReview;
                renderImageProposalCard(container, spec, refreshedReview);
                return false;
            }
            throw new Error(result.error || `Image generation failed (${response.status})`);
        }

        const normalizedResult = rememberGeneratedImageResult(container, result);
        if (!renderGeneratedImageResult(container, spec, normalizedResult)) {
            setCardState(container, 'approved', 'Image generated.');
            container.classList.add('sc-inline-image-proposal-approved');
        }
        return true;
    } catch (error) {
        console.error('Image proposal approval failed:', error);
        actionButtons.forEach(control => {
            control.disabled = false;
        });
        setButtonLoading(approveButton, false);
        setCardState(container, 'error', error.message || 'Image generation failed.');
        return false;
    }
}

function updateQueuedProposalStatuses() {
    imageProposalQueue.forEach((queueItem, index) => {
        if (queueItem.container.getAttribute('data-image-proposal-state') !== 'queued') {
            return;
        }

        const aheadCount = imageProposalQueueActive ? index + 1 : index;
        const message = aheadCount > 0
            ? `Queued. ${aheadCount} image${aheadCount === 1 ? '' : 's'} ahead.`
            : 'Queued. Starting soon...';
        setCardState(queueItem.container, 'queued', message);
    });
}

async function processImageProposalQueue() {
    if (imageProposalQueueActive) {
        updateQueuedProposalStatuses();
        return;
    }

    const nextItem = imageProposalQueue.shift();
    if (!nextItem) {
        updateQueuedProposalStatuses();
        return;
    }

    imageProposalQueueActive = true;
    updateQueuedProposalStatuses();
    try {
        const success = await runImageProposalGeneration(nextItem.container);
        nextItem.resolve(success);
    } catch (error) {
        console.error('Image proposal queue failed:', error);
        setCardState(nextItem.container, 'error', error.message || 'Image generation failed.');
        nextItem.resolve(false);
    } finally {
        imageProposalQueuePromises.delete(nextItem.container);
        imageProposalQueueActive = false;
        processImageProposalQueue();
    }
}

function approveImageProposal(container) {
    const existingPromise = imageProposalQueuePromises.get(container);
    if (existingPromise) {
        return existingPromise;
    }

    const state = container.getAttribute('data-image-proposal-state');
    if (state === 'approved' || state === 'cancelled') {
        return Promise.resolve(false);
    }

    const spec = decodeContainerSpec(container);
    const approvalReview = spec ? getImageProposalApprovalReview(container, spec) : null;
    const confirmationControl = container.querySelector('.sc-inline-image-proposal-confirm-partial');
    if (!approvalReview || approvalReview.state === 'blocked') {
        setCardState(container, 'blocked', approvalReview?.message || 'This proposal is not ready for approval.');
        syncApprovalControls(container);
        return Promise.resolve(false);
    }
    if (approvalReview.requiresConfirmation && !confirmationControl?.checked) {
        setCardState(container, 'pending', 'Confirm that you want to continue with the available evidence.');
        confirmationControl?.focus();
        syncApprovalControls(container);
        return Promise.resolve(false);
    }

    const actionButtons = container.querySelectorAll('button, textarea, input');
    actionButtons.forEach(control => {
        control.disabled = true;
    });
    setCardState(container, 'queued', imageProposalQueueActive ? 'Queued. Waiting for the current image...' : 'Queued. Starting soon...');

    const queuePromise = new Promise(resolve => {
        imageProposalQueue.push({ container, resolve });
        updateQueuedProposalStatuses();
        processImageProposalQueue();
    });
    imageProposalQueuePromises.set(container, queuePromise);
    return queuePromise;
}

function cancelImageProposal(container) {
    container.classList.add('sc-inline-image-proposal-cancelled');
    container.querySelectorAll('button, textarea, input').forEach(control => {
        control.disabled = true;
    });
    setCardState(container, 'cancelled', 'Image proposal dismissed.');
    refreshImageProposalBulkActions(container.closest('.message') || document);
}

function togglePromptEditor(container) {
    const editor = container.querySelector('.sc-inline-image-proposal-prompt-editor');
    const promptPanel = container.querySelector('.sc-inline-image-proposal-prompt-panel');
    const editButton = container.querySelector('.sc-inline-image-proposal-edit');
    if (!editor || !promptPanel || !editButton) {
        return;
    }

    const isHidden = promptPanel.classList.contains('d-none');
    promptPanel.classList.toggle('d-none', !isHidden);
    editButton.textContent = isHidden ? 'Done' : 'Edit';
    editButton.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
    if (isHidden) {
        editor.focus();
    }
}

function createProposalMetaList(spec) {
    const metaItems = [];
    if (spec.visualType) {
        metaItems.push(spec.visualType);
    }
    if (spec.slideNumber !== undefined && spec.slideNumber !== null && String(spec.slideNumber).trim() !== '') {
        metaItems.push(`Slide ${spec.slideNumber}`);
    }
    if (spec.context) {
        metaItems.push(spec.context);
    }

    const list = createElement('div', 'sc-inline-image-proposal-meta d-flex flex-wrap gap-2 mb-2');
    metaItems.forEach(item => {
        const badge = createElement('span', 'badge text-bg-light border sc-inline-image-proposal-meta-badge', item);
        list.appendChild(badge);
    });
    return list;
}

function getSourceBadgeState(source) {
    if (source.used) {
        return { className: 'text-bg-success', label: 'used' };
    }
    if (source.status === 'succeeded') {
        return { className: 'text-bg-light border', label: 'reviewed' };
    }
    if (source.status === 'partial') {
        return { className: 'text-bg-warning', label: 'partial' };
    }
    if (['planned', 'pending', 'running'].includes(source.status)) {
        return { className: 'text-bg-info', label: 'reviewing' };
    }
    return { className: 'text-bg-secondary', label: 'unavailable' };
}

function createReferenceImageTray(referenceImages) {
    const tray = createElement('div', 'sc-inline-image-proposal-reference-tray d-flex flex-wrap gap-2 mt-2');
    referenceImages.forEach(reference => {
        const figure = createElement('figure', 'sc-inline-image-proposal-reference mb-0');
        const preview = createElement('div', 'sc-inline-image-proposal-reference-preview');
        const fallback = createElement('span', 'sc-inline-image-proposal-reference-fallback d-none');
        const fallbackIcon = createElement('i', 'bi bi-image');
        fallbackIcon.setAttribute('aria-hidden', 'true');
        fallback.appendChild(fallbackIcon);

        if (reference.messageId) {
            const image = document.createElement('img');
            image.className = 'sc-inline-image-proposal-reference-image';
            image.src = `/api/image/${encodeURIComponent(reference.messageId)}`;
            image.alt = `Reference image: ${reference.name}`;
            image.loading = 'lazy';
            image.addEventListener('error', () => {
                image.classList.add('d-none');
                fallback.classList.remove('d-none');
            }, { once: true });
            preview.appendChild(image);
        } else {
            fallback.classList.remove('d-none');
        }
        preview.appendChild(fallback);
        figure.appendChild(preview);
        figure.appendChild(createElement('figcaption', 'small text-muted mt-1', reference.name));
        tray.appendChild(figure);
    });
    return tray;
}

function createEvidenceReviewSection(spec, approvalReview) {
    const missingEvidence = sanitizeMetadataList(
        [...(spec.missingEvidence || []), ...(approvalReview.missingEvidence || [])],
        value => sanitizeText(value),
    );
    const hasReviewContent = Boolean(
        spec.sourceSummary
        || spec.evidenceIds?.length
        || approvalReview.sources.length
        || missingEvidence.length
        || approvalReview.referenceImages.length
    );
    if (!hasReviewContent) {
        return null;
    }

    const section = createElement('section', 'sc-inline-image-proposal-evidence mt-3 pt-3');
    section.setAttribute('aria-label', 'Image proposal evidence review');
    section.appendChild(createElement('div', 'small fw-semibold mb-2', 'Evidence review'));

    if (approvalReview.sources.length > 0) {
        const sourceList = createElement('div', 'sc-inline-image-proposal-sources d-flex flex-wrap gap-2');
        sourceList.setAttribute('aria-label', 'Evidence sources');
        approvalReview.sources.forEach(source => {
            const badgeState = getSourceBadgeState(source);
            const badge = createElement(
                'span',
                `badge ${badgeState.className} sc-inline-image-proposal-source-badge`,
                `${source.label} · ${badgeState.label}`,
            );
            sourceList.appendChild(badge);
        });
        section.appendChild(sourceList);
    }

    if (approvalReview.referenceImages.length > 0) {
        const referenceHeading = createElement('div', 'small fw-semibold mt-3', 'Reference images');
        section.appendChild(referenceHeading);
        section.appendChild(createReferenceImageTray(approvalReview.referenceImages));
    }

    if (missingEvidence.length > 0) {
        const missingAlert = createElement('div', 'alert alert-warning py-2 px-3 mt-3 mb-0 sc-inline-image-proposal-missing');
        missingAlert.setAttribute('role', 'note');
        missingAlert.appendChild(createElement('div', 'small fw-semibold', 'Missing evidence'));
        const list = createElement('ul', 'small mb-0 mt-1 ps-3');
        missingEvidence.forEach(message => {
            list.appendChild(createElement('li', '', message));
        });
        missingAlert.appendChild(list);
        section.appendChild(missingAlert);
    }

    const details = createElement('details', 'sc-inline-image-proposal-evidence-details mt-2');
    details.appendChild(createElement('summary', 'small text-primary', 'Review evidence details'));
    const detailBody = createElement('div', 'small text-muted mt-2');
    if (spec.sourceSummary) {
        detailBody.appendChild(createElement('p', 'mb-1', spec.sourceSummary));
    }
    if (spec.evidenceIds?.length) {
        const evidenceCount = spec.evidenceIds.length;
        detailBody.appendChild(createElement(
            'p',
            'mb-0',
            `${evidenceCount} evidence record${evidenceCount === 1 ? '' : 's'} linked to this proposal.`,
        ));
    }
    details.appendChild(detailBody);
    section.appendChild(details);
    return section;
}

function createApprovalNotice(container, approvalReview, spec) {
    if (approvalReview.state === 'ready') {
        return null;
    }

    const noticeClass = approvalReview.state === 'blocked' ? 'alert-secondary' : 'alert-warning';
    const notice = createElement('div', `alert ${noticeClass} py-2 px-3 mb-2 sc-inline-image-proposal-approval-notice`);
    const index = container.getAttribute('data-image-proposal-index') || '0';
    const messageId = sanitizeVisualId(getAssistantMessageId(container)) || 'message';
    const visualId = sanitizeVisualId(spec?.visualId) || 'proposal';
    notice.id = `inline-image-proposal-notice-${messageId}-${index}-${visualId}`;
    notice.setAttribute('role', 'status');
    notice.setAttribute('aria-live', 'polite');
    notice.setAttribute('aria-atomic', 'true');
    notice.appendChild(createElement('div', 'small', approvalReview.message));
    if (!approvalReview.requiresConfirmation) {
        return notice;
    }

    const confirmation = createElement('div', 'form-check mt-2');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input sc-inline-image-proposal-confirm-partial';
    checkbox.id = `inline-image-proposal-confirm-${messageId}-${index}-${visualId}`;
    const label = createElement('label', 'form-check-label small', 'Continue using only the available evidence.');
    label.setAttribute('for', checkbox.id);
    checkbox.addEventListener('change', () => {
        syncApprovalControls(container);
        const liveStatus = container.querySelector('.sc-inline-image-proposal-approval-live');
        if (liveStatus) {
            liveStatus.textContent = checkbox.checked
                ? 'Approval is now available using the current evidence.'
                : 'Approval requires confirmation to use the current evidence.';
        }
    });
    confirmation.appendChild(checkbox);
    confirmation.appendChild(label);
    notice.appendChild(confirmation);
    return notice;
}

function syncApprovalControls(container) {
    const approveButton = container.querySelector('.sc-inline-image-proposal-approve');
    const confirmationControl = container.querySelector('.sc-inline-image-proposal-confirm-partial');
    const approvalReview = container.__simpleChatImageProposalApprovalReview;
    if (!approveButton || !approvalReview) {
        return;
    }
    approveButton.disabled = approvalReview.state === 'blocked'
        || (approvalReview.requiresConfirmation && !confirmationControl?.checked);
    approveButton.setAttribute('aria-disabled', approveButton.disabled ? 'true' : 'false');
}

function renderImageProposalCard(container, spec, providedApprovalReview = null) {
    const generatedImageResult = findGeneratedImageResultForSpec(container, spec);
    if (generatedImageResult && renderGeneratedImageResult(container, spec, generatedImageResult)) {
        return;
    }

    container.replaceChildren();
    container.setAttribute('data-image-proposal-hydrated', 'true');
    const approvalReview = providedApprovalReview || buildImageProposalApprovalReview(container.closest('.message'), spec);
    container.__simpleChatImageProposalApprovalReview = approvalReview;
    container.setAttribute('data-approval-review-state', approvalReview.state);

    const card = createElement('div', 'sc-inline-image-proposal-card card border-0 shadow-sm');
    const cardBody = createElement('div', 'card-body p-3');
    const header = createElement('div', 'd-flex align-items-start gap-2 mb-2');
    const icon = createElement('i', 'bi bi-image text-primary mt-1');
    icon.setAttribute('aria-hidden', 'true');
    const titleGroup = createElement('div', 'flex-grow-1 min-w-0');
    const title = createElement('h6', 'mb-1 sc-inline-image-proposal-title', spec.title);
    const description = createElement('p', 'mb-0 small text-muted sc-inline-image-proposal-description', spec.description);
    titleGroup.appendChild(title);
    if (spec.description) {
        titleGroup.appendChild(description);
    }
    header.appendChild(icon);
    header.appendChild(titleGroup);
    cardBody.appendChild(header);

    const metaList = createProposalMetaList(spec);
    if (metaList.childElementCount > 0) {
        cardBody.appendChild(metaList);
    }

    const evidenceReview = createEvidenceReviewSection(spec, approvalReview);
    if (evidenceReview) {
        cardBody.appendChild(evidenceReview);
    }

    const promptPanel = createElement('div', 'sc-inline-image-proposal-prompt-panel d-none mb-2');
    const promptLabel = createElement('label', 'small fw-semibold mb-1', 'Prompt');
    const promptEditor = createElement('textarea', 'sc-inline-image-proposal-prompt-editor form-control form-control-sm');
    const promptEditorId = `inline-image-proposal-prompt-${container.getAttribute('data-image-proposal-index') || '0'}-${sanitizeVisualId(spec.visualId || 'proposal') || 'proposal'}`;
    promptLabel.setAttribute('for', promptEditorId);
    promptEditor.id = promptEditorId;
    promptEditor.rows = 5;
    promptEditor.maxLength = IMAGE_PROPOSAL_PROMPT_MAX_LENGTH;
    promptEditor.value = spec.prompt;
    promptPanel.appendChild(promptLabel);
    promptPanel.appendChild(promptEditor);
    cardBody.appendChild(promptPanel);

    const status = createElement('div', 'sc-inline-image-proposal-status-text small text-muted mb-2 d-none');
    cardBody.appendChild(status);

    const approvalNotice = createApprovalNotice(container, approvalReview, spec);
    if (approvalNotice) {
        cardBody.appendChild(approvalNotice);
    }

    const actions = createElement('div', 'sc-inline-image-proposal-actions d-flex flex-wrap gap-2');
    const approveButton = createElement(
        'button',
        'btn btn-sm btn-primary sc-inline-image-proposal-approve',
        approvalReview.requiresConfirmation ? 'Approve with available evidence' : 'Approve',
    );
    approveButton.type = 'button';
    approveButton.title = 'Generate this image';
    if (approvalNotice) {
        approveButton.setAttribute('aria-describedby', approvalNotice.id);
    }
    const editButton = createElement('button', 'btn btn-sm btn-outline-secondary sc-inline-image-proposal-edit', 'Edit');
    editButton.type = 'button';
    editButton.title = 'Edit the image prompt';
    editButton.setAttribute('aria-expanded', 'false');
    const cancelButton = createElement('button', 'btn btn-sm btn-outline-secondary sc-inline-image-proposal-cancel', 'Cancel');
    cancelButton.type = 'button';
    cancelButton.title = 'Dismiss this image proposal';

    approveButton.addEventListener('click', async () => {
        await approveImageProposal(container);
        refreshImageProposalBulkActions(container.closest('.message') || document);
    });
    editButton.addEventListener('click', () => togglePromptEditor(container));
    cancelButton.addEventListener('click', () => cancelImageProposal(container));

    actions.appendChild(approveButton);
    actions.appendChild(editButton);
    actions.appendChild(cancelButton);
    const approvalLive = createElement('span', 'visually-hidden sc-inline-image-proposal-approval-live');
    approvalLive.setAttribute('role', 'status');
    approvalLive.setAttribute('aria-live', 'polite');
    approvalLive.setAttribute('aria-atomic', 'true');
    actions.appendChild(approvalLive);
    cardBody.appendChild(actions);
    card.appendChild(cardBody);
    container.appendChild(card);
    syncApprovalControls(container);
}

function getPendingProposalContainers(scopeRoot) {
    return Array.from(scopeRoot.querySelectorAll('.sc-inline-image-proposal[data-image-proposal-state="pending"]'))
        .filter(container => !container.classList.contains('sc-inline-image-proposal-status'))
        .filter(container => container.getAttribute('data-approval-review-state') === 'ready');
}

function createBulkActions(messageElement, pendingContainers) {
    const actions = createElement('div', 'sc-inline-image-proposal-bulk-actions d-flex justify-content-start mt-2');
    const approveAllButton = createElement('button', 'btn btn-sm btn-primary sc-inline-image-proposal-approve-all', 'Approve all image proposals');
    approveAllButton.type = 'button';
    approveAllButton.title = 'Generate every pending image proposal in this message';
    approveAllButton.addEventListener('click', async () => {
        approveAllButton.disabled = true;
        approveAllButton.textContent = 'Queueing images...';
        const approvalPromises = pendingContainers
            .filter(container => container.getAttribute('data-image-proposal-state') === 'pending')
            .map(container => approveImageProposal(container));
        await Promise.all(approvalPromises);
        refreshImageProposalBulkActions(messageElement);
    });
    actions.appendChild(approveAllButton);
    return actions;
}

export function refreshImageProposalBulkActions(root = document) {
    const messageElements = root.matches?.('.message') ? [root] : Array.from(root.querySelectorAll?.('.message') || []);
    messageElements.forEach(messageElement => {
        messageElement.querySelectorAll('.sc-inline-image-proposal-bulk-actions').forEach(element => element.remove());
        const pendingContainers = getPendingProposalContainers(messageElement);
        if (pendingContainers.length <= 2) {
            return;
        }

        const messageText = messageElement.querySelector('.message-text') || messageElement;
        messageText.appendChild(createBulkActions(messageElement, pendingContainers));
    });
}

export function extractInlineImageProposalBlocks(markdownText = '') {
    const blocks = [];
    let markdown = String(markdownText ?? '').replace(INLINE_IMAGE_PROPOSAL_REGEX, (match, payload) => {
        const parsed = parseImageProposalPayload(payload);
        const spec = normalizeImageProposalSpec(parsed);
        if (!spec) {
            return createImageProposalToken(blocks, {
                originalBlock: match,
                error: 'The image proposal JSON was not recognized.',
            });
        }

        return createImageProposalToken(blocks, { spec, originalBlock: match });
    });

    markdown = markdown.replace(INLINE_IMAGE_PROPOSAL_PENDING_REGEX, match => createImageProposalToken(blocks, {
        originalBlock: match,
        pending: true,
    }));

    return { markdown, blocks };
}

export function restoreInlineImageProposalTokens(markdownText = '', blocks = []) {
    let restored = String(markdownText ?? '');
    blocks.forEach(block => {
        restored = replaceAllOccurrences(restored, block.token, block.originalBlock || '');
    });
    return restored;
}

export function injectInlineImageProposalHtml(html = '', blocks = []) {
    let renderedHtml = String(html ?? '');

    blocks.forEach((block, index) => {
        const placeholderHtml = block.spec
            ? buildPlaceholderHtml(block, index)
            : buildStatusPlaceholderHtml(block, index);
        const paragraphToken = `<p>${block.token}</p>`;
        if (renderedHtml.includes(paragraphToken)) {
            renderedHtml = replaceAllOccurrences(renderedHtml, paragraphToken, placeholderHtml);
        } else {
            renderedHtml = replaceAllOccurrences(renderedHtml, block.token, placeholderHtml);
        }
    });

    return renderedHtml;
}

export function hydrateInlineImageProposals(root = document, messageMetadata = null) {
    const messageElement = root.matches?.('.message') ? root : root.closest?.('.message');
    if (messageElement && messageMetadata && typeof messageMetadata === 'object') {
        messageElement.__simpleChatImageProposalReviewMetadata = messageMetadata;
    }
    const proposalContainers = root.querySelectorAll('.sc-inline-image-proposal:not([data-image-proposal-state="status"])');
    proposalContainers.forEach(container => {
        const spec = decodeContainerSpec(container);
        if (!spec) {
            setCardState(container, 'error', 'The image proposal is not valid.');
            return;
        }

        const approvalReview = buildImageProposalApprovalReview(container.closest('.message'), spec);
        const reviewSignature = JSON.stringify(approvalReview);
        if (
            container.getAttribute('data-image-proposal-hydrated') === 'true'
            && container.querySelector('.sc-inline-image-proposal-card')
            && container.__simpleChatImageProposalApprovalReviewSignature === reviewSignature
        ) {
            container.__simpleChatImageProposalApprovalReview = approvalReview;
            return;
        }

        container.__simpleChatImageProposalApprovalReviewSignature = reviewSignature;
        renderImageProposalCard(container, spec, approvalReview);
    });

    refreshImageProposalBulkActions(root);
}

export function attachGeneratedImageProposalResults(root = document, imageResults = []) {
    const messageElement = root.matches?.('.message') ? root : root.closest?.('.message');
    if (!messageElement) {
        return;
    }

    const normalizedResults = normalizeGeneratedImageResults(imageResults);
    messageElement.__simpleChatGeneratedImageProposals = normalizedResults;
    messageElement.querySelectorAll('.sc-inline-image-proposal:not([data-image-proposal-state="status"])').forEach(container => {
        const spec = decodeContainerSpec(container);
        if (!spec) {
            return;
        }

        const generatedImageResult = findGeneratedImageResultForSpec(container, spec);
        if (generatedImageResult) {
            renderGeneratedImageResult(container, spec, generatedImageResult);
        }
    });
}
