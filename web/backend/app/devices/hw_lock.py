"""Process-wide lock on PHYSICAL Bluetooth devices (hardware address), shared by the 1.5 Device Manager and the
legacy 1.4 global sensor (app.ble_sensor). One physical strap can be opened by only one owner at a time, even if it is
registered twice (Backend №2 allows the same external_id for two astronauts) or used through the legacy path.

Scope: one AETHER process. Two AETHER processes on one computer are not coordinated (the OS BLE stack then refuses the
second connection) — documented limitation.
"""
from __future__ import annotations

import threading

from ..science_errors import DeviceBusy

_LOCK = threading.Lock()
_HELD: dict[str, str] = {}


def _norm(address: str) -> str:
    return (address or '').strip().upper()


def acquire(address: str, owner: str) -> None:
    key = _norm(address)
    with _LOCK:
        holder = _HELD.get(key)
        if holder is not None and holder != owner:
            raise DeviceBusy('This physical Bluetooth device is already in use by another session or by the legacy '
                             'sensor path', code='device_busy')
        _HELD[key] = owner


def release(address: str, owner: str) -> None:
    key = _norm(address)
    with _LOCK:
        if _HELD.get(key) == owner:
            del _HELD[key]


def holder(address: str) -> str | None:
    with _LOCK:
        return _HELD.get(_norm(address))


def _reset_for_tests() -> None:
    with _LOCK:
        _HELD.clear()
