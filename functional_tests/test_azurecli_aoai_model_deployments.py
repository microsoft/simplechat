#!/usr/bin/env python3
# test_azurecli_aoai_model_deployments.py
"""
Functional test for Azure CLI Azure OpenAI model deployment support.
Version: 0.237.048
Implemented in: 0.237.048

This test ensures that the Azure CLI deployer and its documentation include
the Azure OpenAI model deployment configuration, creation logic, and retry path.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYER_SCRIPT = REPO_ROOT / "deployers" / "azurecli" / "deploy-simplechat.ps1"
DEPLOYER_README = REPO_ROOT / "deployers" / "azurecli" / "README.md"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azurecli_aoai_model_deployment_support() -> bool:
    print("🧪 Testing Azure CLI Azure OpenAI model deployment support")
    print("=" * 70)

    script_content = DEPLOYER_SCRIPT.read_text(encoding="utf-8")
    readme_content = DEPLOYER_README.read_text(encoding="utf-8")

    require_contains(
        script_content,
        "$param_DeployAzureOpenAiModels = $true",
        "Azure OpenAI model deployment toggle",
    )
    require_contains(
        script_content,
        "$param_AzureOpenAiDeploymentType = \"\"",
        "Azure OpenAI deployment type configuration",
    )
    require_contains(
        script_content,
        "function Ensure-OpenAiModelDeployment",
        "Azure OpenAI model deployment helper",
    )
    require_contains(
        script_content,
        "az cognitiveservices account deployment create",
        "Azure CLI model deployment create command",
    )
    require_contains(
        script_content,
        "Try a different Azure OpenAI deployment type",
        "deployment type retry prompt",
    )

    require_contains(
        readme_content,
        "The Azure CLI deployer can now create the default GPT and embedding model deployments",
        "README Azure OpenAI deployment description",
    )
    require_contains(
        readme_content,
        "param_AzureOpenAiDeploymentType",
        "README configuration guidance",
    )

    print("✅ Azure CLI deployer contains Azure OpenAI model deployment configuration")
    print("✅ Azure CLI deployer contains idempotent model deployment creation logic")
    print("✅ Azure CLI README documents deployment type selection and retry guidance")
    return True


if __name__ == "__main__":
    try:
        success = test_azurecli_aoai_model_deployment_support()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)