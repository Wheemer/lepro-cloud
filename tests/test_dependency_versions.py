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
        "requirements-test.txt",
        "custom_components/lepro_cloud/manifest.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    path = tmp_path / "requirements-runtime.in"
    path.write_text("paho-mqtt>=2.0.0\n")
    with pytest.raises(ValueError, match="Manifest Paho"):
        module().check(tmp_path)
    module().check(tmp_path, sync=True)
    module().check(tmp_path)
    path.write_text("paho-mqtt>=3.0.0\n")
    with pytest.raises(ValueError, match="below the runtime minimum"):
        module().check(tmp_path, sync=True)


@pytest.mark.parametrize("locked", ["2.1.0", "2.2.0"])
def test_ci_version_can_advance_without_raising_runtime_minimum(tmp_path, locked):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "custom_components/lepro_cloud/manifest.json"
    target.parent.mkdir(parents=True)
    shutil.copy2(root / "custom_components/lepro_cloud/manifest.json", target)
    (tmp_path / "requirements-runtime.in").write_text("paho-mqtt>=2.1.0\n")
    (tmp_path / "requirements-test.txt").write_text("paho-mqtt==" + locked + "\n")
    module().check(tmp_path, sync=True)
    assert "paho-mqtt>=2.1.0" in target.read_text()


@pytest.mark.parametrize("requirement", ["paho-mqtt==2.1.0", "paho-mqtt>=2.1.0,<3"])
def test_runtime_requires_one_minimum_specifier(tmp_path, requirement):
    (tmp_path / "requirements-runtime.in").write_text(requirement)
    with pytest.raises(ValueError, match="declare a minimum"):
        module().check(tmp_path)
