# syntax=docker/dockerfile:1
# ============================================================================
# JIRA MCP server — standalone read-only MCP over Streamable HTTP (:8002).
# Stateless: connects OUT to a JIRA Data Center / Server instance; no DB,
# no volumes, GPU-free.
#
#   build:  docker compose build       # or: docker build -t jira-mcp:latest .
#   run:    docker compose up -d
#
# For an air-gapped target with no registry access, save and relay the image:
#   docker save jira-mcp:latest | gzip > jira-mcp.tar.gz
#   # copy to the target host, then:  docker load < jira-mcp.tar.gz
# ============================================================================

ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

# Default index = public PyPI. Behind a corporate firewall, point pip at your
# internal mirror instead:
#   --build-arg PIP_INDEX_URL=https://pypi.example.com/simple \
#   --build-arg PIP_TRUSTED_HOST=pypi.example.com
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=pypi.org

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code changes don't bust the (slow) install layer.
COPY requirements.txt ./
RUN pip install --index-url "${PIP_INDEX_URL}" --trusted-host "${PIP_TRUSTED_HOST}" -r requirements.txt

# Server code (server.py, tools.py, models.py, main.py). .dockerignore keeps
# .env, .venv, tests/, __pycache__ and .git OUT — secrets stay in the runtime
# env_file; the image stays lean and stateless.
COPY . .

# Non-root runtime user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8002

# No HTTP /health endpoint on the MCP server — probe that uvicorn is accepting
# TCP on :8002 (the slim base has no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8002), 3).close()" || exit 1

# server.py -> uvicorn.run(app, host=0.0.0.0, port=8002); MCP at /mcp
CMD ["python", "server.py"]
