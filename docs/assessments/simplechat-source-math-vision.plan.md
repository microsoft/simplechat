# SimpleChat: Bitbucket source awareness, V1 mathematics, and image fidelity

## Document control

| Field | Value |
|---|---|
| Assessment date | 2026-09-30 |
| Repository | Local SimpleChat checkout |
| Branch | `feature/customendpoints` |
| HEAD | `87c0891fe25ee3dcb5262518bc0dc9a93b47926c` |
| Working-tree application version | `0.261.046` |
| Evidence baseline | Current working tree, including pre-existing uncommitted changes; not a clean release or proof of the customer's deployed behavior |
| Status | Proposed plan, pending customer decisions and design review |
| Implementation authorization | None; no application, configuration, dependency, or infrastructure changes made |

## Scope and exclusions

Three bounded questions:

1. Safely add Bitbucket-compatible source awareness to existing agents for application explanation and troubleshooting.
2. Compare the effort to render LaTeX mathematics in the existing V1 display.
3. Investigate whether SimpleChat preprocessing could contribute to the second customer screenshot: a visible image accompanied by a "completely blank/white" answer.

V1 is interpreted as the current Flask/Jinja/JavaScript chat interface in this checkout. Confirm the customer's release before implementation. This is not a full migration assessment, penetration test, ATO determination, or production incident root-cause confirmation.

No live Bitbucket, database, Azure deployment, or model endpoint was accessed. Customer images and source code were not submitted to an external research or inference service. Public documentation research used product-level queries only.

The relevant supplied evidence is the two pasted customer screenshots. The second shows a workspace-image citation, not an original camera file. The original low-contrast images, Example 3 before/after files, prompts, and request captures are unavailable.

## Executive summary

- **Source awareness:** Add a separately isolated, read-only source-context service accessed through a narrowly scoped SimpleChat action. Start with one approved repository/release and a restricted agent. Do not clone customer repositories into SimpleChat's application or plugin directories, execute repository code, or connect a broad Git/terminal tool to an agent.
- **V1 mathematics:** A substantially smaller, mostly frontend change. Use locally hosted KaTeX unless a validated formula/accessibility requirement favors MathJax. Protect mathematical source before Markdown and existing table/citation transformations. Adding a typesetter after the current Markdown parser is insufficient.
- **Image issue:** The traced standalone-image paths do not show contrast adjustment, resizing, or lossy re-encoding. They do show a potentially lossy *information* pipeline: extraction and optional vision analysis become text, and the answering model can receive that text rather than the image. The UI separately retrieves the original stored image. That distinction can explain how a normal-looking image card coexists with an incorrect description, but does not establish the customer's root cause.
- **Priority:** Investigate image fidelity first because it affects the intended imaging use case. Deliver math independently. Treat source awareness as a separately gated integration, not a quick file-upload extension.

## Constraints used and decisions still needed

| ID | Constraint or decision | Status/source | Applicability | Owner / validation |
|---|---|---|---|---|
| CON-001 | Source-aware assistance must not compromise existing SimpleChat behavior or isolation | User request | Source awareness | Product/security owners approve isolation and regression gates |
| CON-002 | Cover both Bitbucket Cloud and Data Center | User selected "Not yet confirmed--cover both in the plan" | Source awareness | Bitbucket owner confirms edition, Data Center version if applicable, token policy, and network route |
| CON-003 | Existing V1 interface is the requested display target | User request; mapping to this checkout is an assumption | Mathematics | SimpleChat owner supplies deployed version/commit |
| CON-004 | Low-contrast image interpretation is important to the proposed PLASO use | Customer statement relayed by user | Vision | Imaging owner supplies approved evaluation cases and acceptance criteria |
| CON-005 | Similar failures were observed in Foundry, while another GPT-5.1 environment reportedly succeeds | Customer-reported observation, not independently reproduced | Vision | Endpoint owners compare identical inputs and deployment details |
| DEC-001 | Approved cloud, regions, model/embedding endpoints, source classification, retention, and authorization boundary | Unknown | All new data processing | Security/data owners approve before ingestion; do not infer Government/CUI requirements from NASA or PLASO names |
| DEC-002 | Repository audience: provider-enforced per-user access or an explicitly approved homogeneous application team | Unknown | Source authorization | Bitbucket/identity owners define authoritative entitlement mapping and revocation behavior |
| DEC-003 | Repositories, languages, size, branch/release selection, update frequency, and troubleshooting tasks | Unknown | Source scope and capacity | Application owner supplies inventory and representative questions |
| DEC-004 | Formula subset and whether visual PDF/DOCX exports are included | Unknown; display-only is the assessment baseline | Mathematics | Product/accessibility owners confirm supported syntax and export expectations |
| DEC-005 | Exact image upload route, extraction settings, ingestion model, answering model, API protocol, and gateway route in each environment | Unknown | Incident isolation | SimpleChat/model owners obtain non-secret configuration evidence |

No customer-constraints assessment file was found in the checkout's documentation. No unanswered requirement is treated as customer approval.

## Evidence coverage and validation performed

