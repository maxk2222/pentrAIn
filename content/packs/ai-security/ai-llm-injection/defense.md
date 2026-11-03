# Defense notes — AskOps

## Vulnerability 1 — guard bypass via encoded input (prompt injection)

- **Weakness**: the word filter inspects the surface string; a `b64:`
  feature decodes and executes the payload without a second pass — any
  banned phrase sails through once encoded.
- **Detect**: high-entropy/base64-looking user messages; decoded payloads
  containing instruction verbs targeting the system prompt.
- **Fix**: run the SAME guard on the *canonicalized* input (after decoding,
  normalizing, unicode-folding) — never trust a string the model interprets
  differently than the filter does. Prefer instruction/data separation:
  treat all user text as data, never as commands.
- **Verify**: `b64:` of the leak payload must trigger the same refusal as
  its plaintext form.

## Vulnerability 2 — excessive agency on the report tool

- **Weakness**: a tool that accepts "as admin" in chat text grants its
  privilege to whoever types it — the model is the only authorization.
- **Detect**: tool invocations whose only authority proof is in the user
  message; markers written without a real authenticated session.
- **Fix**: bind tool calls to the authenticated requester context, never to
  claimed roles; scope the tool's privileges (write-only sandbox path);
  require a signed capability token the user can't forge.
- **Verify**: no chat phrasing can create the report marker without valid
  credentials — the API itself must enforce it.

## Vulnerability 3 — indirect injection through assistant-read data

- **Weakness**: documents the assistant reads can carry
  `assistant: …` instructions that execute with model privileges while the
  user only asked for a summary.
- **Detect**: doc-store content containing assistant-addressed lines; tool
  invocations triggered during summarization with no user intent.
- **Fix**: delimit untrusted content (quoted blocks the model may never
  treat as instructions); strip/neutralize instruction-like patterns on
  ingest; require user confirmation before any tool call.
- **Verify**: summarize `ops-note` — no report may be filed.
