// chat-model-selector.js

import { createFloatingSearchableSelectDropdownConfig, createSearchableSingleSelect } from './chat-searchable-select.js';
import { getEffectiveScopes, setEffectiveScopes } from './chat-documents.js';
import { getConversationFilteringContext } from './chat-conversation-scope.js';

const modelSelect = document.getElementById('model-select');
const modelDropdown = document.getElementById('model-dropdown');
const modelDropdownButton = document.getElementById('model-dropdown-button');
const modelDropdownMenu = document.getElementById('model-dropdown-menu');
const modelDropdownText = modelDropdownButton
    ? modelDropdownButton.querySelector('.chat-searchable-select-text')
    : null;
const modelSearchInput = document.getElementById('model-search-input');
const modelDropdownItems = document.getElementById('model-dropdown-items');

const FLOATING_SELECTOR_DROPDOWN_CONFIG = createFloatingSearchableSelectDropdownConfig();

let modelSelectorController = null;
let scopeChangeListenerInitialized = false;
let suppressScopeNarrowing = false;
let pendingScopeNarrowingModel = null;
let scopeClearActionInitialized = false;
let dropdownHideListenerInitialized = false;
let personaViewportListenerInitialized = false;

function compareByName(leftValue, rightValue) {
    return String(leftValue || '').localeCompare(String(rightValue || ''), undefined, {
        sensitivity: 'base',
    });
}

function getBroadScopes() {
    return {
        personal: true,
        groupIds: getKnownGroupIds(),
        publicWorkspaceIds: getKnownPublicWorkspaceIds(),
    };
}

function getSortedGroups() {
    return (window.userGroups || []).slice().sort((leftGroup, rightGroup) => {
        return compareByName(leftGroup?.name, rightGroup?.name);
    });
}

function getModelDisplayName(option) {
    return (option.display_name || option.request_model || option.model_id || option.deployment_name || 'Unnamed Model').trim() || 'Unnamed Model';
}

function getModelSearchText(option, sectionLabel) {
    return [
        getModelDisplayName(option),
        option.model_id || '',
        option.request_model || '',
        option.deployment_name || '',
        sectionLabel,
    ].join(' ').trim();
}

function getSectionDuplicateCounts(options) {
    return options.reduce((counts, option) => {
        const key = getModelDisplayName(option).toLowerCase();
        counts[key] = (counts[key] || 0) + 1;
        return counts;
    }, {});
}

function getModelOptionLabel(option, duplicateCounts) {
    const displayName = getModelDisplayName(option);
    const duplicateCount = duplicateCounts[displayName.toLowerCase()] || 0;
    if (duplicateCount <= 1) {
        return displayName;
    }

    return `${displayName} (${option.request_model || option.deployment_name || option.model_id || 'model'})`;
}

function getKnownGroupIds() {
    return (window.userGroups || [])
        .map(group => group?.id)
        .filter(Boolean)
        .map(String);
}

function getKnownPublicWorkspaceIds() {
    return (window.userVisiblePublicWorkspaces || [])
        .map(workspace => workspace?.id)
        .filter(Boolean)
        .map(String);
}

function normalizeStringArray(values = []) {
    return Array.from(new Set(values.filter(Boolean).map(String)));
}

function areScopesBroad(scopes) {
    const knownGroupIds = normalizeStringArray(getKnownGroupIds());
    const selectedGroupIds = normalizeStringArray(scopes.groupIds || []);
    const knownPublicWorkspaceIds = normalizeStringArray(getKnownPublicWorkspaceIds());
    const selectedPublicWorkspaceIds = normalizeStringArray(scopes.publicWorkspaceIds || []);

    return scopes.personal === true
        && knownGroupIds.length === selectedGroupIds.length
        && knownGroupIds.every(groupId => selectedGroupIds.includes(groupId))
        && knownPublicWorkspaceIds.length === selectedPublicWorkspaceIds.length
        && knownPublicWorkspaceIds.every(workspaceId => selectedPublicWorkspaceIds.includes(workspaceId));
}

