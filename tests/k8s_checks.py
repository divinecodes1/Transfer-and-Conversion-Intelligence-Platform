"""
Transfer & Conversion Intelligence Platform :: Kubernetes manifest checks.

No cluster is created here. What is checked is what YAML that has never been
applied usually gets wrong, and what would be embarrassing to discover live:

  * it parses, and every document declares apiVersion/kind/metadata;
  * every Deployment has probes, resource limits and a non-root security context
    -- manifests without these look fine until the first OOM or crash-loop;
  * every Service selector matches a Deployment that exists. A typo here produces
    a Service with no endpoints, which fails silently;
  * the dashboard holds no database credentials, because the whole BI argument is
    that it reaches data only through the API. The manifest has to agree with the
    code, or the architecture is only true on the developer's laptop.

Requires PyYAML, which arrives with several existing dependencies.
"""
import os
import sys

import yaml

MANIFEST = os.path.join(os.path.dirname(__file__), "..", "kubernetes",
                        "transferops.yaml")
DOCKERFILE = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def docs():
    with open(MANIFEST, encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f) if d]


def of_kind(kind):
    return [d for d in docs() if d.get("kind") == kind]


@check("every manifest document parses and is well formed")
def _():
    bad = [f"doc {i}" for i, d in enumerate(docs())
           if not all(k in d for k in ("apiVersion", "kind", "metadata"))]
    kinds = {}
    for d in docs():
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    return not bad, ("; ".join(bad) or
                     ", ".join(f"{v}x {k}" for k, v in sorted(kinds.items())))


@check("everything is namespaced, so nothing lands in default")
def _():
    stray = [f"{d['kind']}/{d['metadata']['name']}" for d in docs()
             if d["kind"] != "Namespace"
             and d["metadata"].get("namespace") != "transferops"]
    return not stray, "; ".join(stray) or "all resources in namespace transferops"


@check("every Deployment declares probes")
def _():
    missing = []
    for d in of_kind("Deployment"):
        for c in d["spec"]["template"]["spec"]["containers"]:
            if "livenessProbe" not in c:
                missing.append(f"{d['metadata']['name']}/{c['name']}")
    return not missing, ("; ".join(missing) or
                         f"{len(of_kind('Deployment'))} deployments, all probed")


@check("every Deployment declares resource requests and limits")
def _():
    missing = []
    for d in of_kind("Deployment"):
        for c in d["spec"]["template"]["spec"]["containers"]:
            res = c.get("resources", {})
            if not res.get("requests") or not res.get("limits"):
                missing.append(f"{d['metadata']['name']}/{c['name']}")
    return not missing, ("; ".join(missing) or
                         "every container has requests and limits")


@check("application containers run as non-root without privilege escalation")
def _():
    ours = [d for d in of_kind("Deployment")
            if d["metadata"]["name"] != "qdrant"]      # third-party image
    problems = []
    for d in ours:
        spec = d["spec"]["template"]["spec"]
        if not spec.get("securityContext", {}).get("runAsNonRoot"):
            problems.append(f"{d['metadata']['name']}: pod not runAsNonRoot")
        for c in spec["containers"]:
            sc = c.get("securityContext", {})
            if sc.get("allowPrivilegeEscalation") is not False:
                problems.append(f"{d['metadata']['name']}/{c['name']}: escalation")
    return not problems, ("; ".join(problems) or
                          f"{len(ours)} application deployments locked down")


@check("every Service selector matches a Deployment that exists")
def _():
    labels = {tuple(sorted(d["spec"]["template"]["metadata"]["labels"].items()))
              for d in of_kind("Deployment")}
    orphans = []
    for s in of_kind("Service"):
        sel = tuple(sorted(s["spec"]["selector"].items()))
        if not any(set(sel) <= set(l) for l in labels):
            orphans.append(f"{s['metadata']['name']} -> {dict(sel)}")
    return not orphans, ("; ".join(orphans) or
                         f"{len(of_kind('Service'))} services, all with endpoints")


@check("the dashboard holds no database credentials")
def _():
    # The BI layer reaches data only through the API. bi_checks asserts this in
    # the code; this asserts the deployment agrees.
    dash = next(d for d in of_kind("Deployment")
                if d["metadata"]["name"] == "dashboard")
    sources = []
    for c in dash["spec"]["template"]["spec"]["containers"]:
        for ref in c.get("envFrom", []):
            sources.extend(ref.keys() and [list(ref.values())[0]["name"]])
    leaked = [s for s in sources if "db" in s]
    return not leaked, (f"dashboard mounts {leaked}" if leaked
                        else f"dashboard mounts only {sources}")


@check("the container image runs as a non-root user")
def _():
    text = open(DOCKERFILE, encoding="utf-8").read()
    return ("USER transferops" in text and "useradd" in text,
            "Dockerfile creates and switches to an unprivileged user")


@check("stateful components are deliberately excluded")
def _():
    # PostgreSQL, Prometheus, Grafana and Keycloak stay in Compose. Deploying a
    # stateful warehouse into a local kind cluster adds failure modes to a demo
    # and proves nothing architecturally.
    names = {d["metadata"]["name"] for d in of_kind("Deployment")}
    unexpected = names & {"postgres", "postgresql", "prometheus", "grafana",
                          "keycloak"}
    return not unexpected, (f"unexpectedly deployed: {sorted(unexpected)}"
                            if unexpected
                            else f"deploys only {sorted(names)}; stateful "
                                 f"components remain in docker-compose")


def run():
    print("Kubernetes manifest checks")
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
