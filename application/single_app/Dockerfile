# Builder stage: install dependencies in a virtualenv
FROM python:3.12 AS builder

WORKDIR /app

# Create a Python virtual environment
RUN python -m venv /app/venv

# Copy requirements and install them into the virtualenv
COPY application/single_app/requirements.txt .
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

# Create nonroot user/group with a stable UID/GID (choose values consistent with your org)
ARG UID=10001
ARG GID=10001

RUN set -eux; \
    groupadd --gid $GID nonroot; \
    useradd  --uid $UID --gid $GID --create-home --shell /bin/bash nonroot

USER nonroot:nonroot

WORKDIR /app

# Copy application code and set ownership
COPY --chown=nonroot:nonroot application/single_app ./

# Copy the virtualenv from the builder stage
COPY --from=builder --chown=nonroot:nonroot /app/venv /app/venv

# Expose port
EXPOSE 5000

ENTRYPOINT [ "python", "/app/app.py" ]
