// admin-safety-violations.js

(function () {
    const state = {
        currentPage: 1,
        pageSize: 10,
        items: [],
        userCache: {},
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

            row.appendChild(createTextCell(userDisplay, 'table-message-cell', userDisplay));
            row.appendChild(createTextCell(item.message || '', 'table-message-cell', item.message || ''));
            row.appendChild(createTextCell(categories || '', 'table-message-cell', categories || ''));
            row.appendChild(createTextCell(item.status || 'New'));
            row.appendChild(createTextCell(item.action || 'None'));
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

        const userInfo = await lookupUserInfo(item.user_id);
        setTextContent('editUserId', formatUserDisplay(userInfo, item.user_id));
        setTextContent('editMessage', item.message || '');
        setTextContent('editCategories', formatCategories(item) || '');
        document.getElementById('editStatus').value = item.status || 'New';
        document.getElementById('editAction').value = item.action || 'None';
        document.getElementById('editNotes').value = item.notes || '';
        document.getElementById('editLogId').value = item.id || '';
        setTextContent('safetyEditStatus', '');

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

        if (statusElement) {
            statusElement.textContent = 'Saving changes...';
            statusElement.className = 'small text-info me-auto';
        }

        await fetchJson(`/api/safety/logs/${encodeURIComponent(logId)}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                status: document.getElementById('editStatus')?.value || 'New',
                action: document.getElementById('editAction')?.value || 'None',
                notes: document.getElementById('editNotes')?.value || '',
            }),
        });

        if (statusElement) {
            statusElement.textContent = '';
            statusElement.className = 'small text-danger me-auto';
        }

        const modalInstance = getEditModalInstance();
        if (modalInstance) {
            modalInstance.hide();
        }

        await refreshSafetyView();
    }

    function attachEventListeners() {
        const tableBody = document.querySelector('#safetyLogsTable tbody');
        const pageSizeSelect = document.getElementById('page-size-select');
        const applyFiltersButton = document.getElementById('applyFiltersBtn');
        const clearFiltersButton = document.getElementById('clearFiltersBtn');
        const exportButton = document.getElementById('safetyExportBtn');
        const saveButton = document.getElementById('saveChangesBtn');

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
                refreshSafetyView();
            });
        }

        if (clearFiltersButton) {
            clearFiltersButton.addEventListener('click', function () {
                const statusSelect = document.getElementById('filterStatus');
                const actionSelect = document.getElementById('filterAction');
                if (statusSelect) {
                    statusSelect.value = '';
                }
                if (actionSelect) {
                    actionSelect.value = '';
                }
                state.currentPage = 1;
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
    }

    document.addEventListener('DOMContentLoaded', function () {
        attachEventListeners();
        refreshSafetyView().catch(function (error) {
            renderTableMessage(`Error loading logs: ${error.message}`, true);
        });
    });
})();