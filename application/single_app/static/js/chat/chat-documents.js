// chat-documents.js

import { showToast } from "./chat-toast.js";
import { initializeFilterableDropdownSearch } from "./chat-searchable-select.js";

export const docScopeSelect = document.getElementById("doc-scope-select");
const searchDocumentsBtn = document.getElementById("search-documents-btn");
const docSelectEl = document.getElementById("document-select"); // Hidden select element
const searchDocumentsContainer = document.getElementById("search-documents-container"); // Container for scope/doc/class
const searchDocumentsMobileClose = document.getElementById("search-documents-mobile-close");

// Custom dropdown elements
const docDropdown = document.getElementById("document-dropdown");
const docDropdownButton = document.getElementById("document-dropdown-button");
const docDropdownItems = document.getElementById("document-dropdown-items");
const docDropdownMenu = document.getElementById("document-dropdown-menu");
const docSearchInput = document.getElementById("document-search-input");
const documentActionSelect = document.getElementById("document-action-select");

const DOCUMENT_ACTION_NONE = "none";
const ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS = Object.freeze(['search', 'analyze', 'compare']);
const ASSIGNED_KNOWLEDGE_ACTION_TO_DOCUMENT_ACTION = Object.freeze({
  search: DOCUMENT_ACTION_NONE,
  analyze: 'analyze',
  compare: 'comparison',
});

// Tags filter elements
const chatTagsFilter = document.getElementById("chat-tags-filter");
const tagsDropdown = document.getElementById("tags-dropdown");
const tagsDropdownButton = document.getElementById("tags-dropdown-button");
const tagsDropdownMenu = document.getElementById("tags-dropdown-menu");
const tagsDropdownItems = document.getElementById("tags-dropdown-items");
const tagsSearchInput = document.getElementById("tags-search-input");
const tagsDropdownLoadingSpinner = document.getElementById("tags-dropdown-loading-spinner");
const tagsDropdownText = tagsDropdownButton ? tagsDropdownButton.querySelector('.selected-tags-text') : null;

// Scope dropdown elements
const scopeDropdown = document.getElementById("scope-dropdown");
const scopeDropdownButton = document.getElementById("scope-dropdown-button");
const scopeDropdownItems = document.getElementById("scope-dropdown-items");
const scopeDropdownMenu = document.getElementById("scope-dropdown-menu");
const scopeSearchInput = document.getElementById("scope-search-input");

// We'll store personalDocs/groupDocs/publicDocs in memory once loaded:
export let personalDocs = [];
export let groupDocs = [];
export let publicDocs = [];
const citationMetadataCache = new Map();
const documentVersionsCache = new Map();

// Items removed from the DOM by tag filtering (stored so they can be re-added)
// Each entry: { element, nextSibling }
let tagFilteredOutItems = [];

// Scope lock state
let scopeLocked = null;    // null = auto-lockable, true = locked, false = user-unlocked
let lockedContexts = [];   // Array of {scope, id} identifying locked workspaces
let assignedKnowledgeActive = false;
let assignedKnowledgeAllowsUserContext = false;
let assignedKnowledgeAllowedUserActions = new Set(ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS);
let userWorkspaceContextActive = false;
const conversationTaskDocumentsByConversationId = new Map();

// Build name maps from server-provided data (fixes activeGroupName bug)
const groupIdToName = {};
(window.userGroups || []).forEach(g => { groupIdToName[g.id] = g.name; });

const publicWorkspaceIdToName = {};
(window.userVisiblePublicWorkspaces || []).forEach(ws => { publicWorkspaceIdToName[ws.id] = ws.name; });

function syncWorkspaceNameMaps() {
  Object.keys(groupIdToName).forEach(key => { delete groupIdToName[key]; });
  Object.keys(publicWorkspaceIdToName).forEach(key => { delete publicWorkspaceIdToName[key]; });
  (window.userGroups || []).forEach(g => { groupIdToName[g.id] = g.name; });
  (window.userVisiblePublicWorkspaces || []).forEach(ws => { publicWorkspaceIdToName[ws.id] = ws.name; });
}

// Multi-scope selection state
let selectedPersonal = true;
let selectedGroupIds = (window.userGroups || []).map(g => g.id);
let selectedPublicWorkspaceIds = (window.userVisiblePublicWorkspaces || []).map(ws => ws.id);
let hasResolvedTagsState = false;
let tagsDropdownState = 'loading';

const documentSearchController = initializeFilterableDropdownSearch({
  dropdownEl: docDropdown,
  menuEl: docDropdownMenu,
  searchInputEl: docSearchInput,
  itemsContainerEl: docDropdownItems,
  emptyMessage: 'No matching documents found',
  isAlwaysVisibleItem: item => item.getAttribute('data-search-role') === 'action',
  onFilterApplied: () => updateDocumentDropdownActionState(),
});

const scopeSearchController = initializeFilterableDropdownSearch({
  dropdownEl: scopeDropdown,
  menuEl: scopeDropdownMenu,
  searchInputEl: scopeSearchInput,
  itemsContainerEl: scopeDropdownItems,
  emptyMessage: 'No matching workspaces found',
  isAlwaysVisibleItem: item => item.getAttribute('data-search-role') === 'action',
});

const tagsSearchController = initializeFilterableDropdownSearch({
  dropdownEl: tagsDropdown,
  menuEl: tagsDropdownMenu,
  searchInputEl: tagsSearchInput,
  itemsContainerEl: tagsDropdownItems,
  emptyMessage: 'No matching tags found',
  isAlwaysVisibleItem: item => item.getAttribute('data-search-role') === 'action',
});

const SEARCH_DOCUMENTS_MOBILE_MEDIA_QUERY = '(max-width: 991.98px)';
const SEARCH_DROPDOWN_VIEWPORT_PADDING = 16;
const SEARCH_FILTER_DESKTOP_MIN_WIDTH = 320;
const SEARCH_FILTER_DESKTOP_MAX_WIDTH = 640;

function isSearchDocumentsMobileDrawerViewport() {
  return typeof window !== 'undefined' && window.matchMedia(SEARCH_DOCUMENTS_MOBILE_MEDIA_QUERY).matches;
}

function setSearchDocumentsButtonActiveState(isActive) {
  if (!searchDocumentsBtn) {
    return;
  }

  searchDocumentsBtn.classList.toggle('active', isActive);
  searchDocumentsBtn.setAttribute('aria-expanded', String(isActive));
}

function normalizeAssignedKnowledgeArray(values = []) {
  return Array.from(new Set((Array.isArray(values) ? values : []).map(value => String(value || '').trim()).filter(Boolean)));
}

function normalizeAssignedKnowledgeUserActions(values) {
  if (values === null || values === undefined) {
    return [...ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS];
  }
  const normalizedActions = normalizeAssignedKnowledgeArray(values).map(action => {
    const normalizedAction = action.toLowerCase();
    return normalizedAction === 'comparison' ? 'compare' : normalizedAction;
  });
  return normalizedActions.filter(action => ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS.includes(action));
}

function normalizeTaskDocumentId(documentId) {
  return String(documentId || '').trim();
}

function normalizeTaskDocumentIds(documentIds = []) {
  const normalizedIds = [];
  const seenIds = new Set();
  (Array.isArray(documentIds) ? documentIds : [documentIds]).forEach(documentId => {
    const normalizedId = normalizeTaskDocumentId(documentId);
    if (!normalizedId || seenIds.has(normalizedId)) {
      return;
    }
    seenIds.add(normalizedId);
    normalizedIds.push(normalizedId);
  });
  return normalizedIds;
}

function getConversationTaskDocumentConversationId(conversationId = null) {
  return String(conversationId || window.currentConversationId || '').trim();
}

function getConversationTaskDocumentMap(conversationId, createIfMissing = false) {
  const normalizedConversationId = getConversationTaskDocumentConversationId(conversationId);
  if (!normalizedConversationId) {
    return null;
  }
  if (!conversationTaskDocumentsByConversationId.has(normalizedConversationId) && createIfMissing) {
    conversationTaskDocumentsByConversationId.set(normalizedConversationId, new Map());
  }
  return conversationTaskDocumentsByConversationId.get(normalizedConversationId) || null;
}

function isConversationTaskDocumentReady(taskDocument = {}) {
  const statusText = String(taskDocument.status || '').trim().toLowerCase();
  const percentageComplete = Number(taskDocument.percentage_complete || taskDocument.percentageComplete || 0);
  if (statusText.includes('error') || statusText.includes('failed')) {
    return false;
  }
  return percentageComplete >= 100 || statusText.includes('processing complete') || statusText.includes('complete');
}

function normalizeConversationTaskDocument(documentInfo = {}, fallbackConversationId = null) {
  const attachment = documentInfo.workspace_attachment || documentInfo.attachment || documentInfo;
  const documentId = normalizeTaskDocumentId(
    attachment.document_id || attachment.id || documentInfo.workspace_document_id || documentInfo.document_id || documentInfo.id
  );
  const conversationId = getConversationTaskDocumentConversationId(
    documentInfo.conversation_id || attachment.conversation_id || fallbackConversationId
  );
  if (!documentId || !conversationId) {
    return null;
  }

  const taskDocument = {
    id: documentId,
    conversation_id: conversationId,
    file_name: attachment.file_name || documentInfo.file_name || documentInfo.filename || '',
    scope: String(attachment.scope || documentInfo.scope || documentInfo.workspace_scope || '').trim().toLowerCase(),
    group_id: attachment.group_id || documentInfo.group_id || null,
    status: attachment.status || documentInfo.status || '',
    percentage_complete: attachment.percentage_complete ?? documentInfo.percentage_complete ?? 0,
    link_state: attachment.link_state || documentInfo.link_state || 'linked',
  };
  taskDocument.ready = documentInfo.ready === true || isConversationTaskDocumentReady(taskDocument);
  return taskDocument;
}

function getAssignedKnowledgeActionForDocumentAction(actionType) {
  const normalizedActionType = String(actionType || DOCUMENT_ACTION_NONE).trim().toLowerCase() || DOCUMENT_ACTION_NONE;
  if (normalizedActionType === 'analyze') {
    return 'analyze';
  }
  if (normalizedActionType === 'comparison') {
    return 'compare';
  }
  return 'search';
}

export function canUseConversationTaskDocumentsForAction(actionType = DOCUMENT_ACTION_NONE) {
  if (!assignedKnowledgeActive) {
    return true;
  }
  if (!assignedKnowledgeAllowsUserContext) {
    return false;
  }
  return assignedKnowledgeAllowedUserActions.has(getAssignedKnowledgeActionForDocumentAction(actionType));
}

export function registerConversationTaskDocument(documentInfo = {}, options = {}) {
  const taskDocument = normalizeConversationTaskDocument(documentInfo, options.conversationId);
  if (!taskDocument) {
    return false;
  }

  const taskDocumentMap = getConversationTaskDocumentMap(taskDocument.conversation_id, true);
  if (!taskDocumentMap) {
    return false;
  }

  const previousTaskDocument = taskDocumentMap.get(taskDocument.id) || {};
  taskDocumentMap.set(taskDocument.id, {
    ...previousTaskDocument,
    ...taskDocument,
    ready: Boolean(taskDocument.ready || previousTaskDocument.ready),
  });
  return true;
}

export function updateConversationTaskDocumentsFromMessages(messages = [], conversationId = null) {
  const normalizedConversationId = getConversationTaskDocumentConversationId(conversationId);
  if (!normalizedConversationId) {
    return [];
  }

  const taskDocumentMap = new Map();
  (Array.isArray(messages) ? messages : []).forEach(message => {
    const workspaceAttachment = message?.metadata?.workspace_attachment;
    if (!workspaceAttachment) {
      return;
    }
    const taskDocument = normalizeConversationTaskDocument(
      {
        ...message,
        workspace_attachment: workspaceAttachment,
      },
      normalizedConversationId,
    );
    if (taskDocument) {
      taskDocumentMap.set(taskDocument.id, taskDocument);
    }
  });
  conversationTaskDocumentsByConversationId.set(normalizedConversationId, taskDocumentMap);
  return Array.from(taskDocumentMap.values());
}

export function getConversationTaskDocuments(conversationId = null) {
  const taskDocumentMap = getConversationTaskDocumentMap(conversationId, false);
  return taskDocumentMap ? Array.from(taskDocumentMap.values()) : [];
}

export function getConversationTaskDocumentIds(options = {}) {
  const actionType = options.actionType || DOCUMENT_ACTION_NONE;
  if (!canUseConversationTaskDocumentsForAction(actionType)) {
    return [];
  }
  const readyOnly = options.readyOnly !== false;
  return normalizeTaskDocumentIds(
    getConversationTaskDocuments(options.conversationId)
      .filter(taskDocument => !readyOnly || taskDocument.ready)
      .map(taskDocument => taskDocument.id)
  );
}

export function getConversationTaskDocumentSummary(options = {}) {
  const actionType = options.actionType || DOCUMENT_ACTION_NONE;
  const taskDocuments = getConversationTaskDocuments(options.conversationId);
  const readyIds = canUseConversationTaskDocumentsForAction(actionType)
    ? normalizeTaskDocumentIds(taskDocuments.filter(taskDocument => taskDocument.ready).map(taskDocument => taskDocument.id))
    : [];
  return {
    allowed: canUseConversationTaskDocumentsForAction(actionType),
    totalCount: taskDocuments.length,
    readyCount: readyIds.length,
    pendingCount: taskDocuments.filter(taskDocument => !taskDocument.ready).length,
    readyIds,
  };
}

