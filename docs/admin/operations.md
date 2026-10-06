---
layout: page
title: "Operations settings"
description: "Operations covers who can open the Control Center and how current its figures are, Application Insights, debug and file processing logs with automatic turnoff, health check endpoints, and the Swagger API documentation."
section: "Administration"
audience: admin
admin_tab: operations
redirect_from:
  - /admin/control-center-config/
  - /admin/logging/
---


# Operations settings

## What this group controls

Operations decides how SimpleChat is watched while it runs and how it is diagnosed when
something goes wrong: who can open the Control Center and how current its figures are, what
the app logs and for how long, which health endpoints answer your monitors, and whether the
API is documented for developers.

## Why it matters

Most of these settings are either temporary by nature or tied to something outside
SimpleChat, and both kinds fail quietly. Debug output left on keeps writing request content
to the log stream long after the investigation ended. A health check switched off while App
Service still probes it makes App Service treat healthy instances as failed. Requiring a
Control Center role that nobody holds yet takes the dashboard away from every administrator.

The V2 page puts each of these consequences beside the switch that causes it, and shows what
a save will do before you make it: when a timer will turn logging off, when the next refresh
will run, who will be able to open the Control Center, and whether a restart is still needed.

{% include media.html src="admin-settings/control-center.png" alt="Screenshot of the Operations group in Admin Settings." title="Operations settings" %}

{% include media.html src="admin-settings/logging.png" alt="Screenshot of the Operations group in Admin Settings." title="Operations settings" %}

{% include media.html type="video" title="Operations settings walkthrough" poster="video-posters/admin-operations.png" capture="Recording planned. Walk through each tab in the Operations group and explain when to change each setting." %}

## Before you change anything

- Assign the `ControlCenterAdmin` app role, including to yourself, and sign in again before
  requiring it. A role assignment reaches someone only at their next sign-in.
- Find out whether App Service Health check points at `/external/healthcheck`. The bundled
  deployers configure it, so switching that endpoint off has an effect outside this page.
- Plan an App Service restart for Application Insights global logging and for Swagger. Both
  are read once, when the app starts.

## Control Center {#control-center-config}

The Control Center is SimpleChat's operations dashboard: usage statistics and activity
trends, plus management of users, groups, public workspaces and the activity log. This tab
decides how current its figures are and who can open it.

### Automatic Data Refresh {#control-center-auto-refresh-section}

Control Center figures are cached for each user and group, because working them out reads
every user and group record. The daily refresh recalculates them at a quiet hour, so the
dashboard is current each morning without anyone refreshing it by hand. With it off, the
figures change only when an administrator refreshes them from the Control Center.

The refresh time is a wall-clock time in an IANA timezone, so `02:00` in `America/New_York`
stays 02:00 local time through daylight saving. The next run is calculated when the schedule
is saved and again after each scheduled refresh, and is stored in UTC. Refreshing by hand
from the Control Center updates the last-refreshed time and leaves the next scheduled run
alone. A background check looks for a due refresh every five minutes, so a refresh starts
within five minutes of its time. Saving other settings leaves a scheduled refresh where it
is.

On the days clocks change, a time that is skipped runs when the clock jumps past it: `02:00`
in `America/New_York` runs at 03:00 on the spring changeover. A time that happens twice runs
at the first.

The V2 card shows the next refresh in the schedule's own timezone and, when yours is
different, in your time as well. **Use my timezone** sets the schedule to your browser's
zone. While the time or zone has unsaved changes, the card shows the refresh a save would
schedule; the stored schedule stays in force until you save. The card also shows when the
figures were last refreshed and links to the Control Center.

V2 refuses a time or timezone it cannot read and says so on the field. The classic page
quietly falls back to `02:00` and `America/New_York` instead.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Daily Control Center Refresh | Recalculates the cached Control Center figures for every user and group once a day. Off leaves them as they were at the last manual refresh. | On | `control_center_auto_refresh_enabled` |
| Refresh Time | The time of day the refresh starts, read in the timezone below. | 02:00 | `control_center_auto_refresh_time`; stored as 24-hour `HH:MM` |
| Timezone | The IANA timezone the refresh time is read in, such as `Europe/London`. | America/New_York | `control_center_auto_refresh_timezone` |

### Control Center Access {#control-center-overview-section}

By default the Control Center belongs to SimpleChat's general `Admin` role. Two app roles
let you hand it to people who should not be full SimpleChat administrators, or keep it from
administrators who should not see usage data.

