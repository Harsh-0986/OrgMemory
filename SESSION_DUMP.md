# Session dump

Local only. Never committed, never pushed. One section per branch; newest entry
first within a branch. Update this after every change.

---

## main

### 2026-10-16 — uploads froze the API; ingestion is now queued

Commits `151529c`, `b6ab622`, `ee401fd`, `189fb5a`, `5a963d8`, `8d269fd` (on
top of `bc9126e`, `7e5642f`, `cb2f781`, `f1f7a27`).

**Reported:** "the app gets stuck while uploading documents."

**Diagnosis, measured rather than guessed.** `POST /api/ingest/file` was
`async def` so it could read the upload, and the pipeline behind it —
MarkItDown conversion, then a synchronous model call — ran on the event loop.
The event loop is the only thread serving every other request, so one upload
stopped the server answering anything at all. With a 20s stub model standing in
for a slow provider:

| during | `/health` before | `/health` after |
| --- | --- | --- |
| `POST /api/ingest/text` (`def` → worker thread) | 0.03s | 0.04s |
| `POST /api/ingest/file` (`async def` → event loop) | **18.2s** | **0.03s** |

The route style was the entire difference. With the real provider timing out at
60s per attempt and retrying twice, that was ~3 minutes of an apparently dead
app per upload.

**Fixed in two steps.**

1. `151529c` — the blocking pipeline goes through `run_in_threadpool`. A
   regression test asserts *latency*, not the presence of a threadpool call.
   Note for future me: its first version passed against the bug, because it
   timed `/health` after the blocking call had already finished — the loop
   could not run the timer that was waiting to measure it. It watches timer
   accuracy now; reverting the fix fails with "the event loop stalled for
   1.56s".
2. `ee401fd` / `189fb5a` — ingestion is queued like investigations: `POST`
   returns 202 with a poll URL, the work runs in a background thread, phases
   (`convert`, `extract`, `write`) are published as they finish, and the panel
   polls. `?wait=true` still blocks and returns the full report for scripts.

**Verified live** against a 12s stub: POST returned in 0.10s, `convert` was
visible at t+1s while the model was still working, `/health` stayed ~0.03s
throughout, `?wait=true` blocked 12.15s and returned the report, unknown job →
404. Panel verified in a browser with the ingest endpoints intercepted (no
quota): progress rows render, then the report with timings. No console errors.

**Other things found and fixed on the way.**

- `_invoke(system, user, timeout)` **ignores its `timeout` argument** —
  `timeout=2` against a 15s stub took 15.5s. Both `plan_node` and
  `extract_graph` pass a timeout expecting it to matter. The only real bound is
  client-level (`agent_query_timeout_seconds × 4`) with `max_retries=2`, so a
  dead provider costs ~3 minutes **per call, in investigations too**. Still
  open (see below).
- `test_counts_match_seed` asserted the live graph was *exactly* the seed.
  Ingestion is a feature that adds to it, so equality was the wrong invariant;
  it is now "nothing from the seed is missing" (counts as a floor, plus a
  presence check per label). Similarly, the investigation-memory test no longer
  assumes the newest investigation cites nodes — a citation-free investigation
  is legitimate (that is what you get with no model configured). Both were
  latent failures that would have started failing the moment anyone used the
  app as intended.
- 413 was missing from the error-envelope code map, so an oversized upload
  would have surfaced as a bare `http_error`.
- `capitalize` was rendering the tabs as "Upload A File" / "Paste Text";
  and phase timings read as "0.0s" for a 41ms conversion.

**Live graph housekeeping.** Three documents in the live graph are leftover
uploads made while the model was disabled, so they have no extracted entities:

- `doc-ingested-8b6696966f2c` — "Harsh Shah Resume AI Engineer"
- `doc-ingested-bfc90e8fc4d8` — "Harsh Shah Resume"
- `doc-ingested-3d7776fcc90a` — "Harsh Shah ATS Friendly"

