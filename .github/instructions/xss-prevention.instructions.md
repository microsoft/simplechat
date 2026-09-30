---
applyTo: '**/*.js, **/*.html, **/*.py, **/*.ts, **/*.tsx, **/*.jsx, **/*.mjs'
---

# Security: XSS Prevention and Browser Rendering

## Critical Requirement

**NEVER pass untrusted data into browser HTML or JavaScript execution sinks without an explicit safe boundary.**

Treat all of the following as untrusted unless the code proves otherwise:

- User profile fields, workspace names, group names, agent names, document titles, filenames, tags, descriptions, emails, and ids
- API response values returned from storage, Microsoft Graph, Cosmos DB, Azure AI Search, or any plugin/tool response
- Markdown, rich text, uploaded text files, generated summaries, model output, and any server-returned error string

## Preferred Safe Patterns

Use these patterns by default:

- Create DOM nodes with `document.createElement(...)`
- Set untrusted text with `textContent`
- Set trusted static classes with `className`
- Use `setAttribute(...)` or `dataset` for inert data only when DOM node creation is not practical
- Attach behavior with `addEventListener(...)`
- Normalize dynamic HTTP links with a helper such as `sanitizeHttpUrl(...)` before assigning `href` or `src`
- Sanitize rendered markdown with `DOMPurify.sanitize(marked.parse(...))` before inserting HTML
- Keep static modal or card shells fully static, then populate untrusted fields with DOM APIs after creation

## Disallowed Patterns For New Code

Do not add new code that does any of the following with untrusted values:

- `innerHTML`, `outerHTML`, `insertAdjacentHTML`, or jQuery `.html(...)`
- Inline event handlers such as `onclick=`, `onerror=`, `onload=`, or `setAttribute('onclick', ...)`
- Dynamic interpolation into HTML attributes such as `href`, `src`, `title`, `style`, or `data-*`
- `javascript:` URLs
- `Markup(...)` in Python on untrusted content
- Jinja `|safe` on untrusted content
- `marked.parse(...)` output rendered without `DOMPurify.sanitize(...)`

## Safe Examples

### JavaScript

```javascript
const row = document.createElement('tr');
const nameCell = document.createElement('td');
nameCell.textContent = user.displayName || 'Unknown User';

const actionButton = document.createElement('button');
actionButton.type = 'button';
actionButton.dataset.userId = user.id || '';
actionButton.addEventListener('click', handleUserClick);

row.appendChild(nameCell);
row.appendChild(actionButton);
```

```javascript
const renderedHtml = DOMPurify.sanitize(marked.parse(markdownText || ''));
markdownContainer.innerHTML = renderedHtml;
```

### HTML / Jinja

```html
<button type="button" class="btn btn-primary user-action-btn" data-user-id="{{ user.id }}">
    Select
</button>
```

### Python

```python
return render_template(
    'page.html',
    title=page_title,
    items=items,
)
```

## Unsafe Examples

```javascript
row.innerHTML = `<td>${user.displayName}</td>`;
```

```javascript
button.setAttribute('onclick', `selectUser('${user.id}', '${user.displayName}')`);
```

```html
<a href="javascript:${payload}">Run</a>
```

```python
return Markup(user_supplied_html)
```

```html
{{ user_supplied_html|safe }}
```

## Static HTML Shell Exception

When a static HTML shell is genuinely simpler, it is acceptable only if:

- The HTML string is fully static
- It contains no `${...}` interpolation or dynamic concatenation
- Untrusted values are populated afterward with `textContent`, `setAttribute(...)`, or `dataset`

## React and TypeScript (V2 UI)

The V2 UI in `application/v2_ui/src` is React 18 with TypeScript. React removes most string-to-HTML risk, but not all of it, so the same trust-boundary thinking applies.

### What React 18 escapes

- Text rendered as JSX children, such as `<p>{message.text}</p>`, is inserted as text, never parsed as HTML.
- String values in attributes are escaped, so a quote in a value cannot break out of the attribute.

### What React 18 does not protect

