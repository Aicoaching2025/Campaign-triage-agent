import asyncio
import json
import os
from datetime import date

from graph import build_graph
from state import AgentState

ACTION_LABEL = {
    "scale_budget": "SCALE BUDGET",
    "pause": "PAUSE",
    "reallocate_budget": "REALLOCATE",
    "hold": "HOLD",
    "escalate_to_human": "ESCALATE",
}


async def run():
    app = build_graph()
    initial_state = AgentState(run_date=date.today().isoformat())

    result = await app.ainvoke(initial_state)

    mode = "LIVE (Claude API)" if os.environ.get("ANTHROPIC_API_KEY") else "RULE-BASED FALLBACK (no ANTHROPIC_API_KEY set)"
    print(f"\n{'='*78}\nCAMPAIGN TRIAGE RUN -- {result['run_date']}  [{mode}]\n{'='*78}\n")

    decisions = result["ranked_decisions"]
    for d in decisions:
        flag = "  [NEEDS HUMAN APPROVAL]" if d.requires_human_approval else ""
        mag = f" ({d.magnitude_pct:+.0%})" if d.magnitude_pct else ""
        print(f"[{ACTION_LABEL[d.action]}{mag}]{flag}")
        print(f"  {d.campaign_name}  |  daily $ impact: ${d.dollar_impact_daily:,.2f}  |  confidence: {d.confidence:.0%}")
        print(f"  -> {d.rationale}\n")

    log = result["learning_log"][0]
    print(f"{'-'*78}")
    print(f"Summary: {log['campaigns_assessed']} campaigns assessed | "
          f"{log['auto_actionable']} auto-actionable | "
          f"{log['escalated']} escalated for approval | "
          f"{log['held']} held")
    print(f"{'='*78}\n")

    # Persist full structured output for downstream use (dashboard, review queue, etc.)
    out = {
        "run_date": result["run_date"],
        "decisions": [d.model_dump() for d in decisions],
        "classifications": [c.model_dump() for c in result["classifications"]],
        "summary": log,
    }
    with open("run_output.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Full structured output written to run_output.json")


if __name__ == "__main__":
    asyncio.run(run())
