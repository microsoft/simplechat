# Troubleshooting

- [OpenTelemetry Settings](#opentelemetry-settings)
- [Backend call failing](#backend-call-failing)
- [Flask Instrumentation Startup Error](#flask-instrumentation-startup-error)

## OpenTelemetry Settings

- [Azure Monitor Info](https://pypi.org/project/azure-monitor-opentelemetry)
- [OpenTelemetry Settings](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)

## Backend call failing

SimpleChat uses flask instrumentation by default and backend calls are logged to Application Insights.  Query the 'requests' table to find the failing call and note the 'operation_Id'.  Use the operation ID to find associated exceptions like below.

### Query failed requests

```
requests
| where success == false
```

### Query most recent exceptions

```
exceptions
| top 10 by timestamp
```

### Query exceptions associated with a specific operation_Id

```
exceptions
| where operation_Id == '61a97b6a6ddc11b465b5289738bddcf1'
```

## Flask Instrumentation Startup Error

If startup logs show an error initializing Flask Instrumentation it can be disabled using environment variable DISABLE_FLASK_INSTRUMENTATION.  Set it to '1' or 'true' to disable flask instrumentation. **REQUIRES APP RESTART**.

