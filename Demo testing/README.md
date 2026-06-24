# Demo Testing Walkthrough

Version: **0.250.024**
Implemented in version: **0.250.024**

This folder is presentation material for showing developers how SimpleChat testing works during local development and in CI/CD. The examples are intentionally small and readable so the audience can follow the shape of the test while you run it live.

## Demo Goals

- Demonstrate test creation with Playwright, using the Playwright Python SDK locally and the existing Azure Playwright Workspaces runner for deployed environments.
- Show how functional tests and selected end-to-end tests validate behavior while changes are being made.
- Explain authentication strategies for role-based testing, with CI impersonating a class of user rather than a named person.
- Show where GitHub workflows enforce guardrails and verify requirements earlier in the development cycle.
- Discuss test data generation using local scripts, including scripts developed with AI, without asking the model to generate large data sets directly during test execution.

## Files

- `test_unit_model_endpoint_helpers.py` is a pure Python unit test for small helper functions. It validates isolated function inputs and outputs only.
- `test_functional_application_logic.py` is a pure Python functional test for backend application logic. It does not use Playwright, a browser, a live server, or authentication.
- `test_functional_agent_runtime.py` validates a small model endpoint runtime contract. It can optionally query a live SimpleChat environment for any visible agent when authenticated state is supplied.
- `test_e2e_chat_file_upload.py` opens a headed local browser, lets the presenter sign in, uploads a small text file to Personal Workspace, launches chat with that workspace document, sends a prompt about the file, waits for an assistant response, and cleans up the created document/conversation.
- `test_playwright_profile_memory.py` opens the profile page, lets the presenter sign in, creates a fact memory through the UI, verifies the API/UI response, and deletes the demo memory.
- `demo_helpers.py` contains shared local Playwright helpers for headed browser launch, manual login waiting, storage-state reuse, and artifact paths.
- `fixtures/simplechat_demo_upload.txt` is the tiny upload file used by the chat upload demo.

## Local Setup

Start SimpleChat locally before running the Playwright demos:

```powershell
cd E:\repos\simplechat\application\single_app
..\..\.venv\Scripts\python.exe app.py
```

The local demo tests default to:

```text
https://127.0.0.1:5000
```

The tests are headed by default. If no storage state file is supplied, the browser opens and waits while you sign in manually. If `SIMPLECHAT_DEMO_STORAGE_STATE` is supplied, the demos expect it to authenticate automatically and fail fast if the stored session is missing or stale.

Run virtual environment script to activate

```powershell
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& e:\repos\simplechat\.venv\Scripts\Activate.ps1)
```

Run the functional agent runtime contract test:

```powershell
cd "E:\repos\simplechat\Demo testing"
python -m pytest "test_functional_agent_runtime.py" -ra -v
```

Run the pure Python unit test:

```powershell
cd "E:\repos\simplechat\Demo testing"
python -m pytest "test_unit_model_endpoint_helpers.py" -ra -v -s
```

This is the smallest test type in the demo set: it checks isolated helper function inputs and outputs only. It does not validate a broader application workflow.

Run the pure Python functional application-logic test:

```powershell
cd "E:\repos\simplechat\Demo testing"
python -m pytest "test_functional_application_logic.py" -ra -v -s
```

This test is the simplest example of a functional test: it imports application modules and validates backend decisions directly, without Playwright, browser automation, storage state, or a running Flask server.

Run the optional live agent availability check after capturing authenticated browser state:

```powershell
cd "E:\repos\simplechat\Demo testing"
$env:SIMPLECHAT_DEMO_FUNCTIONAL_LIVE = "1"
$env:SIMPLECHAT_DEMO_BASE_URL = "https://127.0.0.1:5000"
$env:SIMPLECHAT_DEMO_STORAGE_STATE = "E:\repos\simplechat\Demo testing\artifacts\auth\local_storage_state.json"
Remove-Item Env:SIMPLECHAT_DEMO_AGENT_KEYWORD -ErrorAction SilentlyContinue
Remove-Item Env:SIMPLECHAT_DEMO_REQUIRE_GLOBAL_AGENT -ErrorAction SilentlyContinue
python -m pytest "test_functional_agent_runtime.py" -ra -v -s
```

Set `SIMPLECHAT_DEMO_AGENT_KEYWORD` only when you want to narrow the live check to a specific visible agent or model label. Set `SIMPLECHAT_DEMO_REQUIRE_GLOBAL_AGENT=1` only when the signed-in user is expected to see merged global agents.

Run the optional headed browser version when you want developers to see the UI while the test runs:

