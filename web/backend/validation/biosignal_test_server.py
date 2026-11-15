"""Development test server ONLY. Fake BLE transport never used by desktop runtime."""
import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.ble_sensor import Sensor,HRS
from app import bio_api
from app.devserver import serve
class FakeClient:
    def __init__(self,device,disconnected_callback):self.callback=disconnected_callback;self.is_connected=False
    async def connect(self):self.is_connected=True
    async def start_notify(self,char,notify):notify(None,bytes([22,60,0,4]))
    async def disconnect(self):self.is_connected=False;self.callback(self)
async def scan():return {'FAKE-TEST-ONLY':(SimpleNamespace(name='AUTOMATED TEST ONLY'),SimpleNamespace(service_uuids=[HRS]))}
a=argparse.ArgumentParser();a.add_argument('--port',type=int,required=True);a.add_argument('--static',required=True);args=a.parse_args()
bio_api.sensor=Sensor(FakeClient,scan)
serve(port=args.port,static=args.static).serve_forever()
