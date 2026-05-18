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
    const groupState = {
        currentPage: 1,
        pageSize: 10,
        search: '',
        items: [],
        hasLoaded: false,
        viewMode: 'list',
    };
    const publicWorkspaceState = {
        currentPage: 1,
        pageSize: 10,
        search: '',
        items: [],
        hasLoaded: false,
        viewMode: 'list',
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

    function getProfileTabButton(tabName) {
        const tabButtons = document.querySelectorAll('#profileTabs [data-profile-tab]');
        for (const tabButton of tabButtons) {
            if (tabButton.dataset.profileTab === tabName) {
                return tabButton;
            }
        }

        return null;
    }

    function getRequestedProfileTabName() {
        const url = new URL(window.location.href);
        return (url.searchParams.get('tab') || '').trim().toLowerCase();
    }

    function loadProfileTabData(tabName) {
        if (tabName === 'feedback' && pageConfig.feedbackEnabled && !feedbackState.hasLoaded) {
            refreshProfileFeedback();
        }
        if (tabName === 'violations' && pageConfig.contentSafetyEnabled && !violationState.hasLoaded) {
            refreshProfileViolations();
        }
        if (tabName === 'groups' && pageConfig.groupWorkspacesEnabled && !groupState.hasLoaded) {
            loadWorkspaceCollection(workspaceTabConfigs.groups);
        }
        if (tabName === 'public-workspaces' && pageConfig.publicWorkspacesEnabled && !publicWorkspaceState.hasLoaded) {
            loadWorkspaceCollection(workspaceTabConfigs.publicWorkspaces);
        }
    }

    function activateRequestedProfileTab() {
        const requestedTab = getRequestedProfileTabName();
        if (!requestedTab) {
            return pageConfig.initialTab || 'stats';
        }

        const tabButton = getProfileTabButton(requestedTab);
        if (!tabButton) {
            return pageConfig.initialTab || 'stats';
        }

        if (tabButton.classList.contains('active')) {
            return requestedTab;
        }

        if (typeof bootstrap !== 'undefined' && bootstrap.Tab) {
            bootstrap.Tab.getOrCreateInstance(tabButton).show();
            return '';
        }

        return requestedTab;
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

    function normalizeSafetySeverity(severity) {
        const parsedSeverity = Number(severity);
        return Number.isFinite(parsedSeverity) ? parsedSeverity : null;
    }

    function getTriggeredCategoryEntries(logItem) {
        const categories = Array.isArray(logItem.triggered_categories) ? logItem.triggered_categories : [];
        return categories.reduce(function (entries, entry) {
            const categoryName = String(entry.category || '').trim();
            const severity = normalizeSafetySeverity(entry.severity);
            if (categoryName && severity >= 1 && severity <= 4) {
                entries.push({ category: categoryName, severity });
            }
            return entries;
        }, []);
    }

    function getSafetyCategoryBadgeVariant(severity) {
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

    function createSafetyCategoryBadge(entry) {
        const badge = document.createElement('span');
        badge.className = `badge rounded-pill text-bg-${getSafetyCategoryBadgeVariant(entry.severity)}`;
        badge.textContent = entry.category;
        badge.title = `Severity ${entry.severity}`;
        return badge;
    }

    function appendSafetyCategoryBadges(container, logItem, emptyText) {
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
            container.appendChild(createSafetyCategoryBadge(entry));
        });
    }

    function createSafetyCategoryCell(logItem) {
        const cell = document.createElement('td');
        const wrapper = document.createElement('div');
        wrapper.className = 'd-flex flex-wrap gap-1';
        appendSafetyCategoryBadges(wrapper, logItem, '-');
        cell.appendChild(wrapper);
        return cell;
    }

    const workspaceTabConfigs = {
        groups: {
            type: 'groups',
            label: 'groups',
            itemLabel: 'group',
            state: groupState,
            apiEndpoint: '/api/groups',
            responseKey: 'groups',
            activeEndpoint: '/api/groups/setActive',
            activePayloadKey: 'groupId',
            createEndpoint: '/api/groups',
            discoverEndpoint: '/api/groups/discover',
            logoEndpoint: function (workspaceId, logoVersion) {
                return `/api/groups/${encodeURIComponent(workspaceId)}/logo?v=${encodeURIComponent(logoVersion)}`;
            },
            managePath: function (workspaceId) {
                return `/groups/${encodeURIComponent(workspaceId)}`;
            },
            requestEndpoint: function (workspaceId) {
                return `/api/groups/${encodeURIComponent(workspaceId)}/requests`;
            },
            tableSelector: '#profile-groups-table tbody',
            listViewId: 'profile-groups-list-view',
            cardViewId: 'profile-groups-card-view',
            paginationId: 'profile-groups-pagination',
            pageSizeSelectId: 'profile-groups-page-size',
            searchInputId: 'profile-groups-search-input',
            searchButtonId: 'profile-groups-search-btn',
            clearSearchButtonId: 'profile-groups-clear-search-btn',
            viewListId: 'profile-groups-view-list',
            viewCardsId: 'profile-groups-view-cards',
            createFormId: 'profile-create-group-form',
            createNameId: 'profile-create-group-name',
            createDescriptionId: 'profile-create-group-description',
            createStatusId: 'profile-create-group-status',
            createModalId: 'profileCreateGroupModal',
            discoverSearchId: 'profile-find-groups-search',
            discoverSearchButtonId: 'profile-find-groups-search-btn',
            discoverStatusId: 'profile-find-groups-status',
            discoverTbodyId: 'profile-find-groups-tbody',
            storageKey: 'simplechat.profile.groups.viewMode',
            emptyMessage: 'No groups found for the current search.',
            loadingMessage: 'Loading your groups...',
            discoverEmptyMessage: 'No groups found for the current search.',
            requestLabel: 'Request to Join',
        },
        publicWorkspaces: {
            type: 'publicWorkspaces',
            label: 'public workspaces',
            itemLabel: 'public workspace',
            state: publicWorkspaceState,
            apiEndpoint: '/api/public_workspaces',
            responseKey: 'workspaces',
            activeEndpoint: '/api/public_workspaces/setActive',
            activePayloadKey: 'workspaceId',
            createEndpoint: '/api/public_workspaces',
            discoverEndpoint: '/api/public_workspaces/discover',
            logoEndpoint: function (workspaceId, logoVersion) {
                return `/api/public_workspaces/${encodeURIComponent(workspaceId)}/logo?v=${encodeURIComponent(logoVersion)}`;
            },
            managePath: function (workspaceId) {
                return `/public_workspaces/${encodeURIComponent(workspaceId)}`;
            },
            requestEndpoint: function (workspaceId) {
                return `/api/public_workspaces/${encodeURIComponent(workspaceId)}/requests`;
            },
            tableSelector: '#profile-public-workspaces-table tbody',
            listViewId: 'profile-public-workspaces-list-view',
            cardViewId: 'profile-public-workspaces-card-view',
            paginationId: 'profile-public-workspaces-pagination',
            pageSizeSelectId: 'profile-public-workspaces-page-size',
            searchInputId: 'profile-public-workspaces-search-input',
            searchButtonId: 'profile-public-workspaces-search-btn',
            clearSearchButtonId: 'profile-public-workspaces-clear-search-btn',
            viewListId: 'profile-public-workspaces-view-list',
            viewCardsId: 'profile-public-workspaces-view-cards',
            createFormId: 'profile-create-public-workspace-form',
            createNameId: 'profile-create-public-workspace-name',
            createDescriptionId: 'profile-create-public-workspace-description',
            createStatusId: 'profile-create-public-workspace-status',
            createModalId: 'profileCreatePublicWorkspaceModal',
            discoverSearchId: 'profile-find-public-workspaces-search',
            discoverSearchButtonId: 'profile-find-public-workspaces-search-btn',
            discoverStatusId: 'profile-find-public-workspaces-status',
            discoverTbodyId: 'profile-find-public-workspaces-tbody',
            storageKey: 'simplechat.profile.publicWorkspaces.viewMode',
            emptyMessage: 'No public workspaces found for the current search.',
            loadingMessage: 'Loading public workspaces...',
            discoverEmptyMessage: 'No public workspaces found for the current search.',
            requestLabel: 'Request Access',
        },
    };

    function getWorkspaceConfigFromType(workspaceType) {
        if (workspaceType === 'groups') {
            return workspaceTabConfigs.groups;
        }
        if (workspaceType === 'publicWorkspaces') {
            return workspaceTabConfigs.publicWorkspaces;
        }

        return null;
    }

    function getWorkspaceId(item) {
        return item && item.id ? String(item.id) : '';
    }

    function getWorkspaceName(item, fallback) {
        const value = item && item.name ? String(item.name).trim() : '';
        return value || fallback;
    }

    function getOwnerLabel(owner) {
        if (!owner || typeof owner !== 'object') {
            return '';
        }

        return owner.displayName || owner.email || '';
    }

    function getWorkspaceRoleLabel(item) {
        return item && item.userRole ? String(item.userRole) : 'Viewer';
    }

    function getWorkspaceStatusLabel(item) {
        const status = item && item.status ? String(item.status) : 'active';
        return status.charAt(0).toUpperCase() + status.slice(1);
    }

    function getSafeHeroColor(value) {
        const colorValue = value ? String(value).trim() : '';
        if (/^#[0-9a-fA-F]{6}$/.test(colorValue)) {
            return colorValue;
        }

        return '#0d6efd';
    }

    function getWorkspaceInitial(name) {
        const normalizedName = String(name || '').trim();
        return normalizedName ? normalizedName.charAt(0).toUpperCase() : 'W';
    }

    function appendIconText(element, iconClass, label) {
        const iconElement = document.createElement('i');
        iconElement.className = `${iconClass} me-1`;
        element.appendChild(iconElement);
        element.appendChild(document.createTextNode(label));
    }

    function createStatusBadge(label, statusValue) {
        const badge = document.createElement('span');
        const normalizedStatus = String(statusValue || label || '').toLowerCase();
        badge.className = 'badge';
        if (normalizedStatus.includes('pending')) {
            badge.classList.add('bg-warning', 'text-dark');
        } else if (normalizedStatus.includes('reject') || normalizedStatus.includes('error')) {
            badge.classList.add('bg-danger');
        } else if (normalizedStatus.includes('archive') || normalizedStatus.includes('disabled')) {
            badge.classList.add('bg-secondary');
        } else {
            badge.classList.add('bg-success');
        }
        badge.textContent = label;
        return badge;
    }

    function createWorkspaceMedia(config, item) {
        const workspaceId = getWorkspaceId(item);
        const workspaceName = getWorkspaceName(item, config.itemLabel);
        const media = document.createElement('div');
        media.className = 'profile-workspace-card-media flex-shrink-0';
        media.style.backgroundColor = getSafeHeroColor(item?.heroColor);

        if (workspaceId && item?.hasLogo) {
            const logoVersion = item.logoVersion || 1;
            const imageElement = document.createElement('img');
            imageElement.src = config.logoEndpoint(workspaceId, logoVersion);
            imageElement.alt = `${workspaceName} logo`;
            media.appendChild(imageElement);
        } else {
            media.textContent = getWorkspaceInitial(workspaceName);
        }

        return media;
    }

    function createManageLink(config, workspaceId) {
        const manageLink = document.createElement('a');
        manageLink.className = 'btn btn-sm btn-outline-primary';
        manageLink.href = config.managePath(workspaceId);
        appendIconText(manageLink, 'bi bi-gear', 'Manage');
        return manageLink;
    }

    function createSetActiveButton(config, workspaceId) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-success';
        button.dataset.workspaceAction = 'activate';
        button.dataset.workspaceType = config.type;
        button.dataset.workspaceId = workspaceId;
        appendIconText(button, 'bi bi-check2-circle', 'Set Active');
        return button;
    }

    function createWorkspaceNameCell(config, item) {
        const cell = document.createElement('td');
        const workspaceName = getWorkspaceName(item, config.itemLabel);
        const description = item && item.description ? String(item.description) : '';

        const nameElement = document.createElement('div');
        nameElement.className = 'profile-workspace-name-cell fw-semibold';
        nameElement.textContent = workspaceName;
        nameElement.title = workspaceName;
        cell.appendChild(nameElement);

        if (description) {
            const descriptionElement = document.createElement('div');
            descriptionElement.className = 'small text-muted profile-workspace-description';
            descriptionElement.textContent = description;
            descriptionElement.title = description;
            cell.appendChild(descriptionElement);
        }

        return cell;
    }

    function createWorkspaceActiveCell(config, item) {
        const cell = document.createElement('td');
        const workspaceId = getWorkspaceId(item);
        if (item && item.isActive) {
            cell.appendChild(createStatusBadge('Active', 'active'));
        } else if (workspaceId) {
            cell.appendChild(createSetActiveButton(config, workspaceId));
        } else {
            cell.textContent = '-';
        }

        return cell;
    }

    function createWorkspaceActionsCell(config, item) {
        const cell = document.createElement('td');
        const workspaceId = getWorkspaceId(item);
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'profile-workspace-actions';

        if (workspaceId) {
            actionsContainer.appendChild(createManageLink(config, workspaceId));
        }

        cell.appendChild(actionsContainer);
        return cell;
    }

    function renderWorkspaceTableRows(config, items) {
        const tableBody = document.querySelector(config.tableSelector);
        if (!tableBody) {
            return;
        }

        clearElement(tableBody);
        if (!items.length) {
            renderTableMessageRow(tableBody, 5, config.emptyMessage, false);
            return;
        }

        items.forEach(function (item) {
            const row = document.createElement('tr');
            const statusLabel = getWorkspaceStatusLabel(item);

            row.appendChild(createWorkspaceNameCell(config, item));
            row.appendChild(createTextCell(getWorkspaceRoleLabel(item)));

            const statusCell = document.createElement('td');
            statusCell.appendChild(createStatusBadge(statusLabel, item?.status));
            row.appendChild(statusCell);

            row.appendChild(createWorkspaceActiveCell(config, item));
            row.appendChild(createWorkspaceActionsCell(config, item));
            tableBody.appendChild(row);
        });
    }

    function renderWorkspaceCardMessage(config, message, isError) {
        const cardContainer = document.getElementById(config.cardViewId);
        if (!cardContainer) {
            return;
        }

        clearElement(cardContainer);
        const column = document.createElement('div');
        column.className = 'col-12';
        const messageElement = document.createElement('div');
        messageElement.className = isError ? 'profile-empty-state text-danger' : 'profile-empty-state';
        messageElement.textContent = message;
        column.appendChild(messageElement);
        cardContainer.appendChild(column);
    }

    function renderWorkspaceCards(config, items) {
        const cardContainer = document.getElementById(config.cardViewId);
        if (!cardContainer) {
            return;
        }

        clearElement(cardContainer);
        if (!items.length) {
            renderWorkspaceCardMessage(config, config.emptyMessage, false);
            return;
        }

        items.forEach(function (item) {
            const workspaceId = getWorkspaceId(item);
            const workspaceName = getWorkspaceName(item, config.itemLabel);
            const description = item && item.description ? String(item.description) : 'No description provided.';
            const ownerLabel = getOwnerLabel(item?.owner);

            const column = document.createElement('div');
            column.className = 'col-12 col-md-6 col-xl-4';

            const card = document.createElement('div');
            card.className = 'profile-workspace-card profile-workspace-card-clickable';
            if (workspaceId) {
                card.dataset.manageUrl = config.managePath(workspaceId);
                card.setAttribute('role', 'link');
                card.setAttribute('tabindex', '0');
                card.setAttribute('aria-label', `Manage ${workspaceName}`);
            }

            const header = document.createElement('div');
            header.className = 'd-flex align-items-start gap-3 mb-3';
            header.appendChild(createWorkspaceMedia(config, item));

            const titleWrap = document.createElement('div');
            titleWrap.className = 'min-w-0';
            const title = document.createElement('div');
            title.className = 'profile-workspace-card-title';
            title.textContent = workspaceName;
            titleWrap.appendChild(title);

            if (ownerLabel) {
                const owner = document.createElement('div');
                owner.className = 'profile-workspace-card-meta';
                owner.textContent = `Owner: ${ownerLabel}`;
                titleWrap.appendChild(owner);
            }

            header.appendChild(titleWrap);
            card.appendChild(header);

            const descriptionElement = document.createElement('div');
            descriptionElement.className = 'profile-workspace-card-description mb-3';
            descriptionElement.textContent = description;
            card.appendChild(descriptionElement);

            const badgeRow = document.createElement('div');
            badgeRow.className = 'd-flex flex-wrap gap-2 mb-3';
            badgeRow.appendChild(createStatusBadge(getWorkspaceRoleLabel(item), 'active'));
            badgeRow.appendChild(createStatusBadge(getWorkspaceStatusLabel(item), item?.status));
            if (item && item.isActive) {
                badgeRow.appendChild(createStatusBadge('Active', 'active'));
            }
            card.appendChild(badgeRow);

            const actions = document.createElement('div');
            actions.className = 'profile-workspace-actions';
            if (workspaceId && !item?.isActive) {
                actions.appendChild(createSetActiveButton(config, workspaceId));
            }
            if (workspaceId) {
                actions.appendChild(createManageLink(config, workspaceId));
            }
            card.appendChild(actions);

            column.appendChild(card);
            cardContainer.appendChild(column);
        });
    }

    function setWorkspaceViewMode(config, viewMode) {
        const normalizedViewMode = viewMode === 'cards' ? 'cards' : 'list';
        const listView = document.getElementById(config.listViewId);
        const cardView = document.getElementById(config.cardViewId);
        const listRadio = document.getElementById(config.viewListId);
        const cardsRadio = document.getElementById(config.viewCardsId);

        config.state.viewMode = normalizedViewMode;
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

        try {
            window.localStorage.setItem(config.storageKey, normalizedViewMode);
        } catch (error) {
            // Ignore storage issues and keep the in-memory view mode.
        }
    }

    function initializeWorkspaceViewMode(config) {
        let savedViewMode = '';
        try {
            savedViewMode = window.localStorage.getItem(config.storageKey) || '';
        } catch (error) {
            savedViewMode = '';
        }

        const defaultViewMode = window.matchMedia && window.matchMedia('(max-width: 991.98px)').matches ? 'cards' : 'list';
        setWorkspaceViewMode(config, savedViewMode || defaultViewMode);
    }

    function renderWorkspaceCollection(config, items) {
        renderWorkspaceTableRows(config, items);
        renderWorkspaceCards(config, items);
        setWorkspaceViewMode(config, config.state.viewMode);
    }

    function getWorkspaceQueryParams(config) {
        const params = new URLSearchParams();
        params.set('page', String(config.state.currentPage));
        params.set('page_size', String(config.state.pageSize));
        if (config.state.search) {
            params.set('search', config.state.search);
        }
        return params;
    }

    async function loadWorkspaceCollection(config) {
        const tableBody = document.querySelector(config.tableSelector);
        const paginationContainer = document.getElementById(config.paginationId);
        if (!tableBody || !paginationContainer) {
            return;
        }

        renderTableMessageRow(tableBody, 5, config.loadingMessage, false);
        renderWorkspaceCardMessage(config, config.loadingMessage, false);
        clearElement(paginationContainer);

        try {
            const params = getWorkspaceQueryParams(config);
            const data = await fetchJson(`${config.apiEndpoint}?${params.toString()}`);
            const items = Array.isArray(data[config.responseKey]) ? data[config.responseKey] : [];
            config.state.items = items;
            config.state.hasLoaded = true;
            renderWorkspaceCollection(config, items);
            buildPagination(
                paginationContainer,
                data.page || config.state.currentPage,
                data.page_size || config.state.pageSize,
                data.total_count || 0,
                function (pageNumber) {
                    config.state.currentPage = pageNumber;
                    loadWorkspaceCollection(config);
                }
            );
        } catch (error) {
            renderTableMessageRow(tableBody, 5, `Error loading ${config.label}: ${error.message}`, true);
            renderWorkspaceCardMessage(config, `Error loading ${config.label}: ${error.message}`, true);
        }
    }

    async function setActiveWorkspace(config, workspaceId) {
        if (!workspaceId) {
            return;
        }

        await fetchJson(config.activeEndpoint, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                [config.activePayloadKey]: workspaceId,
            }),
        });

        config.state.items.forEach(function (item) {
            item.isActive = getWorkspaceId(item) === workspaceId;
        });
        renderWorkspaceCollection(config, config.state.items);
    }

    function setAlertMessage(elementId, message, variant) {
        const statusElement = document.getElementById(elementId);
        if (!statusElement) {
            return;
        }

        if (!message) {
            statusElement.className = 'alert d-none';
            statusElement.textContent = '';
            return;
        }

        statusElement.className = `alert alert-${variant || 'info'}`;
        statusElement.textContent = message;
    }

    async function createWorkspaceItem(config) {
        const form = document.getElementById(config.createFormId);
        const nameInput = document.getElementById(config.createNameId);
        const descriptionInput = document.getElementById(config.createDescriptionId);
        const nameValue = nameInput ? nameInput.value.trim() : '';
        const descriptionValue = descriptionInput ? descriptionInput.value.trim() : '';

        if (!nameValue) {
            setAlertMessage(config.createStatusId, 'Name is required.', 'warning');
            return;
        }

        setAlertMessage(config.createStatusId, `Creating ${config.itemLabel}...`, 'info');

        try {
            await fetchJson(config.createEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: nameValue,
                    description: descriptionValue,
                }),
            });

            setAlertMessage(config.createStatusId, '', 'success');
            if (form) {
                form.reset();
            }

            const modalElement = document.getElementById(config.createModalId);
            if (modalElement && typeof bootstrap !== 'undefined') {
                const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                modalInstance.hide();
            }

            config.state.currentPage = 1;
            await loadWorkspaceCollection(config);
        } catch (error) {
            setAlertMessage(config.createStatusId, error.message, 'danger');
        }
    }

    function renderDiscoverMessage(config, message, isError) {
        const tableBody = document.getElementById(config.discoverTbodyId);
        if (!tableBody) {
            return;
        }

        renderTableMessageRow(tableBody, config.type === 'groups' ? 5 : 3, message, isError);
    }

    function createRequestAccessButton(config, workspaceId) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-primary';
        button.dataset.workspaceAction = 'request-access';
        button.dataset.workspaceType = config.type;
        button.dataset.workspaceId = workspaceId;
        appendIconText(button, 'bi bi-person-plus', config.requestLabel);
        return button;
    }

    function renderDiscoverRows(config, items) {
        const tableBody = document.getElementById(config.discoverTbodyId);
        if (!tableBody) {
            return;
        }

        clearElement(tableBody);
        if (!items.length) {
            renderDiscoverMessage(config, config.discoverEmptyMessage, false);
            return;
        }

        items.forEach(function (item) {
            const workspaceId = getWorkspaceId(item);
            const row = document.createElement('tr');
            row.appendChild(createTextCell(getWorkspaceName(item, config.itemLabel), 'profile-workspace-name-cell', getWorkspaceName(item, config.itemLabel)));
            row.appendChild(createTextCell(item.description || '', 'profile-workspace-description', item.description || ''));

            if (config.type === 'groups') {
                row.appendChild(createTextCell(getOwnerLabel(item.owner)));
                row.appendChild(createTextCell(item.member_count == null ? '0' : String(item.member_count)));
            }

            const actionCell = document.createElement('td');
            if (workspaceId) {
                actionCell.appendChild(createRequestAccessButton(config, workspaceId));
            } else {
                actionCell.textContent = '-';
            }
            row.appendChild(actionCell);
            tableBody.appendChild(row);
        });
    }

    async function searchDiscoverWorkspaces(config) {
        const searchInput = document.getElementById(config.discoverSearchId);
        const searchValue = searchInput ? searchInput.value.trim() : '';
        const params = new URLSearchParams();
        if (searchValue) {
            params.set('search', searchValue);
        }

        renderDiscoverMessage(config, `Searching ${config.label}...`, false);
        setAlertMessage(config.discoverStatusId, '', 'info');

        try {
            const items = await fetchJson(`${config.discoverEndpoint}?${params.toString()}`);
            renderDiscoverRows(config, Array.isArray(items) ? items : []);
        } catch (error) {
            renderDiscoverMessage(config, `Error searching ${config.label}: ${error.message}`, true);
        }
    }

    async function requestWorkspaceAccess(config, workspaceId, triggerButton) {
        if (!workspaceId) {
            return;
        }

        if (triggerButton) {
            triggerButton.disabled = true;
        }
        setAlertMessage(config.discoverStatusId, 'Sending request...', 'info');

        try {
            await fetchJson(config.requestEndpoint(workspaceId), {
                method: 'POST',
            });
            setAlertMessage(config.discoverStatusId, 'Request sent.', 'success');
            if (triggerButton) {
                triggerButton.textContent = 'Requested';
                triggerButton.className = 'btn btn-sm btn-outline-secondary';
            }
        } catch (error) {
            setAlertMessage(config.discoverStatusId, error.message, 'danger');
            if (triggerButton) {
                triggerButton.disabled = false;
            }
        }
    }

    function attachWorkspaceCollectionListeners(config) {
        const tableBody = document.querySelector(config.tableSelector);
        const cardContainer = document.getElementById(config.cardViewId);
        const pageSizeSelect = document.getElementById(config.pageSizeSelectId);
        const searchInput = document.getElementById(config.searchInputId);
        const searchButton = document.getElementById(config.searchButtonId);
        const clearSearchButton = document.getElementById(config.clearSearchButtonId);
        const listRadio = document.getElementById(config.viewListId);
        const cardsRadio = document.getElementById(config.viewCardsId);
        const createForm = document.getElementById(config.createFormId);
        const discoverSearchButton = document.getElementById(config.discoverSearchButtonId);
        const discoverSearchInput = document.getElementById(config.discoverSearchId);
        const discoverTableBody = document.getElementById(config.discoverTbodyId);

        initializeWorkspaceViewMode(config);

        function handleWorkspaceActionClick(event) {
            const target = event.target.closest('button[data-workspace-action]');
            if (!target || target.dataset.workspaceType !== config.type) {
                return;
            }

            if (target.dataset.workspaceAction === 'activate') {
                setActiveWorkspace(config, target.dataset.workspaceId || '').catch(function (error) {
                    renderTableMessageRow(document.querySelector(config.tableSelector), 5, error.message, true);
                    renderWorkspaceCardMessage(config, error.message, true);
                });
            }
        }

        if (tableBody) {
            tableBody.addEventListener('click', handleWorkspaceActionClick);
        }
        if (cardContainer) {
            cardContainer.addEventListener('click', handleWorkspaceActionClick);
            cardContainer.addEventListener('click', function (event) {
                const interactiveTarget = event.target.closest('a, button, input, select, textarea, label');
                if (interactiveTarget) {
                    return;
                }

                const card = event.target.closest('.profile-workspace-card-clickable[data-manage-url]');
                if (card && card.dataset.manageUrl) {
                    window.location.assign(card.dataset.manageUrl);
                }
            });
            cardContainer.addEventListener('keydown', function (event) {
                if (event.key !== 'Enter' && event.key !== ' ') {
                    return;
                }

                const card = event.target.closest('.profile-workspace-card-clickable[data-manage-url]');
                if (card && event.target === card && card.dataset.manageUrl) {
                    event.preventDefault();
                    window.location.assign(card.dataset.manageUrl);
                }
            });
        }

        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', function () {
                config.state.pageSize = parseInt(pageSizeSelect.value, 10) || 10;
                config.state.currentPage = 1;
                loadWorkspaceCollection(config);
            });
        }

        if (searchButton) {
            searchButton.addEventListener('click', function () {
                config.state.search = searchInput ? searchInput.value.trim() : '';
                config.state.currentPage = 1;
                loadWorkspaceCollection(config);
            });
        }

        if (searchInput) {
            searchInput.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    config.state.search = searchInput.value.trim();
                    config.state.currentPage = 1;
                    loadWorkspaceCollection(config);
                }
            });
        }

        if (clearSearchButton) {
            clearSearchButton.addEventListener('click', function () {
                if (searchInput) {
                    searchInput.value = '';
                }
                config.state.search = '';
                config.state.currentPage = 1;
                loadWorkspaceCollection(config);
            });
        }

        if (listRadio) {
            listRadio.addEventListener('change', function () {
                if (listRadio.checked) {
                    setWorkspaceViewMode(config, 'list');
                }
            });
        }

        if (cardsRadio) {
            cardsRadio.addEventListener('change', function () {
                if (cardsRadio.checked) {
                    setWorkspaceViewMode(config, 'cards');
                }
            });
        }

        if (createForm) {
            createForm.addEventListener('submit', function (event) {
                event.preventDefault();
                createWorkspaceItem(config);
            });
        }

        if (discoverSearchButton) {
            discoverSearchButton.addEventListener('click', function () {
                searchDiscoverWorkspaces(config);
            });
        }

        if (discoverSearchInput) {
            discoverSearchInput.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    searchDiscoverWorkspaces(config);
                }
            });
        }

        if (discoverTableBody) {
            discoverTableBody.addEventListener('click', function (event) {
                const target = event.target.closest('button[data-workspace-action="request-access"]');
                if (!target || target.dataset.workspaceType !== config.type) {
                    return;
                }

                requestWorkspaceAccess(config, target.dataset.workspaceId || '', target);
            });
        }
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
            renderTableMessageRow(tbody, 6, 'No feedback found for the current filters.', false);
            return;
        }

        items.forEach(function (item) {
            const row = document.createElement('tr');
            const adminReview = item.adminReview || {};

            row.appendChild(createTextCell(formatDateTime(item.timestamp)));
            row.appendChild(createTextCell(item.prompt || '', 'table-message-cell', item.prompt || ''));
            row.appendChild(createTextCell(item.feedbackType || ''));
            row.appendChild(createTextCell(item.reason || '', 'table-note-cell', item.reason || ''));
            row.appendChild(createTextCell(adminReview.acknowledged ? 'Yes' : 'No'));

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

        renderTableMessageRow(tbody, 6, 'Loading feedback...', false);
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
            renderTableMessageRow(tbody, 6, `Error loading feedback: ${error.message}`, true);
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

            row.appendChild(createTextCell(logItem.id || '', 'table-note-cell', logItem.id || ''));
            row.appendChild(createTextCell(logItem.message || '', 'table-message-cell', logItem.message || ''));
            row.appendChild(createSafetyCategoryCell(logItem));
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

        setTextContent('profile-violation-detail-id', selectedItem.id || '');
        setTextContent('profile-violation-detail-message', selectedItem.message || '');
        appendSafetyCategoryBadges(document.getElementById('profile-violation-detail-categories'), selectedItem, '-');
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
                loadProfileTabData(tabName);
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
        }

        if (pageConfig.contentSafetyEnabled) {
            attachViolationListeners();
        }

        if (pageConfig.groupWorkspacesEnabled) {
            attachWorkspaceCollectionListeners(workspaceTabConfigs.groups);
        }

        if (pageConfig.publicWorkspacesEnabled) {
            attachWorkspaceCollectionListeners(workspaceTabConfigs.publicWorkspaces);
        }

        const startupTabName = activateRequestedProfileTab();
        if (startupTabName) {
            loadProfileTabData(startupTabName);
        }
    });
})();