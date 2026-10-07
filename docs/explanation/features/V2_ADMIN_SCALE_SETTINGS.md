# V2 Admin Scale Settings

## Overview

The V2 Admin Settings surface renders from `admin_settings_fields.py`, a machine-readable
description of every control. Sections with no entry there fall back to scanning the settings
document for `enable_*` booleans, which can only produce switches.

Scale was almost entirely undescribed. Only Cosmos Maintenance declared its two switches, so the
rest of the group was whatever the scan could guess. The Redis connection, both cache TTLs, the
Cosmos resource, and every throughput guardrail were unreachable in V2, and none of the
operational surfaces the server-rendered page offers existed there: Redis health, the Redis
Explorer, document access index status, Cosmos maintenance runs, the throughput console, and
the per-container workbench.

This work describes all seven Scale sections, builds native panels over the existing admin APIs,
enforces the throughput policy rules on the V2 save, and adds two generic schema descriptors.

**Implemented in version:** 0.261.260

**Dependencies:** `admin_settings_nav.py` for section ids; the existing admin APIs under
`/api/admin/settings/redis-monitoring`, `/redis-explorer`, `/app-maintenance`, and
`/cosmos-throughput`; the shared connection-test dispatcher; and the rules and normalizers in
`functions_cosmos_throughput.py`.

## What was missing

| Section | V2 before | V2 after |
| --- | --- | --- |
| Redis Cache | One guessed switch | Connection group, Key Vault-aware key field, connection test, restart notice, "Used by" |
| Redis Metrics | Not rendered | Health and capacity readouts, loaded on first view, and an inline Redis Explorer |
| Conversation Cache | One guessed switch | Switch, TTL, and the last 15 minutes of cache activity |
| DAI Metrics | Guessed switches for flags the server forces on, which reverted on save | Always-on states, backfill, read, and cache metrics; diagnostics behind `enable_dai_debug` |
| Cosmos Maintenance | Two switches | Switches, indexing and cleanup status, and three on-demand runs |
| Cosmos DB Throughput | Not rendered, because none of its keys are named `enable_*` | Console, saved target readout, resource, metrics window, guardrails |
| Cosmos Metrics | Not rendered | Container workbench with per-container policies |

`enable_dai_debug` had also been guessed into Operations > Debug Logging, although neither
interface offers a control for it.

## Technical specifications

### Schema

The seven sections use the existing vocabulary: section capabilities (`role: capability`),
groups, `depends_on` chains copied from the server-rendered page's nesting, `requires` for
cross-section prerequisites, and the `secret` type for `redis_key`. The index diagnostics are
gated on a runtime flag, `{"flag": "dai_debug_enabled", "equals": True}`, which the settings
GET derives from `enable_dai_debug`.

Two descriptors were added for every group:

| Descriptor | Purpose |
| --- | --- |
| `label_variants` | Replaces a field's label and help while a condition holds. `redis_key` reads **Key Vault Secret Name** with Key Vault authentication, as the classic form relabels its one input. Declaring a second field would invent a setting nothing reads. |
| `requires.when` | Limits a prerequisite to one configuration. Redis needs Key Vault secret storage only while its key is read from a vault. |

A `requires.target_section` now also drives a **Used by** line on the target card, built from
the same rules as the prerequisite notices (`buildSectionDependents` reads `collectRequirements`),
so Redis Cache lists exactly the sections that show a Redis notice.

The four always-on index flags and `enable_dai_debug` are in `SUPPRESSED_CAPABILITY_KEYS`.
`cosmos_throughput_container_policies` claims V1's `cosmos_throughput_container_policies_json`
through `LEGACY_FIELD_NAMES`. The schema mirrors three constants from
`functions_cosmos_throughput.py` (10,000 RU/s ceiling, 1,000 RU/s minimum, `SimpleChat`
database), and the parity test compares them.

### Save path

`normalize_admin_settings_updates` gained three Scale rules:

| Rule | Behaviour |
| --- | --- |
| `_validate_redis_port` | Blank, or 1 to 65535, stored as a string because the connection test reads it with `.strip()`. |
| `_normalize_cosmos_container_policies` | Accepts V1's JSON string or the workbench's object. Each policy's automation timestamps are always taken from the stored document, so a page loaded before a scale cannot reset a cooldown. |
| `_check_cosmos_throughput_policy` | Judges the merged state of a save with `collect_cosmos_throughput_policy_errors`, places each error on the setting keys involved, then normalizes the save as V1 does and reports any value it adjusted as a warning. |

`collect_cosmos_throughput_policy_errors` is new in `functions_cosmos_throughput.py`. It returns
each broken rule with its scope, container, rule id, fields, setting keys, and message.
`validate_cosmos_throughput_policy_settings`, which V1 calls, now wraps it and returns the same
messages as before.

### Settings GET

`runtime_flags.dai_debug_enabled` reports `enable_dai_debug`, and the `cosmos_throughput_resource`
status readout names the account and database automation manages, and whether each value comes
from saved settings or App Service settings.

### Browser

