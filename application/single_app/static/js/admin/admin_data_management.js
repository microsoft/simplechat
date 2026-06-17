// admin_data_management.js

import { showToast } from "../chat/chat-toast.js";

const redactedValue = "***REDACTED***";
const backupStorageAuthManagedIdentity = "managed_identity";
const backupStorageAuthConnectionString = "connection_string";
const targetCosmosDatabaseName = "SimpleChat";
const elements = {};
let dataManagementModified = false;
let storedBackupConnectionStringAvailable = false;
let backupInventory = [];
let currentBackupFilter = "all";
let currentJobDetailId = null;
let jobDetailRefreshTimer = null;
let jobDetailRefreshInFlight = false;
let refreshListsWhenJobCompletes = false;

const jobDetailRefreshIntervalMs = 4000;
const activeJobStatuses = new Set(["queued", "running"]);
const migrationTargetTypes = ["users", "groups", "public_workspaces"];
const migrationSelections = {
    users: new Map(),
    groups: new Map(),
    public_workspaces: new Map(),
};

document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    if (!elements.tabPane) {
        return;
    }

    bindEvents();
    loadDataManagementSettings();
    loadDataManagementBackups();
    loadDataManagementJobs();
});

function bindElements() {
    const ids = [
        "data-management",
        "data-management-status",
        "data-management-save-settings-btn",
        "data_management_enabled",
        "data_management_full_frequency",
        "data_management_scheduled_time_utc",
        "data_management_retention_days",
        "data_management_partial_enabled",
        "data_management_low_impact_mode",
        "data_management_include_cosmos",
        "data_management_include_ai_search",
        "data_management_include_source_blobs",
        "data-management-source-blobs-lock-message",
        "data_management_storage_auth",
        "data-management-blob-endpoint-field",
        "data_management_blob_endpoint",
        "data_management_container_name",
        "data-management-connection-string-field",
        "data_management_connection_string",
        "data-management-connection-string-status",
        "data_management_path_prefix",
        "data_management_encryption_enabled",
        "data-management-key-storage",
        "data-management-key-reference",
        "data-management-key-storage-alert",
        "data-management-key-storage-alert-icon",
        "data-management-key-storage-alert-title",
        "data-management-key-storage-alert-message",
        "data-management-key-vault-link",
        "data-management-generate-key-btn",
        "data_management_target_cosmos_auth",
        "data_management_target_cosmos_endpoint",
        "data_management_target_cosmos_database",
        "data-management-target-cosmos-key-field",
        "data_management_target_cosmos_key",
        "data-management-test-target-cosmos-btn",
        "data-management-target-ai-search-section",
        "data_management_target_ai_search_auth",
        "data_management_target_ai_search_endpoint",
        "data-management-target-ai-search-key-field",
        "data_management_target_ai_search_key",
        "data-management-test-target-search-btn",
        "data-management-target-enhanced-citations-section",
        "data_management_target_ec_storage_auth",
        "data-management-target-ec-blob-endpoint-field",
        "data_management_target_ec_blob_endpoint",
        "data-management-target-ec-connection-string-field",
        "data_management_target_ec_connection_string",
        "data-management-test-target-ec-storage-btn",
        "data-management-refresh-migration-summary-btn",
        "data_management_migration_users_mode",
        "data_management_migration_users_search",
        "data-management-search-users-btn",
        "data-management-migration-users-available",
        "data-management-migration-users-selected",
        "data_management_migration_users_documents",
        "data_management_migration_groups_mode",
        "data_management_migration_groups_search",
        "data-management-search-groups-btn",
        "data-management-migration-groups-available",
        "data-management-migration-groups-selected",
        "data_management_migration_groups_documents",
        "data_management_migration_public_workspaces_mode",
        "data_management_migration_public_workspaces_search",
        "data-management-search-public-workspaces-btn",
        "data-management-migration-public-workspaces-available",
        "data-management-migration-public-workspaces-selected",
        "data_management_migration_public_workspaces_documents",
        "data_management_migration_include_ai_search",
        "data_management_migration_include_source_blobs",
        "data-management-migration-summary",
        "data-management-migration-preview-btn",
        "data-management-execute-migration-btn",
        "data-management-test-storage-btn",
        "data-management-run-full-backup-btn",
        "data-management-run-partial-backup-btn",
        "data-management-refresh-backups-btn",
        "data-management-view-full-backups-btn",
        "data-management-view-partial-backups-btn",
        "data-management-view-all-backups-btn",
        "data-management-full-backup-count",
        "data-management-partial-backup-count",
        "data-management-available-backup-count",
        "data-management-backups-tbody",
        "data-management-refresh-jobs-btn",
        "data-management-jobs-tbody",
        "data-management-job-detail-modal",
        "data-management-job-detail-title",
        "data-management-job-detail-subtitle",
        "data-management-job-detail-refresh-state",
        "data-management-job-detail-summary",
        "data-management-job-detail-progress",
        "data-management-job-items-tbody",
        "data-management-job-artifacts-tbody",
        "data-management-job-manifest-detail",
        "data-management-job-warnings",
    ];

    ids.forEach((id) => {
        const key = id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()).replace(/_/g, "");
        elements[key] = document.getElementById(id);
    });

    elements.tabPane = elements.dataManagement;
}

function bindEvents() {
    elements.dataManagementSaveSettingsBtn?.addEventListener("click", () => saveDataManagementSettings());
    elements.datamanagementstorageauth?.addEventListener("change", () => {
        setStorageAuthVisibility();
        updateConnectionStringStatus();
    });
    elements.datamanagementconnectionstring?.addEventListener("input", updateConnectionStringStatus);
    elements.datamanagementtargetcosmosauth?.addEventListener("change", () => {
        setMigrationTargetVisibility();
        markDataManagementModified();
    });
    elements.datamanagementtargetaisearchauth?.addEventListener("change", () => {
        setMigrationTargetVisibility();
        markDataManagementModified();
    });
    elements.datamanagementtargetecstorageauth?.addEventListener("change", () => {
        setMigrationTargetVisibility();
        markDataManagementModified();
    });
    elements.dataManagementGenerateKeyBtn?.addEventListener("click", generateEncryptionKey);
    elements.dataManagementTestStorageBtn?.addEventListener("click", testBackupStorage);
    elements.dataManagementTestTargetCosmosBtn?.addEventListener("click", testTargetCosmos);
    elements.dataManagementTestTargetSearchBtn?.addEventListener("click", testTargetSearch);
    elements.dataManagementTestTargetEcStorageBtn?.addEventListener("click", testTargetEnhancedCitationStorage);
    elements.dataManagementRunFullBackupBtn?.addEventListener("click", () => queueBackup("full"));
    elements.dataManagementRunPartialBackupBtn?.addEventListener("click", () => queueBackup("partial"));
    elements.dataManagementMigrationPreviewBtn?.addEventListener("click", () => loadMigrationSummary(elements.dataManagementMigrationPreviewBtn, true));
    elements.dataManagementExecuteMigrationBtn?.addEventListener("click", () => queueMigration(false));
    elements.dataManagementRefreshMigrationSummaryBtn?.addEventListener("click", () => loadMigrationSummary(elements.dataManagementRefreshMigrationSummaryBtn, true));
    bindMigrationPickerEvents();
    elements.dataManagementRefreshBackupsBtn?.addEventListener("click", loadDataManagementBackups);
    elements.dataManagementViewFullBackupsBtn?.addEventListener("click", () => setBackupFilter("full"));
    elements.dataManagementViewPartialBackupsBtn?.addEventListener("click", () => setBackupFilter("partial"));
    elements.dataManagementViewAllBackupsBtn?.addEventListener("click", () => setBackupFilter("all"));
    elements.dataManagementRefreshJobsBtn?.addEventListener("click", loadDataManagementJobs);
    elements.dataManagementJobDetailModal?.addEventListener("hidden.bs.modal", () => stopJobDetailAutoRefresh({ clearJob: true }));
    elements.dataManagementKeyVaultLink?.addEventListener("click", openKeyVaultSettings);
    bindDataManagementChangeTracking();
    setStorageAuthVisibility();
    setMigrationTargetVisibility();
    updateConnectionStringStatus();
    updateDataManagementSaveButtonState();
}

function bindMigrationPickerEvents() {
    migrationTargetTypes.forEach((targetType) => {
        getMigrationModeElement(targetType)?.addEventListener("change", () => {
            updateMigrationPickerVisibility(targetType);
            loadMigrationSummary();
        });
        getMigrationDocumentsElement(targetType)?.addEventListener("change", loadMigrationSummary);
        getMigrationSearchButton(targetType)?.addEventListener("click", () => loadMigrationCatalog(targetType));
        getMigrationSearchElement(targetType)?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                loadMigrationCatalog(targetType);
            }
        });
    });
    elements.datamanagementmigrationincludeaisearch?.addEventListener("change", loadMigrationSummary);
    elements.datamanagementmigrationincludesourceblobs?.addEventListener("change", loadMigrationSummary);
}

