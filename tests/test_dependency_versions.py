"""Check dependency updates cannot silently leave the HA manifest behind."""

import importlib.util
import shutil
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/check_dependency_versions.py"
    spec = importlib.util.spec_from_file_location("dependency_versions", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_manifest_runtime_and_test_locks_match():
    module().check()


def test_dependency_update_requires_manifest_sync(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "requirements-runtime.in",
        "requirements-runtime.txt",
        "requirements-test.txt",
        "custom_components/lepro_cloud/manifest.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    for path in tmp_path.glob("requirements*"):
        path.write_text(
            path.read_text().replace("paho-mqtt==2.1.0", "paho-mqtt==2.2.0")
        )
    with pytest.raises(ValueError, match="Manifest Paho"):
        module().check(tmp_path)
    module().check(tmp_path, sync=True)
    module().check(tmp_path)