Inspected the plugin/action loading and identity hooks, File Sync source registry, document search action, MCP destination governance, V1 renderer and streaming callers, standalone-image ingestion, extraction engine selection, vision request construction, chat history conversion, and original-image citation delivery.

- Pylance references verified the vision-analysis helper's callers in workspace processing and chat upload.
- A local Node check using the repository's existing Marked library reproduced loss of `\[` / `\(` delimiters and collapse of `\\` matrix row separators. No library was installed.
- The editor test tool did not discover the selected tests. The existing virtual environment then ran the two selected test files with bytecode and pytest cache writing disabled: **3 passed, 1 existing `PytestReturnNotNoneWarning`**.
- Those tests verify image data-URL decoding and admin vision connection-test wiring. They do **not** measure low-contrast accuracy, prove ingestion uses the same endpoint as the test button, or prove byte fidelity through the customer's deployment.
- No end-to-end model accuracy, browser-rendered mathematics, Bitbucket access, or production performance claims are made.

## Material findings

Scores below describe only the stated capability, not general application security. `NE` means the required evidence is unavailable.

| ID | Observation | Evidence | Impact or risk | Score | Confidence | Recommendation |
|---|---|---|---|---:|---|---|
| ARC-001 | Existing actions and document-search integration are useful extension points; File Sync has no Bitbucket source in its registry | E01-E04 | Extending generic ingestion alone does not provide repository ACLs, commit consistency, or code citations | NE | High | Thin source action plus isolated source service |
| RISK-001 | Plugin discovery imports Python modules from SimpleChat's plugin directory | E02 | Putting retrieved source in that directory would cross a code-execution trust boundary | NE | High | Never store customer repositories in an executable/importable app location |
| MOD-001 | V1 uses Marked followed by DOMPurify, with no KaTeX/MathJax found in static assets/templates | E05-E07; local parser reproduction | Raw math remains visible; ordinary Markdown alters TeX escapes | 0 | High | Tokenize/preserve math before existing transformations, then typeset safely |
| AIO-001 | Standalone-image vision analysis reads file bytes and base64-encodes them; `image_url.detail` is omitted | E08 | No observed app-level pixel enhancement/compression in that helper; service detail selection is implicit | NE | High | Compare explicit `high` with `auto` using the same bytes and endpoint |
| AIO-002 | Workspace vision descriptions are appended to indexed text; search augmentation and uploaded-image history can be text-only | E09-E11 | An earlier incorrect caption can be repeated without fresh pixel inspection | NE | High | Distinguish indexed descriptions from direct image evidence; add explicit reinspection only after controlled validation |
| AIO-003 | The workspace image card uses a citation endpoint serving stored blob bytes independently | E12 | A correct preview is not proof that the answering model received those bytes | NE | High | Correlate preview, ingestion, and inference payloads by artifact/version/hash |
| RISK-002 | Ingestion vision helper uses legacy GPT/APIM settings and `multimodal_vision_model`; admin connection test has multi-endpoint resolution | E08, E13 | Chat label or successful admin test does not establish actual ingestion endpoint/model parity | NE | High | Verify actual resolved endpoint and model for each stage |
| RISK-003 | Image chunk creation depends on extraction pages, and empty chunk content is skipped before saving | E14 | A non-text image may have vision metadata but no searchable chunk; adding text can change ingestion behavior | NE | High for code condition; Low for incident causality | Test zero-OCR images explicitly; do not treat OCR absence as visual blankness |
| RISK-004 | Public-cloud DI byte submission sets `content_type="application/pdf"` even though the helper accepts images | E15 | MIME handling is another variable to validate; this is not evidence of pixel alteration | NE | High for code; Low for incident causality | Verify real PNG/JPEG submissions and service behavior separately from direct vision |

## 1. Safe Bitbucket-compatible source awareness

### Recommended architecture

**Recommended target architecture pending customer decisions and formal design review.**

```text
Existing SimpleChat sign-in, conversation, and agent governance
    -> narrow Source Context action
    -> authenticated source-context API
         -> current-user entitlement and repository policy checks
         -> bounded search / tree / exact-line retrieval
         -> isolated, immutable repository snapshots and optional code index

Separate ingestion worker
    -> approved Bitbucket Cloud OR Data Center read APIs
    -> file validation, secret screening, static parsing, snapshot creation
    -> staging index -> validated atomic promotion
```

The source service has its own identity, compute/resource limits, temporary storage, egress policy, and operational kill switch. Its compromise must not grant access to SimpleChat settings, other workspaces, operational secrets, deployment credentials, or production application data.

Use an approved Azure hosting service for the API and worker only after cloud/region eligibility is confirmed. Candidate capabilities include managed compute, private storage, managed identity, Key Vault, and a separate Azure AI Search code index if scale warrants it. These are capability candidates, not approved services/SKUs for this customer. A separate index is a logical boundary, not sufficient physical resource or credential isolation by itself.

Reuse existing action governance and citation UI patterns. Do not replace document search, change default agents, or globally enlarge the chat context. Source-aware agents should initially have no outbound mail, arbitrary HTTP, write tools, workflow execution, or shell tools.

