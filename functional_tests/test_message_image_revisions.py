#!/usr/bin/env python3
"""
Functional test for generated image revision storage and editing.
Version: 0.261.050
Implemented in: 0.261.050

This test ensures a generated image can be changed in place, versioned and restored without the
conversation filling up with near-duplicate images, and that the two details most easily got
silently wrong are right.

The first is **mask polarity**. In the images API a fully transparent pixel marks the region to
edit and an opaque one is preserved. Invert that and every edit changes the whole image *except*
the part that was selected, which looks like a model failure rather than a bug and would survive
review. So the polarity is asserted end to end against a real PNG rather than trusted.

The second is **capability**. DALL-E 3 has no edit endpoint at all, and an APIM deployment
records no model name, so offering region editing on either would fail only after a reader had
already selected a region and waited.
"""

import base64
import io
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'application',
        'single_app',
    )
)

from PIL import Image  # noqa: E402

from test_support.versioning import assert_app_version_at_least  # noqa: E402

from functions_message_image_revisions import (  # noqa: E402
    MAX_REVISIONS,
    ORIGIN_ORIGINAL,
    ImageRevisionConflictError,
    ImageRevisionError,
    append_image_chat_turn,
    apply_image_revision,
    current_image_prompt,
    read_image_chat,
    read_image_revisions,
    read_revisions,
    resolve_current_revision,
    resolve_image_message_content,
    resolve_served_revision,
    serialize_image_revisions,
    set_current_image_revision,
)
from functions_image_edit import (  # noqa: E402
    ImageEditError,
    compose_edit_prompt,
    image_api_version_supports_edit,
    normalize_mask,
    prepare_source_image,
    resolve_image_edit_capability,
    _optional_parameters,
)

IMPLEMENTED_IN = "0.261.050"

MESSAGE_ID = "conv123_image_1700000000_4242"
BLOB = {
    'blob_container': 'chat',
    'blob_path': 'user/conv123/images/msg/revision-abc.png',
    'mime_type': 'image/png',
    'width': 1024,
    'height': 1024,
}


def _image_message(content='data:image/png;base64,AAAA', prompt='a cat on a wall'):
    return {
        'id': MESSAGE_ID,
        'conversation_id': 'conv123',
        'role': 'image',
        'content': content,
        'prompt': prompt,
        'model_deployment_name': 'gpt-image-1',
        'metadata': {},
    }


def _mask_png(size, holes):
    """A mask that is opaque everywhere except inside each hole, which is where edits apply."""
    mask = Image.new('RGBA', size, (0, 0, 0, 255))
    pixels = mask.load()
    for (x0, y0, x1, y1) in holes:
        for x in range(x0, x1):
            for y in range(y0, y1):
                pixels[x, y] = (0, 0, 0, 0)
    buffer = io.BytesIO()
    mask.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _png_bytes(size, mode='RGB'):
    buffer = io.BytesIO()
    Image.new(mode, size, (10, 20, 30) if mode == 'RGB' else (10, 20, 30, 255)).save(
        buffer, format='PNG'
    )
    return buffer.getvalue()


