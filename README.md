# Campaign Performance Triage Agent

Autonomous decision-making agent for a digital marketing agency: ingests
per-campaign ad performance metrics across clients, reasons against
client-specific policy thresholds, and produces ranked, rationale-backed
action recommendations. **Recommend/log only** — no execution against ad
platforms in this build.

## Architecture

Perceive -> Reason -> Plan -> Act -> Learn, implemented as a fixed
LangGraph `StateGraph` (not a dynamic planning DAG — the node sequence is
known at design time, same call as the Verdantis SDR pipeline):

```
ingest --> Send(fan-out per campaign) --> assess_campaign (parallel, semaphore-bounded)
        --> aggregate_and_prioritize --> log_run
```

- **Perception**: `synthetic_data.py` stands in for a live Meta Marketing
  API / Google Ads API pull. Swap this module for a real fetcher later —
  the graph and state schema don't change, as long as it returns
  `list[CampaignMetrics]`.
- **Reasoning + Planning**: `assess_campaign` runs once per campaign, in
  parallel (bounded concurrency, matching the `validate_trade_evidence` /
  `resolve_contacts` pattern from Verdantis). One structured-output LLM
  call per campaign produces both a performance classification and a
  single recommended action with rationale.
- **Action**: none — this agent only recommends. `requires_human_approval`
  is set by the LLM *and* independently hard-enforced in code whenever
  `daily_spend` exceeds the client's `escalation_spend_threshold`. Don't
  trust the model alone for the approval gate.
- **Learning**: `log_run` writes a per-run summary to `learning_log`.
  Currently just counts; the natural extension is persisting this to
  Postgres and using historical accuracy (did CPA actually improve after
  a "scale_budget" call?) to adjust confidence thresholds over time.

## Prompt architecture

`prompts.py` follows the same PTCF (Persona/Task/Context/Format) framework
used on Verdantis, with two guardrails enforced in the prompt *and* in
code: (1) campaigns younger than `min_days_before_judgment` are held, not
judged; (2) the escalation spend threshold is a hard approval gate.

## Files

| File | Purpose |
|---|---|
| `state.py` | Pydantic state schema (`AgentState`, `CampaignMetrics`, `ClientPolicy`, etc.) |
| `synthetic_data.py` | Mock multi-client campaign data + policies (swap for live API later) |
| `prompts.py` | PTCF system/user prompts for the reasoning+decision node |
| `graph.py` | LangGraph `StateGraph` definition, `Send`-based fan-out, rule-based fallback |
| `main.py` | Entry point — runs the graph, prints a formatted report, writes `run_output.json` |

## Running it

```bash
pip install -r requirements.txt
python3 main.py
```

Without `ANTHROPIC_API_KEY` set, it runs on a deterministic rule-based
fallback (`_rule_based_fallback` in `graph.py`) so the graph is fully
demoable with zero cost/setup. Set the key to switch to live Claude
reasoning:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 main.py
```

Model used: `claude-sonnet-4-5`. Change in `graph.py::_get_llm()`.

## Web UI / API

`server.py` wraps the same graph behind a small FastAPI app and serves a
static frontend (`static/index.html`) from the same process — one
deployable service, no separate frontend build/host needed.

```bash
uvicorn server:app --reload
```

Then open `http://localhost:8000` and click **Run Triage**.

- `GET /api/health` — health check
- `POST /api/run` — runs the graph against `synthetic_data.py` and
  returns the ranked decisions as JSON (same shape as `run_output.json`)

The CLI (`main.py`) still works independently for scripting/cron use.

## Deploying

Two deploy paths are wired up, pick whichever your host expects:

- **Docker** (`Dockerfile`) — works on Render, Fly.io, Railway, AWS App
  Runner, or any container host. Build with
  `docker build -t campaign-triage-agent .` and run with
  `docker run -p 8000:8000 --env-file .env campaign-triage-agent`.
- **Buildpack** (`Procfile`) — for hosts that detect Python apps directly
  (Railway, Heroku-style platforms) without a Dockerfile.

Either way, set `ANTHROPIC_API_KEY`, `LANGCHAIN_TRACING_V2`,
`LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT` as environment variables /
secrets in the hosting platform's dashboard — never commit `.env` or bake
keys into the image (`.dockerignore` already excludes it).

## Known gaps / next steps toward production

1. **No LangSmith tracing wired yet** — add `LANGCHAIN_TRACING_V2=true` +
   `LANGCHAIN_API_KEY`/`LANGCHAIN_PROJECT` env vars; zero code changes
   needed, LangGraph picks it up automatically. This is the single
   highest-leverage addition for a client demo — a traced run showing the
   model's classification signals and rationale per campaign is the sales
   artifact.
2. **No Postgres checkpointing** — not yet needed since there's no
   human-in-the-loop interrupt to resume from (recommend/log only has no
   pause point). Add when you wire an approval UI that needs to persist
   state between the recommendation and the human's decision.
3. **No live platform connector** — `synthetic_data.py` is the seam.
   Real version needs Meta Marketing API (`GET /act_{ad_account_id}/insights`)
   and/or Google Ads API (`GoogleAdsService.SearchStream` with GAQL),
   both of which require app review / developer token approval — budget
   1-2 weeks lead time before this can run on a real account.
4. **`dollar_impact_daily` is a placeholder heuristic** — currently
   `|spend - target_budget| + 10% of spend`. Real prioritization should
   weight by historical campaign value or client tier, not just spend
   delta.
5. **No approval UI** — recommendations currently print to console /
   JSON. A minimal next step is a Slack digest or a simple review queue
   (Retool/Streamlit) an account manager checks each morning.