```powershell
cd "E:\repos\simplechat\Demo testing"
$env:SIMPLECHAT_DEMO_FUNCTIONAL_LIVE = "1"
$env:SIMPLECHAT_DEMO_SHOW_BROWSER = "1"
$env:SIMPLECHAT_DEMO_BASE_URL = "https://127.0.0.1:5000"
$env:SIMPLECHAT_DEMO_STORAGE_STATE = "E:\repos\simplechat\Demo testing\artifacts\auth\local_storage_state.json"
$env:SIMPLECHAT_DEMO_BROWSER_PAUSE_MS = "30000"
$env:SIMPLECHAT_DEMO_POST_RESPONSE_PAUSE_MS = "10000"
$env:SIMPLECHAT_DEMO_BROWSER_AGENT_KEYWORD = "Simple Chat"
$env:SIMPLECHAT_DEMO_AGENT_PROMPT = "Demo test: do not search documents or workspaces. Reply exactly: Simple Chat agent demo response."
$env:SIMPLECHAT_DEMO_EXPECTED_RESPONSE_TEXT = "Simple Chat agent demo response"
python -m pytest "test_functional_agent_runtime.py" -ra -v -s
```

The browser demo opens `/chats`, verifies the authenticated agent API, prints visible agents, picks the first agent matching `SIMPLECHAT_DEMO_BROWSER_AGENT_KEYWORD` (defaulting to Simple Chat), sends a short prompt, waits for a new assistant response containing `SIMPLECHAT_DEMO_EXPECTED_RESPONSE_TEXT` to finish streaming, then keeps the browser open for `SIMPLECHAT_DEMO_POST_RESPONSE_PAUSE_MS` so the presenter can click around. Screenshots and traces are written under `Demo testing/artifacts/`.

The file-upload demo accepts the upload user-agreement modal automatically when that gate is enabled, persists model-chat mode by setting `enable_agents=false`, waits for the workspace upload and document processing to finish, clicks the uploaded document's visible **Chat** button in Personal Workspace, then opens the chat document picker and verifies the uploaded file is selected before sending the prompt.

Run the local personal workspace upload plus chat end-to-end demo from the repo root:

```powershell
cd "E:\repos\simplechat\Demo testing"
$env:SIMPLECHAT_DEMO_BASE_URL = "https://127.0.0.1:5000"
$env:SIMPLECHAT_DEMO_STORAGE_STATE = "E:\repos\simplechat\Demo testing\artifacts\auth\local_storage_state.json"
$env:SIMPLECHAT_DEMO_FILE_DISABLE_AGENTS = "1"
$env:SIMPLECHAT_DEMO_FILE_EXPECTED_RESPONSE_TEXT = "SimpleChat local Playwright testing demo"
$env:SIMPLECHAT_DEMO_FILE_PROMPT = "Using only the selected workspace file, reply exactly: SimpleChat local Playwright testing demo."
$env:SIMPLECHAT_DEMO_FILE_POST_RESPONSE_PAUSE_MS = "10000"
$env:SIMPLECHAT_DEMO_FILE_BROWSER_PAUSE_MS = "30000"
python -m pytest "test_e2e_chat_file_upload.py" -s -ra -v
```

Run the profile memory Playwright demo from the repo root:

```powershell
cd "E:\repos\simplechat\Demo testing"
$env:SIMPLECHAT_DEMO_FUNCTIONAL_LIVE = "1"
$env:SIMPLECHAT_DEMO_SHOW_BROWSER = "1"
$env:SIMPLECHAT_DEMO_BASE_URL = "https://127.0.0.1:5000"
$env:SIMPLECHAT_DEMO_STORAGE_STATE = "E:\repos\simplechat\Demo testing\artifacts\auth\local_storage_state.json"
$env:SIMPLECHAT_DEMO_PROFILE_MEMORY_PAUSE_MS = "10000"
python -m pytest "test_playwright_profile_memory.py" -s -ra -v
```

The profile memory demo uses the saved storage state, opens the Profile Settings tab, scrolls the Fact Memory card into view, creates a memory, opens the Memory Manager, verifies the memory is visible, then pauses for `SIMPLECHAT_DEMO_PROFILE_MEMORY_PAUSE_MS`.

If you want to avoid signing in interactively every time, capture authenticated browser state once:

```powershell
cd E:\repos\simplechat
$env:SIMPLECHAT_DEMO_BASE_URL = "https://127.0.0.1:5000"
.\.venv\Scripts\python.exe -m playwright codegen --ignore-https-errors "$env:SIMPLECHAT_DEMO_BASE_URL/chats" --save-storage "Demo testing\artifacts\auth\local_storage_state.json"
$env:SIMPLECHAT_DEMO_STORAGE_STATE = "E:\repos\simplechat\Demo testing\artifacts\auth\local_storage_state.json"
```

