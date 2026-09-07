// test_docs_site_responsive.js
/**
 * Responsive and search verification for the Simple Chat documentation site.
 *
 * Version: 0.250.230
 * Implemented in: 0.250.230
 *
 * Verifies that the redesigned documentation site works on phone, tablet, and
 * desktop viewports, that search is reachable and functional at every size, and
 * that wide content such as settings tables does not overflow horizontally.
 *
 * The site is served from a local static server. Because the site is published
 * under the /simplechat baseurl, the server root must expose the built site at
 * /simplechat.
 *
 * Usage:
 *   cd docs
 *   bundle exec jekyll build
 *   node ../ui_tests/test_docs_site_responsive.js [baseUrl]
 */

const { chromium } = require("playwright");

const BASE_URL = process.argv[2] || "http://127.0.0.1:4111/simplechat";

const VIEWPORTS = [
    { name: "phone-small", width: 360, height: 640 },
    { name: "phone-large", width: 390, height: 844 },
    { name: "tablet", width: 768, height: 1024 },
    { name: "desktop", width: 1280, height: 800 },
    { name: "wide", width: 1920, height: 1080 }
];

const PAGES = [
    { name: "home", path: "/" },
    { name: "admin-index", path: "/admin/" },
    { name: "admin-knowledge", path: "/admin/knowledge/" },
    { name: "release-notes", path: "/explanation/release_notes/" },
    { name: "search", path: "/search/" },
    { name: "media-status", path: "/contributing/media-status/" }
];

// Allow a small tolerance for sub-pixel rounding and scrollbar width.
const OVERFLOW_TOLERANCE = 2;

const failures = [];
const passes = [];

function record(ok, label, detail) {
    if (ok) {
        passes.push(label);
    } else {
        failures.push(`${label}${detail ? ` -- ${detail}` : ""}`);
    }
}

async function checkOverflow(page, viewport, pageName) {
    const result = await page.evaluate(() => {
        const doc = document.documentElement;
        const offenders = [];
        document.querySelectorAll("body *").forEach((element) => {
            const rect = element.getBoundingClientRect();
            if (rect.width > 0 && rect.right > window.innerWidth + 2) {
                offenders.push({
                    tag: element.tagName.toLowerCase(),
                    cls: (element.className || "").toString().slice(0, 60),
                    right: Math.round(rect.right)
                });
            }
        });
        return {
            scrollWidth: doc.scrollWidth,
            innerWidth: window.innerWidth,
            offenders: offenders.slice(0, 5)
        };
    });

    const overflow = result.scrollWidth - result.innerWidth;
    const ok = overflow <= OVERFLOW_TOLERANCE;
    const detail = ok
        ? ""
        : `scrollWidth ${result.scrollWidth} vs viewport ${result.innerWidth} (+${overflow}px); offenders: ` +
          result.offenders.map((o) => `${o.tag}.${o.cls}@${o.right}`).join(", ");

    record(ok, `[${viewport.name}] ${pageName}: no horizontal overflow`, detail);
}

async function checkSearchReachable(page, viewport, pageName) {
    const reachable = await page.evaluate(() => {
        const isVisible = (element) => {
            if (element === null) {
                return false;
            }
            const style = window.getComputedStyle(element);
            if (style.display === "none" || style.visibility === "hidden") {
                return false;
            }
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        return {
            topbar: isVisible(document.getElementById("docs-topbar-search-input")),
            mobile: isVisible(document.getElementById("docs-mobile-search-toggle"))
        };
    });

    const ok = reachable.topbar || reachable.mobile;
    record(
        ok,
        `[${viewport.name}] ${pageName}: search is reachable`,
        ok ? "" : "neither the top bar search input nor the mobile search toggle is visible"
    );
}

async function checkNavReachable(page, viewport, pageName) {
    const reachable = await page.evaluate(() => {
        // offsetParent is null for position: fixed elements, so it cannot be
        // used to test visibility of the fixed sidebar. Measure geometry and
        // computed style instead.
        const isVisible = (element) => {
            if (element === null) {
                return false;
            }
            const style = window.getComputedStyle(element);
            if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
                return false;
            }
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < window.innerWidth;
        };

        return {
            sidebar: isVisible(document.getElementById("sidebar-nav")),
            toggle: isVisible(document.getElementById("docs-mobile-menu-toggle"))
        };
    });

    const ok = reachable.sidebar || reachable.toggle;
    record(
        ok,
        `[${viewport.name}] ${pageName}: navigation is reachable`,
        ok ? "" : "neither the sidebar nor the mobile menu toggle is visible"
    );
}

async function checkSearchWorks(browser) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();

    await page.goto(`${BASE_URL}/search/?q=file%20sync`, { waitUntil: "networkidle" });
    await page.waitForTimeout(900);

    const results = await page.evaluate(() => {
        const nodes = document.querySelectorAll(".docs-search-page-results .docs-search-result");
        return Array.from(nodes).slice(0, 5).map((node) => {
            const title = node.querySelector(".docs-search-result-title");
            return title ? title.textContent.trim() : "";
        });
    });

    record(results.length > 0, "search page returns results for 'file sync'",
        results.length > 0 ? "" : "no results rendered");

    if (results.length > 0) {
        const relevant = results.some((title) => title.toLowerCase().includes("file sync"));
        record(relevant, "top search results are relevant to 'file sync'",
            relevant ? "" : `got: ${results.join(" | ")}`);
        console.log(`    search results: ${results.join(" | ")}`);
    }

    const highlighted = await page.evaluate(() => document.querySelectorAll(".docs-search-result mark").length);
    record(highlighted > 0, "search results highlight matched terms",
        highlighted > 0 ? "" : "no <mark> elements found");

    await context.close();
}

