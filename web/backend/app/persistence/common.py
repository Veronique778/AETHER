"""Shared primitives. Error messages never contain request bodies or credentials."""
import hashlib
import json
import uuid
from datetime import datetime, timezone


class APIError(Exception):
    def __init__(self, status, code, detail):
        self.status, self.code, self.detail = status, code, detail
        super().__init__(detail)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def utc(value):
    if not isinstance(value, str):
        raise ValueError('An ISO 8601 timestamp with timezone is required')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('A timezone is required')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def uid():
    return str(uuid.uuid4())


def dumps(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def audit(c, actor, action, resource_type, resource_id=None, outcome='ok'):
    # Deliberate whitelist: no arbitrary metadata, values, names, passwords or tokens.
    c.execute('INSERT INTO audit_logs(created_at,actor_id,action,resource_type,resource_id,outcome) VALUES(?,?,?,?,?,?)',
              (utcnow(), actor, action, resource_type, resource_id, outcome))
