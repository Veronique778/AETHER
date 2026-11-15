"""Real SQLite and both HTTP surfaces; no FakeStorage or fixture provider."""
from test_api_security_15 import client, register

def test_science_auth_and_gate_on_both_servers(client):
    a,t=register(client,'alice');b,v=register(client,'bob')
    assert client('GET','/api/signals')[0]==401
    assert client('GET','/api/signals',token=t)[0]==200
    aid=a['user']['astronaut_id'];bid=b['user']['astronaut_id']
    code,res=client('POST','/api/phantom-analyses',{'astronaut_id':aid,'from':'2026-11-01T00:00:00Z','to':'2026-11-01T01:00:00Z'},t)
    assert code==201 and res['outcome']=='insufficient_data'
    assert client('POST','/api/phantom-analyses',{'astronaut_id':bid,'from':'2026-11-01T00:00:00Z','to':'2026-11-01T01:00:00Z'},t)[0]==404
    assert client('GET','/api/phantom-analyses',token=t)[1]['items'][0]['analysis_id']==res['analysis_id']