async function checkMobileSearchSheet(browser) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();

    await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

    const toggle = await page.$("#docs-mobile-search-toggle");
    record(toggle !== null, "mobile search toggle exists", toggle ? "" : "#docs-mobile-search-toggle not found");

    if (toggle) {
        await toggle.click();
        await page.waitForTimeout(400);

        const sheetOpen = await page.evaluate(() => {
            const sheet = document.getElementById("docs-search-sheet");
            return sheet !== null && sheet.classList.contains("is-open") && !sheet.classList.contains("d-none");
        });
        record(sheetOpen, "mobile search sheet opens", sheetOpen ? "" : "sheet did not open");

        if (sheetOpen) {
            await page.fill("#docs-search-sheet-input", "terraform");
            await page.waitForTimeout(900);

            const count = await page.evaluate(
                () => document.querySelectorAll("#docs-search-sheet .docs-search-result").length
            );
            record(count > 0, "mobile search sheet returns results", count > 0 ? "" : "no results in sheet");
        }
    }

    await context.close();
}

async function checkMediaPlaceholders(browser) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();

    // Use a group page that still has unfilled media slots, so the placeholder
    // rendering path is genuinely exercised.
    await page.goto(`${BASE_URL}/admin/backup-recovery/`, { waitUntil: "domcontentloaded" });

    const counts = await page.evaluate(() => ({
        placeholders: document.querySelectorAll(".docs-media--placeholder").length,
        videoPlanned: document.querySelectorAll(".docs-media--video-planned").length,
        pathHints: Array.from(document.querySelectorAll(".docs-media-placeholder-path code"))
            .map((node) => node.textContent.trim())
            .slice(0, 3)
    }));

    record(counts.placeholders > 0, "media placeholders render on admin pages",
        counts.placeholders > 0 ? "" : "no placeholder cards found");
    record(counts.videoPlanned > 0, "video placeholder renders its planned state",
        counts.videoPlanned > 0 ? "" : "no video-planned card found");
    record(counts.pathHints.length > 0, "placeholder names the exact file to create",
        counts.pathHints.length > 0 ? "" : "no expected-path hint rendered");

    if (counts.pathHints.length > 0) {
        console.log(`    expected asset paths: ${counts.pathHints.join(", ")}`);
    }

    await context.close();
}

async function checkNoCdnAssets(browser) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();

    const external = [];
    page.on("request", (request) => {
        const url = request.url();
        if (!url.startsWith(BASE_URL) && !url.startsWith("data:") && !url.startsWith("http://127.0.0.1")) {
            external.push(url);
        }
    });

    await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

    const scriptAndStyle = external.filter((url) => /\.js(\?|$)|\.css(\?|$)|fonts\.googleapis|fonts\.gstatic/.test(url));
    record(scriptAndStyle.length === 0, "no external script or style requests",
        scriptAndStyle.length === 0 ? "" : scriptAndStyle.join(", "));

    if (external.length > 0) {
        console.log(`    other external requests: ${external.slice(0, 5).join(", ")}`);
    }

    await context.close();
}

async function main() {
    const browser = await chromium.launch();

    console.log(`Testing documentation site at ${BASE_URL}\n`);

    for (const viewport of VIEWPORTS) {
        console.log(`Viewport ${viewport.name} (${viewport.width}x${viewport.height})`);
        const context = await browser.newContext({
            viewport: { width: viewport.width, height: viewport.height }
        });
        const page = await context.newPage();

        for (const target of PAGES) {
            const response = await page.goto(`${BASE_URL}${target.path}`, { waitUntil: "domcontentloaded" });

            if (!response || !response.ok()) {
                record(false, `[${viewport.name}] ${target.name}: page loads`,
                    `status ${response ? response.status() : "no response"} for ${target.path}`);
                continue;
            }

            await page.waitForTimeout(150);
            await checkOverflow(page, viewport, target.name);
            await checkSearchReachable(page, viewport, target.name);
            await checkNavReachable(page, viewport, target.name);
        }

        await context.close();
    }

    console.log("\nFunctional checks");
    await checkSearchWorks(browser);
    await checkMobileSearchSheet(browser);
    await checkMediaPlaceholders(browser);
    await checkNoCdnAssets(browser);

    await browser.close();

    console.log(`\n${"=".repeat(60)}`);
    console.log(`Passed: ${passes.length}`);
    console.log(`Failed: ${failures.length}`);

    if (failures.length > 0) {
        console.log("\nFailures:");
        failures.forEach((failure) => console.log(`  - ${failure}`));
        process.exit(1);
    }

    console.log("\nAll documentation site checks passed.");
    process.exit(0);
}

main().catch((error) => {
    console.error("Test run failed:", error);
    process.exit(1);
});
