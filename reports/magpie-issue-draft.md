# Draft: magpie issue

Target repo: `yetone/magpie` (issues enabled, MIT, no issue templates).
Suggested title (matches repo convention of `area: symptom`):

    gateway: protocol translation drops caller correlation carriers (body metadata, X-Cid header, URL query string)

---

## What happens

When a provider is configured in translation mode (only `url=`, no `anthropic=` / `responses=`),
a request that arrives as Anthropic Messages or OpenAI Responses is translated to OpenAI Chat
before it goes upstream. During that translation, every caller-supplied correlation carrier I
tried is dropped:

- `metadata` object in the request body,
- `X-Cid` request header,
- `cid` in the URL query string.

The upstream sees a normal Chat completion request with none of them, so a caller cannot match
an upstream observation back to the request that produced it.

Configure the same provider in pass-through mode (`url=` + `anthropic=` + `responses=`) and all
three carriers survive unchanged.

## Environment

- magpie 0.1.2687, `magpie-cli-windows-amd64.exe`,
  sha256 `1fa70112864d6d39d6e5e97d8895248085296a483843f4f5cf6c26bfe869a83f`
- Windows 11, loopback only (`MAGPIE_ADDR=127.0.0.1:3425`, `DO_NOT_TRACK=1`)
- upstream is a local recording stub, so "what arrived" is exact bytes, not a log summary

## Minimal reproduction

1. Start a stub that records method, path, query string, headers and raw body, then answers with SSE
   (magpie streams upstream even for non-streaming client requests, so a non-SSE stub fails with
   `did not stream`).
2. `magpie provider set stub url=http://127.0.0.1:18080 models=stub-model`
3. POST an Anthropic request to `http://127.0.0.1:3425/v1/messages?cid=abc123` with:
   - header `X-Cid: abc123`
   - body `"metadata": {"cid": "abc123"}`
4. Inspect what the stub received.

Expected: at least one of the three survives, so the caller can correlate.
Actual: none of them present. Repeating the same call with `provider set stub url=... anthropic=... responses=...`
makes all three survive.

Reproduction harness (public, synthetic payloads only, no keys, no real provider calls):
`https://github.com/coeo91/headroom-chain-test`
The two configurations are described in RUNBOOK §6.0, and the raw comparison is in
`RESULTS-SAMEMACHINE.md` vs `RESULTS-PASSTHROUGH.md`.

## Evidence from the test run

Ten cases, 3 repetitions each. In translation mode, exactly the two cases that arrive in a
non-Chat protocol failed correlation and had to be matched by content instead:

    arm 0M-L  63 sent / 63 received / 0 unmatched, of which 6 recovered by content fallback
    arm A-L   63 / 63 / 0, 6 by fallback
    arm B-L   63 / 63 / 0, 6 by fallback

In pass-through mode there was no fallback at all — cid matched on every one of the 63 requests
per arm. So the loss tracks the translation path, not the surrounding proxies.

## Impact

- Any caller that relies on request correlation (tracing, per-request accounting, A/B comparison)
  loses attribution as soon as magpie translates.
- Clients that put per-request parameters in the query string (common for proxies and test
  harnesses) see them silently disappear.
- Header and body `metadata` are the conventional places for this, so both are affected too.

## Additional observation (separate, lower priority)

In translation mode, `cache_control` on an Anthropic request is also lost: the client sent one
`cache_control` block, the upstream received zero, with the gateway alone in the path
(no other proxy involved). The tool list survived (12/12), so this is specific to
`cache_control` rather than to the whole block structure.

Separately, if an upstream proxy injects a tool definition into the Anthropic body before
magpie translates it, the translated Chat body is larger than if translation happened first:
3275 B vs 2793 B on the same payload (+482 B). Likely just an expected consequence of translating
an already-augmented body, not a defect — mentioning it only because it changes which side of the
chain a compression proxy should sit on.
