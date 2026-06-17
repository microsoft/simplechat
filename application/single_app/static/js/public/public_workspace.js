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
let publicLastCardSelectionAnchorId = null;

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
let publicFileDownloadsEnabled = false;
let publicBulkSelectedTags = new Set();
let publicDocSelectedTags = new Set();
let publicEditingTag = null;
let publicFileSyncTagSelectionDone = null;
window.currentPublicStatus = window.currentPublicStatus || 'active';

// Modals
const publicPromptModal = new bootstrap.Modal(document.getElementById('publicPromptModal'));
const publicDocMetadataModal = new bootstrap.Modal(document.getElementById('publicDocMetadataModal'));
const publicTagManagementModal = new bootstrap.Modal(document.getElementById('publicTagManagementModal'));
const publicTagSelectionModal = new bootstrap.Modal(document.getElementById('publicTagSelectionModal'));
const publicDocumentDeleteModalElement = document.getElementById('publicDocumentDeleteModal');
const publicDocumentDeleteModal = publicDocumentDeleteModalElement ? new bootstrap.Modal(publicDocumentDeleteModalElement) : null;
const publicDocumentDeleteModalTitle = document.getElementById('publicDocumentDeleteModalLabel');
const publicDocumentDeleteModalBody = document.getElementById('publicDocumentDeleteModalBody');
const publicDeleteCurrentBtn = document.getElementById('publicDeleteCurrentBtn');
const publicDeleteAllBtn = document.getElementById('publicDeleteAllBtn');

function getPublicDeleteModalContent(documentCount) {
  if (documentCount === 1) {
    return {
      title: 'Delete Public Document',
      body: `
        <p class="mb-2">Choose how to delete this public document revision.</p>
        <p class="mb-2"><strong>Delete Current Version</strong> removes the visible revision and keeps older revisions for future comparison.</p>
        <p class="mb-0"><strong>Delete All Versions</strong> permanently removes every stored revision for this document.</p>
      `,
    };
  }

  return {
    title: 'Delete Selected Public Documents',
    body: `
      <p class="mb-2">Choose how to delete ${documentCount} selected current public document revision(s).</p>
      <p class="mb-2"><strong>Delete Current Version</strong> removes only the visible revision for each selected document and keeps older revisions.</p>
      <p class="mb-0"><strong>Delete All Versions</strong> permanently removes every stored revision for each selected document.</p>
    `,
  };
}

function showPublicDocumentDeleteFeedback(message, variant = 'danger') {
  if (typeof window.showToast === 'function') {
    window.showToast(message, variant);
    return;
  }

  let container = document.getElementById('publicDocumentDeleteFeedbackContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'publicDocumentDeleteFeedbackContainer';
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    document.body.appendChild(container);
  }

  if (window.bootstrap && typeof window.bootstrap.Toast === 'function') {
    const toastElement = document.createElement('div');
    toastElement.className = `toast align-items-center text-white bg-${variant} border-0`;
    toastElement.setAttribute('role', 'alert');
    toastElement.setAttribute('aria-live', 'assertive');
    toastElement.setAttribute('aria-atomic', 'true');

    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex';

    const body = document.createElement('div');
    body.className = 'toast-body';
    body.textContent = message;

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close btn-close-white me-2 m-auto';
    closeButton.setAttribute('data-bs-dismiss', 'toast');
    closeButton.setAttribute('aria-label', 'Close');

    wrapper.appendChild(body);
    wrapper.appendChild(closeButton);
    toastElement.appendChild(wrapper);
    container.appendChild(toastElement);

    const toast = new window.bootstrap.Toast(toastElement);
    toast.show();
    toastElement.addEventListener('hidden.bs.toast', () => {
      toastElement.remove();
    });
    return;
  }

  const alertElement = document.createElement('div');
  alertElement.className = `alert alert-${variant} alert-dismissible fade show mb-2`;
  alertElement.setAttribute('role', 'alert');

  const body = document.createElement('span');
  body.textContent = message;

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'btn-close';
  closeButton.setAttribute('data-bs-dismiss', 'alert');
  closeButton.setAttribute('aria-label', 'Close');

  alertElement.appendChild(body);
  alertElement.appendChild(closeButton);
  container.appendChild(alertElement);
}

function getPublicDownloadFileNameFromResponse(response, fallbackFileName) {
  const disposition = response.headers.get('Content-Disposition') || response.headers.get('content-disposition') || '';
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch && encodedMatch[1]) {
    try {
      return decodeURIComponent(encodedMatch[1].replace(/"/g, ''));
    } catch (error) {
      console.warn('Unable to decode public download filename', error);
    }
  }

  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  if (plainMatch && plainMatch[1]) {
    return plainMatch[1];
  }

  return fallbackFileName;
}

async function downloadPublicFile(endpoint, options = {}, fallbackFileName = 'document') {
  const response = await fetch(endpoint, options);
  if (!response.ok) {
    let message = 'Unable to download document';
    try {
      const errorData = await response.json();
      message = errorData.error || message;
    } catch (error) {
      message = response.statusText || message;
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const fileName = getPublicDownloadFileNameFromResponse(response, fallbackFileName);
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = fileName;
  link.classList.add('d-none');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}

async function downloadPublicDocumentFile(documentId, event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (!publicFileDownloadsEnabled) {
    showPublicDocumentDeleteFeedback('File downloads are disabled for this public workspace.', 'warning');
    return;
  }

  try {
    await downloadPublicFile(`/api/public_documents/${encodeURIComponent(documentId)}/download`);
  } catch (error) {
    console.error('Error downloading public document:', error);
    showPublicDocumentDeleteFeedback(error.message || 'Unable to download document', 'danger');
  }
}
window.downloadPublicDocumentFile = downloadPublicDocumentFile;

function isPublicDocumentDeleteModalReady() {
  return Boolean(
    publicDocumentDeleteModal &&
    publicDocumentDeleteModalElement &&
    publicDocumentDeleteModalElement.isConnected &&
    publicDocumentDeleteModalBody &&
    publicDocumentDeleteModalBody.isConnected &&
    publicDeleteCurrentBtn &&
    publicDeleteCurrentBtn.isConnected &&
    publicDeleteAllBtn &&
    publicDeleteAllBtn.isConnected
  );
}

function promptPublicDeleteMode(documentCount = 1) {
  if (!isPublicDocumentDeleteModalReady()) {
    showPublicDocumentDeleteFeedback('Delete confirmation dialog is unavailable. Refresh the page and try again.');
    return Promise.resolve(null);
  }

  const modalContent = getPublicDeleteModalContent(documentCount);
  if (publicDocumentDeleteModalTitle) {
    publicDocumentDeleteModalTitle.textContent = modalContent.title;
  }
  publicDocumentDeleteModalBody.innerHTML = modalContent.body;

  return new Promise((resolve) => {
    let settled = false;
    let selectedValue = null;

    const cleanup = () => {
      publicDocumentDeleteModalElement.removeEventListener('hidden.bs.modal', handleHidden);
      publicDeleteCurrentBtn.removeEventListener('click', handleCurrentOnly);
      publicDeleteAllBtn.removeEventListener('click', handleAllVersions);
    };

    const finalize = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(selectedValue);
    };

    const hideWithValue = (value) => {
      if (selectedValue) {
        return;
      }
      selectedValue = value;
      publicDocumentDeleteModal.hide();
    };

    const handleHidden = () => finalize();
    const handleCurrentOnly = () => hideWithValue('current_only');
    const handleAllVersions = () => hideWithValue('all_versions');

    publicDocumentDeleteModalElement.addEventListener('hidden.bs.modal', handleHidden);
    publicDeleteCurrentBtn.addEventListener('click', handleCurrentOnly);
    publicDeleteAllBtn.addEventListener('click', handleAllVersions);
    publicDocumentDeleteModal.show();
  });
}

function promptPublicSyncedDocumentDeleteAction(deleteInfo) {
  if (!isPublicDocumentDeleteModalReady()) {
    showPublicDocumentDeleteFeedback('Delete confirmation dialog is unavailable. Refresh the page and try again.');
    return Promise.resolve(null);
  }

  if (publicDocumentDeleteModalTitle) {
    publicDocumentDeleteModalTitle.textContent = 'Delete Synced Public Document';
  }

  const body = document.createElement('div');
  const intro = document.createElement('p');
  intro.className = 'mb-2';
  intro.textContent = deleteInfo.message || 'This document was created by File Sync.';
  body.appendChild(intro);

  if (deleteInfo.file_sync && deleteInfo.file_sync.relative_path) {
    const path = document.createElement('p');
    path.className = 'mb-2 small text-muted';
    path.textContent = deleteInfo.file_sync.relative_path;
    body.appendChild(path);
  }

  const choice = document.createElement('p');
  choice.className = 'mb-0';
  choice.textContent = 'Choose whether this remote file should be ignored by future sync runs.';
  body.appendChild(choice);
  publicDocumentDeleteModalBody.replaceChildren(body);

  const currentLabel = publicDeleteCurrentBtn.textContent;
  const allLabel = publicDeleteAllBtn.textContent;
  publicDeleteCurrentBtn.textContent = 'Delete Only';
  publicDeleteAllBtn.textContent = 'Delete and Ignore Remote';

  return new Promise((resolve) => {
    let settled = false;
    let selectedValue = null;

    const cleanup = () => {
      publicDocumentDeleteModalElement.removeEventListener('hidden.bs.modal', handleHidden);
      publicDeleteCurrentBtn.removeEventListener('click', handleDeleteOnly);
      publicDeleteAllBtn.removeEventListener('click', handleIgnoreRemote);
      publicDeleteCurrentBtn.textContent = currentLabel;
      publicDeleteAllBtn.textContent = allLabel;
    };

    const finalize = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(selectedValue);
    };

    const hideWithValue = (value) => {
      if (selectedValue) {
        return;
      }
      selectedValue = value;
      publicDocumentDeleteModal.hide();
    };

    const handleHidden = () => finalize();
    const handleDeleteOnly = () => hideWithValue('delete_only');
    const handleIgnoreRemote = () => hideWithValue('ignore_remote');

    publicDocumentDeleteModalElement.addEventListener('hidden.bs.modal', handleHidden);
    publicDeleteCurrentBtn.addEventListener('click', handleDeleteOnly);
    publicDeleteAllBtn.addEventListener('click', handleIgnoreRemote);
    publicDocumentDeleteModal.show();
  });
}

async function requestPublicDocumentDeletion(documentId, deleteMode, fileSyncDeleteAction = null) {
  const query = new URLSearchParams({ delete_mode: deleteMode });
  if (fileSyncDeleteAction) {
    query.set('file_sync_delete_action', fileSyncDeleteAction);
  }
  const response = await fetch(`/api/public_documents/${documentId}?${query.toString()}`, { method: 'DELETE' });

  let responseData = {};
  try {
    responseData = await response.json();
  } catch (error) {
    responseData = {};
  }

  if (!response.ok) {
    if (response.status === 409 && responseData.error === 'synced_document_delete_requires_action' && !fileSyncDeleteAction) {
      const syncAction = await promptPublicSyncedDocumentDeleteAction(responseData);
      if (!syncAction) {
        throw { error: 'Deletion canceled' };
      }
      return requestPublicDocumentDeletion(documentId, deleteMode, syncAction);
    }
    throw responseData.error ? responseData : { error: `Server responded with status ${response.status}` };
  }

  return responseData;
}

// Editors
let publicSimplemde = null;
const publicPromptContentEl = document.getElementById('public-prompt-content');
if (publicPromptContentEl && window.SimpleMDE) {
  publicSimplemde = new SimpleMDE({ element: publicPromptContentEl, spellChecker:false, autoDownloadFontAwesome: false });
}
document.getElementById('publicPromptModal')?.addEventListener('shown.bs.modal', () => {
  if (publicSimplemde?.codemirror) {
    publicSimplemde.codemirror.refresh();
    publicSimplemde.codemirror.focus();
  }
});

// DOM elements
const publicSelect = document.getElementById('public-select');
const publicDropdownBtn = document.getElementById('public-dropdown-button');
const publicDropdownItems = document.getElementById('public-dropdown-items');
const publicSearchInput = document.getElementById('public-search-input');
const publicSearchContainer = publicSearchInput ? publicSearchInput.closest('.public-search-container') : null;
const btnMyPublics = document.getElementById('btn-my-publics');
const uploadSection = document.getElementById('upload-public-section');
const uploadHr = document.getElementById('public-upload-hr');
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn') || document.getElementById('public-upload-btn');
const uploadStatus = document.getElementById('upload-status');
const publicDocsTableBody = document.querySelector('#public-documents-table tbody');
const publicDocumentsCardView = document.getElementById('public-documents-card-view');
const publicDocsPagination = document.getElementById('public-docs-pagination-container');
const publicDocsPageSizeSelect = document.getElementById('public-docs-page-size-select');
const publicDocsSearchInput = document.getElementById('public-docs-search-input');
const docsApplyBtn = document.getElementById('public-docs-apply-filters-btn');
const docsClearBtn = document.getElementById('public-docs-clear-filters-btn');

const publicPromptsTableBody = document.querySelector('#public-prompts-table tbody');
const publicPromptsListView = document.getElementById('public-prompts-list-view');
const publicPromptsCardView = document.getElementById('public-prompts-card-view');
const publicPromptsPagination = document.getElementById('public-prompts-pagination-container');
const publicPromptsPageSizeSelect = document.getElementById('public-prompts-page-size-select');
const publicPromptsSearchInput = document.getElementById('public-prompts-search-input');
const promptsApplyBtn = document.getElementById('public-prompts-apply-filters-btn');
const promptsClearBtn = document.getElementById('public-prompts-clear-filters-btn');
const createPublicPromptBtn = document.getElementById('create-public-prompt-btn');
const publicPromptForm = document.getElementById('public-prompt-form');
const publicPromptIdEl = document.getElementById('public-prompt-id');
const publicPromptNameEl = document.getElementById('public-prompt-name');

function setPublicTableMessage(tableBody, columnSpan, message) {
  if (!tableBody) return;

  const row = document.createElement('tr');
  const cell = document.createElement('td');
  cell.colSpan = columnSpan;
  cell.className = 'text-center p-4 text-muted';
  cell.textContent = message;
  row.appendChild(cell);
  tableBody.replaceChildren(row);
}

function filterPublicDropdownItems() {
  if (!publicDropdownItems) return;

  const searchTerm = publicSearchInput ? publicSearchInput.value.toLowerCase().trim() : '';
  let visibleCount = 0;

  document.querySelectorAll('#public-dropdown-items .dropdown-item').forEach((item) => {
    const workspaceName = item.textContent.toLowerCase();
    const isVisible = workspaceName.includes(searchTerm);
    item.classList.toggle('d-none', !isVisible);
    if (isVisible) {
      visibleCount += 1;
    }
  });

  const noMatchesItem = document.getElementById('public-dropdown-no-matches');
  if (noMatchesItem) {
    noMatchesItem.classList.toggle('d-none', !searchTerm || visibleCount > 0);
  }
}

function updatePublicDropdownSearchVisibility() {
  if (!publicSearchContainer || !publicSearchInput) return;

  const shouldShowSearch = userPublics.length > 0;
  publicSearchContainer.classList.toggle('d-none', !shouldShowSearch);
  if (!shouldShowSearch) {
    publicSearchInput.value = '';
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', ()=>{
  fetchUserPublics().then(()=>{
    if(activePublicId) loadActivePublicData();
    else {
      const noActivePublicMessage = userPublics.length === 0
        ? 'No public workspaces are available. Select My Workspaces to create one.'
        : 'Please select an active public workspace.';
      setPublicTableMessage(publicDocsTableBody, 4, noActivePublicMessage);
      setPublicTableMessage(publicPromptsTableBody, 2, noActivePublicMessage);
      renderPublicPromptsEmptyState(noActivePublicMessage);
    }
  });

  if (publicSearchInput) {
    publicSearchInput.addEventListener('input', filterPublicDropdownItems);
    publicSearchInput.addEventListener('click', (event) => {
      event.stopPropagation();
    });
  }

  if (btnMyPublics) btnMyPublics.onclick = ()=> window.location.href = '/profile?tab=public-workspaces';

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
  setupPublicPromptsViewSwitcher();

  // Add tab change event listeners to load data when switching tabs
  document.getElementById('public-prompts-tab-btn').addEventListener('shown.bs.tab', () => {
    if (activePublicId) fetchPublicPrompts();
  });
  
  document.getElementById('public-docs-tab-btn').addEventListener('shown.bs.tab', () => {
    if (!activePublicId) return;
    if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') {
      renderPublicGridView();
    } else {
      fetchPublicDocs();
    }
  });

  // --- Document selection event listeners ---
  // Event delegation for document checkboxes
  document.addEventListener('change', function(event) {
    if (event.target.classList.contains('document-checkbox')) {
      const documentId = event.target.getAttribute('data-document-id');
      if (window.updatePublicSelectedDocuments) {
        window.updatePublicSelectedDocuments(documentId, event.target.checked);
      }
    }

    if (event.target.classList.contains('document-select-all-checkbox')) {
      togglePublicSelectAllDocuments(event.target.checked);
    }
  });

  // Bulk action buttons
  const publicDeleteSelectedBtn = document.getElementById('public-delete-selected-btn');
  const publicDownloadSelectedBtn = document.getElementById('public-download-selected-btn');
  const publicClearSelectionBtn = document.getElementById('public-clear-selection-btn');
  const publicChatSelectedBtn = document.getElementById('public-chat-selected-btn');

  if (publicDeleteSelectedBtn) publicDeleteSelectedBtn.addEventListener('click', deletePublicSelectedDocuments);
  if (publicDownloadSelectedBtn) publicDownloadSelectedBtn.addEventListener('click', downloadPublicSelectedDocuments);
  if (publicClearSelectionBtn) publicClearSelectionBtn.addEventListener('click', clearPublicSelection);
  if (publicChatSelectedBtn) publicChatSelectedBtn.addEventListener('click', chatWithPublicSelected);
  document.getElementById('public-toggle-selection-btn')?.addEventListener('click', togglePublicSelectionMode);
  document.addEventListener('click', handlePublicDocumentCardClick);
});

