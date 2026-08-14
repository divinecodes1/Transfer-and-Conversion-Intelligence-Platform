"""
Trigger the nightly AI refresh through the governed API's signed endpoint.

`python -m ai.refresh` is the *local* path: it drives the API as an HTTP client
under an asserted identity. That works on a laptop in demo mode and cannot work
in a deployment, because the identity is asserted with `X-Demo-User` and
TRANSFEROPS_AUTH=enforce refuses that header by design -- it is the
authentication bypass docs/PRODUCTION.md documents closing. Handing the job a
Keycloak service account would mean a non-human identity with standing access
to governed data, which is a real decision and not a config tweak.

So the scheduled path does not authenticate as anybody. It asks the API to
refresh *itself*: `POST /ai/refresh` runs generation in-process through
`_LocalApi`, so no token crosses a wire, and the request is authorised by an
HMAC over the body with a shared secret instead. With no secret configured that
endpoint refuses everything rather than defaulting to open.

The signature must be computed over exactly the bytes that are sent -- the API
verifies against the raw body -- so the payload is written once and reused,
never re-serialised between signing and posting.

    python -m ai.trigger              # job=all
    TRANSFEROPS_AI_JOB=risk python -m ai.trigger
"""
import hashlib
import hmac
import os
import sys

BODY = b"{}"


def main() -> int:
    base = os.environ.get("TRANSFEROPS_API", "").strip().rstrip("/")
    secret = os.environ.get("TRANSFEROPS_AI_CRON_SECRET", "").strip()
    job = os.environ.get("TRANSFEROPS_AI_JOB", "all").strip() or "all"
    trigger = os.environ.get("TRANSFEROPS_AI_TRIGGER", "scheduled").strip()

    if not base:
        print("TRANSFEROPS_API is not set; nothing to call.", file=sys.stderr)
        return 1
    if not secret:
        print("TRANSFEROPS_AI_CRON_SECRET is not set; the endpoint would refuse "
              "the request anyway.", file=sys.stderr)
        return 1

    import httpx

    signature = hmac.new(secret.encode("utf-8"), BODY, hashlib.sha256).hexdigest()
    url = f"{base}/ai/refresh"
    print(f"POST {url}?job={job} (trigger={trigger})")

    try:
        # Generous, because this is the one request that may sit behind a model.
        # The API's own ceiling stops it long before this does.
        response = httpx.post(
            url,
            params={"job": job},
            content=BODY,
            headers={
                "content-type": "application/json",
                "x-transferops-signature": signature,
                "x-transferops-trigger": trigger,
            },
            timeout=300.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP {response.status_code}")
    print(response.text[:2000])
    # A refresh that fails must fail the invocation: a scheduled job that always
    # reports success is a scheduled job nobody notices has stopped working.
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
