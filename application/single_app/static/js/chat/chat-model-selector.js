// chat-model-selector.js

import { createSearchableSingleSelect } from './chat-searchable-select.js';
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

let modelSelectorController = null;
let scopeChangeListenerInitialized = false;
let suppressScopeNarrowing = false;
let pendingScopeNarrowingModel = null;
let scopeClearActionInitialized = false;
let dropdownHideListenerInitialized = false;

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
    return (option.display_name || option.model_id || option.deployment_name || 'Unnamed Model').trim() || 'Unnamed Model';
}

function getModelSearchText(option, sectionLabel) {
    return [
        getModelDisplayName(option),
        option.model_id || '',
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

    return `${displayName} (${option.deployment_name || option.model_id || 'model'})`;
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
            deploymentName: null,
        };
    }

    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    return {
        value: modelSelect.value || null,
        selectionKey: selectedOption?.dataset?.selectionKey || null,
        modelId: selectedOption?.dataset?.modelId || null,
        deploymentName: selectedOption?.dataset?.deploymentName || null,
    };
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
        const deploymentOption = matchBy(option => option.deployment_name === preferredModelDeployment);
        if (deploymentOption) {
            return deploymentOption.selection_key;
        }
    }

    if (preserveCurrentSelection && currentSelection?.deploymentName) {
        const currentDeploymentOption = matchBy(option => option.deployment_name === currentSelection.deploymentName);
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
            modelOption.value = option.deployment_name || option.model_id || option.selection_key;
            modelOption.textContent = option.optionLabel;
            modelOption.dataset.selectionKey = option.selection_key || '';
            modelOption.dataset.modelId = option.model_id || '';
            modelOption.dataset.displayName = option.display_name || '';
            modelOption.dataset.deploymentName = option.deployment_name || '';
            modelOption.dataset.endpointId = option.endpoint_id || '';
            modelOption.dataset.provider = option.provider || '';
            modelOption.dataset.scopeType = option.scope_type || '';
            modelOption.dataset.scopeId = option.scope_id || '';
            modelOption.dataset.scopeName = option.scope_name || '';
            modelOption.dataset.searchText = option.searchText || '';
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

export function refreshModelSelector() {
    if (!modelSelectorController) {
        initializeModelSelector();
    }

    modelSelectorController?.refresh();
}