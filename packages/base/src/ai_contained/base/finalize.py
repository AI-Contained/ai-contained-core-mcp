"""Finalize script — installs all providers at image build time."""

import argparse
import glob
import os
import pathlib
import shutil
import subprocess
import tempfile

UV: str = shutil.which("uv") or ""
if not UV:
    raise RuntimeError("uv not found in PATH")


def _local_overrides(providers: list[str]) -> str:
    """Build a uv --override file pinning every co-located provider to its own /opt/ copy.

    Whatever the Dockerfile author chose to COPY --from= is authoritative: --override
    replaces the *source* uv would otherwise pick for that name (a URL/git pin declared
    by some other package's dependency), not just the version, so the local build
    can never conflict with — or silently ignore — its own bundled copy.
    """
    lines = [f"{pathlib.Path(p.rstrip('/')).name} @ file://{p.rstrip('/')}" for p in providers]
    return "\n".join(lines) + "\n"


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
    # whichever provider happened to install last. --overrides makes every
    # co-located /opt/ copy authoritative over any sibling's URL/git pin for
    # the same name (see _local_overrides) — a genuine version mismatch still
    # fails loudly, since --overrides replaces the source, not the check.
    providers = sorted(glob.glob("/opt/ai-contained-*/"))
    if providers:
        uv_install = [UV, "pip", "install", "--system", "--python", "/usr/local/bin/python3"]
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
            f.write(_local_overrides(providers))
            f.flush()
            subprocess.run(
                [*uv_install, "--break-system-packages", "--overrides", f.name, *providers], check=True
            )
