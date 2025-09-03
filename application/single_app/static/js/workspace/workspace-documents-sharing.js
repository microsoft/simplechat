// workspace-documents-sharing.js - Document sharing functionality

let currentDocumentId = null;
let shareModal = null;

// Initialize sharing functionality when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeSharing();
});

function initializeSharing() {
    // Get modal element
    const shareModalElement = document.getElementById('shareDocumentModal');
    if (shareModalElement) {
        shareModal = new bootstrap.Modal(shareModalElement);
    }

    // Setup event listeners
    setupShareEventListeners();
    
    // Setup chevron rotation for manual user section
    setupManualUserSectionToggle();
}

function setupManualUserSectionToggle() {
    const manualUserSection = document.getElementById('manualUserSection');
    const manualUserChevron = document.getElementById('manualUserChevron');
    
    if (manualUserSection && manualUserChevron) {
        manualUserSection.addEventListener('show.bs.collapse', function () {
            manualUserChevron.classList.remove('fa-chevron-right');
            manualUserChevron.classList.add('fa-chevron-down');
        });
        
        manualUserSection.addEventListener('hide.bs.collapse', function () {
            manualUserChevron.classList.remove('fa-chevron-down');
            manualUserChevron.classList.add('fa-chevron-right');
        });
    }
}

function setupShareEventListeners() {
    // User search functionality
    const searchUsersBtn = document.getElementById('searchUsersBtn');
    const userSearchTerm = document.getElementById('userSearchTerm');
    
    if (searchUsersBtn) {
        searchUsersBtn.addEventListener('click', handleUserSearch);
    }
    
    if (userSearchTerm) {
        userSearchTerm.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleUserSearch();
            }
        });
    }

    // Share form submission
    const shareDocumentForm = document.getElementById('shareDocumentForm');
    if (shareDocumentForm) {
        // Remove form submit handler; use explicit button click for manual add
        const manualAddUserBtn = document.getElementById('manualAddUserBtn');
        if (manualAddUserBtn) {
            manualAddUserBtn.addEventListener('click', handleManualUserAdd);
        }
    }

    // Modal reset when closed
    const shareModalElement = document.getElementById('shareDocumentModal');
    if (shareModalElement) {
        shareModalElement.addEventListener('hidden.bs.modal', function() {
            resetShareModal();
        });
    }
}

// Main function to open share modal
window.shareDocument = function(documentId, fileName) {
    currentDocumentId = documentId;
    
    // Set document name in modal
    const shareDocumentName = document.getElementById('shareDocumentName');
    if (shareDocumentName) {
        shareDocumentName.textContent = fileName;
    }
    
    // Load current shared users
    loadSharedUsers(documentId);
    
    // Clear search results and form
    resetShareModal();
    
    // Show modal
    if (shareModal) {
        shareModal.show();
    }
};

async function loadSharedUsers(documentId) {
    try {
        const response = await fetch(`/api/documents/${documentId}/shared-users`);
        const data = await response.json();
        
        if (response.ok) {
            renderSharedUsers(data.shared_users || []);
        } else {
            console.error('Error loading shared users:', data.error);
            showToast('Error loading shared users: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error loading shared users:', error);
        showToast('Error loading shared users', 'danger');
    }
}

function renderSharedUsers(sharedUsers) {
    const noSharedUsers = document.getElementById('noSharedUsers');
    const sharedUsersList = document.getElementById('sharedUsersList');
    
    if (!noSharedUsers || !sharedUsersList) return;
    
    if (sharedUsers.length === 0) {
        noSharedUsers.style.display = 'block';
        sharedUsersList.innerHTML = '';
    } else {
        noSharedUsers.style.display = 'none';
        sharedUsersList.innerHTML = sharedUsers.map(user => `
            <div class="d-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded">
                <div>
                    <strong>${escapeHtml(user.displayName)}</strong>
                    <br>
                    <small class="text-muted">${escapeHtml(user.email)}</small>
                </div>
                <button class="btn btn-sm btn-outline-danger" onclick="removeUserFromDocument('${user.id}', '${escapeHtml(user.displayName)}')">
                    <i class="bi bi-x"></i> Remove
                </button>
            </div>
        `).join('');
    }
}

async function handleUserSearch() {
    const userSearchTerm = document.getElementById('userSearchTerm');
    const searchStatus = document.getElementById('searchStatus');
    const searchUsersBtn = document.getElementById('searchUsersBtn');
    
    if (!userSearchTerm || !userSearchTerm.value.trim()) {
        showToast('Please enter a search term', 'warning');
        return;
    }
    
    const query = userSearchTerm.value.trim();
    
    // Update UI to show searching
    if (searchUsersBtn) {
        searchUsersBtn.disabled = true;
        searchUsersBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Searching...';
    }
    if (searchStatus) {
        searchStatus.textContent = 'Searching...';
    }
    
    try {
        const response = await fetch(`/api/userSearch?query=${encodeURIComponent(query)}`);
        const users = await response.json();
        
        if (response.ok) {
            renderUserSearchResults(users);
            if (searchStatus) {
                searchStatus.textContent = `Found ${users.length} user(s)`;
            }
        } else {
            console.error('Error searching users:', users.error);
            showToast('Error searching users: ' + users.error, 'danger');
            if (searchStatus) {
                searchStatus.textContent = 'Search failed';
            }
        }
    } catch (error) {
        console.error('Error searching users:', error);
        showToast('Error searching users', 'danger');
        if (searchStatus) {
            searchStatus.textContent = 'Search failed';
        }
    } finally {
        // Reset search button
        if (searchUsersBtn) {
            searchUsersBtn.disabled = false;
            searchUsersBtn.innerHTML = 'Search';
        }
    }
}

function renderUserSearchResults(users) {
    const tbody = document.querySelector('#userSearchResultsTable tbody');
    if (!tbody) return;
    
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No users found</td></tr>';
        return;
    }
    
    tbody.innerHTML = users.map(user => `
        <tr>
            <td>${escapeHtml(user.displayName)}</td>
            <td>${escapeHtml(user.email)}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="addUserToDocument('${user.id}', '${escapeHtml(user.displayName)}', '${escapeHtml(user.email)}')">
                    Add
                </button>
            </td>
        </tr>
    `).join('');
}

