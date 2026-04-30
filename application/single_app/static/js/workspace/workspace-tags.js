// static/js/workspace/workspace-tags.js
// Handles tag management for workspace documents

import { escapeHtml } from "./workspace-utils.js";
import { showTagManagementModal } from "./workspace-tag-management.js";

// ============= State Variables =============
let workspaceTags = []; // All available workspace tags with colors
let currentView = 'list'; // 'list' or 'grid'
let selectedTagFilter = [];
let currentFolder = null;    // null = folder overview, string = tag name being viewed
let currentFolderType = null; // null | 'tag' | 'classification'
let folderCurrentPage = 1;
let folderPageSize = 10;
let gridSortBy = 'count';    // 'count' or 'name'
let gridSortOrder = 'desc';  // 'asc' or 'desc'
let folderSortBy = '_ts';    // Sort field for folder drill-down
let folderSortOrder = 'desc'; // Sort order for folder drill-down
let folderSearchTerm = '';    // Search term for folder drill-down

// ============= Initialization =============

export function initializeTags() {
    // Load workspace tags
    loadWorkspaceTags();
    
    // Setup view switcher
    setupViewSwitcher();
    
    // Setup tag filter
    setupTagFilter();
    
    // Setup bulk tag management
    setupBulkTagManagement();

    // Wire static grid sort buttons
    document.querySelectorAll('#grid-controls-bar .grid-sort-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const field = btn.getAttribute('data-sort');
            if (gridSortBy === field) {
                gridSortOrder = gridSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                gridSortBy = field;
                gridSortOrder = field === 'name' ? 'asc' : 'desc';
            }
            renderGridView();
        });
    });

    // Wire grid page-size select
    const gridPageSizeSelect = document.getElementById('grid-page-size-select');
    if (gridPageSizeSelect) {
        gridPageSizeSelect.addEventListener('change', (e) => {
            folderPageSize = parseInt(e.target.value, 10);
            folderCurrentPage = 1;
            if (currentFolder) {
                renderFolderContents(currentFolder);
            }
        });
    }
    
    // Load saved view preference
    const savedView = localStorage.getItem('personalWorkspaceViewPreference');
    if (savedView === 'grid') {
        document.getElementById('docs-view-grid').checked = true;
        switchView('grid');
    }
}

// ============= Load Workspace Tags =============

// Expose for cross-module refresh (avoids circular imports)
window.refreshWorkspaceTags = () => loadWorkspaceTags();

export async function loadWorkspaceTags() {
    try {
        const response = await fetch('/api/documents/tags');
        const data = await response.json();
        
        if (response.ok && data.tags) {
            workspaceTags = data.tags;
            updateTagFilterOptions();
            updateDocTagsSelect();
            updateBulkTagSelect();
            
            // Update grid view if visible
            if (currentView === 'grid') {
                renderGridView();
            }
        } else {
            console.error('Failed to load workspace tags:', data.error);
        }
    } catch (error) {
        console.error('Error loading workspace tags:', error);
    }
}

// ============= View Switcher =============

function setupViewSwitcher() {
    const listRadio = document.getElementById('docs-view-list');
    const gridRadio = document.getElementById('docs-view-grid');
    
    if (listRadio) {
        listRadio.addEventListener('change', () => {
            if (listRadio.checked) {
                switchView('list');
            }
        });
    }
    
    if (gridRadio) {
        gridRadio.addEventListener('change', () => {
            if (gridRadio.checked) {
                switchView('grid');
            }
        });
    }
}

function switchView(view) {
    currentView = view;
    localStorage.setItem('personalWorkspaceViewPreference', view);

    const listView = document.getElementById('documents-list-view');
    const gridView = document.getElementById('documents-grid-view');
    const viewInfo = document.getElementById('docs-view-info');
    const listControls = document.getElementById('list-controls-bar');
    const gridControls = document.getElementById('grid-controls-bar');

    const filterBtn = document.getElementById('docs-filters-toggle-btn');
    const filterCollapse = document.getElementById('docs-filters-collapse');

    if (view === 'list') {
        // Reset folder drill-down state
        currentFolder = null;
        currentFolderType = null;
        folderCurrentPage = 1;
        folderSortBy = '_ts';
        folderSortOrder = 'desc';
        folderSearchTerm = '';
        const tagContainer = document.getElementById('tag-folders-container');
        if (tagContainer) tagContainer.className = 'row g-2';

        listView.style.display = 'block';
        gridView.style.display = 'none';
        if (listControls) listControls.style.display = 'flex';
        if (gridControls) gridControls.style.display = 'none';
        if (filterBtn) filterBtn.style.display = '';
        if (viewInfo) viewInfo.textContent = '';
        // Trigger reload of documents if needed
        window.fetchUserDocuments?.();
    } else {
        listView.style.display = 'none';
        gridView.style.display = 'block';
        if (listControls) listControls.style.display = 'none';
        if (gridControls) gridControls.style.display = 'flex';
        // Hide list view filters in grid folder overview
        if (filterBtn) filterBtn.style.display = 'none';
        if (filterCollapse) {
            const bsCollapse = bootstrap.Collapse.getInstance(filterCollapse);
            if (bsCollapse) bsCollapse.hide();
        }
        renderGridView();
    }
}


export function setWorkspaceView(view) {
    const normalizedView = view === 'grid' ? 'grid' : 'list';
    const listRadio = document.getElementById('docs-view-list');
    const gridRadio = document.getElementById('docs-view-grid');

    if (normalizedView === 'grid') {
        if (gridRadio) {
            gridRadio.checked = true;
        }
        if (listRadio) {
            listRadio.checked = false;
        }
    } else {
        if (listRadio) {
            listRadio.checked = true;
        }
        if (gridRadio) {
            gridRadio.checked = false;
        }
    }

    switchView(normalizedView);
}

