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
import json
import os
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
}

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
    """
    return bool(api_key()) or bool(os.environ.get("TRANSFEROPS_AI_BASE_URL", "").strip())


def describe():
    return {
        "configured": configured(),
        "provider": provider_name(),
        "model": model_name() if configured() else None,
        "base_url": base_url(),
        "max_tokens": MAX_TOKENS,
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
_ADAPTERS = {"anthropic": _Anthropic, "openai": _OpenAICompatible,
             "openai-compatible": _OpenAICompatible}

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
