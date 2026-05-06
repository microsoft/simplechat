// profile-tabs.js

(function () {
    const pageConfig = window.profilePageConfig || {};
    const feedbackState = {
        currentPage: 1,
        pageSize: 10,
        items: [],
        hasLoaded: false,
    };
    const violationState = {
        currentPage: 1,
        pageSize: 10,
        items: [],
        hasLoaded: false,
    };

    let feedbackModalInstance = null;
    let violationModalInstance = null;

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

    function renderTableMessageRow(tbody, colSpan, message, isError) {
        clearElement(tbody);

        const row = document.createElement('tr');
        row.className = isError ? '' : 'table-loading-row';

        const cell = document.createElement('td');
        cell.colSpan = colSpan;
        cell.className = isError ? 'profile-empty-state text-danger' : 'table-loading-row';
        cell.textContent = message;

        row.appendChild(cell);
        tbody.appendChild(row);
    }

    function buildPagination(container, currentPage, pageSize, totalCount, onPageSelected) {
        clearElement(container);

        const totalPages = Math.ceil(totalCount / pageSize);
        if (!totalPages || totalPages <= 1) {
            return;
        }

        const list = document.createElement('ul');
        list.className = 'pagination pagination-sm mb-0';

        function appendPageButton(label, pageNumber, disabled, active) {
            const listItem = document.createElement('li');
            listItem.className = 'page-item';
            if (disabled) {
                listItem.classList.add('disabled');
            }
            if (active) {
                listItem.classList.add('active');
            }

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'page-link';
            button.textContent = label;
            if (!disabled && !active) {
                button.addEventListener('click', function () {
                    onPageSelected(pageNumber);
                });
            }

            listItem.appendChild(button);
            list.appendChild(listItem);
        }

        appendPageButton('«', currentPage - 1, currentPage <= 1, false);

        const windowStart = Math.max(1, currentPage - 2);
        const windowEnd = Math.min(totalPages, windowStart + 4);
        for (let pageNumber = windowStart; pageNumber <= windowEnd; pageNumber += 1) {
            appendPageButton(String(pageNumber), pageNumber, false, pageNumber === currentPage);
        }

        appendPageButton('»', currentPage + 1, currentPage >= totalPages, false);
        container.appendChild(list);
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            let errorMessage = `Request failed with status ${response.status}`;
            try {
                const payload = await response.json();
                errorMessage = payload.error || payload.message || errorMessage;
            } catch (error) {
                // Ignore JSON parsing issues and keep the generic message.
            }
            throw new Error(errorMessage);
        }

        return response.json();
    }

    function updateProfileTabQuery(tabName) {
        const url = new URL(window.location.href);
        url.searchParams.set('tab', tabName);
        window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);
    }

    function getFeedbackQueryParams(includePagination) {
        const params = new URLSearchParams();
        const feedbackType = document.getElementById('profile-feedback-filter-type')?.value || '';
        const acknowledged = document.getElementById('profile-feedback-filter-ack')?.value || '';

        if (includePagination) {
            params.set('page', String(feedbackState.currentPage));
            params.set('page_size', String(feedbackState.pageSize));
        }

        if (feedbackType) {
            params.set('type', feedbackType);
        }
        if (acknowledged) {
            params.set('ack', acknowledged);
        }

        return params;
    }

    function getViolationQueryParams(includePagination) {
        const params = new URLSearchParams();
        const status = document.getElementById('profile-violations-filter-status')?.value || '';
        const action = document.getElementById('profile-violations-filter-action')?.value || '';

        if (includePagination) {
            params.set('page', String(violationState.currentPage));
            params.set('page_size', String(violationState.pageSize));
        }

        if (status) {
            params.set('status', status);
        }
        if (action) {
            params.set('action', action);
        }

        return params;
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

    function getFeedbackModalInstance() {
        if (!feedbackModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('profileFeedbackDetailModal');
            if (modalElement) {
                feedbackModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return feedbackModalInstance;
    }

    function getViolationModalInstance() {
        if (!violationModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('profileViolationDetailModal');
            if (modalElement) {
                violationModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return violationModalInstance;
    }

    function renderFeedbackTableRows(items) {
        const tbody = document.querySelector('#profile-feedback-table tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        if (!items.length) {
            renderTableMessageRow(tbody, 8, 'No feedback found for the current filters.', false);
            return;
        }

        items.forEach(function (item) {
            const row = document.createElement('tr');
            const adminReview = item.adminReview || {};

            row.appendChild(createTextCell(formatDateTime(item.timestamp)));
            row.appendChild(createTextCell(item.prompt || '', 'table-message-cell', item.prompt || ''));
            row.appendChild(createTextCell(item.aiResponse || '', 'table-message-cell', item.aiResponse || ''));
            row.appendChild(createTextCell(item.feedbackType || ''));
            row.appendChild(createTextCell(item.reason || '', 'table-note-cell', item.reason || ''));
            row.appendChild(createTextCell(adminReview.acknowledged ? 'Yes' : 'No'));
            row.appendChild(createTextCell(adminReview.actionTaken || '', 'table-note-cell', adminReview.actionTaken || ''));

            const detailsCell = document.createElement('td');
            detailsCell.className = 'table-details-cell';
            const detailsButton = document.createElement('button');
            detailsButton.type = 'button';
            detailsButton.className = 'btn btn-sm btn-primary';
            detailsButton.dataset.feedbackId = item.id || '';
            detailsButton.textContent = 'View';
            detailsCell.appendChild(detailsButton);
            row.appendChild(detailsCell);

            tbody.appendChild(row);
        });
    }

    async function loadProfileFeedbackStats() {
        const params = getFeedbackQueryParams(false);
        const data = await fetchJson(`/feedback/my/stats?${params.toString()}`);
        setTextContent('profile-feedback-total-count', data.total_count || 0);
        setTextContent('profile-feedback-positive-count', data.positive_count || 0);
        setTextContent('profile-feedback-negative-count', data.negative_count || 0);
        setTextContent('profile-feedback-acknowledged-count', data.acknowledged_count || 0);
    }

    async function loadProfileFeedbackTable() {
        const tbody = document.querySelector('#profile-feedback-table tbody');
        const paginationContainer = document.getElementById('profile-feedback-pagination');
        if (!tbody || !paginationContainer) {
            return;
        }

        renderTableMessageRow(tbody, 8, 'Loading feedback...', false);
        clearElement(paginationContainer);

        try {
            const params = getFeedbackQueryParams(true);
            const data = await fetchJson(`/feedback/my?${params.toString()}`);
            feedbackState.items = Array.isArray(data.feedback) ? data.feedback : [];
            feedbackState.hasLoaded = true;
            renderFeedbackTableRows(feedbackState.items);
            buildPagination(
                paginationContainer,
                data.page || feedbackState.currentPage,
                data.page_size || feedbackState.pageSize,
                data.total_count || 0,
                function (pageNumber) {
                    feedbackState.currentPage = pageNumber;
                    loadProfileFeedbackTable();
                }
            );
        } catch (error) {
            renderTableMessageRow(tbody, 8, `Error loading feedback: ${error.message}`, true);
        }
    }

    async function refreshProfileFeedback() {
        await loadProfileFeedbackStats();
        await loadProfileFeedbackTable();
    }

    function openProfileFeedbackModal(feedbackId) {
        const selectedItem = feedbackState.items.find(function (item) {
            return item.id === feedbackId;
        });
        if (!selectedItem) {
            return;
        }

        const adminReview = selectedItem.adminReview || {};
        setTextContent('profile-feedback-detail-timestamp', formatDateTime(selectedItem.timestamp));
        setTextContent('profile-feedback-detail-prompt', selectedItem.prompt || '');
        setTextContent('profile-feedback-detail-response', selectedItem.aiResponse || '');
        setTextContent('profile-feedback-detail-type', selectedItem.feedbackType || '');
        setTextContent('profile-feedback-detail-reason', selectedItem.reason || '');
        setTextContent('profile-feedback-detail-acknowledged', adminReview.acknowledged ? 'Yes' : 'No');
        setTextContent('profile-feedback-detail-analysis', adminReview.analysisNotes || '');
        setTextContent('profile-feedback-detail-admin-response', adminReview.responseToUser || '');
        setTextContent('profile-feedback-detail-action', adminReview.actionTaken || '');

        const modalInstance = getFeedbackModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }
    }

    function renderViolationTableRows(items) {
        const tbody = document.querySelector('#profile-violations-table tbody');
        if (!tbody) {
            return;
        }

        clearElement(tbody);
        if (!items.length) {
            renderTableMessageRow(tbody, 7, 'No safety violations found for the current filters.', false);
            return;
        }

        items.forEach(function (logItem) {
            const row = document.createElement('tr');
            const categories = Array.isArray(logItem.triggered_categories)
                ? logItem.triggered_categories.map(function (entry) {
                    const categoryName = entry.category || '';
                    const severity = entry.severity;
                    return severity == null ? categoryName : `${categoryName}(s=${severity})`;
                }).join(', ')
                : '';

            row.appendChild(createTextCell(logItem.id || '', 'table-note-cell', logItem.id || ''));
            row.appendChild(createTextCell(logItem.message || '', 'table-message-cell', logItem.message || ''));
            row.appendChild(createTextCell(categories || '', 'table-note-cell', categories || ''));
            row.appendChild(createTextCell(logItem.status || 'New'));
            row.appendChild(createTextCell(logItem.action || 'None'));
            row.appendChild(createTextCell(logItem.user_notes || '', 'table-note-cell', logItem.user_notes || ''));

            const detailsCell = document.createElement('td');
            detailsCell.className = 'table-details-cell';
            const detailsButton = document.createElement('button');
            detailsButton.type = 'button';
            detailsButton.className = 'btn btn-sm btn-primary';
            detailsButton.dataset.logId = logItem.id || '';
            detailsButton.textContent = 'View/Edit';
            detailsCell.appendChild(detailsButton);
            row.appendChild(detailsCell);

            tbody.appendChild(row);
        });
    }

    async function loadProfileViolationStats() {
        const params = getViolationQueryParams(false);
        const data = await fetchJson(`/api/safety/logs/my/stats?${params.toString()}`);
        setTextContent('profile-violations-total-count', data.total_count || 0);
        setTextContent('profile-violations-open-count', (data.new_count || 0) + (data.in_review_count || 0));
        setTextContent('profile-violations-resolved-count', data.resolved_count || 0);
        setTextContent('profile-violations-recent-count', data.recent_30_day_count || 0);
    }

    async function loadProfileViolationTable() {
        const tbody = document.querySelector('#profile-violations-table tbody');
        const paginationContainer = document.getElementById('profile-violations-pagination');
        if (!tbody || !paginationContainer) {
            return;
        }

        renderTableMessageRow(tbody, 7, 'Loading violations...', false);
        clearElement(paginationContainer);

        try {
            const params = getViolationQueryParams(true);
            const data = await fetchJson(`/api/safety/logs/my?${params.toString()}`);
            violationState.items = Array.isArray(data.logs) ? data.logs : [];
            violationState.hasLoaded = true;
            renderViolationTableRows(violationState.items);
            buildPagination(
                paginationContainer,
                data.page || violationState.currentPage,
                data.page_size || violationState.pageSize,
                data.total_count || 0,
                function (pageNumber) {
                    violationState.currentPage = pageNumber;
                    loadProfileViolationTable();
                }
            );
        } catch (error) {
            renderTableMessageRow(tbody, 7, `Error loading violations: ${error.message}`, true);
        }
    }

    async function refreshProfileViolations() {
        await loadProfileViolationStats();
        await loadProfileViolationTable();
    }

    function openProfileViolationModal(logId) {
        const selectedItem = violationState.items.find(function (item) {
            return item.id === logId;
        });
        if (!selectedItem) {
            return;
        }

        const categories = Array.isArray(selectedItem.triggered_categories)
            ? selectedItem.triggered_categories.map(function (entry) {
                const categoryName = entry.category || '';
                const severity = entry.severity;
                return severity == null ? categoryName : `${categoryName}(s=${severity})`;
            }).join(', ')
            : '';

        setTextContent('profile-violation-detail-id', selectedItem.id || '');
        setTextContent('profile-violation-detail-message', selectedItem.message || '');
        setTextContent('profile-violation-detail-categories', categories || '');
        setTextContent('profile-violation-detail-status', selectedItem.status || 'New');
        setTextContent('profile-violation-detail-action', selectedItem.action || 'None');
        document.getElementById('profile-violation-detail-hidden-id').value = selectedItem.id || '';
        document.getElementById('profile-violation-detail-user-notes').value = selectedItem.user_notes || '';
        setTextContent('profile-violation-save-status', '');

        const modalInstance = getViolationModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }
    }

    async function saveProfileViolationNotes() {
        const logId = document.getElementById('profile-violation-detail-hidden-id')?.value || '';
        const notesValue = document.getElementById('profile-violation-detail-user-notes')?.value || '';
        const statusElement = document.getElementById('profile-violation-save-status');
        if (!logId) {
            return;
        }

        if (statusElement) {
            statusElement.textContent = 'Saving your notes...';
            statusElement.className = 'small text-info mt-2';
        }

        try {
            await fetchJson(`/api/safety/logs/my/${encodeURIComponent(logId)}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_notes: notesValue,
                }),
            });

            const selectedItem = violationState.items.find(function (item) {
                return item.id === logId;
            });
            if (selectedItem) {
                selectedItem.user_notes = notesValue;
            }

            if (statusElement) {
                statusElement.textContent = 'Notes saved.';
                statusElement.className = 'small text-success mt-2';
            }

            renderViolationTableRows(violationState.items);
        } catch (error) {
            if (statusElement) {
                statusElement.textContent = error.message;
                statusElement.className = 'small text-danger mt-2';
            }
        }
    }

    function attachProfileTabListeners() {
        const tabButtons = document.querySelectorAll('#profileTabs [data-profile-tab]');
        tabButtons.forEach(function (tabButton) {
            tabButton.addEventListener('shown.bs.tab', function () {
                const tabName = tabButton.dataset.profileTab || 'stats';
                updateProfileTabQuery(tabName);

                if (tabName === 'feedback' && pageConfig.feedbackEnabled && !feedbackState.hasLoaded) {
                    refreshProfileFeedback();
                }
                if (tabName === 'violations' && pageConfig.contentSafetyEnabled && !violationState.hasLoaded) {
                    refreshProfileViolations();
                }
            });
        });
    }

    function attachFeedbackListeners() {
        const tableBody = document.querySelector('#profile-feedback-table tbody');
        const pageSizeSelect = document.getElementById('profile-feedback-page-size');
        const applyFiltersButton = document.getElementById('profile-feedback-apply-filters-btn');
        const clearFiltersButton = document.getElementById('profile-feedback-clear-filters-btn');
        const exportButton = document.getElementById('profile-feedback-export-btn');

        if (tableBody) {
            tableBody.addEventListener('click', function (event) {
                const target = event.target.closest('button[data-feedback-id]');
                if (!target) {
                    return;
                }

                openProfileFeedbackModal(target.dataset.feedbackId || '');
            });
        }

        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', function () {
                feedbackState.pageSize = parseInt(pageSizeSelect.value, 10) || 10;
                feedbackState.currentPage = 1;
                refreshProfileFeedback();
            });
        }

        if (applyFiltersButton) {
            applyFiltersButton.addEventListener('click', function () {
                feedbackState.currentPage = 1;
                refreshProfileFeedback();
            });
        }

        if (clearFiltersButton) {
            clearFiltersButton.addEventListener('click', function () {
                const typeSelect = document.getElementById('profile-feedback-filter-type');
                const acknowledgedSelect = document.getElementById('profile-feedback-filter-ack');
                if (typeSelect) {
                    typeSelect.value = '';
                }
                if (acknowledgedSelect) {
                    acknowledgedSelect.value = '';
                }
                feedbackState.currentPage = 1;
                refreshProfileFeedback();
            });
        }

        if (exportButton) {
            exportButton.addEventListener('click', function () {
                const params = getFeedbackQueryParams(false);
                const exportUrl = `/feedback/my/export?${params.toString()}`;
                window.location.assign(exportUrl);
            });
        }
    }

    function attachViolationListeners() {
        const tableBody = document.querySelector('#profile-violations-table tbody');
        const pageSizeSelect = document.getElementById('profile-violations-page-size');
        const applyFiltersButton = document.getElementById('profile-violations-apply-filters-btn');
        const clearFiltersButton = document.getElementById('profile-violations-clear-filters-btn');
        const exportButton = document.getElementById('profile-violations-export-btn');
        const saveButton = document.getElementById('profile-violation-save-btn');

        if (tableBody) {
            tableBody.addEventListener('click', function (event) {
                const target = event.target.closest('button[data-log-id]');
                if (!target) {
                    return;
                }

                openProfileViolationModal(target.dataset.logId || '');
            });
        }

        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', function () {
                violationState.pageSize = parseInt(pageSizeSelect.value, 10) || 10;
                violationState.currentPage = 1;
                refreshProfileViolations();
            });
        }

        if (applyFiltersButton) {
            applyFiltersButton.addEventListener('click', function () {
                violationState.currentPage = 1;
                refreshProfileViolations();
            });
        }

        if (clearFiltersButton) {
            clearFiltersButton.addEventListener('click', function () {
                const statusSelect = document.getElementById('profile-violations-filter-status');
                const actionSelect = document.getElementById('profile-violations-filter-action');
                if (statusSelect) {
                    statusSelect.value = '';
                }
                if (actionSelect) {
                    actionSelect.value = '';
                }
                violationState.currentPage = 1;
                refreshProfileViolations();
            });
        }

        if (exportButton) {
            exportButton.addEventListener('click', function () {
                const params = getViolationQueryParams(false);
                const exportUrl = `/api/safety/logs/my/export?${params.toString()}`;
                window.location.assign(exportUrl);
            });
        }

        if (saveButton) {
            saveButton.addEventListener('click', function () {
                saveProfileViolationNotes();
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        attachProfileTabListeners();

        if (pageConfig.feedbackEnabled) {
            attachFeedbackListeners();
            if (pageConfig.initialTab === 'feedback') {
                refreshProfileFeedback();
            }
        }

        if (pageConfig.contentSafetyEnabled) {
            attachViolationListeners();
            if (pageConfig.initialTab === 'violations') {
                refreshProfileViolations();
            }
        }
    });
})();