// Update sort icons in the static grid control bar
function updateGridSortIcons() {
    const bar = document.getElementById('grid-controls-bar');
    if (!bar) return;
    bar.querySelectorAll('.grid-sort-icon').forEach(icon => {
        const field = icon.getAttribute('data-sort');
        icon.className = 'bi ms-1 grid-sort-icon';
        icon.setAttribute('data-sort', field);
        if (gridSortBy === field) {
            if (field === 'name') {
                icon.classList.add(gridSortOrder === 'asc' ? 'bi-sort-alpha-down' : 'bi-sort-alpha-up');
            } else {
                icon.classList.add(gridSortOrder === 'asc' ? 'bi-sort-numeric-down' : 'bi-sort-numeric-up');
            }
        } else {
            icon.classList.add('bi-arrow-down-up', 'text-muted');
        }
    });
}

// ============= Grid View Rendering =============

async function renderGridView() {
    const container = document.getElementById('tag-folders-container');
    if (!container) return;

    // If inside a folder, check that the folder still exists
    if (currentFolder && currentFolder !== '__untagged__' && currentFolder !== '__unclassified__') {
        if (currentFolderType === 'classification') {
            const categories = window.classification_categories || [];
            const folderStillExists = categories.some(cat => cat.label === currentFolder);
            if (!folderStillExists) {
                currentFolder = null;
                currentFolderType = null;
                folderCurrentPage = 1;
            }
        } else {
            const folderStillExists = workspaceTags.some(t => t.name === currentFolder);
            if (!folderStillExists) {
                currentFolder = null;
                currentFolderType = null;
                folderCurrentPage = 1;
            }
        }
    }

    // If inside a folder, render folder contents instead
    if (currentFolder) {
        renderFolderContents(currentFolder);
        return;
    }

    // Clear view info
    const viewInfo = document.getElementById('docs-view-info');
    if (viewInfo) viewInfo.textContent = '';

    // Ensure container has grid layout
    container.className = 'row g-2';

    // Show loading
    container.innerHTML = `
        <div class="col-12 text-center text-muted py-5">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            Loading tag folders...
        </div>
    `;

    // Get all documents to count untagged
    try {
        const docsResponse = await fetch('/api/documents?page_size=1000');
        const docsData = await docsResponse.json();
        const allDocs = docsData.documents || [];

        const untaggedCount = allDocs.filter(doc => !doc.tags || doc.tags.length === 0).length;

        // Classification folder data
        const classificationEnabled = (window.enable_document_classification === true
            || window.enable_document_classification === "true");
        const categories = classificationEnabled ? (window.classification_categories || []) : [];
        const classificationCounts = {};
        let unclassifiedCount = 0;
        if (classificationEnabled) {
            allDocs.forEach(doc => {
                const cls = doc.document_classification;
                if (!cls || cls === '' || cls.toLowerCase() === 'none') {
                    unclassifiedCount++;
                } else {
                    classificationCounts[cls] = (classificationCounts[cls] || 0) + 1;
                }
            });
        }

        // Build unified array of folder items
        const folderItems = [];

        if (untaggedCount > 0) {
            folderItems.push({
                type: 'tag', key: '__untagged__', displayName: 'Untagged',
                count: untaggedCount, icon: 'bi-folder2-open', color: '#6c757d', isSpecial: true
            });
        }

        if (classificationEnabled && unclassifiedCount > 0) {
            folderItems.push({
                type: 'classification', key: '__unclassified__', displayName: 'Unclassified',
                count: unclassifiedCount, icon: 'bi-bookmark', color: '#6c757d', isSpecial: true
            });
        }

        workspaceTags.forEach(tag => {
            folderItems.push({
                type: 'tag', key: tag.name, displayName: tag.name,
                count: tag.count, icon: 'bi-folder-fill', color: tag.color,
                isSpecial: false, tagData: tag
            });
        });

        if (classificationEnabled) {
            categories.forEach(cat => {
                const count = classificationCounts[cat.label] || 0;
                if (count > 0) {
                    folderItems.push({
                        type: 'classification', key: cat.label, displayName: cat.label,
                        count: count, icon: 'bi-bookmark-fill', color: cat.color || '#6c757d',
                        isSpecial: false
                    });
                }
            });
        }

        // Sort: special folders first, then by user-selected sort
        folderItems.sort((a, b) => {
            if (a.isSpecial && !b.isSpecial) return -1;
            if (!a.isSpecial && b.isSpecial) return 1;
            if (gridSortBy === 'name') {
                const cmp = a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' });
                return gridSortOrder === 'asc' ? cmp : -cmp;
            }
            // Default: sort by count
            const cmp = a.count - b.count;
            return gridSortOrder === 'asc' ? cmp : -cmp;
        });

        // Update sort icons in the static control bar
        updateGridSortIcons();

        let html = '';

        // Render folder cards
        folderItems.forEach(item => {
            const escapedKey = escapeHtml(item.key);
            const escapedName = escapeHtml(item.displayName);
            const countLabel = `${item.count} file${item.count !== 1 ? 's' : ''}`;

            let actionsHtml = '';
            if (item.type === 'tag' && !item.isSpecial) {
                actionsHtml = `
                    <div class="tag-folder-actions">
                        <div class="dropdown">
                            <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu">
                                <li><a class="dropdown-item" href="#" onclick="window.chatWithFolder('tag', '${escapedKey}'); return false;">
                                    <i class="bi bi-chat-dots me-2"></i>Chat
                                </a></li>
                                <li><a class="dropdown-item" href="#" onclick="window.renameTag('${escapedKey}'); return false;">
                                    <i class="bi bi-pencil me-2"></i>Rename Tag
                                </a></li>
                                <li><a class="dropdown-item" href="#" onclick="window.changeTagColor('${escapedKey}', '${item.tagData.color}'); return false;">
                                    <i class="bi bi-palette me-2"></i>Change Color
                                </a></li>
                                <li><hr class="dropdown-divider"></li>
                                <li><a class="dropdown-item text-danger" href="#" onclick="window.deleteTag('${escapedKey}'); return false;">
                                    <i class="bi bi-trash me-2"></i>Delete Tag
                                </a></li>
                            </ul>
                        </div>
                    </div>`;
            } else if (item.type === 'classification') {
                actionsHtml = `
                    <div class="tag-folder-actions">
                        <div class="dropdown">
                            <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu">
                                <li><a class="dropdown-item" href="#" onclick="window.chatWithFolder('classification', '${escapedKey}'); return false;">
                                    <i class="bi bi-chat-dots me-2"></i>Chat
                                </a></li>
                            </ul>
                        </div>
                    </div>`;
            } else if (item.type === 'tag' && item.isSpecial) {
                actionsHtml = `
                    <div class="tag-folder-actions">
                        <div class="dropdown">
                            <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu">
                                <li><a class="dropdown-item" href="#" onclick="window.chatWithFolder('tag', '${escapedKey}'); return false;">
                                    <i class="bi bi-chat-dots me-2"></i>Chat
                                </a></li>
                            </ul>
                        </div>
                    </div>`;
            }

            html += `
                <div class="col-6 col-sm-4 col-md-3 col-lg-2">
                    <div class="tag-folder-card" data-tag="${escapedKey}" data-folder-type="${item.type}" title="${escapedName} (${countLabel})">
                        ${actionsHtml}
                        <div class="tag-folder-icon"><i class="bi ${item.icon}" style="color: ${item.color};"></i></div>
                        <div class="tag-folder-name${item.isSpecial ? ' text-muted' : ''}">${escapedName}</div>
                        <div class="tag-folder-count">${countLabel}</div>
                    </div>
                </div>
            `;
        });

        if (folderItems.length === 0) {
            html = `
                <div class="col-12 text-center text-muted py-5">
                    <i class="bi bi-folder2-open display-1 mb-3"></i>
                    <p>No folders yet. Add tags to documents to organize them into folders.</p>
                </div>
            `;
        }

        container.innerHTML = html;

        // Add click handlers to folder cards
        container.querySelectorAll('.tag-folder-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.closest('.tag-folder-actions')) return;
                const tagName = card.getAttribute('data-tag');
                const folderType = card.getAttribute('data-folder-type') || 'tag';
                currentFolder = tagName;
                currentFolderType = folderType;
                folderCurrentPage = 1;
                folderSortBy = '_ts';
                folderSortOrder = 'desc';
                folderSearchTerm = '';
                renderFolderContents(tagName);
            });
        });

    } catch (error) {
        console.error('Error rendering grid view:', error);
        container.innerHTML = `
            <div class="col-12 text-center text-danger py-5">
                <i class="bi bi-exclamation-triangle display-4 mb-2"></i>
                <p>Error loading tag folders</p>
            </div>
        `;
    }
}