def test_version_is_at_least_the_implementing_release():
    """The feature must not appear in a build older than the one that introduced it."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_an_unedited_image_is_left_completely_alone():
    """Nothing changes for the overwhelmingly common case of an image nobody has touched."""
    message = _image_message()

    assert read_image_revisions(message) == {}
    assert serialize_image_revisions(read_image_revisions(message)) == {}
    assert resolve_served_revision(message) is None, (
        "an unedited image must fall through to its own stored content"
    )
    assert resolve_image_message_content(message, f'/api/image/{MESSAGE_ID}') == message['content']
    assert 'image_revisions' not in message['metadata']
    print("  ok  an unedited image resolves exactly as it did before revisions existed")


def test_the_original_is_seeded_from_the_message_not_the_request():
    """"Restore the original" cannot be pointed at a prompt the caller invented."""
    message = _image_message(prompt='the real prompt')
    apply_image_revision(message, BLOB, origin='ai', prompt='an edited prompt', instruction='x')

    revisions = read_revisions(read_image_revisions(message))
    assert revisions[0]['origin'] == ORIGIN_ORIGINAL
    assert revisions[0]['prompt'] == 'the real prompt', (
        "revision zero must describe the image as generated, taken from the message itself"
    )
    assert 'blob_path' not in revisions[0], (
        "the original stores no bytes; it *is* the message's own content, which for a chunked "
        "image could not be copied into metadata at all"
    )
    print("  ok  the original is seeded from the message and stores no bytes")


def test_an_edited_image_is_served_from_its_own_revision():
    """The content resolves to a URL carrying the revision, which is what busts the cache."""
    message = _image_message()
    entry = apply_image_revision(message, BLOB, origin='ai', instruction='orange sky')
    revision_id = entry['revisions'][1]['id']

    resolved = resolve_image_message_content(message, f'/api/image/{MESSAGE_ID}')
    assert resolved == f'/api/image/{MESSAGE_ID}?rev={revision_id}', resolved

    # The collaboration endpoint already carries a path, and may carry a query.
    collaborative = resolve_image_message_content(
        message, '/api/collaboration/conversations/c/images/m?x=1'
    )
    assert collaborative.endswith(f'&rev={revision_id}'), collaborative

    served = resolve_served_revision(message, revision_id)
    assert served['blob_path'] == BLOB['blob_path']

    # An unknown revision is answered with whatever is current rather than with an error: the
    # parameter exists to change the URL, so a stale link should still show the live image.
    assert resolve_served_revision(message, 'not-a-revision')['blob_path'] == BLOB['blob_path']
    print("  ok  an edited image is served from its revision, and a stale rev degrades sanely")


def test_restoring_the_original_still_yields_a_usable_url():
    """The original has no blob of its own, but the endpoint resolves it perfectly well.

    Returning the message's stored content here looks reasonable and is wrong twice over. A
    collaboration mirror stores a placeholder rather than a URL, so handing it back would
    replace a working image with that placeholder for every participant, permanently. And a
    legacy chunked image stores only its first chunk, which is a truncated data URL.
    """
    message = _image_message()
    entry = apply_image_revision(message, BLOB, origin='ai', instruction='orange sky')
    original_id = entry['revisions'][0]['id']

    set_current_image_revision(message, original_id)
    assert resolve_served_revision(message) is None, (
        "the original has no blob, so the serve route must fall through to the message's bytes"
    )
    assert resolve_image_message_content(message, f'/api/image/{MESSAGE_ID}') == (
        f'/api/image/{MESSAGE_ID}?rev={original_id}'
    ), "the endpoint must still be used, addressed by the original's id"

    # The case that would break a shared conversation permanently.
    mirror = _image_message(content='[GENERATED_IMAGE]')
    mirror_entry = apply_image_revision(mirror, BLOB, origin='ai', instruction='x')
    set_current_image_revision(mirror, mirror_entry['revisions'][0]['id'])
    resolved = resolve_image_message_content(
        mirror, '/api/collaboration/conversations/c/images/m'
    )
    assert resolved.startswith('/api/collaboration/'), resolved
    assert '[GENERATED_IMAGE]' not in resolved, (
        "a shared mirror's placeholder must never be handed back as an image URL"
    )

    # A legacy chunked image stores only chunk zero, which is not a usable data URL.
    chunked = _image_message(content='data:image/png;base64,FIRSTCHUNKONLY')
    chunked['metadata']['is_chunked'] = True
    chunked_entry = apply_image_revision(chunked, BLOB, origin='ai', instruction='x')
    set_current_image_revision(chunked, chunked_entry['revisions'][0]['id'])
    assert resolve_image_message_content(chunked, f'/api/image/{MESSAGE_ID}').startswith(
        f'/api/image/{MESSAGE_ID}?rev='
    )

    # Editing after restoring appends rather than truncating: the history is a record of what
    # happened, not a stack.
    apply_image_revision(message, BLOB, origin='ai', instruction='second')
    revisions = read_revisions(read_image_revisions(message))
    assert len(revisions) == 3 and read_image_revisions(message)['current'] == 2
    print("  ok  restoring the original yields a usable URL, and editing afterwards appends")


def test_blob_locations_never_reach_the_browser():
    """Where the bytes live is storage detail, and the serializer is what a route returns."""
    message = _image_message()
    apply_image_revision(
        message,
        BLOB,
        origin='ai',
        instruction='orange sky',
        mask={'coverage': 0.25, 'regions': 2},
        author_name='Ada Lovelace',
    )

    public = serialize_image_revisions(read_image_revisions(message))
    leaked = sorted(
        key
        for revision in public['revisions']
        for key in revision
        if 'blob' in key or 'container' in key
    )
    assert not leaked, f"storage detail leaked to the client: {leaked}"

    edited = public['revisions'][1]
    assert edited['has_mask'] is True and edited['mask_coverage'] == 0.25
    assert edited['author_name'] == 'Ada Lovelace'
    print("  ok  the public shape carries history without storage detail")


def test_a_revision_must_carry_its_bytes():
    """A revision with nowhere to read from would silently discard a generation already paid for."""
    message = _image_message()
    for bad in (None, {}, {'blob_container': 'chat'}, {'blob_path': 'x'}):
        try:
            apply_image_revision(message, bad, origin='ai', instruction='x')
        except ImageRevisionError:
            continue
        raise AssertionError(f"a revision without a blob location was accepted: {bad!r}")

    try:
        apply_image_revision(message, BLOB, origin=ORIGIN_ORIGINAL)
    except ImageRevisionError:
        pass
    else:
        raise AssertionError("a revision was allowed to masquerade as the original")
    print("  ok  a revision without stored bytes, or posing as the original, is refused")


def test_pruning_keeps_the_original_pinned():
    """However many edits are made, the image as generated stays recoverable."""
    message = _image_message()
    for index in range(MAX_REVISIONS + 15):
        apply_image_revision(message, BLOB, origin='ai', instruction=f'change {index}')

    entry = read_image_revisions(message)
    revisions = read_revisions(entry)
    assert len(revisions) == MAX_REVISIONS, len(revisions)
    assert revisions[0]['origin'] == ORIGIN_ORIGINAL, "the original must never be pruned"
    assert revisions[0]['prompt'] == 'a cat on a wall'
    assert entry['current'] == MAX_REVISIONS - 1
    print(f"  ok  pruning holds at {MAX_REVISIONS} versions and never drops the original")


def test_a_concurrent_edit_is_reported_rather_than_overwritten():
    """Two participants editing one shared image must not silently clobber each other."""
    message = _image_message()
    apply_image_revision(message, BLOB, origin='ai', instruction='first')

    try:
        apply_image_revision(
            message, BLOB, origin='ai', instruction='second', expected_revision_count=1
        )
    except ImageRevisionConflictError:
        pass
    else:
        raise AssertionError("an edit written against a stale count overwrote another")

    # The matching count still succeeds, so the guard is not simply always failing.
    apply_image_revision(
        message, BLOB, origin='ai', instruction='second', expected_revision_count=2
    )
    print("  ok  a stale edit is refused and a current one is accepted")


def test_the_edit_prompt_builds_on_the_version_on_screen():
    """Successive edits accumulate instead of each being applied to the original."""
    message = _image_message(prompt='a cat')
    assert current_image_prompt(message) == 'a cat'

    apply_image_revision(message, BLOB, origin='ai', prompt='a cat, orange sky', instruction='x')
    assert current_image_prompt(message) == 'a cat, orange sky', (
        "an edit must be composed against what the reader is looking at"
    )
    print("  ok  the prompt follows the version currently showing")


def test_the_transcript_stays_with_the_image():
    """A follow-up needs something to refer to, and none of it is conversation history."""
    message = _image_message()
    try:
        append_image_chat_turn(message, 'user', 'orange sky')
    except ImageRevisionError:
        pass
    else:
        raise AssertionError("a turn was stored against an image with no versions")

    apply_image_revision(message, BLOB, origin='ai', instruction='orange sky')
    append_image_chat_turn(message, 'user', 'orange sky')
    append_image_chat_turn(message, 'assistant', 'a cat, orange sky')

    assert read_image_chat(read_image_revisions(message)) == [
        {'role': 'user', 'content': 'orange sky'},
        {'role': 'assistant', 'content': 'a cat, orange sky'},
    ]

    for bad_role in ('system', 'image', ''):
        try:
            append_image_chat_turn(message, bad_role, 'x')
        except ImageRevisionError:
            continue
        raise AssertionError(f"an unsupported chat role was stored: {bad_role!r}")
    print("  ok  the sub-conversation is kept with the image and rejects stray roles")


def test_mask_polarity_is_transparent_means_edit():
    """The whole feature is wrong if this is inverted, and it would still look plausible."""
    mask = normalize_mask(_mask_png((100, 100), [(0, 0, 50, 50)]), 100, 100, regions=1)
    assert mask is not None

    rendered = Image.open(io.BytesIO(mask['bytes'])).convert('RGBA')
    assert rendered.getpixel((10, 10))[3] == 0, (
        "the selected region must be TRANSPARENT: that is what the API edits"
    )
    assert rendered.getpixel((90, 90))[3] == 255, (
        "everything not selected must be OPAQUE, which is what preserves it"
    )
    assert mask['coverage'] == 0.25, mask['coverage']
    assert mask['covers_everything'] is False
    print("  ok  transparent marks the region to edit and opaque preserves the rest")


def test_a_mask_selecting_nothing_is_reported_as_absent():
    """An all-opaque mask asks the model to change nothing while still being charged for."""
    assert normalize_mask(_mask_png((80, 80), []), 80, 80) is None
    assert normalize_mask(None, 80, 80) is None
    assert normalize_mask('', 80, 80) is None

    covering = normalize_mask(_mask_png((40, 40), [(0, 0, 40, 40)]), 40, 40)
    assert covering['covers_everything'] is True and covering['coverage'] == 1.0
    print("  ok  an empty selection is absent, and a full one is recognised as such")


def test_a_mask_is_resized_to_the_image_it_masks():
    """The API requires identical dimensions, and a browser's idea of size is its layout size."""
    mask = normalize_mask(_mask_png((50, 50), [(0, 0, 25, 50)]), 100, 200)
    assert (mask['width'], mask['height']) == (100, 200), mask
    assert abs(mask['coverage'] - 0.5) < 0.02, mask['coverage']

    rendered = Image.open(io.BytesIO(mask['bytes'])).convert('RGBA')
    assert rendered.size == (100, 200)
    # Nearest neighbour, so a hard mask edge does not become partial alpha under resizing.
    assert rendered.getpixel((10, 10))[3] == 0
    assert rendered.getpixel((90, 10))[3] == 255
    print("  ok  a mask is resized to the source image without softening its edges")


