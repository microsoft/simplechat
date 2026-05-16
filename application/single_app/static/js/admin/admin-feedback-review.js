// admin-feedback-review.js

(function () {
    const state = {
        currentPage: 1,
        pageSize: 10,
        viewMode: 'list',
        items: [],
        userCache: {},
    };

    const FEEDBACK_VIEW_STORAGE_KEY = 'simplechat.admin.feedback.viewMode';

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
        cell.colSpan = 5;
        cell.className = isError ? 'text-danger text-center p-4' : 'table-loading-row';
        cell.textContent = message;
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    function renderCardMessage(message, isError) {
        const cardView = document.getElementById('feedback-card-view');
        if (!cardView) {
            return;
        }

        clearElement(cardView);
        const column = document.createElement('div');
        column.className = 'col-12';
        const messageElement = document.createElement('div');
        messageElement.className = isError ? 'review-empty-state text-danger' : 'review-empty-state';
        messageElement.textContent = message;
        column.appendChild(messageElement);
        cardView.appendChild(column);
    }

    function renderFeedbackMessage(message, isError) {
        renderTableMessage(message, isError);
        renderCardMessage(message, isError);
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

    function createIcon(iconClass) {
        const icon = document.createElement('i');
        icon.className = iconClass;
        icon.setAttribute('aria-hidden', 'true');
        return icon;
    }

    function createBadge(label, variant, title) {
        const badge = document.createElement('span');
        badge.className = `badge rounded-pill text-bg-${variant || 'secondary'}`;
        badge.textContent = label == null || label === '' ? '-' : String(label);
        if (title) {
            badge.title = title;
        }
        return badge;
    }

    function getFeedbackVariant(feedbackType) {
        if (feedbackType === 'Positive') {
            return 'success';
        }
        if (feedbackType === 'Negative') {
            return 'danger';
        }
        if (feedbackType === 'Neutral') {
            return 'info';
        }
        return 'secondary';
    }

    function createFeedbackBadge(feedbackType) {
        const label = feedbackType || 'Unknown';
        return createBadge(label, getFeedbackVariant(feedbackType));
    }

    function createAcknowledgedBadge(acknowledged) {
        return createBadge(acknowledged ? 'Acknowledged' : 'Not acknowledged', acknowledged ? 'primary' : 'warning');
    }

    function createBadgeCell(badge) {
        const cell = document.createElement('td');
        const wrapper = document.createElement('div');
        wrapper.className = 'review-badge-list';
        wrapper.appendChild(badge);
        cell.appendChild(wrapper);
        return cell;
    }

    function createViewButton(feedbackId) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-primary';
        button.dataset.feedbackId = feedbackId || '';
        button.dataset.action = 'view';
        button.appendChild(createIcon('bi bi-eye me-1'));
        button.appendChild(document.createTextNode('View'));
        return button;
    }

    function appendCardDetail(parent, label, value) {
        if (value == null || value === '') {
            return;
        }

        const detail = document.createElement('div');
        detail.className = 'small';
        const labelElement = document.createElement('span');
        labelElement.className = 'fw-semibold text-muted';
        labelElement.textContent = `${label}: `;
        const valueElement = document.createElement('span');
        valueElement.textContent = String(value);
        detail.appendChild(labelElement);
        detail.appendChild(valueElement);
        parent.appendChild(detail);
    }

    function getInitialViewMode() {
        try {
            const savedViewMode = window.localStorage.getItem(FEEDBACK_VIEW_STORAGE_KEY);
            if (savedViewMode === 'cards' || savedViewMode === 'list') {
                return savedViewMode;
            }
        } catch (error) {
            // Ignore storage access errors and fall back to viewport defaults.
        }

        if (window.matchMedia && window.matchMedia('(max-width: 991.98px)').matches) {
            return 'cards';
        }
        return 'list';
    }

    function setFeedbackViewMode(viewMode, persist) {
        const normalizedViewMode = viewMode === 'cards' ? 'cards' : 'list';
        state.viewMode = normalizedViewMode;

        const listView = document.getElementById('feedback-list-view');
        const cardView = document.getElementById('feedback-card-view');
        const listRadio = document.getElementById('feedback-view-list');
        const cardsRadio = document.getElementById('feedback-view-cards');

        if (listView) {
            listView.classList.toggle('d-none', normalizedViewMode !== 'list');
        }
        if (cardView) {
            cardView.classList.toggle('d-none', normalizedViewMode !== 'cards');
        }
        if (listRadio) {
            listRadio.checked = normalizedViewMode === 'list';
        }
        if (cardsRadio) {
            cardsRadio.checked = normalizedViewMode === 'cards';
        }

        if (persist) {
            try {
                window.localStorage.setItem(FEEDBACK_VIEW_STORAGE_KEY, normalizedViewMode);
            } catch (error) {
                // Ignore storage access errors; the current view has already been applied.
            }
        }
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
            const adminReview = item.adminReview || {};
            const timestamp = formatDateTime(item.timestamp);

            row.appendChild(createTextCell(timestamp, 'table-message-cell', timestamp));
            row.appendChild(createTextCell(item.prompt || '', 'table-message-cell', item.prompt || ''));
            row.appendChild(createBadgeCell(createFeedbackBadge(item.feedbackType)));
            row.appendChild(createBadgeCell(createAcknowledgedBadge(Boolean(adminReview.acknowledged))));

            const viewCell = document.createElement('td');
            viewCell.className = 'table-details-cell';
            viewCell.appendChild(createViewButton(item.id));
            row.appendChild(viewCell);

            tbody.appendChild(row);
        }
    }

    function renderFeedbackCards(items) {
        const cardView = document.getElementById('feedback-card-view');
        if (!cardView) {
            return;
        }

        clearElement(cardView);
        if (!items.length) {
            renderCardMessage('No feedback found for the current filters.', false);
            return;
        }

        items.forEach(function (item) {
            const adminReview = item.adminReview || {};
            const column = document.createElement('div');
            column.className = 'col-12 col-xl-6 col-xxl-4';

            const card = document.createElement('article');
            card.className = 'review-card';

            const header = document.createElement('div');
            header.className = 'review-card-header';
            const timestamp = document.createElement('div');
            timestamp.className = 'review-card-meta';
            timestamp.textContent = formatDateTime(item.timestamp);
            const badges = document.createElement('div');
            badges.className = 'review-badge-list';
            badges.appendChild(createFeedbackBadge(item.feedbackType));
            badges.appendChild(createAcknowledgedBadge(Boolean(adminReview.acknowledged)));
            header.appendChild(timestamp);
            header.appendChild(badges);

            const prompt = document.createElement('p');
            prompt.className = 'review-card-title';
            prompt.textContent = item.prompt || 'No prompt captured.';

            const details = document.createElement('div');
            details.className = 'd-grid gap-1';
            appendCardDetail(details, 'Reason', item.reason || '');
            appendCardDetail(details, 'Action', adminReview.actionTaken || '');

            const footer = document.createElement('div');
            footer.className = 'review-card-footer';
            const footerMeta = document.createElement('div');
            footerMeta.className = 'review-card-meta';
            footerMeta.textContent = adminReview.reviewTimestamp ? `Reviewed ${formatDateTime(adminReview.reviewTimestamp)}` : 'Waiting for review';
            footer.appendChild(footerMeta);
            footer.appendChild(createViewButton(item.id));

            card.appendChild(header);
            card.appendChild(prompt);
            if (details.childElementCount) {
                card.appendChild(details);
            }
            card.appendChild(footer);
            column.appendChild(card);
            cardView.appendChild(column);
        });
    }

    async function renderFeedbackItems(items) {
        await renderFeedbackRows(items);
        renderFeedbackCards(items);
    }

    async function loadFeedbackData() {
        renderFeedbackMessage('Loading feedback...', false);

        try {
            const params = getQueryParams(true);
            const data = await fetchJson(`/feedback/review?${params.toString()}`);
            state.items = Array.isArray(data.feedback) ? data.feedback : [];
            await renderFeedbackItems(state.items);
            buildPagination(data.page || state.currentPage, data.page_size || state.pageSize, data.total_count || 0);
        } catch (error) {
            renderFeedbackMessage(`Error loading feedback: ${error.message}`, true);
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
            statusElement.textContent = 'Saving review...';
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

    function handleFeedbackActionClick(event) {
        const actionButton = event.target.closest('button[data-feedback-id]');
        if (!actionButton) {
            return;
        }

        const feedbackId = actionButton.dataset.feedbackId || '';
        const action = actionButton.dataset.action || 'view';
        if (action === 'retest') {
            openRetestModal(feedbackId);
        } else {
            openEditModal(feedbackId);
        }
    }

    function attachEventListeners() {
        const tableBody = document.querySelector('#feedback-table tbody');
        const cardView = document.getElementById('feedback-card-view');
        const pageSizeSelect = document.getElementById('page-size-select');
        const applyFiltersButton = document.getElementById('applyFiltersBtn');
        const clearFiltersButton = document.getElementById('clearFiltersBtn');
        const exportButton = document.getElementById('feedbackExportBtn');
        const saveButton = document.getElementById('saveFeedbackChangesBtn');
        const retestButton = document.getElementById('retestFeedbackBtn');
        const listViewRadio = document.getElementById('feedback-view-list');
        const cardsViewRadio = document.getElementById('feedback-view-cards');

        if (tableBody) {
            tableBody.addEventListener('click', handleFeedbackActionClick);
        }

        if (cardView) {
            cardView.addEventListener('click', handleFeedbackActionClick);
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

        if (retestButton) {
            retestButton.addEventListener('click', function () {
                const feedbackId = document.getElementById('editFeedbackId')?.value || '';
                openRetestModal(feedbackId);
            });
        }

        if (listViewRadio) {
            listViewRadio.addEventListener('change', function () {
                if (listViewRadio.checked) {
                    setFeedbackViewMode('list', true);
                }
            });
        }

        if (cardsViewRadio) {
            cardsViewRadio.addEventListener('change', function () {
                if (cardsViewRadio.checked) {
                    setFeedbackViewMode('cards', true);
                }
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        setFeedbackViewMode(getInitialViewMode(), false);
        attachEventListeners();
        refreshFeedbackView().catch(function (error) {
            renderFeedbackMessage(`Error loading feedback: ${error.message}`, true);
        });
    });
})();