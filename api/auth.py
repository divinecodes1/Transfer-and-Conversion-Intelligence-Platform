"""
Transfer & Conversion Intelligence Platform :: identity and entitlement resolution.

The separation that matters: **authentication** says who you are, **entitlement**
says which business data you may see, and neither is ever inferred from the
content of a request. A question that claims "I am a manager" carries exactly zero
authority, because the scope is resolved here, before any query runs, from tables
the caller cannot write.

Two identity sources, one resolution path:

  * Keycloak / OIDC -- `Authorization: Bearer <jwt>`, verified against the realm's
    published keys, with issuer, audience and expiry all checked. This is the
    production door and the only one open by default.
  * Demo header -- `X-Demo-User: manager.auto`, resolved against tr_gov.app_user.
    This is how the repository stays runnable and how the RBAC suite drives
    several identities without standing up an identity provider. It is an
    **unauthenticated assertion of identity**, so it is accepted only when demo
    mode has been switched on deliberately.

Both end at the same `Identity`, so the enforcement below them never learns which
door a caller came through.

Modes (TRANSFEROPS_AUTH), read per request so a deployment cannot be left in the
wrong mode by import order:

  enforce (default)  only a verified token is accepted. `X-Demo-User` is refused
                     and an unauthenticated caller gets 401. Fail-safe: you have
                     to opt *out* of security, never into it.
  demo               `X-Demo-User` is honoured and an unauthenticated caller gets
                     the admin identity, so the local quickstart just works. Every
                     process logs a warning on startup, because a demo-mode
                     service reachable by anyone else is an open door.
"""
import logging
import os
import threading
import time

from fastapi import HTTPException

from . import db

log = logging.getLogger("transferops.auth")

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "transferops")
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "transferops-api")

# Published keys are cached, but not forever: a realm rotates its signing keys,
# and a cache with no expiry turns that rotation into an outage.
JWKS_TTL_SECONDS = int(os.environ.get("TRANSFEROPS_JWKS_TTL", "300"))
_JWKS = {"keys": None, "fetched_at": 0.0}
_JWKS_LOCK = threading.Lock()


def auth_mode():
    """Read per request. Defaults to enforce -- security is not opt-in."""
    return os.environ.get("TRANSFEROPS_AUTH", "enforce").strip().lower()


def demo_mode_enabled():
    return auth_mode() == "demo"


def warn_if_demo_mode(service):
    """Called on startup so demo mode is never a silent condition."""
    if demo_mode_enabled():
        log.warning(
            "%s is running with TRANSFEROPS_AUTH=demo: the X-Demo-User header is "
            "accepted without authentication and unauthenticated callers resolve "
            "to the admin identity. Never expose this beyond localhost.", service)


class Identity:
    def __init__(self, username, roles, portfolios, sites, source):
        self.username = username
        self.roles = roles
        self.portfolios = portfolios      # ['*'] or explicit list
        self.sites = sites
        self.source = source

    @property
    def scope(self):
        """The value handed to PostgreSQL for the row-level security policy."""
        return "*" if "*" in self.portfolios else ",".join(sorted(self.portfolios))

    @property
    def unrestricted(self):
        return "*" in self.portfolios

    def as_dict(self):
        return {"username": self.username, "roles": self.roles,
                "portfolios": self.portfolios, "sites": self.sites,
                "source": self.source, "unrestricted": self.unrestricted}


ADMIN = Identity("admin.demo", ["PLATFORM_ADMIN"], ["*"], ["*"], "demo-default")


def entitlements_for(username):
    """Resolve roles and data scope from the governance tables."""
    # tr_gov is not behind RLS -- it is the authority that RLS is derived from --
    # but the scope must still be set for the session to reach the tables at all.
    rows = db.fetch(
        "SELECT role_code FROM tr_gov.user_role WHERE username = %s",
        [username], scope="*")
    if not rows:
        return None
    roles = [r["role_code"] for r in rows]

    ents = db.fetch(
        "SELECT dimension_type, dimension_value FROM tr_gov.data_entitlement "
        "WHERE username = %s "
        "  AND (valid_to IS NULL OR valid_to >= CURRENT_DATE) "
        "  AND (valid_from IS NULL OR valid_from <= CURRENT_DATE)",
        [username], scope="*")

    portfolios = [e["dimension_value"] for e in ents if e["dimension_type"] == "PORTFOLIO"]
    sites = [e["dimension_value"] for e in ents if e["dimension_type"] == "SITE"]
    # No entitlement row means no data. Fail closed, always.
    return Identity(username, roles, portfolios or [], sites or ["*"], "resolved")


def _jwks():
    """The realm's public keys, refreshed on a TTL so key rotation is survivable."""
    now = time.time()
    with _JWKS_LOCK:
        if _JWKS["keys"] is None or now - _JWKS["fetched_at"] > JWKS_TTL_SECONDS:
            import httpx
            url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
            _JWKS["keys"] = httpx.get(url, timeout=5.0).json()
            _JWKS["fetched_at"] = now
        return _JWKS["keys"]


def _verify_keycloak(token):
    """
    Verify an OIDC access token against the realm's published keys.

    Signature, issuer, audience and expiry are all checked. Audience
    verification in particular is not optional: without it a token minted for a
    *different* client in the same realm is accepted here, which is how one
    compromised low-privilege application becomes access to this one.
    """
    from jose import jwt  # imported lazily so SSO stays optional

    claims = jwt.decode(
        token, _jwks(),
        audience=KEYCLOAK_AUDIENCE,
        issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
        options={"verify_aud": True, "verify_exp": True,
                 "verify_iss": True, "verify_signature": True})
    username = claims.get("preferred_username")
    if not username:
        raise ValueError("token carries no preferred_username claim")
    return username


def resolve(request):
    """Identity for this request, or 401/403. Never returns an unscoped identity."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            username = _verify_keycloak(header.split(" ", 1)[1])
        except Exception as exc:
            # The reason is logged; the caller is told only that it failed, so a
            # probing client cannot use the error text to refine an attack.
            log.warning("token rejected: %s: %s", type(exc).__name__, exc)
            raise HTTPException(status_code=401, detail="invalid or expired token")
        identity = entitlements_for(username)
        if identity is None:
            raise HTTPException(
                status_code=403,
                detail=f"{username} authenticated but holds no entitlement")
        identity.source = "keycloak"
        return identity

    demo_user = request.headers.get("x-demo-user")
    if demo_user:
        # An unauthenticated claim of identity. Honoured only when this service
        # was deliberately started in demo mode; otherwise it is exactly the
        # header an attacker would try first.
        if not demo_mode_enabled():
            log.warning("X-Demo-User refused (%s): demo mode is off", demo_user)
            raise HTTPException(status_code=401, detail="authentication required")
        identity = entitlements_for(demo_user)
        if identity is None:
            raise HTTPException(status_code=403, detail=f"unknown user {demo_user}")
        identity.source = "demo-header"
        return identity

    if demo_mode_enabled():
        return ADMIN
    raise HTTPException(status_code=401, detail="authentication required")
