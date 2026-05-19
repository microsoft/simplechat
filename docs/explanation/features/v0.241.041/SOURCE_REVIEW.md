# Source Review

Implemented in version: **0.241.041**

Refined in version: **0.241.042**

Planner refinement in version: **0.241.043**

Traversal observability refinement in version: **0.241.044**

Citation seeding and second-hop traversal refinement in version: **0.241.045**

Rendered Load More refinement in version: **0.241.046**

## Overview

Source Review adds an optional chat control that lets SimpleChat inspect source pages directly instead of relying only on search result snippets. It is designed to work with Web Search by using returned citation URLs as review seeds, and it can also review URLs pasted directly in a user's message.

Deep Source Review can follow a bounded set of relevant links from a listing or index page, such as press release indexes, RSS feeds, sitemap entries, or source pages that point to detail pages. Reviewed content is packaged as untrusted evidence and added to the model context with explicit prompt-injection isolation instructions.

The v0.241.042 refinement keeps seed/archive pages ahead of child pages in the page budget, then uses leftover budget for the highest-scoring child links across all reviewed seed pages. This avoids over-investing in the first source page when a request spans multiple organizations, products, or official archives.

The v0.241.043 refinement adds optional model-assisted link planning for Deep Source Review. After seed pages are reviewed and child links are extracted, the selected chat model can rank only those already-extracted candidate URLs before the server fetches additional pages. The planner cannot browse, invent fetch targets, or bypass Source Review URL policy; if planning is unavailable or returns unusable URLs, deterministic child-link ordering remains the fallback.

The v0.241.044 refinement scores extracted links before applying the bounded link inventory limit. This keeps relevant press-release, archive, and source-detail links available even when source pages contain long navigation menus before the actual evidence links. It also expands Source Review audit output so logs show whether Deep Source Review and model-assisted planning were actually used.

The v0.241.045 refinement sends all Foundry web-search URL citations into Source Review, not just links repeated in the web-search answer text. It also adds a configurable seed-page budget and raises bounded Deep Source Review depth to `2`, so official source pages can be inspected through one additional section or year page before reaching detail pages.

The v0.241.046 refinement adds optional Load More support to the rendered-page path. When JavaScript rendering is enabled and a source page exposes visible Load More, Show More, View More, or similar controls, Source Review can click them up to a configured cap before extracting evidence. The renderer stops early when no new content appears or the requested date range appears visible.

## Dependencies

Source Review uses server-side HTTP requests through `aiohttp` and HTML/XML extraction through `beautifulsoup4`, both already present in the application requirements. Optional JavaScript rendering is available only when admins enable it and the app host has a Playwright browser runtime installed.

## Technical Specifications

### Architecture

The implementation is centered in `application/single_app/functions_source_review.py` and is invoked from `application/single_app/route_backend_chats.py` after Web Search runs. This ordering lets the feature review both user-provided URLs and Web Search citation URLs before the final model response is generated.

The chat route appends Source Review output as a system augmentation message. The message clearly labels page content as untrusted web evidence and directs the model to ignore instructions found inside fetched pages.

### Server-Side Protections

These protections are enforced in code and are not user configurable:

* Only `http` and `https` URLs are allowed.
* URL credentials are blocked.
* Localhost, single-label hostnames, private/internal/link-local/multicast/reserved IPs, and metadata endpoints are blocked.
* DNS-resolved addresses are checked before fetch.
* Every redirect target is revalidated.
* Unsupported content types are skipped.
* Page size, redirect count, timeout, depth, and total pages are bounded by hard ceilings.
* Web page text is never treated as tool instructions or policy text.

### Configurable Settings

Admins can configure Source Review in **Admin Settings > Search & Extract**:

* Enable Source Review.
* Enable Deep Source Review.
* Enable model-assisted link planning for Deep Source Review.
* Default mode: manual toggle, automatic for pasted URLs, or automatic with URLs/Web Search.
* Max pages per turn, max seed pages per turn, timeout, redirect count, max MB per page, and depth.
* Optional JavaScript rendering fallback.
* Rendered Load More click cap.
* robots.txt handling.
* Domain allowlist and blocklist.
* User allowlist and blocklist.
* Audit logging.

The app version was updated in `application/single_app/config.py` to `0.241.041` with this implementation.

The traversal refinement updated `application/single_app/config.py` to `0.241.042`.

The model-assisted link planning refinement updated `application/single_app/config.py` to `0.241.043`.

The link-prioritization and audit refinement updated `application/single_app/config.py` to `0.241.044`.

The citation seeding and second-hop traversal refinement updated `application/single_app/config.py` to `0.241.045`.

The rendered Load More refinement updated `application/single_app/config.py` to `0.241.046`.

## Usage Instructions

Admins enable Source Review from the Search & Extract settings tab. Once enabled for a user, the chat toolbar shows a **Sources** button. Users can toggle it when they want the system to review actual pages behind pasted URLs or Web Search citations.

Source Review works best when the user includes a specific source URL, asks for the latest item from an official listing page, or combines Web Search with Source Review for broad discovery plus source inspection.

## Testing and Validation

Functional coverage was added in `functional_tests/test_source_review_security.py` for:

* User allowlist/blocklist behavior.
* Hard clamping of admin limits.
* SSRF-sensitive URL rejection.
* HTML extraction, link inventory, date extraction, and prompt-injection marker detection.
* Seed URL ordering from direct URLs and Web Search citations.

Additional coverage was added in `functional_tests/test_source_review_deep_traversal.py` for generic archive-style child-link prioritization and cross-seed child selection.

The v0.241.043 coverage extends `functional_tests/test_source_review_deep_traversal.py` to validate that model planning accepts only existing candidate URLs, ignores invented URLs, and preserves planner-selected ordering before deterministic fallback candidates.

The v0.241.044 coverage extends `functional_tests/test_source_review_deep_traversal.py` to validate that relevant archive links survive noisy navigation before truncation and that generic same-domain navigation links are not followed for source-archive requests.

The v0.241.045 coverage extends `functional_tests/test_web_search_current_message_only.py` to validate that raw Foundry citations become Source Review seed candidates, and extends `functional_tests/test_source_review_deep_traversal.py` to validate bounded second-hop traversal and seed-page budgeting.

The v0.241.046 coverage extends `functional_tests/test_source_review_security.py` to validate Load More detection and click-cap clamping.

UI coverage was added in `ui_tests/test_admin_source_review_settings.py` for the admin Source Review panel and bounded controls.

## Known Limitations

Source Review is intentionally bounded and is not a general crawler. Deep review follows only selected scored links within the configured page and depth budgets. JavaScript rendering and Load More clicks depend on optional runtime support and are treated as a fallback rather than the default fetch path.