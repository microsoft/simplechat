# Azure Managed Redis Support

## Overview

SimpleChat connects to **Azure Managed Redis** and **Azure Cache for Redis** from the same
code path. New deployments provision Azure Managed Redis, while existing Azure Cache for
Redis instances keep working with no configuration change.

**Implemented in version:** 0.261.010
**Deployer version:** 1.0.27

Azure Cache for Redis Basic, Standard, and Premium retire on **September 30, 2028**, and the
Enterprise and Enterprise Flash tiers retire on **March 31, 2027**. Azure Managed Redis is
Microsoft's replacement offering, built on the Redis Enterprise stack.

Dual support is not only a migration convenience. Azure Managed Redis is not available in
Azure Government or Azure operated by 21Vianet, so organizations in those clouds must
continue to run Azure Cache for Redis.

## Why the two services need different handling

| | Azure Cache for Redis | Azure Managed Redis |
| --- | --- | --- |
| Resource type | `Microsoft.Cache/Redis` | `Microsoft.Cache/redisEnterprise` + `/databases` |
| TLS port | 6380 | **10000** |
| Host name suffix (public cloud) | `*.redis.cache.windows.net` | `*.<region>.redis.azure.net` |
| Host name suffix (US Gov) | `*.redis.cache.usgovcloudapi.net` | Not available |
| Host name suffix (21Vianet) | `*.redis.cache.chinacloudapi.cn` | Not available |
| Microsoft Entra token scope | `https://redis.azure.com/.default` | Same |
| Redis ACL username | Token `oid` claim | Same |
| Databases | Up to 16 | Only database 0 |
| Clustering | Non-clustered | Clustered by default |

The port is the change that breaks a deployment silently, so SimpleChat resolves it rather
than asking every administrator to know it.

## Architecture

### Service and port resolution

`application/single_app/functions_redis_client.py` is the single place that turns settings
into a connected client. Every caller &mdash; Flask session storage, the shared application
cache, and the admin connection test &mdash; goes through `create_redis_client()`.

Resolution order:

1. If `redis_port` is set to a valid port between 1 and 65535, use it.
2. Otherwise resolve the service type: an explicit `redis_service_type` wins; failing that
   the host name suffix is matched against the documented Azure suffixes.
3. Azure Managed Redis resolves to port 10000, Azure Cache for Redis to port 6380.

An unrecognized host name resolves to Azure Cache for Redis and port 6380. That preserves the
behavior of every deployment that predates this feature, including ones that front Azure
Cache for Redis with a custom DNS name.

`*.<region>.redisenterprise.cache.azure.net` &mdash; the retiring Azure Cache for Redis
Enterprise tiers &mdash; also resolves to port 10000, because those tiers run the same engine.

### Microsoft Entra authentication

Managed identity authentication uses the `redis-entraid` package, whose
`EntraIdCredentialsProvider` is a redis-py *streaming* credential provider. It renews the
Microsoft Entra token in the background and re-issues `AUTH` on connections that are already
open, which is what Microsoft requires for Azure Managed Redis.

Each long-lived client gets its own provider instance, cached by purpose: one for the shared
application cache and one for Flask session storage. That matters because
`EntraIdCredentialsProvider` holds a *single* re-authentication callback slot &mdash; handing
one provider to both clients would silently leave the first client's pooled connections
without proactive re-`AUTH`. Caching by purpose also means reconfiguring the cache does not
leak a refresh thread per call.

The admin "Test Redis Connection" button requests a non-streaming provider, so clicking it
does not start a background refresh thread, event loop, and recurring token request that
would live for the rest of the worker process.

`redis-entraid` is imported defensively. If the package is missing &mdash; for example an
application updated without reinstalling requirements &mdash; SimpleChat falls back to the
in-repo `RedisManagedIdentityCredentialProvider` and logs a warning instead of failing to
start. The fallback supplies credentials at connect time only, so it relies on the server
closing expired connections rather than refreshing them proactively.

Sovereign clouds are supported: the Microsoft Entra authority from `config.py` is passed
through to `DefaultAzureCredential`, so an Azure Government deployment acquires its token
from `login.microsoftonline.us`.

### Why `db=0` is safe

Azure Managed Redis serves a single database. redis-py only emits a `SELECT` command when the
database index is non-zero, so the `db=0` SimpleChat uses sends no `SELECT` and works against
both services.

## Configuration

