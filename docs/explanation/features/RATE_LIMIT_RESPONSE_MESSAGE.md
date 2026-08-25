# Rate Limit Response Message

## Overview

SimpleChat returns HTTP 429 from several unrelated places. Before this feature each of those places carried its own hard-coded string, so a throttled user got a different, and usually unhelpful, explanation depending on which surface they happened to hit. In chat the situation was worse: an exhausted 429 never became a real 429 at all, and the user saw the generic streaming failure message instead.

This feature introduces a single admin-configurable, Markdown-capable message that is resolved from one place and used by every 429 the application returns.

**Version implemented:** 0.261.001

**Related issue:** [#1354](https://github.com/microsoft/simplechat/issues/1354)

**Dependencies:** none beyond what the application already ships. Markdown rendering reuses `markdown2` and `bleach` on the server, and the locally vendored `marked` and `DOMPurify` in the browser.

## Why it exists

The driver is deployments that front their model endpoints with Azure API Management. Throttling there is a deliberate capacity decision, not a fault. SimpleChat already retries 429s with backoff, which absorbs the transient cases, but retries eventually run out. At that point the user needs to be told that throttling is what happened, roughly how long to wait, and who to contact for more capacity. None of that is knowledge the application has; it belongs to the admin.

## Technical specifications

### Settings

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enable_custom_rate_limit_message` | boolean | `False` | When off, the built-in default message is used. |
| `rate_limit_message` | string (Markdown) | Built-in default | The message shown to a throttled user. |

Both keys are non-sensitive and pass through `sanitize_settings_for_user()` unchanged.

### Resolution

`functions_rate_limit.py` is a leaf module with no imports, which lets any surface depend on it without risking a circular import.

| Function | Purpose |
| --- | --- |
| `normalize_rate_limit_message(value)` | Normalizes line endings, trims, bounds to 3000 characters, and substitutes the default when blank. |
| `build_rate_limit_message(settings)` | Returns the message to display, honoring the toggle. |
| `build_rate_limit_error_payload(settings, **extra)` | Returns the JSON body, including `rate_limited: true`. |

`functions_settings.get_rate_limit_message(settings=None)` wraps the resolver and looks settings up when a caller does not already hold them.

The message is always returned as raw Markdown. Rendering is left to the caller because the surfaces differ: the chat client parses it with `marked`, while server-rendered pages use the existing Jinja `markdown` filter.

### Fallback behavior

A throttled user never receives an empty response. The built-in default is used when the toggle is off, when the stored message is blank or whitespace, and when settings cannot be read as a dictionary.

### Surfaces

| Surface | File | Behavior |
| --- | --- | --- |
| Chat streaming | `route_backend_chats.py` | An exhausted throttle is classified by `is_rate_limit_error()` and emitted as a stream error carrying `rate_limited: true` and `status_code: 429`. The persisted message metadata records `error: 'rate_limited'`. |
| Chat image generation | `route_backend_chats.py` | Returns 429 with the message and `rate_limited: true`. |
| Text to speech | `route_backend_tts.py` | Returns the shared payload once retries are exhausted. |
| Swagger specification | `swagger_wrapper.py` | `swagger.json` and `swagger.yaml` return the shared payload with `retry_after` set from the cache's rate-limit window. |
| Inbound MCP | `route_inbound_mcp.py` | JSON-RPC error `-32029` carries the message in the human-readable `message` field while `data` keeps the structured limit, window, and reset values so clients can still back off. |
| Anything else | `app.py` | An `@app.errorhandler(429)` covers `abort(429)` and any 429 raised inside the stack. |

### Content negotiation

The global handler returns JSON when the request path starts with `/api/` or `/external/`, when `X-Requested-With` is `XMLHttpRequest`, or when the client accepts JSON but not HTML. Otherwise it renders `templates/errors/429.html`. If that render fails the handler falls back to the raw Markdown as `text/plain`, so the message still reaches the user. A `Retry-After` header is set when a retry window is known.

### Frontend

`chat-streaming.js` special-cases `rate_limited` in `appendStreamErrorBanner`. The banner switches to an hourglass icon and a "Rate limited:" heading, and the body is rendered with `DOMPurify.sanitize(marked.parse(...))`. Every other stream error keeps its existing `createTextNode` rendering, so this change cannot widen the blast radius of other error messages.

The accompanying toast uses `toPlainTextSummary()` to strip Markdown syntax down to a short single-line summary, because raw Markdown in a toast is unreadable.

## Usage

1. Open **Admin Settings → Security → Rate Limiting**.
2. Turn on **Use a custom rate limit message**.
3. Write the message in the Markdown editor. Links are supported, so an internal runbook or capacity request form can be linked directly.
4. Save.

Leaving the toggle off, or saving an empty message, restores the built-in default.

## Testing and validation

`functional_tests/test_rate_limit_message_configuration.py` covers the default settings keys, the toggle and blank-message fallbacks, length bounding, payload shape, sanitization passthrough, admin persistence, tab and pane registration, and the frontend rendering path.

Documentation coverage is enforced by `functional_tests/test_docs_app_surface_coverage.py`, which requires the `{#rate-limiting}` anchor on `docs/admin/security.md` and a claim for `enable_custom_rate_limit_message` in `docs/_data/features.yml`.

### Known limitations

- Rate limits enforced at the edge, such as an Azure Front Door WAF rule or an API Management policy that rejects a request before it reaches the app, cannot be customized here. The request never arrives, so SimpleChat has no opportunity to render the message.
- The message is global. There is no per-workspace, per-group, or per-endpoint variant.
- This feature changes only what a user is told when a 429 happens. It does not add or configure any rate limit thresholds.
