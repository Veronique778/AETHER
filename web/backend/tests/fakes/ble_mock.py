"""Deterministic BLE test doubles (Backend №3). FOR TESTS ONLY — never a substitute for hardware validation.

ManualClock / ManualScheduler drive time explicitly; MockTransport delivers scripted 0x2A37 packets and can inject link
loss, connection failures, an unavailable adapter and a missing bleak package. Packets are built with
app.devices.hrs.encode, i.e. exactly the byte layout the decoder parses.
"""
from __future__ import annotations

import heapq
import itertools
import threading
from datetime import datetime, timedelta, timezone

from app.devices import hrs


class ManualClock:
    def __init__(self, start=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)):
        self._t0 = start
        self._mono = 1000.0
        self.lock = threading.Lock()
        self.wall_offset = 0.0           # lets a test move the WALL clock backwards (clock regression)

    def now(self):
        with self.lock:
            return self._t0 + timedelta(seconds=self._mono - 1000.0 + self.wall_offset)

    def monotonic(self):
        with self.lock:
            return self._mono

    def advance(self, s):
        with self.lock:
            self._mono += s


class ManualScheduler:
    def __init__(self, clock: ManualClock):
        self.clock = clock
        self._q = []
        self._seq = itertools.count()
        self._cancelled = set()
        self.lock = threading.Lock()

    def call_later(self, delay, fn):
        h = next(self._seq)
        with self.lock:
            heapq.heappush(self._q, (self.clock.monotonic() + max(0.0, delay), h, fn))
        return h

    def cancel(self, handle):
        if handle is not None:
            self._cancelled.add(handle)

    def advance(self, seconds):
        """Move time forward, running due callbacks in time order (callbacks may schedule more)."""
        target = self.clock.monotonic() + seconds
        while True:
            with self.lock:
                if not self._q or self._q[0][0] > target:
                    break
                due, h, fn = heapq.heappop(self._q)
            if due > self.clock.monotonic():
                self.clock.advance(due - self.clock.monotonic())
            if h not in self._cancelled:
                fn()
        if target > self.clock.monotonic():
            self.clock.advance(target - self.clock.monotonic())

    def pending(self):
        return len([x for x in self._q if x[1] not in self._cancelled])


class Link:
    def __init__(self, transport, address, on_notify, on_disconnect):
        self.transport, self.address, self.on_notify, self.on_disconnect = transport, address, on_notify, on_disconnect
        self.alive = True

    def send(self, packet: bytes):
        if self.alive:
            self.on_notify(packet)

    def hr(self, bpm, rr_raw=(), contact=True, **kw):
        self.send(hrs.encode(bpm, rr_raw, contact, **kw))

    def drop(self, reason='link_lost'):
        """Simulates out-of-range / device off / battery empty: the stack reports a disconnection."""
        if self.alive:
            self.alive = False
            self.on_disconnect(reason)


class MockTransport:
    # Stands in for the PHYSICAL radio in Device-Manager unit tests (manager logic only). The shipped product path
    # without hardware is app.devices.simulated.SimulatedHrsTransport, whose rows are always 'synthetic'.
    DATA_CLASS = 'real_wearable'
    KIND = 'test_double_for_radio'

    def __init__(self):
        self.available, self.reason = True, None
        self.devices = {}                       # address → {'name', 'advertised_hrs'}
        self.fail_connects: dict[str, int] = {}  # address → number of next connects that fail
        self.never_connect: set[str] = set()
        self.links: list[Link] = []
        self.lock = threading.Lock()

    def add(self, address, name='Mock HRS strap', advertised=True):
        self.devices[address] = {'name': name, 'advertised_hrs': advertised}

    def availability(self):
        return (True, None) if self.available else (False, self.reason or 'Bluetooth adapter not found')

    def scan(self, include_unadvertised, timeout_s):
        return [{'hardware_address': a, 'name': d['name'], 'advertised_hrs': d['advertised_hrs']}
                for a, d in sorted(self.devices.items()) if d['advertised_hrs'] or include_unadvertised]

    def connect(self, address, on_notify, on_disconnect, timeout_s):
        with self.lock:
            if not self.available:
                raise OSError(self.reason or 'adapter unavailable')
            if address in self.never_connect or address not in self.devices:
                raise ConnectionError(f'{address} not reachable')
            if self.fail_connects.get(address, 0) > 0:
                self.fail_connects[address] -= 1
                raise TimeoutError(f'{address} connect timed out')
            link = Link(self, address, on_notify, on_disconnect)
            self.links.append(link)
            return link

    def disconnect(self, handle):
        handle.alive = False

    def link(self, address) -> Link:
        return [l for l in self.links if l.address == address and l.alive][-1]