function getPreloadedModelOptions() {
    return Array.isArray(window.chatModelOptions) ? window.chatModelOptions : [];
}

function parseJsonObject(rawValue) {
    if (!rawValue) {
        return {};
    }
    try {
        const parsed = JSON.parse(rawValue);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
        return {};
    }
}

function normalizeIconPayload(iconPayload) {
    if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
        return null;
    }
    const kind = String(iconPayload.kind || '').trim().toLowerCase();
    const value = String(iconPayload.value || '').trim();
    if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
        return { kind, value };
    }
    if (kind === 'image' && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 350000) {
        return { kind, value };
    }
    return null;
}

function createOptionIconElement(iconPayload) {
    const icon = normalizeIconPayload(iconPayload);
    if (!icon) {
        return null;
    }
    if (icon.kind === 'image') {
        const image = document.createElement('img');
        image.src = icon.value;
        image.alt = '';
        image.className = 'chat-searchable-select-item-icon';
        return image;
    }
    const iconWrapper = document.createElement('span');
    iconWrapper.className = 'chat-searchable-select-item-icon';
    const iconElement = document.createElement('i');
    iconElement.className = `bi ${icon.value}`;
    iconElement.setAttribute('aria-hidden', 'true');
    iconWrapper.appendChild(iconElement);
    return iconWrapper;
}

