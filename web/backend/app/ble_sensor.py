"""Bluetooth SIG HRS acquisition. Optional bleak; no simulation fallback.
Dedicated asyncio loop retains WinRT clients across desktop HTTP requests.

1.4: connection timeout, bounded automatic reconnection into the same session
after an unexpected link loss, and explicit gap markers (missing=1) so that a
dropout is stored as missing data, never as a normal reading.
"""
import asyncio
import importlib.util
import os
import struct
import threading
import time
from . import biosignals as bio

HRS='0000180d-0000-1000-8000-00805f9b34fb'
HRM='00002a37-0000-1000-8000-00805f9b34fb'

def decode(packet):
    b=bytes(packet)
    if len(b)<2: raise ValueError('Truncated heart-rate notification')
    flags=b[0]; offset=1
    def take(width):
        nonlocal offset
        if offset+width>len(b): raise ValueError('Truncated HRS field')
        v=int.from_bytes(b[offset:offset+width],'little'); offset+=width; return v
    hr=take(2 if flags&1 else 1)
    contact=bool(flags&2) if flags&4 else None
    energy=take(2) if flags&8 else None
    rr=[]
    if flags&16:
        if offset==len(b) or (len(b)-offset)%2: raise ValueError('Malformed RR intervals')
        while offset<len(b): rr.append(take(2)*1000/1024)
    elif offset!=len(b): raise ValueError('Unexpected HRS bytes')
    return {'heart_rate':hr,'rr_ms':rr,'contact':contact,'energy_kj':energy}

CONNECT_TIMEOUT=20.0
STALE_SECONDS=15

