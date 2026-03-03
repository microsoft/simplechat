// public_workspace.js
'use strict';

// --- Global State ---
let userRoleInActivePublic = null;
let userPublics = [];
let activePublicId = null;
let activePublicName = '';

// Documents state
let publicDocsCurrentPage = 1;
let publicDocsPageSize = 10;
let publicDocsSearchTerm = '';

// Prompts state
let publicPromptsCurrentPage = 1;
let publicPromptsPageSize = 10;
let publicPromptsSearchTerm = '';

// Polling set for documents
const publicActivePolls = new Set();

// Document selection state
let publicSelectedDocuments = new Set();
let publicSelectionMode = false;

// Grid/folder view state
let publicCurrentView = 'list';
let publicCurrentFolder = null;
let publicCurrentFolderType = null;
let publicFolderCurrentPage = 1;
let publicFolderPageSize = 10;
let publicGridSortBy = 'count';
let publicGridSortOrder = 'desc';
let publicFolderSortBy = '_ts';
let publicFolderSortOrder = 'desc';
let publicFolderSearchTerm = '';
let publicWorkspaceTags = [];
let publicDocsSortBy = '_ts';
let publicDocsSortOrder = 'desc';
let publicDocsTagsFilter = '';
let publicBulkSelectedTags = new Set();
let publicDocSelectedTags = new Set();
let publicEditingTag = null;

// Modals
const publicPromptModal = new bootstrap.Modal(document.getElementById('publicPromptModal'));
const publicDocMetadataModal = new bootstrap.Modal(document.getElementById('publicDocMetadataModal'));
const publicTagManagementModal = new bootstrap.Modal(document.getElementById('publicTagManagementModal'));
const publicTagSelectionModal = new bootstrap.Modal(document.getElementById('publicTagSelectionModal'));

// Editors
let publicSimplemde = null;
const publicPromptContentEl = document.getElementById('public-prompt-content');
if (publicPromptContentEl && window.SimpleMDE) {
  publicSimplemde = new SimpleMDE({ element: publicPromptContentEl, spellChecker:false, autoDownloadFontAwesome: false });
}

// DOM elements
const publicSelect = document.getElementById('public-select');
const publicDropdownBtn = document.getElementById('public-dropdown-button');
const publicDropdownItems = document.getElementById('public-dropdown-items');
const publicSearchInput = document.getElementById('public-search-input');
const btnChangePublic = document.getElementById('btn-change-public');
const btnMyPublics = document.getElementById('btn-my-publics');
const uploadSection = document.getElementById('upload-public-section');
const uploadHr = document.getElementById('public-upload-hr');
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn') || document.getElementById('public-upload-btn');
const uploadStatus = document.getElementById('upload-status');
const publicDocsTableBody = document.querySelector('#public-documents-table tbody');
const publicDocsPagination = document.getElementById('public-docs-pagination-container');
const publicDocsPageSizeSelect = document.getElementById('public-docs-page-size-select');
const publicDocsSearchInput = document.getElementById('public-docs-search-input');
const docsApplyBtn = document.getElementById('public-docs-apply-filters-btn');
const docsClearBtn = document.getElementById('public-docs-clear-filters-btn');

const publicPromptsTableBody = document.querySelector('#public-prompts-table tbody');
const publicPromptsPagination = document.getElementById('public-prompts-pagination-container');
const publicPromptsPageSizeSelect = document.getElementById('public-prompts-page-size-select');
const publicPromptsSearchInput = document.getElementById('public-prompts-search-input');
const promptsApplyBtn = document.getElementById('public-prompts-apply-filters-btn');
const promptsClearBtn = document.getElementById('public-prompts-clear-filters-btn');
const createPublicPromptBtn = document.getElementById('create-public-prompt-btn');
const publicPromptForm = document.getElementById('public-prompt-form');
const publicPromptIdEl = document.getElementById('public-prompt-id');
const publicPromptNameEl = document.getElementById('public-prompt-name');

// Initialize
document.addEventListener('DOMContentLoaded', ()=>{
  fetchUserPublics().then(()=>{
    if(activePublicId) loadActivePublicData();
    else {
      publicDocsTableBody.innerHTML = '<tr><td colspan="4" class="text-center p-4 text-muted">Please select an active public workspace.</td></tr>';
      publicPromptsTableBody.innerHTML = '<tr><td colspan="2" class="text-center p-4 text-muted">Please select an active public workspace.</td></tr>';
    }
  });

  if (btnMyPublics) btnMyPublics.onclick = ()=> window.location.href = '/my_public_workspaces';
  if (btnChangePublic) btnChangePublic.onclick = onChangeActivePublic;

  // Upload functionality - handle both button click and drag-and-drop
  if (uploadBtn) uploadBtn.onclick = () => checkUserAgreementBeforePublicUpload();
  
  // Add upload area functionality (drag-and-drop and click-to-browse)
  const uploadArea = document.getElementById('upload-area');
  if (fileInput && uploadArea) {
    // Auto-upload on file selection (with user agreement check)
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        checkUserAgreementBeforePublicUpload();
      }
    });

    // Click on area triggers file input
    uploadArea.addEventListener('click', (e) => {
      // Only trigger if not clicking the hidden input itself
      if (e.target !== fileInput) {
        fileInput.click();
      }
    });

    // Drag-and-drop support
    uploadArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadArea.classList.add('dragover');
      uploadArea.style.borderColor = '#0d6efd';
    });
    
    uploadArea.addEventListener('dragleave', (e) => {
      e.preventDefault();
      uploadArea.classList.remove('dragover');
      uploadArea.style.borderColor = '';
    });
    
    uploadArea.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadArea.classList.remove('dragover');
      uploadArea.style.borderColor = '';
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        // Set the files to the file input and trigger upload with user agreement check
        fileInput.files = e.dataTransfer.files;
        checkUserAgreementBeforePublicUpload();
      }
    });
  }
  
  if (publicDocsPageSizeSelect) publicDocsPageSizeSelect.onchange = (e)=>{ publicDocsPageSize = +e.target.value; publicDocsCurrentPage=1; fetchPublicDocs(); };
  if (docsApplyBtn) docsApplyBtn.onclick = ()=>{
    publicDocsSearchTerm = publicDocsSearchInput ? publicDocsSearchInput.value.trim() : '';
    // Read tags filter
    const tagsSelect = document.getElementById('public-docs-tags-filter');
    if (tagsSelect) {
      publicDocsTagsFilter = Array.from(tagsSelect.selectedOptions).map(o => o.value).join(',');
    }
    publicDocsCurrentPage=1;
    fetchPublicDocs();
  };
  if (docsClearBtn) docsClearBtn.onclick = ()=>{
    if (publicDocsSearchInput) publicDocsSearchInput.value='';
    publicDocsSearchTerm='';
    publicDocsSortBy='_ts'; publicDocsSortOrder='desc';
    publicDocsTagsFilter='';
    const classFilter = document.getElementById('public-docs-classification-filter');
    if (classFilter) classFilter.value='';
    const authorFilter = document.getElementById('public-docs-author-filter');
    if (authorFilter) authorFilter.value='';
    const keywordsFilter = document.getElementById('public-docs-keywords-filter');
    if (keywordsFilter) keywordsFilter.value='';
    const abstractFilter = document.getElementById('public-docs-abstract-filter');
    if (abstractFilter) abstractFilter.value='';
    const tagsSelect = document.getElementById('public-docs-tags-filter');
    if (tagsSelect) { Array.from(tagsSelect.options).forEach(o => o.selected = false); }
    updatePublicListSortIcons();
    publicDocsCurrentPage=1;
    fetchPublicDocs();
  };
  if (publicDocsSearchInput) publicDocsSearchInput.onkeypress = e=>{ if(e.key==='Enter') docsApplyBtn && docsApplyBtn.click(); };

  createPublicPromptBtn.onclick = ()=> openPublicPromptModal();
  publicPromptForm.onsubmit = onSavePublicPrompt;
  
  // Document metadata form submission
  const publicDocMetadataForm = document.getElementById('public-doc-metadata-form');
  if (publicDocMetadataForm) {
    publicDocMetadataForm.addEventListener('submit', onSavePublicDocMetadata);
  }
  publicPromptsPageSizeSelect.onchange = e=>{ publicPromptsPageSize=+e.target.value; publicPromptsCurrentPage=1; fetchPublicPrompts(); };
  promptsApplyBtn.onclick = ()=>{ publicPromptsSearchTerm = publicPromptsSearchInput.value.trim(); publicPromptsCurrentPage=1; fetchPublicPrompts(); };
  promptsClearBtn.onclick = ()=>{ publicPromptsSearchInput.value=''; publicPromptsSearchTerm=''; publicPromptsCurrentPage=1; fetchPublicPrompts(); };
  publicPromptsSearchInput.onkeypress = e=>{ if(e.key==='Enter') promptsApplyBtn.click(); };

  // Add tab change event listeners to load data when switching tabs
  document.getElementById('public-prompts-tab-btn').addEventListener('shown.bs.tab', () => {
    if (activePublicId) fetchPublicPrompts();
  });
  
  document.getElementById('public-docs-tab-btn').addEventListener('shown.bs.tab', () => {
    if (activePublicId) fetchPublicDocs();
  });

  Array.from(publicDropdownItems.children).forEach(()=>{}); // placeholder

  // --- Document selection event listeners ---
  // Event delegation for document checkboxes
  document.addEventListener('change', function(event) {
    if (event.target.classList.contains('document-checkbox')) {
      const documentId = event.target.getAttribute('data-document-id');
      if (window.updatePublicSelectedDocuments) {
        window.updatePublicSelectedDocuments(documentId, event.target.checked);
      }
    }
  });

  // Bulk action buttons
  const publicDeleteSelectedBtn = document.getElementById('public-delete-selected-btn');
  const publicClearSelectionBtn = document.getElementById('public-clear-selection-btn');
  const publicChatSelectedBtn = document.getElementById('public-chat-selected-btn');

  if (publicDeleteSelectedBtn) publicDeleteSelectedBtn.addEventListener('click', deletePublicSelectedDocuments);
  if (publicClearSelectionBtn) publicClearSelectionBtn.addEventListener('click', clearPublicSelection);
  if (publicChatSelectedBtn) publicChatSelectedBtn.addEventListener('click', chatWithPublicSelected);
});

// Fetch User's Public Workspaces
async function fetchUserPublics(){
  publicSelect.disabled = true;
  publicDropdownBtn.disabled = true;
  btnChangePublic.disabled = true;
  publicDropdownBtn.querySelector('.selected-public-text').textContent = 'Loading...';
  publicDropdownItems.innerHTML = '<div class="text-center py-2"><div class="spinner-border spinner-border-sm"></div> Loading...</div>';
  try {
    const r = await fetch('/api/public_workspaces?');
    if(!r.ok) throw await r.json();
    const data = await r.json();
    userPublics = data.workspaces || [];
    publicSelect.innerHTML=''; publicDropdownItems.innerHTML='';
    let found=false;
    userPublics.forEach(w=>{
      const opt = document.createElement('option'); opt.value=w.id; opt.text=w.name; publicSelect.append(opt);
      const btn = document.createElement('button'); btn.type='button'; btn.className='dropdown-item'; btn.textContent=w.name; btn.dataset.publicId=w.id;
      btn.onclick = ()=>{ publicSelect.value=w.id; publicDropdownBtn.querySelector('.selected-public-text').textContent=w.name; document.querySelectorAll('#public-dropdown-items .dropdown-item').forEach(i=>i.classList.remove('active')); btn.classList.add('active'); };
      publicDropdownItems.append(btn);
      if(w.isActive){ publicSelect.value=w.id; publicDropdownBtn.querySelector('.selected-public-text').textContent=w.name; activePublicId=w.id; userRoleInActivePublic=w.userRole; activePublicName=w.name; found=true; }
    });
    if(!found){ activePublicId=null; publicDropdownBtn.querySelector('.selected-public-text').textContent = userPublics.length? 'Select a workspace...':'No workspaces'; }
    updatePublicRoleDisplay();
  } catch(err){ console.error(err); publicDropdownItems.innerHTML='<div class="dropdown-item disabled">Error loading</div>'; publicDropdownBtn.querySelector('.selected-public-text').textContent='Error'; }
  finally{ publicSelect.disabled=false; publicDropdownBtn.disabled=false; btnChangePublic.disabled=false; }
}