### Options and tradeoffs

| Option | Benefits | Limitations / operating burden | Disposition |
|---|---|---|---|
| Isolated read API with bounded repository tree and file retrieval | Smaller initial data footprint; current permissions can be checked on demand; easily disabled | Provider latency/rate limits; limited repository-wide reasoning; no assumption of equivalent Cloud/DC code search | Initial pilot capability |
| Isolated immutable snapshots with lexical/symbol search, optional semantic index, and exact-source retrieval | Commit-consistent answers; good repository-wide lookup; incremental updates | More sensitive derived data; ACL/revocation, indexing, deletion, and lifecycle work | Recommended progression when the pilot demonstrates need |
| Manual upload of curated source excerpts through existing documents | Useful for a short, controlled feasibility exercise | Manual freshness and permissions; weak commit/line provenance; not general Bitbucket compatibility | Non-automated fallback, not the requested production solution |

Do not start with fine-tuning, a full code graph, a repository rewrite, or an autonomous coding agent. Deterministic path/symbol/error-string search may solve many troubleshooting questions without embeddings.

### Bitbucket edition compatibility

| Concern | Bitbucket Cloud | Bitbucket Data Center |
|---|---|---|
| Adapter | Cloud REST v2; source at an immutable commit | Adapter for the customer's supported DC version; repository browse/raw/commit APIs |
| Read access | Repository-scoped read token for ingestion where permitted; delegated OAuth or appropriately scoped user API token where user-context access is required | Read-only repository/project HTTP token for ingestion where supported; user-context access according to approved deployment policy |
| Important distinction | Repository tokens are not individual-user authorization | Same: integration token access is not proof of end-user entitlement |
| Network | Allowlisted Bitbucket API hosts; no arbitrary Internet repository URLs | Explicit approved hostname, private route, DNS, and trusted CA; never disable TLS validation |
| Compatibility tests | Pagination, throttling, renamed/deleted repos, revocation, source metadata | Installed API version, permissions, context path, custom certificates, pagination, throttling |
| Special files | Source API can redirect LFS files and identifies links/subrepositories | Confirm analogous behavior for installed version; do not follow it implicitly |

Cloud and Data Center are separate adapters, not a single base-URL substitution. Do not make legacy Cloud App passwords the integration baseline; current Atlassian documentation directs users to API tokens. Verify exact supported auth method, scopes, product entitlement, and expiry policy before implementation.

### Security and reliability contract

1. **Server-enforced access intersection.** Effective access is current user permission intersected with approved repositories, agent grants, workspace scope, and data policy. The LLM may select only from server-issued repository handles. It cannot supply the effective user, ACL, arbitrary endpoint, or credentials.
2. **Identity propagation.** Authenticate SimpleChat-to-service requests with a validated service identity and trusted, audience-bound, short-lived user context. Do not accept identity headers from a browser or model without verification. Repository read credentials remain in the broker/worker, not in prompts, URLs, the UI, or client-visible manifests.
3. **Authoritative repository authorization.** Implement provider-specific entitlement resolution. If a chosen integration token cannot determine user access, do not guess from SimpleChat group membership. The pilot may use a separately approved homogeneous audience only after the repository owner explicitly approves and owns that mapping.
4. **Revocation and cache safety.** Pilot: revalidate grants on every request, with no positive authorization cache across requests. Cache content only under repository ID, immutable commit, path, and policy context, and check authorization before returning it. Later auth caching requires an agreed maximum revocation delay. Failed ACL resolution denies source access; no stale-ACL fallback.
5. **No execution.** Prefer read REST APIs over cloning. Do not run hooks, builds, package managers, tests, imports, notebooks, language-server plugins, or repository scripts. Do not follow symlinks, submodules, or LFS redirects by default. Static parsing must itself be sandboxed and resource-bounded.
6. **Storage isolation.** Never mount source snapshots into SimpleChat's runtime, plugin discovery, static-file, upload, or deployment directories. Use opaque storage names, not repository paths as filesystem destinations. Do not share cloud credentials with the main application.
7. **Network controls.** Admin-approved origins only; validate every redirect and pagination URL; prevent cross-origin authorization-header forwarding. Block metadata, loopback, link-local, and unapproved private destinations. Data Center private addresses require explicit policy, not a broad private-network exception. Enforce DNS/egress controls in the worker network, not only string checks.
8. **Data minimization.** Default-deny credentials, private keys, environment files, dumps, binaries, archives, generated outputs, dependencies, and unapproved large files. Use content/size/encoding checks and secret screening before persistence or embeddings. Exclusions and scanners reduce risk but cannot establish data classification or guarantee that code has no secrets.
9. **Prompt injection and tool composition.** Repository comments, README files, issue text, and instructions are untrusted evidence, never system instructions. Instructions in a repository cannot enable tools, change endpoints, or relax permissions. Keep the source agent's outbound capabilities restricted so a malicious source snippet cannot use another tool to export code.
10. **Derived-data policy.** Embeddings, summaries, answers, citations, caches, telemetry, and conversation exports inherit source sensitivity. No automatic public-workspace indexing, external sharing, agent memory, or workflow publication. For the pilot, restrict sharing/export of source-bearing conversations; later recipient access must be checked. Revocation cannot retract content already downloaded or seen.
11. **Stable provenance.** Each excerpt identifies provider, stable repository ID, immutable commit, path, start/end lines, and content hash. Pin a conversation task to a release commit; never mix moving branch revisions silently. Source links are built from approved origins and encoded components.
12. **Bounded work.** Enforce per-file, per-repository, per-run, concurrency, returned-line, token, and request-time limits. Set pilot limits from the actual repository inventory, not guessed production capacity. Handle retries with backoff and throttling; jobs are idempotent.
13. **Failure isolation.** Separate workers/queues and budgets prevent a large repository or Bitbucket outage from exhausting the chat process. Explicitly report "source context unavailable" rather than invent a source-backed answer. Ordinary non-source chat stays available.
14. **Audit without source dumps.** Log principal, operation, opaque repo/commit reference, authorization decision, result count, duration, and correlation ID. Preserve existing shape-only result summaries where applicable. Validate parameters, exceptions, traces, tool histories, exports, and debug paths so no source or credentials leak through logging.

