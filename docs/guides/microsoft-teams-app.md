---
layout: page
title: "Microsoft Teams App Configuration"
permalink: /guides/microsoft-teams-app/
section: "Guides"
redirect_from:
  - /how-to/teams_app/
  - /how-to/teams_app.html
---

# Microsoft Teams App Configuration

This guide explains how to run SimpleChat as a Microsoft Teams personal tab with Teams Single Sign-On (SSO).

## Enablement Model

Teams SSO requires two layers:

1. A Teams app package installed in Teams. The package contains the Teams manifest, icons, tab URL, valid domain, and `webApplicationInfo` values.
2. SimpleChat runtime configuration. The app must enable `ENABLE_TEAMS_SSO`, allow Teams framing in Content Security Policy, use cross-site secure session cookies, and allow the Teams login page to reach the Flask authentication flow.

The Bicep deployer exposes `enableTeamsSso` for the runtime layer. It does not install the Teams app package into Teams; a Teams administrator or developer still uploads the generated app package.

## Prerequisites

- An Entra app registration for SimpleChat.
- The SimpleChat application URL, such as `https://simplechat.contoso.com`.
- Permission to update the Entra app registration.
- Permission to upload or publish a custom Teams app.

## Entra App Registration

### Expose An API

1. Open the SimpleChat app registration in the Azure portal.
2. Select **Expose an API**.
3. Set the Application ID URI to a stable URI for the SimpleChat web app.

Example:

```text
api://simplechat.contoso.com/00000000-0000-0000-0000-000000000000
```

4. Add a delegated scope named `access_as_user`.
5. Allow admins and users to consent, or use your tenant policy standard.

### Preauthorize Teams Clients

Under **Authorized client applications**, add the Teams clients that should acquire the `access_as_user` token.

Common Teams client IDs:

```text
5e3ce6c0-2b1f-4285-8d4b-75ee78787346
1fec8e78-bce4-4aaf-ab1b-5451cc387264
4345a7b9-9a63-4910-a426-35363201d503
```

Select the `access_as_user` scope for each client.

## SimpleChat Runtime Configuration

### Bicep Deployment

Set `enableTeamsSso` to `true` when deploying SimpleChat.

```json
{
  "enableTeamsSso": {
    "value": true
  },
  "teamsAppResource": {
    "value": "api://simplechat.contoso.com/00000000-0000-0000-0000-000000000000"
  }
}
```

When `enableTeamsSso` is true, the deployer sets these app settings for you:

- `ENABLE_TEAMS_SSO=true`
- `SESSION_COOKIE_SAMESITE=None`
- `SESSION_COOKIE_SECURE=true`
- `TEAMS_SUCCESS_REDIRECT_PATH=/chats`
- `TEAMS_APP_RESOURCE=<teamsAppResource value>` when supplied

The deployer also changes App Service Authentication (`authsettingsV2`) so unauthenticated requests can reach SimpleChat's app-level login flow. Teams cannot complete tab SSO if Easy Auth redirects the iframe to the Microsoft login page before `/login?teams=true` loads.

### Environment Variables

For manual deployments, set:

```bash
ENABLE_TEAMS_SSO=true
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=true
TEAMS_APP_RESOURCE=api://simplechat.contoso.com/00000000-0000-0000-0000-000000000000
```

Commercial Azure and Azure Government deployments get default Teams frame origins when `ENABLE_TEAMS_SSO=true`.

Use these only when you need to override the defaults, such as custom or air-gapped Teams clouds:

```bash
TEAMS_FRAME_ANCESTORS=https://teams.example.cloud https://*.teams.example.cloud
CUSTOM_TEAMS_ORIGINS=["https://teams.example.cloud", "https://*.teams.example.cloud"]
```

`TEAMS_FRAME_ANCESTORS` controls the server Content Security Policy `frame-ancestors` directive. `CUSTOM_TEAMS_ORIGINS` is passed to the Teams JavaScript SDK initialization call.

## Teams App Manifest

Use [application/teams_app/manifest.template.json](../../application/teams_app/manifest.template.json) as the starting point.

Replace these placeholders:

- `TEAMS_APP_ID`: A Teams app ID. This can be a generated GUID and does not have to be the Entra client ID.
- `HOSTNAME`: The SimpleChat host name without `https://`, such as `simplechat.contoso.com`.
- `CLIENT_ID`: The Entra app registration client ID.
- `TEAMS_APP_RESOURCE_URI`: The Application ID URI from **Expose an API**, such as `api://simplechat.contoso.com/<client-id>`.

The personal tab `contentUrl` should stay pointed at:

```text
https://HOSTNAME/login?teams=true
```

Package these files into a zip:

```text
manifest.json
color.png
outline.png
```

The generated `manifest.json` and zip file are intentionally ignored by Git.

## Cloud Notes

### Azure Commercial

Default Teams frame ancestors:

```text
https://teams.microsoft.com https://*.teams.microsoft.com
```

### Azure Government

Default Teams frame ancestors:

```text
https://teams.microsoft.us https://*.teams.microsoft.us
```

### Custom Clouds

Set `teamsFrameAncestors`, `customTeamsOrigins`, and `teamsAppResource` explicitly. Also verify Graph authority and Graph endpoint settings for the target cloud, because Teams SSO exchanges the Teams assertion for Microsoft Graph delegated scopes.

## Test Flow

1. Deploy SimpleChat with Teams SSO enabled.
2. Confirm `/login?teams=true` loads without an App Service Authentication redirect.
3. Upload the Teams app package in Teams.
4. Open the SimpleChat tab in Teams.
5. Confirm the tab signs in and redirects to `/chats`.

## Troubleshooting

### Failed To Get Authentication Token

- Confirm `webApplicationInfo.resource` exactly matches `TEAMS_APP_RESOURCE` and the Entra Application ID URI.
- Confirm Teams client applications are preauthorized for `access_as_user`.
- Confirm the Teams manifest `validDomains` includes the SimpleChat host name.

### Teams Sign-In Falls Back To Microsoft Sign-In

- Confirm `ENABLE_TEAMS_SSO=true`.
- Confirm the Teams tab URL is `/login?teams=true`.
- Confirm the local Teams SDK file is served from `/static/js/MicrosoftTeams.min.js`.

### App Does Not Load In The Teams Frame

- Confirm `TEAMS_FRAME_ANCESTORS` includes the Teams host for your cloud.
- Confirm `X-Frame-Options` is not emitted when Teams SSO is enabled.
- Confirm App Service Authentication allows unauthenticated requests to the app-level login flow.

### Session Does Not Persist

- Confirm HTTPS is used.
- Confirm `SESSION_COOKIE_SAMESITE=None`.
- Confirm `SESSION_COOKIE_SECURE=true`.

## Local Teams SDK Asset

SimpleChat vendors the Teams JavaScript SDK under `application/single_app/static/js/MicrosoftTeams.min.js` so disconnected and sovereign environments do not load browser runtime JavaScript from a public CDN.