async function onChangeActivePublic(){
  const newId = publicSelect.value; if(newId===activePublicId) return;
  btnChangePublic.disabled=true; btnChangePublic.textContent='Changing...';
  try { const r=await fetch('/api/public_workspaces/setActive',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspaceId:newId})}); if(!r.ok) throw await r.json(); await fetchUserPublics(); if(activePublicId===newId) loadActivePublicData(); }
  catch(e){ console.error(e); alert('Error setting active workspace: '+(e.error||e.message)); }
  finally{ btnChangePublic.disabled=false; btnChangePublic.textContent='Change Active Workspace'; }
}

function updatePublicRoleDisplay(){
  const display = document.getElementById('user-public-role-display');
  if (activePublicId) {
    const roleEl = document.getElementById('user-public-role');
    const nameRoleEl = document.getElementById('active-public-name-role');
    if (roleEl) roleEl.textContent = userRoleInActivePublic;
    if (nameRoleEl) nameRoleEl.textContent = activePublicName;
    if (display) display.style.display = 'block';
    if (uploadSection) uploadSection.style.display = ['Owner','Admin','DocumentManager'].includes(userRoleInActivePublic) ? 'block' : 'none';
    // uploadHr was removed from template, so skip
    
    // Control visibility of Settings tab (only for Owners and Admins)
    const settingsTabNav = document.getElementById('public-settings-tab-nav');
    const canManageSettings = ['Owner', 'Admin'].includes(userRoleInActivePublic);
    if (settingsTabNav) {
      settingsTabNav.classList.toggle('d-none', !canManageSettings);
    }
  } else {
    if (display) display.style.display = 'none';
  }
}

// Update workspace status alert based on status - uses shared utility
function updateWorkspaceStatusAlert() {
  if (!activePublicId) return;
  
  fetchAndUpdateWorkspaceStatus(activePublicId, (workspace) => {
    const status = workspace.status || 'active';
    updateWorkspaceUIBasedOnStatus(status);
  });
}

// Update UI elements based on workspace status
function updateWorkspaceUIBasedOnStatus(status) {
  const isLocked = status === 'locked';
  const uploadDisabled = status === 'upload_disabled' || isLocked;
  const isInactive = status === 'inactive';
  
  const uploadSection = document.getElementById('upload-public-section');
  const fileInput = document.getElementById('file-input');
  
  // Hide/disable upload section based on status
  if (uploadSection) {
    if (uploadDisabled || isInactive) {
      uploadSection.style.display = 'none';
    }
  }
  
  // Disable file input if needed
  if (fileInput) {
    fileInput.disabled = uploadDisabled || isInactive;
  }
  
  // Disable document action buttons for locked/inactive workspaces
  if (isLocked || isInactive) {
    const actionButtons = document.querySelectorAll('#public-documents-table .btn-danger, #public-documents-table .btn-warning');
    actionButtons.forEach(btn => {
      if (isLocked) {
        btn.disabled = true;
        btn.title = 'Workspace is locked';
      } else if (isInactive) {
        btn.disabled = true;
        btn.title = 'Workspace is inactive';
      }
    });
  }
}

function loadActivePublicData(){
  const activeTab = document.querySelector('#publicWorkspaceTab .nav-link.active').dataset.bsTarget;
  if(activeTab==='#public-docs-tab') fetchPublicDocs(); else fetchPublicPrompts();
  updatePublicRoleDisplay(); updatePublicPromptsRoleUI(); updateWorkspaceStatusAlert();
}

async function fetchPublicDocs(){
  if(!activePublicId) return;
  publicDocsTableBody.innerHTML='<tr class="table-loading-row"><td colspan="4"><div class="spinner-border spinner-border-sm me-2"></div> Loading public documents...</td></tr>';
  publicDocsPagination.innerHTML='';
  const params=new URLSearchParams({page:publicDocsCurrentPage,page_size:publicDocsPageSize});
  if(publicDocsSearchTerm) params.append('search',publicDocsSearchTerm);

  // Classification filter
  const classFilter = document.getElementById('public-docs-classification-filter');
  if (classFilter && classFilter.value) params.append('classification', classFilter.value);

  // Author filter
  const authorFilter = document.getElementById('public-docs-author-filter');
  if (authorFilter && authorFilter.value.trim()) params.append('author', authorFilter.value.trim());

  // Keywords filter
  const keywordsFilter = document.getElementById('public-docs-keywords-filter');
  if (keywordsFilter && keywordsFilter.value.trim()) params.append('keywords', keywordsFilter.value.trim());

  // Abstract filter
  const abstractFilter = document.getElementById('public-docs-abstract-filter');
  if (abstractFilter && abstractFilter.value.trim()) params.append('abstract', abstractFilter.value.trim());

  // Tags filter
  if (publicDocsTagsFilter) params.append('tags', publicDocsTagsFilter);

  // Sort
  if (publicDocsSortBy !== '_ts') params.append('sort_by', publicDocsSortBy);
  if (publicDocsSortOrder !== 'desc') params.append('sort_order', publicDocsSortOrder);

  try {
    const r=await fetch(`/api/public_documents?${params}`);
    if(!r.ok) throw await r.json(); const data=await r.json();
    publicDocsTableBody.innerHTML='';
    if(!data.documents.length){ publicDocsTableBody.innerHTML=`<tr><td colspan="4" class="text-center p-4 text-muted">${publicDocsSearchTerm?'No documents found.':'No documents in this workspace.'}</td></tr>`; }
    else data.documents.forEach(doc=> renderPublicDocumentRow(doc));
    renderPublicDocsPagination(data.page,data.page_size,data.total_count);
  } catch(err){ console.error(err); publicDocsTableBody.innerHTML=`<tr><td colspan="4" class="text-center text-danger p-4">Error: ${escapeHtml(err.error||err.message)}</td></tr>`; }
}

function renderPublicDocumentRow(doc) {
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);

  // Create main document row
  const tr = document.createElement('tr');
  tr.id = `public-doc-row-${doc.id}`;
  // Compute status for icon logic and status row logic (declare once)
  const pctString = String((doc.percentage_complete ?? doc.percentage) || "0");
  const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
  const docStatus = doc.status || "";
  const isComplete = pct >= 100 || docStatus.toLowerCase().includes("complete") || docStatus.toLowerCase().includes("error");
  const hasError = docStatus.toLowerCase().includes("error") || docStatus.toLowerCase().includes("failed");

  let firstTdHtml = "";
  if (isComplete && !hasError) {
    firstTdHtml = `
      <input type="checkbox" class="document-checkbox" data-document-id="${doc.id}" style="display: none;">
      <span class="expand-collapse-container">
        <button class="btn btn-link p-0" onclick="window.togglePublicDetails('${doc.id}')" title="Show/Hide Details"><span id="public-arrow-icon-${doc.id}" class="bi bi-chevron-right"></span></button>
      </span>`;
  } else if (hasError) {
    firstTdHtml = `<span class="text-danger" title="Processing Error: ${escapeHtml(docStatus)}"><i class="bi bi-exclamation-triangle-fill"></i></span>`;
  } else {
    firstTdHtml = `<span class="text-muted" title="Processing: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)"><i class="bi bi-hourglass-split"></i></span>`;
  }

  // Build actions column
  let chatButton = '';
  let actionsDropdown = '';

  if (isComplete && !hasError) {
    chatButton = `<button class="btn btn-sm btn-primary me-1" onclick="searchPublicDocumentInChat('${doc.id}')" title="Chat"><i class="bi bi-chat-dots-fill me-1"></i>Chat</button>`;

    actionsDropdown = `
      <div class="dropdown action-dropdown d-inline-block">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
          <i class="bi bi-three-dots-vertical"></i>
        </button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><a class="dropdown-item" href="#" onclick="togglePublicSelectionMode(); return false;">
            <i class="bi bi-check-square me-2"></i>Select
          </a></li>
          <li><a class="dropdown-item" href="#" onclick="searchPublicDocumentInChat('${doc.id}'); return false;">
            <i class="bi bi-chat-dots-fill me-2"></i>Chat
          </a></li>`;

    if (canManage) {
      actionsDropdown += `
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item" href="#" onclick="window.onEditPublicDocument('${doc.id}'); return false;">
            <i class="bi bi-pencil-fill me-2"></i>Edit Metadata
          </a></li>
          <li><a class="dropdown-item" href="#" onclick="window.onExtractPublicMetadata('${doc.id}', event); return false;">
            <i class="bi bi-magic me-2"></i>Extract Metadata
          </a></li>
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item text-danger" href="#" onclick="deletePublicDocument('${doc.id}', event); return false;">
            <i class="bi bi-trash-fill me-2"></i>Delete
          </a></li>`;
    }

    actionsDropdown += `
        </ul>
      </div>`;
  } else if (canManage) {
    actionsDropdown = `
      <div class="dropdown action-dropdown d-inline-block">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
          <i class="bi bi-three-dots-vertical"></i>
        </button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><a class="dropdown-item text-danger" href="#" onclick="deletePublicDocument('${doc.id}', event); return false;">
            <i class="bi bi-trash-fill me-2"></i>Delete
          </a></li>
        </ul>
      </div>`;
  }

  tr.classList.add('document-row');
  tr.innerHTML = `
    <td class="align-middle">${firstTdHtml}</td>
    <td class="align-middle" title="${escapeHtml(doc.file_name)}">${escapeHtml(doc.file_name)}</td>
    <td class="align-middle" title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || '')}</td>
    <td class="align-middle">${chatButton}${actionsDropdown}</td>`;

  // Create details row
  const detailsRow = document.createElement('tr');
  detailsRow.id = `public-details-row-${doc.id}`;
  detailsRow.style.display = 'none';

  // Helper function to get classification badge style
  function getClassificationBadgeStyle(classification) {
    const styles = {
      'Public': 'background-color: #28a745;',
      'CUI': 'background-color: #ffc107;',
      'ITAR': 'background-color: #dc3545;',
      'Pending': 'background-color: #79bcfb;',
      'None': 'background-color: #6c757d;',
      'N/A': 'background-color: #6c757d;'
    };
    return styles[classification] || 'background-color: #6c757d;';
  }

  // Helper function to get citation badge
  function getCitationBadge(enhanced_citations) {
    return enhanced_citations ?
      '<span class="badge bg-success">Enhanced</span>' :
      '<span class="badge bg-secondary">Standard</span>';
  }

  detailsRow.innerHTML = `
    <td colspan="4">
      <div class="bg-light p-3 border rounded small">
        <p class="mb-1"><strong>Classification:</strong> <span class="classification-badge text-dark" style="${getClassificationBadgeStyle(doc.document_classification || doc.classification)}">${escapeHtml(doc.document_classification || doc.classification || 'N/A')}</span></p>
        <p class="mb-1"><strong>Version:</strong> ${escapeHtml(doc.version || '1')}</p>
        <p class="mb-1"><strong>Authors:</strong> ${escapeHtml(doc.authors || 'N/A')}</p>
        <p class="mb-1"><strong>Pages/Chunks:</strong> ${escapeHtml(doc.number_of_pages || 'N/A')}</p>
        <p class="mb-1"><strong>Citations:</strong> ${getCitationBadge(doc.enhanced_citations)}</p>
        <p class="mb-1"><strong>Publication Date:</strong> ${escapeHtml(doc.publication_date || 'N/A')}</p>
        <p class="mb-1"><strong>Keywords:</strong> ${escapeHtml(doc.keywords || 'N/A')}</p>
        <p class="mb-0"><strong>Abstract:</strong> ${escapeHtml(doc.abstract || 'N/A')}</p>
        <hr class="my-2">
        <div class="d-flex flex-wrap gap-2">
          ${canManage ? `
            <button class="btn btn-sm btn-info" onclick="window.onEditPublicDocument('${doc.id}')" title="Edit Metadata">
              <i class="bi bi-pencil-fill"></i> Edit Metadata
            </button>
            <button class="btn btn-sm btn-warning" onclick="window.onExtractPublicMetadata('${doc.id}', event)" title="Re-run Metadata Extraction">
              <i class="bi bi-magic"></i> Extract Metadata
            </button>
          ` : ''}
        </div>
      </div>
    </td>`;

  // Append main and details rows
  const tbody = document.querySelector('#public-documents-table tbody');
  tbody.append(tr);

  // --- Status Row Logic (like private workspace) ---
  // Show status row if not complete or errored
  if (!isComplete || hasError) {
    const statusRow = document.createElement("tr");
    statusRow.id = `public-status-row-${doc.id}`;
    if (hasError) {
      statusRow.innerHTML = `
        <td colspan="4">
          <div class="alert alert-danger alert-sm py-1 px-2 mb-0 small" role="alert">
            <i class="bi bi-exclamation-triangle-fill me-1"></i>
            ${escapeHtml(docStatus)}
          </div>
        </td>`;
    } else if (pct < 100) {
      statusRow.innerHTML = `
        <td colspan="4">
          <div class="progress" style="height: 10px;" title="Status: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)">
            <div id="public-progress-bar-${doc.id}" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: ${pct}%;" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
          </div>
          <div class="text-muted text-end small" id="public-status-text-${doc.id}">${escapeHtml(docStatus)} (${pct.toFixed(0)}%)</div>
        </td>`;
    } else {
      statusRow.innerHTML = `
        <td colspan="4">
          <div class="alert alert-info alert-sm py-1 px-2 mb-0 small" role="alert">
            <i class="bi bi-info-circle-fill me-1"></i>
            ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)
          </div>
        </td>`;
    }
    tbody.append(statusRow);

    // Start polling for status if still processing and not errored
    if (!isComplete && !hasError) {
      pollPublicDocumentStatus(doc.id);
    }
  }

  tbody.append(detailsRow);
}

