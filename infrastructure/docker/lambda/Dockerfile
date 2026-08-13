# Transfer & Conversion Intelligence Platform :: the API, packaged for Lambda.
#
# Lambda is what makes this deployment nearly free: it scales to zero properly,
# and a million requests a month cost nothing. The usual price of that is
# rewriting the application around a handler signature -- Mangum, or an ASGI
# shim, or splitting routes into functions.
#
# None of that happens here. The AWS Lambda Web Adapter sits in front of an
# ordinary HTTP server: it accepts the Lambda invocation, replays it as a normal
# HTTP request against 127.0.0.1, and translates the response back. So the image
# below runs the SAME `uvicorn api.main:app` the container ran on Azure and runs
# locally, and api/main.py does not learn that Lambda exists.
#
# That matters beyond convenience. `tests/api_checks.py` drives the real ASGI
# app; if the deployment ran a different entry point, the contract those tests
# assert would no longer be the contract in production.

ARG BASE_IMAGE=transfer-intelligence:latest
FROM ${BASE_IMAGE}

# The adapter is an internal Lambda extension: a static binary dropped into
# /opt/extensions, discovered by the runtime, no code that imports it.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 \
     /lambda-adapter /opt/extensions/lambda-adapter

# Where the adapter forwards to. Must match the uvicorn port below.
ENV AWS_LWA_PORT=8000 \
    # Lambda freezes the execution environment between invocations, so the
    # adapter has to know the server is listening before the first request is
    # forwarded. /health does a real warehouse round-trip and would make cold
    # starts pay for a database call; /healthz is the liveness route that does
    # not, which is exactly what a readiness check should use.
    AWS_LWA_READINESS_CHECK_PATH=/healthz \
    # Function URLs stream the response; buffering the whole body first would
    # add latency for no benefit on JSON this size.
    AWS_LWA_INVOKE_MODE=buffered \
    # One worker. Lambda gives each execution environment a single request at a
    # time, so a second worker would double memory to serve nothing.
    PYTHONUNBUFFERED=1

# Root is required: Lambda's runtime writes into /tmp and manages the extension
# lifecycle, and the base image's unprivileged user cannot start the adapter.
# The database still enforces its own least privilege through the reader role,
# which is where the boundary that matters actually lives.
USER root

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
