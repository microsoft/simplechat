# test_deployer_key_vault_secret_permissions.py
#!/usr/bin/env python3
"""
Functional tests for deployer Key Vault secret-management permissions.
Version: 0.261.125
Implemented in: 0.261.125

Validate vault-scoped Secrets Officer grants, runtime identity wiring, additive
upgrades, compiled ARM, and Azure CLI reconciliation. PowerShell scenarios load
only the permission helper and identity setup fragments, with every Azure CLI
command intercepted by a fail-closed fake. No Azure access or deployment occurs.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
OFFICER_ROLE_ID = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"
SUBSCRIPTION_ID = "11111111-1111-1111-1111-111111111111"
VAULT_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/test-rg/"
    "providers/Microsoft.KeyVault/vaults/test-vault"
)
SYSTEM_PRINCIPAL = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_PRINCIPAL = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OTHER_PRINCIPAL = "cccccccc-cccc-cccc-cccc-cccccccccccc"
UAMI_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/test-rg/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-identity"
)
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def read_file(*parts):
    return REPO_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def resource_block(source, declaration):
    """Extract these deployment resources without depending on an HCL parser."""
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Unclosed resource: {declaration}")


def assignment(principal, role=OFFICER_ROLE_ID, scope=VAULT_ID, condition=None):
    return {
        "name": f"manual-{principal}",
        "principalId": principal,
        "scope": scope,
        "roleDefinitionId": (
            f"/subscriptions/{SUBSCRIPTION_ID}/providers/"
            f"Microsoft.Authorization/roleDefinitions/{role}"
        ),
        "condition": condition,
    }


def scenario(name, **changes):
    result = {
        "name": name,
        "mode": "permissions",
        "principals": [SYSTEM_PRINCIPAL, USER_PRINCIPAL],
        "rbac": True,
        "vaultId": VAULT_ID,
        "assignments": [],
        "policies": [],
        "failure": "",
        "identityExists": True,
        "repeat": False,
    }
    result.update(changes)
    return result


POWERSHELL_HARNESS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$source = Get-Content -LiteralPath $env:SIMPLECHAT_TEST_DEPLOYER -Raw
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$helpers = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Ensure-KeyVaultSecretPermissions'
}, $true))
if ($helpers.Count -ne 1) { throw 'Expected one Key Vault permission helper.' }
. ([scriptblock]::Create($helpers[0].Extent.Text))
$data = $env:SIMPLECHAT_TEST_CASES | ConvertFrom-Json

function Get-ArgumentValue($arguments, $name) {
    $index = [array]::IndexOf($arguments, $name)
    if ($index -lt 0) { throw "Missing argument $name" }
    return $arguments[$index + 1]
}

function Write-Host {
    $script:messages.Add(($args -join ' '))
}

function az {
    $arguments = @($args | ForEach-Object { $_ })
    $commandLength = if ($arguments[0] -in @('role', 'webapp')) { 3 } else { 2 }
    $command = $arguments[0..($commandLength - 1)] -join ' '
    $script:calls.Add([pscustomobject]@{command = $command; arguments = $arguments})
    $global:LASTEXITCODE = 0
    if ($script:case.failure -eq $command) {
        $global:LASTEXITCODE = 1
        return
    }
    switch ($command) {
        'keyvault show' {
            return (ConvertTo-Json -InputObject $script:vault -Depth 12 -Compress)
        }
        'role assignment list' {
            return (ConvertTo-Json -InputObject @($script:assignments) -Depth 12 -Compress)
        }
        'role assignment create' {
            $principal = Get-ArgumentValue $arguments '--assignee-object-id'
            $scope = Get-ArgumentValue $arguments '--scope'
            $role = Get-ArgumentValue $arguments '--role'
            $name = Get-ArgumentValue $arguments '--name'
            $script:assignments += [pscustomobject]@{
                name = $name
                principalId = $principal
                scope = $scope
                roleDefinitionId = "/subscriptions/$($data.subscriptionId)/providers/Microsoft.Authorization/roleDefinitions/$role"
                condition = $null
            }
            if ($script:case.failure -eq 'assignment-race') {
                $global:LASTEXITCODE = 1
            }
            return
        }
        'keyvault set-policy' {
            $principal = Get-ArgumentValue $arguments '--object-id'
            $index = [array]::IndexOf($arguments, '--secret-permissions') + 1
            $permissions = @()
            while ($index -lt $arguments.Count -and -not $arguments[$index].StartsWith('--')) {
                $permissions += $arguments[$index]
                $index++
            }
            $script:policyUpdates.Add([pscustomobject]@{principal = $principal; secrets = $permissions})
            return
        }
        'identity show' {
            if (-not $script:identityExists) {
                $global:LASTEXITCODE = 1
                return
            }
            if ($arguments -contains '--query') {
                return 'test-identity'
            }
            if ($script:case.failure -eq 'identity-details') {
                $global:LASTEXITCODE = 1
                return
            }
            return (ConvertTo-Json -InputObject @{
                id = $data.uamiId
                principalId = $data.userPrincipal
            } -Compress)
        }
        'identity create' {
            $script:identityExists = $true
            return
        }
        'webapp identity assign' { return }
        default { throw "Unmocked Azure command blocked: $command" }
    }
}

function Get-Fragment($startMarker, $endMarker) {
    $start = $source.IndexOf($startMarker, [StringComparison]::Ordinal)
    if ($start -lt 0) { throw "Missing fragment $startMarker" }
    $end = $source.IndexOf($endMarker, $start, [StringComparison]::Ordinal)
    if ($end -lt 0) { throw "Missing fragment end $endMarker" }
    return $source.Substring($start, $end - $start)
}

$results = foreach ($script:case in $data.cases) {
    $script:calls = [System.Collections.Generic.List[object]]::new()
    $script:messages = [System.Collections.Generic.List[string]]::new()
    $script:policyUpdates = [System.Collections.Generic.List[object]]::new()
    $script:assignments = @($script:case.assignments)
    $script:identityExists = $script:case.identityExists
    $script:vault = @{
        id = $script:case.vaultId
        rbacEnabled = $script:case.rbac
        accessPolicies = @($script:case.policies)
    }
    $errorText = ''
    try {
        if ($script:case.mode -eq 'identities') {
            $managedIdentityName = 'test-identity'
            $resourceGroupName = 'test-rg'
            $paramLocation = 'eastus'
            $appServiceName = 'test-app'
            $setup = Get-Fragment '# --- Create User-Assigned Managed Identity ---' '# --- Create App Service Plan ---'
            $attach = Get-Fragment '# --- Reconcile App Service managed identities ---' '# --- Entra App Registration ---'
            & ([scriptblock]::Create("$setup`n$attach"))
        } else {
            Ensure-KeyVaultSecretPermissions -VaultName 'test-vault' -ResourceGroupName 'test-rg' -PrincipalIds $script:case.principals
            if ($script:case.repeat) {
                Ensure-KeyVaultSecretPermissions -VaultName 'test-vault' -ResourceGroupName 'test-rg' -PrincipalIds $script:case.principals
            }
        }
    } catch {
        $errorText = $_.Exception.Message
    }
    [pscustomobject]@{
        name = $script:case.name
        error = $errorText
        calls = @($script:calls.ToArray())
        assignments = @($script:assignments)
        policyUpdates = @($script:policyUpdates.ToArray())
        messages = @($script:messages.ToArray())
    }
}
ConvertTo-Json -InputObject @($results) -Depth 16 -Compress
"""


class DeployerKeyVaultPermissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bicep = read_file("deployers", "bicep", "main.bicep")
        cls.arm = json.loads(read_file("deployers", "bicep", "main.json"))
        cls.cli = read_file("deployers", "azurecli", "deploy-simplechat.ps1")
        cls.terraform = read_file("deployers", "terraform", "main.tf")

    def test_bicep_roles_are_unconditional_vault_scoped_officer_grants(self):
        for filename in ("setPermissions.bicep", "setNativeWebAppPermissions.bicep"):
            with self.subTest(module=filename):
                source = read_file("deployers", "bicep", "modules", filename)
                block = resource_block(source, "resource kvSecretsOfficerRole ")
                self.assertIn("= {", block.splitlines()[0])
                self.assertNotIn("if (", block)
                self.assertIn("scope: kv", block)
                self.assertIn("principalId: webApp.identity.principalId", block)
                self.assertIn("principalType: 'ServicePrincipal'", block)
                self.assertIn(OFFICER_ROLE_ID, block)
                self.assertIn("name: guid(kv.id, webApp.id, 'kv-secrets-officer')", block)
                self.assertNotIn(USER_ROLE_ID, source)
                self.assertNotIn("'kv-secrets-user'", source)

    def test_permission_switch_and_compiled_arm_preserve_identity_and_scope(self):
        modules = (
            ("setPermissions", "webAppName", "[parameters('configureApplicationPermissions')]"),
            (
                "setNativeWebAppPermissions",
                "nativeWebAppName",
                "[and(parameters('configureApplicationPermissions'), parameters('deployNativePythonWebApp'))]",
            ),
        )
        for module_name, app_parameter, condition in modules:
            with self.subTest(module=module_name):
                module = self.arm["resources"][module_name]
                self.assertEqual(module["condition"], condition)
                self.assertIn("if (configureApplicationPermissions", self.bicep)
                resources = module["properties"]["template"]["resources"]
                if isinstance(resources, dict):
                    resources = resources.values()
                grants = [
                    resource for resource in resources
                    if resource["type"] == "Microsoft.Authorization/roleAssignments"
                    and OFFICER_ROLE_ID in resource["properties"]["roleDefinitionId"]
                ]
                self.assertEqual(len(grants), 1)
                grant = grants[0]
                self.assertNotIn("condition", grant)
                self.assertIn("Microsoft.KeyVault/vaults", grant["scope"])
                self.assertIn("parameters('keyVaultName')", grant["scope"])
                self.assertIn("'kv-secrets-officer'", grant["name"])
                self.assertIn("guid(", grant["name"])
                principal = grant["properties"]["principalId"]
                self.assertIn("Microsoft.Web/sites", principal)
                self.assertIn(f"parameters('{app_parameter}')", principal)
                self.assertTrue(principal.endswith(".identity.principalId]"))
                self.assertEqual(grant["properties"]["principalType"], "ServicePrincipal")

    def test_runtime_identity_defaults_and_cli_permission_wiring(self):
        for filename in ("appService.bicep", "appServiceNativePython.bicep"):
            source = read_file("deployers", "bicep", "modules", filename)
            self.assertRegex(source, r"identity:\s*\{\s*type: 'SystemAssigned'")
            self.assertNotIn("AZURE_CLIENT_ID", source)
        self.assertIn('type         = "SystemAssigned, UserAssigned"', self.terraform)
        self.assertNotIn('"AZURE_CLIENT_ID"', self.terraform)
        self.assertNotIn('"AZURE_CLIENT_ID=', self.cli)
        self.assertFalse('"Key Vault Secrets User"' in self.cli, "CLI runtime grants must use Secrets Officer.")
        invocation = re.search(
            r"(?m)^Ensure-KeyVaultSecretPermissions -VaultName \$keyVaultName "
            r"-ResourceGroupName \$resourceGroupName `\n"
            r"\s+-PrincipalIds @\(\$appService_SystemManagedIdentity_ObjectId, \$managedIdentity_PrincipalId\)",
            self.cli,
        )
        self.assertIsNotNone(invocation)
        self.assertGreater(invocation.start(), self.cli.index("# RBAC ASSIGNMENTS"))

    def test_terraform_adds_both_runtime_grants_without_deleting_old_grant(self):
        for name, principal in (
            ("kv_secrets_officer_managed_identity", "azurerm_user_assigned_identity.id.principal_id"),
            ("kv_secrets_officer_app_service", "azurerm_linux_web_app.app.identity[0].principal_id"),
        ):
            with self.subTest(resource=name):
                block = resource_block(self.terraform, f'resource "azurerm_role_assignment" "{name}"')
                self.assertIn("scope                = azurerm_key_vault.kv.id", block)
                self.assertIn('role_definition_name = "Key Vault Secrets Officer"', block)
                self.assertIn(f"principal_id         = {principal}", block)
                self.assertNotIn("count", block)
                self.assertNotRegex(block, r"(?m)^\s+name\s*=")
        removed = resource_block(self.terraform, "removed {")
        self.assertIn("from = azurerm_role_assignment.kv_secrets_user_managed_identity", removed)
        self.assertIn("destroy = false", removed)
        self.assertNotIn('resource "azurerm_role_assignment" "kv_secrets_user_managed_identity"', self.terraform)

    def test_guidance_covers_runtime_selection_and_non_destructive_adoption(self):
        for parts in (("bicep", "README.md"), ("azurecli", "README.md"), ("terraform", "ReadMe.md")):
            with self.subTest(deployer=parts[0]):
                source = read_file("deployers", *parts)
                for expected in (
                    "Key Vault Secrets Officer", "Key Vault Secrets User", OFFICER_ROLE_ID,
                    "0.261.125", "system-assigned", "vault scope",
                ):
                    self.assertTrue(expected in source, f"Missing {expected} in {parts[0]} guidance.")
        bicep_readme = read_file("deployers", "bicep", "README.md")
        self.assertIn("RoleAssignmentExists", bicep_readme)
        self.assertIn("kv-secrets-officer", bicep_readme)
        self.assertIn("configureApplicationPermissions=false", bicep_readme)
        terraform_readme = read_file("deployers", "terraform", "ReadMe.md")
        self.assertIn("terraform import", terraform_readme)
        self.assertIn("destroy = false", terraform_readme)

    def test_deployer_version_is_at_least_the_permission_fix(self):
        version = read_file("deployers", "version.txt").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (1, 0, 32))

    @unittest.skipUnless(POWERSHELL, "PowerShell is required for offline CLI behavior tests.")
    def test_cli_reconciliation_behavior_without_azure_access(self):
        cases = [
            scenario("fresh"),
            scenario("rerun", repeat=True),
            scenario("manual", assignments=[
                assignment(SYSTEM_PRINCIPAL, scope=VAULT_ID.upper()),
                assignment(USER_PRINCIPAL),
            ]),
            scenario("old-user", assignments=[
                assignment(SYSTEM_PRINCIPAL, USER_ROLE_ID),
                assignment(USER_PRINCIPAL, USER_ROLE_ID),
            ]),
            scenario("wrong-scope", assignments=[
                assignment(SYSTEM_PRINCIPAL, scope=VAULT_ID.split("/providers/")[0]),
                assignment(USER_PRINCIPAL, scope=f"{VAULT_ID}/secrets/one-secret"),
            ]),
            scenario("wrong-principal", assignments=[assignment(OTHER_PRINCIPAL)]),
            scenario("conditional", assignments=[
                assignment(SYSTEM_PRINCIPAL, condition="restricted-secret-condition")
            ]),
            scenario("race", failure="assignment-race"),
            scenario("deduplicate", principals=[SYSTEM_PRINCIPAL, SYSTEM_PRINCIPAL]),
            scenario("legacy", rbac=False),
            scenario("legacy-null", rbac=None),
            scenario("legacy-merge", rbac=False, policies=[
                {"objectId": SYSTEM_PRINCIPAL, "permissions": {"secrets": ["get", "list", "backup", "recover"], "keys": ["get"]}},
                {"objectId": OTHER_PRINCIPAL, "permissions": {"secrets": ["get"]}},
            ]),
            scenario("legacy-complete", rbac=False, policies=[
                {"objectId": principal, "permissions": {"secrets": ["get", "list", "set", "delete", "purge"]}}
                for principal in (SYSTEM_PRINCIPAL, USER_PRINCIPAL)
            ]),
            scenario("vault-failure", failure="keyvault show"),
            scenario("list-failure", failure="role assignment list"),
            scenario("create-failure", failure="role assignment create"),
            scenario("policy-failure", rbac=False, failure="keyvault set-policy"),
            scenario("invalid-scope", vaultId=VAULT_ID.split("/providers/")[0]),
            scenario("empty-principal", principals=[""]),
            scenario("new-identity", mode="identities", identityExists=False),
            scenario("existing-identity", mode="identities"),
            scenario("identity-create-failure", mode="identities", identityExists=False, failure="identity create"),
            scenario("identity-read-failure", mode="identities", failure="identity-details"),
            scenario("identity-attach-failure", mode="identities", failure="webapp identity assign"),
        ]
        environment = os.environ.copy()
        environment["SIMPLECHAT_TEST_DEPLOYER"] = str(
            REPO_ROOT.joinpath("deployers", "azurecli", "deploy-simplechat.ps1")
        )
        environment["SIMPLECHAT_TEST_CASES"] = json.dumps({
            "subscriptionId": SUBSCRIPTION_ID,
            "uamiId": UAMI_ID,
            "userPrincipal": USER_PRINCIPAL,
            "cases": cases,
        })
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "& ([scriptblock]::Create([Console]::In.ReadToEnd()))"],
            input=POWERSHELL_HARNESS,
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        outcomes = {item["name"]: item for item in json.loads(result.stdout)}
        self.assertEqual(set(outcomes), {item["name"] for item in cases})

        def calls(outcome, command):
            return [call["arguments"] for call in outcome["calls"] if call["command"] == command]

        def argument(arguments, name):
            return arguments[arguments.index(name) + 1]

        for case in cases:
            name = case["name"]
            outcome = outcomes[name]
            with self.subTest(scenario=name):
                must_fail = name.endswith("-failure") or name in {
                    "invalid-scope", "empty-principal", "conditional",
                }
                self.assertEqual(bool(outcome["error"]), must_fail, outcome["error"])
                if must_fail:
                    self.assertFalse(any("confirmed" in message for message in outcome["messages"]))
                for arguments in calls(outcome, "role assignment create"):
                    self.assertEqual(argument(arguments, "--scope"), VAULT_ID)
                    self.assertEqual(argument(arguments, "--role"), OFFICER_ROLE_ID)
                    self.assertIn(argument(arguments, "--assignee-object-id"), (SYSTEM_PRINCIPAL, USER_PRINCIPAL))
                    self.assertEqual(argument(arguments, "--assignee-principal-type"), "ServicePrincipal")
                    assignment_name = uuid.UUID(argument(arguments, "--name"))
                    self.assertIsInstance(assignment_name, uuid.UUID)
                self.assertFalse(any("delete" in call["command"] for call in outcome["calls"]))

        for name in ("fresh", "rerun", "old-user", "wrong-scope", "wrong-principal", "race"):
            self.assertEqual(len(calls(outcomes[name], "role assignment create")), 2, name)
        self.assertEqual(len(calls(outcomes["deduplicate"], "role assignment create")), 1)
        self.assertEqual(calls(outcomes["manual"], "role assignment create"), [])
        self.assertEqual(len(outcomes["old-user"]["assignments"]), 4)
        fresh_names = [argument(args, "--name") for args in calls(outcomes["fresh"], "role assignment create")]
        upgrade_names = [argument(args, "--name") for args in calls(outcomes["old-user"], "role assignment create")]
        self.assertEqual(fresh_names, upgrade_names)

        for name in ("legacy", "legacy-null", "legacy-merge"):
            self.assertEqual(calls(outcomes[name], "role assignment create"), [])
            updates = outcomes[name]["policyUpdates"]
            self.assertEqual({update["principal"] for update in updates}, {SYSTEM_PRINCIPAL, USER_PRINCIPAL})
            for update in updates:
                self.assertTrue({"get", "list", "set", "delete"}.issubset(update["secrets"]))
        merged = outcomes["legacy-merge"]["policyUpdates"][0]["secrets"]
        self.assertTrue({"backup", "recover"}.issubset(merged))
        self.assertEqual(calls(outcomes["legacy-complete"], "keyvault set-policy"), [])
        self.assertEqual(len(calls(outcomes["new-identity"], "identity create")), 1)
        self.assertEqual(calls(outcomes["existing-identity"], "identity create"), [])
        for name in ("new-identity", "existing-identity"):
            attachments = calls(outcomes[name], "webapp identity assign")
            self.assertEqual(len(attachments), 1)
            self.assertIn("[system]", attachments[0])
            self.assertIn(UAMI_ID, attachments[0])


if __name__ == "__main__":
    unittest.main()