// Polling for public document status (like private workspace)
function pollPublicDocumentStatus(documentId) {
  if (publicActivePolls.has(documentId)) return;
  publicActivePolls.add(documentId);

  const intervalId = setInterval(async () => {
    const docRow = document.getElementById(`public-doc-row-${documentId}`);
    const statusRow = document.getElementById(`public-status-row-${documentId}`);
    if (!docRow && !statusRow) {
      clearInterval(intervalId);
      publicActivePolls.delete(documentId);
      return;
    }
    try {
      const r = await fetch(`/api/public_documents/${documentId}`);
      if (r.status === 404) throw new Error('Document not found (likely deleted).');
      const doc = await r.json();
      const pctString = String((doc.percentage_complete ?? doc.percentage) || "0");
      const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
      const docStatus = doc.status || "";
      const isComplete = pct >= 100 || docStatus.toLowerCase().includes("complete") || docStatus.toLowerCase().includes("error");
      const hasError = docStatus.toLowerCase().includes("error") || docStatus.toLowerCase().includes("failed");

      if (!isComplete && statusRow) {
        // Update progress bar and status text if still processing
        const progressBar = statusRow.querySelector(`#public-progress-bar-${documentId}`);
        const statusText = statusRow.querySelector(`#public-status-text-${documentId}`);
        if (progressBar) {
          progressBar.style.width = pct + "%";
          progressBar.setAttribute("aria-valuenow", pct);
        }
        if (statusText) {
          statusText.textContent = `${docStatus} (${pct.toFixed(0)}%)`;
        }
      } else {
        // Stop polling and remove status row if complete or errored
        clearInterval(intervalId);
        publicActivePolls.delete(documentId);
        if (statusRow) statusRow.remove();
        // Wait 5 seconds, then reload the table to show the detail button
        setTimeout(() => {
          const docRow = document.getElementById(`public-doc-row-${documentId}`);
          if (docRow) fetchPublicDocs();
        }, 5000);
      }
    } catch (err) {
      clearInterval(intervalId);
      publicActivePolls.delete(documentId);
      const statusRow = document.getElementById(`public-status-row-${documentId}`);
      if (statusRow) {
        statusRow.innerHTML = `<td colspan="4"><div class="alert alert-warning alert-sm py-1 px-2 mb-0 small" role="alert"><i class="bi bi-exclamation-triangle-fill me-1"></i>Could not retrieve status: ${escapeHtml(err.message || 'Polling failed')}</div></td>`;
      }
    }
  }, 2000);
}

function renderPublicDocsPagination(page, pageSize, totalCount){
  const container=publicDocsPagination; container.innerHTML=''; const totalPages=Math.ceil(totalCount/pageSize); if(totalPages<=1) return;
  const ul=document.createElement('ul'); ul.className='pagination pagination-sm mb-0';
  function make(p,text,disabled,active){ const li=document.createElement('li'); li.className=`page-item${disabled?' disabled':''}${active?' active':''}`; const a=document.createElement('a'); a.className='page-link'; a.href='#'; a.textContent=text; if(!disabled&&!active) a.onclick=e=>{e.preventDefault();publicDocsCurrentPage=p;fetchPublicDocs();}; li.append(a); return li; }
  ul.append(make(page-1,'«',page<=1,false)); let start=1,end=totalPages; if(totalPages>5){ const mid=2; if(page>mid) start=page-mid; end=start+4; if(end>totalPages){ end=totalPages; start=end-4; } } if(start>1){ ul.append(make(1,'1',false,false)); ul.append(make(0,'...',true,false)); } for(let p=start;p<=end;p++) ul.append(make(p,p,false,p===page)); if(end<totalPages){ ul.append(make(0,'...',true,false)); ul.append(make(totalPages,totalPages,false,false)); } ul.append(make(page+1,'»',page>=totalPages,false)); container.append(ul);
}

/**
 * Check for user agreement before public workspace upload
 * Wraps onPublicUploadClick with user agreement check
 */
function checkUserAgreementBeforePublicUpload() {
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    alert('Select files');
    return;
  }
  
  // Check for user agreement before uploading
  if (window.UserAgreementManager && activePublicId) {
    window.UserAgreementManager.checkBeforeUpload(
      fileInput.files,
      'public',
      activePublicId,
      function(files) {
        // Proceed with upload
        onPublicUploadClick();
      }
    );
  } else {
    onPublicUploadClick();
  }
}

async function onPublicUploadClick() {
  if (!fileInput) return alert('File input not found');
  const files = fileInput.files;
  if (!files || !files.length) return alert('Select files');
  
  // Client-side file size validation
  const maxFileSizeMB = window.max_file_size_mb || 16; // Default to 16MB if not set
  const maxFileSizeBytes = maxFileSizeMB * 1024 * 1024;
  
  for (const file of files) {
      if (file.size > maxFileSizeBytes) {
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(1);
          alert(`File "${file.name}" (${fileSizeMB} MB) exceeds the maximum allowed size of ${maxFileSizeMB} MB. Please select a smaller file.`);
          return;
      }
  }
  
  // Disable upload button if it exists
  if (uploadBtn) {
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Uploading...';
  }
  
  // Show upload status
  if (uploadStatus) uploadStatus.textContent = `Uploading ${files.length} file(s)...`;

  // Progress container for per-file status
  const progressContainer = document.getElementById('public-upload-progress-container');
  if (progressContainer) progressContainer.innerHTML = '';

  let completed = 0;
  let failed = 0;

  // Helper to create a unique ID for each file
  function makeId(file) {
    return 'progress-' + Math.random().toString(36).slice(2, 10) + '-' + encodeURIComponent(file.name.replace(/\W+/g, ''));
  }

  // Helper to create progress bar/status for a file
  function createProgressBar(file, id) {
    const wrapper = document.createElement('div');
    wrapper.className = 'mb-2';
    wrapper.id = id + '-wrapper';
    wrapper.innerHTML = `
      <div class="progress" style="height: 10px;" title="Status: Uploading ${escapeHtml(file.name)} (0%)">
        <div id="${id}" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
      </div>
      <div class="text-muted text-end small" id="${id}-text">Uploading ${escapeHtml(file.name)} (0%)</div>
    `;
    return wrapper;
  }

  // Upload each file individually with progress
  Array.from(files).forEach(file => {
    const id = makeId(file);
    if (progressContainer) progressContainer.appendChild(createProgressBar(file, id));

    const progressBar = document.getElementById(id);
    const statusText = document.getElementById(id + '-text');

    const formData = new FormData();
    formData.append('file', file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/public_documents/upload', true);

    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        if (progressBar) {
          progressBar.style.width = percent + '%';
          progressBar.setAttribute('aria-valuenow', percent);
        }
        if (statusText) {
          statusText.textContent = `Uploading ${file.name} (${percent}%)`;
        }
      }
    };

    xhr.onload = function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (progressBar) {
          progressBar.classList.remove('bg-info');
          progressBar.classList.add('bg-success');
          progressBar.classList.remove('progress-bar-animated');
        }
        if (statusText) {
          statusText.textContent = `Uploaded ${file.name} (100%)`;
        }
        completed++;
      } else {
        if (progressBar) {
          progressBar.classList.remove('bg-info');
          progressBar.classList.add('bg-danger');
          progressBar.classList.remove('progress-bar-animated');
        }
        if (statusText) {
          statusText.textContent = `Failed to upload ${file.name}`;
        }
        failed++;
      }
      // Update summary status
      if (uploadStatus) uploadStatus.textContent = `Uploaded ${completed}/${files.length}${failed ? `, Failed: ${failed}` : ''}`;
      if (completed + failed === files.length) {
        fileInput.value = '';
        publicDocsCurrentPage = 1;
        fetchPublicDocs();
        
        // Re-enable upload button if it exists
        if (uploadBtn) {
          uploadBtn.disabled = false;
          uploadBtn.textContent = 'Upload Document(s)';
        }
        
        // Clear upload progress bars after all uploads and table refresh
        const progressContainer = document.getElementById('public-upload-progress-container');
        if (progressContainer) progressContainer.innerHTML = '';
      }
    };

    xhr.onerror = function () {
      if (progressBar) {
        progressBar.classList.remove('bg-info');
        progressBar.classList.add('bg-danger');
        progressBar.classList.remove('progress-bar-animated');
      }
      if (statusText) {
        statusText.textContent = `Failed to upload ${file.name}`;
      }
      failed++;
      if (uploadStatus) uploadStatus.textContent = `Uploaded ${completed}/${files.length}${failed ? `, Failed: ${failed}` : ''}`;
      if (completed + failed === files.length) {
        fileInput.value = '';
        publicDocsCurrentPage = 1;
        fetchPublicDocs();
        
        // Re-enable upload button if it exists
        if (uploadBtn) {
          uploadBtn.disabled = false;
          uploadBtn.textContent = 'Upload Document(s)';
        }
        
        // Clear upload progress bars after all uploads and table refresh
        const progressContainer = document.getElementById('public-upload-progress-container');
        if (progressContainer) progressContainer.innerHTML = '';
      }
    };

    xhr.send(formData);
  });
}
window.deletePublicDocument=async function(id, event){ if(!confirm('Delete?')) return; try{ await fetch(`/api/public_documents/${id}`,{method:'DELETE'}); fetchPublicDocs(); }catch(e){ alert(`Error deleting: ${e.error||e.message}`);} };

