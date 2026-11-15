"""AETHER 1.0 · B9: RECOVERY backend – history persistence, API validation, simulated biofeedback is labelled."""
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import db, service
from app.schemas import RecoverySession


@pytest.fixture()
def temp_db():
    prev = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 'r.sqlite3'; db.init_db()
        try:
            yield
        finally:
            db.DB_PATH = prev


def test_history_is_personal_ordered_and_persistent(temp_db):
    for i, (who, act) in enumerate([('A01', 'zero-g-garden'), ('A02', 'earth-window'), ('A01', 'mind-pulse')]):
        service.save_recovery(RecoverySession(astronaut_id=who, activity=act, before_mood=4, after_mood=5 + i, duration_seconds=60,
                                              details={'breaths': 6}))
    a01 = service.get_recovery('A01')
    assert [r['activity'] for r in a01] == ['mind-pulse', 'zero-g-garden']        # newest first, only this person
    assert a01[0]['details'] == {'breaths': 6} and a01[0]['after_mood'] == 7
    with pytest.raises(service.NotFound):
        service.get_recovery('X99')


def test_session_validation():
    for bad in ({'activity': 'zero-g-garden', 'before_mood': 0, 'after_mood': 5, 'duration_seconds': 1},
                {'activity': 'cure', 'before_mood': 3, 'after_mood': 5, 'duration_seconds': 1},
                {'activity': 'zero-g-garden', 'before_mood': 3, 'after_mood': 5, 'duration_seconds': -1}):
        with pytest.raises(ValidationError):
            RecoverySession(**bad)


def test_biofeedback_is_labelled_simulated_and_makes_no_medical_claim(temp_db):
    b = service.biofeedback('A01')
    assert b['source'] == 'simulated'
    assert 30 < b['heart_rate_bpm'] < 200 and 0 <= b['coherence_0_1'] <= 1
    assert not any(k in b for k in ('diagnosis', 'treatment', 'therapy'))
