// notifications.js

/**
 * Notifications UI Management
 * 
 * Handles notification polling, rendering, interactions, and badge updates.
 * Polling interval is randomized between 20-40 seconds to prevent thundering herd.
 */

(function() {
    'use strict';
    
    // Configuration
    const MIN_POLL_INTERVAL = 20000; // 20 seconds
    const MAX_POLL_INTERVAL = 40000; // 40 seconds
    
    // State
    let currentPage = 1;
    let currentPerPage = 20;
    let currentFilter = 'all';
    let currentSearch = '';
    let pollTimeout = null;
    let isPolling = false;
    
    /**
     * Get randomized poll interval
     */
    function getRandomPollInterval() {
        return Math.floor(Math.random() * (MAX_POLL_INTERVAL - MIN_POLL_INTERVAL + 1)) + MIN_POLL_INTERVAL;
    }
    
    /**
     * Update notification badge in top nav and sidebar
     */
    function updateNotificationBadge(count) {
        // Top nav badges
        const badge = document.getElementById('notification-badge');
        const countBadge = document.getElementById('notification-count-badge');
        
        // Sidebar badges
        const sidebarBadge = document.getElementById('sidebar-notification-badge');
        const sidebarCountBadge = document.getElementById('sidebar-notification-count-badge');
        
        if (count > 0) {
            const displayCount = count > 9 ? '+' : count.toString();
            
            // Update top nav avatar badge
            if (badge) {
                badge.textContent = displayCount;
                badge.classList.add('d-flex');
                badge.style.display = 'flex';
            }
            
            // Update top nav menu badge
            if (countBadge) {
                countBadge.textContent = displayCount;
                countBadge.style.display = 'inline-block';
            }
            
            // Update sidebar avatar badge
            if (sidebarBadge) {
                sidebarBadge.textContent = displayCount;
                sidebarBadge.classList.add('d-flex');
                sidebarBadge.style.display = 'flex';
            }
            
            // Update sidebar menu badge
            if (sidebarCountBadge) {
                sidebarCountBadge.textContent = displayCount;
                sidebarCountBadge.style.display = 'inline-block';
            }
        } else {
            // Hide all badges
            if (badge) {
                badge.classList.remove('d-flex');
                badge.style.display = 'none';
            }
            
            if (countBadge) {
                countBadge.style.display = 'none';
            }
            
            if (sidebarBadge) {
                sidebarBadge.classList.remove('d-flex');
                sidebarBadge.style.display = 'none';
            }
            
            if (sidebarCountBadge) {
                sidebarCountBadge.style.display = 'none';
            }
        }
    }
    
    /**
     * Poll for notification count
     */
    function pollNotificationCount() {
        if (isPolling) return;
        
        isPolling = true;
        
        fetch('/api/notifications/count')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateNotificationBadge(data.count);
                }
            })
            .catch(error => {
                console.error('Error polling notification count:', error);
            })
            .finally(() => {
                isPolling = false;
                
                // Schedule next poll with randomized interval
                pollTimeout = setTimeout(pollNotificationCount, getRandomPollInterval());
            });
    }
    
    /**
     * Format relative time
     */
    function formatRelativeTime(isoString) {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
        
        return date.toLocaleDateString();
    }
    
    /**
     * Render notification item
     */
    function renderNotification(notification) {
        const isUnread = !notification.is_read;
        const typeConfig = notification.type_config || { icon: 'bi-bell', color: 'secondary' };
        
        return `
            <div class="card mb-2 notification-item ${isUnread ? 'unread' : ''}" data-notification-id="${notification.id}">
                <div class="card-body p-3">
                    <div class="d-flex align-items-start">
                        <div class="notification-icon bg-${typeConfig.color} bg-opacity-10 text-${typeConfig.color} me-3">
                            <i class="bi ${typeConfig.icon}"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="notification-title">${escapeHtml(notification.title)}</div>
                            <div class="notification-message">${escapeHtml(notification.message)}</div>
                            <div class="notification-time">
                                <i class="bi bi-clock me-1"></i>${formatRelativeTime(notification.created_at)}
                            </div>
                        </div>
                        <div class="notification-actions ms-3">
                            ${!isUnread ? '' : `
                                <button class="btn btn-sm btn-outline-primary mark-read-btn me-1" data-notification-id="${notification.id}">
                                    <i class="bi bi-check"></i>
                                </button>
                            `}
                            <button class="btn btn-sm btn-outline-danger dismiss-btn" data-notification-id="${notification.id}">
                                <i class="bi bi-x"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    /**
     * Escape HTML to prevent XSS
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Render pagination
     */
    function renderPagination(page, totalPages, hasMore) {
        if (totalPages <= 1) return '';
        
        let html = '<nav><ul class="pagination">';
        
        // Previous button
        html += `
            <li class="page-item ${page === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${page - 1}">Previous</a>
            </li>
        `;
        
        // Page numbers (show max 7 pages)
        const startPage = Math.max(1, page - 3);
        const endPage = Math.min(totalPages, page + 3);
        
        if (startPage > 1) {
            html += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
            if (startPage > 2) {
                html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            html += `
                <li class="page-item ${i === page ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `;
        }
        
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
            html += `<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`;
        }
        
        // Next button
        html += `
            <li class="page-item ${!hasMore ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${page + 1}">Next</a>
            </li>
        `;
        
        html += '</ul></nav>';
        return html;
    }
    
    /**
     * Load and render notifications
     */
    function loadNotifications() {
        const container = document.getElementById('notifications-container');
        const paginationContainer = document.getElementById('pagination-container');
        const loadingIndicator = document.getElementById('loading-indicator');
        
        if (!container) return;
        
        // Show loading
        loadingIndicator.style.display = 'block';
        container.innerHTML = '';
        
        // Build query parameters
        const params = new URLSearchParams({
            page: currentPage,
            per_page: currentPerPage,
            include_read: currentFilter !== 'unread',
            include_dismissed: false
        });
        
        fetch(`/api/notifications?${params}`)
            .then(response => response.json())
            .then(data => {
                loadingIndicator.style.display = 'none';
                
                if (!data.success) {
                    container.innerHTML = '<div class="alert alert-danger">Failed to load notifications</div>';
                    return;
                }
                
                // Filter by search if needed
                let notifications = data.notifications;
                
                if (currentSearch) {
                    const searchLower = currentSearch.toLowerCase();
                    notifications = notifications.filter(n => 
                        n.title.toLowerCase().includes(searchLower) ||
                        n.message.toLowerCase().includes(searchLower)
                    );
                }
                
                // Filter by read status
                if (currentFilter === 'read') {
                    notifications = notifications.filter(n => n.is_read);
                } else if (currentFilter === 'unread') {
                    notifications = notifications.filter(n => !n.is_read);
                }
                
                // Cache notifications for click handlers
                cachedNotifications = notifications;
                
                // Render notifications
                if (notifications.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <i class="bi bi-bell-slash"></i>
                            <h4>No notifications</h4>
                            <p>You're all caught up!</p>
                        </div>
                    `;
                } else {
                    container.innerHTML = notifications.map(renderNotification).join('');
                    
                    // Attach event listeners
                    attachNotificationListeners();
                }
                
                // Render pagination
                const totalPages = Math.ceil(data.total / currentPerPage);
                paginationContainer.innerHTML = renderPagination(currentPage, totalPages, data.has_more);
                
                // Attach pagination listeners
                attachPaginationListeners();
                
                // Update badge
                pollNotificationCount();
            })
            .catch(error => {
                console.error('Error loading notifications:', error);
                loadingIndicator.style.display = 'none';
                container.innerHTML = '<div class="alert alert-danger">Failed to load notifications</div>';
            });
    }
    
    /**
     * Attach event listeners to notification items
     */
    function attachNotificationListeners() {
        // Click on notification to view/navigate
        document.querySelectorAll('.notification-item').forEach(item => {
            item.addEventListener('click', function(e) {
                // Don't navigate if clicking action buttons
                if (e.target.closest('.mark-read-btn') || e.target.closest('.dismiss-btn')) {
                    return;
                }
                
                const notificationId = this.dataset.notificationId;
                const notification = getNotificationById(notificationId);
                
                if (notification) {
                    handleNotificationClick(notification);
                }
            });
        });
        
        // Mark as read buttons
        document.querySelectorAll('.mark-read-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const notificationId = this.dataset.notificationId;
                markNotificationRead(notificationId);
            });
        });
        
        // Dismiss buttons
        document.querySelectorAll('.dismiss-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const notificationId = this.dataset.notificationId;
                dismissNotification(notificationId);
            });
        });
    }
    
    /**
     * Attach pagination listeners
     */
    function attachPaginationListeners() {
        document.querySelectorAll('.page-link').forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                const page = parseInt(this.dataset.page);
                if (page && !isNaN(page)) {
                    currentPage = page;
                    loadNotifications();
                }
            });
        });
    }
    
    /**
     * Get notification data by ID (stored during render)
     */
    let cachedNotifications = [];
    
    function getNotificationById(id) {
        return cachedNotifications.find(n => n.id === id);
    }
    
    /**
     * Handle notification click
     */
    async function handleNotificationClick(notification) {
        // Mark as read
        if (!notification.is_read) {
            markNotificationRead(notification.id);
        }
        
        // Check if this is a group notification - set active group before navigating
        const groupId = notification.metadata?.group_id;
        if (groupId && notification.link_url === '/group_workspaces') {
            try {
                const response = await fetch('/api/groups/setActive', {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ groupId: groupId })
                });
                
                if (!response.ok) {
                    console.error('Failed to set active group:', await response.text());
                }
            } catch (error) {
                console.error('Error setting active group:', error);
            }
        }
        
        // Navigate if link exists
        if (notification.link_url) {
            window.location.href = notification.link_url;
        }
    }
    
    /**
     * Mark notification as read
     */
    function markNotificationRead(notificationId) {
        fetch(`/api/notifications/${notificationId}/read`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications();
            }
        })
        .catch(error => {
            console.error('Error marking notification as read:', error);
        });
    }
    
    /**
     * Dismiss notification
     */
    function dismissNotification(notificationId) {
        fetch(`/api/notifications/${notificationId}/dismiss`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadNotifications();
            }
        })
        .catch(error => {
            console.error('Error dismissing notification:', error);
        });
    }
    
    /**
     * Initialize page
     */
    function initNotificationsPage() {
        // Only run on notifications page
        if (!window.location.pathname.includes('/notifications')) {
            return;
        }
        
        // Get user's per-page preference
        const perPageSelect = document.getElementById('per-page-select');
        if (perPageSelect) {
            currentPerPage = parseInt(perPageSelect.value);
            
            perPageSelect.addEventListener('change', function() {
                currentPerPage = parseInt(this.value);
                currentPage = 1;
                
                // Save preference
                fetch('/api/notifications/settings', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        notifications_per_page: currentPerPage
                    })
                });
                
                loadNotifications();
            });
        }
        
        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                currentFilter = this.dataset.filter;
                currentPage = 1;
                loadNotifications();
            });
        });
        
        // Search input
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener('input', function() {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    currentSearch = this.value;
                    currentPage = 1;
                    loadNotifications();
                }, 500);
            });
        }
        
        // Mark all as read button
        const markAllReadBtn = document.getElementById('mark-all-read-btn');
        if (markAllReadBtn) {
            markAllReadBtn.addEventListener('click', function() {
                fetch('/api/notifications/mark-all-read', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        loadNotifications();
                    }
                })
                .catch(error => {
                    console.error('Error marking all as read:', error);
                });
            });
        }
        
        // Refresh button
        const refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function() {
                loadNotifications();
            });
        }
        
        // Initial load
        loadNotifications();
    }
    
    // Start polling when page loads (for badge updates)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            pollNotificationCount();
            initNotificationsPage();
        });
    } else {
        pollNotificationCount();
        initNotificationsPage();
    }
    
    // Clean up on page unload
    window.addEventListener('beforeunload', function() {
        if (pollTimeout) {
            clearTimeout(pollTimeout);
        }
    });
    
})();