window.searchPublicDocumentInChat = function(docId) {
  window.location.href = `/chats?search_documents=true&doc_scope=public&document_id=${docId}&workspace_id=${activePublicId}`;
};

// --- Public Document Selection Functions ---
function updatePublicSelectedDocuments(documentId, isSelected) {
  if (isSelected) {
    publicSelectedDocuments.add(documentId);
  } else {
    publicSelectedDocuments.delete(documentId);
  }
  updatePublicBulkActionButtons();
}

function updatePublicBulkActionButtons() {
  const bulkActionsBar = document.getElementById('publicBulkActionsBar');
  const selectedCountSpan = document.getElementById('publicSelectedCount');
  const deleteBtn = document.getElementById('public-delete-selected-btn');

  if (publicSelectedDocuments.size > 0) {
    if (bulkActionsBar) bulkActionsBar.style.display = 'block';
    if (selectedCountSpan) selectedCountSpan.textContent = publicSelectedDocuments.size;
    const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
    if (deleteBtn) deleteBtn.style.display = canManage ? 'inline-block' : 'none';
  } else {
    if (bulkActionsBar) bulkActionsBar.style.display = 'none';
  }
}

function togglePublicSelectionMode() {
  const table = document.getElementById('public-documents-table');
  const checkboxes = document.querySelectorAll('.document-checkbox');
  const expandContainers = document.querySelectorAll('.expand-collapse-container');
  const bulkActionsBar = document.getElementById('publicBulkActionsBar');

  publicSelectionMode = !publicSelectionMode;

  if (publicSelectionMode) {
    table.classList.add('selection-mode');
    checkboxes.forEach(cb => { cb.style.display = 'inline-block'; });
    expandContainers.forEach(c => { c.style.display = 'none'; });
  } else {
    table.classList.remove('selection-mode');
    checkboxes.forEach(cb => { cb.style.display = 'none'; cb.checked = false; });
    expandContainers.forEach(c => { c.style.display = 'inline-block'; });
    if (bulkActionsBar) bulkActionsBar.style.display = 'none';
    publicSelectedDocuments.clear();
  }
}

function clearPublicSelection() {
  document.querySelectorAll('.document-checkbox').forEach(cb => { cb.checked = false; });
  publicSelectedDocuments.clear();
  updatePublicBulkActionButtons();
}

function deletePublicSelectedDocuments() {
  if (publicSelectedDocuments.size === 0) return;
  if (!confirm(`Are you sure you want to delete ${publicSelectedDocuments.size} selected document(s)? This action cannot be undone.`)) return;

  const deleteBtn = document.getElementById('public-delete-selected-btn');
  if (deleteBtn) {
    deleteBtn.disabled = true;
    deleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Deleting...';
  }

  const deletePromises = Array.from(publicSelectedDocuments).map(docId =>
    fetch(`/api/public_documents/${docId}`, { method: 'DELETE' })
      .then(r => r.ok ? r.json() : Promise.reject(r))
  );

  Promise.allSettled(deletePromises)
    .then(results => {
      const successful = results.filter(r => r.status === 'fulfilled').length;
      const failed = results.filter(r => r.status === 'rejected').length;
      if (failed > 0) alert(`Deleted ${successful} document(s). ${failed} failed to delete.`);
      publicSelectedDocuments.clear();
      updatePublicBulkActionButtons();
      fetchPublicDocs();
    })
    .finally(() => {
      if (deleteBtn) {
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete Selected';
      }
    });
}

function chatWithPublicSelected() {
  if (publicSelectedDocuments.size === 0) return;
  const idsParam = encodeURIComponent(Array.from(publicSelectedDocuments).join(','));
  window.location.href = `/chats?search_documents=true&doc_scope=public&document_ids=${idsParam}&workspace_id=${activePublicId}`;
}

// Expose selection functions globally
window.updatePublicSelectedDocuments = updatePublicSelectedDocuments;
window.togglePublicSelectionMode = togglePublicSelectionMode;
window.deletePublicSelectedDocuments = deletePublicSelectedDocuments;
window.clearPublicSelection = clearPublicSelection;
window.chatWithPublicSelected = chatWithPublicSelected;

// Prompts
async function fetchPublicPrompts(){
  publicPromptsTableBody.innerHTML='<tr class="table-loading-row"><td colspan="2"><div class="spinner-border spinner-border-sm me-2"></div> Loading prompts...</td></tr>';
  publicPromptsPagination.innerHTML=''; const params=new URLSearchParams({page:publicPromptsCurrentPage,page_size:publicPromptsPageSize}); if(publicPromptsSearchTerm) params.append('search',publicPromptsSearchTerm);
  try{ const r=await fetch(`/api/public_prompts?${params}`); if(!r.ok) throw await r.json(); const d=await r.json(); publicPromptsTableBody.innerHTML=''; if(!d.prompts.length) publicPromptsTableBody.innerHTML='<tr><td colspan="2" class="text-center p-4 text-muted">No prompts.</td></tr>'; else d.prompts.forEach(p=>renderPublicPromptRow(p)); renderPublicPromptsPagination(d.page,d.page_size,d.total_count); }catch(e){ publicPromptsTableBody.innerHTML=`<tr><td colspan="2" class="text-center text-danger p-3">Error: ${escapeHtml(e.error||e.message)}</td></tr>`; }
}
function renderPublicPromptRow(p){ const tr=document.createElement('tr'); tr.innerHTML=`<td title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</td><td><button class="btn btn-sm btn-primary" onclick="onEditPublicPrompt('${p.id}')"><i class="bi bi-pencil-fill"></i></button><button class="btn btn-sm btn-danger ms-1" onclick="onDeletePublicPrompt('${p.id}')"><i class="bi bi-trash-fill"></i></button></td>`; publicPromptsTableBody.append(tr); }
function renderPublicPromptsPagination(page,pageSize,totalCount){ const container=publicPromptsPagination; container.innerHTML=''; const totalPages=Math.ceil(totalCount/pageSize); if(totalPages<=1) return; const ul=document.createElement('ul'); ul.className='pagination pagination-sm mb-0'; function mk(p,t,d,a){ const li=document.createElement('li'); li.className=`page-item${d?' disabled':''}${a?' active':''}`; const aEl=document.createElement('a'); aEl.className='page-link'; aEl.href='#'; aEl.textContent=t; if(!d&&!a) aEl.onclick=e=>{e.preventDefault();publicPromptsCurrentPage=p;fetchPublicPrompts();}; li.append(aEl); return li;} ul.append(mk(page-1,'«',page<=1,false)); for(let p=1;p<=totalPages;p++) ul.append(mk(p,p,false,p===page)); ul.append(mk(page+1,'»',page>=totalPages,false)); container.append(ul);} 

function openPublicPromptModal(){ publicPromptIdEl.value=''; publicPromptNameEl.value=''; if(publicSimplemde) publicSimplemde.value(''); else publicPromptContentEl.value=''; document.getElementById('publicPromptModalLabel').textContent='Create Public Prompt'; publicPromptModal.show(); updatePublicPromptsRoleUI(); }
async function onSavePublicPrompt(e){ e.preventDefault(); const id=publicPromptIdEl.value; const url=id?`/api/public_prompts/${id}`:'/api/public_prompts'; const method=id?'PATCH':'POST'; const name=publicPromptNameEl.value.trim(); const content=publicSimplemde?publicSimplemde.value():publicPromptContentEl.value.trim(); if(!name||!content) return alert('Name & content required'); const btn=document.getElementById('public-prompt-save-btn'); btn.disabled=true; btn.innerHTML='<span class="spinner-border spinner-border-sm me-1"></span>Saving…'; try{ const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify({name,content})}); if(!r.ok) throw await r.json(); publicPromptModal.hide(); fetchPublicPrompts(); }catch(err){ alert(err.error||err.message); }finally{ btn.disabled=false; btn.textContent='Save Prompt'; }}
window.onEditPublicPrompt=async function(id){ try{ const r=await fetch(`/api/public_prompts/${id}`); if(!r.ok) throw await r.json(); const d=await r.json(); document.getElementById('publicPromptModalLabel').textContent=`Edit: ${d.name}`; publicPromptIdEl.value=d.id; publicPromptNameEl.value=d.name; if(publicSimplemde) publicSimplemde.value(d.content); else publicPromptContentEl.value=d.content; publicPromptModal.show(); }catch(e){ alert(e.error||e.message);} };
window.onDeletePublicPrompt=async function(id){ if(!confirm('Delete prompt?')) return; try{ await fetch(`/api/public_prompts/${id}`,{method:'DELETE'}); fetchPublicPrompts(); }catch(e){ alert(e.error||e.message);} };

// Document metadata functions
window.onEditPublicDocument = function(docId) {
  if (!publicDocMetadataModal) {
    console.error("Public document metadata modal element not found.");
    return;
  }
  
  fetch(`/api/public_documents/${docId}`)
    .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
    .then(doc => {
      const docIdInput = document.getElementById("public-doc-id");
      const docTitleInput = document.getElementById("public-doc-title");
      const docAbstractInput = document.getElementById("public-doc-abstract");
      const docKeywordsInput = document.getElementById("public-doc-keywords");
      const docPubDateInput = document.getElementById("public-doc-publication-date");
      const docAuthorsInput = document.getElementById("public-doc-authors");
      const classificationSelect = document.getElementById("public-doc-classification");

      if (docIdInput) docIdInput.value = doc.id;
      if (docTitleInput) docTitleInput.value = doc.title || "";
      if (docAbstractInput) docAbstractInput.value = doc.abstract || "";
      if (docKeywordsInput) docKeywordsInput.value = Array.isArray(doc.keywords) ? doc.keywords.join(", ") : (doc.keywords || "");
      if (docPubDateInput) docPubDateInput.value = doc.publication_date || "";
      if (docAuthorsInput) docAuthorsInput.value = Array.isArray(doc.authors) ? doc.authors.join(", ") : (doc.authors || "");

      // Handle classification dropdown
      if (classificationSelect) {
        const currentClassification = doc.classification || doc.document_classification || 'none';
        classificationSelect.value = currentClassification;
        // Double-check if the value actually exists in the options
        if (![...classificationSelect.options].some(option => option.value === classificationSelect.value)) {
          console.warn(`Classification value "${currentClassification}" not found in dropdown, defaulting.`);
          classificationSelect.value = "none";
        }
      }

      // Load tags for the document
      publicDocSelectedTags = new Set(Array.isArray(doc.tags) ? doc.tags : []);
      updatePublicDocTagsDisplay();

      publicDocMetadataModal.show();
    })
    .catch(err => {
      console.error("Error retrieving public document for edit:", err);
      alert("Error retrieving document details: " + (err.error || err.message || "Unknown error"));
    });
};

