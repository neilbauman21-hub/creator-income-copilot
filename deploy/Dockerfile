# Creator Income Copilot — production image (Wave 4)
# Build:  docker build -f deploy/Dockerfile -t creator-income-copilot .
# Run:    docker run -p 8000:8000 --env-file .env creator-income-copilot
#         (PORT env var overrides the listening port — Render sets it automatically)

FROM python:3.11-slim

# Keep logs unbuffered and skip __pycache__ in the container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the runtime sources (no .venv, tests, or build_logs).
COPY main.py .
COPY core ./core
COPY static ./static
COPY sample_data ./sample_data

EXPOSE 8000

# ${PORT:-8000} lets Render (or any platform) inject the port; defaults to 8000 locally.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
