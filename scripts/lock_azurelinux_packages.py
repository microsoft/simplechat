# lock_azurelinux_packages.py
"""Resolve RPM closures inside the exact application builder image."""

import configparser
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urljoin
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "mcr.microsoft.com/azurelinux/base/python:3.12.16-1-azl3.0.20261028@sha256:71a1f5a1821f4c56e45aff52e792ed6c0500631e201cfc140c4c9d22886b29f9"
PACKAGES = {
    "common": ["curl", "ca-certificates", "unixODBC", "unixODBC-devel", "msodbcsql18", "libgcc-atomic"],
    "chromium": [
        "alsa-lib", "atk", "at-spi2-atk", "at-spi2-core", "cairo", "cups-libs",
        "dbus-libs", "expat", "fontconfig", "freetype", "glib2", "gtk3", "libdrm",
        "libjpeg-turbo", "libpng", "libX11", "libxcb", "libXcomposite", "libXcursor",
        "libXdamage", "libXext", "libXfixes", "libXi", "libXrandr", "libXrender",
        "libXtst", "libxkbcommon", "libxshmfence", "mesa-libgbm", "nspr", "nss",
        "pango", "dejavu-sans-fonts",
    ],
}
NS = "{http://linux.duke.edu/metadata/common}"


def repository_packages():
    configuration = configparser.ConfigParser(interpolation=None)
    configuration.read(Path("/etc/yum.repos.d").glob("*.repo"))
    packages = {}
    for metadata in Path("/var/cache/tdnf").glob("*/repodata/*-primary.xml.gz"):
        repository = next(
            name for name in configuration
            if metadata.parents[1].name.startswith(name + "-")
        )
        base = configuration[repository]["baseurl"].replace("$releasever", "3.0").replace("$basearch", "x86_64")
        with gzip.open(metadata, "rb") as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag != NS + "package":
                    continue
                location = element.find(NS + "location").attrib["href"]
                checksum = element.find(NS + "checksum")
                if checksum.attrib["type"] != "sha256":
                    raise ValueError(f"Unexpected repository checksum: {checksum.attrib['type']}")
                packages[Path(location).name] = {
                    "url": urljoin(base.rstrip("/") + "/", location),
                    "sha256": checksum.text,
                    "published_at": int(element.find(NS + "time").attrib["file"]),
                }
                element.clear()
    return packages


def main():
    selected = datetime.now(timezone.utc)
    cutoff = int((selected - timedelta(days=14)).timestamp())
    profiles = {}
    with tempfile.TemporaryDirectory(prefix="simplechat-rpms-") as directory:
        for profile, names in PACKAGES.items():
            destination = Path(directory) / profile
            destination.mkdir()
            command = ["tdnf", f"--snapshottime={cutoff}", "install", "-y", *names]
            subprocess.run(
                [*command, "--downloadonly", f"--downloaddir={destination}"], check=True,
            )
            metadata = repository_packages()
            records = []
            for package in sorted(destination.glob("*.rpm")):
                record = dict(metadata[package.name])
                if hashlib.sha256(package.read_bytes()).hexdigest() != record["sha256"]:
                    raise ValueError(f"Repository checksum mismatch: {package.name}")
                if record["published_at"] > cutoff:
                    raise ValueError(f"RPM has not been published for 14 days: {package.name}")
                records.append(record)
            if not records:
                raise ValueError(f"No dependency closure resolved for {profile}")
            profiles[profile] = records
            subprocess.run(command, check=True)
    output = {
        "base_image": BASE_IMAGE, "selected_at": selected.isoformat(),
        "minimum_age_days": 14, "profiles": profiles,
    }
    (ROOT / "docker-customization" / "azurelinux-packages.lock.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
