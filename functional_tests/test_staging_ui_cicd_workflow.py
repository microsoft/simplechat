# test_staging_ui_cicd_workflow.py
#!/usr/bin/env python3
"""
Functional test for staging UI CI/CD workflow assets.
Version: 0.241.018
Implemented in: 0.241.014

This test ensures that the reusable GitHub Actions staging deployment workflow,
Azure/GitHub bootstrap script, and Playwright smoke test are present and wired
for OIDC-based azd deployment followed by authenticated UI validation.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def repo_root():
    """Return the repository root path."""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def read_repo_file(*parts):
    """Read a repository file for assertions."""
    file_path = os.path.join(repo_root(), *parts)
    with open(file_path, 'r', encoding='utf-8') as handle:
        return handle.read()


def assert_fragments(content, fragments, label):
    """Validate that each expected fragment exists in the supplied content."""
    for fragment in fragments:
        if fragment not in content:
            print(f'Missing {label} fragment: {fragment}')
            return False
    return True


def test_staging_workflow_configuration():
    """Verify the staging workflow runs azd deployment and UI tests."""
    print('Testing staging workflow configuration...')

    try:
        content = read_repo_file('.github', 'workflows', 'staging-azd-ui-tests.yml')
        required_fragments = [
            'name: Staging AZD Deploy and UI Smoke Tests',
            'branches:',
            '- Staging',
            "name: ${{ vars.STAGING_GITHUB_ENVIRONMENT || 'Staging' }}",
            'id-token: write',
            'azure/login@v2',
            'Azure/setup-azd@v2',
            '--federated-credential-provider github',
            'azd up --no-prompt',
            'azd deploy --no-prompt',
            'Waiting up to 15 minutes for staging to finish App Service warm-up.',
            '/external/healthcheckz',
            'SIMPLECHAT_UI_STORAGE_STATE_B64',
            'SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64',
            'SIMPLECHAT_UI_AUTH_RESOURCE',
            'SIMPLECHAT_UI_ACCESS_TOKEN',
            'az account get-access-token --resource',
            'PLAYWRIGHT_SERVICE_URL',
            'actions/setup-node@v4',
            'ui_tests/playwright-workspaces/package-lock.json',
            'npm run test:staging:azure',
            'ui_tests/requirements.txt',
            'python -m pytest "$PYTEST_TARGET" -m ui -ra',
            'actions/upload-artifact@v4',
        ]

        if not assert_fragments(content, required_fragments, 'workflow'):
            return False

        print('Staging workflow is configured for OIDC azd deployment and UI smoke tests.')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_branch_flow_uses_actual_branch_casing():
    """Verify branch-flow guard matches the repository's branch names."""
    print('Testing branch-flow casing configuration...')

    try:
        content = read_repo_file('.github', 'workflows', 'enforce-branch-flow.yml')
        required_fragments = [
            "github.event.pull_request.base.ref == 'Staging'",
            "github.event.pull_request.head.ref != 'Development'",
            "github.event.pull_request.head.ref != 'Staging'",
            "Pull requests into 'Staging' must originate from branch 'Development'.",
            "Pull requests into 'main' must originate from branch 'Staging'.",
        ]

        if not assert_fragments(content, required_fragments, 'branch-flow workflow'):
            return False

        print('Branch-flow guard uses the actual Development and Staging branch casing.')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_bootstrap_script_configuration():
    """Verify the bootstrap script creates OIDC and GitHub Environment settings."""
    print('Testing staging bootstrap script configuration...')

    try:
        content = read_repo_file('deployers', 'Initialize-GitHubActionsStaging.ps1')
        required_fragments = [
            'az ad app create',
            'az ad sp create',
            'az ad app federated-credential create',
            'repo:${Repository}:environment:${EnvironmentName}',
            'Contributor',
            'User Access Administrator',
            'gh api --method PUT',
            'gh variable set',
            'gh secret set',
            'AZD_ENV_FILE_B64',
            'SIMPLECHAT_UI_STORAGE_STATE_B64',
            'SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64',
            'Microsoft.LoadTestService/playwrightWorkspaces',
            'Playwright Workspace Contributor',
            'PLAYWRIGHT_SERVICE_URL',
            'SIMPLECHAT_UI_AUTH_RESOURCE',
            'ENABLE_CI_BEARER_SESSION_AUTH',
            'CI_BEARER_SESSION_ALLOWED_APP_IDS',
            'AppRoleValue "Admin"',
            'Assigning Enterprise App role',
        ]

        if not assert_fragments(content, required_fragments, 'bootstrap script'):
            return False

        print('Bootstrap script includes Azure OIDC, RBAC, GitHub secret, and app assignment support.')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_staging_smoke_test_configuration():
    """Verify the live Playwright smoke test targets the deployed chat workflow."""
    print('Testing staging Playwright smoke test configuration...')

    try:
        content = read_repo_file('ui_tests', 'test_staging_chat_smoke.py')
        required_fragments = [
            'Version: 0.241.018',
            'SIMPLECHAT_UI_BASE_URL',
            'SIMPLECHAT_UI_STORAGE_STATE',
            'SIMPLECHAT_UI_ADMIN_STORAGE_STATE',
            'SIMPLECHAT_UI_ACCESS_TOKEN',
            '/ci-auth/session',
            '@pytest.mark.ui',
            'page.goto(f"{BASE_URL}/chats"',
            '#new-conversation-btn',
            '#user-input',
            '#send-btn',
            '.ai-message .message-text',
            'context.request.delete',
            'context.tracing.start',
        ]

        if not assert_fragments(content, required_fragments, 'smoke test'):
            return False

        print('Staging smoke test validates authenticated chat creation and assistant response.')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_playwright_workspaces_runner_configuration():
    """Verify the Azure Playwright Workspaces runner is configured."""
    print('Testing Playwright Workspaces runner configuration...')

    try:
        package_content = read_repo_file('ui_tests', 'playwright-workspaces', 'package.json')
        service_config = read_repo_file('ui_tests', 'playwright-workspaces', 'playwright.service.config.js')
        smoke_test = read_repo_file('ui_tests', 'playwright-workspaces', 'staging-chat-smoke.spec.js')

        required_package_fragments = [
            '@azure/playwright',
            '@azure/identity',
            '@playwright/test',
            'test:staging:azure',
        ]
        required_service_fragments = [
            'createAzurePlaywrightConfig',
            'DefaultAzureCredential',
            'ServiceOS.LINUX',
            'PLAYWRIGHT_SERVICE_URL',
        ]
        required_smoke_fragments = [
            'Version: 0.241.018',
            'SIMPLECHAT_UI_BASE_URL',
            'SIMPLECHAT_UI_STORAGE_STATE',
            'SIMPLECHAT_UI_ADMIN_STORAGE_STATE',
            'SIMPLECHAT_UI_ACCESS_TOKEN',
            '/ci-auth/session',
            'page.goto(`${baseUrl}/chats`',
            '#new-conversation-btn',
            '#user-input',
            '#send-btn',
            '.ai-message .message-text',
            'page.context().request.delete',
        ]

        if not assert_fragments(package_content, required_package_fragments, 'Playwright package'):
            return False
        if not assert_fragments(service_config, required_service_fragments, 'Playwright service config'):
            return False
        if not assert_fragments(smoke_test, required_smoke_fragments, 'Playwright Workspaces smoke test'):
            return False

        print('Playwright Workspaces runner is configured for Azure-hosted browser smoke tests.')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_staging_workflow_configuration,
        test_branch_flow_uses_actual_branch_casing,
        test_bootstrap_script_configuration,
        test_staging_smoke_test_configuration,
        test_playwright_workspaces_runner_configuration,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
