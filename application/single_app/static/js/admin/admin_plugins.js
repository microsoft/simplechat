// admin_plugins.js
import { showToast } from "../chat/chat-toast.js"

async function populatePluginTypes() {
    const typeSelect = document.getElementById('plugin-type');
    try {
        const res = await fetch('/api/admin/plugins/types');
        const types = await res.json();
        typeSelect.innerHTML = '<option value="">Select type...</option>';
        types.forEach(t => {
            typeSelect.innerHTML += `<option value="${t.type}">${t.display || t.type}</option>`;
        });
    } catch (e) {
        typeSelect.innerHTML = '<option value="">Error loading types</option>';
    }
}

document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('plugins-tab')) return;

    // Populate plugin type dropdown on modal open
    populatePluginTypes();

    // Auth type toggle logic
    const authTypeSelect = document.getElementById('plugin-auth-type');
    const authKeyGroup = document.getElementById('auth-key-group');
    const authIdentityGroup = document.getElementById('auth-identity-group');
    function toggleAuthFields() {
        if (authTypeSelect.value === 'key') {
            authKeyGroup.style.display = '';
            authIdentityGroup.style.display = 'none';
        } else {
            authKeyGroup.style.display = 'none';
            authIdentityGroup.style.display = '';
        }
    }
    authTypeSelect.addEventListener('change', toggleAuthFields);


    // Add plugin button
    document.getElementById('add-plugin-btn').addEventListener('click', async function () {
        await populatePluginTypes();
        showPluginModal();
        toggleAuthFields();
    });

    // Save plugin (add or edit)
    document.getElementById('save-plugin-btn').addEventListener('click', function (event) {
        event.preventDefault();
        // Validate name (no spaces)
        const name = document.getElementById('plugin-name').value.trim();
        if (/\s/.test(name)) {
            showPluginModalError('Name cannot contain spaces.');
            return;
        }
        // Validate endpoint (must start with https://)
        const endpoint = document.getElementById('plugin-endpoint').value.trim();
        if (endpoint && !endpoint.startsWith('https://')) {
            showPluginModalError('Endpoint must start with https://');
            return;
        }
        savePlugin();
    });

    // Prepopulate endpoint field
    document.getElementById('plugin-endpoint').addEventListener('focus', function() {
        if (!this.value) this.value = 'https://';
    });

    // Load plugins when the Plugins tab is shown
    document.getElementById('plugins-tab').addEventListener('shown.bs.tab', function () {
        fetchPlugins();
    });

    // Event delegation for edit and delete buttons
    const pluginTable = document.getElementById('plugins-table');
    if (pluginTable) {
        pluginTable.addEventListener('click', function (event) {
            const target = event.target;
            if (target.classList.contains('edit-plugin-btn')) {
                const name = target.getAttribute('data-plugin-name');
                if (name) editPlugin(name);
            } else if (target.classList.contains('delete-plugin-btn')) {
                const name = target.getAttribute('data-plugin-name');
                if (name) deletePlugin(name);
            }
        });
    }
});

function fetchPlugins() {
    fetch('/api/admin/plugins')
        .then(res => {
            if (!res.ok) throw new Error('Failed to fetch plugins');
            return res.json();
        })
        .then(plugins => renderPluginsTable(plugins))
        .catch(err => showToast('Error loading plugins: ' + err.message, 'danger'));
}

// Escape HTML entities to prevent XSS
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, function (c) {
        return ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]);
    });
}

