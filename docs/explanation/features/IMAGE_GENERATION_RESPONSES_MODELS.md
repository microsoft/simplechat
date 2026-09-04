# Image Generation Through Responses-Capable Chat Models

## Overview

SimpleChat can now produce images from a chat deployment such as `gpt-5.6-sol`, not only
from a dedicated `gpt-image-*` or DALL-E deployment.

The reason is availability rather than quality. An image model is a separate deployment,
often gated by approval and not offered in every subscription or region, while a chat
deployment is generally already there. Before this change, a tenant without an image model
could not switch image generation on at all: the deployment list was filtered to names
containing `dall-e` or `image`, so nothing appeared to select.

**Implemented in version:** `0.261.088`

**Dependencies:** `openai==1.109.1` (the `responses` client surface and the
`image_generation` hosted tool), an Azure OpenAI resource in a region where the Responses
API is available.

## Architecture

### Two routes, chosen from the model name

Azure OpenAI serves images two ways, and a deployment answers on one of them and not the
other:

| Route | Endpoint | Models |
| --- | --- | --- |
| `images` | `/images/generations`, `/images/edits` | `gpt-image-*`, `dall-e-*` |
| `responses` | `/responses` with the hosted `image_generation` tool | chat models — `gpt-5.6-*`, `gpt-5*`, `gpt-4o`, `o*` |

The route is derived from the `modelName` already stored alongside the selected
deployment, not asked of the administrator. It is not a preference: a wrong answer is a
failed request rather than a degraded one, and an administrator would be guessing at
something the deployment already states.

Two cases keep the images endpoint rather than being classified, because in both of them
"unknown" would otherwise be read as "chat model" and move a working deployment onto a
route it cannot serve:

- A deployment whose `modelName` was never recorded. Settings saved before that field
  existed have none.
- The API Management route, which records a deployment name only. What the gateway
  publishes decides the shape of the call in any case.

### API version

`azure_openai_image_gen_api_version` defaults to `2024-12-01-preview`, which predates the
Responses API. Honouring it on the Responses route would fail every request against a
deployment that is otherwise configured correctly, so that route substitutes
`RESPONSES_IMAGE_API_VERSION` (`2025-04-01-preview`) instead. A stored version *newer*
than the constant is honoured, so a deliberate pin is not overridden by a constant that
will age.

The stored setting continues to govern `/images/generations` and `/images/edits`
unchanged.

### Response shape

The images endpoint answers with `data[0].url` or `data[0].b64_json`. The Responses route
answers with an `image_generation_call` item in `output`, alongside the reasoning and
message items the model also produced, carrying base64 in `result` and an optional
`output_format`.

Both are normalised to the same data-URL or HTTP-URL string before returning, which is
what lets blob storage, the image proposal pipeline, revision history and the lightbox
stay unaware of which route was taken.

A reply that carries no `image_generation_call` is reported as an empty result rather than
raised, because "the model answered without calling the tool" and "the call failed" are
different outcomes with different messages. The generation helper turns the first into a
message naming the deployment.

## File structure

| File | Role |
| --- | --- |
| `application/single_app/functions_image_api_route.py` | New. Route classification, API version selection, tool spec, and Responses output reading. Imports no application configuration, so all of it is directly testable. |
| `application/single_app/functions_image_generation.py` | `request_generated_image_source` — the single entry point every caller uses. `resolve_image_generation_client` gained an API version override. |
| `application/single_app/functions_image_edit.py` | Regeneration takes the Responses route when that is the deployment's route. `resolve_selected_image_model_name` moved to the new module. |
| `application/single_app/route_backend_chats.py` | The inline client construction and response parsing in the chat path were replaced by the shared helper. |
| `application/single_app/route_backend_settings.py` | Admin **Test connection** exercises whichever route the real call will take. |
| `application/single_app/route_backend_models.py` | `/api/models/image` lists chat deployments as well as image deployments. |

### Callers

Every path that produces an image goes through
`functions_image_generation.request_generated_image_source`:

- `generate_chat_image_message` — the image proposal pipeline and inline approvals.
- `route_backend_chats` — the chat image generation toggle.
- `functions_image_edit.request_image_edit` — the regenerate branch of the image editor.
- `route_backend_settings._test_image_gen_connection` — admin **Test connection**.

The connection test is included deliberately. A test that took a different route from the
real call would report success for a path chat never uses.

## Configuration

No new setting. Selecting a different deployment under **Admin Settings → AI Models →
Image Generation → Image model** is the whole of it.

**Fetch deployments** now returns image models and chat models, and excludes embedding
deployments, which can produce an image on neither route.

## Behaviour with a chat deployment

- **Generation** works as it does for an image model. Size, quality and background are
  carried onto the tool spec; unset controls are left unset rather than filled with a
  guess, since a value the deployment does not accept fails the whole request.
- **Editing** offers whole-image regeneration only. `resolve_image_edit_capability`
  already degrades any non-`gpt-image` model to regenerate-only, and now explains that the
  Responses tool has no way to change part of an image. The editor states this before a
  region is painted.
- **Tool choice** is forced. Without it the model is free to answer with prose about the
  image it would have drawn, which reads as an empty result rather than as a refusal.

## Testing and validation

`functional_tests/test_image_generation_responses_route.py` covers the classification in
both directions, the two cases that must stay on the images endpoint, the API version
substitution, the tool spec, and the response reading including replies that carry no
image.

The emphasis is on what must *not* change. Every deployment selectable before this feature
existed answers on the images endpoint, and the classifier is tested against the full set
of image model names to prove none of them moved.

## Known limitations

- **The Responses `image_generation` tool is served by an image model behind the scenes.**
  Where a subscription has no image capability at all rather than no image *deployment*,
  this route may fail for the same underlying reason. It is the only way a chat deployment
  can produce an image, so it is worth having either way, but it is not a guaranteed
  substitute for an image model and should be confirmed with one test generation.
- **Masked editing is unavailable** on this route, as described above.
- **API Management cannot use it.** The gateway route records no model name to classify
  on.
- **Cost and latency are higher** than an equivalent image deployment, because an
  orchestrating model sits in front of every generation.
