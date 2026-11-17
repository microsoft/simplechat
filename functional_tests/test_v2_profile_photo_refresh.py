#!/usr/bin/env python3
# test_v2_profile_photo_refresh.py
"""
Functional test for "Refresh photo" on the V2 User Settings page.
Version: 0.261.445
Implemented in: 0.261.445

The profile photo is read from Microsoft Graph once, when a user is first seen, and cached on
their settings document. Classic has a "Refresh Profile Image" button that asks the server to
read it again; V2 showed the photo but had no way to change it. The Settings header now has a
"Refresh photo" control for the same route.

These checks pin what the control relies on:

- the route it calls is the one classic calls, with the same gates and the same three answer
  fields, and the V2 endpoint constant is that route;
- the control is in the Settings header with a busy state, and its outcome is said in a live
  region that is always on the page and an alert for a failure;
- the photograph is never logged, shown as text or copied into an error, and never posted back
  through the settings route;
- the answer is read, the failure words chosen, the request shaped and the store updated as
  intended (executed under node, including that a later failed save of another preference does
  not put the old photo back).
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
PROFILE_ROUTE = APP_ROOT / "route_frontend_profile.py"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_profile_photo_refresh_logic.ts"

PHOTO_FILES = (
    V2_SRC / "lib" / "profileImage.ts",
    V2_SRC / "lib" / "useProfilePhotoRefresh.ts",
    V2_SRC / "components" / "settings" / "ProfilePhotoStatus.tsx",
)


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _nested_function(tree, outer, name):
    outer_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == outer)
    return next(node for node in outer_node.body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


def test_the_control_calls_the_route_classic_calls_with_the_answer_it_reads():
    """The route, its gates and the three fields V2 reads are classic's."""
    tree = ast.parse(_read(PROFILE_ROUTE))
    route = _nested_function(tree, "register_route_frontend_profile", "refresh_profile_image")
    assert [ast.unparse(decorator) for decorator in route.decorator_list] == [
        "bp.route('/api/profile/image/refresh', methods=['POST'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]

    answers = [
        node for node in ast.walk(route)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "jsonify"
        and node.args and isinstance(node.args[0], ast.Dict)
    ]
    successes = [call for call in answers if any(
        isinstance(key, ast.Constant) and key.value == "success" for key in call.args[0].keys)]
    assert len(successes) == 2, "A new photo and no photo are the two successful answers"
    for call in successes:
        fields = {key.value for key in call.args[0].keys if isinstance(key, ast.Constant)}
        assert fields == {"success", "message", "profileImage"}
    values = {ast.unparse(call.args[0].values[-1]) for call in successes}
    assert values == {"profile_image_data", "None"}, "No photo is `profileImage: null`, which V2 reads as an answer"

    profile_image = _read(V2_SRC / "lib" / "profileImage.ts")
    endpoint = re.search(r"PROFILE_IMAGE_REFRESH_ENDPOINT = '([^']+)'", profile_image).group(1)
    assert endpoint == "/api/profile/image/refresh"
    assert f"bp.route('{endpoint}', methods=['POST'])" in _read(PROFILE_ROUTE)
    assert "api.post<unknown>(PROFILE_IMAGE_REFRESH_ENDPOINT, {}, signal)" in profile_image
    assert "fetch(" not in profile_image, "The request goes through the API client"
    assert "from './apiClient'" in profile_image


def test_the_settings_header_has_the_control_and_says_how_it_went():
    page = _read(V2_SRC / "pages" / "SettingsPage.tsx")
    assert "const photo = useProfilePhotoRefresh();" in page
    assert re.search(r"label: 'Refresh photo',", page), "The control is named for what it does"
    assert "onClick: photo.refresh," in page
    assert "loading: photo.busy," in page, "The header action turns a running refresh into a busy, disabled control"
    assert "<ProfilePhotoStatus message={photo.message} />" in page
    # What the page already relied on stays.
    for existing in ('title="User Settings"', "<UserAvatar size={36} />", "searchParams.get('section')"):
        assert existing in page

    status = _read(V2_SRC / "components" / "settings" / "ProfilePhotoStatus.tsx")
    assert 'role="status"' in status and 'aria-live="polite"' in status
    assert 'role="alert"' in status
    assert "'sr-only'" in status, "The live region stays on the page, empty, between outcomes"
    assert 'aria-hidden="true"' in status, "The outcome icons are decoration"

    header = _read(V2_SRC / "components" / "layout" / "HeaderActions.tsx")
    assert "aria-busy={action.loading || undefined}" in header and "disabled={action.disabled || action.loading}" in header


def test_the_photograph_is_never_logged_shown_or_posted_back():
    for path in PHOTO_FILES:
        source = _read(path)
        for forbidden in ("console.", "dangerouslySetInnerHTML", "innerHTML", "alert(", "localStorage", "sessionStorage"):
            assert forbidden not in source.replace(" ", ""), f"{path.name} uses {forbidden}"
        assert "error.message" not in source and "String(error)" not in source, (
            f"{path.name} must not put what the server said into the interface"
        )

    hook = _read(V2_SRC / "lib" / "useProfilePhotoRefresh.ts")
    assert "describeProfileImageFailure(error)" in hook
    assert "setProfileImage(result.profileImage)" in hook and "setProfileImage(null)" in hook

    store = _read(V2_SRC / "stores" / "userSettingsStore.ts")
    body = re.search(r"setProfileImage: \(image\) => \{(.*?)\n        \},", store, re.DOTALL).group(1)
    assert "set((state)" in body
    for write in ("scheduleWrite", "queueWrite", "pending", "rollback"):
        assert write not in body, "A photo that goes into the store is not scheduled for a write"

    for path in V2_SRC.rglob("*.ts*"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"update\(\s*\{\s*profileImage", source), f"{path.name} writes the photo back"


def test_a_photo_that_failed_to_decode_does_not_hide_the_one_fetched_next():
    avatar = _read(V2_SRC / "components" / "layout" / "UserAvatar.tsx")
    assert "const [failedSrc, setFailedSrc] = useState('');" in avatar
    assert "const showImage = Boolean(src) && failedSrc !== src;" in avatar
    assert "onError={() => setFailedSrc(src)}" in avatar
    assert "settings.profileImage" in avatar, "The avatar still reads the photo from the user settings store"


def test_the_photo_logic_passes_under_node():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return
    assert LOGIC_CHECK_TS.exists(), "The TypeScript profile photo checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-profile-photo-check.mjs"
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK_TS), "--bundle", "--platform=node", "--format=esm",
                "--packages=external",
                # apiClient reads import.meta.env, which only Vite provides.
                "--define:import.meta.env={}", f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)], cwd=str(V2_DIR), capture_output=True, text=True,
            env={**os.environ}, shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript profile photo checks failed")
    passed = result.stdout.count("  ok  ")
    assert passed >= 14, f"Only {passed} profile photo checks ran; the runner likely broke."
    print(f"  ok  {passed} TypeScript profile photo checks passed")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
