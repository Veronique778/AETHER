"""AETHER 1.5 — Bluetooth SIG Heart Rate Measurement (0x2A37) decoder, app/devices/hrs.py.
Packets are hand-written byte strings (not only round-trips) so the byte layout itself is checked."""
import pytest

from app.ble_sensor import decode as legacy_decode
from app.devices.hrs import RR_RESOLUTION_MS, decode, encode
from app.science_errors import CorruptedData


def test_uint8_heart_rate_no_contact_feature():
    m = decode(bytes([0x00, 72]))
    assert (m.heart_rate_bpm, m.hr_format, m.contact_supported, m.contact, m.rr_raw_1024) == (72, 'uint8', False, None, ())


def test_uint16_heart_rate():
    m = decode(bytes([0x01, 0x2C, 0x01]))                # 0x012C = 300
    assert m.heart_rate_bpm == 300 and m.hr_format == 'uint16'


@pytest.mark.parametrize('flags,expect', [(0x00, (False, None)), (0x02, (False, None)), (0x04, (True, False)), (0x06, (True, True))])
def test_contact_status_bits(flags, expect):
    m = decode(bytes([flags, 60]))
    assert (m.contact_supported, m.contact) == expect      # bit 1 alone (0x02) is meaningless without bit 2


def test_single_rr_exact_conversion():
    m = decode(bytes([0x16, 60, 0x00, 0x04]))             # contact detected + RR; raw 1024 = exactly 1000 ms
    assert m.contact is True and m.rr_raw_1024 == (1024,) and m.rr_ms == [1000.0]


def test_several_rr_in_one_notification_kept_in_order():
    m = decode(bytes([0x10, 70, 0x00, 0x03, 0x10, 0x03, 0x20, 0x03]))   # 768, 784, 800
    assert m.rr_raw_1024 == (768, 784, 800)
    assert m.rr_ms == [768 * RR_RESOLUTION_MS, 784 * RR_RESOLUTION_MS, 800 * RR_RESOLUTION_MS]


def test_energy_then_rr():
    m = decode(bytes([0x18, 80, 0x34, 0x12, 0x00, 0x04]))  # energy 0x1234 = 4660 kJ, RR 1024
    assert m.energy_expended_kj == 4660 and m.rr_raw_1024 == (1024,)


def test_uint16_energy_and_rr_all_fields():
    m = decode(encode(301, (500, 600), True, uint16=True, energy_kj=12))
    assert (m.heart_rate_bpm, m.energy_expended_kj, m.rr_raw_1024, m.contact) == (301, 12, (500, 600), True)


def test_reserved_bits_reported_not_fatal():
    m = decode(bytes([0xE0, 65]))
    assert m.reserved_bits_set and m.heart_rate_bpm == 65


def test_zero_heart_rate_is_returned_as_is():
    assert decode(bytes([0x00, 0])).heart_rate_bpm == 0


@pytest.mark.parametrize('packet,why', [
    (b'', 'Truncated'), (bytes([0x00]), 'Truncated'), (bytes([0x01, 0x48]), 'heart rate'),
    (bytes([0x08, 60, 0x01]), 'energy'), (bytes([0x10, 60]), 'no RR'), (bytes([0x10, 60, 0x00]), 'odd'),
    (bytes([0x10, 60, 0x00, 0x04, 0x01]), 'odd'), (bytes([0x00, 60, 0x99]), 'trailing'),
    (bytes([0x01]) + b'\x00' * 70, 'too long'),
])
def test_malformed_packets_rejected(packet, why):
    with pytest.raises(CorruptedData) as e:
        decode(packet)
    assert why.lower() in e.value.message.lower() and e.value.code == 'corrupted_data'


def test_non_bytes_rejected():
    with pytest.raises(CorruptedData):
        decode('0048')


@pytest.mark.parametrize('hr,rr,contact,uint16,energy', [(64, (), True, False, None), (182, (500, 512), None, False, None),
                                                       (301, (), False, True, None), (45, (1365,), True, True, 99),
                                                       (255, tuple(range(700, 708)), True, False, None)])
def test_encode_decode_round_trip_and_agreement_with_legacy_decoder(hr, rr, contact, uint16, energy):
    pkt = encode(hr, rr, contact, uint16=uint16, energy_kj=energy)
    m, old = decode(pkt), legacy_decode(pkt)
    assert (m.heart_rate_bpm, m.contact, m.rr_raw_1024, m.energy_expended_kj) == (hr, contact, rr, energy)
    assert old['heart_rate'] == hr and old['contact'] == contact and old['rr_ms'] == m.rr_ms