// Form submission handler for public document metadata
async function onSavePublicDocMetadata(e) {
  e.preventDefault();
  const docSaveBtn = document.getElementById("public-doc-save-btn");
  if (!docSaveBtn) return;
  
  docSaveBtn.disabled = true;
  docSaveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...`;

  const docId = document.getElementById("public-doc-id").value;
  const payload = {
    title: document.getElementById("public-doc-title")?.value.trim() || null,
    abstract: document.getElementById("public-doc-abstract")?.value.trim() || null,
    keywords: document.getElementById("public-doc-keywords")?.value.trim() || null,
    publication_date: document.getElementById("public-doc-publication-date")?.value.trim() || null,
    authors: document.getElementById("public-doc-authors")?.value.trim() || null,
  };

  if (payload.keywords) {
    payload.keywords = payload.keywords.split(",").map(kw => kw.trim()).filter(Boolean);
  } else {
    payload.keywords = [];
  }
  
  if (payload.authors) {
    payload.authors = payload.authors.split(",").map(a => a.trim()).filter(Boolean);
  } else {
    payload.authors = [];
  }

  // Add classification
  const classificationSelect = document.getElementById("public-doc-classification");
  let selectedClassification = classificationSelect?.value || null;
  // Treat 'none' selection as null/empty on the backend
  if (selectedClassification === 'none') {
    selectedClassification = null;
  }
  payload.document_classification = selectedClassification;

  // Add tags
  payload.tags = Array.from(publicDocSelectedTags);

  try {
    const response = await fetch(`/api/public_documents/${docId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || `Server responded with status ${response.status}`);
    }
    
    const updatedDoc = await response.json();
    publicDocMetadataModal.hide();
    fetchPublicDocs(); // Refresh the table
    loadPublicWorkspaceTags(); // Refresh tag counts
  } catch (err) {
    console.error("Error updating public document:", err);
    alert("Error updating document: " + (err.message || "Unknown error"));
  } finally {
    docSaveBtn.disabled = false;
    docSaveBtn.textContent = "Save Metadata";
  }
}

window.onExtractPublicMetadata = function(docId, event) {
  if (!confirm("Run metadata extraction for this document? This may overwrite existing metadata.")) return;

  const extractBtn = event ? event.target.closest('button') : null;
  if (extractBtn) {
    extractBtn.disabled = true;
    extractBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Extracting...`;
  }

  fetch(`/api/public_documents/${docId}/extract_metadata`, {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  })
    .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
    .then(data => {
      console.log("Public document metadata extraction started/completed:", data);
      // Refresh the list after a short delay to allow backend processing
      setTimeout(fetchPublicDocs, 1500);
      // Optionally close the details view if open
      const detailsRow = document.getElementById(`public-details-row-${docId}`);
      if (detailsRow && detailsRow.style.display !== "none") {
        window.togglePublicDetails(docId); // Close details to show updated summary row first
      }
    })
    .catch(err => {
      console.error("Error calling extract metadata for public document:", err);
      alert("Error extracting metadata: " + (err.error || err.message || "Unknown error"));
    })
    .finally(() => {
      if (extractBtn) {
        // Check if button still exists before re-enabling
        if (document.body.contains(extractBtn)) {
          extractBtn.disabled = false;
          extractBtn.innerHTML = '<i class="bi bi-magic"></i> Extract Metadata';
        }
      }
    });
};

function updatePublicPromptsRoleUI(){ const canManage=['Owner','Admin','PromptManager'].includes(userRoleInActivePublic); document.getElementById('create-public-prompt-section').style.display=canManage?'block':'none'; document.getElementById('public-prompts-role-warning').style.display=canManage?'none':'block'; }

// Expose fetch
window.fetchPublicPrompts = fetchPublicPrompts;

// Function to toggle document details
function togglePublicDetails(docId) {
  const detailsRow = document.getElementById(`public-details-row-${docId}`);
  const arrowIcon = document.getElementById(`public-arrow-icon-${docId}`);
  
  if (!detailsRow || !arrowIcon) return;
  
  if (detailsRow.style.display === "none") {
    detailsRow.style.display = "";
    arrowIcon.className = "bi bi-chevron-down";
  } else {
    detailsRow.style.display = "none";
    arrowIcon.className = "bi bi-chevron-right";
  }
}

// Make the function globally available
window.togglePublicDetails = togglePublicDetails;
window.fetchPublicDocs = fetchPublicDocs;

// === Grid/Folder/Tag Management Functions ===

function loadPublicWorkspaceTags() {
  if (!activePublicId) return Promise.resolve();
  return fetch(`/api/public_workspace_documents/tags?workspace_ids=${activePublicId}`)
    .then(r => r.ok ? r.json() : Promise.reject('Failed to load tags'))
    .then(data => {
      publicWorkspaceTags = data.tags || [];
      const sel = document.getElementById('public-docs-tags-filter');
      if (sel) {
        const prev = Array.from(sel.selectedOptions).map(o => o.value);
        sel.innerHTML = '';
        publicWorkspaceTags.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.name;
          opt.textContent = `${t.name} (${t.count})`;
          if (prev.includes(t.name)) opt.selected = true;
          sel.appendChild(opt);
        });
      }
      updatePublicBulkTagsList();
      if (publicCurrentView === 'grid') renderPublicGridView();
    })
    .catch(err => console.error('Error loading public workspace tags:', err));
}

function setupPublicViewSwitcher() {
  const listRadio = document.getElementById('public-docs-view-list');
  const gridRadio = document.getElementById('public-docs-view-grid');
  if (listRadio) listRadio.addEventListener('change', () => { if (listRadio.checked) switchPublicView('list'); });
  if (gridRadio) gridRadio.addEventListener('change', () => { if (gridRadio.checked) switchPublicView('grid'); });
}

function switchPublicView(view) {
  publicCurrentView = view;
  localStorage.setItem('publicWorkspaceViewPreference', view);
  const listView = document.getElementById('public-documents-list-view');
  const gridView = document.getElementById('public-documents-grid-view');
  const viewInfo = document.getElementById('public-docs-view-info');
  const gridControls = document.getElementById('public-grid-controls-bar');
  const filterBtn = document.getElementById('public-docs-filters-toggle-btn');
  const filterCollapse = document.getElementById('public-docs-filters-collapse');
  const bulkBar = document.getElementById('publicBulkActionsBar');

  if (view === 'list') {
    publicCurrentFolder = null;
    publicCurrentFolderType = null;
    publicFolderCurrentPage = 1;
    publicFolderSortBy = '_ts';
    publicFolderSortOrder = 'desc';
    publicFolderSearchTerm = '';
    const tagContainer = document.getElementById('public-tag-folders-container');
    if (tagContainer) tagContainer.className = 'row g-2';
    if (listView) listView.style.display = 'block';
    if (gridView) gridView.style.display = 'none';
    if (gridControls) gridControls.style.display = 'none';
    if (filterBtn) filterBtn.style.display = '';
    if (viewInfo) viewInfo.textContent = '';
    fetchPublicDocs();
  } else {
    if (listView) listView.style.display = 'none';
    if (gridView) gridView.style.display = 'block';
    if (gridControls) gridControls.style.display = 'flex';
    if (filterBtn) filterBtn.style.display = 'none';
    if (filterCollapse) {
      const bsCollapse = bootstrap.Collapse.getInstance(filterCollapse);
      if (bsCollapse) bsCollapse.hide();
    }
    if (bulkBar) bulkBar.style.display = 'none';
    renderPublicGridView();
  }
}

async function renderPublicGridView() {
  const container = document.getElementById('public-tag-folders-container');
  if (!container || !activePublicId) return;

  if (publicCurrentFolder && publicCurrentFolder !== '__untagged__' && publicCurrentFolder !== '__unclassified__') {
    if (publicCurrentFolderType === 'classification') {
      const categories = window.classification_categories || [];
      if (!categories.some(cat => cat.label === publicCurrentFolder)) {
        publicCurrentFolder = null; publicCurrentFolderType = null; publicFolderCurrentPage = 1;
      }
    } else {
      if (!publicWorkspaceTags.some(t => t.name === publicCurrentFolder)) {
        publicCurrentFolder = null; publicCurrentFolderType = null; publicFolderCurrentPage = 1;
      }
    }
  }

  if (publicCurrentFolder) { renderPublicFolderContents(publicCurrentFolder); return; }

  const viewInfo = document.getElementById('public-docs-view-info');
  if (viewInfo) viewInfo.textContent = '';
  container.className = 'row g-2';
  container.innerHTML = '<div class="col-12 text-center text-muted py-5"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading tag folders...</div>';

  try {
    const docsResponse = await fetch(`/api/public_documents?page_size=1000`);
    const docsData = await docsResponse.json();
    const allDocs = docsData.documents || [];
    const untaggedCount = allDocs.filter(doc => !doc.tags || doc.tags.length === 0).length;

    const classificationEnabled = (window.enable_document_classification === true || window.enable_document_classification === "true");
    const categories = classificationEnabled ? (window.classification_categories || []) : [];
    const classificationCounts = {};
    let unclassifiedCount = 0;
    if (classificationEnabled) {
      allDocs.forEach(doc => {
        const cls = doc.document_classification;
        if (!cls || cls === '' || cls.toLowerCase() === 'none') { unclassifiedCount++; }
        else { classificationCounts[cls] = (classificationCounts[cls] || 0) + 1; }
      });
    }

    const folderItems = [];
    if (untaggedCount > 0) {
      folderItems.push({ type: 'tag', key: '__untagged__', displayName: 'Untagged', count: untaggedCount, icon: 'bi-folder2-open', color: '#6c757d', isSpecial: true });
    }
    if (classificationEnabled && unclassifiedCount > 0) {
      folderItems.push({ type: 'classification', key: '__unclassified__', displayName: 'Unclassified', count: unclassifiedCount, icon: 'bi-bookmark', color: '#6c757d', isSpecial: true });
    }
    publicWorkspaceTags.forEach(tag => {
      folderItems.push({ type: 'tag', key: tag.name, displayName: tag.name, count: tag.count, icon: 'bi-folder-fill', color: tag.color, isSpecial: false, tagData: tag });
    });
    if (classificationEnabled) {
      categories.forEach(cat => {
        const count = classificationCounts[cat.label] || 0;
        if (count > 0) {
          folderItems.push({ type: 'classification', key: cat.label, displayName: cat.label, count: count, icon: 'bi-bookmark-fill', color: cat.color || '#6c757d', isSpecial: false });
        }
      });
    }

    folderItems.sort((a, b) => {
      if (a.isSpecial && !b.isSpecial) return -1;
      if (!a.isSpecial && b.isSpecial) return 1;
      if (publicGridSortBy === 'name') {
        const cmp = a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' });
        return publicGridSortOrder === 'asc' ? cmp : -cmp;
      }
      const cmp = a.count - b.count;
      return publicGridSortOrder === 'asc' ? cmp : -cmp;
    });

    updatePublicGridSortIcons();

    const canManageTags = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
    let html = '';
    folderItems.forEach(item => {
      const ek = escapeHtml(item.key);
      const en = escapeHtml(item.displayName);
      const cl = `${item.count} file${item.count !== 1 ? 's' : ''}`;
      let actionsHtml = '';
      if (item.type === 'tag' && !item.isSpecial && canManageTags) {
        actionsHtml = `<div class="tag-folder-actions"><div class="dropdown">
          <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();"><i class="bi bi-three-dots-vertical"></i></button>
          <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="#" onclick="chatWithPublicFolder('tag','${ek}'); return false;"><i class="bi bi-chat-dots me-2"></i>Chat</a></li>
            <li><a class="dropdown-item" href="#" onclick="renamePublicTag('${ek}'); return false;"><i class="bi bi-pencil me-2"></i>Rename Tag</a></li>
            <li><a class="dropdown-item" href="#" onclick="changePublicTagColor('${ek}','${item.tagData.color}'); return false;"><i class="bi bi-palette me-2"></i>Change Color</a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item text-danger" href="#" onclick="deletePublicTag('${ek}'); return false;"><i class="bi bi-trash me-2"></i>Delete Tag</a></li>
          </ul></div></div>`;
      } else if (item.type === 'classification') {
        actionsHtml = `<div class="tag-folder-actions"><div class="dropdown">
          <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();"><i class="bi bi-three-dots-vertical"></i></button>
          <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="#" onclick="chatWithPublicFolder('classification','${ek}'); return false;"><i class="bi bi-chat-dots me-2"></i>Chat</a></li>
          </ul></div></div>`;
      } else if (item.type === 'tag' && item.isSpecial) {
        actionsHtml = `<div class="tag-folder-actions"><div class="dropdown">
          <button class="tag-folder-menu-btn" type="button" data-bs-toggle="dropdown" onclick="event.stopPropagation();"><i class="bi bi-three-dots-vertical"></i></button>
          <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="#" onclick="chatWithPublicFolder('tag','${ek}'); return false;"><i class="bi bi-chat-dots me-2"></i>Chat</a></li>
          </ul></div></div>`;
      }
      html += `<div class="col-6 col-sm-4 col-md-3 col-lg-2">
        <div class="tag-folder-card" data-tag="${ek}" data-folder-type="${item.type}" title="${en} (${cl})">
          ${actionsHtml}
          <div class="tag-folder-icon"><i class="bi ${item.icon}" style="color: ${item.color};"></i></div>
          <div class="tag-folder-name${item.isSpecial ? ' text-muted' : ''}">${en}</div>
          <div class="tag-folder-count">${cl}</div>
        </div></div>`;
    });

    if (folderItems.length === 0) {
      html = '<div class="col-12 text-center text-muted py-5"><i class="bi bi-folder2-open display-1 mb-3"></i><p>No folders yet. Add tags to documents to organize them.</p></div>';
    }
    container.innerHTML = html;
    container.querySelectorAll('.tag-folder-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.tag-folder-actions')) return;
        publicCurrentFolder = card.getAttribute('data-tag');
        publicCurrentFolderType = card.getAttribute('data-folder-type') || 'tag';
        publicFolderCurrentPage = 1;
        publicFolderSortBy = '_ts'; publicFolderSortOrder = 'desc'; publicFolderSearchTerm = '';
        renderPublicFolderContents(publicCurrentFolder);
      });
    });
  } catch (error) {
    console.error('Error rendering public grid view:', error);
    container.innerHTML = '<div class="col-12 text-center text-danger py-5"><i class="bi bi-exclamation-triangle display-4 mb-2"></i><p>Error loading tag folders</p></div>';
  }
}

function buildPublicBreadcrumbHtml(displayName, tagColor, folderType) {
  const icon = folderType === 'classification' ? 'bi-bookmark-fill' : 'bi-folder-fill';
  return `<div class="folder-breadcrumb">
    <a href="#" class="public-back-to-grid"><i class="bi bi-grid-3x3-gap me-1"></i>All Folders</a>
    <span class="mx-2">/</span>
    <i class="bi ${icon}" style="color: ${tagColor};"></i>
    <strong class="ms-1">${escapeHtml(displayName)}</strong>
  </div>`;
}

function wirePublicBackButton(container) {
  container.querySelectorAll('.public-back-to-grid').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      publicCurrentFolder = null;
      publicCurrentFolderType = null;
      publicFolderCurrentPage = 1;
      publicFolderSortBy = '_ts'; publicFolderSortOrder = 'desc'; publicFolderSearchTerm = '';
      renderPublicGridView();
    });
  });
}

function buildPublicFolderDocumentsTable(docs) {
  function getSortIcon(field) {
    if (publicFolderSortBy === field) {
      return publicFolderSortOrder === 'asc' ? 'bi-sort-up' : 'bi-sort-down';
    }
    return 'bi-arrow-down-up text-muted';
  }
  let html = '<table class="table table-striped table-sm"><thead><tr>';
  html += `<th class="folder-sortable-header" data-sort-field="file_name" style="cursor:pointer;user-select:none;">File Name <i class="bi ${getSortIcon('file_name')} small"></i></th>`;
  html += `<th class="folder-sortable-header" data-sort-field="title" style="cursor:pointer;user-select:none;">Title <i class="bi ${getSortIcon('title')} small"></i></th>`;
  html += '<th>Actions</th></tr></thead><tbody>';
  docs.forEach(doc => {
    const chatBtn = `<button class="btn btn-sm btn-primary" onclick="searchPublicDocumentInChat('${doc.id}')" title="Chat"><i class="bi bi-chat-dots-fill me-1"></i>Chat</button>`;
    html += `<tr>
      <td title="${escapeHtml(doc.file_name)}">${escapeHtml(doc.file_name)}</td>
      <td title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || '')}</td>
      <td>${chatBtn}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  return html;
}

