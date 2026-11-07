# Content Safety Violation Messages

Implemented in version: **0.250.061**

Related config.py version update: `application/single_app/config.py` is **0.250.061** for this implementation.

Current documentation version: **0.261.127**. Expanded chat checkpoints were implemented in **0.261.127**, tracked in the same configuration file.

## Overview

Administrators can configure the Markdown notice shown when Azure Content Safety blocks a submitted message. They can also choose whether safe trigger information, such as detected categories and severity, is included. The expanded chat checkpoints do not echo matched sensitive values.

## Dependencies

- Content Safety must be enabled in Admin Settings.
- The existing local `marked` and `DOMPurify` assets render and sanitize the saved Markdown in chat.

## Technical Specifications

- `content_safety_violation_message` stores the administrator-authored Markdown template.
- `content_safety_include_trigger_information` controls whether Content Safety details are appended to the message.
- The default message is `Your message was blocked by Content Safety.` and trigger information is enabled by default, preserving previous behavior.
- Blank or missing templates fall back to the default message, and saved templates are limited to 3,000 characters.
- Normal and streaming chat requests call the same backend formatter before persisting and returning a `safety` message.
- The chat UI renders safety messages through `DOMPurify.sanitize(marked.parse(...))`; no remote browser assets are added.
- The editor refreshes after the hidden Safety tab becomes visible, and Markdown-only edits enable Save Settings and synchronize to the submitted form value.

## Usage Instructions

1. Open **Admin Settings** and enable Content Safety.
2. Use the standard Markdown toolbar in **Safety Violation Message** to format the desired text.
3. Keep **Include Trigger Information** selected to append the block reason, categories, and severities. Clear it to show only the configured message.
4. Save the settings. Newly blocked chat messages use the saved configuration.

## Testing and Validation

- `functional_tests/test_content_safety_violation_message.py` validates the Markdown editor toolbar, default output, Markdown template preservation, trigger-information suppression, and blank-template fallback.
- Admin Settings validation verifies message normalization, seed defaults, and the form controls.
- Version was updated in `application/single_app/config.py` to `0.250.061` for traceability.

## Known Limitations

- The template applies to submitted-message Content Safety blocks. AI-output removal uses a separate neutral notice without repeating rejected text or blaming the user. Image-generation moderation keeps its existing dedicated copy.
- Saved messages affect newly created safety messages; historical conversation messages retain the text stored when they were created.
- Scanner outages are not findings. By default, they allow chat through without a user warning and record private not-checked metadata for administrator rechecks. See [Chat content checks]({{ '/explanation/features/CHAT_CONTENT_CHECKS/' | relative_url }}).
