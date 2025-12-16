# Builder stage: install dependencies in a virtualenv
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies for packages with C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    gfortran \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a Python virtual environment
RUN python -m venv /app/venv

# Copy requirements and install them into the virtualenv
COPY application/single_app/requirements.txt .
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

# Install runtime libraries only (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY application/single_app ./

# Copy the virtualenv from the builder stage
COPY --from=builder /app/venv /app/venv

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 5000

ENTRYPOINT [ "python", "/app/app.py" ]