function personaTooltip(markdown) {
    const preview = String(markdown || '')
        .replace(/[#>*_`~[\]()!-]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    return `Persona enabled${preview ? `: ${preview.slice(0, 240)}` : ''}`;
}

function refreshPersonaDropdownPlacement(focusTarget) {
    window.requestAnimationFrame(() => {
        const dropdown = bootstrap.Dropdown.getInstance(modelDropdownButton);
        dropdown?.update?.();
        const items = modelDropdownItems;
        if (!items || !modelDropdownMenu || !modelDropdownButton) {
            return;
        }
        const hasInspector = Boolean(items.querySelector('.chat-model-persona-inspector'));
        if (!hasInspector) {
            items.style.maxHeight = '';
            dropdown?.update?.();
            focusTarget?.scrollIntoView({ block: 'nearest' });
            return;
        }

        const buttonRect = modelDropdownButton.getBoundingClientRect();
        const visualViewport = window.visualViewport;
        const viewportTop = visualViewport?.offsetTop || 0;
        const viewportHeight = visualViewport?.height || window.innerHeight;
        const viewportBottom = viewportTop + viewportHeight;
        const placement = dropdown?._popper?.state?.placement || '';
        const availableSideHeight = placement.startsWith('top')
            ? Math.max(0, buttonRect.top - viewportTop - 24)
            : Math.max(0, viewportBottom - buttonRect.bottom - 24);
        const availableMenuHeight = Math.min(
            availableSideHeight,
            viewportHeight * 0.6,
        );
        const menuStyle = window.getComputedStyle(modelDropdownMenu);
        const nonItemsHeight = Array.from(modelDropdownMenu.children).reduce((height, child) => {
            if (child === items || child.classList.contains('d-none')) {
                return height;
            }
            return height + child.getBoundingClientRect().height;
        }, parseFloat(menuStyle.paddingTop || '0') + parseFloat(menuStyle.paddingBottom || '0'));
        items.style.maxHeight = `${Math.max(48, availableMenuHeight - nonItemsHeight)}px`;
        dropdown?.update?.();
        window.requestAnimationFrame(() => {
            focusTarget?.scrollIntoView({ block: 'nearest' });
        });
    });
}

function initializePersonaViewportListener() {
    if (personaViewportListenerInitialized) {
        return;
    }
    const refreshOpenInspector = () => {
        const inspector = modelDropdownItems?.querySelector('.chat-model-persona-inspector');
        if (inspector) {
            refreshPersonaDropdownPlacement(inspector);
        }
    };
    window.addEventListener('resize', refreshOpenInspector);
    window.addEventListener('orientationchange', refreshOpenInspector);
    window.visualViewport?.addEventListener('resize', refreshOpenInspector);
    personaViewportListenerInitialized = true;
}

function createPersonaIndicator(option, interactive) {
    if (option.dataset.personaEnabled !== 'true') {
        return null;
    }

    const indicator = document.createElement(interactive ? 'span' : 'span');
    indicator.className = interactive
        ? 'chat-model-persona-indicator btn btn-sm btn-light border rounded-circle p-0'
        : 'chat-model-persona-indicator text-primary';
    indicator.title = personaTooltip(option.dataset.personaMarkdown);
    if (interactive) {
        indicator.tabIndex = 0;
        indicator.setAttribute('role', 'button');
        indicator.setAttribute('aria-label', `View persona for ${option.textContent.trim()}`);
        indicator.setAttribute('aria-expanded', 'false');
    }

    const icon = document.createElement('i');
    icon.className = 'bi bi-person';
    icon.setAttribute('aria-hidden', 'true');
    indicator.appendChild(icon);

    if (!interactive) {
        indicator.setAttribute('aria-hidden', 'true');
        return indicator;
    }
    initializePersonaViewportListener();

    const openPersona = (event) => {
        event.preventDefault();
        event.stopPropagation();
        const item = indicator.closest('.chat-searchable-select-item[data-option-index]');
        const items = item?.parentElement;
        if (!item || !items) {
            return;
        }
        const current = items.querySelector('.chat-model-persona-inspector');
        if (current?.dataset.personaFor === item.dataset.optionIndex) {
            current._closePersona?.(true);
            return;
        }
        current?._closePersona?.();

        const inspector = document.createElement('div');
        inspector.className = 'chat-model-persona-inspector border rounded-3 mx-2 mt-1 mb-2 p-3';
        inspector.dataset.personaFor = item.dataset.optionIndex;
        inspector.setAttribute('role', 'dialog');
        inspector.setAttribute('aria-label', `Persona for ${option.textContent.trim()}`);
        inspector.tabIndex = 0;

        const heading = document.createElement('div');
        heading.className = 'd-flex align-items-center gap-2 small fw-semibold text-primary mb-2';
        const headingIcon = document.createElement('i');
        headingIcon.className = 'bi bi-person';
        headingIcon.setAttribute('aria-hidden', 'true');
        heading.append(headingIcon, document.createTextNode('Persona enabled'));

        const content = document.createElement('div');
        content.className = 'chat-model-persona-inspector-content';
        content.tabIndex = 0;
        if (option.dataset.personaMarkdown) {
            content.innerHTML = DOMPurify.sanitize(marked.parse(option.dataset.personaMarkdown), {
                ALLOWED_TAGS: ['a', 'blockquote', 'br', 'code', 'em', 'h1', 'h2', 'h3', 'li', 'ol', 'p', 'pre', 'strong', 'ul'],
                ALLOWED_ATTR: ['href', 'title'],
                ALLOW_DATA_ATTR: false,
            });
        } else {
            content.className += ' small text-muted';
            content.textContent = 'The persona text is not visible to you.';
        }
        inspector.append(heading, content);

        const closePersona = (restoreFocus = false) => {
            window.removeEventListener('keydown', handleInspectorKeyboard, true);
            inspector.remove();
            indicator.setAttribute('aria-expanded', 'false');
            if (restoreFocus) {
                indicator.focus();
            }
            refreshPersonaDropdownPlacement(restoreFocus ? indicator : null);
        };
        const handleInspectorKeyboard = keyEvent => {
            if (keyEvent.key === 'Escape') {
                keyEvent.preventDefault();
                keyEvent.stopImmediatePropagation();
                closePersona(true);
                return;
            }
            if (!['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End'].includes(keyEvent.key)) {
                return;
            }
            if (!inspector.contains(keyEvent.target)) {
                return;
            }
            const scrollContainer = inspector.closest('.chat-searchable-select-items');
            if (!scrollContainer) {
                return;
            }
            keyEvent.preventDefault();
            keyEvent.stopImmediatePropagation();
            if (keyEvent.key === 'Home') {
                scrollContainer.scrollTop = 0;
            } else if (keyEvent.key === 'End') {
                scrollContainer.scrollTop = scrollContainer.scrollHeight;
            } else if (keyEvent.key === 'PageDown') {
                scrollContainer.scrollTop += Math.max(40, scrollContainer.clientHeight * 0.9);
            } else if (keyEvent.key === 'PageUp') {
                scrollContainer.scrollTop -= Math.max(40, scrollContainer.clientHeight * 0.9);
            } else {
                scrollContainer.scrollTop += keyEvent.key === 'ArrowDown' ? 40 : -40;
            }
        };
        inspector._closePersona = closePersona;
        inspector.addEventListener('click', clickEvent => clickEvent.stopPropagation());
        inspector.addEventListener('keydown', keyEvent => keyEvent.stopPropagation());
        window.addEventListener('keydown', handleInspectorKeyboard, true);
        item.after(inspector);
        indicator.setAttribute('aria-expanded', 'true');
        content.focus({ preventScroll: true });
        refreshPersonaDropdownPlacement(inspector);
    };
    indicator.addEventListener('click', openPersona);
    indicator.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
            openPersona(event);
        }
    });
    return indicator;
}