### Proposed read-only action contract

Expose only capabilities such as:

- List repositories available to this user/agent.
- Resolve an approved branch/tag to a commit.
- List a bounded tree at that commit.
- Search exact identifiers, paths, error strings, and optionally semantic descriptions.
- Read bounded line ranges from a validated file at that commit.
- Later, compare two authorized commits with bounded diffs.

Responses must carry success/error status, source revision, precise citations, truncation indicators, and freshness information. No write, commit, PR creation, shell, arbitrary URL-fetch, or file-upload operation belongs in the initial contract.

For troubleshooting, require the deployed release/commit and sanitized error context. Repository evidence supports possible causes, not proof of runtime state. A suggested fix remains a human-reviewed recommendation; any future telemetry connector is separately permissioned and is not included automatically.

### SimpleChat integration surfaces

| Existing surface | Proposed use | Boundary to preserve |
|---|---|---|
| Plugin/action loader and action catalog | Thin action exposing the approved source API | Never import retrieved source as plugins |
| Governed action loading / workspace identities / MCP destination policy | Reuse app-side action permission and credential patterns | These do not replace Bitbucket ACL enforcement |
| Document search and citation annotation patterns | Consistent source cards and evidence presentation | Code citations need commit/path/line semantics, not invented document page numbers |
| File Sync configuration patterns | Reuse UX concepts such as source status, schedule, pause, and errors | Do not automatically reuse broad document ingestion or its deletion defaults |
| Chat history, collaboration, exports, memory, workflows | Explicit classification and recipient handling | No widening of the audience through derived content |
| Settings sanitization and operational logging | Expose safe configuration/status only | Credentials and raw source stay out of browser settings and ordinary logs |

A remote MCP action can be the thin integration if the existing transport and trusted-user propagation satisfy the contract. A dedicated typed plugin is an alternative when a generic MCP configuration would expose excess operations or lack user-context guarantees. MCP is a transport, not a security boundary.

### Delivery waves and acceptance evidence

| ID / priority | Outcome | Entry criteria | Exit / acceptance evidence | Effort / risk / owner |
|---|---|---|---|---|
| ACT-001 / Now | Agree scope and data/identity contract | Repository and security owners engaged | Edition, approved repo audience, cloud/region/data processing, source retention, release mapping, limits, and rollback approved | S / High / Product + security + Bitbucket owners |
| ACT-002 / Next | Isolated read-only vertical slice | ACT-001 | One repository; read/tree/search operations; exact commit/line citations; no writes; denied-user tests; credentials absent from logs/UI | M / High / Integration + identity engineers |
| ACT-003 / Next | Representative troubleshooting pilot | ACT-002 | Golden questions cover error-to-code lookup, config flow, dependencies, and unsupported questions; source inspection versus hypothesis is clearly distinguished | M / Medium / Application SME + QA |
| ACT-004 / Later | Indexed, incrementally updated snapshots if justified | Successful pilot plus approved derived-data storage | Atomic promotion, deletion/rename handling, revocation during sync, no mixed revisions, failed jobs leave previous validated snapshot intact | L / High / Retrieval + platform engineers |
| ACT-005 / Before wider release | Regression and abuse-case release gate | Relevant pilot/indexed implementation ready | All gates below pass; documented operation, retention, disable/delete procedures, owner sign-off | M / High / QA + security + operations |

Release gates:

- Zero unauthorized excerpts, filenames, search counts, citations, or cached results in the negative-access test set, including a user removed mid-session.
- Zero repository writes and no repository-origin code execution in the pilot.
- All returned citations resolve to the exact indexed/fetched content and immutable commit; no unsupported line numbers.
- Secret canaries excluded from indexed/model-bound content and all observability/export surfaces.
- Malicious instructions, cross-origin redirects, submodules, symlinks, archives, path traversal, large files, and rate limits remain contained.
- Turning the feature off makes no Bitbucket/source-service calls. Existing chat, agents, documents, citations, uploads, and history pass their baseline regression cases.
- Under a bounded ingestion stress test, existing-chat p95 latency degradation is no more than a proposed 5% versus the same-load baseline, and error rate remains within the existing SLO. Platform/product owners must approve or replace this target before testing.
- Proposed pilot quality target: relevant source in the first five results for at least 90% of the SME-authored answerable question set; every unsupported question is labeled rather than given invented source citations. Approve the dataset and target before treating this as acceptance.

