// check_docs_links.js
/**
 * Internal link checker for the built documentation site.
 *
 * Version: 0.250.230
 * Implemented in: 0.250.230
 *
 * Walks a built Jekyll site and verifies that every internal href and src
 * resolves to a file that exists. Unlike a naive checker, this resolves
 * relative links against the containing page, which is where link rot from page
 * moves actually shows up.
 *
 * Usage:
 *   node ui_tests/check_docs_links.js <path-to-_site> [--baseurl /simplechat] [--json]
 */

const fs = require("fs");
const path = require("path");

const siteRoot = path.resolve(process.argv[2] || "docs/_site");
const baseurlArgIndex = process.argv.indexOf("--baseurl");
const baseurl = baseurlArgIndex !== -1 ? process.argv[baseurlArgIndex + 1] : "/simplechat";
const asJson = process.argv.includes("--json");

const SKIP_PREFIXES = ["http://", "https://", "mailto:", "data:", "javascript:", "//", "#", "tel:"];

function walk(directory, collected) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const full = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            walk(full, collected);
        } else if (entry.name.endsWith(".html")) {
            collected.push(full);
        }
    }
    return collected;
}

function resolveTarget(rawUrl, pageUrl) {
    const cleaned = rawUrl.split("#")[0].split("?")[0].trim();
    if (!cleaned) {
        return null;
    }

    let relative;
    if (cleaned.startsWith(`${baseurl}/`)) {
        relative = cleaned.slice(baseurl.length + 1);
    } else if (cleaned.startsWith("/")) {
        relative = cleaned.slice(1);
    } else {
        const pageDirectory = path.posix.dirname(pageUrl);
        relative = path.posix.normalize(path.posix.join(pageDirectory, cleaned)).replace(/^\/+/, "");
    }

    return decodeURIComponent(relative);
}

function exists(relative) {
    const candidate = path.join(siteRoot, relative.split("/").join(path.sep));
    if (fs.existsSync(candidate)) {
        return !fs.statSync(candidate).isDirectory() || fs.existsSync(path.join(candidate, "index.html"));
    }
    return false;
}

function main() {
    if (!fs.existsSync(siteRoot)) {
        console.error(`Built site not found at ${siteRoot}. Run: cd docs; bundle exec jekyll build`);
        process.exit(2);
    }

    const pages = walk(siteRoot, []);
    const broken = new Map();
    let linkCount = 0;

    for (const page of pages) {
        const html = fs.readFileSync(page, "utf8");
        const pageUrl = `/${path.relative(siteRoot, page).split(path.sep).join("/")}`;

        for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
            const rawUrl = match[1];
            if (SKIP_PREFIXES.some((prefix) => rawUrl.startsWith(prefix))) {
                continue;
            }

            const target = resolveTarget(rawUrl, pageUrl);
            if (target === null) {
                continue;
            }

            linkCount += 1;
            if (!exists(target)) {
                if (!broken.has(rawUrl)) {
                    broken.set(rawUrl, new Set());
                }
                broken.get(rawUrl).add(pageUrl);
            }
        }
    }

    if (asJson) {
        const payload = {};
        for (const [url, sources] of broken) {
            payload[url] = Array.from(sources).sort();
        }
        console.log(JSON.stringify({ pages: pages.length, links: linkCount, broken: payload }, null, 2));
        process.exit(broken.size === 0 ? 0 : 1);
    }

    console.log(`Pages scanned:  ${pages.length}`);
    console.log(`Internal links: ${linkCount}`);
    console.log(`Broken targets: ${broken.size}`);

    if (broken.size > 0) {
        console.log("");
        for (const [url, sources] of Array.from(broken).sort()) {
            const sourceList = Array.from(sources).sort();
            const shown = sourceList.slice(0, 2).join(", ");
            const more = sourceList.length > 2 ? ` (+${sourceList.length - 2} more)` : "";
            console.log(`  ${url}`);
            console.log(`      from: ${shown}${more}`);
        }
    }

    process.exit(broken.size === 0 ? 0 : 1);
}

main();
