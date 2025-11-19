
// Control Center JavaScript functionality
// Handles user management, pagination, modals, and API interactions

class ControlCenter {
    constructor() {
        this.currentPage = 1;
        this.usersPerPage = 50;
        this.searchTerm = '';
        this.accessFilter = 'all';
        this.selectedUsers = new Set();
        this.selectedGroups = new Set();
        this.selectedPublicWorkspaces = new Set();
        this.currentUser = null;
        this.loginsChart = null;
        this.chatsChart = null;
        this.documentsChart = null;
        this.currentTrendDays = 30;
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadUsers();
        this.loadActivityTrends();
        
        // Also load groups and public workspaces on initial page load
        // This ensures they get their cached metrics on first load
        setTimeout(() => {
            this.loadGroups();
            this.loadPublicWorkspaces();
        }, 500); // Small delay to ensure DOM is ready
    }
    
    bindEvents() {
        // Tab switching
        document.getElementById('users-tab')?.addEventListener('click', () => {
            setTimeout(() => this.loadUsers(), 100);
        });
        
        document.getElementById('groups-tab')?.addEventListener('click', () => {
            setTimeout(() => this.loadGroups(), 100);
        });
        
        document.getElementById('workspaces-tab')?.addEventListener('click', () => {
            setTimeout(() => this.loadPublicWorkspaces(), 100);
        });
        
        // Search and filter controls
        document.getElementById('userSearchInput')?.addEventListener('input', 
            this.debounce(() => this.handleSearchChange(), 300));
        document.getElementById('accessFilterSelect')?.addEventListener('change', 
            () => this.handleFilterChange());
        
        // Public workspace search and filter controls
        document.getElementById('publicWorkspaceSearchInput')?.addEventListener('input', 
            this.debounce((e) => this.searchPublicWorkspaces(e.target.value), 300));
        document.getElementById('publicWorkspaceStatusFilterSelect')?.addEventListener('change', 
            (e) => this.filterPublicWorkspacesByStatus(e.target.value));
        
        // Export buttons
        document.getElementById('exportGroupsBtn')?.addEventListener('click', 
            () => this.exportGroupsToCSV());
        document.getElementById('exportPublicWorkspacesBtn')?.addEventListener('click', 
            () => this.exportPublicWorkspacesToCSV());
        
        // Bulk action buttons
        document.getElementById('bulkPublicWorkspaceActionBtn')?.addEventListener('click', 
            () => this.showPublicWorkspaceBulkActionModal());
        
        // Select all checkboxes
        document.getElementById('selectAllPublicWorkspaces')?.addEventListener('change', 
            (e) => this.handleSelectAllPublicWorkspaces(e));
        
        // Additional refresh buttons
        document.getElementById('refreshGroupsBtn')?.addEventListener('click', 
            () => this.loadGroups());
        document.getElementById('refreshPublicWorkspacesBtn')?.addEventListener('click', 
            () => this.refreshPublicWorkspaces());
        
        // Refresh buttons - these reload cached data, don't recalculate metrics
        document.getElementById('refreshUsersBtn')?.addEventListener('click', 
            () => this.loadUsers());
        document.getElementById('refreshStatsBtn')?.addEventListener('click', 
            () => this.refreshStats());
        
        // Export button
        document.getElementById('exportUsersBtn')?.addEventListener('click', 
            () => this.exportUsersToCSV());
        
        // User selection
        document.getElementById('selectAllUsers')?.addEventListener('change', 
            (e) => this.handleSelectAll(e));
        
        // Bulk actions
        document.getElementById('bulkActionBtn')?.addEventListener('click', 
            () => this.showBulkActionModal());
        document.getElementById('executeBulkActionBtn')?.addEventListener('click', 
            () => this.executeBulkAction());
        
        // User management modal
        document.getElementById('saveUserChangesBtn')?.addEventListener('click', 
            () => this.saveUserChanges());
        
        // Modal controls
        document.getElementById('accessStatusSelect')?.addEventListener('change', 
            () => this.toggleAccessDateTime());
        document.getElementById('fileUploadStatusSelect')?.addEventListener('change', 
            () => this.toggleFileUploadDateTime());
        document.getElementById('bulkActionType')?.addEventListener('change', 
            () => this.toggleBulkActionSettings());
        document.getElementById('bulkStatusSelect')?.addEventListener('change', 
            () => this.toggleBulkDateTime());
        
        // Alert action buttons
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.target.getAttribute('data-action');
                if (action === 'View Users') {
                    this.switchToUsersTab();
                }
            });
        });
        
        // Activity trends time period buttons
        document.getElementById('trend-7days')?.addEventListener('click', 
            () => this.changeTrendPeriod(7));
        document.getElementById('trend-30days')?.addEventListener('click', 
            () => this.changeTrendPeriod(30));
        document.getElementById('trend-90days')?.addEventListener('click', 
            () => this.changeTrendPeriod(90));
        document.getElementById('trend-custom')?.addEventListener('click', 
            () => this.toggleCustomDateRange());
        
        // Custom date range handlers
        document.getElementById('applyCustomRange')?.addEventListener('click', 
            () => this.applyCustomDateRange());
        
        // Export functionality
        document.getElementById('executeExportBtn')?.addEventListener('click', 
            () => this.exportActivityTrends());
        
        // Export modal - show/hide custom date range based on radio selection
        document.querySelectorAll('input[name="exportTimeWindow"]').forEach(radio => {
            radio.addEventListener('change', () => this.toggleExportCustomDateRange());
        });
        
        // Chat functionality
        document.getElementById('executeChatBtn')?.addEventListener('click', 
            () => this.chatActivityTrends());
        
        // Chat modal - show/hide custom date range based on radio selection
        document.querySelectorAll('input[name="chatTimeWindow"]').forEach(radio => {
            radio.addEventListener('change', () => this.toggleChatCustomDateRange());
        });
    }
    
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    async loadUsers() {
        this.showLoading(true);
        
        try {
            const params = new URLSearchParams({
                page: this.currentPage,
                per_page: this.usersPerPage,
                search: this.searchTerm,
                access_filter: this.accessFilter
            });
            
            const response = await fetch(`/api/admin/control-center/users?${params}`);
            const data = await response.json();
            
            if (response.ok) {
                this.renderUsers(data.users);
                this.renderPagination(data.pagination);
            } else {
                this.showError('Failed to load users: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            this.showError('Network error: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }
    
    renderUsers(users) {
        const tbody = document.getElementById('usersTableBody');
        if (!tbody) return;
        
        if (users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center py-4">
                        <i class="bi bi-people" style="font-size: 2rem; color: var(--bs-secondary);"></i>
                        <div class="mt-2">No users found</div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = users.map(user => {
            const isSelected = this.selectedUsers.has(user.id);
            return `
                <tr>
                    <td>
                        <input type="checkbox" class="form-check-input user-checkbox" 
                               value="${user.id}" ${isSelected ? 'checked' : ''}>
                    </td>
                    <td>
                        <div class="d-flex align-items-center">
                            ${this.renderUserAvatar(user)}
                            <div>
                                <div class="fw-semibold">${this.escapeHtml(user.display_name || 'Unknown User')}</div>
                                <div class="text-muted small">${this.escapeHtml(user.email || '')}</div>
                                <div class="text-muted small">ID: ${user.id}</div>
                            </div>
                        </div>
                    </td>
                    <td>
                        ${this.renderAccessBadge(user.access_status)}
                    </td>
                    <td>
                        ${this.renderFileUploadBadge(user.file_upload_status)}
                    </td>
                    <td>
                        ${this.renderLoginActivity(user.activity.login_metrics)}
                    </td>
                    <td>
                        ${this.renderChatMetrics(user.activity.chat_metrics)}
                    </td>
                    <td>
                        ${this.renderDocumentMetrics(user.activity.document_metrics)}
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary" 
                                onclick="controlCenter.showUserModal('${user.id}')">
                            <i class="bi bi-gear"></i> Manage
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
        
        // Bind checkbox events
        tbody.querySelectorAll('.user-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => this.handleUserSelection(e));
        });
        
        this.updateBulkActionButton();
    }
    
    renderAccessBadge(status) {
        if (status === 'allow') {
            return '<span class="badge access-allow">Allowed</span>';
        } else if (status === 'deny') {
            return '<span class="badge access-deny">Denied</span>';
        } else if (status.startsWith('deny_until_')) {
            const dateStr = status.substring(11);
            return `<span class="badge access-temporary" title="Until ${this.formatDate(dateStr)}">Temporary</span>`;
        }
        return '<span class="badge bg-secondary">Unknown</span>';
    }
    
    renderFileUploadBadge(status) {
        if (status === 'allow') {
            return '<span class="badge access-allow">Allowed</span>';
        } else if (status === 'deny') {
            return '<span class="badge access-deny">Denied</span>';
        } else if (status.startsWith('deny_until_')) {
            const dateStr = status.substring(11);
            return `<span class="badge access-temporary" title="Until ${this.formatDate(dateStr)}">Temporary</span>`;
        }
        return '<span class="badge bg-secondary">Unknown</span>';
    }
    
    renderUserAvatar(user) {
        if (user.profile_image) {
            return `
                <img src="${user.profile_image}" alt="${this.escapeHtml(user.display_name || user.email)}" 
                     class="rounded-circle me-2" style="width: 32px; height: 32px; object-fit: cover;">
            `;
        } else {
            // Fallback to initials
            const initials = (user.display_name || user.email || 'U').slice(0, 2).toUpperCase();
            return `
                <div class="bg-secondary rounded-circle d-flex align-items-center justify-content-center me-2" 
                     style="width: 32px; height: 32px;">
                    <span class="text-white fw-bold" style="font-size: 0.8rem;">
                        ${initials}
                    </span>
                </div>
            `;
        }
    }
    
    renderChatMetrics(chatMetrics) {
        if (!chatMetrics) {
            return '<div class="small text-muted">No data<br><em>Use Refresh Data button</em></div>';
        }
        
        const totalConversations = chatMetrics.total_conversations || 0;
        const totalMessages = chatMetrics.total_messages || 0;
        const messageSize = chatMetrics.total_message_size || 0;
        
        // If all values are zero/empty, show refresh message
        if (totalConversations === 0 && totalMessages === 0 && messageSize === 0) {
            return '<div class="small text-muted">No cached data<br><em>Use Refresh Data button</em></div>';
        }
        
        return `
            <div class="small">
                <div><strong>Total:</strong> ${totalConversations} convos</div>
                <div><strong>Messages:</strong> ${totalMessages}</div>
                <div class="text-muted">Size: ${this.formatBytes(messageSize)}</div>
            </div>
        `;
    }
    
    renderDocumentMetrics(docMetrics) {
        if (!docMetrics) {
            return '<div class="small text-muted">No data<br><em>Use Refresh Data button</em></div>';
        }
        
        const totalDocs = docMetrics.total_documents || 0;
        const aiSearchSize = docMetrics.ai_search_size || 0;
        const storageSize = docMetrics.storage_account_size || 0;
        // Always get enhanced citation setting from app settings, not user data
        const enhancedCitation = (typeof appSettings !== 'undefined' && appSettings.enable_enhanced_citations) || false;
        const personalWorkspace = docMetrics.personal_workspace_enabled;
        
        // If all values are zero/empty, show refresh message
        if (totalDocs === 0 && aiSearchSize === 0 && storageSize === 0) {
            return '<div class="small text-muted">No cached data<br><em>Use Refresh Data button</em></div>';
        }
        
        let html = `
            <div class="small">
                <div><strong>Total Docs:</strong> ${totalDocs}</div>
                <div><strong>AI Search:</strong> ${this.formatBytes(aiSearchSize)}</div>
        `;
        
        if (enhancedCitation) {
            html += `<div><strong>Storage:</strong> ${this.formatBytes(storageSize)}</div>`;
        }
        
        const features = [];
        if (personalWorkspace) features.push('Personal');
        if (enhancedCitation) features.push('Enhanced');
        
        if (features.length > 0) {
            html += `<div class="text-muted" style="font-size: 0.75rem;">(${features.join(' + ')})</div>`;
        }
        
        html += '</div>';
        return html;
    }
    
    renderGroupDocumentMetrics(docMetrics) {
        if (!docMetrics) {
            return '<div class="small text-muted">No data<br><em>Use Refresh Data button</em></div>';
        }
        
        const totalDocs = docMetrics.total_documents || 0;
        const aiSearchSize = docMetrics.ai_search_size || 0;
        const storageSize = docMetrics.storage_account_size || 0;
        // Always get enhanced citation setting from app settings, not user data
        const enhancedCitation = (typeof appSettings !== 'undefined' && appSettings.enable_enhanced_citations) || false;
        
        // If all values are zero/empty, show refresh message
        if (totalDocs === 0 && aiSearchSize === 0 && storageSize === 0) {
            return '<div class="small text-muted">No cached data<br><em>Use Refresh Data button</em></div>';
        }
        
        let html = `
            <div class="small">
                <div><strong>Total Docs:</strong> ${totalDocs}</div>
                <div><strong>AI Search:</strong> ${this.formatBytes(aiSearchSize)}</div>
        `;
        
        if (enhancedCitation) {
            html += `<div><strong>Storage:</strong> ${this.formatBytes(storageSize)}</div>`;
        }
        
        html += '<div class="text-muted" style="font-size: 0.75rem;">(Enhanced)</div>';
        html += '</div>';
        return html;
    }
    
    renderLoginActivity(loginMetrics) {
        if (!loginMetrics) {
            return '<div class="small text-muted">No login data<br><em>Use Refresh Data button</em></div>';
        }
        
        const totalLogins = loginMetrics.total_logins || 0;
        const lastLogin = loginMetrics.last_login;
        
        // If no logins recorded and no last login, show refresh message
        if (totalLogins === 0 && !lastLogin) {
            return '<div class="small text-muted">No cached data<br><em>Use Refresh Data button</em></div>';
        }
        
        let lastLoginFormatted = 'Never';
        if (lastLogin) {
            try {
                const date = new Date(lastLogin);
                // Format as MM/DD/YYYY
                lastLoginFormatted = date.toLocaleDateString('en-US', {
                    month: '2-digit',
                    day: '2-digit',
                    year: 'numeric'
                });
            } catch {
                lastLoginFormatted = 'Invalid date';
            }
        }
        
        return `
            <div class="small">
                <div><strong>Last Login:</strong> ${lastLoginFormatted}</div>
                <div><strong>Total Logins:</strong> ${totalLogins}</div>
            </div>
        `;
    }
    
    renderPagination(pagination) {
        const paginationInfo = document.getElementById('usersPaginationInfo');
        const paginationNav = document.getElementById('usersPagination');
        
        if (paginationInfo) {
            const start = (pagination.page - 1) * pagination.per_page + 1;
            const end = Math.min(pagination.page * pagination.per_page, pagination.total_items);
            paginationInfo.textContent = `Showing ${start}-${end} of ${pagination.total_items} users`;
        }
        
        if (paginationNav) {
            let paginationHtml = '';
            
            // Previous button
            paginationHtml += `
                <li class="page-item ${!pagination.has_prev ? 'disabled' : ''}">
                    <a class="page-link" href="#" onclick="controlCenter.goToPage(${pagination.page - 1}); return false;">
                        <i class="bi bi-chevron-left"></i>
                    </a>
                </li>
            `;
            
            // Page numbers
            const startPage = Math.max(1, pagination.page - 2);
            const endPage = Math.min(pagination.total_pages, pagination.page + 2);
            
            if (startPage > 1) {
                paginationHtml += `
                    <li class="page-item">
                        <a class="page-link" href="#" onclick="controlCenter.goToPage(1); return false;">1</a>
                    </li>
                `;
                if (startPage > 2) {
                    paginationHtml += '<li class="page-item disabled"><span class="page-link">...</span></li>';
                }
            }
            
            for (let i = startPage; i <= endPage; i++) {
                paginationHtml += `
                    <li class="page-item ${i === pagination.page ? 'active' : ''}">
                        <a class="page-link" href="#" onclick="controlCenter.goToPage(${i}); return false;">${i}</a>
                    </li>
                `;
            }
            
            if (endPage < pagination.total_pages) {
                if (endPage < pagination.total_pages - 1) {
                    paginationHtml += '<li class="page-item disabled"><span class="page-link">...</span></li>';
                }
                paginationHtml += `
                    <li class="page-item">
                        <a class="page-link" href="#" onclick="controlCenter.goToPage(${pagination.total_pages}); return false;">${pagination.total_pages}</a>
                    </li>
                `;
            }
            
            // Next button
            paginationHtml += `
                <li class="page-item ${!pagination.has_next ? 'disabled' : ''}">
                    <a class="page-link" href="#" onclick="controlCenter.goToPage(${pagination.page + 1}); return false;">
                        <i class="bi bi-chevron-right"></i>
                    </a>
                </li>
            `;
            
            paginationNav.innerHTML = paginationHtml;
        }
    }
    
    goToPage(page) {
        this.currentPage = page;
        this.loadUsers();
    }
    
    handleSearchChange() {
        this.searchTerm = document.getElementById('userSearchInput')?.value || '';
        this.currentPage = 1;
        this.loadUsers();
    }
    
    handleFilterChange() {
        this.accessFilter = document.getElementById('accessFilterSelect')?.value || 'all';
        this.currentPage = 1;
        this.loadUsers();
    }
    
    handleSelectAll(e) {
        const checkboxes = document.querySelectorAll('.user-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = e.target.checked;
            if (e.target.checked) {
                this.selectedUsers.add(checkbox.value);
            } else {
                this.selectedUsers.delete(checkbox.value);
            }
        });
        this.updateBulkActionButton();
    }
    
    handleUserSelection(e) {
        if (e.target.checked) {
            this.selectedUsers.add(e.target.value);
        } else {
            this.selectedUsers.delete(e.target.value);
        }
        
        // Update select all checkbox
        const allCheckboxes = document.querySelectorAll('.user-checkbox');
        const checkedCheckboxes = document.querySelectorAll('.user-checkbox:checked');
        const selectAllCheckbox = document.getElementById('selectAllUsers');
        
        if (selectAllCheckbox) {
            if (checkedCheckboxes.length === 0) {
                selectAllCheckbox.indeterminate = false;
                selectAllCheckbox.checked = false;
            } else if (checkedCheckboxes.length === allCheckboxes.length) {
                selectAllCheckbox.indeterminate = false;
                selectAllCheckbox.checked = true;
            } else {
                selectAllCheckbox.indeterminate = true;
            }
        }
        
        this.updateBulkActionButton();
    }
    
    updateBulkActionButton() {
        const bulkActionBtn = document.getElementById('bulkActionBtn');
        if (bulkActionBtn) {
            bulkActionBtn.disabled = this.selectedUsers.size === 0;
        }
        
        const selectedCount = document.getElementById('selectedUserCount');
        if (selectedCount) {
            selectedCount.textContent = this.selectedUsers.size;
        }
    }
    
    updatePublicWorkspaceBulkActionButton() {
        const bulkActionBtn = document.getElementById('publicWorkspaceBulkActionBtn');
        if (bulkActionBtn) {
            bulkActionBtn.disabled = this.selectedPublicWorkspaces.size === 0;
        }
        
        const selectedCount = document.getElementById('selectedPublicWorkspaceCount');
        if (selectedCount) {
            selectedCount.textContent = this.selectedPublicWorkspaces.size;
        }
    }
    
    updateGroupBulkActionButton() {
        const bulkActionBtn = document.getElementById('groupBulkActionBtn');
        if (bulkActionBtn) {
            bulkActionBtn.disabled = this.selectedGroups.size === 0;
        }
        
        const selectedCount = document.getElementById('selectedGroupCount');
        if (selectedCount) {
            selectedCount.textContent = this.selectedGroups.size;
        }
    }
    
    async showUserModal(userId) {
        try {
            // Find user data in current page
            const userCheckbox = document.querySelector(`input[value="${userId}"]`);
            if (!userCheckbox) return;
            
            const userRow = userCheckbox.closest('tr');
            const cells = userRow.querySelectorAll('td');
            
            // Extract user info from table row
            const nameCell = cells[1];
            const userName = nameCell.querySelector('.fw-semibold')?.textContent || 'Unknown User';
            const userEmail = nameCell.querySelector('.text-muted')?.textContent || '';
            
            // Populate modal
            document.getElementById('modalUserName').textContent = userName;
            document.getElementById('modalUserEmail').textContent = userEmail;
            document.getElementById('modalUserDocuments').textContent = cells[4]?.textContent.split('\n')[0] || '0 docs';
            document.getElementById('modalUserLastActivity').textContent = cells[4]?.textContent.split('\n')[1]?.replace('Last: ', '') || 'Unknown';
            
            // Set current user
            this.currentUser = { id: userId, name: userName, email: userEmail };
            
            // Reset form
            document.getElementById('accessStatusSelect').value = 'allow';
            document.getElementById('fileUploadStatusSelect').value = 'allow';
            document.getElementById('accessDateTime').value = '';
            document.getElementById('fileUploadDateTime').value = '';
            this.toggleAccessDateTime();
            this.toggleFileUploadDateTime();
            
            // Show modal
            const modal = new bootstrap.Modal(document.getElementById('userManagementModal'));
            modal.show();
            
        } catch (error) {
            this.showError('Failed to load user details');
        }
    }
    
    toggleAccessDateTime() {
        const select = document.getElementById('accessStatusSelect');
        const group = document.getElementById('accessDateTimeGroup');
        if (select && group) {
            group.style.display = select.value === 'deny_until' ? 'block' : 'none';
        }
    }
    
    toggleFileUploadDateTime() {
        const select = document.getElementById('fileUploadStatusSelect');
        const group = document.getElementById('fileUploadDateTimeGroup');
        if (select && group) {
            group.style.display = select.value === 'deny_until' ? 'block' : 'none';
        }
    }
    
    async saveUserChanges() {
        if (!this.currentUser) return;
        
        this.showLoading(true);
        
        try {
            const accessStatus = document.getElementById('accessStatusSelect').value;
            const fileUploadStatus = document.getElementById('fileUploadStatusSelect').value;
            
            // Update access control
            let accessDateTime = null;
            if (accessStatus === 'deny_until') {
                const dateTimeInput = document.getElementById('accessDateTime').value;
                if (dateTimeInput) {
                    accessDateTime = new Date(dateTimeInput).toISOString();
                }
            }
            
            const accessResponse = await fetch(`/api/admin/control-center/users/${this.currentUser.id}/access`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    status: accessStatus === 'deny_until' ? 'deny' : accessStatus,
                    datetime_to_allow: accessDateTime
                })
            });
            
            if (!accessResponse.ok) {
                const errorData = await accessResponse.json();
                throw new Error(errorData.error || 'Failed to update access');
            }
            
            // Update file upload permissions
            let fileUploadDateTime = null;
            if (fileUploadStatus === 'deny_until') {
                const dateTimeInput = document.getElementById('fileUploadDateTime').value;
                if (dateTimeInput) {
                    fileUploadDateTime = new Date(dateTimeInput).toISOString();
                }
            }
            
            const fileUploadResponse = await fetch(`/api/admin/control-center/users/${this.currentUser.id}/file-uploads`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    status: fileUploadStatus === 'deny_until' ? 'deny' : fileUploadStatus,
                    datetime_to_allow: fileUploadDateTime
                })
            });
            
            if (!fileUploadResponse.ok) {
                const errorData = await fileUploadResponse.json();
                throw new Error(errorData.error || 'Failed to update file upload permissions');
            }
            
            // Close modal and refresh
            bootstrap.Modal.getInstance(document.getElementById('userManagementModal')).hide();
            this.showSuccess('User settings updated successfully');
            this.loadUsers();
            
        } catch (error) {
            this.showError(error.message);
        } finally {
            this.showLoading(false);
        }
    }
    
    showBulkActionModal() {
        if (this.selectedUsers.size === 0) return;
        
        // Reset form
        document.getElementById('bulkActionType').value = '';
        document.getElementById('bulkStatusSelect').value = 'allow';
        document.getElementById('bulkDateTime').value = '';
        this.toggleBulkActionSettings();
        this.toggleBulkDateTime();
        
        const modal = new bootstrap.Modal(document.getElementById('bulkActionModal'));
        modal.show();
    }
    
    toggleBulkActionSettings() {
        const actionType = document.getElementById('bulkActionType').value;
        const settingsGroup = document.getElementById('bulkActionSettings');
        if (settingsGroup) {
            settingsGroup.style.display = actionType ? 'block' : 'none';
        }
    }
    
    toggleBulkDateTime() {
        const select = document.getElementById('bulkStatusSelect');
        const group = document.getElementById('bulkDateTimeGroup');
        if (select && group) {
            group.style.display = select.value === 'deny_until' ? 'block' : 'none';
        }
    }
    
    async executeBulkAction() {
        const actionType = document.getElementById('bulkActionType').value;
        const status = document.getElementById('bulkStatusSelect').value;
        
        if (!actionType || this.selectedUsers.size === 0) return;
        
        this.showLoading(true);
        
        try {
            let datetimeToAllow = null;
            if (status === 'deny_until') {
                const dateTimeInput = document.getElementById('bulkDateTime').value;
                if (dateTimeInput) {
                    datetimeToAllow = new Date(dateTimeInput).toISOString();
                }
            }
            
            const response = await fetch('/api/admin/control-center/users/bulk-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_ids: Array.from(this.selectedUsers),
                    action_type: actionType,
                    settings: {
                        status: status === 'deny_until' ? 'deny' : status,
                        datetime_to_allow: datetimeToAllow
                    }
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                bootstrap.Modal.getInstance(document.getElementById('bulkActionModal')).hide();
                this.showSuccess(data.message);
                this.selectedUsers.clear();
                this.loadUsers();
            } else {
                throw new Error(data.error || 'Bulk action failed');
            }
            
        } catch (error) {
            this.showError(error.message);
        } finally {
            this.showLoading(false);
        }
    }
    
    switchToUsersTab() {
        const usersTab = document.getElementById('users-tab');
        if (usersTab) {
            usersTab.click();
        }
    }
    
    async refreshStats() {
        // Reload the page to refresh statistics
        window.location.reload();
    }
    
    async exportUsersToCSV() {
        try {
            // Show loading state
            const exportBtn = document.getElementById('exportUsersBtn');
            const originalText = exportBtn.innerHTML;
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Exporting...';
            
            // Get all users data (not just current page)
            const response = await fetch('/api/admin/control-center/users?all=true');
            if (!response.ok) {
                throw new Error(`Failed to fetch users: ${response.status}`);
            }
            
            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Failed to fetch users');
            }
            
            // Convert users data to CSV
            const csvContent = this.convertUsersToCSV(data.users);
            
            // Create and download CSV file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            
            // Generate filename with current date
            const now = new Date();
            const dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD format
            link.setAttribute('download', `users_export_${dateStr}.csv`);
            
            // Trigger download
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            this.showSuccess(`Successfully exported ${data.users.length} users to CSV`);
            
        } catch (error) {
            console.error('Export error:', error);
            this.showError(`Export failed: ${error.message}`);
        } finally {
            // Restore button state
            const exportBtn = document.getElementById('exportUsersBtn');
            exportBtn.disabled = false;
            exportBtn.innerHTML = '<i class="bi bi-download me-1"></i>Export';
        }
    }
    
    convertUsersToCSV(users) {
        if (!users || users.length === 0) {
            return 'No users to export';
        }
        
        // Define CSV headers
        const headers = [
            'Name',
            'Email', 
            'Access Status',
            'File Upload Status',
            'Last Login',
            'Total Logins',
            'Total Conversations',
            'Total Messages',
            'Total Documents',
            'AI Search Size (MB)'
        ];
        
        // Add enhanced citations column if enabled
        const enhancedCitationsEnabled = (typeof appSettings !== 'undefined' && appSettings.enable_enhanced_citations) || false;
        if (enhancedCitationsEnabled) {
            headers.push('Storage Account Size (MB)');
        }
        
        // Convert users to CSV rows
        const csvRows = [headers.join(',')];
        
        users.forEach(user => {
            const activity = user.activity || {};
            const loginMetrics = activity.login_metrics || {};
            const chatMetrics = activity.chat_metrics || {};
            const docMetrics = activity.document_metrics || {};
            
            const row = [
                this.escapeCSVField(user.display_name || ''),
                this.escapeCSVField(user.email || user.mail || ''),
                this.escapeCSVField(user.access_status || ''),
                this.escapeCSVField(user.file_upload_status || ''),
                this.escapeCSVField(loginMetrics.last_login || 'Never'),
                loginMetrics.total_logins || 0,
                chatMetrics.total_conversations || 0,
                chatMetrics.total_messages || 0,
                docMetrics.total_documents || 0,
                this.formatBytesForCSV(docMetrics.ai_search_size || 0)
            ];
            
            // Add storage account size if enhanced citations is enabled
            if (enhancedCitationsEnabled) {
                row.push(this.formatBytesForCSV(docMetrics.storage_account_size || 0));
            }
            
            csvRows.push(row.join(','));
        });
        
        return csvRows.join('\n');
    }
    
    escapeCSVField(field) {
        if (field === null || field === undefined) {
            return '';
        }
        
        const stringField = String(field);
        
        // If field contains comma, quote, or newline, wrap in quotes and escape quotes
        if (stringField.includes(',') || stringField.includes('"') || stringField.includes('\n')) {
            return '"' + stringField.replace(/"/g, '""') + '"';
        }
        
        return stringField;
    }
    
    formatBytesForCSV(bytes) {
        if (!bytes || bytes === 0) return '0';
        
        // Convert to MB and round to 2 decimal places
        const mb = bytes / (1024 * 1024);
        return Math.round(mb * 100) / 100;
    }

    convertGroupsToCSV(groups) {
        if (!groups || groups.length === 0) {
            return 'No groups to export';
        }
        
        // Define CSV headers
        const headers = [
            'Group Name',
            'Description',
            'Owner Name', 
            'Owner Email',
            'Member Count',
            'Status',
            'Total Documents',
            'AI Search Size (MB)',
            'Storage Account Size (MB)',
            'Group ID'
        ];
        
        // Convert groups to CSV rows
        const csvRows = [headers.join(',')];
        
        groups.forEach(group => {
            const activity = group.activity || {};
            const docMetrics = activity.document_metrics || {};
            const ownerName = group.owner?.displayName || group.owner?.display_name || 'Unknown';
            const ownerEmail = group.owner?.email || '';
            
            const row = [
                this.escapeCSVField(group.name || ''),
                this.escapeCSVField(group.description || ''),
                this.escapeCSVField(ownerName),
                this.escapeCSVField(ownerEmail),
                group.member_count || 0,
                'Active',
                docMetrics.total_documents || 0,
                this.formatBytesForCSV(docMetrics.ai_search_size || 0),
                this.formatBytesForCSV(docMetrics.storage_account_size || 0),
                this.escapeCSVField(group.id || '')
            ];
            
            csvRows.push(row.join(','));
        });
        
        return csvRows.join('\n');
    }

    convertPublicWorkspacesToCSV(workspaces) {
        if (!workspaces || workspaces.length === 0) {
            return 'No public workspaces to export';
        }
        
        // Define CSV headers
        const headers = [
            'Workspace Name',
            'Description',
            'Owner Name', 
            'Owner Email',
            'Member Count',
            'Status',
            'Total Documents',
            'AI Search Size (MB)',
            'Storage Account Size (MB)',
            'Workspace ID'
        ];
        
        // Convert workspaces to CSV rows
        const csvRows = [headers.join(',')];
        
        workspaces.forEach(workspace => {
            const activity = workspace.activity || {};
            const docMetrics = activity.document_metrics || {};
            const ownerName = workspace.owner?.displayName || workspace.owner?.display_name || workspace.owner_name || 'Unknown';
            const ownerEmail = workspace.owner?.email || workspace.owner_email || '';
            
            const row = [
                this.escapeCSVField(workspace.name || ''),
                this.escapeCSVField(workspace.description || ''),
                this.escapeCSVField(ownerName),
                this.escapeCSVField(ownerEmail),
                workspace.member_count || 0,
                'Active',
                docMetrics.total_documents || 0,
                this.formatBytesForCSV(docMetrics.ai_search_size || 0),
                this.formatBytesForCSV(docMetrics.storage_account_size || 0),
                this.escapeCSVField(workspace.id || '')
            ];
            
            csvRows.push(row.join(','));
        });
        
        return csvRows.join('\n');
    }
    
    showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.toggle('d-none', !show);
        }
    }
    
    showSuccess(message) {
        this.showToast(message, 'success');
    }
    
    showError(message) {
        this.showToast(message, 'danger');
    }
    
    showToast(message, type = 'info') {
        // Create toast HTML
        const toastHtml = `
            <div class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        
        // Get or create toast container
        let toastContainer = document.getElementById('toastContainer');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toastContainer';
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '11000';
            document.body.appendChild(toastContainer);
        }
        
        // Add toast to container
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        
        // Show toast
        const toastElement = toastContainer.lastElementChild;
        const toast = new bootstrap.Toast(toastElement);
        toast.show();
        
        // Remove toast element after it's hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    formatDate(dateString) {
        if (!dateString) return 'Never';
        try {
            return new Date(dateString).toLocaleDateString();
        } catch {
            return 'Invalid date';
        }
    }
    
    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }
    
    // Activity Trends Methods
    async loadActivityTrends() {
        try {
            console.log('🔍 [Frontend Debug] Loading activity trends for', this.currentTrendDays, 'days');
            
            // Build API URL with custom date range if specified
            let apiUrl = `/api/admin/control-center/activity-trends?days=${this.currentTrendDays}`;
            if (this.customStartDate && this.customEndDate) {
                apiUrl += `&start_date=${this.customStartDate}&end_date=${this.customEndDate}`;
            }
            
            const response = await fetch(apiUrl);
            console.log('🔍 [Frontend Debug] API response status:', response.status);
            
            const data = await response.json();
            console.log('🔍 [Frontend Debug] API response data:', data);
            
            if (response.ok) {
                console.log('🔍 [Frontend Debug] Activity data received:', data.activity_data);
                // Render all three charts
                this.renderLoginsChart(data.activity_data);
                this.renderChatsChart(data.activity_data);
                this.renderDocumentsChart(data.activity_data);  // Now renders both personal and group
                // Ensure main loading overlay is hidden after all charts are created
                this.showLoading(false);
            } else {
                console.error('❌ [Frontend Debug] API error:', data.error);
                this.showAllChartsError();
                // Ensure main loading overlay is hidden on API error
                this.showLoading(false);
            }
        } catch (error) {
            console.error('❌ [Frontend Debug] Exception loading activity trends:', error);
            this.showAllChartsError();
            // Ensure main loading overlay is hidden on error
            this.showLoading(false);
        }
    }
    
    renderLoginsChart(activityData) {
        console.log('🔍 [Frontend Debug] Rendering logins chart with data:', activityData.logins);
        this.renderSingleChart('loginsChart', 'logins', activityData.logins, {
            label: 'Logins',
            backgroundColor: 'rgba(255, 193, 7, 0.2)',
            borderColor: '#ffc107'
        });
    }
    
    renderChatsChart(activityData) {
        console.log('🔍 [Frontend Debug] Rendering chats chart with data:', activityData.chats);
        this.renderSingleChart('chatsChart', 'chats', activityData.chats, {
            label: 'Chats',
            backgroundColor: 'rgba(13, 110, 253, 0.2)',
            borderColor: '#0d6efd'
        });
    }
    
    renderDocumentsChart(activityData) {
        console.log('🔍 [Frontend Debug] Rendering documents chart with personal, group, and public data');
        console.log('🔍 [Frontend Debug] Personal documents:', activityData.personal_documents);
        console.log('🔍 [Frontend Debug] Group documents:', activityData.group_documents);
        console.log('🔍 [Frontend Debug] Public documents:', activityData.public_documents);
        
        // Render combined chart with personal, group, and public documents
        this.renderCombinedDocumentsChart('documentsChart', {
            personal: activityData.personal_documents || {},
            group: activityData.group_documents || {},
            public: activityData.public_documents || {}
        });
    }
    
    renderCombinedDocumentsChart(canvasId, documentsData) {
        // Check if Chart.js is available
        if (typeof Chart === 'undefined') {
            console.error(`❌ [Frontend Debug] Chart.js is not loaded. Cannot render documents chart.`);
            this.showChartError(canvasId, 'documents');
            return;
        }
        
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            console.error(`❌ [Frontend Debug] Chart canvas element ${canvasId} not found`);
            return;
        }
        
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            console.error(`❌ [Frontend Debug] Could not get 2D context from ${canvasId} canvas`);
            return;
        }
        
        console.log(`✅ [Frontend Debug] Chart.js loaded, ${canvasId} canvas found, context ready`);
        
        // Show canvas
        canvas.style.display = 'block';
        console.log(`🔍 [Frontend Debug] ${canvasId} canvas displayed`);
        
        // Destroy existing chart if it exists
        if (this.documentsChart) {
            console.log(`🔍 [Frontend Debug] Destroying existing documents chart`);
            this.documentsChart.destroy();
        }
        
        // Prepare data for Chart.js - get all unique dates and sort them
        const personalDates = Object.keys(documentsData.personal || {});
        const groupDates = Object.keys(documentsData.group || {});
        const publicDates = Object.keys(documentsData.public || {});
        const allDates = [...new Set([...personalDates, ...groupDates, ...publicDates])].sort();
        
        console.log(`🔍 [Frontend Debug] Documents date range:`, allDates);
        
        const labels = allDates.map(date => {
            const dateObj = new Date(date);
            return dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        });
        
        // Prepare datasets for personal, group, and public documents
        const personalData = allDates.map(date => (documentsData.personal || {})[date] || 0);
        const groupData = allDates.map(date => (documentsData.group || {})[date] || 0);
        const publicData = allDates.map(date => (documentsData.public || {})[date] || 0);
        
        console.log(`🔍 [Frontend Debug] Personal documents data:`, personalData);
        console.log(`🔍 [Frontend Debug] Group documents data:`, groupData);
        console.log(`🔍 [Frontend Debug] Public documents data:`, publicData);
        
        const datasets = [
            {
                label: 'Personal',
                data: personalData,
                backgroundColor: 'rgba(144, 238, 144, 0.4)',  // Light green
                borderColor: '#90EE90',                        // Light green
                borderWidth: 2,
                fill: false,
                tension: 0.1
            },
            {
                label: 'Group',
                data: groupData,
                backgroundColor: 'rgba(34, 139, 34, 0.4)',    // Medium green (forest green)
                borderColor: '#228B22',                        // Medium green (forest green)
                borderWidth: 2,
                fill: false,
                tension: 0.1
            },
            {
                label: 'Public',
                data: publicData,
                backgroundColor: 'rgba(0, 100, 0, 0.4)',      // Dark green
                borderColor: '#006400',                        // Dark green
                borderWidth: 2,
                fill: false,
                tension: 0.1
            }
        ];
        
        console.log(`🔍 [Frontend Debug] Documents datasets prepared:`, datasets);
        
        // Create new chart
        try {
            this.documentsChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,  // Show legend for multiple datasets
                            position: 'top',
                            labels: {
                                usePointStyle: true,
                                padding: 15
                            }
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                title: function(context) {
                                    const dataIndex = context[0].dataIndex;
                                    const dateStr = allDates[dataIndex];
                                    const date = new Date(dateStr);
                                    return date.toLocaleDateString('en-US', { 
                                        weekday: 'long', 
                                        year: 'numeric', 
                                        month: 'long', 
                                        day: 'numeric' 
                                    });
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            display: true,
                            grid: {
                                display: false
                            }
                        },
                        y: {
                            display: true,
                            beginAtZero: true,
                            grid: {
                                color: 'rgba(0, 0, 0, 0.1)'
                            },
                            ticks: {
                                precision: 0
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    }
                }
            });
            
            console.log(`✅ [Frontend Debug] Documents chart created successfully`);
            
        } catch (error) {
            console.error(`❌ [Frontend Debug] Error creating documents chart:`, error);
            this.showChartError(canvasId, 'documents');
        }
    }

    renderSingleChart(canvasId, chartType, chartData, chartConfig) {
        // Check if Chart.js is available
        if (typeof Chart === 'undefined') {
            console.error(`❌ [Frontend Debug] Chart.js is not loaded. Cannot render ${chartType} chart.`);
            this.showChartError(canvasId, chartType);
            return;
        }
        
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            console.error(`❌ [Frontend Debug] Chart canvas element ${canvasId} not found`);
            return;
        }
        
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            console.error(`❌ [Frontend Debug] Could not get 2D context from ${canvasId} canvas`);
            return;
        }
        
        console.log(`✅ [Frontend Debug] Chart.js loaded, ${canvasId} canvas found, context ready`);
        
        // Show canvas
        canvas.style.display = 'block';
        console.log(`🔍 [Frontend Debug] ${canvasId} canvas displayed`);
        
        // Destroy existing chart if it exists
        const chartProperty = chartType + 'Chart';
        if (this[chartProperty]) {
            console.log(`🔍 [Frontend Debug] Destroying existing ${chartType} chart`);
            this[chartProperty].destroy();
        }
        
        // Prepare data for Chart.js - convert object format to arrays
        console.log(`🔍 [Frontend Debug] Processing ${chartType} data structure...`);
        
        // Get dates and sort them
        const dates = Object.keys(chartData || {}).sort();
        console.log(`🔍 [Frontend Debug] ${chartType} date range:`, dates);
        
        const labels = dates.map(date => {
            const dateObj = new Date(date);
            return dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        });
        
        const data = dates.map(date => chartData[date] || 0);
        
        console.log(`🔍 [Frontend Debug] ${chartType} chart labels:`, labels);
        console.log(`🔍 [Frontend Debug] ${chartType} chart data:`, data);
        
        const dataset = {
            label: chartConfig.label,
            data: data,
            backgroundColor: chartConfig.backgroundColor,
            borderColor: chartConfig.borderColor,
            borderWidth: 2,
            fill: false,
            tension: 0.1
        };
        
        console.log(`🔍 [Frontend Debug] ${chartType} dataset prepared:`, dataset);
        
        // Create new chart
        try {
            this[chartProperty] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [dataset]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false // Charts have headers instead
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                title: function(context) {
                                    const dataIndex = context[0].dataIndex;
                                    const dateStr = dates[dataIndex];
                                    const date = new Date(dateStr);
                                    return date.toLocaleDateString('en-US', { 
                                        weekday: 'long', 
                                        year: 'numeric', 
                                        month: 'long', 
                                        day: 'numeric' 
                                    });
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            display: true,
                            grid: {
                                display: false
                            }
                        },
                        y: {
                            display: true,
                            beginAtZero: true,
                            grid: {
                                color: 'rgba(0, 0, 0, 0.1)'
                            },
                            ticks: {
                                precision: 0
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    elements: {
                        point: {
                            radius: 4,
                            hoverRadius: 6
                        }
                    }
                }
            });
            
            console.log(`✅ [Frontend Debug] ${chartType} chart created successfully`);
            
        } catch (error) {
            console.error(`❌ [Frontend Debug] Error creating ${chartType} chart:`, error);
            this.showChartError(canvasId, chartType);
        }
    }
    
    changeTrendPeriod(days) {
        // Update button active states
        document.querySelectorAll('[id^="trend-"]').forEach(btn => {
            btn.classList.remove('active');
        });
        document.getElementById(`trend-${days}days`).classList.add('active');
        
        // Clear custom date range when switching to preset periods
        this.customStartDate = null;
        this.customEndDate = null;
        
        // Collapse custom date range if it's open
        const customDateRange = document.getElementById('customDateRange');
        if (customDateRange && customDateRange.classList.contains('show')) {
            const collapse = new bootstrap.Collapse(customDateRange, {toggle: false});
            collapse.hide();
        }
        
        // Update current period and reload data
        this.currentTrendDays = days;
        this.loadActivityTrends();
    }
    
    toggleCustomDateRange() {
        // Update button active states
        document.querySelectorAll('[id^="trend-"]').forEach(btn => {
            btn.classList.remove('active');
        });
        document.getElementById('trend-custom').classList.add('active');
        
        // Set default dates (last 30 days)
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - 29);
        
        document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
        document.getElementById('endDate').value = endDate.toISOString().split('T')[0];
    }
    
    applyCustomDateRange() {
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        
        if (!startDate || !endDate) {
            alert('Please select both start and end dates.');
            return;
        }
        
        if (new Date(startDate) > new Date(endDate)) {
            alert('Start date must be before end date.');
            return;
        }
        
        // Calculate days difference for API call
        const start = new Date(startDate);
        const end = new Date(endDate);
        const diffTime = Math.abs(end - start);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
        
        this.currentTrendDays = diffDays;
        this.customStartDate = startDate;
        this.customEndDate = endDate;
        
        this.loadActivityTrends();
    }
    
    toggleExportCustomDateRange() {
        const customRadio = document.getElementById('exportCustom');
        const customDateRange = document.getElementById('exportCustomDateRange');
        
        if (customRadio.checked) {
            customDateRange.style.display = 'block';
            // Set default dates
            const endDate = new Date();
            const startDate = new Date();
            startDate.setDate(startDate.getDate() - 29);
            
            document.getElementById('exportStartDate').value = startDate.toISOString().split('T')[0];
            document.getElementById('exportEndDate').value = endDate.toISOString().split('T')[0];
        } else {
            customDateRange.style.display = 'none';
        }
    }
    
    async exportActivityTrends() {
        try {
            // Get selected charts
            const selectedCharts = [];
            if (document.getElementById('exportLogins').checked) selectedCharts.push('logins');
            if (document.getElementById('exportChats').checked) selectedCharts.push('chats');
            if (document.getElementById('exportPersonalDocuments').checked) selectedCharts.push('personal_documents');
            if (document.getElementById('exportGroupDocuments').checked) selectedCharts.push('group_documents');
            if (document.getElementById('exportPublicDocuments').checked) selectedCharts.push('public_documents');
            
            if (selectedCharts.length === 0) {
                alert('Please select at least one chart to export.');
                return;
            }
            
            // Get selected time window
            const timeWindowRadio = document.querySelector('input[name="exportTimeWindow"]:checked');
            const timeWindow = timeWindowRadio.value;
            
            let exportData = {
                charts: selectedCharts,
                time_window: timeWindow
            };
            
            // Add custom dates if selected
            if (timeWindow === 'custom') {
                const startDate = document.getElementById('exportStartDate').value;
                const endDate = document.getElementById('exportEndDate').value;
                
                if (!startDate || !endDate) {
                    alert('Please select both start and end dates for custom range.');
                    return;
                }
                
                if (new Date(startDate) > new Date(endDate)) {
                    alert('Start date must be before end date.');
                    return;
                }
                
                exportData.start_date = startDate;
                exportData.end_date = endDate;
            }
            
            // Show loading state
            const exportBtn = document.getElementById('executeExportBtn');
            const originalText = exportBtn.innerHTML;
            exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Exporting...';
            exportBtn.disabled = true;
            
            // Make API call
            const response = await fetch('/api/admin/control-center/activity-trends/export', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(exportData)
            });
            
            if (response.ok) {
                // Create download link
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                
                // Get filename from response headers or generate one
                const contentDisposition = response.headers.get('Content-Disposition');
                const filename = contentDisposition 
                    ? contentDisposition.split('filename=')[1].replace(/"/g, '')
                    : 'activity_trends_export.csv';
                
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('exportModal'));
                modal.hide();
                
                // Show success message
                this.showAlert('success', 'Activity trends exported successfully!');
                
            } else {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Export failed');
            }
            
        } catch (error) {
            console.error('Export error:', error);
            this.showAlert('danger', `Export failed: ${error.message}`);
        } finally {
            // Reset button state
            const exportBtn = document.getElementById('executeExportBtn');
            exportBtn.innerHTML = '<i class="bi bi-download me-1"></i>Export CSV';
            exportBtn.disabled = false;
        }
    }
    
    toggleChatCustomDateRange() {
        const customRadio = document.getElementById('chatCustom');
        const customDateRange = document.getElementById('chatCustomDateRange');
        
        if (customRadio.checked) {
            customDateRange.style.display = 'block';
            // Set default dates
            const endDate = new Date();
            const startDate = new Date();
            startDate.setDate(startDate.getDate() - 29);
            
            document.getElementById('chatStartDate').value = startDate.toISOString().split('T')[0];
            document.getElementById('chatEndDate').value = endDate.toISOString().split('T')[0];
        } else {
            customDateRange.style.display = 'none';
        }
    }
    
    async chatActivityTrends() {
        try {
            // Get selected charts
            const selectedCharts = [];
            if (document.getElementById('chatLogins').checked) selectedCharts.push('logins');
            if (document.getElementById('chatChats').checked) selectedCharts.push('chats');
            if (document.getElementById('chatDocuments').checked) selectedCharts.push('documents');
            
            if (selectedCharts.length === 0) {
                alert('Please select at least one chart to include in the chat.');
                return;
            }
            
            // Get selected time window
            const timeWindowRadio = document.querySelector('input[name="chatTimeWindow"]:checked');
            const timeWindow = timeWindowRadio.value;
            
            let chatData = {
                charts: selectedCharts,
                time_window: timeWindow
            };
            
            // Add custom dates if selected
            if (timeWindow === 'custom') {
                const startDate = document.getElementById('chatStartDate').value;
                const endDate = document.getElementById('chatEndDate').value;
                
                if (!startDate || !endDate) {
                    alert('Please select both start and end dates for custom range.');
                    return;
                }
                
                if (new Date(startDate) > new Date(endDate)) {
                    alert('Start date must be before end date.');
                    return;
                }
                
                chatData.start_date = startDate;
                chatData.end_date = endDate;
            }
            
            // Show loading state
            const chatBtn = document.getElementById('executeChatBtn');
            const originalText = chatBtn.innerHTML;
            chatBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Creating Chat...';
            chatBtn.disabled = true;
            
            // Make API call
            const response = await fetch('/api/admin/control-center/activity-trends/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(chatData)
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('chatModal'));
                modal.hide();
                
                // Show success message
                this.showAlert('success', 'Chat conversation created successfully! Redirecting...');
                
                // Redirect to the new conversation
                setTimeout(() => {
                    window.location.href = result.redirect_url;
                }, 1500);
                
            } else {
                throw new Error(result.error || 'Failed to create chat conversation');
            }
            
        } catch (error) {
            console.error('Chat creation error:', error);
            this.showAlert('danger', `Failed to create chat: ${error.message}`);
        } finally {
            // Reset button state
            const chatBtn = document.getElementById('executeChatBtn');
            chatBtn.innerHTML = '<i class="bi bi-chat-dots me-1"></i>Start Chat';
            chatBtn.disabled = false;
        }
    }
    
    destroyAllCharts() {
        // Destroy all chart instances
        if (this.loginsChart) {
            this.loginsChart.destroy();
            this.loginsChart = null;
        }
        if (this.chatsChart) {
            this.chatsChart.destroy();
            this.chatsChart = null;
        }
        if (this.documentsChart) {
            this.documentsChart.destroy();
            this.documentsChart = null;
        }
        if (this.personalDocumentsChart) {
            this.personalDocumentsChart.destroy();
            this.personalDocumentsChart = null;
        }
        if (this.groupDocumentsChart) {
            this.groupDocumentsChart.destroy();
            this.groupDocumentsChart = null;
        }
        console.log('🔍 [Frontend Debug] All charts destroyed');
    }
    
    showAllChartsError() {
        // Show error for all three charts
        this.showChartError('loginsChart', 'logins');
        this.showChartError('chatsChart', 'chats');
        this.showChartError('documentsChart', 'documents');
        
        // Ensure main loading overlay is hidden when showing error
        this.showLoading(false);
        console.log('🔍 [Frontend Debug] Main loading overlay hidden after all charts error');
    }
    
    showChartError(canvasId, chartType) {
        const canvas = document.getElementById(canvasId);
        const chartProperty = chartType + 'Chart';
        
        if (canvas) {
            // Hide canvas
            canvas.style.display = 'none';
            
            // Destroy existing chart if it exists
            if (this[chartProperty]) {
                this[chartProperty].destroy();
                this[chartProperty] = null;
            }
            
            // Find the chart container (parent of canvas)
            const chartContainer = canvas.parentElement;
            if (chartContainer) {
                chartContainer.innerHTML = `
                    <canvas id="${canvasId}" style="display: none;"></canvas>
                    <div class="d-flex flex-column justify-content-center align-items-center h-100 text-muted">
                        <i class="bi bi-exclamation-triangle fs-3 mb-2"></i>
                        <p class="small">Unable to load ${chartType}</p>
                        <button class="btn btn-outline-primary btn-sm" onclick="window.controlCenter.loadActivityTrends()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Retry
                        </button>
                    </div>
                `;
            }
        }
    }
    
    async loadGroups() {
        console.log('🔄 ControlCenter.loadGroups() called - using direct API approach like loadUsers()');
        
        const tbody = document.getElementById('groupsTableBody');
        if (!tbody) {
            console.warn('⚠️  Groups table body not found');
            return;
        }
        
        // Show loading state like users do
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <div class="mt-2">Loading groups...</div>
                </td>
            </tr>
        `;
        
        try {
            // Get current filter values like users do
            const searchTerm = document.getElementById('groupSearchInput')?.value || '';
            const statusFilter = document.getElementById('groupStatusFilterSelect')?.value || 'all';
            
            // Build API URL with filters - same pattern as loadUsers
            // Use cached metrics by default (force_refresh=false) to get pre-calculated data
            const params = new URLSearchParams({
                page: 1,
                per_page: 100,
                search: searchTerm,
                status_filter: statusFilter,
                force_refresh: 'false'  // Use cached metrics for performance
            });
            
            console.log('📡 Fetching groups from API:', `/api/admin/control-center/groups?${params}`);
            
            const response = await fetch(`/api/admin/control-center/groups?${params}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            console.log('📊 Groups data received:', {
                groupCount: data.groups ? data.groups.length : 0,
                sampleGroup: data.groups && data.groups[0] ? {
                    id: data.groups[0].id,
                    name: data.groups[0].name,
                    hasCachedMetrics: !!data.groups[0].activity,
                    storageSize: data.groups[0].activity?.document_metrics?.storage_account_size
                } : null
            });
            
            // Render groups data directly like users
            this.renderGroups(data.groups || []);
            
            console.log('✅ Groups loaded and rendered successfully');
            
        } catch (error) {
            console.error('❌ Error loading groups:', error);
            
            // Show error state like users do
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-4 text-danger">
                        <i class="bi bi-exclamation-triangle" style="font-size: 2rem;"></i>
                        <div class="mt-2">Error loading groups: ${error.message}</div>
                        <button class="btn btn-sm btn-outline-primary mt-2" onclick="window.controlCenter.loadGroups()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Retry
                        </button>
                    </td>
                </tr>
            `;
        }
    }

    renderGroups(groups) {
        const tbody = document.getElementById('groupsTableBody');
        if (!tbody) return;
        
        console.log('🎨 Rendering', groups.length, 'groups');
        
        if (groups.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-4">
                        <i class="bi bi-collection" style="font-size: 2rem; color: var(--bs-secondary);"></i>
                        <div class="mt-2">No groups found</div>
                    </td>
                </tr>
            `;
            return;
        }
        
        // Render groups using the same pattern as users
        tbody.innerHTML = groups.map(group => this.createGroupRow(group)).join('');
        
        // Add event listeners to checkboxes
        const checkboxes = tbody.querySelectorAll('.group-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.selectedGroups.add(e.target.value);
                } else {
                    this.selectedGroups.delete(e.target.value);
                }
                this.updateGroupBulkActionButton();
            });
        });
        
        // Update bulk action button state
        this.updateGroupBulkActionButton();
        
        // Initialize sorting after data is loaded
        if (!window.groupTableSorter) {
            window.groupTableSorter = new GroupTableSorter('groupsTable');
        }
    }
    
    createGroupRow(group) {
        // Format storage size
        const storageSize = group.activity?.document_metrics?.storage_account_size || 0;
        const storageSizeFormatted = storageSize > 0 ? this.formatBytes(storageSize) : '0 B';
        
        // Format AI search size
        const aiSearchSize = group.activity?.document_metrics?.ai_search_size || 0;
        const aiSearchSizeFormatted = aiSearchSize > 0 ? this.formatBytes(aiSearchSize) : '0 B';
        
        // Get document metrics
        const totalDocs = group.activity?.document_metrics?.total_documents || 0;
        
        // Get group info
        const memberCount = group.member_count || 0;
        const ownerName = group.owner?.displayName || group.owner?.display_name || 'Unknown';
        const ownerEmail = group.owner?.email || '';
        
        return `
            <tr>
                <td>
                    <input type="checkbox" class="form-check-input group-checkbox" value="${group.id}">
                </td>
                <td>
                    <div><strong>${this.escapeHtml(group.name || 'Unnamed Group')}</strong></div>
                    <div class="text-muted small">${this.escapeHtml(group.description || 'No description')}</div>
                    <div class="text-muted small">ID: ${group.id}</div>
                </td>
                <td>
                    <div>${this.escapeHtml(ownerName)}</div>
                    <div class="text-muted small">${this.escapeHtml(ownerEmail)}</div>
                </td>
                <td>
                    <span class="badge bg-success">Active</span>
                    <div class="text-muted small">${memberCount} members</div>
                </td>
                <td>
                    <span class="badge bg-success">Active</span>
                </td>
                <td>
                    <div><strong>Total Docs:</strong> ${totalDocs}</div>
                    <div><strong>AI Search:</strong> ${aiSearchSizeFormatted}</div>
                    <div><strong>Storage:</strong> ${storageSizeFormatted}</div>
                    ${group.activity?.document_metrics?.storage_account_size > 0 ? '<div class="text-muted small">(Enhanced)</div>' : ''}
                </td>
                <td>
                    <button class="btn btn-outline-primary btn-sm" onclick="window.controlCenter.manageGroup('${group.id}')">
                        <i class="bi bi-gear me-1"></i>Manage
                    </button>
                </td>
            </tr>
        `;
    }
    
    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    manageGroup(groupId) {
        // Placeholder for group management - can be implemented later
        console.log('Managing group:', groupId);
        alert('Group management functionality would open here');
    }

    // Public Workspaces Management Methods
    async loadPublicWorkspaces() {
        console.log('🌐 ControlCenter.loadPublicWorkspaces() called - using same approach as loadGroups()');
        
        const tbody = document.getElementById('publicWorkspacesTableBody');
        if (!tbody) {
            console.warn('⚠️  Public workspaces table body not found');
            return;
        }
        
        // Show loading state like groups do
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <div class="mt-2">Loading public workspaces...</div>
                </td>
            </tr>
        `;
        
        try {
            // Get current filter values like groups do
            const searchTerm = document.getElementById('publicWorkspaceSearchInput')?.value || '';
            const statusFilter = document.getElementById('publicWorkspaceStatusFilterSelect')?.value || 'all';
            
            // Build API URL with filters - same pattern as loadGroups
            // Use cached metrics by default (force_refresh=false) to get pre-calculated data
            const params = new URLSearchParams({
                page: 1,
                per_page: 100,
                search: searchTerm,
                status_filter: statusFilter,
                force_refresh: 'false'  // Use cached metrics for performance
            });
            
            console.log('📡 Fetching public workspaces from API:', `/api/admin/control-center/public-workspaces?${params}`);
            
            const response = await fetch(`/api/admin/control-center/public-workspaces?${params}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            console.log('📊 Public workspaces data received:', {
                workspaceCount: data.workspaces ? data.workspaces.length : 0,
                sampleWorkspace: data.workspaces && data.workspaces[0] ? {
                    id: data.workspaces[0].id,
                    name: data.workspaces[0].name,
                    hasCachedMetrics: !!data.workspaces[0].activity,
                    storageSize: data.workspaces[0].activity?.document_metrics?.storage_account_size
                } : null
            });
            
            // Render workspaces data directly like groups
            this.renderPublicWorkspaces(data.workspaces || []);
            
            console.log('✅ Public workspaces loaded and rendered successfully');
            
        } catch (error) {
            console.error('❌ Error loading public workspaces:', error);
            
            // Show error state like groups do
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-4 text-danger">
                        <i class="bi bi-exclamation-triangle" style="font-size: 2rem;"></i>
                        <div class="mt-2">Error loading public workspaces: ${error.message}</div>
                        <button class="btn btn-sm btn-outline-primary mt-2" onclick="window.controlCenter.loadPublicWorkspaces()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Retry
                        </button>
                    </td>
                </tr>
            `;
        }
    }

    renderPublicWorkspaces(workspaces) {
        const tbody = document.getElementById('publicWorkspacesTableBody');
        if (!tbody) return;
        
        console.log('🎨 Rendering', workspaces.length, 'public workspaces');
        
        if (workspaces.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-4">
                        <i class="bi bi-globe" style="font-size: 2rem; color: var(--bs-secondary);"></i>
                        <div class="mt-2">No public workspaces found</div>
                    </td>
                </tr>
            `;
            return;
        }
        
        // Render workspaces using the same pattern as groups
        tbody.innerHTML = workspaces.map(workspace => this.createPublicWorkspaceRow(workspace)).join('');
        
        // Add event listeners to checkboxes
        const checkboxes = tbody.querySelectorAll('.public-workspace-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.selectedPublicWorkspaces.add(e.target.value);
                } else {
                    this.selectedPublicWorkspaces.delete(e.target.value);
                }
                this.updatePublicWorkspaceBulkActionButton();
            });
        });
        
        // Update bulk action button state
        this.updatePublicWorkspaceBulkActionButton();
    }
    
    createPublicWorkspaceRow(workspace) {
        // Format storage size
        const storageSize = workspace.activity?.document_metrics?.storage_account_size || 0;
        const storageSizeFormatted = storageSize > 0 ? this.formatBytes(storageSize) : '0 B';
        
        // Format AI search size
        const aiSearchSize = workspace.activity?.document_metrics?.ai_search_size || 0;
        const aiSearchSizeFormatted = aiSearchSize > 0 ? this.formatBytes(aiSearchSize) : '0 B';
        
        // Get document metrics
        const totalDocs = workspace.activity?.document_metrics?.total_documents || 0;
        
        // Get workspace info
        const memberCount = workspace.member_count || 0;
        const ownerName = workspace.owner?.displayName || workspace.owner?.display_name || workspace.owner_name || 'Unknown';
        const ownerEmail = workspace.owner?.email || workspace.owner_email || '';
        
        return `
            <tr>
                <td>
                    <input type="checkbox" class="form-check-input public-workspace-checkbox" value="${workspace.id}">
                </td>
                <td>
                    <div><strong>${workspace.name || 'Unnamed Workspace'}</strong></div>
                    <div class="text-muted small">${workspace.description || 'No description'}</div>
                    <div class="text-muted small">ID: ${workspace.id}</div>
                </td>
                <td>
                    <div>${ownerName}</div>
                    <div class="text-muted small">${ownerEmail}</div>
                </td>
                <td>
                    <span class="badge bg-light text-dark">${memberCount} member${memberCount !== 1 ? 's' : ''}</span>
                </td>
                <td>
                    <span class="badge bg-success">Active</span>
                </td>
                <td>
                    <div><strong>Total Docs:</strong> ${totalDocs}</div>
                    <div><strong>AI Search:</strong> ${aiSearchSizeFormatted}</div>
                    <div><strong>Storage:</strong> ${storageSizeFormatted}</div>
                    ${workspace.activity?.document_metrics?.storage_account_size > 0 ? '<div class="text-muted small">(Enhanced)</div>' : ''}
                </td>
                <td>
                    <button class="btn btn-outline-primary btn-sm" onclick="window.controlCenter.managePublicWorkspace('${workspace.id}')">
                        <i class="bi bi-gear me-1"></i>Manage
                    </button>
                </td>
            </tr>
        `;
    }
    
    managePublicWorkspace(workspaceId) {
        // Placeholder for public workspace management - can be implemented later
        console.log('Managing public workspace:', workspaceId);
        alert('Public workspace management functionality would open here');
    }

    searchPublicWorkspaces(searchTerm) {
        // Debounce search like groups
        clearTimeout(this.publicWorkspaceSearchTimeout);
        this.publicWorkspaceSearchTimeout = setTimeout(() => {
            this.loadPublicWorkspaces();
        }, 300);
    }

    filterPublicWorkspacesByStatus(status) {
        // Reload with new filter
        this.loadPublicWorkspaces();
    }

    refreshPublicWorkspaces() {
        console.log('🌐 Refreshing public workspaces with fresh data...');
        
        // Get current search and filter values
        const searchInput = document.getElementById('publicWorkspaceSearchInput');
        const statusSelect = document.getElementById('publicWorkspaceStatusFilterSelect');
        
        const searchTerm = searchInput ? searchInput.value.trim() : '';
        const statusFilter = statusSelect ? statusSelect.value : 'all';
        
        // Build API URL with force_refresh=true
        const params = new URLSearchParams({
            page: 1,
            per_page: 100,
            search: searchTerm,
            status_filter: statusFilter,
            force_refresh: 'true'  // Force fresh calculation
        });
        
        fetch(`/api/admin/control-center/public-workspaces?${params}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.log('🌍 Refreshed public workspaces data received:', data);
                this.renderPublicWorkspaces(data.workspaces || []);
                
                // Show success message
                this.showAlert('success', 'Public workspaces refreshed successfully');
            })
            .catch(error => {
                console.error('Error refreshing public workspaces:', error);
                this.showAlert('danger', `Error refreshing public workspaces: ${error.message}`);
            });
    }

    async exportGroupsToCSV() {
        try {
            // Show loading state
            const exportBtn = document.getElementById('exportGroupsBtn');
            const originalText = exportBtn.innerHTML;
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Exporting...';
            
            // Get all groups data
            const response = await fetch('/api/admin/control-center/groups?all=true&force_refresh=false');
            if (!response.ok) {
                throw new Error(`Failed to fetch groups: ${response.status}`);
            }
            
            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Failed to fetch groups');
            }
            
            // Convert groups data to CSV
            const csvContent = this.convertGroupsToCSV(data.groups || []);
            
            // Create and download CSV file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            
            // Generate filename with current date
            const now = new Date();
            const dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD format
            link.setAttribute('download', `groups_export_${dateStr}.csv`);
            
            // Trigger download
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            this.showAlert('success', `Successfully exported ${data.groups?.length || 0} groups to CSV`);
            
        } catch (error) {
            console.error('Export error:', error);
            this.showAlert('danger', `Export failed: ${error.message}`);
        } finally {
            // Restore button state
            const exportBtn = document.getElementById('exportGroupsBtn');
            if (exportBtn) {
                exportBtn.disabled = false;
                exportBtn.innerHTML = '<i class="bi bi-download me-1"></i>Export';
            }
        }
    }

    async exportPublicWorkspacesToCSV() {
        try {
            // Show loading state
            const exportBtn = document.getElementById('exportPublicWorkspacesBtn');
            const originalText = exportBtn.innerHTML;
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Exporting...';
            
            // Get all public workspaces data
            const response = await fetch('/api/admin/control-center/public-workspaces?all=true&force_refresh=false');
            if (!response.ok) {
                throw new Error(`Failed to fetch public workspaces: ${response.status}`);
            }
            
            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Failed to fetch public workspaces');
            }
            
            // Convert workspaces data to CSV
            const csvContent = this.convertPublicWorkspacesToCSV(data.workspaces || []);
            
            // Create and download CSV file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            
            // Generate filename with current date
            const now = new Date();
            const dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD format
            link.setAttribute('download', `public_workspaces_export_${dateStr}.csv`);
            
            // Trigger download
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            this.showAlert('success', `Successfully exported ${data.workspaces?.length || 0} public workspaces to CSV`);
            
        } catch (error) {
            console.error('Export error:', error);
            this.showAlert('danger', `Export failed: ${error.message}`);
        } finally {
            // Restore button state
            const exportBtn = document.getElementById('exportPublicWorkspacesBtn');
            if (exportBtn) {
                exportBtn.disabled = false;
                exportBtn.innerHTML = '<i class="bi bi-download me-1"></i>Export';
            }
        }
    }
    
    showAlert(type, message) {
        // Create alert element
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        // Add to page
        document.body.appendChild(alertDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, 5000);
    }
}

// Global functions for refresh functionality
async function refreshControlCenterData() {
    console.log('Refresh function called');
    
    const refreshBtn = document.getElementById('refreshDataBtn');
    const refreshBtnText = document.getElementById('refreshBtnText');
    
    console.log('Elements found:', {
        refreshBtn: !!refreshBtn,
        refreshBtnText: !!refreshBtnText
    });
    
    // Check if elements exist
    if (!refreshBtn || !refreshBtnText) {
        console.error('Refresh button elements not found');
        console.log('Available elements:', {
            refreshDataBtn: document.getElementById('refreshDataBtn'),
            refreshBtnText: document.getElementById('refreshBtnText'),
            allButtons: document.querySelectorAll('button'),
            elementsWithRefresh: document.querySelectorAll('[id*="refresh"]')
        });
        showAlert('Refresh button not found. Please reload the page.', 'danger');
        return;
    }
    
    const originalText = refreshBtnText ? refreshBtnText.textContent : 'Refresh Data';
    const iconElement = refreshBtn ? refreshBtn.querySelector('i') : null;
    
    try {
        // Update button state
        refreshBtn.disabled = true;
        refreshBtnText.textContent = 'Refreshing...';
        if (iconElement) {
            iconElement.className = 'bi bi-arrow-repeat me-1 fa-spin';
        }
        
        // Call refresh API
        const response = await fetch('/api/admin/control-center/refresh', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        
        if (result.success) {
            // Show success message with both users and groups
            const usersMsg = `${result.refreshed_users} users`;
            const groupsMsg = `${result.refreshed_groups || 0} groups`;
            showAlert(`Data refreshed successfully! Updated ${usersMsg} and ${groupsMsg}.`, 'success');
            
            console.log('🎉 Data refresh completed:', {
                refreshed_users: result.refreshed_users,
                refreshed_groups: result.refreshed_groups,
                timestamp: new Date().toISOString()
            });
            
            // Update last refresh timestamp
            await loadRefreshStatus();
            
            console.log('🔄 Starting UI refresh...');
            // Refresh the currently active tab content
            await refreshActiveTabContent();
            
            console.log('✅ Data refresh and view refresh completed successfully');
        } else {
            throw new Error(result.message || 'Failed to refresh data');
        }
        
    } catch (error) {
        console.error('Error refreshing data:', error);
        showAlert(`Failed to refresh data: ${error.message}`, 'danger');
    } finally {
        // Restore button state
        if (refreshBtn) {
            refreshBtn.disabled = false;
        }
        if (refreshBtnText) {
            refreshBtnText.textContent = originalText;
        }
        if (iconElement) {
            iconElement.className = 'bi bi-arrow-clockwise me-1';
        }
    }
}

async function loadRefreshStatus() {
    try {
        const response = await fetch('/api/admin/control-center/refresh-status');
        if (response.ok) {
            const result = await response.json();
            const lastRefreshElement = document.getElementById('lastRefreshTime');
            
            if (lastRefreshElement) {
                if (result.last_refresh_formatted) {
                    lastRefreshElement.textContent = result.last_refresh_formatted;
                    if (lastRefreshElement.parentElement) {
                        lastRefreshElement.parentElement.style.display = '';
                    }
                } else {
                    lastRefreshElement.textContent = 'Never';
                    if (lastRefreshElement.parentElement) {
                        lastRefreshElement.parentElement.style.display = '';
                    }
                }
            } else {
                console.warn('lastRefreshTime element not found');
            }
        } else {
            console.error('Failed to load refresh status:', response.status);
        }
    } catch (error) {
        console.error('Error loading refresh status:', error);
        const lastRefreshElement = document.getElementById('lastRefreshTime');
        if (lastRefreshElement) {
            lastRefreshElement.textContent = 'Error loading';
        }
    }
}

async function refreshActiveTabContent() {
    try {
        console.log('🔄 Refreshing active tab content...');
        
        // Check which tab is currently active
        const activeTab = document.querySelector('.nav-link.active');
        const activeTabContent = document.querySelector('.tab-pane.active');
        
        console.log('🔍 Tab detection:', {
            activeTab: activeTab ? activeTab.id : 'none',
            activeTabContent: activeTabContent ? activeTabContent.id : 'none',
            allTabs: Array.from(document.querySelectorAll('.nav-link')).map(t => ({id: t.id, active: t.classList.contains('active')})),
            windowControlCenter: !!window.controlCenter,
            groupManager: typeof GroupManager !== 'undefined'
        });
        
        if (!activeTab) {
            console.log('📝 No active tab found, checking for direct content...');
            // If no tabs (sidebar navigation), refresh both users and groups
            if (window.controlCenter && window.controlCenter.loadUsers) {
                console.log('👤 Refreshing users in sidebar mode...');
                await window.controlCenter.loadUsers();
            }
            
            if (window.controlCenter && window.controlCenter.loadGroups) {
                console.log('👥 Refreshing groups in sidebar mode...');
                await window.controlCenter.loadGroups();
            }
            return;
        }
        
        const tabId = activeTab ? activeTab.id : null;
        console.log('🎯 Active tab detected:', tabId);
        
        // Refresh content based on active tab
        switch (tabId) {
            case 'dashboard-tab':
                console.log('Refreshing dashboard content...');
                // Refresh dashboard stats if available
                if (window.controlCenter && window.controlCenter.refreshStats) {
                    await window.controlCenter.refreshStats();
                }
                break;
                
            case 'users-tab':
                console.log('Refreshing users table...');
                // Refresh users table
                if (window.controlCenter && window.controlCenter.loadUsers) {
                    await window.controlCenter.loadUsers();
                }
                break;
                
            case 'groups-tab':
                console.log('👥 Refreshing groups content...');
                // Refresh groups using ControlCenter method (same pattern as users)
                if (window.controlCenter && window.controlCenter.loadGroups) {
                    await window.controlCenter.loadGroups();
                }
                break;
                
            case 'workspaces-tab':
                console.log('Refreshing workspaces content...');
                // Refresh public workspaces if available
                if (window.controlCenter && window.controlCenter.loadPublicWorkspaces) {
                    await window.controlCenter.loadPublicWorkspaces();
                }
                break;
                
            case 'activity-tab':
                console.log('Refreshing activity trends...');
                // Refresh activity trends if available
                if (window.controlCenter && window.controlCenter.loadActivityTrends) {
                    await window.controlCenter.loadActivityTrends();
                }
                break;
                
            default:
                console.log('🤔 Unknown or no active tab, attempting to refresh all content...');
                // Default fallback - refresh both users and groups using ControlCenter methods
                if (window.controlCenter && window.controlCenter.loadUsers) {
                    console.log('👤 Fallback: Refreshing users');
                    await window.controlCenter.loadUsers();
                }
                
                if (window.controlCenter && window.controlCenter.loadGroups) {
                    console.log('👥 Fallback: Refreshing groups');
                    await window.controlCenter.loadGroups();
                }
                break;
        }
        
        console.log('Active tab content refresh completed');
        
    } catch (error) {
        console.error('Error refreshing active tab content:', error);
        // Don't throw the error to avoid breaking the main refresh flow
    }
}

function showAlert(message, type = 'info') {
    // Create alert element
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    // Add to page
    document.body.appendChild(alertDiv);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, 5000);
}

// Make refresh function globally accessible for debugging
window.refreshControlCenterData = refreshControlCenterData;
window.loadRefreshStatus = loadRefreshStatus;
window.refreshActiveTabContent = refreshActiveTabContent;
window.debugControlCenterElements = function() {
    console.log('=== Control Center Elements Debug ===');
    console.log('refreshDataBtn:', document.getElementById('refreshDataBtn'));
    console.log('refreshBtnText:', document.getElementById('refreshBtnText'));
    console.log('lastRefreshTime:', document.getElementById('lastRefreshTime'));
    console.log('lastRefreshInfo:', document.getElementById('lastRefreshInfo'));
    console.log('All buttons:', Array.from(document.querySelectorAll('button')).map(b => ({id: b.id, text: b.textContent.trim()})));
    console.log('All spans:', Array.from(document.querySelectorAll('span')).map(s => ({id: s.id, text: s.textContent.trim()})));
};

// Initialize Control Center when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.controlCenter = new ControlCenter();
    
    // Debug: Log element availability
    console.log('Control Center Elements Check on DOM Ready:');
    window.debugControlCenterElements();
    
    // Load initial refresh status with a slight delay to ensure elements are rendered
    setTimeout(() => {
        loadRefreshStatus();
    }, 100);
});