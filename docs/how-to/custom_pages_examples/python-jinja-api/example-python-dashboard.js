// example-python-dashboard.js
const pythonExampleRoot = document.querySelector("[data-python-example]");

if (pythonExampleRoot) {
    const refreshButton = pythonExampleRoot.querySelector("[data-python-refresh-button]");
    const statusValue = pythonExampleRoot.querySelector("[data-python-status]");
    const userValue = pythonExampleRoot.querySelector("[data-python-user]");
    const serverTimeValue = pythonExampleRoot.querySelector("[data-python-server-time]");
    const requestCountValue = pythonExampleRoot.querySelector("[data-python-request-count]");
    const apiStatusUrl = pythonExampleRoot.dataset.apiStatusUrl || "";

    async function refreshStatus() {
        if (!apiStatusUrl) {
            if (statusValue) {
                statusValue.textContent = "Missing API URL";
            }
            return;
        }

        if (statusValue) {
            statusValue.textContent = "Loading";
        }

        try {
            const response = await fetch(apiStatusUrl, { credentials: "same-origin" });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || "Backend refresh failed.");
            }

            if (userValue) {
                userValue.textContent = payload.user_name || "Signed-in user";
            }
            if (serverTimeValue) {
                serverTimeValue.textContent = payload.server_time || "Unknown";
            }
            if (requestCountValue) {
                requestCountValue.textContent = String(payload.request_count || 0);
            }
            if (statusValue) {
                statusValue.textContent = "Loaded";
            }
        } catch (error) {
            if (statusValue) {
                statusValue.textContent = error.message;
            }
        }
    }

    if (refreshButton) {
        refreshButton.addEventListener("click", refreshStatus);
    }

    refreshStatus();
}