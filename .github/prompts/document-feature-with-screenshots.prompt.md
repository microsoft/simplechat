---
description: "Use when: documenting a new SimpleChat release feature or capability with browser screenshots, annotations, docs image assets, and related docs updates."
name: "Document Feature With Screenshots"
argument-hint: "Feature name, routes/pages to capture, docs pages to update, optional viewport/zoom"
agent: "agent"
---

Create or update SimpleChat documentation for a user-facing feature or release capability using browser screenshots and lightweight annotations.

The user will describe the feature, where it appears in the app, and any release context. If critical details are missing, ask only the smallest number of clarifying questions needed to proceed.

## Inputs To Gather

- Feature or capability name.
- User-facing workflow to show, including routes, pages, modals, tabs, settings, or roles needed.
- Documentation destinations, if known.
- Screenshot preferences, such as viewport size, browser zoom, or whether to use an existing logged-in browser session.
- Privacy constraints, including names, emails, tenants, secrets, connection strings, document titles, or customer data that must be masked.

## Documentation Targets

- Feature documentation: `docs/explanation/features/[FEATURE_NAME].md`.
- Latest release highlights: `docs/latest-release/` when the feature belongs in the current release showcase.
- Main capability overview: `docs/features.md` when the feature is user-facing enough to appear in the public feature map.
- Feature index: `docs/explanation/features/index.md`.
- Screenshot assets: `docs/images/` using descriptive lowercase names, such as `feature-example-workflow.png`.
- Release notes: check `docs/explanation/release_notes.md`; update only after confirming with the user when required by repo instructions.

## Workflow

1. Inspect the existing docs and feature implementation just enough to understand the feature and current conventions.
2. Confirm the current app version from `application/single_app/config.py` for docs metadata. Do not bump the version for docs-only changes.
3. Use the local app in an authenticated browser session when available. If the user provides viewport or zoom requirements, set them before capturing screenshots.
4. Navigate the real workflow a user would follow. Prefer selectors, URLs, and Bootstrap APIs over fragile pointer clicks when modals, zoom, or tabs make hit testing unreliable.
5. Before capturing screenshots, mask sensitive or distracting values in the DOM where possible instead of editing them into the final image later.
6. Capture screenshots that show the feature clearly. Use focused element screenshots or clipped captures when full-page screenshots bury the important controls.
7. Annotate screenshots with restrained callouts, boxes, and labels that identify the relevant controls or state. Keep the annotations readable at docs display size.
8. Remove temporary raw screenshots and keep only the final documentation-ready assets.
9. Update the relevant Markdown docs with concise user-facing copy, image references using `{{ '/images/name.png' | relative_url }}`, and implementation/version details where appropriate.
10. Validate the changes:
    - Confirm every referenced image file exists.
    - Run Markdown diagnostics on edited docs.
    - Run `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.
    - Review a scoped `git status --short` and text diff for only the documentation and image files you touched.

## Screenshot Quality Rules

- Show the actual product workflow, not a marketing-style mockup.
- Prefer one clear workflow image over several noisy images.
- Make sure controls, labels, menus, selected options, preview states, and save actions are fully visible.
- Avoid clipping the control that the documentation is explaining.
- Use consistent annotation colors and label style across screenshots in the same documentation pass.
- If the app contains real user or tenant information, mask it before the screenshot.
- Do not include browser chrome unless it is needed to explain navigation.

## Output Expectations

At the end, summarize:

- Which docs were created or updated.
- Which screenshot assets were added.
- What validation was run and whether it passed.
- Any intentionally skipped work, such as version bumps or release notes updates.
