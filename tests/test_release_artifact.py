"""Offline checks for archive integrity and the manual release gate."""

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_requires_exact_successful_verification_commit():
    gate = load("check_verification")
    valid = {
        "status": "completed",
        "conclusion": "success",
        "head_sha": "fixture",
        "event": "workflow_dispatch",
        "path": ".github/workflows/release-verify.yml",
        "repository": {"full_name": "Wheemer/lepro-cloud"},
    }
    gate.validate(
        valid,
        "Wheemer/lepro-cloud",
        "fixture",
        {"commit": "fixture", "ref": "v1", "run_id": "12"},
        "v1",
        "12",
    )
    for key, value in (
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("event", "pull_request"),
        ("path", ".github/workflows/other.yml"),
        ("repository", {"full_name": "someone/else"}),
    ):
        changed = deepcopy(valid)
        changed[key] = value
        with pytest.raises(ValueError):
            gate.validate(
                changed,
                "Wheemer/lepro-cloud",
                "fixture",
                {"commit": "fixture", "ref": "v1", "run_id": "12"},
                "v1",
                "12",
            )

    for receipt in (
        {"commit": "other", "ref": "v1", "run_id": "12"},
        {"commit": "fixture", "ref": "v2", "run_id": "12"},
        {"commit": "fixture", "ref": "v1", "run_id": "13"},
    ):
        with pytest.raises(ValueError):
            gate.validate(valid, "Wheemer/lepro-cloud", "fixture", receipt, "v1", "12")


def test_packaged_icon_has_complete_crc_checked_png_data():
    release = load("build_release")
    data = (release.COMPONENT / "brand/icon.png").read_bytes()
    release.validate_png(data)
    for invalid in (data[:8], data[:-8], b"not an image"):
        with pytest.raises(ValueError):
            release.validate_png(invalid)