function getAssignedKnowledgeScopes(assignedKnowledge = {}) {
  const scopes = assignedKnowledge.scopes || {};
  return {
    personal: Boolean(scopes.personal),
    groupIds: normalizeAssignedKnowledgeArray(scopes.group_ids),
    publicWorkspaceIds: normalizeAssignedKnowledgeArray(scopes.public_workspace_ids),
  };
}

function getAssignedKnowledgeScopeSelection(agent = {}, assignedKnowledge = {}) {
  const scopes = getAssignedKnowledgeScopes(assignedKnowledge);
  const groupIds = [...scopes.groupIds];
  const publicWorkspaceIds = [...scopes.publicWorkspaceIds];
  let personal = scopes.personal;

  if (agent?.is_group && agent?.group_id) {
    const ownerGroupId = String(agent.group_id || '').trim();
    if (ownerGroupId && !groupIds.includes(ownerGroupId)) {
      groupIds.push(ownerGroupId);
    }
  } else if (!agent?.is_global) {
    personal = true;
  }

  return {
    personal,
    groupIds,
    publicWorkspaceIds,
  };
}

function syncAssignedKnowledgeButtonState() {
  if (!searchDocumentsBtn) {
    return;
  }

  if (!assignedKnowledgeActive) {
    setSearchDocumentsButtonActiveState(Boolean(userWorkspaceContextActive));
    searchDocumentsBtn.title = 'Search workspaces';
    searchDocumentsBtn.setAttribute('aria-expanded', String(userWorkspaceContextActive));
    return;
  }

  searchDocumentsBtn.classList.add('active');
  searchDocumentsBtn.title = assignedKnowledgeAllowsUserContext
    ? 'Assigned Knowledge active. Open Workspaces to add task documents.'
    : 'Assigned Knowledge active for the selected agent.';
  searchDocumentsBtn.setAttribute('aria-expanded', String(userWorkspaceContextActive));
}

function syncAssignedKnowledgeDocumentActionOptions() {
  if (!documentActionSelect) {
    return;
  }

  const allowedDocumentActions = new Set(
    Array.from(assignedKnowledgeAllowedUserActions)
      .map(action => ASSIGNED_KNOWLEDGE_ACTION_TO_DOCUMENT_ACTION[action])
      .filter(Boolean)
  );
  Array.from(documentActionSelect.options || []).forEach(option => {
    option.disabled = assignedKnowledgeActive
      && assignedKnowledgeAllowsUserContext
      && !allowedDocumentActions.has(option.value);
  });

  if (assignedKnowledgeActive && assignedKnowledgeAllowsUserContext && allowedDocumentActions.size === 0) {
    documentActionSelect.disabled = true;
  }

  if (documentActionSelect.selectedOptions?.[0]?.disabled) {
    const firstEnabledOption = Array.from(documentActionSelect.options || []).find(option => !option.disabled);
    documentActionSelect.value = firstEnabledOption?.value || DOCUMENT_ACTION_NONE;
  }
}

function setAssignedKnowledgeControlState(isActive) {
  const lockPickerControls = isActive && !assignedKnowledgeAllowsUserContext;
  [scopeDropdownButton, tagsDropdownButton, docDropdownButton].forEach(button => {
    if (!button) {
      return;
    }
    button.disabled = lockPickerControls;
    button.setAttribute('aria-disabled', String(lockPickerControls));
    button.title = lockPickerControls ? 'Controlled by the selected agent assigned knowledge.' : '';
  });
  if (documentActionSelect) {
    documentActionSelect.disabled = lockPickerControls;
  }
  syncAssignedKnowledgeDocumentActionOptions();
  syncAssignedKnowledgeButtonState();
}

function applyTagSelectionForValues(tags = []) {
  const selectedTags = new Set(normalizeAssignedKnowledgeArray(tags));
  if (chatTagsFilter) {
    Array.from(chatTagsFilter.options).forEach(option => {
      option.selected = selectedTags.has(option.value);
    });
  }
  if (tagsDropdownItems) {
    tagsDropdownItems.querySelectorAll('.dropdown-item').forEach(item => {
      const checkbox = item.querySelector('.tag-checkbox');
      const value = item.getAttribute('data-tag-value');
      if (checkbox) {
        checkbox.checked = selectedTags.has(value);
      }
    });
  }
  syncTagsDropdownButtonText();
  filterDocumentsBySelectedTags();
}

export function isAssignedKnowledgeActive() {
  return assignedKnowledgeActive;
}

export function isUserWorkspaceContextEnabled() {
  if (assignedKnowledgeActive) {
    return assignedKnowledgeAllowsUserContext && userWorkspaceContextActive;
  }
  return Boolean(searchDocumentsBtn?.classList.contains('active'));
}

export function getAssignedKnowledgeAllowedUserActions() {
  return Array.from(assignedKnowledgeAllowedUserActions);
}

export function clearAssignedKnowledgeLock() {
  const panelVisible = Boolean(
    searchDocumentsContainer
    && searchDocumentsContainer.style.display !== 'none'
    && !searchDocumentsContainer.classList.contains('d-none')
  );
  assignedKnowledgeActive = false;
  assignedKnowledgeAllowsUserContext = false;
  assignedKnowledgeAllowedUserActions = new Set(ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS);
  userWorkspaceContextActive = panelVisible && Boolean(searchDocumentsBtn?.classList.contains('active'));
  setAssignedKnowledgeControlState(false);
}

export async function applyAssignedKnowledgeLock(agent = null) {
  const assignedKnowledge = agent?.assigned_knowledge || agent?.assignedKnowledge || null;
  if (!assignedKnowledge?.enabled) {
    clearAssignedKnowledgeLock();
    return false;
  }

  assignedKnowledgeActive = true;
  assignedKnowledgeAllowsUserContext = Boolean(assignedKnowledge.allow_user_workspace_context);
  assignedKnowledgeAllowedUserActions = new Set(
    normalizeAssignedKnowledgeUserActions(
      assignedKnowledge.allowed_user_workspace_actions ?? assignedKnowledge.allowed_user_context_actions
    )
  );
  userWorkspaceContextActive = false;
  await setEffectiveScopes(
    getAssignedKnowledgeScopeSelection(agent || {}, assignedKnowledge),
    {
      source: 'assigned-knowledge',
      reload: false,
    }
  );
  hideSearchDocumentsPanel();
  setAssignedKnowledgeControlState(true);
  syncDropdownButtonText();
  return true;
}

function setTagsDropdownButtonState({ state, message, enabled }) {
  tagsDropdownState = state;
  hasResolvedTagsState = state !== 'loading';

  if (tagsDropdownButton) {
    tagsDropdownButton.disabled = !enabled;
    tagsDropdownButton.setAttribute('aria-disabled', String(!enabled));
    tagsDropdownButton.classList.toggle('is-loading', state === 'loading');
    tagsDropdownButton.classList.toggle('is-empty', state === 'empty');

    if (!enabled && typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
      bootstrap.Dropdown.getInstance(tagsDropdownButton)?.hide();
    }
  }

  if (tagsDropdownLoadingSpinner) {
    tagsDropdownLoadingSpinner.classList.toggle('d-none', state !== 'loading');
  }

  if (tagsDropdownText && typeof message === 'string') {
    tagsDropdownText.textContent = message;
  }
}

function setTagsDropdownLoadingState(message = 'Loading tags...') {
  tagsSearchController?.resetFilter();
  setTagsDropdownButtonState({
    state: 'loading',
    message,
    enabled: false,
  });
}

function setTagsDropdownReadyState() {
  setTagsDropdownButtonState({
    state: 'ready',
    message: 'All Tags',
    enabled: true,
  });
  syncTagsDropdownButtonText();
}

function setTagsDropdownEmptyState(message = 'No tags available for this scope') {
  tagsSearchController?.resetFilter();
  setTagsDropdownButtonState({
    state: 'empty',
    message,
    enabled: false,
  });
}

function getSearchDocumentsOffcanvasInstance() {
  if (!searchDocumentsContainer || !isSearchDocumentsMobileDrawerViewport()) {
    return null;
  }

  if (typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
    return null;
  }

  return bootstrap.Offcanvas.getOrCreateInstance(searchDocumentsContainer, { toggle: false });
}

function closeSearchDocumentsDropdowns() {
  if (typeof bootstrap === 'undefined' || !bootstrap.Dropdown) {
    return;
  }

  [scopeDropdownButton, tagsDropdownButton, docDropdownButton].forEach((buttonEl) => {
    if (!buttonEl) {
      return;
    }

    bootstrap.Dropdown.getInstance(buttonEl)?.hide();
  });
}

function refreshDocumentsAndTags({ source = null, showLoading = true } = {}) {
  if (showLoading) {
    setTagsDropdownLoadingState();
  }

  return loadAllDocs()
    .then(() => loadTagsForScope())
    .then(() => {
      if (source) {
        dispatchScopeChanged(source);
      }
    });
}

const SEARCH_FILTER_DROPDOWN_FLIP_THRESHOLD = 180;
const SEARCH_FILTER_DROPDOWN_MAX_HEIGHT = 420;
const SEARCH_FILTER_DROPDOWN_WIDTHS = {
  'scope-dropdown-menu': 360,
  'tags-dropdown-menu': 360,
  'document-dropdown-menu': 520,
};

function getSearchFilterDropdownViewportSpace(buttonEl) {
  if (!buttonEl) {
    return {
      above: 0,
      below: 0,
    };
  }

  const buttonRect = buttonEl.getBoundingClientRect();

  return {
    above: Math.max(0, buttonRect.top - SEARCH_DROPDOWN_VIEWPORT_PADDING),
    below: Math.max(0, window.innerHeight - buttonRect.bottom - SEARCH_DROPDOWN_VIEWPORT_PADDING),
  };
}

function getSearchFilterDropdownPlacement(buttonEl, { openUpOnDesktop = false } = {}) {
  if (openUpOnDesktop && !isSearchDocumentsMobileDrawerViewport()) {
    return 'top-start';
  }

  const viewportSpace = getSearchFilterDropdownViewportSpace(buttonEl);

  if (
    viewportSpace.below < SEARCH_FILTER_DROPDOWN_FLIP_THRESHOLD
    && viewportSpace.above > viewportSpace.below
  ) {
    return 'top-start';
  }

  return 'bottom-start';
}

function getSearchDocumentsDropdownConfig({ buttonEl = null, openUpOnDesktop = false } = {}) {
  return {
    boundary: 'viewport',
    reference: 'toggle',
    autoClose: 'outside',
    popperConfig(defaultConfig) {
      const placement = getSearchFilterDropdownPlacement(buttonEl, { openUpOnDesktop });
      const baseModifiers = Array.isArray(defaultConfig.modifiers)
        ? defaultConfig.modifiers.filter(modifier => !['flip', 'preventOverflow'].includes(modifier.name))
        : [];

      return {
        ...defaultConfig,
        placement,
        strategy: 'fixed',
        modifiers: [
          ...baseModifiers,
          {
            name: 'flip',
            options: {
              boundary: 'viewport',
              fallbackPlacements: placement.startsWith('top') ? ['bottom-start'] : ['top-start'],
              padding: SEARCH_DROPDOWN_VIEWPORT_PADDING,
              rootBoundary: 'viewport',
            },
          },
          {
            name: 'preventOverflow',
            options: {
              boundary: 'viewport',
              padding: SEARCH_DROPDOWN_VIEWPORT_PADDING,
              rootBoundary: 'viewport',
            },
          },
        ],
      };
    },
  };
}

function getSearchFilterDropdownAvailableHeight(buttonEl, menuEl) {
  const placement = menuEl.getAttribute('data-popper-placement') || getSearchFilterDropdownPlacement(buttonEl);
  const viewportSpace = getSearchFilterDropdownViewportSpace(buttonEl);

  if (placement.startsWith('top')) {
    return viewportSpace.above;
  }

  return viewportSpace.below;
}

function getSearchFilterDropdownWidth(buttonEl, menuEl) {
  const fieldContainer = buttonEl.closest('.chat-search-panel-field');
  const containerWidth = fieldContainer ? fieldContainer.offsetWidth : buttonEl.offsetWidth || 280;
  const viewportMaxWidth = Math.max(0, window.innerWidth - (SEARCH_DROPDOWN_VIEWPORT_PADDING * 2));

  if (isSearchDocumentsMobileDrawerViewport() || menuEl.closest('.document-comparison-picker-controls')) {
    return Math.min(containerWidth, viewportMaxWidth || containerWidth);
  }

  const preferredWidth = SEARCH_FILTER_DROPDOWN_WIDTHS[menuEl.id] || containerWidth;
  return Math.min(Math.max(containerWidth, preferredWidth), viewportMaxWidth || preferredWidth);
}