function renderPublicFolderPagination(page, pageSize, totalCount) {
  const container = document.getElementById('public-folder-pagination');
  if (!container) return;
  container.innerHTML = '';
  const totalPages = Math.ceil(totalCount / pageSize);
  if (totalPages <= 1) return;
  const ul = document.createElement('ul');
  ul.className = 'pagination pagination-sm mb-0';
  function make(p, text, disabled, active) {
    const li = document.createElement('li');
    li.className = `page-item${disabled ? ' disabled' : ''}${active ? ' active' : ''}`;
    const a = document.createElement('a');
    a.className = 'page-link'; a.href = '#'; a.textContent = text;
    if (!disabled && !active) a.onclick = e => { e.preventDefault(); publicFolderCurrentPage = p; renderPublicFolderContents(publicCurrentFolder); };
    li.append(a); return li;
  }
  ul.append(make(page - 1, '\u00AB', page <= 1, false));
  for (let p = 1; p <= totalPages; p++) ul.append(make(p, p, false, p === page));
  ul.append(make(page + 1, '\u00BB', page >= totalPages, false));
  container.append(ul);
}

async function renderPublicFolderContents(tagName) {
  const container = document.getElementById('public-tag-folders-container');
  if (!container) return;
  const gridControls = document.getElementById('public-grid-controls-bar');
  if (gridControls) gridControls.style.display = 'none';
  container.className = '';

  const isClassification = (publicCurrentFolderType === 'classification');
  let displayName, tagColor;
  if (tagName === '__untagged__') { displayName = 'Untagged Documents'; tagColor = '#6c757d'; }
  else if (tagName === '__unclassified__') { displayName = 'Unclassified Documents'; tagColor = '#6c757d'; }
  else if (isClassification) {
    const cat = (window.classification_categories || []).find(c => c.label === tagName);
    displayName = tagName; tagColor = cat?.color || '#6c757d';
  } else {
    const tagInfo = publicWorkspaceTags.find(t => t.name === tagName);
    displayName = tagName; tagColor = tagInfo?.color || '#6c757d';
  }

  const viewInfo = document.getElementById('public-docs-view-info');
  if (viewInfo) viewInfo.textContent = `Viewing: ${displayName}`;

  container.innerHTML = buildPublicBreadcrumbHtml(displayName, tagColor, publicCurrentFolderType || 'tag') +
    '<div class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading documents...</div>';
  wirePublicBackButton(container);

  try {
    let docs, totalCount;
    if (tagName === '__untagged__') {
      const resp = await fetch(`/api/public_documents?page_size=1000${publicFolderSearchTerm ? '&search=' + encodeURIComponent(publicFolderSearchTerm) : ''}`);
      const data = await resp.json();
      let allUntagged = (data.documents || []).filter(d => !d.tags || d.tags.length === 0);
      if (publicFolderSortBy !== '_ts') {
        allUntagged.sort((a, b) => {
          const va = (a[publicFolderSortBy] || '').toLowerCase();
          const vb = (b[publicFolderSortBy] || '').toLowerCase();
          const cmp = va.localeCompare(vb);
          return publicFolderSortOrder === 'asc' ? cmp : -cmp;
        });
      }
      totalCount = allUntagged.length;
      const start = (publicFolderCurrentPage - 1) * publicFolderPageSize;
      docs = allUntagged.slice(start, start + publicFolderPageSize);
    } else if (tagName === '__unclassified__') {
      const params = new URLSearchParams({ page: publicFolderCurrentPage, page_size: publicFolderPageSize, classification: 'none' });
      if (publicFolderSearchTerm) params.append('search', publicFolderSearchTerm);
      if (publicFolderSortBy !== '_ts') params.append('sort_by', publicFolderSortBy);
      if (publicFolderSortOrder !== 'desc') params.append('sort_order', publicFolderSortOrder);
      const resp = await fetch(`/api/public_documents?${params.toString()}`);
      const data = await resp.json();
      docs = data.documents || []; totalCount = data.total_count || docs.length;
    } else if (isClassification) {
      const params = new URLSearchParams({ page: publicFolderCurrentPage, page_size: publicFolderPageSize, classification: tagName });
      if (publicFolderSearchTerm) params.append('search', publicFolderSearchTerm);
      if (publicFolderSortBy !== '_ts') params.append('sort_by', publicFolderSortBy);
      if (publicFolderSortOrder !== 'desc') params.append('sort_order', publicFolderSortOrder);
      const resp = await fetch(`/api/public_documents?${params.toString()}`);
      const data = await resp.json();
      docs = data.documents || []; totalCount = data.total_count || docs.length;
    } else {
      const params = new URLSearchParams({ page: publicFolderCurrentPage, page_size: publicFolderPageSize, tags: tagName });
      if (publicFolderSearchTerm) params.append('search', publicFolderSearchTerm);
      if (publicFolderSortBy !== '_ts') params.append('sort_by', publicFolderSortBy);
      if (publicFolderSortOrder !== 'desc') params.append('sort_order', publicFolderSortOrder);
      const resp = await fetch(`/api/public_documents?${params.toString()}`);
      const data = await resp.json();
      docs = data.documents || []; totalCount = data.total_count || docs.length;
    }

    let html = buildPublicBreadcrumbHtml(displayName, tagColor, publicCurrentFolderType || 'tag');
    html += `<div class="d-flex align-items-center gap-2 mb-2">
      <div class="input-group input-group-sm" style="max-width: 320px;">
        <input type="search" id="public-folder-search-input" class="form-control form-control-sm" placeholder="Search file name or title..." value="${escapeHtml(publicFolderSearchTerm)}">
        <button class="btn btn-outline-secondary" type="button" id="public-folder-search-btn"><i class="bi bi-search"></i></button>
      </div>
      <span class="text-muted small">${totalCount} document(s)</span>
      <div class="ms-auto">
        <select id="public-folder-page-size-select" class="form-select form-select-sm d-inline-block" style="width:auto;">
          <option value="10"${publicFolderPageSize === 10 ? ' selected' : ''}>10</option>
          <option value="20"${publicFolderPageSize === 20 ? ' selected' : ''}>20</option>
          <option value="50"${publicFolderPageSize === 50 ? ' selected' : ''}>50</option>
        </select>
        <span class="ms-1 small text-muted">per page</span>
      </div>
    </div>`;

    if (docs.length === 0) {
      html += '<div class="text-center text-muted py-4"><i class="bi bi-folder2-open display-4 d-block mb-2"></i><p>No documents found in this folder.</p></div>';
    } else {
      html += buildPublicFolderDocumentsTable(docs);
      html += '<div id="public-folder-pagination" class="d-flex justify-content-center mt-3"></div>';
    }

    container.innerHTML = html;
    wirePublicBackButton(container);

    const si = document.getElementById('public-folder-search-input');
    const sb = document.getElementById('public-folder-search-btn');
    if (si) {
      const doSearch = () => { publicFolderSearchTerm = si.value.trim(); publicFolderCurrentPage = 1; renderPublicFolderContents(publicCurrentFolder); };
      sb?.addEventListener('click', doSearch);
      si.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doSearch(); } });
      si.addEventListener('search', doSearch);
    }

    const fps = document.getElementById('public-folder-page-size-select');
    if (fps) fps.addEventListener('change', (e) => { publicFolderPageSize = parseInt(e.target.value, 10); publicFolderCurrentPage = 1; renderPublicFolderContents(publicCurrentFolder); });

    container.querySelectorAll('.folder-sortable-header').forEach(th => {
      th.addEventListener('click', () => {
        const field = th.getAttribute('data-sort-field');
        if (publicFolderSortBy === field) { publicFolderSortOrder = publicFolderSortOrder === 'asc' ? 'desc' : 'asc'; }
        else { publicFolderSortBy = field; publicFolderSortOrder = 'asc'; }
        publicFolderCurrentPage = 1;
        renderPublicFolderContents(publicCurrentFolder);
      });
    });

    if (docs.length > 0) renderPublicFolderPagination(publicFolderCurrentPage, publicFolderPageSize, totalCount);
  } catch (error) {
    console.error('Error loading public folder contents:', error);
    container.innerHTML = buildPublicBreadcrumbHtml(displayName, tagColor, publicCurrentFolderType || 'tag') +
      '<div class="text-center text-danger py-4"><i class="bi bi-exclamation-triangle display-4 d-block mb-2"></i><p>Error loading documents.</p></div>';
    wirePublicBackButton(container);
  }
}