function bindDataManagementChangeTracking() {
    elements.tabPane?.querySelectorAll("input, select, textarea").forEach((element) => {
        const eventName = element.type === "checkbox" || element.type === "radio" || element.tagName === "SELECT" ? "change" : "input";
        element.addEventListener(eventName, markDataManagementModified);
    });
}

function markDataManagementModified() {
    dataManagementModified = true;
    updateDataManagementSaveButtonState();
}

function resetDataManagementModified() {
    dataManagementModified = false;
    updateDataManagementSaveButtonState();
}

function updateDataManagementSaveButtonState() {
    const button = elements.dataManagementSaveSettingsBtn;
    if (!button) {
        return;
    }

    button.disabled = !dataManagementModified;
    button.setAttribute("aria-disabled", String(!dataManagementModified));
    button.classList.toggle("btn-primary", dataManagementModified);
    button.classList.toggle("btn-secondary", !dataManagementModified);

    const icon = document.createElement("i");
    icon.className = "bi bi-save me-1";
    button.replaceChildren(icon, document.createTextNode(dataManagementModified ? "Save Settings" : "Saved"));
}

function setStatus(message, variant = "info") {
    if (!elements.dataManagementStatus) {
        return;
    }
    elements.dataManagementStatus.textContent = message || "";
    elements.dataManagementStatus.className = `alert alert-${variant}`;
    if (!message) {
        elements.dataManagementStatus.classList.add("d-none");
    } else {
        elements.dataManagementStatus.classList.remove("d-none");
    }
}

function setBusy(button, isBusy, busyLabel = "Working...") {
    if (!button) {
        return;
    }
    if (isBusy) {
        button.dataset.busyLabel = busyLabel;
        button.setAttribute("aria-busy", "true");
        button.disabled = true;
        return;
    }
    button.removeAttribute("aria-busy");
    button.disabled = false;
}

function setValue(element, value) {
    if (!element) {
        return;
    }
    element.value = value ?? "";
}

function setChecked(element, value) {
    if (!element) {
        return;
    }
    element.checked = Boolean(value);
}

function setElementVisible(element, isVisible) {
    if (!element) {
        return;
    }
    element.classList.toggle("d-none", !isVisible);
}

function getValue(element) {
    return element?.value?.trim() || "";
}

function getNumberValue(element, fallbackValue) {
    const parsed = Number.parseInt(getValue(element), 10);
    if (Number.isNaN(parsed)) {
        return fallbackValue;
    }
    return parsed;
}

function setStorageAuthVisibility() {
    const authenticationType = getValue(elements.datamanagementstorageauth) || backupStorageAuthManagedIdentity;
    const usesConnectionString = authenticationType === backupStorageAuthConnectionString;

    setElementVisible(elements.dataManagementBlobEndpointField, !usesConnectionString);
    setElementVisible(elements.dataManagementConnectionStringField, usesConnectionString);
    if (elements.datamanagementblobendpoint) {
        elements.datamanagementblobendpoint.disabled = usesConnectionString;
    }
    if (elements.datamanagementconnectionstring) {
        elements.datamanagementconnectionstring.disabled = !usesConnectionString;
    }
}

function updateConnectionStringStatus() {
    const statusElement = elements.dataManagementConnectionStringStatus;
    if (!statusElement) {
        return;
    }

    const authenticationType = getValue(elements.datamanagementstorageauth) || backupStorageAuthManagedIdentity;
    const connectionStringValue = getValue(elements.datamanagementconnectionstring);
    if (authenticationType !== backupStorageAuthConnectionString) {
        statusElement.textContent = "Connection strings are only used when authentication is set to Connection string.";
        return;
    }
    if (connectionStringValue && connectionStringValue !== redactedValue) {
        statusElement.textContent = "New connection string pending save.";
        return;
    }
    if (storedBackupConnectionStringAvailable) {
        statusElement.textContent = "Stored connection string saved. You can test storage without re-entering it.";
        return;
    }
    statusElement.textContent = "No connection string saved yet.";
}

function populateSettings(settings) {
    setChecked(elements.datamanagementenabled, settings.enabled);
    setValue(elements.datamanagementfullfrequency, settings.full_backup_frequency || "weekly");
    setValue(elements.datamanagementscheduledtimeutc, settings.scheduled_time_utc || settings.default_scheduled_time_utc || "03:00");
    setValue(elements.datamanagementretentiondays, settings.retention_days ?? 30);
    setChecked(elements.datamanagementpartialenabled, settings.partial_backups_enabled !== false);
    setChecked(elements.datamanagementlowimpactmode, settings.low_impact_mode !== false);
    setChecked(elements.datamanagementincludecosmos, settings.include_cosmos !== false);
    setChecked(elements.datamanagementincludeaisearch, settings.include_ai_search !== false);
    setChecked(elements.datamanagementincludesourceblobs, settings.enhanced_citations_enabled ? settings.include_source_blobs !== false : false);
    setValue(elements.datamanagementstorageauth, settings.backup_storage_authentication_type || backupStorageAuthManagedIdentity);
    setValue(elements.datamanagementblobendpoint, settings.backup_storage_blob_endpoint || "");
    setValue(elements.datamanagementcontainername, settings.backup_storage_container_name || "simplechat-backups");
    storedBackupConnectionStringAvailable = settings.backup_storage_connection_string === redactedValue;
    setValue(elements.datamanagementconnectionstring, storedBackupConnectionStringAvailable ? redactedValue : "");
    setValue(elements.datamanagementpathprefix, settings.backup_storage_path_prefix || "simplechat-backups");
    setChecked(elements.datamanagementencryptionenabled, settings.encryption_enabled !== false);
    setValue(elements.datamanagementtargetcosmosauth, settings.target_cosmos_authentication_type || "managed_identity");
    setValue(elements.datamanagementtargetcosmosendpoint, settings.target_cosmos_endpoint || "");
    setValue(elements.datamanagementtargetcosmosdatabase, targetCosmosDatabaseName);
    setValue(elements.datamanagementtargetcosmoskey, settings.target_cosmos_key || "");
    setValue(elements.datamanagementtargetaisearchauth, settings.target_ai_search_authentication_type || "managed_identity");
    setValue(elements.datamanagementtargetaisearchendpoint, settings.target_ai_search_endpoint || "");
    setValue(elements.datamanagementtargetaisearchkey, settings.target_ai_search_key || "");
    setValue(elements.datamanagementtargetecstorageauth, settings.target_enhanced_citations_storage_authentication_type || "managed_identity");
    setValue(elements.datamanagementtargetecblobendpoint, settings.target_enhanced_citations_storage_blob_endpoint || "");
    setValue(elements.datamanagementtargetecconnectionstring, settings.target_enhanced_citations_storage_connection_string || "");

    if (elements.dataManagementKeyStorage) {
        elements.dataManagementKeyStorage.textContent = formatKeyStorage(settings.encryption_key_storage);
    }
    if (elements.dataManagementKeyReference) {
        elements.dataManagementKeyReference.textContent = settings.encryption_key_reference ? redactedValue : "Not configured";
    }
    updateSourceBlobBackupAvailability(settings);
    updateKeyStorageExperience(settings);
    setStorageAuthVisibility();
    setMigrationTargetVisibility();
    migrationTargetTypes.forEach(updateMigrationPickerVisibility);
    updateConnectionStringStatus();
    resetDataManagementModified();
}

function updateSourceBlobBackupAvailability(settings) {
    const checkbox = elements.datamanagementincludesourceblobs;
    const message = elements.dataManagementSourceBlobsLockMessage;
    if (!checkbox) {
        return;
    }
    const enhancedCitationsEnabled = settings?.enhanced_citations_enabled === true;
    checkbox.disabled = !enhancedCitationsEnabled;
    checkbox.setAttribute("aria-disabled", String(!enhancedCitationsEnabled));
    if (!enhancedCitationsEnabled) {
        checkbox.checked = false;
        if (elements.datamanagementmigrationincludesourceblobs) {
            elements.datamanagementmigrationincludesourceblobs.checked = false;
            elements.datamanagementmigrationincludesourceblobs.disabled = true;
        }
        setText(message, "Enhanced Citations is off, so source document blob backups are unavailable.");
        return;
    }
    if (elements.datamanagementmigrationincludesourceblobs) {
        elements.datamanagementmigrationincludesourceblobs.disabled = false;
    }
    setText(message, "Enhanced Citations is on. Source document blob backup is available and enabled by default.");
}