function renderModelOptionContent(option, optionLabel) {
    const wrapper = document.createElement('span');
    wrapper.className = 'd-flex align-items-center gap-2 min-w-0';
    const iconElement = createOptionIconElement(parseJsonObject(option.dataset.modelIcon || ''));
    if (iconElement) {
        wrapper.appendChild(iconElement);
    }
    const textEl = document.createElement('span');
    textEl.className = 'chat-searchable-select-item-text text-truncate';
    textEl.textContent = optionLabel;
    wrapper.appendChild(textEl);
    const personaIndicator = createPersonaIndicator(option, true);
    if (personaIndicator) {
        wrapper.appendChild(personaIndicator);
    }
    return wrapper;
}

function renderSelectedModelContent(option, optionLabel) {
    const wrapper = document.createElement('span');
    wrapper.className = 'd-flex align-items-center gap-1.5 min-w-0';
    const label = document.createElement('span');
    label.className = 'text-truncate';
    label.textContent = optionLabel;
    wrapper.appendChild(label);
    const personaIndicator = createPersonaIndicator(option, false);
    if (personaIndicator) {
        wrapper.appendChild(personaIndicator);
    }
    return wrapper;
}

function isModelEnabledForContext(option, scopes, filteringContext) {
    if (!filteringContext.isNewConversation && filteringContext.conversationScope === 'group') {
        return option.scope_type === 'global'
            || String(option.scope_id || '') === String(filteringContext.groupId || '');
    }

    if (!filteringContext.isNewConversation && filteringContext.conversationScope === 'public') {
        return option.scope_type === 'global';
    }

    if (!filteringContext.isNewConversation && filteringContext.conversationScope === 'personal') {
        return option.scope_type === 'global' || option.scope_type === 'personal';
    }

    if (option.scope_type === 'global') {
        return true;
    }

    if (option.scope_type === 'group') {
        return normalizeStringArray(scopes.groupIds || []).includes(String(option.scope_id || ''));
    }

    if (option.scope_type === 'personal') {
        return scopes.personal === true;
    }

    return false;
}

