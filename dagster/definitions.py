"""Starter code location for the Railway Dagster template.

A small dependency-free asset graph plus a daily schedule, so the deployment
has something to materialize and the daemon has something to run out of the
box. Replace this file with your own pipelines and rebuild the image (or fork
the template repo and point CI at your fork).
"""

import random

from dagster import (
    AssetExecutionContext,
    Definitions,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    define_asset_job,
)


@asset(group_name="starter")
def raw_orders(context: AssetExecutionContext) -> list[dict]:
    """Pretend ingestion step — swap for your API / DB / file source."""
    orders = [
        {"order_id": i, "amount_eur": round(random.uniform(5.0, 250.0), 2)}
        for i in range(1, 51)
    ]
    context.log.info("Ingested %d orders", len(orders))
    return orders


@asset(group_name="starter")
def order_stats(context: AssetExecutionContext, raw_orders: list[dict]) -> dict:
    """Pretend transform step — aggregates the raw feed."""
    amounts = [o["amount_eur"] for o in raw_orders]
    stats = {
        "count": len(amounts),
        "revenue_eur": round(sum(amounts), 2),
        "avg_order_eur": round(sum(amounts) / len(amounts), 2),
        "max_order_eur": max(amounts),
    }
    context.log.info("Computed stats: %s", stats)
    return stats


@asset(group_name="starter")
def daily_report(context: AssetExecutionContext, order_stats: dict) -> MaterializeResult:
    """Pretend publish step — renders a report into asset metadata."""
    report = (
        f"### Daily order report\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Orders | {order_stats['count']} |\n"
        f"| Revenue | €{order_stats['revenue_eur']} |\n"
        f"| Average order | €{order_stats['avg_order_eur']} |\n"
        f"| Largest order | €{order_stats['max_order_eur']} |\n"
    )
    context.log.info("Report ready")
    return MaterializeResult(
        metadata={
            "report": MetadataValue.md(report),
            "orders": order_stats["count"],
            "revenue_eur": order_stats["revenue_eur"],
        }
    )


starter_pipeline = define_asset_job(
    "starter_pipeline",
    selection="*",
    description="Materializes the full starter asset graph.",
)

daily_schedule = ScheduleDefinition(
    name="daily_starter_pipeline",
    job=starter_pipeline,
    cron_schedule="0 6 * * *",
    execution_timezone="Europe/Berlin",
)

defs = Definitions(
    assets=[raw_orders, order_stats, daily_report],
    jobs=[starter_pipeline],
    schedules=[daily_schedule],
)
