# Orchestration deliverables

**Version: 0.261.139** (tracked in `application/single_app/config.py`)

**Implemented in version: 0.261.138**

## Overview

An orchestrated request is often a request to *receive* something: a CSV file, a Word
report, or an image of each person a report describes. Before this change, nothing in a
plan represented what the user asked to receive. A planner could title a step "Create
state-capital CSV" and then write the rows into the chat, describe a "Word-ready" report
with `[Insert Image here]` placeholders, or note in its assumptions that a file "cannot be
created" and run anyway.

A Gather / Reason / Render plan now lists its **deliverables** before its steps, and the
server checks that list against what it can actually produce:

- Every deliverable the user asked for is either produced by a step whose capability can
  produce it, or shown as unavailable with a reason the server itself reports.
- Nothing is silently downgraded. A file is a file from `render_file`, never text in the
  chat, and an explicitly requested image is generated, not replaced by a proposal card or
  a placeholder.
- The checks compare structured plan data with server state. No keyword in the request,
  step titles, or assumptions is read.

Images the user explicitly asked for are generated as planned `generate_image` steps.
Approving the plan (or the explicit ask, in Run automatically mode) is the consent to
generate them. They appear inline in the answer and are embedded in DOCX, PDF, and PPTX
files. Images the planner only suggests remain `simpleimage` proposal cards the user
approves one at a time.

## Dependencies

- Chat orchestration (`enable_chat_orchestration`). New plans use Gather / Reason / Render; plans created by an earlier orchestration version are not opened or rerun.
- File deliverables need the `render_file` capability and the shared export catalog.
- Generated images need `enable_image_generation` and a configured image model that the
  image service projection reports as supported. Orchestration grants no new access: the
  run's owner must own the conversation, and the image model's own option limits apply.
- No new setting. The per-plan image budget is the constant
  `MAX_GENERATED_IMAGES_PER_PLAN` (4) in `functions_orchestration_registry.py`.

## Technical specifications

### The plan field

`deliverables` is a plan-level list, filled by the planner before its steps:

| Field | Meaning |
| --- | --- |
| `id` | A name of letters, digits, `_` or `-`, starting with a letter. Unique in the plan. |
| `kind` | `answer`, `file`, `image`, `chart`, or `diagram`. |
| `format` | For a file only: a format id from the export catalog (`csv`, `xlsx`, `docx`, `pdf`, `pptx`, `json`, `md`, ...). Catalog aliases such as `yml` are normalized. |
| `requested` | `explicit` when the user asked for it, including through the Image control; `suggested` when the planner added it. |
| `quantity` | Optional count of files or images, such as 3 for "an image of each of the first three presidents". |
| `description` | A short description, shown to the user. |
| `status` | `planned` or `unavailable`. |
| `unavailable_reason` | Required when unavailable: one closed reason code (below). |

Steps name the deliverables they produce in `delivers: [ids]`. The server adds two fields
of its own: `unavailable_message`, the application-owned text for an unavailable reason,
and `implicit`, which marks the answer deliverable the server adds to a plan that declared
none. Each answer-writing step also receives a derived `deliverable_context`, described
under Execution.

### Server truth

`plan_request` adds `capability_availability.deliverables` to the planner context. It is
built by `build_deliverable_availability` from the same capability resolution the planner
is shown, so the two cannot disagree:

- `answer`, `chart`, `diagram`: whether they can be produced, and by which capabilities.
- `file`: whether `render_file` is available, and for every catalog format its status,
  reason, profiles, accepted prepared-content kinds, and whether it embeds images.
- `image.explicit`: whether `generate_image` is available, its per-plan budget, and the
  sizes, qualities, and backgrounds the configured model accepts.
- `image.suggested`: whether proposal cards are available.
- `unavailable_reasons`: the closed reason codes and their messages.
- `facts`: that only `render_file` creates a file, that web search, URL reading, and deep
  research return text and links only and cannot retrieve images, that generated images are
  AI illustrations to be labelled as such (especially for real people and historical
  figures), and that proposal cards need the user's approval and so never appear in a file.
- `recipes`: records-v1 with explicit columns into CSV or XLSX; a markdown-v1 document into
  DOCX or PDF; the prepared slide deck into PPTX; one `generate_image` step per requested
  image, bound to the step that places it; and a chart of the rows an action retrieves.

