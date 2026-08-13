# Security Posture — Student Tier

This document states what is enforced, and — more importantly — **what is not**.
A demo that implies production networking is a demo that misrepresents itself.

---

## What holds

### Authentication

Keycloak, OIDC Authorization Code flow with PKCE. The console is a public client:
it holds no secret, because a secret compiled into a browser bundle is not a
secret.

`api/auth.py` verifies **signature, issuer, audience and expiry** on every
request. Audience verification is not optional — without it, a token minted for
a different client in the same realm is accepted, which is how one compromised
low-privilege application becomes access to this one.

The default posture is `TRANSFEROPS_AUTH=enforce`. You have to opt *out* of
security, never into it. `tests/security_checks.py` asserts that default.

### Authorisation, enforced at the database

The distinction the platform rests on: **authentication** says who you are,
**entitlement** says which business data you may see.

- Roles: `tr_gov.user_role`
- Data scope: `tr_gov.data_entitlement`
- Enforcement: a **forced row-level security policy** on `tr_core.dim_project`

A workbook filter is not a security boundary and neither is an application
`WHERE` clause on its own. The policy holds for the API, the assistant, the
dashboards and anyone with a `psql` prompt.

Three things must be true together, and `sql/10_rls.sql` does all three: `FORCE
ROW LEVEL SECURITY` so the owner does not bypass it, a **non-superuser**
connection (`transferops_reader`, `NOBYPASSRLS`), and `security_invoker` on every
view — applied dynamically so a view added later cannot silently miss it.

The scope is **fail-closed**: an unset scope selects no rows.

### Secrets

| Secret | Where it lives | How it is reached |
|---|---|---|
| DB role passwords | Terraform-generated → Key Vault + Container Apps secrets | never in a file, never in an image |
| Keycloak admin password | Terraform-generated → Key Vault | `terraform output -raw keycloak_admin_password` |
| Model API key | Container Apps secret, from `TF_VAR_ai_api_key` | backend only |
| Blob access | **no key exists** | shared key access disabled; managed identity only |

Connection strings are assembled inside the Terraform module and stored **whole**
as secrets. The alternative — password in a separate secret, DSN composed at
runtime — is not possible, and the fallback of putting the password in a plain
environment variable would expose it in the portal, in `az containerapp show`,
and in any log that dumps the environment.

`tests/security_checks.py` asserts no key material is committed. It is the gate
that caught a tracked `.env` in this repository.

### Transport

HTTPS only, everywhere. Container Apps ingress sets
`allow_insecure_connections = false`; PostgreSQL sets
`require_secure_transport = ON` and every DSN carries `sslmode=require`. Without
that flag libpq will happily fall back to plaintext, and the traffic crosses
shared Azure networking.

### The AI fence

Enforced in code and asserted by `tests/ai_checks.py` (13 assertions, all of
which run **without a model**):

- the tool list is closed — six governed mart endpoints, nothing else
- the caller's entitlement scope **overrides** the model's arguments
- a hallucinated project id is dropped rather than stored
- no model output is ever registered as a governed metric
- injected text in retrieved content is data, not instruction
- prompts quote the catalogue rather than restating it

The frontend never calls a model provider. `tests/web_checks.py` asserts the
console holds no SQL, no credential, no metric definition and no banding
threshold.

---

## What does **not** hold

Stated plainly, because the gap between this and production is the honest part
of the exercise.

### The database is on public networking

Firewall rules, not a private endpoint. `allow-azure-services` (0.0.0.0) admits
**any** Azure service to attempt a connection — it is not a boundary, it is a
filter, and it is paired with strong generated credentials and least-privilege
roles rather than trusted on its own.

This is deliberate. A private endpoint costs roughly the database again, plus a
VNet, plus the Container Apps environment would have to be VNet-injected — which
forfeits the Consumption profile and therefore scale-to-zero, which is the entire
cost model.

### No WAF, no DDoS protection, no rate limiting at the edge

There is no Front Door and no Application Gateway. The API is directly
internet-facing. Application-level rate limiting exists for the AI endpoints
only.

### Keycloak runs a single replica with no session replication

`max_replicas = 1` on purpose: Keycloak clusters via Infinispan, and a second
replica without a configured cache stack serves inconsistent sessions. Scaling to
zero also drops in-memory sessions — a user signs in again. Acceptable for a
demo, not for production.

### Terraform state holds every generated secret in plaintext

State is local and gitignored. Anyone with the file has the database. The
enterprise path moves it to a storage account with restricted access and
customer-managed keys.

### Secrets are not rotated

Generated once at apply time and stable until the next `terraform apply` that
changes them. There is no rotation schedule and no expiry.

### Purge protection is disabled on Key Vault

`purge_protection_enabled = true` would block `terraform destroy` outright, which
conflicts directly with the ability to tear the stack down — the most important
cost control here. Production reverses this trade.

### The demo data is synthetic

260 fictional transfer projects. Nothing here is Infineon's data, and it must
never be presented as such.

---

## The rules that are non-negotiable

Even at student tier:

- **No secret in the browser.** No model key, no DSN, no `VITE_*OPENAI*`
  anything. `VITE_` values compile into the bundle and are public.
- **No secret in git.** `.env`, `*.tfvars`, `*.pem`, `*.key` are gitignored, and
  a test enforces it.
- **No secret in the image.** The Dockerfile copies source, never configuration.
- **`TRANSFEROPS_AUTH=demo` never on a public URL.** It accepts an
  unauthenticated `X-Demo-User` header. Every process logs a warning on startup
  in that mode, because demo mode must never be a silent condition.
- **The container runs as non-root** (uid 10001, no login shell, no home).
- **Dependencies are pinned exactly**, and a test asserts it — a `>=` range means
  the image built today and the image built next month are different software.

---

## Closing the gap

In rough order of value per unit of cost and effort — see
[migration-to-enterprise.md](migration-to-enterprise.md):

1. Private endpoint for PostgreSQL + VNet-integrated Container Apps environment
2. Front Door with WAF in front of both the console and the API
3. Remote Terraform state with restricted access
4. Secret rotation via Key Vault, with the application reading at runtime
5. Key Vault purge protection and soft-delete retention at 90 days
6. Defender for Cloud on the subscription
7. Private container registry with image scanning and signed images
