# Transfer & Conversion Intelligence Platform :: one image, three entrypoints.
#
# The API, the assistant and the dashboard share a codebase and a dependency set,
# so they share an image and differ only by command. Three near-identical
# Dockerfiles would be three places to forget a dependency.
#
# Two stages: the build stage owns the compiler toolchain that some wheels need,
# and the runtime stage keeps none of it. What ships is the interpreter, the
# installed packages and the application -- nothing that could be used to build
# something else inside a running container.
FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not invalidate the install layer.
# Installed into a virtualenv so the runtime stage can take the whole tree in one
# COPY without dragging in pip's own build machinery.
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Fail-safe: the image defaults to enforcing authentication. A deployment
    # that wants the demo header has to set TRANSFEROPS_AUTH=demo deliberately.
    TRANSFEROPS_AUTH=enforce

WORKDIR /app

COPY --from=build /opt/venv /opt/venv

COPY sql/ ./sql/
COPY etl/ ./etl/
COPY api/ ./api/
COPY agent/ ./agent/
COPY ai/ ./ai/
COPY bi/ ./bi/
COPY rag/ ./rag/
COPY observability/ ./observability/
COPY legacy/ ./legacy/

# The React console is deliberately NOT in this image. It is static assets with
# no runtime of their own, so it belongs behind the same web server or CDN that
# terminates TLS -- not bundled into a Python service that would then have to
# grow a static-file route and a Node build stage. `make web-build` produces
# web/dist; ship that where the ingress can serve it.

# Runs as a non-root user with no login shell and no home to write into. The
# database enforces its own least privilege via the reader and auditor roles; the
# container should not undercut that by running as root inside the cluster.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin transferops \
 && chown -R transferops:transferops /app
USER transferops

EXPOSE 8000 8100 8501

# The probe belongs to the image, so `docker run` gets the same liveness signal
# the Kubernetes manifest configures. /health does a real warehouse round-trip:
# a process that is up but cannot reach the metric layer is not healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# Overridden per deployment; the API is the sensible default.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
