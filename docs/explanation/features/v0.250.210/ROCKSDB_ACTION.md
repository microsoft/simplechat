# RocksDB Action

Implemented in version: **0.250.210**

Version reference: `application/single_app/config.py` was updated to `VERSION = "0.250.210"` for this feature.

Dependencies: `requests`, Semantic Kernel action loading, workspace actions, and Key Vault action secret handling. No RocksDB library is installed in the application.

## Overview

The RocksDB action lets an agent read (and optionally write) an ordered
[RocksDB](https://github.com/facebook/rocksdb) key-value store from a SimpleChat conversation.

RocksDB is an **embedded** C++ library with no native network protocol. SimpleChat does **not**
run RocksDB locally and never opens a database directory on the application host. Instead, the
action calls a RocksDB-backed **HTTP/JSON service** that you operate alongside your data, using
the contract documented below.

```
Agent
  └── RocksDbPlugin (semantic_kernel_plugins/rocksdb_plugin.py)
        └── requests ──► RocksDB HTTP/JSON service ──► RocksDB database
```

Reads are always available. Writes are refused unless the action is explicitly configured to
allow them, matching the read-only default of the SQL action.

- **Action type**: `rocksdb`
- **Plugin module**: `application/single_app/semantic_kernel_plugins/rocksdb_plugin.py`

## Configuration

### Configuration fields

| Field | `additionalFields` key | Notes |
|---|---|---|
| Service Base URL | `base_url` | Required. `http` or `https` only. |
| Authentication Scheme | `auth_scheme` | `none`, `bearer`, or `api_key` |
| API Key Header Name | `api_key_header` | Only for `api_key`. Defaults to `X-API-Key`. |
| Verify TLS Certificate | `verify_tls` | Defaults to `true` |
| Column Family | `column_family` | Defaults to `default` |
| Read-Only | `read_only` | Defaults to `true` |
| Key Encoding | `key_encoding` | `utf8` or `base64` |
| Value Encoding | `value_encoding` | `utf8`, `json`, or `base64` |
| Key Prefix Hints | `key_prefix_hints` | One prefix per line, surfaced to the model |
| Max Results | `max_results` | 1–1000, defaults to 100 |
| Max Value Bytes | `max_value_bytes` | 1–1048576, defaults to 32768 |
| Timeout (seconds) | `timeout` | 1–300, defaults to 30 |

The service token is stored in `auth.key` with `auth.type` set to `key`, so it participates in the
existing Key Vault secret storage and masked-edit flows. Actions without authentication use
`auth.type` of `NoAuth`.

### Encodings

Keys and values in RocksDB are byte strings. The configured `key_encoding` and `value_encoding`
are sent with every request so the service knows how to interpret the strings on the wire:

- `utf8` — keys and values are UTF-8 text.
- `base64` — keys and values are base64-encoded bytes, for binary data that cannot travel as text.
- `json` (values only) — the service returns values already parsed as JSON.

Values larger than **Max Value Bytes** are truncated by the plugin so a single record cannot
flood the model context. The result reports the original `value_bytes` alongside a
`value_truncated` flag, so the model can tell a truncated value from a short one.

### Example manifest

```json
{
  "name": "rocksdb_events",
  "displayName": "RocksDB Events",
  "type": "rocksdb",
  "description": "Read-only access to the event key-value store",
  "endpoint": "https://rocksdb.example.com/api",
  "auth": { "type": "key", "key": "service-token" },
  "metadata": { "description": "Event store lookups" },
  "additionalFields": {
    "base_url": "https://rocksdb.example.com/api",
    "auth_scheme": "bearer",
    "verify_tls": true,
    "column_family": "events",
    "key_encoding": "utf8",
    "value_encoding": "json",
    "key_prefix_hints": ["user:", "event:"],
    "read_only": true,
    "max_results": 100,
    "max_value_bytes": 32768,
    "timeout": 30
  }
}
```

## Agent functions

Keys are sorted lexicographically, so prefix and range scans are the efficient access pattern.

### Read functions (always available)

| Function | Purpose |
|---|---|
| `get_value(key, column_family=None)` | Read one value by exact key |
| `get_values(keys, column_family=None)` | Read several values; accepts a list or JSON array string |
| `key_exists(key, column_family=None)` | Cheap existence check that skips the value |
| `scan_prefix(prefix, limit=None, column_family=None)` | List pairs whose keys start with a prefix |
| `scan_range(start_key=None, end_key=None, limit=None, reverse=False, column_family=None)` | Walk an inclusive-start, exclusive-end key range, optionally descending |
| `list_column_families()` | List available column families |
| `get_database_stats()` | Report key-count and size estimates |

### Write functions (require writes to be enabled)

| Function | Purpose |
|---|---|
| `put_value(key, value, column_family=None)` | Write one key-value pair |
| `delete_value(key, column_family=None)` | Delete one key |
| `write_batch(operations, column_family=None)` | Apply put and delete operations atomically |

While the action is read-only, these three functions return an explicit refusal that names the
operation and never issue a request to the service.

`write_batch` accepts a list or a JSON array string:

```json
[
  { "op": "put", "key": "user:005", "value": "erin" },
  { "op": "delete", "key": "user:004" }
]
```

## RocksDB HTTP service contract

Implement these endpoints under the configured base URL. Requests are JSON, responses are JSON
objects. Every request body also carries `key_encoding` and `value_encoding`.

| Function | Method | Path | Request body | Response |
|---|---|---|---|---|
| Health probe | `GET` | `/health` | – | any JSON object |
| `get_value` | `POST` | `/get` | `{key, column_family}` | `{found, value}` |
| `get_values` | `POST` | `/multi_get` | `{keys, column_family}` | `{results: [{key, found, value}]}` |
| `key_exists` | `POST` | `/exists` | `{key, column_family}` | `{exists}` |
| `scan_prefix` / `scan_range` | `POST` | `/scan` | `{prefix?, start_key?, end_key?, limit, reverse, column_family}` | `{items: [{key, value}], truncated?}` |
| `list_column_families` | `GET` | `/column_families` | – | `{column_families: [...]}` |
| `get_database_stats` | `GET` | `/stats` | – | `{stats: {...}}` or a flat object |
| `put_value` | `POST` | `/put` | `{key, value, column_family}` | `{success}` |
| `delete_value` | `POST` | `/delete` | `{key, column_family}` | `{success}` |
| `write_batch` | `POST` | `/batch` | `{operations, column_family}` | `{success}` |

Authentication headers:

- `bearer` sends `Authorization: Bearer <token>`
- `api_key` sends `<api_key_header>: <token>`
- `none` sends no credential header

The **Test RocksDB Connection** button probes `GET /health` and falls back to `POST /scan` with
`{"limit": 1}` when `/health` returns 404, so minimal services still validate.

Range semantics the service should honor:

- `start_key` is **inclusive**, `end_key` is **exclusive**.
- `prefix` and the range bounds are mutually exclusive in practice; the plugin sends only what
  the caller supplied.
- `reverse` walks the range from the highest matching key downwards.
- `limit` is already clamped to the action's **Max Results** before it reaches the service.

## Using the action

1. Open **Workspace → Actions → Create Action** (or the group / admin equivalent).
2. Choose the **RocksDB** action type and continue to the configuration step.
3. Enter the **Service Base URL** for your RocksDB HTTP service.
4. Pick an **Authentication Scheme** and supply the token when using bearer or API key auth.
5. Set the data-handling options: column family, read-only toggle, encodings, key prefix hints,
   and the result, value-size, and timeout caps.
6. Click **Test RocksDB Connection** to verify the configuration before saving.
7. Review the **RocksDB Configuration** summary card and save.

Key prefix hints are surfaced to the model through the action instructions, so listing the
prefixes that organize the keyspace measurably improves how well the agent targets its scans.

## Security considerations

- SimpleChat never opens a RocksDB database directory, so there is no local filesystem exposure
  and no path-traversal surface.
- Service base URLs are restricted to `http` and `https`.
- The connection-test endpoint requires an authenticated user (`@login_required`,
  `@user_required`).
- Service errors report the HTTP status code only; response bodies are never echoed back to the
  browser or the model.
- Writes are off by default and are refused both client-side and server-side while `read_only`
  is true.
- Disable **Verify TLS Certificate** only for trusted internal services using a private
  certificate authority.

## Testing and validation

| Test | Location |
|---|---|
| Manifest validation, write guard, request shaping, auth headers, caps, error handling | `functional_tests/test_rocksdb_plugin.py` |
| Action modal flow, connection test, validation messages, summary card | `ui_tests/test_workspace_rocksdb_action_modal.py` |
| Route registration and auth policy | `functional_tests/route_tests/` |

## Known limitations

- The action depends on a RocksDB HTTP service that you operate; SimpleChat does not ship one.
- The service contract is SimpleChat-defined, so an existing RocksDB proxy will usually need a
  thin adapter.
- Results are capped per call, so very large scans must be paged by the agent using narrower
  prefixes or range bounds.

## Related

- Action type registry: `application/single_app/route_backend_plugins.py`
- Action type definition: `application/single_app/static/json/schemas/rocksdb.definition.json`
- Manifest validation: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- Action modal: `application/single_app/templates/_plugin_modal.html`,
  `application/single_app/static/js/plugin_modal_stepper.js`
- Logging tag: `[ROCKSDB_PLUGIN]` (see `docs/reference/logging-tags.md`)