// ============= Folder Drill-Down =============

function buildBreadcrumbHtml(displayName, tagColor, folderType = 'tag') {
    const icon = (folderType === 'classification') ? 'bi-bookmark-fill' : 'bi-folder-fill';
    return `
        <div class="folder-breadcrumb d-flex align-items-center">
            <a href="#" class="grid-back-btn d-flex align-items-center">
                <i class="bi bi-arrow-left me-1"></i> All
            </a>
            <span class="mx-2 text-muted">/</span>
            <span>
                <i class="bi ${icon} me-1" style="color: ${tagColor};"></i>
                <strong>${escapeHtml(displayName)}</strong>
            </span>
        </div>`;
}

function wireBackButton(container) {
    container.querySelectorAll('.grid-back-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            currentFolder = null;
            currentFolderType = null;
            folderCurrentPage = 1;
            folderSortBy = '_ts';
            folderSortOrder = 'desc';
            folderSearchTerm = '';
            container.className = 'row g-2';
            // Show the grid controls bar again
            const gridControls = document.getElementById('grid-controls-bar');
            if (gridControls) gridControls.style.display = 'flex';
            renderGridView();
        });
    });
}

function buildFolderDocumentsTable(docs) {
    const fnIcon = folderSortBy === 'file_name'
        ? (folderSortOrder === 'asc' ? 'bi-sort-alpha-down' : 'bi-sort-alpha-up')
        : 'bi-arrow-down-up text-muted';
    const titleIcon = folderSortBy === 'title'
        ? (folderSortOrder === 'asc' ? 'bi-sort-alpha-down' : 'bi-sort-alpha-up')
        : 'bi-arrow-down-up text-muted';

    let html = `
        <table class="table table-striped table-sm" id="folder-docs-table">
            <thead>
                <tr>
                    <th style="width: 50px;"></th>
                    <th class="folder-sortable-header" data-sort-field="file_name" style="cursor: pointer; user-select: none;">
                        File Name <i class="bi ${fnIcon} small sort-icon"></i>
                    </th>
                    <th class="folder-sortable-header" data-sort-field="title" style="cursor: pointer; user-select: none;">
                        Title <i class="bi ${titleIcon} small sort-icon"></i>
                    </th>
                    <th style="width: 240px;">Actions</th>
                </tr>
            </thead>
            <tbody>`;

    docs.forEach(doc => {
        const docId = doc.id;
        const pctStr = String(doc.percentage_complete);
        const pct = /^\d+(\.\d+)?$/.test(pctStr) ? parseFloat(pctStr) : 0;
        const docStatus = doc.status || '';
        const isComplete = pct >= 100
            || docStatus.toLowerCase().includes('complete')
            || docStatus.toLowerCase().includes('error');
        const hasError = docStatus.toLowerCase().includes('error');

        const currentUserId = window.current_user_id;
        const isOwner = doc.user_id === currentUserId;

        // First column: expand/collapse or status indicator
        let firstColHtml = '';
        if (isComplete && !hasError) {
            firstColHtml = `
                <button class="btn btn-link p-0" onclick="window.onEditDocument('${docId}')" title="View Metadata">
                    <span class="bi bi-chevron-right"></span>
                </button>`;
        } else if (hasError) {
            firstColHtml = `<span class="text-danger" title="Processing Error: ${escapeHtml(docStatus)}"><i class="bi bi-exclamation-triangle-fill"></i></span>`;
        } else {
            firstColHtml = `<span class="text-muted" title="Processing: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)"><i class="bi bi-hourglass-split"></i></span>`;
        }

        // Chat button
        let chatButton = '';
        if (isComplete && !hasError) {
            chatButton = `
                <button class="btn btn-sm btn-primary me-1 action-btn-wide text-start"
                    onclick="window.redirectToChat('${docId}')"
                    title="Open Chat for Document"
                    aria-label="Open Chat for Document: ${escapeHtml(doc.file_name || 'Untitled')}"
                >
                    <i class="bi bi-chat-dots-fill me-1" aria-hidden="true"></i>
                    Chat
                </button>`;
        }

        // Ellipsis dropdown menu
        let actionsDropdown = '';
        if (isComplete && !hasError) {
            actionsDropdown = `
                <div class="dropdown action-dropdown d-inline-block">
                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" onclick="window.onEditDocument('${docId}'); return false;">
                            <i class="bi bi-pencil-fill me-2"></i>Edit Metadata
                        </a></li>`;

            if (window.enable_extract_meta_data === true || window.enable_extract_meta_data === "true") {
                actionsDropdown += `
                        <li><a class="dropdown-item" href="#" onclick="window.onExtractMetadata('${docId}', event); return false;">
                            <i class="bi bi-magic me-2"></i>Extract Metadata
                        </a></li>`;
            }

            actionsDropdown += `
                        <li><a class="dropdown-item" href="#" onclick="window.redirectToChat('${docId}'); return false;">
                            <i class="bi bi-chat-dots-fill me-2"></i>Chat
                        </a></li>`;

            if (isOwner) {
                if (window.enable_file_sharing === true || window.enable_file_sharing === "true") {
                    const shareCount = doc.shared_user_ids && doc.shared_user_ids.length > 0 ? doc.shared_user_ids.length : 0;
                    actionsDropdown += `
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" href="#" onclick="window.shareDocument('${docId}', '${escapeHtml(doc.file_name || '')}'); return false;">
                            <i class="bi bi-share-fill me-2"></i>Share
                            <span class="badge bg-secondary ms-1">${shareCount}</span>
                        </a></li>`;
                }

                actionsDropdown += `
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item text-danger" href="#" onclick="window.deleteDocument('${docId}', event); return false;">
                            <i class="bi bi-trash-fill me-2"></i>Delete
                        </a></li>`;
            }

            actionsDropdown += `
                    </ul>
                </div>`;
        } else if (isOwner) {
            actionsDropdown = `
                <div class="dropdown action-dropdown d-inline-block">
                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item text-danger" href="#" onclick="window.deleteDocument('${docId}', event); return false;">
                            <i class="bi bi-trash-fill me-2"></i>Delete
                        </a></li>
                    </ul>
                </div>`;
        }

        html += `
            <tr>
                <td class="align-middle">${firstColHtml}</td>
                <td class="align-middle" title="${escapeHtml(doc.file_name || '')}">${escapeHtml(doc.file_name || '')}</td>
                <td class="align-middle" title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || 'N/A')}</td>
                <td class="align-middle">${chatButton}${actionsDropdown}</td>
            </tr>`;
    });

    html += '</tbody></table>';
    return html;
}

