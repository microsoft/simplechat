
// workspace_plugins.js (refactored to use plugin_common.js)
import { renderPluginsTable, toggleAuthFields, populatePluginTypes, showPluginModal, validatePluginManifest } from '../plugin_common.js';
import { showToast } from "../chat/chat-toast.js"

const root = document.getElementById('workspace-plugins-root');

function renderLoading() {
  root.innerHTML = `<div class="text-center p-4"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
}

function renderError(msg) {
  root.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
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
        //showToast('Workspace: New Plugin button clicked', 'info');
        openPluginModal();
      };
    }
  } catch (e) {
    renderError(e.message);
  }
}

function openPluginModal(plugin = null) {
  const modalEl = document.getElementById('plugin-modal');
  if (!modalEl) return alert('Plugin modal not found.');
  // Fields
  const nameField = document.getElementById('plugin-name');
  const typeField = document.getElementById('plugin-type');
  const descField = document.getElementById('plugin-description');
  const endpointField = document.getElementById('plugin-endpoint');
  const authTypeField = document.getElementById('plugin-auth-type');
  const authKeyField = document.getElementById('plugin-auth-key');
  const authIdentityField = document.getElementById('plugin-auth-identity');
  const authTenantIdField = document.getElementById('plugin-auth-tenant-id');
  const metadataField = document.getElementById('plugin-metadata');
  const additionalFieldsField = document.getElementById('plugin-additional-fields');
  const errorDiv = document.getElementById('plugin-modal-error');
  // Auth field groups and labels
  const authKeyGroup = document.getElementById('auth-key-group');
  const authIdentityGroup = document.getElementById('auth-identity-group');
  const authTenantIdGroup = document.getElementById('auth-tenantid-group');
  const authKeyLabel = document.getElementById('auth-key-label');
  const authIdentityLabel = document.getElementById('auth-identity-label');
  const authTenantIdLabel = document.getElementById('auth-tenantid-label');

  // Attach auth type toggle
  authTypeField.onchange = () => toggleAuthFields({
    authTypeSelect: authTypeField,
    authKeyGroup,
    authIdentityGroup,
    authTenantIdGroup,
    authKeyLabel,
    authIdentityLabel,
    authTenantIdLabel
  });

  // Show modal with shared logic
  showPluginModal({
    plugin,
    populateTypes: () => populatePluginTypes({ endpoint: '/api/user/plugins/types', typeSelect: typeField }),
    nameField,
    typeField,
    descField,
    endpointField,
    authTypeField,
    authKeyField,
    authIdentityField,
    authTenantIdField,
    metadataField,
    additionalFieldsField,
    errorDiv,
    modalEl,
    afterShow: () => {
      // Save handler
      document.getElementById('save-plugin-btn').onclick = async (event) => {
        event.preventDefault();
        // Always get the latest typeField from the DOM in case it was replaced
        const currentTypeField = document.getElementById('plugin-type');
        // Parse JSON fields
        let metadataObj = {};
        let additionalFieldsObj = {};
        try {
          metadataObj = metadataField.value.trim() ? JSON.parse(metadataField.value) : {};
          if (typeof metadataObj !== 'object' || Array.isArray(metadataObj)) throw new Error('Metadata must be a JSON object');
        } catch (e) {
          errorDiv.textContent = 'Metadata: ' + e.message;
          errorDiv.classList.remove('d-none');
          return;
        }
        try {
          additionalFieldsObj = additionalFieldsField.value.trim() ? JSON.parse(additionalFieldsField.value) : {};
          if (typeof additionalFieldsObj !== 'object' || Array.isArray(additionalFieldsObj)) throw new Error('Additional Fields must be a JSON object');
        } catch (e) {
          errorDiv.textContent = 'Additional Fields: ' + e.message;
          errorDiv.classList.remove('d-none');
          return;
        }
        // Build plugin object
        const authType = authTypeField.value;
        const auth = { type: authType };
        if (authType === 'key') {
          auth.key = authKeyField.value.trim();
        } else if (authType === 'identity') {
          auth.identity = authIdentityField.value.trim();
        } else if (authType === 'servicePrincipal') {
          auth.identity = authIdentityField.value.trim();
          auth.key = authKeyField.value.trim();
          auth.tenantId = authTenantIdField.value.trim();
        }
        // For 'user', no extra fields
        const selectedType = currentTypeField ? currentTypeField.value.trim() : '';
        console.log('[PLUGIN SAVE] Selected type:', selectedType);
        if (!selectedType) {
          errorDiv.textContent = 'Please select a plugin type.';
          errorDiv.classList.remove('d-none');
          return;
        }
        const newPlugin = {
          name: nameField.value.trim(),
          type: selectedType,
          description: descField.value.trim(),
          endpoint: endpointField.value.trim(),
          auth,
          metadata: metadataObj,
          additionalFields: additionalFieldsObj
        };
        // Validate with JSON schema (Ajv)
        try {
          const valid = await validatePluginManifest(newPlugin);
          if (!valid) {
            errorDiv.textContent = 'Validation error: Invalid plugin data.';
            errorDiv.classList.remove('d-none');
            return;
          }
        } catch (e) {
          errorDiv.textContent = 'Schema validation failed: ' + e.message;
          errorDiv.classList.remove('d-none');
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
          bootstrap.Modal.getInstance(modalEl).hide();
          fetchPlugins();
        } catch (e) {
          errorDiv.textContent = e.message;
          errorDiv.classList.remove('d-none');
        }
      };
    }
  });
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
  } catch (e) {
    renderError(e.message);
  }
}

// Initial load
if (root) fetchPlugins();
