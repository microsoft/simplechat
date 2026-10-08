// admin-safety-violations.js

(function () {
    const state = {
        currentPage: 1,
        pageSize: 10,
        viewMode: 'list',
        items: [],
        userCache: {},
        activeItem: null,
    };

    const SAFETY_VIEW_STORAGE_KEY = 'simplechat.admin.safetyViolations.viewMode';

    const SAFETY_REMEDIATION_ACTIONS = new Set(['WarnUser', 'SuspendUser', 'BlockUser']);
    // Escalate is no longer an action. A record that already carries it keeps it, labelled
    // as legacy, and only that record's editor offers it again.
    const LEGACY_ESCALATE_ACTION = 'Escalate';
    // Every value the action select can hold. The select is read through this list, so only
    // these constant strings, never text taken from the page, reach data attributes or a save.
    const ACTION_VALUES = ['None', 'WarnUser', 'SuspendUser', 'BlockUser', LEGACY_ESCALATE_ACTION];
    const ACTION_LABELS = {
        None: 'None',
        WarnUser: 'Warn user',
        SuspendUser: 'Suspend user',
        Escalate: 'Escalated (legacy)',
        BlockUser: 'Block user',
    };

    let editModalInstance = null;
    let deleteModalInstance = null;

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
        cell.colSpan = 5;
        cell.className = isError ? 'text-danger text-center p-4' : 'table-loading-row';
        cell.textContent = message;
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    function renderCardMessage(message, isError) {
        const cardView = document.getElementById('safety-card-view');
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

    function renderSafetyMessage(message, isError) {
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
        const archiveState = document.getElementById('filterSafetyArchive')?.value || 'active';

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
        params.set('archive', archiveState);

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

    function normalizeSeverity(severity) {
        const parsedSeverity = Number(severity);
        return Number.isFinite(parsedSeverity) ? parsedSeverity : null;
    }

    function getTriggeredCategoryEntries(logItem) {
        const categories = Array.isArray(logItem.triggered_categories) ? logItem.triggered_categories : [];
        return categories.reduce(function (entries, entry) {
            const categoryName = String(entry.category || '').trim();
            const severity = normalizeSeverity(entry.severity);
            if (categoryName && severity >= 1 && severity <= 4) {
                entries.push({ category: categoryName, severity });
            }
            return entries;
        }, []);
    }

    function formatCategories(logItem) {
        return getTriggeredCategoryEntries(logItem).map(function (entry) {
            return `${entry.category}(s=${entry.severity})`;
        }).join(', ');
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

    function getCategoryVariant(severity) {
        if (severity >= 4) {
            return 'danger';
        }
        if (severity === 3) {
            return 'warning';
        }
        if (severity === 2) {
            return 'info';
        }
        return 'secondary';
    }

    function appendCategoryBadges(container, logItem, emptyText) {
        if (!container) {
            return;
        }

        clearElement(container);
        const entries = getTriggeredCategoryEntries(logItem);
        if (!entries.length) {
            const emptyElement = document.createElement('span');
            emptyElement.className = 'text-muted small';
            emptyElement.textContent = emptyText || '-';
            container.appendChild(emptyElement);
            return;
        }

        entries.forEach(function (entry) {
            container.appendChild(createBadge(entry.category, getCategoryVariant(entry.severity), `Severity ${entry.severity}`));
        });
    }

    function createCategoryCell(logItem) {
        const cell = document.createElement('td');
        const wrapper = document.createElement('div');
        wrapper.className = 'review-badge-list';
        appendCategoryBadges(wrapper, logItem, '-');
        cell.appendChild(wrapper);
        return cell;
    }

    function getStatusVariant(status) {
        if (status === 'Resolved') {
            return 'success';
        }
        if (status === 'Dismissed') {
            return 'secondary';
        }
        if (status === 'In-Review') {
            return 'info';
        }
        return 'warning';
    }

    function getActionVariant(action) {
        if (action === 'BlockUser') {
            return 'dark';
        }
        if (action === 'SuspendUser') {
            return 'danger';
        }
        if (action === 'WarnUser') {
            return 'warning';
        }
        if (action === 'Escalate') {
            return 'info';
        }
        return 'secondary';
    }

    function createStatusBadge(status) {
        const normalizedStatus = status || 'New';
        return createBadge(normalizedStatus, getStatusVariant(normalizedStatus));
    }

    function createActionBadge(logItem) {
        const action = logItem.action || 'None';
        return createBadge(formatActionDisplay(logItem), getActionVariant(action));
    }

    function createBadgeCell(badge) {
        const cell = document.createElement('td');
        const wrapper = document.createElement('div');
        wrapper.className = 'review-badge-list';
        wrapper.appendChild(badge);
        cell.appendChild(wrapper);
        return cell;
    }

    function createActionButton(logId, action, label, iconClass, variant) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn btn-sm btn-${variant}`;
        button.dataset.logId = logId || '';
        button.dataset.action = action;
        button.title = label;
        button.setAttribute('aria-label', label);
        button.appendChild(createIcon(iconClass));
        if (action === 'view') {
            button.firstChild.classList.add('me-1');
            button.appendChild(document.createTextNode(label));
        }
        return button;
    }

    function createSafetyActions(item) {
        const actions = document.createElement('div');
        actions.className = 'btn-group btn-group-sm';
        actions.setAttribute('role', 'group');
        actions.setAttribute('aria-label', 'Safety violation actions');
        actions.appendChild(createActionButton(item.id, 'view', 'View', 'bi bi-eye', 'primary'));
        actions.appendChild(createActionButton(
            item.id,
            item.isArchived ? 'unarchive' : 'archive',
            item.isArchived ? 'Unarchive' : 'Archive',
            item.isArchived ? 'bi bi-arrow-counterclockwise' : 'bi bi-archive',
            'outline-secondary',
        ));
        actions.appendChild(createActionButton(
            item.id,
            'delete',
            'Delete',
            'bi bi-trash',
            'outline-danger',
        ));
        return actions;
    }

    function getInitialViewMode() {
        try {
            const savedViewMode = window.localStorage.getItem(SAFETY_VIEW_STORAGE_KEY);
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

    function setSafetyViewMode(viewMode, persist) {
        const normalizedViewMode = viewMode === 'cards' ? 'cards' : 'list';
        state.viewMode = normalizedViewMode;

        const listView = document.getElementById('safety-list-view');
        const cardView = document.getElementById('safety-card-view');
        const listRadio = document.getElementById('safety-view-list');
        const cardsRadio = document.getElementById('safety-view-cards');

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
                window.localStorage.setItem(SAFETY_VIEW_STORAGE_KEY, normalizedViewMode);
            } catch (error) {
                // Ignore storage access errors; the current view has already been applied.
            }
        }
    }

    function formatActionLabel(action) {
        return ACTION_LABELS[action] || action || 'None';
    }

    function formatActionDisplay(logItem) {
        let actionLabel = formatActionLabel(logItem.action || 'None');
        const requestStatus = String(logItem.action_request_status || '').toLowerCase();
        if (requestStatus === 'pending') {
            actionLabel += ' (Pending approval)';
        } else if (requestStatus === 'sending') {
            actionLabel += ' (Sending)';
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

    function isExecutedWarning(logItem) {
        return logItem.action === 'WarnUser'
            && String(logItem.action_request_status || '').toLowerCase() === 'executed';
    }

    function isRestrictionAction(action) {
        return action === 'SuspendUser' || action === 'BlockUser';
    }

    // The action chosen in the review, as the matching entry of ACTION_VALUES. An empty or
    // unknown value reads as None, as an empty one always has.
    function readSelectedAction() {
        const selectedValue = document.getElementById('editAction')?.value || '';
        return ACTION_VALUES.find(function (value) {
            return value === selectedValue;
        }) || 'None';
    }

    // A suspension or block the violation already records is requested again only on purpose,
    // whatever became of the last request, and never while one is waiting or a warning is sent.
    function offersReissue(logItem, action) {
        const requestStatus = String(logItem.action_request_status || '').toLowerCase();
        return isRestrictionAction(action)
            && logItem.action === action
            && requestStatus !== 'pending'
            && requestStatus !== 'sending';
    }

    function describeExistingRestriction(logItem, action) {
        const noun = action === 'BlockUser' ? 'block' : 'suspension';
        const requestStatus = String(logItem.action_request_status || '').toLowerCase();
        if (requestStatus === 'pending') {
            return `This ${noun} is waiting for another eligible reviewer to approve it. The violation can't be changed until the request is decided.`;
        }
        const states = {
            executed: `This ${noun} was approved and applied.`,
            denied: `This ${noun} request was denied.`,
            expired: `This ${noun} request expired without a decision.`,
            failed: `This ${noun} was approved but could not be applied.`,
        };
        const where = states[requestStatus] || `This violation already records a ${noun}.`;
        return `${where} Saving updates the review only and requests nothing new. To ask another eligible reviewer to approve it again, select "Request this ${noun} again".`;
    }

    function isFutureDate(isoValue) {
        const parsedDate = isoValue ? new Date(isoValue) : null;
        return Boolean(parsedDate) && !Number.isNaN(parsedDate.getTime()) && parsedDate.getTime() > Date.now();
    }

    function syncLegacyEscalateOption(selectElement, logItem) {
        if (!selectElement) {
            return;
        }

        const existingOption = Array.from(selectElement.options).find(function (option) {
            return option.value === LEGACY_ESCALATE_ACTION;
        });
        if (logItem.action === LEGACY_ESCALATE_ACTION) {
            if (!existingOption) {
                const legacyOption = document.createElement('option');
                legacyOption.value = LEGACY_ESCALATE_ACTION;
                legacyOption.textContent = ACTION_LABELS.Escalate;
                selectElement.appendChild(legacyOption);
            }
        } else if (existingOption) {
            existingOption.remove();
        }
    }

    function updateWarningAcknowledgment(logItem) {
        const acknowledgmentElement = document.getElementById('safetyWarningAcknowledgment');
        if (!acknowledgmentElement) {
            return;
        }

        const status = isExecutedWarning(logItem) ? logItem.warning_acknowledgment_status : null;
        let text = '';
        if (status === 'acknowledged') {
            text = `Warning acknowledged ${formatDateTime(logItem.warning_acknowledged_at)}`;
        } else if (status === 'pending') {
            text = 'Warning sent. Not yet acknowledged by the user.';
        } else if (status === 'not_tracked') {
            text = 'Warning sent before acknowledgment was tracked.';
        }
        acknowledgmentElement.textContent = text;
        setElementHidden(acknowledgmentElement, !text);
    }

    function updateRemediationFields(logItem, forcePopulate) {
        const action = readSelectedAction();
        const remediationFields = document.getElementById('safetyRemediationFields');
        const remediationHelp = document.getElementById('safetyRemediationHelp');
        const notificationGroup = document.getElementById('safetyNotificationGroup');
        const notificationMessage = document.getElementById('editNotificationMessage');
        const suspendGroup = document.getElementById('safetySuspendUntilGroup');
        const suspendInput = document.getElementById('editSuspendUntil');

        if (!remediationFields || !remediationHelp || !notificationMessage || !suspendGroup || !suspendInput) {
            return;
        }

        const shouldShow = SAFETY_REMEDIATION_ACTIONS.has(action);
        setElementHidden(remediationFields, !shouldShow);
        const reissueGroup = document.getElementById('safetyReissueGroup');
        const reissueInput = document.getElementById('editReissue');
        const reissueOffered = shouldShow && offersReissue(logItem, action);
        if (reissueGroup && reissueInput) {
            setElementHidden(reissueGroup, !reissueOffered);
            if (forcePopulate || !reissueOffered) {
                reissueInput.checked = false;
            }
            const noun = action === 'BlockUser' ? 'block' : 'suspension';
            document.getElementById('editReissueLabel').textContent = `Request this ${noun} again`;
            document.getElementById('editReissueHelp').textContent = action === 'SuspendUser'
                ? 'Creates a new approval request with the notification and restore date below. It applies only after another eligible reviewer approves it.'
                : 'Creates a new approval request with the notification below. It applies only after another eligible reviewer approves it.';
        }
        // Saving the same suspension or block again, without asking for it again, requests
        // nothing, so the notification and restore date would not be used. Nor would they for
        // one still waiting for approval, which can't be changed until it is decided.
        const awaitingApproval = isRestrictionAction(action)
            && logItem.action === action
            && String(logItem.action_request_status || '').toLowerCase() === 'pending';
        const requestsNothing = awaitingApproval || (reissueOffered && !(reissueInput && reissueInput.checked));

        if (!shouldShow) {
            remediationHelp.textContent = '';
            notificationMessage.value = '';
            notificationMessage.dataset.generatedMessage = '';
            notificationMessage.dataset.action = action;
            suspendInput.value = '';
            suspendInput.dataset.action = action;
            setElementHidden(suspendGroup, true);
            return;
        }

        // A warning already sent is not sent again, so saving this record again only updates it.
        const warningAlreadySent = action === 'WarnUser' && isExecutedWarning(logItem);
        setElementHidden(notificationGroup, warningAlreadySent || requestsNothing);

        const helpTextMap = {
            WarnUser: 'Warn user sends the warning to the affected user as soon as you save, without a second reviewer. The user must acknowledge it the next time they use SimpleChat.',
            SuspendUser: 'Suspend user restricts access until the restore date. Because it restricts access, saving creates an approval request, and the suspension applies only after another eligible reviewer approves it.',
            BlockUser: 'Block user restricts access with no automatic restore date. Saving creates an approval request, and the block applies only after another eligible reviewer approves it.',
        };
        if (warningAlreadySent) {
            remediationHelp.textContent = 'This warning was already sent. Saving updates the review without sending the warning again.';
        } else if (requestsNothing) {
            remediationHelp.textContent = describeExistingRestriction(logItem, action);
        } else {
            remediationHelp.textContent = helpTextMap[action] || '';
        }

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

        const showSuspendUntil = action === 'SuspendUser' && !requestsNothing;
        setElementHidden(suspendGroup, !showSuspendUntil);
        if (forcePopulate || suspendInput.dataset.action !== action) {
            // The last restore time is offered again only while it is still ahead.
            const restoreDate = logItem.action === action && isFutureDate(logItem.action_datetime_to_allow)
                ? logItem.action_datetime_to_allow
                : '';
            suspendInput.value = action === 'SuspendUser' ? toLocalDateTimeInputValue(restoreDate) : '';
        }
        suspendInput.dataset.action = action;
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
        setTextContent('safetyBlockedCount', data.block_user_count || 0);

        setTextContent('safetyStatsNewSummary', data.new_count || 0);
        setTextContent('safetyStatsInReviewSummary', data.in_review_count || 0);
        setTextContent('safetyStatsResolvedSummary', data.resolved_count || 0);
        setTextContent('safetyStatsDismissedSummary', data.dismissed_count || 0);
        setTextContent('safetyStatsNoneActionSummary', data.none_action_count || 0);
        setTextContent('safetyStatsWarnSummary', data.warn_user_count || 0);
        setTextContent('safetyStatsSuspendSummary', data.suspend_user_count || 0);
        setTextContent('safetyStatsBlockSummary', data.block_user_count || 0);
        // Escalations recorded before the action was removed are still counted, and only
        // shown when there are any.
        const legacyEscalations = data.escalate_count || 0;
        setTextContent('safetyStatsLegacyEscalateSummary', legacyEscalations);
        setElementHidden(document.getElementById('safetyStatsLegacyEscalateRow'), legacyEscalations <= 0);
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

            row.appendChild(createTextCell(item.message || '', 'table-message-cell', item.message || ''));
            row.appendChild(createCategoryCell(item));
            row.appendChild(createBadgeCell(createStatusBadge(item.status || 'New')));
            row.appendChild(createBadgeCell(createActionBadge(item)));

            const viewCell = document.createElement('td');
            viewCell.className = 'table-details-cell';
            viewCell.appendChild(createSafetyActions(item));
            row.appendChild(viewCell);

            tbody.appendChild(row);
        }
    }

    function renderSafetyCards(items) {
        const cardView = document.getElementById('safety-card-view');
        if (!cardView) {
            return;
        }

        clearElement(cardView);
        if (!items.length) {
            renderCardMessage('No safety violations found for the current filters.', false);
            return;
        }

        items.forEach(function (item) {
            const column = document.createElement('div');
            column.className = 'col-12 col-xl-6 col-xxl-4';

            const card = document.createElement('article');
            card.className = 'review-card';

            const header = document.createElement('div');
            header.className = 'review-card-header';
            const timestamp = document.createElement('div');
            timestamp.className = 'review-card-meta';
            timestamp.textContent = formatDateTime(item.last_updated || item.created_at);
            const statusBadges = document.createElement('div');
            statusBadges.className = 'review-badge-list';
            statusBadges.appendChild(createStatusBadge(item.status || 'New'));
            statusBadges.appendChild(createActionBadge(item));
            header.appendChild(timestamp);
            header.appendChild(statusBadges);

            const message = document.createElement('p');
            message.className = 'review-card-title';
            message.textContent = item.message || 'No message captured.';

            const categoryBadges = document.createElement('div');
            categoryBadges.className = 'review-badge-list';
            appendCategoryBadges(categoryBadges, item, 'No triggered categories');

            const footer = document.createElement('div');
            footer.className = 'review-card-footer';
            const footerMeta = document.createElement('div');
            footerMeta.className = 'review-card-meta';
            footerMeta.textContent = item.notes ? 'Notes added' : 'No notes yet';
            footer.appendChild(footerMeta);
            footer.appendChild(createSafetyActions(item));

            card.appendChild(header);
            card.appendChild(message);
            card.appendChild(categoryBadges);
            card.appendChild(footer);
            column.appendChild(card);
            cardView.appendChild(column);
        });
    }

    async function renderSafetyItems(items) {
        await renderSafetyRows(items);
        renderSafetyCards(items);
    }

    async function loadSafetyLogs() {
        renderSafetyMessage('Loading logs...', false);

        try {
            const params = getQueryParams(true);
            const data = await fetchJson(`/api/safety/logs?${params.toString()}`);
            state.items = Array.isArray(data.logs) ? data.logs : [];
            await renderSafetyItems(state.items);
            buildPagination(data.page || state.currentPage, data.page_size || state.pageSize, data.total_count || 0);
        } catch (error) {
            renderSafetyMessage(`Error loading logs: ${error.message}`, true);
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

    function getDeleteModalInstance() {
        if (!deleteModalInstance && typeof bootstrap !== 'undefined') {
            const modalElement = document.getElementById('deleteSafetyModal');
            if (modalElement) {
                deleteModalInstance = new bootstrap.Modal(modalElement);
            }
        }

        return deleteModalInstance;
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
        appendCategoryBadges(document.getElementById('editCategories'), item, 'No triggered categories');
        document.getElementById('editStatus').value = item.status || 'New';
        syncLegacyEscalateOption(document.getElementById('editAction'), item);
        document.getElementById('editAction').value = item.action || 'None';
        for (const option of document.getElementById('editAction').options) {
            option.disabled = item.content_origin === 'assistant' && SAFETY_REMEDIATION_ACTIONS.has(option.value);
        }
        document.getElementById('editNotes').value = item.notes || '';
        document.getElementById('editLogId').value = item.id || '';
        setTextContent('safetyEditStatus', '');
        updateWarningAcknowledgment(item);
        const archiveButton = document.getElementById('archiveSafetyBtn');
        if (archiveButton) {
            archiveButton.dataset.archived = item.isArchived ? 'true' : 'false';
            const label = archiveButton.querySelector('span');
            if (label) {
                label.textContent = item.isArchived ? 'Unarchive' : 'Archive';
            }
        }
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

        const action = readSelectedAction();
        const payload = {
            status: document.getElementById('editStatus')?.value || 'New',
            action: action,
            notes: document.getElementById('editNotes')?.value || '',
        };

        // A suspension or block is requested when it is newly chosen, or asked for again.
        const activeItem = state.activeItem || {};
        const reissue = offersReissue(activeItem, action) && Boolean(document.getElementById('editReissue')?.checked);
        const requestsRestriction = isRestrictionAction(action) && (activeItem.action !== action || reissue);
        if (action === 'WarnUser' || requestsRestriction) {
            payload.notification_message = document.getElementById('editNotificationMessage')?.value || '';

            if (action === 'SuspendUser') {
                const suspendUntilValue = document.getElementById('editSuspendUntil')?.value || '';
                payload.datetime_to_allow = fromLocalDateTimeInputValue(suspendUntilValue);
                if (!payload.datetime_to_allow) {
                    throw new Error('Restore access date is required for a suspension.');
                }
                if (!isFutureDate(payload.datetime_to_allow)) {
                    throw new Error('Choose a restore date and time in the future.');
                }
            }
        }
        if (reissue) {
            payload.reissue = true;
        }

        if (statusElement) {
            statusElement.textContent = 'Saving review...';
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

    function getLifecycleResultMessage(result) {
        return result.audit_warning || result.message || 'Safety violation updated successfully.';
    }

    async function updateSafetyArchiveState(logId, archived) {
        const result = await fetchJson(`/api/safety/logs/${encodeURIComponent(logId)}/archive`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ archived: archived }),
        });

        const modalInstance = getEditModalInstance();
        if (modalInstance && state.activeItem?.id === logId) {
            modalInstance.hide();
        }
        showPageStatus(getLifecycleResultMessage(result), result.audit_warning ? 'warning' : 'success');
        await refreshSafetyView();
    }

    function openDeleteModal(logId) {
        const item = state.items.find(function (entry) {
            return entry.id === logId;
        });
        if (!item) {
            return;
        }

        state.activeItem = item;
        const modalInstance = getDeleteModalInstance();
        if (modalInstance) {
            modalInstance.show();
        }
    }

    async function deleteSafetyViolation() {
        const logId = state.activeItem?.id || '';
        if (!logId) {
            return;
        }

        const confirmButton = document.getElementById('confirmDeleteSafetyBtn');
        if (confirmButton) {
            confirmButton.disabled = true;
        }

        try {
            const result = await fetchJson(`/api/safety/logs/${encodeURIComponent(logId)}`, {
                method: 'DELETE',
            });
            const deleteModal = getDeleteModalInstance();
            if (deleteModal) {
                deleteModal.hide();
            }
            const editModal = getEditModalInstance();
            if (editModal) {
                editModal.hide();
            }
            if (state.items.length === 1 && state.currentPage > 1) {
                state.currentPage -= 1;
            }
            showPageStatus(getLifecycleResultMessage(result), result.audit_warning ? 'warning' : 'success');
            await refreshSafetyView();
        } finally {
            if (confirmButton) {
                confirmButton.disabled = false;
            }
        }
    }

    function handleSafetyActionClick(event) {
        const actionButton = event.target.closest('button[data-log-id]');
        if (!actionButton) {
            return;
        }

        const logId = actionButton.dataset.logId || '';
        const action = actionButton.dataset.action || 'view';
        if (action === 'archive' || action === 'unarchive') {
            updateSafetyArchiveState(logId, action === 'archive').catch(function (error) {
                showPageStatus(error.message, 'danger');
            });
        } else if (action === 'delete') {
            openDeleteModal(logId);
        } else {
            openEditModal(logId);
        }
    }

    function attachEventListeners() {
        const tableBody = document.querySelector('#safetyLogsTable tbody');
        const cardView = document.getElementById('safety-card-view');
        const pageSizeSelect = document.getElementById('page-size-select');
        const applyFiltersButton = document.getElementById('applyFiltersBtn');
        const clearFiltersButton = document.getElementById('clearFiltersBtn');
        const exportButton = document.getElementById('safetyExportBtn');
        const saveButton = document.getElementById('saveChangesBtn');
        const actionSelect = document.getElementById('editAction');
        const listViewRadio = document.getElementById('safety-view-list');
        const cardsViewRadio = document.getElementById('safety-view-cards');
        const archiveButton = document.getElementById('archiveSafetyBtn');
        const deleteButton = document.getElementById('deleteSafetyBtn');
        const confirmDeleteButton = document.getElementById('confirmDeleteSafetyBtn');

        if (tableBody) {
            tableBody.addEventListener('click', handleSafetyActionClick);
        }

        if (cardView) {
            cardView.addEventListener('click', handleSafetyActionClick);
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
                const archiveSelect = document.getElementById('filterSafetyArchive');
                if (statusSelect) {
                    statusSelect.value = '';
                }
                if (actionFilterSelect) {
                    actionFilterSelect.value = '';
                }
                if (archiveSelect) {
                    archiveSelect.value = 'active';
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
                if (saveButton.disabled) {
                    return;
                }
                // A second click while the save is in flight would send a second request.
                saveButton.disabled = true;
                saveButton.setAttribute('aria-busy', 'true');
                saveSafetyChanges().catch(function (error) {
                    const statusElement = document.getElementById('safetyEditStatus');
                    if (statusElement) {
                        statusElement.textContent = error.message;
                        statusElement.className = 'small text-danger me-auto';
                    }
                }).finally(function () {
                    saveButton.disabled = false;
                    saveButton.removeAttribute('aria-busy');
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

        const reissueInput = document.getElementById('editReissue');
        if (reissueInput) {
            reissueInput.addEventListener('change', function () {
                if (state.activeItem) {
                    updateRemediationFields(state.activeItem, false);
                }
            });
        }

        if (archiveButton) {
            archiveButton.addEventListener('click', function () {
                const logId = document.getElementById('editLogId')?.value || '';
                const archived = archiveButton.dataset.archived !== 'true';
                updateSafetyArchiveState(logId, archived).catch(function (error) {
                    const statusElement = document.getElementById('safetyEditStatus');
                    if (statusElement) {
                        statusElement.textContent = error.message;
                    }
                });
            });
        }

        if (deleteButton) {
            deleteButton.addEventListener('click', function () {
                const logId = document.getElementById('editLogId')?.value || '';
                openDeleteModal(logId);
            });
        }

        if (confirmDeleteButton) {
            confirmDeleteButton.addEventListener('click', function () {
                deleteSafetyViolation().catch(function (error) {
                    showPageStatus(error.message, 'danger');
                });
            });
        }

        if (listViewRadio) {
            listViewRadio.addEventListener('change', function () {
                if (listViewRadio.checked) {
                    setSafetyViewMode('list', true);
                }
            });
        }

        if (cardsViewRadio) {
            cardsViewRadio.addEventListener('change', function () {
                if (cardsViewRadio.checked) {
                    setSafetyViewMode('cards', true);
                }
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        setSafetyViewMode(getInitialViewMode(), false);
        attachEventListeners();
        clearPageStatus();
        refreshSafetyView().catch(function (error) {
            renderSafetyMessage(`Error loading logs: ${error.message}`, true);
        });
    });
})();