async function addUserToDocument(userId, displayName, email) {
    if (!currentDocumentId) {
        showToast('No document selected', 'danger');
        return;
    }
    
    try {
        const response = await fetch(`/api/documents/${currentDocumentId}/share`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: userId
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(`Document shared with ${displayName}`, 'success');
            // Reload shared users list
            loadSharedUsers(currentDocumentId);
            // Clear search results
            clearSearchResults();
            // Refresh documents table if available
            if (window.fetchUserDocuments) {
                window.fetchUserDocuments();
            }
        } else {
            showToast('Error sharing document: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error sharing document:', error);
        showToast('Error sharing document', 'danger');
    }
}

window.removeUserFromDocument = async function(userId, displayName) {
    if (!currentDocumentId) {
        showToast('No document selected', 'danger');
        return;
    }
    
    if (!confirm(`Remove sharing with ${displayName}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/documents/${currentDocumentId}/unshare`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: userId
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(`Removed sharing with ${displayName}`, 'success');
            // Reload shared users list
            loadSharedUsers(currentDocumentId);
            // Refresh documents table if available
            if (window.fetchUserDocuments) {
                window.fetchUserDocuments();
            }
        } else {
            showToast('Error removing user: ' + data.error, 'danger');
        }
    } catch (error) {
        console.error('Error removing user:', error);
        showToast('Error removing user', 'danger');
    }
};

async function handleManualUserAdd(event) {
    event.preventDefault();
    
    const newUserId = document.getElementById('newUserId');
    const newUserDisplayName = document.getElementById('newUserDisplayName');
    const newUserEmail = document.getElementById('newUserEmail');
    const userId = newUserId ? newUserId.value.trim() : '';
    const displayName = newUserDisplayName ? newUserDisplayName.value.trim() || 'Unknown User' : 'Unknown User';
    const email = newUserEmail ? newUserEmail.value.trim() || '' : '';
    
    // Validate that userId is provided
    if (!userId) {
        showToast('User ID is required', 'warning');
        return;
    }
    
    await addUserToDocument(userId, displayName, email);
    
    // Clear form
    if (newUserId) newUserId.value = '';
    if (newUserDisplayName) newUserDisplayName.value = '';
    if (newUserEmail) newUserEmail.value = '';
}

function clearSearchResults() {
    const tbody = document.querySelector('#userSearchResultsTable tbody');
    if (tbody) {
        tbody.innerHTML = '';
    }
    
    const userSearchTerm = document.getElementById('userSearchTerm');
    if (userSearchTerm) {
        userSearchTerm.value = '';
    }
    
    const searchStatus = document.getElementById('searchStatus');
    if (searchStatus) {
        searchStatus.textContent = '';
    }
}

function resetShareModal() {
    clearSearchResults();
    
    // Clear manual form
    const newUserId = document.getElementById('newUserId');
    const newUserDisplayName = document.getElementById('newUserDisplayName');
    const newUserEmail = document.getElementById('newUserEmail');
    
    if (newUserId) newUserId.value = '';
    if (newUserDisplayName) newUserDisplayName.value = '';
    if (newUserEmail) newUserEmail.value = '';
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