# Swagger PR Route Check

Version implemented: **0.240.005**
Updated in version: **0.240.003**

## Overview

This pull request workflow validates changed Flask route files and fails the PR when an edited route is missing `@swagger_route(security=get_auth_security())` or places it in the wrong position.

Dependencies:

- GitHub Actions
- `tj-actions/changed-files@v46.0.1`
- `scripts/check_swagger_routes.py`

## Technical Specifications

Architecture overview:

- The workflow runs on `pull_request` events for `main`, `Development`, and `staging`.
- It scopes execution to changes in `application/single_app/**/*.py`, the checker script, and the workflow file itself.
- The workflow uses `tj-actions/changed-files` to gather only edited Python files.
- The checker script parses each changed file with Python AST and inspects route decorators on Flask route functions.
- Files that cannot be read as UTF-8 or parsed as valid Python now fail with GitHub Actions `::error` annotations so pull request failures point at the file and line that blocked validation.

Configuration options:

- Workflow file: `.github/workflows/swagger-route-check.yml`
- Validation script: `scripts/check_swagger_routes.py`

File structure:

- `.github/workflows/swagger-route-check.yml`
- `scripts/check_swagger_routes.py`
- `functional_tests/test_swagger_route_pr_workflow.py`

## Usage Instructions

How to enable/configure:

- The workflow is enabled automatically once merged into a branch that GitHub Actions runs for pull requests.

User workflow:

- Edit or add a Flask route in `application/single_app/`.
- Open or update a pull request.
- The workflow checks only the changed Python files in the PR.
- If any changed route omits the required swagger decorator, the job fails with a file and line annotation.
- If a changed Python file cannot be decoded or parsed, the job fails with a file and line annotation instead of a raw traceback.

Integration points:

- Complements the repository route standard defined in the application instructions.
- Works alongside syntax and release-note pull request workflows.

## Testing And Validation

Test coverage:

- `functional_tests/test_swagger_route_pr_workflow.py` validates the workflow file exists and the checker script accepts valid routes, rejects missing swagger decorators, and emits annotations for syntax or UTF-8 read failures.

Performance considerations:

- The workflow only inspects changed Python files instead of scanning the entire codebase for every pull request.

Known limitations:

- The check enforces the exact decorator pattern `@swagger_route(security=get_auth_security())`.
- The check focuses on changed files, so historical files that are not edited in a pull request are not rescanned by the workflow.