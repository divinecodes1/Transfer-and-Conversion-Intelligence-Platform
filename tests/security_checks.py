"""
Transfer & Conversion Intelligence Platform :: security checks.

Each check here exists because the property it asserts was once wrong, or would
be easy to make wrong again. Security posture is exactly the kind of thing that
looks fine in review and rots in a config file, so it gets the same treatment as
metric governance: an executable gate rather than a paragraph.

The one that matters most is the first. `TRANSFEROPS_AUTH=enforce` used to accept
the `X-Demo-User` header, which meant the documented "production" mode granted
full PLATFORM_ADMIN access to anyone who sent one header and no credentials. It
was invisible because every test drove demo mode, where the behaviour is correct.

Requires the PostgreSQL warehouse:
    make pg-up && make pg-build
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Deliberately NOT setting TRANSFEROPS_AUTH here: this suite asserts what the
# platform does with its own default, and flips the mode per check.
from fastapi.testclient import TestClient  # noqa: E402

from api import auth  # noqa: E402
from api.main import app as api_app  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def with_auth(mode):
    """Run against a specific auth mode, restoring whatever was set before."""
    class _Ctx:
        def __enter__(self):
            self.prev = os.environ.get("TRANSFEROPS_AUTH")
            if mode is None:
                os.environ.pop("TRANSFEROPS_AUTH", None)
            else:
                os.environ["TRANSFEROPS_AUTH"] = mode
            return TestClient(api_app)

        def __exit__(self, *exc):
            if self.prev is None:
                os.environ.pop("TRANSFEROPS_AUTH", None)
            else:
                os.environ["TRANSFEROPS_AUTH"] = self.prev
    return _Ctx()


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
@check("enforce mode refuses the demo identity header")
def _():
    # The regression test for an authentication bypass: X-Demo-User is an
    # unauthenticated claim of identity and must carry no weight in enforce mode.
    with with_auth("enforce") as c:
        results = {u: c.get("/whoami", headers={"X-Demo-User": u}).status_code
                   for u in ("admin.demo", "manager.auto", "analyst.demo")}
    granted = {u: s for u, s in results.items() if s == 200}
    return not granted, (f"GRANTED without credentials: {granted}" if granted
                         else f"all refused with {sorted(set(results.values()))}")


@check("enforce mode refuses an unauthenticated caller")
def _():
    with with_auth("enforce") as c:
        codes = {p: c.get(p).status_code
                 for p in ("/whoami", "/health", "/catalogue", "/metrics/cycle-time",
                           "/projects")}
    open_paths = {p: s for p, s in codes.items() if s == 200}
    return not open_paths, (f"reachable anonymously: {open_paths}" if open_paths
                            else f"{len(codes)} endpoints all 401")


@check("the default posture is enforce -- security is never opt-in")
def _():
    # A deployment that forgets to set TRANSFEROPS_AUTH must land in the safe
    # state, not the convenient one.
    with with_auth(None) as c:
        mode = auth.auth_mode()
        anon = c.get("/whoami").status_code
        header = c.get("/whoami", headers={"X-Demo-User": "admin.demo"}).status_code
    return (mode == "enforce" and anon == 401 and header == 401,
            f"unset TRANSFEROPS_AUTH -> mode={mode}, anonymous={anon}, header={header}")


@check("demo mode still works, and is clearly labelled as unauthenticated")
def _():
    # The escape hatch has to keep working, or people disable the whole control.
    with with_auth("demo") as c:
        anon = c.get("/whoami").json()
        scoped = c.get("/whoami", headers={"X-Demo-User": "manager.auto"}).json()
    return (anon["username"] == "admin.demo" and anon["source"] == "demo-default"
            and scoped["username"] == "manager.auto"
            and scoped["source"] == "demo-header"
            and scoped["portfolios"] == ["PF_AUTO"],
            f"anonymous={anon['source']}, header={scoped['source']} "
            f"scoped to {scoped['portfolios']}")


@check("no login password is written into the SQL files")
def _():
    # Role credentials are supplied by the loader from the environment. A
    # password in version control is a password published with the repository,
    # and rotating it would mean a code change.
    offenders = []
    sql_dir = os.path.join(ROOT, "sql")
    for name in sorted(os.listdir(sql_dir)):
        if not name.endswith(".sql"):
            continue
        for m in re.finditer(r"PASSWORD\s+'([^']*)'", read("sql", name), re.IGNORECASE):
            offenders.append(f"{name}: PASSWORD '{m.group(1)}'")
    return not offenders, ("; ".join(offenders) or
                           "role passwords come from the environment, via "
                           "current_setting()")


@check("a remote warehouse refuses to install a default credential")
def _():
    sys.path.insert(0, os.path.join(ROOT, "etl"))
    import credentials
    quiet = lambda *_a: None
    local_ok = remote_refused = False
    try:
        credentials.apply(lambda *_a: None, "postgresql://u:p@localhost:5432/db", warn=quiet)
        local_ok = True
    except SystemExit:
        pass
    try:
        credentials.apply(lambda *_a: None,
                          "postgresql://u:p@warehouse.internal:5432/db", warn=quiet)
    except SystemExit:
        remote_refused = True
    return (local_ok and remote_refused,
            f"local fallback allowed={local_ok}, remote refused={remote_refused}")


@check("JWT validation checks signature, issuer, audience and expiry")
def _():
    # `verify_aud: False` was the original setting, which accepts a token minted
    # for any other client in the same realm.
    src = read("api", "auth.py")
    required = {'"verify_aud": True': None, '"verify_exp": True': None,
                '"verify_iss": True': None, '"verify_signature": True': None,
                "audience=KEYCLOAK_AUDIENCE": None, "issuer=": None}
    missing = [k for k in required if k not in src]
    disabled = re.findall(r'"verify_\w+":\s*False', src)
    return (not missing and not disabled,
            f"missing={missing} disabled={disabled}" if (missing or disabled)
            else "signature, issuer, audience and expiry all verified")


@check("every dependency is pinned to an exact version")
def _():
    # A floor (`>=`) means the artefact built today and the one built next month
    # are different software, so a green pipeline stops being evidence.
    loose = []
    for line in read("requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        if "==" not in line:
            loose.append(line)
    pinned = [l for l in read("requirements.txt").splitlines()
              if "==" in l.split("#")[0]]
    return not loose, (f"unpinned: {loose}" if loose
                       else f"{len(pinned)} dependencies pinned exactly")


@check("the build context excludes environments, secrets and data")
def _():
    ignored = read(".dockerignore")
    need = [".venv", ".env", "*.duckdb", ".git", "__pycache__"]
    missing = [n for n in need if n not in ignored]
    return not missing, (f"missing from .dockerignore: {missing}" if missing
                         else "virtualenvs, .env, warehouses and .git all excluded")


@check("the NAT instance permits stateful private-subnet forwarding")
def _():
    # MASQUERADE is not sufficient on a Docker host: Docker sets the FORWARD
    # policy to DROP. Both directions must be explicitly allowed or VPC Lambda
    # calls to external AI providers stall until API Gateway times out.
    user_data = read("infrastructure", "aws", "keycloak-user-data.sh.tftpl")
    keycloak_tf = read("infrastructure", "aws", "keycloak.tf")
    required = [
        "net.ipv4.ip_forward = 1",
        "-t nat -C POSTROUTING",
        '-C FORWARD -s "$PRIVATE_CIDR"',
        "--ctstate ESTABLISHED,RELATED",
        "systemctl enable --now amazon-ssm-agent",
    ]
    missing = [item for item in required if item not in user_data]
    wired = 'private_cidrs  = join(" ", aws_subnet.private[*].cidr_block)' in keycloak_tf
    return (not missing and wired,
            f"missing={missing}, private CIDRs wired={wired}" if (missing or not wired)
            else "masquerade, bidirectional forwarding and SSM startup configured")


@check("no private key or credential file is committed")
def _():
    import subprocess
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True).stdout.split()
    patterns = (".pem", ".key", ".pfx", ".p12", "id_rsa", ".env")
    suspicious = [f for f in tracked
                  if f.endswith(patterns) or os.path.basename(f) == ".env"]
    # .env.example is documentation of shape, not a credential store.
    suspicious = [f for f in suspicious if not f.endswith(".example")]
    return not suspicious, (f"committed: {suspicious}" if suspicious
                            else f"{len(tracked)} tracked files, no key material")


def run():
    print("Security checks")
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
