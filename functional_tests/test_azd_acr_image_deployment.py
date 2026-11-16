# test_azd_acr_image_deployment.py
"""
Functional regression for deploying the image built by the azd ACR hook.
Version: 0.261.394
Implemented in: 0.261.394

Validates the parsed manifest selects container image passthrough instead of
Python ZIP deployment or a duplicate local Docker build.
"""

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def manifest():
    return yaml.safe_load(
        (REPO_ROOT / "deployers" / "azure.yaml").read_text(encoding="utf-8")
    )


def test_web_deploys_the_acr_hook_image(manifest):
    web = manifest["services"]["web"]

    assert web["host"] == "appservice"
    assert web["language"] == "docker", "Python selects ZIP deployment, not the ACR image"
    assert web["image"] == "${var_containerRegistry}/${var_imageName}:latest"
    assert web["docker"] == {"imagePassthrough": True}, (
        "Reuse the hook's remote image without requiring a second Docker build"
    )


@pytest.mark.parametrize(
    ("platform", "latest_tag", "root_context"),
    [
        ("posix", "--image ${var_imageName}:latest", "cd .."),
        ("windows", '--image "$($env:var_imageName):latest"', "Set-Location .."),
    ],
)
def test_acr_hook_builds_the_deployed_tag(manifest, platform, latest_tag, root_context):
    hook = manifest["hooks"]["predeploy"][platform]["run"]

    assert "az acr build" in hook
    assert "--file application/single_app/Dockerfile" in hook
    assert latest_tag in hook
    assert root_context in hook
