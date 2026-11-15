"""Adapter interface. No BLE connection is claimed until a real driver exists."""
class SensorAdapter:
 def read(self):raise NotImplementedError('Implement a validated BLE/device adapter')
class SimulatorAdapter(SensorAdapter):
 def __init__(self,records):self.records=records
 def read(self):return list(self.records)
