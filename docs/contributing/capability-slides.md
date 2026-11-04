---
layout: page
title: "Maintain the capability slide screenshots"
description: "Keep full presentation slides, feature explanations, and documentation links aligned."
section: "Contributing"
version: "0.261.398"
---

The documentation uses complete screenshots from the approved customer-facing
presentation. They explain a capability where the reader encounters it, alongside
the task instructions, settings, and limitations that remain useful as text.

Implemented in version: **0.261.398**. This is the presentation's capability
snapshot, recorded against `application/single_app/config.py`; documentation-only
updates do not increment the application version.

## What belongs in the documentation

Use the full slide, including its title, diagrams, labels, and footer. Do not
replace it with a cropped diagram, a recreated graphic, a prose-only summary, or
a link to the deck.

The slide is an illustration, not proof of a running application's current
state. Keep real application screenshots when they teach the controls. Do not
fill a missing application-screenshot slot with a presentation slide.

Title pages, dividers, customer-logo lists, historical comparisons, rollout
figures, and proposed roadmap slides do not describe current application
capabilities. The source manifest records those exclusions rather than silently
forgetting part of the presentation.

## Follow the source of truth

| File | Responsibility |
| --- | --- |
| `docs/_data/capability_slides.yml` | Approved deck filename and SHA-256, capability snapshot, every slide's disposition, image fingerprints, and primary page |
| `docs/_data/media.yml` | Stable image IDs, local asset paths, alt text, captions, and dimensions |
| `docs/images/slides/` | Complete PNG exports, stored once and reused by media ID |
| `docs/_data/features.yml` | Feature explanations and their inline `visual_sections` |
| `docs/_layouts/feature.html` | Shared feature-page presentation |
| `docs/_features/` | Generated collection stubs, not durable authored page bodies |

Keep personal filesystem paths, credentials, temporary render packages, and the
PowerPoint/PDF binaries out of this registry and asset directory. Obtain the
approved editable presentation from its maintained document location when a
slide needs updating.

## Update an image deliberately

1. Confirm the approved presentation and its SHA-256. A changed deck needs an
   explicit provenance update rather than an assumption that slide numbers
   still mean the same thing.
2. Export the entire selected slide as a PNG. The current images are
   **1600 x 900**, preserving the original 16:9 canvas.
3. Keep the descriptive asset filename stable when the subject is unchanged.
   Do not add a second binary copy merely because another page uses the slide.
4. Update the source slide number, image fingerprint, and any changed
   disposition in `capability_slides.yml`.
5. Update the media entry's alt text, caption, and actual dimensions. Explain
   what the diagram communicates, including configuration or access caveats
   that are material in its documentation context.
6. Check the image on its primary page and each contextual reuse. Confirm that
   it remains complete and can be enlarged on a small screen.

PowerShell can compute the fingerprint without modifying the image:

```powershell
Get-FileHash -LiteralPath .\docs\images\slides\agents.png -Algorithm SHA256
```

Changing the application version alone does not require relabeling historical
presentation screenshots. Keep the illustration's snapshot explicit and update
it when the illustrated behavior changes.

## Put the slide in the explanation

For an ordinary guide or reference page, use the existing media component near
the heading it explains:

```liquid
{% raw %}{% include media.html id="slide-workspace-scope-lock" %}{% endraw %}
```

For feature collection pages, add a visual section to the feature's central
data:

```yaml
visual_sections:
  - heading: "How a focused assistant works"
    text: "Choose the instructions, knowledge, and approved tools the task needs."
    media_id: slide-agents
```

Do not edit the body of a generated `_features` stub: regeneration replaces it.
From the repository root, regenerate and check the collection:

```powershell
python .\scripts\generate_feature_pages.py
python .\scripts\generate_feature_pages.py --check
```

Use concise supporting text for prerequisites, accessibility, and important
limitations. Do not transcribe every label just to repeat the image, and do not
leave the image in a separate gallery while the feature page contains only a
summary.

## Verify the published result

Run the documentation checks from the repository root:

```powershell
python .\functional_tests\test_docs_capability_slides.py
python .\functional_tests\test_docs_site_quality.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_link_integrity.py
```

Build with the existing docs Gemfile, then point
`SIMPLECHAT_DOCS_SITE_ROOT` at the built output to check actual feature pages,
images, and search entries. Set `SIMPLECHAT_DOCS_BASE_URL` to that site's served
base URL to run `ui_tests/test_docs_capability_slides.py`.

The browser tests reuse the shared Azure Playwright connection when a workspace
is configured, or the existing local-browser path otherwise. They do not
provision Azure resources.

Before sharing the result, inspect representative feature, guide, and
architecture pages on desktop and mobile in both themes. Enlarge a slide with
the keyboard, close it with Escape, and confirm focus returns to its image
button. Keep the existing private-networking and provider-policy qualifications;
an attractive diagram is not a compliance or data-residency guarantee.
