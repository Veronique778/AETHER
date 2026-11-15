"""Authenticated Python contract for developer #3. Does not modify scientific algorithms.

Example:
  api = InternalAPI(personal_session_token)
  session = api.create_session({...})
  api.append_biosignals([{...}, {...}])
  api.save_analysis({...}, processed=[{...}])

Every call revalidates the session. Never persist the token in diagnostic logs.
This adapter makes no clinical inference and accepts no owner from a sensor.
"""
from app import auth
from . import repository as repo


class InternalAPI:
    def __init__(self,session_token): self._session_token=session_token
    def __repr__(self): return 'InternalAPI(<redacted>)'
    def _user(self): return auth.authenticate(self._session_token)
    def create_session(self,data): return repo.create_session(self._user(),data)
    def close_session(self,session_id): return repo.close_session(self._user(),session_id)
    def append_biosignals(self,measurements): return repo.add_measurements(self._user(),measurements)
    def save_analysis(self,data,processed=None): return repo.save_analysis(self._user(),data,processed)
    def create_alert(self,data): return repo.create_alert(self._user(),data)