function sizeSearchFilterDropdown(buttonEl, menuEl, itemsContainerEl) {
  if (!buttonEl || !menuEl) {
    return;
  }

  const menuWidth = Math.floor(getSearchFilterDropdownWidth(buttonEl, menuEl));
  const menuHeight = Math.floor(Math.min(
    getSearchFilterDropdownAvailableHeight(buttonEl, menuEl),
    SEARCH_FILTER_DROPDOWN_MAX_HEIGHT
  ));

  menuEl.style.width = `${menuWidth}px`;
  menuEl.style.minWidth = `${menuWidth}px`;
  menuEl.style.maxWidth = `${menuWidth}px`;
  menuEl.style.maxHeight = `${Math.max(0, menuHeight)}px`;
  menuEl.style.overflowY = 'hidden';
  menuEl.style.zIndex = '1060';
  if (!itemsContainerEl) {
    return;
  }

  const maxMenuHeight = Number.parseFloat(menuEl.style.maxHeight) || 0;
  const searchContainer = menuEl.querySelector('.chat-dropdown-search, .document-search-container');
  const searchHeight = searchContainer && !searchContainer.classList.contains('d-none')
    ? searchContainer.getBoundingClientRect().height
    : 0;
  const menuVerticalChrome = searchHeight + 16;

  itemsContainerEl.style.maxHeight = `${Math.max(0, Math.floor(maxMenuHeight - menuVerticalChrome))}px`;
  itemsContainerEl.style.overflowY = 'auto';
}

function resetSearchFilterDropdownStyles(menuEl, itemsContainerEl) {
  if (menuEl) {
    menuEl.style.maxHeight = '';
    menuEl.style.maxWidth = '';
    menuEl.style.minWidth = '';
    menuEl.style.overflowY = '';
    menuEl.style.width = '';
    menuEl.style.zIndex = '';
  }

  if (itemsContainerEl) {
    itemsContainerEl.style.maxHeight = '';
    itemsContainerEl.style.overflowY = '';
  }
}

function initializeSearchFilterDropdown({
  dropdownEl,
  buttonEl,
  menuEl,
  itemsContainerEl,
  searchInputEl,
  searchController,
  openUpOnDesktop = false,
  onShown,
}) {
  if (!dropdownEl || !buttonEl || !menuEl) {
    return;
  }

  new bootstrap.Dropdown(buttonEl, getSearchDocumentsDropdownConfig({ buttonEl, openUpOnDesktop }));

  dropdownEl.addEventListener('show.bs.dropdown', function() {
    if (searchInputEl) {
      searchInputEl.value = '';
    }

    searchController?.applyFilter('');
    sizeSearchFilterDropdown(buttonEl, menuEl, itemsContainerEl);
  });

  dropdownEl.addEventListener('shown.bs.dropdown', function() {
    sizeSearchFilterDropdown(buttonEl, menuEl, itemsContainerEl);
    onShown?.();

    try {
      bootstrap.Dropdown.getInstance(buttonEl)?.update();
      sizeSearchFilterDropdown(buttonEl, menuEl, itemsContainerEl);
    } catch (error) {
      console.error('Error updating search filter dropdown placement:', error);
    }

    if (searchInputEl) {
      setTimeout(() => searchInputEl.focus(), 50);
    }
  });

  dropdownEl.addEventListener('hidden.bs.dropdown', function() {
    searchController?.resetFilter();
    resetSearchFilterDropdownStyles(menuEl, itemsContainerEl);
  });
}

export async function showSearchDocumentsPanel() {
  if (!searchDocumentsContainer) {
    return false;
  }

  setSearchDocumentsButtonActiveState(true);
  searchDocumentsContainer.style.display = 'block';

  const offcanvasInstance = getSearchDocumentsOffcanvasInstance();
  if (!offcanvasInstance || searchDocumentsContainer.classList.contains('show')) {
    return true;
  }

  await new Promise((resolve) => {
    searchDocumentsContainer.addEventListener('shown.bs.offcanvas', () => resolve(), { once: true });
    offcanvasInstance.show();
  });

  return true;
}

export function hideSearchDocumentsPanel() {
  if (!searchDocumentsContainer) {
    return false;
  }

  closeSearchDocumentsDropdowns();

  const offcanvasInstance = getSearchDocumentsOffcanvasInstance();
  if (offcanvasInstance && searchDocumentsContainer.classList.contains('show')) {
    offcanvasInstance.hide();
    return true;
  }

  setSearchDocumentsButtonActiveState(false);
  searchDocumentsContainer.style.display = 'none';
  return true;
}

if (searchDocumentsContainer) {
  searchDocumentsContainer.addEventListener('shown.bs.offcanvas', () => {
    if (assignedKnowledgeActive && assignedKnowledgeAllowsUserContext) {
      userWorkspaceContextActive = true;
    }
    setSearchDocumentsButtonActiveState(true);
    syncAssignedKnowledgeButtonState();
  });

  searchDocumentsContainer.addEventListener('hidden.bs.offcanvas', () => {
    closeSearchDocumentsDropdowns();
    if (assignedKnowledgeActive) {
      userWorkspaceContextActive = false;
    }

    if (isSearchDocumentsMobileDrawerViewport()) {
      searchDocumentsContainer.style.display = 'none';
    }

    setSearchDocumentsButtonActiveState(false);
    syncAssignedKnowledgeButtonState();
  });
}

searchDocumentsMobileClose?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  hideSearchDocumentsPanel();
});

/* ---------------------------------------------------------------------------
   Get Effective Scopes — used by chat-messages.js and internally
--------------------------------------------------------------------------- */
export function getEffectiveScopes() {
  return {
    personal: selectedPersonal,
    groupIds: [...selectedGroupIds],
    publicWorkspaceIds: [...selectedPublicWorkspaceIds],
  };
}

/* ---------------------------------------------------------------------------
   Scope Lock — exported functions
--------------------------------------------------------------------------- */

/** Returns current scope lock state: null (auto-lockable), true (locked), false (user-unlocked). */
export function isScopeLocked() {
  return scopeLocked;
}

/**
 * Apply scope lock from metadata after a response.
 * Called after AI response when backend sets scope_locked=true.
 */
export function applyScopeLock(contexts, lockState) {
  if (lockState !== true) return;
  scopeLocked = true;
  lockedContexts = contexts || [];
  rebuildScopeDropdownWithLock();
  updateHeaderLockIcon();
}

/**
 * Toggle scope lock via API call. Can both lock and unlock.
 * @param {string} conversationId
 * @param {boolean} newState - true = lock, false = unlock
 * @returns {Promise}
 */
export async function toggleScopeLock(conversationId, newState) {
  if (!conversationId) return;

  const response = await fetch(`/api/conversations/${conversationId}/scope_lock`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ scope_locked: newState })
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || 'Failed to toggle scope lock');
  }

  const result = await response.json();
  scopeLocked = newState;
  // lockedContexts preserved from API response (never cleared)
  lockedContexts = result.locked_contexts || lockedContexts;

  if (newState === true) {
    // Re-locking: narrow scope to locked workspaces, rebuild with lock
    selectedPersonal = lockedContexts.some(c => c.scope === 'personal');
    selectedGroupIds = lockedContexts.filter(c => c.scope === 'group').map(c => c.id);
    selectedPublicWorkspaceIds = lockedContexts.filter(c => c.scope === 'public').map(c => c.id);
    rebuildScopeDropdownWithLock();
  } else {
    // Unlocking: open all scopes, rebuild normally
    const groups = window.userGroups || [];
    const publicWorkspaces = window.userVisiblePublicWorkspaces || [];
    selectedPersonal = true;
    selectedGroupIds = groups.map(g => g.id);
    selectedPublicWorkspaceIds = publicWorkspaces.map(ws => ws.id);
    buildScopeDropdown();
    updateScopeLockIcon();
  }

  updateHeaderLockIcon();

  // Reload scope-dependent UI and notify listeners like the agent picker.
  runScopeRefreshPipeline('scope-lock').catch(error => {
    console.error('Failed to refresh scope-dependent UI after toggling scope lock:', error);
  });
}

/**
 * Restore scope lock state when switching conversations.
 * Called from selectConversation() in chat-conversations.js.
 */
export function restoreScopeLockState(lockState, contexts) {
  scopeLocked = lockState;
  lockedContexts = contexts || [];

  if (scopeLocked === true && lockedContexts.length > 0) {
    // Set scope selection to match locked contexts
    selectedPersonal = lockedContexts.some(c => c.scope === 'personal');
    selectedGroupIds = lockedContexts.filter(c => c.scope === 'group').map(c => c.id);
    selectedPublicWorkspaceIds = lockedContexts.filter(c => c.scope === 'public').map(c => c.id);

    rebuildScopeDropdownWithLock();
    // Reload docs for the locked scope
    refreshDocumentsAndTags();
  } else {
    // Not locked (null or false) — rebuild dropdown normally
    buildScopeDropdown();
    updateScopeLockIcon();
  }

  updateHeaderLockIcon();
}

/**
 * Reset scope lock for a new conversation.
 * Resets to "All" with no lock.
 */
export function resetScopeLock(options = {}) {
  const { preserveSelections = false } = options;

  scopeLocked = null;
  lockedContexts = [];

  if (preserveSelections) {
    buildScopeDropdown();
    updateScopeLockIcon();
    updateHeaderLockIcon();
    return;
  }

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];
  selectedPersonal = true;
  selectedGroupIds = groups.map(g => g.id);
  selectedPublicWorkspaceIds = publicWorkspaces.map(ws => ws.id);

  buildScopeDropdown();
  updateScopeLockIcon();
  updateHeaderLockIcon();

  // Reload documents for the full "All" scope
  refreshDocumentsAndTags();
}

function resetWorkspaceSearchActionState(event = null) {
  const detail = event?.detail || {};
  if (detail.preserveSelections) {
    return;
  }

  userWorkspaceContextActive = false;

  if (documentActionSelect) {
    documentActionSelect.value = DOCUMENT_ACTION_NONE;
  }

  if (docSelectEl) {
    Array.from(docSelectEl.options).forEach(option => {
      option.selected = false;
    });
  }

  if (docDropdownItems) {
    docDropdownItems.querySelectorAll('.doc-checkbox').forEach(checkbox => {
      checkbox.checked = false;
    });
  }

  resetTagSelectionState();
  hideSearchDocumentsPanel();
  syncDropdownButtonText();
  handleDocumentSelectChange();
  syncAssignedKnowledgeButtonState();
}

window.addEventListener('chat:conversation-context-changed', resetWorkspaceSearchActionState);

/* ---------------------------------------------------------------------------
   Set scope from legacy URL parameter values (personal/group/public/all)
--------------------------------------------------------------------------- */
export function setScopeFromUrlParam(scopeString, options = {}) {
  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];

  switch (scopeString) {
    case "personal":
      selectedPersonal = true;
      selectedGroupIds = [];
      selectedPublicWorkspaceIds = [];
      break;
    case "group":
      selectedPersonal = false;
      selectedGroupIds = options.groupId ? [options.groupId] : groups.map(g => g.id);
      selectedPublicWorkspaceIds = [];
      break;
    case "public":
      selectedPersonal = false;
      selectedGroupIds = [];
      selectedPublicWorkspaceIds = options.workspaceId ? [options.workspaceId] : publicWorkspaces.map(ws => ws.id);
      break;
    default: // "all"
      selectedPersonal = true;
      selectedGroupIds = groups.map(g => g.id);
      selectedPublicWorkspaceIds = publicWorkspaces.map(ws => ws.id);
      break;
  }

  buildScopeDropdown();
  dispatchScopeChanged('workspace');
}

/* ---------------------------------------------------------------------------
   Build the Scope Dropdown (called once on init)
--------------------------------------------------------------------------- */
function buildScopeDropdown() {
  if (!scopeDropdownItems) return;

  syncWorkspaceNameMaps();

  scopeDropdownItems.innerHTML = "";

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];

  // "Select All" / "Clear All" toggle
  const allItem = document.createElement("button");
  allItem.type = "button";
  allItem.classList.add("dropdown-item", "d-flex", "align-items-center", "fw-bold");
  allItem.setAttribute("data-scope-action", "toggle-all");
  allItem.setAttribute("data-search-role", "action");
  allItem.style.display = "flex";
  allItem.style.width = "100%";
  allItem.style.textAlign = "left";
  const allCb = document.createElement("input");
  allCb.type = "checkbox";
  allCb.classList.add("form-check-input", "me-2", "scope-checkbox-all");
  allCb.style.pointerEvents = "none";
  allCb.style.minWidth = "16px";
  allCb.checked = true;
  // Compute initial "All" state from module variables
  const totalPossibleInit = 1 + groups.length + publicWorkspaces.length;
  const totalSelectedInit = (selectedPersonal ? 1 : 0) + selectedGroupIds.length + selectedPublicWorkspaceIds.length;
  allCb.checked = (totalSelectedInit === totalPossibleInit);
  allCb.indeterminate = (totalSelectedInit > 0 && totalSelectedInit < totalPossibleInit);
  const allLabel = document.createElement("span");
  allLabel.textContent = "All";
  allItem.appendChild(allCb);
  allItem.appendChild(allLabel);
  scopeDropdownItems.appendChild(allItem);

  // Divider
  const divider1 = document.createElement("div");
  divider1.classList.add("dropdown-divider");
  scopeDropdownItems.appendChild(divider1);

  // Personal item
  const personalItem = createScopeItem("personal", "Personal", selectedPersonal);
  scopeDropdownItems.appendChild(personalItem);

  // Groups section
  if (groups.length > 0) {
    const groupHeader = document.createElement("div");
    groupHeader.classList.add("dropdown-header", "small", "text-muted", "px-2", "pt-2", "pb-1");
    groupHeader.textContent = "Groups";
    scopeDropdownItems.appendChild(groupHeader);

    groups.forEach(g => {
      const item = createScopeItem(`group:${g.id}`, g.name, selectedGroupIds.includes(g.id));
      scopeDropdownItems.appendChild(item);
    });
  }

  // Public Workspaces section
  if (publicWorkspaces.length > 0) {
    const pubHeader = document.createElement("div");
    pubHeader.classList.add("dropdown-header", "small", "text-muted", "px-2", "pt-2", "pb-1");
    pubHeader.textContent = "Public Workspaces";
    scopeDropdownItems.appendChild(pubHeader);

    publicWorkspaces.forEach(ws => {
      const item = createScopeItem(`public:${ws.id}`, ws.name, selectedPublicWorkspaceIds.includes(ws.id));
      scopeDropdownItems.appendChild(item);
    });
  }

  syncScopeButtonText();
  scopeSearchController?.applyFilter(scopeSearchInput ? scopeSearchInput.value : '');
}

