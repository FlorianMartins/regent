# =============================================================================
# Regent — container image of the control plane (API + CLI).
#
# Two stages, so the runtime image ships the installed package and nothing
# else: no compiler, no build metadata, no shell tricks. It runs as an
# unprivileged user and is scanned by CloudGuard-IaC and Trivy on every commit.
#
#   docker build -t regent .
#   docker run --rm regent --version
#   docker run --rm -p 8080:8080 --env-file .env regent            # serve the API
#   docker run --rm -e REGENT_PROVIDER=replay regent agents        # use the CLI
# =============================================================================

# Base images are pinned by digest (tag kept for readability); Dependabot
# bumps tag and digest together, so the image is the same on every rebuild.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS builder

# uv only exports the lockfile here; it never reaches the runtime stage.
COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /usr/local/bin/uv

WORKDIR /src

# Copy only what the build backend needs. The layer is cached until one of
# these files changes, which keeps rebuilds fast.
COPY pyproject.toml uv.lock README.md ./
COPY regent/ ./regent/
COPY policies/mandates/ ./policies/mandates/

# Install into a prefix we can copy wholesale into the runtime stage.
# The dependencies are exactly the ones in uv.lock, each checked against its
# SHA-256 (--require-hashes); then the project itself, without dependencies.
# The `api` extra brings FastAPI + uvicorn; the CLI works without it.
# cloudguard:ignore CG_DOCKER_009 every dependency is pinned and hash-checked by uv.lock; "." is the project itself
RUN uv export --frozen --no-dev --extra api --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir --prefix=/install --require-hashes -r /tmp/requirements.txt \
    && pip install --no-cache-dir --prefix=/install --no-deps .

# -----------------------------------------------------------------------------
# Runtime — no build tooling, no root, read-only friendly.
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime

LABEL org.opencontainers.image.title="regent" \
      org.opencontainers.image.description="Governed AI agents for DevOps automation" \
      org.opencontainers.image.source="https://github.com/FlorianMartins/regent" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Florian Martins"

# Base images lag behind Debian security updates by days. Trivy blocks the
# build on fixable HIGH/CRITICAL CVEs, so the affected packages are upgraded
# explicitly here (a targeted upgrade, not a blanket `apt-get upgrade`, keeps
# the image reproducible). Remove a line once the base image ships the fix.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*

# A dedicated system account: uid 10001 satisfies Kubernetes `runAsNonRoot`
# even when the policy insists on a numeric uid.
RUN groupadd --system --gid 10001 regent \
    && useradd --system --uid 10001 --gid regent \
       --home /home/regent --create-home --shell /usr/sbin/nologin regent \
    && mkdir -p /app/policies /data \
    && chown -R regent:regent /app /data

COPY --from=builder /install /usr/local
# The default mandates ship with the image; mount your own on /app/policies/mandates.
COPY --from=builder --chown=regent:regent /src/policies/mandates /app/policies/mandates

USER 10001:10001
WORKDIR /app

# /data holds the ledger (declare it as a volume in production so it survives
# the container). The mandates directory is read-only by design.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REGENT_MANDATES_DIR=/app/policies/mandates \
    REGENT_LEDGER=/data/ledger.jsonl \
    REGENT_WORKSPACE=/data/workspace

EXPOSE 8080

# Probe the real liveness endpoint with the standard library — no curl in the
# image means one binary fewer to patch. The CLI form (`regent run …`) exits
# before the first probe fires, so the check only matters for `serve`.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["regent"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