function updateKeyStorageExperience(settings) {
    const alertElement = elements.dataManagementKeyStorageAlert;
    if (!alertElement) {
        return;
    }
    const keyStorage = settings?.encryption_key_storage || "not_configured";
    const keyVaultEnabled = settings?.key_vault_secret_storage_enabled === true;
    const keyVaultConfigured = settings?.key_vault_name_configured === true;

    if (keyStorage === "key_vault") {
        setKeyStorageAlert(
            "success",
            "bi-shield-check",
            "Backup encryption key is stored in Key Vault",
            "This backup encryption key is protected by Azure Key Vault. Review Key Vault settings if you need to change the vault or identity.",
            "Review Key Vault settings"
        );
        return;
    }

    if (keyVaultEnabled && keyVaultConfigured) {
        setKeyStorageAlert(
            "info",
            "bi-info-circle-fill",
            "Key Vault is enabled for future backup keys",
            "Generate a new backup encryption key to store it in Key Vault. Existing keys stored in settings remain there until regenerated.",
            "Open Key Vault settings"
        );
        return;
    }

    setKeyStorageAlert(
        "warning",
        "bi-exclamation-triangle-fill",
        "Key Vault is strongly recommended",
        "Generated backup encryption keys are stored in the Data Management settings document when Key Vault is not enabled. This works, but Key Vault is the recommended protection boundary for production.",
        "Enable Key Vault"
    );
}

function setMigrationTargetVisibility() {
    const cosmosUsesKey = getValue(elements.datamanagementtargetcosmosauth) === "key";
    setElementVisible(elements.dataManagementTargetCosmosKeyField, cosmosUsesKey);
    if (elements.datamanagementtargetcosmoskey) {
        elements.datamanagementtargetcosmoskey.disabled = !cosmosUsesKey;
    }

    const searchUsesKey = getValue(elements.datamanagementtargetaisearchauth) === "key";
    setElementVisible(elements.dataManagementTargetAiSearchKeyField, searchUsesKey);
    if (elements.datamanagementtargetaisearchkey) {
        elements.datamanagementtargetaisearchkey.disabled = !searchUsesKey;
    }

    const ecUsesConnectionString = getValue(elements.datamanagementtargetecstorageauth) === backupStorageAuthConnectionString;
    setElementVisible(elements.dataManagementTargetEcConnectionStringField, ecUsesConnectionString);
    setElementVisible(elements.dataManagementTargetEcBlobEndpointField, !ecUsesConnectionString);
    if (elements.datamanagementtargetecconnectionstring) {
        elements.datamanagementtargetecconnectionstring.disabled = !ecUsesConnectionString;
    }
    if (elements.datamanagementtargetecblobendpoint) {
        elements.datamanagementtargetecblobendpoint.disabled = ecUsesConnectionString;
    }
}

function setKeyStorageAlert(variant, iconClass, title, message, linkText) {
    const alertElement = elements.dataManagementKeyStorageAlert;
    const iconElement = elements.dataManagementKeyStorageAlertIcon;
    if (!alertElement) {
        return;
    }
    alertElement.classList.remove("alert-success", "alert-info", "alert-warning", "alert-danger");
    alertElement.classList.add(`alert-${variant}`);
    if (iconElement) {
        iconElement.className = `bi ${iconClass} mt-1`;
    }
    setText(elements.dataManagementKeyStorageAlertTitle, title);
    setText(elements.dataManagementKeyStorageAlertMessage, message);
    setText(elements.dataManagementKeyVaultLink, linkText);
}

function openKeyVaultSettings(event) {
    event?.preventDefault();
    const securityTabButton = document.getElementById("security-tab");
    if (securityTabButton && window.bootstrap?.Tab) {
        window.bootstrap.Tab.getOrCreateInstance(securityTabButton).show();
    } else if (securityTabButton) {
        securityTabButton.click();
    }
    window.location.hash = "security";
    window.setTimeout(() => {
        document.getElementById("keyvault-section")?.scrollIntoView({ block: "start", behavior: "smooth" });
    }, 100);
}

function collectSettings() {
    const backupStorageAuthenticationType = getValue(elements.datamanagementstorageauth) || backupStorageAuthManagedIdentity;
    return {
        enabled: Boolean(elements.datamanagementenabled?.checked),
        full_backup_frequency: getValue(elements.datamanagementfullfrequency) || "weekly",
        scheduled_time_utc: getValue(elements.datamanagementscheduledtimeutc) || "03:00",
        retention_days: getNumberValue(elements.datamanagementretentiondays, 30),
        partial_backups_enabled: Boolean(elements.datamanagementpartialenabled?.checked),
        low_impact_mode: Boolean(elements.datamanagementlowimpactmode?.checked),
        include_cosmos: Boolean(elements.datamanagementincludecosmos?.checked),
        include_ai_search: Boolean(elements.datamanagementincludeaisearch?.checked),
        include_source_blobs: Boolean(elements.datamanagementincludesourceblobs?.checked),
        backup_storage_authentication_type: backupStorageAuthenticationType,
        backup_storage_blob_endpoint: backupStorageAuthenticationType === backupStorageAuthManagedIdentity ? getValue(elements.datamanagementblobendpoint) : "",
        backup_storage_container_name: getValue(elements.datamanagementcontainername) || "simplechat-backups",
        backup_storage_connection_string: backupStorageAuthenticationType === backupStorageAuthConnectionString ? getValue(elements.datamanagementconnectionstring) : "",
        backup_storage_path_prefix: getValue(elements.datamanagementpathprefix) || "simplechat-backups",
        encryption_enabled: Boolean(elements.datamanagementencryptionenabled?.checked),
        target_cosmos_authentication_type: getValue(elements.datamanagementtargetcosmosauth) || "managed_identity",
        target_cosmos_endpoint: getValue(elements.datamanagementtargetcosmosendpoint),
        target_cosmos_database_name: targetCosmosDatabaseName,
        target_cosmos_key: getValue(elements.datamanagementtargetcosmoskey),
        target_ai_search_authentication_type: getValue(elements.datamanagementtargetaisearchauth) || "managed_identity",
        target_ai_search_endpoint: getValue(elements.datamanagementtargetaisearchendpoint),
        target_ai_search_key: getValue(elements.datamanagementtargetaisearchkey),
        target_enhanced_citations_storage_authentication_type: getValue(elements.datamanagementtargetecstorageauth) || backupStorageAuthManagedIdentity,
        target_enhanced_citations_storage_blob_endpoint: getValue(elements.datamanagementtargetecstorageauth) === backupStorageAuthManagedIdentity ? getValue(elements.datamanagementtargetecblobendpoint) : "",
        target_enhanced_citations_storage_connection_string: getValue(elements.datamanagementtargetecstorageauth) === backupStorageAuthConnectionString ? getValue(elements.datamanagementtargetecconnectionstring) : "",
    };
}

function formatKeyStorage(value) {
    if (value === "key_vault") {
        return "Key Vault";
    }
    if (value === "settings") {
        return "Backup settings document";
    }
    return "Not configured";
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });
    const contentType = response.headers.get("Content-Type") || "";
    if (response.redirected || !contentType.toLowerCase().includes("application/json")) {
        throw new Error("The Data Management request returned a non-JSON response. Please refresh and sign in again if needed.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) {
        throw new Error(data.error || `Request failed with status ${response.status}`);
    }
    return data;
}

async function loadDataManagementSettings() {
    try {
        const data = await requestJson("/api/admin/data-management/settings", { method: "GET" });
        populateSettings(data.settings || {});
        setStatus("", "info");
    } catch (error) {
        setStatus(error.message || "Data Management settings could not be loaded.", "danger");
        showToast("Data Management settings could not be loaded.", "danger");
    }
}

async function saveDataManagementSettings(raiseOnFailure = false) {
    if (!dataManagementModified) {
        return true;
    }
    setBusy(elements.dataManagementSaveSettingsBtn, true, "Saving...");
    try {
        const data = await requestJson("/api/admin/data-management/settings", {
            method: "PUT",
            body: JSON.stringify(collectSettings()),
        });
        populateSettings(data.settings || {});
        setStatus("Data Management settings saved.", "success");
        showToast("Data Management settings saved.", "success");
        return true;
    } catch (error) {
        setStatus(error.message || "Data Management settings could not be saved.", "danger");
        showToast(error.message || "Data Management settings could not be saved.", "danger");
        if (raiseOnFailure) {
            throw error;
        }
        return false;
    } finally {
        setBusy(elements.dataManagementSaveSettingsBtn, false);
        updateDataManagementSaveButtonState();
    }
}

async function generateEncryptionKey() {
    setBusy(elements.dataManagementGenerateKeyBtn, true, "Generating...");
    try {
        const data = await requestJson("/api/admin/data-management/encryption-key", { method: "POST", body: "{}" });
        populateSettings(data.settings || {});
        setStatus("Backup encryption key generated.", "success");
        showToast("Backup encryption key generated.", "success");
    } catch (error) {
        setStatus(error.message || "Backup encryption key could not be generated.", "danger");
        showToast("Backup encryption key could not be generated.", "danger");
    } finally {
        setBusy(elements.dataManagementGenerateKeyBtn, false);
    }
}