/* ---------------------------------------------------------------------------
   Rebuild Scope Dropdown with Lock Indicators
--------------------------------------------------------------------------- */
function rebuildScopeDropdownWithLock() {
  if (scopeLocked !== true || !scopeDropdownItems) {
    buildScopeDropdown();
    updateScopeLockIcon();
    return;
  }

  // First build the dropdown normally
  buildScopeDropdown();

  // Build a set of locked scope keys for fast lookup (e.g. "personal", "group:abc", "public:xyz")
  const lockedKeys = new Set();
  for (const ctx of lockedContexts) {
    if (ctx.scope === 'personal') {
      lockedKeys.add('personal');
    } else if (ctx.scope === 'group') {
      lockedKeys.add(`group:${ctx.id}`);
    } else if (ctx.scope === 'public') {
      lockedKeys.add(`public:${ctx.id}`);
    }
  }

  // Force scope selection to match locked contexts
  selectedPersonal = lockedKeys.has('personal');
  selectedGroupIds = lockedContexts.filter(c => c.scope === 'group').map(c => c.id);
  selectedPublicWorkspaceIds = lockedContexts.filter(c => c.scope === 'public').map(c => c.id);

  // Iterate all scope items and apply lock/disable styling
  scopeDropdownItems.querySelectorAll('.dropdown-item[data-scope-value]').forEach(item => {
    const val = item.getAttribute('data-scope-value');
    const cb = item.querySelector('.scope-checkbox');
    const isLocked = lockedKeys.has(val);

    if (isLocked) {
      // This workspace is locked — mark as active and locked
      if (cb) cb.checked = true;
      item.classList.add('scope-locked-item');
      item.classList.remove('scope-disabled-item');
      item.style.pointerEvents = 'none';

      // Add lock icon if not already present
      if (!item.querySelector('.bi-lock-fill')) {
        const lockIcon = document.createElement('i');
        lockIcon.classList.add('bi', 'bi-lock-fill', 'ms-auto', 'text-warning', 'scope-lock-badge');
        item.appendChild(lockIcon);
      }
    } else {
      // This workspace is not locked — gray it out
      if (cb) cb.checked = false;
      item.classList.add('scope-disabled-item');
      item.classList.remove('scope-locked-item');
      item.style.pointerEvents = 'none';
      item.title = 'Scope locked to other workspaces';
    }
  });

  // Disable the "All" toggle
  const allToggle = scopeDropdownItems.querySelector('[data-scope-action="toggle-all"]');
  if (allToggle) {
    allToggle.classList.add('scope-disabled-item');
    allToggle.style.pointerEvents = 'none';
    const allCb = allToggle.querySelector('.scope-checkbox-all');
    if (allCb) {
      allCb.checked = false;
      allCb.indeterminate = true;
    }
  }

  syncScopeButtonText();
  updateScopeLockIcon();
  scopeSearchController?.applyFilter(scopeSearchInput ? scopeSearchInput.value : '');
}

/* ---------------------------------------------------------------------------
   Update Scope Lock Icon Visibility and Tooltip
--------------------------------------------------------------------------- */
function updateScopeLockIcon() {
  const indicator = document.getElementById('scope-lock-indicator');
  if (!indicator) return;

  if (scopeLocked === true) {
    indicator.style.display = 'inline';

    // Build tooltip showing locked workspace names
    const names = [];
    for (const ctx of lockedContexts) {
      if (ctx.scope === 'personal') {
        names.push('Personal');
      } else if (ctx.scope === 'group') {
        const name = groupIdToName[ctx.id] || ctx.id;
        names.push(`Group: ${name}`);
      } else if (ctx.scope === 'public') {
        const name = publicWorkspaceIdToName[ctx.id] || ctx.id;
        names.push(`Public: ${name}`);
      }
    }
    indicator.title = `Scope locked to: ${names.join(', ')}. Click to manage.`;
  } else {
    indicator.style.display = 'none';
  }

  updateHeaderLockIcon();
}

/* ---------------------------------------------------------------------------
   Update Header Lock Icon (inline with classification badges)
--------------------------------------------------------------------------- */
function updateHeaderLockIcon() {
  const headerBtn = document.getElementById('header-scope-lock-btn');
  if (!headerBtn) return;

  if (scopeLocked === null || scopeLocked === undefined) {
    // No data used yet — hide header lock
    headerBtn.style.display = 'none';
  } else if (scopeLocked === true) {
    // Locked
    headerBtn.style.display = 'inline';
    headerBtn.className = 'text-warning';
    headerBtn.innerHTML = '<i class="bi bi-lock-fill"></i>';
    headerBtn.title = 'Scope locked — click to manage';
  } else {
    // Unlocked (false)
    headerBtn.style.display = 'inline';
    headerBtn.className = 'text-muted';
    headerBtn.innerHTML = '<i class="bi bi-unlock"></i>';
    headerBtn.title = 'Scope unlocked — click to re-lock';
  }
}

function createScopeItem(value, label, checked) {
  const item = document.createElement("button");
  item.type = "button";
  item.classList.add("dropdown-item", "d-flex", "align-items-center");
  item.setAttribute("data-scope-value", value);
  item.setAttribute("data-search-role", "item");
  item.dataset.searchLabel = label;
  item.style.display = "flex";
  item.style.width = "100%";
  item.style.textAlign = "left";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.classList.add("form-check-input", "me-2", "scope-checkbox");
  cb.style.pointerEvents = "none";
  cb.style.minWidth = "16px";
  cb.checked = checked;

  const span = document.createElement("span");
  span.textContent = label;
  span.style.overflow = "hidden";
  span.style.textOverflow = "ellipsis";
  span.style.whiteSpace = "nowrap";

  item.appendChild(cb);
  item.appendChild(span);
  return item;
}

/* ---------------------------------------------------------------------------
   Sync scope state from checkboxes → module variables
--------------------------------------------------------------------------- */
function syncScopeStateFromCheckboxes() {
  if (!scopeDropdownItems) return;

  selectedPersonal = false;
  selectedGroupIds = [];
  selectedPublicWorkspaceIds = [];

  scopeDropdownItems.querySelectorAll(".dropdown-item[data-scope-value]").forEach(item => {
    const cb = item.querySelector(".scope-checkbox");
    if (!cb || !cb.checked) return;

    const val = item.getAttribute("data-scope-value");
    if (val === "personal") {
      selectedPersonal = true;
    } else if (val.startsWith("group:")) {
      selectedGroupIds.push(val.substring(6));
    } else if (val.startsWith("public:")) {
      selectedPublicWorkspaceIds.push(val.substring(7));
    }
  });

  // Update the "All" checkbox state
  const allCb = scopeDropdownItems.querySelector(".scope-checkbox-all");
  if (allCb) {
    const totalItems = scopeDropdownItems.querySelectorAll(".scope-checkbox").length;
    const checkedItems = scopeDropdownItems.querySelectorAll(".scope-checkbox:checked").length;
    allCb.checked = (totalItems === checkedItems);
    allCb.indeterminate = (checkedItems > 0 && checkedItems < totalItems);
  }
}

/* ---------------------------------------------------------------------------
   Sync scope button text
--------------------------------------------------------------------------- */
function syncScopeButtonText() {
  if (!scopeDropdownButton) return;
  const textEl = scopeDropdownButton.querySelector(".selected-scope-text");
  if (!textEl) return;

  syncWorkspaceNameMaps();

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];

  const totalPossible = 1 + groups.length + publicWorkspaces.length; // personal + groups + public
  const totalSelected = (selectedPersonal ? 1 : 0) + selectedGroupIds.length + selectedPublicWorkspaceIds.length;

  if (totalSelected === 0) {
    textEl.textContent = "None selected";
  } else if (totalSelected === totalPossible) {
    textEl.textContent = "All";
  } else if (selectedPersonal && selectedGroupIds.length === 0 && selectedPublicWorkspaceIds.length === 0) {
    textEl.textContent = "Personal";
  } else {
    const parts = [];
    if (selectedPersonal) parts.push("Personal");
    if (selectedGroupIds.length === 1) {
      parts.push(groupIdToName[selectedGroupIds[0]] || "1 group");
    } else if (selectedGroupIds.length > 1) {
      parts.push(`${selectedGroupIds.length} groups`);
    }
    if (selectedPublicWorkspaceIds.length === 1) {
      parts.push(publicWorkspaceIdToName[selectedPublicWorkspaceIds[0]] || "1 workspace");
    } else if (selectedPublicWorkspaceIds.length > 1) {
      parts.push(`${selectedPublicWorkspaceIds.length} workspaces`);
    }
    textEl.textContent = parts.join(", ");
  }
}

function dispatchScopeChanged(source = 'workspace') {
  window.dispatchEvent(new CustomEvent('chat:scope-changed', {
    detail: {
      source,
      scopes: getEffectiveScopes(),
    },
  }));
}

function runScopeRefreshPipeline(source = 'workspace') {
  return refreshDocumentsAndTags({ source });
}

export function setEffectiveScopes(nextScopes = {}, options = {}) {
  if (scopeLocked === true && !options.force) {
    return Promise.resolve(false);
  }

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];
  const validGroupIds = new Set(groups.map(group => group.id));
  const validPublicWorkspaceIds = new Set(publicWorkspaces.map(workspace => workspace.id));

  const normalizedPersonal = !!nextScopes.personal;
  const normalizedGroupIds = Array.from(new Set((nextScopes.groupIds || []).filter(groupId => validGroupIds.has(groupId))));
  const normalizedPublicWorkspaceIds = Array.from(new Set((nextScopes.publicWorkspaceIds || []).filter(workspaceId => validPublicWorkspaceIds.has(workspaceId))));

  const selectionChanged = normalizedPersonal !== selectedPersonal
    || normalizedGroupIds.length !== selectedGroupIds.length
    || normalizedPublicWorkspaceIds.length !== selectedPublicWorkspaceIds.length
    || normalizedGroupIds.some((groupId, index) => groupId !== selectedGroupIds[index])
    || normalizedPublicWorkspaceIds.some((workspaceId, index) => workspaceId !== selectedPublicWorkspaceIds[index]);

  selectedPersonal = normalizedPersonal;
  selectedGroupIds = normalizedGroupIds;
  selectedPublicWorkspaceIds = normalizedPublicWorkspaceIds;

  if (scopeLocked === true) {
    rebuildScopeDropdownWithLock();
  } else {
    buildScopeDropdown();
  }

  syncScopeButtonText();

  if (options.reload === false) {
    dispatchScopeChanged(options.source || 'programmatic');
    return Promise.resolve(selectionChanged);
  }

  return runScopeRefreshPipeline(options.source || 'programmatic')
    .then(() => selectionChanged);
}

/* ---------------------------------------------------------------------------
   Handle scope change — reload docs and tags
--------------------------------------------------------------------------- */
function onScopeChanged() {
  syncScopeStateFromCheckboxes();
  syncScopeButtonText();
  runScopeRefreshPipeline('workspace');
}

function compareDisplayNames(leftValue, rightValue) {
  return String(leftValue || '').localeCompare(String(rightValue || ''), undefined, {
    sensitivity: 'base',
  });
}

function getDocumentDisplayName(documentItem) {
  return (documentItem.title || documentItem.file_name || 'Untitled Document').trim() || 'Untitled Document';
}

function createDropdownHeader(label) {
  const header = document.createElement('div');
  header.classList.add('dropdown-header', 'small', 'text-muted', 'px-2', 'pt-2', 'pb-1');
  header.textContent = label;
  return header;
}

function createDropdownDivider() {
  const divider = document.createElement('div');
  divider.classList.add('dropdown-divider');
  return divider;
}

function buildDocumentDescriptor(documentItem, sectionLabel) {
  return {
    id: documentItem.id,
    label: getDocumentDisplayName(documentItem),
    searchLabel: `${getDocumentDisplayName(documentItem)} ${sectionLabel}`.trim(),
    tags: documentItem.tags || [],
    classification: documentItem.document_classification || '',
  };
}

