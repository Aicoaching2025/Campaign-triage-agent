import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/run")
async def run_triage():
    initial_state = AgentState(run_date=date.today().isoformat())
    result = await _graph.ainvoke(initial_state)

    decisions = result["ranked_decisions"]
    log = result["learning_log"][0]

    return {
        "run_date": result["run_date"],
        "mode": "live" if os.environ.get("ANTHROPIC_API_KEY") else "rule_based_fallback",
        "decisions": [d.model_dump() for d in decisions],
        "summary": log,
    }


app.mount("/", StaticFiles(directory="static", html=True), name="static")
