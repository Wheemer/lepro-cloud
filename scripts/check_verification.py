"""Require a successful verification run for the checked-out release commit."""

from __future__ import annotations

import json
import os
import subprocess


def validate(
    run: dict, repository: str, sha: str, receipt: dict, ref: str, run_id: str
) -> None:
    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or receipt.get("commit") != sha
        or receipt.get("ref") != ref
        or str(receipt.get("run_id")) != run_id
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/release-verify.yml"
        or run.get("repository", {}).get("full_name") != repository
    ):
        raise ValueError(
            "A successful Release Verification run for this exact commit is required"
        )


if __name__ == "__main__":
    identifier = os.environ["VERIFICATION_RUN_ID"]
    if not identifier.isdigit():
        raise ValueError("Verification run ID must be numeric")
    repository = os.environ["GITHUB_REPOSITORY"]
    run = json.loads(
        subprocess.check_output(
            ["gh", "api", f"repos/{repository}/actions/runs/{identifier}"]
        )
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    from pathlib import Path

    receipt = json.loads(Path("dist/verification.json").read_text())
    validate(run, repository, sha, receipt, os.environ["GITHUB_REF_NAME"], identifier)
    print("Release verification gate passed")
