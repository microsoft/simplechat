// admin-safety-violations.js

(function () {
    const state = {
        currentPage: 1,
        pageSize: 10,
        items: [],
        userCache: {},
        activeItem: null,
    };

    const SAFETY_REMEDIATION_ACTIONS = new Set(['WarnUser', 'SuspendUser', 'BlockUser']);
    const ACTION_LABELS = {
        None: 'None',
        WarnUser: 'Warn user',
        SuspendUser: 'Suspend user',
        Escalate: 'Escalate',
        BlockUser: 'Block user',
    };

    let editModalInstance = null;

    function clearElement(element) {
        if (!element) {
            return;
        }

        while (element.firstChild) {
            element.removeChild(element.firstChild);
        }
    }

    function setTextContent(elementId, value) {
        const element = document.getElementById(elementId);
        if (!element) {
            return;
        }

        element.textContent = value == null || value === '' ? '-' : String(value);
    }

    function setElementHidden(element, hidden) {
        if (!element) {
            return;
        }

        element.classList.toggle('d-none', hidden);
    }

    function clearPageStatus() {
        const alertElement = document.getElementById('safetyPageStatusAlert');
        if (!alertElement) {
            return;
        }

        alertElement.textContent = '';
        alertElement.className = 'alert d-none mb-3';
    }

    function showPageStatus(message, variant) {
        const alertElement = document.getElementById('safetyPageStatusAlert');
        if (!alertElement) {
            return;
        }

        alertElement.textContent = message;
        alertElement.className = `alert alert-${variant || 'info'} mb-3`;
    }

    function renderTableMessage(message, isError) {
        const tbody = document.querySelector('#safetyLogsTable tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        const row = document.createElement('tr');
        row.className = 'table-loading-row';
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = isError ? 'text-danger text-center p-4' : 'table-loading-row';
        cell.textContent = message;
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            let errorMessage = `Request failed with status ${response.status}`;
            try {
                const payload = await response.json();
                errorMessage = payload.error || payload.message || errorMessage;
            } catch (error) {
                // Ignore parsing issues and keep the generic message.
            }
            throw new Error(errorMessage);
        }

        return response.json();
    }

    function getQueryParams(includePagination) {
        const params = new URLSearchParams();
        const status = document.getElementById('filterStatus')?.value || '';
        const action = document.getElementById('filterAction')?.value || '';

        if (includePagination) {
            params.set('page', String(state.currentPage));
            params.set('page_size', String(state.pageSize));
        }

        if (status) {
            params.set('status', status);
        }
        if (action) {
            params.set('action', action);
        }

        return params;
    }

    async function lookupUserInfo(userId) {
        if (!userId) {
            return { display_name: 'Unknown User', email: '' };
        }

        if (state.userCache[userId]) {
            return state.userCache[userId];
        }

        try {
            const data = await fetchJson(`/api/user/info/${encodeURIComponent(userId)}`);
            const userInfo = {
                display_name: data.display_name || 'Unknown User',
                email: data.email || '',
            };
            state.userCache[userId] = userInfo;
            return userInfo;
        } catch (error) {
            const fallback = { display_name: 'Unknown User', email: '' };
            state.userCache[userId] = fallback;
            return fallback;
        }
    }

    function formatUserDisplay(userInfo, userId) {
        const displayName = userInfo?.display_name || userId || 'Unknown User';
        const email = userInfo?.email || '';
        return email ? `${displayName} (${email})` : displayName;
    }

    function formatCategories(logItem) {
        const categories = Array.isArray(logItem.triggered_categories) ? logItem.triggered_categories : [];
        return categories.map(function (entry) {
            const categoryName = entry.category || '';
            const severity = entry.severity;
            return severity == null ? categoryName : `${categoryName}(s=${severity})`;
        }).join(', ');
    }

    function formatActionLabel(action) {
        return ACTION_LABELS[action] || action || 'None';
    }

    function formatActionDisplay(logItem) {
        let actionLabel = formatActionLabel(logItem.action || 'None');
        const requestStatus = String(logItem.action_request_status || '').toLowerCase();
        if (requestStatus === 'pending') {
            actionLabel += ' (Pending approval)';
        } else if (requestStatus === 'failed') {
            actionLabel += ' (Execution failed)';
        }
        return actionLabel;
    }

    function toLocalDateTimeInputValue(isoValue) {
        if (!isoValue) {
            return '';
        }

        const parsedDate = new Date(isoValue);
        if (Number.isNaN(parsedDate.getTime())) {
            return '';
        }

        const localDate = new Date(parsedDate.getTime() - (parsedDate.getTimezoneOffset() * 60000));
        return localDate.toISOString().slice(0, 16);
    }

    function fromLocalDateTimeInputValue(localValue) {
        if (!localValue) {
            return null;
        }

        const parsedDate = new Date(localValue);
        return Number.isNaN(parsedDate.getTime()) ? null : parsedDate.toISOString();
    }

    function buildDefaultNotificationMessage(logItem, action) {
        const messageLines = [
            'A safety review has been completed for recent activity in your workspace.',
            `Violation ID: ${logItem.id || '-'}`,
        ];

        const categories = formatCategories(logItem);
        if (categories) {
            messageLines.push(`Triggered categories: ${categories}`);
        }

        if (action === 'WarnUser') {
            messageLines.push('Action taken: Warning issued. Please review the acceptable use requirements before continuing.');
        } else if (action === 'SuspendUser') {
            messageLines.push('Action taken: Your access has been temporarily suspended pending the restore date below.');
        } else if (action === 'BlockUser') {
            messageLines.push('Action taken: Your access has been blocked with no automatic restore date.');
        }

        if (logItem.notes) {
            messageLines.push(`Admin notes: ${logItem.notes}`);
        }

        return messageLines.join('\n');
    }

    function updateRemediationFields(logItem, forcePopulate) {
        const action = document.getElementById('editAction')?.value || 'None';
        const remediationFields = document.getElementById('safetyRemediationFields');
        const remediationHelp = document.getElementById('safetyRemediationHelp');
        const notificationMessage = document.getElementById('editNotificationMessage');
        const suspendGroup = document.getElementById('safetySuspendUntilGroup');
        const suspendInput = document.getElementById('editSuspendUntil');

        if (!remediationFields || !remediationHelp || !notificationMessage || !suspendGroup || !suspendInput) {
            return;
        }

        const shouldShow = SAFETY_REMEDIATION_ACTIONS.has(action);
        setElementHidden(remediationFields, !shouldShow);
        if (!shouldShow) {
            remediationHelp.textContent = '';
            notificationMessage.value = '';
            notificationMessage.dataset.generatedMessage = '';
            notificationMessage.dataset.action = action;
            suspendInput.value = '';
            setElementHidden(suspendGroup, true);
            return;
        }

        const helpTextMap = {
            WarnUser: 'Warn user sends a notification to the affected user. If this reviewer also has the required Control Center approval role, the warning is approved and sent immediately.',
            SuspendUser: 'Suspend user uses the Control Center access restriction workflow. Reviewers without approval authority create a pending request instead of applying the suspension immediately.',
            BlockUser: 'Block user applies a permanent access restriction through the same Control Center access workflow, with no automatic restore date.',
        };
        remediationHelp.textContent = helpTextMap[action] || '';

        const generatedMessage = buildDefaultNotificationMessage(logItem, action);
        const savedMessage = logItem.action === action ? logItem.action_notification_message : '';
        const currentGenerated = notificationMessage.dataset.generatedMessage || '';
        const currentAction = notificationMessage.dataset.action || '';
        const nextMessage = savedMessage || generatedMessage;
        if (forcePopulate || currentAction !== action || !notificationMessage.value.trim() || notificationMessage.value === currentGenerated) {
            notificationMessage.value = nextMessage;
        }
        notificationMessage.dataset.generatedMessage = nextMessage;
        notificationMessage.dataset.action = action;

        const showSuspendUntil = action === 'SuspendUser';
        setElementHidden(suspendGroup, !showSuspendUntil);
        if (showSuspendUntil) {
            const restoreDate = logItem.action === action ? logItem.action_datetime_to_allow : '';
            suspendInput.value = toLocalDateTimeInputValue(restoreDate);
        } else {
            suspendInput.value = '';
        }
    }

    function createTextCell(text, className, title) {
        const cell = document.createElement('td');
        if (className) {
            cell.className = className;
        }
        cell.textContent = text == null || text === '' ? '-' : String(text);
        if (title) {
            cell.title = title;
        }
        return cell;
    }

    function buildPagination(page, pageSize, totalCount) {
        const container = document.getElementById('pagination-container');
        if (!container) {
            return;
        }

        clearElement(container);
        const totalPages = Math.ceil(totalCount / pageSize);
        if (!totalPages || totalPages <= 1) {
            return;
        }

        const list = document.createElement('ul');
        list.className = 'pagination pagination-sm mb-0';

        function appendButton(label, nextPage, disabled, active) {
            const item = document.createElement('li');
            item.className = 'page-item';
            if (disabled) {
                item.classList.add('disabled');
            }
            if (active) {
                item.classList.add('active');
            }

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'page-link';
            button.textContent = label;
            if (!disabled && !active) {
                button.addEventListener('click', function () {
                    state.currentPage = nextPage;
                    loadSafetyLogs();
                });
            }

            item.appendChild(button);
            list.appendChild(item);
        }

        appendButton('«', page - 1, page <= 1, false);
        const windowStart = Math.max(1, page - 2);
        const windowEnd = Math.min(totalPages, windowStart + 4);
        for (let pageNumber = windowStart; pageNumber <= windowEnd; pageNumber += 1) {
            appendButton(String(pageNumber), pageNumber, false, pageNumber === page);
        }
        appendButton('»', page + 1, page >= totalPages, false);

        container.appendChild(list);
    }

    async function loadSafetyStats() {
        const params = getQueryParams(false);
        const data = await fetchJson(`/api/safety/logs/stats?${params.toString()}`);

        setTextContent('safetyTotalCount', data.total_count || 0);
        setTextContent('safetyOpenCount', (data.new_count || 0) + (data.in_review_count || 0));
        setTextContent('safetyResolvedCount', data.resolved_count || 0);
        setTextContent('safetyDismissedCount', data.dismissed_count || 0);
        setTextContent('safetyRecentCount', data.recent_30_day_count || 0);
        setTextContent('safetyEscalatedCount', (data.escalate_count || 0) + (data.block_user_count || 0));

        setTextContent('safetyStatsNewSummary', data.new_count || 0);
        setTextContent('safetyStatsInReviewSummary', data.in_review_count || 0);
        setTextContent('safetyStatsResolvedSummary', data.resolved_count || 0);
        setTextContent('safetyStatsDismissedSummary', data.dismissed_count || 0);
        setTextContent('safetyStatsNoneActionSummary', data.none_action_count || 0);
        setTextContent('safetyStatsWarnSummary', data.warn_user_count || 0);
        setTextContent('safetyStatsSuspendSummary', data.suspend_user_count || 0);
        setTextContent('safetyStatsEscalateSummary', (data.escalate_count || 0) + (data.block_user_count || 0));
    }

    async function renderSafetyRows(items) {
        const tbody = document.querySelector('#safetyLogsTable tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        if (!items.length) {
            renderTableMessage('No safety violations found for the current filters.', false);
            return;
        }

        for (const item of items) {
            const row = document.createElement('tr');
            const userInfo = await lookupUserInfo(item.user_id);
            const userDisplay = formatUserDisplay(userInfo, item.user_id);
            const categories = formatCategories(item);
            const actionDisplay = formatActionDisplay(item);

            row.appendChild(createTextCell(userDisplay, 'table-message-cell', userDisplay));
            row.appendChild(createTextCell(item.message || '', 'table-message-cell', item.message || ''));
            row.appendChild(createTextCell(categories || '', 'table-message-cell', categories || ''));
            row.appendChild(createTextCell(item.status || 'New'));
            row.appendChild(createTextCell(actionDisplay, 'table-message-cell', actionDisplay));
            row.appendChild(createTextCell(item.notes || '', 'table-message-cell', item.notes || ''));

            const editCell = document.createElement('td');
            editCell.className = 'table-details-cell';
            const editButton = document.createElement('button');
            editButton.type = 'button';
            editButton.className = 'btn btn-sm btn-primary';
            editButton.dataset.logId = item.id || '';
            editButton.textContent = 'Edit';
            editCell.appendChild(editButton);
            row.appendChild(editCell);

            tbody.appendChild(row);
        }
    }

    async function loadSafetyLogs() {
        renderTableMessage('Loading logs...', false);

        try {
            const params = getQueryParams(true);
            const data = await fetchJson(`/api/safety/logs?${params.toString()}`);
            state.items = Array.isArray(data.logs) ? data.logs : [];
            await renderSafetyRows(state.items);
            buildPagination(data.page || state.currentPage, data.page_size || state.pageSize, data.total_count || 0);
        } catch (error) {
            renderTableMessage(`Error loading logs: ${error.message}`, true);
        }
    }

    async function refreshSafetyView() {
        await loadSafetyStats();
        await loadSafetyLogs();
    }

    function getEditModalInstance() {
        if (!editModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('editModal');
            if (modalElement) {
                editModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return editModalInstance;
    }

    async function openEditModal(logId) {
        const item = state.items.find(function (entry) {
            return entry.id === logId;
        });
        if (!item) {
            return;
        }

        state.activeItem = item;

        const userInfo = await lookupUserInfo(item.user_id);
        setTextContent('editUserId', formatUserDisplay(userInfo, item.user_id));
        setTextContent('editMessage', item.message || '');
        setTextContent('editCategories', formatCategories(item) || '');
        document.getElementById('editStatus').value = item.status || 'New';
        document.getElementById('editAction').value = item.action || 'None';
        document.getElementById('editNotes').value = item.notes || '';
        document.getElementById('editLogId').value = item.id || '';
        setTextContent('safetyEditStatus', '');
        updateRemediationFields(item, true);

        const modalInstance = getEditModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }
    }

    async function saveSafetyChanges() {
        const logId = document.getElementById('editLogId')?.value || '';
        const statusElement = document.getElementById('safetyEditStatus');
        if (!logId) {
            return;
        }

        const action = document.getElementById('editAction')?.value || 'None';
        const payload = {
            status: document.getElementById('editStatus')?.value || 'New',
            action: action,
            notes: document.getElementById('editNotes')?.value || '',
        };

        if (SAFETY_REMEDIATION_ACTIONS.has(action)) {
            payload.notification_message = document.getElementById('editNotificationMessage')?.value || '';

            if (action === 'SuspendUser') {
                const suspendUntilValue = document.getElementById('editSuspendUntil')?.value || '';
                payload.datetime_to_allow = fromLocalDateTimeInputValue(suspendUntilValue);
                if (!payload.datetime_to_allow) {
                    throw new Error('Restore access date is required for a suspension.');
                }
            }
        }

        if (statusElement) {
            statusElement.textContent = 'Saving changes...';
            statusElement.className = 'small text-info me-auto';
        }

        const result = await fetchJson(`/api/safety/logs/${encodeURIComponent(logId)}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });

        if (statusElement) {
            statusElement.textContent = '';
            statusElement.className = 'small text-danger me-auto';
        }

        const modalInstance = getEditModalInstance();
        if (modalInstance) {
            modalInstance.hide();
        }

        showPageStatus(result.message || 'Safety log updated successfully.', result.approval_required ? 'info' : 'success');
        await refreshSafetyView();
    }

    function attachEventListeners() {
        const tableBody = document.querySelector('#safetyLogsTable tbody');
        const pageSizeSelect = document.getElementById('page-size-select');
        const applyFiltersButton = document.getElementById('applyFiltersBtn');
        const clearFiltersButton = document.getElementById('clearFiltersBtn');
        const exportButton = document.getElementById('safetyExportBtn');
        const saveButton = document.getElementById('saveChangesBtn');
        const actionSelect = document.getElementById('editAction');

        if (tableBody) {
            tableBody.addEventListener('click', function (event) {
                const actionButton = event.target.closest('button[data-log-id]');
                if (!actionButton) {
                    return;
                }

                openEditModal(actionButton.dataset.logId || '');
            });
        }

        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', function () {
                state.pageSize = parseInt(pageSizeSelect.value, 10) || 10;
                state.currentPage = 1;
                loadSafetyLogs();
            });
        }

        if (applyFiltersButton) {
            applyFiltersButton.addEventListener('click', function () {
                state.currentPage = 1;
                clearPageStatus();
                refreshSafetyView();
            });
        }

        if (clearFiltersButton) {
            clearFiltersButton.addEventListener('click', function () {
                const statusSelect = document.getElementById('filterStatus');
                const actionFilterSelect = document.getElementById('filterAction');
                if (statusSelect) {
                    statusSelect.value = '';
                }
                if (actionFilterSelect) {
                    actionFilterSelect.value = '';
                }
                state.currentPage = 1;
                clearPageStatus();
                refreshSafetyView();
            });
        }

        if (exportButton) {
            exportButton.addEventListener('click', function () {
                const params = getQueryParams(false);
                window.location.assign(`/api/safety/logs/export?${params.toString()}`);
            });
        }

        if (saveButton) {
            saveButton.addEventListener('click', function () {
                saveSafetyChanges().catch(function (error) {
                    const statusElement = document.getElementById('safetyEditStatus');
                    if (statusElement) {
                        statusElement.textContent = error.message;
                        statusElement.className = 'small text-danger me-auto';
                    }
                });
            });
        }

        if (actionSelect) {
            actionSelect.addEventListener('change', function () {
                if (!state.activeItem) {
                    return;
                }

                updateRemediationFields(state.activeItem, false);
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        attachEventListeners();
        clearPageStatus();
        refreshSafetyView().catch(function (error) {
            renderTableMessage(`Error loading logs: ${error.message}`, true);
        });
    });
})();