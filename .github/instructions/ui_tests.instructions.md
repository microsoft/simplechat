---
applyTo: '**/*.html, **/*.js, **/*.css'
---

# UI Tests

- Always create or update Azure Playwright UI tests when changing HTML, CSS, or JavaScript that affects rendering, user interaction, layout, client-side state, or browser workflows.

## Location

- Store all UI tests in the `ui_tests/` folder at the root of the project.
- Keep reusable helpers, fixtures, authentication utilities, and page models inside `ui_tests/` so UI automation stays separate from `functional_tests/`.
- Place screenshots, traces, and other test artifacts under a dedicated subfolder such as `ui_tests/artifacts/`.

## When UI Tests Are Required

### Always create or update UI tests for:
- New pages, views, or templates.
- HTML changes that affect structure, accessibility, forms, navigation, or conditional rendering.
- CSS changes that affect layout, spacing, responsive behavior, visibility, theming, or visual regressions.
- JavaScript changes that affect event handlers, DOM updates, modals, tabs, filtering, validation, async loading, or error handling.
- Bug fixes involving display logic, user flows, or browser-side regressions.
- Features that require proof that the browser experience works end to end.

### Focus areas for coverage:
- Rendering: page content, empty states, conditional sections, and accessibility attributes.
- Interaction: clicks, typing, keyboard navigation, dialogs, dropdowns, and form submission.
- Styling and layout: visible states, responsive breakpoints, overflow issues, and Bootstrap-driven behavior.
- JavaScript behavior: dynamic updates, loading indicators, validation messages, and error states.

## Required Technology

- Use Azure Playwright for UI automation.
- Use the `azure-mgmt-playwright` Python package when provisioning or connecting to Azure Playwright resources.
- Use `DefaultAzureCredential` for authentication. Never hardcode credentials, API keys, or secrets in UI tests.
- Write UI tests in Python unless the user explicitly requests another language.

## Naming Conventions

### File naming:
- Use `test_{page_or_feature}_{scenario}.py` for executable UI tests.
- Use descriptive names tied to the user-visible workflow being validated.

### Examples:
- `test_chat_sidebar_navigation.py`
- `test_workspace_document_filters.py`
- `test_group_workspace_modal_validation.py`
- `test_public_workspace_responsive_layout.py`

## Suggested Directory Structure

```text
ui_tests/
	test_chat_sidebar_navigation.py
	test_workspace_document_filters.py
	conftest.py
	auth_helpers.py
	page_models/
	fixtures/
	artifacts/
```

## Test Design Requirements

- Keep each test independent and runnable on its own.
- Cover the complete browser workflow: navigation, setup, action, validation, and cleanup when needed.
- Validate both expected success paths and visible failure states.
- Prefer stable selectors such as `id`, `name`, `data-testid`, ARIA roles, labels, and text that is intentionally user-facing.
- Avoid brittle selectors based on deeply nested CSS paths or Bootstrap implementation details.
- If a UI change is responsive, validate at least desktop and mobile viewport behavior.
- If a change is accessibility-sensitive, validate visible labels, roles, focus movement, and keyboard behavior where practical.

## Python UI Test Template

```python
# test_chat_sidebar_navigation.py
"""
UI test for chat sidebar navigation.

Version: [current version from config.py when applicable]
Implemented in: [version when fix or feature was added]

This test ensures that the sidebar navigation renders correctly,
supports keyboard and mouse interaction, and updates the visible
chat panel without browser errors.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.mark.ui
def test_chat_sidebar_navigation(page):
	"""Validate that users can navigate between sidebar destinations."""
	page.goto("http://127.0.0.1:5000")
	page.get_by_role("button", name="Open navigation").click()
	page.get_by_role("link", name="Workspaces").click()

	expect(page.get_by_role("heading", name="Workspaces")).to_be_visible()
	expect(page.get_by_text("Recent documents")).to_be_visible()
```

## Authentication and Environment Rules

- Authenticate Azure dependencies with `DefaultAzureCredential`.
- Read environment-specific values such as base URLs, tenant-specific settings, or test accounts from environment variables or secure configuration.
- Never commit secrets, session tokens, storage keys, or passwords.
- If a test requires signed-in state, create a reusable login helper in `ui_tests/` rather than duplicating login steps across files.

## What to Validate in UI Tests

### HTML changes:
- Key headings, landmarks, labels, buttons, links, and form elements render correctly.
- Conditional content appears or stays hidden at the right time.
- Accessibility-related attributes remain intact.

### CSS changes:
- Elements are visible when expected and hidden only when intended.
- Layout behaves correctly at the supported viewport sizes.
- Important visual states such as error, loading, selected, disabled, and hover-adjacent states are testable.

### JavaScript changes:
- Event handlers trigger the correct visible behavior.
- DOM updates complete after async actions.
- Validation, toast messages, modals, drawers, and loading indicators behave correctly.
- Browser console errors should be treated as failures when they are caused by the changed workflow.

## Reuse and Maintainability

- Extract repeated UI actions into helper functions or page model classes.
- Keep assertions close to the action they validate so failures are easy to diagnose.
- Use concise setup utilities for viewport, authentication, seeded test data, and navigation.
- Prefer a small number of focused tests over one large brittle end-to-end script.

## Execution Patterns

### Typical workflow:
- Start the local app or target environment.
- Run only the relevant UI test file while iterating.
- Run the broader affected UI suite before completing the change.

### Example commands:
```bash
cd ui_tests
pytest test_chat_sidebar_navigation.py
pytest -m ui
```

## Best Practices

- Write UI tests as part of the same change that updates the HTML, CSS, or JavaScript.
- Keep test names and docstrings explicit about the user behavior being validated.
- Capture screenshots or traces for failures when the workflow is difficult to diagnose.
- Avoid sleeping for fixed durations; wait for meaningful UI conditions instead.
- Verify user-visible outcomes, not just implementation details.
- If a bug fix changes browser behavior, add a regression UI test that fails without the fix.