// Fetch User's Public Workspaces
async function fetchUserPublics(){
  const selectedPublicText = publicDropdownBtn.querySelector('.selected-public-text');
  publicSelect.disabled = true;
  publicDropdownBtn.disabled = true;
  if (btnMyPublics) btnMyPublics.disabled = true;
  selectedPublicText.textContent = 'Loading...';
  publicDropdownItems.innerHTML = '<div class="text-center py-2"><div class="spinner-border spinner-border-sm"></div> Loading...</div>';
  try {
    const r = await fetch('/api/public_workspaces?page_size=1000');
    if(!r.ok) throw await r.json();
    const data = await r.json();
    userPublics = Array.isArray(data) ? data : (data.workspaces || []);
    publicSelect.innerHTML=''; publicDropdownItems.innerHTML='';
    if (publicSearchInput) publicSearchInput.value = '';
    updatePublicDropdownSearchVisibility();
    let found=false;
    if (userPublics.length === 0) {
      activePublicId = null;
      userRoleInActivePublic = null;
      activePublicName = '';
      selectedPublicText.textContent = 'No workspaces yet';

      const emptyItem = document.createElement('div');
      emptyItem.className = 'dropdown-item-text text-muted small text-wrap';
      emptyItem.textContent = 'No public workspaces are available. Select My Workspaces to create one.';
      publicDropdownItems.appendChild(emptyItem);

      const emptyOption = document.createElement('option');
      emptyOption.disabled = true;
      emptyOption.selected = true;
      emptyOption.textContent = 'No workspaces available';
      publicSelect.appendChild(emptyOption);
    } else {
      userPublics.forEach(w=>{
        const opt = document.createElement('option'); opt.value=w.id; opt.textContent=w.name; publicSelect.append(opt);
        const btn = document.createElement('button'); btn.type='button'; btn.className='dropdown-item'; btn.textContent=w.name; btn.dataset.publicId=w.id;
        btn.onclick = ()=>{
          publicSelect.value=w.id;
          selectedPublicText.textContent=w.name;
          document.querySelectorAll('#public-dropdown-items .dropdown-item').forEach(i=>i.classList.remove('active'));
          btn.classList.add('active');
          const dropdownInstance = bootstrap.Dropdown.getInstance(publicDropdownBtn);
          if (dropdownInstance) dropdownInstance.hide();
          activateSelectedPublic(w.id);
        };
        publicDropdownItems.append(btn);
        if(w.isActive){ publicSelect.value=w.id; selectedPublicText.textContent=w.name; btn.classList.add('active'); activePublicId=w.id; userRoleInActivePublic=w.userRole; activePublicName=w.name; found=true; }
      });
      const noMatchesItem = document.createElement('div');
      noMatchesItem.id = 'public-dropdown-no-matches';
      noMatchesItem.className = 'dropdown-item-text text-muted small d-none';
      noMatchesItem.textContent = 'No matching workspaces';
      publicDropdownItems.appendChild(noMatchesItem);
      if(!found){ activePublicId=null; userRoleInActivePublic=null; activePublicName=''; selectedPublicText.textContent = 'Select a workspace...'; }
    }
    filterPublicDropdownItems();
    updatePublicRoleDisplay();
  } catch(err){ console.error(err); publicDropdownItems.innerHTML='<div class="dropdown-item disabled">Error loading</div>'; selectedPublicText.textContent='Error'; }
  finally{ publicSelect.disabled=false; publicDropdownBtn.disabled=false; if (btnMyPublics) btnMyPublics.disabled=false; }
}

async function activateSelectedPublic(publicId){
  const selectedPublicText = publicDropdownBtn.querySelector('.selected-public-text');
  const newId = publicId || publicSelect.value;
  if(!newId || newId===activePublicId) return;

  const selectedOption = Array.from(publicSelect.options).find(option => option.value === newId);
  const selectedWorkspaceName = selectedOption?.textContent || selectedPublicText?.textContent || 'selected workspace';

  publicDropdownBtn.disabled = true;
  if (selectedPublicText) selectedPublicText.textContent = `Switching to ${selectedWorkspaceName}...`;
  try {
    const r=await fetch('/api/public_workspaces/setActive',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspaceId:newId})});
    if(!r.ok) throw await r.json();
    await fetchUserPublics();
    if(activePublicId===newId) loadActivePublicData();
  }
  catch(e){
    console.error(e);
    showPublicDocumentDeleteFeedback(`Error setting active workspace: ${e.error||e.message||'Unknown error'}`, 'danger');
    await fetchUserPublics().catch(refreshError => console.error(refreshError));
  }
  finally{ publicDropdownBtn.disabled=false; }
}

function updatePublicRoleDisplay(){
  const display = document.getElementById('user-public-role-display');
  const activeWorkspace = userPublics.find(workspace => workspace.id === activePublicId) || null;
  if (activePublicId) {
    const roleEl = document.getElementById('user-public-role');
    if (roleEl) roleEl.textContent = userRoleInActivePublic;
    if (display) display.classList.remove('d-none');
    if (uploadSection) uploadSection.style.display = ['Owner','Admin','DocumentManager'].includes(userRoleInActivePublic) ? 'block' : 'none';
    // Control visibility of Settings tab (only for Owners and Admins)
    const settingsTabNav = document.getElementById('public-settings-tab-nav');
    const canManageSettings = ['Owner', 'Admin'].includes(userRoleInActivePublic);
    if (settingsTabNav) {
      settingsTabNav.classList.toggle('d-none', !canManageSettings);
    }
    updateActivePublicHero(activeWorkspace);
    updateManagePublicWorkspaceLink(activeWorkspace);
  } else {
    if (display) display.classList.add('d-none');
    updateActivePublicHero(null);
    updateManagePublicWorkspaceLink(null);
  }
}

function updateActivePublicHero(activeWorkspace) {
  const heroCard = document.getElementById('active-public-hero');
  const heroName = document.getElementById('active-public-hero-name');
  const heroOwner = document.getElementById('active-public-hero-owner');
  const heroDescription = document.getElementById('active-public-hero-description');
  const heroInitial = document.getElementById('active-public-hero-initial');
  const heroLogo = document.getElementById('active-public-hero-logo');

  if (!heroCard || !heroName || !heroOwner || !heroDescription || !heroInitial || !heroLogo) {
    return;
  }

  if (!activeWorkspace) {
    heroCard.classList.add('d-none');
    heroLogo.src = '';
    heroLogo.classList.add('d-none');
    heroInitial.classList.remove('d-none');
    return;
  }

  const heroColor = activeWorkspace.heroColor || '#0078d4';
  heroCard.style.setProperty('--workspace-hero-color', heroColor);
  heroCard.style.setProperty('--workspace-hero-color-dark', adjustWorkspaceHeroColor(heroColor, -30));
  heroName.textContent = activeWorkspace.name || 'Unnamed Workspace';
  heroOwner.textContent = activeWorkspace.owner?.displayName || 'Unknown';
  heroDescription.textContent = activeWorkspace.description || 'No description provided';
  heroInitial.textContent = (activeWorkspace.name || 'P').charAt(0).toUpperCase();
  heroCard.classList.remove('d-none');

  if (activeWorkspace.hasLogo) {
    heroLogo.onerror = function () {
      heroLogo.src = '';
      heroLogo.classList.add('d-none');
      heroInitial.classList.remove('d-none');
    };
    heroLogo.src = `/api/public_workspaces/${activeWorkspace.id}/logo?v=${encodeURIComponent(activeWorkspace.logoVersion || 1)}`;
    heroLogo.classList.remove('d-none');
    heroInitial.classList.add('d-none');
    return;
  }

  heroLogo.src = '';
  heroLogo.classList.add('d-none');
  heroInitial.classList.remove('d-none');
}

function updateManagePublicWorkspaceLink(activeWorkspace) {
  const manageButton = document.getElementById('manage-active-public-btn');
  if (!manageButton) {
    return;
  }

  if (!activeWorkspace?.id) {
    manageButton.classList.add('d-none');
    manageButton.removeAttribute('href');
    return;
  }

  manageButton.href = `/public_workspaces/${encodeURIComponent(activeWorkspace.id)}`;
  manageButton.classList.remove('d-none');
}

function adjustWorkspaceHeroColor(color, percent) {
  const numericColor = parseInt(String(color).replace('#', ''), 16);
  const amount = Math.round(2.55 * percent);
  const red = (numericColor >> 16) + amount;
  const green = ((numericColor >> 8) & 0x00FF) + amount;
  const blue = (numericColor & 0x0000FF) + amount;

  return `#${(
    0x1000000 +
    (red < 255 ? (red < 1 ? 0 : red) : 255) * 0x10000 +
    (green < 255 ? (green < 1 ? 0 : green) : 255) * 0x100 +
    (blue < 255 ? (blue < 1 ? 0 : blue) : 255)
  ).toString(16).slice(1)}`;
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
  window.currentPublicStatus = status || 'active';
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

function isPendingGeneratedArtifactDocument(doc) {
  return String((doc && doc.generated_artifact_promotion_status) || '').trim().toLowerCase() === 'pending_approval';
}

function showPublicWorkspaceMessage(message, variant = 'info') {
  if (typeof window.showToast === 'function') {
    window.showToast(message, variant);
    return;
  }

  showPublicDocumentDeleteFeedback(message, variant);
}

function buildPublicGeneratedArtifactApproveButton(documentId, fileName) {
  const approveButton = document.createElement('button');
  approveButton.type = 'button';
  approveButton.className = 'btn btn-sm btn-outline-success me-1';
  approveButton.setAttribute(
    'aria-label',
    `Approve generated artifact ${String(fileName || 'document').trim() || 'document'}`
  );

  const icon = document.createElement('i');
  icon.className = 'bi bi-check2-circle me-1';
  icon.setAttribute('aria-hidden', 'true');
  approveButton.appendChild(icon);
  approveButton.appendChild(document.createTextNode('Approve'));

  approveButton.addEventListener('click', () => {
    window.approvePublicGeneratedArtifactDocument(documentId, approveButton);
  });

  return approveButton;
}

function buildPublicGeneratedArtifactDenyButton(documentId, fileName) {
  const denyButton = document.createElement('button');
  denyButton.type = 'button';
  denyButton.className = 'btn btn-sm btn-outline-danger me-1';
  denyButton.setAttribute(
    'aria-label',
    `Deny generated artifact ${String(fileName || 'document').trim() || 'document'}`
  );

  const icon = document.createElement('i');
  icon.className = 'bi bi-x-circle me-1';
  icon.setAttribute('aria-hidden', 'true');
  denyButton.appendChild(icon);
  denyButton.appendChild(document.createTextNode('Deny'));

  denyButton.addEventListener('click', () => {
    window.denyPublicGeneratedArtifactDocument(documentId, denyButton);
  });

  return denyButton;
}

function buildPublicGeneratedArtifactCancelButton(documentId, fileName) {
  const cancelButton = document.createElement('button');
  cancelButton.type = 'button';
  cancelButton.className = 'btn btn-sm btn-outline-secondary me-1';
  cancelButton.setAttribute(
    'aria-label',
    `Cancel generated artifact ${String(fileName || 'document').trim() || 'document'}`
  );

  const icon = document.createElement('i');
  icon.className = 'bi bi-x-lg me-1';
  icon.setAttribute('aria-hidden', 'true');
  cancelButton.appendChild(icon);
  cancelButton.appendChild(document.createTextNode('Cancel'));

  cancelButton.addEventListener('click', () => {
    window.cancelPublicGeneratedArtifactDocument(documentId, cancelButton);
  });

  return cancelButton;
}

function getPublicGeneratedArtifactRequesterId(doc) {
  return String((doc && (doc.generated_artifact_requested_by_user_id || doc.user_id)) || '').trim();
}

function getCurrentWorkspaceUserId() {
  return String(window.current_user_id || window.currentUser?.id || window.currentUser?.user_id || '').trim();
}

function getPublicGeneratedArtifactActionButtons(doc) {
  if (!isPendingGeneratedArtifactDocument(doc)) {
    return [];
  }

  const actionButtons = [];
  const documentId = String((doc && doc.id) || '').trim();
  if (!documentId) {
    return actionButtons;
  }

  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  const requesterId = getPublicGeneratedArtifactRequesterId(doc);
  const currentUserId = getCurrentWorkspaceUserId();
  const isRequester = !!currentUserId && requesterId === currentUserId;
  const fileName = doc.file_name || 'document';

  if (canManage && window.currentPublicStatus === 'active') {
    actionButtons.push(buildPublicGeneratedArtifactApproveButton(documentId, fileName));
  }

  if (canManage && !isRequester) {
    actionButtons.push(buildPublicGeneratedArtifactDenyButton(documentId, fileName));
  }

  if (isRequester) {
    actionButtons.push(buildPublicGeneratedArtifactCancelButton(documentId, fileName));
  }

  return actionButtons;
}

function prependPublicGeneratedArtifactActionButtons(actionsCell, doc) {
  if (!(actionsCell instanceof HTMLElement)) {
    return;
  }

  const actionButtons = getPublicGeneratedArtifactActionButtons(doc);
  if (!actionButtons.length) {
    return;
  }

  const fragment = document.createDocumentFragment();
  actionButtons.forEach((button) => fragment.appendChild(button));
  actionsCell.prepend(fragment);
}

function wirePublicFolderGeneratedArtifactApproveButtons(docs) {
  const rows = document.querySelectorAll('#public-folder-docs-table tbody tr');
  docs.forEach((doc, index) => {
    const row = rows[index];
    const actionsCell = row && row.children ? row.children[3] : null;
    prependPublicGeneratedArtifactActionButtons(actionsCell, doc);
  });
}

function loadActivePublicData(){
  const activeTab = document.querySelector('#publicWorkspaceTab .nav-link.active').dataset.bsTarget;
  if(activeTab==='#public-docs-tab') {
    if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView(); else fetchPublicDocs();
  } else fetchPublicPrompts();
  updatePublicRoleDisplay(); updatePublicPromptsRoleUI(); updateWorkspaceStatusAlert();
}

function getPublicDocumentProcessingState(doc) {
  const pctString = String((doc.percentage_complete ?? doc.percentage) || '0');
  const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
  const docStatus = doc.status || '';
  const normalizedStatus = docStatus.toLowerCase();
  const hasError = normalizedStatus.includes('error') || normalizedStatus.includes('failed');
  const isComplete = pct >= 100 || normalizedStatus.includes('complete') || hasError;
  return { pct, docStatus, hasError, isComplete };
}

function getPublicDocumentIcon(fileName) {
  const extension = String(fileName || '').split('.').pop().toLowerCase();
  const iconMap = {
    pdf: 'bi-file-earmark-pdf',
    doc: 'bi-file-earmark-word',
    docx: 'bi-file-earmark-word',
    xls: 'bi-file-earmark-excel',
    xlsx: 'bi-file-earmark-excel',
    csv: 'bi-file-earmark-spreadsheet',
    ppt: 'bi-file-earmark-ppt',
    pptx: 'bi-file-earmark-ppt',
    txt: 'bi-file-earmark-text',
    md: 'bi-file-earmark-text',
    json: 'bi-file-earmark-code',
    html: 'bi-file-earmark-code',
  };
  return iconMap[extension] || 'bi-file-earmark-text';
}

function truncatePublicDocumentText(text, maxLength = 90) {
  const value = String(text || '').trim();
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value;
}

function getPublicDocumentSummaryText(doc) {
  return doc.abstract || doc.summary || doc.description || 'No abstract available.';
}

function appendPublicTextElement(parent, tagName, className, text, title) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  if (title) element.title = title;
  parent.appendChild(element);
  return element;
}

