"""
Transfer & Conversion Intelligence Platform :: orchestration checks.

Airflow is optional and deliberately absent from requirements.txt, so these
checks read the DAG as source rather than importing it. That is not a compromise
-- the two properties actually worth guaranteeing are both structural:

  * the DAG contains no SQL and no business logic. An orchestrator that grows its
    own copy of the pipeline is how scheduling starts quietly disagreeing with
    the thing it schedules, which is the same failure the metric layer exists to
    prevent, one floor up.
  * the ordering is right, and quality gates come *after* the load rather than
    beside it. A refresh that silently changes a KPI is worse than one that failed.

A syntax error would also be invisible until someone installed Airflow, so the
file is parsed here too.
"""
import ast
import os
import sys

DAGS = os.path.join(os.path.dirname(__file__), "..", "dags")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def dag_files():
    return [os.path.join(DAGS, f) for f in sorted(os.listdir(DAGS))
            if f.endswith(".py")]


def source(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@check("every DAG file parses")
def _():
    bad = []
    for path in dag_files():
        try:
            ast.parse(source(path))
        except SyntaxError as exc:
            bad.append(f"{os.path.basename(path)}:{exc.lineno} {exc.msg}")
    return not bad, "; ".join(bad) or f"{len(dag_files())} DAG file(s) parse"


@check("the DAG delegates rather than reimplementing the pipeline")
def _():
    offenders = []
    for path in dag_files():
        text = source(path).lower()
        for needle in ("select ", "insert into", "create view", "create table",
                       "psycopg2.connect", "duckdb.connect"):
            if needle in text:
                offenders.append(f"{os.path.basename(path)}: {needle.strip()}")
    return not offenders, "; ".join(offenders) or "no SQL or connections in dags/"


@check("the DAG calls the same entrypoints the CLI does")
def _():
    text = source(os.path.join(DAGS, "transferops_pipeline.py"))
    expected = ["from ingest import ingest",
                "from generate_data import main",
                "from golden_projects import run",
                "from governance_checks import run"]
    missing = [e for e in expected if e not in text]
    return not missing, (f"missing {missing}" if missing
                         else "reuses ingest, generate_data, and both gates")


@check("quality gates run after the load, and failure fails the run")
def _():
    text = source(os.path.join(DAGS, "transferops_pipeline.py"))
    ordered = "generate >> ingest_and_validate >> [reconcile, governance]" in text
    raises = text.count("raise ValueError") >= 3
    return ordered and raises, (
        f"ordering declared: {ordered}; gates raise rather than warn: {raises}")


@check("retries and a single writer are configured")
def _():
    tree = ast.parse(source(os.path.join(DAGS, "transferops_pipeline.py")))
    text = source(os.path.join(DAGS, "transferops_pipeline.py"))
    has_retries = '"retries": 2' in text and "retry_delay" in text
    single_writer = "max_active_runs=1" in text
    no_surprise_backfill = "catchup=False" in text
    assert isinstance(tree, ast.Module)
    return (has_retries and single_writer and no_surprise_backfill,
            f"retries={has_retries}, max_active_runs=1: {single_writer}, "
            f"catchup disabled: {no_surprise_backfill}")


def run():
    print("Orchestration checks")
    print("-" * 72)
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
