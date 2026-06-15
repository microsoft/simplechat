#!/usr/bin/env python3
# test_deployer_capacity_defaults.py
"""
Functional test for deployer capacity defaults.
Version: 0.241.206
Implemented in: 0.241.206

This test ensures deployer defaults use Azure AI Search Standard S1 with
standard Semantic Ranker and Cosmos DB provisioned container autoscale throughput,
while keeping Free Search and serverless Cosmos DB as explicit MVP opt-ins.
"""

from pathlib import Path
import json
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_workspace_file(relative_path: str) -> str:
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content: str, expected: str, description: str) -> None:
    """Assert that expected text exists in content with a useful message."""
    assert expected in content, f"Expected {description}: {expected}"


def assert_not_contains(content: str, unexpected: str, description: str) -> None:
    """Assert that unexpected text does not exist in content with a useful message."""
    assert unexpected not in content, f"Did not expect {description}: {unexpected}"


def test_deployer_capacity_defaults() -> bool:
    """Validate deployer defaults for Search and Cosmos capacity."""
    print("Testing deployer capacity defaults")
    print("=" * 70)

    config_content = read_workspace_file("application/single_app/config.py")
    deployer_version = read_workspace_file("deployers/version.txt").strip()
    bicep_main = read_workspace_file("deployers/bicep/main.bicep")
    bicep_cosmos = read_workspace_file("deployers/bicep/modules/cosmosDb.bicep")
    bicep_search = read_workspace_file("deployers/bicep/modules/search.bicep")
    azurecli_deployer = read_workspace_file("deployers/azurecli/deploy-simplechat.ps1")
    terraform_main = read_workspace_file("deployers/terraform/main.tf")
    one_click_template_content = read_workspace_file("deployers/bicep/main.json")
    one_click_template = json.loads(one_click_template_content)
    feature_doc = read_workspace_file(
        "docs/explanation/features/v0.241.085/DEPLOYER_CAPACITY_DEFAULTS.md"
    )

    assert 'VERSION = "0.241.206"' in config_content, (
        "Expected config.py version 0.241.206 after the Cosmos container throughput deployer fix."
    )
    assert deployer_version == "1.0.14", "Expected deployers/version.txt to be bumped to 1.0.14."
    assert re.fullmatch(r"\d+\.\d+\.\d+", deployer_version), (
        "Expected deployers/version.txt to use a plain semantic version string."
    )

    assert_contains(bicep_main, "param cosmosCapacityMode string = 'provisioned'", "Bicep Cosmos provisioned default")
    assert_contains(bicep_main, "param searchSkuName string = 'standard'", "Bicep Search S1 default")
    assert_contains(bicep_main, "param searchSemanticSearchSku string = 'standard'", "Bicep Semantic Ranker default")
    assert_contains(bicep_main, "param cosmosDatabaseAutoscaleMaxThroughput int = 1000", "Bicep Cosmos container autoscale default")
    assert_contains(bicep_cosmos, "param containerAutoscaleMaxThroughput int = 1000", "Bicep Cosmos container autoscale module default")
    assert_contains(bicep_cosmos, "resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = [for container in cosmosContainers", "Bicep Cosmos container loop")
    assert_contains(bicep_cosmos, "maxThroughput: containerAutoscaleMaxThroughput", "Bicep Cosmos autoscale container throughput")
    assert_not_contains(bicep_cosmos, "maxThroughput: databaseAutoscaleMaxThroughput", "Bicep shared database throughput")
    assert_contains(bicep_cosmos, "capacityMode == 'serverless' ?", "Bicep Cosmos serverless opt-in")
    assert_contains(bicep_search, "name: skuName", "Bicep Search SKU parameter use")
    assert_contains(bicep_search, "semanticSearch: semanticSearchSku", "Bicep Semantic Ranker parameter use")

    assert_contains(azurecli_deployer, '$paramCosmosDbCapacityMode = "Provisioned"', "Azure CLI Cosmos provisioned default")
    assert_contains(azurecli_deployer, '$paramCosmosDbAutoscaleMaxThroughput = 1000', "Azure CLI Cosmos container autoscale default")
    assert_contains(azurecli_deployer, '$paramSearchSku = "standard"', "Azure CLI Search S1 default")
    assert_contains(azurecli_deployer, '$paramSearchSemanticSearchSku = "standard"', "Azure CLI Semantic Ranker default")
    assert_contains(azurecli_deployer, "--max-throughput', $paramCosmosDbAutoscaleMaxThroughput", "Azure CLI Cosmos autoscale container create")
    assert_contains(azurecli_deployer, "CosmosDb_CreateContainer $paramCosmosDbDatabaseName $containerDefinition", "Azure CLI Cosmos container provisioning loop")
    assert_contains(azurecli_deployer, "--semantic-search $paramSearchSemanticSearchSku", "Azure CLI semantic search create option")

    assert_contains(terraform_main, 'default     = "provisioned"', "Terraform Cosmos provisioned default")
    assert_contains(terraform_main, 'default     = "standard"', "Terraform Search/Semantic default")
    assert_contains(terraform_main, 'default     = 1000', "Terraform Cosmos container autoscale default")
    assert_contains(terraform_main, 'resource "azurerm_cosmosdb_sql_database" "simplechat"', "Terraform Cosmos database")
    assert_contains(terraform_main, 'resource "azurerm_cosmosdb_sql_container" "simplechat"', "Terraform Cosmos container resources")
    assert_contains(terraform_main, 'partition_key_paths = [each.value.partition_key_path]', "Terraform Cosmos container partition keys")
    assert_contains(terraform_main, 'sku                           = lower(var.param_search_sku)', "Terraform Search SKU variable")
    assert_contains(terraform_main, 'semantic_search_sku           = lower(var.param_search_semantic_search_sku)', "Terraform semantic SKU variable")

    assert one_click_template["parameters"]["cosmosCapacityMode"]["defaultValue"] == "provisioned"
    assert one_click_template["parameters"]["searchSkuName"]["defaultValue"] == "standard"
    assert one_click_template["parameters"]["searchSemanticSearchSku"]["defaultValue"] == "standard"
    assert one_click_template["parameters"]["cosmosDatabaseAutoscaleMaxThroughput"]["defaultValue"] == 1000
    assert_contains(one_click_template_content, '"containerAutoscaleMaxThroughput"', "one-click ARM Cosmos container throughput parameter")
    assert_contains(one_click_template_content, '"Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers"', "one-click ARM Cosmos container resources")
    assert_contains(one_click_template_content, "parameters('containerAutoscaleMaxThroughput')", "one-click ARM Cosmos container autoscale expression")
    assert_not_contains(one_click_template_content, '"databaseAutoscaleMaxThroughput"', "one-click ARM shared database throughput parameter")

    assert_contains(feature_doc, "Azure AI Search: Standard S1", "feature doc Search default")
    assert_contains(feature_doc, "Azure Cosmos DB: provisioned throughput", "feature doc Cosmos default")
    assert_contains(feature_doc, "dedicated autoscale throughput on each SimpleChat container", "feature doc container throughput default")
    assert_contains(feature_doc, "short-lived MVP", "feature doc MVP alternative guidance")

    print("Deployer defaults are aligned across Bicep, one-click ARM, Azure CLI, and Terraform.")
    print("Provisioned Cosmos deployments use dedicated container throughput to avoid shared database container limits.")
    return True


if __name__ == "__main__":
    try:
        success = test_deployer_capacity_defaults()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)