function appendDocumentSection(sectionLabel, documents, sectionIndex) {
  if (!docDropdownItems || !documents.length) {
    return;
  }

  if (sectionIndex > 0) {
    docDropdownItems.appendChild(createDropdownDivider());
  }

  docDropdownItems.appendChild(createDropdownHeader(sectionLabel));

  documents.forEach(documentItem => {
    const doc = buildDocumentDescriptor(documentItem, sectionLabel);

    const opt = document.createElement('option');
    opt.value = doc.id;
    opt.textContent = doc.label;
    opt.dataset.tags = JSON.stringify(doc.tags || []);
    opt.dataset.classification = doc.classification || '';
    docSelectEl.appendChild(opt);

    const dropdownItem = document.createElement('button');
    dropdownItem.type = 'button';
    dropdownItem.classList.add('dropdown-item', 'd-flex', 'align-items-center');
    dropdownItem.setAttribute('data-document-id', doc.id);
    dropdownItem.setAttribute('data-search-role', 'item');
    dropdownItem.setAttribute('title', doc.label);
    dropdownItem.dataset.searchLabel = doc.searchLabel;
    dropdownItem.dataset.tags = JSON.stringify(doc.tags || []);
    dropdownItem.dataset.classification = doc.classification || '';
    dropdownItem.style.display = 'flex';
    dropdownItem.style.width = '100%';
    dropdownItem.style.textAlign = 'left';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.classList.add('form-check-input', 'me-2', 'doc-checkbox');
    checkbox.style.pointerEvents = 'none';
    checkbox.style.minWidth = '16px';

    const label = document.createElement('span');
    label.textContent = doc.label;
    label.style.overflow = 'hidden';
    label.style.textOverflow = 'ellipsis';
    label.style.whiteSpace = 'nowrap';

    dropdownItem.appendChild(checkbox);
    dropdownItem.appendChild(label);
    docDropdownItems.appendChild(dropdownItem);
  });
}

function getCurrentDocumentActionType() {
  return String(documentActionSelect?.value || DOCUMENT_ACTION_NONE).trim().toLowerCase() || DOCUMENT_ACTION_NONE;
}

function isExplicitDocumentSelectionMode() {
  return getCurrentDocumentActionType() !== DOCUMENT_ACTION_NONE;
}

function getSelectableDocumentOptions() {
  if (!docSelectEl) {
    return [];
  }

  return Array.from(docSelectEl.options).filter(option => option.value && !option.disabled);
}

function getDocumentOptionById(documentId) {
  if (!docSelectEl || !documentId) {
    return null;
  }

  return Array.from(docSelectEl.options).find(option => option.value === documentId) || null;
}

function isDocumentSearchFilterActive() {
  return Boolean(docSearchInput && docSearchInput.value.trim());
}

function isDocumentDropdownItemVisible(item) {
  return Boolean(
    item
    && !item.classList.contains('d-none')
    && item.getAttribute('data-filtered') !== 'hidden'
  );
}

function getVisibleSearchedDocumentIds() {
  if (!docDropdownItems || !isDocumentSearchFilterActive()) {
    return [];
  }

  const seenDocumentIds = new Set();
  const visibleDocumentIds = [];

  docDropdownItems.querySelectorAll('.dropdown-item[data-search-role="item"][data-document-id]').forEach(item => {
    const documentId = item.getAttribute('data-document-id');
    const option = getDocumentOptionById(documentId);

    if (!documentId || seenDocumentIds.has(documentId) || !option || option.disabled || !isDocumentDropdownItemVisible(item)) {
      return;
    }

    seenDocumentIds.add(documentId);
    visibleDocumentIds.push(documentId);
  });

  return visibleDocumentIds;
}

function areDocumentIdsSelected(documentIds) {
  return documentIds.length > 0 && documentIds.every(documentId => {
    const option = getDocumentOptionById(documentId);
    return Boolean(option && option.selected);
  });
}

function areAllSelectableDocumentsSelected() {
  const selectableDocumentOptions = getSelectableDocumentOptions();
  return selectableDocumentOptions.length > 0 && selectableDocumentOptions.every(option => option.selected);
}

function getDocumentDropdownActionState() {
  if (isDocumentSearchFilterActive()) {
    const searchedDocumentIds = getVisibleSearchedDocumentIds();
    const allSearchedDocumentsSelected = areDocumentIdsSelected(searchedDocumentIds);

    if (searchedDocumentIds.length === 0) {
      return {
        disabled: true,
        documentIds: [],
        label: 'No Matching Documents',
        mode: 'searched',
        shouldClearSelections: false,
      };
    }

    return {
      disabled: false,
      documentIds: searchedDocumentIds,
      label: allSearchedDocumentsSelected ? 'Clear Searched' : 'Select All Searched',
      mode: 'searched',
      shouldClearSelections: allSearchedDocumentsSelected,
    };
  }

  if (!isExplicitDocumentSelectionMode()) {
    return {
      disabled: false,
      documentIds: [],
      label: 'All Documents',
      mode: 'all-documents',
      shouldClearSelections: true,
    };
  }

  const allSelectableDocumentsSelected = areAllSelectableDocumentsSelected();

  return {
    disabled: false,
    documentIds: getSelectableDocumentOptions().map(option => option.value),
    label: allSelectableDocumentsSelected ? 'Clear Selected Documents' : 'Select All Documents',
    mode: 'all-selectable',
    shouldClearSelections: allSelectableDocumentsSelected,
  };
}

function getDocumentDropdownActionLabel() {
  return getDocumentDropdownActionState().label;
}

function updateDocumentDropdownActionState() {
  const actionLabel = getDocumentDropdownActionLabel();

  if (docSelectEl) {
    const allDocumentsOption = Array.from(docSelectEl.options).find(option => option.value === "");
    if (allDocumentsOption) {
      allDocumentsOption.textContent = actionLabel;
    }
  }

  if (docDropdownItems) {
    const actionItem = docDropdownItems.querySelector('.dropdown-item[data-document-id=""]');
    if (actionItem) {
      actionItem.textContent = actionLabel;
      const actionState = getDocumentDropdownActionState();
      actionItem.disabled = actionState.disabled;
      actionItem.classList.toggle('disabled', actionState.disabled);
      actionItem.setAttribute('aria-disabled', String(actionState.disabled));
    }
  }
}

function applyDocumentSelectionForIds(documentIds, { clearMatchingDocuments = false, replaceSelection = false } = {}) {
  const targetDocumentIds = new Set(documentIds);

  if (docDropdownItems) {
    docDropdownItems.querySelectorAll('.dropdown-item[data-document-id]').forEach(dropdownItem => {
      const documentId = dropdownItem.getAttribute('data-document-id');
      const checkbox = dropdownItem.querySelector('.doc-checkbox');

      if (!checkbox || !documentId) {
        return;
      }

      if (clearMatchingDocuments) {
        if (targetDocumentIds.has(documentId)) {
          checkbox.checked = false;
        }
        return;
      }

      checkbox.checked = replaceSelection ? targetDocumentIds.has(documentId) : checkbox.checked || targetDocumentIds.has(documentId);
    });
  }

  if (!docSelectEl) {
    return;
  }

  Array.from(docSelectEl.options).forEach(option => {
    if (!option.value) {
      option.selected = false;
      return;
    }

    if (clearMatchingDocuments) {
      if (targetDocumentIds.has(option.value)) {
        option.selected = false;
      }
      return;
    }

    option.selected = replaceSelection ? targetDocumentIds.has(option.value) : option.selected || targetDocumentIds.has(option.value);
  });
}

/* ---------------------------------------------------------------------------
   Populate the Document Dropdown Based on the Scope
--------------------------------------------------------------------------- */
export function populateDocumentSelectScope() {
  if (!docSelectEl) return;

  // Discard any items stored by the tag filter (they're about to be rebuilt)
  tagFilteredOutItems = [];

  const scopes = getEffectiveScopes();

  docSelectEl.innerHTML = ""; // Clear existing options

  // Clear the dropdown items container
  if (docDropdownItems) {
    docDropdownItems.innerHTML = "";
  }

  // Add the top-level picker action to the hidden select.
  const allOpt = document.createElement("option");
  allOpt.value = ""; // Use empty string for "All"
  allOpt.textContent = getDocumentDropdownActionLabel();
  docSelectEl.appendChild(allOpt);

  // Add the top-level picker action to the custom dropdown.
  if (docDropdownItems) {
    const allItem = document.createElement("button");
    allItem.type = "button";
    allItem.classList.add("dropdown-item");
    allItem.setAttribute("data-document-id", "");
    allItem.setAttribute("data-search-role", "action");
    allItem.textContent = getDocumentDropdownActionLabel();
    allItem.style.display = "block";
    allItem.style.width = "100%";
    allItem.style.textAlign = "left";
    docDropdownItems.appendChild(allItem);
  }

  const sections = [];

  if (scopes.personal) {
    const personalSectionDocs = personalDocs.slice().sort((leftDoc, rightDoc) => {
      return compareDisplayNames(getDocumentDisplayName(leftDoc), getDocumentDisplayName(rightDoc));
    });

    if (personalSectionDocs.length > 0) {
      sections.push({
        label: 'Personal',
        documents: personalSectionDocs,
      });
    }
  }

  const sortedGroups = (window.userGroups || [])
    .filter(group => scopes.groupIds.includes(group.id))
    .sort((leftGroup, rightGroup) => compareDisplayNames(leftGroup.name, rightGroup.name));
  sortedGroups.forEach(group => {
    const sectionDocs = groupDocs
      .filter(documentItem => String(documentItem.group_id || '') === String(group.id))
      .slice()
      .sort((leftDoc, rightDoc) => compareDisplayNames(getDocumentDisplayName(leftDoc), getDocumentDisplayName(rightDoc)));

    if (sectionDocs.length > 0) {
      sections.push({
        label: `[Group] ${group.name || 'Unnamed Group'}`,
        documents: sectionDocs,
      });
    }
  });

  const sortedPublicWorkspaces = (window.userVisiblePublicWorkspaces || [])
    .filter(workspace => scopes.publicWorkspaceIds.includes(workspace.id))
    .sort((leftWorkspace, rightWorkspace) => compareDisplayNames(leftWorkspace.name, rightWorkspace.name));
  sortedPublicWorkspaces.forEach(workspace => {
    const sectionDocs = publicDocs
      .filter(documentItem => String(documentItem.public_workspace_id || '') === String(workspace.id))
      .slice()
      .sort((leftDoc, rightDoc) => compareDisplayNames(getDocumentDisplayName(leftDoc), getDocumentDisplayName(rightDoc)));

    if (sectionDocs.length > 0) {
      sections.push({
        label: `[Public] ${workspace.name || 'Unnamed Workspace'}`,
        documents: sectionDocs,
      });
    }
  });

  sections.forEach((section, sectionIndex) => {
    appendDocumentSection(section.label, section.documents, sectionIndex);
  });

  // Show/hide search based on number of documents
  if (docSearchInput && docDropdownItems) {
    const documentsCount = sections.reduce((count, section) => count + section.documents.length, 0);
    const searchContainer = docSearchInput.closest('.document-search-container');

    if (searchContainer) {
      // Always show search if there are more than 0 documents
      if (documentsCount > 0) {
        searchContainer.classList.remove('d-none');
      } else {
        searchContainer.classList.add('d-none');
      }
    }
  }

  // Reset to no specific documents selected.
  Array.from(docSelectEl.options).forEach(opt => { opt.selected = false; });
  if (docDropdownItems) {
    docDropdownItems.querySelectorAll(".doc-checkbox").forEach(cb => {
      cb.checked = false;
    });
  }

  // Trigger UI update after populating
  handleDocumentSelectChange();
  documentSearchController?.applyFilter(docSearchInput ? docSearchInput.value : '');
}

export function getDocumentMetadata(docId) {
  if (!docId) return null;
  // Search personal docs first
  const personalMatch = personalDocs.find(doc => doc.id === docId || doc.document_id === docId); // Check common ID keys
  if (personalMatch) {
    return personalMatch;
  }
  // Then search group docs
  const groupMatch = groupDocs.find(doc => doc.id === docId || doc.document_id === docId);
   if (groupMatch) {
    return groupMatch;
  }
  // Finally search public docs
  const publicMatch = publicDocs.find(doc => doc.id === docId || doc.document_id === docId);
  if (publicMatch) {
    return publicMatch;
  }
  const cachedMatch = citationMetadataCache.get(docId);
  if (cachedMatch) {
    return cachedMatch;
  }
  return null; // Not found in any list
}

function resolveDocumentScopeContext(docId, metadata = null) {
  const resolvedMetadata = metadata || getDocumentMetadata(docId);
  if (!resolvedMetadata) {
    return null;
  }

  if (resolvedMetadata.group_id) {
    return {
      scope: 'group',
      groupId: resolvedMetadata.group_id,
      publicWorkspaceId: null,
      metadata: resolvedMetadata,
    };
  }

  if (resolvedMetadata.public_workspace_id) {
    return {
      scope: 'public',
      groupId: null,
      publicWorkspaceId: resolvedMetadata.public_workspace_id,
      metadata: resolvedMetadata,
    };
  }

  return {
    scope: 'personal',
    groupId: null,
    publicWorkspaceId: null,
    metadata: resolvedMetadata,
  };
}