function renderPluginsTable(plugins) {
    const tbody = document.getElementById('plugins-table-body');
    tbody.innerHTML = '';
    plugins.forEach(plugin => {
        const tr = document.createElement('tr');
        const safeName = escapeHtml(plugin.name);
        const safeType = escapeHtml(plugin.type);
        const safeDesc = escapeHtml(plugin.description || '');
        tr.innerHTML = `
            <td>${safeName}</td>
            <td>${safeType}</td>
            <td>${safeDesc}</td>
            <td>
                <button type="button" class="btn btn-sm btn-secondary me-1 edit-plugin-btn" data-plugin-name="${safeName}">Edit</button>
                <button type="button" class="btn btn-sm btn-danger delete-plugin-btn" data-plugin-name="${safeName}">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}


async function showPluginModal(plugin = null) {
    // Always repopulate types before showing modal
    await populatePluginTypes();
    // Defensive: Ensure required fields are always filled for Edit
    const nameField = document.getElementById('plugin-name');
    const typeField = document.getElementById('plugin-type');
    // If editing, ensure plugin has name and type, else fallback to empty string
    nameField.value = plugin && plugin.name ? plugin.name : '';
    // Wait for types to be populated, then set the value
    if (plugin && plugin.type) {
        // Try to set the value after options are loaded
        setTimeout(() => { typeField.value = plugin.type; }, 0);
    } else {
        typeField.value = '';
    }
    document.getElementById('plugin-modal-title').textContent = plugin ? 'Edit Plugin' : 'Add Plugin';
    document.getElementById('plugin-description').value = plugin ? plugin.description || '' : '';
    document.getElementById('plugin-endpoint').value = plugin ? plugin.endpoint || '' : '';
    document.getElementById('plugin-auth-type').value = plugin && plugin.auth ? plugin.auth.type || 'key' : 'key';
    document.getElementById('plugin-auth-key').value = plugin && plugin.auth ? plugin.auth.key || '' : '';
    document.getElementById('plugin-auth-managed-identity').value = plugin && plugin.auth ? plugin.auth.managedIdentity || '' : '';
    document.getElementById('plugin-metadata').value = plugin && plugin.metadata ? JSON.stringify(plugin.metadata, null, 2) : '{}';
    document.getElementById('plugin-additional-fields').value = plugin && plugin.additionalFields ? JSON.stringify(plugin.additionalFields, null, 2) : '{}';
    document.getElementById('plugin-modal-error').classList.add('d-none');
    document.getElementById('plugin-modal').setAttribute('data-editing', plugin ? plugin.name : '');
    // Set auth fields visibility
    if (document.getElementById('plugin-auth-type')) {
        document.getElementById('plugin-auth-type').dispatchEvent(new Event('change'));
    }
    // Only show the modal if not missing required fields
    if (nameField && typeField) {
        const modal = new bootstrap.Modal(document.getElementById('plugin-modal'));
        modal.show();
    }
}

function savePlugin() {
    // Prevent accidental form submit
    if (event) event.preventDefault();
    const name = document.getElementById('plugin-name').value.trim();
    const type = document.getElementById('plugin-type').value.trim();
    const description = document.getElementById('plugin-description').value.trim();
    const endpoint = document.getElementById('plugin-endpoint').value.trim();
    const authType = document.getElementById('plugin-auth-type').value.trim();
    const authKey = document.getElementById('plugin-auth-key').value.trim();
    const authManagedIdentity = document.getElementById('plugin-auth-managed-identity').value.trim();
    let metadata, additionalFields;
    try {
        metadata = JSON.parse(document.getElementById('plugin-metadata').value.trim() || '{}');
    } catch (e) {
        showPluginModalError('Metadata must be valid JSON.');
        return;
    }
    try {
        additionalFields = JSON.parse(document.getElementById('plugin-additional-fields').value.trim() || '{}');
    } catch (e) {
        showPluginModalError('Additional Fields must be valid JSON.');
        return;
    }
    const editing = document.getElementById('plugin-modal').getAttribute('data-editing');
    const method = editing ? 'PUT' : 'POST';
    const url = editing ? `/api/admin/plugins/${encodeURIComponent(editing)}` : '/api/admin/plugins';
    const pluginManifest = {
        name,
        type,
        description,
        endpoint,
        auth: {
            type: authType,
            key: authKey,
            managedIdentity: authManagedIdentity
        },
        metadata,
        additionalFields
    };
    // Validate with JSON schema (Ajv)
    (async () => {
      try {
        if (!window.validatePlugin) {
          window.validatePlugin = (await import('/static/js/validatePlugin.mjs')).default;
        }
        const valid = window.validatePlugin(pluginManifest);
        if (!valid) {
          showPluginModalError('Validation error: Invalid plugin data.');
          return;
        }
      } catch (e) {
        showPluginModalError('Schema validation failed: ' + e.message);
        return;
      }
      fetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(pluginManifest)
      })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
          if (ok && data.success) {
            fetchPlugins();
            bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
            showToast('Plugin saved successfully', 'success');
          } else {
            showPluginModalError(data.error || 'Error saving plugin.');
          }
        })
        .catch(err => showPluginModalError('Error saving plugin: ' + err.message));
    })();
}

function showPluginModalError(msg) {
    const errDiv = document.getElementById('plugin-modal-error');
    errDiv.textContent = msg;
    errDiv.classList.remove('d-none');
}


async function editPlugin(name) {
    const res = await fetch('/api/admin/plugins');
    const plugins = await res.json();
    const plugin = plugins.find(p => p.name === name);
    if (plugin) await showPluginModal(plugin);
}

// Patch: Ensure deletePlugin never triggers the modal
function deletePlugin(name) {
    // Always hide the modal before delete to prevent form validation errors
    const modalEl = document.getElementById('plugin-modal');
    if (modalEl && bootstrap.Modal.getInstance(modalEl)) {
        bootstrap.Modal.getInstance(modalEl).hide();
    }
    if (!confirm('Delete this plugin?')) return;
    fetch(`/api/admin/plugins/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        headers: {}
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (ok && data.success) {
                fetchPlugins();
                showToast('Plugin deleted', 'success');
            } else {
                showToast(data.error || 'Error deleting plugin.', 'danger');
            }
        })
        .catch(err => showToast('Error deleting plugin: ' + err.message, 'danger'));
}
