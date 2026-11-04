"""Keep the HA minimum and hash-locked CI dependency compatible."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def paho_pin(path: Path) -> str:
    match = re.search(r"^paho-mqtt==([^\s\\]+)", path.read_text(), re.MULTILINE)
    if match is None:
        raise ValueError(f"{path.name} must pin paho-mqtt exactly")
    return "paho-mqtt==" + match[1]


def check(root: Path = ROOT, *, sync: bool = False) -> None:
    from packaging.requirements import Requirement

    expected = (root / "requirements-runtime.in").read_text().strip()
    requirement = Requirement(expected)
    specifiers = list(requirement.specifier)
    if (
        requirement.name != "paho-mqtt"
        or len(specifiers) != 1
        or specifiers[0].operator != ">="
    ):
        raise ValueError("Runtime Paho must declare a minimum version")
    locked = paho_pin(root / "requirements-test.txt").split("==", 1)[1]
    if locked not in requirement.specifier:
        raise ValueError("CI Paho lock is below the runtime minimum")
    path = root / "custom_components/lepro_cloud/manifest.json"
    manifest = json.loads(path.read_text())
    actual = [item for item in manifest["requirements"] if item.startswith("paho-mqtt")]
    if sync:
        manifest["requirements"] = [
            item
            for item in manifest["requirements"]
            if not item.startswith("paho-mqtt")
        ]
        manifest["requirements"].append(expected)
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    elif actual != [expected]:
        raise ValueError(
            "Manifest Paho differs from the runtime minimum; run scripts/check_dependency_versions.py --sync"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    check(sync=parser.parse_args().sync)
    print("CI Paho satisfies the runtime minimum")
