# Entra Application Graph MFA Auth Fix

Fixed/Implemented in version: **0.241.010**

Related config.py update: `VERSION = "0.241.010"`

## Issue Description

`Initialize-EntraApplication.ps1` could fail when Azure CLI was signed in for normal Azure Resource Manager operations but the cached account still needed a Microsoft Graph MFA or conditional-access challenge before `az ad` commands could run.

## Root Cause Analysis

The script only verified `az account show`, which proves the Azure CLI account is present but does not prove the account can acquire a Microsoft Graph token. When `az ad app list` hit `AADSTS50076` or another interaction-required Graph challenge, the failed output was piped into `ConvertFrom-Json`; the script then continued as if no app registration existed and failed later with a generic create error.

## Technical Details

### Files Modified

- `deployers/Initialize-EntraApplication.ps1`
- `application/single_app/config.py`
- `functional_tests/test_entra_application_graph_mfa_auth.py`

### Code Changes Summary

- Added a Microsoft Graph token preflight with `az account get-access-token` after tenant and cloud detection.
- Added interaction-required detection for MFA, invalid grant, and claims-challenge Azure CLI responses.
- Added interactive recovery that runs `az login --tenant ... --scope ...` only when Graph access requires it, preserving existing non-MFA cached-token runs.
- Wrapped app registration and service principal JSON reads in explicit Azure CLI exit-code checks so command failures are not treated as empty JSON.

## Validation

- Functional test: `functional_tests/test_entra_application_graph_mfa_auth.py`
- PowerShell parser validation for `deployers/Initialize-EntraApplication.ps1`
- Expected outcome: MFA-gated tenants get a Graph-scoped interactive login prompt before app registration work begins, while non-MFA tenants continue through the existing authenticated Azure CLI workflow without an extra login.