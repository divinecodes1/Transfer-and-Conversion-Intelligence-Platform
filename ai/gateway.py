"""
Transfer & Conversion Intelligence Platform :: the model gateway.

One interface, several providers. The platform above this module never learns
which model it is talking to -- it asks for a completion, optionally hands over a
JSON schema or a set of tools, and gets back a `Reply`. That indirection is not
architectural politeness: a metric platform that hard-codes one vendor's SDK into
its insight layer has to be rewritten to change models, and "which model wrote
this narrative?" stops being answerable the moment there is more than one.

Two adapters cover the field:

  * **anthropic** -- the official SDK, talking to the Messages API. This is the
    default and the one the prompts are tuned against.
  * **openai-compatible** -- raw HTTP against any `/chat/completions` endpoint.
    That shape is spoken by OpenAI, Gemini's compatibility endpoint, vLLM,
    Ollama, Together and most self-hosted servers, so "run this on our own GPU"
    is a change of two environment variables rather than a change of code.

Configuration is entirely environment-side:

    TRANSFEROPS_AI_PROVIDER    anthropic | openai        (default: anthropic)
    TRANSFEROPS_AI_MODEL       model id                  (default: per provider)
    TRANSFEROPS_AI_API_KEY     credential                (falls back to the
                               provider's own conventional variable)
    TRANSFEROPS_AI_BASE_URL    override the endpoint     (required for local models)
    TRANSFEROPS_AI_MAX_TOKENS  output ceiling            (default: 4000)
    TRANSFEROPS_AI_TIMEOUT     seconds                   (default: 120)

Nothing here reads the warehouse, and nothing here is imported at module scope by
the API. `configured()` is false on a deployment with no credential, and every
entry point raises `AiUnavailable` rather than failing at import -- so the
platform still serves dashboards and the deterministic assistant with no model
configured at all.
"""
import hashlib
import json
import os
import re
import threading

from .errors import AiError, AiUnavailable, classify

