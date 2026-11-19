# install_locked_rpms.py
"""Install only checksum-verified RPMs from a reviewed dependency closure."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen


def download_package(record, destination):
    url = urlparse(record["url"])
    name = Path(url.path).name
    if url.scheme != "https" or url.hostname != "packages.microsoft.com" or not name.endswith(".rpm"):
        raise ValueError("The RPM lock contains an unexpected artifact URL.")
    target = destination / name
    digest = hashlib.sha256()
    with urlopen(record["url"], timeout=60) as response, target.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            stream.write(chunk)
    if digest.hexdigest() != record["sha256"]:
        raise ValueError(f"RPM checksum mismatch: {name}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("common", "chromium"), required=True)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name("azurelinux-packages.lock.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="simplechat-rpms-") as directory:
        destination = Path(directory)
        with ThreadPoolExecutor(max_workers=8) as executor:
            packages = list(executor.map(
                lambda record: download_package(record, destination), lock["profiles"][args.profile],
            ))
        if not packages:
            raise ValueError("The selected RPM dependency closure is empty.")
        subprocess.run(["tdnf", "--disablerepo=*", "install", "-y", *map(str, packages)], check=True)


if __name__ == "__main__":
    main()