function isPublicSyncedDocument(doc) {
  return !!(doc && doc.file_sync && typeof doc.file_sync === 'object');
}

function getPublicDocumentSyncSourceLabel(doc) {
  if (!isPublicSyncedDocument(doc)) {
    return '';
  }

  const syncMetadata = doc.file_sync;
  return syncMetadata.source_name
    || syncMetadata.relative_path
    || syncMetadata.remote_path
    || 'File Sync';
}

function getPublicDocumentSyncTypeConfig(doc) {
  const sourceType = String(doc?.file_sync?.source_type || 'smb').trim().toLowerCase();
  const sourceTypeMap = {
    smb: { label: 'SMB', className: 'bg-primary text-white', title: 'Managed by File Sync from an SMB source.' },
    azure_files: { label: 'Azure Files', className: 'bg-info text-dark', title: 'Managed by File Sync from Azure Files.' },
    m365sp: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
    m365_sp: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
    m365_sharepoint: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
    sharepoint_online: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
    one_drive: { label: 'OneDrive', className: 'bg-dark text-white', title: 'Managed by File Sync from OneDrive.' },
    onedrive: { label: 'OneDrive', className: 'bg-dark text-white', title: 'Managed by File Sync from OneDrive.' },
    google: { label: 'Google', className: 'bg-warning text-dark', title: 'Managed by File Sync from Google Workspace.' },
    google_workspace: { label: 'Google', className: 'bg-warning text-dark', title: 'Managed by File Sync from Google Workspace.' },
    spo: { label: 'SPO', className: 'bg-success text-white', title: 'Managed by File Sync from on-prem SharePoint.' },
    sharepoint_on_prem: { label: 'SPO', className: 'bg-success text-white', title: 'Managed by File Sync from on-prem SharePoint.' },
  };
  return sourceTypeMap[sourceType] || { label: sourceType.toUpperCase() || 'SYNC', className: 'bg-secondary text-white', title: 'Managed by File Sync.' };
}

function getPublicDocumentSyncTypeBadgeHtml(doc, compact = false) {
  const syncType = getPublicDocumentSyncTypeConfig(doc);
  const spacingClass = compact ? 'me-2 align-middle' : '';
  return `<span class="badge ${syncType.className} ${spacingClass}" title="${escapeHtml(syncType.title)}"><i class="bi bi-arrow-repeat me-1"></i>${escapeHtml(syncType.label)}</span>`;
}

function getPublicDocumentSyncBadgeHtml(doc, compact = false) {
  if (!isPublicSyncedDocument(doc)) {
    return '';
  }

  return getPublicDocumentSyncTypeBadgeHtml(doc, compact);
}

function appendPublicDocumentSyncBadge(container, doc, compact = false) {
  if (!isPublicSyncedDocument(doc)) {
    return null;
  }

  const sourceLabel = getPublicDocumentSyncSourceLabel(doc);
  const syncType = getPublicDocumentSyncTypeConfig(doc);
  const badge = document.createElement('span');
  badge.className = compact ? `badge ${syncType.className} me-2 align-middle` : `badge ${syncType.className}`;
  badge.title = sourceLabel && sourceLabel !== 'File Sync' ? `${syncType.title}: ${sourceLabel}` : syncType.title;

  const icon = document.createElement('i');
  icon.className = 'bi bi-arrow-repeat me-1';
  badge.appendChild(icon);
  badge.appendChild(document.createTextNode(syncType.label));
  container.appendChild(badge);
  return badge;
}

function getPublicDocumentSyncDetailsHtml(doc) {
  const synced = isPublicSyncedDocument(doc);
  let details = synced
    ? `<p class="mb-1"><strong>Synced:</strong> ${getPublicDocumentSyncTypeBadgeHtml(doc)}</p>`
    : '<p class="mb-1"><strong>Synced:</strong> <span class="badge bg-secondary" title="This document was uploaded manually and is not managed by File Sync.">No</span></p>';

  if (synced) {
    const syncMetadata = doc.file_sync;
    const sourceLabel = getPublicDocumentSyncSourceLabel(doc);
    if (sourceLabel) {
      details += `<p class="mb-1"><strong>Sync Source:</strong> ${escapeHtml(sourceLabel)}</p>`;
    }
    if (syncMetadata.remote_path) {
      details += `<p class="mb-1"><strong>Remote Path:</strong> ${escapeHtml(syncMetadata.remote_path)}</p>`;
    }
  }

  return details;
}

function setPublicDocumentSyncStatusElement(doc) {
  const syncStatusElement = document.getElementById('public-doc-sync-status');
  if (!syncStatusElement) {
    return;
  }

  const synced = isPublicSyncedDocument(doc);
  syncStatusElement.className = synced ? 'alert alert-info py-2 mb-3' : 'alert alert-secondary py-2 mb-3';
  syncStatusElement.replaceChildren();

  const statusLine = document.createElement('div');
  statusLine.className = 'd-flex align-items-center gap-2 flex-wrap';

  const label = document.createElement('strong');
  label.textContent = 'Synced:';
  statusLine.appendChild(label);

  const badge = document.createElement('span');
  if (synced) {
    const syncType = getPublicDocumentSyncTypeConfig(doc);
    badge.className = `badge ${syncType.className}`;
    badge.title = syncType.title;
    const icon = document.createElement('i');
    icon.className = 'bi bi-arrow-repeat me-1';
    badge.appendChild(icon);
    badge.appendChild(document.createTextNode(syncType.label));
  } else {
    badge.className = 'badge bg-secondary';
    badge.title = 'This document was uploaded manually and is not managed by File Sync.';
    badge.textContent = 'No';
  }

  statusLine.appendChild(badge);
  syncStatusElement.appendChild(statusLine);

  if (!synced) {
    return;
  }

  const syncMetadata = doc.file_sync;
  const sourceLabel = getPublicDocumentSyncSourceLabel(doc);
  const detailLine = document.createElement('div');
  detailLine.className = 'small text-muted mt-1';
  const detailParts = [];
  if (sourceLabel) {
    detailParts.push(`Source: ${sourceLabel}`);
  }
  if (syncMetadata.remote_path) {
    detailParts.push(`Remote path: ${syncMetadata.remote_path}`);
  }
  detailLine.textContent = detailParts.join(' | ');
  syncStatusElement.appendChild(detailLine);
}

function createPublicDocumentCardActionButton(className, iconClass, label, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  const icon = document.createElement('i');
  icon.className = `bi ${iconClass} me-1`;
  button.appendChild(icon);
  button.appendChild(document.createTextNode(label));
  button.addEventListener('click', onClick);
  return button;
}

function createPublicDocumentClassificationBadge(doc) {
  const classification = doc.document_classification || doc.classification || 'N/A';
  const category = (window.classification_categories || []).find(cat => cat.label === classification);
  const badge = document.createElement('span');
  badge.className = 'badge';
  const safeColor = applyPublicBackgroundColor(badge, category?.color, '#6c757d');
  badge.style.color = isPublicColorLight(safeColor) ? '#000' : '#fff';
  badge.textContent = classification;
  return badge;
}

function appendPublicDocumentMetaPills(container, doc) {
  const metaItems = [
    doc.version ? `v${doc.version}` : null,
    doc.authors ? `By ${doc.authors}` : null,
    doc.number_of_pages ? `${doc.number_of_pages} pages` : null,
    isPublicPdfDocument(doc) ? getPublicDocumentExtractionModeLabel(doc) : null,
    doc.publication_date ? doc.publication_date : null,
  ].filter(Boolean);

  if (!metaItems.length) {
    appendPublicTextElement(container, 'span', 'text-muted small', 'No metadata');
    return;
  }

  metaItems.slice(0, 4).forEach((item) => {
    appendPublicTextElement(container, 'span', 'badge bg-light text-dark border', item);
  });
}

function isPublicPdfDocument(doc) {
  return String(doc?.file_name || '').toLowerCase().endsWith('.pdf');
}

function getPublicDocumentExtractionModeLabel(doc) {
  const mode = String(doc?.document_intelligence_extraction_mode || '').trim().toLowerCase();
  return mode === 'layout' ? 'Enhanced' : 'Standard';
}

function getPublicDocumentTargetExtractionMode(doc) {
  const currentMode = String(doc?.document_intelligence_extraction_mode || '').trim().toLowerCase();
  return currentMode === 'layout' ? 'read' : 'layout';
}

function getPublicDocumentExtractionModeIcon(mode) {
  return mode === 'layout' ? 'bi-layout-text-window-reverse' : 'bi-file-earmark-text';
}

function getPublicDocumentExtractionModeLabelFromMode(mode) {
  return mode === 'layout' ? 'Enhanced' : 'Standard';
}

function getPublicDocumentExtractionChangeTooltip(targetMode) {
  return targetMode === 'layout'
    ? 'Extract again with Enhanced extraction. Enhanced extraction uses Document Intelligence Layout to preserve tables, page structure, forms, and checkbox states. Adds latency and higher cost.'
    : 'Extract again with Standard extraction. Standard extraction uses Document Intelligence Read for faster text extraction. Best for plain text PDFs and images.';
}

function getPublicDocumentExtractionModeTooltip(doc) {
  const mode = String(doc?.document_intelligence_extraction_mode || '').trim().toLowerCase();
  return mode === 'layout'
    ? 'Enhanced extraction uses Document Intelligence Layout to preserve tables, page structure, forms, and checkbox states. Adds latency and higher cost.'
    : 'Standard extraction uses Document Intelligence Read for faster text extraction. Best for plain text PDFs and images.';
}

function getPublicDocumentCitationTooltip(doc) {
  return doc?.enhanced_citations
    ? 'Enhanced citations preserve source-file context for richer citation previews and supported file workflows.'
    : 'Standard citations reference indexed text chunks.';
}

function createPublicDocumentExtractionModeBadge(doc) {
  if (!isPublicPdfDocument(doc)) {
    return null;
  }

  const label = getPublicDocumentExtractionModeLabel(doc);
  const badge = document.createElement('span');
  badge.className = `badge ${label === 'Enhanced' ? 'bg-primary' : 'bg-secondary'}`;
  badge.title = getPublicDocumentExtractionModeTooltip(doc);
  const icon = document.createElement('i');
  icon.className = 'bi bi-file-earmark-text me-1';
  badge.appendChild(icon);
  badge.appendChild(document.createTextNode(label));
  return badge;
}

function getPublicDocumentExtractionModeBadgeHtml(doc) {
  if (!isPublicPdfDocument(doc)) {
    return '';
  }

  const label = getPublicDocumentExtractionModeLabel(doc);
  const badgeClass = label === 'Enhanced' ? 'bg-primary' : 'bg-secondary';
  return `<span class="badge ${badgeClass}" title="${escapeHtml(getPublicDocumentExtractionModeTooltip(doc))}"><i class="bi bi-file-earmark-text me-1"></i>${escapeHtml(label)}</span>`;
}

function createPublicDropdownHeader(label) {
  const listItem = document.createElement('li');
  const header = document.createElement('h6');
  header.className = 'dropdown-header';
  header.textContent = label;
  listItem.appendChild(header);
  return listItem;
}