| Setting key | Values | Default | Purpose |
| --- | --- | --- | --- |
| `redis_url` | Host name | Empty | Redis host name; also drives service detection |
| `redis_service_type` | `auto`, `azure_managed_redis`, `azure_cache_for_redis` | `auto` | Overrides host name detection |
| `redis_port` | 1&ndash;65535 | Empty | Overrides the port derived from the service |
| `redis_auth_type` | `key`, `key_vault`, `managed_identity` | Empty | Credential source |
| `redis_key` | Access key or Key Vault secret name | Empty | Credential for key and Key Vault modes |

All five appear on **Admin Settings &rarr; Scale &rarr; Redis & Caching**. The Redis Metrics
section on the same tab reports the resolved service and port, and whether that came from
detection or from an explicit setting.

## Deployment

The Bicep deployer provisions Azure Managed Redis by default.

| Parameter | Default | Purpose |
| --- | --- | --- |
| `redisCacheKind` | `managed` | `managed` for Azure Managed Redis, `classic` for Azure Cache for Redis in sovereign clouds |
| `redisManagedSkuName` | `Balanced_B0` | Azure Managed Redis SKU |
| `redisHighAvailability` | `Enabled` | Replication and availability SLA |
| `redisClusteringPolicy` | `NoCluster` | Clustering policy for the database |

### SKU choice

`Balanced_B0` is Microsoft's documented replacement for the Azure Cache for Redis **Standard
C0** that SimpleChat previously deployed. It provides 0.5 GB instead of 0.25 GB and, with high
availability enabled, costs less than Standard C0 did. It is the smallest Azure Managed Redis
SKU.

Keep `redisHighAvailability` set to `Enabled`. Standard C0 was already replicated, and
disabling high availability removes the SLA, allows data loss during maintenance, and cannot
be re-disabled once the instance exists.

### Clustering policy

`redisClusteringPolicy` must stay `NoCluster` unless you also change the application's Redis
client. The service default when the property is omitted is `OSSCluster`, which requires a
cluster-aware client; SimpleChat uses a plain `redis.Redis` client and hands the same client
to `flask-session`. `NoCluster` is valid up to 25 GB, avoids `CROSSSLOT` errors on multi-key
commands, and is the only policy that can be changed later without deleting the database.

### Access

With `redisAuthenticationType` set to `managed_identity`, the deployer disables access keys on
the Azure Managed Redis database and grants the web app's managed identity the built-in
`default` access policy on the database. No control-plane role assignment is needed, because
data access on Azure Managed Redis comes from the access policy assignment rather than from
Azure RBAC.

With `redisAuthenticationType` set to `key`, access keys stay enabled and `postconfig.py`
retrieves the primary key with `az redisenterprise database list-keys`.

## Migrating an existing deployment

SimpleChat uses Redis as a look-aside cache and session store with a Cosmos DB fallback, so
there is nothing to migrate. Microsoft explicitly sanctions skipping data migration for this
pattern, and RDB export is not available from the Standard tier in any case.

1. Provision an Azure Managed Redis instance, for example by redeploying with
   `redisCacheKind` set to `managed`.
2. Grant the web app's managed identity the `default` access policy on the database, or copy
   an access key.
3. Update **Redis Server Host Name** in Admin Settings to the new
   `<name>.<region>.redis.azure.net` host and save. The port changes automatically.
4. Use **Test Redis Connection**, then confirm the Redis Metrics section reports
   "Azure Managed Redis" and port 10000.
5. Delete the old cache.

Sessions do not survive the cutover, so users signed in at that moment sign in again. Perform
the change outside business hours.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_redis_service_type_detection.py` | Host suffix matrix, unknown-host fallback, admin overrides, invalid port handling, host normalization |
| `functional_tests/test_redis_client_factory.py` | Client construction per authentication mode and service, `db=0`, kwargs passthrough, validation errors, `redis-entraid` fallback, provider caching |
| `functional_tests/test_redis_entra_token_auth.py` | Entra `oid` username, token scope, streaming provider, sovereign-cloud authority |
| `functional_tests/test_cosmos_wave5a3_redis_monitoring.py` | Monitoring payload including the resolved service and port |
| `ui_tests/test_admin_redis_monitoring_settings_ui.py` | Admin Redis monitoring and explorer markup |

## Known limitations

- Azure Managed Redis is unavailable in Azure Government and Azure operated by 21Vianet.
  Deployments in those clouds must set `redisCacheKind` to `classic`.
- Azure Managed Redis does not support virtual network injection. Network isolation requires
  Azure Private Link, which this deployer does not provision for Redis.
- Some Redis `INFO` counters shown in Redis Metrics are unavailable on the Redis Enterprise
  engine and render as "Not available".
- Keyspace notifications are not available on Azure Managed Redis. SimpleChat does not use
  them.
