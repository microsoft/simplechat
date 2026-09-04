# test_teams_app_sso.py
"""
Functional test for Microsoft Teams app SSO.
Version: 0.242.072
Implemented in: 0.242.072

This test ensures the Teams app SSO configuration, token-exchange route,
security headers, deployment settings, and documentation stay wired together.
"""

import ast
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
APP_FILE = REPO_ROOT / "application" / "single_app" / "app.py"
AUTH_ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_frontend_authentication.py"
LOGIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "login.html"
TEAMS_SDK_LICENSE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "MicrosoftTeams.min.LICENSE.txt"
TEAMS_MANIFEST = REPO_ROOT / "application" / "teams_app" / "manifest.template.json"
MAIN_BICEP = REPO_ROOT / "deployers" / "bicep" / "main.bicep"
APP_SERVICE_BICEP = REPO_ROOT / "deployers" / "bicep" / "modules" / "appService.bicep"
DEPLOYER_VERSION = REPO_ROOT / "deployers" / "version.txt"
FEATURE_DOC = REPO_ROOT / "docs" / "explanation" / "features" / "v0.242.072" / "TEAMS_APP_SSO.md"
HOW_TO_DOC = REPO_ROOT / "docs" / "how-to" / "teams_app.md"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_names(source):
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def test_config_security_and_cloud_defaults():
    """Validate Teams SSO app settings, cloud defaults, CSP, and cookies."""
    source = _read(CONFIG_FILE)
    required_snippets = [
        'VERSION = "0.242.072"',
        'ENABLE_TEAMS_SSO = os.getenv("ENABLE_TEAMS_SSO", "false").lower() == "true"',
        'TEAMS_APP_RESOURCE = os.getenv("TEAMS_APP_RESOURCE", "")',
        'TEAMS_SUCCESS_REDIRECT_PATH = os.getenv("TEAMS_SUCCESS_REDIRECT_PATH", "/chats")',
        'TEAMS_FRAME_ANCESTORS = _split_origin_list(os.getenv("TEAMS_FRAME_ANCESTORS", ""))',
        'CUSTOM_TEAMS_ORIGINS = _split_origin_list(os.getenv("CUSTOM_TEAMS_ORIGINS", ""))',
        '"https://teams.microsoft.us"',
        '"https://*.teams.microsoft.us"',
        '"https://teams.microsoft.com"',
        '"https://*.teams.microsoft.com"',
        "SESSION_COOKIE_SAMESITE = 'None'",
        'SESSION_COOKIE_SECURE = True',
        'TEAMS_ALLOWED_ORIGINS',
        'FRAME_ANCESTORS_DIRECTIVE',
        "if not ENABLE_TEAMS_SSO:",
        "SECURITY_HEADERS['X-Frame-Options'] = 'DENY'",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing config snippets: {missing}"


def test_app_origin_guard_supports_teams_exchange():
    """Validate wildcard origin matching and pre-session Teams exchange guard."""
    source = _read(APP_FILE)
    functions = _function_names(source)
    required_functions = {
        '_origin_matches_allowed_origin',
        '_origin_matches_any_allowed_origin',
        'enforce_same_origin_for_state_changing_requests',
    }
    assert not (required_functions - functions)

    required_snippets = [
        "allowed_host.startswith('*.')",
        "request_host.endswith(allowed_suffix)",
        "request.path == '/auth/teams/token-exchange' and ENABLE_TEAMS_SSO",
        "if 'user' not in session and not is_teams_token_exchange:",
        "_origin_matches_any_allowed_origin(request_origin, allowed_origins)",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing app guard snippets: {missing}"


def test_auth_route_teams_token_exchange_contract():
    """Validate the token exchange route handles Teams SSO safely."""
    source = _read(AUTH_ROUTE_FILE)
    functions = _function_names(source)
    required_functions = {
        '_decode_teams_assertion_claims',
        '_fetch_graph_me',
        '_build_teams_session_user',
        'teams_token_exchange',
    }
    assert not (required_functions - functions)

    required_snippets = [
        "@bp.route('/auth/teams/token-exchange', methods=['POST'])",
        '@swagger_route(security=get_auth_security())',
        'if not ENABLE_TEAMS_SSO:',
        'request.get_json(silent=True)',
        'if not isinstance(data, dict):',
        "if not isinstance(teams_token, str) or not teams_token.strip():",
        'authority_override=get_graph_authority()',
        'acquire_token_on_behalf_of(',
        "get_graph_endpoint('/me')",
        "session['user'] = session_user",
        "session['last_activity_epoch'] = int(time.time())",
        "log_user_login(session_user.get('oid'), 'teams_sso')",
        "record_user_login_session_activity(session)",
        '"token_exchange_failed"',
        '"identity_incomplete"',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing auth route snippets: {missing}"


def test_login_template_and_manifest_contract():
    """Validate the Teams login page and manifest placeholders align."""
    template = _read(LOGIN_TEMPLATE)
    sdk_license = _read(TEAMS_SDK_LICENSE)
    manifest = json.loads(_read(TEAMS_MANIFEST))

    template_required = [
        "MicrosoftTeams.min.js') }}?v={{ config['VERSION'] }}",
        'appResource: {{ teams_app_resource|tojson }}',
        'customOrigins: {{ custom_teams_origins|tojson }}',
        'successRedirectPath: {{ teams_success_redirect_path|tojson }}',
        "standardLoginUrl: {{ url_for('login', teams='false')|tojson }}",
        'microsoftTeams.app.initialize(teamsSettings.customOrigins)',
        'microsoftTeams.authentication.getAuthToken(authOptions)',
        "fetch('/auth/teams/token-exchange'",
        "classList.add('d-none')",
        "classList.remove('d-none')",
    ]
    missing_template = [snippet for snippet in template_required if snippet not in template]
    assert not missing_template, f"Missing login template snippets: {missing_template}"
    assert 'style.display' not in template

    assert manifest['id'] == 'TEAMS_APP_ID'
    assert manifest['staticTabs'][0]['contentUrl'] == 'https://HOSTNAME/login?teams=true'
    assert manifest['webApplicationInfo']['id'] == 'CLIENT_ID'
    assert manifest['webApplicationInfo']['resource'] == 'TEAMS_APP_RESOURCE_URI'
    assert manifest['validDomains'] == ['HOSTNAME']
    assert 'Package: @microsoft/teams-js' in sdk_license
    assert 'Pinned version: 2.19.0' in sdk_license


def test_deployer_and_docs_contract():
    """Validate Bicep and docs expose the Teams SSO feature coherently."""
    main_bicep = _read(MAIN_BICEP)
    app_service_bicep = _read(APP_SERVICE_BICEP)
    how_to = _read(HOW_TO_DOC)
    feature_doc = _read(FEATURE_DOC)

    main_required = [
        'param enableTeamsSso bool = false',
        'param teamsFrameAncestors string = \'\'',
        'param customTeamsOrigins string = \'\'',
        'param teamsAppResource string = \'\'',
        'var acrCloudSuffix = az.environment().suffixes.acrLoginServer',
        'enableTeamsSso: enableTeamsSso',
        'teamsFrameAncestors: teamsFrameAncestors',
        'customTeamsOrigins: customTeamsOrigins',
        'teamsAppResource: teamsAppResource',
    ]
    missing_main = [snippet for snippet in main_required if snippet not in main_bicep]
    assert not missing_main, f"Missing main.bicep snippets: {missing_main}"

    module_required = [
        'param enableTeamsSso bool = false',
        "{ name: 'ENABLE_TEAMS_SSO', value: enableTeamsSso ? 'true' : 'false' }",
        "{ name: 'SESSION_COOKIE_SAMESITE', value: 'None' }",
        "{ name: 'SESSION_COOKIE_SECURE', value: 'true' }",
        "{ name: 'TEAMS_APP_RESOURCE', value: teamsAppResource }",
        'requireAuthentication: !enableTeamsSso',
        "unauthenticatedClientAction: enableTeamsSso ? 'AllowAnonymous' : 'RedirectToLoginPage'",
    ]
    missing_module = [snippet for snippet in module_required if snippet not in app_service_bicep]
    assert not missing_module, f"Missing appService.bicep snippets: {missing_module}"

    assert _read(DEPLOYER_VERSION).strip() == '1.0.16'
    assert 'Implemented in version: **0.242.072**' in feature_doc
    assert 'Teams SSO requires two layers' in how_to
    assert 'enableTeamsSso' in how_to
    assert 'TEAMS_APP_RESOURCE' in how_to


if __name__ == "__main__":
    tests = [
        test_config_security_and_cloud_defaults,
        test_app_origin_guard_supports_teams_exchange,
        test_auth_route_teams_token_exchange_contract,
        test_login_template_and_manifest_contract,
        test_deployer_and_docs_contract,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"{test.__name__} passed")
            results.append(True)
        except Exception as exc:
            print(f"{test.__name__} failed: {exc}")
            results.append(False)

    success = all(results)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)