function buildModelSections(scopes, filteringContext) {
    const modelOptions = getPreloadedModelOptions();
    const sections = [];

    const globalModels = modelOptions
        .filter(option => option.scope_type === 'global')
        .slice()
        .sort((leftOption, rightOption) => compareByName(getModelDisplayName(leftOption), getModelDisplayName(rightOption)));
    if (globalModels.length > 0) {
        sections.push({
            label: 'Global',
            options: globalModels,
        });
    }

    const personalModels = modelOptions
        .filter(option => option.scope_type === 'personal')
        .slice()
        .sort((leftOption, rightOption) => compareByName(getModelDisplayName(leftOption), getModelDisplayName(rightOption)));
    if (personalModels.length > 0) {
        sections.push({
            label: 'Personal',
            options: personalModels,
        });
    }

    getSortedGroups().forEach(group => {
        const sectionOptions = modelOptions
            .filter(option => option.scope_type === 'group' && String(option.scope_id || '') === String(group.id))
            .slice()
            .sort((leftOption, rightOption) => compareByName(getModelDisplayName(leftOption), getModelDisplayName(rightOption)));

        if (sectionOptions.length > 0) {
            sections.push({
                label: `[Group] ${group.name || 'Unnamed Group'}`,
                options: sectionOptions,
            });
        }
    });

    return sections.map(section => {
        const duplicateCounts = getSectionDuplicateCounts(section.options);
        return {
            label: section.label,
            options: section.options.map(option => ({
                ...option,
                optionLabel: getModelOptionLabel(option, duplicateCounts),
                searchText: getModelSearchText(option, section.label),
                disabled: !isModelEnabledForContext(option, scopes, filteringContext),
            })),
        };
    });
}

function getSelectionSnapshot() {
    if (!modelSelect) {
        return {
            value: null,
            selectionKey: null,
            modelId: null,
            requestModel: null,
            deploymentName: null,
        };
    }

    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    return {
        value: modelSelect.value || null,
        selectionKey: selectedOption?.dataset?.selectionKey || null,
        modelId: selectedOption?.dataset?.modelId || null,
        requestModel: selectedOption?.dataset?.requestModel || null,
        deploymentName: selectedOption?.dataset?.deploymentName || null,
    };
}

function restoreLegacyPreferredModelSelection(preferredModelDeployment) {
    if (!modelSelect || !preferredModelDeployment) {
        return;
    }

    const matchingOption = Array.from(modelSelect.options).find(option => (
        option.value === preferredModelDeployment
            || option.dataset.deploymentName === preferredModelDeployment
    ));

    if (!matchingOption || matchingOption.disabled) {
        return;
    }

    modelSelect.value = matchingOption.value;
}

function resolveSelectedSelectionKey(options, restoreOptions = {}) {
    const {
        currentSelection = null,
        preferredModelId = null,
        preferredModelDeployment = null,
        preserveCurrentSelection = true,
    } = restoreOptions;

    const enabledOptions = options.filter(option => !option.disabled);
    const matchBy = predicate => enabledOptions.find(predicate);

    if (preserveCurrentSelection && currentSelection?.selectionKey) {
        const currentOption = matchBy(option => option.selection_key === currentSelection.selectionKey);
        if (currentOption) {
            return currentOption.selection_key;
        }
    }

    if (preferredModelId) {
        const preferredOption = matchBy(option => option.selection_key === preferredModelId || option.model_id === preferredModelId);
        if (preferredOption) {
            return preferredOption.selection_key;
        }
    }

    if (preferredModelDeployment) {
        const deploymentOption = matchBy(option => (
            option.request_model === preferredModelDeployment
            || option.deployment_name === preferredModelDeployment
        ));
        if (deploymentOption) {
            return deploymentOption.selection_key;
        }
    }

    if (preserveCurrentSelection && (currentSelection?.requestModel || currentSelection?.deploymentName)) {
        const currentDeploymentOption = matchBy(option => (
            option.request_model === currentSelection.requestModel
            || option.deployment_name === currentSelection.deploymentName
        ));
        if (currentDeploymentOption) {
            return currentDeploymentOption.selection_key;
        }
    }

    if (preserveCurrentSelection && currentSelection?.modelId) {
        const currentModelOption = matchBy(option => option.model_id === currentSelection.modelId);
        if (currentModelOption) {
            return currentModelOption.selection_key;
        }
    }

    return enabledOptions[0]?.selection_key || null;
}

