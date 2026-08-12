"""
Transfer & Conversion Intelligence Platform :: fine-tuning dataset checks.

No model is trained here and none is loaded. What is checked is the property that
actually matters for a governed platform: **training data cannot be allowed to
contradict the catalogue.**

Weights are the one artefact in this architecture that cannot be diffed against
`tr_gov.metric_definition`. Once a definition is baked into a model, there is no
grep that finds it and no test that reads it. So the guard has to sit on the
dataset, and it has to fail the build when a metric version changes and the
dataset was not regenerated.

The second property: the dataset teaches *language and abstention*, never values.
A pair that stated a number would be teaching the model to answer questions that
belong to the governed tools.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fine_tuning.dataset import BEHAVIOUR_PAIRS, build  # noqa: E402
from fine_tuning.evaluate import (ABSTENTION_PROBES,  # noqa: E402
                                  check_dataset_consistency, load_pairs)

DATASET = os.path.join(os.path.dirname(__file__), "..", "fine_tuning",
                       "dataset.jsonl")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def catalogue_rows():
    from api import catalogue
    return catalogue.all_metrics()


@check("the dataset regenerates deterministically from the catalogue")
def _():
    a = build(catalogue_rows())
    b = build(catalogue_rows())
    return a == b, f"{len(a)} pairs, identical across two builds"


@check("the dataset is in the specified 100-200 pair range")
def _():
    pairs = build(catalogue_rows())
    behaviour = sum(p["kind"] == "behaviour" for p in pairs)
    return (100 <= len(pairs) <= 200,
            f"{len(pairs)} pairs ({len(pairs) - behaviour} definition, "
            f"{behaviour} behavioural)")


@check("the committed dataset.jsonl is valid and current")
def _():
    if not os.path.exists(DATASET):
        return False, "dataset.jsonl missing - run python fine_tuning/dataset.py"
    on_disk = load_pairs(DATASET)
    fresh = build(catalogue_rows())
    stale = len(on_disk) != len(fresh)
    return not stale, (f"{len(on_disk)} pairs on disk"
                       + (f", but the catalogue now yields {len(fresh)} - regenerate"
                          if stale else ", matching the current catalogue"))


@check("every definition pair is consistent with the live catalogue")
def _():
    checked, stale = check_dataset_consistency(build(catalogue_rows()),
                                               catalogue_rows())
    return not stale, ("; ".join(stale[:3]) if stale
                       else f"{checked} definition pairs trace to a registered metric")


@check("every definition pair names a metric that is actually registered")
def _():
    registered = {m["metric_code"] for m in catalogue_rows()}
    used = {p["metric_code"] for p in build(catalogue_rows())
            if p["metric_code"]}
    orphans = used - registered
    uncovered = registered - used
    return (not orphans and not uncovered,
            f"orphans={sorted(orphans)}, uncovered={sorted(uncovered)}"
            if (orphans or uncovered)
            else f"all {len(registered)} registered metrics covered, none invented")


@check("no training pair states a metric value")
def _():
    # Version numbers and fiscal-year labels are vocabulary. A quantity with a
    # unit -- "240 days", "62%" -- would be teaching the model an answer that
    # belongs to the governed tools and goes stale the moment data changes.
    offenders = []
    for p in build(catalogue_rows()):
        text = re.sub(r"\bversion \d+(\.\d+)?\b|\bFY\d{2}\b|\b\d{4}\b", "",
                      p["response"])
        for m in re.findall(r"\b\d+(?:\.\d+)?\s*(?:days?|%|percent)\b", text):
            offenders.append(f"{p['instruction'][:40]!r}: {m}")
    return not offenders, ("; ".join(offenders[:3]) or
                           "no quantities in any response")


@check("behaviour pairs teach abstention, refusal and cohort discipline")
def _():
    responses = " ".join(r for _q, r in BEHAVIOUR_PAIRS).lower()
    needed = {
        "ambiguity": "more than one governed metric",
        "no invented numbers": "don't state figures",
        "read-only": "read-only",
        "injection": "data, not as commands",
        "cohort discipline": "shouldn't be mixed",
        "metric gaming": "moves the target",
    }
    missing = [k for k, v in needed.items() if v not in responses]
    return not missing, (f"missing {missing}" if missing
                         else f"{len(BEHAVIOUR_PAIRS)} behaviour pairs covering "
                              f"{', '.join(needed)}")


@check("every abstention probe has a matching behaviour pair to learn from")
def _():
    taught = {q for q, _r in BEHAVIOUR_PAIRS}
    missing = [q for q, _m in ABSTENTION_PROBES if q not in taught]
    return not missing, (f"unteachable probes: {missing}" if missing
                         else f"{len(ABSTENTION_PROBES)} probes, each with "
                              f"training data behind it")


@check("the platform does not depend on a tuned model")
def _():
    # The claim that fine-tuning is an experiment has to be structurally true,
    # not just asserted in a docstring.
    agent_dir = os.path.join(os.path.dirname(__file__), "..", "agent")
    offenders = []
    for fname in os.listdir(agent_dir):
        if not fname.endswith(".py"):
            continue
        text = open(os.path.join(agent_dir, fname), encoding="utf-8").read().lower()
        for needle in ("peft", "transformers", "adapter", "fine_tuning", "torch"):
            if needle in text:
                offenders.append(f"{fname}: {needle}")
    return not offenders, ("; ".join(offenders) or
                           "no model loading anywhere in agent/")


def run():
    print("Fine-tuning dataset checks")
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