function chatWithPublicFolder(folderType, folderName) {
  const encoded = encodeURIComponent(folderName);
  if (folderType === 'classification') {
    window.location.href = `/chats?search_documents=true&doc_scope=public&classification=${encoded}&workspace_id=${activePublicId}`;
  } else {
    window.location.href = `/chats?search_documents=true&doc_scope=public&tags=${encoded}&workspace_id=${activePublicId}`;
  }
}

function renamePublicTag(tagName) {
  const newName = prompt(`Rename tag "${tagName}" to:`, tagName);
  if (!newName || newName.trim() === tagName) return;
  fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName.trim() })
  }).then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid') renderPublicGridView(); else fetchPublicDocs(); }
      else alert('Error: ' + (data.error || 'Failed to rename'));
    }).catch(e => { console.error(e); alert('Error renaming tag'); });
}

function changePublicTagColor(tagName, currentColor) {
  const newColor = prompt(`Enter new hex color for "${tagName}":`, currentColor || '#0d6efd');
  if (!newColor || newColor === currentColor) return;
  fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ color: newColor.trim() })
  }).then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid') renderPublicGridView(); }
      else alert('Error: ' + (data.error || 'Failed to change color'));
    }).catch(e => { console.error(e); alert('Error changing tag color'); });
}

function deletePublicTag(tagName) {
  if (!confirm(`Delete tag "${tagName}" from all documents?`)) return;
  fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, { method: 'DELETE' })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid') renderPublicGridView(); else fetchPublicDocs(); }
      else alert('Error: ' + (data.error || 'Failed to delete'));
    }).catch(e => { console.error(e); alert('Error deleting tag'); });
}

function updatePublicListSortIcons() {
  document.querySelectorAll('#public-documents-table .sortable-header .sort-icon').forEach(icon => {
    const field = icon.closest('.sortable-header').getAttribute('data-sort-field');
    icon.className = 'bi small sort-icon';
    if (publicDocsSortBy === field) {
      icon.classList.add(publicDocsSortOrder === 'asc' ? 'bi-sort-up' : 'bi-sort-down');
    } else {
      icon.classList.add('bi-arrow-down-up', 'text-muted');
    }
  });
}

function updatePublicGridSortIcons() {
  const bar = document.getElementById('public-grid-controls-bar');
  if (!bar) return;
  bar.querySelectorAll('.public-grid-sort-icon').forEach(icon => {
    const field = icon.getAttribute('data-sort');
    icon.className = 'bi ms-1 public-grid-sort-icon';
    icon.setAttribute('data-sort', field);
    if (publicGridSortBy === field) {
      icon.classList.add(field === 'name' ? (publicGridSortOrder === 'asc' ? 'bi-sort-alpha-down' : 'bi-sort-alpha-up') : (publicGridSortOrder === 'asc' ? 'bi-sort-numeric-down' : 'bi-sort-numeric-up'));
    } else {
      icon.classList.add('bi-arrow-down-up', 'text-muted');
    }
  });
}

function isColorLight(hexColor) {
  if (!hexColor) return true;
  const hex = hexColor.replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 128;
}

function updatePublicBulkTagsList() {
  const listEl = document.getElementById('public-bulk-tags-list');
  if (!listEl) return;
  if (publicWorkspaceTags.length === 0) {
    listEl.innerHTML = '<div class="text-muted w-100 text-center py-3">No tags available. Create some first.</div>';
    return;
  }
  listEl.innerHTML = '';
  publicWorkspaceTags.forEach(tag => {
    const el = document.createElement('span');
    el.className = `tag-badge ${isColorLight(tag.color) ? 'text-dark' : 'text-light'}`;
    el.style.backgroundColor = tag.color;
    el.style.border = publicBulkSelectedTags.has(tag.name) ? '3px solid #000' : '3px solid transparent';
    el.textContent = tag.name;
    el.style.cursor = 'pointer';
    el.addEventListener('click', () => {
      if (publicBulkSelectedTags.has(tag.name)) { publicBulkSelectedTags.delete(tag.name); el.style.border = '3px solid transparent'; }
      else { publicBulkSelectedTags.add(tag.name); el.style.border = '3px solid #000'; }
    });
    listEl.appendChild(el);
  });
}

async function applyPublicBulkTagChanges() {
  const action = document.getElementById('public-bulk-tag-action').value;
  const selectedTags = Array.from(publicBulkSelectedTags);
  const documentIds = Array.from(publicSelectedDocuments);
  if (documentIds.length === 0) { alert('No documents selected'); return; }
  if (selectedTags.length === 0) { alert('Please select at least one tag'); return; }

  const applyBtn = document.getElementById('public-bulk-tag-apply-btn');
  const btnText = applyBtn.querySelector('.button-text');
  const btnLoad = applyBtn.querySelector('.button-loading');
  applyBtn.disabled = true; btnText.classList.add('d-none'); btnLoad.classList.remove('d-none');

  try {
    const response = await fetch('/api/public_workspace_documents/bulk-tag', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_ids: documentIds, action: action, tags: selectedTags })
    });
    const result = await response.json();
    if (response.ok) {
      const sc = result.success?.length || 0;
      const ec = result.errors?.length || 0;
      let msg = `Tags updated for ${sc} document(s)`;
      if (ec > 0) msg += `\n${ec} document(s) had errors`;
      alert(msg);
      await loadPublicWorkspaceTags();
      fetchPublicDocs();
      publicSelectedDocuments.clear();
      const bar = document.getElementById('publicBulkActionsBar');
      if (bar) bar.style.display = 'none';
      const modal = bootstrap.Modal.getInstance(document.getElementById('publicBulkTagModal'));
      if (modal) modal.hide();
    } else { alert('Error: ' + (result.error || 'Failed to update tags')); }
  } catch (e) { console.error(e); alert('Error updating tags'); }
  finally { applyBtn.disabled = false; btnText.classList.remove('d-none'); btnLoad.classList.add('d-none'); }
}

// Expose grid/tag functions globally
window.chatWithPublicFolder = chatWithPublicFolder;
window.renamePublicTag = renamePublicTag;
window.changePublicTagColor = changePublicTagColor;
window.deletePublicTag = deletePublicTag;
window.loadPublicWorkspaceTags = loadPublicWorkspaceTags;

// === Initialize Grid/Sort/Tag Features ===
(function initPublicGridView() {
  setupPublicViewSwitcher();

  // Load saved view preference
  const savedView = localStorage.getItem('publicWorkspaceViewPreference');
  if (savedView === 'grid') {
    const gridRadio = document.getElementById('public-docs-view-grid');
    if (gridRadio) { gridRadio.checked = true; switchPublicView('grid'); }
  }

  // Wire sortable headers in list view
  document.querySelectorAll('#public-documents-table .sortable-header').forEach(th => {
    th.addEventListener('click', () => {
      const field = th.getAttribute('data-sort-field');
      if (publicDocsSortBy === field) { publicDocsSortOrder = publicDocsSortOrder === 'asc' ? 'desc' : 'asc'; }
      else { publicDocsSortBy = field; publicDocsSortOrder = 'asc'; }
      publicDocsCurrentPage = 1;
      updatePublicListSortIcons();
      fetchPublicDocs();
    });
  });

  // Wire grid sort buttons
  document.querySelectorAll('#public-grid-controls-bar .public-grid-sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.getAttribute('data-sort');
      if (publicGridSortBy === field) { publicGridSortOrder = publicGridSortOrder === 'asc' ? 'desc' : 'asc'; }
      else { publicGridSortBy = field; publicGridSortOrder = field === 'name' ? 'asc' : 'desc'; }
      renderPublicGridView();
    });
  });

  // Wire grid page size
  const gps = document.getElementById('public-grid-page-size-select');
  if (gps) gps.addEventListener('change', (e) => { publicFolderPageSize = parseInt(e.target.value, 10); publicFolderCurrentPage = 1; if (publicCurrentFolder) renderPublicFolderContents(publicCurrentFolder); });

  // Wire bulk tag modal
  const bulkTagModal = document.getElementById('publicBulkTagModal');
  if (bulkTagModal) {
    bulkTagModal.addEventListener('show.bs.modal', () => {
      document.getElementById('public-bulk-tag-doc-count').textContent = publicSelectedDocuments.size;
      publicBulkSelectedTags.clear();
      updatePublicBulkTagsList();
    });
  }
  const bulkApply = document.getElementById('public-bulk-tag-apply-btn');
  if (bulkApply) bulkApply.addEventListener('click', applyPublicBulkTagChanges);

  // Wire bulk create tag button
  const bulkCreate = document.getElementById('public-bulk-create-tag-btn');
  if (bulkCreate) {
    bulkCreate.addEventListener('click', async () => {
      const name = prompt('Enter new tag name:');
      if (!name) return;
      try {
        const resp = await fetch('/api/public_workspace_documents/tags', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag_name: name.trim() })
        });
        const data = await resp.json();
        if (resp.ok) { await loadPublicWorkspaceTags(); updatePublicBulkTagsList(); }
        else alert('Error: ' + (data.error || 'Failed to create tag'));
      } catch (e) { console.error(e); alert('Error creating tag'); }
    });
  }
})();