function rebuildModelOptions(sections, restoreOptions = {}) {
    if (!modelSelect) {
        return;
    }

    modelSelect.innerHTML = '';

    const filteringContext = restoreOptions.filteringContext || getConversationFilteringContext();
    const hideUnavailableOptions = !filteringContext.isNewConversation;
    const renderedSections = sections
        .map(section => ({
            ...section,
            options: hideUnavailableOptions
                ? section.options.filter(option => !option.disabled)
                : section.options,
        }))
        .filter(section => section.options.length > 0);

    const flattenedOptions = renderedSections.flatMap(section => section.options);

    if (!flattenedOptions.length) {
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = 'No models available';
        modelSelect.appendChild(emptyOption);
        modelSelect.disabled = true;
        return;
    }

    const selectedSelectionKey = resolveSelectedSelectionKey(flattenedOptions, restoreOptions);

    renderedSections.forEach(section => {
        const optGroup = document.createElement('optgroup');
        optGroup.label = section.label;

        section.options.forEach(option => {
            const modelOption = document.createElement('option');
            modelOption.value = option.request_model || option.deployment_name || option.model_id || option.selection_key;
            modelOption.textContent = option.optionLabel;
            modelOption.dataset.selectionKey = option.selection_key || '';
            modelOption.dataset.modelId = option.model_id || '';
            modelOption.dataset.modelName = option.model_name || '';
            modelOption.dataset.reasoningCapabilities = JSON.stringify(option.reasoning_capabilities || {});
            modelOption.dataset.displayName = option.display_name || '';
            modelOption.dataset.requestModel = option.request_model || '';
            modelOption.dataset.deploymentName = option.deployment_name || '';
            modelOption.dataset.endpointId = option.endpoint_id || '';
            modelOption.dataset.provider = option.provider || '';
            modelOption.dataset.scopeType = option.scope_type || '';
            modelOption.dataset.scopeId = option.scope_id || '';
            modelOption.dataset.scopeName = option.scope_name || '';
            modelOption.dataset.searchText = option.searchText || '';
            modelOption.dataset.modelIcon = JSON.stringify(option.icon || {});
            modelOption.dataset.personaEnabled = String(option.persona_enabled === true);
            modelOption.dataset.personaMarkdown = option.persona_markdown || '';
            if (option.persona_enabled) {
                modelOption.textContent = `${modelOption.textContent} (Persona)`;
                modelOption.title = option.persona_markdown || 'Persona enabled';
            }
            modelOption.disabled = option.disabled;
            modelOption.selected = !option.disabled && option.selection_key === selectedSelectionKey;
            optGroup.appendChild(modelOption);
        });

        modelSelect.appendChild(optGroup);
    });

    modelSelect.disabled = !flattenedOptions.some(option => !option.disabled);
}

async function maybeNarrowScopeForSelectedModel(payload) {
    const filteringContext = getConversationFilteringContext();
    if (!filteringContext.isNewConversation || !payload) {
        return;
    }

    const scopeType = payload.scopeType || '';
    const scopeId = payload.scopeId || null;

    if (scopeType === 'group' && scopeId) {
        await setEffectiveScopes(
            {
                personal: false,
                groupIds: [scopeId],
                publicWorkspaceIds: [],
            },
            {
                source: 'model',
            }
        );
        return;
    }

    if (scopeType === 'personal') {
        await setEffectiveScopes(
            {
                personal: true,
                groupIds: [],
                publicWorkspaceIds: [],
            },
            {
                source: 'model',
            }
        );
    }
}

