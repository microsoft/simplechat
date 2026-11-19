# Stage 1: System dependencies and ODBC driver install
ARG PYTHON_VERSION_ARG="3.12"
FROM python:3.12.12-bookworm@sha256:c0abd0758831ad99b7a29e0c1a875da9c4abb9a2e3f21e2eeb585dbcadfb6cd0 AS builder

ARG PYTHON_VERSION_ARG
ARG DRIVER_MAJOR_VERSION="2.9.2"
ARG DRIVER_MINOR_VERSION=1008
ARG DRIVER_SHA256="57e07f0c8ca17784d6bb8217f65a6d500b822816473299dc2cb618e75066b4a0"
ARG BUCKET_URI="https://databricks-bi-artifacts.s3.us-east-2.amazonaws.com/simbaspark-drivers/odbc"

ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV DRIVER_FULL_VERSION=${DRIVER_MAJOR_VERSION}.${DRIVER_MINOR_VERSION}
ENV FOLDER_NAME=SimbaSparkODBC-${DRIVER_FULL_VERSION}-Debian-64bit
ENV ZIP_FILE_NAME=${FOLDER_NAME}.zip

WORKDIR /deps

RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/20261104T000000Z/|g' \
        -e 's|http://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/20261104T000000Z/|g' \
        -e '/^Signed-By:/a Check-Valid-Until: no' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y unixodbc unixodbc-dev wget unzip libsasl2-modules-gssapi-mit
# "https://databricks-bi-artifacts.s3.us-east-2.amazonaws.com/simbaspark-drivers/odbc/2.9.2/SimbaSparkODBC-2.9.2.1008-Debian-64bit.zip"
RUN wget -O /tmp/simbaspark.zip ${BUCKET_URI}/${DRIVER_MAJOR_VERSION}/${ZIP_FILE_NAME} \
    && echo "${DRIVER_SHA256}  /tmp/simbaspark.zip" | sha256sum -c - \
    && unzip /tmp/simbaspark.zip -d /tmp/simbaspark && rm /tmp/simbaspark.zip

RUN dpkg -i /tmp/simbaspark/SimbaSparkODBC-2.9.2.1008-Debian-64bit/simbaspark_2.9.2.1008-2_amd64.deb

USER root
RUN groupadd -g 65532 nonroot && useradd -m -u 65532 -g nonroot nonroot
RUN python -m venv /app/venv
COPY requirements-build.lock.txt /build-assets/requirements-build.lock.txt
ENV PIP_BUILD_CONSTRAINT=/build-assets/requirements-build.lock.txt
RUN python -m pip install pip==26.0.1 \
    && pip install pyodbc==5.3.0 \
    && pip install wheel==0.45.1 \
    && pip wheel pyodbc==5.3.0 -w /tmp/pyodbc-wheel

#RUN find / -name "*odbc*" || true
RUN find / -name "*python${PYTHON_VERSION_ARG}*" || true

WORKDIR /app
# Copy requirements and install them into the virtualenv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt requirements.lock.txt .
RUN pip install /tmp/pyodbc-wheel/pyodbc-*.whl \
    && pip install --no-cache-dir -c requirements.lock.txt -r requirements.txt

# Fix permissions so nonroot can use everything
RUN chown -R 65532:65532 /app

RUN echo "[Simba Spark ODBC Driver]\nDescription=Simba Spark ODBC Driver\nDriver=/opt/simba/spark/lib/64/libsparkodbc_sb64.so" > /etc/odbcinst.ini
RUN echo "[ODBC Data Sources]\nSimba Spark ODBC DSN=Simba Spark ODBC Driver" > /etc/odbc.ini
RUN find / -type f -name '*odbc*' || true
RUN find /etc/ -type f -name '*odbc*' -exec echo "Contents of {}:" \; -exec cat {} \; || true

RUN echo "PATH contents:" && echo $PATH | tr ':' '\n' \
    && echo "LD_LIBRARY_PATH contents:" && echo $LD_LIBRARY_PATH | tr ':' '\n'

RUN mkdir -p /app/flask_session && chown -R 65532:65532 /app/flask_session
RUN mkdir /sc-temp-files
RUN cat /opt/simba/spark/Setup/odbc.ini
RUN cat /opt/simba/spark/Setup/odbcinst.ini
USER 65532:65532

#Stage 3: Final containter
FROM gcr.io/distroless/python3-debian12@sha256:2fdb05402a2cf21cf78fdb3ba4c5db167241e9e498140f5bf689d7efb773731f
ARG PYTHON_VERSION_ARG
WORKDIR /app
USER root
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:/usr/local/bin:$PATH"
ENV LD_LIBRARY_PATH="/opt/simba/spark/lib/64:/usr/local/lib:/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
#Copy 3.12 from Base
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION_ARG} /usr/local/lib/python${PYTHON_VERSION_ARG}
COPY --from=builder \
    /usr/local/lib/libpython3.12.so \
    /usr/local/lib/libpython3.12.so.1.0 \
    /usr/local/lib/libpython3.so \ 
    /usr/local/lib/pkgconfig \ 
    /usr/local/lib/python3.12 \ 
    /usr/local/lib/python3.13 \ 
    /usr/local/lib/
# Copy the Python interpreter with a specific name
COPY --from=builder /usr/local/bin/python${PYTHON_VERSION_ARG} /usr/local/bin/python${PYTHON_VERSION_ARG}
# Add all common Python 3.12 entrypoints for compatibility
COPY --from=builder \ 
    /usr/local/bin/python \
    /usr/local/bin/python3 \
    /usr/local/bin/python${PYTHON_VERSION_ARG} \
    /usr/local/bin/

# Copy system libraries for x86_64
COPY --from=builder /lib/x86_64-linux-gnu/ /lib/x86_64-linux-gnu/

# Copy ODBC from deps build
COPY --from=builder /usr/include /usr/include
COPY --from=builder /opt/simba /opt/simba
COPY --from=builder \
    /etc/odbc.ini \
    /etc/odbcinst.ini \
    /etc/
COPY --from=builder \
    /usr/lib/x86_64-linux-gnu/libodbc.so \
    /usr/lib/x86_64-linux-gnu/libodbc.so.2 \
    /usr/lib/x86_64-linux-gnu/libodbc.so.2.0.0 \
    /usr/lib/x86_64-linux-gnu/libodbcinst.so \
    /usr/lib/x86_64-linux-gnu/libodbcinst.so.2 \
    /usr/lib/x86_64-linux-gnu/libodbcinst.so.2.0.0 \
    /usr/lib/x86_64-linux-gnu/libodbccr.so \
    /usr/lib/x86_64-linux-gnu/libodbccr.so.2 \
    /usr/lib/x86_64-linux-gnu/libodbccr.so.2.0.0 \
    /usr/lib/x86_64-linux-gnu/

# Copy application code and set ownership
COPY --chown=65532:65532 . ./

# Copy the virtualenv from the builder stage
COPY --from=builder --chown=65532:65532 /app/venv /app/venv
COPY --from=builder --chown=65532:65532 /app/flask_session /app/flask_session
COPY --from=builder --chown=65532:65532 /sc-temp-files /sc-temp-files

# Expose port
EXPOSE 5000

USER 65532:65532

ENTRYPOINT ["/app/venv/bin/python", "-c", "import sys, runpy; print('Executable:', sys.executable); print('Version:', sys.version); runpy.run_path('/app/app.py', run_name='__main__')"]