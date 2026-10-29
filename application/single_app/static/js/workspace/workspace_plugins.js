// workspace_plugins.js (refactored to use plugin_common.js and new multi-step modal)
import { renderPluginsTable, renderPluginsGrid, ensurePluginsTableInRoot, validatePluginManifest, getErrorMessageFromResponse } from '../plugin_common.js';
import { showToast } from "../chat/chat-toast.js"
import {
    setupViewToggle, switchViewContainers, openViewModal, getMcpRetirementStatus
} from './view-utils.js';

const root = document.getElementById('workspace-plugins-root');
let plugins = [];
let filteredPlugins = [];
let currentViewMode = 'list';

function renderLoading() {
  root.innerHTML = `<div class="text-center p-4"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
}

function renderError(msg) {
  root.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
}

function getViewHandlers() {
  const findPlugin = key => plugins.find(plugin => plugin.id === key) || plugins.find(plugin => plugin.name === key);
  return {
    getPluginKey: plugin => plugin.id || plugin.name || '',
    onEdit: key => openPluginModal(findPlugin(key)),
    onDelete: key => deletePlugin(key),
    onView: key => {
      const plugin = findPlugin(key);
      if (plugin) {
        openViewModal(plugin, 'action', plugin.is_global ? {} : {
          onEdit: (item) => openPluginModal(item),
          onDelete: (item) => deletePlugin(item.id || item.name)
        });
      }
    }
  };
}

function filterPlugins(searchTerm) {
  if (!searchTerm || !searchTerm.trim()) {
    filteredPlugins = plugins;
  } else {
    const term = searchTerm.toLowerCase().trim();
    filteredPlugins = plugins.filter(plugin => {
      const displayName = (plugin.display_name || plugin.name || '').toLowerCase();
      const description = (plugin.description || '').toLowerCase();
      return displayName.includes(term) || description.includes(term);
    });
  }
  
  ensurePluginsTableInRoot();
  const handlers = getViewHandlers();
  
  renderPluginsTable({
    plugins: filteredPlugins,
    tbodySelector: '#plugins-table-body',
    ...handlers
  });
  renderPluginsGrid({
    plugins: filteredPlugins,
    containerSelector: '#plugins-grid-view',
    ...handlers
  });
}

async function fetchPlugins() {
  renderLoading();
  try {
    const res = await fetch('/api/user/plugins');
    if (!res.ok) throw new Error('Failed to load actions');
    plugins = await res.json();
    filteredPlugins = plugins; // Initialize filtered list
    
    // Ensure table template is in place
    ensurePluginsTableInRoot();
    const handlers = getViewHandlers();
    
    renderPluginsTable({
      plugins: filteredPlugins,
      tbodySelector: '#plugins-table-body',
      ...handlers
    });
    renderPluginsGrid({
      plugins: filteredPlugins,
      containerSelector: '#plugins-grid-view',
      ...handlers
    });
    
    // Set up view toggle (only once after template is in DOM)
    setupViewToggle('plugins', 'pluginsViewPreference', (mode) => {
      currentViewMode = mode;
      switchViewContainers(mode,
        document.getElementById('plugins-list-view'),
        document.getElementById('plugins-grid-view')
      );
    }, { mobileDefault: 'grid' });
    
    // Set up the create action button
    const createPluginBtn = document.getElementById('create-plugin-btn');
    if (createPluginBtn) {
      createPluginBtn.onclick = () => {
        console.log('[WORKSPACE ACTIONS] New Action button clicked');
        openPluginModal();
      };
    }
  } catch (e) {
    renderError(e.message);
  }
}

async function openPluginModal(plugin = null) {
  // Use the new multi-step modal
  if (window.pluginModalStepper) {
    window.pluginModalStepper.setActionScope({
      scope: 'personal',
      apiBase: '/api/workspace-identities/personal'
    });
    const modal = await window.pluginModalStepper.showModal(plugin);
    
    // Set up save handler
    setupSaveHandler(plugin, modal);
  } else {
    showToast('Action modal not available. Please refresh the page.', 'warning');
  }
}

function setupSaveHandler(plugin, modal) {
  const saveBtn = document.getElementById('save-plugin-btn');
  if (saveBtn) {
    // Remove any existing handlers
    saveBtn.onclick = null;
    
    saveBtn.onclick = async (event) => {
      event.preventDefault();
      const errorDiv = document.getElementById('plugin-modal-error');
      if (errorDiv) {
          errorDiv.classList.add('d-none');
          errorDiv.textContent = '';
      }
      try {
        // Get form data from the stepper
        const formData = window.pluginModalStepper.getFormData();
        
        // Validate with JSON schema
        const validation = await validatePluginManifest(formData);
        const validationFailed = validation === false || (validation && validation.valid === false);
        if (validationFailed) {
          const message = validation?.errors?.join('\n') || 'Validation error: Invalid action data.';
          window.pluginModalStepper.showError(message);
          return;
        }
        
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...`;
        saveBtn.disabled = true;
        // Save the action
        try {
          await savePlugin(formData, plugin);
        } catch (error) {
          window.pluginModalStepper.showError(error.message);
          return;
        } finally {
          saveBtn.innerHTML = originalText;
          saveBtn.disabled = false;
        }
        
        // Close modal and refresh
        if (modal && typeof modal.hide === 'function') {
          modal.hide();
        } else {
          bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
        }
        
        fetchPlugins();
        showToast(plugin ? 'Action updated successfully' : 'Action created successfully', 'success');
        
      } catch (error) {
        console.error('Error saving action:', error);
        window.pluginModalStepper.showError(error.message);
      }
    };
  }
}