function ensureScopeClearAction() {
    if (scopeClearActionInitialized || !modelDropdownMenu || !modelDropdownItems) {
        return;
    }

    const actionContainer = document.createElement('div');
    actionContainer.classList.add('d-none');
    actionContainer.setAttribute('data-model-scope-action-container', 'true');

    const divider = document.createElement('div');
    divider.classList.add('dropdown-divider');

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.classList.add('dropdown-item', 'text-muted', 'small');
    actionButton.textContent = 'Use all available workspaces';
    actionButton.addEventListener('click', async event => {
        event.preventDefault();
        event.stopPropagation();

        await setEffectiveScopes(getBroadScopes(), {
            source: 'model-clear',
        });
    });

    actionContainer.appendChild(divider);
    actionContainer.appendChild(actionButton);
    modelDropdownItems.before(actionContainer);
    scopeClearActionInitialized = true;
}

function updateScopeClearAction(scopes, filteringContext) {
    ensureScopeClearAction();

    const actionContainer = modelDropdownMenu?.querySelector('[data-model-scope-action-container="true"]');
    if (!actionContainer) {
        return;
    }

    const shouldShowAction = filteringContext.isNewConversation && !areScopesBroad(scopes);
    actionContainer.classList.toggle('d-none', !shouldShowAction);
}

function initializeDropdownHideListener() {
    if (dropdownHideListenerInitialized || !modelDropdown) {
        return;
    }

    modelDropdown.addEventListener('hidden.bs.dropdown', async () => {
        modelDropdownItems?.querySelectorAll('.chat-model-persona-inspector').forEach(inspector => {
            inspector._closePersona?.();
        });
        if (!pendingScopeNarrowingModel) {
            return;
        }

        const pendingPayload = pendingScopeNarrowingModel;
        pendingScopeNarrowingModel = null;
        await maybeNarrowScopeForSelectedModel(pendingPayload);
    });

    dropdownHideListenerInitialized = true;
}

function initializeScopeChangeListener() {
    if (scopeChangeListenerInitialized) {
        return;
    }

    window.addEventListener('chat:scope-changed', async () => {
        await populateModelDropdown();
    });

    scopeChangeListenerInitialized = true;
}

function initializeModelChangeHandler() {
    if (!modelSelect || modelSelect.dataset.scopeHandlerInitialized === 'true') {
        return;
    }

    modelSelect.addEventListener('change', async () => {
        if (suppressScopeNarrowing) {
            return;
        }

        const selectedOption = modelSelect.options[modelSelect.selectedIndex];
        if (!selectedOption || selectedOption.disabled) {
            pendingScopeNarrowingModel = null;
            return;
        }

        pendingScopeNarrowingModel = {
            scopeType: selectedOption.dataset.scopeType || '',
            scopeId: selectedOption.dataset.scopeId || null,
        };
    });

    modelSelect.dataset.scopeHandlerInitialized = 'true';
}

export function initializeModelSelector() {
    if (!modelSelectorController && modelSelect) {
        modelSelectorController = createSearchableSingleSelect({
            selectEl: modelSelect,
            dropdownEl: modelDropdown,
            buttonEl: modelDropdownButton,
            buttonTextEl: modelDropdownText,
            menuEl: modelDropdownMenu,
            searchInputEl: modelSearchInput,
            itemsContainerEl: modelDropdownItems,
            placeholderText: 'Select a Model',
            emptyMessage: 'No models available',
            emptySearchMessage: 'No matching models found',
            getOptionSearchText: option => option.dataset.searchText || option.textContent.trim(),
            renderOptionContent: renderModelOptionContent,
            renderSelectedContent: renderSelectedModelContent,
            dropdownConfig: FLOATING_SELECTOR_DROPDOWN_CONFIG,
        });
    }

    initializeScopeChangeListener();
    initializeModelChangeHandler();
    initializeDropdownHideListener();
    ensureScopeClearAction();

    return modelSelectorController;
}

