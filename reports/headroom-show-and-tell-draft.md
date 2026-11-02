# Draft: headroom "Show and tell" post

Target: `headroomlabs-ai/headroom` → Discussions → **Show and tell**
(not an issue: this is a benchmark, there is no defect to fix. Categories available:
Announcements / General / Ideas / Polls / Q&A / Show and tell.)

Suggested title:

    Measured byte-level savings on Windows: tool output -71.1%, path list -92.0%, build log +0.7%

---

## Setup

- headroom-ai 0.42.0 (`headroom-ai[proxy]`), Windows wheel, Python 3.14.7
- proxy on loopback, `/health` waited until `kompress: healthy` and `checks.upstream.url` matched
- flags: `--no-cache --no-http2 --no-rate-limit --no-subscription-tracking`,
  `HEADROOM_BEACON=off`, `HEADROOM_TELEMETRY=off`
- upstream is a local stub that records exact received bytes, so numbers are wire bytes, not estimates
- every payload is synthetic; no real provider, no keys, nothing leaves the machine

## Topology measured

Seven arms on one machine: direct to stub; stub behind a gateway; headroom before the gateway;
headroom after the gateway; headroom alone. The reason for the full matrix was to separate
"headroom's own cost" from "gateway interference" rather than comparing two totals.

## Results, headroom alone vs direct (bytes received by the stub)

    P1  240-record JSON array (33 KB)      33,683 -> 9,747    28.9%    needle intact
    P2  600 file paths (20 KB)             20,205 -> 1,616     8.0%    needle intact
    P3  cargo build log, 320 lines         19,056 -> 19,189  100.7%    ~unchanged, as expected
    P4  TypeScript file via Read           23,087 -> 23,569  102.1%    Read is excluded, only +CCR overhead
    P5  12-turn session, 416 KB            416,692 -> 415,804 99.8%   cache mode froze first 2/3
    P6  3 tool calls, tiny request          1,178 -> 1,616   137.2%    pure injection overhead
    P7a Anthropic native, 12 tools          2,646 -> 2,942   111.2%    +1 tool, +1 cache_control
    P7b same payload, OpenAI Chat           2,985 -> 3,254   109.0%    +1 tool
    P7c same payload, OpenAI Responses      2,790 -> 2,790   100.0%    untouched
    P8  same 33 KB JSON in a user message  33,471 -> 33,973  101.5%    not compressed, by design

Token counts from `/stats-history` agree with the wire bytes on the two big cases
(8,695 -> 2,188 tokens, -74.8%; 5,646 -> 237 tokens, -95.8%). I am quoting wire bytes above
because that is what I could verify independently.

## Behaviours worth documenting

- Compression only touches tool observations. User messages and `Read` results are protected —
  P8 exists specifically to confirm that a 33 KB user message is not compressed.
- Structured data compresses extremely well; unstructured build logs do not. P3 moving by 133 B
  is the honest number for that class of content.
- In cache mode the first two thirds of a multi-turn conversation are frozen, so a 416 KB session
  only yields 888 B. Worth knowing when sizing expectations for long sessions.
- CCR adds one `headroom_retrieve` tool and, on the Anthropic path, one `cache_control` block.
  On requests that are already small, that overhead dominates (P6: +438 B, 137%).
- If a translating gateway sits in front of headroom and converts Anthropic to OpenAI Chat first,
  headroom no longer augments the tool list (12/12 instead of 13/12) and the request stays 482 B
  smaller than the other order. Not a bug, just an interposition effect.

## Reproduction

Public harness, synthetic payloads, no secrets:
`https://github.com/coeo91/headroom-chain-test`

`RUNBOOK.md` §3 has a copy-paste block that brings up stub + headroom + gateway and runs all arms;
`RESULTS-SAMEMACHINE.md` is the raw table; `RESULTS-PASSTHROUGH.md` is the byte-transparent control.

## Caveats

- One machine, loopback, synthetic payloads. No public-network latency, no real provider prefix cache.
- One gateway version (magpie 0.1.2687) and one headroom version (0.42.0). Byte numbers will move
  with either.
- "Bytes received by the stub" is the metric. It is not the provider's bill; `cache_read` behaviour
  on a real vendor was not measured here.
