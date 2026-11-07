# XSS PR Guardrails: V2 Baseline Triage

Baseline recorded for GitHub issue #1571 at application version **0.261.203**, on the V2 branch `paullizer-react-v2-ui` at commit `c33ad4d16`. The V2 coverage is a tooling-only change, so the application version did not change.

## Overview

This page is the reviewed baseline for the V2 React/TypeScript rules in `scripts/check_xss_sinks.py`. It lists every finding that a full-mode run reports over the tracked V2 source, the verdict on each one, and the measurements used to tune the rules. The rules themselves are described in [XSS PR Guardrails](XSS_PR_GUARDRAILS.md#v2-reacttypescript-coverage).

The run reports 28 findings. Each one was traced to the source of its value, and all 28 are safe. None is an exploitable XSS.

Pull-request checks report only added lines, so these findings fail a pull request only when it changes a flagged line. When one does, check that the reason recorded below still holds. If it does, move the value onto an accepted source or add `xss-check: ignore` with a justification on the same line. If it no longer holds, fix the code.

## What was scanned

| Files | Count |
|---|---|
| TypeScript-family files tracked under `application/` | 465 |
| In `application/v2_ui/src` | 463 |
| `application/v2_ui/vite.config.ts` | 1 |
| The classic declaration file `application/single_app/static/js/admin/model_catalog_ui.d.ts` | 1 |
| Declaration files skipped (`src/lib/vendor.d.ts`, `src/vite-env.d.ts` and the classic one) | 3 |
| Files inspected | 462 |

Every tracked file is `.ts` (209) or `.tsx` (256). No `.jsx` or `.mjs` files are tracked yet, although the checker handles both.

To reproduce the baseline, run the checker in full mode, which checks every line rather than only added lines. The loop passes the files in batches because Windows limits a command line to 32,767 characters:

```powershell
$tsFiles = @(git ls-files "application/**/*.ts" "application/**/*.tsx" "application/**/*.jsx" "application/**/*.mjs")
for ($i = 0; $i -lt $tsFiles.Count; $i += 200) {
    python scripts/check_xss_sinks.py --full-file $tsFiles[$i..([Math]::Min($i + 199, $tsFiles.Count - 1))]
}
```

## Results by rule

Each rule was measured three ways:

- **Raw** counts every dynamic value that reaches a covered sink, with every approval, guard and suppression switched off. It measures the size of the surface, not the number of problems.
- **First pass** is the rule set as first designed. It accepts literals, safe template-literal prefixes, sanitizers, name-based helpers, reviewed builders and guards written in the same expression.
- **Tuned** adds the precision refinements in the next section. It is what the checker reports now.

| Rule id | Raw | First pass | Tuned |
|---|---|---|---|
| `ts-dangerous-inner-html` | 4 | 4 | 4 |
| `ts-html-sink` | 1 | 1 | 1 |
| `ts-code-eval` | 0 | 0 | 0 |
| `ts-javascript-url` | 3 | 3 | 3 |
| `ts-jsx-url-attribute` | 32 | 15 | 14 |
| `ts-navigation-sink` | 8 | 4 | 4 |
| `ts-markdown-raw-html` | 0 | 0 | 0 |
| `ts-dom-url-property` | 11 | 8 | 2 |
| `ts-inline-event-handler` | 0 | 0 | 0 |
| `ts-attribute-interpolation` | 0 | 0 | 0 |
| `ts-marked-parse` | 0 | 0 | 0 |
| **Total** | **59** | **35** | **28** |

The zero rows are real, not gaps. The V2 source has no `eval`, `Function` or string timers, and no `rehype-raw`, `allowDangerousHtml` or `urlTransform` option; those names appear only in comments that say raw HTML is deliberately off. The self-test covers a flagged case and an accepted case for every rule, including the ones with no baseline findings.

## Precision refinements

These refinements took the first pass from 35 findings to 28. Each removed finding was checked by hand before the refinement was kept.

| Refinement | What it changed | Findings it removed |
|---|---|---|
| Form receivers | A `.action` assignment is checked only when the receiver's name mentions a form, or when the receiver is a call or index result such as `document.forms[0]`, because `.action` is also a common data field. | `components/workflows/WorkflowAuthoringHistory.tsx:376` and `:381`, which store an undo-history entry. |
| Statement guards | For navigation and DOM sinks, an enclosing `if` or an earlier `if (!guard) return;` counts as a guard. | `lib/documentProvenance.ts:54`, which is assigned only after `isSafeOriginHref` passes. |
| `useState` setters | A state value resolves when every setter call passes an accepted value. | `components/workspaceAgents/AgentModelFields.tsx:217`, whose setter receives `''` or a `normalize*Url` result. |
| Block scoping | A name resolves to the binding in the nearest enclosing block rather than to any binding with that name in the file. | `components/chat/MessageActions.tsx:244`, an object URL for a markdown download. |
| Reviewed builders | `vendorUrl`, which prefixes the build-time base path to a vendored file path, joined the reviewed same-origin builders. | `lib/vendorAssets.ts:78` and `:90`. |
| Media receivers | A DOM `.src` assignment is classified by its receiver's name. Image and media receivers are not script sinks, while any receiver whose name mentions a frame, script, embed, object or worker stays strict. | None in the current source. It keeps image previews from being reported without letting a frame or script through. |

One further refinement was considered and left out: following a function parameter back to its call sites. It needs flow across files, and the few parameter-driven findings that remain were traced by hand below.

## Findings

Locations are relative to `application/v2_ui/src/`.

| # | Location | Rule | Verdict | Why it is safe |
|---|---|---|---|---|
| 1 | `App.tsx:170` | `ts-dom-url-property` | Safe | Sets the favicon link from the bootstrap branding payload, which the server builds from a fixed static path. An icon link does not run script. |
| 2 | `components/chat/CitationChip.tsx:168` | `ts-jsx-url-attribute` | Safe | A citation is given the web kind only when its URL matches `^https?://` (`lib/citations.ts`). |
| 3 | `components/chat/ConversationDetails.tsx:640` | `ts-jsx-url-attribute` | Safe | `source.href` is set only when the label matches `^https?://`, and is `undefined` otherwise (`lib/conversationDetails.ts`). |
| 4 | `components/chat/EnhancedCitationViewer.tsx:147` | `ts-jsx-url-attribute` | Safe | The `<iframe>` shows a blob URL made from the enhanced-citation PDF endpoint's response, which the server sends as `application/pdf`. |
| 5 | `components/chat/MathBlock.tsx:171` | `ts-dangerous-inner-html` | Safe | KaTeX renders with `trust: false`, and the output passes through `DOMPurify.sanitize` before it is stored in state. Reported because the checker does not follow the local `render` function. |
| 6 | `components/chat/MermaidDiagram.tsx:331` | `ts-dangerous-inner-html` | Safe | Mermaid renders with `securityLevel: 'strict'`, and the SVG is sanitized with DOMPurify before it is displayed. |
| 7 | `components/chat/MermaidDiagram.tsx:435` | `ts-dangerous-inner-html` | Safe | As row 6. |
| 8 | `components/chat/MermaidDiagram.tsx:590` | `ts-dangerous-inner-html` | Safe | As row 6. |
| 9 | `components/chat/MessageList.tsx:1418` | `ts-jsx-url-attribute` | Safe | The chat store sets `streamAuthUrl` only to `foundryAuthUrl(event)` or `null`. That helper returns an `http:` or `https:` URL on the API origin, without credentials, or `null`. |
| 10 | `components/documents/DocumentDetailsPane.tsx:439` | `ts-jsx-url-attribute` | Safe | `summary.href` is set only after `isSafeOriginHref(record.href)` passes (`lib/documentProvenance.ts`). |
| 11 | `components/layout/NavExtras.tsx:37` | `ts-jsx-url-attribute` | Safe | Custom-page links are server-built `/custom/<slug>` paths. The server drops any external link that fails `is_safe_external_link_url` before sending it. |
| 12 | `components/layout/Sidebar.tsx:432` | `ts-jsx-url-attribute` | Safe | `item.to` comes from the literal paths in the `NAV_ITEMS` list in the same file. |
| 13 | `components/settings/TabScaffold.tsx:59` | `ts-jsx-url-attribute` | Safe | `TabNotBuiltYet` renders its `classicHref` prop, and nothing in `src` renders `TabNotBuiltYet`. |
| 14 | `components/workspace/WorkspaceOverview.tsx:57` | `ts-jsx-url-attribute` | Safe | `basePath` is a prop. Only the group and public workspace pages pass it, and they build it with `groupWorkspacePath` or `publicWorkspacePath`, which encode the id, or use `/groups` or `/public`. |
| 15 | `components/workspace/WorkspaceShell.tsx:57` | `ts-jsx-url-attribute` | Safe | As row 14. |
| 16 | `components/workspace/WorkspaceShell.tsx:69` | `ts-jsx-url-attribute` | Safe | As row 14, followed by a section id from the app's own section definitions. |
| 17 | `dev/alertLabSamples.ts:358` | `ts-javascript-url` | Safe | Deliberately hostile sample data for the development-only alert lab, which checks that alert cards show hostile content as inert text. The lab loads only when `import.meta.env.DEV` is true, so production builds leave it out. |
| 18 | `dev/alertLabSamples.ts:363` | `ts-javascript-url` | Safe | As row 17. |
| 19 | `dev/alertLabSamples.ts:366` | `ts-javascript-url` | Safe | As row 17. |
| 20 | `lib/exportVisuals.ts:196` | `ts-html-sink` | Safe | Parses SVG from `renderMermaidSvgForExport`, which renders with Mermaid's strict security level and sanitizes with DOMPurify. Reported because the markup arrives as a function parameter. |
| 21 | `lib/images.ts:239` | `ts-navigation-sink` | Safe | Opens an image the app is already showing in a new tab and clears `opener`. The URL is the resolved image source, or an object URL made from its data. |
| 22 | `lib/svgRaster.ts:145` | `ts-dom-url-property` | Safe | Sets a download link's `href`. The only caller passes the PNG data URI from rasterizing the diagram on screen. |
| 23 | `pages/GroupWorkspacePage.tsx:357` | `ts-navigation-sink` | Safe | The target comes from `openClassic`, whose callers pass `/group_workspaces` or `/groups/` followed by an `encodeURIComponent` id. |
| 24 | `pages/PlaceholderPage.tsx:31` | `ts-jsx-url-attribute` | Safe | The only caller, in `App.tsx`, passes the literal `/agents`. |
| 25 | `pages/PublicWorkspacePage.tsx:219` | `ts-navigation-sink` | Safe | Every caller passes the `CLASSIC_WORKSPACE_HREF` constant. |
| 26 | `pages/PublicWorkspacePage.tsx:234` | `ts-navigation-sink` | Safe | The target is `/public_workspaces/` followed by an `encodeURIComponent` id. |
| 27 | `pages/workspace/AgentEditorPage.tsx:201` | `ts-jsx-url-attribute` | Safe | The agent workbench's `basePath` is `/workspace/agents` or `workspaceBasePath(scope)` followed by `/agents`. |
| 28 | `pages/workspace/AgentsSection.tsx:123` | `ts-jsx-url-attribute` | Safe | The link is the agent workbench's `basePath` (as row 27) followed by an `encodeURIComponent` agent id. |

The four `dangerouslySetInnerHTML` sites (rows 5 to 8) are also covered by `functional_tests/test_v2_rich_rendering.py`, which guards the KaTeX, Mermaid and DOMPurify settings they depend on.

## Dynamic URL attributes in the V2 source

A lexer count finds 56 dynamic `href`, `src`, `action` and `formAction` JSX attributes in 42 files. The URL rule checks only the ones that can run script:

- 22 are `<img src>`. An image source cannot run script, so it is not checked.
- 16 are `action` props on custom components. Most hold a Retry or empty-state button, and two hold data objects. None is on a `<form>`.
- 16 are `<a href>`, 1 is an `<iframe src>`, and 1 is the `src` prop of the `ImageMaskCanvas` component, which draws an image.

The rule also checks `to` on react-router's `Link`, `NavLink` and `Navigate`, which has 15 dynamic values: 12 on `Link` and 3 on `NavLink`. Of the 32 values the rule checks (16 `href`, 1 `<iframe src>` and 15 `to`), 18 resolve to accepted sources and 14 are in the findings table.

## Accepted sites worth knowing

These navigation sinks are not reported, but a reviewer may ask about them:

- `lib/notificationNavigation.ts:76` calls `window.location.assign(address)` only after `sameSiteAddress` returns a same-site address. It returns early otherwise.
- `components/chat/MessageActions.tsx:206` sets `window.location.href` to `emailDraftMailtoUrl(draft)`, a reviewed builder that always returns a `mailto:` URL.
- `pages/PublicDirectoryPage.tsx:248` navigates to the `CHAT_PUBLIC_HREF` constant.

## Lexer audit

The lexer was run on all 464 TypeScript-family files under `application/v2_ui/`: the 463 in `src`, including both declaration files, and `vite.config.ts`. It took about two seconds and recorded 19,763 JSX attributes.

- No file needed the degraded fallback, which lexes a whole file without JSX, and no `<` had to be re-read as a comparison or a generic instead of a JSX tag.
- Brackets balance in every file's code skeleton. A string, template literal, regular expression or piece of JSX text misread as code usually unbalances them.
- A plain-text search finds 30 `href=` occurrences in `.tsx` files, and the lexer records 29 of them as attributes. The remaining one is inside a comment.

## Classic checks unchanged

The previous checker and the new one were both run on all 2,881 tracked `.js`, `.html` and `.py` files in the repository:

- Both select the same files.
- The previous checker reports 498 findings and the new one 472. All 26 that disappear are in the two vendored V2 libraries under `application/v2_ui/public/vendor/`: 1 in DOMPurify and 25 in Mermaid. That directory is now skipped as vendored code. Every other file reports exactly the same findings.

The existing assertions in `functional_tests/test_xss_guardrails_checker.py` pass without modification.

## Follow-ups

- Add ESLint's `react/no-danger` and `react/jsx-no-script-url` rules from `eslint-plugin-react`, so editors flag the same patterns while code is written. The V2 app has no ESLint setup today.
- Consider a shared helper, for example `sanitizeHttpUrl`, for the `^https?://` checks that several components repeat. The checker accepts a helper with that name, so calling it at the sink would clear rows 2 and 3.
- Consider adding justified `xss-check: ignore` comments to the four `dangerouslySetInnerHTML` sites, so an unrelated edit on those lines does not fail a pull request. The trade-off is that a later change to the sanitized value would no longer be reported.
- Follow function parameters to their call sites, which would remove the parameter-driven findings.
- Remove the temporary `paullizer-react-v2-ui` workflow triggers when the V2 branch merges into Development.