The two switches interact, and the combination matters more than either switch alone:

| App role | Requirement off | Requirement on |
| --- | --- | --- |
| `Admin` | Dashboard and management | No access. Admin Settings stays open, so the requirement can be switched back off. |
| `ControlCenterAdmin` | No access; the role is ignored | Dashboard and management |
| `ControlCenterDashboardReader` | Dashboard only, while **Allow ControlCenterDashboardReader App Role** is on | Dashboard only, while **Allow ControlCenterDashboardReader App Role** is on |

"Requirement" is **Require ControlCenterAdmin App Role**. Each row is one role held on its
own; someone holding two gets the better row. The dashboard reader role works the same way
whether or not the ControlCenterAdmin requirement is on. While the requirement is on,
`ControlCenterAdmin` is enough by itself: holders do not also need `Admin`.

The V2 card draws this table from the switches as they stand, unsaved changes included, so
you can see who gains and loses access before saving. Its role values copy with one click.

#### Setting up the roles

The **Role setup guide** on the V2 card walks through the same steps, with values to copy.

1. In the Azure portal, open **Microsoft Entra ID**, then **App registrations**, and select
   SimpleChat's registration.
2. Under **App roles**, create `ControlCenterAdmin` and `ControlCenterDashboardReader`. Use
   the same text for the display name and the value, which is case-sensitive, and allow
   **Users/Groups**.
3. In **Enterprise applications**, open the application with the same name, select **Users
   and groups**, and assign people or groups to each role.
4. Ask everyone you assigned to sign out and back in.
5. Switch on the requirements you want here, and save.
6. Open the Control Center as each kind of user. ControlCenterAdmin holders see every tab;
   dashboard readers see the dashboard only.

To assign many people at once, or from automation, use Microsoft Graph PowerShell:

```powershell
Install-Module Microsoft.Graph -Scope CurrentUser
Connect-MgGraph -Scopes "AppRoleAssignment.ReadWrite.All", "User.Read.All"

# Find the application and its role ids
$sp = Get-MgServicePrincipal -Filter "displayName eq 'YourAppName'"
$sp.AppRoles | Select-Object DisplayName, Id, Value

# Assign a role to a user
$user = Get-MgUser -UserId "user@domain.com"
$params = @{
    principalId = $user.Id
    resourceId = $sp.Id
    appRoleId = "role-guid-from-the-previous-step"
}
New-MgUserAppRoleAssignment -UserId $user.Id -BodyParameter $params
```

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Require ControlCenterAdmin App Role | Restricts the whole Control Center, dashboard and management alike, to holders of `ControlCenterAdmin`. General Admins without the role lose access. | Off | `require_member_of_control_center_admin` |
| Allow ControlCenterDashboardReader App Role | Opens the Control Center dashboard, without any management, to holders of `ControlCenterDashboardReader`. | Off | `require_member_of_control_center_dashboard_reader`; works whether or not the requirement above is on |

## Logging & Health {#logging}

This tab covers what SimpleChat records about itself, where that goes, and the endpoints
other systems use to check it is running. Two of its settings are read only when the App
Service starts; on the V2 page, a **Running state** line says whether the running app
matches what is saved, so a change that still needs a restart is not mistaken for one that
did not work.

### Application Insights {#application-insights-section}

SimpleChat always sends its own events, and warnings and errors from everything else, to
Application Insights when it has somewhere to send them. Global logging raises the
application-wide log level to informational, so routine messages from every module and
library arrive as well, agents and orchestration included. That is useful while tracing a
problem across components, and costs noticeably more ingestion while it is on.

Application Insights is reached through the `APPLICATIONINSIGHTS_CONNECTION_STRING` App
Service setting, not through anything on this page. The V2 card's **Connection** line says
whether that setting is present and whether the exporter started, because the switch does
nothing without them.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Application Insights Global Logging | Sends informational messages from every module and library to Application Insights, not only SimpleChat's own events. | Off | `enable_appinsights_global_logging`; takes effect after an App Service restart |

### Debug Logging {#debug-logging-section}

Debug logging writes SimpleChat's DEBUG output to the App Service log stream, and to
Application Insights as traces while it is connected. Use it to troubleshoot a problem you
can reproduce, then turn it off: debug output can include tokens, keys and request content
that ordinary logs leave out.

**Turn off automatically** makes that the default outcome. The timer starts when you save
it, so it runs for the full duration from that moment; saving it again with the same duration
and unit leaves the clock where it is. Each unit has its own limit, and a longer duration is
reduced to that limit when saved:

