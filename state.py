"""
State schema for the Campaign Performance Triage Agent.

Design notes:
- CampaignMetrics is the Perception artifact: raw platform data normalized
  into a structured shape the agent can reason over.
- ClientPolicy encodes per-client business rules (tolerances, escalation
  thresholds). This is what makes the agent's judgment client-specific
  rather than a generic rule engine.
- CampaignDecision is the Planning/Action output: one per campaign, always
  carrying a rationale string so every decision is auditable in the log
  and in LangSmith traces. This is non-negotiable for a "recommend only"
  agent whose entire value proposition is trustworthy reasoning.
- AgentState is the graph-level state object threaded through all nodes.
"""

from __future__ import annotations
import operator
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field


class CampaignMetrics(BaseModel):
    campaign_id: str
    client_id: str
    client_name: str
    platform: Literal["meta", "google"]
    campaign_name: str
    objective: Literal["conversions", "lead_gen", "traffic", "awareness"]
    date: str

    daily_spend: float
    target_daily_budget: float

    cpa: float
    target_cpa: float

    roas: float
    target_roas: float

    ctr: float
    conversions: int
    impressions: int

    days_active: int = Field(description="Days this campaign has been live; short-running campaigns get more benefit of the doubt")


class ClientPolicy(BaseModel):
    client_id: str
    client_name: str
    cpa_tolerance_pct: float = Field(description="How far above target_cpa before flagged underperforming, e.g. 0.15 = 15%")
    roas_tolerance_pct: float = Field(description="How far below target_roas before flagged underperforming")
    max_auto_scale_pct: float = Field(description="Max budget increase the agent may recommend in one pass without escalation")
    escalation_spend_threshold: float = Field(description="Daily spend above which ANY action recommendation requires human approval regardless of confidence")
    min_days_before_judgment: int = Field(default=3, description="Campaigns younger than this are held, not judged")


class PerformanceClassification(BaseModel):
    campaign_id: str
    status: Literal["over_performing", "on_target", "underperforming", "anomalous", "insufficient_data"]
    signals: list[str] = Field(description="Specific metric deviations driving the classification")
    confidence: float = Field(ge=0.0, le=1.0)


class CampaignDecision(BaseModel):
    campaign_id: str
    campaign_name: str
    client_id: str
    action: Literal["scale_budget", "pause", "reallocate_budget", "hold", "escalate_to_human"]
    magnitude_pct: Optional[float] = Field(default=None, description="Budget change magnitude if action is scale_budget")
    rationale: str = Field(description="Human-readable justification, written for an account manager to read in under 10 seconds")
    requires_human_approval: bool
    dollar_impact_daily: float = Field(description="Estimated daily $ impact of this decision, used for prioritization")
    confidence: float = Field(ge=0.0, le=1.0)


class AgentState(BaseModel):
    run_date: str
    client_ids: list[str] = Field(default_factory=list)

    raw_metrics: list[CampaignMetrics] = Field(default_factory=list)
    policies: dict[str, ClientPolicy] = Field(default_factory=dict)

    # Annotated with operator.add so parallel assess_campaign branches can
    # each append their single result without clobbering sibling writes --
    # required any time multiple Send-fanned branches write to the same key.
    classifications: Annotated[list[PerformanceClassification], operator.add] = Field(default_factory=list)
    decisions: Annotated[list[CampaignDecision], operator.add] = Field(default_factory=list)

    # Plain (non-reducer) field: written exactly once by aggregate_and_prioritize,
    # so a LastValue channel is correct here -- reusing `decisions` itself for
    # this would double-append since it's re-writing the same items.
    ranked_decisions: list[CampaignDecision] = Field(default_factory=list)

    learning_log: Annotated[list[dict], operator.add] = Field(default_factory=list)
