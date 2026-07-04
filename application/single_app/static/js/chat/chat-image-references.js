// chat-image-references.js

const IMAGE_REFERENCE_ALLOWED_PATTERN = /\.(?:jpe?g|png|webp)(?:$|[?#])/i;
const IMAGE_GENERATION_ACTION_MARKERS = [
    'create',
    'generate',
    'make',
    'draw',
    'design',
    'render',
    'produce',
    'illustrate',
    'visualize',
    'visualise',
    'turn this into',
    'convert this into',
    'criar',
    'crie',
    'gerar',
    'gere',
    'fazer',
    'faca',
    'desenhar',
    'desenhe',
    'crear',
    'generar',
    'dibujar',
    'disenar',
];
const IMAGE_GENERATION_SUBJECT_MARKERS = [
    'image',
    'illustration',
    'visual',
    'picture',
    'graphic',
    'diagram',
    'timeline',
    'slide',
    'poster',
    'infographic',
    'map',
    'scene',
    'concept art',
    'logo',
    'icon',
    'banner',
    'thumbnail',
    'imagem',
    'imagen',
    'ilustracao',
    'ilustracion',
    'figura',
    'grafico',
    'diagrama',
    'mapa',
    'cartaz',
    'infografico',
];
const WRITABLE_GROUP_ROLES = new Set(['owner', 'admin', 'documentmanager']);
const selectedReferences = [];
let workspaceContextProvider = null;
let selectedTarget = null;
let serverTargetOptions = [];

function byId(id) {
    return document.getElementById(id);
}

function createElement(tagName, className = '', textContent = '') {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    if (textContent) {
        element.textContent = textContent;
    }
    return element;
}

function setHidden(element, hidden) {
    if (!element) {
        return;
    }
    element.classList.toggle('d-none', Boolean(hidden));
}

function normalizeText(value, maxLength = 240) {
    return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function normalizeId(value) {
    return normalizeText(value, 180);
}

export function userMessageRequestsImageGeneration(messageText) {
    const normalizedMessage = normalizeText(messageText, 4000).toLowerCase();
    if (!normalizedMessage) {
        return false;
    }

    return IMAGE_GENERATION_ACTION_MARKERS.some(marker => normalizedMessage.includes(marker))
        && IMAGE_GENERATION_SUBJECT_MARKERS.some(marker => normalizedMessage.includes(marker));
}

function isLikelyImageDocument(documentItem) {
    const fileName = normalizeText(documentItem?.file_name || documentItem?.filename || documentItem?.name);
    return IMAGE_REFERENCE_ALLOWED_PATTERN.test(fileName);
}

function sanitizeImagePreviewUrl(value) {
    const candidate = normalizeText(value, 1000);
    if (!candidate) {
        return '';
    }

    if (candidate.startsWith('/api/image/') || candidate.startsWith('/api/enhanced_citations/image?')) {
        return candidate;
    }

    if (candidate.startsWith('data:image/')) {
        return candidate;
    }

    return '';
}

function getReferenceKey(reference) {
    return [
        reference.source_type,
        reference.message_id,
        reference.document_id,
        reference.scope_type,
        reference.group_id,
        reference.public_workspace_id,
    ].map(value => normalizeId(value)).join('|');
}

function getWorkspaceContext() {
    if (typeof workspaceContextProvider !== 'function') {
        return {};
    }

    try {
        return workspaceContextProvider() || {};
    } catch (error) {
        console.warn('Failed to resolve image-reference workspace context:', error);
        return {};
    }
}

function getGroupInfo(groupId) {
    const normalizedGroupId = normalizeId(groupId);
    const groups = Array.isArray(window.userGroups) ? window.userGroups : [];
    return groups.find(group => normalizeId(group?.id || group?.group_id) === normalizedGroupId) || null;
}

function getWritableGroupTargets(scopes = getWorkspaceContext().scopes || {}) {
    if (serverTargetOptions.length > 0) {
        return serverTargetOptions.slice();
    }

    const groupIds = Array.isArray(scopes.groupIds) ? scopes.groupIds : [];
    const seenGroupIds = new Set();
    const targets = [];

    groupIds.forEach(groupId => {
        const normalizedGroupId = normalizeId(groupId);
        if (!normalizedGroupId || seenGroupIds.has(normalizedGroupId)) {
            return;
        }
        seenGroupIds.add(normalizedGroupId);

        const group = getGroupInfo(normalizedGroupId);
        const role = normalizeText(group?.userRole || group?.role).toLowerCase();
        if (!WRITABLE_GROUP_ROLES.has(role)) {
            return;
        }

        targets.push({
            scope_type: 'group',
            group_id: normalizedGroupId,
            label: normalizeText(group?.name || group?.display_name || 'Group workspace'),
            role,
        });
    });

    return targets;
}

function getTargetForPayload(scopes = getWorkspaceContext().scopes || {}) {
    const writableTargets = getWritableGroupTargets(scopes);
    const selectedGroupId = normalizeId(selectedTarget?.group_id);

    if (selectedGroupId && writableTargets.some(target => target.group_id === selectedGroupId)) {
        return {
            scope_type: 'group',
            group_id: selectedGroupId,
        };
    }

    if (writableTargets.length === 1) {
        return {
            scope_type: 'group',
            group_id: writableTargets[0].group_id,
        };
    }

    const activeGroupIds = Array.isArray(scopes.groupIds) ? scopes.groupIds : [];
    if (activeGroupIds.length > 0 && writableTargets.length === 0) {
        return {
            scope_type: 'personal',
        };
    }

    if (Array.isArray(scopes.publicWorkspaceIds) && scopes.publicWorkspaceIds.length > 0) {
        return {
            scope_type: 'personal',
        };
    }

    if (writableTargets.length > 1) {
        return selectedGroupId ? { scope_type: 'group', group_id: selectedGroupId } : null;
    }

    return {
        scope_type: 'personal',
    };
}

function updateTargetSelector(scopes = getWorkspaceContext().scopes || {}) {
    const row = byId('image-reference-target-row');
    const select = byId('image-reference-target-select');
    if (!row || !select) {
        return;
    }

    const writableTargets = getWritableGroupTargets(scopes);
    select.replaceChildren();

    if (writableTargets.length <= 1) {
        setHidden(row, true);
        if (writableTargets.length === 1) {
            selectedTarget = { scope_type: 'group', group_id: writableTargets[0].group_id };
        }
        return;
    }

    setHidden(row, false);
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Choose workspace';
    select.appendChild(placeholder);

    writableTargets.forEach(target => {
        const option = document.createElement('option');
        option.value = target.group_id;
        option.textContent = target.label;
        select.appendChild(option);
    });

    select.value = normalizeId(selectedTarget?.group_id);
}

function renderStatus() {
    const status = byId('image-reference-status');
    if (!status) {
        return;
    }

    const unsavedCount = selectedReferences.filter(reference => !reference.saved).length;
    if (selectedReferences.length === 0) {
        status.textContent = '';
    } else if (unsavedCount > 0) {
        status.textContent = `${unsavedCount} reference image${unsavedCount === 1 ? '' : 's'} pending save.`;
    } else {
        status.textContent = `${selectedReferences.length} reference image${selectedReferences.length === 1 ? '' : 's'} ready.`;
    }
}

function renderReferenceCard(reference) {
    const card = createElement('div', 'border rounded-3 p-2 d-flex align-items-center gap-2 bg-body');
    card.dataset.imageReferenceKey = reference.key;

    const previewUrl = sanitizeImagePreviewUrl(reference.preview_url);
    if (previewUrl) {
        const image = document.createElement('img');
        image.src = previewUrl;
        image.alt = reference.title || 'Reference image';
        image.className = 'rounded border object-fit-cover';
        image.width = 48;
        image.height = 48;
        image.loading = 'lazy';
        image.addEventListener('error', () => {
            image.src = '/static/images/image-error.png';
            image.alt = 'Reference image unavailable';
        }, { once: true });
        card.appendChild(image);
    }

    const body = createElement('div', 'min-w-0 flex-grow-1');
    const title = createElement('div', 'small fw-semibold text-truncate', reference.title || 'Reference image');
    const source = createElement('div', 'small text-muted text-truncate', reference.source_label || 'Image');
    body.appendChild(title);
    body.appendChild(source);
    card.appendChild(body);

    const saveButton = createElement(
        'button',
        reference.saved ? 'btn btn-sm btn-outline-success' : 'btn btn-sm btn-primary',
        reference.saved ? 'Saved' : 'Save',
    );
    saveButton.type = 'button';
    saveButton.disabled = Boolean(reference.saved);
    saveButton.title = 'Save this image for generation';
    saveButton.addEventListener('click', () => {
        reference.saved = true;
        renderImageReferenceTray();
    });
    card.appendChild(saveButton);

    const removeButton = createElement('button', 'btn btn-sm btn-outline-secondary', 'Remove');
    removeButton.type = 'button';
    removeButton.title = 'Remove this reference image';
    removeButton.addEventListener('click', () => {
        const index = selectedReferences.findIndex(item => item.key === reference.key);
        if (index >= 0) {
            selectedReferences.splice(index, 1);
        }
        renderImageReferenceTray();
    });
    card.appendChild(removeButton);

    return card;
}

function renderImageReferenceTray() {
    const panel = byId('image-reference-panel');
    const list = byId('image-reference-list');
    if (!panel || !list) {
        return;
    }

    setHidden(panel, selectedReferences.length === 0);
    if (selectedReferences.length === 0) {
        serverTargetOptions = [];
    }
    list.replaceChildren();
    selectedReferences.forEach(reference => {
        list.appendChild(renderReferenceCard(reference));
    });

    updateTargetSelector();
    renderStatus();
}

function addImageReference(rawReference) {
    const request = rawReference?.request && typeof rawReference.request === 'object'
        ? rawReference.request
        : {};
    const normalizedReference = {
        key: '',
        title: normalizeText(rawReference?.title || rawReference?.source_label || 'Reference image', 120),
        source_label: normalizeText(rawReference?.source_label || 'Image', 160),
        preview_url: sanitizeImagePreviewUrl(rawReference?.preview_url),
        request,
        saved: Boolean(rawReference?.saved),
    };
    normalizedReference.key = getReferenceKey(request);

    if (!normalizedReference.key) {
        renderImageReferenceTray();
        return false;
    }

    const existingReference = selectedReferences.find(reference => reference.key === normalizedReference.key);
    if (existingReference) {
        if (normalizedReference.saved) {
            existingReference.saved = true;
        }
        renderImageReferenceTray();
        return false;
    }

    selectedReferences.push(normalizedReference);
    renderImageReferenceTray();
    return true;
}

function normalizeWorkspaceReference(documentItem, sourceType, scopes = {}) {
    const documentId = normalizeId(documentItem?.id || documentItem?.document_id || documentItem?.doc_id);
    if (!documentId || !isLikelyImageDocument(documentItem)) {
        return null;
    }

    const fileName = normalizeText(documentItem.file_name || documentItem.filename || documentItem.name || 'Workspace image');
    const request = {
        source_type: 'workspace_image',
        document_id: documentId,
        scope_type: sourceType,
    };

    if (sourceType === 'group') {
        request.group_id = normalizeId(documentItem.group_id || documentItem.groupId || scopes.groupIds?.[0]);
    }
    if (sourceType === 'public') {
        request.public_workspace_id = normalizeId(
            documentItem.public_workspace_id
            || documentItem.publicWorkspaceId
            || scopes.publicWorkspaceIds?.[0]
        );
    }

    return {
        title: fileName,
        source_label: sourceType === 'group'
            ? 'Group workspace image'
            : sourceType === 'public'
            ? 'Public workspace image'
            : 'Personal workspace image',
        preview_url: `/api/enhanced_citations/image?doc_id=${encodeURIComponent(documentId)}`,
        request,
    };
}

function findWorkspaceDocumentReference(documentId, context) {
    const normalizedDocumentId = normalizeId(documentId);
    const scopes = context.scopes || {};
    const matchDocument = item => normalizeId(item?.id || item?.document_id || item?.doc_id) === normalizedDocumentId;

    const personalDocument = (context.personalDocs || []).find(matchDocument);
    if (personalDocument) {
        return normalizeWorkspaceReference(personalDocument, 'personal', scopes);
    }

    const groupDocument = (context.groupDocs || []).find(matchDocument);
    if (groupDocument) {
        return normalizeWorkspaceReference(groupDocument, 'group', scopes);
    }

    const publicDocument = (context.publicDocs || []).find(matchDocument);
    if (publicDocument) {
        return normalizeWorkspaceReference(publicDocument, 'public', scopes);
    }

    return null;
}

function addSelectedWorkspaceImages() {
    ensureSelectedWorkspaceImageReferences(getWorkspaceContext(), { markSaved: false });
}

export function ensureSelectedWorkspaceImageReferences(context = getWorkspaceContext(), options = {}) {
    const shouldMarkSaved = Boolean(options.markSaved);
    const selectedDocumentIds = Array.isArray(context.selectedDocumentIds) ? context.selectedDocumentIds : [];
    let selectedImageCount = 0;
    selectedDocumentIds.forEach(documentId => {
        const reference = findWorkspaceDocumentReference(documentId, context);
        if (reference) {
            selectedImageCount += 1;
            addImageReference({
                ...reference,
                saved: shouldMarkSaved,
            });
        }
    });
    renderImageReferenceTray();
    return selectedImageCount;
}

export function setImageReferenceWorkspaceContextProvider(provider) {
    workspaceContextProvider = typeof provider === 'function' ? provider : null;
}

export function attachImageReferenceMessageControls(messageElement, messageObject, imageUrl) {
    if (!messageElement || messageObject?.role !== 'image') {
        return;
    }

    const messageId = normalizeId(messageObject?.id || messageElement.getAttribute('data-message-id'));
    const previewUrl = sanitizeImagePreviewUrl(imageUrl || messageObject?.content);
    if (!messageId || !previewUrl) {
        return;
    }

    const dropdownMenu = messageElement.querySelector('.message-footer .dropdown-menu');
    if (!dropdownMenu || dropdownMenu.querySelector('[data-image-reference-action="add"]')) {
        return;
    }

    const item = document.createElement('li');
    const button = createElement('button', 'dropdown-item', 'Use as image reference');
    button.type = 'button';
    button.dataset.imageReferenceAction = 'add';
    button.addEventListener('click', () => {
        addImageReference({
            title: normalizeText(messageObject?.filename || messageObject?.prompt || 'Conversation image', 120),
            source_label: messageObject?.metadata?.is_user_upload ? 'Uploaded chat image' : 'Conversation image',
            preview_url: previewUrl,
            request: {
                source_type: 'chat_image',
                message_id: messageId,
            },
        });
    });
    item.appendChild(button);
    dropdownMenu.appendChild(item);
}

export function getImageReferenceRequestContext(context = getWorkspaceContext()) {
    const scopes = context?.scopes || getWorkspaceContext().scopes || {};
    const savedReferences = selectedReferences
        .filter(reference => reference.saved)
        .map(reference => reference.request);

    return {
        image_references: savedReferences,
        image_reference_target: savedReferences.length > 0 ? getTargetForPayload(scopes) : null,
        active_group_ids: Array.isArray(scopes.groupIds) ? scopes.groupIds : [],
        active_public_workspace_id: Array.isArray(scopes.publicWorkspaceIds) ? scopes.publicWorkspaceIds[0] || '' : '',
        has_unsaved_references: selectedReferences.some(reference => !reference.saved),
    };
}

export function showImageReferenceTargetOptions(targetOptions = []) {
    if (Array.isArray(targetOptions) && targetOptions.length > 0) {
        serverTargetOptions = targetOptions.map(target => ({
            scope_type: 'group',
            group_id: normalizeId(target.group_id || target.groupId),
            label: normalizeText(target.label || 'Group workspace'),
            role: normalizeText(target.role),
        })).filter(target => target.group_id);
        selectedTarget = null;
    }
    renderImageReferenceTray();
    const status = byId('image-reference-status');
    if (status) {
        status.textContent = 'Choose a workspace target before generating.';
    }
}

export function clearImageReferences() {
    selectedReferences.splice(0, selectedReferences.length);
    selectedTarget = null;
    serverTargetOptions = [];
    renderImageReferenceTray();
}

export function initializeImageReferenceTray() {
    const addWorkspaceButton = byId('image-reference-add-selected-workspace-btn');
    if (addWorkspaceButton && !addWorkspaceButton.dataset.bound) {
        addWorkspaceButton.dataset.bound = 'true';
        addWorkspaceButton.addEventListener('click', addSelectedWorkspaceImages);
    }

    const clearButton = byId('image-reference-clear-btn');
    if (clearButton && !clearButton.dataset.bound) {
        clearButton.dataset.bound = 'true';
        clearButton.addEventListener('click', clearImageReferences);
    }

    const targetSelect = byId('image-reference-target-select');
    if (targetSelect && !targetSelect.dataset.bound) {
        targetSelect.dataset.bound = 'true';
        targetSelect.addEventListener('change', () => {
            const groupId = normalizeId(targetSelect.value);
            selectedTarget = groupId ? { scope_type: 'group', group_id: groupId } : null;
            renderStatus();
        });
    }

    renderImageReferenceTray();
}

document.addEventListener('DOMContentLoaded', initializeImageReferenceTray);
