// media.js
/**
 * Lightbox for documentation screenshots.
 *
 * Screenshots rendered by _includes/media.html are wrapped in a button with
 * data-docs-media-zoom. Clicking one opens a full-viewport overlay so readers
 * can inspect UI detail without leaving the page.
 *
 * Implemented with plain DOM APIs so the docs site carries no third-party
 * lightbox dependency.
 */

(function() {
    "use strict";

    let overlay = null;
    let overlayImage = null;
    let lastFocusedElement = null;

    function buildOverlay() {
        if (overlay) {
            return overlay;
        }

        overlay = document.createElement("div");
        overlay.className = "docs-media-lightbox d-none";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");
        overlay.setAttribute("aria-label", "Enlarged screenshot");

        overlayImage = document.createElement("img");
        overlayImage.alt = "";

        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "docs-media-lightbox-close";
        closeButton.setAttribute("aria-label", "Close enlarged screenshot");

        const closeIcon = document.createElement("i");
        closeIcon.className = "bi bi-x-lg";
        closeIcon.setAttribute("aria-hidden", "true");
        closeButton.appendChild(closeIcon);

        closeButton.addEventListener("click", closeOverlay);

        overlay.addEventListener("click", function(event) {
            if (event.target === overlay) {
                closeOverlay();
            }
        });

        overlay.appendChild(overlayImage);
        overlay.appendChild(closeButton);
        document.body.appendChild(overlay);

        return overlay;
    }

    function isOpen() {
        return overlay !== null && !overlay.classList.contains("d-none");
    }

    function openOverlay(source, altText) {
        lastFocusedElement = document.activeElement;

        buildOverlay();
        overlayImage.src = source;
        overlayImage.alt = altText || "";
        overlay.classList.remove("d-none");
        document.body.classList.add("docs-media-lightbox-open");

        const closeButton = overlay.querySelector(".docs-media-lightbox-close");
        if (closeButton) {
            closeButton.focus();
        }
    }

    function closeOverlay() {
        if (!isOpen()) {
            return;
        }

        overlay.classList.add("d-none");
        overlayImage.src = "";
        document.body.classList.remove("docs-media-lightbox-open");

        if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
            lastFocusedElement.focus();
        }

        lastFocusedElement = null;
    }

    function trapFocus(event) {
        if (!isOpen() || event.key !== "Tab") {
            return;
        }

        // The overlay only contains the close button, so keep focus pinned to it.
        const closeButton = overlay.querySelector(".docs-media-lightbox-close");
        if (closeButton) {
            event.preventDefault();
            closeButton.focus();
        }
    }

    function initMediaZoom() {
        const triggers = document.querySelectorAll("[data-docs-media-zoom='true']");

        triggers.forEach(function(trigger) {
            trigger.addEventListener("click", function() {
                const source = trigger.getAttribute("data-docs-media-src");
                if (!source) {
                    return;
                }
                openOverlay(source, trigger.getAttribute("data-docs-media-alt"));
            });
        });

        document.addEventListener("keydown", function(event) {
            if (event.key === "Escape") {
                closeOverlay();
                return;
            }
            trapFocus(event);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initMediaZoom);
    } else {
        initMediaZoom();
    }

    window.SimpleChat = window.SimpleChat || {};
    window.SimpleChat.Media = {
        openOverlay,
        closeOverlay
    };
})();
