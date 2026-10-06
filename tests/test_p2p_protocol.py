"""Tests for APK-derived Lepro camera P2P wire primitives."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "lepro_cloud" / "p2p_protocol.py"
_SPEC = spec_from_file_location("lepro_cloud_p2p_protocol", _PATH)
assert _SPEC and _SPEC.loader
protocol = module_from_spec(_SPEC)
_SPEC.loader.exec_module(protocol)


def test_encrypts_native_command_header_with_verified_aes_parameters() -> None:
    assert protocol.encrypt_command(0x1208).hex() == "97cf4f78b0deb329177f8381f9fcbe13"


def test_round_trips_an_encrypted_command_packet() -> None:
    packet = protocol.make_command_packet(0x1208, b"abc", 1234, 9)
    assert packet[:12].hex() == "a0800400d204000009000000"
    assert protocol.parse_command_packet(packet) == (0x1208, 1234, 9, b"abc")


def test_rejects_invalid_packet() -> None:
    try:
        protocol.parse_command_packet(b"bad")
    except ValueError as error:
        assert "too short" in str(error)
    else:
        raise AssertionError("invalid packet was accepted")