Rollback: disable source action and ingestion independently, revoke integration credentials, retain or delete snapshots under the approved policy, invalidate source caches, and retain ordinary chat behavior. Do not downgrade authorization or turn off global secret storage as a rollback technique.

### AI suitability

| Branch | Fit |
|---|---|
| Generative AI / NLP | Evidence-grounded explanation and troubleshooting with human review; retrieval preferred to training |
| Deterministic automation / rules | Best fit for synchronization, authorization, exclusions, file validation, freshness, and exact-symbol lookup |
| Machine learning ranking | Optional later if deterministic retrieval fails agreed evaluation; no assumed training-data readiness |
| Neural networks | Already intrinsic to the selected language/vision model; no separate custom network justified |
| Expert systems | Static diagnostic rules may help known error patterns; rules remain auditable and never delegate permission decisions to a model |
| Fuzzy logic | Not applicable: no supported requirement |
| Physical robotics / autonomous operation | Not applicable to this feature; no control or remediation actions proposed |

For AIO-001/AIO-002 and the source assistant, data owners supply approved knowledge and imaging cases; application/imaging SMEs own correctness labels. Required controls include minimization, auditability, human oversight, uncertainty reporting, incident handling, rollback, evaluation after model updates, and cost budgets. Cost tendency is low for deterministic retrieval, increasing with indexing/embeddings and image reinspection. Source delivery risk is High; math is lower; image root-cause confidence remains Low until matched requests are tested.

## 2. V1 LaTeX mathematics: much smaller implementation

### Current behavior and reproduced issue

The answer in the first screenshot contains recognizable TeX but no typeset fractions or matrices. V1 processes assistant content through citation/table transformations, then `DOMPurify.sanitize(marked.parse(...))`.

A local check against the installed Marked asset produced:

| Input | Markdown result |
|---|---|
| `\[ x_n = \frac{X_c}{Z_c} \]` | Literal brackets and raw `\frac`, without the `\[` delimiters |
| `\( x_n \)` | Literal parentheses, not math |
| A `bmatrix` with `\\` row separators | Row separators reduced to single backslashes |

Therefore a DOM auto-render pass added only after Marked cannot reliably recover the original expression. This is a parser/renderer integration issue, not something a "use better fonts" prompt can solve.

### Recommended approach

1. Add an independently switchable math-display capability; retain the raw Markdown/TeX in storage and model history.
2. Vendor pinned KaTeX JavaScript, CSS, fonts, and licenses locally. No CDN, remote typesetting service, server-side TeX compiler, or model change.
3. Use math-aware tokenization before citation/table preprocessing and Marked, preserving the complete math span. Skip code fences, inline code, link destinations, and escaped literal delimiters. Do not use a global regex that rewrites every backslash or bracket.
4. Support `\(...\)`, `\[...\]`, and display `$$...$$` initially. Leave single-dollar inline math off unless requested, to protect currency and existing content.
5. Keep DOMPurify for ordinary model-generated HTML. Render preserved math into dedicated, non-executable placeholders using the typesetter's safe API. Do not broadly relax the HTML sanitizer or enable trusted TeX commands.
6. Use `trust: false`, finite expansion/size limits, per-expression input limits, and fresh macro state per message. Unsupported expressions remain safely escaped text with a visible rendering indication, not a broken chat turn.
7. Reuse the shared assistant renderer for live, final, and history/reload paths. During streaming, leave incomplete expressions as text and typeset complete spans at a bounded cadence or finalization. Handle retry, collaboration, and partial error responses consistently.
8. Preserve copy-raw/copy-Markdown behavior; ensure rendered selection/copy does not duplicate hidden MathML. Provide MathML/accessibility support, horizontal overflow for wide matrices, dark-mode readability, font scaling, and screen-reader testing.
9. Treat displayed equations, formula extraction, and exported editable equations as different capabilities. Existing DI formula extraction is an opt-in ingestion feature; it does not provide browser math rendering.

### KaTeX versus MathJax

| Option | Fit and tradeoff |
|---|---|
| KaTeX, recommended baseline | Synchronous rendering and documented untrusted-input controls; suitable for the pictured fractions, vectors, and matrices if the agreed formula corpus passes. Supports HTML plus MathML. |
| MathJax | Consider for a formula corpus or accessibility workflow that needs its features. Dynamic typesetting needs explicit lifecycle handling; current documentation recommends promise-based typesetting, with font/extension assets kept local. |

Neither library is a full LaTeX document editor or proof that the mathematical answer is correct.

### Validation and relative difficulty