| Unit | Range |
| --- | --- |
| Minutes | 1-120 |
| Hours | 1-24 |
| Days | 1-7 |
| Weeks | 1-52 |

The turnoff time is stored in UTC, and the V2 card shows it in your own timezone with how far
off it is. While you change the duration, the card shows when a save would turn logging off.
A background check runs every minute and switches logging and its timer off once the time
has passed.

#### Document Access Index diagnostics

**Document Access Index diagnostics**, under **Feature diagnostics**, reveals support
controls on the classic page's **Scale › Cosmos › DAI Metrics** card: **Run One Backfill
Batch**, **Reset Checkpoint**, the automatic maintenance and diagnostics controls, and the
shadow validation status and last result. Leave it off unless you are investigating document
access projection problems. The index's background maintenance runs either way. See
[Scale settings]({{ '/admin/scale/' | relative_url }}) for the card itself.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Debug Logging | Writes SimpleChat's DEBUG output to the log stream and, while it is connected, to Application Insights. | Off | `enable_debug_logging` |
| Turn off automatically | Switches debug logging off once the duration below has passed, counted from the save that starts the timer. | Off | `debug_logging_timer_enabled` |
| Duration | How long debug logging stays on. | 1 | `debug_timer_value`; limited by the unit |
| Time Unit | Minutes, hours, days or weeks. | hours | `debug_timer_unit` |
| Document Access Index diagnostics | Shows the support-only backfill, checkpoint and shadow validation controls on the classic DAI Metrics card. | Off | `enable_dai_debug`; V2 only |

### File Process Logging {#file-processing-logs-section}

File processing logs record each step SimpleChat takes with an uploaded file, errors
included, in the `file_processing` container in Cosmos DB. Read them there when an upload
stalls or fails. Turning logging off stops new records; existing ones stay until you delete
them.

The automatic turnoff works exactly as it does for debug logging, with the same limits, and
keeps a temporary investigation from growing the container indefinitely.

#### Deleting stored logs

Records are never pruned on their own, so the container keeps growing while logging is on.
**Delete stored logs** removes records older than a number of days, weeks or months, or every
record, whether or not logging is currently on. It asks you to confirm exactly what will be
deleted, acts immediately rather than waiting for **Save**, and is recorded in the admin
activity log with how many records went. In V2, if a deletion stops partway, the
confirmation dialog says how many records were already removed.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable File Processing Logs | Records each step of processing an uploaded file in the `file_processing` container. | On | `enable_file_processing_logs` |
| Turn off automatically | Switches file processing logs off once the duration below has passed, counted from the save that starts the timer. | Off | `file_processing_logs_timer_enabled` |
| Duration | How long the logs stay on. | 1 | `file_timer_value`; limited by the unit |
| Time Unit | Minutes, hours, days or weeks. | hours | `file_timer_unit` |

### Health Check {#health-check-section}

Two endpoints tell a monitor that SimpleChat is answering requests and can read its own
settings. Neither exercises Azure AI Search, Azure OpenAI or storage, so a failing check
points at the app itself rather than at a service behind it.

| Endpoint | Answers | Switched off |
| --- | --- | --- |
| `/external/healthcheck` | HTTP 200 with the server time as text | HTTP 400 with `{"error": "Enable External Healthcheck is disabled."}` |
| `/external/healthcheckz` | HTTP 200 with `{"status": "ok", "time": "..."}` | HTTP 400 with `{"error": "Enable No Auth External Healthcheck is disabled."}` |

`/external/healthcheck` is reached through the app's normal access boundary, such as App
Service Authentication. App Service's own Health check works with that in place, which is why
the bundled deployers point Health check at this path. While that is configured, switching
the endpoint off here makes every check fail and App Service starts treating its instances as
unhealthy.

`/external/healthcheckz` is for probes that cannot sign in, such as an external monitor or a
load balancer. It answers anyone who can reach the app, so only enable it for trusted probes
or controlled network paths. If App Service Authentication requires sign-in for every
request, exclude this path there as well, or the probe is turned away before it reaches
SimpleChat.

The V2 card lists both endpoints as full addresses for this deployment, ready to copy into a
monitoring tool, says whether each answers without sign-in, and offers **Open** for the ones
that are on. Its **Configuration guide** walks through App Service Health check setup.

#### Pointing App Service Health check at SimpleChat

1. Switch on **Enable /external/healthcheck** and save first, so the path answers before App
   Service starts asking.
