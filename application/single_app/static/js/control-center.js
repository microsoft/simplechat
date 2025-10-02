// Control Center JavaScript functionality
// Handles user management, pagination, modals, and API interactions

class ControlCenter {
    constructor() {
        this.currentPage = 1;
        this.usersPerPage = 50;
        this.searchTerm = '';
        this.accessFilter = 'all';
        this.selectedUsers = new Set();
        this.currentUser = null;
        this.activityChart = null;
        this.currentTrendDays = 30;
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadUsers();
        this.loadActivityTrends();
    }
    
    bindEvents() {
        // Tab switching
        document.getElementById('users-tab')?.addEventListener('click', () => {
            setTimeout(() => this.loadUsers(), 100);
        });
        
        // Search and filter controls
        document.getElementById('userSearchInput')?.addEventListener('input', 
            this.debounce(() => this.handleSearchChange(), 300));
        document.getElementById('accessFilterSelect')?.addEventListener('change', 
            () => this.handleFilterChange());
        
        // Refresh buttons
        document.getElementById('refreshUsersBtn')?.addEventListener('click', 
            () => this.loadUsers());
        document.getElementById('refreshStatsBtn')?.addEventListener('click', 
            () => this.refreshStats());
        
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
                    <td colspan="7" class="text-center py-4">
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
                            <div class="bg-secondary rounded-circle d-flex align-items-center justify-content-center me-2" 
                                 style="width: 32px; height: 32px;">
                                <span class="text-white fw-bold" style="font-size: 0.8rem;">
                                    ${(user.display_name || user.email || 'U').slice(0, 2).toUpperCase()}
                                </span>
                            </div>
                            <div>
                                <div class="fw-semibold">${this.escapeHtml(user.display_name || 'Unknown User')}</div>
                                <div class="text-muted small">${this.escapeHtml(user.email || '')}</div>
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
                        <div class="small">
                            <div>Chat: ${user.activity.chat_volume_3m || 0} (3m)</div>
                            <div class="text-muted">Last: ${this.formatDate(user.lastUpdated)}</div>
                        </div>
                    </td>
                    <td>
                        <div class="small">
                            <div>${user.activity.document_count || 0} docs</div>
                            <div class="text-muted">${this.formatBytes(user.activity.document_storage_size || 0)}</div>
                        </div>
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
            
            const response = await fetch(`/api/admin/control-center/activity-trends?days=${this.currentTrendDays}`);
            console.log('🔍 [Frontend Debug] API response status:', response.status);
            
            const data = await response.json();
            console.log('🔍 [Frontend Debug] API response data:', data);
            
            if (response.ok) {
                console.log('🔍 [Frontend Debug] Activity data received:', data.activity_data);
                this.renderActivityChart(data.activity_data);
            } else {
                console.error('❌ [Frontend Debug] API error:', data.error);
                this.showActivityTrendsError();
            }
        } catch (error) {
            console.error('❌ [Frontend Debug] Exception loading activity trends:', error);
            this.showActivityTrendsError();
        }
    }
    
    renderActivityChart(activityData) {
        console.log('🔍 [Frontend Debug] Rendering chart with data:', activityData);
        
        // Check if Chart.js is available
        if (typeof Chart === 'undefined') {
            console.error('❌ [Frontend Debug] Chart.js is not loaded. Cannot render activity chart.');
            this.showActivityTrendsError();
            return;
        }
        
        const canvas = document.getElementById('activityTrendsChart');
        if (!canvas) {
            console.error('❌ [Frontend Debug] Chart canvas element not found');
            return;
        }
        
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            console.error('❌ [Frontend Debug] Could not get 2D context from canvas');
            return;
        }
        
        console.log('✅ [Frontend Debug] Chart.js loaded, canvas found, context ready');
        
        // Hide loading indicator and show canvas
        const loadingDiv = document.getElementById('activityTrendsLoading');
        if (loadingDiv) loadingDiv.style.display = 'none';
        canvas.style.display = 'block';
        
        // Destroy existing chart if it exists
        if (this.activityChart) {
            console.log('🔍 [Frontend Debug] Destroying existing chart');
            this.activityChart.destroy();
        }
        
        // Prepare data for Chart.js - convert object format to arrays
        console.log('🔍 [Frontend Debug] Processing activity data structure...');
        
        // Get all dates and sort them
        const allDates = new Set();
        if (activityData.chats) Object.keys(activityData.chats).forEach(date => allDates.add(date));
        if (activityData.documents) Object.keys(activityData.documents).forEach(date => allDates.add(date));
        if (activityData.logins) Object.keys(activityData.logins).forEach(date => allDates.add(date));
        
        const sortedDates = Array.from(allDates).sort();
        console.log('🔍 [Frontend Debug] Date range:', sortedDates);
        
        const labels = sortedDates.map(date => {
            const dateObj = new Date(date);
            return dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        });
        
        console.log('🔍 [Frontend Debug] Chart labels:', labels);
        
        const datasets = [
            {
                label: 'Chats',
                data: sortedDates.map(date => activityData.chats[date] || 0),
                backgroundColor: 'rgba(13, 110, 253, 0.2)',
                borderColor: '#0d6efd',
                borderWidth: 2,
                fill: false,
                tension: 0.1
            },
            {
                label: 'Documents',
                data: sortedDates.map(date => activityData.documents[date] || 0),
                backgroundColor: 'rgba(25, 135, 84, 0.2)',
                borderColor: '#198754',
                borderWidth: 2,
                fill: false,
                tension: 0.1
            },
            {
                label: 'Logins',
                data: sortedDates.map(date => activityData.logins[date] || 0),
                backgroundColor: 'rgba(255, 193, 7, 0.2)',
                borderColor: '#ffc107',
                borderWidth: 2,
                fill: false,
                tension: 0.1
            }
        ];
        
        console.log('🔍 [Frontend Debug] Chart datasets prepared:', datasets);
        
        // Create new chart
        this.activityChart = new Chart(ctx, {
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
                        display: false // Using custom legend below chart
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: function(context) {
                                const dataIndex = context[0].dataIndex;
                                const date = new Date(activityData[dataIndex].date);
                                return date.toLocaleDateString('en-US', { 
                                    weekday: 'long', 
                                    year: 'numeric', 
                                    month: 'long', 
                                    day: 'numeric' 
                                });
                            },
                            afterBody: function(context) {
                                const dataIndex = context[0].dataIndex;
                                return `Total Activity: ${activityData[dataIndex].total}`;
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
    }
    
    changeTrendPeriod(days) {
        // Update button active states
        document.querySelectorAll('[id^="trend-"]').forEach(btn => {
            btn.classList.remove('active');
        });
        document.getElementById(`trend-${days}days`).classList.add('active');
        
        // Update current period and reload data
        this.currentTrendDays = days;
        this.loadActivityTrends();
    }
    
    showActivityTrendsError() {
        const chartContainer = document.getElementById('activityTrendsChartContainer');
        const canvas = document.getElementById('activityTrendsChart');
        const loadingDiv = document.getElementById('activityTrendsLoading');
        
        if (chartContainer) {
            // Hide canvas and loading, show error
            if (canvas) canvas.style.display = 'none';
            if (loadingDiv) loadingDiv.style.display = 'none';
            
            // Destroy existing chart if it exists
            if (this.activityChart) {
                this.activityChart.destroy();
                this.activityChart = null;
            }
            
            chartContainer.innerHTML = `
                <canvas id="activityTrendsChart" style="display: none;"></canvas>
                <div class="d-flex flex-column justify-content-center align-items-center h-100 text-muted">
                    <i class="bi bi-exclamation-triangle fs-1 mb-2"></i>
                    <p>Unable to load activity trends</p>
                    <button class="btn btn-outline-primary btn-sm" onclick="window.controlCenter.loadActivityTrends()">
                        <i class="bi bi-arrow-clockwise me-1"></i>Retry
                    </button>
                </div>
            `;
        }
    }
}

// Initialize Control Center when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.controlCenter = new ControlCenter();
});