| File | Role |
| --- | --- |
| `RedisMonitoringPanel.tsx`, `RedisExplorer.tsx` | Redis health and the read-only key browser, inline in the card |
| `ConversationCacheMetrics.tsx`, `DocumentAccessIndexPanel.tsx`, `CosmosMaintenancePanel.tsx` | The three cards fed by the app maintenance status |
| `CosmosThroughputConsole.tsx`, `CosmosContainerMetrics.tsx`, `CosmosContainerPolicyForm.tsx` | Throughput status and actions, and the container workbench |
| `ConfirmActionModal.tsx`, `CosmosCapacityConfirm.tsx` | The confirmation in front of every change to a production resource |
| `OperationalReadouts.tsx` | Readouts, state pills, toolbars, and messages shared by the cards |
| `scaleFormat.ts`, `scaleRedis.ts`, `scaleMaintenance.ts`, `cosmosThroughput.ts` | Formatting, status wording, and the rules mirrored from Python |
| `stores/scaleStatusStore.ts` | Status shared between cards: one maintenance read feeds three cards, and one throughput status feeds two |

Status loads when a card first scrolls into view, not with the page. Collections are browsed
inline, list beside detail, as the Model Catalog does; a modal is used only to confirm an action
that changes a production resource.

The browser mirrors two server computations so it can explain a change before sending it: the
policy rules a save must pass, and the RU/s a manual scale will land on. The server stays
authoritative for both, and the mirrors are tested against cases generated from the Python
implementation.

Two guards keep a confirmed change from being repeated or misdescribed. A capacity change stays
busy until the status has been read again, so the dialog cannot send a second step from the
capacity the first one replaced. **Validate access** keeps what it read with its result instead
of replacing the shared status, because it reads the values on screen and may describe a draft
target; manual changes always estimate from the saved target's status. The classic page shows
the validation's status in its status panel.

### APIs

No routes were added. The V2 panels call the admin APIs the server-rendered page uses, with the
same request bodies.

| API | Used by |
| --- | --- |
| `GET /api/admin/settings/redis-monitoring/status` | Redis Metrics |
| `GET /api/admin/settings/redis-explorer/keys`, `POST .../value` | Redis Explorer |
| `GET /api/admin/settings/app-maintenance/status` | Conversation Cache, DAI Metrics, Cosmos Maintenance |
| `POST /api/admin/settings/app-maintenance/run` | DAI Metrics, Cosmos Maintenance |
| `GET /api/admin/settings/cosmos-throughput/status` | Cosmos DB Throughput, Cosmos Metrics |
| `POST /api/admin/settings/cosmos-throughput/validate-access`, `/scale`, `/convert-autoscale` | Cosmos DB Throughput, Cosmos Metrics |
| `POST /api/v2/admin/settings/test-connection` (`test_type: redis`) | Redis Cache |

## Usage

Open **Admin Settings > Scale**. The group has two tabs, **Redis & Caching** and **Cosmos**.

- **Redis.** Enable Redis Cache, open **Connection**, and enter the host name and how
  SimpleChat signs in. **Test Redis connection** checks the values on screen before saving.
  Changing Redis needs a coordinated restart of every worker and the scheduler.
- **Index diagnostics.** Set `enable_dai_debug` to true in the settings document. DAI Metrics
  then shows shadow validation, batch sizes, the list cache settings, and the backfill actions.
- **Throughput.** Leave the resource blank to use App Service settings, or fill it in, and use
  **Validate access** before turning on automation. **Scale up**, **Scale down**, and **Convert
  to autoscale** confirm the change first and use the saved policy.
- **Container policies.** In Cosmos Metrics select a container, edit its policy, and save the
  page. The form starts from the values that govern the container, including inherited ones.

The admin documentation for the group is `docs/admin/scale.md`.

## Testing and validation

| Test | Coverage |
| --- | --- |
| `functional_tests/test_v2_admin_scale_parity.py` | Panes match navigation; every V1 field is claimed and none invented; secret, selects, number bounds, and port range match V1; dependency chains; diagnostics follow the debug flag; always-on flags stay uneditable; defaults and mirrored constants; routes, methods, and maintenance request bodies match V1; the GET sends the debug flag and readout |
| `functional_tests/test_v2_admin_scale_normalization.py` | Port storage, selects and secret round trip, bounds, every policy rule against V1's messages, partial saves, automation off, RU/s rounding warnings, both policy shapes, stored timestamps, unrelated saves |
| `functional_tests/test_v2_admin_scale_logic.py` with `.ts` | Generates rounding, validation, container policy, and manual scale cases from the Python functions and requires the browser mirrors to agree; label variants, conditional prerequisites, "Used by", status wording, sorting, actions, formatting |
| `ui_tests/test_v2_admin_scale_settings.py` | Key Vault relabelling and prerequisite, lazy metrics, explorer paging and errors, connection test refresh, diagnostics gate, confirmations and request bodies, validate access with draft values, scale confirmation, workbench edit and save, enforced policy, no overflow at phone and desktop widths in both themes |

`test_v2_admin_capability_placement.py` now treats Scale as fully described, and
`test_v2_admin_schema_vocabulary.py` checks `label_variants` and `requires.when`.

### Known limitations

- Cache activity counters are counted per app worker. Application Insights remains the
  fleet-wide record.
- A manual scale's target is an estimate from saved settings. The server computes the real
  target and its result is reported after the change.
- The Key Vault secret name is held in the `redis_key` secret, so V2 shows it as stored rather
  than in a password box as V1 does.
- `enable_search_result_caching` has no control on the server-rendered page, and the V2 fallback
  scan still places its switch with Web Search under Knowledge.