function buildDocumentVersionsCacheKey(docId, scopeContext) {
  return [
    scopeContext?.scope || 'personal',
    scopeContext?.groupId || '',
    scopeContext?.publicWorkspaceId || '',
    docId,
  ].join(':');
}

export async function fetchDocumentVersions(docId) {
  const scopeContext = resolveDocumentScopeContext(docId);
  if (!scopeContext) {
    return [];
  }

  const cacheKey = buildDocumentVersionsCacheKey(docId, scopeContext);
  if (documentVersionsCache.has(cacheKey)) {
    return documentVersionsCache.get(cacheKey);
  }

  let requestUrl = `/api/documents/${encodeURIComponent(docId)}/versions`;
  if (scopeContext.scope === 'group') {
    requestUrl = `/api/group_documents/${encodeURIComponent(docId)}/versions?group_id=${encodeURIComponent(scopeContext.groupId)}`;
  } else if (scopeContext.scope === 'public') {
    requestUrl = `/api/public_workspace_documents/${encodeURIComponent(docId)}/versions?workspace_id=${encodeURIComponent(scopeContext.publicWorkspaceId)}`;
  }

  const response = await fetch(requestUrl, {
    credentials: 'same-origin',
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Unable to load document versions.');
  }

  const versions = Array.isArray(data.versions) ? data.versions : [];
  const normalizedVersions = versions.map((version) => ({
    ...version,
    title: version.title || scopeContext.metadata?.title || '',
    file_name: version.file_name || scopeContext.metadata?.file_name || scopeContext.metadata?.name || '',
    group_id: scopeContext.groupId,
    public_workspace_id: scopeContext.publicWorkspaceId,
    scope: scopeContext.scope,
  }));

  documentVersionsCache.set(cacheKey, normalizedVersions);
  return normalizedVersions;
}

export async function fetchDocumentMetadata(docId) {
  if (!docId) {
    return null;
  }

  const existingMetadata = getDocumentMetadata(docId);
  if (existingMetadata) {
    return existingMetadata;
  }

  try {
    const response = await fetch(`/api/enhanced_citations/document_metadata?doc_id=${encodeURIComponent(docId)}`, {
      credentials: 'same-origin',
    });

    if (!response.ok) {
      return null;
    }

    const metadata = await response.json();
    if (metadata && metadata.id) {
      citationMetadataCache.set(metadata.id, metadata);
    }
    if (metadata && metadata.document_id) {
      citationMetadataCache.set(metadata.document_id, metadata);
    }
    return metadata;
  } catch (error) {
    console.warn('Error fetching citation document metadata:', error);
    return null;
  }
}

/* ---------------------------------------------------------------------------
   Loading Documents
--------------------------------------------------------------------------- */
export function loadPersonalDocs() {
  // Use a large page_size to load all documents at once, without pagination
  return fetch("/api/documents?page_size=1000")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching user docs:", data.error);
        personalDocs = [];
        return;
      }
      personalDocs = data.documents || [];
      console.log(`Loaded ${personalDocs.length} personal documents`);
    })
    .catch((err) => {
      console.error("Error loading personal docs:", err);
      personalDocs = [];
    });
}

export function loadGroupDocs(groupIds) {
  // Accept explicit group IDs list, fall back to selected scope
  const ids = groupIds || selectedGroupIds || [];
  if (ids.length === 0) {
    groupDocs = [];
    return Promise.resolve();
  }
  const idsParam = ids.join(',');
  return fetch(`/api/group_documents?group_ids=${encodeURIComponent(idsParam)}&page_size=1000`)
    .then((r) => {
      if (!r.ok) {
        // Handle 400 errors gracefully (e.g., no active group selected)
        if (r.status === 400) {
          console.log("No active group selected for group documents");
          groupDocs = [];
          return { documents: [] }; // Return empty result to avoid further errors
        }
        throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      }
      return r.json();
    })
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching group docs:", data.error);
        groupDocs = [];
        return;
      }
      groupDocs = data.documents || [];
      console.log(`Loaded ${groupDocs.length} group documents`);
    })
    .catch((err) => {
      console.error("Error loading group docs:", err);
      groupDocs = [];
    });
}

export function loadPublicDocs() {
  // Use a large page_size to load all documents at once, without pagination
  return fetch("/api/public_workspace_documents?page_size=1000")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching public workspace docs:", data.error);
        publicDocs = [];
        return;
      }
      // Filter to only docs from currently selected public workspaces
      const selectedWsSet = new Set(selectedPublicWorkspaceIds);
      publicDocs = (data.documents || []).filter(
        (doc) => selectedWsSet.has(doc.public_workspace_id)
      );
      console.log(
        `Loaded ${publicDocs.length} public workspace documents from selected public workspaces`
      );
    })
    .catch((err) => {
      console.error("Error loading public workspace docs:", err);
      publicDocs = [];
    });
}

export function loadAllDocs() {
  const hasDocControls = searchDocumentsBtn || docScopeSelect || docSelectEl;

  if (!hasDocControls) {
    return Promise.resolve();
  }

  // Initialize custom document dropdown if available
  if (docDropdownButton && docDropdownItems) {
    // Ensure the custom dropdown is properly initialized
    const documentSearchContainer = document.querySelector('.document-search-container');
    if (documentSearchContainer) {
      // Initially show the search field as it will be useful for filtering
      documentSearchContainer.classList.remove('d-none');
    }

  }

  const scopes = getEffectiveScopes();
  documentVersionsCache.clear();

  // Build parallel load promises based on selected scopes
  const promises = [];
  if (scopes.personal) {
    promises.push(loadPersonalDocs());
  } else {
    personalDocs = [];
  }
  if (scopes.groupIds.length > 0) {
    promises.push(loadGroupDocs(scopes.groupIds));
  } else {
    groupDocs = [];
  }
  if (scopes.publicWorkspaceIds.length > 0) {
    promises.push(loadPublicDocs());
  } else {
    publicDocs = [];
  }

  return Promise.all(promises)
    .then(() => {
      // After loading, populate the select and set initial state
      populateDocumentSelectScope();
    })
    .catch(err => {
      console.error("Error loading documents:", err);
    });
}

// Function to adjust dropdown sizing when shown
function initializeDocumentDropdown() {
  if (!docDropdownMenu || !docDropdownButton || !docDropdownItems) return;

  // Clear any leftover search-filter state on visible items
  docDropdownItems.querySelectorAll('.dropdown-item').forEach(item => {
    item.classList.remove('d-none');
  });

  // Re-apply tag filter (DOM removal approach — no CSS issues)
  filterDocumentsBySelectedTags();
  documentSearchController?.applyFilter(docSearchInput ? docSearchInput.value : '');
  sizeSearchFilterDropdown(docDropdownButton, docDropdownMenu, docDropdownItems);
}
/* ---------------------------------------------------------------------------
   Load Tags for Selected Scope
--------------------------------------------------------------------------- */
export async function loadTagsForScope() {
  if (!chatTagsFilter) return;

  // Clear existing options in both hidden select and custom dropdown
  chatTagsFilter.innerHTML = '';
  if (tagsDropdownItems) tagsDropdownItems.innerHTML = '';
  resetTagSelectionState();

  try {
    const scopes = getEffectiveScopes();
    const fetchPromises = [];

    if (scopes.personal) {
      fetchPromises.push(fetch('/api/documents/tags').then(r => r.json()));
    }
    if (scopes.groupIds.length > 0) {
      const idsParam = scopes.groupIds.join(',');
      fetchPromises.push(fetch(`/api/group_documents/tags?group_ids=${encodeURIComponent(idsParam)}`).then(r => r.json()));
    }
    if (scopes.publicWorkspaceIds.length > 0) {
      const wsParam = scopes.publicWorkspaceIds.join(',');
      fetchPromises.push(fetch(`/api/public_workspace_documents/tags?workspace_ids=${encodeURIComponent(wsParam)}`).then(r => r.json()));
    }

    if (fetchPromises.length === 0) {
      hideTagsDropdown();
      return;
    }

    const results = await Promise.allSettled(fetchPromises);

    // Merge tags by name, summing counts
    const tagMap = {};
    results.forEach(result => {
      if (result.status === 'fulfilled' && result.value && result.value.tags) {
        result.value.tags.forEach(tag => {
          if (tagMap[tag.name]) {
            tagMap[tag.name] += tag.count;
          } else {
            tagMap[tag.name] = tag.count;
          }
        });
      }
    });

    const allTags = Object.entries(tagMap).map(([name, count]) => ({ name, displayName: name, count, isClassification: false }));
    allTags.sort((a, b) => a.name.localeCompare(b.name));

    // Add classification categories if enabled
    const classificationItems = [];
    const classificationEnabled = (window.enable_document_classification === true
        || String(window.enable_document_classification).toLowerCase() === 'true');
    if (classificationEnabled) {
      const categories = window.classification_categories || [];
      const scopesForCls = getEffectiveScopes();

      // Gather all in-scope docs
      const scopeDocs = [];
      if (scopesForCls.personal) scopeDocs.push(...personalDocs);
      if (scopesForCls.groupIds.length > 0) scopeDocs.push(...groupDocs);
      if (scopesForCls.publicWorkspaceIds.length > 0) {
        const wsSet = new Set(scopesForCls.publicWorkspaceIds);
        scopeDocs.push(...publicDocs.filter(d => wsSet.has(d.public_workspace_id)));
      }

      // Count classifications
      const clsCounts = {};
      let unclassifiedCount = 0;
      scopeDocs.forEach(doc => {
        const cls = doc.document_classification;
        if (!cls || cls === '' || cls.toLowerCase() === 'none') {
          unclassifiedCount++;
        } else {
          clsCounts[cls] = (clsCounts[cls] || 0) + 1;
        }
      });

      // Always show Unclassified entry
      classificationItems.push({ name: '__unclassified__', displayName: 'Unclassified', count: unclassifiedCount, isClassification: true, color: '#6c757d' });
      // Always show all configured categories (even at 0 count)
      categories.forEach(cat => {
        const count = clsCounts[cat.label] || 0;
        classificationItems.push({ name: cat.label, displayName: cat.label, count, isClassification: true, color: cat.color || '#6c757d' });
      });
    }

    const hasItems = allTags.length > 0 || classificationItems.length > 0;

    if (hasItems) {
      // Populate hidden select with tags and classifications
      allTags.forEach(tag => {
        const option = document.createElement('option');
        option.value = tag.name;
        option.textContent = `${tag.name} (${tag.count})`;
        chatTagsFilter.appendChild(option);
      });
      classificationItems.forEach(cls => {
        const option = document.createElement('option');
        option.value = cls.name;
        option.textContent = `${cls.displayName} (${cls.count})`;
        chatTagsFilter.appendChild(option);
      });

      // Populate custom dropdown with checkboxes
      if (tagsDropdownItems) {
        // Add "Clear All" item
        const allItem = document.createElement('button');
        allItem.type = 'button';
        allItem.classList.add('dropdown-item', 'text-muted', 'small');
        allItem.setAttribute('data-tag-value', '');
        allItem.setAttribute('data-search-role', 'action');
        allItem.textContent = 'Clear All';
        allItem.style.display = 'block';
        allItem.style.width = '100%';
        allItem.style.textAlign = 'left';
        tagsDropdownItems.appendChild(allItem);

        // Divider after Clear All
        const divider1 = document.createElement('div');
        divider1.classList.add('dropdown-divider');
        tagsDropdownItems.appendChild(divider1);

        // Render regular tags
        allTags.forEach(tag => {
          const item = document.createElement('button');
          item.type = 'button';
          item.classList.add('dropdown-item', 'd-flex', 'align-items-center');
          item.setAttribute('data-tag-value', tag.name);
          item.setAttribute('data-search-role', 'item');
          item.dataset.searchLabel = tag.displayName;
          item.style.display = 'flex';
          item.style.width = '100%';
          item.style.textAlign = 'left';

          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.classList.add('form-check-input', 'me-2', 'tag-checkbox');
          checkbox.style.pointerEvents = 'none';
          checkbox.style.minWidth = '16px';

          const label = document.createElement('span');
          label.textContent = `${tag.name} (${tag.count})`;

          item.appendChild(checkbox);
          item.appendChild(label);
          tagsDropdownItems.appendChild(item);
        });

        // Render classification items with visual distinction
        if (classificationItems.length > 0) {
          // Divider before classifications
          const divider2 = document.createElement('div');
          divider2.classList.add('dropdown-divider');
          tagsDropdownItems.appendChild(divider2);

          // Small header
          const header = document.createElement('div');
          header.classList.add('dropdown-header', 'small', 'text-muted', 'px-3', 'py-1');
          header.textContent = 'Classifications';
          tagsDropdownItems.appendChild(header);

          classificationItems.forEach(cls => {
            const item = document.createElement('button');
            item.type = 'button';
            item.classList.add('dropdown-item', 'd-flex', 'align-items-center');
            item.setAttribute('data-tag-value', cls.name);
            item.setAttribute('data-search-role', 'item');
            item.dataset.searchLabel = cls.displayName;
            item.style.display = 'flex';
            item.style.width = '100%';
            item.style.textAlign = 'left';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.classList.add('form-check-input', 'me-2', 'tag-checkbox');
            checkbox.style.pointerEvents = 'none';
            checkbox.style.minWidth = '16px';

            const icon = document.createElement('i');
            icon.classList.add('bi', 'bi-bookmark-fill', 'me-1');
            icon.style.color = cls.color;
            icon.style.fontSize = '0.75rem';

            const label = document.createElement('span');
            label.textContent = `${cls.displayName} (${cls.count})`;

            item.appendChild(checkbox);
            item.appendChild(icon);
            item.appendChild(label);
            tagsDropdownItems.appendChild(item);
          });
        }

        tagsSearchController?.applyFilter(tagsSearchInput ? tagsSearchInput.value : '');
      }

      showTagsDropdown();
    } else {
      hideTagsDropdown();
    }
  } catch (error) {
    console.error('Error loading tags:', error);
    hideTagsDropdown('Unable to load tags');
  }
}

