// static/js/workspace/workspace-tags.js
// Handles tag management for workspace documents

import { escapeHtml } from "./workspace-utils.js";

// ============= State Variables =============
let workspaceTags = []; // All available workspace tags with colors
let currentView = 'list'; // 'list' or 'grid'
let selectedTagFilter = [];

// ============= Initialization =============

export function initializeTags() {
    // Load workspace tags
    loadWorkspaceTags();
    
    // Setup view switcher
    setupViewSwitcher();
    
    // Setup tag filter
    setupTagFilter();
    
    // Setup bulk tag management
    setupBulkTagManagement();
    
    // Load saved view preference
    const savedView = localStorage.getItem('personalWorkspaceViewPreference');
    if (savedView === 'grid') {
        document.getElementById('docs-view-grid').checked = true;
        switchView('grid');
    }
}

// ============= Load Workspace Tags =============

export async function loadWorkspaceTags() {
    try {
        const response = await fetch('/api/documents/tags');
        const data = await response.json();
        
        if (response.ok && data.tags) {
            workspaceTags = data.tags;
            updateTagFilterOptions();
            updateDocTagsSelect();
            updateBulkTagSelect();
            
            // Update grid view if visible
            if (currentView === 'grid') {
                renderGridView();
            }
        } else {
            console.error('Failed to load workspace tags:', data.error);
        }
    } catch (error) {
        console.error('Error loading workspace tags:', error);
    }
}

// ============= View Switcher =============

function setupViewSwitcher() {
    const listRadio = document.getElementById('docs-view-list');
    const gridRadio = document.getElementById('docs-view-grid');
    
    if (listRadio) {
        listRadio.addEventListener('change', () => {
            if (listRadio.checked) {
                switchView('list');
            }
        });
    }
    
    if (gridRadio) {
        gridRadio.addEventListener('change', () => {
            if (gridRadio.checked) {
                switchView('grid');
            }
        });
    }
}

function switchView(view) {
    currentView = view;
    localStorage.setItem('personalWorkspaceViewPreference', view);
    
    const listView = document.getElementById('documents-list-view');
    const gridView = document.getElementById('documents-grid-view');
    const viewInfo = document.getElementById('docs-view-info');
    
    if (view === 'list') {
        listView.style.display = 'block';
        gridView.style.display = 'none';
        if (viewInfo) viewInfo.textContent = '';
        // Trigger reload of documents if needed
        window.fetchUserDocuments?.();
    } else {
        listView.style.display = 'none';
        gridView.style.display = 'block';
        renderGridView();
    }
}

// ============= Grid View Rendering =============

async function renderGridView() {
    const container = document.getElementById('tag-folders-container');
    if (!container) return;
    
    // Show loading
    container.innerHTML = `
        <div class="col-12 text-center text-muted py-5">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            Loading tag folders...
        </div>
    `;
    
    // Get all documents to count untagged
    try {
        const docsResponse = await fetch('/api/documents?page_size=1000');
        const docsData = await docsResponse.json();
        const allDocs = docsData.documents || [];
        
        const untaggedCount = allDocs.filter(doc => !doc.tags || doc.tags.length === 0).length;
        
        // Build folder cards
        let html = '';
        
        // Untagged folder (always show if there are untagged documents)
        if (untaggedCount > 0) {
            html += `
                <div class="col-md-3">
                    <div class="tag-folder-card" data-tag="__untagged__" style="border-left: 4px solid #6c757d;">
                        <div class="tag-folder-icon">📂</div>
                        <div class="tag-folder-name text-muted">Untagged Documents</div>
                        <div class="tag-folder-count">${untaggedCount} file${untaggedCount !== 1 ? 's' : ''}</div>
                    </div>
                </div>
            `;
        }
        
        // Tag folders
        workspaceTags.forEach(tag => {
            const textColor = isColorLight(tag.color) ? 'text-dark' : 'text-light';
            
            html += `
                <div class="col-md-3">
                    <div class="tag-folder-card" data-tag="${escapeHtml(tag.name)}" style="border-left: 4px solid ${tag.color};">
                        <div class="tag-folder-actions">
                            <div class="dropdown">
                                <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();">
                                    <i class="bi bi-three-dots-vertical"></i>
                                </button>
                                <ul class="dropdown-menu">
                                    <li><a class="dropdown-item" href="#" onclick="window.renameTag('${escapeHtml(tag.name)}'); return false;">
                                        <i class="bi bi-pencil me-2"></i>Rename Tag
                                    </a></li>
                                    <li><a class="dropdown-item" href="#" onclick="window.changeTagColor('${escapeHtml(tag.name)}', '${tag.color}'); return false;">
                                        <i class="bi bi-palette me-2"></i>Change Color
                                    </a></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><a class="dropdown-item text-danger" href="#" onclick="window.deleteTag('${escapeHtml(tag.name)}'); return false;">
                                        <i class="bi bi-trash me-2"></i>Delete Tag
                                    </a></li>
                                </ul>
                            </div>
                        </div>
                        <div class="tag-folder-icon" style="color: ${tag.color};">📁</div>
                        <div class="tag-folder-name">${escapeHtml(tag.name)}</div>
                        <div class="tag-folder-count">${tag.count} file${tag.count !== 1 ? 's' : ''}</div>
                    </div>
                </div>
            `;
        });
        
        if (html === '') {
            html = `
                <div class="col-12 text-center text-muted py-5">
                    <i class="bi bi-folder2-open display-1 mb-3"></i>
                    <p>No tags yet. Add tags to documents to organize them into folders.</p>
                </div>
            `;
        }
        
        container.innerHTML = html;
        
        // Add click handlers to folder cards
        container.querySelectorAll('.tag-folder-card').forEach(card => {
            card.addEventListener('click', (e) => {
                const tagName = card.getAttribute('data-tag');
                filterByTag(tagName);
            });
        });
        
    } catch (error) {
        console.error('Error rendering grid view:', error);
        container.innerHTML = `
            <div class="col-12 text-center text-danger py-5">
                <i class="bi bi-exclamation-triangle display-4 mb-2"></i>
                <p>Error loading tag folders</p>
            </div>
        `;
    }
}

