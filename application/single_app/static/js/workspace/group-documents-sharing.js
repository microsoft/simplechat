// group-documents-sharing.js - Group document sharing functionality

let currentGroupDocumentId = null;
let groupShareModal = null;

// Initialize sharing functionality when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeGroupSharing();
});

function initializeGroupSharing() {
    // Get modal element
    const shareModalElement = document.getElementById('groupShareDocumentModal');
    if (shareModalElement) {
        groupShareModal = new bootstrap.Modal(shareModalElement);
    }

    // Setup event listeners
    setupGroupShareEventListeners();
}

function setupGroupShareEventListeners() {
    // Group search functionality
    const searchGroupsBtn = document.getElementById('searchGroupsBtn');
    const groupSearchTerm = document.getElementById('groupSearchTerm');
    
    if (searchGroupsBtn) {
        searchGroupsBtn.addEventListener('click', handleGroupSearch);
    }
    
    if (groupSearchTerm) {
        groupSearchTerm.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleGroupSearch();
            }
        });
    }

    // Modal reset when closed
    const shareModalElement = document.getElementById('groupShareDocumentModal');
    if (shareModalElement) {
        shareModalElement.addEventListener('hidden.bs.modal', function() {
            resetGroupShareModal();
        });
    }
}

// Main function to open share modal
window.shareGroupDocument = function(documentId, fileName) {
    currentGroupDocumentId = documentId;
    
    // Set document name in modal
    const shareDocumentName = document.getElementById('groupShareDocumentName');
    if (shareDocumentName) {
        shareDocumentName.textContent = fileName;
    }
    
    // Load current shared groups
    loadSharedGroups(documentId);
    
    // Clear search results and form
    resetGroupShareModal();
    
    // Show modal
    if (groupShareModal) {
        groupShareModal.show();
    }
};

async function loadSharedGroups(documentId) {
    try {
        const response = await fetch(`/api/group_documents/${documentId}/shared-groups`);
        const data = await response.json();
        
        if (response.ok) {
            renderSharedGroups(data.shared_groups || []);
        } else {
            console.error('Error loading shared groups:', data.error);
            showToast('Error loading shared groups: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error loading shared groups:', error);
        showToast('Error loading shared groups', 'danger');
    }
}

function renderSharedGroups(sharedGroups) {
    const noSharedGroups = document.getElementById('noSharedGroups');
    const sharedGroupsList = document.getElementById('sharedGroupsList');
    
    if (!noSharedGroups || !sharedGroupsList) return;
    
    if (sharedGroups.length === 0) {
        noSharedGroups.style.display = 'block';
        sharedGroupsList.innerHTML = '';
    } else {
        noSharedGroups.style.display = 'none';
        sharedGroupsList.innerHTML = sharedGroups.map(group => `
            <div class="d-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded">
                <div>
                    <strong>${escapeHtml(group.name)}</strong>
                    ${group.description ? `<br><small class="text-muted">${escapeHtml(group.description)}</small>` : ''}
                </div>
                <button class="btn btn-sm btn-outline-danger" onclick="removeGroupFromDocument('${group.id}', '${escapeHtml(group.name)}')">
                    <i class="bi bi-x"></i> Remove
                </button>
            </div>
        `).join('');
    }
}

async function handleGroupSearch() {
    const groupSearchTerm = document.getElementById('groupSearchTerm');
    const searchStatus = document.getElementById('groupSearchStatus');
    const searchGroupsBtn = document.getElementById('searchGroupsBtn');
    
    if (!groupSearchTerm || !groupSearchTerm.value.trim()) {
        showToast('Please enter a search term', 'warning');
        return;
    }
    
    const query = groupSearchTerm.value.trim();
    
    // Update UI to show searching
    if (searchGroupsBtn) {
        searchGroupsBtn.disabled = true;
        searchGroupsBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Searching...';
    }
    if (searchStatus) {
        searchStatus.textContent = 'Searching...';
    }
    
    try {
        // Use the existing group discover endpoint
        const response = await fetch(`/api/groups/discover?search=${encodeURIComponent(query)}&showAll=true`);
        const groups = await response.json();
        
        if (response.ok) {
            renderGroupSearchResults(groups);
            if (searchStatus) {
                searchStatus.textContent = `Found ${groups.length} group(s)`;
            }
        } else {
            console.error('Error searching groups:', groups.error);
            showToast('Error searching groups: ' + groups.error, 'danger');
            if (searchStatus) {
                searchStatus.textContent = 'Search failed';
            }
        }
    } catch (error) {
        console.error('Error searching groups:', error);
        showToast('Error searching groups', 'danger');
        if (searchStatus) {
            searchStatus.textContent = 'Search failed';
        }
    } finally {
        // Reset search button
        if (searchGroupsBtn) {
            searchGroupsBtn.disabled = false;
            searchGroupsBtn.innerHTML = 'Search';
        }
    }
}

function renderGroupSearchResults(groups) {
    const tbody = document.querySelector('#groupSearchResultsTable tbody');
    if (!tbody) return;
    
    if (groups.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No groups found</td></tr>';
        return;
    }
    
    tbody.innerHTML = groups.map(group => `
        <tr>
            <td>${escapeHtml(group.name)}</td>
            <td>${escapeHtml(group.description || '')}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="addGroupToDocument('${group.id}', '${escapeHtml(group.name)}')">
                    Add
                </button>
            </td>
        </tr>
    `).join('');
}

window.addGroupToDocument = async function(groupId, groupName) {
    if (!currentGroupDocumentId) {
        showToast('No document selected', 'danger');
        return;
    }
    
    try {
        const response = await fetch(`/api/group_documents/${currentGroupDocumentId}/share-with-group`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_id: groupId
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(`Document shared with group: ${groupName}`, 'success');
            // Reload shared groups list
            loadSharedGroups(currentGroupDocumentId);
            // Clear search results
            clearGroupSearchResults();
            // Refresh documents table if available
            if (window.fetchGroupDocuments) {
                window.fetchGroupDocuments();
            }
        } else {
            showToast('Error sharing document: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error sharing document with group:', error);
        showToast('Error sharing document with group', 'danger');
    }
};

window.removeGroupFromDocument = async function(groupId, groupName) {
    if (!currentGroupDocumentId) {
        showToast('No document selected', 'danger');
        return;
    }
    
    if (!confirm(`Remove sharing with group "${groupName}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/group_documents/${currentGroupDocumentId}/unshare-with-group`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_id: groupId
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(`Removed sharing with group: ${groupName}`, 'success');
            // Reload shared groups list
            loadSharedGroups(currentGroupDocumentId);
            // Refresh documents table if available
            if (window.fetchGroupDocuments) {
                window.fetchGroupDocuments();
            }
        } else {
            showToast('Error removing group: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error removing group:', error);
        showToast('Error removing group', 'danger');
    }
};

function clearGroupSearchResults() {
    const tbody = document.querySelector('#groupSearchResultsTable tbody');
    if (tbody) {
        tbody.innerHTML = '';
    }
    
    const groupSearchTerm = document.getElementById('groupSearchTerm');
    if (groupSearchTerm) {
        groupSearchTerm.value = '';
    }
    
    const searchStatus = document.getElementById('groupSearchStatus');
    if (searchStatus) {
        searchStatus.textContent = '';
    }
}

function resetGroupShareModal() {
    clearGroupSearchResults();
}

// Utility functions
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function showToast(message, type = 'info') {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    // Add to toast container
    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toastContainer';
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(toastContainer);
    }
    
    toastContainer.appendChild(toast);
    
    // Show toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remove from DOM after hiding
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}