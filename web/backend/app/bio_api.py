"""Shared endpoint dispatcher used by both supported HTTP servers."""
import re
from . import biosignals as bio
from . import mmash
from .ble_sensor import sensor

def dispatch(method,path,body=None,query=None):
    b=body or {}; q=query or {}; parts=path.strip('/').split('/')
    if path=='/api/biosignals/sessions' and method=='GET': return bio.sessions()
    if path=='/api/biosignals/mmash/inspect' and method=='POST': return mmash.inspect(b.get('path',''))
    if path=='/api/biosignals/mmash/import' and method=='POST': return mmash.import_mmash(b.get('path',''),b.get('participant',''),b.get('confirmed',False))
    if path=='/api/biosignals/sensor/status' and method=='GET': return sensor.status()
    if path=='/api/biosignals/sensor/diagnostics' and method=='GET': return sensor.diagnostics()
    if path=='/api/biosignals/sensor/scan' and method=='POST': return sensor.call(sensor.scan(include_unadvertised=b.get('include_unadvertised') is True))
    if path=='/api/biosignals/sensor/connect' and method=='POST': return sensor.call(sensor.connect(b.get('device_id','')))
    if path=='/api/biosignals/sensor/disconnect' and method=='POST': return sensor.call(sensor.disconnect())
    if path=='/api/biosignals/demo/recording' and method=='POST': return bio.demo_recording(b.get('confirm_simulated') is True,b.get('minutes',90))
    if len(parts)>=4 and parts[:3]==['api','biosignals','sessions']:
        sid=parts[3]
        if not re.fullmatch(r'[0-9a-f]{32}',sid): raise ValueError('Invalid session id')
        if len(parts)==4:
            if method=='GET': return bio.session(sid)
            if method=='DELETE': return bio.delete(sid)
        if len(parts)==5:
            if parts[4]=='points' and method=='GET': return bio.points(sid,q.get('signal',['heart_rate'])[0])
            if parts[4]=='analysis' and method in ('GET','POST'): return bio.analyze(sid)
            if parts[4]=='csv' and method=='GET':
                raw=q.get('offset',['0'])[0]
                if not str(raw).isdigit(): raise ValueError('offset must be a non-negative integer')
                return bio.csv_page(sid,int(raw))
    raise ValueError('Unknown biosignal endpoint')