Do not commit storage state, cookies, API keys, bearer tokens, or `.env` files.

## Azure Playwright Workspaces

Use Azure Playwright Workspaces for deployed URLs, not for `127.0.0.1`. An Azure-hosted browser cannot reach the local loopback address on your laptop.

The repo already has the Azure workspace runner here:

```text
ui_tests/playwright-workspaces/staging-chat-smoke.spec.js
ui_tests/playwright-workspaces/playwright.service.config.js
.github/workflows/staging-azd-ui-tests.yml
```

For a deployed SimpleChat app, point the existing runner at the deployment:

```powershell
cd E:\repos\simplechat
$env:SIMPLECHAT_UI_BASE_URL = "https://simplechat-20260506-app.azurewebsites.net"
$env:PLAYWRIGHT_SERVICE_URL = $env:PLAYWRIGHT_API_ENDPOINT
npm --prefix ui_tests\playwright-workspaces run test:staging:azure
```

That runner uses Azure-hosted browsers and `DefaultAzureCredential` via the Azure Playwright package. For local demos, the Python Playwright SDK examples in this folder are easier because they can open a visible browser on the presenter machine and let the presenter sign in.

## Authentication Talk Track

### Local Development

For local testing, use either manual interactive login or a saved Playwright storage state. This represents the real browser experience and is easy to explain during a live demo:

1. Start the local app.
2. Launch a headed Playwright test.
3. Sign in with the desired account.
4. Let the test continue from the authenticated browser session.

This is useful for debugging UI behavior, testing selectors, and validating workflows while code is changing.

### CI/CD Role-Based Testing

For GitHub Actions, the staging workflow avoids tying tests to an individual developer account. Instead, it uses a service principal configured as a class of test user.

The process is:

1. GitHub Actions authenticates to Azure using OIDC and the configured service principal.
2. The workflow requests an access token for the SimpleChat Enterprise App resource, such as `api://<client-id>`.
3. The staging deployment exposes `/ci-auth/session` only when CI bearer session auth is enabled.
4. SimpleChat validates the bearer token and checks that the caller app id is explicitly allowed.
5. SimpleChat creates a normal Flask browser session for the test run.
6. The Playwright smoke test uses that session to exercise the app as the configured role, such as Admin.

The controls that close this off are just as important as the access path:

- Keep `ENABLE_CI_BEARER_SESSION_AUTH` disabled except in environments intended for CI testing.
- Keep `CI_BEARER_SESSION_ALLOWED_APP_IDS` restricted to the CI service principal app ids.
- Assign only the app roles required for the test class, such as Admin for admin smoke tests or a narrower role for user smoke tests.
- Use short-lived OIDC-issued tokens instead of long-lived passwords or browser cookies in GitHub Actions.
- Remove the service principal role assignment or allowed app id when the CI test class is no longer needed.

This is impersonating a class of user, not a specific person. That makes the tests repeatable, auditable, and suitable for automation.

## GitHub Guardrails

Use the existing workflows and prompts as examples of GitHub-based controls that help catch problems before merge or deploy:

- `.github/workflows/staging-azd-ui-tests.yml` deploys staging and runs browser smoke tests.
- Broken access control checks help prevent accidental trust in caller-supplied ids.
- Prompt-based review workflows can focus an AI review on security, XSS, external browser assets, settings exposure, package pinning, or route authentication.
- Required checks and protected environments can prevent deployment until the expected tests and validations pass.

The key message is that GitHub automation is not only for pass/fail tests. It can encode security posture, deployment rules, role assumptions, and workflow controls.

## Test Data Creation Talk Track

For test data creation, use your local scripts under:

```text
E:\repos\scripts
```

The useful point for developers is that AI can help create reusable scripts that generate simulated data deterministically. During test execution, the model should not be asked to invent large data sets on the fly. Instead, generated scripts can create repeatable fixtures, seed data, users, files, or payloads quickly and consistently.

## Suggested Live Demo Order

1. Show the functional agent runtime test to explain fast backend checks.
2. Run the profile memory Playwright test to show a focused UI workflow.
3. Run the personal workspace upload end-to-end test and sign in live when the browser appears.
4. Open the staging GitHub workflow and explain how the same concepts move into CI/CD.
5. Discuss role-based CI authentication and how the bearer session path is enabled and disabled.
6. Show the local test data scripts and explain why reusable generators beat ad hoc model output during tests.