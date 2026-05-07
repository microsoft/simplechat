---
applyTo: '**/*.js, **/*.html, **/*.py'
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

## PR Review Checklist

For any JavaScript, HTML, or Python change that affects browser rendering:

1. Identify the trust boundary for every value that reaches the browser.
2. Prefer DOM node creation and `textContent` for untrusted text.
3. Normalize dynamic URLs before assigning them to clickable or loadable attributes.
4. If HTML rendering is required, document the sanitizer boundary explicitly.
5. Add or update a regression test when untrusted data reaches a browser-rendering path.

## Workflow Guardrail

This repository includes a Development PR check in `.github/workflows/xss-sink-check.yml` backed by `scripts/check_xss_sinks.py`.

If a reviewed exception is unavoidable, add the suppression token below near the specific line and include a justification comment:

```text
xss-check: ignore
```

Use that escape hatch rarely. It is for reviewed legacy exceptions, not for normal rendering code.