class Sensor:
    def __init__(self, client_factory=None, scanner=None, reconnect_delays=(1.0,2.0,4.0), connect_timeout=CONNECT_TIMEOUT):
        self.loop=asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever,daemon=True,name='aether-ble').start()
        self.client=None; self.devices={}; self.client_factory=client_factory; self.scanner=scanner
        self.reconnect_delays=tuple(reconnect_delays); self.connect_timeout=connect_timeout
        self.address=None; self.user_disconnect=False; self.reconnects=0; self.gaps=0
        self.lock=threading.RLock(); self.started=None; self.elapsed=0; self.token=0
        self.state={'connection':'disconnected','session_id':None,'last_sample_utc':None,
                    'heart_rate':None,'quality':'unavailable','error':None,'hardware_validation':'unverified',
                    'device_name':None,'rr_available':False,'received_samples':0,
                    'reconnect_attempt':0,'reconnects':0,'gaps':0,'corrupt_packets':0}
    def call(self,coro):
        return asyncio.run_coroutine_threadsafe(coro,self.loop).result(timeout=35)
    def status(self):
        with self.lock:
            state=dict(self.state)
            age = time.time()-self.last_received if state['last_sample_utc'] and hasattr(self,'last_received') else None
            if state['connection']=='connected' and age is not None and age>STALE_SECONDS:
                state.update(heart_rate=None,quality='stale')
            return {**state,'last_sample_age_seconds':round(age,1) if age is not None else None,
                    'duration_seconds':round(time.monotonic()-self.started) if self.started else self.elapsed,
                    'status':('Live HRS monitor connected — waiting for a valid pulse.' if state['connection']=='connected' and state['heart_rate'] is None
                              else 'Live HRS monitor connected — measurements received.' if state['connection']=='connected'
                              else f"Link lost — reconnecting (attempt {state['reconnect_attempt']}/{len(self.reconnect_delays)}); no values are filled in." if state['connection']=='reconnecting'
                              else 'Sensor disconnected — no live measurements.')}
    def diagnostics(self):
        return {'platform':'Windows' if os.name=='nt' else os.name, 'bleak_installed':importlib.util.find_spec('bleak') is not None,
                'profile':'Bluetooth SIG Heart Rate Service (0x180D / 0x2A37)',
                'modes':['advertised_HRS','all_named_nearby_with_service_check'],
                'limitations':'No universal smartwatch protocol. RR intervals are optional. No sleep, SpO2 or temperature over standard HRS.',
                'physical_hardware_validated':False}
    async def scan(self, include_unadvertised=False):
        """Default: only advertise HRS. Explicit broad mode exposes named devices
        which MUST have HRS+HRM verified after connecting; advertising is not proof.
        """
        try:
            if self.scanner: found=await self.scanner()
            else:
                from bleak import BleakScanner
                found=await BleakScanner.discover(timeout=7,return_adv=True)
            visible=[]
            for address,(dev,advertisement) in found.items():
                advertised = HRS in [str(u).lower() for u in (getattr(advertisement,'service_uuids',None) or [])]
                name = str(getattr(dev,'name',None) or getattr(advertisement,'local_name',None) or '').strip()
                if advertised or (include_unadvertised and name):
                    visible.append((address,dev,advertisement,advertised,name))
            visible.sort(key=lambda x:(not x[3],x[4].lower()))
            visible=visible[:80]  # limit response size and the size of the in-memory candidate list
            self.devices={addr:(dev,adv,advertised) for addr,dev,adv,advertised,_ in visible}
            if self.state['connection']=='unavailable':
                self.state.update(connection='disconnected',error=None)
            return [{'id':addr,'name':name or 'Unnamed HRS monitor',
                     'profile':'HRS advertised' if advertised else 'HRS unverified — connection required',
                     'advertised_hrs':advertised} for addr,_,_,advertised,name in visible]
        except ImportError:
            self.devices={}
            self.state.update(connection='unavailable',heart_rate=None,error='Bluetooth dependency missing. Run ENABLE_BLE.bat, then restart AETHER.'); return []
        except Exception as exc:
            self.devices={}
            self.state.update(connection='unavailable',heart_rate=None,error=f'Bluetooth scan failed; check radio and permissions: {exc}'); return []
    @staticmethod
    def has_heart_rate_service(services):
        if services is None: return False
        try:
            service=services.get_service(HRS)
            characteristic=services.get_characteristic(HRM)
            return service is not None and characteristic is not None
        except (AttributeError,KeyError,ValueError):
            return False
    async def connect(self,address):
        if address not in self.devices: raise ValueError('Scan and select a compatible advertised HRS monitor first')
        if self.state['connection'] in ('connected','connecting','reconnecting'): raise ValueError('Disconnect current sensor first')
        # 1.5.1 (03A): one physical device cannot be opened by the legacy path and the Device Manager at the same time
        from .devices import hw_lock
        try:
            hw_lock.acquire(address,'legacy')
        except Exception as exc:
            raise ValueError(getattr(exc,'message',str(exc))) from None
        self.token+=1; token=self.token; self.address=address; self.user_disconnect=False
        self.state.update(connection='connecting',error=None,heart_rate=None,last_sample_utc=None,
                          session_id=None,device_name=None,rr_available=False,received_samples=0,
                          reconnect_attempt=0,reconnects=0,gaps=0,corrupt_packets=0)
        sid=None
        try:
            factory=self.client_factory
            if factory is None:
                from bleak import BleakClient
                factory=BleakClient
            self.client=factory(self.devices[address][0],disconnected_callback=lambda _:self.disconnected(token))
            try:
                await asyncio.wait_for(self.client.connect(),timeout=self.connect_timeout)
            except asyncio.TimeoutError as exc:
                raise ValueError(f'Connection timed out after {self.connect_timeout:.0f}s') from exc
            if not self.client.is_connected: raise ValueError('Sensor did not establish connection')
            # Some HRS-capable watches omit the service from advertising. Do not
            # label a general nearby device as compatible without GATT verification.
            if not self.devices[address][2] and not self.has_heart_rate_service(getattr(self.client,'services',None)):
                raise ValueError('Device does not expose the standard HRS (0x180D / 0x2A37). Use a watch HR broadcast mode or a supported phone bridge.')
            sid=bio.create('local-sensor-participant','live_sensor','Bluetooth HRS',{'device_name':self.devices[address][0].name,'time_basis':'UTC host receipt; RR beat times reconstructed backwards from receipt','hardware_validation':'unverified','processing_version':bio.VERSION,'data_class':'real_wearable','reconnect_policy':f'{len(self.reconnect_delays)} attempts, delays {list(self.reconnect_delays)} s; gaps stored as missing rows'})
            with self.lock:
                self.state.update(session_id=sid,connection='connected',quality='awaiting_measurements',
                                  device_name=self.devices[address][0].name)
                self.started=time.monotonic(); self.last_received=time.time()
            await self.client.start_notify(HRM,lambda _,data:self.notification(data,token))
            return self.status()
        except Exception as exc:
            if self.client:
                try: await self.client.disconnect()
                except Exception: pass
            if sid: bio.finish(sid,'connection_failed')
            from .devices import hw_lock; hw_lock.release(address,'legacy')
            self.state.update(connection='disconnected',heart_rate=None,quality='unavailable',session_id=None,
                              error=f'Cannot subscribe to HRS; check device compatibility and permissions: {exc}')
            return self.status()
    def notification(self,data,token):
        with self.lock:
            if token!=self.token or self.state['connection']!='connected': return
            try:
                p=decode(data); timestamp=bio.now(); t=time.time(); self.last_received=t
                quality='no_contact' if p['contact'] is False else ('rejected' if not 30<=p['heart_rate']<=220 else 'screened')
                rows=[bio.measurement(t,'heart_rate',p['heart_rate'],'bpm',timestamp,timestamp,quality,{'profile':'HRS','contact':p['contact'],'clock':'host_receipt'},'connected')]
                beat_t=t
                rr_rows=[]
                for rr in reversed(p['rr_ms']):
                    q=quality if 300<=rr<=2000 else 'rejected'
                    rr_rows.append(bio.measurement(beat_t,'rr_interval',rr,'ms',timestamp,timestamp,q,{'profile':'HRS','clock':'receipt-relative beat estimate','conversion':'1000/1024 ms'},'connected'))
                    beat_t-=rr/1000
                rows.extend(reversed(rr_rows)); bio.append(self.state['session_id'],rows)
                self.state.update(last_sample_utc=timestamp,heart_rate=p['heart_rate'] if quality=='screened' else None,
                                  quality=quality,error=None,rr_available=self.state['rr_available'] or bool(p['rr_ms']),
                                  received_samples=self.state['received_samples']+1)
            except Exception as exc:
                self.state.update(heart_rate=None,quality='corrupt',error=str(exc),corrupt_packets=self.state['corrupt_packets']+1)
    def _gap(self,sid,reason):
        """Explicit missing-data marker; analysis never bridges it."""
        if not sid: return
        ts=bio.now()
        try:
            bio.append(sid,[bio.measurement(time.time(),'heart_rate',None,'bpm',ts,ts,'connection_lost',
                                            {'profile':'HRS','event':reason,'clock':'host_receipt'},'disconnected')])
            self.gaps+=1; self.state['gaps']=self.state.get('gaps',0)+1
        except ValueError:
            pass
    def disconnected(self,token):
        """Link-loss callback (bleak) and explicit stop share this path."""
        with self.lock:
            if token!=self.token or self.state['connection'] not in ('connected','connecting'): return
            sid=self.state.get('session_id')
            if not self.user_disconnect and sid and self.reconnect_delays and self.address in self.devices:
                self.state.update(connection='reconnecting',heart_rate=None,quality='unavailable',reconnect_attempt=0,
                                  error='Bluetooth link lost; reconnecting automatically.')
                self._gap(sid,'link_lost')
                asyncio.run_coroutine_threadsafe(self._reconnect(token,sid),self.loop)
                return
            self._finish(sid,'saved')
    def _finish(self,sid,status):
        if self.address:
            from .devices import hw_lock; hw_lock.release(self.address,'legacy')
        if self.started:
            self.elapsed=round(time.monotonic()-self.started); self.started=None
        self.state.update(connection='disconnected',heart_rate=None,quality='unavailable')
        if sid: bio.finish(sid,status)
    async def _reconnect(self,token,sid):
        for attempt,delay in enumerate(self.reconnect_delays,1):
            await asyncio.sleep(delay)
            with self.lock:
                if token!=self.token or self.user_disconnect or self.state['connection']!='reconnecting': return
                self.state['reconnect_attempt']=attempt
            try:
                factory=self.client_factory
                if factory is None:
                    from bleak import BleakClient
                    factory=BleakClient
                client=factory(self.devices[self.address][0],disconnected_callback=lambda _:self.disconnected(token))
                await asyncio.wait_for(client.connect(),timeout=self.connect_timeout)
                if not client.is_connected: raise ValueError('not connected')
                with self.lock:
                    if token!=self.token or self.user_disconnect: 
                        await client.disconnect(); return
                    self.client=client; self.reconnects+=1
                    self.state.update(connection='connected',quality='awaiting_measurements',error=None,
                                      reconnects=self.state['reconnects']+1,reconnect_attempt=0)
                    self.last_received=time.time()
                await client.start_notify(HRM,lambda _,data:self.notification(data,token))
                return
            except Exception as exc:
                self.state['error']=f'Reconnect attempt {attempt} failed: {type(exc).__name__}'
        with self.lock:
            if token==self.token and self.state['connection']=='reconnecting':
                self._finish(sid,'saved_after_connection_loss')
                self.state['error']='Bluetooth link lost; reconnection failed. Recording saved up to the loss; the gap is stored as missing.'
    async def disconnect(self):
        self.user_disconnect=True
        with self.lock:
            sid=self.state.get('session_id')
            if self.state['connection'] in ('connected','connecting','reconnecting'):
                self._finish(sid,'saved')
        if self.client:
            try: await self.client.disconnect()
            except Exception as exc: self.state['error']=str(exc)
        return self.status()

sensor=Sensor()