2. In the Azure portal, open the App Service and select **Health check** under
   **Monitoring**.
3. Select **Enable**, enter `/external/healthcheck`, and save.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable /external/healthcheck | Answers availability checks that come through the app's normal access boundary. | Off | `enable_external_healthcheck`; the bundled deployers switch it on and configure App Service Health check to use it |
| Enable /external/healthcheckz | Answers availability checks from probes that cannot sign in. | Off | `enable_no_auth_external_healthcheck`; answers without sign-in |

### API Documentation {#swagger-section}

Swagger publishes an interactive explorer for SimpleChat's API at `/swagger`, and the
OpenAPI 3 specification it is generated from at `/swagger.json` and `/swagger.yaml`. The
specification comes from the application's own routes, so it stays current as features are
added and shows which routes need a signed-in session. Developers integrating with SimpleChat
can find routes and request shapes themselves, try requests from the browser, and generate
clients from the specification.

Any signed-in user can open these pages, not only administrators, and requests sent from the
explorer run with that person's own session and permissions. There is no admin-only mode, so
switch Swagger off if you would rather not publish the API surface to everyone who can sign
in. The specification is cached on the server, and the two specification endpoints answer at
most 30 requests a minute from each client address.

The routes are registered when the App Service starts, so a saved change takes effect after
a restart. The V2 card's **Running state** line says whether the running app is serving them,
and its links copy the full addresses to share with developers.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Swagger/OpenAPI Documentation (/swagger) | Serves the API explorer and its OpenAPI specification to signed-in users. | On | `enable_swagger`; treated as on when never saved; takes effect after an App Service restart |

## Common tasks

1. **Troubleshoot a reproducible problem.** Switch on debug logging with **Turn off
   automatically** set to a few hours, reproduce the problem, and read the log stream. You
   are done when the card shows a turnoff time, and nothing needs remembering afterwards.
2. **Hand the Control Center to an operations team.** Create and assign the two app roles,
   have the team sign in again, switch on the requirement you need, and check the access
   table before saving. Confirm by opening the Control Center as a member of the team.
3. **Monitor availability from outside Azure.** Switch on `/external/healthcheckz`, exclude
   it from App Service Authentication if sign-in is required, and point the probe at the
   address the V2 card shows. A healthy app answers `{"status": "ok", ...}`.
4. **Keep the file processing container in check.** Delete logs older than the period you
   still investigate, or set a timer the next time you switch logging on for an upload
   problem.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| An administrator can no longer open the Control Center | **Require ControlCenterAdmin App Role** is on and they do not hold `ControlCenterAdmin`, or have not signed in since it was assigned. | Assign the role and have them sign in again, or switch the requirement off. Admin Settings stays open to them either way. |
| Someone with `ControlCenterAdmin` gets no access | The requirement is off, so the role is ignored; or the role value in Entra does not match exactly, including case. | Switch the requirement on, or correct the role value and have them sign in again. |
| A dashboard reader sees Forbidden | The role covers the dashboard only. Users, groups, public workspaces and activity logs are refused by design. | Assign `ControlCenterAdmin` to anyone who needs the management features. |
| Control Center figures are out of date | The daily refresh is off, or its time or timezone is not what you expected. | Check **Next refresh** on the V2 card, which shows the time in your own zone as well as the schedule's. |
| Global logging or Swagger did not change after saving | Both are read when the App Service starts. | Restart the App Service. **Running state** on the V2 card confirms the change once it is live. |
| Nothing reaches Application Insights | `APPLICATIONINSIGHTS_CONNECTION_STRING` is not set, or the exporter did not start. | Set the App Service setting, restart, and check the **Connection** line on the V2 card. |
| Debug logging switched itself off | Its timer ran out. | Switch it on again with a new duration, or switch **Turn off automatically** off. |
| A health check returns HTTP 400 | That endpoint is switched off here. | Switch it on and save. |
| An external probe is redirected to sign in or gets HTTP 401 | App Service Authentication answered before SimpleChat did. | Use `/external/healthcheckz` and exclude it from authentication. |
| App Service keeps replacing instances | Health check points at a path that is switched off, or the app is not answering requests at all. | Switch the configured path on here, then check the application log stream. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }}), where every app role requirement is gathered in one place
- [Scale settings]({{ '/admin/scale/' | relative_url }}), for the DAI Metrics card
- [Logging tags]({{ '/reference/logging-tags/' | relative_url }})
