# Stage 1: System dependencies and ODBC driver install
ARG PYTHON_VERSION_ARG="3.12"
FROM python:3.12 AS builder

ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

WORKDIR /deps

RUN apt-get update && apt-get install -y wget unzip

USER root
RUN groupadd -g 65532 nonroot && useradd -m -u 65532 -g nonroot nonroot
RUN python -m venv /app/venv
RUN pip install wheel

WORKDIR /app
# Copy requirements and install them into the virtualenv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Fix permissions so nonroot can use everything
RUN chown -R 65532:65532 /app

RUN mkdir -p /app/flask_session && chown -R 65532:65532 /app/flask_session
RUN mkdir /sc-temp-files
USER 65532:65532

#Stage 2: Final containter
FROM gcr.io/distroless/base-debian12:latest
ARG PYTHON_VERSION_ARG
WORKDIR /app
USER root
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:/usr/local/bin:$PATH"
#Copy 3.12 from Base
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION_ARG} /usr/local/lib/python${PYTHON_VERSION_ARG}
# Copy the Python interpreter with a specific name
COPY --from=builder /usr/local/bin/python${PYTHON_VERSION_ARG} /usr/local/bin/python${PYTHON_VERSION_ARG}
COPY --from=builder \
    /usr/local/lib/libpython3.12.so \
    /usr/local/lib/libpython3.12.so.1.0 \
    /usr/local/lib/libpython3.so \ 
    /usr/local/lib/pkgconfig \ 
    /usr/local/lib/python3.12 \ 
    /usr/local/lib/python3.13 \ 
    /usr/local/lib/
# Add all common Python 3.12 entrypoints for compatibility
COPY --from=builder \ 
    /usr/local/bin/python \
    /usr/local/bin/python3 \
    /usr/local/bin/python${PYTHON_VERSION_ARG} \
    /usr/local/bin/

# Copy system libraries for x86_64
COPY --from=builder /lib/x86_64-linux-gnu/ \
    /usr/lib/x86_64-linux-gnu/ \
    /lib64/ld-linux-x86-64.so.2 \
    /usr/share/ca-certificates \
    /etc/ssl/certs \
    /usr/bin/ffmpeg \
    /usr/share/zoneinfo /usr/share/
    

# Copy application code and set ownership
COPY --chown=65532:65532 . ./

# Copy the virtualenv from the builder stage
COPY --from=builder --chown=65532:65532 /app/venv /app/venv
COPY --from=builder --chown=65532:65532 /app/flask_session /app/flask_session
COPY --from=builder --chown=65532:65532 /sc-temp-files /sc-temp-files

# Expose port
EXPOSE 5000

USER 65532:65532

ENTRYPOINT ["/app/venv/bin/python", "-c", "import runpy; runpy.run_path('/app/app.py', run_name='__main__')"]