function filterByTag(tagName) {
    // Switch to list view and apply tag filter
    document.getElementById('docs-view-list').checked = true;
    switchView('list');
    
    // Set tag filter
    if (tagName === '__untagged__') {
        // Clear tag filter to show untagged
        selectedTagFilter = [];
        const filterSelect = document.getElementById('docs-tags-filter');
        if (filterSelect) {
            Array.from(filterSelect.options).forEach(opt => opt.selected = false);
        }
        // Need to implement untagged filter in backend
        window.docsTagsFilter = '__untagged__';
    } else {
        selectedTagFilter = [tagName];
        const filterSelect = document.getElementById('docs-tags-filter');
        if (filterSelect) {
            Array.from(filterSelect.options).forEach(opt => {
                opt.selected = opt.value === tagName;
            });
        }
        window.docsTagsFilter = tagName;
    }
    
    // Trigger filter application
    window.docsCurrentPage = 1;
    window.fetchUserDocuments?.();
}

// ============= Color Utility =============

function isColorLight(hexColor) {
    if (!hexColor) return true;
    const cleanHex = hexColor.startsWith('#') ? hexColor.substring(1) : hexColor;
    if (cleanHex.length < 3) return true;

    let r, g, b;
    try {
        if (cleanHex.length === 3) {
            r = parseInt(cleanHex[0] + cleanHex[0], 16);
            g = parseInt(cleanHex[1] + cleanHex[1], 16);
            b = parseInt(cleanHex[2] + cleanHex[2], 16);
        } else if (cleanHex.length >= 6) {
            r = parseInt(cleanHex.substring(0, 2), 16);
            g = parseInt(cleanHex.substring(2, 4), 16);
            b = parseInt(cleanHex.substring(4, 6), 16);
        } else {
            return true;
        }
    } catch (e) {
        return true;
    }

    if (isNaN(r) || isNaN(g) || isNaN(b)) return true;
    const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    return luminance > 0.5;
}

// ============= Tag Filter Setup =============

function setupTagFilter() {
    const filterSelect = document.getElementById('docs-tags-filter');
    if (!filterSelect) return;
    
    filterSelect.addEventListener('change', () => {
        selectedTagFilter = Array.from(filterSelect.selectedOptions).map(opt => opt.value);
    });
}

function updateTagFilterOptions() {
    const filterSelect = document.getElementById('docs-tags-filter');
    if (!filterSelect) return;
    
    filterSelect.innerHTML = workspaceTags.map(tag => {
        const textColor = isColorLight(tag.color) ? 'color: #212529' : 'color: #fff';
        return `<option value="${escapeHtml(tag.name)}" style="background-color: ${tag.color}; ${textColor};">
            ${escapeHtml(tag.name)} (${tag.count})
        </option>`;
    }).join('');
}

// ============= Document Tags Select (Metadata Modal) =============

function updateDocTagsSelect() {
    const select = document.getElementById('doc-tags');
    if (!select) return;
    
    select.innerHTML = workspaceTags.map(tag => {
        const textColor = isColorLight(tag.color) ? 'color: #212529' : 'color: #fff';
        return `<option value="${escapeHtml(tag.name)}" style="background-color: ${tag.color}; ${textColor};">
            ${escapeHtml(tag.name)}
        </option>`;
    }).join('');
}

