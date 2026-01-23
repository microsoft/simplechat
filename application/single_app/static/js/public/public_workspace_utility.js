// static/js/public/public_workspace_utility.js
// Shared utility functions for public workspace operations

/**
 * Escapes HTML special characters to prevent XSS
 * @param {string} unsafe - The string to escape
 * @returns {string} - The escaped string
 */
function escapeHtml(unsafe) {
  if (!unsafe) return '';
  const div = document.createElement('div');
  div.textContent = unsafe.toString();
  return div.innerHTML;
}

/**
 * Updates the workspace status alert display based on workspace status
 * @param {Object} options - Configuration options
 * @param {string} options.status - The workspace status ('active', 'locked', 'upload_disabled', 'inactive')
 * @param {string} [options.alertElementId='workspace-status-alert'] - ID of the alert container element
 * @param {string} [options.contentElementId='workspace-status-content'] - ID of the content element
 */
function updateWorkspaceStatusAlert(options) {
  const {
    status,
    alertElementId = 'workspace-status-alert',
    contentElementId = 'workspace-status-content'
  } = options;

  const statusAlert = document.getElementById(alertElementId);
  const statusContent = document.getElementById(contentElementId);
  
  if (!statusAlert || !statusContent) return;
  
  const statusMessages = {
    'locked': {
      type: 'warning',
      icon: 'bi-lock-fill',
      title: '🔒 Locked (Read-Only)',
      message: 'Workspace is in read-only mode',
      details: [
        '❌ New document uploads',
        '❌ Document deletions',
        '❌ Creating, editing, or deleting prompts',
        '✅ Viewing existing documents',
        '✅ Chat and search with existing documents',
        '✅ Using existing prompts'
      ]
    },
    'upload_disabled': {
      type: 'info',
      icon: 'bi-cloud-slash-fill',
      title: '📁 Upload Disabled',
      message: 'Restrict new content but allow other operations',
      details: [
        '❌ New document uploads',
        '✅ Document deletions (cleanup)',
        '✅ Full chat and search functionality',
        '✅ Creating, editing, and deleting prompts'
      ]
    },
    'inactive': {
      type: 'danger',
      icon: 'bi-exclamation-triangle-fill',
      title: '⭕ Inactive',
      message: 'Workspace is disabled',
      details: [
        '❌ ALL operations (uploads, chat, document access)',
        '❌ Creating, editing, or deleting prompts',
        '✅ Only admin viewing of workspace information',
        'Use case: Decommissioned projects, suspended workspaces, compliance holds'
      ]
    }
  };
  
  // Hide alert for active status
  if (status === 'active') {
    statusAlert.classList.add('d-none');
    statusAlert.classList.remove('alert-warning', 'alert-info', 'alert-danger');
    return;
  }
  
  const config = statusMessages[status];
  if (config) {
    statusAlert.classList.remove('d-none', 'alert-warning', 'alert-info', 'alert-danger');
    statusAlert.classList.add(`alert-${config.type}`);
    
    const detailsList = config.details.map(d => `<li class="mb-1">${d}</li>`).join('');
    
    statusContent.innerHTML = `
      <div class="d-flex align-items-start">
        <i class="bi ${config.icon} me-2 flex-shrink-0" style="font-size: 1.2rem;"></i>
        <div>
          <strong>${config.title}</strong> - ${config.message}
          <ul class="mb-0 mt-2 small">
            ${detailsList}
          </ul>
        </div>
      </div>
    `;
  } else {
    statusAlert.classList.add('d-none');
  }
}

/**
 * Fetches workspace details and updates the status alert
 * @param {string} workspaceId - The ID of the workspace to fetch
 * @param {Function} [callback] - Optional callback to execute after status is updated
 * @param {string} [alertElementId='workspace-status-alert'] - ID of the alert container element
 * @param {string} [contentElementId='workspace-status-content'] - ID of the content element
 */
function fetchAndUpdateWorkspaceStatus(workspaceId, callback, alertElementId = 'workspace-status-alert', contentElementId = 'workspace-status-content') {
  if (!workspaceId) return;
  
  fetch(`/api/public_workspaces/${workspaceId}`)
    .then(response => response.json())
    .then(workspace => {
      const status = workspace.status || 'active';
      updateWorkspaceStatusAlert({ 
        status, 
        alertElementId, 
        contentElementId 
      });
      
      if (callback && typeof callback === 'function') {
        callback(workspace);
      }
    })
    .catch(err => {
      console.error('Error fetching workspace status:', err);
    });
}
