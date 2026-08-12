"""
Transfer & Conversion Intelligence Platform :: scheduled refresh DAG.

Airflow is **optional** here and deliberately not in requirements.txt. The plan's
own rule is to introduce a tool only for clear value, and the pipeline logic does
not need an orchestrator to be correct -- `etl/ingest.py` runs standalone.

What an orchestrator adds is operational: a schedule, retries with backoff,
dependency ordering, and backfills when a definition changes and history has to
be rebuilt for earlier periods. So this file models exactly that and nothing
else. Every task delegates to the same functions the CLI calls; there is no SQL
here and no business logic, because a second copy of the pipeline living in a DAG
is how orchestration starts quietly disagreeing with the thing it orchestrates.

    pip install apache-airflow
    AIRFLOW_HOME=. airflow dags list
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

DSN = os.environ.get("TRANSFEROPS_DSN",
                     "postgresql://app:dev@localhost:5432/transferops")

DEFAULT_ARGS = {
    "owner": "transfer-management",
    "retries": 2,
    # Upstream feeds fail transiently far more often than they fail permanently,
    # so back off rather than paging someone.
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


def _generate(**_):
    from generate_data import main as generate
    generate()


def _ingest(**context):
    """Land, validate, promote -- the whole layered path, one batch per run."""
    from ingest import ingest
    con, summary = ingest(
        engine="postgres", dsn=DSN,
        batch_id=f"batch-{context['ds_nodash']}")
    try:
        # Surface the batch outcome to the UI without duplicating any logic.
        context["ti"].xcom_push(key="summary", value={
            "batch_id": summary["batch_id"],
            "landed": summary["landed"],
            "core_projects": summary["core_projects"],
            "quarantined": summary["quarantined"],
        })
        if summary["core_failures"] or summary["metric_failures"]:
            raise ValueError(
                "core/metric data-quality tier failed: "
                f"{[n for n, _s, _r in summary['core_failures'] + summary['metric_failures']]}")
    finally:
        con.close()


def _reconcile(**_):
    """
    The gate that matters: never publish metrics that do not reconcile.

    Deliberately the last task rather than a separate monitoring concern -- a
    refresh that silently changes a KPI is worse than a refresh that failed.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
    from golden_projects import run as golden
    if not golden():
        raise ValueError("golden-project reconciliation failed; metrics not published")


def _governance(**_):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
    from governance_checks import run as governance
    if not governance():
        raise ValueError("metric catalogue and calculation layer disagree")


def _refresh_ai(**_):
    """
    Warm the AI caches against the vintage this run just published.

    Ordering is the whole point of putting it here rather than on its own
    schedule. A narrative generated while the warehouse is half-loaded is not a
    stale narrative, it is a wrong one -- and it would carry the new vintage
    stamp while describing the old data. So it runs after the load *and* after
    the gates, and it never gates them in return: a model being unavailable must
    not fail a warehouse refresh that already reconciled.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ai import gateway, refresh
    from bi.client import Api

    if not gateway.configured():
        return {"status": "skipped", "detail": "no model configured"}

    api = Api(identity=os.environ.get("TRANSFEROPS_AI_IDENTITY", "admin"))
    try:
        return refresh.run_all(api, trigger="cron")
    except Exception as exc:  # noqa: BLE001
        # Recorded in tr_ai.run_log by the job itself; surfaced here as a log
        # line rather than a failed DAG run.
        print(f"AI refresh did not complete: {type(exc).__name__}: {exc}")
        return {"status": "failed", "detail": str(exc)}


with DAG(
    dag_id="transferops_refresh",
    description="Layered transfer-portfolio refresh with data-quality gates",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule="0 5 * * *",          # daily, before the reporting day starts
    catchup=False,                 # backfills are run deliberately, not by surprise
    max_active_runs=1,             # one writer at a time against the warehouse
    tags=["transferops", "warehouse"],
) as dag:

    generate = PythonOperator(
        task_id="generate_source_extracts",
        python_callable=_generate,
        doc_md="Stands in for the upstream extract. In a real deployment this "
               "task would pull from the source systems instead.",
    )

    ingest_and_validate = PythonOperator(
        task_id="ingest_raw_stage_core",
        python_callable=_ingest,
        doc_md="CSV -> tr_raw -> ingestion checks -> tr_stg -> tr_core, then the "
               "core and metric tiers. REJECT rows are quarantined; the clean "
               "majority still lands.",
    )

    reconcile = PythonOperator(
        task_id="golden_reconciliation",
        python_callable=_reconcile,
        doc_md="31 golden projects across 11 categories, recomputed "
               "independently from source. Fails the run rather than publishing "
               "numbers that moved.",
    )

    governance = PythonOperator(
        task_id="metric_governance",
        python_callable=_governance,
        doc_md="Every registered metric is implemented, and no metric returns a "
               "population its own definition excludes.",
    )

    refresh_ai = PythonOperator(
        task_id="refresh_ai_caches",
        python_callable=_refresh_ai,
        # A model outage should not fail a warehouse refresh that already
        # reconciled. The run is recorded either way, and the console shows it.
        trigger_rule="all_success",
        doc_md="Warms the cached narratives and re-scores in-flight projects "
               "against the vintage this run published. Skipped when no model is "
               "configured; never gates the warehouse.",
    )

    generate >> ingest_and_validate >> [reconcile, governance] >> refresh_ai
