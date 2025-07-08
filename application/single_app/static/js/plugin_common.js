// plugin_common.js
// Shared logic for admin_plugins.js and workspace_plugins.js
// Exports: functions for modal field handling, validation, label toggling, table rendering, and plugin CRUD
import { showToast } from "./chat/chat-toast.js"

// Fetch merged plugin settings from backend given type and current settings
export async function fetchAndMergePluginSettings(pluginType, currentSettings = {}) {
  try {
    const res = await fetch(`/api/plugins/${encodeURIComponent(pluginType)}/merge_settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentSettings || {})
    });
    if (!res.ok) throw new Error(`Failed to fetch merged settings: ${res.status}`);
    return await res.json();
  } catch (e) {
    showToast('Error fetching plugin defaults: ' + e.message, 'danger');
    return {};
  }
}

// Populate modal fields from merged settings (additionalFields, metadata, etc)
export function populatePluginFieldsFromSettings({
  mergedSettings = {},
  additionalFieldsField,
  metadataField
}) {
  if (additionalFieldsField && mergedSettings.additionalFields) {
    additionalFieldsField.value = JSON.stringify(mergedSettings.additionalFields, null, 2);
  }
  if (metadataField && mergedSettings.metadata) {
    metadataField.value = JSON.stringify(mergedSettings.metadata, null, 2);
  }
  // Optionally handle other fields as needed
}

// Helper: Ensure plugins table template is present in the root before rendering
export function ensurePluginsTableInRoot({ rootSelector = '#workspace-plugins-root', templateId = 'plugins-table-template' } = {}) {
  const root = document.querySelector(rootSelector);
  if (!root) {
    console.error('Error: plugins root not found for selector %s', rootSelector);
    return;
  }
  // Only insert if not already present
  if (!root.querySelector('table#plugins-table')) {
    root.innerHTML = '';
    const template = document.getElementById(templateId);
    if (template) {
      root.appendChild(template.content.cloneNode(true));
    } else {
      console.error('Error: plugins table template not found');
    }
  }
}

// Utility: Escape HTML entities to prevent XSS
export function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

// Render plugins table (parameterized for tbody selector and button handlers)
export function renderPluginsTable({plugins, tbodySelector, onEdit, onDelete, ensureTable = true}) {
  console.log('Rendering plugins table with %d plugins', plugins.length);
  // Optionally ensure the table is present before rendering
  if (ensureTable) {
    ensurePluginsTableInRoot();
  }
  const tbody = document.querySelector(tbodySelector);
  if (!tbody) {
    console.error('Error: tbody not found for selector %s', tbodySelector);
    return;
  }
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
  // Attach event handlers
  tbody.querySelectorAll('.edit-plugin-btn').forEach(btn => {
    btn.onclick = () => onEdit(btn.getAttribute('data-plugin-name'));
  });
  tbody.querySelectorAll('.delete-plugin-btn').forEach(btn => {
    btn.onclick = () => onDelete(btn.getAttribute('data-plugin-name'));
  });
}

// Toggle auth fields and labels (parameterized for DOM elements)
export function toggleAuthFields({authTypeSelect, authKeyGroup, authIdentityGroup, authTenantIdGroup, authKeyLabel, authIdentityLabel, authTenantIdLabel}) {
  // Hide all by default
  if (authKeyGroup) authKeyGroup.style.display = 'none';
  if (authIdentityGroup) authIdentityGroup.style.display = 'none';
  if (authTenantIdGroup) authTenantIdGroup.style.display = 'none';
  // Reset labels
  if (authKeyLabel) authKeyLabel.textContent = 'Key';
  if (authIdentityLabel) authIdentityLabel.textContent = 'Identity';
  if (authTenantIdLabel) authTenantIdLabel.textContent = 'Tenant Id';
  if (authTypeSelect.value === 'key') {
    if (authKeyGroup) authKeyGroup.style.display = '';
    if (authKeyLabel) authKeyLabel.textContent = 'Key';
  } else if (authTypeSelect.value === 'identity') {
    if (authIdentityGroup) authIdentityGroup.style.display = '';
    if (authIdentityLabel) authIdentityLabel.textContent = 'Identity';
  } else if (authTypeSelect.value === 'servicePrincipal') {
    if (authIdentityGroup) authIdentityGroup.style.display = '';
    if (authKeyGroup) authKeyGroup.style.display = '';
    if (authTenantIdGroup) authTenantIdGroup.style.display = '';
    if (authIdentityLabel) authIdentityLabel.textContent = 'Client Id';
    if (authKeyLabel) authKeyLabel.textContent = 'Client Secret';
    if (authTenantIdLabel) authTenantIdLabel.textContent = 'Tenant Id';
  }
  // If 'user', all remain hidden
}

// Populate plugin types (parameterized for endpoint and select element)
export async function populatePluginTypes({endpoint, typeSelect}) {
  try {
    const res = await fetch(endpoint);
    const types = await res.json();
    typeSelect.innerHTML = '<option value="">Select type...</option>';
    types.forEach(t => {
      typeSelect.innerHTML += `<option value="${t.type}">${t.display || t.type}</option>`;
    });
  } catch (e) {
    typeSelect.innerHTML = '<option value="">Error loading types</option>';
  }
}

// Show plugin modal (parameterized for field selectors, plugin data, and callbacks)
export async function showPluginModal({
  plugin = null,
  populateTypes,
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
  afterShow
}) {
  await populateTypes();
  nameField.value = plugin && plugin.name ? plugin.name : '';
  descField.value = plugin ? plugin.description || '' : '';
  endpointField.value = plugin ? plugin.endpoint || '' : '';
  const auth = plugin && plugin.auth ? plugin.auth : {};
  let authTypeValue = auth.type;
  if (authTypeValue === 'managedIdentity') authTypeValue = 'identity';
  authTypeField.value = authTypeValue || 'key';
  authKeyField.value = auth.key || '';
  authIdentityField.value = auth.identity || auth.managedIdentity || '';
  authTenantIdField.value = auth.tenantId || '';
  errorDiv.classList.add('d-none');
  modalEl.setAttribute('data-editing', plugin ? plugin.name : '');

  // Helper to update additionalFields/metadata from backend
  async function updateFieldsForType(selectedType) {
    if (!selectedType) return;
    // Compose current settings for merge (if editing)
    let currentSettings = {};
    try {
      currentSettings = {
        additionalFields: additionalFieldsField && additionalFieldsField.value ? JSON.parse(additionalFieldsField.value) : undefined,
        metadata: metadataField && metadataField.value ? JSON.parse(metadataField.value) : undefined
      };
    } catch (e) {
      // Ignore parse errors, treat as empty
      currentSettings = {};
    }
    const merged = await fetchAndMergePluginSettings(selectedType, currentSettings);
    populatePluginFieldsFromSettings({
      mergedSettings: merged,
      additionalFieldsField,
      metadataField
    });
  }

  // Set initial type and fetch defaults if type is present
  if (plugin && plugin.type) {
    setTimeout(() => {
      typeField.value = plugin.type;
      updateFieldsForType(plugin.type);
    }, 0);
  } else {
    typeField.value = '';
    // Optionally clear fields
    additionalFieldsField.value = '{}';
    metadataField.value = '{}';
  }

  // Patch: update dropdown value for identity if legacy value exists
  if (authTypeField) {
    for (const opt of authTypeField.options) {
      if (opt.value === 'managedIdentity') {
        opt.value = 'identity';
        opt.textContent = 'Identity';
      }
    }
  }
  if (authTypeField) {
    authTypeField.dispatchEvent(new Event('change'));
  }

  // Wire up typeField change to auto-fetch defaults
  if (typeField) {
    typeField.addEventListener('change', async () => {
      const selectedType = typeField.value;
      await updateFieldsForType(selectedType);
    });
  }

  if (afterShow) afterShow();
  // Show modal
  if (nameField && typeField) {
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
  }
}

// Validate plugin manifest with Ajv (parameterized for schema loader)
export async function validatePluginManifest(pluginManifest) {
  if (!window.validatePlugin) {
    window.validatePlugin = (await import('/static/js/validatePlugin.mjs')).default;
  }
  return window.validatePlugin(pluginManifest);
}
