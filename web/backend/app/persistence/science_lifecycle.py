"""Single process Device Manager ownership; interrupted sessions are never resumed as live."""
import threading

from app.persistence import science_storage
_LOCK=threading.RLock()
_USERS=0
_MANAGER=None

def start():
    global _USERS,_MANAGER
    with _LOCK:
        if _USERS:
            # A second HTTP surface must reuse the lifecycle-owned manager.
            # Reassert the binding after a legacy consumer/test changed BE3's
            # public manager slot; never let get_manager() build a parallel one.
            from app.devices import api
            api.set_manager(_MANAGER)
            _USERS+=1;return
        try:
            from app.devices import api
            from .recording_lifecycle_06 import ManagedDeviceManager as DeviceManager, recover_at_startup
            from app.devices.runtime import BleakTransport
            from app.devices.simulated import SimulatedHrsTransport
            from app.science_storage import conformance
        except ImportError:return
        storage=science_storage()
        if conformance(storage):raise RuntimeError('Scientific storage protocol mismatch')
        recover_at_startup()
        # Physical radio transport (real_wearable) + the explicit, separately labelled SYNTHETIC test strap.
        manager=DeviceManager(storage,BleakTransport(),sim_transport=SimulatedHrsTransport())
        # BE3_03A performs owner-scoped crash recovery before connect.
        # No HTTP-reachable privileged context is passed to the manager.
        api.set_manager(manager);_MANAGER=manager;_USERS=1

def stop():
    global _USERS,_MANAGER
    with _LOCK:
        if not _USERS:return
        _USERS-=1
        if _USERS:return
        try:
            _MANAGER.shutdown()
        finally:
            from app.devices import api
            api.set_manager(None);_MANAGER=None