async function testBackupStorage() {
    setBusy(elements.dataManagementTestStorageBtn, true, "Testing...");
    try {
        const data = await requestJson("/api/admin/data-management/storage/test", {
            method: "POST",
            body: JSON.stringify({ settings: collectSettings(), create_container: true }),
        });
        const containerStatus = data.container_created ? "created" : data.container_exists ? "found" : "not found";
        setStatus(`Backup storage connection succeeded. Container ${containerStatus}: ${data.container_name}.`, "success");
        showToast("Backup storage connection succeeded.", "success");
    } catch (error) {
        setStatus(error.message || "Backup storage connection test failed.", "danger");
        showToast(error.message || "Backup storage connection test failed.", "danger");
    } finally {
        setBusy(elements.dataManagementTestStorageBtn, false);
    }
}

async function testTargetCosmos() {
    setBusy(elements.dataManagementTestTargetCosmosBtn, true, "Testing...");
    try {
        const data = await requestJson("/api/admin/data-management/target/cosmos/test", {
            method: "POST",
            body: JSON.stringify({ settings: collectSettings() }),
        });
        setStatus(`Target Cosmos connection succeeded. Database: ${data.database_name || targetCosmosDatabaseName}.`, "success");
        showToast("Target Cosmos connection succeeded.", "success");
    } catch (error) {
        setStatus(error.message || "Target Cosmos connection test failed.", "danger");
        showToast(error.message || "Target Cosmos connection test failed.", "danger");
    } finally {
        setBusy(elements.dataManagementTestTargetCosmosBtn, false);
    }
}

async function testTargetSearch() {
    setBusy(elements.dataManagementTestTargetSearchBtn, true, "Testing...");
    try {
        const data = await requestJson("/api/admin/data-management/target/search/test", {
            method: "POST",
            body: JSON.stringify({ settings: collectSettings() }),
        });
        const existingCount = Array.isArray(data.existing_indexes) ? data.existing_indexes.length : 0;
        const missingCount = Array.isArray(data.missing_indexes) ? data.missing_indexes.length : 0;
        setStatus(`Target Search connection succeeded. ${formatNumber(existingCount)} expected indexes found, ${formatNumber(missingCount)} missing. Missing indexes can be created during migration.`, "success");
        showToast("Target Search connection succeeded.", "success");
    } catch (error) {
        setStatus(error.message || "Target Search connection test failed.", "danger");
        showToast(error.message || "Target Search connection test failed.", "danger");
    } finally {
        setBusy(elements.dataManagementTestTargetSearchBtn, false);
    }
}

async function testTargetEnhancedCitationStorage() {
    setBusy(elements.dataManagementTestTargetEcStorageBtn, true, "Testing...");
    try {
        const data = await requestJson("/api/admin/data-management/target/enhanced-citation-storage/test", {
            method: "POST",
            body: JSON.stringify({ settings: collectSettings(), create_containers: true }),
        });
        const containers = Array.isArray(data.containers) ? data.containers : [];
        const readyCount = containers.filter((container) => container.container_exists).length;
        setStatus(`Target Enhanced Citation Storage connection succeeded. ${formatNumber(readyCount)} containers are ready.`, "success");
        showToast("Target Enhanced Citation Storage connection succeeded.", "success");
    } catch (error) {
        setStatus(error.message || "Target Enhanced Citation Storage connection test failed.", "danger");
        showToast(error.message || "Target Enhanced Citation Storage connection test failed.", "danger");
    } finally {
        setBusy(elements.dataManagementTestTargetEcStorageBtn, false);
    }
}

function queueBackup(backupType) {
    return queueOperation("backup", backupType, {
        include_cosmos: Boolean(elements.datamanagementincludecosmos?.checked),
        include_ai_search: Boolean(elements.datamanagementincludeaisearch?.checked),
        include_source_blobs: Boolean(elements.datamanagementincludesourceblobs?.checked),
    });
}

async function queueOperation(operation, backupType = null, options = {}, triggerButton = null) {
    const button = triggerButton || buttonForOperation(operation, backupType);
    setBusy(button, true, "Queueing...");
    try {
        await saveDataManagementSettings(true);
        const data = await requestJson("/api/admin/data-management/jobs", {
            method: "POST",
            body: JSON.stringify({ operation, backup_type: backupType, options }),
        });
        setStatus(`Queued ${formatOperation(operation, backupType)} job.`, "success");
        showToast("Data Management job queued.", "success");
        renderJobs([data.job]);
        loadDataManagementJobs();
        loadDataManagementBackups();
    } catch (error) {
        setStatus(error.message || "Data Management job could not be queued.", "danger");
        showToast(error.message || "Data Management job could not be queued.", "danger");
    } finally {
        setBusy(button, false);
    }
}

function queueMigration(dryRun) {
    const button = elements.dataManagementExecuteMigrationBtn;
    return queueOperation("migration", null, {
        dry_run: Boolean(dryRun),
        migration_plan: buildMigrationPlan(),
    }, button);
}

function buttonForOperation(operation, backupType) {
    if (operation === "backup" && backupType === "full") {
        return elements.dataManagementRunFullBackupBtn;
    }
    if (operation === "backup" && backupType === "partial") {
        return elements.dataManagementRunPartialBackupBtn;
    }
    if (operation === "migration") {
        return elements.dataManagementExecuteMigrationBtn;
    }
    return null;
}

function getMigrationModeElement(targetType) {
    return elements[`datamanagementmigration${targetType.replace(/_/g, "")}mode`];
}

function getMigrationSearchElement(targetType) {
    return elements[`datamanagementmigration${targetType.replace(/_/g, "")}search`];
}

function getMigrationDocumentsElement(targetType) {
    return elements[`datamanagementmigration${targetType.replace(/_/g, "")}documents`];
}

function getMigrationSearchButton(targetType) {
    const key = targetType === "public_workspaces" ? "dataManagementSearchPublicWorkspacesBtn" : `dataManagementSearch${formatMigrationTargetName(targetType)}Btn`;
    return elements[key];
}

function getMigrationAvailableElement(targetType) {
    return elements[`dataManagementMigration${targetType.replace(/_/g, "").replace(/^publicworkspaces$/, "PublicWorkspaces")}Available`] || elements[`dataManagementMigration${formatMigrationTargetName(targetType)}Available`];
}

function getMigrationSelectedElement(targetType) {
    return elements[`dataManagementMigration${targetType.replace(/_/g, "").replace(/^publicworkspaces$/, "PublicWorkspaces")}Selected`] || elements[`dataManagementMigration${formatMigrationTargetName(targetType)}Selected`];
}

function formatMigrationTargetName(targetType) {
    if (targetType === "public_workspaces") {
        return "PublicWorkspaces";
    }
    return targetType.charAt(0).toUpperCase() + targetType.slice(1);
}

function updateMigrationPickerVisibility(targetType) {
    const mode = getValue(getMigrationModeElement(targetType)) || "none";
    const isSelectedMode = mode === "selected";
    const searchElement = getMigrationSearchElement(targetType);
    const searchButton = getMigrationSearchButton(targetType);
    if (searchElement) {
        searchElement.disabled = !isSelectedMode;
    }
    if (searchButton) {
        searchButton.disabled = !isSelectedMode;
    }
    renderMigrationSelectedList(targetType);
}

async function loadMigrationCatalog(targetType) {
    const availableElement = getMigrationAvailableElement(targetType);
    if (!availableElement) {
        return;
    }
    availableElement.replaceChildren(createSmallMutedElement("Loading..."));
    try {
        const search = getValue(getMigrationSearchElement(targetType));
        const data = await requestJson(`/api/admin/data-management/migration/catalog/${encodeURIComponent(targetType)}?search=${encodeURIComponent(search)}&limit=50`, { method: "GET" });
        renderMigrationAvailableList(targetType, Array.isArray(data.items) ? data.items : []);
    } catch (error) {
        availableElement.replaceChildren(createSmallMutedElement(error.message || "Migration catalog could not be loaded."));
    }
}

function renderMigrationAvailableList(targetType, items) {
    const availableElement = getMigrationAvailableElement(targetType);
    if (!availableElement) {
        return;
    }
    availableElement.replaceChildren();
    if (!items.length) {
        availableElement.appendChild(createSmallMutedElement("No matches found."));
        return;
    }
    items.forEach((item) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "list-group-item list-group-item-action py-2";
        row.appendChild(createMigrationItemContent(item, "Add"));
        row.addEventListener("click", () => {
            migrationSelections[targetType].set(item.id, item);
            renderMigrationSelectedList(targetType);
            loadMigrationSummary();
        });
        availableElement.appendChild(row);
    });
}

