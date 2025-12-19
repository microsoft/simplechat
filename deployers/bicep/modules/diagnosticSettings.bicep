// ===============================================
// Diagnostic Settings Configuration Module
// Provides standardized diagnostic settings configurations for reuse
// ===============================================

// Standard retention policy (disabled, follows workspace settings)
var standardRetentionPolicy = {
  enabled: false
  days: 0
}

// Standard log categories using category groups (recommended for most resources)
var standardLogCategories = [
  {
    categoryGroup: 'Audit'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    categoryGroup: 'allLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
]

// Standard log categories using category groups (recommended for most resources)
var limitedLogCategories = [
  {
    categoryGroup: 'allLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
]

// Standard metrics configuration
var standardMetricsCategories = [
  {
    category: 'AllMetrics'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
]

// Transaction metrics only (for storage accounts)
var transactionMetricsCategories = [
  {
    category: 'Transaction'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
]

// Web App specific log categories  
var webAppLogCategories = [
  {
    category: 'AppServiceAntivirusScanAuditLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceHTTPLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceConsoleLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceAppLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceFileAuditLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceAuditLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceIPSecAuditLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServicePlatformLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
  {
    category: 'AppServiceAuthenticationLogs'
    enabled: true
    retentionPolicy: standardRetentionPolicy
  }
]

// Export configurations as outputs so they can be used by other templates
output limitedLogCategories array = limitedLogCategories
output standardRetentionPolicy object = standardRetentionPolicy
output standardLogCategories array = standardLogCategories
output standardMetricsCategories array = standardMetricsCategories
output transactionMetricsCategories array = transactionMetricsCategories
output webAppLogCategories array = webAppLogCategories
