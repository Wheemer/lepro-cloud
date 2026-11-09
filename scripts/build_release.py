"""Build and verify the integration archive without publishing anything."""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "lepro_cloud"


def validate_png(data: bytes) -> None:
    if not data.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])):
        raise ValueError("Invalid PNG signature")
    position = 8
    header = False
    pixels = False
    while position + 12 <= len(data):
        size = struct.unpack(">I", data[position : position + 4])[0]
        chunk = data[position + 4 : position + 8]
        end = position + 8 + size
        if (
            end + 4 > len(data)
            or zlib.crc32(data[position + 4 : end])
            != struct.unpack(">I", data[end : end + 4])[0]
        ):
            raise ValueError("Truncated or corrupt PNG")
        if chunk == b"IHDR":
            if size != 13 or position != 8:
                raise ValueError("Invalid PNG header")
            width, height = struct.unpack(">II", data[position + 8 : position + 16])
            header = 0 < width <= 8192 and 0 < height <= 8192
        if chunk == b"IDAT":
            pixels = True
        if chunk == b"IEND":
            if not header or not pixels or end + 4 != len(data):
                raise ValueError("Invalid PNG structure")
            return
        position = end + 4
    raise ValueError("PNG has no end chunk")


def verify(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt release ZIP")
        names = set(archive.namelist())
        required = {
            "manifest.json",
            "strings.json",
            "translations/en.json",
            "brand/icon.png",
            "_private/mqtt_client_key.pem",
            "app_auth.py",
            "catalog.py",
            "capabilities.py",
            "log_helpers.py",
            "scenes.py",
        }
        if not required <= names:
            raise ValueError("Release ZIP is missing required files")
        if any(
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or "__pycache__" in name
            for name in names
        ):
            raise ValueError("Unsafe archive path")
        if json.loads(archive.read("strings.json")) != json.loads(
            archive.read("translations/en.json")
        ):
            raise ValueError("English translations differ from strings.json")
        validate_png(archive.read("brand/icon.png"))
        subprocess.run(
            ["openssl", "pkey", "-check", "-noout"],
            input=archive.read("_private/mqtt_client_key.pem"),
            check=True,
            stdout=subprocess.DEVNULL,
        )
    print("Integration ZIP verified")


def build(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(COMPONENT.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            relative = source.relative_to(COMPONENT)
            if source.suffix not in {".py", ".json", ".png", ".pem"}:
                continue
            if (
                source.suffix == ".pem"
                and relative.as_posix() != "_private/mqtt_client_key.pem"
            ):
                continue
            archive.write(source, relative.as_posix())
    verify(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    (verify if args.verify_only else build)(args.path)
