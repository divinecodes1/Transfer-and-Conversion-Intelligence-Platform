"""
Transfer & Conversion Intelligence Platform :: AI failure modes, named.

The reason a failure needs a type at all is that the three cases below want three
different responses from the platform, and collapsing them into one "AI error"
string is how a rate limit ends up looking like an outage on a status page.

  * **AiUnavailable** -- no model is configured, or the provider refused the
    credential. Nothing is wrong with the request; this deployment simply does
    not have AI switched on. Screens hide their AI panels; the assistant falls
    back to the deterministic resolver. Never an alert.

  * **AiRateLimited** -- the provider is throttling or out of credit. The request
    was fine and will work later. Worth a retry, worth a metric, not worth waking
    anyone.

  * **AiError** -- everything else. The base class, so `except AiError` catches
    all three at a boundary that just wants to degrade gracefully.
"""


class AiError(Exception):
    """Base for anything the AI layer could not complete."""

    status_code = 502

    def __init__(self, message, *, provider=None):
        super().__init__(message)
        self.provider = provider


class AiUnavailable(AiError):
    """No model is configured, or the credential was rejected."""

    status_code = 503


class AiRateLimited(AiError):
    """The provider is throttling, or the account is out of credit."""

    status_code = 429


def classify(message, *, provider=None, status=None):
    """
    Turn a provider's HTTP failure into one of the three cases above.

    Providers disagree about almost everything in their error payloads, but they
    agree on status codes, so the code is what this reads first and the message
    text is only a fallback for transport-level failures that never got one.
    """
    text = str(message)
    if status in (401, 403) or _mentions(text, "unauthor", "invalid api key",
                                         "authentication"):
        return AiUnavailable(
            f"The AI provider rejected the credential ({provider}).",
            provider=provider)
    if status in (402, 429) or _mentions(text, "rate limit", "rate_limit",
                                         "quota", "insufficient_quota", "credit"):
        return AiRateLimited(
            "The AI provider is rate limited or out of credit. Try again shortly.",
            provider=provider)
    return AiError(f"The AI request failed: {text}", provider=provider)


def _mentions(text, *needles):
    low = text.lower()
    return any(n in low for n in needles)
