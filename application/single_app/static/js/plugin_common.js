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
export function renderPluginsTable({plugins, tbodySelector, onEdit, onDelete, ensureTable = true, isAdmin = false}) {
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
    const safeDisplayName = escapeHtml(plugin.display_name || plugin.name);
    const safeDesc = escapeHtml(plugin.description || 'No description available');
    let actionButtons = '';
    let globalBadge = plugin.is_global ? ' <span class="badge bg-info text-dark">Global</span>' : '';
    
    // Show action buttons for:
    // - Admin context: all actions (global and personal)
    // - User context: only personal actions (not global)
    if (isAdmin || !plugin.is_global) {
      actionButtons = `
        <div class="d-flex gap-1">
          <button type="button" class="btn btn-sm btn-outline-secondary edit-plugin-btn" data-plugin-name="${safeName}" title="Edit action">
            <i class="bi bi-pencil"></i>
          </button>
          <button type="button" class="btn btn-sm btn-outline-danger delete-plugin-btn" data-plugin-name="${safeName}" title="Delete action">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      `;
    }
    tr.innerHTML = `
      <td><strong>${safeDisplayName}</strong>${globalBadge}</td>
      <td class="text-muted small">${safeDesc}</td>
      <td>${actionButtons}</td>
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
  console.log('[PLUGIN MODAL] showPluginModal called', plugin);

  await populateTypes();
  console.log('[PLUGIN MODAL] After populateTypes, typeField.value:', typeField.value, 'options:', Array.from(typeField.options).map(o => o.value));
  nameField.value = plugin && plugin.name ? plugin.name : '';
  descField.value = plugin ? plugin.description || '' : '';
  endpointField.value = plugin ? plugin.endpoint || '' : '';
  // Always pre-populate additionalFields and metadata from plugin object if present
  if (additionalFieldsField) {
    if (plugin && plugin.additionalFields && Object.keys(plugin.additionalFields).length > 0) {
      additionalFieldsField.value = JSON.stringify(plugin.additionalFields, null, 2);
    } else {
      additionalFieldsField.value = '{}';
    }
  }
  if (metadataField) {
    if (plugin && plugin.metadata && Object.keys(plugin.metadata).length > 0) {
      metadataField.value = JSON.stringify(plugin.metadata, null, 2);
    } else {
      metadataField.value = '{}';
    }
  }
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
    console.log('Updating fields for type:', selectedType);
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
      console.error('Error parsing current settings. Continuing with empty settings:', e);
      currentSettings = {};
    }
    console.log('Current settings for merge:', currentSettings);
    const merged = await fetchAndMergePluginSettings(selectedType, currentSettings);
    console.log('Merged settings:', merged);
    // Only overwrite if merged value is non-empty, otherwise preserve user input
    if (additionalFieldsField && merged.additionalFields && Object.keys(merged.additionalFields).length > 0) {
      additionalFieldsField.value = JSON.stringify(merged.additionalFields, null, 2);
    }
    if (metadataField && merged.metadata && Object.keys(merged.metadata).length > 0) {
      metadataField.value = JSON.stringify(merged.metadata, null, 2);
    }
    console.log('Updated additionalFields:', additionalFieldsField.value);
    console.log('Updated metadata:', metadataField.value);
  }

  // Remove any previous change event listeners to avoid duplicates
  if (typeField) {
    const newTypeField = typeField.cloneNode(true);
    typeField.parentNode.replaceChild(newTypeField, typeField);
    typeField = newTypeField;
    typeField.addEventListener('change', async () => {
      const selectedType = typeField.value;
      console.log('[PLUGIN MODAL] typeField changed to:', selectedType);
      await updateFieldsForType(selectedType);
    });
  }

  // Set initial type and always fetch defaults from backend for both edit and new
  if (plugin && plugin.type) {
    typeField.value = plugin.type;
    console.log('[PLUGIN MODAL] Editing plugin, set typeField.value to:', typeField.value);
    await updateFieldsForType(plugin.type);
  } else {
    typeField.value = '';
    additionalFieldsField.value = '{}';
    metadataField.value = '{}';
    console.log('[PLUGIN MODAL] New plugin, typeField.value after reset:', typeField.value);
    // If a type is already selected (e.g., user picks before modal shows), fetch defaults
    if (typeField && typeField.value) {
      console.log('[PLUGIN MODAL] New plugin, typeField.value before updateFieldsForType:', typeField.value);
      await updateFieldsForType(typeField.value);
    }
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
  //if (typeField) {
  //  typeField.addEventListener('change', async () => {
  //    const selectedType = typeField.value;
  //    await updateFieldsForType(selectedType);
  //  });
  //}

  if (afterShow) afterShow();
  // Show modal
  if (nameField && typeField) {
    console.log('[PLUGIN MODAL] Before show, typeField.value:', typeField.value);
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
  }
}

// Validate plugin manifest using server-side validation only
export async function validatePluginManifest(pluginManifest) {
  return await validatePluginManifestServerSide(pluginManifest);
}

// Server-side validation fallback
async function validatePluginManifestServerSide(pluginManifest) {
  try {
    const response = await fetch('/api/admin/plugins/validate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(pluginManifest)
    });
    
    const result = await response.json();
    return {
      valid: result.valid,
      errors: result.errors || [],
      warnings: result.warnings || []
    };
  } catch (error) {
    console.error('Server-side validation failed:', error);
    return {
      valid: false,
      errors: ['Validation service unavailable']
    };
  }
}
