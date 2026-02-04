// workspace-tag-management.js
// Handles the step-through tag management workflow

import { escapeHtml } from "./workspace-utils.js";

// State for tag management
let allWorkspaceTags = [];
let selectedTags = new Set();
let managementContext = null; // 'document' or 'bulk'

// ============= Initialize Tag Management System =============

export function initializeTagManagement() {
    setupTagManagementModal();
    setupTagSelectionModal();
    setupDocumentTagButton();
    setupBulkTagButton();
}

// ============= Setup Modal Event Listeners =============

function setupTagManagementModal() {
    const addTagBtn = document.getElementById('add-tag-btn');
    const newTagNameInput = document.getElementById('new-tag-name');
    
    if (addTagBtn) {
        addTagBtn.addEventListener('click', handleAddNewTag);
    }
    
    if (newTagNameInput) {
        newTagNameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleAddNewTag();
            }
        });
        
        // Real-time validation
        newTagNameInput.addEventListener('input', validateTagNameInput);
    }
}

function setupTagSelectionModal() {
    const doneBtn = document.getElementById('tag-selection-done-btn');
    
    if (doneBtn) {
        doneBtn.addEventListener('click', handleTagSelectionDone);
    }
}

function setupDocumentTagButton() {
    const manageTagsBtn = document.getElementById('doc-manage-tags-btn');
    
    if (manageTagsBtn) {
        manageTagsBtn.addEventListener('click', () => {
            managementContext = 'document';
            showTagSelectionModal();
        });
    }
}

function setupBulkTagButton() {
    const bulkManageBtn = document.getElementById('bulk-manage-tags-btn');
    
    if (bulkManageBtn) {
        bulkManageBtn.addEventListener('click', () => {
            managementContext = 'bulk';
            showTagSelectionModal();
        });
    }
}

// ============= Load Tags from API =============

export async function loadWorkspaceTags() {
    try {
        const response = await fetch('/api/documents/tags');
        const data = await response.json();
        
        if (response.ok && data.tags) {
            allWorkspaceTags = data.tags;
            refreshTagManagementTable();
        } else {
            console.error('Failed to load tags:', data.error);
        }
    } catch (error) {
        console.error('Error loading tags:', error);
    }
}

// ============= Show Tag Selection Modal =============

function showTagSelectionModal() {
    // Load current tags first
    loadWorkspaceTags().then(() => {
        renderTagSelectionList();
        
        const modal = new bootstrap.Modal(document.getElementById('tagSelectionModal'));
        modal.show();
    });
}

function renderTagSelectionList() {
    const listContainer = document.getElementById('tag-selection-list');
    if (!listContainer) return;
    
    if (allWorkspaceTags.length === 0) {
        listContainer.innerHTML = `
            <div class="text-center p-4">
                <p class="text-muted mb-3">No tags available yet.</p>
                <button type="button" class="btn btn-primary" id="open-tag-mgmt-from-selection">
                    <i class="bi bi-plus-circle"></i> Create Your First Tag
                </button>
            </div>
        `;
        
        document.getElementById('open-tag-mgmt-from-selection')?.addEventListener('click', () => {
            bootstrap.Modal.getInstance(document.getElementById('tagSelectionModal')).hide();
            showTagManagementModal();
        });
        return;
    }
    
    let html = '';
    html += `
        <div class="mb-2 p-2 bg-light border-bottom d-flex justify-content-between align-items-center">
            <span class="small">Select tags to apply:</span>
            <button type="button" class="btn btn-sm btn-outline-primary" id="open-tag-mgmt-btn">
                <i class="bi bi-gear"></i> Manage Tags
            </button>
        </div>
    `;
    
    allWorkspaceTags.forEach(tag => {
        const isSelected = selectedTags.has(tag.name);
        const textColor = isColorLight(tag.color) ? '#000' : '#fff';
        
        html += `
            <label class="list-group-item d-flex align-items-center" style="cursor: pointer;">
                <input class="form-check-input me-3" type="checkbox" value="${escapeHtml(tag.name)}" 
                       ${isSelected ? 'checked' : ''}>
                <span class="badge me-2" style="background-color: ${tag.color}; color: ${textColor};">
                    ${escapeHtml(tag.name)}
                </span>
                <span class="ms-auto text-muted small">${tag.count} docs</span>
            </label>
        `;
    });
    
    listContainer.innerHTML = html;
    
    // Add event listeners to checkboxes
    listContainer.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedTags.add(e.target.value);
            } else {
                selectedTags.delete(e.target.value);
            }
        });
    });
    
    // Add manage tags button handler
    document.getElementById('open-tag-mgmt-btn')?.addEventListener('click', () => {
        bootstrap.Modal.getInstance(document.getElementById('tagSelectionModal')).hide();
        showTagManagementModal();
    });
}

