from app.nasa_research import summarize_csv, _summarize

def test_numeric_nasa_csv():
    r = summarize_csv('metric,other\n1,a\n2,b\n3,c\n', 'metric')
    assert r['count'] == 3 and r['mean'] == 2 and r['median'] == 2
    assert r['origin'] == 'imported_research_csv'

def test_missing_values_ignored():
    r = summarize_csv('metric\n1\nNA\n3\n', 'metric')
    assert r['count'] == 2 and r['mean'] == 2

def test_search_response():
    assert _summarize({'hits':[{'_source':{'Accession':'OSD-1','Study Title':'Test'}}]})[0]['accession'] == 'OSD-1'


def test_nested_osdr_search_and_deduplication():
    r = _summarize({'hits': {'hits': [
        {'_source': {'Accession': 'OSD-87', 'Study Title': 'Real sourced title'}},
        {'_source': {'Accession': 'OSD-87', 'Study Title': 'Duplicate'}},
        {'_source': {'Accession': 'OSD-137', 'Study Title': 'Another title'}},
    ]}})
    assert [x['accession'] for x in r] == ['OSD-87', 'OSD-137']


def test_untrusted_download_urls_cannot_be_presented_as_nasa():
    from app.nasa_research import _nasa_file_url
    assert _nasa_file_url('/geode-py/ws/studies/OSD-87/download?file=data.csv').startswith('https://osdr.nasa.gov/')
    assert _nasa_file_url('https://osdr.nasa.gov/example.csv') is not None
    for url in ['https://evil.example/file.csv', '//evil.example/file.csv',
                'https://osdr.nasa.gov.attacker.example/f.csv', 'javascript:alert(1)', '/\\\\evil']:
        assert _nasa_file_url(url) is None or url == '/\\\\evil'


def test_osdr_catalog_query_handles_offline_mode(monkeypatch, tmp_path):
    from app import nasa_research as nasa
    monkeypatch.setattr(nasa, 'CACHE', tmp_path/'catalog.json')
    def offline(path):
        raise OSError('offline')
    monkeypatch.setattr(nasa, '_get_json', offline)
    r = nasa.catalog('radiation', refresh=True)
    assert r['available'] is False and r['studies'] == []
    assert 'unreachable' in r['warning']


def test_catalog_uses_live_response_not_invented_studies(monkeypatch, tmp_path):
    from app import nasa_research as nasa
    monkeypatch.setattr(nasa, 'CACHE', tmp_path/'catalog.json')
    monkeypatch.setattr(nasa, '_get_json', lambda path: {'hits':{'hits':[{'_source':{'Accession':'OSD-87','Study Title':'Published research'}}]}})
    r = nasa.catalog('cardiovascular', refresh=True)
    assert r['available'] is True
    assert r['studies'] == [{'accession':'OSD-87','title':'Published research'}]
    assert nasa.catalog('cardiovascular', refresh=False)['cached'] is True
