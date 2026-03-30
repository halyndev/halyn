FROM python:3.12-slim AS base

LABEL maintainer="Elmadani SALKA <contact@halyn.dev>"
LABEL org.opencontainers.image.title="Halyn"
LABEL org.opencontainers.image.description="The reality browser — AI meets the physical world"
LABEL org.opencontainers.image.source="https://github.com/halyn/halyn"
LABEL org.opencontainers.image.licenses="Proprietary"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install aiohttp pytest

# Copy source
COPY src/ src/
COPY tests/ tests/

# Non-root user
RUN groupadd -r halyn && useradd -r -g halyn -m halyn && \
    mkdir -p /home/halyn/.halyn && \
    chown -R halyn:halyn /app /home/halyn
USER halyn

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8935/health || exit 1

EXPOSE 8935

ENTRYPOINT ["python", "-m", "halyn.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8935"]

