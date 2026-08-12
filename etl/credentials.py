"""
Transfer & Conversion Intelligence Platform :: role credentials, supplied rather than committed.

(Named `credentials`, not `secrets`: a module called `secrets` sitting on
sys.path shadows the standard library module of the same name.)

`sql/10_rls.sql` and `sql/11_observability.sql` create the two least-privilege
login roles the platform runs as. Those files used to carry the passwords inline,
which meant the repository's own security model was published alongside it. The
SQL now reads them from a session setting, and this module decides what that
setting contains.

The rule is scoped to the risk rather than applied uniformly, because a rule
everyone disables is worse than no rule:

  * Loading a **local** database (localhost / 127.0.0.1 / a container host alias)
    with no password set falls back to the documented development value and says
    so. That keeps `make pg-up && make pg-build` a two-command start.
  * Loading **anything else** with no password set is a hard failure. A remote
    warehouse is the case where a default credential is not a convenience but an
    open door, so the loader refuses rather than quietly installing one.

Set them per environment:

    TRANSFEROPS_READER_PASSWORD     the API's SELECT-only role
    TRANSFEROPS_AUDITOR_PASSWORD    the assistant's INSERT-on-one-table role
    TRANSFEROPS_AI_PASSWORD         the AI refresh job's write-only-to-tr_ai role
"""
import os
import re

# The documented development values, used only against a local database and only
# when nothing else is supplied. They are matched by .env.example and by CI.
DEV_READER = "reader"
DEV_AUDITOR = "auditor"
DEV_AI = "ai"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal",
               "postgres", ""}


def _host(dsn):
    """The host out of a libpq URI, without pulling in a URL parser."""
    m = re.search(r"@([^/:?]+)", dsn or "")
    return (m.group(1) if m else "").lower()


def is_local(dsn):
    return _host(dsn) in LOCAL_HOSTS


def role_password(var, dev_default, dsn, warn=print):
    """The password for one role, or a hard failure on a remote database."""
    supplied = os.environ.get(var, "").strip()
    if supplied:
        return supplied
    if is_local(dsn):
        warn(f"  [warn] {var} is not set; using the documented development "
             f"password for a local database. Set it for any real deployment.")
        return dev_default
    raise SystemExit(
        f"{var} must be set when loading a non-local database "
        f"({_host(dsn) or 'unknown host'}). Refusing to install a default "
        f"credential on a remote warehouse.")


def apply(execute, dsn, warn=print):
    """
    Publish both role passwords as session settings for the SQL to consume.

    `execute` takes (sql, params) -- the DB-API surface both loaders already have.
    Passed as parameters, never interpolated, so a password containing a quote is
    a non-event rather than a syntax error or an injection.
    """
    execute("SELECT set_config('transferops.reader_password', %s, false)",
            [role_password("TRANSFEROPS_READER_PASSWORD", DEV_READER, dsn, warn)])
    execute("SELECT set_config('transferops.auditor_password', %s, false)",
            [role_password("TRANSFEROPS_AUDITOR_PASSWORD", DEV_AUDITOR, dsn, warn)])
    execute("SELECT set_config('transferops.ai_password', %s, false)",
            [role_password("TRANSFEROPS_AI_PASSWORD", DEV_AI, dsn, warn)])
