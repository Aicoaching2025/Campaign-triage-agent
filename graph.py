"""
Campaign Performance Triage Agent -- LangGraph StateGraph.

Architecture (fixed deterministic pipeline, not a dynamic planning DAG --
the node sequence is known at design time):

    ingest --> Send(fan-out per campaign) --> assess_campaign (parallel)
            --> aggregate_and_prioritize --> log_run

Parallelism lives only at assess_campaign, bounded by a semaphore, same
pattern as validate_trade_evidence / resolve_contacts on Verdantis.
"""

import asyncio
import os
from datetime import date
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from state import AgentState, CampaignMetrics, ClientPolicy, PerformanceClassification, CampaignDecision
from synthetic_data import get_synthetic_metrics, get_client_policies
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

MAX_CONCURRENT_ASSESSMENTS = 4
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ASSESSMENTS)


class CampaignAssessment(BaseModel):
    """Combined structured output for one LLM call: classification + decision."""
    status: str = Field(description="over_performing | on_target | underperforming | anomalous | insufficient_data")
    signals: list[str]
    classification_confidence: float = Field(ge=0.0, le=1.0)

    action: str = Field(description="scale_budget | pause | reallocate_budget | hold | escalate_to_human")
    magnitude_pct: float | None = None
    rationale: str
    requires_human_approval: bool
    decision_confidence: float = Field(ge=0.0, le=1.0)


class PerCampaignState(TypedDict):
    metric: CampaignMetrics
    policy: ClientPolicy


def _get_llm():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return ChatAnthropic(model="claude-sonnet-4-5", temperature=0).with_structured_output(CampaignAssessment)


