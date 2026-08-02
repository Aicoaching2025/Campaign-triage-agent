import json
import os
import uuid
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from graph import build_graph
from state import AgentState

app = FastAPI(title="Campaign Triage Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = build_graph()

# Runs are persisted to disk so escalation review decisions survive a
# server restart or a page reload -- not a real database, but enough for
# a human-in-the-loop demo. Keyed by run_id -> run record (see /api/run).
_STORE_PATH = Path("approvals_store.json")


def _load_store() -> dict:
    if _STORE_PATH.exists():
        return json.loads(_STORE_PATH.read_text())
    return {}


def _save_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2))


_store = _load_store()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/run")
async def run_triage():
    initial_state = AgentState(run_date=date.today().isoformat())
    result = await _graph.ainvoke(initial_state)

    decisions = result["ranked_decisions"]
    log = result["learning_log"][0]

    decision_records = []
    for d in decisions:
        record = d.model_dump()
        record["approval_status"] = "pending" if d.requires_human_approval else "n/a"
        decision_records.append(record)

    run_record = {
        "run_id": uuid.uuid4().hex[:8],
        "run_date": result["run_date"],
        "mode": "live" if os.environ.get("ANTHROPIC_API_KEY") else "rule_based_fallback",
        "decisions": decision_records,
        "summary": log,
    }
    _store[run_record["run_id"]] = run_record
    _save_store(_store)
    return run_record


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run_record = _store.get(run_id)
    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_record


@app.post("/api/runs/{run_id}/decisions/{campaign_id}/{verdict}")
async def review_decision(run_id: str, campaign_id: str, verdict: str):
    if verdict not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="verdict must be 'approve' or 'reject'")

    run_record = _store.get(run_id)
    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    for record in run_record["decisions"]:
        if record["campaign_id"] == campaign_id:
            if record["approval_status"] == "n/a":
                raise HTTPException(status_code=400, detail="This decision did not require approval")
            record["approval_status"] = "approved" if verdict == "approve" else "rejected"
            _save_store(_store)
            return record

    raise HTTPException(status_code=404, detail="Campaign not found in this run")


app.mount("/", StaticFiles(directory="static", html=True), name="static")