| Scope | Relative effort | Delivery risk | Reason |
|---|---|---|---|
| V1 display-only mathematics | S | Low-Medium | Existing shared renderer; localized parser/assets/styles work |
| Math including live/history/copy/accessibility regression coverage | S-M | Medium | Streaming delimiters, code/currency collisions, sanitizer interaction |
| Math parity in HTML/PDF/DOCX exports | M-L, separate increment | Medium | Server export pipelines and editable equation formats differ from browser DOM |
| Safe Bitbucket read-only pilot | M-L | High | Two providers, identity, network, trust boundaries, provenance |
| Production source snapshots/indexing with revocation and lifecycle | L-XL | High | Distributed state, permissions, derived-data retention, fault isolation |
| Image diagnosis | S-M investigation | High uncertainty | Local paths are understood; endpoint parity and original assets are missing |

These are relative engineering assessments, not calendar, staffing, cost, or delivery commitments.

Math acceptance: all approved formula examples render on initial completion, stream completion, reload, and retry; code and currency remain unchanged; hostile TeX cannot load resources or create executable markup; existing citations/tables/charts/images still work; long formulas stay within the message layout; screen-reader review passes agreed criteria. Rollback disables math display while retaining unchanged source text.

## 3. Image investigation

### What the second screenshot establishes

The displayed thumbnail contains a discernible grayscale indoor scene: floor tiles, walls/equipment, checkerboard-like targets, and dark floor markings. It is not visually a completely blank white image.

That establishes a discrepancy between the displayed preview and the answer. It does not establish the exact bytes given to a model, the original bit depth or dynamic range, whether the UI performed color management, or whether the reply was based on pixels at all. The `.lossy` text in a filename is not proof of the actual encoding.

The reported Example 3 is not available as before/after originals. Adding text changes pixel statistics, structure, and the information available to OCR and attention. It might alter service processing or retrieval behavior, but it does not prove a cropper is deleting white regions. If a region is actually clipped to pure white, added text cannot recover its lost image information.

### Verified current paths

| Stage | Observed behavior | Meaning |
|---|---|---|
| Browser chat upload | Places the selected File directly in FormData | No resize/recompression observed on this upload path |
| Backend upload | Saves uploaded file to a temporary path | Not itself image re-encoding |
| Standard extraction | DI read/layout receives bytes or a base64 representation | Extracts information; OCR absence is not image blankness |
| Enhanced extraction | May use Content Understanding, falling back to DI layout | Different services/configurations can yield different text; record actual engine/fallback |
| Optional vision enrichment | Reads bytes, base64 encodes, sends `image_url`; no explicit `detail` | No contrast/resize/JPEG conversion observed here; service detail handling remains relevant |
| Workspace processing | Vision metadata appended to stored chunk text; empty extraction chunks can be skipped | A bad description can become persistent evidence; a no-text image may be poorly represented |
| Answering and history | Workspace search supplies text/citations; uploaded-image history supplies OCR/vision text | The final selected chat model may not inspect original pixels |
| Image gallery | Independently serves original stored blob content through citation route | Seeing a good thumbnail does not validate the inference input |

Other paths, such as document rendering, embedded Office media, generated images, logos, and third-party gateways, must be evaluated separately if the customer's upload used them. Do not apply findings about logo resizing to ordinary camera images.

### Hypotheses ranked for investigation, not declared causes

1. **Earlier description reused instead of current pixel inspection.** Strong repository evidence for the mechanism; match the stored caption/chunk to the incorrect answer.
2. **Ingestion and answering use different deployments/routes/settings.** The legacy ingestion helper and multi-endpoint admin test are different paths. The label GPT-5.1 alone is insufficient.
3. **Implicit detail mode and service-side image interpretation.** Azure documents `low`, `high`, and default `auto`; compare explicit settings rather than assume `auto` is adequate. `high` can help detail but is not an original-pixel guarantee or a promised fix.
4. **Extraction engine, MIME, or no-OCR behavior.** Validate DI/CU selection, actual content type, empty chunks, and fallback. Added text might improve extraction/retrieval even without any pixel cropper.
5. **Original-file decoding differences.** Compare bit depth, grayscale/RGB, ICC/gamma metadata, alpha, orientation, dimensions, and bytes. A PNG screenshot does not establish parity with a scientific source image.
6. **Gateway or platform/model differences.** Possible but unproven. Foundry reproduction makes a SimpleChat-only explanation less likely for the overall complaint, but does not prove all environments sent identical bytes or settings.

### Controlled diagnostic procedure

