# Create nonroot user/group with a stable UID/GID (choose values consistent with your org)
ARG UID=65532
ARG GID=65532

FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder

ARG UID
ARG GID

# Setup pip.conf if has content
COPY pip.conf.d/ /etc/pip.conf.d

# CA
# copy certs to /etc/pki/ca-trust/source/anchors
#COPY caroots /etc/ssl/certs
RUN mkdir -p /etc/pki/ca-trust/source/anchors/ \
    && update-ca-trust enable \
    && cp /etc/ssl/certs/*.crt /etc/pki/ca-trust/source/anchors/ \
    && update-ca-trust extract

ENV PYTHONUNBUFFERED=1

RUN set -eux; \
    echo "nonroot:x:${GID}:" >> /etc/group; \
    echo "nonroot:x:${UID}:${GID}:nonroot:/home/nonroot:/bin/bash" >> /etc/passwd; \
    mkdir -p /home/nonroot; \
    chown ${UID}:${GID} /home/nonroot; \
    mkdir -p /app; \
    chown ${UID}:${GID} /app; \
    chmod 744 /app

RUN mkdir -p /app/flask_session && chown -R ${UID}:${GID} /app/flask_session
RUN mkdir /sc-temp-files && chown -R ${UID}:${GID} /sc-temp-files

WORKDIR /app

# Copy requirements and install them to system
COPY --chown=${UID}:${GID} application/single_app/requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

FROM mcr.microsoft.com/azurelinux/distroless/python:3.12

ARG UID
ARG GID

COPY --from=builder /etc/pki /etc/pki
COPY --from=builder /home/nonroot /home/nonroot
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /usr/lib/python3.12 /usr/lib/python3.12

USER ${UID}:${GID}

COPY --from=builder --chown=${UID}:${GID} /app /app
COPY --from=builder --chown=${UID}:${GID} /sc-temp-files /sc-temp-files

ENV HOME=/home/nonroot \
    PATH="/home/nonroot/.local/bin:$PATH" \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application code and set ownership
COPY --chown=${UID}:${GID} application/single_app ./

# Expose port
EXPOSE 5000

ENTRYPOINT [ "python3", "/app/app.py" ]
