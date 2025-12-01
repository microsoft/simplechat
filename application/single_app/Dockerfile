# Builder stage: Use standard Python image with all build tools
FROM python:3.12-slim AS builder

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libpq-dev \
    libmariadb-dev \
    unixodbc-dev \
    libffi-dev \
    libssl-dev \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Ensure /app directory exists and has proper permissions
RUN mkdir -p /app && chown root:root /app

WORKDIR /app

# Create a Python virtual environment
RUN python -m venv /app/venv

# Create and permission the flask_session directory in builder stage
RUN mkdir -p /app/flask_session && chmod 777 /app/flask_session

# Copy requirements and install them into the virtualenv
COPY application/single_app/requirements.txt .
ENV PATH="/app/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage: Use secure Chainguard image
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

# Copy application code and set ownership
COPY --chown=nonroot:nonroot application/single_app ./

# Copy the virtualenv from the builder stage
COPY --from=builder --chown=nonroot:nonroot /app/venv /app/venv

# Copy the flask_session directory from the builder stage
COPY --from=builder --chown=nonroot:nonroot /app/flask_session /app/flask_session

# Expose port
EXPOSE 5000

USER nonroot:nonroot

ENTRYPOINT [ "python", "/app/app.py" ]
