# --- Build stage (3.12) ---
FROM python:3.12.7-slim AS builder
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/usr/local -r requirements.txt

COPY app ./app

# --- Runtime stage (distroless 3.12) ---
FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app

EXPOSE 8501
ENTRYPOINT ["python", "-m", "streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
