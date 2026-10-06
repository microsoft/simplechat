# Dockerfile (map server)
# Build from the repository root: docker build -f application/map_server/Dockerfile .
ARG UID=65532
ARG GID=65532

FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder

ARG UID
ARG GID

COPY docker-customization/pip.conf /etc/pip.conf
COPY docker-customization/custom-ca-certificates/ /etc/pki/ca-trust/source/anchors
RUN update-ca-trust enable \
    && update-ca-trust extract

ENV PYTHONUNBUFFERED=1

RUN set -eux; \
    echo "nonroot:x:${GID}:" >> /etc/group; \
    echo "nonroot:x:${UID}:${GID}:nonroot:/home/nonroot:/bin/bash" >> /etc/passwd; \
    mkdir -p /home/nonroot /app; \
    chown ${UID}:${GID} /home/nonroot /app; \
    chmod 744 /app

WORKDIR /app
COPY application/map_server/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

FROM mcr.microsoft.com/azurelinux/distroless/python:3.12

ARG UID
ARG GID

COPY --from=builder /etc/pki /etc/pki
COPY --from=builder /etc/ssl/certs /etc/ssl/certs
COPY --from=builder /home/nonroot /home/nonroot
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /usr/lib/python3.12 /usr/lib/python3.12

USER ${UID}:${GID}

COPY --from=builder --chown=${UID}:${GID} /app /app

ENV HOME=/home/nonroot \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    SSL_CERT_DIR=/etc/ssl/certs \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt

WORKDIR /app
COPY --chown=${UID}:${GID} application/map_server/mapserver ./mapserver

EXPOSE 8080
ENTRYPOINT ["python3", "-m", "uvicorn", "mapserver.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-server-header"]
