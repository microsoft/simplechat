// main.js
/**
 * Main JavaScript for the Simple Chat documentation site.
 */

(function() {
    "use strict";

    let cachedSearchIndex = null;
    let searchIndexPromise = null;

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

    function normalizeSearchIndex(items) {
        if (!Array.isArray(items)) {
            return [];
        }

        return items.filter(function(item) {
            return item && item.title && item.url;
        });
    }

    function getNavigationSearchIndex() {
        return Array.from(document.querySelectorAll(".docs-sidebar-link, .docs-topbar-link")).map(function(link) {
            return {
                title: link.textContent.trim(),
                description: "",
                keywords: "",
                section: "Navigation",
                url: link.href
            };
        });
    }

    function getEmbeddedSearchIndex() {
        const searchDataElement = document.getElementById("docs-search-data");
        if (!searchDataElement) {
            return [];
        }

        try {
            return normalizeSearchIndex(JSON.parse(searchDataElement.textContent));
        } catch (error) {
            return [];
        }
    }

    function getSearchIndex() {
        if (cachedSearchIndex) {
            return Promise.resolve(cachedSearchIndex);
        }

        const embeddedIndex = getEmbeddedSearchIndex();
        if (embeddedIndex.length > 0) {
            cachedSearchIndex = embeddedIndex;
            return Promise.resolve(cachedSearchIndex);
        }

        if (searchIndexPromise) {
            return searchIndexPromise;
        }

        const searchIndexUrl = window.siteSettings?.searchIndexUrl;
        if (!searchIndexUrl || typeof fetch !== "function") {
            cachedSearchIndex = getNavigationSearchIndex();
            return Promise.resolve(cachedSearchIndex);
        }

        searchIndexPromise = fetch(searchIndexUrl, { headers: { Accept: "application/json" } })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error("Search index request failed");
                }
                return response.json();
            })
            .then(function(items) {
                cachedSearchIndex = normalizeSearchIndex(items);
                return cachedSearchIndex;
            })
            .catch(function() {
                cachedSearchIndex = getNavigationSearchIndex();
                return cachedSearchIndex;
            });

        return searchIndexPromise;
    }

    function createSearchResult(item) {
        const result = document.createElement("a");
        result.className = "docs-search-result";
        result.href = item.url;
        result.setAttribute("role", "option");

        const title = document.createElement("span");
        title.className = "docs-search-result-title";
        title.textContent = item.title;

        const meta = document.createElement("span");
        meta.className = "docs-search-result-meta";
        meta.textContent = item.section || "Docs";

        const description = document.createElement("span");
        description.className = "docs-search-result-description";
        description.textContent = item.description || "Open this documentation page.";

        result.appendChild(title);
        result.appendChild(meta);
        result.appendChild(description);
        return result;
    }

    function renderSearchResults(searchInput, resultsContainer) {
        const query = searchInput.value.trim().toLowerCase();
        resultsContainer.replaceChildren();

        if (query.length < 2) {
            resultsContainer.classList.add("d-none");
            return;
        }

        getSearchIndex().then(function(searchIndex) {
            if (searchInput.value.trim().toLowerCase() !== query) {
                return;
            }

            resultsContainer.replaceChildren();
            const matches = searchIndex.map(function(item) {
                const title = item.title.toLowerCase();
                const description = (item.description || "").toLowerCase();
                const keywords = (item.keywords || "").toLowerCase();
                const section = (item.section || "").toLowerCase();
                const searchableText = `${title} ${description} ${keywords} ${section}`;
                let score = 10;

                if (title === query) {
                    score = 0;
                } else if (title.startsWith(query)) {
                    score = 1;
                } else if (title.includes(query)) {
                    score = 2;
                } else if (keywords.includes(query)) {
                    score = 3;
                } else if (section.includes(query)) {
                    score = 4;
                } else if (description.includes(query)) {
                    score = 5;
                }

                return { item, score, searchableText };
            }).filter(function(result) {
                return result.searchableText.includes(query);
            }).sort(function(firstResult, secondResult) {
                if (firstResult.score !== secondResult.score) {
                    return firstResult.score - secondResult.score;
                }
                return firstResult.item.title.localeCompare(secondResult.item.title);
            }).slice(0, 8).map(function(result) {
                return result.item;
            });

            if (matches.length === 0) {
                const emptyState = document.createElement("div");
                emptyState.className = "docs-search-empty";
                emptyState.textContent = "No matching docs found.";
                resultsContainer.appendChild(emptyState);
            } else {
                matches.forEach(function(item) {
                    resultsContainer.appendChild(createSearchResult(item));
                });
            }

            resultsContainer.classList.remove("d-none");
        });
    }

    function initSearch() {
        const searchInputs = document.querySelectorAll("[data-docs-search='true']");

        searchInputs.forEach(function(searchInput) {
            const searchRoot = searchInput.closest(".docs-search");
            const resultsContainer = searchRoot ? searchRoot.querySelector("[data-docs-search-results='true']") : null;

            if (!resultsContainer) {
                return;
            }

            let searchTimeout;

            searchInput.addEventListener("input", function() {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(function() {
                    renderSearchResults(searchInput, resultsContainer);
                }, 120);
            });

            searchInput.addEventListener("keydown", function(event) {
                if (event.key === "Escape") {
                    searchInput.value = "";
                    resultsContainer.classList.add("d-none");
                }
            });
        });

        document.addEventListener("click", function(event) {
            if (!event.target.closest(".docs-search")) {
                document.querySelectorAll("[data-docs-search-results='true']").forEach(function(resultsContainer) {
                    resultsContainer.classList.add("d-none");
                });
            }
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
        initSearch();
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
        initSearch,
        buildOnThisPage
    };
})();