function renderMigrationSelectedList(targetType) {
    const selectedElement = getMigrationSelectedElement(targetType);
    if (!selectedElement) {
        return;
    }
    selectedElement.replaceChildren();
    const selectedItems = Array.from(migrationSelections[targetType].values());
    if (!selectedItems.length) {
        selectedElement.appendChild(createSmallMutedElement("No selected items."));
        return;
    }
    selectedItems.forEach((item) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "list-group-item list-group-item-action py-2";
        row.appendChild(createMigrationItemContent(item, "Remove"));
        row.addEventListener("click", () => {
            migrationSelections[targetType].delete(item.id);
            renderMigrationSelectedList(targetType);
            loadMigrationSummary();
        });
        selectedElement.appendChild(row);
    });
}

function createMigrationItemContent(item, actionLabel) {
    const wrapper = document.createElement("div");
    wrapper.className = "d-flex justify-content-between align-items-start gap-2";
    const textWrapper = document.createElement("div");
    const label = document.createElement("div");
    label.className = "fw-semibold";
    label.textContent = item.label || item.id || "Unnamed";
    const description = document.createElement("div");
    description.className = "text-muted small";
    const documentCount = Number(item.document_count || 0);
    description.textContent = `${item.description || item.id || ""}${documentCount ? ` - ${formatNumber(documentCount)} documents` : ""}`;
    const action = document.createElement("span");
    action.className = "badge bg-light text-dark border";
    action.textContent = actionLabel;
    textWrapper.append(label, description);
    wrapper.append(textWrapper, action);
    return wrapper;
}

function createSmallMutedElement(text) {
    const element = document.createElement("div");
    element.className = "text-muted small p-2";
    element.textContent = text;
    return element;
}

function buildMigrationPlan() {
    return {
        users: buildMigrationSelection("users"),
        groups: buildMigrationSelection("groups"),
        public_workspaces: buildMigrationSelection("public_workspaces"),
        include_ai_search: Boolean(elements.datamanagementmigrationincludeaisearch?.checked),
        include_source_blobs: Boolean(elements.datamanagementmigrationincludesourceblobs?.checked),
    };
}

function buildMigrationSelection(targetType) {
    const mode = getValue(getMigrationModeElement(targetType)) || "none";
    return {
        mode,
        ids: mode === "selected" ? Array.from(migrationSelections[targetType].keys()) : [],
        include_documents: mode !== "none" && Boolean(getMigrationDocumentsElement(targetType)?.checked),
    };
}

async function loadMigrationSummary(triggerButton = null, showSuccess = false) {
    const summaryElement = elements.dataManagementMigrationSummary;
    if (!summaryElement) {
        return;
    }
    setBusy(triggerButton, true, "Previewing...");
    try {
        const data = await requestJson("/api/admin/data-management/migration/summary", {
            method: "POST",
            body: JSON.stringify({ migration_plan: buildMigrationPlan() }),
        });
        renderMigrationSummary(data.summary || {});
        if (showSuccess) {
            setStatus("Migration preview refreshed.", "success");
            showToast("Migration preview refreshed.", "success");
        }
    } catch (error) {
        summaryElement.replaceChildren(createSmallMutedElement(error.message || "Migration summary could not be loaded."));
        if (showSuccess) {
            setStatus(error.message || "Migration summary could not be loaded.", "danger");
            showToast(error.message || "Migration summary could not be loaded.", "danger");
        }
    } finally {
        setBusy(triggerButton, false);
    }
}

function renderMigrationSummary(summary) {
    const summaryElement = elements.dataManagementMigrationSummary;
    if (!summaryElement) {
        return;
    }
    const container = document.createElement("div");
    container.className = "row g-3";
    migrationTargetTypes.forEach((targetType) => {
        const targetSummary = summary[targetType] || {};
        container.appendChild(createMigrationSummaryCard(targetType, targetSummary));
    });
    const optionsColumn = document.createElement("div");
    optionsColumn.className = "col-12";
    const options = document.createElement("div");
    options.className = "d-flex flex-wrap gap-2";
    options.appendChild(createBadge(summary.include_ai_search ? "AI Search included" : "AI Search skipped", summary.include_ai_search ? "bg-info text-dark" : "bg-secondary"));
    options.appendChild(createBadge(summary.include_source_blobs ? "Source blobs included" : "Source blobs skipped", summary.include_source_blobs ? "bg-info text-dark" : "bg-secondary"));
    optionsColumn.appendChild(options);
    container.appendChild(optionsColumn);
    summaryElement.replaceChildren(container);
}

function createMigrationSummaryCard(targetType, targetSummary) {
    const column = document.createElement("div");
    column.className = "col-md-4";
    const wrapper = document.createElement("div");
    wrapper.className = "border rounded p-3 h-100";
    const title = document.createElement("div");
    title.className = "fw-semibold";
    title.textContent = formatActivityLabel(targetType);
    const count = document.createElement("div");
    count.className = "fs-5 fw-semibold";
    count.textContent = formatNumber(targetSummary.count || 0);
    const mode = document.createElement("div");
    mode.className = "text-muted small";
    mode.textContent = `${formatActivityLabel(targetSummary.mode || "none")} - ${targetSummary.include_documents ? "documents included" : "documents skipped"}`;
    const details = document.createElement("details");
    details.className = "mt-2";
    const summaryLabel = document.createElement("summary");
    summaryLabel.className = "small";
    summaryLabel.textContent = "View selected IDs";
    const idList = document.createElement("div");
    idList.className = "small text-muted text-break mt-1";
    idList.textContent = Array.isArray(targetSummary.ids) && targetSummary.ids.length ? targetSummary.ids.join(", ") : "No explicit selected IDs.";
    details.append(summaryLabel, idList);
    wrapper.append(title, count, mode, details);
    column.appendChild(wrapper);
    return column;
}

function formatOperation(operation, backupType) {
    if (operation === "backup") {
        return `${backupType || "manual"} backup`;
    }
    return operation.replace(/_/g, " ");
}

async function loadDataManagementJobs() {
    setBusy(elements.dataManagementRefreshJobsBtn, true, "Refreshing...");
    try {
        const data = await requestJson("/api/admin/data-management/jobs?limit=25", { method: "GET" });
        renderJobs(data.jobs || []);
    } catch (error) {
        renderJobMessage(error.message || "Job history could not be loaded.", "danger");
    } finally {
        setBusy(elements.dataManagementRefreshJobsBtn, false);
    }
}

async function loadDataManagementBackups() {
    setBusy(elements.dataManagementRefreshBackupsBtn, true, "Refreshing...");
    try {
        const data = await requestJson("/api/admin/data-management/backups?limit=100", { method: "GET" });
        backupInventory = Array.isArray(data.backups) ? data.backups : [];
        renderBackupSummary(data.summary || {});
        setBackupFilter(currentBackupFilter);
    } catch (error) {
        renderBackupMessage(error.message || "Backup inventory could not be loaded.", "danger");
    } finally {
        setBusy(elements.dataManagementRefreshBackupsBtn, false);
    }
}

function renderBackupSummary(summary) {
    setText(elements.dataManagementFullBackupCount, formatNumber(summary.full || 0));
    setText(elements.dataManagementPartialBackupCount, formatNumber(summary.partial || 0));
    setText(elements.dataManagementAvailableBackupCount, formatNumber(summary.available || 0));
}

function setBackupFilter(filterValue) {
    currentBackupFilter = ["all", "full", "partial"].includes(filterValue) ? filterValue : "all";
    [
        elements.dataManagementViewAllBackupsBtn,
        elements.dataManagementViewFullBackupsBtn,
        elements.dataManagementViewPartialBackupsBtn,
    ].forEach((button) => {
        const selected = button?.dataset.backupFilter === currentBackupFilter;
        button?.classList.toggle("btn-primary", selected);
        button?.classList.toggle("btn-outline-primary", !selected);
        button?.setAttribute("aria-pressed", String(selected));
        button?.querySelectorAll(".text-muted, .text-white-50").forEach((element) => {
            element.classList.toggle("text-muted", !selected);
            element.classList.toggle("text-white-50", selected);
        });
    });
    renderBackups();
}

function renderBackups() {
    const tbody = elements.dataManagementBackupsTbody;
    if (!tbody) {
        return;
    }
    const availableBackups = backupInventory.filter(isAvailableBackup);
    const filteredBackups = currentBackupFilter === "all"
        ? availableBackups
        : availableBackups.filter((backup) => backup.backup_type === currentBackupFilter);
    tbody.replaceChildren();
    if (filteredBackups.length === 0) {
        renderBackupMessage("No completed backups match this view yet.", "muted");
        return;
    }

    filteredBackups.forEach((backup) => {
        tbody.appendChild(createBackupRow(backup));
    });
}

function renderBackupMessage(message, variant) {
    const tbody = elements.dataManagementBackupsTbody;
    if (!tbody) {
        return;
    }
    tbody.replaceChildren(createMessageRow(message, variant, 7));
}

