# Claude setup

Kako's agents run on Claude through Anthropic's own API (Pim, Nov 27, 2026: "i want to use claude for
now moving forward to save on costs.... maybe foundry can be for later but i prefer to just run the
tests on claude"). This page is the Claude side as it is: the key, the models and their settings, how
to check it, and what has and hasn't been run. Azure AI Foundry stays available behind
`KAKO_MODEL_PROVIDER=foundry` ([azure-setup.md](azure-setup.md)). No secrets here.

## The key

- Made in the Claude Console (API keys, then Create key, then "Continue with an API key": identity
  federation needs a cloud identity provider, which neither the cloud sessions nor the laptop have).
  Named `kako`. Shown once; never pasted into a chat, a commit, a log or a screenshot.
- Kako reads it from **`KAKO_ANTHROPIC_API_KEY`** and nothing else. Never `ANTHROPIC_API_KEY`: Claude
  Code signs itself in with that name, so in a shared environment it could send Claude Code's own work
  to Kako's credit, or Kako's calls to Claude Code's account.
- The model manager hands the key and `https://api.anthropic.com` to the SDK explicitly. Given a key,
  the SDK reads no credential of its own (`ANTHROPIC_AUTH_TOKEN`, profiles, federation), and the URL
  is never taken from `ANTHROPIC_BASE_URL`, which cloud sessions set for Claude Code. `KAKO_ANTHROPIC_BASE_URL`
  can name another HTTPS endpoint; plain HTTP is refused.
- Where it lives:
  - **Cloud sessions:** an environment variable of the cloud environment (Project settings, then the
    gear beside the environment, then Environment variables). Network secrets can't hold a Claude key.
    Everyone who uses the environment, and commands in its sessions, can read it, and only a new
    session picks it up.
  - **The laptop:** the gitignored `.env` beside the backend, as `KAKO_ANTHROPIC_API_KEY=`.
  - **CI:** none. CI replays recordings and never calls a model.
- A spend limit on the key's workspace in the Console (Limits) backs up Kako's own daily cap.

The credit: Pim's Max plan brings US$100 of API credit a month (the Nov grant expires Dec 15; the
next arrives Dec 16), shown in the Console's billing page. It pays for the API, Batch API and
Playground.

## Models, effort and prices

| Setting | Default | Notes |
| --- | --- | --- |
| `KAKO_MODEL_PROVIDER` | `anthropic` | `foundry` for Azure AI Foundry |
| `KAKO_MODEL_STRONG` | `claude-opus-5-5` | Orchestrator, single agent, dreaming. Blank means the default |
| `KAKO_MODEL_FAST` | `claude-haiku-5-5` | The four specialists. `claude-sonnet-5-5` if the test set says Haiku is too weak |
| `KAKO_CLAUDE_EFFORT_STRONG`, `_FAST` | `low` | `low` to `max`. Thinking is always on in Claude's current models; effort is its only control |
| `KAKO_PRICE_STRONG_*` | 4.00 in, 0.20 cache read, 5.00 cache write, 20.00 out | US$ per million tokens, Claude Opus 5.5's list prices (Nov 2026) |
| `KAKO_PRICE_FAST_*` | 0.10 in, 0.01 cache read, 0.125 cache write, 0.50 out | Claude Haiku 5.5's, for prompts up to 100,000 tokens (Kako's are far under) |

A model name that isn't `claude-*` (such as `gpt-5.4` left in an old `.env`) is refused before any
call, with the way out: a Claude model, or `KAKO_MODEL_PROVIDER=foundry`.

## What each call sends

`ClaudeChat` in `backend/src/kako/agents/model_manager.py` (docs/architecture.md, "Models"):

- The system prompt (the shared rules, the brief, the role) as the request's `system`, with a cache
  breakpoint, and automatic caching of the turns after it. A turn's later calls read that prefix from
  the cache at a twentieth of the input price; the first writes it at 1.25 times. Both are logged
  (`cached_tokens`, and the write in `cost_usd`).
- Adaptive thinking at the tier's effort. The reply's thinking blocks are opaque and signed; they come
  back as `ChatReply.blocks`, are kept in recordings, and the tool loop sends them back unchanged with
  the next call of the same loop. When the loop offers only the final tool, the request's tools
  change, and the thinking-binding beta (`thinking-binding-controls-2026-08-01`, `drop_block`) drops
  the earlier blocks rather than refusing the request.
- Strict tools where the schema is structured (a nested object, an enum, a const or a union), and
  plain ones without: Claude compiles every strict schema of a request into one grammar and refuses
  one too large, which the orchestrator's fifteen tools reached (tuning-log entry 17). Tool choice `auto`:
  Claude's current models refuse forced tool use, so the loop keeps "only the final tool" by what it
  offers, and sends an empty reply back once.
- Tool results go back in one user turn, before any note from code.
- No server-side refusal fallback: each call is answered by the model it names, or comes back with
  `finish_reason` "refusal".
- The SDK's own retries are off; the model manager retries a rate limit, an overload, a server error
  or a lost connection (`KAKO_MODEL_MAX_RETRIES`), and logs every attempt.

## Checking it

```
cd backend
uv run kako check-models
```

It prints the settings (never the key), checks the key against the strong model (a free read of the
model's details), then makes one tiny call per model with the same thinking settings and beta as an
agent's call, so a model or account that refuses them fails here first. Exit 1 on any FAIL.

## What has been run

- Nov 27: built and tested with a fake API (`tests/test_claude_chat.py`): no key, no call, no spend.
- Nov 27: `kako check-models` passed on both models. Session 2's pilot ran (US$0.11, figures right,
  but the orchestrator asked no specialist), after strict tools were cut to the structured ones.
  The rest waits on the pilot: [tuning-log.md](tuning-log.md) entry 17.
