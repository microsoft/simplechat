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
    const groupSearchResultsBody = document.querySelector('#groupSearchResultsTable tbody');
    const sharedGroupsList = document.getElementById('sharedGroupsList');
    
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

    if (groupSearchResultsBody) {
        groupSearchResultsBody.addEventListener('click', function(e) {
            const addButton = e.target.closest('.group-search-add-btn');
            if (!addButton) {
                return;
            }

            window.addGroupToDocument(
                addButton.dataset.groupId || '',
                addButton.dataset.groupName || ''
            );
        });
    }

    if (sharedGroupsList) {
        sharedGroupsList.addEventListener('click', function(e) {
            const removeButton = e.target.closest('.shared-group-remove-btn');
            if (!removeButton) {
                return;
            }

            window.removeGroupFromDocument(
                removeButton.dataset.groupId || '',
                removeButton.dataset.groupName || ''
            );
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
        sharedGroupsList.replaceChildren();
    } else {
        noSharedGroups.style.display = 'none';
        const groupRows = sharedGroups.map(group => {
            const row = document.createElement('div');
            row.className = 'd-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded';

            const details = document.createElement('div');

            const name = document.createElement('strong');
            name.textContent = group.name || '';
            details.appendChild(name);

            if (group.description) {
                details.appendChild(document.createElement('br'));

                const description = document.createElement('small');
                description.className = 'text-muted';
                description.textContent = group.description;
                details.appendChild(description);
            }

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'btn btn-sm btn-outline-danger shared-group-remove-btn';
            removeButton.dataset.groupId = group.id || '';
            removeButton.dataset.groupName = group.name || '';
            removeButton.innerHTML = '<i class="bi bi-x"></i> Remove';

            row.appendChild(details);
            row.appendChild(removeButton);

            return row;
        });

        sharedGroupsList.replaceChildren(...groupRows);
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

    const groupRows = groups.map(group => {
        const row = document.createElement('tr');

        const nameCell = document.createElement('td');
        nameCell.textContent = group.name || '';

        const descriptionCell = document.createElement('td');
        descriptionCell.textContent = group.description || '';

        const actionCell = document.createElement('td');
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn btn-sm btn-primary group-search-add-btn';
        addButton.dataset.groupId = group.id || '';
        addButton.dataset.groupName = group.name || '';
        addButton.textContent = 'Add';

        actionCell.appendChild(addButton);
        row.appendChild(nameCell);
        row.appendChild(descriptionCell);
        row.appendChild(actionCell);

        return row;
    });

    tbody.replaceChildren(...groupRows);
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

    const content = document.createElement('div');
    content.className = 'd-flex';

    const toastBody = document.createElement('div');
    toastBody.className = 'toast-body';
    toastBody.textContent = String(message ?? '');

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close btn-close-white me-2 m-auto';
    closeButton.setAttribute('data-bs-dismiss', 'toast');

    content.appendChild(toastBody);
    content.appendChild(closeButton);
    toast.appendChild(content);
    
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