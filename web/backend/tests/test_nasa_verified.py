"""NASA OSDR: provenance, local history, official URL boundary, API parity."""
import hashlib
import json
import pytest

from app import nasa_research as nasa


@pytest.fixture
def official_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(nasa, 'IMPORT_HISTORY', tmp_path / 'verified_imports.json')
    official_file = 'OSD-48_measurements.csv'
    url = 'https://osdr.nasa.gov/geode-py/ws/studies/OSD-48/download?file=OSD-48_measurements.csv'
    monkeypatch.setattr(nasa, 'files', lambda sid: {
        'study': f'OSD-{sid}', 'source': f'https://osdr.nasa.gov/osdr/data/osd/files/{sid}',
        'files': [{'name': official_file, 'restricted': False, 'download_url': url}]})
    payload = b'time,value\n1,67\n2,71\n3,79\n'
    monkeypatch.setattr(nasa, '_download_verified_csv', lambda x: payload)
    monkeypatch.setattr(nasa, 'study_metadata', lambda sid: {'accession': f'OSD-{sid}', 'available': False})
    return official_file, url, payload


def test_verified_nasa_file_is_cited_hashed_and_saved(official_catalog):
    filename, url, payload = official_catalog
    result = nasa.verified_csv(48, filename, 'value')
    assert result['summary']['count'] == 3
    assert result['summary']['mean'] == pytest.approx(72.33333)
    assert result['provenance']['source_type'] == 'verified_public_nasa_osdr_csv'
    assert result['provenance']['download_url'] == url
    assert result['provenance']['sha256'] == hashlib.sha256(payload).hexdigest()
    assert result['saved_to_local_history']
    assert nasa.imports()['imports'][0]['filename'] == filename
    nasa.verified_csv(48, filename, 'value')
    assert len(nasa.imports()['imports']) == 1


def test_verified_nasa_file_first_call_inspects_without_persisting(official_catalog):
    filename, _, _ = official_catalog
    result = nasa.verified_csv(48, filename)
    assert result['columns'] == ['time','value']
    assert len(result['preview']) == 3
    assert 'summary' not in result
    assert nasa.imports()['imports'] == []


def test_verified_nasa_rejects_non_catalog_files_and_non_csv(official_catalog):
    fn, _, _ = official_catalog
    for bad in ['something.csv','../../credentials.csv','dataset.pkl','']:
        with pytest.raises(ValueError): nasa.verified_csv(48, bad, 'value')
    with pytest.raises(ValueError): nasa.verified_csv(-2, fn, 'value')
    with pytest.raises(ValueError): nasa.verified_csv(48, fn, 'fake')


def test_verified_nasa_rejects_restricted_or_untrusted_url(official_catalog, monkeypatch):
    filename, _, _ = official_catalog
    monkeypatch.setattr(nasa, 'files', lambda sid: {'source': 'https://osdr.nasa.gov/', 'files': [
        {'name': filename, 'restricted': True, 'download_url': 'https://osdr.nasa.gov/data.csv'}]})
    with pytest.raises(ValueError, match='restricted'): nasa.verified_csv(48, filename, 'value')
    for unsafe in ['https://example.com/a.csv','https://osdr.nasa.gov.attacker.tld/a.csv',
                   'http://osdr.nasa.gov/a.csv', 'file:///tmp/test.csv', '//localhost/a.csv']:
        assert nasa._nasa_file_url(unsafe) is None


def test_verified_download_rejects_nasa_redirects(monkeypatch):
    class Redirect:
        def __init__(self):self.handlers=[]
        def open(self, request, timeout):
            return self.handlers[0].redirect_request(request, None, 302, 'Found', {}, 'http://127.0.0.1:8080/private')
    fake=Redirect()
    monkeypatch.setattr(nasa.urllib.request, 'build_opener', lambda handler: (setattr(fake, 'handlers', [handler]) or fake))
    with pytest.raises(ValueError, match='redirected'):
        nasa._download_verified_csv('https://osdr.nasa.gov/test.csv')