function createPublicDocumentCard(doc) {
  const docId = doc.id;
  const { pct, docStatus, hasError, isComplete } = getPublicDocumentProcessingState(doc);
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  const canChat = (window.currentPublicStatus || 'active') !== 'inactive';
  const displayTitle = doc.title && doc.title !== doc.file_name ? doc.title : (doc.file_name || 'Untitled');
  const subtitle = doc.title && doc.title !== doc.file_name ? (doc.file_name || '') : '';
  const selected = publicSelectedDocuments.has(docId);

  const column = document.createElement('div');
  column.className = 'col-12 col-md-6 col-xl-4';

  const card = document.createElement('div');
  card.id = `public-doc-card-${docId}`;
  card.className = `card item-card document-item-card h-100${selected ? ' is-selected' : ''}`;
  card.setAttribute('data-document-id', docId);

  const cardBody = document.createElement('div');
  cardBody.className = 'card-body d-flex flex-column';

  const header = document.createElement('div');
  header.className = 'document-item-card__header';

  const checkWrap = document.createElement('div');
  checkWrap.className = 'document-item-card__check';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = `form-check-input document-checkbox${publicSelectionMode ? '' : ' d-none'}`;
  checkbox.setAttribute('data-document-id', docId);
  checkbox.checked = selected;
  checkWrap.appendChild(checkbox);

  const iconWrap = document.createElement('div');
  iconWrap.className = 'item-card-icon';
  const icon = document.createElement('i');
  icon.className = `bi ${getPublicDocumentIcon(doc.file_name || '')}`;
  icon.style.fontSize = '1.75rem';
  iconWrap.appendChild(icon);

  const titleWrap = document.createElement('div');
  titleWrap.className = 'document-item-card__title-wrap';
  appendPublicTextElement(titleWrap, 'div', 'document-item-card__eyebrow', 'Public document');
  appendPublicTextElement(titleWrap, 'h6', 'card-title mb-1', truncatePublicDocumentText(displayTitle, 60), displayTitle);
  if (subtitle) {
    appendPublicTextElement(titleWrap, 'div', 'document-item-card__subtitle', subtitle, subtitle);
  }

  const statusWrap = document.createElement('div');
  statusWrap.className = 'document-item-card__status';
  const statusBadge = document.createElement('span');
  if (hasError) {
    statusBadge.className = 'badge bg-danger';
    statusBadge.textContent = 'Error';
  } else if (!isComplete) {
    statusBadge.className = 'badge bg-info text-dark';
    statusBadge.textContent = `Processing ${pct.toFixed(0)}%`;
  } else if (!canChat) {
    statusBadge.className = 'badge bg-secondary';
    statusBadge.textContent = 'Read Only';
  } else {
    statusBadge.className = 'badge bg-success';
    statusBadge.textContent = 'Ready';
  }
  statusWrap.appendChild(statusBadge);

  header.append(checkWrap, iconWrap, titleWrap, statusWrap);

  const summary = document.createElement('div');
  summary.className = 'document-item-card__summary';
  summary.textContent = truncatePublicDocumentText(getPublicDocumentSummaryText(doc), 160);

  const meta = document.createElement('div');
  meta.className = 'document-item-card__meta';
  appendPublicDocumentMetaPills(meta, doc);

  const badges = document.createElement('div');
  badges.className = 'document-item-card__badges';
  badges.appendChild(createPublicDocumentClassificationBadge(doc));
  const citationBadge = document.createElement('span');
  citationBadge.className = `badge ${doc.enhanced_citations ? 'bg-success' : 'bg-secondary'}`;
  citationBadge.title = getPublicDocumentCitationTooltip(doc);
  citationBadge.textContent = doc.enhanced_citations ? 'Enhanced citations' : 'Standard citations';
  badges.appendChild(citationBadge);
  appendPublicDocumentSyncBadge(badges, doc);

  const tags = document.createElement('div');
  tags.className = 'document-item-card__tags';
  renderPublicTagBadges(doc.tags || [], tags, 4);

  const progress = document.createElement('div');
  if (hasError) {
    progress.className = 'alert alert-danger py-2 px-3 small mb-0';
    progress.textContent = docStatus || 'Processing error';
  } else if (!isComplete) {
    progress.className = 'document-item-card__progress';
    const progressBar = document.createElement('div');
    progressBar.className = 'progress';
    progressBar.style.height = '10px';
    const innerBar = document.createElement('div');
    innerBar.className = 'progress-bar progress-bar-striped progress-bar-animated bg-info';
    innerBar.style.width = `${pct}%`;
    innerBar.setAttribute('role', 'progressbar');
    innerBar.setAttribute('aria-valuenow', String(pct));
    innerBar.setAttribute('aria-valuemin', '0');
    innerBar.setAttribute('aria-valuemax', '100');
    progressBar.appendChild(innerBar);
    appendPublicTextElement(progress, 'span', 'document-item-card__progress-label', `${docStatus} (${pct.toFixed(0)}%)`);
    progress.prepend(progressBar);
  }

  const buttons = document.createElement('div');
  buttons.className = 'item-card-buttons mt-auto d-flex flex-wrap gap-1';
  if (isComplete && !hasError && canChat) {
    buttons.appendChild(createPublicDocumentCardActionButton('btn btn-sm btn-primary me-1', 'bi-chat-dots', 'Chat', () => window.searchPublicDocumentInChat(docId)));
  }
  if (isComplete && !hasError && canManage) {
    buttons.appendChild(createPublicDocumentCardActionButton('btn btn-sm btn-outline-secondary me-1', 'bi-pencil', 'Edit', () => window.onEditPublicDocument(docId)));
  }
  getPublicGeneratedArtifactActionButtons(doc).forEach((button) => buttons.appendChild(button));

  const dropdownItems = [];
  if (isComplete && !hasError) {
    dropdownItems.push(createPublicDropdownItem('bi-check-square', 'Select', () => togglePublicSelectionMode()));
    if (canChat) dropdownItems.push(createPublicDropdownItem('bi-chat-dots-fill', 'Chat', () => window.searchPublicDocumentInChat(docId)));
    if (publicFileDownloadsEnabled) dropdownItems.push(createPublicDropdownItem('bi-download', 'Download file', (event) => window.downloadPublicDocumentFile(docId, event)));
    if (canManage) {
      dropdownItems.push(createPublicDropdownItem('bi-pencil-fill', 'Edit Metadata', () => window.onEditPublicDocument(docId)));
      dropdownItems.push(createPublicDropdownItem('bi-magic', 'Extract Metadata', () => window.onExtractPublicMetadata(docId, null)));
      if (isPublicPdfDocument(doc)) {
        const extractionActionMode = getPublicDocumentTargetExtractionMode(doc);
        const extractionActionLabel = getPublicDocumentExtractionModeLabelFromMode(extractionActionMode);
        const extractionActionIcon = getPublicDocumentExtractionModeIcon(extractionActionMode);
        const extractionActionTooltip = getPublicDocumentExtractionChangeTooltip(extractionActionMode);
        dropdownItems.push(createPublicDropdownDivider());
        dropdownItems.push(createPublicDropdownHeader('Change Extraction'));
        dropdownItems.push(createPublicDropdownItem(extractionActionIcon, `Change to ${extractionActionLabel}`, () => window.reprocessPublicDocumentExtraction(docId, extractionActionMode, null), false, extractionActionTooltip));
      }
      dropdownItems.push(createPublicDropdownDivider());
      dropdownItems.push(createPublicDropdownItem('bi-trash-fill', 'Delete', () => window.deletePublicDocument(docId, null), true));
    }
  } else if (canManage) {
    dropdownItems.push(createPublicDropdownItem('bi-trash-fill', 'Delete', () => window.deletePublicDocument(docId, null), true));
  }

  if (dropdownItems.length) {
    const dropdown = document.createElement('div');
    dropdown.className = 'dropdown action-dropdown d-inline-block ms-auto';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn btn-sm btn-outline-secondary dropdown-toggle';
    toggle.setAttribute('data-bs-toggle', 'dropdown');
    toggle.setAttribute('aria-expanded', 'false');
    const toggleIcon = document.createElement('i');
    toggleIcon.className = 'bi bi-three-dots-vertical';
    toggle.appendChild(toggleIcon);
    const menu = document.createElement('ul');
    menu.className = 'dropdown-menu dropdown-menu-end';
    dropdownItems.forEach((item) => menu.appendChild(item));
    dropdown.append(toggle, menu);
    buttons.appendChild(dropdown);
  }

  cardBody.append(header, summary, meta, badges, tags);
  if (progress.childNodes.length) cardBody.appendChild(progress);
  cardBody.appendChild(buttons);
  card.appendChild(cardBody);
  column.appendChild(card);

  if (!isComplete && !hasError) {
    pollPublicDocumentStatus(docId);
  }

  return column;
}

function renderPublicDocumentCards(docs, container = publicDocumentsCardView) {
  if (!container) return;
  container.innerHTML = '';
  docs.forEach((doc) => container.appendChild(createPublicDocumentCard(doc)));
}

async function fetchPublicDocs(){
  if(!activePublicId) return;
  publicDocsTableBody.innerHTML='<tr class="table-loading-row"><td colspan="4"><div class="spinner-border spinner-border-sm me-2"></div> Loading public documents...</td></tr>';
  if (publicDocumentsCardView) {
    publicDocumentsCardView.innerHTML = '<div class="col-12 text-center text-muted py-5"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading public documents...</div>';
  }
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
    publicFileDownloadsEnabled = Boolean(data.file_downloads_enabled);
    publicDocsTableBody.innerHTML='';
    if (publicDocumentsCardView) publicDocumentsCardView.innerHTML = '';
    if(!data.documents.length){
      const emptyMessage = publicDocsSearchTerm ? 'No documents found.' : 'No documents in this workspace.';
      publicDocsTableBody.innerHTML=`<tr><td colspan="4" class="text-center p-4 text-muted">${escapeHtml(emptyMessage)}</td></tr>`;
      if (publicDocumentsCardView) publicDocumentsCardView.innerHTML = `<div class="col-12 text-center text-muted py-5">${escapeHtml(emptyMessage)}</div>`;
    }
    else if (publicCurrentView === 'cards') {
      renderPublicDocumentCards(data.documents, publicDocumentsCardView);
    }
    else data.documents.forEach(doc=> renderPublicDocumentRow(doc));
    renderPublicDocsPagination(data.page,data.page_size,data.total_count);
    syncPublicSelectionModeUI();
  } catch(err){
    console.error(err);
    const errorMessage = `Error: ${escapeHtml(err.error||err.message)}`;
    publicDocsTableBody.innerHTML=`<tr><td colspan="4" class="text-center text-danger p-4">${errorMessage}</td></tr>`;
    if (publicDocumentsCardView) publicDocumentsCardView.innerHTML = `<div class="col-12 text-center text-danger py-5">${errorMessage}</div>`;
  }
}

function renderPublicDocumentRow(doc) {
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  const currentWorkspaceStatus = window.currentPublicStatus || 'active';

  // Create main document row
  const tr = document.createElement('tr');
  tr.id = `public-doc-row-${doc.id}`;
  // Compute status for icon logic and status row logic (declare once)
  const pctString = String((doc.percentage_complete ?? doc.percentage) || "0");
  const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
  const docStatus = doc.status || "";
  const isComplete = pct >= 100 || docStatus.toLowerCase().includes("complete") || docStatus.toLowerCase().includes("error");
  const hasError = docStatus.toLowerCase().includes("error") || docStatus.toLowerCase().includes("failed");
  const isPendingGeneratedArtifact = isPendingGeneratedArtifactDocument(doc);

  let firstTdHtml = "";
  if (isComplete && !hasError) {
    firstTdHtml = `
      <input type="checkbox" class="form-check-input document-checkbox d-none" data-document-id="${doc.id}">
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

    if (publicFileDownloadsEnabled) {
      actionsDropdown += `
          <li><a class="dropdown-item" href="#" onclick="window.downloadPublicDocumentFile('${doc.id}', event); return false;">
            <i class="bi bi-download me-2"></i>Download file
          </a></li>`;
    }

    if (canManage) {
      const reprocessDocId = escapeHtml(String(doc.id || ''));
      const extractionActionMode = getPublicDocumentTargetExtractionMode(doc);
      const extractionActionLabel = getPublicDocumentExtractionModeLabelFromMode(extractionActionMode);
      const extractionActionIcon = getPublicDocumentExtractionModeIcon(extractionActionMode);
      const extractionActionTooltip = getPublicDocumentExtractionChangeTooltip(extractionActionMode);
      actionsDropdown += `
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item" href="#" onclick="window.onEditPublicDocument('${doc.id}'); return false;">
            <i class="bi bi-pencil-fill me-2"></i>Edit Metadata
          </a></li>
          <li><a class="dropdown-item" href="#" onclick="window.onExtractPublicMetadata('${doc.id}', event); return false;">
            <i class="bi bi-magic me-2"></i>Extract Metadata
          </a></li>
          ${isPublicPdfDocument(doc) ? `
          <li><hr class="dropdown-divider"></li>
          <li><h6 class="dropdown-header">Change Extraction</h6></li>
          <li><a class="dropdown-item" href="#" title="${escapeHtml(extractionActionTooltip)}" onclick="window.reprocessPublicDocumentExtraction('${reprocessDocId}', '${extractionActionMode}', event); return false;">
            <i class="bi ${extractionActionIcon} me-2"></i>Change to ${extractionActionLabel}
          </a></li>` : ''}
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
    <td class="align-middle" title="${escapeHtml(doc.file_name)}">${getPublicDocumentSyncBadgeHtml(doc, true)}${escapeHtml(doc.file_name)}</td>
    <td class="align-middle" title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || '')}</td>
    <td class="align-middle">${chatButton}${actionsDropdown}</td>`;

  const actionsCell = tr.querySelector('td:last-child');
  prependPublicGeneratedArtifactActionButtons(actionsCell, doc);

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
      `<span class="badge bg-success" title="${escapeHtml(getPublicDocumentCitationTooltip({ enhanced_citations }))}">Enhanced</span>` :
      `<span class="badge bg-secondary" title="${escapeHtml(getPublicDocumentCitationTooltip({ enhanced_citations }))}">Standard</span>`;
  }

  const reprocessDocId = escapeHtml(String(doc.id || ''));
  const extractionActionMode = getPublicDocumentTargetExtractionMode(doc);
  const extractionActionLabel = getPublicDocumentExtractionModeLabelFromMode(extractionActionMode);
  const extractionActionIcon = getPublicDocumentExtractionModeIcon(extractionActionMode);
  const extractionActionTooltip = getPublicDocumentExtractionChangeTooltip(extractionActionMode);

  detailsRow.innerHTML = `
    <td colspan="4">
      <div class="bg-light p-3 border rounded small">
        <p class="mb-1"><strong>Classification:</strong> <span class="classification-badge text-dark" style="${getClassificationBadgeStyle(doc.document_classification || doc.classification)}">${escapeHtml(doc.document_classification || doc.classification || 'N/A')}</span></p>
        ${getPublicDocumentSyncDetailsHtml(doc)}
        <p class="mb-1"><strong>Version:</strong> ${escapeHtml(doc.version || '1')}</p>
        <p class="mb-1"><strong>Authors:</strong> ${escapeHtml(doc.authors || 'N/A')}</p>
        <p class="mb-1"><strong>Pages/Chunks:</strong> ${escapeHtml(doc.number_of_pages || 'N/A')}</p>
        ${isPublicPdfDocument(doc) ? `<p class="mb-1"><strong>Extraction:</strong> ${getPublicDocumentExtractionModeBadgeHtml(doc)}</p>` : ''}
        <p class="mb-1"><strong>Citations:</strong> ${getCitationBadge(doc.enhanced_citations)}</p>
        <p class="mb-1"><strong>Publication Date:</strong> ${escapeHtml(doc.publication_date || 'N/A')}</p>
        <p class="mb-1"><strong>Keywords:</strong> ${escapeHtml(doc.keywords || 'N/A')}</p>
        <p class="mb-1"><strong>Tags:</strong> <span class="public-doc-tag-badges"></span></p>
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
            ${isPublicPdfDocument(doc) ? `
            <button class="btn btn-sm btn-outline-secondary" onclick="window.reprocessPublicDocumentExtraction('${reprocessDocId}', '${extractionActionMode}', event)" title="${escapeHtml(extractionActionTooltip)}">
              <i class="bi ${extractionActionIcon}"></i> Change to ${extractionActionLabel}
            </button>` : ''}
          ` : ''}
        </div>
      </div>
    </td>`;

  renderPublicTagBadges(doc.tags || [], detailsRow.querySelector('.public-doc-tag-badges'));

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
    const docCard = document.getElementById(`public-doc-card-${documentId}`);
    if (!docRow && !statusRow && !docCard) {
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
          const docCard = document.getElementById(`public-doc-card-${documentId}`);
          if (docRow || docCard) fetchPublicDocs();
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
window.deletePublicDocument = async function(id, event) {
  const deleteMode = await promptPublicDeleteMode(1);
  if (!deleteMode) {
    return;
  }

  const deleteTrigger = event ? event.target.closest('a, button') : null;
  const originalDeleteTriggerHtml = deleteTrigger ? deleteTrigger.innerHTML : null;
  if (deleteTrigger) {
    deleteTrigger.classList.add('disabled');
    deleteTrigger.setAttribute('aria-disabled', 'true');
    deleteTrigger.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
  }

  try {
    await requestPublicDocumentDeletion(id, deleteMode);
    fetchPublicDocs();
  } catch (e) {
    showPublicWorkspaceToast(`Error deleting: ${e.error || e.message}`, 'danger');
    if (deleteTrigger && document.body.contains(deleteTrigger)) {
      deleteTrigger.classList.remove('disabled');
      deleteTrigger.removeAttribute('aria-disabled');
      deleteTrigger.innerHTML = originalDeleteTriggerHtml;
    }
  }
};

window.approvePublicGeneratedArtifactDocument = async function(id, triggerButton = null) {
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  if (!canManage) {
    showPublicWorkspaceMessage('You do not have permission to approve generated artifacts in this workspace.', 'danger');
    return;
  }

  const originalButtonHtml = triggerButton ? triggerButton.innerHTML : null;
  if (triggerButton) {
    triggerButton.disabled = true;
    triggerButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
  }

  try {
    const response = await fetch(`/api/public_documents/${encodeURIComponent(id)}/approve-generated-artifact`, {
      method: 'POST',
    });
    const responseData = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseData.error || `Server responded with status ${response.status}`);
    }

    showPublicWorkspaceMessage(responseData.message || 'Generated artifact approved.', 'success');
    if (publicCurrentFolder) {
      renderPublicFolderContents(publicCurrentFolder);
      return;
    }
    fetchPublicDocs();
  } catch (error) {
    showPublicWorkspaceMessage(error.message || 'Failed to approve the generated artifact.', 'danger');
    if (triggerButton && document.body.contains(triggerButton)) {
      triggerButton.disabled = false;
      triggerButton.innerHTML = originalButtonHtml;
    }
  }
};