function createBackupRow(backup) {
    const row = document.createElement("tr");
    row.appendChild(createBackupIdentityCell(backup));
    row.appendChild(createCell(formatDate(backup.completed_at || backup.created_at)));
    row.appendChild(createBackupContentsCell(backup));
    row.appendChild(createBackupStorageCell(backup));
    row.appendChild(createBackupProtectionCell(backup));
    row.appendChild(createBackupWarningCell(backup));
    row.appendChild(createJobActionCell(backup.id));
    return row;
}

function createBackupIdentityCell(backup) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("div");
    wrapper.className = "vstack gap-1";
    wrapper.appendChild(createBadge(formatBackupType(backup.backup_type), backup.backup_type === "full" ? "bg-primary" : "bg-info text-dark"));
    const statusLine = document.createElement("small");
    statusLine.className = "text-muted";
    statusLine.textContent = formatStatusLabel(backup.status || "unknown");
    wrapper.appendChild(statusLine);
    cell.appendChild(wrapper);
    return cell;
}

function createBackupContentsCell(backup) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("div");
    wrapper.className = "vstack gap-1";
    wrapper.appendChild(createLabeledValue("Artifacts", formatNumber(backup.artifact_count || 0)));
    wrapper.appendChild(createLabeledValue("Records / blobs", formatBackupRecordCounts(backup)));
    wrapper.appendChild(createLabeledValue("Size", formatBytes(backup.bytes || 0)));
    cell.appendChild(wrapper);
    return cell;
}

function createBackupStorageCell(backup) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("div");
    wrapper.className = "vstack gap-1";
    wrapper.appendChild(createLabeledValue("Prefix", backup.base_prefix || "Not recorded", true));
    wrapper.appendChild(createLabeledValue("Manifest", backup.manifest_path ? "Recorded" : "Not recorded"));
    if (backup.manifest_path) {
        const manifestPath = document.createElement("small");
        manifestPath.className = "text-muted text-break";
        manifestPath.textContent = backup.manifest_path;
        wrapper.appendChild(manifestPath);
    }
    cell.appendChild(wrapper);
    return cell;
}

function createBackupProtectionCell(backup) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("div");
    wrapper.className = "d-flex flex-wrap gap-1";
    wrapper.appendChild(createBadge(backup.encrypted ? "Encrypted" : "Not encrypted", backup.encrypted ? "bg-success" : "bg-secondary"));
    wrapper.appendChild(createBadge(backup.scheduled ? "Scheduled" : "Manual", "bg-light text-dark border"));
    cell.appendChild(wrapper);
    return cell;
}

function createBackupWarningCell(backup) {
    const cell = document.createElement("td");
    const warningCount = Number(backup.warning_count || 0);
    if (warningCount > 0) {
        cell.appendChild(createBadge(`${formatNumber(warningCount)} warning${warningCount === 1 ? "" : "s"}`, "bg-warning text-dark"));
        return cell;
    }
    const noWarnings = document.createElement("span");
    noWarnings.className = "text-muted";
    noWarnings.textContent = "None";
    cell.appendChild(noWarnings);
    return cell;
}

function createLabeledValue(label, value, allowBreak = false) {
    const wrapper = document.createElement("div");
    const labelElement = document.createElement("span");
    labelElement.className = "text-muted small me-1";
    labelElement.textContent = `${label}:`;
    const valueElement = document.createElement("span");
    valueElement.className = allowBreak ? "fw-semibold text-break" : "fw-semibold";
    valueElement.textContent = value || "N/A";
    wrapper.append(labelElement, valueElement);
    return wrapper;
}

function isAvailableBackup(backup) {
    return backup?.status === "completed" || backup?.status === "completed_with_warnings";
}

function renderJobs(jobs) {
    const tbody = elements.dataManagementJobsTbody;
    if (!tbody) {
        return;
    }
    tbody.replaceChildren();
    if (!Array.isArray(jobs) || jobs.length === 0) {
        renderJobMessage("No Data Management jobs have been queued yet.", "muted");
        return;
    }

    jobs.forEach((job) => {
        tbody.appendChild(createJobRow(job));
    });
}

function renderJobMessage(message, variant) {
    const tbody = elements.dataManagementJobsTbody;
    if (!tbody) {
        return;
    }
    tbody.replaceChildren(createMessageRow(message, variant, 6));
}

function createJobRow(job) {
    const row = document.createElement("tr");
    row.appendChild(createCell(formatDate(job.created_at)));
    row.appendChild(createCell(formatOperation(job.operation || "", job.backup_type || "")));
    row.appendChild(createStatusCell(job.status || "unknown"));
    row.appendChild(createCell(formatProgress(job.progress)));
    row.appendChild(createCell(job.last_message || job.last_error || ""));
    row.appendChild(createJobActionCell(job.id));
    return row;
}

function createMessageRow(message, variant, columnSpan) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columnSpan;
    cell.className = variant === "danger" ? "text-danger" : "text-muted";
    cell.textContent = message;
    row.appendChild(cell);
    return row;
}

function createJobActionCell(jobId) {
    const cell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline-primary btn-sm";
    button.disabled = !jobId;
    const icon = document.createElement("i");
    icon.className = "bi bi-list-check me-1";
    button.appendChild(icon);
    button.appendChild(document.createTextNode("View Log"));
    button.addEventListener("click", () => loadDataManagementJobDetail(jobId));
    cell.appendChild(button);
    return cell;
}

function createCell(text) {
    const cell = document.createElement("td");
    cell.textContent = text ?? "";
    return cell;
}

function setText(element, text) {
    if (element) {
        element.textContent = text ?? "";
    }
}

