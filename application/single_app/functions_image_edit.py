# functions_image_edit.py

"""The model call behind "change this part of the image".

Editing a generated image in place is the image equivalent of
``functions_block_revision_assist``, and exists for the same reason: refining an image by asking
again in the thread costs another paid generation, produces another message, and leaves the
previous image sitting in the conversation unrelated to the new one.

An image is pixels rather than source text, so unlike a diagram it cannot be hand-edited. Every
change goes through the model. What a reader *can* supply is a **mask** -- the region the change
applies to -- which is the one thing a text instruction cannot express.

Mask semantics are the detail most easily got backwards, so they are stated here once. In the
images API a mask is a PNG with an alpha channel, and **fully transparent pixels mark the region
to edit** while opaque pixels are preserved. It is not a white-on-black stencil. The client
builds its mask by filling a canvas opaque and then erasing, which produces that polarity by
construction; this module verifies it rather than assuming it.

Two honest limitations are carried through to the interface rather than hidden:

- A mask *guides* the model. It is not a pixel-level clamp, and areas outside it can still shift.
- Provider-qualified capabilities distinguish masked edits, whole-image reference edits,
  and prompt-only regeneration. Unsupported masks are rejected, not discarded.
"""

import base64
import io

from PIL import Image

from functions_ai_connections import AIConnectionError
from functions_image_api_route import (
    ImageGenerationError,
    resolve_image_generation_api_version,
    resolve_selected_image_capability,
    resolve_selected_image_deployment_name,
)
from functions_image_capabilities import validate_image_options
from functions_image_messages import decode_image_content, is_external_image_url

# Config, the Azure clients and the generation helpers are imported inside the functions that
# need them rather than here. Everything above the model call -- mask validation, prompt
# composition, image decoding -- is pure, and keeping the module importable without application
# configuration is what lets those parts be tested directly. The same reason
# `functions_image_generation` defers its own document-processing import.


# The API caps an uploaded mask at 4 MB. Refused before upload so the reader is told what is
# wrong rather than seeing a request rejected downstream.
MAX_MASK_BYTES = 4 * 1024 * 1024

# A source image larger than this is not something to be round-tripping through an edit.
MAX_SOURCE_IMAGE_BYTES = 20 * 1024 * 1024

# Beyond this an image is not a chat illustration, and decoding it would cost more memory than
# the request is worth. Guards against a decompression bomb as much as against a large picture.
MAX_IMAGE_PIXELS = 12_000_000

# Formats the images API accepts as the image being edited. Anything else is converted to PNG.
PASSTHROUGH_IMAGE_MIME_TYPES = ('image/png', 'image/jpeg', 'image/webp')

# Legacy GPT rendering labels; the selected operation profile determines accepted options.
SUPPORTED_IMAGE_SIZES = ('1024x1024', '1024x1536', '1536x1024')
SUPPORTED_IMAGE_QUALITIES = ('low', 'medium', 'high')
SUPPORTED_IMAGE_BACKGROUNDS = ('transparent', 'opaque')

# An alpha at or below this counts as "edit here". Hard zero is what the client writes, but a
# mask that has been resized can carry a few interpolated values at region edges.
MASK_TRANSPARENT_THRESHOLD = 8

class ImageEditError(ImageGenerationError):
    """Safe image-operation failure, retaining the existing shared-editor exception contract."""


# Source edits, region edits, and prompt-only regeneration are distinct operations.
IMAGE_EDIT_MODE_MASKED = 'masked'
IMAGE_EDIT_MODE_REFERENCE = 'edit'
IMAGE_EDIT_MODE_REGENERATE = 'regenerate'
IMAGE_EDIT_MODE_UNAVAILABLE = 'unavailable'

# /images/edits is only routable on a recent preview API version. An older one fails in a way
# that reads like a broken deployment, so it is detected up front and reported against the
# setting that causes it.
MIN_IMAGE_EDIT_API_VERSION = '2025-04-01-preview'


def image_api_version_supports_edit(api_version):
    """Return whether an Azure OpenAI API version can route /images/edits.

    Preview versions are dated, so the leading ``YYYY-MM-DD`` is compared. An unparseable value
    is treated as unsupported: guessing optimistically would trade a clear message here for an
    opaque failure after the reader has already selected a region.
    """
    if str(api_version or '').strip() == 'v1':
        return True
    parts = str(api_version or '').strip().split('-')
    if len(parts) < 3:
        return False
    try:
        candidate = tuple(int(part) for part in parts[:3])
    except (TypeError, ValueError):
        return False
    return candidate >= (2025, 4, 1)


