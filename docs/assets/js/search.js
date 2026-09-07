// search.js
/**
 * Full-text documentation search.
 *
 * Replaces the previous title-only substring match. The index at
 * /search-index.json carries page body text, so queries match what readers
 * actually read rather than only page titles.
 *
 * Provides three surfaces backed by one index:
 *   - a typeahead dropdown in the desktop top bar
 *   - a full-screen search sheet on small viewports
 *   - a full results page at /search/ with section filters
 *
 * Lunr is vendored locally at assets/js/vendor/lunr-2.3.9/ because the repo
 * forbids CDN-hosted browser runtime code.
 */

(function() {
    "use strict";

    const MAX_DROPDOWN_RESULTS = 8;
    const MAX_PAGE_RESULTS = 50;
    const EXCERPT_RADIUS = 90;

    let documents = [];
    let documentsByUrl = {};
    let lunrIndex = null;
    let loadPromise = null;
    let activeSectionFilter = "";

    function getIndexUrl() {
        const configured = window.siteSettings && window.siteSettings.searchIndexUrl;
        return configured || "/search-index.json";
    }

    function buildLunrIndex(entries) {
        if (!window.lunr) {
            return null;
        }

        return window.lunr(function() {
            this.ref("url");
            this.field("title", { boost: 12 });
            this.field("description", { boost: 5 });
            this.field("section", { boost: 3 });
            this.field("body");

            entries.forEach(function(entry) {
                this.add(entry);
            }, this);
        });
    }

    function loadIndex() {
        if (loadPromise) {
            return loadPromise;
        }

        loadPromise = fetch(getIndexUrl(), { headers: { Accept: "application/json" } })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error("Search index request failed");
                }
                return response.json();
            })
            .then(function(entries) {
                documents = Array.isArray(entries) ? entries.filter(function(entry) {
                    return entry && entry.title && entry.url;
                }) : [];

                documentsByUrl = {};
                documents.forEach(function(entry) {
                    documentsByUrl[entry.url] = entry;
                });

                lunrIndex = buildLunrIndex(documents);
                return documents;
            })
            .catch(function() {
                documents = [];
                documentsByUrl = {};
                lunrIndex = null;
                return documents;
            });

        return loadPromise;
    }

    /**
     * Strip characters that are operators in Lunr query syntax so a user typing
     * something like "c++" or "a:b" does not throw a query parse error.
     */
    function sanitizeTerm(term) {
        return term.replace(/[~^:*+\-()]/g, "");
    }

    function substringSearch(query) {
        const needle = query.toLowerCase();

        return documents.filter(function(entry) {
            const haystack = `${entry.title} ${entry.description} ${entry.section} ${entry.body}`.toLowerCase();
            return haystack.indexOf(needle) !== -1;
        }).map(function(entry) {
            const title = entry.title.toLowerCase();
            let score = 1;
            if (title === needle) {
                score = 1000;
            } else if (title.indexOf(needle) === 0) {
                score = 500;
            } else if (title.indexOf(needle) !== -1) {
                score = 250;
            }
            return { ref: entry.url, score: score };
        }).sort(function(a, b) {
            return b.score - a.score;
        });
    }

    function runQuery(rawQuery) {
        const query = rawQuery.trim();
        if (query.length < 2) {
            return [];
        }

        if (!lunrIndex) {
            return substringSearch(query);
        }

        const terms = query.split(/\s+/).map(sanitizeTerm).filter(function(term) {
            return term.length > 0;
        });

        if (terms.length === 0) {
            return substringSearch(query);
        }

        // Match the exact term strongly, and also allow prefix matches so results
        // appear while the reader is still typing.
        const lunrQuery = terms.map(function(term) {
            return `${term}^3 ${term}*`;
        }).join(" ");

        let results = [];
        try {
            results = lunrIndex.search(lunrQuery);
        } catch (error) {
            results = [];
        }

        if (results.length === 0) {
            results = substringSearch(query);
        }

        return results;
    }

    /**
     * Build a short excerpt around the first match and highlight matched terms.
     * Uses DOM nodes rather than HTML strings so page content can never be
     * injected as markup.
     */
    function buildExcerpt(entry, query) {
        const source = entry.body || entry.description || "";
        const container = document.createElement("span");
        container.className = "docs-search-result-description";

        if (!source) {
            container.textContent = "Open this documentation page.";
            return container;
        }

        const lowerSource = source.toLowerCase();
        const firstTerm = query.trim().split(/\s+/)[0].toLowerCase();
        let matchIndex = firstTerm ? lowerSource.indexOf(firstTerm) : -1;

        if (matchIndex === -1) {
            matchIndex = 0;
        }

        const start = Math.max(0, matchIndex - EXCERPT_RADIUS);
        const end = Math.min(source.length, matchIndex + EXCERPT_RADIUS * 2);
        const snippet = source.slice(start, end);

        if (start > 0) {
            container.appendChild(document.createTextNode("\u2026"));
        }

        const terms = query.trim().split(/\s+/).map(function(term) {
            return term.toLowerCase();
        }).filter(function(term) {
            return term.length > 1;
        });

        let cursor = 0;
        const lowerSnippet = snippet.toLowerCase();

        while (cursor < snippet.length) {
            let nextIndex = -1;
            let nextTerm = "";

            terms.forEach(function(term) {
                const found = lowerSnippet.indexOf(term, cursor);
                if (found !== -1 && (nextIndex === -1 || found < nextIndex)) {
                    nextIndex = found;
                    nextTerm = term;
                }
            });

            if (nextIndex === -1) {
                container.appendChild(document.createTextNode(snippet.slice(cursor)));
                break;
            }

            container.appendChild(document.createTextNode(snippet.slice(cursor, nextIndex)));

            const mark = document.createElement("mark");
            mark.textContent = snippet.slice(nextIndex, nextIndex + nextTerm.length);
            container.appendChild(mark);

            cursor = nextIndex + nextTerm.length;
        }

        if (end < source.length) {
            container.appendChild(document.createTextNode("\u2026"));
        }

        return container;
    }

    function createResultElement(entry, query) {
        const result = document.createElement("a");
        result.className = "docs-search-result";
        result.href = entry.url;
        result.setAttribute("role", "option");

        const title = document.createElement("span");
        title.className = "docs-search-result-title";
        title.textContent = entry.title;

        const meta = document.createElement("span");
        meta.className = "docs-search-result-meta";
        meta.textContent = entry.section || "Docs";

        result.appendChild(title);
        result.appendChild(meta);
        result.appendChild(buildExcerpt(entry, query));
        return result;
    }

    function resolveEntries(results) {
        return results.map(function(result) {
            return documentsByUrl[result.ref];
        }).filter(Boolean);
    }

    // -----------------------------------------------------------------------
    // Typeahead (top bar and mobile sheet)
    // -----------------------------------------------------------------------

    function renderDropdown(input, resultsContainer) {
        const query = input.value.trim();
        resultsContainer.replaceChildren();

        if (query.length < 2) {
            resultsContainer.classList.add("d-none");
            return;
        }

        loadIndex().then(function() {
            if (input.value.trim() !== query) {
                return;
            }

            resultsContainer.replaceChildren();
            const entries = resolveEntries(runQuery(query)).slice(0, MAX_DROPDOWN_RESULTS);

            if (entries.length === 0) {
                const empty = document.createElement("div");
                empty.className = "docs-search-empty";
                empty.textContent = "No matching docs found.";
                resultsContainer.appendChild(empty);
            } else {
                entries.forEach(function(entry) {
                    resultsContainer.appendChild(createResultElement(entry, query));
                });

                const viewAll = document.createElement("a");
                viewAll.className = "docs-search-view-all";
                viewAll.href = `${window.siteSettings && window.siteSettings.baseurl ? window.siteSettings.baseurl : ""}/search/?q=${encodeURIComponent(query)}`;
                viewAll.textContent = "See all results";
                resultsContainer.appendChild(viewAll);
            }

            resultsContainer.classList.remove("d-none");
        });
    }

    function moveActiveResult(resultsContainer, direction) {
        const items = Array.from(resultsContainer.querySelectorAll(".docs-search-result"));
        if (items.length === 0) {
            return;
        }

        const currentIndex = items.findIndex(function(item) {
            return item.classList.contains("is-active");
        });

        let nextIndex = currentIndex + direction;
        if (nextIndex < 0) {
            nextIndex = items.length - 1;
        } else if (nextIndex >= items.length) {
            nextIndex = 0;
        }

        items.forEach(function(item) {
            item.classList.remove("is-active");
        });

        items[nextIndex].classList.add("is-active");
        items[nextIndex].scrollIntoView({ block: "nearest" });
    }

    function bindTypeahead(input, resultsContainer) {
        let debounceTimer = null;

        input.addEventListener("input", function() {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(function() {
                renderDropdown(input, resultsContainer);
            }, 120);
        });

        input.addEventListener("focus", function() {
            loadIndex();
        });

        input.addEventListener("keydown", function(event) {
            if (event.key === "Escape") {
                input.value = "";
                resultsContainer.classList.add("d-none");
                return;
            }

            if (event.key === "ArrowDown") {
                event.preventDefault();
                moveActiveResult(resultsContainer, 1);
                return;
            }

            if (event.key === "ArrowUp") {
                event.preventDefault();
                moveActiveResult(resultsContainer, -1);
                return;
            }

            if (event.key === "Enter") {
                const active = resultsContainer.querySelector(".docs-search-result.is-active");
                if (active) {
                    event.preventDefault();
                    window.location.href = active.href;
                    return;
                }

                const query = input.value.trim();
                if (query.length >= 2) {
                    event.preventDefault();
                    const base = window.siteSettings && window.siteSettings.baseurl ? window.siteSettings.baseurl : "";
                    window.location.href = `${base}/search/?q=${encodeURIComponent(query)}`;
                }
            }
        });
    }

    function initTypeaheads() {
        document.querySelectorAll("[data-docs-search='true']").forEach(function(input) {
            const root = input.closest(".docs-search") || input.closest(".docs-search-sheet");
            const resultsContainer = root ? root.querySelector("[data-docs-search-results='true']") : null;

            if (resultsContainer) {
                bindTypeahead(input, resultsContainer);
            }
        });

        document.addEventListener("click", function(event) {
            if (!event.target.closest(".docs-search") && !event.target.closest(".docs-search-sheet")) {
                document.querySelectorAll(".docs-topbar-search [data-docs-search-results='true']").forEach(function(container) {
                    container.classList.add("d-none");
                });
            }
        });
    }

    // -----------------------------------------------------------------------
    // Mobile search sheet
    // -----------------------------------------------------------------------

    function initMobileSheet() {
        const sheet = document.getElementById("docs-search-sheet");
        const openButton = document.getElementById("docs-mobile-search-toggle");

        if (!sheet || !openButton) {
            return;
        }

        const closeButton = sheet.querySelector("[data-docs-search-sheet-close='true']");
        const input = sheet.querySelector("[data-docs-search='true']");
        let lastFocused = null;

        function openSheet() {
            lastFocused = document.activeElement;
            sheet.classList.remove("d-none");
            sheet.classList.add("is-open");
            document.body.classList.add("docs-search-sheet-open");
            loadIndex();
            if (input) {
                input.focus();
            }
        }

        function closeSheet() {
            sheet.classList.add("d-none");
            sheet.classList.remove("is-open");
            document.body.classList.remove("docs-search-sheet-open");
            if (lastFocused && typeof lastFocused.focus === "function") {
                lastFocused.focus();
            }
        }

        openButton.addEventListener("click", openSheet);

        if (closeButton) {
            closeButton.addEventListener("click", closeSheet);
        }

        sheet.addEventListener("keydown", function(event) {
            if (event.key === "Escape") {
                closeSheet();
                return;
            }

            if (event.key !== "Tab") {
                return;
            }

            // Keep focus inside the sheet while it is open.
            const focusable = Array.from(sheet.querySelectorAll("input, button, a[href]")).filter(function(element) {
                return element.offsetParent !== null;
            });

            if (focusable.length === 0) {
                return;
            }

            const firstElement = focusable[0];
            const lastElement = focusable[focusable.length - 1];

            if (event.shiftKey && document.activeElement === firstElement) {
                event.preventDefault();
                lastElement.focus();
            } else if (!event.shiftKey && document.activeElement === lastElement) {
                event.preventDefault();
                firstElement.focus();
            }
        });

        window.SimpleChat = window.SimpleChat || {};
        window.SimpleChat.SearchSheet = { openSheet, closeSheet };
    }

    // -----------------------------------------------------------------------
    // Results page
    // -----------------------------------------------------------------------

    function getQueryParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name) || "";
    }

    function renderFilters(entries, filtersContainer, onChange) {
        const counts = {};
        entries.forEach(function(entry) {
            const section = entry.section || "Docs";
            counts[section] = (counts[section] || 0) + 1;
        });

        const sections = Object.keys(counts).sort();
        filtersContainer.replaceChildren();

        if (sections.length < 2) {
            filtersContainer.classList.add("d-none");
            return;
        }

        function makeButton(label, value, count) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "docs-search-filter";
            if (activeSectionFilter === value) {
                button.classList.add("is-active");
            }
            button.textContent = count === null ? label : `${label} (${count})`;
            button.addEventListener("click", function() {
                activeSectionFilter = value;
                onChange();
            });
            return button;
        }

        filtersContainer.appendChild(makeButton("All", "", entries.length));
        sections.forEach(function(section) {
            filtersContainer.appendChild(makeButton(section, section, counts[section]));
        });

        filtersContainer.classList.remove("d-none");
    }

    function initSearchPage() {
        const page = document.querySelector("[data-docs-search-page='true']");
        if (!page) {
            return;
        }

        const input = page.querySelector("[data-docs-search-page-input='true']");
        const resultsContainer = page.querySelector("[data-docs-search-page-results='true']");
        const statusElement = page.querySelector("[data-docs-search-status='true']");
        const filtersContainer = page.querySelector("[data-docs-search-filters='true']");
        const form = page.querySelector("[data-docs-search-form='true']");

        if (!input || !resultsContainer) {
            return;
        }

        function render() {
            const query = input.value.trim();
            resultsContainer.replaceChildren();

            if (query.length < 2) {
                statusElement.textContent = "Type at least two characters to search.";
                filtersContainer.classList.add("d-none");
                return;
            }

            loadIndex().then(function() {
                const allEntries = resolveEntries(runQuery(query));

                renderFilters(allEntries, filtersContainer, render);

                const entries = activeSectionFilter
                    ? allEntries.filter(function(entry) {
                        return (entry.section || "Docs") === activeSectionFilter;
                    })
                    : allEntries;

                resultsContainer.replaceChildren();

                if (entries.length === 0) {
                    statusElement.textContent = `No results for "${query}".`;
                    return;
                }

                statusElement.textContent = `${entries.length} result${entries.length === 1 ? "" : "s"} for "${query}".`;

                entries.slice(0, MAX_PAGE_RESULTS).forEach(function(entry) {
                    resultsContainer.appendChild(createResultElement(entry, query));
                });
            });
        }

        if (form) {
            form.addEventListener("submit", function(event) {
                event.preventDefault();
                render();
            });
        }

        let debounceTimer = null;
        input.addEventListener("input", function() {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(render, 150);
        });

        const initialQuery = getQueryParam("q");
        if (initialQuery) {
            input.value = initialQuery;
        }

        input.focus();
        render();
    }

    // -----------------------------------------------------------------------
    // Keyboard shortcuts
    // -----------------------------------------------------------------------

    function focusPrimarySearch() {
        const sheetToggle = document.getElementById("docs-mobile-search-toggle");
        const topbarInput = document.getElementById("docs-topbar-search-input");

        if (topbarInput && topbarInput.offsetParent !== null) {
            topbarInput.focus();
            topbarInput.select();
            return;
        }

        if (sheetToggle && window.SimpleChat && window.SimpleChat.SearchSheet) {
            window.SimpleChat.SearchSheet.openSheet();
        }
    }

    function initShortcuts() {
        document.addEventListener("keydown", function(event) {
            const target = event.target;
            const isTypingContext = target && (
                target.tagName === "INPUT" ||
                target.tagName === "TEXTAREA" ||
                target.isContentEditable
            );

            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                focusPrimarySearch();
                return;
            }

            if (event.key === "/" && !isTypingContext) {
                event.preventDefault();
                focusPrimarySearch();
            }
        });
    }

    function init() {
        initTypeaheads();
        initMobileSheet();
        initSearchPage();
        initShortcuts();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.SimpleChat = window.SimpleChat || {};
    window.SimpleChat.Search = {
        loadIndex,
        runQuery
    };
})();
