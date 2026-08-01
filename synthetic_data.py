"""
Synthetic data generator standing in for a live Meta Marketing API / Google
Ads API pull. Swapping this for a real fetcher later requires no changes to
the graph -- it just needs to return list[CampaignMetrics] in this shape.

Simulates a small agency book: 3 clients, 2-4 campaigns each, with metrics
engineered to hit every classification bucket (over-performing, on-target,
underperforming, anomalous, too-young-to-judge) so the demo run exercises
the full decision space.
"""

from datetime import date
from state import CampaignMetrics, ClientPolicy

RUN_DATE = date.today().isoformat()


def get_synthetic_metrics() -> list[CampaignMetrics]:
    return [
        # --- Client: Northbound Coffee Co. (e-commerce, conversions) ---
        CampaignMetrics(
            campaign_id="cmp_001", client_id="cl_northbound", client_name="Northbound Coffee Co.",
            platform="meta", campaign_name="NB - Retargeting - Cart Abandon", objective="conversions",
            date=RUN_DATE, daily_spend=180.0, target_daily_budget=150.0,
            cpa=14.20, target_cpa=18.00, roas=4.8, target_roas=3.5,
            ctr=0.021, conversions=13, impressions=52000, days_active=45,
        ),
        CampaignMetrics(
            campaign_id="cmp_002", client_id="cl_northbound", client_name="Northbound Coffee Co.",
            platform="google", campaign_name="NB - Search - Brand Terms", objective="conversions",
            date=RUN_DATE, daily_spend=95.0, target_daily_budget=100.0,
            cpa=17.50, target_cpa=18.00, roas=3.6, target_roas=3.5,
            ctr=0.045, conversions=5, impressions=8100, days_active=120,
        ),
        CampaignMetrics(
            campaign_id="cmp_003", client_id="cl_northbound", client_name="Northbound Coffee Co.",
            platform="meta", campaign_name="NB - Prospecting - Lookalike 1%", objective="conversions",
            date=RUN_DATE, daily_spend=310.0, target_daily_budget=200.0,
            cpa=41.00, target_cpa=18.00, roas=1.1, target_roas=3.5,
            ctr=0.008, conversions=7, impressions=140000, days_active=9,
        ),

        # --- Client: Ferro & Vale Law Group (lead gen, high stakes/spend) ---
        CampaignMetrics(
            campaign_id="cmp_004", client_id="cl_ferrovale", client_name="Ferro & Vale Law Group",
            platform="google", campaign_name="FV - Search - Personal Injury", objective="lead_gen",
            date=RUN_DATE, daily_spend=850.0, target_daily_budget=700.0,
            cpa=210.0, target_cpa=180.0, roas=0, target_roas=0,
            ctr=0.038, conversions=4, impressions=6200, days_active=200,
        ),
        CampaignMetrics(
            campaign_id="cmp_005", client_id="cl_ferrovale", client_name="Ferro & Vale Law Group",
            platform="meta", campaign_name="FV - Lead Form - Family Law", objective="lead_gen",
            date=RUN_DATE, daily_spend=60.0, target_daily_budget=150.0,
            cpa=310.0, target_cpa=140.0, roas=0, target_roas=0,
            ctr=0.004, conversions=0, impressions=15000, days_active=14,
        ),

        # --- Client: Lumen Skincare (DTC, mix of new and mature) ---
        CampaignMetrics(
            campaign_id="cmp_006", client_id="cl_lumen", client_name="Lumen Skincare",
            platform="meta", campaign_name="LM - Launch - New Serum", objective="conversions",
            date=RUN_DATE, daily_spend=220.0, target_daily_budget=220.0,
            cpa=22.0, target_cpa=25.0, roas=3.9, target_roas=3.0,
            ctr=0.019, conversions=10, impressions=61000, days_active=2,
        ),
        CampaignMetrics(
            campaign_id="cmp_007", client_id="cl_lumen", client_name="Lumen Skincare",
            platform="google", campaign_name="LM - Shopping - Core Catalog", objective="conversions",
            date=RUN_DATE, daily_spend=430.0, target_daily_budget=400.0,
            cpa=19.5, target_cpa=25.0, roas=5.1, target_roas=3.0,
            ctr=0.031, conversions=22, impressions=98000, days_active=310,
        ),
        CampaignMetrics(
            campaign_id="cmp_008", client_id="cl_lumen", client_name="Lumen Skincare",
            platform="meta", campaign_name="LM - Prospecting - Broad", objective="conversions",
            date=RUN_DATE, daily_spend=150.0, target_daily_budget=150.0,
            cpa=61.0, target_cpa=25.0, roas=1.4, target_roas=3.0,
            ctr=0.006, conversions=2, impressions=88000, days_active=60,
        ),
    ]


def get_client_policies() -> dict[str, ClientPolicy]:
    policies = [
        ClientPolicy(
            client_id="cl_northbound", client_name="Northbound Coffee Co.",
            cpa_tolerance_pct=0.15, roas_tolerance_pct=0.15,
            max_auto_scale_pct=0.20, escalation_spend_threshold=250.0,
            min_days_before_judgment=3,
        ),
        ClientPolicy(
            client_id="cl_ferrovale", client_name="Ferro & Vale Law Group",
            cpa_tolerance_pct=0.10, roas_tolerance_pct=0.10,
            max_auto_scale_pct=0.10, escalation_spend_threshold=100.0,
            min_days_before_judgment=5,
        ),
        ClientPolicy(
            client_id="cl_lumen", client_name="Lumen Skincare",
            cpa_tolerance_pct=0.20, roas_tolerance_pct=0.20,
            max_auto_scale_pct=0.25, escalation_spend_threshold=300.0,
            min_days_before_judgment=3,
        ),
    ]
    return {p.client_id: p for p in policies}
