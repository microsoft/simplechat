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
- Only ``gpt-image-*`` and legacy ``dall-e-2`` deployments expose ``/images/edits`` at all.
  Everything else falls back to regenerating the whole image, which is a different operation and
  is labelled as one.
"""

import base64
import io
import re

from PIL import Image

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

# Sizes the GPT image models emit. A value outside this set is rejected by the API, so the
# Controls tab is limited to these and anything else is simply not sent.
SUPPORTED_IMAGE_SIZES = ('1024x1024', '1024x1536', '1536x1024')
SUPPORTED_IMAGE_QUALITIES = ('low', 'medium', 'high')
SUPPORTED_IMAGE_BACKGROUNDS = ('transparent', 'opaque')

# An alpha at or below this counts as "edit here". Hard zero is what the client writes, but a
# mask that has been resized can carry a few interpolated values at region edges.
MASK_TRANSPARENT_THRESHOLD = 8

# Errors naming a parameter the deployment does not know. The optional parameters below are
# newer than some deployments and than the pinned SDK, so one retry without them turns a hard
# failure into a slightly less capable success.
_UNSUPPORTED_PARAMETER_PATTERN = re.compile(
    r'unsupported|unknown|unrecognized|not supported|invalid[_ ]?parameter|extra fields',
    re.IGNORECASE,
)


class ImageEditError(RuntimeError):
    """Raised when an image edit could not be produced."""


# How an image may be changed once it exists.
#
# `masked` means the deployment exposes /images/edits, so a region can be selected and only that
# region asked to change. `regenerate` means it does not, and the only thing on offer is
# producing a new image from a revised prompt.
IMAGE_EDIT_MODE_MASKED = 'masked'
IMAGE_EDIT_MODE_REGENERATE = 'regenerate'

# Models with an /images/edits endpoint. DALL-E 3 has none at all -- it can only generate -- so
# a deployment of it falls back to regeneration rather than failing at the point of use.
EDIT_CAPABLE_MODEL_MARKERS = ('gpt-image', 'dall-e-2', 'dalle-2')

# /images/edits is only routable on a recent preview API version. An older one fails in a way
# that reads like a broken deployment, so it is detected up front and reported against the
# setting that causes it.
MIN_IMAGE_EDIT_API_VERSION = '2025-04-01-preview'


def resolve_selected_image_model_name(settings):
    """Return the model behind the selected image deployment, or '' when it is not recorded.

    Admin settings persist ``{deploymentName, modelName}`` for the chosen deployment, but an
    APIM route records only a deployment name and settings saved before ``modelName`` was added
    have none either. An empty answer therefore means "unknown", not "none".
    """
    if not isinstance(settings, dict):
        return ''

    if settings.get('enable_image_gen_apim', False):
        return ''

    selected = (settings.get('image_gen_model') or {}).get('selected') or []
    if not selected or not isinstance(selected[0], dict):
        return ''
    return str(selected[0].get('modelName') or '').strip()


def image_api_version_supports_edit(api_version):
    """Return whether an Azure OpenAI API version can route /images/edits.

    Preview versions are dated, so the leading ``YYYY-MM-DD`` is compared. An unparseable value
    is treated as unsupported: guessing optimistically would trade a clear message here for an
    opaque failure after the reader has already selected a region.
    """
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

    Lives here rather than beside the generation helpers because those import the Cosmos and
    Azure OpenAI clients at module scope, and this has to stay resolvable from a test.
    """
    settings = settings if isinstance(settings, dict) else {}

    if not settings.get('enable_image_generation'):
        return {
            'mode': IMAGE_EDIT_MODE_REGENERATE,
            'enabled': False,
            'model_name': '',
            'reason': '',
        }

    model_name = resolve_selected_image_model_name(settings)
    normalized_model = model_name.lower()

    if not normalized_model:
        return {
            'mode': IMAGE_EDIT_MODE_REGENERATE,
            'enabled': True,
            'model_name': model_name,
            'reason': (
                'The image deployment does not report which model it runs, so changing part of '
                'an image cannot be offered. Re-selecting the deployment in Admin Settings '
                'records the model name.'
            ),
        }

    if not any(marker in normalized_model for marker in EDIT_CAPABLE_MODEL_MARKERS):
        return {
            'mode': IMAGE_EDIT_MODE_REGENERATE,
            'enabled': True,
            'model_name': model_name,
            'reason': (
                f'{model_name} can generate images but cannot edit them, so a change replaces '
                'the whole image.'
            ),
        }

    api_version = settings.get('azure_openai_image_gen_api_version')
    if not image_api_version_supports_edit(api_version):
        return {
            'mode': IMAGE_EDIT_MODE_REGENERATE,
            'enabled': True,
            'model_name': model_name,
            'reason': (
                f'Changing part of an image needs image generation API version '
                f'{MIN_IMAGE_EDIT_API_VERSION} or newer. It is currently set to '
                f'{api_version or "nothing"}.'
            ),
        }

    return {
        'mode': IMAGE_EDIT_MODE_MASKED,
        'enabled': True,
        'model_name': model_name,
        'reason': '',
    }



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