| Step | Action | Evidence and interpretation |
|---|---|---|
| ACT-006 | Obtain an approved original and the Example 3 pair; preserve originals read-only | File SHA-256, byte count, actual format, dimensions, bit depth, color/alpha/profile metadata; use a protected evidence store |
| ACT-007 | Capture stage provenance without turning on unrestricted payload logging | App commit/version, upload path, artifact ID/version/hash, extraction engine/fallback, ingestion model/deployment, answering model/deployment, API version/protocol, detail mode, gateway route, time and request IDs |
| ACT-008 | Compare bytes before upload, after backend receipt, in blob storage, and decoded from the actual outbound vision payload | First divergent hash identifies a file-byte transformation boundary. Equal hashes rule out file-byte mutation before service entry, not internal model processing |
| ACT-009 | Inspect approved stored OCR, vision metadata, and indexed chunks | Determine whether "blank/white" originated at ingestion and whether the final model received an image part or just that description |
| ACT-010 | Run a minimal fresh-session direct vision request on the approved customer endpoint, with the original byte-identical image and neutral prompt | Compare `auto` and `high`; optionally `low` as a control. Keep deployment/version and all supported generation settings fixed |
| ACT-011 | Compare SimpleChat ingestion, SimpleChat answer path, Foundry, and the successful internal environment | One image per request, same prompt/settings/history, same hashes; record both ingestion and answering outputs where applicable |
| ACT-012 | Repeat trials and score blinded against imaging-SME ground truth | Pre-agree trials and metrics: false-blank rate, required-feature recall, false detections, and correct uncertainty. A single improved response is not validation |
| ACT-013 | If matched direct API calls still fail, prepare a minimal support case | Approved originals or non-sensitive repro, hashes, deployment/version/region, exact request parameters, times/request IDs, repeatability, and differential results; share only through approved support channels |

Interpretation:

- Original bytes work through direct API, but stored ingestion caption is wrong: focus on ingestion route, settings, model, and reprocessing.
- Ingestion caption is right, but final answer is wrong: inspect history, retrieval, scope, truncation, and grounding.
- Same approved original works with `high` but not `auto`: validate an explicit per-feature high-detail setting, with cost/latency measurements.
- All byte-identical direct requests to one deployment fail, but another succeeds: investigate deployment/model/configuration differences with the service owners.
- No image content part is sent in the final request: that is a text-grounded answer, not evidence of the final model's visual perception.

Do not bypass required production network or safety controls for testing. If direct access is not approved, use an approved isolated diagnostic route.

### Potential future changes, conditional on results

- Add explicit vision-detail configuration to the ingestion request, defaulting only after evaluation. Show which model actually performed vision analysis.
- Unify ingestion endpoint resolution with the reviewed model-routing path instead of trusting the chat selector or connection-test button.
- Preserve originals and make any normalized/enhanced variant an explicitly labeled derivative with transformation parameters and hashes.
- Add a separately authorized "inspect original image" operation for selected image questions, with bounded image counts and service limits, rather than attaching all images to every turn.
- Store extraction failure, no OCR, no description, and genuinely blank image as distinct states. Ensure vision-only images can be represented without requiring invented OCR.
- Replace/reindex stale descriptions and invalidate dependent retrieval caches after a validated change. Historical answers do not correct themselves.
- If contrast normalization/crops are useful, make them opt-in, reversible, and scientifically validated; retain the full-image context and coordinate mapping. No generative enhancement, annotation hacks, or silent replacement of evidence.

## Hard gates

- No source ingestion until approved data rights/classification, cloud/region/model eligibility, identity mapping, and retention are established.
- No source release without negative authorization tests, fault isolation, commit/line fidelity, and derived-content audience controls.
- No mission-critical reliance on the image capability until representative low-contrast cases meet imaging-owner-approved criteria with human oversight and a fallback.
- No claim that `detail: high`, a changed prompt, or preprocessing fixes this incident without matched-input evaluation.
- No math rollout that weakens global HTML sanitization, loads Internet runtime assets, or corrupts stored/copyable TeX.
- Missing availability/recovery requirements remain a wider source-service production-readiness gate; the pilot does not imply operational approval.

## Risks, fallback, and operational ownership

| Risk | Control / fallback | Owner |
|---|---|---|
| Source prompt injection affects other tools | Restricted source-only agent; separate network/runtime; server-side operation allowlist | Security + application |
| Deleted/revoked source remains in derived stores | Request-time authorization, tombstones, cache/index lifecycle, restricted sharing/export, documented retention | Data + identity |
| Stale branch gives misleading diagnosis | Release-to-commit mapping; immutable citations; explicit staleness indicator | Application/release |
| Ingestion exhausts shared capacity | Independent workers, bounded queues, service quotas/budgets, stress tests | Platform |
| Renderer breaks existing Markdown or accessibility | Independent feature flag, raw-source preservation, corpus/regression testing | Frontend + accessibility |
| False blank image becomes trusted evidence | Direct original reinspection when approved, provenance, SME evaluation and human fallback | Imaging + model operations |
| Diagnostics leak source/images | Metadata-only ordinary logs; restricted opt-in evidence capture and support sharing | Security + support |

CAF/WAF alignment: data/identity approval establishes governance; isolated least-privilege services support Security; bounded workers and independent rollback support Reliability; provenance and runbooks support Operational Excellence; selective retrieval and image detail budgets support Cost Optimization; incremental indexing and load gates support Performance Efficiency.

## Scorecard and overall confidence

This assessment does not assign a general migration-readiness percentage or an application-security certification.