// ============= Show Tag Management Modal =============

function showTagManagementModal() {
    loadWorkspaceTags().then(() => {
        refreshTagManagementTable();
        
        const modal = new bootstrap.Modal(document.getElementById('tagManagementModal'));
        modal.show();
    });
}

function refreshTagManagementTable() {
    const tbody = document.getElementById('existing-tags-tbody');
    if (!tbody) return;
    
    if (allWorkspaceTags.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No tags yet. Add one above.</td></tr>';
        return;
    }
    
    let html = '';
    allWorkspaceTags.forEach(tag => {
        html += `
            <tr>
                <td>
                    <div style="width: 30px; height: 30px; background-color: ${tag.color}; border-radius: 4px; border: 1px solid #dee2e6;"></div>
                </td>
                <td>
                    <span class="badge" style="background-color: ${tag.color}; color: ${isColorLight(tag.color) ? '#000' : '#fff'};">
                        ${escapeHtml(tag.name)}
                    </span>
                </td>
                <td>${tag.count}</td>
                <td>
                    <button class="btn btn-sm btn-outline-primary me-1" onclick="window.editTag('${escapeHtml(tag.name)}', '${tag.color}')">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="window.deleteTag('${escapeHtml(tag.name)}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

// ============= Add New Tag =============

async function handleAddNewTag() {
    const nameInput = document.getElementById('new-tag-name');
    const colorInput = document.getElementById('new-tag-color');
    
    if (!nameInput || !colorInput) return;
    
    const tagName = nameInput.value.trim().toLowerCase();
    const tagColor = colorInput.value;
    
    if (!tagName) {
        alert('Please enter a tag name');
        return;
    }
    
    // Validate tag name
    if (!/^[a-z0-9_-]+$/.test(tagName)) {
        alert('Tag name must contain only lowercase letters, numbers, hyphens, and underscores');
        return;
    }
    
    // Check if tag already exists
    if (allWorkspaceTags.some(t => t.name === tagName)) {
        alert('A tag with this name already exists');
        return;
    }
    
    try {
        const response = await fetch('/api/documents/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tag_name: tagName,
                color: tagColor
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Clear inputs
            nameInput.value = '';
            colorInput.value = '#0d6efd';
            
            // Reload tags
            await loadWorkspaceTags();
            
            // Show success message
            showToast('Tag created successfully', 'success');
        } else {
            alert('Failed to create tag: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error creating tag:', error);
        alert('Error creating tag');
    }
}

function validateTagNameInput(e) {
    const input = e.target;
    const value = input.value.toLowerCase();
    
    // Remove invalid characters as user types
    input.value = value.replace(/[^a-z0-9_-]/g, '');
}

// ============= Edit Tag =============

window.editTag = async function(tagName, currentColor) {
    const newName = prompt('Enter new tag name (or leave as is):', tagName);
    if (!newName) return; // Cancelled
    
    const normalizedNewName = newName.trim().toLowerCase();
    
    if (normalizedNewName !== tagName && !/^[a-z0-9_-]+$/.test(normalizedNewName)) {
        alert('Tag name must contain only lowercase letters, numbers, hyphens, and underscores');
        return;
    }
    
    const newColor = prompt('Enter new color (hex code):', currentColor);
    if (!newColor) return; // Cancelled
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                new_name: normalizedNewName !== tagName ? normalizedNewName : undefined,
                color: newColor !== currentColor ? newColor : undefined
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            await loadWorkspaceTags();
            showToast('Tag updated successfully', 'success');
        } else {
            alert('Failed to update tag: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error updating tag:', error);
        alert('Error updating tag');
    }
};

// ============= Delete Tag =============

window.deleteTag = async function(tagName) {
    if (!confirm(`Delete tag "${tagName}"? This will remove it from all documents.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (response.ok) {
            await loadWorkspaceTags();
            showToast('Tag deleted successfully', 'success');
        } else {
            alert('Failed to delete tag: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error deleting tag:', error);
        alert('Error deleting tag');
    }
};

// ============= Handle Tag Selection Done =============

function handleTagSelectionDone() {
    // Update the display based on context
    if (managementContext === 'document') {
        updateDocumentTagsDisplay();
    } else if (managementContext === 'bulk') {
        updateBulkTagsDisplay();
    }
    
    // Close modal
    bootstrap.Modal.getInstance(document.getElementById('tagSelectionModal')).hide();
}

function updateDocumentTagsDisplay() {
    const container = document.getElementById('doc-selected-tags-container');
    if (!container) return;
    
    if (selectedTags.size === 0) {
        container.innerHTML = '<span class="text-muted small">No tags selected</span>';
        return;
    }
    
    let html = '';
    selectedTags.forEach(tagName => {
        const tag = allWorkspaceTags.find(t => t.name === tagName);
        if (tag) {
            const textColor = isColorLight(tag.color) ? '#000' : '#fff';
            html += `
                <span class="badge" style="background-color: ${tag.color}; color: ${textColor};">
                    ${escapeHtml(tag.name)}
                    <i class="bi bi-x" style="cursor: pointer;" onclick="window.removeSelectedTag('${escapeHtml(tag.name)}')"></i>
                </span>
            `;
        }
    });
    
    container.innerHTML = html;
}

function updateBulkTagsDisplay() {
    const listContainer = document.getElementById('bulk-tags-list');
    if (!listContainer) return;
    
    if (selectedTags.size === 0) {
        listContainer.innerHTML = '<div class="text-muted">No tags selected</div>';
        return;
    }
    
    let html = '<div class="d-flex flex-wrap gap-1">';
    selectedTags.forEach(tagName => {
        const tag = allWorkspaceTags.find(t => t.name === tagName);
        if (tag) {
            const textColor = isColorLight(tag.color) ? '#000' : '#fff';
            html += `
                <span class="badge" style="background-color: ${tag.color}; color: ${textColor};">
                    ${escapeHtml(tag.name)}
                </span>
            `;
        }
    });
    html += '</div>';
    
    listContainer.innerHTML = html;
}

window.removeSelectedTag = function(tagName) {
    selectedTags.delete(tagName);
    updateDocumentTagsDisplay();
};

// ============= Export Selected Tags =============

export function getSelectedTagsArray() {
    return Array.from(selectedTags);
}

export function setSelectedTags(tags) {
    selectedTags = new Set(tags || []);
}

export function clearSelectedTags() {
    selectedTags.clear();
}

// ============= Utility Functions =============

function isColorLight(color) {
    // Convert hex to RGB
    const hex = color.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    
    // Calculate relative luminance
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    
    return luminance > 0.5;
}

function showToast(message, type = 'info') {
    // Create toast element
    const toastHtml = `
        <div class="toast align-items-center text-white bg-${type}" role="alert">
            <div class="d-flex">
                <div class="toast-body">${escapeHtml(message)}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    // Add to container
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        document.body.appendChild(container);
    }
    
    const temp = document.createElement('div');
    temp.innerHTML = toastHtml;
    const toastElement = temp.firstElementChild;
    container.appendChild(toastElement);
    
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
    
    // Remove after hidden
    toastElement.addEventListener('hidden.bs.toast', () => {
        toastElement.remove();
    });
}
