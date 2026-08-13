# Security Posture — AWS Student Tier

What is enforced, and — more importantly — **what is not**. A demo that implies
production networking misrepresents itself.

---

## What holds

### Authentication

Keycloak, OIDC Authorization Code flow with PKCE. The console is a public client
and holds no secret, because a secret compiled into a browser bundle is not a
secret.

`api/auth.py` verifies **signature, issuer, audience and expiry** on every
request. Audience verification is not optional: without it, a token minted for a
different client in the same realm is accepted.

Default posture is `TRANSFEROPS_AUTH=enforce` — you opt *out* of security, never
into it. `tests/security_checks.py` asserts that default.

### Authorisation, enforced at the database

**Authentication** says who you are; **entitlement** says which data you may
see. Roles live in `tr_gov.user_role`, scope in `tr_gov.data_entitlement`, and
enforcement is a **forced row-level security policy** on `tr_core.dim_project`.

Three things must be true together and `sql/10_rls.sql` does all three: `FORCE
ROW LEVEL SECURITY`, a **non-superuser** connection (`transferops_reader`), and
`security_invoker` on every view. The scope is **fail-closed** — unset selects
no rows.

### Credentials and IAM

| Secret | Where | How reached |
|---|---|---|
| DB passwords | generated → SSM SecureString | Lambda gets a DSN as an env var set at deploy time |
| Keycloak admin | generated → SSM SecureString | read at boot by the instance role |
| Model API key | SSM SecureString | backend only, never the browser |
| **CI credentials** | **none exist** | GitHub OIDC → IAM role, short-lived token |

IAM is scoped tightly:
- the API's Lambda role has **logs + one S3 bucket**, nothing else — no VPC
  access, no `ec2:*`, no broad S3
- the Keycloak instance role can read **only** `/{prefix}-{env}/*` in SSM
- the CI role can push to two ECR repos, update two named functions, write one
  bucket, and invalidate one distribution

**Instance metadata is IMDSv2-only** (`http_tokens = "required"`). IMDSv1 is how
instance credentials get stolen through SSRF.

**No SSH.** There is no port 22 rule and no key pair by default. Administration
is SSM Session Manager, which needs no open port and records who connected.

### Transport

HTTPS everywhere the browser goes. CloudFront redirects HTTP; the Lambda
Function URL is HTTPS-only; RDS sets `rds.force_ssl = 1` and every DSN carries
`sslmode=require`. Without that flag libpq will negotiate plaintext — and this
database is on public networking.

### Storage

Both S3 buckets are private with all four public-access blocks on, encrypted at
rest. The console bucket is readable **only** by its CloudFront distribution via
Origin Access Control.

### The AI fence

Asserted by `tests/ai_checks.py` (13 assertions, all running **without a
model**): closed tool list, caller scope overrides model arguments, hallucinated
project ids dropped, no model output registered as a governed metric, injected
text treated as data.

---

## What does **not** hold

### The database is on public networking

`publicly_accessible = true`, and the security group admits `0.0.0.0/0` on 5432.

This is deliberate and it is the weakest point in the design. The API runs on
Lambda **outside** the VPC so it can reach RDS, Keycloak's public issuer URL and
a model provider without a NAT gateway. Lambda's source addresses are AWS-owned
and dynamic, so they cannot be allow-listed — which leaves the rule open.

What actually protects it: a 32-character generated master password never
written to a file, forced TLS, and an application that connects as a
least-privilege reader role still subject to row-level security.

**The production fix costs ~$32/month** (private subnets + NAT + VPC-attached
Lambda) and is the first item in
[migration-to-enterprise.md](migration-to-enterprise.md).

### Keycloak is served over HTTP

The EC2 host serves port 8080 directly with no TLS. Tokens and the sign-in POST
cross the internet in plaintext.

Fixing it needs either an ALB with an ACM certificate (~$16/month) or a
certificate on the instance with a domain name. **Do not put real credentials
into this deployment.**

### No WAF, no edge rate limiting, no DDoS protection beyond CloudFront's default

The Function URL is directly internet-facing. Rate limiting exists for the AI
endpoints only, in the application.

### Single instance, no HA

One EC2 instance, one RDS instance, no Multi-AZ. An AZ failure takes the demo
down. Keycloak sessions are in memory and do not survive a restart.

### Terraform state holds every generated secret in plaintext

State is local and gitignored. Anyone with the file has the database.

### Secrets are not rotated

Generated once at apply time. No schedule, no expiry. Secrets Manager would
provide rotation; it was rejected on cost — that is the trade.

### Self-registration cannot complete

No SMTP relay, so Keycloak cannot send verification mail. The operator is
granted directly in `tr_gov` instead. `verifyEmail` was deliberately **not**
disabled to paper over this — that would weaken the posture the realm
demonstrates.

### The demo data is synthetic

260 fictional transfer projects. Never present it as real Infineon data.

---

## Non-negotiables, even here

- **No secret in the browser.** No model key, no DSN. `VITE_*` values compile
  into the bundle and are public.
- **No secret in git.** `.env`, `*.tfvars`, `*.tfstate`, `*.pem` are gitignored
  and `tests/security_checks.py` enforces it.
- **No access key for CI.** OIDC only.
- **`TRANSFEROPS_AUTH=demo` never on a public URL.**
- **Container runs as non-root** in every image except the Lambda one, where the
  runtime requires root to manage the extension — the database boundary is
  unaffected.
- **Dependencies pinned exactly**, asserted by a test.

---

## Closing the gap

In order of value per dollar:

1. Private subnets + NAT + VPC-attached Lambda (~$32/mo) — closes the biggest hole
2. ALB + ACM in front of Keycloak (~$16/mo) — HTTPS for sign-in
3. Remote Terraform state in S3 with restricted access and a lock file
4. Secrets Manager with rotation for the database credentials
5. WAF on CloudFront and the API
6. GuardDuty + Security Hub
7. Multi-AZ RDS and a second Keycloak instance behind the ALB