window.denyPublicGeneratedArtifactDocument = async function(id, triggerButton = null) {
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  if (!canManage) {
    showPublicWorkspaceMessage('You do not have permission to deny generated artifacts in this workspace.', 'danger');
    return;
  }

  const originalButtonHtml = triggerButton ? triggerButton.innerHTML : null;
  if (triggerButton) {
    triggerButton.disabled = true;
    triggerButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
  }

  try {
    const response = await fetch(`/api/public_documents/${encodeURIComponent(id)}/deny-generated-artifact`, {
      method: 'POST',
    });
    const responseData = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseData.error || `Server responded with status ${response.status}`);
    }

    showPublicWorkspaceMessage(responseData.message || 'Generated artifact denied.', 'success');
    if (publicCurrentFolder) {
      renderPublicFolderContents(publicCurrentFolder);
      return;
    }
    fetchPublicDocs();
  } catch (error) {
    showPublicWorkspaceMessage(error.message || 'Failed to deny the generated artifact.', 'danger');
    if (triggerButton && document.body.contains(triggerButton)) {
      triggerButton.disabled = false;
      triggerButton.innerHTML = originalButtonHtml;
    }
  }
};

window.cancelPublicGeneratedArtifactDocument = async function(id, triggerButton = null) {
  const originalButtonHtml = triggerButton ? triggerButton.innerHTML : null;
  if (triggerButton) {
    triggerButton.disabled = true;
    triggerButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
  }

  try {
    const response = await fetch(`/api/public_documents/${encodeURIComponent(id)}/cancel-generated-artifact`, {
      method: 'POST',
    });
    const responseData = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseData.error || `Server responded with status ${response.status}`);
    }

    showPublicWorkspaceMessage(responseData.message || 'Generated artifact request canceled.', 'success');
    if (publicCurrentFolder) {
      renderPublicFolderContents(publicCurrentFolder);
      return;
    }
    fetchPublicDocs();
  } catch (error) {
    showPublicWorkspaceMessage(error.message || 'Failed to cancel the generated artifact request.', 'danger');
    if (triggerButton && document.body.contains(triggerButton)) {
      triggerButton.disabled = false;
      triggerButton.innerHTML = originalButtonHtml;
    }
  }
};

window.searchPublicDocumentInChat = function(docId) {
  window.location.href = `/chats?search_documents=true&doc_scope=public&document_id=${docId}&workspace_id=${activePublicId}`;
};

// --- Public Document Selection Functions ---
function getVisiblePublicDocumentCheckboxes() {
  return Array.from(document.querySelectorAll('#public-documents-table .document-checkbox, #public-folder-docs-table .document-checkbox, #public-documents-card-view .document-checkbox, #public-folder-documents-card-view .document-checkbox'))
    .filter(checkbox => checkbox.offsetParent !== null);
}

function syncPublicSelectionUI() {
  document.querySelectorAll('.document-checkbox').forEach((checkbox) => {
    const documentId = checkbox.getAttribute('data-document-id');
    checkbox.checked = publicSelectedDocuments.has(documentId);
  });

  document.querySelectorAll('.document-item-card').forEach((card) => {
    const documentId = card.getAttribute('data-document-id');
    card.classList.toggle('is-selected', publicSelectedDocuments.has(documentId));
  });

  const visibleCheckboxes = getVisiblePublicDocumentCheckboxes();
  document.querySelectorAll('.document-select-all-checkbox').forEach((checkbox) => {
    const visibleScope = checkbox.offsetParent !== null;
    checkbox.checked = visibleScope && visibleCheckboxes.length > 0 && visibleCheckboxes.every(cb => publicSelectedDocuments.has(cb.getAttribute('data-document-id')));
    checkbox.indeterminate = visibleScope && visibleCheckboxes.some(cb => publicSelectedDocuments.has(cb.getAttribute('data-document-id'))) && !checkbox.checked;
  });
}

function syncPublicSelectionModeUI() {
  const table = document.getElementById('public-documents-table');
  const folderTable = document.getElementById('public-folder-docs-table');
  const folderCardView = document.getElementById('public-folder-documents-card-view');
  const bulkActionsBar = document.getElementById('publicBulkActionsBar');
  const toggleSelectionBtn = document.getElementById('public-toggle-selection-btn');

  table?.classList.toggle('selection-mode', publicSelectionMode);
  folderTable?.classList.toggle('selection-mode', publicSelectionMode);
  publicDocumentsCardView?.classList.toggle('selection-mode', publicSelectionMode);
  folderCardView?.classList.toggle('selection-mode', publicSelectionMode);

  document.querySelectorAll('.document-checkbox').forEach((checkbox) => {
    checkbox.classList.toggle('d-none', !publicSelectionMode);
    checkbox.checked = publicSelectionMode && publicSelectedDocuments.has(checkbox.getAttribute('data-document-id'));
  });

  document.querySelectorAll('.expand-collapse-container').forEach((container) => {
    container.classList.toggle('d-none', publicSelectionMode);
    container.classList.toggle('d-inline-block', !publicSelectionMode);
  });

  if (toggleSelectionBtn) {
    toggleSelectionBtn.classList.toggle('active', publicSelectionMode);
    toggleSelectionBtn.setAttribute('aria-pressed', String(publicSelectionMode));
  }

  if (!publicSelectionMode && bulkActionsBar) {
    bulkActionsBar.style.display = 'none';
  }

  syncPublicSelectionUI();
  updatePublicBulkActionButtons();
}

function updatePublicSelectedDocuments(documentId, isSelected) {
  if (isSelected) {
    publicSelectedDocuments.add(documentId);
    publicLastCardSelectionAnchorId = documentId;
  } else {
    publicSelectedDocuments.delete(documentId);
  }
  syncPublicSelectionUI();
  updatePublicBulkActionButtons();
}

function updatePublicBulkActionButtons() {
  const bulkActionsBar = document.getElementById('publicBulkActionsBar');
  const selectedCountSpan = document.getElementById('publicSelectedCount');
  const deleteBtn = document.getElementById('public-delete-selected-btn');
  const downloadBtn = document.getElementById('public-download-selected-btn');
  const reprocessDropdown = document.getElementById('public-reprocess-selected-dropdown');

  if (publicSelectedDocuments.size > 0) {
    if (bulkActionsBar) bulkActionsBar.style.display = 'block';
    if (selectedCountSpan) selectedCountSpan.textContent = publicSelectedDocuments.size;
    const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
    if (deleteBtn) deleteBtn.style.display = canManage ? 'inline-block' : 'none';
    if (downloadBtn) downloadBtn.classList.toggle('d-none', !publicFileDownloadsEnabled);
    if (reprocessDropdown) reprocessDropdown.classList.toggle('d-none', !canManage);
  } else {
    if (bulkActionsBar) bulkActionsBar.style.display = 'none';
    if (downloadBtn) downloadBtn.classList.add('d-none');
  }
}

function togglePublicSelectionMode() {
  publicSelectionMode = !publicSelectionMode;

  if (!publicSelectionMode) {
    publicSelectedDocuments.clear();
    publicLastCardSelectionAnchorId = null;
  }

  syncPublicSelectionModeUI();
}

function clearPublicSelection() {
  publicSelectedDocuments.clear();
  publicLastCardSelectionAnchorId = null;
  syncPublicSelectionUI();
  updatePublicBulkActionButtons();
}

function togglePublicSelectAllDocuments(isSelected) {
  if (isSelected && !publicSelectionMode) {
    publicSelectionMode = true;
    syncPublicSelectionModeUI();
  }

  getVisiblePublicDocumentCheckboxes().forEach((checkbox) => {
    const documentId = checkbox.getAttribute('data-document-id');
    checkbox.checked = isSelected;
    if (isSelected) {
      publicSelectedDocuments.add(documentId);
    } else {
      publicSelectedDocuments.delete(documentId);
    }
  });

  syncPublicSelectionModeUI();
}

function getVisiblePublicDocumentCards() {
  return Array.from(document.querySelectorAll('#public-documents-card-view .document-item-card, #public-folder-documents-card-view .document-item-card'))
    .filter(card => card.offsetParent !== null);
}

function isPublicDocumentCardActionTarget(target) {
  return Boolean(target.closest('a, button, input, label, select, textarea, .dropdown-menu, .tag-badge'));
}

function openPublicDocumentCardDropdown(card) {
  const dropdownToggle = card.querySelector('.action-dropdown [data-bs-toggle="dropdown"]');
  if (!dropdownToggle || !window.bootstrap?.Dropdown) {
    return;
  }
  window.bootstrap.Dropdown.getOrCreateInstance(dropdownToggle).show();
}

function selectPublicDocumentCardRange(documentId) {
  const documentIds = getVisiblePublicDocumentCards()
    .map(card => card.getAttribute('data-document-id'))
    .filter(Boolean);
  const currentIndex = documentIds.indexOf(documentId);
  const anchorIndex = documentIds.indexOf(publicLastCardSelectionAnchorId);

  if (currentIndex === -1) {
    return;
  }

  if (anchorIndex === -1) {
    publicSelectedDocuments.add(documentId);
    publicLastCardSelectionAnchorId = documentId;
    return;
  }

  const startIndex = Math.min(anchorIndex, currentIndex);
  const endIndex = Math.max(anchorIndex, currentIndex);
  documentIds.slice(startIndex, endIndex + 1).forEach(id => publicSelectedDocuments.add(id));
}

function handlePublicDocumentCardClick(event) {
  const card = event.target.closest('.document-item-card');
  if (!card || isPublicDocumentCardActionTarget(event.target)) {
    return;
  }

  const documentId = card.getAttribute('data-document-id');
  if (!documentId) {
    return;
  }

  if (event.shiftKey || event.ctrlKey || event.metaKey || publicSelectionMode) {
    event.preventDefault();
    if (!publicSelectionMode) {
      publicSelectionMode = true;
    }

    if (event.shiftKey) {
      selectPublicDocumentCardRange(documentId);
    } else {
      if (publicSelectedDocuments.has(documentId)) {
        publicSelectedDocuments.delete(documentId);
      } else {
        publicSelectedDocuments.add(documentId);
      }
      publicLastCardSelectionAnchorId = documentId;
    }

    syncPublicSelectionModeUI();
    return;
  }

  openPublicDocumentCardDropdown(card);
}

function deletePublicSelectedDocuments() {
  if (publicSelectedDocuments.size === 0) return;

  promptPublicDeleteMode(publicSelectedDocuments.size).then((deleteMode) => {
    if (!deleteMode) {
      return;
    }

    const deleteBtn = document.getElementById('public-delete-selected-btn');
    if (deleteBtn) {
      deleteBtn.disabled = true;
      deleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Deleting...';
    }

    const deletePromises = Array.from(publicSelectedDocuments).map((docId) => requestPublicDocumentDeletion(docId, deleteMode));

    Promise.allSettled(deletePromises)
      .then((results) => {
        const successful = results.filter((result) => result.status === 'fulfilled').length;
        const failed = results.filter((result) => result.status === 'rejected').length;
        if (failed > 0) {
          const toastType = successful === 0 ? 'danger' : 'warning';
          showPublicWorkspaceToast(`Deleted ${successful} document(s). ${failed} failed to delete.`, toastType);
        }

        if (publicSelectionMode) {
          togglePublicSelectionMode();
        } else {
          publicSelectedDocuments.clear();
          updatePublicBulkActionButtons();
        }

        fetchPublicDocs();
      })
      .finally(() => {
        if (deleteBtn) {
          deleteBtn.disabled = false;
          deleteBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete Selected';
        }
      });
  });
}

function chatWithPublicSelected() {
  if (publicSelectedDocuments.size === 0) return;
  const idsParam = encodeURIComponent(Array.from(publicSelectedDocuments).join(','));
  window.location.href = `/chats?search_documents=true&doc_scope=public&document_ids=${idsParam}&workspace_id=${activePublicId}`;
}

async function requestPublicDocumentExtractionReprocess(documentIds, extractionMode) {
  const response = await fetch('/api/public_documents/reprocess_extraction', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_ids: documentIds,
      extraction_mode: extractionMode,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok && !(Array.isArray(data.queued) && data.queued.length > 0)) {
    throw new Error(data.error || data.message || 'Unable to queue PDF extraction change.');
  }
  return data;
}

function showPublicDocumentReprocessResult(data, extractionMode) {
  const queuedCount = Array.isArray(data.queued) ? data.queued.length : 0;
  const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
  const modeLabel = extractionMode === 'layout' ? 'Enhanced' : 'Standard';
  const message = errorCount > 0
    ? `Queued ${queuedCount} PDF(s) to extract again with ${modeLabel}; ${errorCount} item(s) were skipped.`
    : (data.message || `Queued ${queuedCount} PDF(s) to extract again with ${modeLabel}.`);
  showPublicWorkspaceToast(message, errorCount > 0 ? 'warning' : 'success');
}

async function reprocessPublicDocumentExtraction(documentId, extractionMode, event) {
  if (event) {
    event.preventDefault();
  }
  const modeLabel = extractionMode === 'layout' ? 'Enhanced' : 'Standard';
  if (!confirm(`Queue this PDF to extract again with ${modeLabel}?`)) {
    return;
  }

  try {
    const data = await requestPublicDocumentExtractionReprocess([documentId], extractionMode);
    showPublicDocumentReprocessResult(data, extractionMode);
    fetchPublicDocs();
  } catch (error) {
    showPublicWorkspaceToast(error.message, 'danger');
  }
}

