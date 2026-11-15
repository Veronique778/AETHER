from app import db
from app.human_systems import summary

def test_quality_data():
    db.init_db()
    r = summary('A01', 67, 14)
    assert r['record_count'] == 14
    assert r['completeness'] == 1.0
    assert 'simulated' in r['sources']
    assert r['baselines']['sleep_hours']['median'] is not None

def test_missing_history():
    db.init_db()
    r = summary('A01', 2, 14)
    assert r['completeness'] < 0.2
    assert r['uncertainty']['data'] == 'high'
