# Stage 1: System dependencies and ODBC driver install
ARG PYTHON_MAJOR_VERSION_ARG="3"
ARG PYTHON_MINOR_VERSION_ARG="13"
ARG PYTHON_PATCH_VERSION_ARG="11"
FROM debian:12-slim AS builder

ARG PYTHON_MAJOR_VERSION_ARG
ARG PYTHON_MINOR_VERSION_ARG
ARG PYTHON_PATCH_VERSION_ARG

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Build deps for CPython and pip stdlib modules
WORKDIR /deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget ca-certificates \
    libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
    libncursesw5-dev libffi-dev liblzma-dev uuid-dev tk-dev && \
    rm -rf /var/lib/apt/lists/*

# Build and install Python from source
# Example: https://www.python.org/ftp/python/3.13.11/Python-3.13.11.tgz
WORKDIR /tmp
RUN wget https://www.python.org/ftp/python/${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG}.${PYTHON_PATCH_VERSION_ARG}/Python-${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG}.${PYTHON_PATCH_VERSION_ARG}.tgz && \
    tar -xzf Python-${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG}.${PYTHON_PATCH_VERSION_ARG}.tgz && \
    cd Python-${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG}.${PYTHON_PATCH_VERSION_ARG} && \
    LDFLAGS="-Wl,-rpath,/usr/local/lib" ./configure --enable-optimizations --enable-shared --with-ensurepip=install --prefix=/usr/local && \
    make -j"$(nproc)" && \
    make altinstall

USER root
WORKDIR /app
RUN groupadd -g 65532 nonroot && useradd -m -u 65532 -g nonroot nonroot

RUN python${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG} -m venv /app/venv
RUN python${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG} -m pip install wheel

# Copy requirements and install them into the virtualenv
ENV PATH="/app/venv/bin:$PATH"
COPY application/single_app/requirements.txt /app/requirements.txt
RUN python${PYTHON_MAJOR_VERSION_ARG}.${PYTHON_MINOR_VERSION_ARG} -m pip install --no-cache-dir -r /app/requirements.txt

# Fix permissions so nonroot can use everything
RUN chown -R 65532:65532 /app

RUN mkdir -p /app/flask_session && chown -R 65532:65532 /app/flask_session
RUN mkdir /sc-temp-files && chown -R 65532:65532 /sc-temp-files
USER 65532:65532

#Stage 2: Final containter
FROM gcr.io/distroless/base-debian12:latest
ARG PYTHON_MAJOR_VERSION_ARG
ARG PYTHON_MINOR_VERSION_ARG
ARG PYTHON_PATCH_VERSION_ARG

ENV PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/venv/bin:/usr/local/bin:$PATH" \
    LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH}"

WORKDIR /app

USER root

# Copy only the built Python interpreter (venv entrypoint handles python/python3)
# Copy the full CPython installation so stdlib modules (e.g., encodings) are available
COPY --from=builder /usr/local/ /usr/local/

# Copy system libraries for x86_64
COPY --from=builder /lib/x86_64-linux-gnu/ \
    /lib64/ld-linux-x86-64.so.2 \
    /usr/lib/x86_64-linux-gnu/
    #/usr/share/ca-certificates \
    #/etc/ssl/certs \
    #/usr/bin/ffmpeg \
    #/usr/share/zoneinfo /usr/share/

# Copy application code and set ownership
COPY --chown=65532:65532 application/single_app/ /app/

# Copy the virtualenv from the builder stage
COPY --from=builder --chown=65532:65532 /app/venv /app/venv
COPY --from=builder --chown=65532:65532 /app/flask_session /app/flask_session
COPY --from=builder --chown=65532:65532 /sc-temp-files /sc-temp-files

# Expose port
EXPOSE 5000

USER 65532:65532


ENTRYPOINT ["/app/venv/bin/python", "-c", "import runpy; runpy.run_path('/app/app.py', run_name='__main__')"]