async function reprocessPublicSelectedDocumentExtraction(extractionMode) {
  const documentIds = Array.from(publicSelectedDocuments);
  if (documentIds.length === 0) {
    return;
  }
  const modeLabel = extractionMode === 'layout' ? 'Enhanced' : 'Standard';
  if (!confirm(`Queue ${documentIds.length} selected document(s) to extract again with ${modeLabel}?`)) {
    return;
  }

  try {
    const data = await requestPublicDocumentExtractionReprocess(documentIds, extractionMode);
    showPublicDocumentReprocessResult(data, extractionMode);
    publicSelectedDocuments.clear();
    syncPublicSelectionModeUI();
    fetchPublicDocs();
  } catch (error) {
    showPublicWorkspaceToast(error.message, 'danger');
  }
}

async function downloadPublicSelectedDocuments() {
  if (publicSelectedDocuments.size === 0) {
    return;
  }
  if (!publicFileDownloadsEnabled) {
    showPublicDocumentDeleteFeedback('File downloads are disabled for this public workspace.', 'warning');
    return;
  }

  const downloadBtn = document.getElementById('public-download-selected-btn');
  if (downloadBtn) {
    downloadBtn.disabled = true;
    downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Downloading...';
  }

  try {
    await downloadPublicFile(
      '/api/public_documents/download',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_ids: Array.from(publicSelectedDocuments) })
      },
      publicSelectedDocuments.size === 1 ? 'document' : 'public_workspace_documents.zip'
    );
  } catch (error) {
    console.error('Error downloading selected public documents:', error);
    showPublicDocumentDeleteFeedback(error.message || 'Unable to download selected documents', 'danger');
  } finally {
    if (downloadBtn) {
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = '<i class="bi bi-download me-1"></i>Download Selected';
    }
  }
}
window.downloadPublicSelectedDocuments = downloadPublicSelectedDocuments;

// Expose selection functions globally
window.updatePublicSelectedDocuments = updatePublicSelectedDocuments;
window.togglePublicSelectionMode = togglePublicSelectionMode;
window.deletePublicSelectedDocuments = deletePublicSelectedDocuments;
window.clearPublicSelection = clearPublicSelection;
window.chatWithPublicSelected = chatWithPublicSelected;
window.reprocessPublicDocumentExtraction = reprocessPublicDocumentExtraction;
window.reprocessPublicSelectedDocumentExtraction = reprocessPublicSelectedDocumentExtraction;

// Prompts
function canManagePublicPrompts() {
  return ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic) && (window.currentPublicStatus || 'active') === 'active';
}

function createPublicPromptLoadingElement(message) {
  const wrapper = document.createElement('div');
  wrapper.className = 'col-12 text-center text-muted py-5';
  const spinner = document.createElement('div');
  spinner.className = 'spinner-border spinner-border-sm me-2';
  spinner.setAttribute('role', 'status');
  const hiddenLabel = document.createElement('span');
  hiddenLabel.className = 'visually-hidden';
  hiddenLabel.textContent = 'Loading...';
  spinner.appendChild(hiddenLabel);
  wrapper.appendChild(spinner);
  wrapper.append(message);
  return wrapper;
}

function setPublicPromptsLoadingState() {
  if (publicPromptsTableBody) {
    const row = document.createElement('tr');
    row.className = 'table-loading-row';
    const cell = document.createElement('td');
    cell.colSpan = 2;
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm me-2';
    spinner.setAttribute('role', 'status');
    const hiddenLabel = document.createElement('span');
    hiddenLabel.className = 'visually-hidden';
    hiddenLabel.textContent = 'Loading...';
    spinner.appendChild(hiddenLabel);
    cell.appendChild(spinner);
    cell.append('Loading public prompts...');
    row.appendChild(cell);
    publicPromptsTableBody.replaceChildren(row);
  }

  publicPromptsCardView?.replaceChildren(createPublicPromptLoadingElement('Loading public prompts...'));
}

function renderPublicPromptsEmptyState(message) {
  if (publicPromptsTableBody) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 2;
    cell.className = 'text-center p-4 text-muted';
    cell.textContent = message;
    row.appendChild(cell);
    publicPromptsTableBody.replaceChildren(row);
  }

  if (publicPromptsCardView) {
    const wrapper = document.createElement('div');
    wrapper.className = 'col-12 text-center text-muted py-5';
    const icon = document.createElement('i');
    icon.className = 'bi bi-card-text display-6 mb-2 d-block';
    const text = document.createElement('p');
    text.className = 'mb-0';
    text.textContent = message;
    wrapper.append(icon, text);
    publicPromptsCardView.replaceChildren(wrapper);
  }
}

function renderPublicPromptsErrorState(message) {
  if (publicPromptsTableBody) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 2;
    cell.className = 'text-center text-danger p-3';
    cell.textContent = message;
    row.appendChild(cell);
    publicPromptsTableBody.replaceChildren(row);
  }

  if (publicPromptsCardView) {
    const wrapper = document.createElement('div');
    wrapper.className = 'col-12 text-center text-danger py-5';
    const icon = document.createElement('i');
    icon.className = 'bi bi-exclamation-triangle display-6 mb-2 d-block';
    const text = document.createElement('p');
    text.className = 'mb-0';
    text.textContent = message;
    wrapper.append(icon, text);
    publicPromptsCardView.replaceChildren(wrapper);
  }
}

function getPublicPromptPreview(prompt) {
  const content = String(prompt?.content || '').trim();
  if (!content) return 'Open the prompt to review the reusable content.';
  return content.length > 180 ? `${content.slice(0, 180).trimEnd()}...` : content;
}

function buildPublicPromptChatUrl(promptId) {
  const params = new URLSearchParams({
    prompt_id: String(promptId || ''),
    prompt_scope: 'public',
    openPrompt: '1',
  });

  if (activePublicId) {
    params.set('workspace_id', String(activePublicId));
    params.set('prompt_scope_id', String(activePublicId));
  }

  return `/chats?${params.toString()}`;
}

function chatWithPublicPrompt(promptId) {
  if (!promptId) return;
  window.location.href = buildPublicPromptChatUrl(promptId);
}

function createPublicPromptButton({ className, title, iconClass, label, onClick }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.title = title;
  button.setAttribute('aria-label', title);
  const icon = document.createElement('i');
  icon.className = iconClass;
  button.appendChild(icon);
  if (label) {
    icon.classList.add('me-1');
    button.append(label);
  }
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    onClick(event);
  });
  return button;
}

function appendPublicPromptActions(container, prompt, includeLabels = false) {
  container.appendChild(createPublicPromptButton({
    className: 'btn btn-sm btn-primary',
    title: 'Chat with Prompt',
    iconClass: 'bi bi-chat-dots',
    label: includeLabels ? 'Chat' : '',
    onClick: () => chatWithPublicPrompt(prompt.id),
  }));

  container.appendChild(createPublicPromptButton({
    className: 'btn btn-sm btn-outline-info',
    title: 'View Prompt',
    iconClass: 'bi bi-eye',
    label: includeLabels ? 'View' : '',
    onClick: () => window.onViewPublicPrompt(prompt.id),
  }));

  if (!canManagePublicPrompts()) return;

  container.append(
    createPublicPromptButton({
      className: 'btn btn-sm btn-outline-secondary',
      title: 'Edit Prompt',
      iconClass: 'bi bi-pencil',
      label: includeLabels ? 'Edit' : '',
      onClick: () => window.onEditPublicPrompt(prompt.id),
    }),
    createPublicPromptButton({
      className: 'btn btn-sm btn-outline-danger',
      title: 'Delete Prompt',
      iconClass: 'bi bi-trash',
      onClick: () => window.onDeletePublicPrompt(prompt.id),
    })
  );
}

async function fetchPublicPrompts(){
  setPublicPromptsLoadingState();
  publicPromptsPagination.innerHTML=''; const params=new URLSearchParams({page:publicPromptsCurrentPage,page_size:publicPromptsPageSize}); if(publicPromptsSearchTerm) params.append('search',publicPromptsSearchTerm);
  try{ const r=await fetch(`/api/public_prompts?${params}`); if(!r.ok) throw await r.json(); const d=await r.json(); if(!d.prompts.length) renderPublicPromptsEmptyState(publicPromptsSearchTerm ? 'No public prompts found.' : 'No public prompts created yet.'); else renderPublicPromptViews(d.prompts); renderPublicPromptsPagination(d.page,d.page_size,d.total_count); }catch(e){ renderPublicPromptsErrorState(`Error: ${e.error||e.message||'Unknown error'}`); }
}

function renderPublicPromptViews(prompts) {
  publicPromptsTableBody?.replaceChildren();
  prompts.forEach((prompt) => renderPublicPromptRow(prompt));
  publicPromptsCardView?.replaceChildren(...prompts.map((prompt) => createPublicPromptCard(prompt)));
}

function renderPublicPromptRow(p){
  const tr=document.createElement('tr');
  tr.dataset.promptId = p.id || '';
  const nameCell = document.createElement('td');
  nameCell.title = p.name || '';
  nameCell.textContent = p.name || 'Untitled Prompt';
  const actionsCell = document.createElement('td');
  const actions = document.createElement('div');
  actions.className = 'd-flex gap-1 justify-content-start justify-content-md-end';
  appendPublicPromptActions(actions, p, false);
  actionsCell.appendChild(actions);
  tr.append(nameCell, actionsCell);
  publicPromptsTableBody.append(tr);
}

function createPublicPromptCard(prompt) {
  const col = document.createElement('div');
  col.className = 'col-12 col-md-6 col-xl-4';
  const card = document.createElement('div');
  card.className = 'card item-card prompt-item-card h-100';
  card.tabIndex = 0;
  card.setAttribute('aria-label', `View prompt ${prompt.name || 'Untitled Prompt'}`);
  const body = document.createElement('div');
  body.className = 'card-body d-flex flex-column';
  const iconWrap = document.createElement('div');
  iconWrap.className = 'item-card-icon mb-2';
  const icon = document.createElement('i');
  icon.className = 'bi bi-card-text';
  icon.style.fontSize = '1.75rem';
  iconWrap.appendChild(icon);
  const title = document.createElement('h6');
  title.className = 'card-title mb-2';
  title.textContent = prompt.name || 'Untitled Prompt';
  const preview = document.createElement('p');
  preview.className = 'card-text small text-muted prompt-card-preview flex-grow-1';
  preview.textContent = getPublicPromptPreview(prompt);
  const actions = document.createElement('div');
  actions.className = 'item-card-buttons mt-2 d-flex flex-wrap gap-1';
  appendPublicPromptActions(actions, prompt, true);
  card.addEventListener('click', (event) => {
    if (!event.target.closest('a, button, input, label, select, textarea, .dropdown-menu')) {
      window.onViewPublicPrompt(prompt.id);
    }
  });
  card.addEventListener('keydown', (event) => {
    if (!event.target.closest('a, button, input, label, select, textarea, .dropdown-menu') && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      window.onViewPublicPrompt(prompt.id);
    }
  });
  body.append(iconWrap, title, preview, actions);
  card.appendChild(body);
  col.appendChild(card);
  return col;
}

function setupPublicPromptsViewSwitcher() {
  const listRadio = document.getElementById('public-prompts-view-list');
  const gridRadio = document.getElementById('public-prompts-view-grid');
  const switchView = (view, persist = true) => {
    const mode = view === 'grid' ? 'grid' : 'list';
    if (listRadio) listRadio.checked = mode === 'list';
    if (gridRadio) gridRadio.checked = mode === 'grid';
    publicPromptsListView?.classList.toggle('d-none', mode !== 'list');
    publicPromptsCardView?.classList.toggle('d-none', mode !== 'grid');
    if (persist) localStorage.setItem('publicPromptsViewPreference', mode);
  };
  listRadio?.addEventListener('change', () => { if (listRadio.checked) switchView('list'); });
  gridRadio?.addEventListener('change', () => { if (gridRadio.checked) switchView('grid'); });
  switchView(localStorage.getItem('publicPromptsViewPreference') === 'grid' ? 'grid' : 'list', false);
}

function openPublicPromptViewModal(prompt) {
  const modalEl = document.getElementById('publicPromptViewModal');
  if (!modalEl) return;
  const titleEl = document.getElementById('publicPromptViewModalLabel');
  const bodyEl = document.getElementById('publicPromptViewModalBody');
  const footerEl = document.getElementById('publicPromptViewModalFooter');
  if (!titleEl || !bodyEl || !footerEl) return;
  titleEl.textContent = 'Prompt Details';

  const nameLabel = document.createElement('label');
  nameLabel.className = 'text-muted small mb-1 d-block';
  nameLabel.textContent = 'Prompt Name';
  const nameText = document.createElement('div');
  nameText.className = 'fw-medium mb-3';
  nameText.textContent = prompt.name || 'Untitled Prompt';
  const contentLabel = document.createElement('label');
  contentLabel.className = 'text-muted small mb-1 d-block';
  contentLabel.textContent = 'Prompt Content';
  const contentPre = document.createElement('pre');
  contentPre.className = 'mb-0 p-3 bg-body-tertiary border rounded';
  contentPre.style.whiteSpace = 'pre-wrap';
  contentPre.style.wordBreak = 'break-word';
  contentPre.style.maxHeight = '360px';
  contentPre.style.overflowY = 'auto';
  contentPre.style.fontSize = '0.9rem';
  contentPre.textContent = prompt.content || 'No prompt content available.';
  bodyEl.replaceChildren(nameLabel, nameText, contentLabel, contentPre);

  footerEl.replaceChildren();
  const chatButton = document.createElement('button');
  chatButton.type = 'button';
  chatButton.className = 'btn btn-primary';
  chatButton.innerHTML = '<i class="bi bi-chat-dots-fill me-1"></i>Chat';
  chatButton.addEventListener('click', () => {
    bootstrap.Modal.getInstance(modalEl)?.hide();
    chatWithPublicPrompt(prompt.id);
  });
  footerEl.appendChild(chatButton);

  if (canManagePublicPrompts()) {
    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'btn btn-outline-secondary';
    editButton.innerHTML = '<i class="bi bi-pencil me-1"></i>Edit';
    editButton.addEventListener('click', () => {
      bootstrap.Modal.getInstance(modalEl)?.hide();
      window.onEditPublicPrompt(prompt.id);
    });
    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'btn btn-outline-danger';
    deleteButton.innerHTML = '<i class="bi bi-trash me-1"></i>Delete';
    deleteButton.addEventListener('click', () => {
      bootstrap.Modal.getInstance(modalEl)?.hide();
      window.onDeletePublicPrompt(prompt.id);
    });
    footerEl.append(editButton, deleteButton);
  }
  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'btn btn-secondary';
  closeButton.textContent = 'Close';
  closeButton.setAttribute('data-bs-dismiss', 'modal');
  footerEl.appendChild(closeButton);
  bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

window.onViewPublicPrompt=async function(id){ try{ const r=await fetch(`/api/public_prompts/${encodeURIComponent(id)}`); if(!r.ok) throw await r.json(); const d=await r.json(); openPublicPromptViewModal(d); }catch(e){ alert(e.error||e.message);} };
window.chatWithPublicPrompt=chatWithPublicPrompt;
function renderPublicPromptsPagination(page,pageSize,totalCount){ const container=publicPromptsPagination; container.innerHTML=''; const totalPages=Math.ceil(totalCount/pageSize); if(totalPages<=1) return; const ul=document.createElement('ul'); ul.className='pagination pagination-sm mb-0'; function mk(p,t,d,a){ const li=document.createElement('li'); li.className=`page-item${d?' disabled':''}${a?' active':''}`; const aEl=document.createElement('a'); aEl.className='page-link'; aEl.href='#'; aEl.textContent=t; if(!d&&!a) aEl.onclick=e=>{e.preventDefault();publicPromptsCurrentPage=p;fetchPublicPrompts();}; li.append(aEl); return li;} ul.append(mk(page-1,'«',page<=1,false)); for(let p=1;p<=totalPages;p++) ul.append(mk(p,p,false,p===page)); ul.append(mk(page+1,'»',page>=totalPages,false)); container.append(ul);} 

function openPublicPromptModal(){ publicPromptIdEl.value=''; publicPromptNameEl.value=''; if(publicSimplemde) publicSimplemde.value(''); else publicPromptContentEl.value=''; document.getElementById('publicPromptModalLabel').textContent='Create Public Prompt'; publicPromptModal.show(); updatePublicPromptsRoleUI(); }
async function onSavePublicPrompt(e){ e.preventDefault(); const id=publicPromptIdEl.value; const url=id?`/api/public_prompts/${encodeURIComponent(id)}`:'/api/public_prompts'; const method=id?'PATCH':'POST'; const name=publicPromptNameEl.value.trim(); const content=publicSimplemde?publicSimplemde.value():publicPromptContentEl.value.trim(); if(!name||!content) return alert('Name & content required'); const btn=document.getElementById('public-prompt-save-btn'); btn.disabled=true; btn.innerHTML='<span class="spinner-border spinner-border-sm me-1"></span>Saving…'; try{ const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify({name,content})}); if(!r.ok) throw await r.json(); publicPromptModal.hide(); fetchPublicPrompts(); }catch(err){ alert(err.error||err.message); }finally{ btn.disabled=false; btn.textContent='Save Prompt'; }}
window.onEditPublicPrompt=async function(id){ try{ const r=await fetch(`/api/public_prompts/${encodeURIComponent(id)}`); if(!r.ok) throw await r.json(); const d=await r.json(); document.getElementById('publicPromptModalLabel').textContent=`Edit: ${d.name}`; publicPromptIdEl.value=d.id; publicPromptNameEl.value=d.name; if(publicSimplemde) publicSimplemde.value(d.content); else publicPromptContentEl.value=d.content; publicPromptModal.show(); }catch(e){ alert(e.error||e.message);} };
window.onDeletePublicPrompt=async function(id){ if(!confirm('Delete prompt?')) return; try{ await fetch(`/api/public_prompts/${encodeURIComponent(id)}`,{method:'DELETE'}); fetchPublicPrompts(); }catch(e){ alert(e.error||e.message);} };

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
      setPublicDocumentSyncStatusElement(doc);

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

