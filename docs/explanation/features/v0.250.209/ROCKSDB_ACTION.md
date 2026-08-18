# RocksDB Action

Implemented in version: **0.250.209**

Version reference: `application/single_app/config.py` was updated to `VERSION = "0.250.209"` for this feature.

Dependencies: `rocksdict` (embedded mode only, imported lazily), `requests` for remote mode, Semantic Kernel action loading, and Key Vault action secret handling.

## Overview

The RocksDB action lets an agent read (and optionally write) an ordered
[RocksDB](https://github.com/facebook/rocksdb) key-value store from a SimpleChat conversation.

RocksDB is an embedded C++ library rather than a network database server, so the action supports
two connection modes:

| Mode | What it does |
|---|---|
| **Embedded** | Opens a RocksDB database directory on the application host through the `rocksdict` binding. |
| **Remote** | Calls a RocksDB-backed HTTP/JSON service that implements the contract below. |

Reads are always available. Writes are refused unless the action is explicitly configured to
allow them, matching the read-only default of the SQL action.

- **Action type**: `rocksdb`
- **Implemented in version**: **0.250.209**
- **Plugin module**: `application/single_app/semantic_kernel_plugins/rocksdb_plugin.py`
- **Dependencies**: `rocksdict==0.3.29` (embedded mode only, imported lazily)

## Architecture

```
Agent
  └── RocksDbPlugin (semantic_kernel_plugins/rocksdb_plugin.py)
        ├── Embedded mode ── rocksdict.Rdict ── RocksDB directory on disk
        │                      (read-only | secondary | read-write)
        └── Remote mode ───── requests ─────── RocksDB HTTP/JSON service
```

The plugin is discovered automatically by `discover_plugins()` and `get_plugin_types()` because it
lives in `semantic_kernel_plugins/` and its filename ends with `_plugin.py`.

### Why the binding is imported lazily

`rocksdict` ships as a compiled wheel. It is imported inside the embedded code path only, so a
container image without the wheel still starts normally, still lists the RocksDB action type, and
still supports remote mode. Embedded calls then fail with an explicit "install rocksdict" message
instead of breaking action discovery.

## Configuration

### Enabling embedded mode

Embedded mode is **disabled by default**. An administrator must set the `ROCKSDB_ALLOWED_ROOTS`
environment variable to the directories that RocksDB actions may open, separated by the platform
path separator (`:` on Linux, `;` on Windows):

```bash
# Linux / container
ROCKSDB_ALLOWED_ROOTS=/mnt/rocksdb:/data/analytics
```

Every configured database path is resolved with `os.path.realpath` and must sit inside one of the
allowed roots. This defeats `..` traversal, symlink escapes, and sibling directories that merely
share a name prefix. When the variable is empty, embedded connections are rejected outright.

Remote mode does not depend on this variable.

### Access modes (embedded)

| Access mode | When to use it |
|---|---|
| **Read-only** | The database has no live writer. RocksDB cannot open a read-only handle while another process holds the directory `LOCK`. |
| **Secondary** | The database has a live primary writer. RocksDB follows the primary and needs a writable scratch directory (**Secondary Path**). |

Setting **Read-Only** to *No (Allow writes)* opens the database read-write, which requires exclusive
access to the directory. Secondary access and writes are mutually exclusive, and the action modal
hides the access-mode controls once writes are enabled.

### Configuration fields

| Field | `additionalFields` key | Applies to | Notes |
|---|---|---|---|
| Connection Mode | `connection_mode` | both | `embedded` or `remote` |
| Database Path | `db_path` | embedded | Must resolve inside `ROCKSDB_ALLOWED_ROOTS` |
| Access Mode | `access_mode` | embedded | `read_only` or `secondary` |
| Secondary Path | `secondary_path` | embedded | Required for `secondary` |
| Service Base URL | `base_url` | remote | `http` or `https` only |
| Authentication Scheme | `auth_scheme` | remote | `none`, `bearer`, or `api_key` |
| API Key Header Name | `api_key_header` | remote | Defaults to `X-API-Key` |
| Verify TLS Certificate | `verify_tls` | remote | Defaults to `true` |
| Column Family | `column_family` | both | Defaults to `default` |
| Read-Only | `read_only` | both | Defaults to `true` |
| Key Encoding | `key_encoding` | both | `utf8` or `base64` |
| Value Encoding | `value_encoding` | both | `utf8`, `json`, or `base64` |
| Key Prefix Hints | `key_prefix_hints` | both | One prefix per line, shown to the model |
| Max Results | `max_results` | both | 1–1000, defaults to 100 |
| Max Value Bytes | `max_value_bytes` | both | 1–1048576, defaults to 32768 |
| Timeout (seconds) | `timeout` | both | 1–300, defaults to 30 |

The remote service token is stored in `auth.key` with `auth.type` set to `key`, so it participates
in the existing Key Vault secret storage and masked-edit flows. Embedded actions and remote actions
without authentication use `auth.type` of `NoAuth`.

### Encodings

The database is opened in RocksDB **raw mode**, so keys and values are byte strings. This means
databases written by C++, Java, Go, or any other language are readable — the plugin does not assume
Python pickle payloads.

- `utf8` decodes bytes as UTF-8 text, replacing invalid sequences.
- `base64` exposes binary keys and values as base64 strings in both directions.
- `json` (values only) parses the value as JSON, falling back to text when parsing fails.

Values longer than **Max Value Bytes** are truncated. The result reports the original
`value_bytes` alongside a `value_truncated` flag, so the model can tell a truncated value from a
short one.

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
    "connection_mode": "remote",
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
operation and never reach the database or the remote service.

`write_batch` accepts a list or a JSON array string:

```json
[
  { "op": "put", "key": "user:005", "value": "erin" },
  { "op": "delete", "key": "user:004" }
]
```

## Remote HTTP service contract

Implement these endpoints under the configured base URL. Requests are JSON, responses are JSON
objects.

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

The **Test RocksDB Connection** button probes `GET /health` and falls back to
`POST /scan` with `{"limit": 1}` when `/health` returns 404, so minimal services still validate.

## Using the action

1. Open **Workspace → Actions → Create Action** (or the group / admin equivalent).
2. Choose the **RocksDB** action type and continue to the configuration step.
3. Pick a **Connection Mode**.
   - *Embedded*: enter the database path, choose Read-only or Secondary access, and add a
     secondary path when following a live primary.
   - *Remote*: enter the service base URL, choose an authentication scheme, and supply the token.
4. Set the data-handling options: column family, read-only toggle, encodings, key prefix hints,
   and the result, value-size, and timeout caps.
5. Click **Test RocksDB Connection** to verify the configuration before saving.
6. Review the **RocksDB Configuration** summary card and save.

Key prefix hints are surfaced to the model through the action instructions, so listing the prefixes
that organize the keyspace measurably improves how well the agent targets its scans.

## Security considerations

- Embedded paths are constrained by `ROCKSDB_ALLOWED_ROOTS` and validated with realpath plus a
  common-prefix check, so a configured path cannot escape the allowlist.
- The connection-test endpoint requires an authenticated user (`@login_required`, `@user_required`)
  and returns sanitized errors that do not expose filesystem layout or raw driver text.
- Remote base URLs are restricted to `http` and `https`.
- Remote service errors report the HTTP status code only; response bodies are never echoed back to
  the browser or the model.
- Writes are off by default and are refused client-side and server-side while `read_only` is true.

## Testing and validation

| Test | Location |
|---|---|
| Plugin behavior, allowlist, encodings, remote shaping | `functional_tests/test_rocksdb_plugin.py` |
| Action modal flows, connection test, summary card | `ui_tests/test_workspace_rocksdb_action_modal.py` |
| Route registration and auth policy | `functional_tests/route_tests/` |

The functional test exercises a real embedded RocksDB database when `rocksdict` is installed and
skips that case gracefully when it is not.

## Known limitations

- Read-only access cannot open a database whose `LOCK` is held by a running writer; use secondary
  access for live databases.
- Secondary access is read-only by definition and cannot be combined with writes.
- Merge operators and custom comparators are not supported by the underlying `rocksdict` binding.
- Embedded mode reads from the application host's filesystem, so the database must be present in
  the container image or on a mounted volume.

## Related

- Action type registry: `application/single_app/route_backend_plugins.py`
- Action type definition: `application/single_app/static/json/schemas/rocksdb.definition.json`
- Manifest validation: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- Action modal: `application/single_app/templates/_plugin_modal.html`,
  `application/single_app/static/js/plugin_modal_stepper.js`
- Logging tag: `[ROCKSDB_PLUGIN]` (see `docs/reference/logging-tags.md`)