// ============ Public Tag Management & Selection Functions ============

function isPublicColorLight(hex) {
  if (!hex) return true;
  hex = hex.replace('#', '');
  const r = parseInt(hex.substr(0,2),16), g = parseInt(hex.substr(2,2),16), b = parseInt(hex.substr(4,2),16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 155;
}

function escapePublicHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

// --- Tag Management Modal ---
function showPublicTagManagementModal() {
  loadPublicWorkspaceTags().then(() => {
    refreshPublicTagManagementTable();
    publicTagManagementModal.show();
  });
}

function refreshPublicTagManagementTable() {
  const tbody = document.getElementById('public-existing-tags-tbody');
  if (!tbody) return;
  if (publicWorkspaceTags.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No tags yet. Add one above.</td></tr>';
    return;
  }
  let html = '';
  publicWorkspaceTags.forEach(tag => {
    const ek = escapePublicHtml(tag.name);
    html += `<tr>
      <td><div style="width:30px;height:30px;background-color:${tag.color};border-radius:4px;border:1px solid #dee2e6;"></div></td>
      <td><span class="badge" style="background-color:${tag.color};color:${isPublicColorLight(tag.color)?'#000':'#fff'};">${ek}</span></td>
      <td>${tag.count}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" onclick="window.editPublicTagInModal('${ek}','${tag.color}')"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-sm btn-outline-danger" onclick="window.deletePublicTagFromModal('${ek}')"><i class="bi bi-trash"></i></button>
      </td>
    </tr>`;
  });
  tbody.innerHTML = html;
}

function publicCancelEditMode() {
  publicEditingTag = null;
  const nameInput = document.getElementById('public-new-tag-name');
  const colorInput = document.getElementById('public-new-tag-color');
  const formTitle = document.getElementById('public-tag-form-title');
  const addBtn = document.getElementById('public-add-tag-btn');
  const cancelBtn = document.getElementById('public-cancel-edit-btn');
  if (nameInput) nameInput.value = '';
  if (colorInput) colorInput.value = '#0d6efd';
  if (formTitle) formTitle.textContent = 'Add New Tag';
  if (addBtn) { addBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Add'; addBtn.classList.remove('btn-success'); addBtn.classList.add('btn-primary'); }
  if (cancelBtn) cancelBtn.classList.add('d-none');
}

window.editPublicTagInModal = function(tagName, currentColor) {
  publicEditingTag = { originalName: tagName, originalColor: currentColor };
  const nameInput = document.getElementById('public-new-tag-name');
  const colorInput = document.getElementById('public-new-tag-color');
  const formTitle = document.getElementById('public-tag-form-title');
  const addBtn = document.getElementById('public-add-tag-btn');
  const cancelBtn = document.getElementById('public-cancel-edit-btn');
  if (nameInput) nameInput.value = tagName;
  if (colorInput) colorInput.value = currentColor;
  if (formTitle) formTitle.textContent = 'Edit Tag';
  if (addBtn) { addBtn.innerHTML = '<i class="bi bi-save"></i> Save'; addBtn.classList.remove('btn-primary'); addBtn.classList.add('btn-success'); }
  if (cancelBtn) cancelBtn.classList.remove('d-none');
  if (nameInput) nameInput.focus();
};

window.deletePublicTagFromModal = async function(tagName) {
  if (!confirm(`Delete tag "${tagName}"? This will remove it from all documents.`)) return;
  try {
    const resp = await fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, { method: 'DELETE' });
    const data = await resp.json();
    if (resp.ok) {
      await loadPublicWorkspaceTags();
      refreshPublicTagManagementTable();
    } else {
      alert('Error: ' + (data.error || 'Failed to delete tag'));
    }
  } catch (e) { console.error(e); alert('Error deleting tag'); }
};

async function handlePublicAddOrSaveTag() {
  const nameInput = document.getElementById('public-new-tag-name');
  const colorInput = document.getElementById('public-new-tag-color');
  if (!nameInput || !colorInput) return;
  const tagName = nameInput.value.trim().toLowerCase();
  const tagColor = colorInput.value;

  if (!tagName) { alert('Please enter a tag name'); return; }
  if (!/^[a-z0-9_-]+$/.test(tagName)) { alert('Tag name must contain only lowercase letters, numbers, hyphens, and underscores'); return; }

  if (publicEditingTag) {
    // Edit mode
    const nameChanged = tagName !== publicEditingTag.originalName;
    const colorChanged = tagColor !== publicEditingTag.originalColor;
    if (!nameChanged && !colorChanged) { publicCancelEditMode(); return; }
    if (nameChanged && publicWorkspaceTags.some(t => t.name === tagName && t.name !== publicEditingTag.originalName)) {
      alert('A tag with this name already exists'); return;
    }
    try {
      const body = {};
      if (nameChanged) body.new_name = tagName;
      if (colorChanged) body.color = tagColor;
      const resp = await fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(publicEditingTag.originalName)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      const data = await resp.json();
      if (resp.ok) {
        publicCancelEditMode();
        await loadPublicWorkspaceTags();
        refreshPublicTagManagementTable();
        if (publicCurrentView === 'grid') renderPublicGridView();
      } else { alert('Error: ' + (data.error || 'Failed to update tag')); }
    } catch (e) { console.error(e); alert('Error updating tag'); }
  } else {
    // Add mode
    if (publicWorkspaceTags.some(t => t.name === tagName)) { alert('A tag with this name already exists'); return; }
    try {
      const resp = await fetch('/api/public_workspace_documents/tags', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag_name: tagName, color: tagColor })
      });
      const data = await resp.json();
      if (resp.ok) {
        nameInput.value = '';
        colorInput.value = '#0d6efd';
        await loadPublicWorkspaceTags();
        refreshPublicTagManagementTable();
        if (publicCurrentView === 'grid') renderPublicGridView();
      } else { alert('Error: ' + (data.error || 'Failed to create tag')); }
    } catch (e) { console.error(e); alert('Error creating tag'); }
  }
}

// --- Tag Selection Modal ---
function showPublicTagSelectionModal() {
  loadPublicWorkspaceTags().then(() => {
    renderPublicTagSelectionList();
    publicTagSelectionModal.show();
  });
}

function renderPublicTagSelectionList() {
  const listContainer = document.getElementById('public-tag-selection-list');
  if (!listContainer) return;
  if (publicWorkspaceTags.length === 0) {
    listContainer.innerHTML = `<div class="text-center p-4">
      <p class="text-muted mb-3">No tags available yet.</p>
      <button type="button" class="btn btn-primary" id="public-create-first-tag-btn"><i class="bi bi-plus-circle"></i> Create Your First Tag</button>
    </div>`;
    document.getElementById('public-create-first-tag-btn')?.addEventListener('click', () => {
      publicTagSelectionModal.hide();
      showPublicTagManagementModal();
    });
    return;
  }
  let html = '';
  publicWorkspaceTags.forEach(tag => {
    const isSelected = publicDocSelectedTags.has(tag.name);
    const textColor = isPublicColorLight(tag.color) ? '#000' : '#fff';
    html += `<label class="list-group-item d-flex align-items-center" style="cursor:pointer;">
      <input class="form-check-input me-3" type="checkbox" value="${escapePublicHtml(tag.name)}" ${isSelected ? 'checked' : ''}>
      <span class="badge me-2" style="background-color:${tag.color};color:${textColor};">${escapePublicHtml(tag.name)}</span>
      <span class="ms-auto text-muted small">${tag.count} docs</span>
    </label>`;
  });
  listContainer.innerHTML = html;
  listContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', (e) => {
      if (e.target.checked) publicDocSelectedTags.add(e.target.value);
      else publicDocSelectedTags.delete(e.target.value);
    });
  });
}

// --- Document Tags Display ---
function updatePublicDocTagsDisplay() {
  const container = document.getElementById('public-doc-selected-tags-container');
  if (!container) return;
  if (publicDocSelectedTags.size === 0) {
    container.innerHTML = '<span class="text-muted small">No tags selected</span>';
    return;
  }
  let html = '';
  publicDocSelectedTags.forEach(tagName => {
    const tag = publicWorkspaceTags.find(t => t.name === tagName);
    const color = tag ? tag.color : '#6c757d';
    const textColor = isPublicColorLight(color) ? '#000' : '#fff';
    html += `<span class="badge" style="background-color:${color};color:${textColor};">
      ${escapePublicHtml(tagName)}
      <i class="bi bi-x" style="cursor:pointer;" onclick="window.removePublicDocSelectedTag('${escapePublicHtml(tagName)}')"></i>
    </span>`;
  });
  container.innerHTML = html;
}

window.removePublicDocSelectedTag = function(tagName) {
  publicDocSelectedTags.delete(tagName);
  updatePublicDocTagsDisplay();
};

// --- Wire up events ---
(function initPublicTagManagement() {
  // Manage Tags button (next to view toggle)
  const manageTagsBtn = document.getElementById('public-manage-tags-btn');
  if (manageTagsBtn) {
    manageTagsBtn.addEventListener('click', showPublicTagManagementModal);
  }

  // Manage Tags button inside metadata modal (opens Select Tags)
  const docManageTagsBtn = document.getElementById('public-doc-manage-tags-btn');
  if (docManageTagsBtn) {
    docManageTagsBtn.addEventListener('click', () => {
      showPublicTagSelectionModal();
    });
  }

  // Tag Selection Done button
  const tagSelectDoneBtn = document.getElementById('public-tag-selection-done-btn');
  if (tagSelectDoneBtn) {
    tagSelectDoneBtn.addEventListener('click', () => {
      updatePublicDocTagsDisplay();
      publicTagSelectionModal.hide();
    });
  }

  // Open Manage Tags from within Selection modal
  const openMgmtBtn = document.getElementById('public-open-tag-mgmt-btn');
  if (openMgmtBtn) {
    openMgmtBtn.addEventListener('click', () => {
      publicTagSelectionModal.hide();
      showPublicTagManagementModal();
    });
  }

  // Add/Save tag button in management modal
  const addTagBtn = document.getElementById('public-add-tag-btn');
  if (addTagBtn) addTagBtn.addEventListener('click', handlePublicAddOrSaveTag);

  // Cancel edit button
  const cancelEditBtn = document.getElementById('public-cancel-edit-btn');
  if (cancelEditBtn) cancelEditBtn.addEventListener('click', publicCancelEditMode);

  // Enter key on tag name input
  const tagNameInput = document.getElementById('public-new-tag-name');
  if (tagNameInput) {
    tagNameInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); handlePublicAddOrSaveTag(); }
    });
  }

  // When tag management modal closes, reset edit mode
  document.getElementById('publicTagManagementModal')?.addEventListener('hidden.bs.modal', () => {
    publicCancelEditMode();
  });
})();
