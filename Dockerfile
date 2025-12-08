# --- Build stage (3.12) ---
FROM python:3.14.1-slim AS builder
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/usr/local -r requirements.txt && \
    find /usr/local/bin -maxdepth 1 -type f -name 'pip*' -exec rm -f {} + && \
    rm -rf /usr/local/lib/python3.12/site-packages/pip \
           /usr/local/lib/python3.12/site-packages/pip-*.dist-info

COPY .streamlit ./.streamlit
COPY app ./app

# Ensure the Streamlit configuration directory is writable by the runtime user
RUN chown -R 65532:65532 ./.streamlit

# --- Runtime stage (distroless 3.12) ---
FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
# Guarantee the runtime user owns the Streamlit configuration directory
COPY --from=builder --chown=65532:65532 /app/.streamlit /app/.streamlit

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request, urllib.error; url='http://127.0.0.1:8501/_stcore/health';\ntry:\n    sys.exit(0 if urllib.request.urlopen(url, timeout=5).getcode() == 200 else 1)\nexcept urllib.error.URLError:\n    sys.exit(1)\n"]
ENTRYPOINT ["python", "-m", "streamlit", "run", "app/Home.py", "--server.port=8501", "--server.address=0.0.0.0"]
