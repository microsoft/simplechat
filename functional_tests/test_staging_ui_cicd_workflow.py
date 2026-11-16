# test_staging_ui_cicd_workflow.py
"""Functional tests for authenticated validation of an existing staging deployment.

Version: 0.261.402
Implemented in: 0.241.014; validation-only workflow in 0.261.399; isolated validation in 0.261.400; pinned onboarding in 0.261.401

The workflow must not provision or deploy resources. The standalone, explicitly
invoked deployment bootstrap remains separate and retains its existing contract.
"""

import ast
import json
from pathlib import Path
import re
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def assert_fragments(content, fragments, label):
    for fragment in fragments:
        assert fragment in content, f"Missing {label} fragment: {fragment}"


@pytest.fixture(scope="module")
def workflow():
    source = read_repo_file(".github", "workflows", "staging-ui-smoke.yml")
    return yaml.load(source, Loader=yaml.BaseLoader)


def test_staging_workflow_configuration(workflow):
    events = workflow["on"]
    assert events["push"]["branches"] == ["Staging"]
    assert set(events) == {"push", "pull_request", "workflow_dispatch"}
    assert events["pull_request"]["branches"] == ["Staging", "paullizer-react-v2-ui"]
    assert events["pull_request"]["paths"] == [
        ".github/workflows/staging-ui-smoke.yml",
        "ui_tests/test_staging_chat_smoke.py",
        "ui_tests/playwright-workspaces/**",
    ]
    assert "azd_command" not in events["workflow_dispatch"]["inputs"]
    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    job = workflow["jobs"]["ui-smoke"]
    assert job["environment"]["name"] == "Staging-Validation"
    assert job["if"] == "${{ github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository }}"
    assert job["env"]["SIMPLECHAT_UI_BASE_URL"] == "${{ vars.SIMPLECHAT_UI_BASE_URL }}"
    assert job["env"]["SIMPLECHAT_UI_TERMS_SHA256"] == "${{ vars.SIMPLECHAT_UI_TERMS_SHA256 }}"
    assert not any(name.startswith("AZD_") for name in job["env"])
    assert "AZURE_SUBSCRIPTION_ID" not in job["env"]
    assert "PLAYWRIGHT_SERVICE_URL" not in job["env"]
    assert job["timeout-minutes"] == "30"
    actions = [step["uses"] for step in job["steps"] if "uses" in step]
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in actions)
    assert not any(action.lower().startswith("azure/setup-azd@") for action in actions)
    scripts = "\n".join(step.get("run", "") for step in job["steps"])
    assert not re.search(r"\bazd\s+(?:up|deploy|env|auth)\b", scripts)
    assert "AZD_ENV_FILE_B64" not in scripts and "AZD_CONFIG_FILE_B64" not in scripts
    assert not re.search(r"\baz\s+(?:deployment|role\s+assignment|ad\s+(?:app|sp))\b", scripts)
    assert "simplechat-2026beta" not in scripts
    assert "This workflow does not deploy code or provision Azure resources." in scripts
    assert not any(step.get("working-directory") == "deployers" for step in job["steps"])


