"""AETHER 0.9 scientific core: evidence integrity, radiation physics bookkeeping, hazard graph behaviour."""
import re

import pytest

from app.science import evidence, hazards, radiation

LIB = evidence.by_id()

NASA_HRP_RISKS = {  # as listed on https://www.nasa.gov/hrp/risks/ (fetched 2026-11-14)
    'Risk of Altered Immune System Responses', 'Risk of Altered Sensorimotor and Vestibular Function', 'Risk of Cardiovascular Adaptations',
    'Risk of Decompression Sickness', 'Risk of Host-Microorganism Interactions', 'Risk of Hypoxia', 'Risk of Inadequate Food and Nutrition',
    'Risk of Injury and Compromised Performance from Spacewalks', 'Risk of Reduced Cardiorespiratory and Musculoskeletal Fitness',
    'Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)', 'Risk of Spaceflight-Induced Bone Changes',
    'Risk of Behavioral Changes and Psychiatric Disorders', 'Risk of Inadequate Teamwork', 'Risk of Inadequate Sleep and Irregular Schedules',
    'Risk of Inadequate Systems Operations Support', 'Risk of Injury from Dynamic Loads', 'Risk of Radiation-Induced Cancers',
}


def test_evidence_entries_are_complete_and_unique():
    ids = [e['id'] for e in evidence.EVIDENCE]
    assert len(ids) == len(set(ids)) >= 12
    for e in evidence.EVIDENCE:
        for k in ('title', 'authors', 'year', 'url', 'finding', 'limitation', 'hazards', 'verified_via'):
            assert e[k] not in (None, '', []), (e['id'], k)
        assert e['url'].startswith('https://')
        if e['doi']:
            assert re.fullmatch(r'10\.\d{4,9}/\S+', e['doi']) and e['url'].endswith(e['doi'])
        assert set(e['hazards']) <= {h['id'] for h in hazards.HAZARDS}


def test_every_cited_source_exists_in_the_library():
    cited = {s for h in hazards.HAZARDS for s in h['sources']}
    cited |= {s for r in hazards.HRP_RISKS for s in r[5]}
    cited |= {s for e in hazards.EDGES for s in e[3]}
    assert cited <= set(LIB), cited - set(LIB)


def test_hrp_risk_map_matches_nasa_list_exactly():
    assert {r[0] for r in hazards.HRP_RISKS} == NASA_HRP_RISKS
    assert {h['id'] for h in hazards.HAZARDS} == {'radiation', 'isolation', 'distance', 'gravity', 'environment'}
    # evidence-typed edges must cite a source; hypotheses must not pretend to
    for a, b, kind, src, note in hazards.EDGES:
        assert kind in hazards.TYPE_WEIGHT
        assert (kind != 'evidence') or src, (a, b)


@pytest.mark.parametrize('preset, expected', [
    ('iss_6_months', 182 * 0.731),
    ('mars_conjunction', 360 * 1.84 + 500 * 0.64),
])
def test_radiation_median_matches_analytic_dose(preset, expected):
    p = radiation.PRESETS[preset]
    r = radiation.simulate(p['segments'], p['spe'], runs=2000, seed=1)
    assert abs(r['final']['p50'] - expected) / expected < 0.03
    assert r['final']['p5'] < r['final']['p50'] < r['final']['p95']
    meds = [s['p50'] for s in r['series']]
    assert meds == sorted(meds)                       # cumulative dose never decreases


def test_radiation_spe_and_limits():
    seg = [{'environment': 'deep_space', 'days': 100}]
    base = radiation.simulate(seg, runs=500)
    spe = radiation.simulate(seg, [{'day': 10, 'dose_msv': 300}], runs=500)
    assert abs(spe['final']['p50'] - base['final']['p50'] - 300) < 5
    assert any(e['kind'] == 'solar_particle_event' and e['exceeds_spe_limit'] for e in spe['events'])
    assert 'cancer or other health risk' in base['not_modelled']
    assert base['limits']['career_msv'] == 600
    with pytest.raises(ValueError):
        radiation.simulate([{'environment': 'venus', 'days': 3}])
    with pytest.raises(ValueError):
        radiation.simulate(seg, [{'day': 500, 'dose_msv': 1}])


def test_hazard_graph_reacts_to_the_scenario():
    short = hazards.graph(hazards.MissionProfile(destination='iss', mission_days=30, co2_ppm=1000))
    long_ = hazards.graph(hazards.MissionProfile(destination='mars', mission_days=900, co2_ppm=4500))
    lv = lambda g, i: next(n['level'] for n in g['nodes'] if n['id'] == i)
    for h in ('radiation', 'isolation', 'distance', 'environment'):
        assert lv(long_, h) > lv(short, h), h
    assert short['summary'] != long_['summary']
    # a hypothesis edge can never make a node look more supported than an evidence edge from the same source
    for e in long_['edges']:
        assert e['strength'] <= hazards.TYPE_WEIGHT[e['type']] + 1e-9


def test_unreachable_sources_are_declared_not_cited():
    urls = {e['url'] for e in evidence.EVIDENCE}
    for u in evidence.UNREACHABLE:
        assert u['url'] not in urls


def test_frontend_metric_explanations_cite_library_sources():
    from pathlib import Path
    ts = (Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'lib' / 'metricScience.ts').read_text(encoding='utf-8')
    cited = {s for block in re.findall(r'sources: \[([^\]]*)\]', ts) for s in re.findall(r"'([^']+)'", block)}
    assert cited and cited <= set(LIB), cited - set(LIB)
    assert len(re.findall(r'sources: \[', ts)) == 5
