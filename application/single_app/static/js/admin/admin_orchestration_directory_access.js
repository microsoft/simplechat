// admin_orchestration_directory_access.js
// Warns on the classic Admin Settings page when Chat Orchestration cannot read Microsoft Entra ID.
//
// Before a plan uses web search or another external source, Chat Orchestration rereads the
// user's app roles from Microsoft Graph with the application's own identity. That read needs the
// Microsoft Graph Directory.Read.All application permission with administrator consent. The
// server runs the same read for the signed-in administrator and this module shows the matching
// guidance. Every value from the server is written with textContent.

const CHECK_URL = "/api/admin/settings/orchestration/directory-access-check";
const ALERT_ID = "chat-orchestration-directory-access-alert";
const WEB_SEARCH_ALERT_ID = "web-search-directory-access-alert";
const GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const GRAPH_RESOURCE_APP_ID = "00000003-0000-0000-c000-000000000000";
const GRAPH_DIRECTORY_PERMISSION_ID = "7ab1d382-f21e-4acd-a863-ba3e13f7da61";
const CLIENT_ID_PLACEHOLDER = "<application-client-id>";
const DEFAULT_SOURCES = "web search or another external source";

export const PROBLEM_STATES = Object.freeze(["permission_missing", "sign_in_failed", "unverified"]);

// Maps, so a server value such as "constructor" never resolves to an inherited property.
const SOURCE_NAMES = new Map([
    ["web_search", "web search"],
    ["url_fetch", "linked pages"],
    ["deep_research", "deep research"],
    ["agent_invoke", "agents"],
    ["action_invoke", "actions"],
]);

const WEB_SEARCH_SUMMARIES = new Map([
    ["permission_missing", "Chat Orchestration can't verify that users may use web search, because this app registration doesn't have the Microsoft Graph Directory.Read.All permission."],
    ["sign_in_failed", "Chat Orchestration can't verify that users may use web search, because Microsoft Entra ID refused SimpleChat's application sign-in."],
]);

function guidOr(value, fallback) {
    return typeof value === "string" && GUID_PATTERN.test(value) ? value : fallback;
}

/** Azure CLI commands that add the permission and grant administrator consent. */
export function directoryAccessCommands(report) {
    const clientId = guidOr(report?.application_client_id, CLIENT_ID_PLACEHOLDER);
    const resourceId = guidOr(report?.graph_resource_app_id, GRAPH_RESOURCE_APP_ID);
    const permissionId = guidOr(report?.graph_permission_id, GRAPH_DIRECTORY_PERMISSION_ID);
    return [
        `az ad app permission add --id ${clientId} --api ${resourceId} --api-permissions ${permissionId}=Role`,
        `az ad app permission admin-consent --id ${clientId}`,
    ].join("\n");
}

/** The enabled sources that depend on the directory read, as a readable phrase. */
export function directoryAccessSources(capabilities) {
    const names = (Array.isArray(capabilities) ? capabilities : [])
        .map((capability) => SOURCE_NAMES.get(capability?.id))
        .filter(Boolean);
    if (names.length === 0) {
        return DEFAULT_SOURCES;
    }
    if (names.length === 1) {
        return names[0];
    }
    return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}

function formatCheckedAt(value) {
    const checkedAt = typeof value === "string" ? new Date(value) : null;
    if (!checkedAt || Number.isNaN(checkedAt.getTime())) {
        return "";
    }
    return `Checked ${checkedAt.toLocaleString()}.`;
}

function detailText(report) {
    const parts = [];
    if (report.status === "unverified" && typeof report.reason === "string" && report.reason) {
        parts.push(`Reason: ${report.reason}.`);
    }
    const checked = formatCheckedAt(report.checked_at);
    if (checked) {
        parts.push(checked);
    }
    return parts.join(" ");
}

/** Show the guidance that matches a check result, or hide it when nothing is wrong. */
export function renderDirectoryAccess(report, root = document) {
    const alert = root.getElementById(ALERT_ID);
    const webSearchAlert = root.getElementById(WEB_SEARCH_ALERT_ID);
    const status = typeof report?.status === "string" ? report.status : "";
    const showAlert = PROBLEM_STATES.includes(status);

    if (alert) {
        alert.querySelectorAll("[data-directory-access-state]").forEach((block) => {
            block.classList.toggle("d-none", block.getAttribute("data-directory-access-state") !== status);
        });
        alert.querySelectorAll("[data-directory-access-capabilities]").forEach((element) => {
            element.textContent = directoryAccessSources(report?.capabilities);
        });
        alert.querySelectorAll("[data-directory-access-commands]").forEach((element) => {
            element.textContent = directoryAccessCommands(report);
        });
        const detail = alert.querySelector("[data-directory-access-detail]");
        if (detail) {
            detail.textContent = showAlert ? detailText(report) : "";
        }
        alert.classList.toggle("d-none", !showAlert);
    }

    if (webSearchAlert) {
        const summary = WEB_SEARCH_SUMMARIES.get(status);
        const showWebSearch = Boolean(summary) && report?.web_search_enabled === true;
        const summaryElement = webSearchAlert.querySelector("[data-directory-access-summary]");
        if (summaryElement && summary) {
            summaryElement.textContent = summary;
        }
        webSearchAlert.classList.toggle("d-none", !showWebSearch);
    }
}

async function requestDirectoryAccessCheck(refresh) {
    const response = await fetch(CHECK_URL, {
        method: "POST",
        headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        credentials: "same-origin",
        body: JSON.stringify({ refresh }),
    });
    const payload = await response.json();
    if (!response.ok || payload?.success !== true) {
        throw new Error(payload?.error || "The directory access check could not be completed.");
    }
    return payload;
}

/** Run the check and update the page. A failed check leaves the page as it was. */
export async function checkDirectoryAccess({ refresh = false } = {}) {
    const alert = document.getElementById(ALERT_ID);
    const button = alert?.querySelector("[data-directory-access-recheck]");
    const detail = alert?.querySelector("[data-directory-access-detail]");
    if (button) {
        button.disabled = true;
    }
    if (refresh && detail) {
        detail.textContent = "Checking...";
    }
    try {
        const report = await requestDirectoryAccessCheck(refresh);
        renderDirectoryAccess(report);
        return report;
    } catch (error) {
        console.warn("Chat Orchestration directory access check failed.", error);
        if (refresh && detail) {
            detail.textContent = "The check could not be completed. Try again.";
        }
        return null;
    } finally {
        if (button) {
            button.disabled = false;
        }
    }
}

export function initDirectoryAccessCheck() {
    const alert = document.getElementById(ALERT_ID);
    if (!alert) {
        return;
    }
    alert.querySelector("[data-directory-access-recheck]")?.addEventListener("click", () => {
        checkDirectoryAccess({ refresh: true });
    });
    checkDirectoryAccess();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDirectoryAccessCheck);
} else {
    initDirectoryAccessCheck();
}
