# syntax=docker/dockerfile:1

# --- Build stage (3.14, DHI dev image) ---
FROM dhi.io/python:3.14.2-debian13-dev AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /app/venv

# Upgrade pip to fix CVE-2025-8869
RUN pip install --no-cache-dir --upgrade pip>=25.3

# Install dependencies from pyproject.toml (backend only, no streamlit)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application source
COPY src ./src
COPY templates ./templates
COPY static ./static

# Create data directory for sessions/cache and set ownership
RUN mkdir -p /app/data && chown -R 65532:65532 /app/data

# Update libsqlite3-0 to fix CVE-2025-7709 (integer overflow in FTS5 extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Runtime stage (3.14, DHI nonroot image) ---
FROM dhi.io/python:3.14.2-debian13 AS runtime-stage

# Copy updated libsqlite3 from build stage to fix CVE-2025-7709
COPY --from=build-stage /usr/lib/x86_64-linux-gnu/libsqlite3.so.0* /usr/lib/x86_64-linux-gnu/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

# Default configuration
ENV DASHBOARD_SESSION_BACKEND=sqlite
ENV DASHBOARD_SESSION_DB_PATH=/app/data/sessions.db
ENV PORTAINER_CACHE_DIR=/app/data/cache
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY --from=build-stage /app/src /app/src
COPY --from=build-stage /app/templates /app/templates
COPY --from=build-stage /app/static /app/static
COPY --from=build-stage --chown=65532:65532 /app/data /app/data

# Switch to non-root user
USER 65532

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request, urllib.error; url='http://127.0.0.1:8000/health';\ntry:\n    sys.exit(0 if urllib.request.urlopen(url, timeout=5).getcode() == 200 else 1)\nexcept urllib.error.URLError:\n    sys.exit(1)\n"]

ENTRYPOINT ["python", "-m", "uvicorn", "portainer_dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
