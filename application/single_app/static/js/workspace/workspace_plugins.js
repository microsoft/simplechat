
// workspace_plugins.js (refactored to use plugin_wizard.js)
import { renderPluginsTable, validatePluginManifest } from '../plugin_common.js';
import { showToast } from "../chat/chat-toast.js"
import PluginWizard from "../plugin_wizard.js";

const root = document.getElementById('workspace-plugins-root');
let pluginWizard;

// Initialize wizard when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  pluginWizard = new PluginWizard();
  
  // Handle save button click
  document.getElementById('save-plugin-btn').addEventListener('click', async function(event) {
    event.preventDefault();
    
    // Validate final step
    if (!pluginWizard.validateCurrentStep()) {
      return;
    }

    // Collect form data from wizard
    const pluginData = pluginWizard.collectFormData();
    
    // Validate required fields
    if (!pluginData.name || !pluginData.type) {
      showError('Name and type are required.');
      return;
    }

    // Build plugin manifest for API
    const newPlugin = {
      name: pluginData.name,
      displayName: pluginData.displayName,
      type: pluginData.type,
      description: pluginData.description,
      endpoint: pluginData.additionalFields.endpoint || '',
      auth: pluginData.auth,
      metadata: pluginData.metadata,
      additionalFields: pluginData.additionalFields
    };

    // Validate with JSON schema
    try {
      const valid = await validatePluginManifest(newPlugin);
      if (!valid) {
        showError('Validation error: Invalid plugin data.');
        return;
      }
    } catch (e) {
      showError('Schema validation failed: ' + e.message);
      return;
    }

    // Save
    try {
      // Get all plugins, update or add
      const res = await fetch('/api/user/plugins');
      if (!res.ok) throw new Error('Failed to load plugins');
      let plugins = await res.json();
      const idx = plugins.findIndex(p => p.name === newPlugin.name);
      if (idx >= 0) {
        plugins[idx] = newPlugin;
      } else {
        plugins.push(newPlugin);
      }
      const saveRes = await fetch('/api/user/plugins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plugins)
      });
      if (!saveRes.ok) throw new Error('Failed to save plugin');
      bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
      fetchPlugins();
      showToast('Plugin saved successfully', 'success');
    } catch (e) {
      showError(e.message);
    }
  });
});

function renderLoading() {
  root.innerHTML = `<div class="text-center p-4"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
}

function renderError(msg) {
  root.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
}

function showError(msg) {
  if (pluginWizard) {
    pluginWizard.showError(msg);
  }
}

async function fetchPlugins() {
  renderLoading();
  try {
    const res = await fetch('/api/user/plugins');
    if (!res.ok) throw new Error('Failed to load plugins');
    const plugins = await res.json();
    renderPluginsTable({
      plugins,
      tbodySelector: '#plugins-table-body',
      onEdit: name => openPluginModal(plugins.find(p => p.name === name)),
      onDelete: name => deletePlugin(name)
    });
    const createPluginBtn = document.getElementById('create-plugin-btn');
    if (createPluginBtn) {
      createPluginBtn.onclick = () => {
        console.log('[WORKSPACE PLUGINS] New Plugin button clicked');
        openPluginModal();
      };
    }
  } catch (e) {
    renderError(e.message);
  }
}

function openPluginModal(plugin = null) {
  if (!pluginWizard) {
    console.error('Plugin wizard not initialized');
    return;
  }
  
  pluginWizard.show(plugin);
}

async function deletePlugin(name) {
  try {
    const res = await fetch(`/api/user/plugins/${encodeURIComponent(name)}`, {
      method: 'DELETE'
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to delete plugin');
    }
    fetchPlugins();
    showToast('Plugin deleted successfully', 'success');
  } catch (e) {
    renderError(e.message);
  }
}

// Initial load
if (root) fetchPlugins();
