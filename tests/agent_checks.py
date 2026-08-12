"""
Transfer & Conversion Intelligence Platform :: agent evaluation, wired to run in-process.

Drives the whole agent pipeline against the ASGI API without a server, so the
eval suite runs in CI next to the golden and governance gates rather than being
a thing someone remembers to do by hand.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# These suites drive the demo identities (manager.auto, admin.demo) instead of
# standing up Keycloak, so they opt into demo mode explicitly. The platform
# default is enforce -- security is never opt-in -- and tests/security_checks.py
# asserts that default plus the fact that X-Demo-User is refused without it.
os.environ.setdefault("TRANSFEROPS_AUTH", "demo")

from fastapi.testclient import TestClient  # noqa: E402

from agent.app import ApiClient  # noqa: E402
from agent.evals.run_evals import evaluate, report  # noqa: E402
from api.main import app as api_app  # noqa: E402


def run():
    # TestClient is a synchronous httpx.Client that speaks ASGI, so the agent
    # drives the real API in-process -- same code path as production, no server.
    return report(evaluate(api=ApiClient(client=TestClient(api_app))))


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
