# Microsoft Web IQ discovery (0.261.405)

Implemented in version: **0.261.405**

Application version: `application/single_app/config.py`. Associated issue: [#1887](https://github.com/microsoft/simplechat/issues/1887).

## Overview

Microsoft Web IQ is a V2 alternative to Foundry Grounding with Bing Search. It supplies public evidence to the selected answer model, rather than acting as a separate answer-writing agent. Existing installations default to Foundry, and switching providers does not delete the inactive connection or authorize a fallback.

News, Image, and Video discovery are opt-in additions. They help identify announcements, visual examples, and tutorials when those sources suit the task. These are Gather capabilities, not image generation, image inspection, or video transcription.

## Dependencies and service boundary

Web IQ requires service access, a billing account, portal onboarding, provider-specific consent, and either an API key or an app-only Entra service principal bound to a Web IQ AppID. The Entra client ID and Web IQ AppID are different identifiers.

Search goes to the fixed Microsoft-hosted `https://api.microsoft.ai/v3` endpoint. An Azure billing resource does not imply a private endpoint or hosting-cloud residency. Government and custom-cloud deployments do not offer either public search provider or Content Understanding through the optional-service deployment choices.

Web IQ Browse and Auto are not dependencies. Deep Research and direct URL Access continue to share SimpleChat's existing page reader and traversal policy.

## Runtime architecture

`functions_web_iq.py` is independent of application bootstrap. It validates configuration, consent, result types and limits, acquires credentials only at invocation, and normalizes typed provider responses. `route_backend_chats.py` dispatches through the shared search boundary for manual and orchestrated research.

| Discovery type | Endpoint | Evidence |
| --- | --- | --- |
| Web | `/search/web` | Query-focused passages and public source links |
| News | `/search/news` | News passages with optional publisher/crawl/update metadata |
| Image | `/search/images` | Provider captions and image host-page citations |
| Video | `/search/videos` | Provider descriptions/summaries, source-page citations, and optional moments |

Web/News requests explicitly use passage format. SafeSearch is strict where the endpoint supports it; News does not receive unsupported SafeSearch parameters. Queries over 1,000 characters fail explicitly. Result counts share the configured request budget across selected types, and Deep Research limits query variants against its total endpoint-call budget.

Responses are streamed into a bounded buffer. Redirects are not followed with credentials. Authentication, malformed response, timeout, connection, and HTTP failures are distinct from a successful empty response. At most one additional attempt is allowed for throttling/service-unavailable responses with a short numeric `Retry-After`; cancellation is checked during waits and reads.

## Configuration and delivery policy

| Setting | Meaning |
| --- | --- |
| `web_search_provider` | `foundry` or `web_iq`; existing installations default to Foundry |
| `web_iq_consent_accepted` | Separate acknowledgement for Web IQ |
| `web_iq_news_enabled` | Authorizes News discovery |
| `web_iq_image_mode` | `off`, `text_only`, or `with_media` |
| `web_iq_video_mode` | `off`, `text_only`, or `with_media` |
| `web_iq` | Private connection, authentication, language/region, result and passage limits |

New result types default off. Text-only retains descriptions and titled source-page links, never preview resources. With media permits selected answer media with attribution; it does not display every retrieved item. Hosting-page video URLs are not passed blindly to the direct-file player. Provider HTML and player scripts are not admitted.

The entire private connection is removed from public settings. Result provenance retains provider, source kind, retrieval time, and original media mode; changing administrative policy later does not relabel old results. Generated captions and summaries remain explicitly marked as provider metadata, and crawl/update dates are not represented as publication dates.

Key Vault-backed credentials use scoped, staged references rather than storing resolved values in Cosmos. Runtime reads resolve only the Web IQ global credential namespace, fail closed when retrieval is unavailable, and privately capture the resolved credential so a rotation changes the configuration proof. No Key Vault access occurs at application bootstrap.

## Gather, research, and retained results

`functions_orchestration_registry.py` projects the active provider, enabled result types, and media modes before planning. Web Search and Deep Research accept an optional `result_types` argument. Omitting it preserves ordinary web discovery for old query-only plans. The validator and provider enforce actual server policy rather than trusting planner inputs.

News suits current-announcement evidence; Images suit visual examples; Videos suit demonstrations and tutorials. Availability is permission to choose a useful type, not an instruction to call all endpoints. Manual discovery adds types only for explicit current-message intent.

The external-configuration attestor records the actual Web IQ connection, consent, enabled state, cloud, and delivery policy in private configuration proofs. Public result references do not include credentials. The existing authorization and current-source reader remain in charge of admission and recovery, including Deep Research's planner and traversal configuration.

Search results seed the existing reader; fetched child pages are not manufactured Web IQ results. Typed search metadata is preserved when reviewed-source details are merged into citations.

## Deployment and onboarding

The optional-service AZD/Bicep path is documented alongside its deployer configuration. Resource creation and runtime readiness are separate. Missing Web IQ portal binding or credentials must leave search pending and disabled; no ARM key/AppID endpoint is assumed.

Content Understanding is an independent Enhanced-extraction option. It requires usable model/default/analyzer configuration, not just a provisioned account. Document Intelligence remains available as the existing fallback.

New classic Foundry project/Bing connection/agent creation is not automated in this change. The deployer can configure an existing compatible setup. Microsoft's classic Agents API is deprecated and retires March 31, 2027; this change does not silently migrate the application to a different Agents runtime.

## Validation and limitations

`functional_tests/test_web_iq_provider.py` exercises typed requests, opt-in modes, cloud and consent rejection, auth/AppID handling, budgets, malformed responses, bounded retries, safe URLs, Gather projection, and private configuration revisions.

`functional_tests/test_web_iq_research.py` uses the network-blocked application bootstrap and actual chat/adapters/capture/retention readers to exercise manual V2 gating, current-message-only egress, typed Gather output, shared research traversal, and recovered research results.

These tests use synthetic transport responses. They do not prove subscription eligibility, live endpoint permissions, production relevance, paid-provider billing, or an Azure deployment. Media discovery grants no licensing or reuse rights, and provider descriptions do not prove that SimpleChat inspected media.

## User and administrator references

- [Knowledge settings](../../admin/knowledge.md)
- [Use web search](../../guides/use-web-search.md)
- [Use Deep Research](../../guides/use-deep-research.md)
- [Microsoft Web IQ portal deployment](https://learn.microsoft.com/en-us/web-iq/get-started/deploy-azure-portal)
