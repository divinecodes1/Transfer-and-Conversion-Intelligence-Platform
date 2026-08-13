# AI Provider Configuration

**Do not assume model API access is free.** API billing is separate from any
chat subscription; new accounts generally prepay, and promotional credits — when
they exist at all — are consumed first and then expire.

The platform is built so that this never matters to whether the demo works.

---

## Three providers, one interface

```text
Console ──▶ FastAPI ──▶ ai/gateway.py ──▶ ┌── anthropic  (official SDK)
                                          ├── openai     (any /chat/completions)
                                          └── mock       (deterministic, free)
```

The frontend never calls a provider. `tests/web_checks.py` asserts the console
carries no credential, and `tests/ai_checks.py` asserts the whole AI layer stays
inside its fence — both run without a model.

| Provider | Key needed | Cost | What you get |
|---|---|---|---|
| `mock` | no | **zero** | deterministic narratives from governed data |
| `openai` | yes | pay-per-token | generated analysis |
| `anthropic` | yes | pay-per-token | generated analysis (repo default) |
| Azure OpenAI | yes | pay-per-token | via the `openai` adapter — no separate provider |

---

## Mock mode — the default for Azure

```bash
TRANSFEROPS_AI_PROVIDER=mock
```

No key, no account, no spend. **Every AI surface still works.**

This is not a stub returning placeholder prose. The mock composes its answer out
of the governed payload it was handed, which gives it the same property the real
prompts are held to: no figure appears in the output that did not come from the
metric layer.

```
On-time completion is 41.5%. Median cycle time is 253 days. Replan rate is
79.7%. Work in progress is 69. 50 transfers are in the late band and are where
attention is worth spending. Generated without a model
(TRANSFEROPS_AI_PROVIDER=mock). Every number above was taken from the governed
metric layer, not produced by generation.
```

For structured prompts it produces schema-valid output, expanded per project:

```json
{"scores": [{"project_id": "T-002", "risk_score": 63, "risk_band": "medium",
             "predicted_slip_days": 13, "drivers": [...], "rationale": "..."}]}
```

It is **deterministic** — same vintage, same question, same words — so demos are
repeatable and the caching layer behaves exactly as it does against a real
provider.

`/ai/status` reports `"mocked": true`, so the console labels the panel rather
than passing a placeholder off as generated analysis. A demo that hides which
mode it is in misrepresents itself.

### What mock is not

It does not reason. `rationale` says so in as many words. The ordering is stable
but is not a prediction.

**This costs the demo less than it sounds like.** Two of the three headline AI
features never used an LLM in the first place:

- **Historical similarity** — deterministic, four published weights, in SQL
  (`v_transfer_similarity`). Explainable, free, and it *should* be that way: "it
  is nearby in vector space" cannot defend a decision in a review.
- **Delay risk** — `ai/risk.py`, fenced into `tr_ai` so a model's opinion can
  never acquire a metric code.

Only the narrative surfaces — briefings, root-cause prose, report summaries —
degrade to placeholders.

---

## OpenAI

```bash
TRANSFEROPS_AI_PROVIDER=openai
TRANSFEROPS_AI_MODEL=gpt-4o-mini
TRANSFEROPS_AI_API_KEY=sk-...
```

In Azure:

```bash
export TF_VAR_ai_provider=openai
export TF_VAR_ai_model=gpt-4o-mini
export TF_VAR_ai_api_key="sk-..."
terraform apply
```

The key becomes a Container Apps secret and a Key Vault secret. It never appears
in state output, in the image, or in the browser.

`gpt-4o-mini` is the default deliberately: these prompts summarise governed
numbers that are already computed. The model writes sentences, not analysis, and
a frontier model is not worth its price for that.

---

## Azure OpenAI

No separate adapter — the `openai` adapter is raw HTTP against any
`/chat/completions` endpoint:

```bash
TRANSFEROPS_AI_PROVIDER=openai
TRANSFEROPS_AI_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment>
TRANSFEROPS_AI_MODEL=<deployment-name>
TRANSFEROPS_AI_API_KEY=<azure-openai-key>
```

Availability and quota approval vary by subscription and region, and a student
subscription frequently does not have access. Treat it as optional — the deploy
scripts never assume it exists.

---

## Anthropic

```bash
TRANSFEROPS_AI_PROVIDER=anthropic
TRANSFEROPS_AI_MODEL=claude-opus-5
TRANSFEROPS_AI_API_KEY=sk-ant-...
```

The repository default outside Azure. Requires `pip install anthropic`, which
`requirements.txt` already pins.

---

## Cost controls

All enforced in the application, not by the provider:

| Control | Variable | Default |
|---|---|---|
| Daily requests per user | `TRANSFEROPS_AI_DAILY_CAP` | 50 |
| Max output tokens | `TRANSFEROPS_AI_MAX_TOKENS` | 4000 |
| Request timeout | `TRANSFEROPS_AI_TIMEOUT` | 120s |
| Cache TTL | `TRANSFEROPS_AI_TTL_HOURS` | 24 |

Plus the structural ones:

- **Responses are cached in `tr_ai`**, keyed on the filter scope *and* the
  warehouse vintage. A repeated question against unchanged data never reaches
  the provider. Scope keys are order-independent and null-normalised, and
  `tests/ai_checks.py` asserts a cached narrative cannot be served for a
  different scope.
- **The model never sees the warehouse.** It receives a governed snapshot from a
  closed list of six mart endpoints — never a table, never a row dump.
- **Similarity and risk never call a model at all.**

---

## When the provider fails

The platform degrades; it does not break.

```
AI service temporarily unavailable.
Core Transfer Intelligence functions remain available.
```

`ai/errors.py` classifies the failure and `AiUnavailable` carries a readable
reason. With no key configured:

```
AiUnavailable: No API key. Set TRANSFEROPS_AI_API_KEY or ANTHROPIC_API_KEY.
```

`/ai/status` reports it plainly, the console hides its AI panels rather than
showing empty cards with retry buttons, and **every other screen works
unchanged** — dashboards, the project register, readiness, network, similarity,
the deterministic assistant. That property is asserted by `tests/ai_checks.py`
running with no model at all.

---

## Choosing

| Situation | Use |
|---|---|
| Azure student demo | `mock` |
| Showing generated narrative quality | `openai` + `gpt-4o-mini` |
| Enterprise Azure | Azure OpenAI via the `openai` adapter |
| Local development | `mock` |
| CI | none — every AI gate runs without a model |
