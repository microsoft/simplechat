// static/js/public_workspace.js
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

// Modals
const publicPromptModal = new bootstrap.Modal(document.getElementById('publicPromptModal'));
const publicDocMetadataModal = new bootstrap.Modal(document.getElementById('publicDocMetadataModal'));

// Editors
let publicSimplemde = null;
const publicPromptContentEl = document.getElementById('public-prompt-content');
if (publicPromptContentEl && window.SimpleMDE) {
  publicSimplemde = new SimpleMDE({ element: publicPromptContentEl, spellChecker:false });
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

// Helper
function escapeHtml(unsafe) {
  if (!unsafe) return '';
  return unsafe.toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

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
  if (uploadBtn) uploadBtn.onclick = onPublicUploadClick;
  
  // Add upload area functionality (drag-and-drop and click-to-browse)
  const uploadArea = document.getElementById('upload-area');
  if (fileInput && uploadArea) {
    // Auto-upload on file selection
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        onPublicUploadClick();
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
        // Set the files to the file input and trigger upload
        fileInput.files = e.dataTransfer.files;
        onPublicUploadClick();
      }
    });
  }
  
  if (publicDocsPageSizeSelect) publicDocsPageSizeSelect.onchange = (e)=>{ publicDocsPageSize = +e.target.value; publicDocsCurrentPage=1; fetchPublicDocs(); };
  if (docsApplyBtn) docsApplyBtn.onclick = ()=>{ publicDocsSearchTerm = publicDocsSearchInput.value.trim(); publicDocsCurrentPage=1; fetchPublicDocs(); };
  if (docsClearBtn) docsClearBtn.onclick = ()=>{ publicDocsSearchInput.value=''; publicDocsSearchTerm=''; publicDocsCurrentPage=1; fetchPublicDocs(); };
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
  } else {
    if (display) display.style.display = 'none';
  }
}

function loadActivePublicData(){
  const activeTab = document.querySelector('#publicWorkspaceTab .nav-link.active').dataset.bsTarget;
  if(activeTab==='#public-docs-tab') fetchPublicDocs(); else fetchPublicPrompts();
  updatePublicRoleDisplay(); updatePublicPromptsRoleUI();
}

async function fetchPublicDocs(){
  if(!activePublicId) return;
  publicDocsTableBody.innerHTML='<tr class="table-loading-row"><td colspan="4"><div class="spinner-border spinner-border-sm me-2"></div> Loading public documents...</td></tr>';
  publicDocsPagination.innerHTML='';
  const params=new URLSearchParams({page:publicDocsCurrentPage,page_size:publicDocsPageSize});
  if(publicDocsSearchTerm) params.append('search',publicDocsSearchTerm);
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
    firstTdHtml = `<button class="btn btn-link p-0" onclick="window.togglePublicDetails('${doc.id}')" title="Show/Hide Details"><span id="public-arrow-icon-${doc.id}" class="bi bi-chevron-right"></span></button>`;
  } else if (hasError) {
    firstTdHtml = `<span class="text-danger" title="Processing Error: ${escapeHtml(docStatus)}"><i class="bi bi-exclamation-triangle-fill"></i></span>`;
  } else {
    firstTdHtml = `<span class="text-muted" title="Processing: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)"><i class="bi bi-hourglass-split"></i></span>`;
  }

  tr.innerHTML = `
    <td class="align-middle">${firstTdHtml}</td>
    <td class="align-middle" title="${escapeHtml(doc.file_name)}">${escapeHtml(doc.file_name)}</td>
    <td class="align-middle" title="${escapeHtml(doc.title || '')}">${escapeHtml(doc.title || '')}</td>
    <td class="align-middle">${canManage ? `<button class="btn btn-sm btn-danger" onclick="deletePublicDocument('${doc.id}', event)" title="Delete Document"><i class="bi bi-trash-fill"></i></button><button class="btn btn-sm btn-primary ms-1" onclick="searchPublicDocumentInChat('${doc.id}')" title="Search in Chat"><i class="bi bi-chat-dots-fill"></i> Chat</button>` : ''}</td>`;

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
  console.log(`Search public document in chat: ${docId}`);
  // TODO: Implement search in chat functionality
  alert('Search in chat functionality not yet implemented');
};

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
