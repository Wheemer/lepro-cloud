"""Lepro camera P2P wire primitives derived from the Android application."""

from __future__ import annotations

import struct
from typing import Final

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

P2P_AES_KEY: Final = b"PJtE2rp7Hq6RrUCgYIARj9A3GAQSNwF8"
P2P_AES_IV: Final = b"\0" * 16
P2P_MAGIC: Final = 0xA0
P2P_COMMAND_PACKET: Final = 4
P2P_SHORT_PACKET: Final = 0x80
P2P_LONG_PACKET: Final = 0xC0
P2P_SHORT_MAX_PAYLOAD: Final = 504


def _zero_pad(payload: bytes) -> bytes:
    """Pad to an AES block with the zero-padding used by the native client."""
    block_size = algorithms.AES.block_size // 8
    remainder = len(payload) % block_size
    if remainder:
        payload += b"\0" * (block_size - remainder)
    return payload


def encrypt_command(command: int, payload: bytes = b"") -> bytes:
    """Encode and encrypt a native camera command body.

    The native client serializes a little-endian command ID and byte count before
    AES-256-CBC encryption with a zero IV.
    """
    command_body = struct.pack("<II", command, len(payload)) + payload
    encryptor = Cipher(algorithms.AES(P2P_AES_KEY), modes.CBC(P2P_AES_IV)).encryptor()
    return encryptor.update(_zero_pad(command_body)) + encryptor.finalize()


def decrypt_command(ciphertext: bytes) -> tuple[int, bytes]:
    """Decrypt a native camera command body and return its command and payload."""
    if not ciphertext or len(ciphertext) % (algorithms.AES.block_size // 8):
        raise ValueError("invalid encrypted camera command length")
    decryptor = Cipher(algorithms.AES(P2P_AES_KEY), modes.CBC(P2P_AES_IV)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    if len(plain) < 8:
        raise ValueError("camera command is shorter than its header")
    command, size = struct.unpack_from("<II", plain)
    if size > len(plain) - 8:
        raise ValueError("camera command payload length is invalid")
    return command, plain[8 : 8 + size]


def make_command_packet(command: int, payload: bytes, timestamp: int, sequence: int) -> bytes:
    """Build one encrypted P2P command packet matching the native packet header."""
    encrypted = encrypt_command(command, payload)
    flags = P2P_SHORT_PACKET if len(payload) <= P2P_SHORT_MAX_PAYLOAD else P2P_LONG_PACKET
    header = struct.pack(
        "<BBHII", P2P_MAGIC, flags, P2P_COMMAND_PACKET, timestamp & 0xFFFFFFFF, sequence & 0xFFFFFFFF
    )
    return header + encrypted


def parse_command_packet(packet: bytes) -> tuple[int, int, int, bytes]:
    """Parse an encrypted P2P command packet into command, timestamp, sequence, and data."""
    if len(packet) < 28:
        raise ValueError("camera command packet is too short")
    magic, flags, packet_type, timestamp, sequence = struct.unpack_from("<BBHII", packet)
    if magic != P2P_MAGIC or flags not in (P2P_SHORT_PACKET, P2P_LONG_PACKET):
        raise ValueError("invalid camera command packet header")
    if packet_type != P2P_COMMAND_PACKET:
        raise ValueError("unexpected camera P2P packet type")
    command, payload = decrypt_command(packet[12:])
    return command, timestamp, sequence, payload