def test_a_transparent_source_image_is_not_confused_with_a_mask():
    """An image generated with a transparent background has alpha of its own."""
    prepared = prepare_source_image('image/png', _png_bytes((64, 64), mode='RGBA'))
    assert (prepared['width'], prepared['height']) == (64, 64)
    assert prepared['mime_type'] == 'image/png'

    # The mask's alpha is independent of the image's, so masking such an image still works.
    mask = normalize_mask(_mask_png((64, 64), [(0, 0, 32, 64)]), 64, 64)
    assert mask is not None and abs(mask['coverage'] - 0.5) < 0.01
    print("  ok  an image's own alpha is never conflated with the mask's")


def test_junk_is_refused_before_anything_is_generated():
    """A malformed request should cost a message, not a generation."""
    for bad in ('data:image/png;base64,zzzz', 'not base64 at all!!'):
        try:
            normalize_mask(bad, 10, 10)
        except ImageEditError:
            continue
        raise AssertionError(f"a junk mask was accepted: {bad!r}")

    try:
        prepare_source_image('image/png', b'')
    except ImageEditError:
        pass
    else:
        raise AssertionError("empty image bytes were accepted")
    print("  ok  an unreadable mask or image is refused up front")


def test_the_prompt_describes_the_finished_image():
    """The API's own guidance: describing the whole result preserves the unmasked parts."""
    mask = normalize_mask(_mask_png((60, 60), [(0, 0, 20, 20)]), 60, 60)
    prompt = compose_edit_prompt('a cat on a wall', 'make the sky orange', mask)

    assert 'a cat on a wall' in prompt, "the existing image must be described"
    assert 'make the sky orange' in prompt
    assert 'transparent region' in prompt, "a real region must be named in the prompt"
    assert 'complete resulting image' in prompt

    # A mask covering everything is not a region, so it is not described as one.
    everything = normalize_mask(_mask_png((30, 30), [(0, 0, 30, 30)]), 30, 30)
    assert 'transparent region' not in compose_edit_prompt('a cat', 'orange', everything)
    assert 'transparent region' not in compose_edit_prompt('a cat', 'orange', None)

    try:
        compose_edit_prompt('a cat', '   ')
    except ImageEditError:
        pass
    else:
        raise AssertionError("an empty instruction produced a prompt")
    print("  ok  the composed prompt describes the finished image, and the region when there is one")


