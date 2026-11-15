"""AETHER 1.4 NASA OSDR: classification, provenance, missing values, timepoints, formats,
network failure, corrupted files, offline import, PHANTOM eligibility."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from app import db, nasa_research as nasa

FIX = Path(__file__).parent / 'fixtures'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import osdr_fixture_server  # noqa: E402

CSV = osdr_fixture_server.CSV_NAME


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'n.sqlite3')
    monkeypatch.setattr(nasa, 'IMPORT_HISTORY', tmp_path / 'imports.json')
    monkeypatch.setattr(nasa, 'CACHE', tmp_path / 'cache.json')
    return tmp_path


@pytest.fixture
def mirror(isolated, monkeypatch):
    srv = osdr_fixture_server.start(0)
    monkeypatch.setattr(nasa, 'TEST_MIRROR', f'http://127.0.0.1:{srv.server_port}')
    yield srv
    srv.shutdown(); srv.server_close()


@pytest.mark.parametrize('meta,evidence,layer', [
    ({'organism': 'Homo sapiens', 'Material Type': 'Serum', 'Study Assay Measurement Type': 'Comprehensive Metabolic Panel'}, 'human_in_vivo', 'clinical_physiological'),
    ({'organism': 'Homo sapiens', 'Material Type': 'Peripheral Blood Mononuclear Cell', 'Study Assay Measurement Type': 'transcription profiling'}, 'human_in_vivo', 'molecular'),
    ({'organism': 'Homo sapiens', 'Material Type': 'HUVEC cell line', 'Study Assay Measurement Type': 'RNA-seq'}, 'human_cell_culture', 'molecular'),
    ({'organism': 'Mus musculus', 'Material Type': 'Blood serum', 'Study Assay Measurement Type': 'clinical chemistry'}, 'animal', 'clinical_physiological'),
    ({'organism': 'Rattus norvegicus'}, 'animal', 'unclassified'),
    ({'organism': 'Microbiota', 'Study Assay Measurement Type': 'Metagenomic sequencing'}, 'microbial', 'molecular'),
    ({'organism': 'Arabidopsis thaliana'}, 'plant', 'unclassified'),
    ({'organism': 'Homo sapiens; Mus musculus'}, 'animal', 'unclassified'),
    ({}, 'unclassified', 'unclassified'),
])
def test_classification_never_defaults_to_human(meta, evidence, layer):
    c = nasa.classify(meta)
    assert (c['evidence_class'], c['data_layer']) == (evidence, layer)


def test_only_verified_human_clinical_is_phantom_eligible():
    base = {'source_type': 'verified_public_nasa_osdr_csv', 'evidence_class': 'human_in_vivo', 'data_layer': 'clinical_physiological'}
    assert nasa.phantom_eligibility(base)['eligible']
    for change in ({'evidence_class': 'animal'}, {'evidence_class': 'human_cell_culture'}, {'data_layer': 'molecular'},
                   {'source_type': 'user_supplied_file_unverified'}, {'source_type': 'test_fixture_mirror_not_nasa'}):
        assert not nasa.phantom_eligibility({**base, **change})['eligible'], change


@pytest.mark.parametrize('label,token,phase,offset', [('C001_serum_L-92', 'L-92', 'pre-flight', -92),
                                                     ('C004 R+194', 'R+194', 'post-flight', 194),
                                                     ('FD2_sample', 'FD2', 'in-flight', 2), ('L3', 'L-3', 'pre-flight', -3)])
def test_timepoint_tokens(label, token, phase, offset):
    tp = nasa.timepoint(label)
    assert (tp['token'], tp['phase'], tp['day_offset']) == (token, phase, offset)


@pytest.mark.parametrize('label', ['', 'baseline', 'URL-5', 'CALL-3x', 'sample_17'])
def test_no_timepoint_is_guessed(label):
    assert nasa.timepoint(label) is None


def test_missing_censored_units_and_groups():
    text = (FIX / 'synthetic_cmp_structure_fixture.csv').read_text()
    s = nasa.summarize_csv(text, 'Sodium (mmol/L)', 'Sample Name')
    assert s['unit'] == 'mmol/L'
    assert s['missing_values']['non_numeric_or_censored'] == 1 and '<130' in s['missing_values']['non_numeric_examples']
    assert s['missing_values']['missing_tokens'] == 1  # the formula row has an empty cell
    assert s['count'] == 23
    groups = {g['token']: g for g in s['timepoints']['groups']}
    assert set(groups) == {'L-92', 'L-44', 'L-3', 'R+1', 'R+45', 'R+82'}
    assert groups['L-44']['count'] == 3 and groups['R+1']['count'] == 4
    assert [g['phase'] for g in s['timepoints']['groups']][:3] == ['pre-flight'] * 3
    assert s['timepoints']['subjects_detected'] == ['C001', 'C002', 'C003', 'C004']
    g = nasa.summarize_csv(text, 'Glucose (mg/dL)')
    assert g['missing_values']['missing_tokens'] == 2 and g['unit'] == 'mg/dL'
    assert nasa.summarize_csv('a\n1\n', 'a')['unit'].startswith('not stated')


def test_file_formats_are_explicit():
    assert nasa.file_format('x.csv')['supported'] and nasa.file_format('x.TSV')['supported']
    for name in ('x.xlsx', 'meta.zip', 'reads.fastq', 'blob'):
        f = nasa.file_format(name)
        assert not f['supported'] and f['parser']


def test_real_http_path_against_fixture_mirror_is_labelled_not_nasa(mirror):
    listing = nasa.files(575)
    assert len(listing['files']) == 9
    by = {f['name']: f for f in listing['files']}
    assert by['LSDS-8_Multiplex_serum.immune.AlamarPanel_SUBMITTED.xlsx']['supported'] is False
    assert all(f['download_url'].startswith(nasa.TEST_MIRROR) for f in listing['files'])
    head = nasa.verified_csv(575, CSV)
    assert 'Sodium (mmol/L)' in head['numeric_columns'] and 'Comment' not in head['numeric_columns']
    r = nasa.verified_csv(575, CSV, 'Sodium (mmol/L)', 'Sample Name')
    p = r['provenance']
    assert p['source_type'] == 'test_fixture_mirror_not_nasa' and 'NOT NASA' in p['source_label']
    assert p['sha256'] == hashlib.sha256((FIX / 'synthetic_cmp_structure_fixture.csv').read_bytes()).hexdigest()
    assert p['size_matches_catalog'] is True
    assert p['organism'] == 'Homo sapiens' and p['evidence_class'] == 'human_in_vivo'
    assert p['data_layer'] == 'clinical_physiological' and p['study_title']
    assert r['phantom_reference']['eligible'] is False  # fixture mirror is never eligible
    assert any('no unit conversion' in step for step in r['preprocessing'])
    saved = nasa.imports()['imports']
    assert len(saved) == 1 and saved[0]['import_id'] == r['import_id'] and saved[0]['unit'] == 'mmol/L'
    assert nasa.reference_context()['count'] == 0


def test_mirror_corrupted_redirected_and_unlisted_files(mirror):
    with pytest.raises(ValueError, match='UTF-8'):
        nasa.verified_csv(575, osdr_fixture_server.NON_UTF8_NAME)
    with pytest.raises(ValueError, match='redirected'):
        nasa.verified_csv(575, osdr_fixture_server.REDIRECT_NAME)
    with pytest.raises(ValueError, match='Only CSV/TSV'):
        nasa.verified_csv(575, 'LSDS-8_Multiplex_serum.immune.AlamarPanel_SUBMITTED.xlsx')
    with pytest.raises(ValueError, match='not uniquely listed'):
        nasa.verified_csv(575, 'invented.csv')
    assert nasa.imports()['imports'] == []


def test_network_failure_is_reported_never_replaced(isolated, monkeypatch):
    def offline(path):
        raise OSError('proxy refused')
    monkeypatch.setattr(nasa, '_get_json', offline)
    with pytest.raises(OSError):
        nasa.verified_csv(575, CSV, 'x')
    r = nasa.catalog('inspiration4', refresh=True)
    assert r['available'] is False and r['studies'] == [] and 'proxy refused' in r['error']
    assert nasa.study_metadata(575)['available'] is False
    assert nasa.imports()['imports'] == []


def test_catalog_cache_is_per_query_and_survives_corruption(isolated, monkeypatch):
    payload = json.loads((FIX / 'osdr_search_hits.json').read_text())
    monkeypatch.setattr(nasa, '_get_json', lambda path: payload)
    a = nasa.catalog('inspiration4', refresh=True)
    assert [s['accession'] for s in a['studies']] == ['OSD-575', 'OSD-48', 'OSD-572']
    assert a['studies'][1]['evidence_class'] == 'animal'
    assert a['studies'][0]['official_url'] == 'https://osdr.nasa.gov/bio/repo/data/studies/OSD-575'
    nasa.catalog('mouse', refresh=True)
    monkeypatch.setattr(nasa, '_get_json', lambda path: (_ for _ in ()).throw(OSError('offline')))
    cached = nasa.catalog('inspiration4', refresh=True)
    assert cached['cached'] and 'unreachable' in cached['warning'] and cached['studies'] == a['studies']
    nasa.CACHE.write_text('{corrupt')
    assert nasa.catalog('inspiration4', refresh=False)['available'] is False


def test_1_3_cache_format_is_migrated(isolated):
    nasa.CACHE.write_text(json.dumps({'query': 'old', 'studies': [{'accession': 'OSD-1', 'title': 'x'}], 'available': True}))
    assert nasa.catalog('old')['studies'][0]['accession'] == 'OSD-1'


def test_offline_user_file_is_unverified_and_matches_hash(isolated, monkeypatch):
    text = (FIX / 'synthetic_cmp_structure_fixture.csv').read_text()
    r = nasa.local_csv(575, 'C:\\Users\\me\\Downloads\\cmp.csv', text, 'Glucose (mg/dL)', 'Sample Name')
    assert r['provenance']['source_type'] == 'user_supplied_file_unverified'
    assert r['provenance']['filename'] == 'cmp.csv' or r['provenance']['filename'].endswith('cmp.csv')
    assert r['phantom_reference']['eligible'] is False
    assert r['provenance']['matches_previous_verified_download'] is False
    digest = hashlib.sha256(text.encode()).hexdigest()
    hist = json.loads(nasa.IMPORT_HISTORY.read_text())
    hist.append({'sha256': digest, 'source_type': 'verified_public_nasa_osdr_csv', 'study': 'OSD-575', 'column': 'z',
                 'evidence_class': 'human_in_vivo', 'data_layer': 'clinical_physiological', 'organism': 'Homo sapiens'})
    nasa.IMPORT_HISTORY.write_text(json.dumps(hist))
    again = nasa.local_csv(575, 'cmp.csv', text, 'Sodium (mmol/L)')
    assert again['provenance']['matches_previous_verified_download'] is True
    assert again['phantom_reference']['eligible'] is False  # still user-supplied
    for bad in [(575, 'a.xlsx', text), (575, 'a.csv', ''), (0, 'a.csv', text), (575, 'a.csv', 'x' * 3_000_001)]:
        with pytest.raises(ValueError):
            nasa.local_csv(*bad)


def test_reference_context_lists_only_eligible(isolated):
    good = {'sha256': 'a' * 64, 'study': 'OSD-575', 'column': 'Glucose (mg/dL)', 'source_type': 'verified_public_nasa_osdr_csv',
            'evidence_class': 'human_in_vivo', 'data_layer': 'clinical_physiological'}
    mouse = {**good, 'sha256': 'b' * 64, 'study': 'OSD-48', 'evidence_class': 'animal'}
    nasa.IMPORT_HISTORY.write_text(json.dumps([good, mouse]))
    ctx = nasa.reference_context()
    assert ctx['count'] == 1 and ctx['references'][0]['study'] == 'OSD-575'
    assert 'not used to calibrate' in ctx['policy']


def test_corrupt_history_file_does_not_crash(isolated):
    nasa.IMPORT_HISTORY.write_text('not json')
    assert nasa.imports()['imports'] == []
    nasa.IMPORT_HISTORY.write_text(json.dumps([1, 'x', {'sha256': 'c' * 64, 'study': 'OSD-1', 'column': 'v'}]))
    assert len(nasa.imports()['imports']) == 1


def test_untrusted_urls_still_rejected_without_mirror():
    assert nasa.TEST_MIRROR == ''
    for unsafe in ['https://example.com/a.csv', 'http://osdr.nasa.gov/a.csv', 'https://osdr.nasa.gov.evil/a',
                   '//osdr.nasa.gov/a', 'https://user@osdr.nasa.gov/a', '/a\\b', 'https://osdr.nasa.gov:444/a']:
        assert nasa._nasa_file_url(unsafe) is None, unsafe