def test_staging_requires_authentication_and_verified_transport(workflow):
    steps = workflow["jobs"]["ui-smoke"]["steps"]
    validation = next(step for step in steps if step["name"] == "Validate required environment values")
    assert_fragments(validation["run"], [
        "required=(SIMPLECHAT_UI_BASE_URL)",
        "required+=(AZURE_CLIENT_ID AZURE_TENANT_ID)",
        "SIMPLECHAT_UI_STORAGE_STATE_B64",
        "SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64",
        "SIMPLECHAT_UI_AUTH_RESOURCE",
        '[[ ${#missing[@]} -gt 0 ]]',
        "exit 1",
        '!= https://*',
    ], "required staging configuration")
    login = next(step for step in steps if step.get("uses", "").startswith("azure/login@"))
    assert login["with"] == {
        "client-id": "${{ env.AZURE_CLIENT_ID }}",
        "tenant-id": "${{ env.AZURE_TENANT_ID }}",
        "allow-no-subscriptions": "true",
    }
    assert login["if"] == "${{ env.SIMPLECHAT_UI_AUTH_RESOURCE != '' }}"
    token = next(step for step in steps if step["name"] == "Acquire SimpleChat UI access token")
    assert token["if"] == "${{ env.SIMPLECHAT_UI_AUTH_RESOURCE != '' }}"
    assert 'az account get-access-token --resource "$SIMPLECHAT_UI_AUTH_RESOURCE"' in token["run"]
    assert "::add-mask::$access_token" in token["run"]
    reachability = next(step for step in steps if step["name"] == "Wait for staging endpoint reachability")
    assert "Reachability is not application readiness" in reachability["run"]
    assert not re.search(r"\bcurl\b[^\n]*(?:\s-k\b|--insecure\b)", reachability["run"])
    assert "Staging health check passed." not in reachability["run"]
    assert "exit 1" in reachability["run"]
    assert any("npm run test:staging\n" in step.get("run", "") for step in steps)
    assert any("npx playwright install --with-deps chromium" in step.get("run", "") for step in steps)
    assert any('python -m pytest "$PYTEST_TARGET" -m ui -ra' in step.get("run", "") for step in steps)
    assert any("functional_tests/test_staging_terms_onboarding.py" in step.get("run", "") for step in steps)
    assert any("node --test functional_tests/test_staging_terms_onboarding.mjs" in step.get("run", "") for step in steps)
    assert not any(step.get("continue-on-error") == "true" for step in steps)


def test_staging_artifacts_exclude_browser_credentials_and_traces(workflow):
    steps = workflow["jobs"]["ui-smoke"]["steps"]
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["path"].splitlines() == [
        "ui_tests/artifacts/*.png",
        "ui_tests/playwright-workspaces/test-results/**/*.png",
    ]
    assert upload["with"]["retention-days"] == "7"
    assert upload["if"] == "always()"


def test_branch_flow_uses_actual_branch_casing():
    content = read_repo_file(".github", "workflows", "enforce-branch-flow.yml")
    assert_fragments(content, [
        "github.event.pull_request.base.ref == 'Staging'",
        "github.event.pull_request.head.ref != 'Development'",
        "github.event.pull_request.head.ref != 'Staging'",
        "Pull requests into 'Staging' must originate from branch 'Development'.",
        "Pull requests into 'main' must originate from branch 'Staging'.",
    ], "branch-flow workflow")


def test_bootstrap_script_configuration():
    content = read_repo_file("deployers", "Initialize-GitHubActionsStaging.ps1")
    assert_fragments(content, [
        "az ad app create", "az ad sp create", "az ad app federated-credential create",
        "repo:${Repository}:environment:${EnvironmentName}",
        "Contributor", "User Access Administrator",
        "gh api --method PUT", "gh variable set", "gh secret set",
        "AZD_ENV_FILE_B64", "SIMPLECHAT_UI_STORAGE_STATE_B64",
        "SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64",
        "Microsoft.LoadTestService/playwrightWorkspaces",
        "Playwright Workspace Contributor", "PLAYWRIGHT_SERVICE_URL",
        "SIMPLECHAT_UI_AUTH_RESOURCE", "ENABLE_CI_BEARER_SESSION_AUTH",
        "CI_BEARER_SESSION_ALLOWED_APP_IDS", 'AppRoleValue "Admin"',
        "Assigning Enterprise App role",
    ], "standalone deployment bootstrap")


def test_staging_smoke_test_configuration():
    source = read_repo_file("ui_tests", "test_staging_chat_smoke.py")
    assert_fragments(source, [
        "SIMPLECHAT_UI_BASE_URL", "SIMPLECHAT_UI_STORAGE_STATE",
        "SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "SIMPLECHAT_UI_ACCESS_TOKEN",
        "/ci-auth/session", "@pytest.mark.ui", 'page.goto(f"{BASE_URL}/chats"',
        "#new-conversation-btn", "#user-input", "#send-btn",
        ".ai-message .message-text", "context.request.delete", "context.tracing.start",
        "complete_staging_terms_onboarding", "SIMPLECHAT_UI_TERMS_SHA256",
        "#new-conversation-btn:visible, #sidebar-new-chat-btn:visible",
        "EXPECTED_RESPONSE",
        "arg=EXPECTED_RESPONSE",
        "text.includes(expectedResponseText)",
    ], "authenticated smoke test")
    tree = ast.parse(source)
    authorization = [
        node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name) and target.value.id == "auth_headers"
            and isinstance(target.slice, ast.Constant) and target.slice.value == "Authorization"
            for target in node.targets
        )
    ]
    assert len(authorization) == 1 and isinstance(authorization[0], ast.JoinedStr)
    assert any(
        isinstance(value, ast.FormattedValue)
        and isinstance(value.value, ast.Name) and value.value.id == "ACCESS_TOKEN"
        for value in authorization[0].values
    )