def resolve_image_edit_capability(settings):
    """Describe how images from this deployment may be changed.

    Returned rather than raised, because the answer drives what the editor offers *before* a
    reader does any work. Being told up front that only whole-image regeneration is available is
    a usable experience; painting a mask and then being refused is not.

    Resolving this projection must not initialize runtime clients, read secrets, or turn
    a cleared shared default into a bootstrap failure.
    """
    settings = settings if isinstance(settings, dict) else {}
    unavailable = {
        'mode': IMAGE_EDIT_MODE_UNAVAILABLE, 'enabled': False, 'supported': False,
        'model_name': '', 'reason': '', 'api': '', 'editing': False, 'masking': False,
        'provider_label': '', 'cloud_label': '', 'availability': 'unknown',
        'availability_reason': '', 'sizes': [], 'qualities': [], 'backgrounds': [],
        'input_formats': [], 'output_formats': [],
    }
    if not settings.get('enable_image_generation'):
        return {**unavailable, 'reason': 'Image generation is not enabled.'}
    try:
        capability = resolve_selected_image_capability(settings)
        api_version = resolve_image_generation_api_version(settings)
    except AIConnectionError as exc:
        return {**unavailable, 'reason': exc.public_message}
    capability['enabled'] = True
    if (
        capability['api'] == 'images'
        and capability['provider'] in ('azure_openai', 'foundry')
        and capability['editing']
        and not image_api_version_supports_edit(api_version)
    ):
        capability.update(
            mode=IMAGE_EDIT_MODE_REGENERATE, editing=False, masking=False,
            reason=f'Source-image editing requires Images API version {MIN_IMAGE_EDIT_API_VERSION} or newer.',
        )
    elif capability['editing'] and not capability['masking']:
        capability['reason'] = (
            'This model supports whole-image reference edits, but an uploaded-mask operation '
            'is not documented for this integration.'
        )
    elif not capability['editing']:
        capability['reason'] = (
            'This model is configured for generation only. Regeneration creates a new whole image from the prompt.'
        )
    return capability



def _open_image(image_bytes, what):
    """Decode image bytes into a Pillow image, refusing anything implausible.

    The dimension check runs against the header, *before* the raster is decoded. ``Image.open``
    only reads enough to populate ``size``; ``load`` is what allocates the pixels. Checking
    after loading -- which is the obvious way to write this -- would mean a file declaring
    50000x50000 had already been expanded into memory by the time it was rejected, which is
    precisely the attack the limit exists to stop.
    """
    if not image_bytes:
        raise ImageEditError(f'The {what} is empty')

    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        raise ImageEditError(f'The {what} could not be read as an image') from exc

    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageEditError(f'The {what} has no dimensions')
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageEditError(f'The {what} is too large to process')

    try:
        image.load()
    except Exception as exc:
        raise ImageEditError(f'The {what} could not be read as an image') from exc

    return image


