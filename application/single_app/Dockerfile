# Builder stage: install dependencies in a virtualenv
FROM cgr.dev/chainguard/python:latest-dev AS builder

USER root

# Ensure /app directory exists and has proper permissions
RUN mkdir -p /app && chown root:root /app

WORKDIR /app

# Create a Python virtual environment
RUN python -m venv /app/venv

# Create and permission the flask_session directory
RUN mkdir -p /app/flask_session && chown -R nonroot:nonroot /app/flask_session

# Copy requirements and install them into the virtualenv
COPY application/single_app/requirements.txt .
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

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