# Per-provider defaults. The Anthropic default is the current frontier model:
# these prompts do portfolio analysis over governed numbers, which is exactly the
# reasoning-shaped work the largest model is worth paying for, and the volume is
# a handful of calls a night rather than a per-request cost.
DEFAULTS = {
    "anthropic": {
        "model": "claude-opus-5",
        "key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
    "openai": {
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
    },
    # No key, no endpoint, no bill. See _Mock for why this is a first-class
    # provider rather than a test double.
    "mock": {
        "model": "mock-deterministic",
        "key_env": None,
        "base_url": None,
    },
}

# Providers that need no credential to be considered usable.
CREDENTIAL_FREE = {"mock"}

MAX_TOKENS = int(os.environ.get("TRANSFEROPS_AI_MAX_TOKENS", "4000"))
TIMEOUT = float(os.environ.get("TRANSFEROPS_AI_TIMEOUT", "120"))


def provider_name():
    return (os.environ.get("TRANSFEROPS_AI_PROVIDER") or "anthropic").strip().lower()


def model_name():
    explicit = os.environ.get("TRANSFEROPS_AI_MODEL", "").strip()
    if explicit:
        return explicit
    return DEFAULTS.get(provider_name(), {}).get("model", "")


def api_key():
    """The credential, from our own variable or the provider's conventional one."""
    explicit = os.environ.get("TRANSFEROPS_AI_API_KEY", "").strip()
    if explicit:
        return explicit
    env = DEFAULTS.get(provider_name(), {}).get("key_env")
    return os.environ.get(env, "").strip() if env else ""


def base_url():
    explicit = os.environ.get("TRANSFEROPS_AI_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return DEFAULTS.get(provider_name(), {}).get("base_url")


def configured():
    """
    Whether a model is reachable.

    A local server needs no credential, so a base URL on its own counts. This is
    what the API reports at /ai/status and what the frontend reads to decide
    whether to render an AI panel at all -- an empty card with a retry button is
    worse than no card.

    The mock provider is always configured: it is the deployment mode that
    exists precisely so the AI surfaces stay usable when no credential does.
    """
    if provider_name() in CREDENTIAL_FREE:
        return True
    return bool(api_key()) or bool(os.environ.get("TRANSFEROPS_AI_BASE_URL", "").strip())


def mocked():
    """Whether answers are deterministic placeholders rather than generated."""
    return provider_name() in CREDENTIAL_FREE


def describe():
    return {
        "configured": configured(),
        "provider": provider_name(),
        "model": model_name() if configured() else None,
        "base_url": base_url(),
        "max_tokens": MAX_TOKENS,
        # Surfaced so the console can label the panel rather than passing a
        # placeholder off as generated analysis. A demo that hides which mode it
        # is in is a demo that misrepresents itself.
        "mocked": mocked(),
    }


# ---------------------------------------------------------------------------
class ToolCall:
    """One tool the model asked for, in provider-neutral form."""

    __slots__ = ("id", "name", "arguments")

    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments if isinstance(arguments, dict) else {}

    def __repr__(self):
        return f"ToolCall({self.name!r}, {self.arguments!r})"


class Reply:
    """A completion, whatever produced it."""

    __slots__ = ("text", "tool_calls", "stop_reason", "model", "provider", "usage")

    def __init__(self, text="", tool_calls=None, stop_reason=None,
                 model=None, provider=None, usage=None):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.stop_reason = stop_reason
        self.model = model
        self.provider = provider
        self.usage = usage or {}

    def json(self):
        """
        The reply parsed as JSON.

        Both adapters can ask the provider to *guarantee* a schema, so this is
        normally a plain `json.loads`. The fence-stripping and object-scanning
        below are the fallback for a local model that does not implement
        structured output -- the one case where the guarantee is a request rather
        than a contract.
        """
        raw = self.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except ValueError:
            for opener, closer in (("[", "]"), ("{", "}")):
                start, end = raw.find(opener), raw.rfind(closer)
                if start != -1 and end > start:
                    try:
                        return json.loads(raw[start:end + 1])
                    except ValueError:
                        continue
            raise AiError("The model did not return usable JSON.")


# ---------------------------------------------------------------------------
class _Anthropic:
    """The Messages API, through the official SDK."""

    name = "anthropic"

    def __init__(self):
        try:
            import anthropic
        except ImportError:
            raise AiUnavailable(
                "The anthropic package is not installed; run "
                "`pip install -r requirements.txt` or set "
                "TRANSFEROPS_AI_PROVIDER=openai.", provider="anthropic")
        key = api_key()
        if not key:
            raise AiUnavailable(
                "No API key. Set TRANSFEROPS_AI_API_KEY or ANTHROPIC_API_KEY.",
                provider="anthropic")
        kwargs = {"api_key": key, "timeout": TIMEOUT}
        if base_url():
            kwargs["base_url"] = base_url()
        self._sdk = anthropic
        self._client = anthropic.Anthropic(**kwargs)

    def complete(self, *, system, messages, tools=None, json_schema=None,
                 max_tokens=None):
        payload = {
            "model": model_name(),
            "max_tokens": max_tokens or MAX_TOKENS,
            "system": system,
            "messages": [_to_anthropic(m) for m in messages],
        }
        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t["description"],
                 "input_schema": t["parameters"]}
                for t in tools
            ]
        if json_schema is not None:
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": json_schema}}

        try:
            response = self._client.messages.create(**payload)
        except Exception as exc:  # noqa: BLE001 -- re-raised as our own type
            raise self._translate(exc)

        # A safety decline is a successful HTTP response with an empty body, so
        # reading content[0] blind would be an IndexError on the one path that
        # most needs a readable message.
        if getattr(response, "stop_reason", None) == "refusal":
            raise AiError("The model declined to answer this request.",
                          provider=self.name)

        text, calls = [], []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, block.input))

        usage = getattr(response, "usage", None)
        return Reply(
            text="".join(text),
            tool_calls=calls,
            stop_reason=getattr(response, "stop_reason", None),
            model=getattr(response, "model", model_name()),
            provider=self.name,
            usage={"input_tokens": getattr(usage, "input_tokens", None),
                   "output_tokens": getattr(usage, "output_tokens", None)},
        )

    def _translate(self, exc):
        """Typed SDK exceptions carry the status code; use it, not the message."""
        sdk = self._sdk
        if isinstance(exc, sdk.APIStatusError):
            return classify(getattr(exc, "message", exc),
                            provider=self.name, status=exc.status_code)
        if isinstance(exc, sdk.APIConnectionError):
            return AiError(f"Could not reach the AI provider: {exc}",
                           provider=self.name)
        return classify(exc, provider=self.name)