function renderFolderPagination(page, pageSize, totalCount) {
    const paginationContainer = document.getElementById('folder-pagination');
    if (!paginationContainer) return;
    paginationContainer.innerHTML = '';

    const totalPages = Math.ceil(totalCount / pageSize);
    if (totalPages <= 1) return;

    const ul = document.createElement('ul');
    ul.classList.add('pagination', 'pagination-sm', 'mb-0');

    // Previous button
    const prevLi = document.createElement('li');
    prevLi.classList.add('page-item');
    if (page <= 1) prevLi.classList.add('disabled');
    const prevA = document.createElement('a');
    prevA.classList.add('page-link');
    prevA.href = '#';
    prevA.innerHTML = '&laquo;';
    prevA.addEventListener('click', (e) => {
        e.preventDefault();
        if (folderCurrentPage > 1) {
            folderCurrentPage -= 1;
            renderFolderContents(currentFolder);
        }
    });
    prevLi.appendChild(prevA);
    ul.appendChild(prevLi);

    // Page numbers
    const maxPages = 5;
    let startPage = 1;
    let endPage = totalPages;
    if (totalPages > maxPages) {
        const before = Math.floor(maxPages / 2);
        const after = Math.ceil(maxPages / 2) - 1;
        if (page <= before) { startPage = 1; endPage = maxPages; }
        else if (page + after >= totalPages) { startPage = totalPages - maxPages + 1; endPage = totalPages; }
        else { startPage = page - before; endPage = page + after; }
    }

    if (startPage > 1) {
        const firstLi = document.createElement('li'); firstLi.classList.add('page-item');
        const firstA = document.createElement('a'); firstA.classList.add('page-link'); firstA.href = '#'; firstA.textContent = '1';
        firstA.addEventListener('click', (e) => { e.preventDefault(); folderCurrentPage = 1; renderFolderContents(currentFolder); });
        firstLi.appendChild(firstA); ul.appendChild(firstLi);
        if (startPage > 2) {
            const ellipsis = document.createElement('li'); ellipsis.classList.add('page-item', 'disabled');
            ellipsis.innerHTML = '<span class="page-link">...</span>'; ul.appendChild(ellipsis);
        }
    }

    for (let p = startPage; p <= endPage; p++) {
        const li = document.createElement('li'); li.classList.add('page-item');
        if (p === page) { li.classList.add('active'); li.setAttribute('aria-current', 'page'); }
        const a = document.createElement('a'); a.classList.add('page-link'); a.href = '#'; a.textContent = p;
        a.addEventListener('click', ((pageNum) => (e) => {
            e.preventDefault();
            if (folderCurrentPage !== pageNum) {
                folderCurrentPage = pageNum;
                renderFolderContents(currentFolder);
            }
        })(p));
        li.appendChild(a); ul.appendChild(li);
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            const ellipsis = document.createElement('li'); ellipsis.classList.add('page-item', 'disabled');
            ellipsis.innerHTML = '<span class="page-link">...</span>'; ul.appendChild(ellipsis);
        }
        const lastLi = document.createElement('li'); lastLi.classList.add('page-item');
        const lastA = document.createElement('a'); lastA.classList.add('page-link'); lastA.href = '#'; lastA.textContent = totalPages;
        lastA.addEventListener('click', (e) => { e.preventDefault(); folderCurrentPage = totalPages; renderFolderContents(currentFolder); });
        lastLi.appendChild(lastA); ul.appendChild(lastLi);
    }

    // Next button
    const nextLi = document.createElement('li');
    nextLi.classList.add('page-item');
    if (page >= totalPages) nextLi.classList.add('disabled');
    const nextA = document.createElement('a');
    nextA.classList.add('page-link');
    nextA.href = '#';
    nextA.innerHTML = '&raquo;';
    nextA.addEventListener('click', (e) => {
        e.preventDefault();
        if (folderCurrentPage < totalPages) {
            folderCurrentPage += 1;
            renderFolderContents(currentFolder);
        }
    });
    nextLi.appendChild(nextA);
    ul.appendChild(nextLi);

    paginationContainer.appendChild(ul);
}

