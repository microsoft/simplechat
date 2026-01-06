# OpenTelemetry Configuration Settings

## Overview
This document outlines the OpenTelemetry (OTEL) configuration settings exposed in the SimpleChat admin settings interface. These settings allow administrators to fine-tune telemetry collection, sampling, and instrumentation behavior for Azure Monitor Application Insights integration.

**Version Implemented:** 0.229.099  
**Feature Type:** Configuration Enhancement  
**Component:** Azure Monitor / Application Insights Integration

## Architecture

SimpleChat uses the Azure Monitor OpenTelemetry Distro (`azure-monitor-opentelemetry==1.6.13`) which provides:
- Automatic instrumentation for Flask and other Python libraries
- Integration with Azure Monitor Application Insights
- OpenTelemetry-based telemetry collection (traces, metrics, logs)

## Exposed Configuration Settings

### 1. OTEL_SERVICE_NAME

**Type:** String (Environment Variable)  
**Default:** `"simplechat"`  
**Purpose:** Sets the logical service name for the application in telemetry data.

#### Why Expose This Setting?

**Admin Need:**
- **Multi-Environment Identification:** Administrators managing multiple SimpleChat deployments (dev, staging, production) need to distinguish telemetry data by environment.
- **Service Grouping:** In organizations running multiple instances, a custom service name helps group and filter telemetry data in Azure Monitor.
- **Compliance & Auditing:** Some organizations require specific naming conventions for services to meet compliance requirements.

**Use Cases:**
- Setting `"simplechat-production"` vs `"simplechat-dev"` to separate environments
- Using `"department-simplechat"` for departmental deployments
- Implementing naming conventions like `"region-environment-service"` (e.g., `"us-east-prod-simplechat"`)

**Toggle Behavior:**
- **When Set:** All telemetry will be tagged with the specified service name, making it easily filterable in Azure Monitor
- **When Not Set:** Defaults to `"simplechat"`, which may make it difficult to distinguish between multiple deployments

---

### 2. OTEL_TRACES_SAMPLER

**Type:** String (Environment Variable)  
**Default:** `"parentbased_always_on"`  
**Allowed Values:** 
- `"always_on"` - Sample all traces (100%)
- `"always_off"` - Sample no traces (0%)
- `"traceidratio"` - Sample a percentage of traces (requires OTEL_TRACES_SAMPLER_ARG)
- `"parentbased_always_on"` - Always sample, respecting parent trace decisions
- `"parentbased_always_off"` - Never sample, respecting parent trace decisions
- `"parentbased_traceidratio"` - Percentage-based sampling, respecting parent trace decisions

**Purpose:** Controls what percentage of application traces are collected and sent to Azure Monitor.

#### Why Expose This Setting?

**Admin Need:**
- **Cost Management:** Application Insights charges based on data ingestion volume. High-traffic applications can generate significant costs. Sampling reduces costs while maintaining visibility.
- **Performance Optimization:** Collecting every trace can impact application performance. Sampling reduces overhead.
- **Noise Reduction:** In high-volume environments, collecting 100% of traces can create noise. Sampling provides representative data without overwhelming the monitoring system.
- **Testing & Development:** Admins may want `always_on` in development but `parentbased_traceidratio` in production.

**Use Cases:**
- **Production High-Traffic:** Set to `"parentbased_traceidratio"` with 10% sampling to manage costs
- **Development/Testing:** Set to `"always_on"` to capture all traces for debugging
- **Incident Investigation:** Temporarily increase sampling during troubleshooting
- **Low-Traffic Environments:** Use `"always_on"` when cost isn't a concern

**Toggle Behavior:**
- **always_on:** Every request generates telemetry - highest visibility, highest cost
- **always_off:** No traces collected - zero cost, zero visibility (useful for temporarily disabling)
- **traceidratio:** Collects specified percentage - balanced cost/visibility (requires OTEL_TRACES_SAMPLER_ARG)

---

### 3. OTEL_TRACES_SAMPLER_ARG

**Type:** Float (Environment Variable)  
**Default:** `"1.0"` (100%)  
**Range:** 0.0 to 1.0  
**Purpose:** When using ratio-based samplers, defines the sampling percentage.

#### Why Expose This Setting?

**Admin Need:**
- **Fine-Grained Control:** Allows precise control over sampling rate to balance cost and visibility
- **Dynamic Cost Management:** Can be adjusted based on budget constraints or traffic patterns
- **Progressive Monitoring:** Start with low sampling and increase as needed

**Use Cases:**
- **Budget-Conscious Production:** Set to `"0.1"` (10% sampling) for cost-effective monitoring
- **High-Value Transactions:** Set to `"1.0"` (100%) for critical systems where every request matters
- **Gradual Rollout:** Start with `"0.01"` (1%) during initial deployment, increase to `"0.1"` after stabilization