| Reason code | When the server reports it |
| --- | --- |
| `capability_not_enabled_for_orchestration` | The administrator's orchestration allowlist excludes the producing capability. |
| `file_rendering_unavailable` | `render_file` or its rendering service is unavailable for this request. |
| `format_not_admitted` | The format is known but not in the export catalog admitted for this plan. |
| `format_not_supported` | No SimpleChat renderer exists for the format. |
| `image_generation_disabled` | `enable_image_generation` is off. |
| `image_generation_unavailable` | Image generation is on, but the configured image model cannot generate images. |
| `image_budget_exceeded` | The plan already generates the maximum number of images. |

### Validation

`compile_deliverables` in `functions_orchestration_deliverables.py` runs inside
`validate_dependency_plan` for every Gather / Reason / Render plan:

- `delivers` may reference only declared deliverables, and an unavailable deliverable may
  not be delivered by any step.
- A step's capability must be able to produce what it delivers:
  - a file only from `render_file`, and its `output_format` must equal the file's format;
  - an explicit image only from `generate_image`;
  - a suggested image only from a compose step with a Markdown output, as a proposal card;
  - a chart from a compose step with Markdown output or from `action_invoke`;
  - a diagram from a compose step with Markdown output;
  - the answer from the step that `final_response` selects.
- Every planned deliverable needs a producing step, and a `quantity` of files or explicit
  images needs that many producing steps.
- Every `render_file` and `generate_image` step must deliver a declared deliverable, so the
  plan never creates a file or image it does not list.
- `delivers` is filled in only where exactly one deliverable can be meant: the answer for
  the `final_response` step, the only planned file of a render step's format, or the plan's
  only explicit image deliverable for an image step.
- A plan that declares no deliverables gets the implicit answer deliverable, so saved and
  simple plans keep working.

While planning, the server truth is also enforced:

- Planned deliverables must be delivered by enabled steps.
- An unavailable deliverable's reason must equal the reason the server reports. The
  planner cannot call something unavailable that the server can produce, or use the wrong
  reason. `image_budget_exceeded` is accepted only once the plan already uses the whole
  image budget.
- When the Image control is selected, the plan must declare an explicit image deliverable.
  A plan revision may remove those images at the user's request; the revised plan then
  carries a review warning instead of failing.
- Image options must be values the configured image model supports.

A saved plan is revalidated without the server truth, so a later availability change or a
step the user turns off never invalidates an approved plan. The delivery notes report such
gaps instead.

On a `deliverables_invalid` error, `plan_request` makes **one** repair call. The planner
receives its rejected reply and the server's validation message and answers the same
request again. A second failure raises `PlannerError` with "The plan could not account for
everything you asked to receive."

### Execution

- **Answer steps.** `compose` receives the deliverables its content is for, derived into
  its `deliverable_context`, and turns them into guidance:
  - when a later `render_file` step saves an output as a file, "write its complete content
    as the finished file; never say files cannot be created";
  - what the user asked for, such as "an image of each president (3)";
  - for an explicit deliverable that is unavailable, the server's message and an
    instruction not to claim, promise, or apologize for it, because the delivery note
    states it once.
- **Visuals.** Chart, diagram, and suggested-image deliverables become the step's structured
  `visuals` (`chart`, `diagram`, `image_proposal`). The composer's Image control no longer
  forces proposal cards in these plans; it makes the user's images explicit deliverables.
- **Images in content.** A compose step bound to generated images receives each one as
  `[[image:<step_id>]]` with its title. Prepared Markdown then carries
  `![AI-generated illustration: ...](asset:<step_id>)` followed by an italic
  "AI-generated illustration" caption; images the content did not place are added after
  it. A prepared slide deck uses image shapes with `source: "asset:<step_id>"`, and an image
  the deck did not place gets a slide of its own. Content that received images can
  reference no other image. Image inputs to compose are always optional, so one failed
  image never blocks the answer or a file.
- **Chat.** Finalization turns each generated image into a `simpleimage` block whose
  `visualId` is the image step id. The answer owns the list of image messages it shows,
  `metadata.orchestration.generated_images`, and the run's terminal frame repeats that list
  at its top level, so the browser reads the thread again and loads the images with the
  answer. The V2 image card finds its saved image by message id from that list and shows
  it as already generated, with the existing viewer and editor. A card for a planned image
  never offers Approve or Approve all, even before its image has loaded; it says the image
  was generated with the answer. As defense in depth, `/api/chat/image-proposals/generate`
  returns the saved image for a planned image's card instead of generating another. The
  classic client and conversation export group images by the same list.
