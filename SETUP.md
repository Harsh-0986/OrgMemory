# Setup

Everything needed to run OrgMemory locally. About 10 minutes, most of it waiting on
account approval.

If you only want to *see* it work, you can skip the LLM key entirely — see
[Step 3](#step-3-optional-add-an-llm-key). The app runs end to end without one.

---

## What you need

| | Version | Check with |
| --- | --- | --- |
| Python | 3.12.x (not 3.13) | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) | any recent | `uv --version` |
| Node.js | 20.9 or newer | `node --version` |
| A FalkorDB instance | Free tier is fine | — |
| An NVIDIA NIM key | *optional* | — |

Two terminals are needed: one for the backend, one for the frontend.

---

## Step 1 — Get a FalkorDB instance

The app talks to FalkorDB over the network, so you need an instance before anything
else will start.

1. Sign up at [app.falkordb.cloud](https://app.falkordb.cloud) and create an instance
   from the Free tier.
2. Go to **Deployments → Instances → your instance → Connectivity**.
3. Copy the **Endpoint**. It is `host:port` and **the port is usually not 6379**.
4. Go to **Instance Details** and copy the **FalkorDB User** and **FalkorDB Password**.

Write those four values down — you need them in Step 2.

---

## Step 2 — Configure

```bash
git clone https://github.com/Harsh-0986/OrgMemory.git
cd OrgMemory
cp .env.example .env
```

Open `.env` and fill in the four values from Step 1:

```ini
FALKORDB_HOST=instance-xxxxx.your-region.aws.example
FALKORDB_PORT=60756
FALKORDB_USERNAME=falkordb
FALKORDB_PASSWORD=...
FALKORDB_TLS=false
```

`FALKORDB_TLS=false` is correct for the Free tier. Only paid tiers with "Enable TLS" need
it set to `true`.

> The FalkorDB dashboard also labels these `FALKOR_DB_INSTANCE` and `FALKOR_DB_PASS`.
> The app accepts either spelling, so a config copied from the dashboard works unchanged.

---

## Step 3 — (Optional) Add an LLM key

**You can skip this.** With `LLM_ENABLED=false` the app still answers questions end to
end using a deterministic writer built straight from the graph. This is the mode the
test suite runs in.

To use a model, get a key from [build.nvidia.com](https://build.nvidia.com) and set:

```ini
LLM_ENABLED=true
NVIDIA_API_KEY=...
NVIDIA_MODEL=z-ai/glm-5.3-flash
```

NIM is OpenAI-compatible, so no custom client is involved. Not every model on the
public model list is enabled for every account — if you get a 404, test your key with a
quick chat completion and pick one that answers.

---

## Step 4 — Run the backend

```bash
cd backend
uv sync
```

`uv sync` creates the virtualenv and installs everything. If it complains about Python
versions, make sure you are on 3.12.

Seed the database, then start the server:

```bash
uv run python -m app.seed.seed --reset
uv run uvicorn app.main:app --port 8000
```

`--reset` drops and rebuilds the graph, so it is safe to re-run whenever you want a
clean slate.

The API is at <http://localhost:8000>, with docs at
<http://localhost:8000/docs>.

### Confirm it worked

```bash
curl http://localhost:8000/health
```

You want `"status": "ok"` and a graph name of `orgmemory`. If the graph field is missing
or the status is not ok, the most common cause is a wrong host, port, or password — the
port in particular is easy to copy wrong.

---

## Step 5 — Run the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> and click **The primary demo**.

> Use `localhost` or `127.0.0.1`, not both, and match whichever you typed. They are
> different origins to a browser, and the default `CORS_ORIGINS` allows both.

---

## Step 6 — Run the tests

Optional, and needs no API keys — the tests never call a model.

```bash
cd backend
uv run pytest                  # full suite
uv run pytest -m integration   # only tests needing a live FalkorDB
```

---

## The demo question

> *"Can we replace Payment Service A with Payment Service B? What could break, who
> should review it, and why do we use the current service?"*

The seeded company, "Northwind Logistics", is entirely fictional. The answer should
show 8 downstream services across 3 hops with shortest paths, the owners of each, four
architecture decisions including one marked `superseded`, and one incident with **no
recorded cause** that the agent reports as unknown rather than guessing at.

That last one is deliberate and worth watching for — it demonstrates the agent refusing
to invent a fact the graph does not contain.

Other questions worth trying:

| Question | What it shows |
| --- | --- |
| What depends on the General Ledger Sync? | Single-hop traversal, no LLM needed |
| Who owns the Checkout API? | Intent routing skips impact analysis entirely |
| Why do we use Payment Service A? | Decision rationale and supersession chains |
| What incidents affected the Webhook Dispatcher and what caused them? | An incident with no `CAUSED_BY` edge, reported as unknown |

---

## If something goes wrong

**Backend exits immediately, mentions FalkorDB.** Almost always the port. Re-copy the
endpoint from the Connectivity tab; do not assume 6379.

**`401` or `WRONGPASS`.** Username and password come from *Instance Details*, not
*Connectivity*. Check for a trailing space when copying.

**Frontend loads, every request fails in the console.** A CORS mismatch. The origin in
your address bar must appear in `CORS_ORIGINS` in `.env`, exactly — including scheme and
port. Restart the backend after changing it.

**Investigations return a fallback answer.** Expected whenever `LLM_ENABLED=false`, and
also when the model is slow or rate-limited. The response says which writer produced it.
The reasoning trace and citations still come from the graph either way.

**`uv sync` fails on Python.** The backend requires `>=3.12,<3.13`. Check with
`python3 --version`.

**Seeding is slow or fails partway.** Your instance may be cold or below the Free-tier
size limits. Re-run with `--reset`.

---

## Reference

### Ports

| Service | Port |
| --- | --- |
| Backend API | 8000 |
| Frontend | 3000 |
| FalkorDB Cloud | from your instance's Connectivity tab |

### Useful endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness, plus graph name and version |
| `GET` | `/docs` | Interactive OpenAPI docs |
| `GET` | `/api/graph/overview` | Node and edge counts |
| `GET` | `/api/graph/full` | Whole graph, for the visual browser |
| `GET` | `/api/graph/neighborhood` | One entity's immediate neighbourhood |
| `POST` | `/api/investigations` | Ask a question |
| `GET` | `/api/investigations/history` | Past investigations from graph memory |

`POST /api/investigations` takes `{"question": "..."}` with a minimum length of 8
characters, and returns `202` while work continues in the background.

### Configuration reference

Every setting has a working default in `.env.example`; only the FalkorDB block is
mandatory. The most useful ones to know about:

| Variable | Default | Notes |
| --- | --- | --- |
| `LLM_ENABLED` | `true` | `false` runs the whole app with no model |
| `LLM_PROVIDER` | `auto` | `nvidia`, `google`, or `auto` |
| `AGENT_MAX_STEPS` | `8` | Ceiling on agent iterations |
| `AGENT_MAX_TOOL_CALLS` | `24` | Ceiling on graph calls per investigation |
| `AGENT_MAX_RECURSION` | `25` | LangGraph recursion limit |
| `GRAPH_MAX_DEPENDENCY_DEPTH` | `3` | Max `DEPENDS_ON` hops, 1–6 |
| `GRAPH_MAX_RESULTS` | `100` | Max rows any one graph tool returns |

Those limits are what keep a misbehaving agent loop from running away: an acyclic
pipeline, a per-investigation tool budget, and a recursion limit.

### Re-seeding

```bash
cd backend
uv run python -m app.seed.seed --reset
```

Deterministic — the same 52 nodes and 124 relationships every time.