- **URL-bearing props.** React 18 only logs a development warning for a `javascript:` URL in `href`, `src`, `action` or `formAction`; React 19 blocks it, React 18 does not. Treat these props, plus `srcDoc`, `xlinkHref` and router `to` on `Link`, `NavLink` and `Navigate`, as sinks.
- **`dangerouslySetInnerHTML`.** The value is parsed as HTML with no escaping.
- **Refs and DOM APIs.** `ref.current.innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `createContextualFragment`, and `DOMParser` output appended to the page all bypass React.
- **DOM URL properties.** `element.href`, `element.src`, `form.action`, `frame.srcdoc` and `setAttribute('href', ...)` are not React props, so React never inspects them.
- **Navigation.** `window.open(url)`, `location.href = url`, `location = url`, and `location.assign(url)` or `location.replace(url)` can run a `javascript:` URL with the page's origin.
- **String-to-code APIs.** `eval`, `new Function`, and `setTimeout`/`setInterval` with a string argument.

### Required patterns

- Render untrusted text as JSX children. Never route text through `dangerouslySetInnerHTML` to get formatting.
- Use `dangerouslySetInnerHTML` only with the output of `DOMPurify.sanitize(...)`, either inline or through a clearly named `const`. Rich renderers must also run their own safe mode first: KaTeX with `trust: false`, Mermaid with `securityLevel: 'strict'` and `htmlLabels: false`.
- Give every dynamic URL prop or navigation value one of these safe sources:
  - a literal, or a same-origin path built from a literal prefix and `encodeURIComponent(...)` segments;
  - a reviewed URL builder (the lists are `TS_SAME_ORIGIN_URL_BUILDERS` and `TS_HREF_URL_BUILDERS` in `scripts/check_xss_sinks.py`; add a builder there only after reviewing that it cannot return a script URL);
  - a `sanitize*Url`, `normalize*Url` or `safe*Url` helper;
  - a guard such as `isSafeOriginHref(url)` or an `http(s)` scheme test, in the same expression or in an enclosing `if` or early return.
- `iframe`, `script`, `embed`, `object` and worker sources are stricter. A pinned `https://host/` prefix or a same-origin path with encoded segments is fine; an arbitrary host or `//` is not.
- Keep `react-markdown` raw HTML off. Do not add `rehype-raw`, `allowDangerousHtml: true`, or a `urlTransform` that returns the URL unchanged; keep the default URL transform.
- `<img src>` and media sources are not script sinks, so the checker does not flag them. Still pass them through the same helpers when the value comes from a user.

### React examples

```tsx
<p>{message.text}</p>
<a href={isSafeOriginHref(link) ? link : undefined}>Open</a>
<Link to={`/workspace/${encodeURIComponent(workspaceId)}`}>Open workspace</Link>
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(renderedSvg) }} />
```

Unsafe, because nothing proves the value's scheme or origin:

```tsx
<a href={message.link}>Open</a>
<div dangerouslySetInnerHTML={{ __html: modelOutput }} />
window.location.href = searchParams.get('next') ?? '/';
```

### Suppressions in TypeScript

In `.ts`, `.tsx`, `.jsx` and `.mjs` files the suppression token counts only when a reason follows it on the same line. Put it within four lines above the finding:

```tsx
{/* xss-check: ignore reviewed: value is restricted to https URLs before it is stored */}
<a href={agent.homepage}>Homepage</a>
```

A bare token does not suppress anything; the finding stays and says the reason is missing.

## PR Review Checklist

For any JavaScript, TypeScript, HTML, or Python change that affects browser rendering:

1. Identify the trust boundary for every value that reaches the browser.
2. Prefer DOM node creation and `textContent` for untrusted text; in React, render it as JSX children.
3. Normalize dynamic URLs before assigning them to clickable or loadable attributes, React props, or navigation calls.
4. If HTML rendering is required, document the sanitizer boundary explicitly.
5. Add or update a regression test when untrusted data reaches a browser-rendering path.

## Workflow Guardrail

This repository includes a PR check in `.github/workflows/xss-sink-check.yml` backed by `scripts/check_xss_sinks.py`. It runs on PRs into `Development` and, until the V2 branch merges into `Development`, on PRs into `paullizer-react-v2-ui`. It checks the added lines of changed `.js`, `.html`, `.py`, `.ts`, `.tsx`, `.jsx` and `.mjs` files under `application/`, and skips vendored browser assets such as `application/v2_ui/public/vendor/`. `.github/workflows/xss-full-scan.yml` runs the same checker over whole files on demand.

If a reviewed exception is unavoidable, add the suppression token below near the specific line and include a justification comment:

```text
xss-check: ignore
```

Use that escape hatch rarely. It is for reviewed legacy exceptions, not for normal rendering code. In TypeScript-family files the justification must follow the token on the same line.