async function loadDataManagementJobDetail(jobId, options = {}) {
    if (!jobId) {
        return;
    }
    const shouldShowModal = options.showModal !== false;
    const isLiveRefresh = options.liveRefresh === true;
    try {
        const data = await requestJson(`/api/admin/data-management/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
        renderJobDetailModal(data.job || {}, Array.isArray(data.items) ? data.items : []);
        if (shouldShowModal && elements.dataManagementJobDetailModal && window.bootstrap?.Modal) {
            const modal = window.bootstrap.Modal.getOrCreateInstance(elements.dataManagementJobDetailModal);
            modal.show();
        }
        updateJobDetailAutoRefresh(data.job || {});
    } catch (error) {
        if (isLiveRefresh) {
            stopJobDetailAutoRefresh({ message: "Live refresh paused after a request failure." });
            return;
        }
        setStatus(error.message || "Data Management job details could not be loaded.", "danger");
        showToast("Data Management job details could not be loaded.", "danger");
    }
}

function renderJobDetailModal(job, items) {
    currentJobDetailId = job.id || currentJobDetailId;
    setText(elements.dataManagementJobDetailTitle, formatOperation(job.operation || "job", job.backup_type || ""));
    setText(elements.dataManagementJobDetailSubtitle, job.id ? `Job ID: ${job.id}` : "Job ID not available");
    renderJobDetailSummary(job);
    renderJobDetailProgress(job);
    renderJobItems(items);
    const artifacts = getJobArtifacts(job, items);
    renderJobArtifacts(artifacts);
    renderJobManifest(job, artifacts);
    renderJobWarnings(job, artifacts);
}

function renderJobDetailSummary(job) {
    const container = elements.dataManagementJobDetailSummary;
    if (!container) {
        return;
    }
    const result = job.result && typeof job.result === "object" ? job.result : {};
    container.replaceChildren(
        createSummaryTile("Status", createStatusBadge(job.status || "unknown")),
        createSummaryTile("Progress", formatProgress(job.progress)),
        createSummaryTile("Operation", formatOperation(job.operation || "job", job.backup_type || "")),
        createSummaryTile("Backup Type", job.backup_type ? formatBackupType(job.backup_type) : "N/A"),
        createSummaryTile("Requested By", job.requested_by_email || (job.scheduled ? "Scheduled" : "Unknown")),
        createSummaryTile("Created", formatDate(job.created_at)),
        createSummaryTile("Started", formatDate(job.started_at)),
        createSummaryTile("Completed", formatDate(job.completed_at)),
        createSummaryTile("Artifacts", formatNumber(result.artifact_count || getArtifactTotals(result.artifacts).artifactCount || 0))
    );
}

function createSummaryTile(label, value) {
    const wrapper = document.createElement("div");
    wrapper.className = "col-sm-6 col-xl-3";
    const labelElement = document.createElement("div");
    labelElement.className = "text-muted small";
    labelElement.textContent = label;
    const valueElement = document.createElement("div");
    valueElement.className = "fw-semibold text-break";
    if (value instanceof Node) {
        valueElement.appendChild(value);
    } else {
        valueElement.textContent = value || "N/A";
    }
    wrapper.append(labelElement, valueElement);
    return wrapper;
}

function renderJobDetailProgress(job) {
    const container = elements.dataManagementJobDetailProgress;
    if (!container) {
        return;
    }
    const progress = job.progress && typeof job.progress === "object" ? job.progress : {};
    const percent = getProgressPercent(progress);
    const completedSteps = Number(progress.completed_steps || 0);
    const totalSteps = Number(progress.total_steps || 0);
    const card = document.createElement("div");
    card.className = "card border-info-subtle";
    const body = document.createElement("div");
    body.className = "card-body";

    const header = document.createElement("div");
    header.className = "d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2";
    const title = document.createElement("div");
    title.className = "fw-semibold";
    title.textContent = progress.current_step ? formatActivityLabel(progress.current_step) : "Job progress";
    const stepText = document.createElement("small");
    stepText.className = "text-muted";
    stepText.textContent = totalSteps > 0 ? `${formatNumber(completedSteps)} of ${formatNumber(totalSteps)} steps complete` : "Waiting for step details";
    header.append(title, stepText);

    const progressWrapper = document.createElement("div");
    progressWrapper.className = "progress";
    progressWrapper.setAttribute("role", "progressbar");
    progressWrapper.setAttribute("aria-valuenow", String(percent));
    progressWrapper.setAttribute("aria-valuemin", "0");
    progressWrapper.setAttribute("aria-valuemax", "100");
    const progressBar = document.createElement("div");
    progressBar.className = `progress-bar ${job.status === "failed" ? "bg-danger" : "bg-primary"}`;
    progressBar.style.width = `${percent}%`;
    progressBar.textContent = `${percent}%`;
    progressWrapper.appendChild(progressBar);

    const message = document.createElement("p");
    message.className = "text-muted small mt-2 mb-0";
    message.textContent = job.last_message || job.last_error || "No job message has been recorded yet.";
    body.append(header, progressWrapper, message);
    card.appendChild(body);
    container.replaceChildren(card);
}

function renderJobItems(items) {
    const container = elements.dataManagementJobItemsTbody;
    if (!container) {
        return;
    }
    container.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
        container.appendChild(createEmptyDetailState("No timeline events recorded for this job."));
        return;
    }
    items.forEach((item) => {
        container.appendChild(createTimelineItem(item));
    });
}

function createTimelineItem(item) {
    const itemElement = document.createElement("div");
    itemElement.className = "list-group-item";
    const header = document.createElement("div");
    header.className = "d-flex flex-wrap justify-content-between align-items-start gap-2";

    const titleWrapper = document.createElement("div");
    const title = document.createElement("div");
    title.className = "fw-semibold";
    title.textContent = formatActivityLabel(item.step_name || "event");
    const timestamp = document.createElement("small");
    timestamp.className = "text-muted";
    timestamp.textContent = formatDate(item.created_at);
    titleWrapper.append(title, timestamp);
    header.append(titleWrapper, createStatusBadge(item.status || "unknown"));

    const message = document.createElement("p");
    message.className = "small mb-2 mt-2";
    message.textContent = item.message || "No message recorded.";

    const details = createDetailChipGroup(item.details);
    itemElement.append(header, message, details);
    return itemElement;
}

function getJobArtifacts(job, items) {
    const resultArtifacts = job?.result?.artifacts;
    if (Array.isArray(resultArtifacts) && resultArtifacts.length > 0) {
        return resultArtifacts;
    }
    const exportItem = items.find((item) => Array.isArray(item?.details?.artifacts));
    return exportItem?.details?.artifacts || [];
}

function renderJobArtifacts(artifacts) {
    const container = elements.dataManagementJobArtifactsTbody;
    if (!container) {
        return;
    }
    container.replaceChildren();
    if (!Array.isArray(artifacts) || artifacts.length === 0) {
        container.appendChild(createEmptyDetailState("No backup artifacts recorded for this job."));
        return;
    }
    artifacts.forEach((artifact) => {
        container.appendChild(createArtifactCard(artifact));
    });
}

function createArtifactCard(artifact) {
    const card = document.createElement("div");
    card.className = "card border-light-subtle";
    const body = document.createElement("div");
    body.className = "card-body p-3";

    const header = document.createElement("div");
    header.className = "d-flex flex-wrap justify-content-between align-items-start gap-2 mb-2";
    const titleWrapper = document.createElement("div");
    const title = document.createElement("div");
    title.className = "fw-semibold";
    title.textContent = artifact.name || artifact.index_name || artifact.container_name || "Unnamed artifact";
    const typeLine = document.createElement("small");
    typeLine.className = "text-muted";
    typeLine.textContent = [artifact.type, artifact.category || artifact.index_name].filter(Boolean).map(formatActivityLabel).join(" / ") || "Artifact";
    titleWrapper.append(title, typeLine);

    const badges = document.createElement("div");
    badges.className = "d-flex flex-wrap gap-1";
    badges.appendChild(createBadge(formatActivityLabel(artifact.status || "recorded"), artifact.status === "warning" ? "bg-warning text-dark" : "bg-light text-dark border"));
    if (artifact.encrypted) {
        badges.appendChild(createBadge("Encrypted", "bg-success"));
    }
    header.append(titleWrapper, badges);

    const metrics = document.createElement("div");
    metrics.className = "row g-2 small mb-2";
    metrics.append(
        createDetailMetric("Records", formatNumber(artifact.item_count || 0)),
        createDetailMetric("Blobs", formatNumber(artifact.blob_count || 0)),
        createDetailMetric("Size", formatBytes(artifact.bytes || 0))
    );

    const location = createDetailBlock("Location", artifact.path || artifact.prefix || "Not recorded");
    const notes = createArtifactNoteGroup(artifact);
    body.append(header, metrics, location, notes);
    card.appendChild(body);
    return card;
}

function renderJobManifest(job, artifacts) {
    const container = elements.dataManagementJobManifestDetail;
    if (!container) {
        return;
    }
    const result = job.result && typeof job.result === "object" ? job.result : {};
    const totals = getArtifactTotals(artifacts);
    const fieldList = document.createElement("div");
    fieldList.className = "vstack gap-2";
    fieldList.append(
        createDetailBlock("Manifest path", result.manifest_path || "Not recorded"),
        createDetailBlock("Storage prefix", result.base_prefix || "Not recorded"),
        createDetailBlock("Artifacts", formatNumber(result.artifact_count || totals.artifactCount || 0)),
        createDetailBlock("Records / blobs", `${formatNumber(totals.recordCount)} records / ${formatNumber(totals.blobCount)} blobs`),
        createDetailBlock("Total size", formatBytes(totals.bytes))
    );
    container.replaceChildren(fieldList);
}

function renderJobWarnings(job, artifacts) {
    const container = elements.dataManagementJobWarnings;
    if (!container) {
        return;
    }
    const warnings = [];
    if (Array.isArray(job.warnings)) {
        job.warnings.forEach((warning) => warnings.push(String(warning || "")));
    }
    if (Array.isArray(artifacts)) {
        artifacts.forEach((artifact) => {
            if (artifact?.warning) {
                warnings.push(`${artifact.name || artifact.type || "Artifact"}: ${artifact.warning}`);
            }
        });
    }

    if (!warnings.length) {
        container.replaceChildren(createEmptyDetailState("No warnings recorded for this job."));
        return;
    }

    const list = document.createElement("div");
    list.className = "vstack gap-2";
    warnings.forEach((warning) => {
        const alert = document.createElement("div");
        alert.className = "alert alert-warning py-2 px-3 mb-0 small";
        alert.textContent = warning;
        list.appendChild(alert);
    });
    container.replaceChildren(list);
}

function createBadge(text, className) {
    const badge = document.createElement("span");
    badge.className = `badge ${className || "bg-secondary"}`;
    badge.textContent = text || "Unknown";
    return badge;
}

function createStatusBadge(status) {
    return createBadge(String(status || "unknown").replace(/_/g, " "), statusBadgeClass(status || "unknown"));
}

function createEmptyDetailState(message) {
    const emptyState = document.createElement("div");
    emptyState.className = "text-muted small";
    emptyState.textContent = message;
    return emptyState;
}

function createDetailMetric(label, value) {
    const column = document.createElement("div");
    column.className = "col-sm-4";
    const labelElement = document.createElement("div");
    labelElement.className = "text-muted";
    labelElement.textContent = label;
    const valueElement = document.createElement("div");
    valueElement.className = "fw-semibold text-break";
    valueElement.textContent = value || "0";
    column.append(labelElement, valueElement);
    return column;
}

function createDetailBlock(label, value) {
    const wrapper = document.createElement("div");
    const labelElement = document.createElement("div");
    labelElement.className = "text-muted small";
    labelElement.textContent = label;
    const valueElement = document.createElement("div");
    valueElement.className = "fw-semibold text-break";
    valueElement.textContent = value || "N/A";
    wrapper.append(labelElement, valueElement);
    return wrapper;
}

function createDetailChip(label, value, className = "bg-light text-dark border") {
    const chip = document.createElement("span");
    chip.className = `badge ${className}`;
    chip.textContent = label ? `${label}: ${formatDetailValue(value)}` : formatDetailValue(value);
    return chip;
}

function createDetailChipGroup(details) {
    const group = document.createElement("div");
    group.className = "d-flex flex-wrap gap-1";
    const entries = flattenDetailEntries(details).slice(0, 12);
    if (!entries.length) {
        group.appendChild(createEmptyDetailState("No structured details recorded."));
        return group;
    }
    entries.forEach((entry) => {
        group.appendChild(createDetailChip(entry.label, entry.value));
    });
    return group;
}

function createArtifactNoteGroup(artifact) {
    const group = document.createElement("div");
    group.className = "d-flex flex-wrap gap-1 mt-2";
    const notes = [
        { label: "Container", value: artifact.container_name },
        { label: "Partition key", value: artifact.partition_key_path },
        { label: "Index", value: artifact.index_name },
        { label: "Partial since", value: artifact.partial_since_epoch },
        { label: "Filter", value: artifact.partial_filter },
        { label: "Warning", value: artifact.warning, className: "bg-warning text-dark" },
    ].filter((note) => isPresent(note.value));

    if (!notes.length) {
        return group;
    }
    notes.forEach((note) => {
        group.appendChild(createDetailChip(note.label, note.value, note.className));
    });
    return group;
}

function flattenDetailEntries(value, prefix = "") {
    const entries = [];
    if (!value || typeof value !== "object") {
        return entries;
    }
    Object.keys(value).forEach((key) => {
        const detailValue = value[key];
        const label = prefix ? `${prefix} ${formatActivityLabel(key)}` : formatActivityLabel(key);
        if (!isPresent(detailValue)) {
            return;
        }
        if (key === "artifacts" && Array.isArray(detailValue)) {
            entries.push({ label, value: `${formatNumber(detailValue.length)} recorded` });
            return;
        }
        if (Array.isArray(detailValue)) {
            entries.push({ label, value: summarizeArrayDetail(detailValue) });
            return;
        }
        if (typeof detailValue === "object") {
            const nestedEntries = flattenDetailEntries(detailValue, label);
            if (nestedEntries.length) {
                entries.push(...nestedEntries);
            }
            return;
        }
        entries.push({ label, value: detailValue });
    });
    return entries;
}

function summarizeArrayDetail(value) {
    if (!Array.isArray(value)) {
        return "";
    }
    if (value.length === 0) {
        return "0 items";
    }
    const primitiveValues = value.filter((item) => item === null || ["string", "number", "boolean"].includes(typeof item));
    if (primitiveValues.length === value.length) {
        return primitiveValues.map(formatDetailValue).slice(0, 4).join(", ");
    }
    return `${formatNumber(value.length)} items`;
}

function formatDetailValue(value) {
    if (typeof value === "boolean") {
        return value ? "Yes" : "No";
    }
    if (typeof value === "number") {
        return formatNumber(value);
    }
    if (value === null || value === undefined || value === "") {
        return "N/A";
    }
    const text = String(value);
    if (text.length > 96) {
        return `${text.slice(0, 60)}...${text.slice(-24)}`;
    }
    return text;
}

function getArtifactTotals(artifacts) {
    const totals = {
        artifactCount: 0,
        bytes: 0,
        recordCount: 0,
        blobCount: 0,
    };
    if (!Array.isArray(artifacts)) {
        return totals;
    }
    artifacts.forEach((artifact) => {
        if (!artifact || typeof artifact !== "object") {
            return;
        }
        totals.artifactCount += 1;
        totals.bytes += Number(artifact.bytes || 0);
        totals.recordCount += Number(artifact.item_count || 0);
        totals.blobCount += Number(artifact.blob_count || 0);
    });
    return totals;
}

function getProgressPercent(progress) {
    if (!progress || typeof progress !== "object") {
        return 0;
    }
    const percent = Number.parseInt(progress.percent_complete, 10);
    if (Number.isNaN(percent)) {
        return 0;
    }
    return Math.max(0, Math.min(100, percent));
}

function isPresent(value) {
    if (value === null || value === undefined) {
        return false;
    }
    if (typeof value === "string") {
        return value.trim() !== "";
    }
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    if (typeof value === "object") {
        return Object.keys(value).length > 0;
    }
    return true;
}

function updateJobDetailAutoRefresh(job) {
    const status = String(job.status || "unknown");
    const jobId = job.id || currentJobDetailId;
    const refreshText = elements.dataManagementJobDetailRefreshState;
    const timestamp = `Last refreshed ${new Date().toLocaleTimeString()}`;
    if (!jobId) {
        stopJobDetailAutoRefresh({ message: timestamp });
        return;
    }
    currentJobDetailId = jobId;

    if (activeJobStatuses.has(status)) {
        refreshListsWhenJobCompletes = true;
        startJobDetailAutoRefresh();
        setText(refreshText, `Live updates on - ${timestamp}`);
        return;
    }

    const hadActiveRefresh = Boolean(jobDetailRefreshTimer);
    stopJobDetailAutoRefresh({ message: `Job is ${formatStatusLabel(status)} - ${timestamp}` });
    if (hadActiveRefresh || refreshListsWhenJobCompletes) {
        refreshListsWhenJobCompletes = false;
        loadDataManagementJobs();
        loadDataManagementBackups();
    }
}

function startJobDetailAutoRefresh() {
    if (jobDetailRefreshTimer || !currentJobDetailId) {
        return;
    }
    jobDetailRefreshTimer = window.setInterval(refreshOpenJobDetail, jobDetailRefreshIntervalMs);
}

async function refreshOpenJobDetail() {
    if (jobDetailRefreshInFlight || !currentJobDetailId) {
        return;
    }
    if (!elements.dataManagementJobDetailModal?.classList.contains("show")) {
        stopJobDetailAutoRefresh({ clearJob: true });
        return;
    }
    jobDetailRefreshInFlight = true;
    try {
        await loadDataManagementJobDetail(currentJobDetailId, { showModal: false, liveRefresh: true });
    } finally {
        jobDetailRefreshInFlight = false;
    }
}

function stopJobDetailAutoRefresh(options = {}) {
    if (jobDetailRefreshTimer) {
        window.clearInterval(jobDetailRefreshTimer);
        jobDetailRefreshTimer = null;
    }
    if (options.clearJob) {
        currentJobDetailId = null;
        refreshListsWhenJobCompletes = false;
    }
    if (options.message) {
        setText(elements.dataManagementJobDetailRefreshState, options.message);
    }
}

function createStatusCell(status) {
    const cell = document.createElement("td");
    cell.appendChild(createStatusBadge(status));
    return cell;
}

function statusBadgeClass(status) {
    if (status === "completed") {
        return "bg-success";
    }
    if (status === "completed_with_warnings") {
        return "bg-warning text-dark";
    }
    if (status === "failed" || status === "canceled") {
        return "bg-danger";
    }
    if (status === "running") {
        return "bg-info text-dark";
    }
    return "bg-secondary";
}

function formatProgress(progress) {
    if (!progress || typeof progress !== "object") {
        return "0%";
    }
    return `${getProgressPercent(progress)}%`;
}

function formatDate(value) {
    if (!value) {
        return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }
    return parsed.toLocaleString();
}

function formatNumber(value) {
    const numericValue = Number(value || 0);
    if (!Number.isFinite(numericValue)) {
        return "0";
    }
    return numericValue.toLocaleString();
}

function formatBytes(value) {
    const numericValue = Number(value || 0);
    if (!Number.isFinite(numericValue) || numericValue <= 0) {
        return "0 B";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    let unitIndex = 0;
    let displayValue = numericValue;
    while (displayValue >= 1024 && unitIndex < units.length - 1) {
        displayValue /= 1024;
        unitIndex += 1;
    }
    const precision = unitIndex === 0 ? 0 : 1;
    return `${displayValue.toFixed(precision)} ${units[unitIndex]}`;
}

function formatBackupType(value) {
    if (value === "full") {
        return "Full";
    }
    if (value === "partial") {
        return "Partial";
    }
    return formatActivityLabel(value || "backup");
}

function formatStatusLabel(value) {
    return formatActivityLabel(value || "unknown");
}

function formatActivityLabel(value) {
    return String(value || "")
        .replace(/[_-]/g, " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatBackupRecordCounts(backup) {
    const parts = [];
    if (Number(backup.record_count || 0) > 0) {
        parts.push(`${formatNumber(backup.record_count)} records`);
    }
    if (Number(backup.blob_count || 0) > 0) {
        parts.push(`${formatNumber(backup.blob_count)} blobs`);
    }
    return parts.length > 0 ? parts.join(" / ") : "0";
}