export async function populateModelDropdown(restoreOptions = {}) {
    initializeModelSelector();

    if (!modelSelect) {
        return;
    }

    if (!window.appSettings?.enable_multi_model_endpoints) {
        restoreLegacyPreferredModelSelection(restoreOptions.preferredModelDeployment || null);
        modelSelectorController?.refresh();
        return;
    }

    const scopes = getEffectiveScopes();
    const filteringContext = getConversationFilteringContext();
    const sections = buildModelSections(scopes, filteringContext);
    const currentSelection = getSelectionSnapshot();

    suppressScopeNarrowing = true;
    rebuildModelOptions(sections, {
        currentSelection,
        preserveCurrentSelection: restoreOptions.preserveCurrentSelection !== false,
        preferredModelId: restoreOptions.preferredModelId || null,
        preferredModelDeployment: restoreOptions.preferredModelDeployment || null,
        filteringContext,
    });
    updateScopeClearAction(scopes, filteringContext);
    modelSelectorController?.refresh();
    modelSelect.dispatchEvent(new Event('change'));
    suppressScopeNarrowing = false;
}

export async function selectModelForChatLink(selectionKey) {
    if (!modelSelect || !selectionKey) {
        return false;
    }
    await populateModelDropdown({
        preferredModelId: selectionKey,
        preferredModelDeployment: selectionKey,
        preserveCurrentSelection: false,
    });
    const option = modelSelect.options[modelSelect.selectedIndex];
    if (
        !option
        || option.disabled
        || (option.dataset.selectionKey || option.value) !== selectionKey
    ) {
        return false;
    }
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    const agentSelectContainer = document.getElementById('agent-select-container');
    enableAgentsBtn?.classList.remove('active');
    if (agentSelectContainer) {
        agentSelectContainer.classList.add('d-none');
    }
    if (modelSelectContainer) {
        modelSelectContainer.classList.remove('d-none');
        modelSelectContainer.style.removeProperty('display');
    }
    modelSelectorController?.refresh();
    return true;
}

export function refreshModelSelector() {
    if (!modelSelectorController) {
        initializeModelSelector();
    }

    modelSelectorController?.refresh();
}

function findModelOptionForMetadata(modelSelection = {}) {
    if (!modelSelect || !modelSelection || typeof modelSelection !== 'object') {
        return null;
    }

    const endpointId = String(modelSelection.model_endpoint_id || modelSelection.endpoint_id || '').trim();
    const modelId = String(modelSelection.model_id || '').trim();
    const selectedModel = String(modelSelection.selected_model || modelSelection.request_model || '').trim();
    const frontendModel = String(modelSelection.frontend_requested_model || modelSelection.deployment_name || '').trim();
    const options = Array.from(modelSelect.options).filter(option => !option.disabled);

    if (endpointId && modelId) {
        const scopeType = String(modelSelection.model_scope_type || '').trim();
        const scopeId = String(modelSelection.model_scope_id || '').trim();
        const endpointMatch = options.find(option => (
            option.dataset.endpointId === endpointId
            && option.dataset.modelId === modelId
            && (!scopeType || option.dataset.scopeType === scopeType)
            && (!scopeId || option.dataset.scopeId === scopeId)
        ));
        if (endpointMatch) {
            return endpointMatch;
        }
    }

    const modelNames = [frontendModel, selectedModel].filter(Boolean);
    return options.find(option => modelNames.some(modelName => (
        option.dataset.requestModel === modelName
        || option.dataset.deploymentName === modelName
        || option.value === modelName
    ))) || null;
}

export function restoreModelSelectionFromConversationMetadata(modelSelection = {}) {
    const matchingOption = findModelOptionForMetadata(modelSelection);
    if (!matchingOption || !modelSelect) {
        return false;
    }

    modelSelect.value = matchingOption.value;
    matchingOption.selected = true;
    modelSelectorController?.refresh();
    modelSelect.dispatchEvent(new CustomEvent('change', {
        bubbles: true,
        detail: { conversationRestore: true }
    }));
    return true;
}

export function restoreAdminDefaultModelSelection() {
    if (!window.appSettings?.enable_default_model_for_new_conversations) {
        return false;
    }

    return restoreModelSelectionFromConversationMetadata(
        window.initialChatModelSelection || window.appSettings.default_model_selection || {}
    );
}