async function renderFolderContents(tagName) {
    const container = document.getElementById('tag-folders-container');
    if (!container) return;

    // Hide the grid controls bar (folder sort buttons don't apply inside a folder)
    const gridControls = document.getElementById('grid-controls-bar');
    if (gridControls) gridControls.style.display = 'none';

    // Switch container from grid layout to single-column
    container.className = '';

    // Determine display values based on folder type
    const isClassification = (currentFolderType === 'classification');
    let displayName, tagColor;

    if (tagName === '__untagged__') {
        displayName = 'Untagged Documents';
        tagColor = '#6c757d';
    } else if (tagName === '__unclassified__') {
        displayName = 'Unclassified Documents';
        tagColor = '#6c757d';
    } else if (isClassification) {
        const categories = window.classification_categories || [];
        const cat = categories.find(c => c.label === tagName);
        displayName = tagName;
        tagColor = cat?.color || '#6c757d';
    } else {
        const tagInfo = workspaceTags.find(t => t.name === tagName);
        displayName = tagName;
        tagColor = tagInfo?.color || '#6c757d';
    }

    // Update view info
    const viewInfo = document.getElementById('docs-view-info');
    if (viewInfo) viewInfo.textContent = `Viewing: ${displayName}`;

    // Show breadcrumb + loading spinner
    container.innerHTML = buildBreadcrumbHtml(displayName, tagColor, currentFolderType || 'tag') +
        `<div class="text-center text-muted py-4">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            Loading documents...
        </div>`;
    wireBackButton(container);

    try {
        let docs, totalCount;

        if (tagName === '__untagged__') {
            // Fetch all and filter client-side for untagged
            const untaggedParams = new URLSearchParams({ page_size: 1000 });
            if (folderSearchTerm) untaggedParams.append('search', folderSearchTerm);
            const allResponse = await fetch(`/api/documents?${untaggedParams.toString()}`);
            const allData = await allResponse.json();
            const allUntagged = (allData.documents || []).filter(
                doc => !doc.tags || doc.tags.length === 0
            );
            // Client-side sorting for untagged
            if (folderSortBy !== '_ts') {
                allUntagged.sort((a, b) => {
                    const valA = (a[folderSortBy] || '').toLowerCase();
                    const valB = (b[folderSortBy] || '').toLowerCase();
                    const cmp = valA.localeCompare(valB);
                    return folderSortOrder === 'asc' ? cmp : -cmp;
                });
            }
            totalCount = allUntagged.length;
            const start = (folderCurrentPage - 1) * folderPageSize;
            docs = allUntagged.slice(start, start + folderPageSize);
        } else if (tagName === '__unclassified__') {
            // Server-side filter for unclassified documents
            const params = new URLSearchParams({
                page: folderCurrentPage,
                page_size: folderPageSize,
                classification: 'none'
            });
            if (folderSearchTerm) params.append('search', folderSearchTerm);
            if (folderSortBy !== '_ts') params.append('sort_by', folderSortBy);
            if (folderSortOrder !== 'desc') params.append('sort_order', folderSortOrder);
            const response = await fetch(`/api/documents?${params.toString()}`);
            const data = await response.json();
            docs = data.documents || [];
            totalCount = data.total_count || docs.length;
        } else if (isClassification) {
            // Server-side filter for a specific classification category
            const params = new URLSearchParams({
                page: folderCurrentPage,
                page_size: folderPageSize,
                classification: tagName
            });
            if (folderSearchTerm) params.append('search', folderSearchTerm);
            if (folderSortBy !== '_ts') params.append('sort_by', folderSortBy);
            if (folderSortOrder !== 'desc') params.append('sort_order', folderSortOrder);
            const response = await fetch(`/api/documents?${params.toString()}`);
            const data = await response.json();
            docs = data.documents || [];
            totalCount = data.total_count || docs.length;
        } else {
            // Use server-side tag filtering with pagination
            const params = new URLSearchParams({
                page: folderCurrentPage,
                page_size: folderPageSize,
                tags: tagName
            });
            if (folderSearchTerm) params.append('search', folderSearchTerm);
            if (folderSortBy !== '_ts') params.append('sort_by', folderSortBy);
            if (folderSortOrder !== 'desc') params.append('sort_order', folderSortOrder);
            const response = await fetch(`/api/documents?${params.toString()}`);
            const data = await response.json();
            docs = data.documents || [];
            totalCount = data.total_count || docs.length;
        }

        // Client-side sort to ensure correct order (fallback if server-side ORDER BY is ignored)
        if (folderSortBy !== '_ts' && docs.length > 1) {
            docs.sort((a, b) => {
                const valA = (a[folderSortBy] || '').toLowerCase();
                const valB = (b[folderSortBy] || '').toLowerCase();
                const cmp = valA.localeCompare(valB);
                return folderSortOrder === 'asc' ? cmp : -cmp;
            });
        }

        // Build the full view
        let html = buildBreadcrumbHtml(displayName, tagColor, currentFolderType || 'tag');
        // Inline search bar for folder drill-down
        html += `<div class="d-flex align-items-center gap-2 mb-2">
            <div class="input-group input-group-sm" style="max-width: 320px;">
                <input type="search" id="folder-search-input" class="form-control form-control-sm" 
                       placeholder="Search file name or title..." value="${escapeHtml(folderSearchTerm)}">
                <button class="btn btn-outline-secondary" type="button" id="folder-search-btn">
                    <i class="bi bi-search"></i>
                </button>
            </div>
            <span class="text-muted small">${totalCount} document(s)</span>
            <div class="ms-auto">
                <select id="folder-page-size-select" class="form-select form-select-sm d-inline-block" style="width:auto;">
                    <option value="10"${folderPageSize === 10 ? ' selected' : ''}>10</option>
                    <option value="20"${folderPageSize === 20 ? ' selected' : ''}>20</option>
                    <option value="50"${folderPageSize === 50 ? ' selected' : ''}>50</option>
                </select>
                <span class="ms-1 small text-muted">items per page</span>
            </div>
        </div>`;

        if (docs.length === 0) {
            html += `
                <div class="text-center text-muted py-4">
                    <i class="bi bi-folder2-open display-4 d-block mb-2"></i>
                    <p>No documents found in this folder.</p>
                </div>`;
        } else {
            html += buildFolderDocumentsTable(docs);
            html += '<div id="folder-pagination" class="d-flex justify-content-center mt-3"></div>';
        }

        container.innerHTML = html;
        wireBackButton(container);

        // Wire up folder page-size select
        const folderPageSizeSelect = document.getElementById('folder-page-size-select');
        if (folderPageSizeSelect) {
            folderPageSizeSelect.addEventListener('change', (e) => {
                folderPageSize = parseInt(e.target.value, 10);
                folderCurrentPage = 1;
                renderFolderContents(currentFolder);
            });
        }

        // Wire up folder search
        const folderSearchInput = document.getElementById('folder-search-input');
        const folderSearchBtn = document.getElementById('folder-search-btn');
        if (folderSearchInput) {
            const doSearch = () => {
                folderSearchTerm = folderSearchInput.value.trim();
                folderCurrentPage = 1;
                renderFolderContents(currentFolder);
            };
            folderSearchBtn?.addEventListener('click', doSearch);
            folderSearchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); doSearch(); }
            });
            // Clear search on the 'x' button in type=search
            folderSearchInput.addEventListener('search', doSearch);
        }

        // Wire up sortable column headers in folder drill-down table
        container.querySelectorAll('.folder-sortable-header').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.getAttribute('data-sort-field');
                if (folderSortBy === field) {
                    folderSortOrder = folderSortOrder === 'asc' ? 'desc' : 'asc';
                } else {
                    folderSortBy = field;
                    folderSortOrder = 'asc';
                }
                folderCurrentPage = 1;
                renderFolderContents(currentFolder);
            });
        });

        if (docs.length > 0) {
            renderFolderPagination(folderCurrentPage, folderPageSize, totalCount);
        }
    } catch (error) {
        console.error('Error loading folder contents:', error);
        container.innerHTML = buildBreadcrumbHtml(displayName, tagColor, currentFolderType || 'tag') +
            `<div class="text-center text-danger py-4">
                <i class="bi bi-exclamation-triangle display-4 d-block mb-2"></i>
                <p>Error loading documents.</p>
            </div>`;
        wireBackButton(container);
    }
}