def test_capability_matches_what_the_deployment_can_actually_do():
    """Region editing is offered only where /images/edits exists and is routable."""

    def capability(**overrides):
        settings = {
            'enable_image_generation': True,
            'azure_openai_image_gen_api_version': '2025-04-01-preview',
            'image_gen_model': {'selected': [{'deploymentName': 'd', 'modelName': 'gpt-image-1'}]},
        }
        settings.update(overrides)
        return resolve_image_edit_capability(settings)

    def with_model(name):
        return capability(image_gen_model={'selected': [{'deploymentName': 'd', 'modelName': name}]})

    for editable in ('gpt-image-1', 'gpt-image-1-mini', 'gpt-image-2', 'dall-e-2'):
        assert with_model(editable)['mode'] == 'masked', editable

    # DALL-E 3 has no edit endpoint at all. Offering a region would fail after the reader had
    # already selected one and waited for the request.
    refused = with_model('dall-e-3')
    assert refused['mode'] == 'regenerate' and 'cannot edit' in refused['reason']

    # An APIM route records no model name, so the capability is unknown and the safe answer wins.
    unknown = capability(enable_image_gen_apim=True)
    assert unknown['mode'] == 'regenerate' and 'does not report' in unknown['reason']
    assert capability(image_gen_model={'selected': [{'deploymentName': 'd'}]})['mode'] == 'regenerate'

    # An old API version cannot route the request, and the reason names the setting to change.
    stale = capability(azure_openai_image_gen_api_version='2024-02-01')
    assert stale['mode'] == 'regenerate'
    assert '2025-04-01-preview' in stale['reason'] and '2024-02-01' in stale['reason']

    assert resolve_image_edit_capability({'enable_image_generation': False})['enabled'] is False
    assert resolve_image_edit_capability(None)['enabled'] is False

    assert image_api_version_supports_edit('2025-04-01-preview') is True
    assert image_api_version_supports_edit('2025-03-31-preview') is False
    assert image_api_version_supports_edit('nonsense') is False
    print("  ok  capability tracks the model, the API version and the APIM unknown")


