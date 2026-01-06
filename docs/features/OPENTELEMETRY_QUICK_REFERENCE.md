# OpenTelemetry Configuration - Quick Reference

## Version: 0.229.099

## Admin Settings Location
Navigate to: **Admin Settings > Logging Tab > OpenTelemetry Configuration**

---

## Quick Configuration Scenarios

### 🚀 Production (Cost-Optimized)
```
Service Name: simplechat-production
Traces Sampler: parentbased_traceidratio
Sampler Argument: 0.1
Flask Excluded URLs: healthcheck,/health,/external/health
Logs Exporter: otlp
Metrics Exporter: otlp
Live Metrics: Enabled
```
**Result:** 10% sampling = 90% cost reduction while maintaining visibility

---

### 🔧 Development (Full Visibility)
```
Service Name: simplechat-dev
Traces Sampler: always_on
Sampler Argument: 1.0
Flask Excluded URLs: (leave default)
Logs Exporter: console,otlp
Metrics Exporter: console,otlp
Live Metrics: Enabled
```
**Result:** Complete telemetry for debugging and development

---

### 🔒 Privacy-Focused (No Database Queries)
```
Service Name: simplechat-compliance
Traces Sampler: parentbased_always_on
Sampler Argument: 1.0
Flask Excluded URLs: healthcheck,/health,/external/health
Disabled Instrumentations: sqlalchemy,pymysql,psycopg2
Logs Exporter: otlp
Metrics Exporter: otlp
Live Metrics: Enabled
```
**Result:** Full tracing without exposing database query contents

---

### 📊 Metrics-Only (External Platform)
```
Service Name: simplechat
Traces Sampler: always_off
Sampler Argument: 0.0
Logs Exporter: none
Metrics Exporter: none
Live Metrics: Disabled
```
**Result:** Use external metrics platform (Prometheus, etc.)

---

## Setting Defaults

| Setting | Default Value | Valid Options |
|---------|---------------|---------------|
| Service Name | simplechat | Any string |
| Traces Sampler | parentbased_always_on | See options below |
| Sampler Argument | 1.0 | 0.0 to 1.0 |
| Flask Excluded URLs | healthcheck,/health,/external/health | Comma-separated patterns |
| Disabled Instrumentations | (empty) | flask,requests,redis,sqlalchemy,etc. |
| Logs Exporter | console,otlp | console, otlp, both, none |
| Metrics Exporter | otlp | console, otlp, both, none |
| Live Metrics | Enabled | On/Off |

---

## Traces Sampler Options

- **always_on** - Sample all traces (100%)
- **always_off** - Sample no traces (0%)
- **traceidratio** - Sample percentage based on sampler argument
- **parentbased_always_on** - Always sample, respect parent decisions (default)
- **parentbased_always_off** - Never sample, respect parent decisions
- **parentbased_traceidratio** - Percentage sampling, respect parent decisions (recommended for production)

---

## Common Excluded URL Patterns

```
healthcheck                          # Matches /healthcheck
/health                              # Matches /health exactly
/external/health                     # Matches /external/health exactly
healthcheck,/health,/external/health # Multiple patterns (default)
/static/.*                          # Exclude all static files
/api/internal/.*                    # Exclude internal API endpoints
^/metrics                           # Metrics endpoint
(healthcheck|ping|status)           # Multiple alternatives
```

---

## Common Disabled Instrumentations

```
flask                    # Disable Flask endpoint tracing
requests                 # Disable outbound HTTP call tracing
redis                    # Disable Redis operation tracing
sqlalchemy               # Disable SQLAlchemy query tracing
pymysql                  # Disable PyMySQL query tracing
psycopg2                 # Disable PostgreSQL query tracing
flask,requests           # Multiple (comma-separated)
sqlalchemy,pymysql,psycopg2  # All database instrumentations
```

---

## Cost Optimization Tips

1. **Start Conservative**: Begin with 10% sampling (0.1) in production
2. **Exclude Health Checks**: Always exclude high-frequency endpoints
3. **Monitor Costs**: Review Azure Monitor billing regularly
4. **Adjust Dynamically**: Increase sampling during incidents, reduce during normal operation
5. **Use Parent-Based Samplers**: Respect upstream sampling decisions
6. **Consider Business Value**: Sample 100% of critical transactions, less for routine operations

---

## Important Notes

⚠️ **Restart Required**: All OpenTelemetry setting changes require an application restart to take effect.

⚠️ **Connection String**: Ensure `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable is set for telemetry to work.

⚠️ **Sampling Impact**: Low sampling rates may miss rare issues. Balance cost vs visibility.

⚠️ **Privacy Considerations**: Disable database instrumentation if queries contain PII.

---

## Troubleshooting

### No Telemetry Appearing
1. Check Application Insights connection string is set
2. Verify Application Insights Global Logging is enabled
3. Ensure traces sampler is not set to "always_off"
4. Confirm application has been restarted after changes

### Too Much Data / High Costs
1. Reduce sampler argument (e.g., from 1.0 to 0.1)
2. Add more patterns to Flask excluded URLs
3. Disable unnecessary instrumentations
4. Set logs/metrics exporter to "none" if not needed

### Missing Specific Traces
1. Check if URL matches excluded patterns
2. Verify sampler is not too restrictive
3. Ensure relevant instrumentation is not disabled
4. Check if parent trace context is being dropped

---

## Additional Resources

- Full Documentation: `docs/features/OPENTELEMETRY_CONFIGURATION.md`
- Functional Tests: `functional_tests/test_otel_settings.py`
- OpenTelemetry Docs: https://opentelemetry.io/docs/zero-code/python/configuration/
- Azure Monitor Docs: https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-configuration

---

## Support

For questions or issues with OpenTelemetry configuration:
1. Review the full documentation linked above
2. Check the functional tests for examples
3. Consult OpenTelemetry and Azure Monitor documentation
4. Contact your administrator or DevOps team