async def assess_campaign(payload: PerCampaignState) -> dict:
    """Runs for a single campaign in parallel. Perception is already done
    upstream (metric is already structured); this node does Reasoning +
    Planning in one LLM call, bounded by a semaphore for concurrency control."""
    metric = payload["metric"]
    policy = payload["policy"]

    async with _semaphore:
        llm = _get_llm()
        if llm is None:
            assessment = _rule_based_fallback(metric, policy)
        else:
            user_prompt = USER_PROMPT_TEMPLATE.format(
                client_name=policy.client_name,
                cpa_tolerance_pct=policy.cpa_tolerance_pct,
                roas_tolerance_pct=policy.roas_tolerance_pct,
                max_auto_scale_pct=policy.max_auto_scale_pct,
                escalation_spend_threshold=policy.escalation_spend_threshold,
                min_days_before_judgment=policy.min_days_before_judgment,
                campaign_name=metric.campaign_name, platform=metric.platform,
                objective=metric.objective, days_active=metric.days_active,
                daily_spend=metric.daily_spend, target_daily_budget=metric.target_daily_budget,
                cpa=metric.cpa, target_cpa=metric.target_cpa,
                roas=metric.roas, target_roas=metric.target_roas,
                ctr=metric.ctr, conversions=metric.conversions, impressions=metric.impressions,
            )
            result = await llm.ainvoke([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
            assessment = result

        # Hard rule enforced in code, not just prompted -- never trust the
        # model alone for the escalation gate.
        requires_approval = assessment.requires_human_approval or (
            metric.daily_spend > policy.escalation_spend_threshold
        )

    classification = PerformanceClassification(
        campaign_id=metric.campaign_id,
        status=assessment.status,
        signals=assessment.signals,
        confidence=assessment.classification_confidence,
    )
    decision = CampaignDecision(
        campaign_id=metric.campaign_id,
        campaign_name=metric.campaign_name,
        client_id=metric.client_id,
        action=assessment.action,
        magnitude_pct=assessment.magnitude_pct,
        rationale=assessment.rationale,
        requires_human_approval=requires_approval,
        dollar_impact_daily=abs(metric.daily_spend - metric.target_daily_budget) + metric.daily_spend * 0.1,
        confidence=assessment.decision_confidence,
    )
    return {"classifications": [classification], "decisions": [decision]}


def _rule_based_fallback(metric: CampaignMetrics, policy: ClientPolicy) -> CampaignAssessment:
    """Used only when no ANTHROPIC_API_KEY is set, so the graph is still
    runnable end-to-end for demo/dev purposes without a key. Production
    runs should always go through the LLM path above."""
    if metric.days_active < policy.min_days_before_judgment:
        return CampaignAssessment(
            status="insufficient_data", signals=[f"Only {metric.days_active} days active"],
            classification_confidence=0.9, action="hold", rationale="Too new to judge; holding.",
            requires_human_approval=False, decision_confidence=0.9,
        )

    cpa_over = (metric.cpa - metric.target_cpa) / metric.target_cpa if metric.target_cpa else 0
    roas_under = (metric.target_roas - metric.roas) / metric.target_roas if metric.target_roas else 0

    if metric.conversions == 0 and metric.impressions > 10000:
        return CampaignAssessment(
            status="anomalous", signals=[f"{metric.impressions} impressions, 0 conversions"],
            classification_confidence=0.7, action="escalate_to_human",
            rationale="Zero conversions on high impressions suggests a tracking or setup issue.",
            requires_human_approval=True, decision_confidence=0.6,
        )
    if cpa_over > policy.cpa_tolerance_pct or roas_under > policy.roas_tolerance_pct:
        return CampaignAssessment(
            status="underperforming",
            signals=[f"CPA ${metric.cpa:.2f} vs target ${metric.target_cpa:.2f} (+{cpa_over:.0%})"],
            classification_confidence=0.75, action="pause",
            rationale=f"CPA is {cpa_over:.0%} over target, outside the {policy.cpa_tolerance_pct:.0%} tolerance.",
            requires_human_approval=False, decision_confidence=0.75,
        )
    if cpa_over < -0.1 and metric.roas > metric.target_roas:
        return CampaignAssessment(
            status="over_performing",
            signals=[f"CPA ${metric.cpa:.2f} beating target ${metric.target_cpa:.2f}"],
            classification_confidence=0.8,
            action="scale_budget", magnitude_pct=min(0.15, policy.max_auto_scale_pct),
            rationale="Beating target CPA and ROAS -- recommend scaling budget.",
            requires_human_approval=False, decision_confidence=0.8,
        )
    return CampaignAssessment(
        status="on_target", signals=["Within tolerance on CPA and ROAS"],
        classification_confidence=0.7, action="hold",
        rationale="Performing within policy tolerance; no action needed.",
        requires_human_approval=False, decision_confidence=0.7,
    )


def ingest(state: AgentState) -> dict:
    metrics = get_synthetic_metrics()
    policies = get_client_policies()
    return {
        "raw_metrics": metrics,
        "policies": policies,
        "client_ids": list(policies.keys()),
    }


def fan_out_assessments(state: AgentState) -> list[Send]:
    return [
        Send("assess_campaign", {"metric": m, "policy": state.policies[m.client_id]})
        for m in state.raw_metrics
    ]


def aggregate_and_prioritize(state: AgentState) -> dict:
    ranked = sorted(state.decisions, key=lambda d: d.dollar_impact_daily, reverse=True)
    return {"ranked_decisions": ranked}


def log_run(state: AgentState) -> dict:
    entry = {
        "run_date": state.run_date,
        "campaigns_assessed": len(state.raw_metrics),
        "auto_actionable": sum(1 for d in state.ranked_decisions if not d.requires_human_approval and d.action != "hold"),
        "escalated": sum(1 for d in state.ranked_decisions if d.requires_human_approval),
        "held": sum(1 for d in state.ranked_decisions if d.action == "hold"),
    }
    return {"learning_log": [entry]}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("ingest", ingest)
    graph.add_node("assess_campaign", assess_campaign)
    graph.add_node("aggregate_and_prioritize", aggregate_and_prioritize)
    graph.add_node("log_run", log_run)

    graph.set_entry_point("ingest")
    graph.add_conditional_edges("ingest", fan_out_assessments, ["assess_campaign"])
    graph.add_edge("assess_campaign", "aggregate_and_prioritize")
    graph.add_edge("aggregate_and_prioritize", "log_run")
    graph.add_edge("log_run", END)

    return graph.compile()
