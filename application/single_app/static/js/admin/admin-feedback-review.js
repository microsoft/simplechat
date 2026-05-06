// admin-feedback-review.js

(function () {
    const state = {
        currentPage: 1,
        pageSize: 10,
        items: [],
        userCache: {},
    };

    let editModalInstance = null;
    let retestModalInstance = null;

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

    function formatDateTime(value) {
        if (!value) {
            return 'N/A';
        }

        const parsedDate = new Date(value);
        if (Number.isNaN(parsedDate.getTime())) {
            return String(value);
        }

        return parsedDate.toLocaleString();
    }

    function renderTableMessage(message, isError) {
        const tbody = document.querySelector('#feedback-table tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        const row = document.createElement('tr');
        row.className = 'table-loading-row';
        const cell = document.createElement('td');
        cell.colSpan = 9;
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
                // Ignore invalid JSON and keep the generic message.
            }
            throw new Error(errorMessage);
        }

        return response.json();
    }

    function getQueryParams(includePagination) {
        const params = new URLSearchParams();
        const type = document.getElementById('filterFeedbackType')?.value || '';
        const acknowledged = document.getElementById('filterAcknowledged')?.value || '';

        if (includePagination) {
            params.set('page', String(state.currentPage));
            params.set('page_size', String(state.pageSize));
        }

        if (type) {
            params.set('type', type);
        }
        if (acknowledged) {
            params.set('ack', acknowledged);
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
                    loadFeedbackData();
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

    async function loadFeedbackStats() {
        const params = getQueryParams(false);
        const data = await fetchJson(`/feedback/review/stats?${params.toString()}`);

        setTextContent('feedbackTotalCount', data.total_count || 0);
        setTextContent('feedbackPositiveCount', data.positive_count || 0);
        setTextContent('feedbackNegativeCount', data.negative_count || 0);
        setTextContent('feedbackNeutralCount', data.neutral_count || 0);
        setTextContent('feedbackAcknowledgedCount', data.acknowledged_count || 0);
        setTextContent('feedbackRecentCount', data.recent_30_day_count || 0);

        setTextContent('feedbackStatsPositiveSummary', data.positive_count || 0);
        setTextContent('feedbackStatsNegativeSummary', data.negative_count || 0);
        setTextContent('feedbackStatsNeutralSummary', data.neutral_count || 0);
        setTextContent('feedbackStatsAcknowledgedSummary', data.acknowledged_count || 0);
        setTextContent('feedbackStatsUnacknowledgedSummary', data.unacknowledged_count || 0);
        setTextContent('feedbackStatsLatestTimestamp', formatDateTime(data.latest_timestamp));
    }

    async function renderFeedbackRows(items) {
        const tbody = document.querySelector('#feedback-table tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        if (!items.length) {
            renderTableMessage('No feedback found for the current filters.', false);
            return;
        }

        for (const item of items) {
            const row = document.createElement('tr');
            const userInfo = await lookupUserInfo(item.userId);
            const userDisplay = formatUserDisplay(userInfo, item.userId);
            const adminReview = item.adminReview || {};

            row.appendChild(createTextCell(userDisplay, 'table-message-cell', userDisplay));
            row.appendChild(createTextCell(item.prompt || '', 'table-message-cell', item.prompt || ''));
            row.appendChild(createTextCell(item.aiResponse || '', 'table-message-cell', item.aiResponse || ''));
            row.appendChild(createTextCell(item.feedbackType || ''));
            row.appendChild(createTextCell(item.reason || '', 'table-message-cell', item.reason || ''));
            row.appendChild(createTextCell(adminReview.acknowledged ? 'Yes' : 'No'));
            row.appendChild(createTextCell(adminReview.actionTaken || '', 'table-message-cell', adminReview.actionTaken || ''));

            const editCell = document.createElement('td');
            editCell.className = 'table-details-cell';
            const editButton = document.createElement('button');
            editButton.type = 'button';
            editButton.className = 'btn btn-sm btn-primary';
            editButton.dataset.feedbackId = item.id || '';
            editButton.dataset.action = 'edit';
            editButton.textContent = 'Edit';
            editCell.appendChild(editButton);
            row.appendChild(editCell);

            const retestCell = document.createElement('td');
            retestCell.className = 'table-details-cell';
            const retestButton = document.createElement('button');
            retestButton.type = 'button';
            retestButton.className = 'btn btn-sm btn-outline-secondary';
            retestButton.dataset.feedbackId = item.id || '';
            retestButton.dataset.action = 'retest';
            retestButton.textContent = 'Retest';
            retestCell.appendChild(retestButton);
            row.appendChild(retestCell);

            tbody.appendChild(row);
        }
    }

    async function loadFeedbackData() {
        renderTableMessage('Loading feedback...', false);

        try {
            const params = getQueryParams(true);
            const data = await fetchJson(`/feedback/review?${params.toString()}`);
            state.items = Array.isArray(data.feedback) ? data.feedback : [];
            await renderFeedbackRows(state.items);
            buildPagination(data.page || state.currentPage, data.page_size || state.pageSize, data.total_count || 0);
        } catch (error) {
            renderTableMessage(`Error loading feedback: ${error.message}`, true);
        }
    }

    async function refreshFeedbackView() {
        await loadFeedbackStats();
        await loadFeedbackData();
    }

    function getEditModalInstance() {
        if (!editModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('editFeedbackModal');
            if (modalElement) {
                editModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return editModalInstance;
    }

    function getRetestModalInstance() {
        if (!retestModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('retestModal');
            if (modalElement) {
                retestModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return retestModalInstance;
    }

    async function openEditModal(feedbackId) {
        const item = state.items.find(function (entry) {
            return entry.id === feedbackId;
        });
        if (!item) {
            return;
        }

        const userInfo = await lookupUserInfo(item.userId);
        const adminReview = item.adminReview || {};

        setTextContent('editTimestamp', formatDateTime(item.timestamp));
        setTextContent('editUserInfo', formatUserDisplay(userInfo, item.userId));
        setTextContent('editPrompt', item.prompt || '');
        setTextContent('editAiResponse', item.aiResponse || '');
        setTextContent('editFeedbackType', item.feedbackType || '');
        setTextContent('editReason', item.reason || '');
        document.getElementById('editAcknowledged').checked = Boolean(adminReview.acknowledged);
        document.getElementById('editAnalysisNotes').value = adminReview.analysisNotes || '';
        document.getElementById('editResponseToUser').value = adminReview.responseToUser || '';
        document.getElementById('editActionTaken').value = adminReview.actionTaken || '';
        document.getElementById('editFeedbackId').value = item.id || '';
        setTextContent('feedbackEditStatus', '');

        const modalInstance = getEditModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }
    }

    async function openRetestModal(feedbackId) {
        const item = state.items.find(function (entry) {
            return entry.id === feedbackId;
        });
        if (!item) {
            return;
        }

        const modalBody = document.getElementById('retest-body');
        if (modalBody) {
            modalBody.textContent = 'Retesting...';
        }

        const modalInstance = getRetestModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }

        try {
            const data = await fetchJson(`/feedback/retest/${encodeURIComponent(feedbackId)}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    prompt: item.prompt || '',
                }),
            });

            if (modalBody) {
                modalBody.textContent = data.retestResponse || 'No retest response was returned.';
            }
        } catch (error) {
            if (modalBody) {
                modalBody.textContent = error.message;
            }
        }
    }

    async function saveFeedbackChanges() {
        const feedbackId = document.getElementById('editFeedbackId')?.value || '';
        const statusElement = document.getElementById('feedbackEditStatus');
        if (!feedbackId) {
            return;
        }

        if (statusElement) {
            statusElement.textContent = 'Saving changes...';
            statusElement.className = 'small text-info me-auto';
        }

        await fetchJson(`/feedback/review/${encodeURIComponent(feedbackId)}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                acknowledged: document.getElementById('editAcknowledged')?.checked || false,
                analysisNotes: document.getElementById('editAnalysisNotes')?.value || '',
                responseToUser: document.getElementById('editResponseToUser')?.value || '',
                actionTaken: document.getElementById('editActionTaken')?.value || '',
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

        await refreshFeedbackView();
    }

    function attachEventListeners() {
        const tableBody = document.querySelector('#feedback-table tbody');
        const pageSizeSelect = document.getElementById('page-size-select');
        const applyFiltersButton = document.getElementById('applyFiltersBtn');
        const clearFiltersButton = document.getElementById('clearFiltersBtn');
        const exportButton = document.getElementById('feedbackExportBtn');
        const saveButton = document.getElementById('saveFeedbackChangesBtn');

        if (tableBody) {
            tableBody.addEventListener('click', function (event) {
                const actionButton = event.target.closest('button[data-feedback-id]');
                if (!actionButton) {
                    return;
                }

                const feedbackId = actionButton.dataset.feedbackId || '';
                const action = actionButton.dataset.action || '';
                if (action === 'edit') {
                    openEditModal(feedbackId);
                } else if (action === 'retest') {
                    openRetestModal(feedbackId);
                }
            });
        }

        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', function () {
                state.pageSize = parseInt(pageSizeSelect.value, 10) || 10;
                state.currentPage = 1;
                loadFeedbackData();
            });
        }

        if (applyFiltersButton) {
            applyFiltersButton.addEventListener('click', function () {
                state.currentPage = 1;
                refreshFeedbackView();
            });
        }

        if (clearFiltersButton) {
            clearFiltersButton.addEventListener('click', function () {
                const typeSelect = document.getElementById('filterFeedbackType');
                const acknowledgedSelect = document.getElementById('filterAcknowledged');
                if (typeSelect) {
                    typeSelect.value = '';
                }
                if (acknowledgedSelect) {
                    acknowledgedSelect.value = '';
                }
                state.currentPage = 1;
                refreshFeedbackView();
            });
        }

        if (exportButton) {
            exportButton.addEventListener('click', function () {
                const params = getQueryParams(false);
                window.location.assign(`/feedback/review/export?${params.toString()}`);
            });
        }

        if (saveButton) {
            saveButton.addEventListener('click', function () {
                saveFeedbackChanges().catch(function (error) {
                    const statusElement = document.getElementById('feedbackEditStatus');
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
        refreshFeedbackView().catch(function (error) {
            renderTableMessage(`Error loading feedback: ${error.message}`, true);
        });
    });
})();