// workspace_plugins.js (refactored to use plugin_common.js and new multi-step modal)
import { renderPluginsTable, ensurePluginsTableInRoot, validatePluginManifest } from '../plugin_common.js';
import { showToast } from "../chat/chat-toast.js"

const root = document.getElementById('workspace-plugins-root');
let plugins = [];
let filteredPlugins = [];

function renderLoading() {
  root.innerHTML = `<div class="text-center p-4"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
}

function renderError(msg) {
  root.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
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
  
  // Ensure table template is in place
  ensurePluginsTableInRoot();
  
  renderPluginsTable({
    plugins: filteredPlugins,
    tbodySelector: '#plugins-table-body',
    onEdit: name => openPluginModal(plugins.find(p => p.name === name)),
    onDelete: name => deletePlugin(name)
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
    
    renderPluginsTable({
      plugins: filteredPlugins,
      tbodySelector: '#plugins-table-body',
      onEdit: name => openPluginModal(plugins.find(p => p.name === name)),
      onDelete: name => deletePlugin(name)
    });
    
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

function openPluginModal(plugin = null) {
  // Use the new multi-step modal
  if (window.pluginModalStepper) {
    const modal = window.pluginModalStepper.showModal(plugin);
    
    // Set up save handler
    setupSaveHandler(plugin, modal);
  } else {
    alert('Action modal not available. Please refresh the page.');
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
        const valid = await validatePluginManifest(formData);
        if (!valid) {
          window.pluginModalStepper.showError('Validation error: Invalid action data.');
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
  // Get all plugins first
  const res = await fetch('/api/user/plugins');

  if (!res.ok) throw new Error('Failed to load existing actions');
  
  let plugins = await res.json();
  
  // Update or add the plugin
  const existingIndex = plugins.findIndex(p => p.name === pluginData.name);
  if (existingIndex >= 0) {
    plugins[existingIndex] = pluginData;
  } else {
    plugins.push(pluginData);
  }
  
  // Save back to server
  const saveRes = await fetch('/api/user/plugins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(plugins)
  });
  
  if (!saveRes.ok) {
    throw new Error('Failed to save action');
  }
}

async function deletePlugin(name) {
  if (!confirm(`Are you sure you want to delete action "${name}"?`)) return;
  
  try {
    const res = await fetch(`/api/user/plugins/${encodeURIComponent(name)}`, {
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
