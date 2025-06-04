# Builder stage: install dependencies in a virtualenv
FROM cgr.dev/chainguard/python:latest-dev AS builder

WORKDIR /app

# Create a Python virtual environment
RUN python -m venv /app/venv

# Copy requirements and install them into the virtualenv
COPY application/single_app/requirements.txt .
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Production stage: copy only the venv and app code
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

# Set environment so Python output is logged directly
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

# Copy application code
COPY application/single_app ./

# Copy the virtualenv from the builder stage
COPY --from=builder /app/venv /app/venv

EXPOSE 5000

ENTRYPOINT [ "python", "/app/app.py" ]