async function savePlugin(pluginData, existingPlugin = null) {
  const payload = existingPlugin?.id ? { ...pluginData, id: existingPlugin.id } : { ...pluginData };

  // Get all plugins first
  const res = await fetch('/api/user/plugins');

  if (!res.ok) throw new Error('Failed to load existing actions');
  
  let plugins = await res.json();
  
  // Update or add the plugin
  let existingIndex;
  if (existingPlugin?.id) {
      existingIndex = plugins.findIndex(item => item.id === existingPlugin.id);
      if (existingIndex < 0) {
          throw new Error('This action is no longer available. Refresh the action list before saving.');
      }
  } else {
      const matchingName = existingPlugin?.name || payload.name;
      const matches = plugins.map((item, index) => item.name === matchingName ? index : -1).filter(index => index >= 0);
      if (matches.length > 1) {
          throw new Error('Multiple actions have this name. Refresh the list and edit the specific action.');
      }
      existingIndex = matches.length ? matches[0] : -1;
      if (!existingPlugin && existingIndex >= 0 && getMcpRetirementStatus(plugins[existingIndex])) {
          throw new Error('An unsupported action already has this name. Reconfigure or delete that action explicitly.');
      }
  }
  if (existingIndex >= 0) {
    plugins[existingIndex] = payload;
  } else {
    plugins.push(payload);
  }
  
  // Save back to server
  const saveRes = await fetch('/api/user/plugins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(plugins)
  });
  
  if (!saveRes.ok) {
    const errorMessage = await getErrorMessageFromResponse(saveRes, 'Failed to save action');
    throw new Error(errorMessage);
  }
}

async function deletePlugin(key) {
  const plugin = plugins.find(item => item.id === key) || plugins.find(item => item.name === key);
  if (!plugin || plugin.is_global) {
      return;
  }
  const name = plugin.name || '';
  const locator = plugin.id || name;
  if (!confirm(`Are you sure you want to delete action "${name}"?`)) return;
  
  try {
    const res = await fetch(`/api/user/plugins/${encodeURIComponent(locator)}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' }
    });
    
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to delete action');
    }
    
    // Refresh the plugins list
    fetchPlugins();
    showToast(`Action "${name}" deleted successfully`, 'success');
  } catch (e) {
    showToast('Error deleting action: ' + e.message, 'danger');
  }
}

// Initialize when the plugins tab is shown
document.addEventListener('DOMContentLoaded', () => {
  // Check if we're on the workspace page and the plugins tab exists
  const pluginsTabBtn = document.getElementById('plugins-tab-btn');
  if (pluginsTabBtn) {
    pluginsTabBtn.addEventListener('shown.bs.tab', fetchPlugins);
    
    // If plugins tab is already active, load immediately
    if (pluginsTabBtn.classList.contains('active')) {
      fetchPlugins();
    }
  }
  
  // Setup search functionality
  const pluginsSearchInput = document.getElementById('plugins-search');
  if (pluginsSearchInput) {
    pluginsSearchInput.addEventListener('input', (e) => {
      filterPlugins(e.target.value);
    });
  }
});

// Expose fetchPlugins globally for migration script
window.fetchPlugins = fetchPlugins;