// ============= Bulk Tag Management =============

// Track selected tags for bulk operations
let bulkSelectedTags = new Set();

function setupBulkTagManagement() {
    const manageTagsBtn = document.getElementById('manage-tags-btn');
    const bulkTagModal = document.getElementById('bulkTagModal');
    const bulkTagApplyBtn = document.getElementById('bulk-tag-apply-btn');
    
    if (manageTagsBtn && bulkTagModal) {
        const modalInstance = new bootstrap.Modal(bulkTagModal);
        
        manageTagsBtn.addEventListener('click', () => {
            const count = window.selectedDocuments?.size || 0;
            document.getElementById('bulk-tag-doc-count').textContent = count;
            
            // Clear selection and populate tags list
            bulkSelectedTags.clear();
            updateBulkTagsList();
            
            modalInstance.show();
        });
        
        if (bulkTagApplyBtn) {
            bulkTagApplyBtn.addEventListener('click', async () => {
                await applyBulkTagChanges();
                modalInstance.hide();
            });
        }
    }
}

function updateBulkTagsList() {
    const listContainer = document.getElementById('bulk-tags-list');
    if (!listContainer) return;
    
    if (workspaceTags.length === 0) {
        listContainer.innerHTML = '<div class="text-muted w-100 text-center py-3">No tags available. Click "Create New Tag" to add some.</div>';
        return;
    }
    
    let html = '';
    workspaceTags.forEach(tag => {
        const textColor = isColorLight(tag.color) ? '#000' : '#fff';
        const isSelected = bulkSelectedTags.has(tag.name);
        const selectedClass = isSelected ? 'selected border-dark' : '';
        const opacity = isSelected ? '1' : '0.7';
        
        html += `
            <span class="badge tag-badge ${selectedClass}" 
                  style="background-color: ${tag.color}; color: ${textColor}; opacity: ${opacity}; cursor: pointer; border: 2px solid transparent;"
                  onclick="window.toggleBulkTag('${escapeHtml(tag.name)}', '${tag.color}', this)">
                ${escapeHtml(tag.name)}
                ${isSelected ? '<i class="bi bi-check-circle-fill ms-1"></i>' : ''}
            </span>
        `;
    });
    
    listContainer.innerHTML = html;
}

// Make toggle function global so onclick can access it
window.toggleBulkTag = function(tagName, color, element) {
    if (bulkSelectedTags.has(tagName)) {
        bulkSelectedTags.delete(tagName);
        element.classList.remove('selected', 'border-dark');
        element.style.opacity = '0.7';
        // Remove checkmark
        const icon = element.querySelector('.bi-check-circle-fill');
        if (icon) icon.remove();
    } else {
        bulkSelectedTags.add(tagName);
        element.classList.add('selected', 'border-dark');
        element.style.opacity = '1';
        // Add checkmark
        element.innerHTML = `${escapeHtml(tagName)} <i class="bi bi-check-circle-fill ms-1"></i>`;
    }
};

function updateBulkTagSelect() {
    // This function is deprecated - now using updateBulkTagsList()
    updateBulkTagsList();
}

