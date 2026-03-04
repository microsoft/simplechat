# SimpleChat — Project Instructions

SimpleChat is a Flask web application using Azure Cosmos DB, Azure AI Search, and Azure OpenAI. It supports personal, group, and public workspaces for document management and AI-powered chat.

## Code Style — Python

- Start every file with a filename comment: `# filename.py`
- Place imports at the top, after the module docstring (exceptions must be documented)
- Use 4-space indentation, never tabs
- Use `log_event` from `functions_appinsights.py` for logging instead of `print()`

## Code Style — JavaScript

- Start every file with a filename comment: `// filename.js`
- Group imports at the top of the file (exceptions must be documented)
- Use 4-space indentation, never tabs
- Use camelCase for variables and functions: `myVariable`, `getUserData()`
- Use PascalCase for classes: `MyClass`
- Never use `display:none` in JavaScript; use Bootstrap's `d-none` class instead
- Use Bootstrap alert classes for notifications, not `alert()` calls

## Route Decorators — Swagger Security

**Every Flask route MUST include the `@swagger_route(security=get_auth_security())` decorator.**

- Import `swagger_route` and `get_auth_security` from `swagger_wrapper`
- Place `@swagger_route(security=get_auth_security())` immediately after the `@app.route(...)` decorator and before any authentication decorators (`@login_required`, `@user_required`, etc.)
- This applies to all new and existing routes — no exceptions

Correct pattern:
```python
from swagger_wrapper import swagger_route, get_auth_security

@app.route("/api/example", methods=["GET"])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def example_route():
    ...
```

## Security — Settings Sanitization

**NEVER send raw settings or configuration data to the frontend without sanitization.**

- Always use `sanitize_settings_for_user()` from `functions_settings.py` before passing settings to `render_template()` or `jsonify()`
- **Exception**: Admin routes should NOT be sanitized (breaks admin features)
- Sanitization strips: API keys, Cosmos DB connection strings, Azure Search admin keys, Document Intelligence keys, authentication secrets, internal endpoint URLs, database credentials, and any field containing "key", "secret", "password", or "connection"

Correct pattern:
```python
from functions_settings import get_settings, sanitize_settings_for_user

settings = get_settings()
public_settings = sanitize_settings_for_user(settings)
return render_template('page.html', settings=public_settings)
```

## Version Management

- Its important to update the version at the end of every plan
- Version is stored in `config.py`: `VERSION = "X.XXX.XXX"`
- When incrementing, only change the third segment (e.g., `0.238.024` -> `0.238.025`)
- Include the current version in functional test file headers and documentation files

## Documentation Locations

- **Feature documentation**: `docs/explanation/features/[FEATURE_NAME].md` (uppercase with underscores)
- **Fix documentation**: `docs/explanation/fixes/[ISSUE_NAME]_FIX.md` (uppercase with underscores)
- **Release notes**: `docs/explanation/release_notes.md`

### Feature Documentation Structure

1. Header: title, overview, version, dependencies
2. Technical specifications: architecture, APIs, configuration, file structure
3. Usage instructions: enable/configure, workflows, examples
4. Testing and validation: coverage, performance, limitations

### Fix Documentation Structure

1. Header: title, issue description, root cause, version
2. Technical details: files modified, code changes, testing, impact
3. Validation: test results, before/after comparison

## Release Notes

After completing code changes, offer to update `docs/explanation/release_notes.md`.

- Add entries under the current version from `config.py`
- If the version was bumped, create a new section at the top: `### **(vX.XXX.XXX)**`
- Entry categories: **New Features**, **Bug Fixes**, **User Interface Enhancements**, **Breaking Changes**
- Format each entry with a bold title, bullet-point details, and a `(Ref: ...)` line referencing relevant files/concepts

## Functional Tests

- **Location**: `functional_tests/`
- **Naming**: `test_{feature_area}_{specific_test}.py` or `.js`
- **When to create**: bug fixes, new features, API changes, database migration, UI/UX changes, authentication/security changes

Every test file must include a version header:
```python
#!/usr/bin/env python3
"""
Functional test for [feature/fix name].
Version: [current version from config.py]
Implemented in: [version when fix/feature was added]

This test ensures that [description of what is being tested].
"""
```

Test template pattern:
```python
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_primary_functionality():
    """Test the main functionality."""
    print("Testing [Feature Name]...")
    try:
        # Setup, execute, validate, cleanup
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_primary_functionality()
    sys.exit(0 if success else 1)
```



## Key Project Files

| File | Purpose |
|------|---------|
| `application/single_app/config.py` | App configuration and `VERSION` |
| `application/single_app/functions_settings.py` | `get_settings()`, `sanitize_settings_for_user()` |
| `application/single_app/functions_appinsights.py` | `log_event()` for logging |
| `application/single_app/functions_documents.py` | Document CRUD, chunk operations, tag management |
| `application/single_app/functions_group.py` | Group workspace operations |
| `application/single_app/functions_public_workspaces.py` | Public workspace operations |
| `application/single_app/route_backend_documents.py` | Personal document API routes |
| `application/single_app/route_backend_group_documents.py` | Group document API routes |
| `application/single_app/route_external_public_documents.py` | Public document API routes |
| `application/single_app/route_backend_chats.py` | Chat API routes and AI search integration |

## Frontend Architecture

- Templates: `application/single_app/templates/` (Jinja2 HTML)
- Static JS: `application/single_app/static/js/`
  - `chat/` — Chat interface modules (chat-messages.js, chat-documents.js, chat-citations.js, chat-streaming.js)
  - `workspace/` — Personal workspace (workspace-documents.js, workspace-tags.js)
  - `public/` — Public workspace (public_workspace.js)
- Group workspace JS is inline in `templates/group_workspaces.html`
- Uses Bootstrap 5 for UI components and styling
