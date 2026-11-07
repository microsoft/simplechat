# functions_image_proposals.py
"""Import-light helpers for opt-in chat image proposal guidance.

These helpers only decide when image proposal cards are appropriate and describe the
``simpleimage`` fence the browser renders as an approval card. They live apart from
``functions_image_generation`` because that module builds image service clients, and
orchestration planning and answering must be able to read this guidance without
initializing those dependencies. ``functions_image_generation`` re-exports every name
here, so existing imports keep working.
"""

import re


INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE = 'simpleimage'
IMAGE_PROPOSAL_GUIDANCE_MARKER = '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]'
IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000

IMAGE_PROPOSAL_REQUEST_MARKERS = (
    'image',
    'illustration',
    'illustrate',
    'visual',
    'visualize',
    'visualise',
    'picture',
    'graphic',
    'diagram',
    'timeline',
    'slide',
    'powerpoint',
    'presentation',
    'poster',
    'infographic',
    'storyboard',
    'concept art',
    'map',
    'workflow',
    'process',
)


def image_generation_is_enabled(settings):
    """Return whether chat image generation is enabled in app settings."""
    return bool(isinstance(settings, dict) and settings.get('enable_image_generation'))


def user_request_supports_image_proposals(user_message):
    """Return true when a response could reasonably include optional image proposals."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    return any(marker in normalized_message for marker in IMAGE_PROPOSAL_REQUEST_MARKERS)


def build_image_proposal_guidance_message():
    """Return system guidance for assistant-authored image proposal cards."""
    return f"""{IMAGE_PROPOSAL_GUIDANCE_MARKER}
Image generation is available as an opt-in user action. Do not generate or embed images directly in the assistant answer. When one or more generated images would materially help the user, include compact fenced `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` JSON proposals inline at the point where each visual belongs. The browser will render each block as an approval card with approve, cancel, and edit controls.

Use this exact fenced block shape and valid JSON only:
```{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}
{{
  "version": 1,
  "visualId": "short_stable_id",
  "title": "Short image title",
  "description": "One sentence describing the proposed image.",
  "prompt": "Detailed image-generation prompt with subject, composition, labels, style, accessibility/readability constraints, and any source context needed.",
  "visualType": "timeline|diagram|illustration|infographic|map|scene|other",
  "slideNumber": 9,
  "context": "Brief source context"
}}
```

Rules:
- Only propose images when they are useful; omit the block when text alone is better.
- Place each `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` block immediately after the paragraph, bullet, slide section, or visual suggestion it supports. Do not collect image proposals at the end unless the end is the relevant section.
- For slide decks, keep each proposal inside the slide it supports, directly after the slide's visual suggestion, include list, or speaker note.
- Suggest zero, one, or multiple images based on value. One strong image proposal is fine; multiple distinct proposals are appropriate when several slides or sections benefit from visuals.
- Avoid decorative duplicates and avoid proposing images that do not directly support the surrounding content.
- Keep each prompt self-contained and under {IMAGE_PROPOSAL_PROMPT_MAX_LENGTH} characters.
- The user must approve before generation; never state that an image has already been created.
- Do not include secrets, private URLs, or unsupported instructions in the prompt.
""".strip()
