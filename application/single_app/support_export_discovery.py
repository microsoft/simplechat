# support_export_discovery.py
"""Find the Azure resources a support export reads from, without asking the admin.

The application already runs inside the resources it needs to query: App Service
publishes the site's identity in platform environment variables, the deployers set
AZURE_ENVIRONMENT, and the telemetry connection string names the Application
Insights component. This module turns those into Azure Monitor resource IDs.
Nothing here performs I/O except ``lookup_app_insights_resource_id``.
"""

import json
import re

import requests


GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
RESOURCE_NAME = re.compile(r"[A-Za-z0-9_.()-]{1,90}\Z")
APP_INSIGHTS_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[A-Za-z0-9_.()-]+/providers/"
    r"Microsoft\.Insights/components/[A-Za-z0-9_.()-]+\Z", re.I,
)
RESOURCE_MANAGERS = {
    "public": "https://management.azure.com",
    "usgovernment": "https://management.usgovcloudapi.net",
}
RESOURCE_GRAPH_API_VERSION = "2021-03-01"


def detect_cloud(env):
    """Return the Azure Monitor cloud from AZURE_ENVIRONMENT, or "" when it cannot be inferred."""
    value = (env.get("AZURE_ENVIRONMENT") or "public").strip().lower()
    return value if value in RESOURCE_MANAGERS else ""


def detect_site_resource_id(env):
    """Build this App Service's resource ID from the platform's own environment variables.

    App Service sets WEBSITE_OWNER_NAME to "<subscription>+<resource group>-<region>webspace",
    WEBSITE_RESOURCE_GROUP and WEBSITE_SITE_NAME on every worker. The deployers also set
    AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP, which fill any gap.
    """
    site = (env.get("WEBSITE_SITE_NAME") or "").strip()
    if not site or not RESOURCE_NAME.fullmatch(site):
        return ""
    owner = (env.get("WEBSITE_OWNER_NAME") or "").strip()
    subscription = owner.split("+", 1)[0].strip() if "+" in owner else ""
    if not GUID.fullmatch(subscription):
        subscription = (env.get("AZURE_SUBSCRIPTION_ID") or "").strip()
    group = (env.get("WEBSITE_RESOURCE_GROUP") or env.get("AZURE_RESOURCE_GROUP") or "").strip()
    if not group and "+" in owner:
        # The owner name ends in "-<region>webspace" (optionally "-Linux"); the region never contains "-".
        group = re.sub(r"-[A-Za-z0-9]+webspace(-Linux)?\Z", "", owner.split("+", 1)[1], flags=re.I)
    if not GUID.fullmatch(subscription) or not RESOURCE_NAME.fullmatch(group):
        return ""
    resource = f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.Web/sites/{site}"
    slot = (env.get("WEBSITE_SLOT_NAME") or "").strip()
    if slot and slot.lower() != "production" and RESOURCE_NAME.fullmatch(slot):
        resource += f"/slots/{slot}"
    return resource


def instrumentation_key(env):
    """Return the Application Insights instrumentation key the app already sends telemetry to."""
    connection = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING") or ""
    for part in connection.split(";"):
        name, _, value = part.partition("=")
        if name.strip().lower() == "instrumentationkey" and GUID.fullmatch(value.strip()):
            return value.strip().lower()
    legacy = (env.get("APPINSIGHTS_INSTRUMENTATIONKEY") or "").strip()
    return legacy.lower() if GUID.fullmatch(legacy) else ""


def configured_app_insights_resource_id(env):
    value = (env.get("APPLICATIONINSIGHTS_RESOURCE_ID") or "").strip()
    return value if APP_INSIGHTS_ID.fullmatch(value) else ""


def lookup_app_insights_resource_id(key, cloud, credential, *, post=None, timeout=15):
    """Find the component that owns ``key`` with Azure Resource Graph.

    The application identity needs read access to the component to query its logs, and
    that same access lets Resource Graph see it, so no extra role is required.
    Returns "" when nothing (or more than one component) matches.
    """
    if not GUID.fullmatch(key or "") or cloud not in RESOURCE_MANAGERS:
        return ""
    manager = RESOURCE_MANAGERS[cloud]
    token = credential.get_token(manager + "/.default").token
    query = (
        "resources | where type =~ 'microsoft.insights/components' "
        f"| where tolower(tostring(properties.InstrumentationKey)) == {json.dumps(key)} "
        "| project id | take 2"
    )
    response = (post or requests.post)(
        f"{manager}/providers/Microsoft.ResourceGraph/resources?api-version={RESOURCE_GRAPH_API_VERSION}",
        json={"query": query}, headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
    )
    response.raise_for_status()
    rows = (response.json() or {}).get("data") or []
    if len(rows) != 1:
        return ""
    resource = str(rows[0].get("id") or "")
    return resource if APP_INSIGHTS_ID.fullmatch(resource) else ""


def detect_configuration(env, *, lookup=None):
    """Return detected values plus where each came from.

    ``lookup(key, cloud)`` resolves an instrumentation key to a component ID; it is only
    called when the deployer did not set APPLICATIONINSIGHTS_RESOURCE_ID.
    """
    cloud = detect_cloud(env)
    site = detect_site_resource_id(env)
    app = configured_app_insights_resource_id(env)
    app_origin = "environment" if app else ""
    if not app and lookup is not None and cloud:
        key = instrumentation_key(env)
        if key:
            app = lookup(key, cloud) or ""
            app_origin = "connection_string" if app else ""
    return {
        "cloud": cloud,
        "app_resource_id": app,
        "site_resource_id": site,
        "origins": {
            "cloud": "environment" if cloud else "",
            "app_resource_id": app_origin,
            "site_resource_id": "app_service" if site else "",
        },
    }
