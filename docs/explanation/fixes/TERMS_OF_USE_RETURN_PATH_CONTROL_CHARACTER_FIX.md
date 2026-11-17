# Terms Of Use Return Path Control Character Fix (v0.261.448)

## Issue

After a person accepted the Terms of Use in the classic interface, the server redirected them to
the return path saved when they opened `/terms-of-use?next=...`. The check on that path kept a TAB
inside it, so `/terms-of-use?next=/%09/evil.example` was saved as `/<TAB>/evil.example`.
Werkzeug's `redirect` drops the TAB, as browsers do, so the response carried
`Location: //evil.example`, which a browser reads as another site. Opening a crafted link and
choosing **Accept and continue** sent the person off the site.

The problem was found by the security review of this release. The code predates it.

Fixed in version: **0.261.448**, tracked in `application/single_app/config.py`.

## Root cause

`normalize_terms_of_use_return_path` in `functions_terms_of_use.py` required a leading `/`, refused
a leading `//` and any backslash, and trimmed the ends of the value. It never looked inside the
path. A TAB, carriage return or line feed is removed when a URL is parsed, so the single-slash
check was made on text that later changed shape. A carriage return or line feed is refused by
Werkzeug with an error, which gave a 500 and no redirect; the TAB was the usable case.

The same function feeds the V2 terms endpoints in `route_backend_v2.py`. The V2 page opens the
saved path through `safeSameOriginUrl`, which already rejects control characters, so only the
classic accept redirect could be misused.

## Technical details

### Files modified

- `application/single_app/functions_terms_of_use.py`: `normalize_terms_of_use_return_path` now
  falls back when the value holds any control character (U+0000 to U+001F, or U+007F).
- `functional_tests/test_terms_of_use.py`: a regression test for the normalizer and for the
  redirect it feeds.

### Code change

```python
if any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
    return fallback
```

The check sits after the existing leading-slash, double-slash and backslash tests. The fallback is
the caller's own: `/` for the classic page and `/v2` for the V2 endpoints.

### Impact

- A `next` value with a control character no longer reaches a redirect. The person lands on the
  default page after accepting.
- Ordinary return paths are unchanged, including `/chats?conversationId=1` and a path that holds a
  percent-encoded TAB such as `/chats?x=%09y`, which stays encoded text and is not a control
  character.
- The decline redirect is a separate administrator-configured setting and is not changed.

## Validation

- `python -m pytest functional_tests\test_terms_of_use.py -q -p no:cacheprovider` passes all five
  tests.
- The new test, `test_return_path_with_a_control_character_never_becomes_an_off_site_redirect`,
  asserts that the TAB, carriage return, line feed, NUL and DEL variants fall back, then sends the
  normalized value through a real Flask `redirect` and checks that the `Location` header is `/`,
  never `//evil.example`.
- Run against the module as it was before the fix, the same test fails and the normalizer returns
  `'/\t/evil.example'`.

Before: `GET /terms-of-use?next=/%09/evil.example`, then **Accept and continue**, answered
`302 Location: //evil.example`. After: it answers `302 Location: /`.
