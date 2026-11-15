"""BLE device lifecycle (AETHER 1.5, Backend №3) — states, allowed transitions, mapping to the contract `connection` field.

    DISCONNECTED → SCANNING → DISCONNECTED
    DISCONNECTED → CONNECTING → CONNECTED → RECORDING → DISCONNECTING → DISCONNECTED
    RECORDING → RECONNECTING → RECORDING            (link lost, reconnected into the SAME session)
    RECONNECTING → DISCONNECTING → DISCONNECTED    (all attempts failed / user stop; data stored up to the loss)
    CONNECTING → CONNECTION_FAILED → DISCONNECTED   (timeout, no HRS, refused)
    any → UNAVAILABLE                               (no BLE stack / adapter); UNAVAILABLE → DISCONNECTED on recovery

DEVICE_BUSY is not a state: it is the refusal (409) of a request that would put a busy device into a second session.
SENSOR_NO_CONTACT is not a state either: it is `contact_state = 'no_contact'` while RECORDING (the link is alive, the
sensor reports no skin contact; such samples are stored as quality 'no_contact', never as valid values).
"""
from __future__ import annotations

from enum import Enum

from ..science_errors import Conflict


class State(str, Enum):
    DISCONNECTED = 'disconnected'
    SCANNING = 'scanning'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECORDING = 'recording'
    DISCONNECTING = 'disconnecting'
    RECONNECTING = 'reconnecting'
    UNAVAILABLE = 'unavailable'
    CONNECTION_FAILED = 'connection_failed'


S = State
ALLOWED: dict[State, set[State]] = {
    S.DISCONNECTED: {S.SCANNING, S.CONNECTING, S.UNAVAILABLE},
    S.SCANNING: {S.DISCONNECTED, S.UNAVAILABLE},
    S.CONNECTING: {S.CONNECTED, S.CONNECTION_FAILED, S.DISCONNECTING, S.UNAVAILABLE},
    S.CONNECTED: {S.RECORDING, S.DISCONNECTING, S.RECONNECTING, S.UNAVAILABLE},
    S.RECORDING: {S.DISCONNECTING, S.RECONNECTING, S.UNAVAILABLE},
    S.RECONNECTING: {S.RECORDING, S.DISCONNECTING, S.UNAVAILABLE},
    S.DISCONNECTING: {S.DISCONNECTED},
    S.CONNECTION_FAILED: {S.DISCONNECTED},
    S.UNAVAILABLE: {S.DISCONNECTED},
}
ACTIVE = {S.CONNECTING, S.CONNECTED, S.RECORDING, S.RECONNECTING, S.DISCONNECTING}
CONTRACT_CONNECTION = {   # API Contract 1.5 §3.6 `connection` values
    S.DISCONNECTED: 'disconnected', S.SCANNING: 'scanning', S.CONNECTING: 'connecting', S.CONNECTED: 'connected',
    S.RECORDING: 'connected', S.DISCONNECTING: 'connected', S.RECONNECTING: 'reconnecting',
    S.UNAVAILABLE: 'unavailable', S.CONNECTION_FAILED: 'disconnected',
}


def can(old: State, new: State) -> bool:
    return new in ALLOWED[old]


def check(old: State, new: State) -> State:
    if not can(old, new):
        raise Conflict(f'Forbidden device state transition {old.value} → {new.value}', code='conflict')
    return new
