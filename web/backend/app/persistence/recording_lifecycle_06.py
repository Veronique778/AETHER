"""Bounded recording lifetime. No system token or HTTP-callable privileged context."""
import json
from app import db
from app.persistence.common import utcnow,audit,dumps
from app.devices.manager import DeviceManager
from app.science_errors import Unauthenticated


def recover_at_startup():
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        rows=c.execute("SELECT * FROM sensor_sessions WHERE ended_at IS NULL AND origin='real'").fetchall()
        for row in rows:
            old=c.execute('SELECT source_type FROM science_sessions WHERE session_id=?',(row['id'],)).fetchone()
            if json.loads(row['metadata']).get('source_type')!='live_sensor' and not (old and old['source_type']=='live_sensor'):continue
            c.execute('UPDATE sensor_sessions SET ended_at=? WHERE id=?',(utcnow(),row['id']))
            c.execute("INSERT INTO session_end_states VALUES(?,'recovered',?) ON CONFLICT(session_id) DO NOTHING",(row['id'],dumps({'reason':'process_restart'})))
            audit(c,None,'recover','sensor_session',row['id'])


class ManagedDeviceManager(DeviceManager):
    """Production manager: an ended personal session stops the recording AND closes its DB session as 'failed'.

    1.5 BLE: revocation is detected on flush (storage write) and by the periodic owner check in DeviceManager._tick
    (AUTH_CHECK_S), so a recording that receives no packets also stops. A normal logout never reaches this path: the
    logout route stops the recordings of that token at once (DeviceManager.stop_for_token): pending rows are flushed
    while the token is still valid, then the session is closed here as 'failed'."""
    REVOKE_ON_AUTH_END = True

    def flush(self,device_id):
        slot=self._slots.get(device_id)
        if slot is not None and slot.ctx is not None:
            try:slot.ctx.user
            except Unauthenticated:
                self._revoke(slot,slot.token)
                return 0
        return super().flush(device_id)

    def _revoke(self,slot,token):
        sid,aid,did,pending=slot.session_id,slot.astronaut_id,slot.device_id,len(slot.pending)
        super()._revoke(slot,token)
        if not slot.revoked or sid is None or slot.last_session_id!=sid:return
        slot.last_session_status='failed'
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM sensor_sessions WHERE id=? AND astronaut_id=? AND device_id=?',(sid,aid,did)).fetchone()
            if row and row['ended_at'] is None:
                c.execute('UPDATE sensor_sessions SET ended_at=? WHERE id=?',(utcnow(),row['id']))
                c.execute("INSERT INTO session_end_states VALUES(?,'failed',?) ON CONFLICT(session_id) DO NOTHING",(row['id'],dumps({'reason':'personal_session_expired_or_revoked','unstored_count':pending})))
                audit(c,None,'recording_auth_ended','sensor_session',row['id'])
        slot.error='Recording stopped: personal authentication ended; committed rows retained'
