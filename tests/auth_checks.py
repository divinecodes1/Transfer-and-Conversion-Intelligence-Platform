"""Transfer & Conversion Intelligence Platform :: self-service identity flow configuration checks.

These checks are static on purpose. They prove that registration, recovery,
verification, PKCE and local email delivery stay configured even on a machine
without a running identity server.
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


REALM = json.loads(read("keycloak", "realm-export.json"))
CLIENT = next(c for c in REALM["clients"] if c["clientId"] == "transferops-api")


@check("self-registration is enabled and email is the account identifier")
def _():
    ok = (REALM.get("registrationAllowed") is True
          and REALM.get("registrationEmailAsUsername") is True
          and REALM.get("duplicateEmailsAllowed") is False)
    return ok, "registration on; unique work email is the username"


@check("new accounts must verify email before access")
def _():
    ok = REALM.get("verifyEmail") is True
    return ok, f"verifyEmail={REALM.get('verifyEmail')}"


@check("forgot-password recovery is enabled")
def _():
    ok = REALM.get("resetPasswordAllowed") is True
    return ok, f"resetPasswordAllowed={REALM.get('resetPasswordAllowed')}"


@check("SMTP is environment-backed and no mail credential is committed")
def _():
    smtp = REALM.get("smtpServer", {})
    required = ("host", "port", "from", "auth", "password", "ssl", "starttls")
    missing = [key for key in required if key not in smtp]
    literal_secret = smtp.get("password", "") not in ("", "${KEYCLOAK_SMTP_PASSWORD}")
    return (not missing and not literal_secret,
            f"missing={missing}, password is an environment reference={not literal_secret}")


@check("one branded theme covers login and email workflows")
def _():
    files = [
        ("keycloak", "themes", "transferops", "login", "theme.properties"),
        ("keycloak", "themes", "transferops", "login", "resources", "css", "transferops.css"),
        ("keycloak", "themes", "transferops", "login", "resources", "js", "transferops.js"),
        ("keycloak", "themes", "transferops", "email", "theme.properties"),
    ]
    missing = ["/".join(parts) for parts in files
               if not os.path.isfile(os.path.join(ROOT, *parts))]
    css = read("keycloak", "themes", "transferops", "login", "resources",
               "css", "transferops.css")
    email_messages = read("keycloak", "themes", "transferops", "email",
                          "messages", "messages_en.properties")
    product_name = "Transfer & Conversion Intelligence Platform"
    selected = (REALM.get("loginTheme") == "transferops"
                and REALM.get("emailTheme") == "transferops")
    branded = (REALM.get("displayName") == product_name
               and REALM.get("smtpServer", {}).get("fromDisplayName") == product_name
               and email_messages.count(product_name) == 3)
    layout_reset = ('grid-template-areas:' in css
                    and 'grid-area: header !important' in css
                    and 'grid-area: main !important' in css
                    and '.pf-v5-c-login {\n  display: block !important' in css
                    and '#kc-header.pf-v5-c-login__header' in css
                    and 'height: 54px !important' in css
                    and 'padding-block: 0 !important' in css
                    and 'word-break: normal' in css)
    return (selected and branded and not missing and layout_reset,
            f"selected={selected}, branded={branded}, missing={missing}, "
            f"layout_reset={layout_reset}")


@check("the browser client uses public Authorization Code flow with PKCE")
def _():
    attrs = CLIENT.get("attributes", {})
    ok = (REALM.get("sslRequired") == "external"
          and CLIENT.get("publicClient") is True
          and CLIENT.get("standardFlowEnabled") is True
          and CLIENT.get("directAccessGrantsEnabled") is False
          and attrs.get("pkce.code.challenge.method") == "S256")
    return ok, "external HTTPS required; public client; standard flow; direct grant off; PKCE S256"


@check("browser redirects are explicit and never wildcard-origin")
def _():
    origins = CLIENT.get("webOrigins", [])
    redirects = CLIENT.get("redirectUris", [])
    ok = ("*" not in origins and any(":5173" in item for item in origins)
          and any(":5173/" in item for item in redirects))
    return ok, f"origins={origins}"


@check("access tokens carry the analytics API audience")
def _():
    mappers = CLIENT.get("protocolMappers", [])
    audience = [m for m in mappers
                if m.get("protocolMapper") == "oidc-audience-mapper"
                and m.get("config", {}).get("included.client.audience")
                == "transferops-api"
                and m.get("config", {}).get("access.token.claim") == "true"]
    return bool(audience), f"audience mapper count={len(audience)}"


@check("the console initialises Keycloak before routing and forwards bearer tokens")
def _():
    auth = read("web", "src", "lib", "auth.ts")
    main = read("web", "src", "main.tsx")
    api = read("web", "src", "lib", "api.ts")
    ok = ("onLoad: \"login-required\"" in auth and "pkceMethod: \"S256\"" in auth
          and main.index("await initialiseAuthentication()") < main.index("<RouterProvider")
          and 'out["Authorization"] = `Bearer ${token}`' in api)
    return ok, "login-required + PKCE, initialised before router, bearer forwarded"


@check("tokens remain in memory and local email is captured by a pinned Mailpit")
def _():
    auth = read("web", "src", "lib", "auth.ts")
    compose = read("docker-compose.yml")
    persisted_token = ("localStorage.setItem" in auth or "sessionStorage.setItem" in auth)
    ok = (not persisted_token and "axllent/mailpit:v1.30.0" in compose
          and "./keycloak/themes:/opt/keycloak/themes:ro" in compose)
    return ok, f"persisted_token={persisted_token}, pinned local SMTP + theme mount"


def run():
    print("Authentication checks")
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
