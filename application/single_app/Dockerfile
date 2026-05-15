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

ENV ACCEPT_EULA=Y

RUN set -eux; \
    printf '%s\n' \
        '[packages-microsoft-com-prod]' \
        'name=packages-microsoft-com-prod' \
        'baseurl=https://packages.microsoft.com/azurelinux/3.0/prod/ms-non-oss/x86_64' \
        'enabled=1' \
        'gpgcheck=1' \
        'gpgkey=https://packages.microsoft.com/keys/microsoft.asc' \
        > /etc/yum.repos.d/packages-microsoft-com-prod.repo; \
    tdnf install -y msodbcsql18 unixODBC; \
    driver_lib="$(find /opt/microsoft/msodbcsql18/lib64 -name 'libmsodbcsql-*.so*' | sort | tail -n 1)"; \
    test -n "${driver_lib}"; \
    printf '[ODBC Driver 18 for SQL Server]\nDescription=Microsoft ODBC Driver 18 for SQL Server\nDriver=%s\nUsageCount=1\n' "${driver_lib}" > /etc/odbcinst.ini; \
    mkdir -p /odbc-runtime/usr/lib64; \
    for lib in /usr/lib64/libodbc* /usr/lib/libodbc* /usr/lib64/libltdl* /usr/lib/libltdl*; do \
        if [ -e "${lib}" ]; then cp -a "${lib}" /odbc-runtime/usr/lib64/; fi; \
    done; \
    find /odbc-runtime/usr/lib64 -maxdepth 1 -name 'libodbc*' | grep -q .; \
    find /odbc-runtime/usr/lib64 -maxdepth 1 -name 'libltdl*' | grep -q .; \
    tdnf clean all

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
COPY --from=builder /etc/ssl/certs /etc/ssl/certs
COPY --from=builder /home/nonroot /home/nonroot
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /usr/lib/python3.12 /usr/lib/python3.12
COPY --from=builder /opt/microsoft /opt/microsoft
COPY --from=builder /etc/odbcinst.ini /etc/odbcinst.ini
COPY --from=builder /odbc-runtime/usr/lib64/ /usr/lib64/

USER ${UID}:${GID}

COPY --from=builder --chown=${UID}:${GID} /app /app
COPY --from=builder --chown=${UID}:${GID} /sc-temp-files /sc-temp-files

ENV HOME=/home/nonroot \
    PATH="/home/nonroot/.local/bin:$PATH" \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/usr/lib64:/opt/microsoft/msodbcsql18/lib64 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    SSL_CERT_DIR=/etc/ssl/certs \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt
    
WORKDIR /app

# Copy application code and set ownership
COPY --chown=${UID}:${GID} application/single_app ./

# Expose port
EXPOSE 5000

ENTRYPOINT ["python3", "-m", "gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