**Toggle Behavior:**
- **1.0 (100%):** Full sampling - complete visibility, highest cost
- **0.1 (10%):** One in ten requests - reduced cost, statistically representative
- **0.01 (1%):** One in hundred requests - minimal cost, high-level trends only

---

### 4. OTEL_PYTHON_FLASK_EXCLUDED_URLS

**Type:** String (Comma-separated regex patterns)  
**Default:** `"healthcheck,/health,/external/health"`  
**Purpose:** Excludes specific URL patterns from Flask instrumentation to reduce noise and costs.

#### Why Expose This Setting?

**Admin Need:**
- **Noise Reduction:** Health check endpoints are called frequently (every few seconds) but rarely provide value in traces
- **Cost Optimization:** Excluding high-frequency, low-value endpoints significantly reduces data ingestion costs
- **Performance:** Reduces instrumentation overhead for endpoints that don't need tracing
- **Custom Requirements:** Different deployments may have different endpoints to exclude (internal monitoring, metrics, etc.)

**Use Cases:**
- **Health Checks:** Exclude `healthcheck,/health,/external/health` - these are called constantly by load balancers
- **Metrics Endpoints:** Exclude `/metrics,/prometheus` if using separate metrics collection
- **Static Assets:** Exclude `/static/.*` to avoid tracing CSS, JS, image requests
- **Internal APIs:** Exclude `/internal/.*` for endpoints used by monitoring systems

**Toggle Behavior:**
- **When Set:** Matching URLs are not instrumented, reducing cost and noise
- **When Not Set:** All endpoints are instrumented, including high-frequency health checks

**Example Patterns:**
```
healthcheck                    # Matches /healthcheck
/health                        # Matches /health exactly
/api/internal/.*              # Matches all URLs under /api/internal/
^/static/.*                   # Matches all static resources
(healthcheck|metrics|ping)    # Matches multiple patterns
```

---

### 5. OTEL_PYTHON_DISABLED_INSTRUMENTATIONS

**Type:** String (Comma-separated instrumentation names)  
**Default:** `""` (empty - all instrumentations enabled)  
**Common Values:** `"flask"`, `"requests"`, `"sqlalchemy"`, `"redis"`, etc.  
**Purpose:** Completely disables specific auto-instrumentation libraries.

#### Why Expose This Setting?

**Admin Need:**
- **Selective Instrumentation:** Some instrumentations may cause compatibility issues or performance problems
- **Debugging:** Temporarily disable specific instrumentations to isolate issues
- **Privacy & Compliance:** Disable database instrumentation if SQL queries contain sensitive data
- **Cost Control:** Disable high-volume, low-value instrumentations

**Use Cases:**
- **Database Privacy:** Set to `"sqlalchemy,pymysql"` to prevent SQL query capture
- **Compatibility Issues:** Disable specific instrumentation that conflicts with other libraries
- **Microservices:** In service mesh environments, disable Flask instrumentation in favor of mesh-level tracing
- **Selective Monitoring:** Only monitor specific layers (e.g., disable `"requests"` to only see Flask endpoints, not outbound calls)

**Toggle Behavior:**
- **Empty String:** All available instrumentations are active (default)
- **"flask":** Flask endpoint instrumentation disabled - no HTTP request traces
- **"requests":** Outbound HTTP call instrumentation disabled - only see inbound requests
- **"flask,requests":** Both disabled - minimal telemetry

**Available Instrumentation Names:**
- `flask` - Flask web framework
- `requests` - HTTP requests library
- `redis` - Redis client operations
- `pymysql` / `psycopg2` - Database clients
- `sqlalchemy` - SQLAlchemy ORM

---

### 6. OTEL_LOGS_EXPORTER

**Type:** String (Environment Variable)  
**Default:** `"console,otlp"`  
**Allowed Values:** `"console"`, `"otlp"`, `"none"`, `"console,otlp"`  
**Purpose:** Controls where OpenTelemetry logs are exported.

#### Why Expose This Setting?

**Admin Need:**
- **Log Routing Control:** Administrators may want logs in console for debugging but OTLP (Azure Monitor) for production
- **Cost Management:** Disabling log export to Azure Monitor while keeping traces can reduce costs
- **Development vs Production:** Different log export strategies for different environments
- **Troubleshooting:** Enable console logs temporarily to debug instrumentation issues

**Use Cases:**
- **Development:** `"console"` - see logs in application output for debugging
- **Production:** `"otlp"` - send logs only to Azure Monitor
- **Hybrid:** `"console,otlp"` - logs go to both console and Azure Monitor
- **Cost Savings:** `"none"` - disable log export while keeping traces and metrics