- **Files.** DOCX, PDF, and PPTX rendering receive an `image_resolver` built for each
  render attempt. It resolves only `image-asset-v1` results in the rendered source's own
  retained lineage, reads the bytes from the image's own conversation message and blob,
  and verifies their size and SHA-256 against the retained result. An image the source did
  not consume, a deleted or masked image message, or changed bytes fail the file.
  After that check, `document_image_bytes` gives the renderer a rendition it accepts:
  single-frame PNG or JPEG within `EXPORT_VISUAL_ASSET_MAX_BYTES` (4 MB) and a share of the
  renderer's total pixel budget. An image that already fits is embedded unchanged; a WEBP
  image or a large PNG is re-encoded (PNG keeps transparency, JPEG is flattened onto white)
  and scaled down only as far as needed. Generation admits only images this can convert
  (PNG, JPEG, or WEBP, up to 20 MB and 12 megapixels), so an image never fails its file for
  its size or format. The chat keeps the original.
- **Honest completion.** A run in which an explicit image deliverable's steps did not all
  complete is reported as incomplete, as a missing required file already was. After the
  answer and the files summary, a deterministic **Delivery notes** list names each explicit
  deliverable that was not delivered or is unavailable, such as "Not delivered: An image of
  each president. 2 of 3 images were generated."
- **Retries.** A retry of such a run reuses the images that were generated, generates the
  missing image again, and runs again the answer and file steps computed without it, so the
  new answer and file contain every image. The earlier attempt's answer keeps showing its
  images. A retry is not offered, with reason `retry_would_repeat`, when everything it
  would run again either failed because a service declined its request (`image_content_refused`
  or `image_request_invalid`) or runs again only because of such a step: the retry would
  send the same prompt. Asking again plans a new request instead. Any other failed or
  unfinished step keeps the retry available.

### The `generate_image` capability

- Reason role, prepared content, cost class high, at most `MAX_GENERATED_IMAGES_PER_PLAN`
  per plan.
- Gated by `enable_image_generation` and by the configured image model's readiness. The
  arguments schema lists the model's exact `size`, `quality`, and `background` values.
- Arguments: a self-contained `prompt` (up to 3,000 characters) and a short `title`.
  Named text or Markdown inputs add "Visual details" to the prompt, within the image
  service's 4,000-character limit and never truncated.
- The prompt passes the chat output checks configured for answers before any image is
  generated.
- The adapter reuses `generate_chat_image_message`. The image is saved as a blob-backed
  image message whose `metadata.image_proposal` carries the step id as `visualId`, the
  orchestration run and step, and `source_assistant_message_id` set to the run's
  deterministic answer message id (`orchestration_answer_message_id`). That link never
  moves: a retry that reuses the image lists it in its own answer's `generated_images`.
- The step retains an `image-asset-v1` result: the asset and message ids, title, alt text,
  prompt, MIME type, byte size, SHA-256, and model name. It never contains the image bytes
  or a URL.
- Gather and Reason steps run under `orchestration_file_policy(allow_generated_files=False)`.
  `generate_image` is the only non-Render capability that may publish, because saving the
  one image it was approved to create is its output. It runs no model tools, and a result
  carrying file artifacts still fails closed.

### API and UI

- Plans carry `deliverables` and steps carry `delivers` through the planner, plan
  revisions, the plan editor, and checkpoints. A step's `delivers` and
  `deliverable_context` are part of its checkpoint identity.
- In the V2 interface, the plan panel and the approval card show **You asked for**: each explicit deliverable
  with its state (planned, in progress, delivered, not delivered, turned off, or not
  available with its reason) and, in the plan panel, the step that produces it.
  Suggested deliverables appear under **Also included**.
- A `generate_image` step card shows its image prompt and caption.
- All plan values are rendered as React text.

### Files

