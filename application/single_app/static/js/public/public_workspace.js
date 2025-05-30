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
const fileInput = document.getElementById('public-file-input');
const uploadBtn = document.getElementById('public-upload-btn');
const uploadStatus = document.getElementById('public-upload-status');
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

  btnMyPublics.onclick = ()=> window.location.href = '/my_public_workspaces';
  btnChangePublic.onclick = onChangeActivePublic;

  uploadBtn.onclick = onPublicUploadClick;
  publicDocsPageSizeSelect.onchange = (e)=>{ publicDocsPageSize = +e.target.value; publicDocsCurrentPage=1; fetchPublicDocs(); };
  docsApplyBtn.onclick = ()=>{ publicDocsSearchTerm = publicDocsSearchInput.value.trim(); publicDocsCurrentPage=1; fetchPublicDocs(); };
  docsClearBtn.onclick = ()=>{ publicDocsSearchInput.value=''; publicDocsSearchTerm=''; publicDocsCurrentPage=1; fetchPublicDocs(); };
  publicDocsSearchInput.onkeypress = e=>{ if(e.key==='Enter') docsApplyBtn.click(); };

  createPublicPromptBtn.onclick = ()=> openPublicPromptModal();
  publicPromptForm.onsubmit = onSavePublicPrompt;
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
  if(activePublicId){ document.getElementById('user-public-role').textContent=userRoleInActivePublic; document.getElementById('active-public-name-role').textContent=activePublicName; display.style.display='block'; uploadSection.style.display=['Owner','Admin','DocumentManager'].includes(userRoleInActivePublic)?'block':'none'; uploadHr.style.display=uploadSection.style.display; } else display.style.display='none';
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

function renderPublicDocumentRow(doc){
  const canManage=['Owner','Admin','DocumentManager'].includes(userRoleInActivePublic);
  const tr=document.createElement('tr'); tr.innerHTML=`
    <td>${doc.percentage_complete>=100?'<i class="bi bi-file-earmark-text-fill"></i>':'<i class="bi bi-hourglass-split"></i>'}</td>
    <td title="${escapeHtml(doc.file_name)}">${escapeHtml(doc.file_name)}</td>
    <td title="${escapeHtml(doc.title||'')}">${escapeHtml(doc.title||'')}</td>
    <td>${canManage?`<button class="btn btn-sm btn-danger" onclick="deletePublicDocument('${doc.id}')"><i class="bi bi-trash-fill"></i></button>`:''}</td>`;
  document.querySelector('#public-documents-table tbody').append(tr);
}

function renderPublicDocsPagination(page, pageSize, totalCount){
  const container=publicDocsPagination; container.innerHTML=''; const totalPages=Math.ceil(totalCount/pageSize); if(totalPages<=1) return;
  const ul=document.createElement('ul'); ul.className='pagination pagination-sm mb-0';
  function make(p,text,disabled,active){ const li=document.createElement('li'); li.className=`page-item${disabled?' disabled':''}${active?' active':''}`; const a=document.createElement('a'); a.className='page-link'; a.href='#'; a.textContent=text; if(!disabled&&!active) a.onclick=e=>{e.preventDefault();publicDocsCurrentPage=p;fetchPublicDocs();}; li.append(a); return li; }
  ul.append(make(page-1,'«',page<=1,false)); let start=1,end=totalPages; if(totalPages>5){ const mid=2; if(page>mid) start=page-mid; end=start+4; if(end>totalPages){ end=totalPages; start=end-4; } } if(start>1){ ul.append(make(1,'1',false,false)); ul.append(make(0,'...',true,false)); } for(let p=start;p<=end;p++) ul.append(make(p,p,false,p===page)); if(end<totalPages){ ul.append(make(0,'...',true,false)); ul.append(make(totalPages,totalPages,false,false)); } ul.append(make(page+1,'»',page>=totalPages,false)); container.append(ul);
}

async function onPublicUploadClick(){
  const files=fileInput.files;
  if(!files.length) return alert('Select files');
  uploadBtn.disabled=true; uploadBtn.innerHTML='<span class="spinner-border spinner-border-sm me-2"></span>Uploading...'; uploadStatus.textContent=`Uploading ${files.length} file(s)...`;
  const fd=new FormData(); Array.from(files).forEach(f=>fd.append('file',f,f.name));
  try{ const r=await fetch('/api/public_documents/upload',{method:'POST',body:fd}); if(!r.ok) throw await r.json(); const d=await r.json(); uploadStatus.textContent=`Uploaded ${d.document_ids.length}/${files.length}`; fileInput.value=''; publicDocsCurrentPage=1; fetchPublicDocs(); }catch(err){ alert(`Upload failed: ${err.error||err.message}`); }
  finally{ uploadBtn.disabled=false; uploadBtn.textContent='Upload Document(s)'; }
}
window.deletePublicDocument=async function(id){ if(!confirm('Delete?')) return; try{ await fetch(`/api/public_documents/${id}`,{method:'DELETE'}); fetchPublicDocs(); }catch(e){ alert(`Error deleting: ${e.error||e.message}`);} };

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

function updatePublicPromptsRoleUI(){ const canManage=['Owner','Admin','PromptManager'].includes(userRoleInActivePublic); document.getElementById('create-public-prompt-section').style.display=canManage?'block':'none'; document.getElementById('public-prompts-role-warning').style.display=canManage?'none':'block'; }

// Expose fetch
window.fetchPublicPrompts = fetchPublicPrompts;
window.fetchPublicDocs = fetchPublicDocs;
