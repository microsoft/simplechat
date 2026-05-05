// chat-toast.js

export function showToast(message, variant = "danger") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const id = "toast-" + Date.now();
  const toastEl = document.createElement("div");
  toastEl.id = id;
  toastEl.className = `toast align-items-center text-bg-${variant}`;
  toastEl.setAttribute("role", "alert");
  toastEl.setAttribute("aria-live", "assertive");
  toastEl.setAttribute("aria-atomic", "true");

  const contentEl = document.createElement("div");
  contentEl.className = "d-flex";

  const bodyEl = document.createElement("div");
  bodyEl.className = "toast-body";
  bodyEl.textContent = String(message ?? "");

  const closeButtonEl = document.createElement("button");
  closeButtonEl.type = "button";
  closeButtonEl.className = "btn-close btn-close-white me-2 m-auto";
  closeButtonEl.setAttribute("data-bs-dismiss", "toast");
  closeButtonEl.setAttribute("aria-label", "Close");

  contentEl.appendChild(bodyEl);
  contentEl.appendChild(closeButtonEl);
  toastEl.appendChild(contentEl);
  container.appendChild(toastEl);

  const bsToast = new bootstrap.Toast(toastEl, { delay: 5000 });
  bsToast.show();
}