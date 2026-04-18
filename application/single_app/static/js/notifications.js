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
    let workflowAlertQueue = [];
    let activeWorkflowAlert = null;
    let activeWorkflowAlertTargets = [];
    let isLoadingWorkflowAlerts = false;
    const shownWorkflowAlertsStorageKey = 'simplechat-shown-workflow-alerts';
    const workflowAlertModalEl = document.getElementById('workflowAlertModal');
    const workflowAlertModal = workflowAlertModalEl && window.bootstrap
        ? bootstrap.Modal.getOrCreateInstance(workflowAlertModalEl)
        : null;
    const workflowAlertModalContent = workflowAlertModalEl?.querySelector('.workflow-alert-modal-content') || null;
    const workflowAlertPriorityBadge = document.getElementById('workflow-alert-priority-badge');
    const workflowAlertTitle = document.getElementById('workflowAlertModalLabel');
    const workflowAlertTriggeredAt = document.getElementById('workflow-alert-triggered-at');
    const workflowAlertTypeCard = document.getElementById('workflow-alert-type-card');
    const workflowAlertTypeValue = document.getElementById('workflow-alert-type-value');
    const workflowAlertSummaryIcon = document.getElementById('workflow-alert-summary-icon');
    const workflowAlertMeta = document.getElementById('workflow-alert-meta');
    const workflowAlertMessage = document.getElementById('workflow-alert-message');
    const workflowAlertResponsePreview = document.getElementById('workflow-alert-response-preview');
    const workflowAlertResponsePreviewCard = document.getElementById('workflow-alert-response-preview-card');
    const workflowAlertLinks = document.getElementById('workflow-alert-links');
    const workflowAlertMarkReadBtn = document.getElementById('workflow-alert-mark-read-btn');
    const workflowAlertDismissBtn = document.getElementById('workflow-alert-dismiss-btn');
    
    /**
     * Get randomized poll interval
     */
    function getRandomPollInterval() {
        return Math.floor(Math.random() * (MAX_POLL_INTERVAL - MIN_POLL_INTERVAL + 1)) + MIN_POLL_INTERVAL;
    }

    function getShownWorkflowAlertIds() {
        try {
            const storedValue = sessionStorage.getItem(shownWorkflowAlertsStorageKey);
            const parsedValue = storedValue ? JSON.parse(storedValue) : [];
            return Array.isArray(parsedValue) ? parsedValue : [];
        } catch (error) {
            console.warn('Failed to read shown workflow alerts from session storage:', error);
            return [];
        }
    }

    function setShownWorkflowAlertIds(alertIds) {
        try {
            sessionStorage.setItem(
                shownWorkflowAlertsStorageKey,
                JSON.stringify((alertIds || []).slice(-50)),
            );
        } catch (error) {
            console.warn('Failed to persist shown workflow alerts to session storage:', error);
        }
    }

    function hasShownWorkflowAlert(notificationId) {
        return getShownWorkflowAlertIds().includes(notificationId);
    }

    function rememberShownWorkflowAlert(notificationId) {
        if (!notificationId) {
            return;
        }

        const shownAlertIds = getShownWorkflowAlertIds();
        if (shownAlertIds.includes(notificationId)) {
            return;
        }

        shownAlertIds.push(notificationId);
        setShownWorkflowAlertIds(shownAlertIds);
    }

    function getWorkflowAlertPriorityBadgeClass(priority) {
        const normalizedPriority = String(priority || '').trim().toLowerCase();
        if (normalizedPriority === 'high') {
            return 'text-bg-danger';
        }
        if (normalizedPriority === 'medium') {
            return 'text-bg-warning';
        }
        if (normalizedPriority === 'low') {
            return 'text-bg-info';
        }
        return 'text-bg-secondary';
    }

    function formatWorkflowAlertPriorityLabel(priority) {
        const normalizedPriority = String(priority || '').trim().toLowerCase();
        if (!normalizedPriority) {
            return 'ALERT';
        }
        return `${normalizedPriority.toUpperCase()} PRIORITY`;
    }

    function formatWorkflowTriggeredTime(isoString) {
        if (!isoString) {
            return 'Triggered: --:--:--';
        }

        const date = new Date(isoString);
        return `Triggered: ${date.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        })}`;
    }

    function normalizeWorkflowAlertText(text) {
        return String(text || '').replace(/\s+/g, ' ').trim();
    }

    function buildWorkflowAlertSummary(text, maxLength = 140) {
        const normalizedText = normalizeWorkflowAlertText(text);
        if (!normalizedText) {
            return '';
        }

        const sentenceMatch = normalizedText.match(/^(.+?[.!?])(?:\s|$)/);
        if (sentenceMatch && sentenceMatch[1].trim().length >= 24 && sentenceMatch[1].trim().length <= maxLength) {
            return sentenceMatch[1].trim();
        }

        const numberedSplit = normalizedText.split(/\s+\d+\.\s+/)[0].trim();
        if (numberedSplit.length >= 24 && numberedSplit.length <= maxLength) {
            return numberedSplit;
        }

        const dashSplit = normalizedText.split(/\s+-\s+/)[0].trim();
        if (dashSplit.length >= 24 && dashSplit.length <= maxLength) {
            return dashSplit;
        }

        if (normalizedText.length <= maxLength) {
            return normalizedText;
        }

        return `${normalizedText.slice(0, maxLength - 3).trimEnd()}...`;
    }

    function normalizeWorkflowAlertTargetLabel(label) {
        const normalizedLabel = String(label || '').trim();
        const lowerLabel = normalizedLabel.toLowerCase();
        if (lowerLabel === 'open workflow conversation' || lowerLabel === 'open workflow') {
            return 'Open workflow';
        }
        if (lowerLabel.startsWith('open created')) {
            return 'Open created conversation';
        }
        if (lowerLabel.startsWith('open updated')) {
            return 'Open conversation';
        }
        return normalizedLabel || 'Open conversation';
    }

    function isWorkflowAlertWorkflowTarget(target) {
        return String(target?.label || '').trim().toLowerCase() === 'open workflow';
    }

    function getWorkflowAlertTargetPriority(target) {
        const label = String(target?.label || '').trim().toLowerCase();
        const linkContext = target?.link_context || {};
        const workspaceType = String(linkContext.workspace_type || '').trim().toLowerCase();
        const chatType = String(linkContext.chat_type || '').trim().toLowerCase();
        const conversationKind = String(linkContext.conversation_kind || '').trim().toLowerCase();

        let priority = 0;
        if (label.startsWith('open created')) {
            priority += 100;
        } else if (label.startsWith('open conversation')) {
            priority += 60;
        } else {
            priority += 20;
        }

        if (workspaceType === 'group' || chatType.startsWith('group')) {
            priority += 40;
        } else if (workspaceType === 'personal' && (chatType === 'personal_multi_user' || conversationKind === 'collaboration')) {
            priority += 20;
        } else if (workspaceType === 'personal') {
            priority += 10;
        }

        return priority;
    }

    function selectPreferredWorkflowAlertTargets(targets) {
        const workflowTarget = targets.find(target => isWorkflowAlertWorkflowTarget(target)) || null;
        const nonWorkflowTargets = targets.filter(target => !isWorkflowAlertWorkflowTarget(target));
        const selectedTargets = [];

        if (nonWorkflowTargets.length) {
            const preferredTarget = [...nonWorkflowTargets].sort((leftTarget, rightTarget) => (
                getWorkflowAlertTargetPriority(rightTarget) - getWorkflowAlertTargetPriority(leftTarget)
            ))[0];
            selectedTargets.push(preferredTarget);
        }

        if (workflowTarget && (!selectedTargets.length || selectedTargets[0]?.link_context?.conversation_id !== workflowTarget?.link_context?.conversation_id)) {
            selectedTargets.push(workflowTarget);
        }

        return selectedTargets.length ? selectedTargets : targets.slice(0, 1);
    }

    function extractWorkflowEventTitle(text) {
        const normalizedText = normalizeWorkflowAlertText(text);
        if (!normalizedText) {
            return '';
        }

        const numberedMatch = normalizedText.match(/(?:^|\s)\d+\.\s*([^\-:.]{3,90}?)(?=\s+-|\.|:|$)/);
        if (numberedMatch) {
            return numberedMatch[1].trim();
        }

        const headingMatch = normalizedText.match(/^([A-Z][A-Za-z0-9/&()'\s]{5,90}?)(?=\s+-|:|\.)/);
        if (headingMatch) {
            return headingMatch[1].trim();
        }

        return '';
    }

    function buildWorkflowAlertTitle(notification, summaryText, detailText) {
        const metadata = notification?.metadata || {};
        const explicitTitle = normalizeWorkflowAlertText(metadata.event_title || metadata.alert_title || '');
        if (explicitTitle) {
            return explicitTitle;
        }

        const extractedTitle = extractWorkflowEventTitle(detailText) || extractWorkflowEventTitle(summaryText);
        if (extractedTitle) {
            return extractedTitle;
        }

        const normalizedNotificationTitle = normalizeWorkflowAlertText(notification?.title || '');
        const strippedNotificationTitle = normalizedNotificationTitle.replace(/^(low|medium|high)\s+priority\s+workflow\s+alert:\s*/i, '').trim();
        if (strippedNotificationTitle) {
            return strippedNotificationTitle;
        }

        return normalizeWorkflowAlertText(metadata.workflow_name || '') || 'Workflow alert';
    }

    function buildWorkflowAlertType(notification, alertTitle) {
        const metadata = notification?.metadata || {};
        const workflowName = normalizeWorkflowAlertText(metadata.workflow_name || '');
        if (workflowName && workflowName.toLowerCase() !== String(alertTitle || '').trim().toLowerCase()) {
            return workflowName;
        }

        const runnerType = String(metadata.runner_type || '').trim().toLowerCase();
        if (runnerType === 'agent') {
            return 'Agent Workflow';
        }
        if (runnerType === 'model') {
            return 'Model Workflow';
        }
        return '';
    }

    function getWorkflowAlertTargetButtonClass(target, index) {
        const label = String(target?.label || '').trim().toLowerCase();
        if (label.startsWith('open created')) {
            return 'btn btn-success';
        }
        if (label === 'open workflow') {
            return 'btn btn-outline-secondary';
        }
        return `btn ${index === 0 ? 'btn-primary' : 'btn-outline-primary'}`;
    }

    function normalizeWorkflowAlertTargets(notification) {
        const metadata = notification?.metadata || {};
        const rawTargets = Array.isArray(metadata.link_targets) ? metadata.link_targets : [];
        const normalizedTargets = [];
        const seenTargetKeys = new Set();

        rawTargets.forEach(target => {
            if (!target || !target.link_url) {
                return;
            }

            const linkContext = target.link_context || {};
            const dedupeKey = linkContext.conversation_id || target.link_url;
            if (!dedupeKey || seenTargetKeys.has(dedupeKey)) {
                return;
            }

            seenTargetKeys.add(dedupeKey);
            normalizedTargets.push({
                label: normalizeWorkflowAlertTargetLabel(target.label),
                link_url: target.link_url,
                link_context: linkContext,
            });
        });

        if (!normalizedTargets.length && notification?.link_url) {
            normalizedTargets.push({
                label: 'Open conversation',
                link_url: notification.link_url,
                link_context: notification.link_context || {},
            });
        }

        return selectPreferredWorkflowAlertTargets(normalizedTargets);
    }

    function populateWorkflowAlertModal(notification) {
        if (!workflowAlertModal) {
            return;
        }

        const metadata = notification?.metadata || {};
        const priority = String(metadata.priority || notification?.priority || 'medium').trim().toLowerCase();
        const workflowName = metadata.workflow_name || notification?.title || 'Workflow';
        const triggerSource = metadata.trigger_source || '';
        const detailText = normalizeWorkflowAlertText(metadata.response_preview || metadata.error || '');
        const summaryText = buildWorkflowAlertSummary(
            normalizeWorkflowAlertText(notification?.message || '') || detailText || 'Workflow update available.',
        );
        const alertTitle = buildWorkflowAlertTitle(notification, summaryText, detailText);
        const alertType = buildWorkflowAlertType(notification, alertTitle);
        const metaParts = [];
        if (triggerSource) {
            metaParts.push(`Trigger: ${triggerSource}`);
        }
        if (metadata.runner_type) {
            metaParts.push(`Runner: ${String(metadata.runner_type).trim()}`);
        }
        metaParts.push(formatRelativeTime(notification.created_at));

        if (workflowAlertModalContent) {
            workflowAlertModalContent.dataset.priority = priority || 'medium';
        }
        if (workflowAlertPriorityBadge) {
            workflowAlertPriorityBadge.className = `badge text-uppercase ${getWorkflowAlertPriorityBadgeClass(priority)}`;
            workflowAlertPriorityBadge.textContent = formatWorkflowAlertPriorityLabel(priority);
        }
        if (workflowAlertTitle) {
            workflowAlertTitle.textContent = alertTitle || workflowName || 'Workflow alert';
        }
        if (workflowAlertTriggeredAt) {
            workflowAlertTriggeredAt.innerHTML = `<span>Triggered:</span> <strong>${escapeHtml(formatWorkflowTriggeredTime(notification.created_at).replace(/^Triggered:\s*/, ''))}</strong>`;
        }
        if (workflowAlertTypeCard && workflowAlertTypeValue) {
            if (alertType) {
                workflowAlertTypeValue.textContent = alertType;
                workflowAlertTypeCard.classList.remove('d-none');
            } else {
                workflowAlertTypeValue.textContent = '';
                workflowAlertTypeCard.classList.add('d-none');
            }
        }
        if (workflowAlertSummaryIcon) {
            const iconClass = String(notification?.type_config?.icon || 'bi-bell-fill').trim();
            workflowAlertSummaryIcon.className = `bi ${iconClass}`;
        }
        if (workflowAlertMeta) {
            workflowAlertMeta.innerHTML = metaParts.filter(Boolean).map(item => `
                <span><i class="bi bi-dot"></i>${escapeHtml(item)}</span>
            `).join('');
        }
        if (workflowAlertMessage) {
            workflowAlertMessage.textContent = summaryText || 'Workflow update available.';
        }

        if (workflowAlertResponsePreview && workflowAlertResponsePreviewCard) {
            if (detailText && detailText !== normalizeWorkflowAlertText(summaryText)) {
                workflowAlertResponsePreview.textContent = detailText;
                workflowAlertResponsePreviewCard.classList.remove('d-none');
            } else {
                workflowAlertResponsePreview.textContent = '';
                workflowAlertResponsePreviewCard.classList.add('d-none');
            }
        }

        activeWorkflowAlertTargets = normalizeWorkflowAlertTargets(notification);
        if (workflowAlertLinks) {
            if (!activeWorkflowAlertTargets.length) {
                workflowAlertLinks.innerHTML = '<div class="text-muted small">No linked conversation is available for this alert.</div>';
            } else {
                workflowAlertLinks.innerHTML = activeWorkflowAlertTargets.map((target, index) => `
                    <button
                        type="button"
                        class="${getWorkflowAlertTargetButtonClass(target, index)} text-start"
                        data-workflow-alert-link="${index}"
                    >
                        ${escapeHtml(target.label || 'Open conversation')}
                    </button>
                `).join('');
            }
        }
    }

    function enqueueWorkflowAlerts(notifications) {
        if (!Array.isArray(notifications) || !notifications.length) {
            return;
        }

        const queuedIds = new Set(workflowAlertQueue.map(notification => notification.id));
        notifications.forEach(notification => {
            if (!notification?.id) {
                return;
            }
            if (queuedIds.has(notification.id) || activeWorkflowAlert?.id === notification.id || hasShownWorkflowAlert(notification.id)) {
                return;
            }

            queuedIds.add(notification.id);
            workflowAlertQueue.push(notification);
        });

        showNextWorkflowAlert();
    }

    function showNextWorkflowAlert() {
        if (!workflowAlertModal || activeWorkflowAlert || !workflowAlertQueue.length) {
            return;
        }

        activeWorkflowAlert = workflowAlertQueue.shift();
        activeWorkflowAlertTargets = [];
        rememberShownWorkflowAlert(activeWorkflowAlert.id);
        populateWorkflowAlertModal(activeWorkflowAlert);
        workflowAlertModal.show();
    }

    function loadWorkflowAlerts() {
        if (!workflowAlertModal || isLoadingWorkflowAlerts) {
            return Promise.resolve();
        }

        isLoadingWorkflowAlerts = true;

        return fetch('/api/notifications/workflow-alerts?limit=5')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    enqueueWorkflowAlerts(data.notifications || []);
                }
            })
            .catch(error => {
                console.error('Error loading workflow alerts:', error);
            })
            .finally(() => {
                isLoadingWorkflowAlerts = false;
            });
    }

    function fetchNotificationCount() {
        return fetch('/api/notifications/count')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateNotificationBadge(data.count);
                    if (data.count > 0) {
                        return loadWorkflowAlerts();
                    }
                }
                return undefined;
            })
            .catch(error => {
                console.error('Error polling notification count:', error);
            });
    }

    function refreshNotificationsUi() {
        if (document.getElementById('notifications-container')) {
            loadNotifications();
            return;
        }

        fetchNotificationCount();
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

        fetchNotificationCount()
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
                fetchNotificationCount();
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
            await markNotificationRead(notification.id);
        }

        const groupId = notification.link_context?.group_id || notification.metadata?.group_id;
        if (groupId) {
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
        return fetch(`/api/notifications/${notificationId}/read`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                refreshNotificationsUi();
                return true;
            }
            return false;
        })
        .catch(error => {
            console.error('Error marking notification as read:', error);
            return false;
        });
    }
    
    /**
     * Dismiss notification
     */
    function dismissNotification(notificationId) {
        return fetch(`/api/notifications/${notificationId}/dismiss`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                refreshNotificationsUi();
                return true;
            }
            return false;
        })
        .catch(error => {
            console.error('Error dismissing notification:', error);
            return false;
        });
    }

    function initializeWorkflowAlertModal() {
        if (!workflowAlertModalEl || !workflowAlertModal) {
            return;
        }

        workflowAlertLinks?.addEventListener('click', async function(event) {
            const linkButton = event.target.closest('[data-workflow-alert-link]');
            if (!linkButton || !activeWorkflowAlert) {
                return;
            }

            const linkIndex = Number.parseInt(linkButton.getAttribute('data-workflow-alert-link') || '-1', 10);
            const target = activeWorkflowAlertTargets[linkIndex];
            if (!target?.link_url) {
                return;
            }

            await markNotificationRead(activeWorkflowAlert.id);

            const groupId = target.link_context?.group_id || '';
            if (groupId) {
                try {
                    await fetch('/api/groups/setActive', {
                        method: 'PATCH',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ groupId: groupId })
                    });
                } catch (error) {
                    console.error('Error aligning group context for workflow alert:', error);
                }
            }

            window.location.href = target.link_url;
        });

        workflowAlertMarkReadBtn?.addEventListener('click', async function() {
            if (!activeWorkflowAlert) {
                return;
            }

            await markNotificationRead(activeWorkflowAlert.id);
            workflowAlertModal.hide();
        });

        workflowAlertDismissBtn?.addEventListener('click', async function() {
            if (!activeWorkflowAlert) {
                return;
            }

            await dismissNotification(activeWorkflowAlert.id);
            workflowAlertModal.hide();
        });

        workflowAlertModalEl.addEventListener('hidden.bs.modal', function() {
            activeWorkflowAlert = null;
            activeWorkflowAlertTargets = [];
            showNextWorkflowAlert();
        });

        window.addEventListener('workflow-alert-refresh-requested', function() {
            fetchNotificationCount();
            loadWorkflowAlerts();
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
            initializeWorkflowAlertModal();
            initNotificationsPage();
        });
    } else {
        pollNotificationCount();
        initializeWorkflowAlertModal();
        initNotificationsPage();
    }
    
    // Clean up on page unload
    window.addEventListener('beforeunload', function() {
        if (pollTimeout) {
            clearTimeout(pollTimeout);
        }
    });
    
})();
