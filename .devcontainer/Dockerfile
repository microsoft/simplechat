FROM mcr.microsoft.com/devcontainers/base:1.2.6-ubuntu-24.04@sha256:763eca1839b2c6366f25b9c2b4c75c46e3d485a8d1b95f725e829397398a4c46
RUN sed -i \
        -e 's|http://archive.ubuntu.com/ubuntu/|https://snapshot.ubuntu.com/ubuntu/20261104T000000Z/|g' \
        -e 's|http://security.ubuntu.com/ubuntu/|https://snapshot.ubuntu.com/ubuntu/20261104T000000Z/|g' \
        -e '/^Signed-By:/a Check-Valid-Until: no' \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update && apt-get install -y xz-utils