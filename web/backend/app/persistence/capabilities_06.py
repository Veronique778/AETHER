"""Operational capabilities: routing/storage availability, never hardware claims from mocks."""
from app import db

def capabilities():
    healthy=False
    try:
        with db.connect() as c:
            c.execute('SELECT 1 FROM users LIMIT 1');c.execute('SELECT 1 FROM analysis_evidence LIMIT 1')
        healthy=True
    except Exception:pass
    try:
        from app import science_storage,api15_science
        from .science_adapter_06 import CanonicalScienceStorage
        resolved=science_storage.resolve()
        protocol=isinstance(resolved,CanonicalScienceStorage) and not science_storage.conformance(resolved)
        protocol=protocol and all(api15_science.match(m,p) is not None for m,p in [('GET','/api/signals'),('POST','/api/phantom-analyses'),('GET','/api/phantom-analyses')])
    except Exception:protocol=False
    ble=False
    try:
        from app.devices.api import get_manager
        manager=get_manager();ble=bool(manager.transport.availability()[0])
    except Exception:pass
    def state(implemented,tested,available):return {'implementation_available':implemented,'automated_tested':tested,'available':available,'integration_pending':not available,'hardware_verified':False}
    return {'auth':state(True,True,healthy),'personal_measurements':state(True,True,healthy),
      'scientific_signals':state(True,True,healthy and protocol),'phantom':state(True,True,healthy and protocol),
      'ble':state(True,True,healthy and protocol and ble),
      'nasa':{'implementation_available':True,'automated_tested':False,'available':False,'integration_pending':True,'hardware_verified':False,'reason':'Remote NASA availability is not probed by health'}}
