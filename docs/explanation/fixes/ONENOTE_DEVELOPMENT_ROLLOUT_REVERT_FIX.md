# OneNote Development Rollout Revert (v0.261.046)

## Issue and root cause

Native OneNote support was accidentally merged into `Development` through
[PR #1525](https://github.com/microsoft/simplechat/pull/1525) before the intended
Reactv2 testing. Merge `f3da1b61de7322a9b6a092a258b92d895fb26b6a` introduced
`.one` and `.onepkg` upload support and native extractor packaging on the wrong
branch.

## Fixed in version: **0.261.046**

`application/single_app/config.py` advances from the accidentally released
`0.261.045` to `0.261.046`, rather than restoring the older `0.261.044` version.

## Technical changes and impact

A normal first-parent revert restores application code and packaging to
`e1e017129c58f01390e3ff533543e004c3f83a5c`, except for the version bump.
It removes the OneNote MIME registrations, shared upload/category allowlists,
ingestion dispatch, narrative-source extensions, extractor module, native
sources, licenses, fixtures, and OneNote-only tests. The Dockerfile and ignore
rules return to their previous contents.

The inverse also removes the premature feature documentation and `0.261.045`
release entry. All earlier release entries are retained, with a corrective
`0.261.046` Bug Fix entry added.

The existing PDF, Office, text, tabular, image, media, MSG, Visio, and XSD paths
remain intact. This source correction does not delete stored documents, change
live settings, deploy resources, or rewrite Git history. The adapted Reactv2
implementation on `paullizer-react-v2-ui` at
`c9faeae08cfbeccad1ae5212c1d9304f419fdf58` is not changed.

## Validation

`functional_tests/test_onenote_development_revert.py` covers rejection of both
native formats, including uppercase filenames, in personal, group, and public
background uploads; explicit error status and temporary-file cleanup; retained
legacy allowlists and optional media/schema categories; mixed-source
classification; and absence of native imports and container packaging.

The source comparison against the merge's first parent allows only the version
bump, corrective release/fix documentation, and this focused regression beyond
the exact inverse. Documentation inventory, coverage and quality checks, route
policy suites, the existing mixed-source and workspace-format contracts, and
Python syntax checks cover the restored integration surfaces without deploying
or rebuilding cloud images.
