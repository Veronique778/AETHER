"""Machine-readable errors of the AETHER 1.5 scientific backend (Backend №3).

`code` is the HTTP-facing code from API Contract 1.5 §1.9 (plus the amendments in
docs/SCIENTIFIC_API_AMENDMENTS_1_5.md §6). `category` is the scientific error class used for logging/statistics.
Messages never contain tokens, passwords, file system paths of other users or stack traces.

Backend №2 maps ScienceError → HTTP in app/routing15.py:  status = err.status, body = err.body().
`insufficient_data` is NOT an error: analyses return 201 with outcome = 'insufficient_data'.
"""
from __future__ import annotations


class ScienceError(Exception):
    status = 400
    code = 'bad_request'
    category = 'invalid_input'

    def __init__(self, message: str, *, code: str | None = None, field: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.field = field

    def body(self) -> dict:
        """Legacy flat body (BE3 01–03)."""
        out = {'detail': self.message, 'code': self.code, 'category': self.category}
        if self.field:
            out['field'] = self.field
        return out

    def envelope(self) -> dict:
        """Backend №2 error format (api_15.error_response): {"error": {"code", "detail", ...}} — the one AETHER 1.5 format."""
        err = {'code': self.code, 'detail': self.message, 'category': self.category}
        if self.field:
            err['field'] = self.field
        return {'error': err}


class InvalidInput(ScienceError):
    status, code, category = 422, 'validation_error', 'invalid_input'


class UnsupportedSignal(InvalidInput):
    status, code, category = 422, 'unknown_signal', 'unsupported_signal'


class InvalidUnits(InvalidInput):
    status, code, category = 422, 'unit_mismatch', 'invalid_units'


class ValueOutOfRange(InvalidInput):
    status, code, category = 422, 'value_out_of_range', 'invalid_input'


class TimestampWithoutOffset(InvalidInput):
    status, code, category = 422, 'timestamp_without_offset', 'invalid_input'


class Forbidden(ScienceError):
    """No access to an astronaut-scoped resource. 1.5.1 (03A): answered as 404 'not_found' with a generic message,
    exactly like Backend №2's access_control.profile, so that foreign ids cannot be enumerated (IDOR)."""
    status, code, category = 404, 'not_found', 'access_denied'
    PUBLIC_MESSAGE = 'Resource not found'

    def __init__(self, message: str = 'Resource not found', **kw):
        super().__init__(message, **kw)
        self.internal_message = message
        self.message = self.PUBLIC_MESSAGE            # never echo the foreign id back to the caller


class RoleForbidden(ScienceError):
    """The caller's role may not perform the action at all (no object is revealed)."""
    status, code, category = 403, 'forbidden', 'access_denied'


class Unauthenticated(ScienceError):
    status, code, category = 401, 'unauthenticated', 'access_denied'


class NotFound(ScienceError):
    status, code, category = 404, 'not_found', 'invalid_input'


class DeviceUnavailable(ScienceError):
    status, code, category = 503, 'ble_unavailable', 'device_unavailable'


class DeviceBusy(ScienceError):
    status, code, category = 409, 'device_busy', 'device_busy'


class Conflict(ScienceError):
    status, code, category = 409, 'conflict', 'invalid_input'


class SensorDisconnected(ScienceError):
    status, code, category = 409, 'sensor_disconnected', 'sensor_disconnected'


class CorruptedData(InvalidInput):
    status, code, category = 422, 'corrupted_data', 'corrupted_data'


class StorageUnavailable(ScienceError):
    status, code, category = 503, 'storage_unavailable', 'storage_unavailable'


class AnalysisError(ScienceError):
    status, code, category = 500, 'analysis_error', 'analysis_error'


class ExternalServiceUnavailable(ScienceError):
    status, code, category = 503, 'external_service_unavailable', 'external_service_unavailable'
