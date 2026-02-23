// chat-documents.js

import { showToast } from "./chat-toast.js";

export const docScopeSelect = document.getElementById("doc-scope-select");
const searchDocumentsBtn = document.getElementById("search-documents-btn");
const docSelectEl = document.getElementById("document-select"); // Hidden select element
const searchDocumentsContainer = document.getElementById("search-documents-container"); // Container for scope/doc/class

// Custom dropdown elements
const docDropdownButton = document.getElementById("document-dropdown-button");
const docDropdownItems = document.getElementById("document-dropdown-items");
const docDropdownMenu = document.getElementById("document-dropdown-menu");
const docSearchInput = document.getElementById("document-search-input");

// Tags filter elements
const chatTagsFilter = document.getElementById("chat-tags-filter");
const tagsDropdown = document.getElementById("tags-dropdown");
const tagsDropdownButton = document.getElementById("tags-dropdown-button");
const tagsDropdownItems = document.getElementById("tags-dropdown-items");

// Scope dropdown elements
const scopeDropdownButton = document.getElementById("scope-dropdown-button");
const scopeDropdownItems = document.getElementById("scope-dropdown-items");
const scopeDropdownMenu = document.getElementById("scope-dropdown-menu");

// We'll store personalDocs/groupDocs/publicDocs in memory once loaded:
export let personalDocs = [];
export let groupDocs = [];
export let publicDocs = [];

// Items removed from the DOM by tag filtering (stored so they can be re-added)
// Each entry: { element, nextSibling }
let tagFilteredOutItems = [];

// Scope lock state
let scopeLocked = null;    // null = auto-lockable, true = locked, false = user-unlocked
let lockedContexts = [];   // Array of {scope, id} identifying locked workspaces

// Build name maps from server-provided data (fixes activeGroupName bug)
const groupIdToName = {};
(window.userGroups || []).forEach(g => { groupIdToName[g.id] = g.name; });

const publicWorkspaceIdToName = {};
(window.userVisiblePublicWorkspaces || []).forEach(ws => { publicWorkspaceIdToName[ws.id] = ws.name; });

// Multi-scope selection state
let selectedPersonal = true;
let selectedGroupIds = (window.userGroups || []).map(g => g.id);
let selectedPublicWorkspaceIds = (window.userVisiblePublicWorkspaces || []).map(ws => ws.id);

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

  // Reload docs for the new scope
  loadAllDocs().then(() => { loadTagsForScope(); });
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
    loadAllDocs().then(() => { loadTagsForScope(); });
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
export function resetScopeLock() {
  scopeLocked = null;
  lockedContexts = [];

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];
  selectedPersonal = true;
  selectedGroupIds = groups.map(g => g.id);
  selectedPublicWorkspaceIds = publicWorkspaces.map(ws => ws.id);

  buildScopeDropdown();
  updateScopeLockIcon();
  updateHeaderLockIcon();

  // Reload documents for the full "All" scope
  loadAllDocs().then(() => { loadTagsForScope(); });
}

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
}

