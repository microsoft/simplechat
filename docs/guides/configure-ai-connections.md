---
layout: page
title: "Configure AI connections"
description: "Configure shared AI resources once, publish compatible models, and choose independent chat and image defaults."
section: "Guides"
audience: admin
version: "0.261.105"
---

## What this does

AI Connections keeps a resource's address, authentication, and models together. Chat and
image generation select models from that shared source instead of keeping separate
copies of the same endpoint and key. Rotating a shared connection's credential then
updates the connection used by both tasks.

Implemented in version: **0.261.105**.
[Issue #1436](https://github.com/microsoft/simplechat/issues/1436) tracks the shared
connection and GPT image-generation changes.

## When to use shared connections

Use one connection when chat and images use the same resource and authentication. They
can use different models on that resource, or the same model when it supports both
operations. Their defaults stay independent: changing the chat default does not change
the image default.

Use a separate connection for an image-only resource, another region, different
credentials, or an API Management gateway with a different route. It still appears in
the same manager; you do not have to move images onto your chat resource.

Embeddings, transcription, speech, and other services retain their existing
configuration. This guide does not migrate them.

## Before you start

- Sign in with the SimpleChat **Admin** role to manage global connections and defaults.
  This image default is global; personal and group chat connections do not become
  global image choices.
- Have an existing supported deployment and its actual deployment name, not just the
  underlying model family name. SimpleChat does not create a deployment for you.
- Decide whether requests must go through API Management. Keep its published path,
  authentication convention, and supported operations; do not substitute the backend
  resource URL to make a failing gateway request work.
- Grant the identity used by SimpleChat the appropriate inference permissions.
  Deployment discovery also needs management/project read access. An inference API
  key alone cannot enumerate Azure resource deployments.
- If using Key Vault, ensure the configured application identity can read and save
  connection secrets. See [model endpoint identity setup]({{ '/guides/model-endpoint-identity-setup/' | relative_url }})
  for provider-specific access guidance.

A model appearing in discovery does not prove that its image operation is available.
Azure region, entitlement, deployment support, quota, and gateway operations still
matter. A GPT deployment that accepts images as input or calls generic tools is not
automatically an image generator.

## Configure a connection once

1. Open **Admin Settings → AI Models → AI Connections**. For an upgraded installation,
   review any imported image connection before adding another copy.
2. Give the connection a recognizable resource or purpose label, such as
   **Team Azure** or **Creative gateway**. Select the existing provider and configure
   the endpoint and authentication for that resource.
3. Discover existing deployments with managed identity or service-principal access,
   or enter deployment names manually when using inference-only credentials.
   Record the underlying model accurately so capability information is meaningful.
4. Review which operations each model supports, enable the intended models, and
   publish only the operations people should use. Finding a deployment does not
   publish it automatically.
5. Save the connection. Connections are saved individually; there is no need to
   duplicate the resource details in the image settings.

Treat **technical support**, **publication**, and **readiness** separately. A model may
support both chat and images but be published only for images. Conversely, publishing
an image operation cannot grant service access the resource does not have.

If you manually declare support for an internally named model, verify the provider's
operation contract first. Do not mark it image-capable just to make an empty picker
show a choice.

## Select task-specific defaults

### Chat

If you already use **Use AI Connections for chat**, choose an enabled, chat-compatible
model as its default under **Chat**.

If chat still uses the classic endpoint, keep that configuration unless you intend to
migrate chat. **Use AI Connections for chat is irreversible** through the admin interface.
It is not a prerequisite for shared image generation.

### Image generation

1. Under **Image Generation**, choose the default image model from the single picker
   grouped by connection. The choice identifies both the connection and model.
2. Enable **Image Generation** when you are ready to offer it to users. You can
   configure its default while the feature is off without enabling it or changing
   chat mode.
3. Generate a test image using that default before relying on it in production.

There is no second backing-image chooser and no required **Images versus Responses**
setting. SimpleChat uses model capability metadata and the connection's operation
configuration to choose the supported API. That does not remove Azure prerequisites:
where a Responses image tool needs a backing deployment or service default, it must
be established by verified provider configuration or existing metadata, not guessed.

Users continue to use the chat **Image** control. The normal chat-model choice does not
override this global image default, and this release adds no per-chat image-model picker.

### Disambiguate equal deployment names

Two resources can both have a deployment named `production`. Choose by the displayed
connection and model labels, not that name alone. SimpleChat saves connection/model
IDs, so **production on Team Azure** and **production on Creative gateway** remain
different choices even when their deployment names match.

An image-only model remains available for its image task without becoming a text
chat, agent, or workflow model.

## What happens during an upgrade

Startup automatically imports existing direct and APIM image configuration into AI
Connections, or conservatively reuses a compatible connection. If both routes were
configured, both are retained and the previously active deployment stays the image
default. Authentication, API version, and gateway transport information are retained.

Newly imported image models initially publish only image generation. The import does
not enable images, enable connections for chat, or publish an extra chat model merely
because the imported deployment can also produce text.

The original legacy values are retained as backup. After a successful import or an
explicit shared-default save, they are no longer the active image configuration.
Clearing the shared default does **not** switch back to those values.

Import preserves configuration, not provider availability. For example,
[Azure retired DALL-E 3 on March 4, 2026](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/dall-e),
and existing deployments no longer work. If an imported default names a retired
deployment, choose an approved replacement; the migration does not silently change
the selected model.

### Recover a failed import

An import warning means the shared migration did not finish; existing legacy image
operation is retained. Review the safe error notice and server `[AI_CONNECTIONS]`
logs, then correct the connection, settings-write access, or Key Vault configuration
identified by the failure. Restart after correcting it to retry the import.

Do not delete a working legacy endpoint or secret while investigating. Concurrent
settings writes are retried only a bounded number of times to avoid overwriting another
administrator's edits. Avoid simultaneous connection edits during the retry.

If you deliberately configure and save a shared image default instead, that selection
becomes authoritative; subsequent clearing is not a legacy fallback.

## Change or retire a connection safely

- **Rotate a key:** edit the shared connection, supply the replacement, save, and test
  each task that uses it. Stored secret values are not shown; leaving the secret field
  empty preserves an existing value.
- **Stop publishing one operation:** keep the model's technical capability information
  accurate and change its publication instead. A dual-capable model can remain
  available for chat while no longer being offered for images.
- **Disable or delete a selected model/connection:** review the default-unavailable
  notice and choose a compatible replacement. SimpleChat does not silently select
  another connection or revive old image settings.
- **Intentionally stop image generation:** disable the image feature. Merely clearing
  its default leaves enabled image requests without a configured model.

## Verify the operation, not just connectivity

Discovery verifies the deployment-listing path, and a chat test verifies chat.
Neither establishes image generation. Use an image-specific test where available,
or follow [Generate images]({{ '/guides/generate-images/' | relative_url }}) with a
small request such as “Create a simple blue circle on a white background.”

Check that the conversation contains an actual image, not a text description. If the
request uses API Management, confirm the request went through the expected gateway.
Repeat the relevant operation after changing a deployment, credential, or route.
Generation tests can incur provider charges.

Responses image generation supports whole-image regeneration in SimpleChat, not masked
editing. Existing direct-image masked editing remains subject to the selected model
and Images API support.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| The image picker has no choices | Enable a connection and model, establish supported image capability for its provider, and publish image generation. Enabling chat connections is not the fix |
| A model supports images but is not selectable | Technical support alone is insufficient: the connection/model may be disabled or image generation may not be published |
| Chat changed but image output still uses the old model | The defaults are independent; change the image default explicitly |
| A default becomes unavailable | The selected record was deleted, disabled, or made incompatible/unpublished. Choose a valid replacement rather than relying on a fallback |
| Discovery fails but inference works | The identity lacks management/project read access, or inference-only key authentication is in use. Supply deployment names manually or correct discovery permissions |
| A GPT model produces no image or the service rejects the tool | Confirm that deployment and resource support the hosted image operation, including any required backend binding, entitlement, and gateway operation. A successful text response is not image readiness |
| Images worked before an import warning | Preserve the legacy values, correct the reported configuration/permissions, and restart to retry |
| Images fail after clearing a successfully imported default | Clearing was authoritative. Choose a new shared default or disable image generation; legacy values will not be reactivated |
| An older settings integration reports `409` / `image_catalog_migrated` | The legacy image catalog is no longer authoritative. Use AI Connections or update the integration to `GET`/`PUT /api/v2/admin/capability-models/image_generation`; retrying the old catalog write will not update the default |

## Related

- [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
- [Generate images]({{ '/guides/generate-images/' | relative_url }})
- [Use managed identity]({{ '/guides/use-managed-identity/' | relative_url }})
- [Model endpoint identity setup]({{ '/guides/model-endpoint-identity-setup/' | relative_url }})