**Toggle Behavior:**
- **"console":** Logs appear in application output (stdout/stderr)
- **"otlp":** Logs sent to Azure Monitor via OpenTelemetry Protocol
- **"none":** No log export (logs still generated, just not exported)
- **"console,otlp":** Dual export for development environments

---

### 7. OTEL_METRICS_EXPORTER

**Type:** String (Environment Variable)  
**Default:** `"otlp"`  
**Allowed Values:** `"console"`, `"otlp"`, `"none"`, `"console,otlp"`  
**Purpose:** Controls where OpenTelemetry metrics are exported.

#### Why Expose This Setting?

**Admin Need:**
- **Metrics Strategy:** Some organizations use separate metrics platforms (Prometheus, etc.)
- **Cost Optimization:** Metrics can be high-volume; selective export reduces costs
- **Testing:** Console export useful for validating metrics without Azure Monitor
- **Granular Control:** Enable/disable metrics independently from traces and logs

**Use Cases:**
- **Prometheus Integration:** Set to `"none"` if using Prometheus for metrics
- **Development:** `"console"` to validate metric generation without cloud costs
- **Production:** `"otlp"` for full Azure Monitor integration
- **Troubleshooting:** Temporarily switch to `"console"` to debug metrics issues

**Toggle Behavior:**
- **"otlp":** Metrics flow to Azure Monitor (standard)
- **"console":** Metrics printed to console (debugging)
- **"none":** No metrics export (use external metrics system)

---

### 8. Enable Live Metrics

**Type:** Boolean  
**Default:** `True`  
**Purpose:** Enables Azure Monitor Live Metrics stream for real-time monitoring.

#### Why Expose This Setting?

**Admin Need:**
- **Real-Time Monitoring:** Live Metrics provides immediate visibility into application performance
- **Resource Usage:** Live Metrics maintains a persistent connection, which consumes resources
- **Development vs Production:** May want live metrics in production but not in development
- **Cost Awareness:** While Live Metrics itself is free, it does generate additional network traffic

**Use Cases:**
- **Production Monitoring:** Enable to see real-time request rates, failures, and performance
- **Resource-Constrained Environments:** Disable to reduce network and CPU overhead
- **Development:** Disable to reduce complexity during testing
- **Incident Response:** Enable during active troubleshooting for immediate feedback

**Toggle Behavior:**
- **Enabled:** Live Metrics stream active in Azure Monitor portal
- **Disabled:** Only historical telemetry available (reduces overhead)

---

## Configuration Priority

OpenTelemetry configuration follows this priority order:
1. **Environment Variables** (highest priority) - set in system environment
2. **Admin Settings** (medium priority) - set via web interface, written to environment
3. **Code Defaults** (lowest priority) - hardcoded in `functions_appinsights.py`

## Implementation Details

### Environment Variable Management
Settings are stored in the `settings` container in Cosmos DB and applied as environment variables during application startup. Changes require an application restart to take effect.

### Integration Points
- **app.py:** Calls `configure_azure_monitor()` at startup
- **functions_appinsights.py:** Manages OpenTelemetry configuration
- **route_frontend_admin_settings.py:** Handles admin UI for OTEL settings
- **admin_settings.html:** Provides UI for OTEL configuration

## Security Considerations

- **Sensitive Data:** OTEL_PYTHON_FLASK_EXCLUDED_URLS should be configured to exclude endpoints that might log sensitive information
- **SQL Queries:** Consider disabling database instrumentation if queries might contain PII
- **Debug Mode:** Be cautious with `always_on` sampling in production due to cost and data volume

## Cost Management Recommendations

1. **Start Conservative:** Begin with 10% sampling (`traceidratio` + `0.1`)
2. **Exclude Health Checks:** Always exclude high-frequency, low-value endpoints
3. **Monitor Costs:** Review Azure Monitor billing regularly
4. **Adjust Dynamically:** Increase sampling during incidents, reduce during normal operation
5. **Use Parent-Based:** `parentbased_traceidratio` respects upstream sampling decisions

## Migration Notes

Existing deployments using `enable_appinsights_global_logging` will continue to work. The new OTEL settings provide additional fine-grained control on top of the global enable/disable toggle.

## Testing

A functional test is provided at `functional_tests/test_otel_settings.py` to validate:
- Settings persistence in Cosmos DB
- Environment variable application
- Configuration precedence
- Restart requirement enforcement

## References

- [OpenTelemetry Environment Variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)
- [Azure Monitor OpenTelemetry](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-configuration)
- [Flask Instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/flask/flask.html)
- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/zero-code/python/configuration/)