/* ---------------------------------------------------------------------------
   Build the Scope Dropdown (called once on init)
--------------------------------------------------------------------------- */
function buildScopeDropdown() {
  if (!scopeDropdownItems) return;

  scopeDropdownItems.innerHTML = "";

  const groups = window.userGroups || [];
  const publicWorkspaces = window.userVisiblePublicWorkspaces || [];

  // "Select All" / "Clear All" toggle
  const allItem = document.createElement("button");
  allItem.type = "button";
  allItem.classList.add("dropdown-item", "d-flex", "align-items-center", "fw-bold");
  allItem.setAttribute("data-scope-action", "toggle-all");
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

/* ---------------------------------------------------------------------------
   Handle scope change — reload docs and tags
--------------------------------------------------------------------------- */
function onScopeChanged() {
  syncScopeStateFromCheckboxes();
  syncScopeButtonText();
  // Reload docs and tags for the new scope
  loadAllDocs().then(() => {
    loadTagsForScope();
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

  // Always add an "All Documents" option to the hidden select
  const allOpt = document.createElement("option");
  allOpt.value = ""; // Use empty string for "All"
  allOpt.textContent = "All Documents"; // Consistent label
  docSelectEl.appendChild(allOpt);

  // Add "All Documents" item to custom dropdown
  if (docDropdownItems) {
    const allItem = document.createElement("button");
    allItem.type = "button";
    allItem.classList.add("dropdown-item");
    allItem.setAttribute("data-document-id", "");
    allItem.textContent = "All Documents";
    allItem.style.display = "block";
    allItem.style.width = "100%";
    allItem.style.textAlign = "left";
    docDropdownItems.appendChild(allItem);
  }

  let finalDocs = [];

  // Add personal docs if personal scope is selected
  if (scopes.personal) {
    const pDocs = personalDocs.map((d) => ({
      id: d.id,
      label: `[Personal] ${d.title || d.file_name}`,
      tags: d.tags || [],
      classification: d.document_classification || '',
    }));
    finalDocs = finalDocs.concat(pDocs);
  }

  // Add group docs — label each with its group name
  if (scopes.groupIds.length > 0) {
    const gDocs = groupDocs.map((d) => ({
      id: d.id,
      label: `[Group: ${groupIdToName[d.group_id] || "Unknown"}] ${d.title || d.file_name}`,
      tags: d.tags || [],
      classification: d.document_classification || '',
    }));
    finalDocs = finalDocs.concat(gDocs);
  }

  // Add public docs — label each with its workspace name
  if (scopes.publicWorkspaceIds.length > 0) {
    // Filter publicDocs to only those in selected workspaces
    const selectedWsSet = new Set(scopes.publicWorkspaceIds);
    const pubDocs = publicDocs
      .filter(d => selectedWsSet.has(d.public_workspace_id))
      .map((d) => ({
        id: d.id,
        label: `[Public: ${publicWorkspaceIdToName[d.public_workspace_id] || "Unknown"}] ${d.title || d.file_name}`,
        tags: d.tags || [],
        classification: d.document_classification || '',
      }));
    finalDocs = finalDocs.concat(pubDocs);
  }

  // Add document options to the hidden select and populate the custom dropdown
  finalDocs.forEach((doc) => {
    // Add to hidden select
    const opt = document.createElement("option");
    opt.value = doc.id;
    opt.textContent = doc.label;
    opt.dataset.tags = JSON.stringify(doc.tags || []);
    opt.dataset.classification = doc.classification || '';
    docSelectEl.appendChild(opt);

    // Add to custom dropdown
    if (docDropdownItems) {
      const dropdownItem = document.createElement("button");
      dropdownItem.type = "button";
      dropdownItem.classList.add("dropdown-item", "d-flex", "align-items-center");
      dropdownItem.setAttribute("data-document-id", doc.id);
      dropdownItem.setAttribute("title", doc.label);
      dropdownItem.dataset.tags = JSON.stringify(doc.tags || []);
      dropdownItem.dataset.classification = doc.classification || '';
      dropdownItem.style.display = "flex";
      dropdownItem.style.width = "100%";
      dropdownItem.style.textAlign = "left";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.classList.add("form-check-input", "me-2", "doc-checkbox");
      checkbox.style.pointerEvents = "none"; // Click handled by button
      checkbox.style.minWidth = "16px";

      const label = document.createElement("span");
      label.textContent = doc.label;
      label.style.overflow = "hidden";
      label.style.textOverflow = "ellipsis";
      label.style.whiteSpace = "nowrap";

      dropdownItem.appendChild(checkbox);
      dropdownItem.appendChild(label);
      docDropdownItems.appendChild(dropdownItem);
    }
  });

  // Show/hide search based on number of documents
  if (docSearchInput && docDropdownItems) {
    const documentsCount = finalDocs.length;
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

  // Reset to "All Documents" (no specific documents selected)
  // With multi-select, clear all selections
  Array.from(docSelectEl.options).forEach(opt => { opt.selected = false; });
  if (docDropdownButton) {
    docDropdownButton.querySelector(".selected-document-text").textContent = "All Documents";

    // Clear all checkbox states
    if (docDropdownItems) {
      docDropdownItems.querySelectorAll(".doc-checkbox").forEach(cb => {
        cb.checked = false;
      });
    }
  }

  // Trigger UI update after populating
  handleDocumentSelectChange();
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
  return null; // Not found in any list
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
  if (!docDropdownMenu) return;

  // Clear any leftover search-filter inline styles on visible items
  docDropdownItems.querySelectorAll('.dropdown-item').forEach(item => {
    item.removeAttribute('data-filtered');
    item.style.display = '';
  });

  // Re-apply tag filter (DOM removal approach — no CSS issues)
  filterDocumentsBySelectedTags();

  // Size the dropdown to fill its parent container
  const parentContainer = docDropdownButton.closest('.flex-grow-1');
  const maxWidth = parentContainer ? parentContainer.offsetWidth : 400;

  docDropdownMenu.style.maxWidth = `${maxWidth}px`;
  docDropdownMenu.style.width = `${maxWidth}px`;

  // Ensure dropdown stays within viewport bounds
  const menuRect = docDropdownMenu.getBoundingClientRect();
  const viewportHeight = window.innerHeight;

  if (menuRect.bottom > viewportHeight) {
    const maxPossibleHeight = viewportHeight - menuRect.top - 10;
    docDropdownMenu.style.maxHeight = `${maxPossibleHeight}px`;

    if (docDropdownItems) {
      const searchContainer = docDropdownMenu.querySelector('.document-search-container');
      const searchHeight = searchContainer ? searchContainer.offsetHeight : 40;
      docDropdownItems.style.maxHeight = `${maxPossibleHeight - searchHeight}px`;
    }
  }
}
/* ---------------------------------------------------------------------------
   Load Tags for Selected Scope
--------------------------------------------------------------------------- */
export async function loadTagsForScope() {
  if (!chatTagsFilter) return;

  // Clear existing options in both hidden select and custom dropdown
  chatTagsFilter.innerHTML = '';
  if (tagsDropdownItems) tagsDropdownItems.innerHTML = '';

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
      showTagsDropdown();

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
      }
    } else {
      hideTagsDropdown();
    }
  } catch (error) {
    console.error('Error loading tags:', error);
    hideTagsDropdown();
  }
}

function showTagsDropdown() {
  if (tagsDropdown) tagsDropdown.style.display = 'block';
}

function hideTagsDropdown() {
  if (tagsDropdown) tagsDropdown.style.display = 'none';
}

/* ---------------------------------------------------------------------------
   Sync Tags Dropdown Button Text with Selection State
--------------------------------------------------------------------------- */
function syncTagsDropdownButtonText() {
  if (!tagsDropdownButton || !tagsDropdownItems) return;

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

/* ---------------------------------------------------------------------------
   Get Selected Tags
--------------------------------------------------------------------------- */
export function getSelectedTags() {
  if (!chatTagsFilter) return [];
  // Check if the tags dropdown is visible (the hidden select is always display:none via d-none class)
  if (tagsDropdown && tagsDropdown.style.display === 'none') return [];
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
}

/* ---------------------------------------------------------------------------
   Sync Dropdown Button Text with Selection State
--------------------------------------------------------------------------- */
function syncDropdownButtonText() {
  if (!docDropdownButton || !docDropdownItems) return;

  const checkedItems = docDropdownItems.querySelectorAll('.doc-checkbox:checked');
  const count = checkedItems.length;
  const textEl = docDropdownButton.querySelector(".selected-document-text");
  if (!textEl) return;

  if (count === 0) {
    textEl.textContent = "All Documents";
  } else if (count === 1) {
    // Show the single document name
    const parentItem = checkedItems[0].closest('.dropdown-item');
    const labelSpan = parentItem ? parentItem.querySelector('span') : null;
    textEl.textContent = labelSpan ? labelSpan.textContent : "1 document selected";
  } else {
    textEl.textContent = `${count} documents selected`;
  }
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
    if (scopeLocked === true) { e.preventDefault(); return; }

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
  const tagsDropdownMenu = document.getElementById("tags-dropdown-menu");
  if (tagsDropdownMenu) {
    tagsDropdownMenu.addEventListener('click', function(e) {
      e.stopPropagation();
    });
  }

  // Click handler for tag items with checkbox toggling
  tagsDropdownItems.addEventListener('click', function(e) {
    e.stopPropagation();
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
  searchDocumentsBtn.addEventListener("click", function () {
    this.classList.toggle("active");

    if (!searchDocumentsContainer) return;

    if (this.classList.contains("active")) {
      searchDocumentsContainer.style.display = "block";
      // Build the scope dropdown on first open (respect lock state)
      if (scopeLocked === true) {
        rebuildScopeDropdownWithLock();
      } else {
        buildScopeDropdown();
      }
      // Ensure initial population and state is correct when opening
      loadAllDocs().then(() => {
        // Load tags for the currently selected scope
        loadTagsForScope();
        // Update Bootstrap Popper positioning if dropdown was already initialized
        try {
          const dropdownInstance = bootstrap.Dropdown.getInstance(docDropdownButton);
          if (dropdownInstance) {
            dropdownInstance.update();
          }
        } catch (err) {
          console.error("Error updating dropdown:", err);
        }
      });
    } else {
      searchDocumentsContainer.style.display = "none";
    }
  });
}

if (docSelectEl) {
  // Listen for changes on the document select dropdown (this is now hidden and used as state keeper)
  docSelectEl.addEventListener("change", handleDocumentSelectChange);
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
    const item = e.target.closest('.dropdown-item');
    if (!item) return;

    const docId = item.getAttribute('data-document-id');

    // "All Documents" item clears all selections
    if (docId === '' || docId === null) {
      // Uncheck all checkboxes
      docDropdownItems.querySelectorAll('.doc-checkbox').forEach(cb => {
        cb.checked = false;
      });
      // Clear hidden select
      if (docSelectEl) {
        Array.from(docSelectEl.options).forEach(opt => { opt.selected = false; });
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

// Add search functionality
if (docSearchInput) {
  // Define our filtering function to ensure consistent filtering logic.
  // Items hidden by tag filter are physically removed from the DOM,
  // so querySelectorAll naturally excludes them.
  const filterDocumentItems = function(searchTerm) {
    if (!docDropdownItems) return;

    const items = docDropdownItems.querySelectorAll('.dropdown-item');
    let matchFound = false;

    items.forEach(item => {
      const docName = item.textContent.toLowerCase();

      if (!searchTerm || docName.includes(searchTerm)) {
        item.style.display = '';
        item.setAttribute('data-filtered', 'visible');
        matchFound = true;
      } else {
        item.style.display = 'none';
        item.setAttribute('data-filtered', 'hidden');
      }
    });

    // Show a message if no matches found
    const noMatchesEl = docDropdownItems.querySelector('.no-matches');
    if (!matchFound && searchTerm && searchTerm.length > 0) {
      if (!noMatchesEl) {
        const noMatchesMsg = document.createElement('div');
        noMatchesMsg.className = 'no-matches text-center text-muted py-2';
        noMatchesMsg.textContent = 'No matching documents found';
        docDropdownItems.appendChild(noMatchesMsg);
      }
    } else {
      if (noMatchesEl) {
        noMatchesEl.remove();
      }
    }
  };

  // Attach input event directly
  docSearchInput.addEventListener('input', function() {
    const searchTerm = this.value.toLowerCase().trim();
    filterDocumentItems(searchTerm);
  });

  // Also attach keyup event as a fallback
  docSearchInput.addEventListener('keyup', function() {
    const searchTerm = this.value.toLowerCase().trim();
    filterDocumentItems(searchTerm);
  });

  // Prevent dropdown from closing when clicking in search input
  docSearchInput.addEventListener('click', function(e) {
    e.stopPropagation();
    e.preventDefault();
  });

  // Prevent dropdown from closing when pressing keys in search input
  docSearchInput.addEventListener('keydown', function(e) {
    e.stopPropagation();
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
        new bootstrap.Dropdown(scopeDropdownButton, {
          autoClose: 'outside'
        });
      }
    } catch (err) {
      console.error("Error initializing scope dropdown:", err);
    }
  }

  // If search documents button exists, it needs to be clicked to show controls
  if (searchDocumentsBtn && docDropdownButton) {
    try {
      // Get the dropdown element
      const dropdownEl = document.getElementById('document-dropdown');

      if (dropdownEl) {
        // Initialize Bootstrap dropdown with the right configuration
        new bootstrap.Dropdown(docDropdownButton, {
          boundary: 'viewport',
          reference: 'toggle',
          autoClose: 'outside',
          popperConfig: {
            strategy: 'fixed',
            modifiers: [
              {
                name: 'preventOverflow',
                options: {
                  boundary: 'viewport',
                  padding: 10
                }
              }
            ]
          }
        });

        // Clear search when opening
        dropdownEl.addEventListener('show.bs.dropdown', function() {
          if (docSearchInput) {
            docSearchInput.value = '';
          }
        });

        // Adjust sizing and focus search when shown
        dropdownEl.addEventListener('shown.bs.dropdown', function() {
          initializeDocumentDropdown();
          if (docSearchInput) {
            setTimeout(() => docSearchInput.focus(), 50);
          }
        });

        // Clean up inline styles and reset state when hidden
        dropdownEl.addEventListener('hidden.bs.dropdown', function() {
          if (docSearchInput) {
            docSearchInput.value = '';
          }
          // Clear search filtering state
          if (docDropdownItems) {
            const items = docDropdownItems.querySelectorAll('.dropdown-item');
            items.forEach(item => {
              item.removeAttribute('data-filtered');
              item.style.display = '';
            });
            const noMatchesEl = docDropdownItems.querySelector('.no-matches');
            if (noMatchesEl) noMatchesEl.remove();
          }
          // Clear inline styles set by initializeDocumentDropdown so they
          // don't interfere with Bootstrap's positioning on next open
          if (docDropdownMenu) {
            docDropdownMenu.style.maxHeight = '';
            docDropdownMenu.style.maxWidth = '';
            docDropdownMenu.style.width = '';
          }
          if (docDropdownItems) {
            docDropdownItems.style.maxHeight = '';
          }
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
          workspaceItems.push(`<li class="list-group-item"><i class="bi ${icon} me-2"></i>${name}</li>`);
        }
      }

      if (listEl) {
        if (workspaceItems.length > 0) {
          const listLabel = scopeLocked === true ? 'Currently locked to:' : 'Will lock to:';
          listEl.innerHTML = `<p class="small text-muted mb-2">${listLabel}</p><ul class="list-group list-group-flush">${workspaceItems.join('')}</ul>`;
        } else {
          listEl.innerHTML = '<p class="text-muted">No specific workspaces recorded.</p>';
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
