# Data Management Source Blob Backup Throughput

Implemented in version: **0.250.102**

GitHub issue: [#1095](https://github.com/microsoft/simplechat/issues/1095)

## Overview

Data Management source-blob backups transfer Enhanced Citations files through
bounded Azure SDK blocks instead of downloading whole blobs with `readall()` or
copying every file serially. The worker preserves durable per-file outcomes,
optional backup encryption, source-version safety, cooperative cancellation,
and restart-safe target verification while allowing several files to transfer
concurrently.

## Transport Evaluation

| Candidate | Strengths | SimpleChat constraints | Decision |
|---|---|---|---|
| AzCopy | High aggregate throughput and mature transfer scheduling | Requires an additional platform-specific executable and deployment lifecycle. It cannot apply SimpleChat's framed Fernet backup encryption. Supplying source and destination authorization safely also varies by hosting platform. | Available in the operator benchmark harness, but not bundled or invoked by the application. |
| Blob server-side copy | Keeps unencrypted bytes off App Service and can be the fastest compatible cross-account path | The target storage service must be able to authorize the source URL. Existing managed-identity and connection-string configurations do not universally provide a delegated source URL. It cannot apply SimpleChat backup encryption. | Available in the benchmark harness when the operator supplies service-authorizable source access; not selected as the universal runtime path. |
| Azure SDK bounded block transfer | Works with the application's existing managed-identity and connection-string clients, supports conditional source reads, target verification, cancellation, durable retry, and application encryption | Bytes pass through App Service, so concurrency and chunk size must remain bounded. | Selected for encrypted and unencrypted application backups. |

The selected path prioritizes a safe transport that works for every currently
supported SimpleChat authentication and encryption mode. The benchmark harness
keeps faster environment-specific alternatives measurable without silently
weakening encryption or requiring source SAS delegation in production.

## Technical Specifications

### Bounded Transfer Pipeline

- The immutable job plan records concurrent blob transfers, chunk size, retry
  attempts, and adaptive recovery behavior.
- Defaults are four file transfers with 8 MiB source chunks. Admin bounds are
  one to eight transfers and 1 to 16 MiB chunks, so default application
  buffering is approximately 32 MiB plus encryption and Azure SDK overhead.
- Each file uses ETag-conditional range downloads and deterministic staged
  blocks. No source file is loaded into memory as a whole.
- Worker threads perform Blob operations only. The lease-owning coordinator
  writes manifests, latest-item state, job progress, and resource checkpoints.
- `408`, `409`, `412`, `429`, `5xx`, Azure transport failures, and timeouts use
  bounded exponential retry with jitter and service `Retry-After` guidance.
- `429` and `503` responses reduce active file concurrency. Three clean
  transfers restore one slot until the immutable limit is reached.

### Encryption Format

Encrypted source artifacts use `fernet-chunked-v1`:

1. The first block starts with the ASCII magic value `SCBF1` and a newline.
2. Every frame contains a four-byte big-endian Fernet token length.
3. The authenticated token payload contains a SHA-256 binding to the source
   version, the chunk index, total chunk count, a final-chunk flag, and the
   plaintext chunk.

This format preserves bounded memory and authenticates content, source binding,
ordering, completeness, and finality. Empty encrypted files contain one
authenticated empty frame. Unencrypted artifacts use `raw-v1`.

### Durable Resume and Fencing

- Target metadata records pending or succeeded state, job and attempt identity,
  lease generation, source version and length, and transfer format.
- Block IDs include a transfer-generation identity so concurrent attempts
  cannot mix staged blocks from different source versions.
- Final commit uses target ETag or missing-target conditions. A stale attempt
  cannot overwrite a newer commit, and seeing a newer lease generation stops
  the stale worker.
- A succeeded target is reused only when job, source version, source length,
  format, and generation rules verify. Uploaded-but-not-yet-checkpointed work is
  therefore recovered without a duplicate target artifact.
- Each durable manifest outcome records hashed source identity, source ETag,
  Last-Modified value, source and artifact bytes, target path and ETag, status,
  retries, throttles, transfer format, job attempt, and lease generation.
- One unreadable or exhausted file becomes a sanitized failed outcome while
  independent files continue. Enumeration failure remains resource-fatal
  because a complete manifest cannot then be established.

### Progress

Per-container and aggregate progress includes source reads, completed/reused,
skipped and failed files, source and artifact bytes, retries, throttles, retry
delay, configured and active concurrency, chunk size, in-flight count, elapsed
time, bytes per second, hashed current-file identity, and last durable
checkpoint. Public progress never includes source content, account keys,
connection strings, SAS query strings, or raw token-bearing provider errors.

## Configuration and Usage

Open **Admin Settings > Data Management > Source Blob Backup Performance**:

- **Concurrent blob transfers**: 1-8; default 4.
- **Transfer chunk size (MiB)**: 1-16; default 8.
- **Blob retry attempts**: 1-10; default 5.

Settings are captured when a job is queued. Retry/Resume uses that immutable
plan rather than current admin values.

## Reproducible Azure Benchmark

The operator-run harness is
`functional_tests/benchmark_data_management_blob_backup.py`. It never writes
container URLs, endpoints, SAS values, source names, or exception messages to
its report. Run it only in an approved Azure environment; benchmark target
artifacts remain under a unique `simplechat-blob-benchmark/` prefix for operator
verification and cleanup.

### Managed Identity SDK Comparison

Assign the executing identity source Blob Data Reader and target Blob Data
Contributor, then set container URLs without SAS query strings:

```powershell
$env:SIMPLECHAT_BLOB_BENCHMARK_AUTHENTICATION = "managed_identity"
$env:SIMPLECHAT_BLOB_BENCHMARK_SOURCE_CONTAINER_URL = "https://<source>.blob.core.windows.net/<container>"
$env:SIMPLECHAT_BLOB_BENCHMARK_TARGET_CONTAINER_URL = "https://<target>.blob.core.windows.net/<container>"
$env:SIMPLECHAT_BLOB_BENCHMARK_ENVIRONMENT = "approved-azure-test"
python functional_tests\benchmark_data_management_blob_backup.py --candidate sdk --parallelism 4 --chunk-size-mib 8 --output blob-benchmark-sdk.json
python functional_tests\benchmark_data_management_blob_backup.py --candidate sdk --parallelism 4 --chunk-size-mib 8 --encrypted --output blob-benchmark-sdk-encrypted.json
```

The SDK run records both the serial baseline and bounded parallel result.
Every completed candidate reports source bytes, artifact bytes, blob count,
elapsed time, and bytes per second. Server-side copy and AzCopy additionally
verify target count and length before the harness records completion.

### Optional Candidate Comparison

Server-side copy requires source authorization that the target storage service
can use. Configure SAS values only through the secure process environment and
never commit them:

```powershell
$env:SIMPLECHAT_BLOB_BENCHMARK_AUTHENTICATION = "sas"
$env:SIMPLECHAT_BLOB_BENCHMARK_SOURCE_CONTAINER_URL = "https://<source>.blob.core.windows.net/<container>?<sas>"
$env:SIMPLECHAT_BLOB_BENCHMARK_TARGET_CONTAINER_URL = "https://<target>.blob.core.windows.net/<container>?<sas>"
python functional_tests\benchmark_data_management_blob_backup.py --candidate server-copy --parallelism 4 --chunk-size-mib 8 --output blob-benchmark-server-copy.json
```

Encrypted runs intentionally mark server-side copy and AzCopy incompatible
because neither candidate can apply the SimpleChat encryption format.

AzCopy benchmark URLs must not contain SAS query strings because command
arguments are visible to local process inspection. Configure AzCopy managed
identity login for the approved host and use query-free container URLs:

```powershell
$env:SIMPLECHAT_BLOB_BENCHMARK_AUTHENTICATION = "managed_identity"
$env:SIMPLECHAT_BLOB_BENCHMARK_SOURCE_CONTAINER_URL = "https://<source>.blob.core.windows.net/<container>"
$env:SIMPLECHAT_BLOB_BENCHMARK_TARGET_CONTAINER_URL = "https://<target>.blob.core.windows.net/<container>"
$env:SIMPLECHAT_BLOB_BENCHMARK_AZCOPY = "C:\approved-tools\azcopy.exe"
$env:AZCOPY_AUTO_LOGIN_TYPE = "MSI"
python functional_tests\benchmark_data_management_blob_backup.py --candidate azcopy --output blob-benchmark-azcopy.json
```

### Representative 50 GB Evidence

The default harness threshold is 50 GiB. It refuses smaller source sets unless
`--allow-smaller` is supplied for harness validation. Record these environment
facts alongside the generated secret-free JSON:

- App Service or runner SKU, region, operating system, and Python version.
- Source and target account regions, redundancy type, network path, and
  private-endpoint configuration.
- Blob count and size distribution.
- Authentication mode, encryption mode, parallelism, and chunk size.
- Serial and bounded elapsed time and bytes per second.
- Any observed storage throttling.

Throughput is environment-specific and is not a universal SimpleChat guarantee.
This repository does not contain fabricated 50 GiB results. Release evidence
must attach the JSON generated in the approved operator environment and show a
material elapsed-time improvement over that environment's serial baseline.

## Testing and Validation

- `functional_tests/test_data_management_blob_backup_transfers.py`
- `functional_tests/test_data_management_backup_durability.py`
- `functional_tests/test_data_management_security_patterns.py`
- `ui_tests/test_admin_data_management_settings_ui.py`

Focused coverage validates chunk bounds, concurrent file limits, authenticated
encrypted framing, verified target reuse, source mutation, target-generation
fencing, Retry-After pressure, adaptive concurrency, isolated setup and transfer
failures, cancellation, durable manifests, and secret-safe failure summaries.

## Limitations

- The application does not bundle AzCopy or generate source SAS credentials.
- Server-side copy remains an operator benchmark candidate, not an automatic
  production fallback.
- The application supports files up to the configured 50,000-block limit at the
  maximum 16 MiB chunk size. A larger individual file is failed explicitly
  rather than exceeding the configured memory bound.
- Live 50 GiB results require an operator-provided Azure environment and are not
  produced by local functional tests.