// ============= Color Utility =============

function isColorLight(hexColor) {
    if (!hexColor) return true;
    const cleanHex = hexColor.startsWith('#') ? hexColor.substring(1) : hexColor;
    if (cleanHex.length < 3) return true;

    let r, g, b;
    try {
        if (cleanHex.length === 3) {
            r = parseInt(cleanHex[0] + cleanHex[0], 16);
            g = parseInt(cleanHex[1] + cleanHex[1], 16);
            b = parseInt(cleanHex[2] + cleanHex[2], 16);
        } else if (cleanHex.length >= 6) {
            r = parseInt(cleanHex.substring(0, 2), 16);
            g = parseInt(cleanHex.substring(2, 4), 16);
            b = parseInt(cleanHex.substring(4, 6), 16);
        } else {
            return true;
        }
    } catch (e) {
        return true;
    }

    if (isNaN(r) || isNaN(g) || isNaN(b)) return true;
    const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    return luminance > 0.5;
}

// ============= Tag Filter Setup =============

function setupTagFilter() {
    const filterSelect = document.getElementById('docs-tags-filter');
    if (!filterSelect) return;
    
    filterSelect.addEventListener('change', () => {
        selectedTagFilter = Array.from(filterSelect.selectedOptions).map(opt => opt.value);
    });
}

