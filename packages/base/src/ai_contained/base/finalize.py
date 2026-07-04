"""Finalize script — installs all providers at image build time."""

import argparse
import glob
import os
import pathlib
import shutil
import subprocess

UV: str = shutil.which("uv") or ""
if not UV:
    raise RuntimeError("uv not found in PATH")


def _apk_packages() -> list[str]:
    """Union of every provider's apk-packages.txt (newline list, # comments)."""
    packages: set[str] = set()
    for f in glob.glob("/opt/ai-contained-*/apk-packages.txt"):
        for line in pathlib.Path(f).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                packages.add(line)
    return sorted(packages)


def main() -> None:
    """Symlink provider binaries, install apk packages, and install all provider packages."""
    parser = argparse.ArgumentParser(description="Install AI-Contained providers into the image")
    parser.parse_args()
    for b in glob.glob("/opt/ai-contained-*/bin/*"):
        p = pathlib.Path(b)
        dest = pathlib.Path(f"/usr/local/bin/{p.name}")
        if p.is_file() and not dest.exists():
            os.symlink(b, dest)

    apk_packages = _apk_packages()
    if apk_packages:
        subprocess.run(["apk", "add", "--no-cache", *apk_packages], check=True)

    # One invocation for all providers: uv resolves the union jointly, so a
    # shared dependency satisfies every provider's constraint instead of
    # whichever provider happened to install last. Conflicting direct-URL
    # pins fail the build loudly here — fix the pins, not the order.
    providers = sorted(glob.glob("/opt/ai-contained-*/"))
    if providers:
        uv_install = [UV, "pip", "install", "--system", "--python", "/usr/local/bin/python3"]
        subprocess.run([*uv_install, "--break-system-packages", *providers], check=True)
