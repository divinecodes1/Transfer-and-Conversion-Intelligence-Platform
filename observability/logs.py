"""
Transfer & Conversion Intelligence Platform :: structured logging.

Human-readable log lines are for a developer watching one terminal. Everything
past that -- searching an incident across three services, correlating a slow
dashboard panel with the API call underneath it, counting 401s by identity --
needs fields, not prose. So every record is emitted as one JSON object per line,
which every log platform ingests without a custom parser.

Two decisions worth stating:

  * **A request id is generated at the edge and reused, not invented per hop.**
    An inbound `X-Request-ID` is honoured, so a trace started by a load balancer
    or by the dashboard continues through the API and the assistant instead of
    restarting. It is echoed back on the response, which is what lets a user
    paste an id from an error into a support conversation.

  * **Nothing that identifies data is logged.** Identity (who asked) and route
    (what shape of question) are recorded; query results, project rows and the
    portfolio scope's contents are not. The audit trail in `tr_gov.agent_audit`
    is the place where "who asked what" is deliberately kept, under a role that
    can write nothing else. A log that quietly becomes a second copy of the data
    it was meant to govern access to is a liability, not observability.

Set TRANSFEROPS_LOG_FORMAT=text for line-oriented output while developing.
"""
import contextvars
import json
import logging
import os
import sys
import time
import uuid

REQUEST_ID = contextvars.ContextVar("transferops_request_id", default="-")

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": REQUEST_ID.get(),
        }
        # Anything passed via `extra=` rides along as a field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(service, level=None):
    """Install the formatter once, for this process and for uvicorn's loggers."""
    level = (level or os.environ.get("TRANSFEROPS_LOG_LEVEL", "INFO")).upper()
    text = os.environ.get("TRANSFEROPS_LOG_FORMAT", "json").lower() == "text"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        if text else JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers; drop them so one process emits one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # The access log is replaced by the request middleware, which knows the route
    # template and the resolved identity -- neither of which uvicorn can see.
    logging.getLogger("uvicorn.access").disabled = True

    logging.getLogger(service).info("logging configured",
                                    extra={"service": service, "format":
                                           "text" if text else "json"})
    return logging.getLogger(service)


def new_request_id(inbound=None):
    """Honour an upstream id when present; otherwise mint one."""
    rid = (inbound or "").strip()
    if not rid or len(rid) > 128:
        rid = uuid.uuid4().hex[:16]
    REQUEST_ID.set(rid)
    return rid