async function applyBulkTagChanges() {
    console.log('[Bulk Tag] Starting applyBulkTagChanges...');
    
    const action = document.getElementById('bulk-tag-action').value;
    console.log('[Bulk Tag] Action:', action);
    
    // Get selected tags from the bulkSelectedTags Set
    const selectedTags = Array.from(bulkSelectedTags);
    console.log('[Bulk Tag] Selected tags:', selectedTags);
    console.log('[Bulk Tag] bulkSelectedTags Set:', bulkSelectedTags);
    
    const documentIds = Array.from(window.selectedDocuments || []);
    console.log('[Bulk Tag] Document IDs:', documentIds);
    console.log('[Bulk Tag] window.selectedDocuments:', window.selectedDocuments);
    
    if (documentIds.length === 0) {
        console.log('[Bulk Tag] ERROR: No documents selected');
        alert('No documents selected');
        return;
    }
    
    if (selectedTags.length === 0) {
        console.log('[Bulk Tag] ERROR: No tags selected');
        alert('Please select at least one tag by clicking on it');
        return;
    }
    
    // Show loading state
    const applyBtn = document.getElementById('bulk-tag-apply-btn');
    const buttonText = applyBtn.querySelector('.button-text');
    const buttonLoading = applyBtn.querySelector('.button-loading');
    
    applyBtn.disabled = true;
    buttonText.classList.add('d-none');
    buttonLoading.classList.remove('d-none');
    
    console.log('[Bulk Tag] Preparing request with:', {
        document_ids: documentIds,
        action: action,
        tags: selectedTags
    });
    
    try {
        console.log('[Bulk Tag] Sending POST to /api/documents/bulk-tag...');
        const response = await fetch('/api/documents/bulk-tag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                document_ids: documentIds,
                action: action,
                tags: selectedTags
            })
        });
        
        console.log('[Bulk Tag] Response status:', response.status);
        
        const result = await response.json();
        console.log('[Bulk Tag] Response data:', result);
        
        // Log error details if any
        if (result.errors && result.errors.length > 0) {
            console.error('[Bulk Tag] Error details:', result.errors);
            result.errors.forEach((err, idx) => {
                console.error(`[Bulk Tag] Error ${idx + 1}:`, err);
            });
        }
        
        if (response.ok) {
            const successCount = result.success?.length || 0;
            const errorCount = result.errors?.length || 0;
            
            console.log('[Bulk Tag] Success count:', successCount);
            console.log('[Bulk Tag] Error count:', errorCount);
            
            let message = `Tags updated for ${successCount} document(s)`;
            if (errorCount > 0) {
                message += `\n${errorCount} document(s) had errors`;
            }
            alert(message);
            
            // Reload workspace tags and documents
            console.log('[Bulk Tag] Reloading tags and documents...');
            await loadWorkspaceTags();
            window.fetchUserDocuments?.();
            
            // Clear selection
            window.selectedDocuments?.clear();
            updateSelectionUI();
        } else {
            alert('Error: ' + (result.error || 'Failed to update tags'));
        }
    } catch (error) {
        console.error('Error applying bulk tag changes:', error);
        alert('Error updating tags');
    } finally {
        // Reset button state
        applyBtn.disabled = false;
        buttonText.classList.remove('d-none');
        buttonLoading.classList.add('d-none');
    }
}

function updateSelectionUI() {
    const bulkActionsBar = document.getElementById('bulkActionsBar');
    const selectedCount = document.getElementById('selectedCount');
    const count = window.selectedDocuments?.size || 0;
    
    if (selectedCount) {
        selectedCount.textContent = count;
    }
    
    if (bulkActionsBar) {
        bulkActionsBar.style.display = count > 0 ? 'block' : 'none';
    }
}

// ============= Tag Display Helper =============

export function renderTagBadges(tags, maxDisplay = 3) {
    if (!tags || tags.length === 0) {
        return '<span class="text-muted small">No tags</span>';
    }
    
    let html = '';
    const displayTags = tags.slice(0, maxDisplay);
    
    displayTags.forEach(tagName => {
        const tag = workspaceTags.find(t => t.name === tagName);
        const color = tag?.color || '#6c757d';
        const textClass = isColorLight(color) ? 'text-dark' : 'text-light';
        
        html += `<span class="tag-badge ${textClass}" 
                      style="background-color: ${color};" 
                      title="${escapeHtml(tagName)}">
            ${escapeHtml(tagName)}
        </span>`;
    });
    
    if (tags.length > maxDisplay) {
        html += `<span class="badge bg-secondary">+${tags.length - maxDisplay}</span>`;
    }
    
    return html;
}

// ============= Tag Management Actions (exposed globally) =============

window.renameTag = async function(tagName) {
    const newName = prompt(`Rename tag "${tagName}" to:`, tagName);
    if (!newName || newName === tagName) return;
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(result.message);
            await loadWorkspaceTags();
            if (currentView === 'grid') {
                renderGridView();
            } else {
                window.fetchUserDocuments?.();
            }
        } else {
            alert('Error: ' + (result.error || 'Failed to rename tag'));
        }
    } catch (error) {
        console.error('Error renaming tag:', error);
        alert('Error renaming tag');
    }
};

window.changeTagColor = async function(tagName, currentColor) {
    const newColor = prompt(`Enter new color for tag "${tagName}" (hex code):`, currentColor);
    if (!newColor || newColor === currentColor) return;
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ color: newColor })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(result.message);
            await loadWorkspaceTags();
            if (currentView === 'grid') {
                renderGridView();
            } else {
                window.fetchUserDocuments?.();
            }
        } else {
            alert('Error: ' + (result.error || 'Failed to change color'));
        }
    } catch (error) {
        console.error('Error changing tag color:', error);
        alert('Error changing tag color');
    }
};

window.deleteTag = async function(tagName) {
    if (!confirm(`Delete tag "${tagName}" from all documents?`)) return;
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(result.message);
            await loadWorkspaceTags();
            if (currentView === 'grid') {
                renderGridView();
            } else {
                window.fetchUserDocuments?.();
            }
        } else {
            alert('Error: ' + (result.error || 'Failed to delete tag'));
        }
    } catch (error) {
        console.error('Error deleting tag:', error);
        alert('Error deleting tag');
    }
};

// ============= Export for use in other modules =============

export { workspaceTags, currentView, selectedTagFilter };
