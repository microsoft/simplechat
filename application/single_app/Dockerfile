# Create nonroot user/group with a stable UID/GID (choose values consistent with your org)
ARG UID=65532
ARG GID=65532

FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder

ARG UID
ARG GID

# Copy pip.conf into the image for pip configuration
COPY docker-customization/pip.conf /etc/pip.conf

# CA
# copy certs to /etc/pki/ca-trust/source/anchors
COPY docker-customization/custom-ca-certificates/ /etc/pki/ca-trust/source/anchors
RUN update-ca-trust enable \
    && update-ca-trust extract

ENV PYTHONUNBUFFERED=1

RUN set -eux; \
    tdnf install -y curl ca-certificates; \
    printf '%s\n' \
        '[microsoft-azurelinux-3-ms-non-oss]' \
        'name=Microsoft Azure Linux 3 Non-OSS' \
        'baseurl=https://packages.microsoft.com/azurelinux/3.0/prod/ms-non-oss/$basearch' \
        'enabled=1' \
        'gpgcheck=1' \
        'gpgkey=https://packages.microsoft.com/keys/microsoft.asc' \
        > /etc/yum.repos.d/microsoft-ms-non-oss.repo; \
    mkdir -p /opt/microsoft/msodbcsql18; \
    touch /opt/microsoft/msodbcsql18/ACCEPT_EULA; \
    tdnf install -y unixODBC unixODBC-devel msodbcsql18; \
    tdnf clean all; \
    rm -rf /var/cache/tdnf

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
# Preserve the package-selected unixODBC driver registry path for the distroless runtime.
RUN set -eux; \
    driver_config_dir="$(odbcinst -j | while IFS= read -r line; do case "$line" in DRIVERS*) printf '%s\n' "${line##*: }"; break ;; esac; done)"; \
    test -n "${driver_config_dir}"; \
    test -f "${driver_config_dir}/odbcinst.ini"; \
    mkdir -p /odbc-runtime/usr/lib64 /odbc-runtime/opt "/odbc-runtime${driver_config_dir}" /odbc-runtime/etc; \
    cp -a "${driver_config_dir}/odbcinst.ini" "/odbc-runtime${driver_config_dir}/"; \
    if [ "${driver_config_dir}" != "/etc" ]; then cp -a "${driver_config_dir}/odbcinst.ini" /odbc-runtime/etc/; fi; \
    cp -a /opt/microsoft /odbc-runtime/opt/; \
    cp -a /usr/lib64/libodbc.so* /odbc-runtime/usr/lib64/; \
    cp -a /usr/lib64/libodbcinst.so* /odbc-runtime/usr/lib64/; \
    cp -a /usr/lib64/libodbccr.so* /odbc-runtime/usr/lib64/; \
    cp -a /usr/lib64/libltdl.so* /odbc-runtime/usr/lib64/

WORKDIR /app

# Copy requirements and install them to system
COPY --chown=${UID}:${GID} application/single_app/requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

FROM mcr.microsoft.com/azurelinux/distroless/python:3.12

ARG UID
ARG GID

COPY --from=builder /etc/pki /etc/pki
COPY --from=builder /etc/ssl/certs /etc/ssl/certs
COPY --from=builder /home/nonroot /home/nonroot
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /usr/lib/python3.12 /usr/lib/python3.12
COPY --from=builder /odbc-runtime/ /

USER ${UID}:${GID}

COPY --from=builder --chown=${UID}:${GID} /app /app
COPY --from=builder --chown=${UID}:${GID} /sc-temp-files /sc-temp-files

ENV HOME=/home/nonroot \
    LD_LIBRARY_PATH="/usr/lib64:/opt/microsoft/msodbcsql18/lib64" \
    PATH="/home/nonroot/.local/bin:$PATH" \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    SSL_CERT_DIR=/etc/ssl/certs \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt
    
WORKDIR /app

# Copy application code and set ownership
COPY --chown=${UID}:${GID} application/single_app ./

# Expose port
EXPOSE 5000

ENTRYPOINT ["python3", "-m", "gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