def test_playwright_workspaces_runner_configuration():
    package = json.loads(read_repo_file("ui_tests", "playwright-workspaces", "package.json"))
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    assert {"@azure/playwright", "@azure/identity", "@playwright/test"} <= dependencies.keys()
    assert "test:staging:azure" in package["scripts"]
    assert package["scripts"]["test:staging"] == (
        "playwright test staging-chat-smoke.spec.js --config=playwright.config.js --workers=1"
    )
    local_config = read_repo_file("ui_tests", "playwright-workspaces", "playwright.config.js")
    assert "PLAYWRIGHT_SERVICE_URL" not in local_config
    assert "@azure/playwright" not in local_config
    service_config = read_repo_file("ui_tests", "playwright-workspaces", "playwright.service.config.js")
    assert_fragments(service_config, [
        "createAzurePlaywrightConfig", "DefaultAzureCredential",
        "ServiceOS.LINUX", "PLAYWRIGHT_SERVICE_URL",
    ], "Playwright service configuration")
    smoke_test = read_repo_file("ui_tests", "playwright-workspaces", "staging-chat-smoke.spec.js")
    assert_fragments(smoke_test, [
        "SIMPLECHAT_UI_BASE_URL", "SIMPLECHAT_UI_STORAGE_STATE",
        "SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "SIMPLECHAT_UI_ACCESS_TOKEN",
        "/ci-auth/session", "page.goto(`${baseUrl}/chats`",
        "#new-conversation-btn", "#user-input", "#send-btn",
        ".ai-message .message-text", "page.context().request.delete",
        "completeStagingTermsOnboarding", "SIMPLECHAT_UI_TERMS_SHA256",
        "#new-conversation-btn:visible, #sidebar-new-chat-btn:visible",
        "expectedResponse",
        "text.includes(expectedResponseText)",
    ], "Playwright smoke test")


def test_local_authentication_template_matches_application_setting_names():
    template = read_repo_file("application", "single_app", "example.env")
    values = dict(
        line.split("=", 1) for line in template.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    )
    assert {"TENANT_ID", "CLIENT_ID", "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET", "SECRET_KEY"} <= values.keys()
    assert "<your-local-app-registration-client-secret>" in values["MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"]
    config = ast.parse(read_repo_file("application", "single_app", "config.py"))
    credential = next(
        node.value for node in config.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CLIENT_SECRET" for target in node.targets)
    )
    assert isinstance(credential, ast.Call)
    assert credential.args[0].value == "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"


def test_cosmos_contract_job_keeps_complete_guarded_selection_and_bounded_runtime():
    source = read_repo_file(".github", "workflows", "cosmos-response-contract-check.yml")
    contracts = yaml.load(source, Loader=yaml.BaseLoader)
    job = contracts["jobs"]["cosmos-contracts"]
    assert job["timeout-minutes"] == "30"
    commands = [step["run"] for step in job["steps"] if "run" in step]
    assert commands[-1] == "python scripts/check_cosmos_response_boundaries.py --run-contracts"
    assert not any("-k " in command or "--maxfail" in command for command in commands)
    assert job["env"]["TIKTOKEN_CACHE_DIR"] == "${{ github.workspace }}/.cosmos-contract-assets/tiktoken"
    assert commands.index(
        'python -c "import tiktoken; tiktoken.get_encoding(\'cl100k_base\'); tiktoken.get_encoding(\'o200k_base\')"'
    ) < commands.index("python scripts/check_cosmos_response_boundaries.py --run-contracts")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