def normalize_mask(mask_data_url, width, height, regions=0):
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

    if len(mask_bytes) > MAX_MASK_BYTES:
        raise ImageEditError('The selected region is too large to send')

    mask = _open_image(mask_bytes, 'selected region').convert('RGBA')
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
    if len(encoded) > MAX_MASK_BYTES:
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


def prepare_source_image(mime_type, image_bytes):
    """Return the image to edit as bytes the API accepts, with its true dimensions.

    The dimensions matter more than the format: the mask has to match them exactly, and the only
    trustworthy source for them is the image itself. A browser reporting its own idea of the
    size would be reporting the size it laid the image out at.
    """
    if len(image_bytes or b'') > MAX_SOURCE_IMAGE_BYTES:
        raise ImageEditError('This image is too large to edit')

    image = _open_image(image_bytes, 'image')
    width, height = image.size

    normalized_mime = str(mime_type or '').strip().lower()
    if normalized_mime in PASSTHROUGH_IMAGE_MIME_TYPES:
        return {
            'bytes': image_bytes,
            'mime_type': normalized_mime,
            'file_name': f"image.{'jpg' if normalized_mime == 'image/jpeg' else normalized_mime.split('/')[1]}",
            'width': width,
            'height': height,
        }

    buffer = io.BytesIO()
    image.convert('RGBA').save(buffer, format='PNG')
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

    source_mime, source_bytes = load_current_image_bytes(message_doc, complete_content)
    source_image = prepare_source_image(source_mime, source_bytes)

    capability = resolve_image_edit_capability(settings)
    mask = None
    if revision_origin == ORIGIN_AI:
        normalized_instruction = str(instruction or '').strip()
        if not normalized_instruction:
            raise ImageEditError('Describe the change you want')
        # A region is only meaningful when the deployment can act on one. Sending a mask to a
        # model without an edit endpoint would silently discard it, so it is dropped here and
        # the interface says up front that the whole image will be replaced.
        if capability['mode'] == IMAGE_EDIT_MODE_MASKED:
            mask = normalize_mask(
                mask_data_url,
                source_image['width'],
                source_image['height'],
                regions=mask_regions,
            )
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


def _optional_parameters(quality='', background='', input_fidelity=''):
    """Return the newer, optional API parameters as a body fragment.

    Sent through ``extra_body`` rather than as keyword arguments deliberately. ``quality``,
    ``background`` and ``input_fidelity`` do not exist in every version of the SDK -- the
    installed one has none of them on ``images.edit`` -- so passing them directly raises
    ``TypeError`` depending on which version is present. ``extra_body`` merges into the same
    request body on every 1.x release, which makes this work against both the pinned SDK and an
    older one without version sniffing.
    """
    optional = {}
    if quality in SUPPORTED_IMAGE_QUALITIES:
        optional['quality'] = quality
    if background in SUPPORTED_IMAGE_BACKGROUNDS:
        optional['background'] = background
    if input_fidelity in ('high', 'low'):
        optional['input_fidelity'] = input_fidelity
    return optional


