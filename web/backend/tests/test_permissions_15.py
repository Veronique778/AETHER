import pytest
from app import db
from app.persistence import repository as repo, missions
from app.persistence.common import APIError,uid,utcnow
from app.schemas_15 import HistoryQuery
from helpers_be2_15 import account,measurement

@pytest.fixture(autouse=True)
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'permissions.db'); db.init_db()


def assert_hidden(fn,*args):
    with pytest.raises(APIError) as e: fn(*args)
    assert e.value.status==404


def test_owner_isolation_on_read_write_device_and_session():
    a,_,_=account('alice'); b,_,_=account('bob')
    r=repo.add_measurements(a,[measurement()])[0]['measurement']
    assert_hidden(repo.get_measurement,b,r['id'])
    assert_hidden(repo.list_measurements,b,HistoryQuery(astronaut_id=a['astronaut_id']))
    assert_hidden(repo.aggregates,b,HistoryQuery(astronaut_id=a['astronaut_id']))
    assert_hidden(repo.export_measurements,b,HistoryQuery(astronaut_id=a['astronaut_id']))
    assert_hidden(repo.add_measurements,b,[measurement('attack',astronaut_id=a['astronaut_id'])])
    d=repo.create_device(a,{'name':'Band','kind':'ble'})
    assert_hidden(repo.device_sessions,b,d['id'],HistoryQuery())
    assert_hidden(repo.create_session,b,{'device_id':d['id'],'source':'Band','origin':'real','started_at':'2026-01-01T00:00:00Z'})
    assert_hidden(repo.add_measurements,b,[measurement('edit',supersedes_id=r['id'])])


def setup_crew():
    a,_,_=account('alice'); med,_,_=account('medic'); admin,_,_=account('admin')
    with db.connect() as c: c.execute("UPDATE users SET role='administrator' WHERE id=?",(admin['id'],))
    admin['role']='administrator'
    mission=missions.create_mission(admin,{'name':'Alpha'})['id']
    for u,role in [(a,'astronaut'),(med,'medical_officer')]: missions.membership(admin,mission,{'user_id':u['id'],'role':role})
    return a,med,admin,mission


def test_medical_assignment_is_explicit_mission_scoped_and_read_only():
    a,med,admin,mid=setup_crew()
    in_mission=repo.add_measurements(a,[measurement('mission',mission_id=mid)])[0]['measurement']
    private=repo.add_measurements(a,[measurement('private')])[0]['measurement']
    assert_hidden(repo.get_measurement,med,in_mission['id'])
    missions.grant(admin,mid,{'officer_id':med['id'],'astronaut_id':a['astronaut_id'],'can_review':False})
    assert repo.get_measurement(med,in_mission['id'])['id']==in_mission['id']
    assert_hidden(repo.get_measurement,med,private['id'])
    assert_hidden(repo.list_measurements,med,HistoryQuery(astronaut_id=a['astronaut_id']))
    result=repo.list_measurements(med,HistoryQuery(astronaut_id=a['astronaut_id'],mission_id=mid))
    assert len(result['items'])==1
    assert_hidden(repo.add_measurements,med,[measurement('write',astronaut_id=a['astronaut_id'],mission_id=mid)])
    missions.revoke(admin,mid,med['id'],a['astronaut_id'])
    assert_hidden(repo.get_measurement,med,in_mission['id'])


def test_admin_has_no_automatic_medical_access_and_astronaut_cannot_administer():
    a,med,admin,mid=setup_crew()
    r=repo.add_measurements(a,[measurement(mission_id=mid)])[0]['measurement']
    assert_hidden(repo.get_measurement,admin,r['id'])
    assert_hidden(repo.aggregates,admin,HistoryQuery(astronaut_id=a['astronaut_id'],mission_id=mid))
    with pytest.raises(APIError) as e: missions.create_mission(a,{'name':'Unauthorized'})
    assert e.value.status==403
    assert len(missions.crew(admin,mid)['items'])==2


def test_review_permission_and_membership_removal():
    a,med,admin,mid=setup_crew(); alert=uid()
    with db.connect() as c:
        c.execute('INSERT INTO alerts(id,astronaut_id,mission_id,severity,message,created_at) VALUES(?,?,?,?,?,?)',(alert,a['astronaut_id'],mid,'warning','Review requested',utcnow()))
    missions.grant(admin,mid,{'officer_id':med['id'],'astronaut_id':a['astronaut_id'],'can_review':False})
    assert_hidden(repo.review_alert,med,alert,'confirmed')
    missions.grant(admin,mid,{'officer_id':med['id'],'astronaut_id':a['astronaut_id'],'can_review':True})
    assert repo.review_alert(med,alert,'confirmed')['status']=='confirmed'
    with pytest.raises(APIError) as e: repo.review_alert(med,alert,'rejected')
    assert e.value.status==409
    missions.remove_member(admin,mid,med['id'])
    assert_hidden(repo.list_records,med,HistoryQuery(astronaut_id=a['astronaut_id'],mission_id=mid),'alerts')


def test_history_recovery_analysis_do_not_leak():
    a,_,_=account('alice'); b,_,_=account('bob')
    sid=repo.create_session(a,{'source':'manual','origin':'manual','started_at':'2026-01-01T00:00:00Z'})['id']
    run=repo.run_summary(a,{'session_id':sid,'idempotency_key':'r'})
    assert_hidden(repo.get_analysis,b,run['id'])
    assert_hidden(repo.run_summary,b,{'session_id':sid,'idempotency_key':'r'})
    assert_hidden(repo.list_records,b,HistoryQuery(astronaut_id=a['astronaut_id']),'recovery_sessions')
    assert_hidden(repo.create_recovery,b,{'astronaut_id':a['astronaut_id']})


def test_demo_profile_cannot_be_claimed_by_real_account():
    a,_,_=account()
    assert_hidden(repo.add_measurements,a,[measurement(astronaut_id='A01')])
    with pytest.raises(APIError): missions.membership(a,'x',{'user_id':a['id'],'role':'medical_officer'})
