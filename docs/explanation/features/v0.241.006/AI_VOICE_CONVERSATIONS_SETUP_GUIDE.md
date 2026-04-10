# AI Voice Conversations Setup Guide

Version implemented: **0.241.009**
Enhanced in version: **0.241.010**

## Overview and Purpose

This feature adds a dedicated Setup Guide modal to the Admin Settings AI Voice Conversations card. The guide gives admins an in-app reference for configuring Azure AI Speech for audio uploads, voice input, and voice responses without leaving the settings page.

Dependencies:

- Azure AI Speech
- Admin Settings Search & Extract tab
- Shared Speech configuration fields in the AI Voice Conversations card

## Technical Specifications

### Architecture Overview

The feature follows the same UI pattern already used by the Azure AI Video Indexer setup guide:

- A Setup Guide button is rendered in the AI Voice Conversations card header.
- A dedicated modal partial contains setup guidance, required field descriptions, and a snapshot of the current form state.
- Client-side modal update logic reads the current Speech settings just before the modal opens.

### Configuration Options

The guide explains the settings used by the shared Speech configuration section:

- Speech Service Endpoint
- Speech Service Location
- Speech Service Locale
- Authentication Type
- Speech Service Key
- Speech Resource ID
- Speech Subscription ID
- Speech Resource Group
- Speech Resource Name

### File Structure

- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/_speech_service_info.html`
- `ui_tests/test_admin_multimedia_guidance.py`
- `functional_tests/test_multimedia_support_reorganization.py`

## Usage Instructions

### How to Open the Guide

1. Go to Admin Settings.
2. Open the Search & Extract tab.
3. Find the AI Voice Conversations card.
4. Click **Setup Guide**.

### What the Guide Covers

1. The shared-resource model for audio uploads, voice input, and voice responses.
2. The difference between API key and managed-identity authentication.
3. A step-by-step custom-domain walkthrough for managed identity: **Networking** → **Firewalls and virtual networks** → **Generate Custom Domain Name** → verify on **Keys and Endpoint**.
4. Speech-specific RBAC role guidance.
5. When the Speech Resource ID is required and how the built-in helper fields can construct it.

### Custom-Domain Walkthrough

The guide now walks admins through the exact managed-identity endpoint setup flow in Azure:

1. Open the Speech resource in Azure portal.
2. Go to **Resource Management** → **Networking**.
3. Open **Firewalls and virtual networks**.
4. Choose **Generate Custom Domain Name**.
5. Save a globally unique custom name.
6. Verify the resulting endpoint in **Keys and Endpoint** before copying it into Simple Chat.

## Testing and Validation

### Test Coverage

- Functional test coverage verifies that the AI Voice setup guide modal is included in the admin settings template and that the Setup Guide trigger is present.
- UI test coverage verifies that the modal opens from the Admin Settings page and reflects the current shared Speech configuration values.

### Known Limitations

- The guide is informational. It does not provision Azure resources or assign roles automatically.
- The UI test requires an authenticated admin Playwright session to run end to end.