def _call_with_optional_parameters(operation, optional):
    """Run an images call, retrying once without the optional parameters if they are refused.

    A deployment that predates ``input_fidelity`` rejects the whole request rather than ignoring
    the field it does not know. Retrying without them produces a slightly less controlled image,
    which is a much better outcome than refusing to edit at all on an older deployment.
    """
    try:
        return operation(optional)
    except Exception as exc:
        if not optional or not _UNSUPPORTED_PARAMETER_PATTERN.search(str(exc)):
            raise
        from functions_appinsights import log_event

        log_event(
            '[IMAGE_EDIT] Retrying without optional image parameters',
            extra={'parameters': sorted(optional), 'error': str(exc)[:400]},
        )
        return operation({})


def request_image_edit(
    settings,
    source_image,
    prompt,
    mask=None,
    size='',
    quality='',
    background='',
):
    """Ask the model for an edited image, returning its bytes and how it was produced.

    Falls back to generating a new image when the deployment has no edit endpoint. The fallback
    is reported in the result as ``method`` rather than being hidden, because "part of this
    image changed" and "this is a different image" are different outcomes and the history has to
    be able to say which happened.
    """
    from functions_appinsights import log_event
    from functions_image_generation import (
        extract_generated_image_source,
        resolve_image_generation_client,
        resolve_generated_image_bytes,
    )

    capability = resolve_image_edit_capability(settings)
    client, deployment = resolve_image_generation_client(settings)

    normalized_size = size if size in SUPPORTED_IMAGE_SIZES else ''
    optional = _optional_parameters(
        quality=quality,
        background=background,
        # Only meaningful alongside a real edit, and only for the GPT image models.
        input_fidelity='high' if capability['mode'] == IMAGE_EDIT_MODE_MASKED else '',
    )

    if capability['mode'] == IMAGE_EDIT_MODE_MASKED:
        def edit(extra):
            arguments = {
                'model': deployment,
                'prompt': prompt,
                'n': 1,
                'image': (
                    source_image['file_name'],
                    source_image['bytes'],
                    source_image['mime_type'],
                ),
            }
            if mask:
                arguments['mask'] = ('mask.png', mask['bytes'], 'image/png')
            if normalized_size:
                arguments['size'] = normalized_size
            if extra:
                arguments['extra_body'] = extra
            return client.images.edit(**arguments)

        try:
            response = _call_with_optional_parameters(edit, optional)
        except Exception as exc:
            log_event(
                f'[IMAGE_EDIT] Edit request failed: {exc}',
                extra={'deployment': deployment},
            )
            raise ImageEditError('The image could not be edited') from exc

        method = 'edit'
    else:
        def generate(extra):
            arguments = {'model': deployment, 'prompt': prompt, 'n': 1}
            if normalized_size:
                arguments['size'] = normalized_size
            if extra:
                arguments['extra_body'] = extra
            return client.images.generate(**arguments)

        try:
            response = _call_with_optional_parameters(generate, optional)
        except Exception as exc:
            log_event(
                f'[IMAGE_EDIT] Regeneration request failed: {exc}',
                extra={'deployment': deployment},
            )
            raise ImageEditError('The image could not be regenerated') from exc

        method = 'regenerate'

    try:
        generated_source = extract_generated_image_source(response)
    except ValueError as exc:
        raise ImageEditError('The model returned no image') from exc

    if is_external_image_url(generated_source) or generated_source.startswith('data:image/'):
        mime_type, image_bytes = resolve_generated_image_bytes(generated_source)
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
