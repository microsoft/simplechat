# Contributing to SimpleChat

This repository uses the standard `CONTRIBUTING.md` filename so GitHub can surface the guide automatically.
The documentation-site copy lives at `docs/contributing.md`, and both files should stay aligned.

## Contribution Flow

SimpleChat contributions should be made through a fork-based workflow.

1. Fork the repository.
2. Clone your fork locally.
3. Add the main SimpleChat repository as `upstream`.
4. Create a new branch from the upstream `Development` branch.
5. Make your changes in that new branch.
6. Push the branch to your fork.
7. Open a pull request from your fork branch back to the main SimpleChat repository's `Development` branch.

Do not open contributor pull requests directly to `Staging` or `main`. The repository uses a staged promotion flow: `Development` -> `Staging` -> `main`.
Use the branch names exactly as written here. In this repository, `Development` and `Staging` are capitalized.
After a contribution is merged into `Development`, the SimpleChat team handles promotion forward.

<!-- Optional image placeholder:
Add a branch-flow diagram here later if you want a visual version of the process.

Example:
![SimpleChat contribution flow](docs/images/contribution-flow.png)
-->

## Suggested Git Commands

Use whatever Git workflow you prefer, but this is the expected starting point:

```bash
git clone <your-fork-url>
cd simplechat
git remote add upstream <simplechat-upstream-url>
git fetch upstream
git switch -c feature/my-change upstream/Development
```

When you are ready to publish your work:

```bash
git push -u origin feature/my-change
```

If your branch falls behind, sync it from `upstream/Development` before opening or updating the pull request.

## Local Development

Before contributing, make sure you can run SimpleChat locally.

Recommended local setup in VS Code uses a repo-local `.venv` with Python 3.12.

From the repo root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r application/single_app/requirements.txt
Set-Location application/single_app
$env:FLASK_DEBUG = "1"
python app.py
```

For the full local workflow, environment guidance, and notes about Docker, WSL2, and Gunicorn validation, see:

- [README.md](./README.md)
- [docs/setup_instructions_manual.md](./docs/setup_instructions_manual.md)
- [docs/explanation/running_simplechat_locally.md](./docs/explanation/running_simplechat_locally.md)

## Pull Request Expectations

Keep pull requests focused and easy to review.

- Base your work on `Development`, not `main`.
- Keep unrelated refactors out of the same pull request.
- Explain what changed, why it changed, and how you tested it.
- Include screenshots or short recordings for UI changes when helpful.
- Call out any configuration, schema, security, or deployment impact.
- Update documentation when user-facing behavior or setup steps change.

## Tests and Validation

Before opening a pull request, run the tests that match your change.

- Add or update functional tests for bug fixes and new features when appropriate.
- Run relevant tests from `functional_tests/` and `ui_tests/` when your change affects those areas.
- If you change Flask routes, keep the existing Swagger route decorator pattern intact.

Pull requests are reviewed by the SimpleChat team and go through repository validation. Depending on the files changed, that can include Python syntax checks, release-note validation, Swagger route validation, and additional maintainer review. Maintainers may also run additional security or AI-assisted review before merge.

## Security and Repo Conventions

- Never commit secrets, keys, or environment-specific credentials.
- Review [SECURITY.md](./SECURITY.md) before submitting security-sensitive changes.
- Follow the repository's existing structure and conventions instead of introducing broad cleanup changes.
- If you use AI-assisted tooling while contributing, also review [CLAUDE.md](./CLAUDE.md) and [.github/copilot-instructions.md](./.github/copilot-instructions.md) for repo-specific guidance.

## Need Help?

If you are unsure about the right target branch or how to structure a change, open a draft pull request against `Development` and explain the question in the description. That gives the maintainers a concrete starting point for feedback.
