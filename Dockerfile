# --- Build stage (3.12) ---
FROM python:3.12.7-slim AS builder
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/usr/local -r requirements.txt

COPY .streamlit ./.streamlit
COPY app ./app

# --- Runtime stage (distroless 3.12) ---
FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request, urllib.error; url='http://127.0.0.1:8501/_stcore/health';\ntry:\n    sys.exit(0 if urllib.request.urlopen(url, timeout=5).getcode() == 200 else 1)\nexcept urllib.error.URLError:\n    sys.exit(1)\n"]
ENTRYPOINT ["python", "-m", "streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