def _to_anthropic(message):
    """Neutral message -> Messages API shape."""
    role = message["role"]
    if role == "tool":
        return {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": message["tool_call_id"],
            "content": message["content"],
        }]}
    if role == "assistant" and message.get("tool_calls"):
        blocks = []
        if message.get("text"):
            blocks.append({"type": "text", "text": message["text"]})
        for call in message["tool_calls"]:
            blocks.append({"type": "tool_use", "id": call.id,
                           "name": call.name, "input": call.arguments})
        return {"role": "assistant", "content": blocks}
    return {"role": role, "content": message.get("text", "")}


# ---------------------------------------------------------------------------
class _OpenAICompatible:
    """
    Any `/chat/completions` endpoint.

    Deliberately raw HTTP over httpx -- already a dependency -- rather than a
    vendor SDK. The whole value of this adapter is that it points at servers no
    SDK knows about.
    """

    name = "openai"

    def __init__(self):
        url = base_url()
        if not url:
            raise AiUnavailable(
                "No base URL. Set TRANSFEROPS_AI_BASE_URL for an "
                "OpenAI-compatible endpoint.", provider="openai")
        if not api_key() and "localhost" not in url and "127.0.0.1" not in url:
            raise AiUnavailable(
                "No API key. Set TRANSFEROPS_AI_API_KEY.", provider="openai")
        self._url = url

    def complete(self, *, system, messages, tools=None, json_schema=None,
                 max_tokens=None):
        import httpx

        payload = {
            "model": model_name(),
            "max_tokens": max_tokens or MAX_TOKENS,
            "messages": [{"role": "system", "content": system}]
                        + [_to_openai(m) for m in messages],
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True,
                                "schema": json_schema},
            }

        headers = {"Content-Type": "application/json"}
        if api_key():
            headers["Authorization"] = f"Bearer {api_key()}"

        try:
            response = httpx.post(f"{self._url}/chat/completions", json=payload,
                                  headers=headers, timeout=TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            raise AiError(f"Could not reach the AI provider: {exc}",
                          provider=self.name)
        if response.status_code >= 400:
            raise classify(response.text, provider=self.name,
                           status=response.status_code)

        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(ToolCall(call.get("id"), fn.get("name"), args))

        return Reply(
            text=message.get("content") or "",
            tool_calls=calls,
            stop_reason=choice.get("finish_reason"),
            model=body.get("model", model_name()),
            provider=self.name,
            usage=body.get("usage") or {},
        )


def _to_openai(message):
    role = message["role"]
    if role == "tool":
        return {"role": "tool", "tool_call_id": message["tool_call_id"],
                "content": message["content"]}
    if role == "assistant" and message.get("tool_calls"):
        return {
            "role": "assistant",
            "content": message.get("text") or None,
            "tool_calls": [{
                "id": c.id, "type": "function",
                "function": {"name": c.name,
                             "arguments": json.dumps(c.arguments)},
            } for c in message["tool_calls"]],
        }
    return {"role": role, "content": message.get("text", "")}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
class _Mock:
    """
    A provider that answers without a model.

    This exists because a demonstration must not depend on somebody's API
    credits. Model billing is separate from any chat subscription, promotional
    credits expire, and a key that worked in October is a 401 in November -- so
    "the AI features are unavailable today" would otherwise be the story a
    reviewer leaves with.

    The important design constraint is that this is NOT a stub returning lorem
    ipsum. It composes its answer *out of the governed payload it was handed*,
    which gives it the same property the real prompts are held to and which
    tests/ai_checks.py asserts: no figure appears in the output that did not
    arrive from the metric layer. A mock free to invent numbers would be worse
    than no mock, because a reviewer cannot tell an invented 78% from a governed
    one by looking.

    It is deterministic. The same warehouse vintage and the same question
    produce the same words, which makes the demo repeatable and makes the
    caching layer above behave exactly as it does against a real provider.
    """

    name = "mock"

    # A figure the prompt actually stated, e.g. `"on_time_rate": 41.5`.
    _NUMBER = re.compile(r'"([a-z_]+)"\s*:\s*(-?\d+(?:\.\d+)?)')
    _PROJECT = re.compile(r"\b(T-\d{3})\b")

    def complete(self, *, system, messages, tools=None, json_schema=None,
                 max_tokens=None):
        context = "\n".join(
            m.get("content", "") if isinstance(m.get("content"), str)
            else json.dumps(m.get("content"), default=str)
            for m in messages
        )
        facts = {k: float(v) for k, v in self._NUMBER.findall(context)}
        projects = sorted(set(self._PROJECT.findall(context)))

        if json_schema is not None:
            payload = _mock_from_schema(json_schema, facts, projects)
            text = json.dumps(payload)
        else:
            text = self._narrative(facts, projects)

        return Reply(
            text=text,
            tool_calls=[],          # the mock never asks for a tool: it has the data
            stop_reason="end_turn",
            model="mock-deterministic",
            provider=self.name,
            # Zero, honestly. The cost dashboard should show this as free rather
            # than estimating tokens nobody was billed for.
            usage={"input_tokens": 0, "output_tokens": 0, "mocked": True},
        )

    def _narrative(self, facts, projects):
        """A briefing assembled from the figures the prompt supplied."""
        lines = []

        def say(label, key, unit="", digits=1):
            if key in facts:
                value = facts[key]
                shown = f"{value:.{digits}f}".rstrip("0").rstrip(".")
                lines.append(f"{label} is {shown}{unit}.")

        say("On-time completion", "on_time_rate", "%")
        say("Median cycle time", "median_cycle_time", " days", 0)
        say("Replan rate", "replan_rate", "%")
        say("Average readiness", "avg_readiness_pct", "%")
        say("Work in progress", "wip", "", 0)

        if "delayed_count" in facts and facts["delayed_count"] > 0:
            lines.append(
                f"{int(facts['delayed_count'])} transfers are in the late band "
                f"and are where attention is worth spending.")

        if projects:
            named = ", ".join(projects[:5])
            lines.append(f"The transfers in scope include {named}.")

        if not lines:
            lines.append(
                "No governed figures were supplied with this question, so there "
                "is nothing to summarise.")

        lines.append(
            "Generated without a model (TRANSFEROPS_AI_PROVIDER=mock). Every "
            "number above was taken from the governed metric layer, not "
            "produced by generation.")
        return " ".join(lines)


def _mock_score(project_id):
    """
    A stable pseudo-score for one project, in 0..100.

    Deterministic from the id alone, so the same project scores the same on
    every run and across every replica -- a demo where the risk table reshuffles
    on refresh reads as broken, however plausible each individual number looks.

    This is a *placeholder ordering*, not a prediction, and the band names below
    are the platform's own. The real delay-risk model lives in ai/risk.py and is
    fenced out of the metric layer; nothing here is registered as a metric.
    """
    digest = hashlib.sha256(project_id.encode()).digest()
    return digest[0] * 100 // 255


def _mock_from_schema(schema, facts, projects, field=None):
    """
    Build a value satisfying `schema`, using the prompt's own figures.

    Walks the schema rather than hard-coding a response shape, so a new
    structured prompt does not need a matching branch here. Arrays of
    per-project objects expand to one entry per project the prompt named, which
    is what makes the structured output look like an answer rather than a stub.
    """
    kind = schema.get("type")

    if kind == "object":
        props = schema.get("properties", {})
        return {
            name: _mock_from_schema(sub, facts, projects, field=name)
            for name, sub in props.items()
        }

    if kind == "array":
        items = schema.get("items", {})
        per_project = (
            items.get("type") == "object"
            and "project_id" in items.get("properties", {})
        )
        if per_project:
            return [_mock_from_schema(items, facts, [pid]) for pid in projects]
        if items.get("type") == "string":
            return list(_MOCK_DRIVERS[:3])
        return []

    score = _mock_score(projects[0]) if projects else 0

    if kind in ("integer", "number"):
        if field == "risk_score":
            return score
        if field == "predicted_slip_days":
            # Scaled off the same digest so slip and score never disagree.
            return round(score / 5)
        # Any other number the prompt already stated, echoed rather than invented.
        return round(facts.get(field, 0)) if kind == "integer" else facts.get(field, 0)

    if kind == "string":
        if field == "project_id":
            return projects[0] if projects else ""
        if schema.get("enum"):
            options = schema["enum"]
            if field in ("risk_band", "band"):
                # Thirds of the score range, mapped onto whatever the schema
                # actually offers rather than assuming low/medium/high.
                index = min(len(options) - 1, score * len(options) // 100)
                return options[index]
            return options[0]
        if field in ("rationale", "summary", "explanation"):
            return (
                "Deterministic placeholder produced without a model "
                "(TRANSFEROPS_AI_PROVIDER=mock). Ordering is stable but is not a "
                "prediction; configure a provider for generated reasoning."
            )
        return ""

    if kind == "boolean":
        return False

    return None


_MOCK_DRIVERS = [
    "qualification readiness below the portfolio average",
    "equipment readiness below the portfolio average",
    "schedule already moved from the frozen baseline",
]


_ADAPTERS = {"anthropic": _Anthropic, "openai": _OpenAICompatible,
             "openai-compatible": _OpenAICompatible, "mock": _Mock}

_CLIENT = {"key": None, "value": None}
_LOCK = threading.Lock()


def client():
    """
    The configured provider, built once and reused.

    Keyed on the settings that shaped it, so a test that repoints the
    environment gets a new adapter instead of a stale one holding the previous
    endpoint -- the same reason the warehouse pool resets its scope per checkout.
    """
    key = (provider_name(), model_name(), base_url(), bool(api_key()))
    with _LOCK:
        if _CLIENT["key"] != key or _CLIENT["value"] is None:
            adapter = _ADAPTERS.get(provider_name())
            if adapter is None:
                raise AiUnavailable(
                    f"Unknown AI provider {provider_name()!r}; expected one of "
                    f"{sorted(set(_ADAPTERS))}.")
            _CLIENT["value"] = adapter()
            _CLIENT["key"] = key
        return _CLIENT["value"]


def reset():
    """Drop the cached adapter. Used by tests that change the environment."""
    with _LOCK:
        _CLIENT["key"] = None
        _CLIENT["value"] = None


def complete(system, messages, *, tools=None, json_schema=None, max_tokens=None):
    """One completion. The only function the rest of `ai/` calls."""
    return client().complete(system=system, messages=messages, tools=tools,
                             json_schema=json_schema, max_tokens=max_tokens)


def user(text):
    return {"role": "user", "text": text}


def assistant(reply):
    return {"role": "assistant", "text": reply.text,
            "tool_calls": reply.tool_calls}


def tool_result(call, content):
    return {"role": "tool", "tool_call_id": call.id, "name": call.name,
            "content": content if isinstance(content, str) else json.dumps(content)}