def test_optional_parameters_are_filtered_to_what_the_api_accepts():
    """These travel in extra_body, so a typo would reach the service rather than raise here."""
    assert _optional_parameters(quality='high', background='transparent', input_fidelity='high') == {
        'quality': 'high',
        'background': 'transparent',
        'input_fidelity': 'high',
    }
    assert _optional_parameters(quality='ultra', background='rainbow', input_fidelity='max') == {}
    assert _optional_parameters() == {}
    print("  ok  only recognised optional parameters are sent")


def test_an_oversized_image_is_refused_before_it_is_decoded():
    """The pixel limit only protects anything if it runs before the raster is allocated.

    Pillow's ``Image.open`` reads the header; ``load`` allocates the pixels. Checking the
    dimensions after loading -- the obvious way to write it -- would mean a file declaring
    enormous dimensions had already been expanded into memory by the time it was rejected,
    which is exactly what the limit exists to stop.

    Asserted by watching whether ``load`` is reached at all, rather than by timing or by
    measuring memory, both of which would be flaky.
    """
    import functions_image_edit as module

    loaded = []
    real_open = module.Image.open

    class _Probe:
        def __init__(self, image):
            self._image = image

        @property
        def size(self):
            # A plausible header for a decompression bomb: small file, enormous raster.
            return (60000, 60000)

        def load(self):
            loaded.append(True)
            return self._image.load()

        def __getattr__(self, name):
            return getattr(self._image, name)

    module.Image.open = lambda *args, **kwargs: _Probe(real_open(*args, **kwargs))
    try:
        try:
            module.prepare_source_image('image/png', _png_bytes((8, 8)))
        except ImageEditError as exc:
            assert 'too large' in str(exc), exc
        else:
            raise AssertionError('an image declaring 60000x60000 pixels was accepted')
    finally:
        module.Image.open = real_open

    assert not loaded, (
        'the raster was decoded before the dimension check, so the limit protects nothing'
    )
    print("  ok  an oversized image is rejected from its header, before being decoded")