| File | Role |
| --- | --- |
| `functions_orchestration_deliverables.py` | Server truth, validation, answer guidance, image placement, the chat projection, and delivery notes |
| `functions_orchestration_images.py` | Image readiness and the `generate_image` adapter |
| `functions_orchestration_registry.py` | The `generate_image` descriptor, budget, and readiness gate |
| `functions_orchestration_result_contracts.py`, `functions_orchestration_results.py`, `functions_orchestration_result_runtime.py` | The `image-asset-v1` result kind |
| `functions_orchestration_schema.py` | `delivers`, optional image inputs, and deliverable compilation |
| `functions_orchestration_planner.py` | The deliverables prompt, server truth in the context, and the repair call |
| `functions_orchestration_composition.py` | Deliverable guidance and image placement in prepared content |
| `functions_orchestration_executor.py` | Image publication policy and explicit-image reconciliation |
| `functions_orchestration_execution.py`, `functions_orchestration_events.py` | Images in the chat answer, the answer's image list in the terminal frame, and delivery notes |
| `functions_orchestration_rendering.py`, `functions_orchestration_services.py`, `functions_orchestration_bootstrap.py` | The per-render image resolver, its byte reader, and document renditions |
| `functions_orchestration_recovery.py` | Retry eligibility, including `retry_would_repeat` for declined requests |
| `functions_image_generation.py`, `route_backend_chats.py` | Size, quality, and background options, the stored image's digest, and returning a planned image instead of generating another |
| `route_backend_conversation_export.py`, `static/js/chat/chat-messages.js` | Export and the classic client group an answer's listed images |
| `application/v2_ui/src/lib/orchestrationPlan.ts`, `OrchestrationDeliverables.tsx` | Deliverable normalization, states, and the You asked for section |
| `application/v2_ui/src/lib/imageProposalSpec.ts`, `ImageProposalContext.tsx`, `InlineImageProposal.tsx`, `MessageList.tsx` | Answer-owned image lists and planned image cards without approval |

## Usage

### How the reported requests run

- **"create a csv of states and capitals"**: `compose` prepares records-v1 rows with the
  columns State and Capital from general knowledge, and `render_file` saves
  `us_states_capitals.csv`. The chat shows the file card, and You asked for shows the CSV
  file as delivered.
- **"create a word file ... images for each president"**: an optional `web_search`, three
  `generate_image` steps, a `compose` step that writes the Markdown report with an image
  token in each section, and `render_file` to DOCX with the images embedded. The report is
  the final response, so the chat shows it with its images.
- **"report ... images"** without a file: the same plan without `render_file`.
- If the search fails, the report is still written from general knowledge and says so. If
  an image or the file fails, the run is reported as incomplete and the delivery notes say
  what is missing.

### What the user sees

1. The approval card lists You asked for, including anything that is not available here
   and why.
2. The plan panel shows the step that produces each deliverable, and each
   `generate_image` step's prompt.
3. After the run, generated images appear inline in the answer, and the DOCX, PDF, or PPTX
   file contains them.

## Testing and validation

- `functional_tests/test_orchestration_deliverables.py` uses the real headless orchestration runner with
  offline model replies and a doubled image service call. It covers:
  - validation, linking, derived visuals, optional image inputs, the Image control, and the
    image budget and options;
  - unavailable reasons that must match the server, and render formats that must match
    the file deliverable;
  - the server truth in the planner context and the single repair call;
  - `generate_image` gating, prompt checks, persistence, and answer-owned image lists;
  - DOCX, PDF, and PPTX embedding, including WEBP images and a 4.7 MB PNG embedded as
    renditions while chat keeps the originals, and the refusal of images outside a file's
    own source;
  - scenarios for a CSV, a Word report with three images, a report without a file, and a
    failing search, image, and render;
  - a retry that reuses two images, generates the missing one, and delivers all three in the
    answer and the Word file while the earlier answer keeps its images; no retry when it
    could only resend a refused prompt; and the approval route returning a planned image
    without calling the image service;
  - a file step turned off at approval, which keeps the run retryable, and a run in which
    every image fails, which leaves no image tokens in the answer or the file.
- `functional_tests/test_v2_orchestration_deliverables.mjs` covers browser normalization,
  deliverable states, a terminal frame read through the real run stream client, and a
  reused image grouped under both answers in React V2 and the classic client.
- `ui_tests/test_v2_orchestration_dependency_plans.py` covers the You asked for section in
  the plan panel and approval card at desktop and mobile widths, including XSS-safe text.
- `ui_tests/test_v2_orchestration_generated_images.py` covers the live chat loading an
  answer's images after the run, planned image cards that never offer approval, and a
  reused image shown under both the earlier and the retried answer.

### Performance

Images generate one at a time, so each adds the image service's latency, usually tens of
seconds. Four images plus a report and a file fit within the default step and run time
limits. Running image steps in parallel is a possible follow-up.

### Known limitations

- Generated images are AI illustrations. Retrieving authentic images, such as
  public-domain museum portraits, is not supported; reports link those sources instead.
- Markdown and plain-text files do not contain images.
- A plan generates at most four images.
- React V2 offers **Retry from failed step** only for an attempt without files, because
  preparing a whole-run retry withdraws the attempt's available files. So a run that
  delivered its file but missed a requested image offers no whole-run retry in the chat,
  and **Retry file** cannot generate an image. Ask again to create a new plan. The
  server-side retry itself delivers the image and the file; only the chat does not offer
  it for such an attempt.