| Evaluated area | Readiness score | Evidence coverage |
|---|---:|---|
| Existing V1 math rendering capability | 0/4: absent on inspected path | High; source plus parser reproduction |
| Proposed Bitbucket production capability | NE | Extension points verified; implementation and customer controls unverified |
| Low-contrast image fitness for mission use | NE | App data path verified; originals, matched requests, and accuracy evidence missing |
| Preservation of ordinary chat after proposed changes | NE | Requires implementation-specific regression and stress tests |

Overall production readiness is **Incomplete**; no aggregate is calculated from this bounded feature assessment. Strong confidence in the observed code paths must not be confused with confidence in the customer's incident root cause.

## Evidence appendix

Line locations refer to the assessed working tree and may shift as existing changes evolve.

| ID | Source and relevant lines |
|---|---|
| E01 | [File Sync](../../application/single_app/functions_file_sync.py), lines 84-110: known/implemented provider registry; 142-169: governance and run-limit patterns |
| E02 | [Plugin loader](../../application/single_app/semantic_kernel_plugins/plugin_loader.py), lines 10-30: dynamic module import/discovery |
| E03 | [Document search action](../../application/single_app/semantic_kernel_plugins/document_search_plugin.py), lines 18-84 and 137-170: metadata, authenticated user context, search/citation patterns |
| E04 | [Semantic Kernel loader](../../application/single_app/semantic_kernel_loader.py), lines 1295-1314 and 2295-2338; [MCP destination policy](../../application/single_app/functions_mcp_destinations.py), lines 675-755: governed loading, identity hydration, configured destination enforcement |
| E05 | [Assistant renderer](../../application/single_app/static/js/chat/chat-messages.js), lines 2754-2788 and 5830: preprocessing, Marked, DOMPurify, copy source, shared rendering |
| E06 | [Streaming renderer](../../application/single_app/static/js/chat/chat-streaming.js), lines 1370-1373, 1489-1491, 1619-1620 |
| E07 | [Base template](../../application/single_app/templates/base.html), lines 672-674; [local browser asset rules](../../.github/instructions/local_browser_assets.instructions.md); [Marked](../../application/single_app/static/js/chat/marked.min.js): current runtime and local parser test |
| E08 | [Vision request](../../application/single_app/functions_documents.py), lines 5809-5970: raw-byte base64, legacy endpoint settings, separate model selection, no explicit detail |
| E09 | [Image processing and indexed text](../../application/single_app/functions_documents.py), lines 9178-9210 and 3632-3670 |
| E10 | [Workspace search augmentation](../../application/single_app/route_backend_chats.py), lines 18643-18713 and 23219-23299 |
| E11 | [Uploaded-image history](../../application/single_app/route_backend_chats.py), lines 26973-27013 |
| E12 | [Workspace gallery](../../application/single_app/static/js/chat/chat-inline-images.js), lines 80-86, 236-242, 690-695; [image citation delivery](../../application/single_app/route_enhanced_citations.py), lines 262-295 and 1197-1275 |
| E13 | [Admin vision test](../../application/single_app/route_backend_settings.py), lines 1401-1476; [connection-test wiring test](../../functional_tests/test_multimodal_vision_multi_endpoint_connection.py) |
| E14 | [Image chunk gates](../../application/single_app/functions_documents.py), lines 9259-9263 and 9315-9340 |
| E15 | [DI request](../../application/single_app/functions_content.py), lines 443-510: bytes/base64, content type, optional formula extraction |
| E16 | [Extraction engine selection](../../application/single_app/functions_content.py), lines 618-685; [Content Understanding byte submission](../../application/single_app/functions_content_understanding.py), lines 173-208 |
| E17 | [Browser upload](../../application/single_app/static/js/chat/chat-input-actions.js), lines 682-713; [backend upload](../../application/single_app/route_frontend_chats.py), lines 1119-1127 and 1428-1500 |
| E18 | [Image decoding tests](../../functional_tests/test_base64_image_handling.py); [image serialization](../../application/single_app/functions_image_messages.py), lines 214-220 |
| E19 | [Plugin log summaries](../../application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py), lines 254-280: shape-only result summaries; validate all other data surfaces separately |

Official documentation accessed 2026-09-30:

- [Azure vision-enabled chat and detail levels](https://learn.microsoft.com/azure/foundry/openai/how-to/gpt-with-vision)
- [Bitbucket Cloud source API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-source/)
- [Bitbucket Cloud repository access tokens](https://support.atlassian.com/bitbucket-cloud/docs/repository-access-tokens/)
- [Bitbucket Cloud API tokens](https://support.atlassian.com/bitbucket-cloud/docs/api-tokens/)
- [Bitbucket Data Center HTTP access tokens](https://confluence.atlassian.com/bitbucketserver/http-access-tokens-939515499.html)
- [Bitbucket Data Center REST repository API](https://developer.atlassian.com/server/bitbucket/rest/v1000/api-group-repository/) -- actual adapter version remains customer-dependent.
- [KaTeX security](https://katex.org/docs/security.html)
- [KaTeX options](https://katex.org/docs/options.html)
- [MathJax dynamic typesetting](https://docs.mathjax.org/en/latest/web/typeset.html)

Application version remains `0.261.046`; this planning-only deliverable does not change runtime versioning.