function updateTagFilterOptions() {
    const filterSelect = document.getElementById('docs-tags-filter');
    if (!filterSelect) return;
    
    filterSelect.innerHTML = workspaceTags.map(tag => {
        const textColor = isColorLight(tag.color) ? 'color: #212529' : 'color: #fff';
        return `<option value="${escapeHtml(tag.name)}" style="background-color: ${tag.color}; ${textColor};">
            ${escapeHtml(tag.name)} (${tag.count})
        </option>`;
    }).join('');
}

// ============= Document Tags Select (Metadata Modal) =============

function updateDocTagsSelect() {
    const select = document.getElementById('doc-tags');
    if (!select) return;
    
    select.innerHTML = workspaceTags.map(tag => {
        const textColor = isColorLight(tag.color) ? 'color: #212529' : 'color: #fff';
        return `<option value="${escapeHtml(tag.name)}" style="background-color: ${tag.color}; ${textColor};">
            ${escapeHtml(tag.name)}
        </option>`;
    }).join('');
}

// ============= Bulk Tag Management =============

// Track selected tags for bulk operations
let bulkSelectedTags = new Set();

function setupBulkTagManagement() {
    const manageTagsBtn = document.getElementById('manage-tags-btn');
    const bulkTagModal = document.getElementById('bulkTagModal');
    const bulkTagApplyBtn = document.getElementById('bulk-tag-apply-btn');
    
    if (manageTagsBtn && bulkTagModal) {
        const modalInstance = new bootstrap.Modal(bulkTagModal);
        
        manageTagsBtn.addEventListener('click', () => {
            const count = window.selectedDocuments?.size || 0;
            document.getElementById('bulk-tag-doc-count').textContent = count;
            
            // Clear selection and populate tags list
            bulkSelectedTags.clear();
            updateBulkTagsList();
            
            modalInstance.show();
        });
        
        if (bulkTagApplyBtn) {
            bulkTagApplyBtn.addEventListener('click', async () => {
                await applyBulkTagChanges();
                modalInstance.hide();
            });
        }
    }
}

function updateBulkTagsList() {
    const listContainer = document.getElementById('bulk-tags-list');
    if (!listContainer) return;
    
    if (workspaceTags.length === 0) {
        listContainer.innerHTML = '<div class="text-muted w-100 text-center py-3">No tags available. Click "Create New Tag" to add some.</div>';
        return;
    }
    
    let html = '';
    workspaceTags.forEach(tag => {
        const textColor = isColorLight(tag.color) ? '#000' : '#fff';
        const isSelected = bulkSelectedTags.has(tag.name);
        const selectedClass = isSelected ? 'selected border-dark' : '';
        const opacity = isSelected ? '1' : '0.7';
        
        html += `
            <span class="badge tag-badge ${selectedClass}" 
                  style="background-color: ${tag.color}; color: ${textColor}; opacity: ${opacity}; cursor: pointer; border: 2px solid transparent;"
                  onclick="window.toggleBulkTag('${escapeHtml(tag.name)}', '${tag.color}', this)">
                ${escapeHtml(tag.name)}
                ${isSelected ? '<i class="bi bi-check-circle-fill ms-1"></i>' : ''}
            </span>
        `;
    });
    
    listContainer.innerHTML = html;
}

// Make toggle function global so onclick can access it
window.toggleBulkTag = function(tagName, color, element) {
    if (bulkSelectedTags.has(tagName)) {
        bulkSelectedTags.delete(tagName);
        element.classList.remove('selected', 'border-dark');
        element.style.opacity = '0.7';
        // Remove checkmark
        const icon = element.querySelector('.bi-check-circle-fill');
        if (icon) icon.remove();
    } else {
        bulkSelectedTags.add(tagName);
        element.classList.add('selected', 'border-dark');
        element.style.opacity = '1';
        // Add checkmark
        element.innerHTML = `${escapeHtml(tagName)} <i class="bi bi-check-circle-fill ms-1"></i>`;
    }
};

function updateBulkTagSelect() {
    // This function is deprecated - now using updateBulkTagsList()
    updateBulkTagsList();
}

