// admin-chat-content-checks.js
(function () {
    "use strict";

    function initialize() {
        const root = document.getElementById("unchecked-chat-content");
        if (!root) return;
        const body = root.querySelector("tbody");
        const status = document.getElementById("uncheckedChatStatus");
        const refresh = document.getElementById("refreshUncheckedChat");
        const more = document.getElementById("moreUncheckedChat");
        const source = document.getElementById("uncheckedChatSource");
        const checkpoint = document.getElementById("uncheckedChatCheckpoint");
        const scanner = document.getElementById("uncheckedChatScanner");
        const confirm = document.getElementById("confirmChatRecheck");
        const modalElement = document.getElementById("chatCheckConfirmModal");
        let continuation = null;
        let busy = false;
        let pendingItem = null;

        function notify(message, variant = "info") {
            status.textContent = message;
            status.className = `alert alert-${variant}`;
        }

        function setBusy(value) {
            busy = value;
            root.setAttribute("aria-busy", String(value));
            for (const control of [refresh, more, source, checkpoint, scanner]) control.disabled = value;
            confirm.disabled = value;
            for (const button of body.querySelectorAll("button")) {
                button.disabled = value || button.dataset.recheckAvailable === "false";
            }
        }

        async function requestJson(url, options = {}) {
            const response = await fetch(url, {
                credentials: "same-origin",
                cache: "no-store",
                ...options,
                headers: { Accept: "application/json", ...options.headers },
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "The content check request could not complete.");
            return payload;
        }

        function messageRow(text) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = text;
            row.appendChild(cell);
            body.replaceChildren(row);
        }

        async function recheck(item) {
            if (busy) return;
            setBusy(true);
            try {
                const outcome = await requestJson("/api/safety/chat-checks/recheck", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        source: item.source,
                        conversation_id: item.conversation_id,
                        message_id: item.message_id,
                        etag: item.etag,
                    }),
                });
                setBusy(false);
                await load(false);
                if (outcome.removed) {
                    notify("The AI reply was removed from saved chat and its shared copies.", "success");
                } else if (outcome.check?.status === "passed") {
                    notify("The message passed its required checks.", "success");
                } else if (outcome.check?.status === "findings") {
                    notify("The submitted message was flagged for review. Earlier model calls and actions have not been undone.", "warning");
                } else {
                    notify("The check still could not finish. The message remains marked not checked and can be retried.", "warning");
                }
            } catch (error) {
                notify(error instanceof Error ? error.message : "The recheck could not complete.", "danger");
            } finally {
                setBusy(false);
            }
        }

        function renderRow(item) {
            const row = document.createElement("tr");
            const identity = document.createElement("td");
            identity.className = "text-break";
            const messageId = document.createElement("div");
            messageId.textContent = item.message_id;
            const conversationId = document.createElement("small");
            conversationId.className = "text-body-secondary";
            conversationId.textContent = `Conversation: ${item.conversation_id}`;
            identity.append(messageId, conversationId);
            const type = document.createElement("td");
            type.textContent = item.check?.checkpoint === "chat_output" ? "AI reply" : "Submitted message";
            const checks = document.createElement("td");
            checks.textContent = (item.check?.scanners || [])
                .filter((entry) => !entry.complete)
                .map((entry) => `${entry.scanner === "content_safety" ? "Content Safety" : "Content Screening"}: ${entry.error_code || "incomplete"}`)
                .join("; ");
            const attempted = document.createElement("td");
            attempted.textContent = item.check?.attempted_at || "Not recorded";
            const action = document.createElement("td");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-sm btn-outline-primary";
            button.textContent = "Recheck";
            button.dataset.recheckAvailable = String(Boolean(item.etag));
            button.disabled = !item.etag;
            button.addEventListener("click", () => {
                if (busy) return;
                if (!window.bootstrap?.Modal) {
                    notify("The confirmation dialog could not load. Reload before rechecking.", "danger");
                    return;
                }
                pendingItem = item;
                window.bootstrap.Modal.getOrCreateInstance(modalElement).show(button);
            });
            action.appendChild(button);
            row.append(identity, type, checks, attempted, action);
            body.appendChild(row);
        }

        async function load(append) {
            if (busy) return;
            setBusy(true);
            status.classList.add("d-none");
            const params = new URLSearchParams({ source: source.value, page_size: "25" });
            if (checkpoint.value) params.set("checkpoint", checkpoint.value);
            if (scanner.value) params.set("scanner", scanner.value);
            if (append && continuation) params.set("continuation", continuation);
            try {
                const page = await requestJson(`/api/safety/chat-checks?${params}`);
                if (!Array.isArray(page.items)) throw new Error("The unchecked message list was not valid.");
                if (!append) body.replaceChildren();
                for (const item of page.items) renderRow(item);
                continuation = page.continuation;
                more.classList.toggle("d-none", !continuation);
                if (!body.children.length) messageRow("No unchecked messages match these filters.");
            } catch (error) {
                notify(error instanceof Error ? error.message : "The unchecked message list could not load.", "danger");
            } finally {
                setBusy(false);
            }
        }

        refresh.addEventListener("click", () => void load(false));
        confirm.addEventListener("click", () => {
            if (busy || !pendingItem) return;
            const item = pendingItem;
            pendingItem = null;
            window.bootstrap.Modal.getOrCreateInstance(modalElement).hide();
            void recheck(item);
        });
        more.addEventListener("click", () => void load(true));
        for (const control of [source, checkpoint, scanner]) {
            control.addEventListener("change", () => void load(false));
        }
        void load(false);
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
    else initialize();
}());