def normalize_mask(mask_data_url, width, height, regions=0, max_bytes=MAX_MASK_BYTES):
    """Return a mask PNG matching the source image, or None when nothing was selected.

    The returned bytes are RGBA PNG where transparent means "edit here", which is what the API
    expects. The incoming mask is checked rather than trusted on three points that each produce
    a silently wrong edit rather than an error:

    - It must actually carry an alpha channel. A fully opaque mask selects nothing, and sending
      one asks the model to change nothing while charging for it.
    - It must match the source image's dimensions exactly. A resize is applied with nearest
      neighbour, so a rounding difference between the browser's layout and the image's true size
      is absorbed without blurring hard mask edges into partial alpha.
    - Selecting nothing is reported as None rather than as an empty mask, so the caller can fall
      back to editing the whole image instead of sending a no-op.
    """
    if not mask_data_url:
        return None

    normalized = str(mask_data_url).strip()
    if not normalized:
        return None
    limit = min(MAX_MASK_BYTES, max_bytes)
    if len(normalized) > ((limit + 2) // 3) * 4 + 128:
        raise ImageEditError('The selected region is too large to send', 'invalid_image_mask', 400)

    if normalized.startswith('data:image/'):
        try:
            _, mask_bytes = decode_image_content(normalized)
        except ValueError as exc:
            raise ImageEditError('The selected region could not be read') from exc
    else:
        try:
            mask_bytes = base64.b64decode(normalized, validate=True)
        except Exception as exc:
            raise ImageEditError('The selected region could not be read') from exc

    if len(mask_bytes) >= limit:
        raise ImageEditError('The selected region is too large to send')

    original_mask = _open_image(mask_bytes, 'selected region')
    if original_mask.format != 'PNG' or (
        'A' not in original_mask.getbands() and 'transparency' not in original_mask.info
    ):
        raise ImageEditError('The selected region must be a PNG mask with transparency.', 'invalid_image_mask', 400)
    mask = original_mask.convert('RGBA')
    if mask.size != (int(width), int(height)):
        mask = mask.resize((int(width), int(height)), Image.NEAREST)

    alpha = mask.getchannel('A')
    histogram = alpha.histogram()
    editable_pixels = sum(histogram[: MASK_TRANSPARENT_THRESHOLD + 1])
    total_pixels = max(1, mask.size[0] * mask.size[1])

    if editable_pixels == 0:
        # Nothing was selected. Reported as absent so the caller edits the whole image rather
        # than paying for a request that asks the model to change nothing.
        return None

    buffer = io.BytesIO()
    mask.save(buffer, format='PNG')
    encoded = buffer.getvalue()
    if len(encoded) >= limit:
        raise ImageEditError('The selected region is too large to send')

    bounded_regions = regions if isinstance(regions, int) and not isinstance(regions, bool) else 0
    return {
        'bytes': encoded,
        'coverage': round(editable_pixels / total_pixels, 4),
        'regions': max(0, min(bounded_regions, 999)),
        'covers_everything': editable_pixels >= total_pixels,
        'width': mask.size[0],
        'height': mask.size[1],
    }


def prepare_source_image(mime_type, image_bytes, allowed_formats=None):
    """Return the image to edit as bytes the API accepts, with its true dimensions.

    The dimensions matter more than the format: the mask has to match them exactly, and the only
    trustworthy source for them is the image itself. A browser reporting its own idea of the
    size would be reporting the size it laid the image out at.
    """
    if len(image_bytes or b'') > MAX_SOURCE_IMAGE_BYTES:
        raise ImageEditError('This image is too large to edit')

    image = _open_image(image_bytes, 'image')
    width, height = image.size

    normalized_mime = Image.MIME.get(image.format) or str(mime_type or '').strip().lower()
    allowed_formats = PASSTHROUGH_IMAGE_MIME_TYPES if allowed_formats is None else allowed_formats
    if normalized_mime in allowed_formats:
        return {
            'bytes': image_bytes,
            'mime_type': normalized_mime,
            'file_name': f"image.{'jpg' if normalized_mime == 'image/jpeg' else normalized_mime.split('/')[1]}",
            'width': width,
            'height': height,
        }

    if 'image/png' not in allowed_formats:
        raise ImageEditError('The source image format is unsupported by this model.', 'invalid_image_request', 400)
    buffer = io.BytesIO()
    image.convert('RGBA').save(buffer, format='PNG')
    if len(buffer.getvalue()) > MAX_SOURCE_IMAGE_BYTES:
        raise ImageEditError('This image is too large to edit after format conversion.', 'invalid_image_request', 400)
    return {
        'bytes': buffer.getvalue(),
        'mime_type': 'image/png',
        'file_name': 'image.png',
        'width': width,
        'height': height,
    }


def load_current_image_bytes(message_doc, complete_content=''):
    """Return the MIME type and bytes of the version of an image currently on screen.

    An edit is applied to what the reader is looking at, not to the first image ever generated,
    so successive edits accumulate instead of each one being applied to the original. That makes
    the current revision's blob the first place to look, with the message's own content -- blob,
    chunked data URL or external URL -- as the fallback for an image nobody has edited.
    """
    from functions_image_messages import is_blob_backed_image_message
    from functions_message_image_revisions import (
        read_image_revisions,
        resolve_current_revision,
        revision_blob_location,
    )

    location = revision_blob_location(resolve_current_revision(read_image_revisions(message_doc)))
    if location:
        return location['mime_type'], load_image_bytes_from_blob(
            location['blob_container'], location['blob_path']
        )

    if is_blob_backed_image_message(message_doc):
        container = str((message_doc or {}).get('blob_container') or '').strip()
        path = str((message_doc or {}).get('blob_path') or '').strip()
        if not container or not path:
            raise ImageEditError('This image could not be located in storage')
        mime_type = str((message_doc or {}).get('mime_type') or '').strip() or 'image/png'
        return mime_type, load_image_bytes_from_blob(container, path)

    content = str(complete_content or (message_doc or {}).get('content') or '').strip()
    if not content:
        raise ImageEditError('This image has no content to edit')

    if content.startswith('data:image/'):
        try:
            return decode_image_content(content)
        except ValueError as exc:
            raise ImageEditError('This image could not be read') from exc

    if is_external_image_url(content):
        from functions_image_generation import resolve_generated_image_bytes

        try:
            return resolve_generated_image_bytes(content)
        except Exception as exc:
            raise ImageEditError('This image could not be downloaded') from exc

    raise ImageEditError('This image cannot be edited')


def revise_image_message(
    settings,
    message_doc,
    owner_user_id,
    conversation_id,
    complete_content='',
    origin='ai',
    instruction='',
    prompt='',
    mask_data_url='',
    mask_regions=0,
    size='',
    quality='',
    background='',
    author_id='',
    author_name='',
    expected_revision_count=None,
    expected_current_revision_id='',
    reload_message=None,
    operation='',
):
    """Produce a new version of an image message and store it, mutating ``message_doc``.

    Shared by the personal and the collaborative routes so that the two cannot drift. Both hand
    it the *source* image document, because a shared image is a mirror and its bytes live with
    the original.

    The three origins are genuinely different operations rather than variations of one:

    - ``ai`` applies an instruction, and is the only one that uses a mask.
    - ``prompt`` replaces the prompt outright and rebuilds the image from it.
    - ``control`` keeps the prompt and changes how it is rendered -- size, quality, background.

    The revision is written only after the image comes back, so a failed generation leaves no
    version behind describing an edit that never happened.
    """
    from functions_message_image_revisions import (
        ORIGIN_AI,
        ORIGIN_CONTROL,
        ORIGIN_PROMPT,
        apply_image_revision,
        assert_revision_expectations,
        current_image_prompt,
        normalize_prompt,
        validate_origin,
    )

    revision_origin = validate_origin(origin)
    current_prompt = current_image_prompt(message_doc)

    # Checked before the model is called, not only after. `apply_image_revision` guards this too,
    # and has to, but discovering the conflict there alone would mean a participant paid for a
    # generation that was always going to be rejected -- and left its bytes in blob storage with
    # nothing pointing at them.
    assert_revision_expectations(message_doc, expected_revision_count, expected_current_revision_id)

    capability = resolve_image_edit_capability(settings)
    if not capability['enabled']:
        raise AIConnectionError(
            capability.get('reason') or 'The image model is unavailable.',
            'model_configuration_unavailable' if settings.get('enable_image_generation') else 'capability_disabled',
        )
    if mask_data_url is not None and not isinstance(mask_data_url, str):
        raise ImageEditError('The selected region must be an encoded PNG mask.', 'invalid_image_mask', 400)
    if mask_regions and not mask_data_url:
        raise ImageEditError('The selected region has no PNG mask. Clear or redraw the selection.', 'invalid_image_mask', 400)
    if operation not in ('', 'edit', 'regenerate'):
        raise ImageEditError('The image operation is invalid.', 'invalid_image_request', 400)
    effective_operation = operation or (
        'edit' if revision_origin == ORIGIN_AI and capability['editing'] else 'regenerate'
    )
    if effective_operation == 'edit' and not capability['editing']:
        raise ImageEditError('The selected model cannot edit a source image.', 'unsupported_image_operation', 400)
    if mask_data_url and (not capability['masking'] or effective_operation != 'edit' or revision_origin != ORIGIN_AI):
        raise ImageEditError(
            'The selected model or operation cannot use this mask. Refresh the image controls or remove the selection.',
            'unsupported_image_operation', 400,
        )
    source_image = None
    if effective_operation == 'edit':
        source_mime, source_bytes = load_current_image_bytes(message_doc, complete_content)
        source_image = prepare_source_image(source_mime, source_bytes, capability['input_formats'])
    mask = None
    if revision_origin == ORIGIN_AI:
        normalized_instruction = str(instruction or '').strip()
        if not normalized_instruction:
            raise ImageEditError('Describe the change you want')
        if mask_data_url:
            mask = normalize_mask(
                mask_data_url,
                source_image['width'],
                source_image['height'],
                regions=mask_regions,
                max_bytes=capability.get('max_mask_bytes', MAX_MASK_BYTES),
            )
            if mask_regions and mask is None:
                raise ImageEditError('The selected region contains no editable pixels.', 'invalid_image_mask', 400)
        effective_prompt = compose_edit_prompt(current_prompt, normalized_instruction, mask)
    elif revision_origin == ORIGIN_PROMPT:
        normalized_instruction = ''
        effective_prompt = normalize_prompt(prompt)
    elif revision_origin == ORIGIN_CONTROL:
        normalized_instruction = ''
        effective_prompt = current_prompt or normalize_prompt(prompt)
        if not effective_prompt:
            raise ImageEditError('This image has no prompt to rebuild it from')
    else:
        raise ImageEditError('Unsupported revision origin')

    result = request_image_edit(
        settings,
        source_image,
        effective_prompt,
        mask=mask,
        size=size,
        quality=quality,
        background=background,
        operation=effective_operation,
    )

    stored = store_revision_image(
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        message_id=str((message_doc or {}).get('id') or ''),
        image_bytes=result['bytes'],
        mime_type=result['mime_type'],
    )
    # Recorded from the returned image rather than from what was asked for: the GPT image models
    # emit only a fixed set of sizes, so a revision's aspect can legitimately differ from the
    # original's and the history has to describe what actually came back.
    stored['width'] = result['width']
    stored['height'] = result['height']

    # The revision is applied to a freshly read document, not to the one loaded before the model
    # was called. A generation takes seconds, and in a shared conversation another participant
    # can land their own version inside that window. Writing to the stale copy would pass the
    # conflict check -- it was true when the request started -- and then silently discard their
    # edit on upsert.
    target_doc = message_doc
    if reload_message is not None:
        reloaded = reload_message()
        if isinstance(reloaded, dict):
            target_doc = reloaded

    entry = apply_image_revision(
        target_doc,
        stored,
        origin=revision_origin,
        prompt=effective_prompt,
        instruction=normalized_instruction,
        mask={
            'coverage': mask['coverage'],
            'regions': mask['regions'],
        } if mask else None,
        model=result['model'],
        method=result['method'],
        size=result['size'],
        quality=result['quality'],
        background=result['background'],
        author_id=author_id,
        author_name=author_name,
        expected_revision_count=expected_revision_count,
        expected_current_revision_id=expected_current_revision_id,
    )

    return {
        'entry': entry,
        'message': target_doc,
        'method': result['method'],
        'model': result['model'],
        'prompt': effective_prompt,
        'instruction': normalized_instruction,
        'capability': capability,
    }


def store_revision_image(owner_user_id, conversation_id, message_id, image_bytes, mime_type):
    """Write one revision's bytes to blob storage and return where they went.

    Always blob, never inline. Image messages already split across several documents at 1.5 MB
    because a data URL exceeds the Cosmos item limit, so a revision that embedded its bytes in
    metadata would grow the message document past what can be written after only a couple of
    edits.

    The filename is unique per revision, so nothing overwrites the original or an earlier
    version and restoring one keeps working.
    """
    import uuid

    from functions_simplechat_operations import upload_chat_image_bytes_for_user

    extension = {
        'image/jpeg': '.jpg',
        'image/webp': '.webp',
        'image/gif': '.gif',
    }.get(str(mime_type or '').lower(), '.png')

    return upload_chat_image_bytes_for_user(
        user_id=owner_user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        file_name=f'revision-{uuid.uuid4().hex}{extension}',
        image_bytes=image_bytes,
        content_type=mime_type or 'image/png',
        image_source='edited',
    )


def load_image_bytes_from_blob(blob_container, blob_path):
    """Download one stored image from blob storage."""
    from config import CLIENTS

    blob_service_client = CLIENTS.get('storage_account_office_docs_client')
    if not blob_service_client:
        raise ImageEditError('Image storage is not available')

    try:
        blob_client = blob_service_client.get_blob_client(
            container=blob_container,
            blob=blob_path,
        )
        return blob_client.download_blob().readall()
    except Exception as exc:
        raise ImageEditError('The image could not be read from storage') from exc


def compose_edit_prompt(current_prompt, instruction, mask=None):
    """Return the prompt describing the image as it should end up.

    The API's own guidance is that describing the *complete* desired image preserves the
    unmasked regions far better than describing only the change, because the model is generating
    a whole image either way and a change-only prompt leaves the rest unspecified. So the
    instruction is not sent alone: it is combined with the prompt that describes the version
    currently on screen.

    Composed deterministically rather than by asking a chat model to rewrite it. A second
    completion would add latency and cost to every edit, and give the wording another chance to
    drift away from what the reader asked for.
    """
    base = str(current_prompt or '').strip()
    change = str(instruction or '').strip()
    if not change:
        raise ImageEditError('Describe the change you want')

    parts = []
    if base:
        parts.append(f'The existing image shows: {base}')

    if mask and not mask.get('covers_everything'):
        parts.append(
            'Apply this change only within the transparent region of the supplied mask, and '
            'keep everything outside it exactly as it is: '
            f'{change}'
        )
    else:
        parts.append(f'Apply this change: {change}')

    parts.append(
        'Produce the complete resulting image, preserving the composition, style and subject '
        'that are not being changed.'
    )
    return '\n\n'.join(parts)


def request_image_edit(
    settings,
    source_image,
    prompt,
    mask=None,
    size='',
    quality='',
    background='',
    operation='',
):
    """Ask the model for an edited image, returning its bytes and how it was produced.

    An explicit edit must remain an edit. Regeneration is requested separately, or
    selected for a generation-only model when a legacy caller omitted the operation.
    """
    from functions_image_generation import (
        request_edited_image_source,
        request_generated_image_source,
    )

    capability = resolve_image_edit_capability(settings)
    if not capability['enabled']:
        raise AIConnectionError(
            capability.get('reason') or 'Image generation is not enabled.',
            'model_configuration_unavailable' if settings.get('enable_image_generation') else 'capability_disabled',
        )
    if operation not in ('', 'edit', 'regenerate'):
        raise ImageEditError('The image operation is invalid.', 'invalid_image_request', 400)
    effective_operation = operation or ('edit' if capability['editing'] else 'regenerate')
    if mask and (not capability['masking'] or effective_operation != 'edit'):
        raise ImageEditError('The selected model or operation cannot use an uploaded mask.', 'unsupported_image_operation', 400)
    if effective_operation == 'edit' and not capability['editing']:
        raise ImageEditError('The selected model cannot edit a source image.', 'unsupported_image_operation', 400)
    try:
        validate_image_options(capability, size, quality, background)
    except ValueError as exc:
        raise ImageEditError(
            'The selected model does not support the requested image options.', 'invalid_image_request', 400
        ) from exc
    deployment = resolve_selected_image_deployment_name(settings)
    try:
        if effective_operation == 'regenerate':
            generated_source = request_generated_image_source(
                settings, prompt, size=size, quality=quality, background=background,
            )
        else:
            generated_source = request_edited_image_source(
                settings, prompt, source_image, mask=mask, size=size, quality=quality, background=background,
            )
    except ImageGenerationError as exc:
        raise ImageEditError(exc.public_message, exc.code, exc.status_code, exc.context) from exc

    return _finish_image_edit(
        generated_source,
        deployment=deployment,
        method=effective_operation,
        normalized_size=size,
        quality=quality,
        background=background,
    )


def _finish_image_edit(
    generated_source,
    *,
    deployment,
    method,
    normalized_size,
    quality,
    background,
):
    """Turn a produced image into the result shape both routes return.

    Shared so the Responses route reports its outcome identically to the images endpoint:
    the caller records ``method`` in the revision history, and a difference here would show
    up as two kinds of regeneration rather than one.
    """
    from functions_image_generation import resolve_generated_image_bytes

    if is_external_image_url(generated_source) or generated_source.startswith('data:image/'):
        try:
            mime_type, image_bytes = resolve_generated_image_bytes(generated_source)
        except ImageGenerationError as exc:
            raise ImageEditError(exc.public_message, exc.code, exc.status_code, exc.context) from exc
    else:
        raise ImageEditError('The model returned an unusable image')

    produced = _open_image(image_bytes, 'edited image')
    return {
        'bytes': image_bytes,
        'mime_type': mime_type or 'image/png',
        'width': produced.size[0],
        'height': produced.size[1],
        'model': deployment,
        'method': method,
        'size': normalized_size,
        'quality': quality if quality in SUPPORTED_IMAGE_QUALITIES else '',
        'background': background if background in SUPPORTED_IMAGE_BACKGROUNDS else '',
    }