async function applyBulkTagChanges() {
    console.log('[Bulk Tag] Starting applyBulkTagChanges...');
    
    const action = document.getElementById('bulk-tag-action').value;
    console.log('[Bulk Tag] Action:', action);
    
    // Get selected tags from the bulkSelectedTags Set
    const selectedTags = Array.from(bulkSelectedTags);
    console.log('[Bulk Tag] Selected tags:', selectedTags);
    console.log('[Bulk Tag] bulkSelectedTags Set:', bulkSelectedTags);
    
    const documentIds = Array.from(window.selectedDocuments || []);
    console.log('[Bulk Tag] Document IDs:', documentIds);
    console.log('[Bulk Tag] window.selectedDocuments:', window.selectedDocuments);
    
    if (documentIds.length === 0) {
        console.log('[Bulk Tag] ERROR: No documents selected');
        alert('No documents selected');
        return;
    }
    
    if (selectedTags.length === 0) {
        console.log('[Bulk Tag] ERROR: No tags selected');
        alert('Please select at least one tag by clicking on it');
        return;
    }
    
    // Show loading state
    const applyBtn = document.getElementById('bulk-tag-apply-btn');
    const buttonText = applyBtn.querySelector('.button-text');
    const buttonLoading = applyBtn.querySelector('.button-loading');
    
    applyBtn.disabled = true;
    buttonText.classList.add('d-none');
    buttonLoading.classList.remove('d-none');
    
    console.log('[Bulk Tag] Preparing request with:', {
        document_ids: documentIds,
        action: action,
        tags: selectedTags
    });
    
    try {
        console.log('[Bulk Tag] Sending POST to /api/documents/bulk-tag...');
        const response = await fetch('/api/documents/bulk-tag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                document_ids: documentIds,
                action: action,
                tags: selectedTags
            })
        });
        
        console.log('[Bulk Tag] Response status:', response.status);
        
        const result = await response.json();
        console.log('[Bulk Tag] Response data:', result);
        
        // Log error details if any
        if (result.errors && result.errors.length > 0) {
            console.error('[Bulk Tag] Error details:', result.errors);
            result.errors.forEach((err, idx) => {
                console.error(`[Bulk Tag] Error ${idx + 1}:`, err);
            });
        }
        
        if (response.ok) {
            const successCount = result.success?.length || 0;
            const errorCount = result.errors?.length || 0;
            
            console.log('[Bulk Tag] Success count:', successCount);
            console.log('[Bulk Tag] Error count:', errorCount);
            
            let message = `Tags updated for ${successCount} document(s)`;
            if (errorCount > 0) {
                message += `\n${errorCount} document(s) had errors`;
            }
            alert(message);
            
            // Reload workspace tags and documents
            console.log('[Bulk Tag] Reloading tags and documents...');
            await loadWorkspaceTags();
            window.fetchUserDocuments?.();
            
            // Clear selection
            window.selectedDocuments?.clear();
            updateSelectionUI();
        } else {
            alert('Error: ' + (result.error || 'Failed to update tags'));
        }
    } catch (error) {
        console.error('Error applying bulk tag changes:', error);
        alert('Error updating tags');
    } finally {
        // Reset button state
        applyBtn.disabled = false;
        buttonText.classList.remove('d-none');
        buttonLoading.classList.add('d-none');
    }
}

function updateSelectionUI() {
    const bulkActionsBar = document.getElementById('bulkActionsBar');
    const selectedCount = document.getElementById('selectedCount');
    const count = window.selectedDocuments?.size || 0;
    
    if (selectedCount) {
        selectedCount.textContent = count;
    }
    
    if (bulkActionsBar) {
        bulkActionsBar.style.display = count > 0 ? 'block' : 'none';
    }
}

// ============= Tag Display Helper =============

export function renderTagBadges(tags, maxDisplay = 3) {
    if (!tags || tags.length === 0) {
        return '<span class="text-muted small">No tags</span>';
    }
    
    let html = '';
    const displayTags = tags.slice(0, maxDisplay);
    
    displayTags.forEach(tagName => {
        const tag = workspaceTags.find(t => t.name === tagName);
        const color = tag?.color || '#6c757d';
        const textClass = isColorLight(color) ? 'text-dark' : 'text-light';
        
        html += `<span class="tag-badge ${textClass}" 
                      style="background-color: ${color};" 
                      title="${escapeHtml(tagName)}">
            ${escapeHtml(tagName)}
        </span>`;
    });
    
    if (tags.length > maxDisplay) {
        html += `<span class="badge bg-secondary">+${tags.length - maxDisplay}</span>`;
    }
    
    return html;
}

// ============= Tag Management Actions (exposed globally) =============

window.renameTag = function(tagName) {
    const tag = workspaceTags.find(t => t.name === tagName);
    showTagManagementModal(tagName, tag?.color);
};

window.changeTagColor = function(tagName, currentColor) {
    showTagManagementModal(tagName, currentColor);
};

window.deleteTag = async function(tagName) {
    if (!confirm(`Delete tag "${tagName}" from all documents?`)) return;
    
    try {
        const response = await fetch(`/api/documents/tags/${encodeURIComponent(tagName)}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(result.message);
            await loadWorkspaceTags();
            if (currentView === 'grid') {
                renderGridView();
            } else {
                window.fetchUserDocuments?.();
            }
        } else {
            alert('Error: ' + (result.error || 'Failed to delete tag'));
        }
    } catch (error) {
        console.error('Error deleting tag:', error);
        alert('Error deleting tag');
    }
};

window.chatWithFolder = function(folderType, folderName) {
    const encoded = encodeURIComponent(folderName);
    window.location.href = `/chats?search_documents=true&doc_scope=personal&tags=${encoded}`;
};

// ============= Export for use in other modules =============

export { workspaceTags, currentView, selectedTagFilter };
