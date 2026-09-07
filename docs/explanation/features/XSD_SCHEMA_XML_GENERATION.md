# XSD Schema Ingestion and XML Generation

Implemented in version: **0.250.160**

GitHub issue: [#1212](https://github.com/microsoft/simplechat/issues/1212)

Related `config.py` update: `VERSION = "0.250.160"`

## Overview

SimpleChat supports XML Schema Definition (`.xsd`) files as a distinct document type. An XSD is preserved byte-for-byte in Enhanced Citations storage, represented in AI Search by one bounded metadata summary, and can be selected as the authoritative contract for generated XML.

This design avoids splitting schema declarations into unrelated narrative chunks. It also prevents well-formed but schema-invalid XML from being published as a successful generated artifact.

## Dependencies

- Enhanced Citations and its Blob Storage client
- `lxml==6.1.2`
- `functions_xsd_schema.py` for hardened parsing, closed dependency resolution, schema compilation, generation guidance, and final XML validation
- `functions_documents.py` for XSD ingestion, immutable source storage, revision handling, workspace dependency resolution, and readiness metadata
- Mixed-source Chat and Analyze orchestration for schema selection and evidence isolation
- Existing generated-file artifact storage and authorization controls

## Technical Specifications

### Supported Profile

The implementation uses the named `simplechat-xsd10-subset-profile/1` application profile, backed by the pinned lxml/libxml2 validator. It is intentionally a restricted XSD 1.0 profile, not a claim of complete XSD 1.0 or XSD 1.1 conformance.

The profile fails closed for unsupported or uncertain constructs. It rejects:

- DTDs and entity declarations or references
- XSD 1.1 assertions, alternatives, open content, assertion facets, and conditional-version attributes
- `xs:redefine` and `xs:override`
- locationless imports
- remote, absolute, drive, UNC, query, fragment, encoded-separator, and logical-root-escaping dependency locations

Schemas and XML instances are parsed with entity expansion, DTD loading, network access, and filesystem fallback disabled. Instance `xsi:schemaLocation` hints do not influence validation.

### Ingestion and Storage

XSD upload is available only when Enhanced Citations is enabled and its Blob client is configured. The capability check runs before application-managed document persistence or processing is accepted.

The uploaded bytes are inspected before document creation and stored at an immutable, document-specific Blob path:

```text
{scope_id}/xsd/{logical_path_hash}/{document_id}/{safe_basename}
```

Uploads use non-overwriting Blob semantics. SimpleChat downloads the stored object immediately and verifies its SHA-256 digest and byte length. A failed verification removes only a Blob created by that failed attempt; it never deletes a pre-existing immutable object.

Document metadata records the logical path, source digest and size, Blob ETag, validator/profile identity, target namespace, author-provided schema version, global declarations, dependency declarations, diagnostics, and readiness state.

### Search Representation

Each XSD has exactly one deterministic page-one search chunk. The chunk contains bounded metadata such as:

- logical schema path
- target namespace
- profile and validator identity
- source SHA-256 and byte size
- global element and type names
- direct dependency declarations
- current readiness state

Raw schema text is never split into ordinary narrative chunks. When an XSD is selected for a schema question rather than XML generation, the summary is carried as `source_kind="xml_schema"` so coverage and citations remain distinct from narrative evidence.

### Dependency Resolution

`xs:include` and location-bearing `xs:import` dependencies are resolved only against current XSD documents in the same owning personal, group, or public workspace. Resolution uses normalized logical paths rather than Blob paths or host filesystem paths.

Safe parent-relative locations such as `../common/types.xsd` are allowed only when the normalized result remains inside the logical root. Spaces in `schemaLocation` values must use URI encoding such as `%20`; UTF-8 percent-encoded names are canonicalized before matching. Missing or ambiguous paths fail closed. Imported namespaces must match the dependency's `targetNamespace`; chameleon includes without a target namespace remain supported.

Uploading, replacing, deleting, or promoting a current XSD revalidates direct and transitive dependents. Archived revisions are excluded from dependency discovery.

### Readiness States

XSD ingestion completes with one of these schema-specific states:

| State | Meaning |
|---|---|
| `ready` | The complete same-workspace graph compiled successfully and may govern XML generation. |
| `dependencies_unresolved` | A required dependency is missing or ambiguous. |
| `schema_invalid` | The source is safe XML but violates the supported schema profile or cannot compile. |
| `validation_blocked` | An operational dependency prevented validation from completing. |

Safe but non-ready schemas remain stored and searchable for diagnosis. Only `ready` schemas can govern generated XML.

### Schema-Driven XML Generation

When a user explicitly selects an XSD and requests XML:

1. SimpleChat resolves the selection through the existing authorization-aware source manifest.
2. It reloads and verifies the immutable root and dependency bytes from the owning workspace.
3. The schema graph is compiled in memory with a closed resolver.
4. Schema declarations, excluding annotations, comments, and processing instructions, are provided to the model as an untrusted structural contract.
5. The selected XSD is excluded from ordinary data evidence; selected narrative, XML, tabular, pasted, or other authorized content remains source evidence.
6. Generic XML publishers are suppressed for the request.
7. The model response must be exactly one complete XML document, optionally inside one surrounding code fence; malformed wrappers are not searched for a publishable nested fragment.
8. Immediately before publication, SimpleChat reauthorizes every graph member, reloads the exact sources, and rejects an archived root or any changed dependency graph.
9. The complete final UTF-8 XML artifact bytes are validated against the refreshed graph.
10. The artifact is uploaded only after successful whole-document validation.

The same validation-before-publication rule applies to non-streaming Chat, streaming Chat, agent-backed responses, document Analyze actions, and workflow Analyze execution. Streaming does not expose the model's raw XML payload before validation succeeds.

Without an explicitly selected ready XSD, existing generic XML and tabular export behavior is unchanged.

### Authorization and Citations

Selecting a schema never grants access to its dependencies. Every root and dependency is loaded from the same owning workspace and independently checked against the requester's active scope. When a personal or group root is shared, each dependency must also have an approved share; pending or unapproved shares do not grant schema access. A chat-only temporary source must first be promoted to a workspace document before it can govern generation.

The XSD summary remains discoverable and citable for schema questions. In generation mode, the XSD is recorded as artifact provenance rather than counted as business-data evidence.

## Usage

1. Enable Enhanced Citations and configure its Blob Storage account.
2. Upload the root XSD and any relative includes or imports to the same workspace, preserving their intended logical paths.
3. Wait for the root schema status to become `ready`.
4. Select one root XSD together with any source-data documents.
5. Ask Chat or Analyze to create an XML file from the selected data.
6. Download the artifact shown after schema validation succeeds.

Example:

```text
Use the selected order schema and spreadsheet to create an XML file for these orders.
```

For workflow execution, configure an Analyze task with the XSD and data documents selected together and request XML in the task prompt.

## Testing and Validation

- `functional_tests/test_xsd_schema_profile.py` exercises real lxml parsing, schema compilation, dependency resolution, QName behavior, unsafe XML rejection, closed resolver behavior, summary bounds, source digests, and final-byte validation.
- `functional_tests/test_xsd_ingestion_generation_integration.py` covers exact-source staging, verification cleanup, one-summary indexing, transitive revalidation, feature-flag-independent chat preflight, evidence isolation, and validation-before-upload for Chat and workflows.
- `functional_tests/test_mixed_source_manifest_contracts.py` covers `xml_schema` classification, projections, partitioning, evidence envelopes, and terminal coverage.
- Existing JSON/XML export, tabular export, mixed-source Analyze, workflow sequence, and document access-index suites provide regression coverage for unchanged paths.

## Performance and Limitations

- One explicitly selected root XSD is supported per XML generation request. Dependencies are loaded automatically and do not need separate selection.
- If a root schema declares multiple global elements, the model may use any schema-valid global root. There is no root-choice control yet.
- XSD 1.1, `xs:redefine`, `xs:override`, and locationless imports are not supported.
- Schema compilation and validation use lxml/libxml2 in the application process. This release does not add a separate validator worker or durable multi-artifact generation run.
- Generation guidance is not silently truncated. A schema graph that exceeds the selected model's practical context capacity fails rather than being treated as a partial contract.
- One validated XML artifact is published per request. Multi-root all-or-nothing artifact bundles are not implemented.
- Workflow schema selection currently uses explicitly selected Analyze documents; there is no separate workflow-editor root selector.
- Search uses bounded schema metadata. It does not provide exhaustive free-form search over every raw XSD declaration.