Left alone (they are the user's content, not debris). Re-uploading the same
content updates the *same* node — ids are content-derived — and would extract
entities properly. My own experiment debris (`svc-stub` and three throwaway
Document nodes) was deleted from the live graph.

`inv-8e039913d020` ("who is harsh shah?", 04:53) has zero citations for the same
reason: it ran with the model off. Left in place.

**The model call is failing, and the app blames the config.** Worth reading
before touching ingestion again.

The configured model is `nvidia/nemotron-3-ultra-550b-a55b` — valid (it appears
in the endpoint's model list) but 550B, so an extraction prompt that asks for up
to 40 entities is slow. The client timeout is
`agent_query_timeout_seconds × 4` = 60s, retried twice, so the ceiling is about
three minutes per call.

A diagnostic POST I made (see below) wrote its Document node at 05:11:05 with
`extracted_by_model = False`, roughly three minutes after it started. That is
the signature of the retry storm exhausting itself and `_invoke` returning `""`
— *not* of a document that contained no entities.

The problem is what that gets reported as. `_invoke` is documented as "never
raises" and returns `""` for every failure including a timeout;
`extract_graph` reads an empty string as "no model" and returns
`model_used=False`; the report then says **"No model was available"**. So with
this model, every upload will extract nothing and blame a missing key, while
`/api/ingest/capabilities` simultaneously reports the model as available. That
contradiction is very likely the "why is model not configured?" confusion, and
it is the single biggest obstacle to a convincing demo.

**How to tell the two apart, fixed (option 3).** `5a963d8` / `8d269fd`.

`_invoke` is now a thin wrapper over `invoke_with_reason(system, user, timeout)
-> (text, failure)`, which separates the three cases that used to collapse into
an empty string:

- `("<text>", None)` — the model answered.
- `("", None)` — no model is configured. Nothing was attempted, so there is
  nothing to report; this is the honest "no model available".
- `("", "<reason>")` — a call was attempted and failed. An exhausted key, a
  rejected model id, and a timeout all land here.

The reason travels as `ExtractionOutcome.model_error` / `IngestReport.model_error`
and changes what the pipeline *says*, not just what it stores: the `extract` step
reads "The model call failed" with the reason, and the panel shows it as a fault
with a hint that a large model times out rather than erroring outright. The
document is stored and citable either way — a reader that failed is not an ingest
that failed. The panel also stopped claiming "everything it mentioned was already
known" when nothing had been read.

Verified in a browser against an intercepted response: the failure renders as a
failure, the "No model was available" wording is absent, no console errors. 218
passed (8 new), ruff/tsc/eslint clean.

Note the extractor has two seams now. `invoke=` scripts a *successful* answer and
is what the 18 existing tests use; `_call_model` is the real tuple-returning call,
isolated so the failure path can be driven without a provider.

**Still the biggest obstacle to the demo.** The call is still failing and still
costing ~3 minutes before it admits it. Two ways left, cheapest first:

1. Point `NVIDIA_MODEL` at `deepseek-ai/deepseek-v4.1-flash` (also offered by the
   endpoint). No code change; the same prompt becomes fast enough to finish.
   Only the user can do this — `.env` is theirs.
2. Make `_invoke` honour its `timeout` argument, so a dead call fails in seconds
   instead of three minutes. It is currently inert — verified: `timeout=2`
   against a 15s stub took 15.5s.

**A mistake I made, recorded so it is not repeated.** I probed the running
backend on :8000 with a real `POST /api/ingest/text` to check whether it had
picked up the new code. It had not — it was started without `--reload`, so the
probe went through the *old* blocking route, reached the real model, held the
server for three minutes, and left a Document node behind (since removed). The
port list was already in hand and would have told me: a server with no
`--reload` cannot have new code. The right probe is `GET /openapi.json`, which
proves which routes are loaded and costs nothing. The backend has since been
restarted on the new code and now serves `/api/ingest/{job_id}/status`.

**Two servers, two ways to lose them (both hit this session).**

- Running `npm run build` in `frontend/` while `next dev` is serving the same
  directory breaks the dev server: the build rewrites `.next` underneath it and
  the running process eventually dies on a request. It took the dev server on
  :3000 down mid-session. Verify the build in that directory only when the dev
  server is stopped, or expect to restart it.
- A backgrounded server started with `nohup … &` inside a shell call did not
  survive; the backend on :8000 died the same way. Servers should be started with
  the shell tool's own background mode, which is what restored both.

Both are back up: `3000` (frontend) and `8000` (backend, real config, serving the
new routes). Nothing else is listening.

**Port 8000 is claimed by the agent harness (found 2026-10-16, late session).**

The backend on :8000 was SIGKILLed with no explanation in its log, and a fresh
backend immediately picked up a steady stream of `GET /health` +
`GET /v1/models` requests, one pair per second, each from a new source port.
Ruled out: this repo (no reference to `/v1/models` anywhere), `~/.config/opencode`
(no `8000`), LogSherlock (a sibling project that also hardcodes `BACKEND_PORT=8000`,
but it is not running).

What it is, from the binary rather than a guess:

```
strings ~/.opencode/bin/opencode | grep -oE 'http://[0-9.:]*8000…'  → http://127.0.0.1:8000
strings ~/.opencode/bin/opencode | grep -oE '/v1/models|/health'    → /v1/models ×7, /health ×4
lsof -nP -iTCP:8000 (tight sample)                                  → client = opencode (pid 56874)
```

`/health` + `/v1/models` is the shape of a local OpenAI-compatible model-server
probe, and 8000 is the conventional port for one. So the harness running this
session probes 8000 looking for a model server, and OrgMemory's backend is
sitting on it. The `404`s are harmless; the risk is the kill, which recurs
whenever whatever owns that probe reclaims the port.

**Implication for the demo:** do not run the backend on 8000. Move it to a quiet
port (e.g. `8010`) and point the frontend at it with
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8010` in `frontend/.env.local`
(the default lives in `frontend/lib/api.ts:25`; there is no `.env*` in
`frontend/` today, and the backend `.env` needs no change because the port is
passed on the uvicorn command line). Until that is done, expect the backend to be
killed at random while the app is being demoed.

### Open

- **The model call still fails, and now says so** (above). The reporting half is
  done; the remaining half is the model being too slow to answer inside the
  timeout. Switching `NVIDIA_MODEL` is the user's call; making `timeout` real is
  the code-side fix.
- **`_invoke` still ignores `timeout`.** A failing provider costs ~3 minutes per
  call, in investigations as well as ingestion. Needs a test against a stalling
  stub first.
- **Investigations inherit the same lie.** `plan_node` uses `_invoke`, so a failed
  model call there degrades to "no evidence found" without saying why. The
  mechanism now exists (`invoke_with_reason`); nobody has wired it up on that
  path.
- If the backend is left running, it needs a restart after every code change —
  it was started without `--reload`. Consider adding it.
- Remaining gaps for the submission: screenshots, deployment, demo video, DEV
  blog post, and 5 untriaged high-severity npm advisories.
