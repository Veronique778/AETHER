"""Bluetooth SIG Heart Rate Service — Heart Rate Measurement characteristic (0x2A37) decoder (AETHER 1.5, Backend №3).

Layout (little-endian), as described for the HRS Heart Rate Measurement characteristic:
    byte 0  flags
        bit 0      HR value format: 0 = uint8, 1 = uint16
        bits 1–2   sensor contact status: bit 2 = "contact feature supported", bit 1 = "contact detected"
                   (bit 1 is meaningful only when bit 2 is set)
        bit 3      Energy Expended field present (uint16, kilojoules)
        bit 4      one or more RR-interval fields present (uint16 each, resolution 1/1024 s)
        bits 5–7   reserved for future use
    then: HR (1 or 2 bytes) · [Energy Expended (2)] · [RR (2) × n]

Strictness (no silent repair): a packet that is shorter than its flags require, has an odd number of RR bytes, has RR
flagged but no RR bytes, or carries trailing bytes when RR is not flagged is rejected as CorruptedData. Reserved bits
are reported (`reserved_bits_set`) but do not invalidate the packet. All RR values of one notification are returned in
order; none is merged or dropped. RR ms = raw × 1000 / 1024 (exact rational conversion, reported unrounded).
An HR value of 0 is returned as 0 (devices use it when no beat is detected); the registry marks it out_of_range.
The decoder knows nothing about astronauts, sessions or time — see manager.py.

Reference: Bluetooth SIG Heart Rate Service / GATT characteristic description (not re-verified online in this session).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..science_errors import CorruptedData

HRS_SERVICE_UUID = '0000180d-0000-1000-8000-00805f9b34fb'
HRM_CHAR_UUID = '00002a37-0000-1000-8000-00805f9b34fb'
RR_RESOLUTION_MS = 1000 / 1024
FLAG_HR_UINT16, FLAG_CONTACT_DETECTED, FLAG_CONTACT_SUPPORTED, FLAG_ENERGY, FLAG_RR = 0x01, 0x02, 0x04, 0x08, 0x10
RESERVED_MASK = 0xE0
MAX_PACKET = 64            # ATT payloads larger than this are not plausible for 0x2A37


@dataclass(frozen=True)
class HeartRateMeasurement:
    flags: int
    heart_rate_bpm: int
    hr_format: str                     # 'uint8' | 'uint16'
    contact_supported: bool
    contact: bool | None               # None = the device does not report contact
    energy_expended_kj: int | None
    rr_raw_1024: tuple[int, ...] = field(default_factory=tuple)
    reserved_bits_set: bool = False

    @property
    def rr_ms(self) -> list[float]:
        return [r * RR_RESOLUTION_MS for r in self.rr_raw_1024]


def decode(packet: bytes | bytearray | memoryview) -> HeartRateMeasurement:
    if not isinstance(packet, (bytes, bytearray, memoryview)):
        raise CorruptedData('HRS notification must be bytes')
    b = bytes(packet)
    if len(b) < 2:
        raise CorruptedData(f'Truncated HRS notification ({len(b)} bytes)')
    if len(b) > MAX_PACKET:
        raise CorruptedData(f'HRS notification too long ({len(b)} bytes)')
    flags = b[0]
    pos = 1

    def take(width: int, what: str) -> int:
        nonlocal pos
        if pos + width > len(b):
            raise CorruptedData(f'Truncated HRS field: {what}')
        v = int.from_bytes(b[pos:pos + width], 'little')
        pos += width
        return v

    uint16 = bool(flags & FLAG_HR_UINT16)
    hr = take(2 if uint16 else 1, 'heart rate')
    supported = bool(flags & FLAG_CONTACT_SUPPORTED)
    contact = bool(flags & FLAG_CONTACT_DETECTED) if supported else None
    energy = take(2, 'energy expended') if flags & FLAG_ENERGY else None
    rr: list[int] = []
    if flags & FLAG_RR:
        rest = len(b) - pos
        if rest == 0:
            raise CorruptedData('RR flag set but no RR interval present')
        if rest % 2:
            raise CorruptedData('Malformed RR intervals (odd number of bytes)')
        while pos < len(b):
            rr.append(take(2, 'rr interval'))
    elif pos != len(b):
        raise CorruptedData(f'Unexpected {len(b) - pos} trailing byte(s) in HRS notification')
    return HeartRateMeasurement(flags=flags, heart_rate_bpm=hr, hr_format='uint16' if uint16 else 'uint8',
                                contact_supported=supported, contact=contact, energy_expended_kj=energy,
                                rr_raw_1024=tuple(rr), reserved_bits_set=bool(flags & RESERVED_MASK))


def encode(hr: int, rr_raw_1024: list[int] | tuple[int, ...] = (), contact: bool | None = None, *, uint16: bool = False,
           energy_kj: int | None = None, reserved: int = 0) -> bytes:
    """Test/simulation helper producing a well-formed 0x2A37 payload (used only by mocks and the hardware procedure)."""
    flags = (FLAG_HR_UINT16 if uint16 else 0) | (reserved & RESERVED_MASK)
    if contact is not None:
        flags |= FLAG_CONTACT_SUPPORTED | (FLAG_CONTACT_DETECTED if contact else 0)
    if energy_kj is not None:
        flags |= FLAG_ENERGY
    if rr_raw_1024:
        flags |= FLAG_RR
    out = bytes([flags]) + int(hr).to_bytes(2 if uint16 else 1, 'little')
    if energy_kj is not None:
        out += int(energy_kj).to_bytes(2, 'little')
    for r in rr_raw_1024:
        out += int(r).to_bytes(2, 'little')
    return out
