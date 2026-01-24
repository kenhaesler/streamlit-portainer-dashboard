# syntax=docker/dockerfile:1

# --- Build stage (3.14, DHI dev image) ---
FROM dhi.io/python:3.14.0-debian12-dev AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /app/venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY .streamlit ./.streamlit
COPY app ./app

# Ensure the Streamlit configuration directory is writable by the runtime user
RUN chown -R 65532:65532 ./.streamlit

# --- Runtime stage (3.14, DHI nonroot image) ---
FROM dhi.io/python:3.14.0-debian12 AS runtime-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY --from=build-stage /app/app /app/app
# Guarantee the runtime user owns the Streamlit configuration directory
COPY --from=build-stage --chown=65532:65532 /app/.streamlit /app/.streamlit

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request, urllib.error; url='http://127.0.0.1:8501/_stcore/health';\ntry:\n    sys.exit(0 if urllib.request.urlopen(url, timeout=5).getcode() == 200 else 1)\nexcept urllib.error.URLError:\n    sys.exit(1)\n"]
ENTRYPOINT ["python", "-m", "streamlit", "run", "app/Home.py", "--server.port=8501", "--server.address=0.0.0.0"]
