// main.js
/**
 * Main JavaScript for the Simple Chat documentation site.
 */

(function() {
    "use strict";

    function createIcon(iconClass) {
        const icon = document.createElement("i");
        icon.className = iconClass;
        icon.setAttribute("aria-hidden", "true");
        return icon;
    }

    function showToast(message, type = "info", duration = 5000) {
        const toastContainer = document.getElementById("toast-container");
        if (!toastContainer || !window.bootstrap) {
            return;
        }

        const toast = document.createElement("div");
        toast.className = `toast align-items-center text-bg-${type} border-0`;
        toast.setAttribute("role", "alert");
        toast.setAttribute("aria-live", "assertive");
        toast.setAttribute("aria-atomic", "true");

        const row = document.createElement("div");
        row.className = "d-flex";

        const body = document.createElement("div");
        body.className = "toast-body";
        body.textContent = message;

        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "btn-close btn-close-white me-2 m-auto";
        closeButton.setAttribute("data-bs-dismiss", "toast");
        closeButton.setAttribute("aria-label", "Close");

        row.appendChild(body);
        row.appendChild(closeButton);
        toast.appendChild(row);
        toastContainer.appendChild(toast);

        const bootstrapToast = new bootstrap.Toast(toast, { delay: duration });
        toast.addEventListener("hidden.bs.toast", function() {
            toast.remove();
        });
        bootstrapToast.show();
    }

    function fallbackCopy(text, successMessage) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.className = "docs-visually-hidden-copy-field";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        try {
            document.execCommand("copy");
            showToast(successMessage, "success", 2000);
        } catch (error) {
            showToast("Failed to copy to clipboard", "danger", 3000);
        }

        textArea.remove();
    }

    function copyToClipboard(text, successMessage = "Copied to clipboard") {
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(function() {
                showToast(successMessage, "success", 2000);
            }).catch(function() {
                fallbackCopy(text, successMessage);
            });
        } else {
            fallbackCopy(text, successMessage);
        }
    }

    function setButtonIcon(button, iconClass) {
        button.replaceChildren(createIcon(iconClass));
    }

    function addCopyButtonsToCodeBlocks() {
        const codeBlocks = document.querySelectorAll("pre[class*='language-'], .docs-prose pre");

        codeBlocks.forEach(function(codeBlock) {
            if (codeBlock.querySelector(".copy-button")) {
                return;
            }

            const code = codeBlock.querySelector("code");
            if (!code) {
                return;
            }

            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-sm btn-outline-secondary copy-button docs-copy-button";
            button.title = "Copy code";
            button.setAttribute("aria-label", "Copy code");
            setButtonIcon(button, "bi bi-clipboard");

            codeBlock.classList.add("docs-code-block");
            button.addEventListener("click", function() {
                copyToClipboard(code.textContent, "Code copied");
                setButtonIcon(button, "bi bi-clipboard-check");
                setTimeout(function() {
                    setButtonIcon(button, "bi bi-clipboard");
                }, 2000);
            });

            codeBlock.appendChild(button);
        });
    }

    function initTooltips() {
        if (!window.bootstrap) {
            return;
        }

        const tooltipTriggerList = Array.from(document.querySelectorAll("[data-bs-toggle='tooltip']"));
        tooltipTriggerList.forEach(function(tooltipTriggerElement) {
            new bootstrap.Tooltip(tooltipTriggerElement);
        });
    }

    function initPopovers() {
        if (!window.bootstrap) {
            return;
        }

        const popoverTriggerList = Array.from(document.querySelectorAll("[data-bs-toggle='popover']"));
        popoverTriggerList.forEach(function(popoverTriggerElement) {
            new bootstrap.Popover(popoverTriggerElement);
        });
    }

    function initSmoothScrolling() {
        document.querySelectorAll("a[href^='#']").forEach(function(anchor) {
            anchor.addEventListener("click", function(event) {
                const targetId = anchor.getAttribute("href");
                if (!targetId || targetId === "#") {
                    return;
                }

                const targetElement = document.querySelector(targetId);
                if (!targetElement) {
                    return;
                }

                event.preventDefault();
                const headerHeight = document.querySelector(".docs-topbar")?.offsetHeight || 0;
                const targetPosition = targetElement.offsetTop - headerHeight - 20;

                window.scrollTo({
                    top: targetPosition,
                    behavior: "smooth"
                });

                history.pushState(null, "", targetId);
            });
        });
    }

    function addHeadingAnchors() {
        const headings = document.querySelectorAll(".docs-prose h2[id], .docs-prose h3[id], .docs-prose h4[id]");

        headings.forEach(function(heading) {
            if (heading.querySelector(".heading-anchor")) {
                return;
            }

            const anchor = document.createElement("a");
            anchor.href = `#${heading.id}`;
            anchor.className = "heading-anchor";
            anchor.title = "Link to this heading";
            anchor.setAttribute("aria-label", "Copy link to this heading");
            anchor.appendChild(createIcon("bi bi-link-45deg"));

            anchor.addEventListener("click", function(event) {
                event.preventDefault();
                const url = `${window.location.origin}${window.location.pathname}${anchor.getAttribute("href")}`;
                copyToClipboard(url, "Link copied");
            });

            heading.appendChild(anchor);
        });
    }

    function buildOnThisPage() {
        const tocContainers = document.querySelectorAll("[data-docs-toc='true']");
        if (tocContainers.length === 0) {
            return;
        }

        const headings = Array.from(document.querySelectorAll(".docs-prose h2[id], .docs-prose h3[id]")).filter(function(heading) {
            return heading.textContent.trim().length > 0;
        });

        tocContainers.forEach(function(tocContainer) {
            const linksContainer = tocContainer.querySelector("[data-docs-toc-links='true']");
            if (!linksContainer) {
                return;
            }

            linksContainer.replaceChildren();

            if (headings.length === 0) {
                tocContainer.classList.add("d-none");
                return;
            }

            headings.slice(0, 12).forEach(function(heading) {
                const link = document.createElement("a");
                link.href = `#${heading.id}`;
                link.textContent = heading.textContent.replace("#", "").trim();
                if (heading.tagName.toLowerCase() === "h3") {
                    link.classList.add("is-subheading");
                }
                linksContainer.appendChild(link);
            });

            tocContainer.classList.remove("d-none");
        });
    }

    function init() {
        initTooltips();
        initPopovers();
        initSmoothScrolling();
        addHeadingAnchors();
        addCopyButtonsToCodeBlocks();
        buildOnThisPage();

        document.addEventListener("themeChanged", function() {
            setTimeout(function() {
                if (window.Prism) {
                    Prism.highlightAll();
                }
                addCopyButtonsToCodeBlocks();
            }, 100);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.SimpleChat = window.SimpleChat || {};
    window.SimpleChat.Utils = {
        showToast,
        copyToClipboard,
        addCopyButtonsToCodeBlocks,
        initTooltips,
        initPopovers,
        buildOnThisPage
    };
})();