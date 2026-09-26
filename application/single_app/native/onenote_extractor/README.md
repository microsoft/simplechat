# SimpleChat native OneNote extractor

Helper version: **0.1.0**. Protocol version: **1**.
Implemented in SimpleChat version: **0.261.045** (`application/single_app/config.py`).
Parser revision: `d0d3330f9674f07903664329f50434d997eced8c`.

This offline worker extracts visible typed text and table values from a `.one`
section or an entire CAB-based `.onepkg`. It does not perform OCR, recognize
handwriting, ingest embedded files, render HTML, contact Microsoft Graph, or
convert notebooks through an installed OneNote application.

## Build and validate

Use Rust **1.85.1** or a compatible newer toolchain:

```text
cargo test --locked --all-targets
cargo fmt --all --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
```

The executable is `target/release/simplechat-onenote-extractor` (with `.exe` on
Windows). `CARGO_TARGET_DIR` can place build output outside the source checkout.
Production needs only the executable, its platform C runtime, and the notices
and corresponding covered source described in `THIRD_PARTY_NOTICES.txt`. Cargo and
network access are build-time requirements, not runtime requirements.

## Command contract

Pass an absolute input filename, with a case-insensitive `.one` or `.onepkg`
extension, optionally followed by the original upload's friendly basename:

```text
simplechat-onenote-extractor ABSOLUTE_INPUT [ORIGINAL_FILENAME]
```

One-argument calls remain supported. `ORIGINAL_FILENAME` must be a nonempty
basename of at most 1,024 Unicode scalar values, including a suffix matching
the input type. Directory separators, drive/URI colons, and control characters
are rejected. Invalid labels return `invalid_file`; oversized labels return
`limit_exceeded`. The label is never opened, resolved, or used as a filesystem
lookup. For `.one`, the parser's buffer API uses it only when stored section
display-name metadata is absent; genuine metadata is not guessed or replaced.
The suffix is normalized case-insensitively before the parser applies its usual
`.one` display-name trimming. Without a label, missing metadata uses the fixed
fallback `section`, never the temporary input filename. For `.onepkg`, an
optional valid original basename is accepted but ignored; hierarchy comes
entirely from the package.

A relative input path, more than two arguments, or an unsupported suffix fails.
`--version` prints a static single-line helper/protocol/parser identity.
It accepts no second argument.
There are no environment or command-line limit overrides.

A successful invocation exits **0** and writes one JSON object to stdout:

```json
{
  "protocol_version": 1,
  "parser_revision": "d0d3330f9674f07903664329f50434d997eced8c",
  "sections": 1,
  "source_pages": 1,
  "pages": [{
    "section_path": ["Group", "Section"],
    "id": "{page-guid}",
    "title": "Visible page title",
    "level": 1,
    "text": "Visible text\nCell A\tCell B"
  }],
  "excluded_content": {
    "images": 0, "ink": 0, "attachments": 0, "empty_pages": 0
  }
}
```

`source_pages` equals the length of `pages`, including blank pages. Empty valid
sections count toward `sections`; they do not manufacture pages. If the entire
input has no visible text, the result is `no_text`, not a success-shaped empty
fallback. A title-only page retains its visible title as text. Page titles come
from the first title outline, not generated date/time title decorations or the
parser's heuristic title fallback.

Section paths omit the package's notebook-root directory and preserve the
validated archive's actual group/section names. `.one` suffixes are removed
from section names. Standalone sections use the parsed section display name.
Level is the positive source page nesting level.

Hidden rich-text runs are removed using their UTF-16 run boundaries and hidden
styles, never by searching for marker strings. Malformed or ambiguous run
metadata fails closed. Unicode is preserved; line endings and whitespace
controls are normalized. Table columns use tabs and rows use newlines;
multiline, tab-containing, or quoted cells use TSV-style quoting. Plain typed
math text is retained, but structural math objects without a supported plain
text representation and unknown content types fail as unsupported.
Mixed inline ink/text that the upstream API cannot expose without losing typed
runs fails as incomplete rather than silently omitting those runs.

Exclusion counts are object counts, not pixel, stroke, or byte counts.
Attachment counts include ignored non-notebook CAB members outside the recycle
bin. Cached OCR/recognized handwriting and media metadata are never emitted.