def test_serialized_history_survives_a_round_trip():
    """The client reads this shape, so its own fields have to be present and stable."""
    message = _image_message()
    apply_image_revision(
        message,
        BLOB,
        origin='ai',
        instruction='orange sky',
        model='gpt-image-1',
        method='edit',
        size='1024x1024',
        quality='high',
    )
    public = serialize_image_revisions(read_image_revisions(message))

    assert public['current'] == 1
    latest = public['revisions'][1]
    for field in ('id', 'origin', 'prompt', 'instruction', 'timestamp', 'model', 'method'):
        assert field in latest, f"the client reads {field} and it is missing"
    assert latest['method'] == 'edit' and latest['size'] == '1024x1024'
    assert resolve_current_revision(read_image_revisions(message))['id'] == latest['id']
    print("  ok  the serialized history carries every field the client reads")


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_an_unedited_image_is_left_completely_alone,
        test_the_original_is_seeded_from_the_message_not_the_request,
        test_an_edited_image_is_served_from_its_own_revision,
        test_restoring_the_original_still_yields_a_usable_url,
        test_blob_locations_never_reach_the_browser,
        test_a_revision_must_carry_its_bytes,
        test_pruning_keeps_the_original_pinned,
        test_a_concurrent_edit_is_reported_rather_than_overwritten,
        test_the_edit_prompt_builds_on_the_version_on_screen,
        test_the_transcript_stays_with_the_image,
        test_mask_polarity_is_transparent_means_edit,
        test_a_mask_selecting_nothing_is_reported_as_absent,
        test_a_mask_is_resized_to_the_image_it_masks,
        test_a_transparent_source_image_is_not_confused_with_a_mask,
        test_junk_is_refused_before_anything_is_generated,
        test_the_prompt_describes_the_finished_image,
        test_capability_matches_what_the_deployment_can_actually_do,
        test_optional_parameters_are_filtered_to_what_the_api_accepts,
        test_an_oversized_image_is_refused_before_it_is_decoded,
        test_serialized_history_survives_a_round_trip,
    ]

    failures = 0
    for test in tests:
        print(f"\n{test.__name__}")
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {exc}")
            import traceback

            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
