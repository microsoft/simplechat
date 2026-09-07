# Synthetic Streaming For Completed Responses

## Overview

SimpleChat supports one response mode: streaming. The non-streaming chat path is
legacy and is being retired.

Some responses cannot be streamed by the model. The clearest case is tool
calling: a tool call has to arrive complete before it can be executed, so the
request is made without streaming. Some providers also expose no streaming
surface at all.

Those responses still have to reach the browser through the stream. Synthetic
streaming is how a completed answer is delivered as a stream.

**Implemented in version: 0.261.018**

## The problem it solves

The behaviour already existed in miniature. The Anthropic adapter's tool-calling
path took a completed response and pushed it through the streaming interface —
but as a single chunk.

That satisfies the interface and fails the user. The response arrives as nothing,
nothing, nothing, then the entire answer at once. For a long answer that reads as
a hang, and because SimpleChat leans heavily on agents and plugins, this was a
common path rather than an exotic one.

## Architecture

### Chunking

`iter_synthetic_stream_text_chunks(text, chunk_characters=24)` splits completed
text at word boundaries into stream-sized chunks.

The critical property is that **chunking is lossless**. The frontend accumulates
chunks by string concatenation, so any lost or duplicated character would corrupt
the rendered answer. The splitter tokenizes with `\S+\s*|\s+`, which preserves
every character including runs of whitespace and newlines, so concatenating every
chunk reproduces the input exactly.

```python
"".join(iter_synthetic_stream_text_chunks(text)) == text   # always true
```

Short answers stay a single chunk, because there is nothing to animate.

### Message assembly

`_iter_synthetic_stream_messages` turns one completed `ChatMessageContent` into
several `StreamingChatMessageContent` messages:

| Content | Placement |
|---|---|
| Text | Split across every chunk |
| Function calls and other non-text items | The final message only |
| `finish_reason` | The final message only |
| `metadata`, including usage | The final message only |

Non-text items ride on the final message because a function call cannot be
partially delivered. The finish reason and metadata are emitted exactly once so
that token usage is not multiplied by the number of chunks.

### Streaming usage reporting

`stream_options` is how an OpenAI-compatible streaming response reports token
usage. It was previously stripped from every OpenAI-compatible request, which
suppressed usage reporting for all of them, including endpoints that support it.

Support is now declared per provider through `supports_stream_options` on the
provider registry entry, and the option is dropped only for surfaces that reject
it. OpenAI declares support; other providers keep the conservative default until
their support is confirmed.

## Usage

Any adapter that must return a completed answer through the streaming interface
should use the chunker rather than yielding one message:

```python
from model_endpoint_clients import iter_synthetic_stream_text_chunks

for chunk_text in iter_synthetic_stream_text_chunks(completed_text):
    yield build_streaming_message(chunk_text)
```

The provider registry's `supports_streaming` flag records whether an API type can
stream natively, so a future adapter can decide whether to wrap.

## Testing and validation

`functional_tests/test_custom_model_endpoint_synthetic_streaming.py` covers:

- lossless chunking across eight samples, including empty input, leading and
  trailing whitespace, embedded newlines, a 200-character unbroken token, and
  multi-byte Unicode including an emoji;
- a long answer being split into several chunks while a short one stays single;
- function calls surviving as exactly one item, on the final chunk, with the text
  still reconstructing exactly;
- the finish reason and usage metadata appearing only on the final chunk;
- `stream_options` no longer being dropped unconditionally.

## Known limitations

- The terminal `done` event guarantee on the server's SSE route is unchanged in
  this version. The frontend errors if a stream ends without one, so that
  guarantee is worth making explicit on every failure path.
- The legacy non-streaming `/api/chat` route still exists and is still reachable
  through the compatibility bridge. It is expected to be deprecated and removed
  in a later release.
- `supports_streaming` is declared on provider registry entries but is not yet
  used to wrap a non-streaming provider automatically, because every currently
  registered provider streams natively.