An ordinary failure exits **2**, writes no stderr, and emits only:

```json
{"protocol_version":1,"error":{"code":"invalid_file"}}
```

The finite error codes are `invalid_file`, `unsupported_file`, `encrypted_file`,
`unsafe_package`, `limit_exceeded`, `incomplete_notebook`, `no_text`, and
`extraction_failed`. No diagnostic, source path, title, or input text appears in
failure output. The pinned parser sometimes cannot distinguish encryption
from corruption; its explicit encryption-or-corruption error is classified as
`encrypted_file`. Other unreadable sections still fail closed.

## Compiled safety policy

| Resource | Maximum |
|---|---:|
| Input file | 128 MiB |
| Expanded individual CAB member | 128 MiB |
| Total expanded CAB bytes, including gaps/ignored data | 256 MiB |
| CAB members / compression folders | 1,024 each |
| CAB data blocks | 65,536 |
| Archive path components, content depth, page level | 16 |
| Pages | 10,000 |
| Normalized body and title bytes combined | 16 MiB |
| Serialized stdout | 32 MiB |
| Title | 4,096 Unicode scalar values |
| Path component | 1,024 Unicode scalar values |
| Worker memory | 1 GiB |
| Worker CPU | 120 seconds |

The application must additionally enforce its 150-second wall deadline and
bound subprocess output. Limits cannot be loosened by notebook metadata.
Lower inherited OS limits remain in force.

On Linux, resource limits and disabled core dumps are applied before parsing.
A single-threaded native supervisor forks a worker with a private result pipe.
The worker's ordinary stdout/stderr are redirected away from the protocol,
including an upstream malformed-file diagnostic. Panics become failures.
Memory/CPU/stack termination becomes a bounded error, never partial JSON.
The worker is killed if its supervisor dies. The Python caller does not need a
thread-unsafe `preexec_fn`.

Windows uses a process job with memory/CPU limits and disabled unhandled-error
dialogs, and suppresses parser diagnostic streams. Job assignment failure is a
hard error. OS-enforced Windows termination still needs normalization by the
calling application; the Linux crash-normalizing supervisor is not available
on Windows. Other platforms fail closed rather than running without limits.

## Package completeness

The helper never calls the upstream `parse_package` or `PackageStore`. It
preflights the raw CAB header, counts, paths, compression, member ranges, and
block expansion before passing a synthetic safe directory to `cab` 0.6.0.
Uncompressed, MSZIP, and LZX cabinets are supported; multipart cabinets and
other compression are rejected. Each selected compression folder is decoded
only once. Only `.one`/`.onetoc2` payloads are retained in memory. Attachments
sharing a compression stream may be decoded into a fixed-size discard buffer,
but are never interpreted, written to disk, or opened as files.

Paths must be relative UTF-8 names without traversal, control characters,
Windows drive/UNC/stream syntax, reserved device names, trailing dots/spaces,
or case-folded file/directory collisions. Non-UTF-8 legacy CAB names are rejected
rather than decoded lossily. Exactly one unambiguous root TOC is required, and
each active section-group directory must have exactly one TOC. Metadata cannot
skip group manifests by referring directly to a deep descendant.

The parser sees only a read-only memory filesystem. Missing required accesses,
denied paths, duplicate/recursive opens, unvisited or unsuccessfully returned
active TOCs, and discrepancies
between the archive section inventory and returned sections fail the whole
notebook. This detects failures hidden by the upstream nested warning behavior.
Only exact `OneNote_RecycleBin` directories are excluded. Unknown warnings fail;
only fixed warnings about deliberately excluded media/recognition are allowed.

## Test data and privacy

Native tests cover visible Unicode/hidden runs, tables, malformed input, CAB
safety, strict VFS coverage, nested failures, protocol errors, and bounded output.
Public OneNote fixture provenance is in `tests/fixtures/SOURCES.txt`.
Generated CAB test containers are not represented as desktop exports.
Private real notebook acceptance tests must run separately, read-only, without
network access, and report counts or equality checks only. Never add private
notebooks or their extracted contents to this crate, fixtures, or build context.
