// admin_data_management.js

import { showToast } from "../chat/chat-toast.js";

const redactedValue = "***REDACTED***";
const elements = {};

document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    if (!elements.tabPane) {
        return;
    }

    bindEvents();
    loadDataManagementSettings();
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
        "data_management_storage_auth",
        "data_management_blob_endpoint",
        "data_management_container_name",
        "data_management_connection_string",
        "data_management_path_prefix",
        "data_management_encryption_enabled",
        "data-management-key-storage",
        "data-management-key-reference",
        "data-management-generate-key-btn",
        "data_management_target_cosmos_auth",
        "data_management_target_cosmos_endpoint",
        "data_management_target_cosmos_database",
        "data_management_target_cosmos_key",
        "data-management-test-storage-btn",
        "data-management-run-full-backup-btn",
        "data-management-run-partial-backup-btn",
        "data-management-restore-dry-run-btn",
        "data-management-migration-dry-run-btn",
        "data-management-refresh-jobs-btn",
        "data-management-jobs-tbody",
    ];

    ids.forEach((id) => {
        const key = id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()).replace(/_/g, "");
        elements[key] = document.getElementById(id);
    });

    elements.tabPane = elements.dataManagement;
}

function bindEvents() {
    elements.dataManagementSaveSettingsBtn?.addEventListener("click", () => saveDataManagementSettings());
    elements.dataManagementGenerateKeyBtn?.addEventListener("click", generateEncryptionKey);
    elements.dataManagementTestStorageBtn?.addEventListener("click", testBackupStorage);
    elements.dataManagementRunFullBackupBtn?.addEventListener("click", () => queueBackup("full"));
    elements.dataManagementRunPartialBackupBtn?.addEventListener("click", () => queueBackup("partial"));
    elements.dataManagementRestoreDryRunBtn?.addEventListener("click", () => queueOperation("restore", null, { dry_run: true }));
    elements.dataManagementMigrationDryRunBtn?.addEventListener("click", () => queueOperation("migration", null, { dry_run: true }));
    elements.dataManagementRefreshJobsBtn?.addEventListener("click", loadDataManagementJobs);
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

function populateSettings(settings) {
    setChecked(elements.datamanagementenabled, settings.enabled);
    setValue(elements.datamanagementfullfrequency, settings.full_backup_frequency || "weekly");
    setValue(elements.datamanagementscheduledtimeutc, settings.scheduled_time_utc || settings.default_scheduled_time_utc || "03:00");
    setValue(elements.datamanagementretentiondays, settings.retention_days ?? 30);
    setChecked(elements.datamanagementpartialenabled, settings.partial_backups_enabled !== false);
    setChecked(elements.datamanagementlowimpactmode, settings.low_impact_mode !== false);
    setChecked(elements.datamanagementincludecosmos, settings.include_cosmos !== false);
    setChecked(elements.datamanagementincludeaisearch, settings.include_ai_search !== false);
    setChecked(elements.datamanagementincludesourceblobs, settings.include_source_blobs);
    setValue(elements.datamanagementstorageauth, settings.backup_storage_authentication_type || "managed_identity");
    setValue(elements.datamanagementblobendpoint, settings.backup_storage_blob_endpoint || "");
    setValue(elements.datamanagementcontainername, settings.backup_storage_container_name || "simplechat-backups");
    setValue(elements.datamanagementconnectionstring, settings.backup_storage_connection_string || "");
    setValue(elements.datamanagementpathprefix, settings.backup_storage_path_prefix || "simplechat-backups");
    setChecked(elements.datamanagementencryptionenabled, settings.encryption_enabled !== false);
    setValue(elements.datamanagementtargetcosmosauth, settings.target_cosmos_authentication_type || "managed_identity");
    setValue(elements.datamanagementtargetcosmosendpoint, settings.target_cosmos_endpoint || "");
    setValue(elements.datamanagementtargetcosmosdatabase, settings.target_cosmos_database_name || "SimpleChat");
    setValue(elements.datamanagementtargetcosmoskey, settings.target_cosmos_key || "");

    if (elements.dataManagementKeyStorage) {
        elements.dataManagementKeyStorage.textContent = formatKeyStorage(settings.encryption_key_storage);
    }
    if (elements.dataManagementKeyReference) {
        elements.dataManagementKeyReference.textContent = settings.encryption_key_reference ? redactedValue : "Not configured";
    }
}

function collectSettings() {
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
        backup_storage_authentication_type: getValue(elements.datamanagementstorageauth) || "managed_identity",
        backup_storage_blob_endpoint: getValue(elements.datamanagementblobendpoint),
        backup_storage_container_name: getValue(elements.datamanagementcontainername) || "simplechat-backups",
        backup_storage_connection_string: getValue(elements.datamanagementconnectionstring),
        backup_storage_path_prefix: getValue(elements.datamanagementpathprefix) || "simplechat-backups",
        encryption_enabled: Boolean(elements.datamanagementencryptionenabled?.checked),
        target_cosmos_authentication_type: getValue(elements.datamanagementtargetcosmosauth) || "managed_identity",
        target_cosmos_endpoint: getValue(elements.datamanagementtargetcosmosendpoint),
        target_cosmos_database_name: getValue(elements.datamanagementtargetcosmosdatabase) || "SimpleChat",
        target_cosmos_key: getValue(elements.datamanagementtargetcosmoskey),
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

async function saveDataManagementSettings(throwOnError = false) {
    setBusy(elements.dataManagementSaveSettingsBtn, true, "Saving...");
    try {
        const data = await requestJson("/api/admin/data-management/settings", {
            method: "PUT",
            body: JSON.stringify(collectSettings()),
        });
        populateSettings(data.settings || {});
        setStatus("Data Management settings saved.", "success");
        showToast("Data Management settings saved.", "success");
    } catch (error) {
        setStatus(error.message || "Data Management settings could not be saved.", "danger");
        showToast("Data Management settings could not be saved.", "danger");
        if (throwOnError) {
            throw error;
        }
    } finally {
        setBusy(elements.dataManagementSaveSettingsBtn, false);
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
        showToast("Backup storage connection test failed.", "danger");
    } finally {
        setBusy(elements.dataManagementTestStorageBtn, false);
    }
}

function queueBackup(backupType) {
    return queueOperation("backup", backupType, {
        include_cosmos: Boolean(elements.datamanagementincludecosmos?.checked),
        include_ai_search: Boolean(elements.datamanagementincludeaisearch?.checked),
        include_source_blobs: Boolean(elements.datamanagementincludesourceblobs?.checked),
    });
}

async function queueOperation(operation, backupType = null, options = {}) {
    const button = buttonForOperation(operation, backupType);
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
    } catch (error) {
        setStatus(error.message || "Data Management job could not be queued.", "danger");
        showToast("Data Management job could not be queued.", "danger");
    } finally {
        setBusy(button, false);
    }
}

function buttonForOperation(operation, backupType) {
    if (operation === "backup" && backupType === "full") {
        return elements.dataManagementRunFullBackupBtn;
    }
    if (operation === "backup" && backupType === "partial") {
        return elements.dataManagementRunPartialBackupBtn;
    }
    if (operation === "restore") {
        return elements.dataManagementRestoreDryRunBtn;
    }
    if (operation === "migration") {
        return elements.dataManagementMigrationDryRunBtn;
    }
    return null;
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
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = variant === "danger" ? "text-danger" : "text-muted";
    cell.textContent = message;
    row.appendChild(cell);
    tbody.replaceChildren(row);
}

function createJobRow(job) {
    const row = document.createElement("tr");
    row.appendChild(createCell(formatDate(job.created_at)));
    row.appendChild(createCell(formatOperation(job.operation || "", job.backup_type || "")));
    row.appendChild(createStatusCell(job.status || "unknown"));
    row.appendChild(createCell(formatProgress(job.progress)));
    row.appendChild(createCell(job.last_message || job.last_error || ""));
    return row;
}

function createCell(text) {
    const cell = document.createElement("td");
    cell.textContent = text ?? "";
    return cell;
}

function createStatusCell(status) {
    const cell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${statusBadgeClass(status)}`;
    badge.textContent = status.replace(/_/g, " ");
    cell.appendChild(badge);
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
    const percent = Number.parseInt(progress.percent_complete, 10);
    if (Number.isNaN(percent)) {
        return "0%";
    }
    return `${percent}%`;
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