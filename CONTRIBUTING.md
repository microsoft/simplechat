# Contributing to Simple Chat

Simple Chat keeps application code, deployment assets, tests, and public docs in one repository. The safest way to contribute is to keep changes focused, target the correct branch, and run the validation that matches the surface you changed.

For the docs-site version of this guide, see [docs/contributing.md](docs/contributing.md).

## Branch flow

- Start normal feature and fix work from `Development`.
- Open pull requests into `Development` for day-to-day contributions.
- Treat `Development` → `Staging` → `main` as the promotion flow.
- Use the actual upstream branch casing: `Development` and `Staging`.
- If you edit workflow automation, verify branch comparisons carefully because some older workflow logic still uses lowercase strings.

## What to run locally

For docs changes:

```powershell
cd docs
bundle exec jekyll build
bundle exec jekyll serve --host 127.0.0.1 --port 4000
```

The docs site uses a Jekyll `baseurl`, so local pages are typically served from `http://127.0.0.1:4000/simplechat/`.

For docs UI regression:

```powershell
cd ..
$env:SIMPLECHAT_DOCS_BASE_URL = "http://127.0.0.1:4000/simplechat"
python -m pytest ui_tests/test_docs_showcase_pages.py
```

For application changes:

- Run the narrowest relevant tests in `functional_tests/` and `ui_tests/`.
- Update documentation when the behavior, workflow, or screenshots changed.
- Keep deployer changes aligned across the relevant `deployers/` entry points.

## Pull request checklist

- Target `Development` unless a maintainer explicitly tells you otherwise.
- Explain the user-facing impact in the PR description.
- Update docs, screenshots, or release notes when the change affects them.
- Add or update regression coverage for fixes and browser-facing changes.
- Keep unrelated cleanup out of the same PR.