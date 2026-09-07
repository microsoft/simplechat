// test_docs_media_lightbox_source_validation.js
/**
 * Regression test for documentation media lightbox source validation.
 *
 * Version: 0.260.021
 * Implemented in: 0.260.021
 *
 * The lightbox assigns an image URL that originates from a data attribute in
 * the rendered page. That is DOM text flowing into a URL sink, which CodeQL
 * flagged as js/xss-through-dom. The lightbox now resolves and validates the
 * value first, requiring a same-origin http(s) URL with an image extension.
 *
 * This test executes the real safeMediaUrl logic from docs/assets/js/media.js
 * against hostile and legitimate inputs, so the guard cannot be silently
 * removed or weakened.
 *
 * Usage:
 *   node ui_tests/test_docs_media_lightbox_source_validation.js
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const MEDIA_JS = path.resolve(__dirname, "..", "docs", "assets", "js", "media.js");

const ORIGIN = "https://microsoft.github.io";
const BASE_URI = `${ORIGIN}/simplechat/admin/safety/`;

const BLOCKED = [
    ["javascript: URL", "javascript:alert(document.domain)"],
    ["uppercase javascript URL", "JaVaScRiPt:alert(1)"],
    ["data URL carrying markup", "data:text/html,<script>alert(1)</script>"],
    ["data URL image", "data:image/svg+xml;base64,PHN2Zy8+"],
    ["off-site absolute URL", "https://evil.example.com/images/x.png"],
    ["protocol-relative off-site URL", "//evil.example.com/images/x.png"],
    ["same-origin non-image path", "/simplechat/admin/safety/"],
    ["traversal to a non-image", "../../../etc/passwd"],
    ["empty string", ""],
    ["null", null],
    ["non-string", 42]
];

const ALLOWED = [
    ["absolute site image path", "/simplechat/images/admin-settings/safety.png"],
    ["relative image path", "../../images/latest-release/release_260_yamcs_action_1.png"],
    ["same-origin absolute URL", `${ORIGIN}/simplechat/images/architecture.png`],
    ["uppercase extension", "/simplechat/images/admin-settings/safety.PNG"],
    ["jpeg image", "/simplechat/images/foo.jpeg"],
    ["webp image", "/simplechat/images/foo.webp"]
];

function loadSafeMediaUrl() {
    const source = fs.readFileSync(MEDIA_JS, "utf8");

    const match = source.match(/function safeMediaUrl\(rawSource\) \{[\s\S]*?\n {4}\}/);
    if (!match) {
        throw new Error(
            "safeMediaUrl not found in docs/assets/js/media.js. The lightbox must " +
            "validate media URLs before assigning them; see js/xss-through-dom."
        );
    }

    const sandbox = {
        URL,
        document: { baseURI: BASE_URI },
        window: { location: { origin: ORIGIN } }
    };
    vm.createContext(sandbox);
    vm.runInContext(`${match[0]}\nthis.safeMediaUrl = safeMediaUrl;`, sandbox);
    return sandbox.safeMediaUrl;
}

/**
 * Compare origins by parsing, not by string prefix.
 *
 * A prefix check such as startsWith(ORIGIN) is weak URL matching: a host like
 * "microsoft.github.io.example.com" shares the prefix without sharing the
 * origin. Parsing and comparing the origin field avoids that class of mistake.
 */
function isSameOrigin(candidate) {
    try {
        return new URL(candidate).origin === ORIGIN;
    } catch (error) {
        return false;
    }
}

function main() {
    let safeMediaUrl;
    try {
        safeMediaUrl = loadSafeMediaUrl();
    } catch (error) {
        console.error(`FAILED: ${error.message}`);
        process.exit(1);
    }

    const failures = [];
    let passed = 0;

    for (const [label, value] of BLOCKED) {
        const result = safeMediaUrl(value);
        if (result === null) {
            passed += 1;
        } else {
            failures.push(`should have rejected ${label} (${JSON.stringify(value)}) but returned ${result}`);
        }
    }

    for (const [label, value] of ALLOWED) {
        const result = safeMediaUrl(value);
        if (typeof result === "string" && isSameOrigin(result)) {
            passed += 1;
        } else {
            failures.push(`should have accepted ${label} (${JSON.stringify(value)}) but returned ${result}`);
        }
    }

    console.log(`Media lightbox source validation: ${passed}/${BLOCKED.length + ALLOWED.length} checks passed`);

    if (failures.length > 0) {
        console.log("\nFailures:");
        failures.forEach((failure) => console.log(`  - ${failure}`));
        process.exit(1);
    }

    console.log("All media lightbox source validation checks passed.");
    process.exit(0);
}

main();