function updatePublicPromptsRoleUI(){ const canManage=canManagePublicPrompts(); document.getElementById('create-public-prompt-section')?.classList.toggle('d-none', !canManage); document.getElementById('public-prompts-role-warning')?.classList.toggle('d-none', canManage); }

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
      if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView();
    })
    .catch(err => console.error('Error loading public workspace tags:', err));
}

function setupPublicViewSwitcher() {
  const listRadio = document.getElementById('public-docs-view-list');
  const cardsRadio = document.getElementById('public-docs-view-cards');
  const gridRadio = document.getElementById('public-docs-view-grid');
  const foldersCardsRadio = document.getElementById('public-docs-view-folders-cards');
  if (listRadio) listRadio.addEventListener('change', () => { if (listRadio.checked) switchPublicView('list'); });
  if (cardsRadio) cardsRadio.addEventListener('change', () => { if (cardsRadio.checked) switchPublicView('cards'); });
  if (gridRadio) gridRadio.addEventListener('change', () => { if (gridRadio.checked) switchPublicView('grid'); });
  if (foldersCardsRadio) foldersCardsRadio.addEventListener('change', () => { if (foldersCardsRadio.checked) switchPublicView('folders-cards'); });
}

function switchPublicView(view) {
  publicCurrentView = ['list', 'cards', 'grid', 'folders-cards'].includes(view) ? view : 'list';
  localStorage.setItem('publicWorkspaceViewPreference', publicCurrentView);
  const listView = document.getElementById('public-documents-list-view');
  const cardView = document.getElementById('public-documents-card-view');
  const gridView = document.getElementById('public-documents-grid-view');
  const viewInfo = document.getElementById('public-docs-view-info');
  const gridControls = document.getElementById('public-grid-controls-bar');
  const listControls = document.getElementById('public-list-controls-bar');
  const filterBtn = document.getElementById('public-docs-filters-toggle-btn');
  const filterCollapse = document.getElementById('public-docs-filters-collapse');
  const bulkBar = document.getElementById('publicBulkActionsBar');

  if (publicCurrentView === 'list' || publicCurrentView === 'cards') {
    publicCurrentFolder = null;
    publicCurrentFolderType = null;
    publicFolderCurrentPage = 1;
    publicFolderSortBy = '_ts';
    publicFolderSortOrder = 'desc';
    publicFolderSearchTerm = '';
    const tagContainer = document.getElementById('public-tag-folders-container');
    if (tagContainer) tagContainer.className = 'row g-2';
    if (listView) listView.classList.toggle('d-none', publicCurrentView !== 'list');
    if (cardView) cardView.classList.toggle('d-none', publicCurrentView !== 'cards');
    if (gridView) gridView.classList.add('d-none');
    if (listControls) {
      listControls.classList.remove('d-none');
      listControls.classList.add('d-flex');
    }
    if (gridControls) {
      gridControls.classList.add('d-none');
      gridControls.classList.remove('d-flex');
    }
    if (filterBtn) filterBtn.classList.remove('d-none');
    if (viewInfo) viewInfo.textContent = publicCurrentView === 'cards' ? 'Cards surface status, metadata, and quick actions.' : '';
    fetchPublicDocs();
  } else {
    if (listView) listView.classList.add('d-none');
    if (cardView) cardView.classList.add('d-none');
    if (gridView) gridView.classList.remove('d-none');
    if (listControls) {
      listControls.classList.add('d-none');
      listControls.classList.remove('d-flex');
    }
    if (gridControls) {
      gridControls.classList.remove('d-none');
      gridControls.classList.add('d-flex');
    }
    if (filterBtn) filterBtn.classList.add('d-none');
    if (filterCollapse) {
      const bsCollapse = bootstrap.Collapse.getInstance(filterCollapse);
      if (bsCollapse) bsCollapse.hide();
    }
    if (viewInfo) {
      viewInfo.textContent = publicCurrentView === 'folders-cards'
        ? ''
        : '';
    }
    if (publicSelectionMode) {
      togglePublicSelectionMode();
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
    if (folderItems.length === 0) {
      container.innerHTML = '<div class="col-12 text-center text-muted py-5"><i class="bi bi-folder2-open display-1 mb-3"></i><p>No folders yet. Add tags to documents to organize them.</p></div>';
      return;
    }

    const cards = document.createDocumentFragment();
    folderItems.forEach((item) => {
      cards.appendChild(createPublicFolderCard(item, canManageTags));
    });
    container.replaceChildren(cards);
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
  const selectionModeClass = publicSelectionMode ? ' selection-mode' : '';
  let html = `<table class="table table-striped table-sm${selectionModeClass}" id="public-folder-docs-table"><thead><tr>`;
  html += '<th style="width:50px;"><input type="checkbox" class="form-check-input document-select-all-checkbox" aria-label="Select all visible public folder documents" /></th>';
  html += `<th class="folder-sortable-header" data-sort-field="file_name" style="cursor:pointer;user-select:none;">File Name <i class="bi ${getSortIcon('file_name')} small"></i></th>`;
  html += `<th class="folder-sortable-header" data-sort-field="title" style="cursor:pointer;user-select:none;">Title <i class="bi ${getSortIcon('title')} small"></i></th>`;
  html += '<th>Actions</th></tr></thead><tbody>';
  const canManage = ['Owner', 'Admin', 'DocumentManager'].includes(userRoleInActivePublic);
  docs.forEach(doc => {
    const pctString = String((doc.percentage_complete ?? doc.percentage) || '0');
    const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
    const docStatus = doc.status || '';
    const isComplete = pct >= 100 || docStatus.toLowerCase().includes('complete') || docStatus.toLowerCase().includes('error');
    const hasError = docStatus.toLowerCase().includes('error') || docStatus.toLowerCase().includes('failed');
    const isSelected = publicSelectedDocuments.has(doc.id);
    let firstColHtml = `<input type="checkbox" class="form-check-input document-checkbox${publicSelectionMode ? '' : ' d-none'}" data-document-id="${doc.id}"${isSelected ? ' checked' : ''}>`;
    let actionsHtml = '';

    if (isComplete && !hasError) {
      actionsHtml = `<button class="btn btn-sm btn-primary me-1" onclick="searchPublicDocumentInChat('${doc.id}')" title="Chat"><i class="bi bi-chat-dots-fill me-1"></i>Chat</button>
        <div class="dropdown action-dropdown d-inline-block">
          <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots-vertical"></i></button>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="#" onclick="togglePublicSelectionMode(); return false;"><i class="bi bi-check-square me-2"></i>Select</a></li>
            <li><a class="dropdown-item" href="#" onclick="searchPublicDocumentInChat('${doc.id}'); return false;"><i class="bi bi-chat-dots-fill me-2"></i>Chat</a></li>`;
      if (canManage) {
        const reprocessDocId = escapeHtml(String(doc.id || ''));
        const extractionActionMode = getPublicDocumentTargetExtractionMode(doc);
        const extractionActionLabel = getPublicDocumentExtractionModeLabelFromMode(extractionActionMode);
        const extractionActionIcon = getPublicDocumentExtractionModeIcon(extractionActionMode);
        const extractionActionTooltip = getPublicDocumentExtractionChangeTooltip(extractionActionMode);
        actionsHtml += `<li><a class="dropdown-item" href="#" onclick="window.onEditPublicDocument('${doc.id}'); return false;"><i class="bi bi-pencil-fill me-2"></i>Edit Metadata</a></li>
            <li><a class="dropdown-item" href="#" onclick="window.onExtractPublicMetadata('${doc.id}', event); return false;"><i class="bi bi-magic me-2"></i>Extract Metadata</a></li>
        ${isPublicPdfDocument(doc) ? `<li><hr class="dropdown-divider"></li>
        <li><h6 class="dropdown-header">Change Extraction</h6></li>
        <li><a class="dropdown-item" href="#" title="${escapeHtml(extractionActionTooltip)}" onclick="window.reprocessPublicDocumentExtraction('${reprocessDocId}', '${extractionActionMode}', event); return false;"><i class="bi ${extractionActionIcon} me-2"></i>Change to ${extractionActionLabel}</a></li>` : ''}
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item text-danger" href="#" onclick="deletePublicDocument('${doc.id}', event); return false;"><i class="bi bi-trash-fill me-2"></i>Delete</a></li>`;
      }
      actionsHtml += '</ul></div>';
    } else if (hasError) {
      actionsHtml = `<span class="text-danger small">${escapeHtml(docStatus || 'Processing error')}</span>`;
    } else {
      actionsHtml = `<span class="text-muted small">${escapeHtml(docStatus || 'Pending approval')}</span>`;
    }

    html += `<tr>
      <td>${firstColHtml}</td>
      <td title="${escapeHtml(doc.file_name)}">${getPublicDocumentSyncBadgeHtml(doc, true)}${escapeHtml(doc.file_name)}</td>
      <td title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || '')}</td>
      <td>${actionsHtml}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  return html;
}

function buildPublicFolderDocumentsCardsHtml() {
  return '<div id="public-folder-documents-card-view" class="row g-3"></div>';
}

function renderPublicFolderDocumentCards(docs) {
  const cardContainer = document.getElementById('public-folder-documents-card-view');
  renderPublicDocumentCards(docs, cardContainer);
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
  if (gridControls) {
    gridControls.classList.add('d-none');
    gridControls.classList.remove('d-flex');
  }
  container.className = '';

  const isClassification = (publicCurrentFolderType === 'classification');
  let displayName, tagColor;
  if (tagName === '__untagged__') { displayName = 'Untagged Documents'; tagColor = '#6c757d'; }
  else if (tagName === '__unclassified__') { displayName = 'Unclassified Documents'; tagColor = '#6c757d'; }
  else if (isClassification) {
    const cat = (window.classification_categories || []).find(c => c.label === tagName);
    displayName = tagName; tagColor = normalizePublicHexColor(cat?.color, '#6c757d');
  } else {
    displayName = tagName; tagColor = getPublicTagColorByName(tagName, '#6c757d');
  }

  const viewInfo = document.getElementById('public-docs-view-info');
  //if (viewInfo) viewInfo.textContent = `Viewing: ${displayName}`;

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
      html += publicCurrentView === 'folders-cards'
        ? buildPublicFolderDocumentsCardsHtml()
        : buildPublicFolderDocumentsTable(docs);
      html += '<div id="public-folder-pagination" class="d-flex justify-content-center mt-3"></div>';
    }

    container.innerHTML = html;
    wirePublicBackButton(container);
    if (publicCurrentView === 'folders-cards' && docs.length > 0) {
      renderPublicFolderDocumentCards(docs);
    } else {
      wirePublicFolderGeneratedArtifactApproveButtons(docs);
    }
    syncPublicSelectionModeUI();

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
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView(); else fetchPublicDocs(); }
      else alert('Error: ' + (data.error || 'Failed to rename'));
    }).catch(e => { console.error(e); alert('Error renaming tag'); });
}

function changePublicTagColor(tagName, currentColor) {
  const safeCurrentColor = currentColor || getPublicTagColorByName(tagName, '#0d6efd');
  const newColor = prompt(`Enter new hex color for "${tagName}":`, safeCurrentColor);
  if (!newColor || newColor === safeCurrentColor) return;
  fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ color: newColor.trim() })
  }).then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView(); }
      else alert('Error: ' + (data.error || 'Failed to change color'));
    }).catch(e => { console.error(e); alert('Error changing tag color'); });
}

function deletePublicTag(tagName) {
  if (!confirm(`Delete tag "${tagName}" from all documents?`)) return;
  fetch(`/api/public_workspace_documents/tags/${encodeURIComponent(tagName)}`, { method: 'DELETE' })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      if (ok) { alert(data.message); loadPublicWorkspaceTags(); if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView(); else fetchPublicDocs(); }
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

const publicHexColorPattern = /^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function normalizePublicHexColor(color, fallback = '#6c757d') {
  const rawColor = typeof color === 'string' ? color.trim() : '';
  const fallbackColor = typeof fallback === 'string' ? fallback.trim() : '#6c757d';
  const candidate = publicHexColorPattern.test(rawColor)
    ? rawColor
    : (publicHexColorPattern.test(fallbackColor) ? fallbackColor : '#6c757d');

  let normalizedColor = candidate.startsWith('#') ? candidate : `#${candidate}`;
  if (normalizedColor.length === 4) {
    normalizedColor = '#' + normalizedColor.slice(1).split('').map((component) => component + component).join('');
  }

  return normalizedColor.toLowerCase();
}

function getPublicWorkspaceTagByName(tagName) {
  return publicWorkspaceTags.find((tag) => tag.name === tagName) || null;
}

function getPublicTagColorByName(tagName, fallback = '#6c757d') {
  const tag = getPublicWorkspaceTagByName(tagName);
  return normalizePublicHexColor(tag?.color, fallback);
}

function applyPublicBackgroundColor(element, color, fallback = '#6c757d') {
  const safeColor = normalizePublicHexColor(color, fallback);
  element.style.backgroundColor = safeColor;
  return safeColor;
}

function applyPublicForegroundColor(element, color, fallback = '#6c757d') {
  const safeColor = normalizePublicHexColor(color, fallback);
  element.style.color = safeColor;
  return safeColor;
}

function createPublicTagBadgeElement(tagName, color, className = 'tag-badge') {
  const badge = document.createElement('span');
  badge.className = className;
  const safeColor = applyPublicBackgroundColor(badge, color);
  badge.style.color = isPublicColorLight(safeColor) ? '#000' : '#fff';
  badge.textContent = String(tagName || '');
  return badge;
}

function createPublicDropdownItem(iconClasses, label, onClick, danger = false, title = '') {
  const listItem = document.createElement('li');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `dropdown-item${danger ? ' text-danger' : ''}`;
  if (title) {
    button.title = title;
  }

  const icon = document.createElement('i');
  icon.className = `bi ${iconClasses} me-2`;
  button.appendChild(icon);
  button.appendChild(document.createTextNode(label));

  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    onClick();
  });

  listItem.appendChild(button);
  return listItem;
}

function createPublicDropdownDivider() {
  const listItem = document.createElement('li');
  const divider = document.createElement('hr');
  divider.className = 'dropdown-divider';
  listItem.appendChild(divider);
  return listItem;
}

function createPublicFolderActionsMenu(item, canManageTags) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tag-folder-actions';

  const dropdown = document.createElement('div');
  dropdown.className = 'dropdown';

  const menuButton = document.createElement('button');
  menuButton.type = 'button';
  menuButton.className = 'tag-folder-menu-btn';
  menuButton.setAttribute('data-bs-toggle', 'dropdown');
  menuButton.addEventListener('click', (event) => {
    event.stopPropagation();
  });

  const menuIcon = document.createElement('i');
  menuIcon.className = 'bi bi-three-dots-vertical';
  menuButton.appendChild(menuIcon);

  const menu = document.createElement('ul');
  menu.className = 'dropdown-menu';

  if (item.type === 'classification') {
    menu.appendChild(createPublicDropdownItem('bi-chat-dots', 'Chat', () => chatWithPublicFolder('classification', item.key)));
  } else if (item.isSpecial) {
    menu.appendChild(createPublicDropdownItem('bi-chat-dots', 'Chat', () => chatWithPublicFolder('tag', item.key)));
  } else if (canManageTags) {
    menu.appendChild(createPublicDropdownItem('bi-chat-dots', 'Chat', () => chatWithPublicFolder('tag', item.key)));
    menu.appendChild(createPublicDropdownItem('bi-pencil', 'Rename Tag', () => renamePublicTag(item.key)));
    menu.appendChild(createPublicDropdownItem('bi-palette', 'Change Color', () => changePublicTagColor(item.key, item.tagData?.color)));
    menu.appendChild(createPublicDropdownDivider());
    menu.appendChild(createPublicDropdownItem('bi-trash', 'Delete Tag', () => deletePublicTag(item.key), true));
  }

  dropdown.appendChild(menuButton);
  dropdown.appendChild(menu);
  wrapper.appendChild(dropdown);

  return wrapper;
}

function createPublicFolderCard(item, canManageTags) {
  const col = document.createElement('div');
  col.className = 'col-6 col-sm-4 col-md-3 col-lg-2';

  const card = document.createElement('div');
  card.className = 'tag-folder-card';
  card.dataset.tag = item.key;
  card.dataset.folderType = item.type;

  const countLabel = `${item.count} file${item.count !== 1 ? 's' : ''}`;
  card.title = `${item.displayName} (${countLabel})`;

  const actions = createPublicFolderActionsMenu(item, canManageTags);
  if (actions.querySelector('.dropdown-item')) {
    card.appendChild(actions);
  }

  const iconWrapper = document.createElement('div');
  iconWrapper.className = 'tag-folder-icon';
  const icon = document.createElement('i');
  icon.className = `bi ${item.icon}`;
  applyPublicForegroundColor(icon, item.color);
  iconWrapper.appendChild(icon);

  const name = document.createElement('div');
  name.className = `tag-folder-name${item.isSpecial ? ' text-muted' : ''}`;
  name.textContent = item.displayName;

  const count = document.createElement('div');
  count.className = 'tag-folder-count';
  count.textContent = countLabel;

  card.appendChild(iconWrapper);
  card.appendChild(name);
  card.appendChild(count);

  card.addEventListener('click', (event) => {
    if (event.target.closest('.tag-folder-actions')) {
      return;
    }

    publicCurrentFolder = item.key;
    publicCurrentFolderType = item.type || 'tag';
    publicFolderCurrentPage = 1;
    publicFolderSortBy = '_ts';
    publicFolderSortOrder = 'desc';
    publicFolderSearchTerm = '';
    renderPublicFolderContents(publicCurrentFolder);
  });

  col.appendChild(card);
  return col;
}

function isColorLight(hexColor) {
  const hex = normalizePublicHexColor(hexColor).replace('#', '');
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
    const safeColor = applyPublicBackgroundColor(el, tag.color);
    el.className = `tag-badge ${isColorLight(safeColor) ? 'text-dark' : 'text-light'}`;
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

function getPublicBulkTagLoadingLabel(buttonLoading) {
  const existingLabel = buttonLoading.querySelector('.button-loading-label');
  if (existingLabel) {
    return existingLabel;
  }

  const textNode = Array.from(buttonLoading.childNodes).find((node) => {
    return node.nodeType === 3 && node.textContent.trim().length > 0;
  });
  if (textNode) {
    return textNode;
  }

  const fallbackLabel = document.createElement('span');
  fallbackLabel.className = 'button-loading-label';
  fallbackLabel.textContent = 'Applying...';
  buttonLoading.appendChild(fallbackLabel);
  return fallbackLabel;
}

function setPublicBulkTagButtonLoadingState(applyBtn, isLoading, current = 0, total = 0) {
  const btnText = applyBtn.querySelector('.button-text');
  const btnLoad = applyBtn.querySelector('.button-loading');
  const loadingLabel = getPublicBulkTagLoadingLabel(btnLoad);
  const loadingText = isLoading && total > 0
    ? `Applying ${Math.min(current, total)}/${total}...`
    : 'Applying...';

  applyBtn.disabled = isLoading;
  btnText.classList.toggle('d-none', isLoading);
  btnLoad.classList.toggle('d-none', !isLoading);
  loadingLabel.textContent = loadingText;
}

function mergePublicBulkTagResults(targetResults, result) {
  if (Array.isArray(result?.success) && result.success.length > 0) {
    targetResults.success.push(...result.success);
  }

  if (Array.isArray(result?.errors) && result.errors.length > 0) {
    targetResults.errors.push(...result.errors);
  }
}

async function applyPublicBulkTagChanges() {
  const action = document.getElementById('public-bulk-tag-action').value;
  const selectedTags = Array.from(publicBulkSelectedTags);
  const documentIds = Array.from(publicSelectedDocuments);
  if (documentIds.length === 0) { alert('No documents selected'); return; }
  if (selectedTags.length === 0) { alert('Please select at least one tag'); return; }

  const applyBtn = document.getElementById('public-bulk-tag-apply-btn');
  const totalDocuments = documentIds.length;
  const results = { success: [], errors: [] };
  let processedCount = 0;

  try {
    for (let index = 0; index < documentIds.length; index += 1) {
      const documentId = documentIds[index];
      setPublicBulkTagButtonLoadingState(applyBtn, true, index + 1, totalDocuments);

      const response = await fetch('/api/public_workspace_documents/bulk-tag', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_ids: [documentId], action: action, tags: selectedTags })
      });
      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || `Failed to update tags for document ${documentId}`);
      }

      mergePublicBulkTagResults(results, result);
      processedCount = index + 1;
    }

    const sc = results.success.length;
    const ec = results.errors.length;
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
  } catch (e) {
    console.error(e);

    if (processedCount > 0) {
      await loadPublicWorkspaceTags();
      fetchPublicDocs();
    }

    let errorMessage = 'Error updating tags';
    if (processedCount > 0) {
      errorMessage = `Stopped after ${processedCount}/${totalDocuments} document(s).`;
      if (results.success.length > 0) errorMessage += `\nUpdated ${results.success.length} document(s) before the error.`;
      if (results.errors.length > 0) errorMessage += `\n${results.errors.length} document(s) had errors before the stop.`;
      errorMessage += `\n${e.message}`;
    }

    alert(errorMessage);
  } finally {
    setPublicBulkTagButtonLoadingState(applyBtn, false);
  }
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
  if (savedView === 'cards') {
    const cardsRadio = document.getElementById('public-docs-view-cards');
    if (cardsRadio) { cardsRadio.checked = true; switchPublicView('cards'); }
  } else if (savedView === 'grid') {
    const gridRadio = document.getElementById('public-docs-view-grid');
    if (gridRadio) { gridRadio.checked = true; switchPublicView('grid'); }
  } else if (savedView === 'folders-cards') {
    const foldersCardsRadio = document.getElementById('public-docs-view-folders-cards');
    if (foldersCardsRadio) { foldersCardsRadio.checked = true; switchPublicView('folders-cards'); }
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
  hex = normalizePublicHexColor(hex).replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16), g = parseInt(hex.substring(2, 4), 16), b = parseInt(hex.substring(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 155;
}

function escapePublicHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function renderPublicTagBadges(tags, container, maxDisplay = 3) {
  if (!container) return;

  container.textContent = '';

  if (!Array.isArray(tags) || tags.length === 0) {
    const emptyState = document.createElement('span');
    emptyState.className = 'text-muted small';
    emptyState.textContent = 'No tags';
    container.appendChild(emptyState);
    return;
  }

  const fragment = document.createDocumentFragment();
  const displayTags = tags.slice(0, maxDisplay);

  displayTags.forEach((tagName) => {
    const badge = createPublicTagBadgeElement(tagName, getPublicTagColorByName(tagName), 'tag-badge me-1');
    badge.title = tagName;
    fragment.appendChild(badge);
  });

  if (tags.length > maxDisplay) {
    const extraBadge = document.createElement('span');
    extraBadge.className = 'badge bg-secondary';
    extraBadge.textContent = `+${tags.length - maxDisplay}`;
    fragment.appendChild(extraBadge);
  }

  container.appendChild(fragment);
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
  tbody.textContent = '';
  const fragment = document.createDocumentFragment();

  publicWorkspaceTags.forEach((tag) => {
    const row = document.createElement('tr');

    const colorCell = document.createElement('td');
    const colorSwatch = document.createElement('div');
    colorSwatch.style.width = '30px';
    colorSwatch.style.height = '30px';
    colorSwatch.style.borderRadius = '4px';
    colorSwatch.style.border = '1px solid #dee2e6';
    applyPublicBackgroundColor(colorSwatch, tag.color);
    colorCell.appendChild(colorSwatch);

    const tagCell = document.createElement('td');
    tagCell.appendChild(createPublicTagBadgeElement(tag.name, tag.color, 'badge'));

    const countCell = document.createElement('td');
    countCell.textContent = String(tag.count);

    const actionsCell = document.createElement('td');
    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'btn btn-sm btn-outline-primary me-1';
    editButton.innerHTML = '<i class="bi bi-pencil"></i>';
    editButton.addEventListener('click', () => {
      window.editPublicTagInModal(tag.name);
    });

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'btn btn-sm btn-outline-danger';
    deleteButton.innerHTML = '<i class="bi bi-trash"></i>';
    deleteButton.addEventListener('click', () => {
      window.deletePublicTagFromModal(tag.name);
    });

    actionsCell.appendChild(editButton);
    actionsCell.appendChild(deleteButton);

    row.appendChild(colorCell);
    row.appendChild(tagCell);
    row.appendChild(countCell);
    row.appendChild(actionsCell);
    fragment.appendChild(row);
  });

  tbody.appendChild(fragment);
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

window.editPublicTagInModal = function(tagName) {
  const currentColor = getPublicTagColorByName(tagName, '#0d6efd');
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
        if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView();
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
        if (publicCurrentView === 'grid' || publicCurrentView === 'folders-cards') renderPublicGridView();
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

function showPublicFileSyncTagSelectionModal(initialTags, onDone) {
  publicDocSelectedTags = new Set(initialTags || []);
  publicFileSyncTagSelectionDone = onDone;
  showPublicTagSelectionModal();
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
  listContainer.textContent = '';
  const fragment = document.createDocumentFragment();

  publicWorkspaceTags.forEach((tag) => {
    const row = document.createElement('label');
    row.className = 'list-group-item d-flex align-items-center';
    row.style.cursor = 'pointer';

    const checkbox = document.createElement('input');
    checkbox.className = 'form-check-input me-3';
    checkbox.type = 'checkbox';
    checkbox.value = tag.name;
    checkbox.checked = publicDocSelectedTags.has(tag.name);
    checkbox.addEventListener('change', (event) => {
      if (event.target.checked) {
        publicDocSelectedTags.add(event.target.value);
      } else {
        publicDocSelectedTags.delete(event.target.value);
      }
    });

    const badge = createPublicTagBadgeElement(tag.name, tag.color, 'badge me-2');

    const count = document.createElement('span');
    count.className = 'ms-auto text-muted small';
    count.textContent = `${tag.count} docs`;

    row.appendChild(checkbox);
    row.appendChild(badge);
    row.appendChild(count);
    fragment.appendChild(row);
  });

  listContainer.appendChild(fragment);
}

// --- Document Tags Display ---
function updatePublicDocTagsDisplay() {
  const container = document.getElementById('public-doc-selected-tags-container');
  if (!container) return;
  if (publicDocSelectedTags.size === 0) {
    container.innerHTML = '<span class="text-muted small">No tags selected</span>';
    return;
  }

  container.textContent = '';
  publicDocSelectedTags.forEach((tagName) => {
    const badge = createPublicTagBadgeElement(tagName, getPublicTagColorByName(tagName), 'badge me-1');
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'btn btn-link btn-sm text-reset text-decoration-none p-0 ms-1 align-baseline';
    removeButton.setAttribute('aria-label', `Remove ${tagName}`);

    const removeIcon = document.createElement('i');
    removeIcon.className = 'bi bi-x';
    removeButton.appendChild(removeIcon);
    removeButton.addEventListener('click', () => {
      window.removePublicDocSelectedTag(tagName);
    });

    badge.appendChild(document.createTextNode(' '));
    badge.appendChild(removeButton);
    container.appendChild(badge);
  });
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
      if (publicFileSyncTagSelectionDone) {
        publicFileSyncTagSelectionDone(Array.from(publicDocSelectedTags));
        publicFileSyncTagSelectionDone = null;
      } else {
        updatePublicDocTagsDisplay();
      }
      publicTagSelectionModal.hide();
    });
  }

  window.simpleChatTagModalAdapters = window.simpleChatTagModalAdapters || {};
  window.simpleChatTagModalAdapters.public = {
    openSelector: ({ selectedTags = [], onDone } = {}) => showPublicFileSyncTagSelectionModal(selectedTags, onDone),
    openManager: () => showPublicTagManagementModal(),
  };

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
