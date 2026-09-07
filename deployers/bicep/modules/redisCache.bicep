targetScope = 'resourceGroup'

param location string
param appName string
param environment string

@description('''Authentication type for the Redis cache.
- managed_identity uses Microsoft Entra authentication and disables access keys on Azure Managed Redis.
- key provisions the cache with access key authentication enabled.''')
@allowed([
  'key'
  'managed_identity'
])
param redisAuthenticationType string = 'managed_identity'

@description('''Which Azure Redis offering to provision.
- managed deploys Azure Managed Redis (Microsoft.Cache/redisEnterprise), the replacement for the retiring Azure Cache for Redis tiers.
- classic deploys Azure Cache for Redis (Microsoft.Cache/Redis) for clouds where Azure Managed Redis is unavailable, such as Azure Government and Azure operated by 21Vianet.''')
@allowed([
  'managed'
  'classic'
])
param redisCacheKind string = 'managed'

@description('''Azure Managed Redis SKU. Balanced_B0 (0.5 GB) is the documented replacement for Azure Cache for Redis Standard C0.
Only applies when redisCacheKind is managed.''')
param redisManagedSkuName string = 'Balanced_B0'

@description('''High availability for Azure Managed Redis.
Enabled matches the replication of Azure Cache for Redis Standard and is required for the availability SLA.
Disabled halves the cost for dev/test and cannot be turned back off once the instance exists.''')
@allowed([
  'Enabled'
  'Disabled'
])
param redisHighAvailability string = 'Enabled'

@description('''Clustering policy for the Azure Managed Redis database.
- NoCluster presents a single non-sharded endpoint, which is what SimpleChat's non-cluster-aware Redis client requires. Valid up to 25 GB and the only policy that can be changed later without recreating the database.
- EnterpriseCluster proxies a sharded cluster behind one endpoint; multi-key commands can return CROSSSLOT errors.
- OSSCluster requires a cluster-aware client and is not supported by SimpleChat.''')
@allowed([
  'NoCluster'
  'EnterpriseCluster'
  'OSSCluster'
])
param redisClusteringPolicy string = 'NoCluster'

param tags object

param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

var deployManagedRedis = redisCacheKind == 'managed'
var deployClassicRedis = !deployManagedRedis
var redisName = toLower('${appName}-${environment}-redis')

// Azure Cache for Redis exposes Microsoft Entra authentication through redisConfiguration.
var redisConfiguration = redisAuthenticationType == 'managed_identity' ? {
  'aad-enabled': 'true'
} : {}

//=========================================================
// Azure Managed Redis (Microsoft.Cache/redisEnterprise)
//=========================================================
resource managedRedis 'Microsoft.Cache/redisEnterprise@2025-07-01' = if (deployManagedRedis) {
  name: redisName
  location: location
  sku: {
    name: redisManagedSkuName
  }
  properties: {
    highAvailability: redisHighAvailability
    minimumTlsVersion: '1.2'
    // Azure Managed Redis does not support virtual network injection; the deployer does not
    // provision a Redis private endpoint today, matching the classic cache behavior.
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

// Azure Managed Redis serves a single database that must be named 'default'.
resource managedRedisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = if (deployManagedRedis) {
  #disable-next-line BCP318 // guarded by the same deployManagedRedis condition
  parent: managedRedis
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    // Must be set explicitly: the service default is OSSCluster, which requires a
    // cluster-aware client that SimpleChat does not use.
    clusteringPolicy: redisClusteringPolicy
    evictionPolicy: 'VolatileLRU'
    accessKeysAuthentication: redisAuthenticationType == 'key' ? 'Enabled' : 'Disabled'
    modules: []
  }
}

//=========================================================
// Azure Cache for Redis (Microsoft.Cache/Redis)
//=========================================================
resource classicRedisCache 'Microsoft.Cache/Redis@2024-11-01' = if (deployClassicRedis) {
  name: redisName
  location: location
  properties: {
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 0
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: redisConfiguration
  }
  tags: tags
}

//=========================================================
// Diagnostic settings
//=========================================================
resource classicRedisDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && deployClassicRedis) {
  name: toLower('${redisName}-diagnostics')
  #disable-next-line BCP318 // guarded by the same deployClassicRedis condition
  scope: classicRedisCache
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// Azure Managed Redis emits metrics on the cluster and connection logs on the database.
resource managedRedisMetricsDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && deployManagedRedis) {
  name: toLower('${redisName}-diagnostics')
  #disable-next-line BCP318 // guarded by the same deployManagedRedis condition
  scope: managedRedis
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

resource managedRedisDatabaseDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && deployManagedRedis) {
  name: toLower('${redisName}-database-diagnostics')
  #disable-next-line BCP318 // guarded by the same deployManagedRedis condition
  scope: managedRedisDatabase
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
  }
}

#disable-next-line BCP318 // exactly one of the two cache resources is deployed
output redisCacheName string = deployManagedRedis ? managedRedis.name : classicRedisCache.name
#disable-next-line BCP318 // exactly one of the two cache resources is deployed
output redisCacheHostName string = deployManagedRedis ? managedRedis.properties.hostName : classicRedisCache.properties.hostName
output redisCachePort int = deployManagedRedis ? 10000 : 6380
output redisCacheKind string = redisCacheKind
