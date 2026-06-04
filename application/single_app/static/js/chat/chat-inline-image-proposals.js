// chat-inline-image-proposals.js

const INLINE_IMAGE_PROPOSAL_LANGUAGE = 'simpleimage';
const INLINE_IMAGE_PROPOSAL_REGEX = new RegExp(`\`\`\`${INLINE_IMAGE_PROPOSAL_LANGUAGE}\\s*([\\s\\S]*?)\`\`\``, 'gi');
const INLINE_IMAGE_PROPOSAL_PENDING_REGEX = new RegExp(`\`\`\`${INLINE_IMAGE_PROPOSAL_LANGUAGE}\\b[\\s\\S]*$`, 'i');
const IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000;
const IMAGE_PROPOSAL_TEXT_MAX_LENGTH = 600;
const IMAGE_PROPOSAL_TOKEN_PREFIX = '@@SC_INLINE_IMAGE_PROPOSAL_';
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
    container.querySelectorAll('button, textarea').forEach(control => {
        control.disabled = false;
    });
    setButtonLoading(container.querySelector('.sc-inline-image-proposal-approve'), false);
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

    const approveButton = container.querySelector('.sc-inline-image-proposal-approve');
    const actionButtons = container.querySelectorAll('button, textarea');
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
                proposal: {
                    ...spec,
                    prompt,
                },
            }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
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

    const actionButtons = container.querySelectorAll('button, textarea');
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
    container.querySelectorAll('button, textarea').forEach(control => {
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

function renderImageProposalCard(container, spec) {
    const generatedImageResult = findGeneratedImageResultForSpec(container, spec);
    if (generatedImageResult && renderGeneratedImageResult(container, spec, generatedImageResult)) {
        return;
    }

    container.replaceChildren();
    container.setAttribute('data-image-proposal-hydrated', 'true');

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

    const actions = createElement('div', 'sc-inline-image-proposal-actions d-flex flex-wrap gap-2');
    const approveButton = createElement('button', 'btn btn-sm btn-primary sc-inline-image-proposal-approve', 'Approve');
    approveButton.type = 'button';
    approveButton.title = 'Generate this image';
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
    cardBody.appendChild(actions);
    card.appendChild(cardBody);
    container.appendChild(card);
}

function getPendingProposalContainers(scopeRoot) {
    return Array.from(scopeRoot.querySelectorAll('.sc-inline-image-proposal[data-image-proposal-state="pending"]'))
        .filter(container => !container.classList.contains('sc-inline-image-proposal-status'));
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

export function hydrateInlineImageProposals(root = document) {
    const proposalContainers = root.querySelectorAll('.sc-inline-image-proposal:not([data-image-proposal-state="status"])');
    proposalContainers.forEach(container => {
        const spec = decodeContainerSpec(container);
        if (!spec) {
            setCardState(container, 'error', 'The image proposal is not valid.');
            return;
        }

        if (container.getAttribute('data-image-proposal-hydrated') === 'true' && container.querySelector('.sc-inline-image-proposal-card')) {
            return;
        }

        renderImageProposalCard(container, spec);
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
