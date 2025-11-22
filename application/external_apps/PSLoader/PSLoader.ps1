
#requires -Version 7.2
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Microsoft Corporation. All rights reserved.

<#
.SYNOPSIS
Upload utility to bulk upload documents to the SimpleChat system.

.DESCRIPTION
This module provides functions to upload documents to the SimpleChat system in bulk.

.LICENSE
This module is licensed under the MIT License.
See the LICENSE file in the repository root or:
https://spdx.org/licenses/MIT.html

.NOTES
Author: John Scott
CompanyName: Microsoft Corporation
Module Version: 0.1.0
Created: 2025-11-05
Project: https://github.com/microsoft/simplechat

.LINK
ProjectUri: https://github.com/microsoft/simplechat
#>

param(
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The directory containing files to upload.")]
  $uploadDirectory,
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The user ID (GUID found in CosmosDB users) to associate the uploaded documents with.")]
  $userId,
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The workspace ID (GUID found in CosmosDB tables) with which to associate the uploaded documents.  Could be groups or public workspaces. ")]
  $activeWorkspaceId,
  [string]
  [parameter(Mandatory = $false)]
  [DESCRIPTION("The classification of the document being uploaded. Default is 'unclassified.'")]
  $classification = "unclassified",
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The Entra ID tenant (GUID) for authentication.")]
  $tenantId,
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The Entra ID client/application ID (GUID) for authentication.")]
  $clientId,
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The Entra ID client/application secret for authentication.")]
  $clientSecret,
  [string]
  [Parameter(Mandatory = $true)]
  [DESCRIPTION("The Application ID URI for authentication, e.g. api://<GUID of SimpleChat app registration>/.default This is the endpoint of the Simplechat app registration, NOT the PSLoader app registration")]
  $scope,
  [switch]
  [DESCRIPTION("Use this switch to indicate if connecting to Azure US Government.")]
  $AzureUSGovernment
)

Set-StrictMode -Version Latest
$script:ModuleRoot = Split-Path -Parent $PSCommandPath

if ($AzureUSGovernment) {
  $authAuthority = "https://login.microsoftonline.us/$tenantId"
}
else {
  $authAuthority = "https://login.microsoftonline.com/$tenantId"
}

$tokenUrl = "$authAuthority/oauth2/v2.0/token"

$body = @{
  client_id     = $clientId
  scope         = $scope
  client_secret = $clientSecret
  grant_type    = "client_credentials"
}

$response = Invoke-RestMethod -Method Post -Uri $tokenUrl -ContentType "application/x-www-form-urlencoded" -Body $body
$accessToken = $response.access_token

$headers = @{
  Authorization = "Bearer $accessToken"
}

write-host "Retrieved access token. Beginning file upload process..."

$files = @(Get-ChildItem -Path $uploadDirectory -File -Recurse -Include *.pdf, *.docx, *.pptx, *.txt, *.md, *.json, *.html, `
    *.xsl, *.xslx, *.csv, *.jpg, *.jpeg, *.png, *.bmp, *.tiff, *.tif, *.heif, `
    *.wav, *.m4a, *.mp4, *.mov, *.avi, *.mkv, *.flv, *.mxf, *.gxf, *.ts, *.ps, *.3gp, *.3gpp, *.mpg, `
    *.wmv, *.asf, *.m4v, *.isma, *.ismv, *.dvr-ms
)

write-host "Found $($files.Count) files to upload. Beginning upload..."
$fileUploadCount = 0
$fileFailedCount = 0
foreach ($file in $files) {
  write-host "Uploading file: $($file.FullName)..."
  $form = @{
    file                = Get-Item $file.FullName
    user_Id             = $userId
    active_Workspace_Id = $activeWorkspaceId
    classification      = $classification
  }

  try {
    $uploadResponse = Invoke-RestMethod -Method Post -Uri "https://your-simplechat-api-endpoint/api/external/public/documents/upload" -Headers $headers -Form $form
    write-host "Successfully uploaded file: $($file.FullName)" -ForegroundColor Green
    $uploadResponse | ConvertTo-Json -Depth 5
    $fileUploadCount++
  }
  catch {
    write-host "Failed to upload file: $($file.FullName). Error: $_" -ForegroundColor Red
    $fileFailedCount++
  }
} 
write-host "File upload process completed. Successfully uploaded $fileUploadCount files. Failed to upload $fileFailedCount files."