function showTagsDropdown() {
  setTagsDropdownReadyState();
}

function hideTagsDropdown(message = 'No tags available for this scope') {
  setTagsDropdownEmptyState(message);
}

function resetTagSelectionState() {
  if (chatTagsFilter) {
    Array.from(chatTagsFilter.options).forEach(option => {
      option.selected = false;
    });
  }

  if (tagsDropdownItems) {
    tagsDropdownItems.querySelectorAll('.tag-checkbox').forEach(checkbox => {
      checkbox.checked = false;
    });
  }

  tagsSearchController?.resetFilter();
  syncTagsDropdownButtonText();
  filterDocumentsBySelectedTags();
}

/* ---------------------------------------------------------------------------
   Sync Tags Dropdown Button Text with Selection State
--------------------------------------------------------------------------- */
function syncTagsDropdownButtonText() {
  if (!tagsDropdownButton || !tagsDropdownItems || tagsDropdownState !== 'ready') return;

  const checkedItems = tagsDropdownItems.querySelectorAll('.tag-checkbox:checked');
  const count = checkedItems.length;
  const textEl = tagsDropdownButton.querySelector('.selected-tags-text');
  if (!textEl) return;

  if (count === 0) {
    textEl.textContent = 'All Tags';
  } else if (count === 1) {
    const parentItem = checkedItems[0].closest('.dropdown-item');
    const tagValue = parentItem ? parentItem.getAttribute('data-tag-value') : '';
    textEl.textContent = tagValue || '1 tag selected';
  } else {
    textEl.textContent = `${count} tags selected`;
  }
}


export async function ensureDocumentPickerReady(options = {}) {
  const { reload = false, showLoading = !hasResolvedTagsState } = options;

  if (!docSelectEl && !scopeDropdownButton && !tagsDropdownButton && !docDropdownButton) {
    return false;
  }

  if (scopeLocked === true) {
    rebuildScopeDropdownWithLock();
  } else {
    buildScopeDropdown();
  }

  if (reload || !hasResolvedTagsState) {
    await refreshDocumentsAndTags({ showLoading });
  } else {
    filterDocumentsBySelectedTags();
  }

  try {
    const dropdownInstance = bootstrap.Dropdown.getInstance(docDropdownButton);
    if (dropdownInstance) {
      dropdownInstance.update();
    }
  } catch (err) {
    console.error('Error updating document dropdown:', err);
  }

  handleDocumentSelectChange();
  return true;
}


export async function ensureSearchDocumentsVisible() {
  if (!searchDocumentsBtn || !searchDocumentsContainer) {
    return false;
  }

  userWorkspaceContextActive = true;
  syncAssignedKnowledgeButtonState();
  await showSearchDocumentsPanel();
  return ensureDocumentPickerReady({ reload: true, showLoading: !hasResolvedTagsState });
}


export function activateUserWorkspaceContextForChatUpload() {
  if (assignedKnowledgeActive && !assignedKnowledgeAllowsUserContext) {
    return false;
  }

  userWorkspaceContextActive = true;
  syncAssignedKnowledgeButtonState();
  return true;
}


export async function selectWorkspaceDocumentForChatUpload(documentId, options = {}) {
  const normalizedDocumentId = String(documentId || '').trim();
  if (!normalizedDocumentId) {
    return false;
  }

  if (!activateUserWorkspaceContextForChatUpload()) {
    return false;
  }

  const workspaceScope = String(options.workspaceScope || options.scope || '').trim().toLowerCase();
  const groupId = String(options.groupId || options.group_id || '').trim();
  const currentScopes = getEffectiveScopes();
  if (workspaceScope === 'group' && groupId && !currentScopes.groupIds.includes(groupId) && scopeLocked !== true) {
    await setEffectiveScopes(
      {
        ...currentScopes,
        groupIds: [...currentScopes.groupIds, groupId],
      },
      {
        source: 'chat-upload-workspace-document',
        reload: true,
      }
    );
  } else if (workspaceScope !== 'group' && !currentScopes.personal && scopeLocked !== true) {
    await setEffectiveScopes(
      {
        ...currentScopes,
        personal: true,
      },
      {
        source: 'chat-upload-workspace-document',
        reload: true,
      }
    );
  }

  await ensureSearchDocumentsVisible();

  let documentOption = getDocumentOptionById(normalizedDocumentId);
  if (!documentOption) {
    await ensureDocumentPickerReady({ reload: true, showLoading: false });
    documentOption = getDocumentOptionById(normalizedDocumentId);
  }

  if (!documentOption) {
    return false;
  }

  applyDocumentSelectionForIds([normalizedDocumentId], {
    replaceSelection: options.replaceSelection !== false,
  });
  syncDropdownButtonText();
  handleDocumentSelectChange();
  syncAssignedKnowledgeButtonState();
  return true;
}


export async function selectPersonalWorkspaceDocumentForChatUpload(documentId, options = {}) {
  return selectWorkspaceDocumentForChatUpload(documentId, {
    ...options,
    workspaceScope: 'personal',
  });
}


function openDropdown(buttonElement) {
  if (!buttonElement) {
    return false;
  }

  try {
    bootstrap.Dropdown.getOrCreateInstance(buttonElement, {
      autoClose: 'outside'
    }).show();
    buttonElement.focus();
    return true;
  } catch (err) {
    console.error('Error opening dropdown:', err);
    return false;
  }
}


export function openScopeDropdown() {
  return openDropdown(scopeDropdownButton);
}


export function openTagsDropdown() {
  if (!tagsDropdown || !tagsDropdownButton) {
    return false;
  }

  if (tagsDropdownState !== 'ready' || !tagsDropdownItems || !tagsDropdownItems.children.length) {
    return false;
  }

  return openDropdown(tagsDropdownButton);
}

/* ---------------------------------------------------------------------------
   Get Selected Tags
--------------------------------------------------------------------------- */
export function getSelectedTags() {
  if (!chatTagsFilter) return [];
  return Array.from(chatTagsFilter.selectedOptions).map(opt => opt.value);
}

/* ---------------------------------------------------------------------------
   Filter Document Dropdown by Selected Tags
   Uses DOM removal instead of CSS hiding to guarantee items disappear.
--------------------------------------------------------------------------- */
export function filterDocumentsBySelectedTags() {
  if (!docDropdownItems) return;

  // 1) Re-add any items previously removed by this filter (preserve order)
  for (let i = tagFilteredOutItems.length - 1; i >= 0; i--) {
    const { element, nextSibling } = tagFilteredOutItems[i];
    if (nextSibling && nextSibling.parentNode === docDropdownItems) {
      docDropdownItems.insertBefore(element, nextSibling);
    } else {
      docDropdownItems.appendChild(element);
    }
  }
  tagFilteredOutItems = [];

  const selectedTags = getSelectedTags();

  // Helper: check if a document matches by tag or classification
  function matchesSelection(tags, classification) {
    const matchesByTag = tags.some(tag => selectedTags.includes(tag));
    if (matchesByTag) return true;
    const docCls = classification || '';
    return selectedTags.some(sel => {
      if (sel === '__unclassified__') return !docCls || docCls === '' || docCls.toLowerCase() === 'none';
      return docCls === sel;
    });
  }

  // 2) If tags/classifications are selected, remove non-matching items from the DOM
  if (selectedTags.length > 0) {
    const items = Array.from(docDropdownItems.querySelectorAll('.dropdown-item'));
    items.forEach(item => {
      const docId = item.getAttribute('data-document-id');
      // "All Documents" item stays
      if (docId === '' || docId === null) return;

      let docTags = [];
      try { docTags = JSON.parse(item.dataset.tags || '[]'); } catch (e) { docTags = []; }
      const docClassification = item.dataset.classification || '';

      if (!matchesSelection(docTags, docClassification)) {
        const nextSibling = item.nextElementSibling;
        docDropdownItems.removeChild(item);
        tagFilteredOutItems.push({ element: item, nextSibling });
      }
    });
  }

  // 3) Sync hidden select to keep state consistent
  if (docSelectEl) {
    Array.from(docSelectEl.options).forEach(opt => {
      if (opt.value === '') return;
      if (selectedTags.length === 0) { opt.disabled = false; return; }

      let optTags = [];
      try { optTags = JSON.parse(opt.dataset.tags || '[]'); } catch (e) { optTags = []; }
      const optClassification = opt.dataset.classification || '';
      opt.disabled = !matchesSelection(optTags, optClassification);
    });
  }

  documentSearchController?.applyFilter(docSearchInput ? docSearchInput.value : '');
}

/* ---------------------------------------------------------------------------
   Sync Dropdown Button Text with Selection State
--------------------------------------------------------------------------- */
function syncDropdownButtonText() {
  if (!docDropdownButton || !docSelectEl) return;

  const selectedDocumentOptions = Array.from(docSelectEl.selectedOptions).filter(option => option.value);
  const count = selectedDocumentOptions.length;
  const textEl = docDropdownButton.querySelector(".selected-document-text");
  if (!textEl) return;

  if (count === 0) {
    textEl.textContent = isExplicitDocumentSelectionMode() ? "Select Documents" : "All Documents";
  } else if (count === 1) {
    const selectedDocumentId = selectedDocumentOptions[0].value;
    const labelSpan = docDropdownItems
      ? docDropdownItems.querySelector(`.dropdown-item[data-document-id="${selectedDocumentId}"] span`)
      : null;
    textEl.textContent = labelSpan ? labelSpan.textContent : "1 document selected";
  } else {
    textEl.textContent = `${count} documents selected`;
  }

  updateDocumentDropdownActionState();
}

/* ---------------------------------------------------------------------------
   UI Event Listeners
--------------------------------------------------------------------------- */

// Scope dropdown: prevent closing when clicking inside
if (scopeDropdownMenu) {
  scopeDropdownMenu.addEventListener('click', function(e) {
    e.stopPropagation();
  });
}

// Scope dropdown: click handler for scope items
if (scopeDropdownItems) {
  scopeDropdownItems.addEventListener('click', function(e) {
    e.stopPropagation();

    // Guard: prevent changes when scope is locked
    if (scopeLocked === true || (assignedKnowledgeActive && !assignedKnowledgeAllowsUserContext)) { e.preventDefault(); return; }

    const item = e.target.closest('.dropdown-item');
    if (!item) return;

    const action = item.getAttribute('data-scope-action');
    const scopeValue = item.getAttribute('data-scope-value');

    if (action === 'toggle-all') {
      // Toggle all checkboxes
      const allCb = item.querySelector('.scope-checkbox-all');
      if (allCb) {
        const newState = !allCb.checked;
        allCb.checked = newState;
        allCb.indeterminate = false;
        scopeDropdownItems.querySelectorAll('.scope-checkbox').forEach(cb => {
          cb.checked = newState;
        });
      }
      onScopeChanged();
      return;
    }

    if (scopeValue) {
      // Toggle individual checkbox
      const cb = item.querySelector('.scope-checkbox');
      if (cb) {
        cb.checked = !cb.checked;
      }
      onScopeChanged();
    }
  });
}

if (chatTagsFilter) {
  chatTagsFilter.addEventListener("change", () => {
    filterDocumentsBySelectedTags();
  });
}

// Tags dropdown: prevent closing when clicking inside
if (tagsDropdownItems) {
  if (tagsDropdownMenu) {
    tagsDropdownMenu.addEventListener('click', function(e) {
      e.stopPropagation();
    });
  }

  // Click handler for tag items with checkbox toggling
  tagsDropdownItems.addEventListener('click', function(e) {
    e.stopPropagation();
    if (assignedKnowledgeActive && !assignedKnowledgeAllowsUserContext) {
      e.preventDefault();
      return;
    }
    const item = e.target.closest('.dropdown-item');
    if (!item) return;

    const tagValue = item.getAttribute('data-tag-value');

    // "Clear All" item unchecks everything
    if (tagValue === '' || tagValue === null) {
      tagsDropdownItems.querySelectorAll('.tag-checkbox').forEach(cb => {
        cb.checked = false;
      });
      // Clear hidden select
      if (chatTagsFilter) {
        Array.from(chatTagsFilter.options).forEach(opt => { opt.selected = false; });
      }
      syncTagsDropdownButtonText();
      filterDocumentsBySelectedTags();
      return;
    }

    // Toggle checkbox
    const checkbox = item.querySelector('.tag-checkbox');
    if (checkbox) {
      checkbox.checked = !checkbox.checked;
    }

    // Sync hidden select with checked state
    if (chatTagsFilter) {
      Array.from(chatTagsFilter.options).forEach(opt => { opt.selected = false; });
      tagsDropdownItems.querySelectorAll('.dropdown-item').forEach(di => {
        const cb = di.querySelector('.tag-checkbox');
        const val = di.getAttribute('data-tag-value');
        if (cb && cb.checked && val) {
          const matchingOpt = Array.from(chatTagsFilter.options).find(o => o.value === val);
          if (matchingOpt) matchingOpt.selected = true;
        }
      });
    }

    syncTagsDropdownButtonText();
    filterDocumentsBySelectedTags();
  });
}

