# V1 LaTeX math rendering

Version implemented: **0.261.047**

The existing V1 chat interface now typesets assistant equations, fractions, and
matrices using the same KaTeX engine and delimiter approach as V2. React is not
required. Model selection, stored responses, and backend APIs are unchanged.

## Usage

Math rendering is automatic when an assistant response contains supported TeX:

```text
Inline: \(x_n = \frac{X_c}{Z_c}\)

Display:
\[
\mathbf{X}_c = \begin{bmatrix} X_c \\ Y_c \\ Z_c \end{bmatrix}
\]

$$E = mc^2$$
```

Double-dollar expressions on their own lines render as display math; in prose they
render inline, matching V2. Single-dollar delimiters are intentionally not supported
so amounts such as "$5 to $10" remain text. Inline code and fenced code remain code.
No administrator setting or new model prompt is required.

Completed streamed expressions, saved messages, retries, and interrupted responses
use the same math renderer. An incomplete streamed expression remains ordinary
Markdown until it closes. Copy as Markdown retains the original TeX delimiters and
matrix row separators. Server-side PDF, Word, and PowerPoint equation typesetting
is not part of this change.

## Technical specifications

- [Math scanner](../../../application/single_app/static/js/chat/chat-math-segments.js):
  framework-independent adaptation of V2's mathSegments.ts.
- [Math runtime](../../../application/single_app/static/js/chat/chat-math.js):
  lazy asset loading, placeholder hydration, sanitization, and selection handling.
- [Assistant rendering](../../../application/single_app/static/js/chat/chat-messages.js)
  and [streaming](../../../application/single_app/static/js/chat/chat-streaming.js):
  integration into the existing V1 lifecycle.
- [Styles](../../../application/single_app/static/css/chats.css):
  inherited theme colors, raw-source fallback, and horizontally scrollable display math.
- [Pinned KaTeX distribution](../../../application/single_app/static/vendor/katex-0.18.4):
  JavaScript, stylesheet, fonts, and MIT license copied byte-for-byte from V2 commit
  `70c255508675bb0de7b7940c0ec90d5980f8b529`.

Expressions are lifted out before Markdown/table transformations can consume TeX
escapes. Inert, collision-avoiding tokens survive Markdown; DOM text-node replacement
creates math containers afterward. Tokens never substitute into HTML attributes.
The existing DOMPurify sanitizes Markdown and independently sanitizes KaTeX output.
KaTeX uses `trust: false`, `maxExpand: 1000`, `maxSize: 20`, and HTML plus MathML.
The existing sanitizer and CSP are not relaxed.

Scripts, CSS, and fonts are served locally. No Internet typesetting service or CDN
is used. Assets load only when an expression is rendered. Each message is limited
to 100 extracted expressions of at most 2,000 characters; excess input remains
ordinary Markdown. The rendered-expression cache holds at most 200 entries.
Asset failures show a visible source-text fallback and allow a later message to
retry loading. Unsupported expressions also show a source-text fallback.

## Masking and accessibility

Existing text-mask offsets are preserved against V1's pre-math display text. A
selection within a rendered formula expands to the whole expression for masking;
individual visual glyphs do not have reliable source offsets. Math intersecting a
text mask remains untypeset so rendering cannot overwrite that mask.

MathML accompanies the visual HTML. Colors inherit from the chat theme and display
expressions scroll within the message rather than expanding the page. Screen-reader
behavior depends on the reader/browser and should be included in deployment acceptance.

## Testing and limitations

- [Functional tests](../../../functional_tests/test_chat_math_segments.js) exercise
  delimiters, matrix escapes, currency, code, links, streaming prefixes, bounds,
  placeholder collisions, and the pinned renderer.
- [UI tests](../../../ui_tests/test_chat_math_rendering.py) use real V1 templates and
  modules with same-origin API fixtures for desktop/mobile, light/dark themes,
  replay, streaming, masking, sanitized math, asset failures, and retries.
  They support the existing Azure Playwright environment configuration and local Chromium.

Run `node --test functional_tests/test_chat_math_segments.js` and
`python -m pytest ui_tests/test_chat_math_rendering.py`.

KaTeX supports a mathematical TeX subset, not arbitrary LaTeX documents or packages.
Rendering an equation does not verify its mathematical correctness. No production
backend or model endpoint is needed for the isolated regression tests.
