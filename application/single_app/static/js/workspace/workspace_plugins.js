// workspace_plugins.js
// Handles user plugin CRUD in the workspace UI

const root = document.getElementById('workspace-plugins-root');

function renderLoading() {
  root.innerHTML = `<div class="text-center p-4"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
}

function renderError(msg) {
  root.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
}

function renderPluginsTable(plugins) {
  const template = document.getElementById('plugins-table-template');
  if (!template) {
    renderError('Plugins table template not found.');
    return;
  }
  const clone = template.content.cloneNode(true);
  const tbody = clone.querySelector('#plugins-table-body');
  tbody.innerHTML = '';
  if (!plugins.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="4" class="text-center text-muted">No plugins found.</td>';
    tbody.appendChild(tr);
  } else {
    for (const plugin of plugins) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${plugin.name || ''}</td>
        <td>${plugin.type || ''}</td>
        <td>${plugin.description || ''}</td>
        <td>
          <button class="btn btn-sm btn-primary edit-plugin-btn" data-name="${plugin.name}">Edit</button>
          <button class="btn btn-sm btn-danger ms-1 delete-plugin-btn" data-name="${plugin.name}">Delete</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  }
  root.innerHTML = '';
  root.appendChild(clone);
}

async function fetchPlugins() {
  renderLoading();
  try {
    const res = await fetch('/api/user/plugins');
    if (!res.ok) throw new Error('Failed to load plugins');
    const plugins = await res.json();
    renderPluginsTable(plugins);
    attachPluginTableEvents(plugins);
  } catch (e) {
    renderError(e.message);
  }
}

function attachPluginTableEvents(plugins) {
  document.getElementById('create-plugin-btn').onclick = () => openPluginModal();
  for (const btn of document.querySelectorAll('.edit-plugin-btn')) {
    btn.onclick = () => {
      const plugin = plugins.find(p => p.name === btn.dataset.name);
      openPluginModal(plugin);
    };
  }
  for (const btn of document.querySelectorAll('.delete-plugin-btn')) {
    btn.onclick = () => {
      const plugin = plugins.find(p => p.name === btn.dataset.name);
      if (confirm(`Delete plugin '${plugin.name}'?`)) deletePlugin(plugin.name);
    };
  }
}

function openPluginModal(plugin = null) {
  // Get modal and fields
  const modalEl = document.getElementById('plugin-modal');
  if (!modalEl) return alert('Plugin modal not found.');
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  // Fields
  const nameInput = document.getElementById('plugin-name');
  const typeInput = document.getElementById('plugin-type');
  const descInput = document.getElementById('plugin-description');
  const endpointInput = document.getElementById('plugin-endpoint');
  const authTypeInput = document.getElementById('plugin-auth-type');
  const authKeyInput = document.getElementById('plugin-auth-key');
  const authIdentityInput = document.getElementById('plugin-auth-managed-identity');
  const authKeyGroup = document.getElementById('auth-key-group');
  const authIdentityGroup = document.getElementById('auth-identity-group');
  const metadataInput = document.getElementById('plugin-metadata');
  const additionalFieldsInput = document.getElementById('plugin-additional-fields');
  const errorDiv = document.getElementById('plugin-modal-error');
  const saveBtn = document.getElementById('save-plugin-btn');
  // Populate plugin type dropdown from backend
  async function populatePluginTypes(selectedType) {
    typeInput.innerHTML = '';
    const loadingOpt = document.createElement('option');
    loadingOpt.value = '';
    loadingOpt.textContent = 'Loading...';
    typeInput.appendChild(loadingOpt);
    try {
      const res = await fetch('/api/user/plugins/types');
      if (!res.ok) throw new Error('Failed to load plugin types');
      const types = await res.json();
      typeInput.innerHTML = '';
      const defaultOpt = document.createElement('option');
      defaultOpt.value = '';
      defaultOpt.textContent = 'Select type...';
      typeInput.appendChild(defaultOpt);
      for (const t of types) {
        const opt = document.createElement('option');
        opt.value = t.type || t; // support both [{value,label}] and [str]
        opt.textContent = t.display || t.type || t;
        typeInput.appendChild(opt);
      }
      if (selectedType) typeInput.value = selectedType;
    } catch (e) {
      typeInput.innerHTML = '';
      const errOpt = document.createElement('option');
      errOpt.value = '';
      errOpt.textContent = 'Error loading types';
      typeInput.appendChild(errOpt);
    }
  }
  // Reset error
  errorDiv.classList.add('d-none');
  errorDiv.textContent = '';
  // Populate fields and plugin types
  if (plugin) {
    nameInput.value = plugin.name || '';
    nameInput.disabled = true;
    descInput.value = plugin.description || '';
    endpointInput.value = plugin.endpoint || '';
    authTypeInput.value = plugin.auth_type || 'key';
    authKeyInput.value = plugin.auth_key || '';
    authIdentityInput.value = plugin.auth_managed_identity || '';
    metadataInput.value = plugin.metadata ? JSON.stringify(plugin.metadata, null, 2) : '';
    additionalFieldsInput.value = plugin.additional_fields ? JSON.stringify(plugin.additional_fields, null, 2) : '';
    populatePluginTypes(plugin.type || '');
  } else {
    nameInput.value = '';
    nameInput.disabled = false;
    descInput.value = '';
    endpointInput.value = '';
    authTypeInput.value = 'key';
    authKeyInput.value = '';
    authIdentityInput.value = '';
    metadataInput.value = '';
    additionalFieldsInput.value = '';
    populatePluginTypes('');
  }
  // Auth type toggle
  function updateAuthFields() {
    if (authTypeInput.value === 'key') {
      authKeyGroup.style.display = '';
      authIdentityGroup.style.display = 'none';
    } else {
      authKeyGroup.style.display = 'none';
      authIdentityGroup.style.display = '';
    }
  }
  authTypeInput.onchange = updateAuthFields;
  updateAuthFields();
  // Save handler
  saveBtn.onclick = async () => {
    // Parse JSON fields
    let metadataObj = {};
    let additionalFieldsObj = {};
    try {
      metadataObj = metadataInput.value.trim() ? JSON.parse(metadataInput.value) : {};
      if (typeof metadataObj !== 'object' || Array.isArray(metadataObj)) throw new Error('Metadata must be a JSON object');
    } catch (e) {
      errorDiv.textContent = 'Metadata: ' + e.message;
      errorDiv.classList.remove('d-none');
      return;
    }
    try {
      additionalFieldsObj = additionalFieldsInput.value.trim() ? JSON.parse(additionalFieldsInput.value) : {};
      if (typeof additionalFieldsObj !== 'object' || Array.isArray(additionalFieldsObj)) throw new Error('Additional Fields must be a JSON object');
    } catch (e) {
      errorDiv.textContent = 'Additional Fields: ' + e.message;
      errorDiv.classList.remove('d-none');
      return;
    }
    // Build plugin object
    const newPlugin = {
      name: nameInput.value.trim(),
      type: typeInput.value.trim(),
      description: descInput.value.trim(),
      endpoint: endpointInput.value.trim(),
      auth: {
        type: authTypeInput.value,
        key: authKeyInput.value.trim(),
        managedIdentity: authIdentityInput.value.trim()
      },
      metadata: metadataObj,
      additionalFields: additionalFieldsObj
    };
    // Validate with JSON schema (Ajv)
    try {
      if (!window.validatePlugin) {
        window.validatePlugin = (await import('/static/js/validatePlugin.mjs')).default;
      }
      const valid = window.validatePlugin(newPlugin);
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
      modal.hide();
      fetchPlugins();
    } catch (e) {
      errorDiv.textContent = e.message;
      errorDiv.classList.remove('d-none');
    }
  };
  // Show modal
  modal.show();
}

async function deletePlugin(name) {
  // Use the dedicated DELETE endpoint for user plugins
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
