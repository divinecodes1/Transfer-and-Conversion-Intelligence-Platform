"""
Transfer & Conversion Intelligence Platform :: report email drafting.

The same governed snapshot as every other surface, written for a named audience.
Audience is a real variable rather than decoration: a steering committee wants
exceptions and money-relevant risk, a site lead wants WIP age and local
bottlenecks, and a project manager wants dates. One generic "portfolio update"
serves none of them, which is how a weekly report becomes something everyone
filters into a folder.

A draft, deliberately. Nothing here sends anything, and there is no mail
transport in the dependency list -- the reply is text the user copies. An
assistant that can silently mail a portfolio summary to a distribution list is a
much larger blast radius than one that writes a good draft.
"""
from . import gateway, prompts, snapshot as snap
from .errors import AiError

DEFAULT_SUBJECT = "Transfer & Conversion Intelligence Platform portfolio report"


def draft(api, filters=None, audience="steering_committee", cadence="weekly"):
    """Draft the subject line and body of one report email."""
    if audience not in prompts.AUDIENCES:
        raise AiError(f"Unknown audience {audience!r}; expected one of "
                      f"{sorted(prompts.AUDIENCES)}.")

    snapshot = snap.build(api, filters)
    system = prompts.email(audience, cadence, snapshot.get("definitions"))
    reply = gateway.complete(system, [gateway.user(
        f"Scope: {snap.describe_scope(filters)}\n\n"
        f"Governed metric snapshot (JSON):\n{snap.serialise(snapshot)}")])

    text = (reply.text or "").strip()
    if not text:
        raise AiError("The model returned an empty draft.")

    subject, body = _split(text)
    return {
        "subject": subject,
        "body": body,
        "audience": audience,
        "cadence": cadence,
        "filters": snapshot["filters"],
        "model": reply.model,
        "provider": reply.provider,
        "data_as_of": snapshot.get("data_as_of") or None,
    }


def _split(text):
    """
    Separate the subject line from the body.

    The prompt asks for `Subject: …` on the first line. Falling back to a fixed
    subject rather than raising is the right trade here: a draft with a generic
    subject and a good body is still useful, and the user is about to edit both.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped.split(":", 1)[1].strip() or DEFAULT_SUBJECT
            body = "\n".join(lines[index + 1:]).strip()
            return subject[:200], body or text
    return DEFAULT_SUBJECT, text