if (searchDocumentsBtn) {
  searchDocumentsBtn.addEventListener("click", async function () {
    if (!searchDocumentsContainer) return;

    if (assignedKnowledgeActive) {
      if (!assignedKnowledgeAllowsUserContext) {
        userWorkspaceContextActive = false;
        hideSearchDocumentsPanel();
        setAssignedKnowledgeControlState(true);
        showToast('This agent uses assigned knowledge. Ask the agent what knowledge it has for details.', 'info');
        return;
      }

      if (userWorkspaceContextActive) {
        userWorkspaceContextActive = false;
        hideSearchDocumentsPanel();
        setAssignedKnowledgeControlState(true);
      } else {
        userWorkspaceContextActive = true;
        await ensureSearchDocumentsVisible();
        setAssignedKnowledgeControlState(true);
      }
      return;
    }

    if (this.classList.contains("active")) {
      hideSearchDocumentsPanel();
    } else {
      ensureSearchDocumentsVisible();
    }
  });
}

if (docSelectEl) {
  // Listen for changes on the document select dropdown (this is now hidden and used as state keeper)
  docSelectEl.addEventListener("change", handleDocumentSelectChange);
}

if (documentActionSelect) {
  documentActionSelect.addEventListener("change", function() {
    syncDropdownButtonText();
  });
}

// Add event listeners for custom document dropdown
if (docDropdownMenu) {
  // Prevent dropdown menu from closing when clicking inside
  docDropdownMenu.addEventListener('click', function(e) {
    e.stopPropagation();
  });

  // Additional event handlers to prevent dropdown from closing
  docDropdownMenu.addEventListener('keydown', function(e) {
    e.stopPropagation();
  });

  docDropdownMenu.addEventListener('keyup', function(e) {
    e.stopPropagation();
  });
}

if (docDropdownItems) {
  // Prevent dropdown menu from closing when clicking inside items container
  docDropdownItems.addEventListener('click', function(e) {
    e.stopPropagation();
  });

  // Multi-select click handler with checkbox toggling
  docDropdownItems.addEventListener('click', function(e) {
    if (assignedKnowledgeActive && !assignedKnowledgeAllowsUserContext) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    const item = e.target.closest('.dropdown-item');
    if (!item) return;

    const docId = item.getAttribute('data-document-id');

    // The top picker action follows the active document search when present.
    if (docId === '' || docId === null) {
      const actionState = getDocumentDropdownActionState();

      if (actionState.disabled) {
        return;
      }

      if (actionState.mode === 'searched') {
        applyDocumentSelectionForIds(actionState.documentIds, {
          clearMatchingDocuments: actionState.shouldClearSelections,
          replaceSelection: !actionState.shouldClearSelections,
        });
      } else if (isExplicitDocumentSelectionMode()) {
        const selectableDocumentIds = new Set(getSelectableDocumentOptions().map(option => option.value));
        const shouldClearSelections = areAllSelectableDocumentsSelected();

        docDropdownItems.querySelectorAll('.dropdown-item').forEach(dropdownItem => {
          const itemDocumentId = dropdownItem.getAttribute('data-document-id');
          const checkbox = dropdownItem.querySelector('.doc-checkbox');
          if (!checkbox || !itemDocumentId) {
            return;
          }

          checkbox.checked = !shouldClearSelections && selectableDocumentIds.has(itemDocumentId);
        });

        if (docSelectEl) {
          Array.from(docSelectEl.options).forEach(option => {
            if (!option.value) {
              option.selected = false;
              return;
            }

            option.selected = !shouldClearSelections && !option.disabled;
          });
        }
      } else {
        docDropdownItems.querySelectorAll('.doc-checkbox').forEach(cb => {
          cb.checked = false;
        });
        if (docSelectEl) {
          Array.from(docSelectEl.options).forEach(opt => { opt.selected = false; });
        }
      }

      syncDropdownButtonText();
      handleDocumentSelectChange();
      return;
    }

    // Toggle checkbox
    const checkbox = item.querySelector('.doc-checkbox');
    if (checkbox) {
      checkbox.checked = !checkbox.checked;
    }

    // Sync hidden select with checked state
    if (docSelectEl) {
      Array.from(docSelectEl.options).forEach(opt => { opt.selected = false; });
      docDropdownItems.querySelectorAll('.dropdown-item').forEach(di => {
        const cb = di.querySelector('.doc-checkbox');
        const id = di.getAttribute('data-document-id');
        if (cb && cb.checked && id) {
          const matchingOpt = Array.from(docSelectEl.options).find(o => o.value === id);
          if (matchingOpt) matchingOpt.selected = true;
        }
      });
    }

    syncDropdownButtonText();
    handleDocumentSelectChange();

    // Do NOT close dropdown - allow multiple selections
  });
}

/* ---------------------------------------------------------------------------
   Handle Document Selection & Update UI
--------------------------------------------------------------------------- */
export function handleDocumentSelectChange() {
  if (!docSelectEl) {
      console.error("Document select element not found, cannot update UI.");
      return;
  }

  // Sync button text from current hidden select state
  syncDropdownButtonText();
  window.dispatchEvent(new CustomEvent('chat:document-selection-changed', {
    detail: {
      documentIds: Array.from(docSelectEl.selectedOptions).map(option => option.value).filter(Boolean),
    },
  }));
}


// --- Ensure initial state is set after documents are loaded ---
// The call within loadAllDocs -> populateDocumentSelectScope handles the initial setup.

// Initialize the dropdown on page load
document.addEventListener('DOMContentLoaded', function() {
  // Initialize scope dropdown
  if (scopeDropdownButton) {
    try {
      const scopeDropdownEl = document.getElementById('scope-dropdown');
      if (scopeDropdownEl) {
        initializeSearchFilterDropdown({
          dropdownEl: scopeDropdownEl,
          buttonEl: scopeDropdownButton,
          menuEl: scopeDropdownMenu,
          itemsContainerEl: scopeDropdownItems,
          searchInputEl: scopeSearchInput,
          searchController: scopeSearchController,
        });
      }
    } catch (err) {
      console.error("Error initializing scope dropdown:", err);
    }
  }

  if (tagsDropdown && tagsDropdownButton) {
    try {
      initializeSearchFilterDropdown({
        dropdownEl: tagsDropdown,
        buttonEl: tagsDropdownButton,
        menuEl: tagsDropdownMenu,
        itemsContainerEl: tagsDropdownItems,
        searchInputEl: tagsSearchInput,
        searchController: tagsSearchController,
      });
    } catch (err) {
      console.error("Error initializing tags dropdown:", err);
    }
  }

  if (docDropdownButton) {
    try {
      if (docDropdown) {
        initializeSearchFilterDropdown({
          dropdownEl: docDropdown,
          buttonEl: docDropdownButton,
          menuEl: docDropdownMenu,
          itemsContainerEl: docDropdownItems,
          searchInputEl: docSearchInput,
          searchController: documentSearchController,
          openUpOnDesktop: true,
          onShown: initializeDocumentDropdown,
        });
      }
    } catch (err) {
      console.error("Error initializing bootstrap dropdown:", err);
    }
  }

  // --- Scope Lock: Dual-mode modal event wiring ---
  const confirmToggleBtn = document.getElementById('confirm-scope-lock-toggle-btn');
  if (confirmToggleBtn) {
    confirmToggleBtn.addEventListener('click', async () => {
      const conversationId = window.currentConversationId;
      if (!conversationId) return;

      const newState = scopeLocked === true ? false : true;

      try {
        confirmToggleBtn.disabled = true;
        confirmToggleBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>' +
          (newState ? 'Locking...' : 'Unlocking...');
        await toggleScopeLock(conversationId, newState);

        // Hide modal
        const modalEl = document.getElementById('scopeLockModal');
        if (modalEl) {
          const modalInstance = bootstrap.Modal.getInstance(modalEl);
          if (modalInstance) modalInstance.hide();
        }
      } catch (err) {
        console.error('Failed to toggle scope lock:', err);
      } finally {
        confirmToggleBtn.disabled = false;
      }
    });
  }

  const scopeLockModal = document.getElementById('scopeLockModal');
  if (scopeLockModal) {
    scopeLockModal.addEventListener('show.bs.modal', () => {
      const titleEl = document.getElementById('scopeLockModalLabel');
      const descEl = document.getElementById('scope-lock-modal-description');
      const alertEl = document.getElementById('scope-lock-modal-alert');
      const toggleBtn = document.getElementById('confirm-scope-lock-toggle-btn');
      const listEl = document.getElementById('locked-workspaces-list');

      // Build workspace list
      const workspaceItems = [];
      for (const ctx of lockedContexts) {
        let name = '';
        let icon = '';
        if (ctx.scope === 'personal') {
          name = 'Personal';
          icon = 'bi-person';
        } else if (ctx.scope === 'group') {
          name = groupIdToName[ctx.id] || ctx.id;
          icon = 'bi-people';
        } else if (ctx.scope === 'public') {
          name = publicWorkspaceIdToName[ctx.id] || ctx.id;
          icon = 'bi-globe';
        }
        if (name) {
          workspaceItems.push({ icon, name });
        }
      }

      if (listEl) {
        listEl.textContent = '';
        if (workspaceItems.length > 0) {
          const listLabel = scopeLocked === true ? 'Currently locked to:' : 'Will lock to:';
          const listLabelEl = document.createElement('p');
          listLabelEl.className = 'small text-muted mb-2';
          listLabelEl.textContent = listLabel;

          const listGroupEl = document.createElement('ul');
          listGroupEl.className = 'list-group list-group-flush';

          workspaceItems.forEach(({ icon, name }) => {
            const listItemEl = document.createElement('li');
            listItemEl.className = 'list-group-item';

            const iconEl = document.createElement('i');
            iconEl.className = `bi ${icon} me-2`;

            const nameEl = document.createElement('span');
            nameEl.textContent = name;

            listItemEl.appendChild(iconEl);
            listItemEl.appendChild(nameEl);
            listGroupEl.appendChild(listItemEl);
          });

          listEl.appendChild(listLabelEl);
          listEl.appendChild(listGroupEl);
        } else {
          const emptyStateEl = document.createElement('p');
          emptyStateEl.className = 'text-muted';
          emptyStateEl.textContent = 'No specific workspaces recorded.';
          listEl.appendChild(emptyStateEl);
        }
      }

      if (scopeLocked === true) {
        // Currently locked — show unlock mode
        if (titleEl) titleEl.innerHTML = '<i class="bi bi-unlock me-2"></i>Unlock Workspace Scope';
        if (descEl) descEl.textContent = 'This conversation\'s scope is locked to prevent accidental cross-contamination with other data sources.';
        if (alertEl) {
          alertEl.className = 'alert alert-warning mb-0';
          alertEl.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Unlocking allows you to select any workspace for this conversation. You can re-lock it later.';
        }
        if (toggleBtn) {
          toggleBtn.className = 'btn btn-warning';
          toggleBtn.innerHTML = '<i class="bi bi-unlock me-1"></i>Unlock Scope';
        }

        // Check if admin enforces scope lock — hide unlock button
        if (window.appSettings && window.appSettings.enforce_workspace_scope_lock) {
          if (toggleBtn) toggleBtn.classList.add('d-none');
          if (alertEl) {
            alertEl.className = 'alert alert-info mb-0';
            alertEl.innerHTML = '<i class="bi bi-info-circle me-1"></i>Workspace scope lock is enforced by your administrator. The scope cannot be unlocked.';
          }
        } else {
          if (toggleBtn) toggleBtn.classList.remove('d-none');
        }
      } else {
        // Currently unlocked — show lock mode
        if (titleEl) titleEl.innerHTML = '<i class="bi bi-lock me-2"></i>Lock Workspace Scope';
        if (descEl) descEl.textContent = 'Re-lock the scope to restrict this conversation to the workspaces that produced search results.';
        if (alertEl) {
          alertEl.className = 'alert alert-info mb-0';
          alertEl.innerHTML = '<i class="bi bi-info-circle me-1"></i>Locking will restrict the scope dropdown to only the workspaces listed above.';
        }
        if (toggleBtn) {
          toggleBtn.className = 'btn btn-success';
          toggleBtn.innerHTML = '<i class="bi bi-lock me-1"></i>Lock Scope';
          toggleBtn.classList.remove('d-none');
        }
      }
    });
  }
});
